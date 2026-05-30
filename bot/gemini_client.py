"""
gemini_client.py — Wraps Gemini API calls for the resume tailoring bot.

Uses the newer google-genai SDK (v1.5+) which supports Python 3.14.
"""

import os
import re
import json
import logging
import json_repair
import asyncio
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from tenacity import AsyncRetrying, wait_random_exponential, stop_after_attempt, retry_if_exception_type
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError
from models import ResumeEvaluation, ResumeRevisions, Phase1Research, Phase2FinalGuide
from prompts import build_evaluator_prompt, build_generator_prompt
import analytics_logger

logger = logging.getLogger(__name__)

# ─── Skill file paths ─────────────────────────────────────────────────────────
_BOT_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.join(_BOT_DIR, '..')

# Try the plugin location first (local dev), then repo root (Render)
SKILL_FILE = os.path.join(
    os.path.expandvars(r'%USERPROFILE%'),
    '.gemini', 'config', 'plugins', 'my-custom-skills',
    'skills', 'tailor_resume_skill.md'
)
MASTER_PROFILE_FILE = os.path.join(_REPO_ROOT, 'master_profile.json')

# Fallback: bundled copies in repo root (for Render)
_ALT_SKILL = os.path.join(_REPO_ROOT, 'tailor_resume_skill.md')

GUIDE_SKILL_FILE = os.path.join(
    os.path.expandvars(r'%USERPROFILE%'),
    '.gemini', 'config', 'plugins', 'my-custom-skills',
    'skills', 'generate_guide_skill.md'
)
_ALT_GUIDE_SKILL = os.path.join(_REPO_ROOT, 'generate_guide_skill.md')


def _read_file(primary, fallback=''):
    for p in [primary, fallback]:
        if p and os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return f.read()
    return ''


def _load_base_resume(role_hint: str, base_dir: str):
    """Pick fullstack or backend resume based on role hint."""
    fullstack = os.path.join(base_dir, 'PurveshGandhi_Base_Resume_1_Fullstack.html')
    backend = os.path.join(base_dir, 'PurveshGandhi_Base_Resume_2_Backend.html')

    backend_kw = ['backend', 'back-end', 'back end', 'api', 'microservice',
                  'distributed', 'golang', 'rust', 'java developer', 'python developer']
    use_backend = any(kw in role_hint.lower() for kw in backend_kw)

    chosen = backend if use_backend else fullstack
    if not os.path.exists(chosen):
        chosen = fullstack  # fallback

    if os.path.exists(chosen):
        with open(chosen, 'r', encoding='utf-8') as f:
            return f.read(), os.path.basename(chosen)
    return '', 'unknown'

def _truncate_jd_boilerplate(jd: str) -> str:
    """Removes standard Indian market boilerplate and EEO statements to save context window."""
    boilerplate_markers = [
        "Equal Opportunity Employer",
        "is an equal opportunity employer",
        "does not charge any fee at any stage",
        "fraudulent job offers",
        "Rights of Persons with Disabilities",
        "caste, religion, gender, sexual orientation"
    ]
    jd_lower = jd.lower()
    earliest_idx = len(jd)
    start_search_idx = len(jd) // 2
    for marker in boilerplate_markers:
        idx = jd_lower.find(marker.lower(), start_search_idx)
        if idx != -1 and idx < earliest_idx:
            earliest_idx = idx
    if earliest_idx < len(jd):
        return jd[:earliest_idx].strip()
    return jd


class GeminiClient:
    def __init__(self, session_id=None):
        self.session_id = session_id
        api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            raise RuntimeError('GEMINI_API_KEY environment variable not set.')
        # Set a 10-minute timeout so long resume generations never get cut off
        self.client = genai.Client(
            api_key=api_key,
            http_options={'timeout': 600000},  # 600,000 milliseconds = 10 minutes
        )

    def _calculate_cost(self, model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate cost based on 2026 pricing."""
        if 'pro' in model_name.lower():
            # $1.25 / 1M input, $5.00 / 1M output
            return (prompt_tokens / 1_000_000 * 1.25) + (completion_tokens / 1_000_000 * 5.00)
        else:
            # $0.075 / 1M input, $0.30 / 1M output
            return (prompt_tokens / 1_000_000 * 0.075) + (completion_tokens / 1_000_000 * 0.30)



    async def start_chat_session(self, jd: str, base_resumes_dir: str, priority: str = 'normal', generate_cover_letter: bool = False, status_callback=None) -> dict:
        """
        Starts a chat session with the JD as the first message.
        Returns dict containing the chat object, first response text, and base resume name.
        """
        boundary = _read_file(MASTER_PROFILE_FILE)
        skill_instructions = _read_file(SKILL_FILE, _ALT_SKILL)
        base_html, base_name = _load_base_resume(jd, base_resumes_dir)

        if not base_html:
            raise RuntimeError('Could not load any base resume HTML file.')

        # Strip terminal commands from the prompt so Gemini doesn't hallucinate function calls
        sanitized_skill = re.sub(r'### Step 5: PDF Generation.*?### Step 6:', '### Step 6:', skill_instructions, flags=re.DOTALL)
        sanitized_skill = re.sub(r'### Step 7: Google Drive Upload.*', '', sanitized_skill, flags=re.DOTALL)

        system_prompt = f"""{sanitized_skill}

---

## OVERRIDE FOR API EXECUTION
You are running as a headless text-generation API inside a Python wrapper.
DO NOT output any function calls. DO NOT attempt to run any terminal commands or upload anything to Google Drive.
DO NOT generate the Company Guide or the Summary (these are handled by a separate background research agent).
Your ONLY job is to expertly rewrite the HTML and output the final exact text blocks (COMPANY_NAME, TAILORED_HTML) exactly as requested below.

---

## MASTER PROFILE (CORE SKILLS & EXPERIENCE)
{boundary}

---

## CANDIDATE'S BASE RESUME (HTML)
You must modify this HTML for the tailored output. Do NOT edit the base file.
```html
{base_html}
```

---

## OUTPUT FORMAT
If you need clarification about adding a high-signal skill, ASK THE USER FIRST.
Do not generate the resume until your questions are answered.
When you are ready to generate the final resume, respond with EXACTLY this structure — no extra prose before or after:

===COMPANY_NAME===
<CompanyName with no spaces, e.g. AlignTechnology>

===TAILORED_HTML===
<full tailored HTML content>
"""
        if generate_cover_letter:
            system_prompt += "\n\n===COVER_LETTER===\n<full cover letter following specifications>"

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            max_output_tokens=65536,
            # No tools: prevents the model from hallucinating HTML or getting distracted by search results.
        )

        chat = None
        
        # Determine primary model based on priority
        model_name = 'gemini-3.1-pro-preview' if priority == 'high' else 'gemini-3.5-flash'
        logger.info(f'Starting Gemini chat session ({model_name})...')
        chat = self.client.aio.chats.create(model=model_name, config=config)

        res_data = await self.send_message_with_retry(chat, f"Here is the Job Description:\n\n{jd}", status_callback)
        
        # Log audit details
        if res_data['error']:
            if self.session_id:
                await analytics_logger.log_llm_request(self.session_id, 'start_chat_session', chat._model, 0, 0, 0.0, error=res_data['error'])
        else:
            cost = self._calculate_cost(chat._model, res_data['prompt_tokens'], res_data['completion_tokens'])
            if self.session_id:
                await analytics_logger.log_llm_request(self.session_id, 'start_chat_session', chat._model, res_data['prompt_tokens'], res_data['completion_tokens'], cost)
            res_data['cost'] = cost
            res_data['model_used'] = chat._model

        return {
            'chat': chat,
            'response_text': res_data['text'],
            'base_resume_used': base_name,
            'usage': res_data
        }

    async def generate_company_guide(self, jd: str, priority: str = 'normal') -> dict:
        """Phase 1: Background research (Sections 1-4, 6). Runs in parallel with resume tailoring."""
        jd = _truncate_jd_boilerplate(jd)
        skill_instructions = _read_file(GUIDE_SKILL_FILE, _ALT_GUIDE_SKILL)
        system_prompt = skill_instructions

        contents = f"""## API EXECUTION INSTRUCTIONS — PHASE 1: RESEARCH
You are running as a headless background research API. Execute Phase 1 only.
Output strict JSON matching the schema.

Job Description:
{jd}
"""

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            max_output_tokens=32768,
            tools=[{'google_search': {}}],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode='NONE')
            ),
            response_mime_type="application/json",
            response_schema=Phase1Research,
        )

        model_name = 'gemini-3.5-flash'
        logger.info(f"Starting background Guide Research — Phase 1 ({model_name})...")

        retryer = AsyncRetrying(
            wait=wait_random_exponential(multiplier=2, max=30),
            stop=stop_after_attempt(5),
            retry=retry_if_exception_type((APIError, ClientError)),
            reraise=True
        )

        response = None
        async for attempt in retryer:
            with attempt:
                if attempt.retry_state.attempt_number == 5:
                    logger.info("Guide Phase 1: Switching to fallback model gemini-3.1-pro...")
                    model_name = 'gemini-3.1-pro-preview'
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=f"Job Description:\n\n{jd}",
                    config=config
                )

        response_text = response.text if response else ""

        grounding_sources = []
        if response and getattr(response, 'candidates', None) and len(response.candidates) > 0:
            candidate = response.candidates[0]
            if getattr(candidate, 'grounding_metadata', None) and getattr(candidate.grounding_metadata, 'grounding_chunks', None):
                for chunk in candidate.grounding_metadata.grounding_chunks:
                    if getattr(chunk, 'web', None):
                        title = getattr(chunk.web, 'title', 'Source')
                        uri = getattr(chunk.web, 'uri', '')
                        if uri:
                            grounding_sources.append({'title': title, 'uri': uri})

        company_type = 'product_startup'
        research_md = ''
        if response_text:
            try:
                data = json.loads(response_text)
                research_obj = Phase1Research(**data)
                research_md = research_obj.research_markdown
                company_type = research_obj.company_type.lower()
                if 'services' in company_type or 'agency' in company_type:
                    company_type = 'it_services'
                elif 'gcc' in company_type or 'capability' in company_type or 'captive' in company_type or 'global tech' in company_type or 'gbs' in company_type:
                    company_type = 'gcc'
            except Exception as e:
                logger.error(f"Failed to parse Phase 1 JSON: {e}")
                research_md = response_text

        prompt_tokens = 0
        completion_tokens = 0
        if response and getattr(response, 'usage_metadata', None):
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)

        cost = self._calculate_cost(model_name, prompt_tokens, completion_tokens)
        if self.session_id:
            await analytics_logger.log_llm_request(self.session_id, 'generate_guide_phase1', model_name, prompt_tokens, completion_tokens, cost)

        return {
            'research_md': research_md,
            'company_type': company_type,
            'grounding_sources': grounding_sources,
            'usage': {
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'cost': cost,
                'model_used': model_name
            }
        }

    async def finalize_guide(self, jd: str, research_md: str, tailored_html: str, priority: str = 'normal') -> dict:
        """Phase 2: Generates Sections 5 & 7 using tailored resume, assembles full guide."""
        jd = _truncate_jd_boilerplate(jd)
        stripped_html = re.sub(r'<[^>]+>', ' ', tailored_html)
        
        skill_instructions = _read_file(GUIDE_SKILL_FILE, _ALT_GUIDE_SKILL)
        system_prompt = skill_instructions

        contents = f"""## API EXECUTION INSTRUCTIONS — PHASE 2: FINALIZATION
Phase 1 research is complete. Use the tailored resume text to generate Section 5 and Section 7, then assemble the complete guide.
Output strict JSON matching the schema.

Job Description:
{jd}

---
Phase 1 Research (Sections 1, 2, 3, 4, 6):
{research_md}

---
Tailored Resume (Stripped of HTML):
{stripped_html}
"""
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            max_output_tokens=32768,
            response_mime_type="application/json",
            response_schema=Phase2FinalGuide,
        )

        model_name = 'gemini-3.1-pro-preview' if priority == 'high' else 'gemini-3.5-flash'
        logger.info(f"Starting Guide Finalization — Phase 2 ({model_name})...")

        retryer = AsyncRetrying(
            wait=wait_random_exponential(multiplier=2, max=30),
            stop=stop_after_attempt(5),
            retry=retry_if_exception_type((APIError, ClientError)),
            reraise=True
        )

        response = None
        async for attempt in retryer:
            with attempt:
                if attempt.retry_state.attempt_number == 5:
                    logger.info("Guide Phase 2: Switching to fallback model gemini-3.1-pro...")
                    model_name = 'gemini-3.1-pro-preview'
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )

        response_text = response.text if response else ""

        guide_md = ''
        summary = ''
        if response_text:
            try:
                data = json.loads(response_text)
                final_obj = Phase2FinalGuide(**data)
                guide_md = final_obj.guide_markdown
                summary = final_obj.summary
            except Exception as e:
                logger.error(f"Failed to parse Phase 2 JSON: {e}")
                if "## " in response_text:
                    guide_md = response_text.strip()

        prompt_tokens = 0
        completion_tokens = 0
        if response and getattr(response, 'usage_metadata', None):
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)

        cost = self._calculate_cost(model_name, prompt_tokens, completion_tokens)
        if self.session_id:
            await analytics_logger.log_llm_request(self.session_id, 'generate_guide_phase2', model_name, prompt_tokens, completion_tokens, cost)

        return {
            'guide_md': guide_md,
            'summary': summary,
            'usage': {
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'cost': cost,
                'model_used': model_name
            }
        }

    async def generate_cover_letter(self, jd: str, company_name: str, tailored_html: str) -> dict:
        """Generates a cover letter asynchronously using the cheaper Flash model."""
        system_prompt = f"Act as an expert career coach. Write a tailored, one-page cover letter for {company_name}."
        contents = f"## Job Description\n{jd}\n\n## Tailored Resume Data\n{tailored_html}\n\nWrite a compelling cover letter based on the above information. Do not include any HTML formatting, just plain text."
        
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            max_output_tokens=65536,
        )
        
        # Hardcoding to Flash for cost efficiency as requested
        model_name = 'gemini-3.5-flash'
        logger.info(f"Starting Cover Letter Generation ({model_name})...")
        
        retryer = AsyncRetrying(
            wait=wait_random_exponential(multiplier=2, max=10),
            stop=stop_after_attempt(3),
            retry=retry_if_exception_type((APIError, ClientError)),
            reraise=True
        )
        
        response = None
        async for attempt in retryer:
            with attempt:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                
        response_text = response.text if response else ""
        
        prompt_tokens = 0
        completion_tokens = 0
        if response and getattr(response, 'usage_metadata', None):
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)
            
        cost = self._calculate_cost(model_name, prompt_tokens, completion_tokens)
        if self.session_id:
            await analytics_logger.log_llm_request(self.session_id, 'generate_cover_letter', model_name, prompt_tokens, completion_tokens, cost)
            
        return {
            'cover_letter': response_text,
            'usage': {
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'cost': cost,
                'model_used': model_name
            }
        }

    async def revise_resume(self, current_html: str, company_name: str, jd: str, feedback: str, priority: str = 'normal') -> dict:
        """
        Lean stateless revision call. Uses only the current tailored HTML + feedback
        instead of re-sending the full skill file, base resume, and chat history.
        Dramatically cheaper than continuing the original chat session.
        Returns targeted JSON edits to save on output tokens.
        """


        revision_system_prompt = f"""You are an expert resume editor. You will receive a fully tailored HTML resume and a specific revision request. Apply the changes precisely by returning a list of targeted text replacements.

## EDITING RULES (strictly enforced)
- Address the feedback AND NOTHING ELSE. Do not rewrite the entire file.
- Provide the exact contiguous text block in the current HTML to be replaced. Ensure the `search_string` is unique and exactly matches the existing HTML including whitespace.
- Provide the `replacement_string` with the new text/HTML.
- Do NOT use Markdown formatting inside HTML. Use only proper HTML tags: <strong>, <em>, <b>.
- Do NOT alter the CSS, layout, margins, or fonts. Only edit text content and bullet points.
- Every bullet must describe a consequence — what got faster, more reliable, or more scalable — not just a task.
- Every bullet must contain at least one of: a specific technology name, a metric, an architectural pattern, or a problem name.
- Start each bullet with a strong action verb: Engineered, Architected, Optimized, Eliminated, Automated, Refactored, Decoupled, Instrumented, Migrated, Hardened, Scaled.
- Do NOT fabricate new metrics. Reuse or reframe existing quantifiable metrics only.
- The resume must remain within one page — do not add so many bullets that it overflows.

## JD CONTEXT (for keyword alignment during edits)
{jd}
"""

        user_message = (
            f"Current tailored HTML resume:\n```html\n{current_html}\n```\n\n"
            f"Revision request: {feedback}"
        )

        config = types.GenerateContentConfig(
            system_instruction=revision_system_prompt,
            temperature=0.2, # Lower temp for more precise replacements
            max_output_tokens=65536,
            response_mime_type="application/json",
            response_schema=ResumeRevisions,
        )

        model_name = 'gemini-3.1-pro-preview' if priority == 'high' else 'gemini-3.5-flash'
        logger.info(f'Starting stateless revision with targeted edits ({model_name})...')

        retryer = AsyncRetrying(
            wait=wait_random_exponential(multiplier=2, max=30),
            stop=stop_after_attempt(5),
            retry=retry_if_exception_type((APIError, ClientError)),
            reraise=True
        )

        response = None
        async for attempt in retryer:
            with attempt:
                if attempt.retry_state.attempt_number == 5:
                    logger.info("Revision: Switching to fallback model gemini-3.1-pro...")
                    model_name = 'gemini-3.1-pro-preview'
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=user_message,
                    config=config
                )

        response_text = response.text if response else None

        prompt_tokens = 0
        completion_tokens = 0
        if response and getattr(response, 'usage_metadata', None):
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)

        error_msg = None
        new_html = current_html
        
        if response_text is None:
            error_msg = "Gemini returned an empty or blocked response."
            fake_raw_response = "⚠️ Gemini returned an empty or blocked response."
        else:
            try:
                data = json.loads(response_text)
                revisions = ResumeRevisions(**data)
                
                # Apply patches iteratively
                for edit in revisions.edits:
                    if edit.search_string in new_html:
                        new_html = new_html.replace(edit.search_string, edit.replacement_string, 1)
                    else:
                        logger.warning(f"Revision edit missed: Could not find exact string:\\n{edit.search_string}")
                
                # Construct fake raw response for bot.py compatibility
                fake_raw_response = f"===COMPANY_NAME===\n{company_name}\n\n===TAILORED_HTML===\n{new_html}"
            except Exception as e:
                logger.error(f"Failed to parse or apply targeted edits: {e}")
                error_msg = f"Failed to parse or apply targeted edits: {e}"
                fake_raw_response = f"⚠️ Gemini returned invalid JSON or edits could not be applied: {e}"

        cost = self._calculate_cost(model_name, prompt_tokens, completion_tokens)
        if self.session_id:
            await analytics_logger.log_llm_request(self.session_id, 'revise_resume', model_name, prompt_tokens, completion_tokens, cost, error=error_msg)

        return {
            'text': fake_raw_response,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'cost': cost,
            'model_used': model_name,
            'error': error_msg,
        }

    async def refine_resume(self, jd: str, company_type: str, master_profile_json: str, template_html: str, research_md: str, current_html: str = None, feedback: str = None, priority: str = 'normal') -> dict:
        """Phase 3: Stateless generator that creates or refines a resume draft."""
        system_prompt, contents = build_generator_prompt(company_type, master_profile_json, template_html, jd, research_md, current_html, feedback)

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            max_output_tokens=65536,
        )

        model_name = 'gemini-3.1-pro-preview'
        logger.info(f"Starting Generator Agent ({model_name}) for company_type: {company_type}...")

        retryer = AsyncRetrying(
            wait=wait_random_exponential(multiplier=2, max=30),
            stop=stop_after_attempt(5),
            retry=retry_if_exception_type((APIError, ClientError)),
            reraise=True
        )

        response = None
        async for attempt in retryer:
            with attempt:
                if attempt.retry_state.attempt_number == 5:
                    logger.info("Generator: Switching to fallback model gemini-3.1-pro...")
                    model_name = 'gemini-3.1-pro-preview'
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )

        response_text = response.text if response else None

        prompt_tokens = 0
        completion_tokens = 0
        if response and getattr(response, 'usage_metadata', None):
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)

        error_msg = None
        if response_text is None:
            error_msg = "Gemini returned an empty or blocked response."
            response_text = "⚠️ Gemini returned an empty or blocked response."

        cost = self._calculate_cost(model_name, prompt_tokens, completion_tokens)
        if self.session_id:
            await analytics_logger.log_llm_request(self.session_id, 'tailor_generator', model_name, prompt_tokens, completion_tokens, cost, error=error_msg)

        return {
            'text': response_text,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'cost': cost,
            'model_used': model_name,
            'error': error_msg,
        }

    async def send_message_with_retry(self, chat, text: str, status_callback=None) -> dict:
        """Sends a message with exponential backoff, jitter, and fallback model switching."""
        response = None
        
        retryer = AsyncRetrying(
            wait=wait_random_exponential(multiplier=2, max=30),
            stop=stop_after_attempt(5),
            retry=retry_if_exception_type((APIError, ClientError)),
            reraise=True
        )

        async for attempt in retryer:
            with attempt:
                attempt_number = attempt.retry_state.attempt_number
                
                # If we fail 4 times, switch the chat model for the fallback
                if attempt_number == 5:
                    logger.info("Switching to fallback model gemini-3.1-pro...")
                    chat._model = 'gemini-3.1-pro-preview'
                    
                if attempt_number > 1 and status_callback:
                    msg = f"⏳ *Model busy* \\(Attempt {attempt_number}/5\\)\\. Retrying\\.\\.\\."
                    try:
                        await status_callback(msg)
                    except Exception as e:
                        logger.error(f"Callback failed: {e}")

                response = await chat.send_message(text)

        response_text = response.text if response else None
        
        grounding_sources = []
        if response and getattr(response, 'candidates', None) and len(response.candidates) > 0:
            candidate = response.candidates[0]
            if getattr(candidate, 'grounding_metadata', None) and getattr(candidate.grounding_metadata, 'grounding_chunks', None):
                for chunk in candidate.grounding_metadata.grounding_chunks:
                    if getattr(chunk, 'web', None):
                        title = getattr(chunk.web, 'title', 'Source')
                        uri = getattr(chunk.web, 'uri', '')
                        if uri:
                            grounding_sources.append({'title': title, 'uri': uri})

        prompt_tokens = 0
        completion_tokens = 0
        if response and getattr(response, 'usage_metadata', None):
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)

        error_msg = None
        if response_text is None:
            logger.error(f"Gemini returned an empty/blocked response: {response}")
            error_msg = "Gemini returned an empty or blocked response."
            response_text = "⚠️ Gemini returned an empty or blocked response (likely triggered safety filters). Please check the JD and try again."
            
        return {
            'text': response_text,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'cost': self._calculate_cost(chat._model, prompt_tokens, completion_tokens),
            'model_used': chat._model,
            'error': error_msg,
            'grounding_sources': grounding_sources
        }

    def is_final_output(self, raw: str) -> bool:
        """Check if the response contains the final structured markers."""
        if not raw: return False
        return "===COMPANY_NAME===" in raw and "===TAILORED_HTML===" in raw

    def parse_final_response(self, raw: str) -> dict:
        def extract(tag):
            pattern = rf'==={tag}===\s*(.*?)(?====\w+===|$)'
            m = re.search(pattern, raw, re.DOTALL)
            return m.group(1).strip() if m else ''

        company = extract('COMPANY_NAME')
        html = extract('TAILORED_HTML')
        guide = extract('GUIDE')
        summary = extract('SUMMARY')
        cover_letter = extract('COVER_LETTER')

        # Strip code fences if Gemini wrapped HTML in ```html ... ```
        html = re.sub(r'^```html\s*', '', html, flags=re.MULTILINE)
        html = re.sub(r'^```\s*$', '', html, flags=re.MULTILINE)

        if not company:
            company = 'UnknownCompany'
        if not html:
            raise ValueError('Gemini did not return tailored HTML.\nRaw: ' + raw[:500])

        # Build display name by inserting spaces before caps (e.g. AlignTechnology → Align Technology)
        display = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', company)

        return {
            'company_name': re.sub(r'[^\w]', '', company),
            'company_name_display': display,
            'tailored_html': html,
            'guide_md': guide,
            'cover_letter': cover_letter,
            'summary': summary,
        }

    async def evaluate_resume(self, current_html: str, master_profile_json: str, jd: str, company_type: str, research_md: str, priority: str = 'normal') -> tuple[ResumeEvaluation, dict]:
        """Phase 2: Evaluates a given tailored resume draft against the master profile and JD."""
        
        stripped_html = re.sub(r'<[^>]+>', ' ', current_html)
        system_prompt, contents = build_evaluator_prompt(company_type, master_profile_json, jd, stripped_html, research_md)

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2, # Low temperature for more consistent evaluation
            max_output_tokens=65536,
            response_mime_type="application/json",
            response_schema=ResumeEvaluation,
        )

        model_name = 'gemini-3.5-flash'
        logger.info(f"Starting Evaluator Agent ({model_name}) for company_type: {company_type}...")

        retryer = AsyncRetrying(
            wait=wait_random_exponential(multiplier=2, max=30),
            stop=stop_after_attempt(5),
            retry=retry_if_exception_type((APIError, ClientError, ValueError)),
            reraise=True
        )

        response = None
        parsed_evaluation = None
        
        async for attempt in retryer:
            with attempt:
                if attempt.retry_state.attempt_number == 5:
                    logger.info("Evaluator: Switching to fallback model gemini-3.1-pro...")
                    model_name = 'gemini-3.1-pro-preview'
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                
                if not response or not response.text:
                    raise ValueError("Evaluator returned an empty response.")
                    
                try:
                    text = response.text.strip()
                    if text.startswith('```json'):
                        text = text[7:]
                    if text.endswith('```'):
                        text = text[:-3]
                    text = text.strip()
                    
                    data = json_repair.loads(text)
                    if isinstance(data, str):
                        data = json.loads(data)
                    parsed_evaluation = ResumeEvaluation(**data)

                except Exception as e:
                    finish_reason = "UNKNOWN"
                    if response and getattr(response, 'candidates', None) and len(response.candidates) > 0:
                        finish_reason = str(response.candidates[0].finish_reason)
                        
                    logger.error(f"JSON Decode Error in Evaluator (Finish Reason: {finish_reason}). Raw response:\n{response.text}")
                    
                    # Log the failed LLM request so the user can inspect it in the database
                    prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) if response and getattr(response, 'usage_metadata', None) else 0
                    completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) if response and getattr(response, 'usage_metadata', None) else 0
                    cost = self._calculate_cost(model_name, prompt_tokens, completion_tokens)
                    
                    if getattr(self, 'session_id', None):
                        # Use asyncio.create_task to run this in the background since we're about to raise
                        import asyncio
                        asyncio.create_task(analytics_logger.log_llm_request(
                            self.session_id, 'critic_evaluator', model_name, 
                            prompt_tokens, completion_tokens, cost, error=f"FinishReason: {finish_reason} | Error: {e}"
                        ))
                        asyncio.create_task(analytics_logger.log_agent_trace(
                            self.session_id, 0, 'evaluator_failed', 
                            prompt_text="Evaluating current_html", 
                            raw_response=response.text if response else "", 
                            parsed_output=f"FinishReason: {finish_reason} | Error: {e}"
                        ))
                        
                    raise ValueError(f"Failed to parse JSON (Finish Reason: {finish_reason}): {e}")

        if not parsed_evaluation:
            raise RuntimeError("Evaluator failed to generate a valid evaluation.")

        prompt_tokens = 0
        completion_tokens = 0
        if response and getattr(response, 'usage_metadata', None):
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)

        cost = self._calculate_cost(model_name, prompt_tokens, completion_tokens)
        if getattr(self, 'session_id', None):
            await analytics_logger.log_llm_request(self.session_id, 'critic_evaluator', model_name, prompt_tokens, completion_tokens, cost)

        usage = {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'cost': cost,
            'model_used': model_name
        }

        return parsed_evaluation, usage
