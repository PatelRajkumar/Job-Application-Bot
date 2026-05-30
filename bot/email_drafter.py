"""
email_drafter.py — Gemini-powered cold email composer.

Uses the company guide (generated during /tailor) and the found email contacts
to draft a highly personalized, recruiter-optimized cold outreach email.

Design:
- Keeps emails to 75–120 words (recruiter attention span)
- Opens with a specific hook, not "I am reaching out"
- Subject line uses the clear "[Role] @ [Company] — Purvesh Gandhi" formula
- Supports revision loop: draft → user feedback → re-draft
"""

import os
import re
import logging
import asyncio

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


# ─── System prompt for cold email drafting ───────────────────────────────────
_DRAFT_SYSTEM_PROMPT = """You are an expert cold email writer specializing in tech job applications.
Your emails are known for being punchy, personalized, and highly effective.

## Rules — follow strictly
- Length: 75–120 words (body only, excluding subject line and signature)
- Open with a SPECIFIC hook about the company — never "I am reaching out" or "I hope this email finds you well"
- Hook examples: a specific product/feature they launched, a recent funding round, their tech stack, a culture value from the guide
- The ask must be LOW FRICTION: "Would you have 10–15 minutes to connect?" — never "I would like to apply for..."
- Do NOT use resume buzzwords: passionate, leverage, synergy, hardworking, motivated
- Use the candidate's real metrics from the resume — never invent new ones
- Tone: confident and direct, not desperate or sycophantic
- End with a real signature (no placeholder like "[Your Name]")

## Candidate Details
- Name: Purvesh Gandhi
- Role: Full-Stack / Backend Software Engineer
- Current status: Actively exploring new opportunities

## Output format
Respond with EXACTLY this structure — no extra prose:

===SUBJECT===
<subject line here>

===EMAIL===
<email body here — no greeting line, start directly with "Hi [FirstName],">

===HOOK_USED===
<1 sentence: what specific fact from the guide you used as the hook>
"""

_REVISE_SYSTEM_PROMPT = """You are revising a cold email based on user feedback.
Apply the feedback precisely. Maintain the same length (75–120 words), tone, and structure.
Keep the opening hook and low-friction ask unless the feedback specifically changes them.

Output format — respond with EXACTLY this structure:

===SUBJECT===
<revised subject line>

===EMAIL===
<revised email body>

===HOOK_USED===
<1 sentence: the hook used>
"""


def _build_draft_prompt(
    contact: dict,
    company_name: str,
    role: str,
    guide_md: str,
    drive_link: str = "",
) -> str:
    """Build the user-turn prompt for the initial cold email draft."""
    first_name = (contact.get("name") or "").split()[0] or "there"
    title = contact.get("title") or "Recruiter"

    prompt_parts = [
        f"Draft a cold email to {contact.get('name', 'the recruiter')} ({title}) at {company_name}.",
        f"The role I'm targeting: {role}",
        f"Recipient email: {contact['email']}",
        f"Recipient first name to use in greeting: {first_name}",
        "",
    ]

    if drive_link:
        prompt_parts.append(f"Resume Drive link to include: {drive_link}")
        prompt_parts.append("")

    if guide_md:
        # Trim guide to avoid overly long prompts — first 2000 chars is enough for hooks
        guide_snippet = guide_md[:2000].strip()
        prompt_parts.append("## Company Research Guide (use this for the hook):")
        prompt_parts.append(guide_snippet)

    return "\n".join(prompt_parts)


def _build_revise_prompt(
    original_email: str,
    original_subject: str,
    feedback: str,
) -> str:
    """Build the user-turn prompt for a revision request."""
    return (
        f"Original subject: {original_subject}\n\n"
        f"Original email:\n{original_email}\n\n"
        f"Revision feedback: {feedback}"
    )


def _parse_draft_response(raw: str) -> dict | None:
    """
    Parse the structured Gemini output into subject + email body + hook.
    Returns None if the expected markers are missing.
    """
    def extract(tag: str) -> str:
        pattern = rf"==={tag}===\s*(.*?)(?====\w+===|$)"
        m = re.search(pattern, raw, re.DOTALL)
        return m.group(1).strip() if m else ""

    subject = extract("SUBJECT")
    body = extract("EMAIL")
    hook = extract("HOOK_USED")

    if not (subject and body):
        return None

    return {"subject": subject, "body": body, "hook": hook}


# ─── Main async API ──────────────────────────────────────────────────────────
async def draft_cold_email(
    contact: dict,
    company_name: str,
    role: str,
    guide_md: str = "",
    drive_link: str = "",
) -> dict | None:
    """
    Draft a personalized cold email for the given contact.

    Args:
        contact:      Email result dict from email_finder.py
        company_name: Display name e.g. "Stripe"
        role:         Job title e.g. "Senior Software Engineer"
        guide_md:     Company guide markdown (from /tailor flow)
        drive_link:   Google Drive URL of the tailored resume PDF

    Returns:
        {"subject": ..., "body": ..., "hook": ...} or None on failure
    """
    if not GEMINI_API_KEY:
        logger.warning("email_drafter: GEMINI_API_KEY not set")
        return None

    def _sync_draft():
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        config = types.GenerateContentConfig(
            system_instruction=_DRAFT_SYSTEM_PROMPT,
            temperature=0.8,   # slightly creative for hook variety
            max_output_tokens=8192,
        )
        user_prompt = _build_draft_prompt(contact, company_name, role, guide_md, drive_link)
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=user_prompt,
            config=config,
        )
        return response.text or ""

    try:
        raw = await asyncio.to_thread(_sync_draft)
        result = _parse_draft_response(raw)
        if result:
            logger.info(f"email_drafter: draft ready for {contact.get('email')} — hook: {result['hook'][:80]}")
        else:
            logger.warning(f"email_drafter: could not parse Gemini response:\n{raw[:300]}")
        return result
    except Exception as e:
        logger.error(f"email_drafter: Gemini call failed: {e}")
        return None


async def revise_cold_email(
    original_subject: str,
    original_body: str,
    feedback: str,
) -> dict | None:
    """
    Revise an existing draft based on user feedback.

    Args:
        original_subject: The current subject line
        original_body:    The current email body
        feedback:         User's revision instruction

    Returns:
        {"subject": ..., "body": ..., "hook": ...} or None on failure
    """
    if not GEMINI_API_KEY:
        logger.warning("email_drafter: GEMINI_API_KEY not set")
        return None

    def _sync_revise():
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        config = types.GenerateContentConfig(
            system_instruction=_REVISE_SYSTEM_PROMPT,
            temperature=0.7,
            max_output_tokens=8192,
        )
        user_prompt = _build_revise_prompt(original_body, original_subject, feedback)
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=user_prompt,
            config=config,
        )
        return response.text or ""

    try:
        raw = await asyncio.to_thread(_sync_revise)
        result = _parse_draft_response(raw)
        if result:
            logger.info("email_drafter: revision complete")
        else:
            logger.warning(f"email_drafter: could not parse revision response:\n{raw[:300]}")
        return result
    except Exception as e:
        logger.error(f"email_drafter: revision Gemini call failed: {e}")
        return None


def format_draft_for_telegram(draft: dict) -> str:
    """
    Format the draft dict into a readable Telegram message (plain text).
    Caller should escape for MarkdownV2 if needed.
    """
    return (
        f"📧 Cold Email Draft\n\n"
        f"Subject: {draft['subject']}\n\n"
        f"{draft['body']}\n\n"
        f"💡 Hook used: {draft.get('hook', 'N/A')}"
    )
