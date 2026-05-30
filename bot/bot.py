"""
bot.py — Telegram bot for automated resume tailoring.

Commands:
  /start       — Welcome message
  /tailor      — Start resume tailoring flow (paste JD when prompted)
  /done        — Finish iteration and end the session
  /cancel      — Cancel current operation
  /status      — Health check
  /findemail   — Standalone email finder (LinkedIn URL or company name)
  /reviewemail — Review and send the drafted cold email
  /sendemail   — Send the cold email via Gmail
  /editemail   — Revise the cold email draft with feedback

Also exposes a /health HTTP endpoint to keep Render's free tier alive.
"""

import os
import re
import logging
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, constants, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest

from gemini_client import GeminiClient
from drive_client import upload_files_to_company_folder, format_upload_results
from email_finder import find_emails_async, format_email_results
from email_drafter import draft_cold_email, revise_cold_email, format_draft_for_telegram
from email_sender import send_cold_email_async, is_gmail_configured
import analytics_logger
import uuid

# ─── Setup ───────────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
ALLOWED_USER_ID = int(os.environ['ALLOWED_USER_ID'])

# Paths (relative to repo root)
REPO_ROOT = Path(__file__).parent.parent
BASE_RESUMES_DIR = REPO_ROOT / 'base_resumes'
GENERATED_DIR = REPO_ROOT / 'generated'
GENERATE_PDF_SCRIPT = REPO_ROOT / 'generate_pdf.js'

# Conversation states
WAITING_FOR_PRIORITY     = 1
WAITING_FOR_JD           = 2
WAITING_FOR_REPLY        = 3
WAITING_FOR_ITERATION    = 4
WAITING_FOR_COVER_LETTER = 5
WAITING_FOR_EMAIL_INPUT  = 6  # /findemail standalone: user pastes LinkedIn/domain
WAITING_FOR_EMAIL_REVIEW = 7  # user sees draft email and chooses action
WAITING_FOR_EMAIL_EDIT   = 8  # user gives Gemini feedback to revise draft
WAITING_FOR_COMPANY_TYPE = 9  # selects IT Services or Product/Startup
WAITING_FOR_EMAIL_FINDER = 10 # selects if email finder should run automatically

LOCAL_CLEANUP_DELAY = 30 * 60  # 30 minutes in seconds

# ─── Security ────────────────────────────────────────────────────────────────
def is_authorized(update: Update) -> bool:
    return update.effective_user.id == ALLOWED_USER_ID

async def reject_unauthorized(update: Update):
    await update.message.reply_text("🚫 Sorry, you're not authorized to use this bot.")

# ─── Helpers ─────────────────────────────────────────────────────────────────
def sanitize_name(name: str) -> str:
    return re.sub(r'[^\w]', '', name)

def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

def _esc_path(p) -> str:
    """Escape a file path for use inside a MarkdownV2 code span."""
    s = str(p).replace('\\', '\\\\')
    s = s.replace('`', '\\`')
    return s

async def generate_pdf(html_path: Path, pdf_path: Path) -> bool:
    """Run generate_pdf.js via Node.js subprocess."""
    import asyncio
    try:
        def run_node():
            return subprocess.run(
                ['node', str(GENERATE_PDF_SCRIPT), str(html_path), str(pdf_path)],
                capture_output=True, text=True, timeout=60,
                cwd=str(REPO_ROOT)
            )
        result = await asyncio.to_thread(run_node)
        if result.returncode != 0:
            logger.error(f"PDF gen stderr: {result.stderr}")
            return False
        logger.info(f"PDF generated: {pdf_path}")
        return True
    except subprocess.TimeoutExpired:
        logger.error("PDF generation timed out")
        return False

def _clear_session(context: ContextTypes.DEFAULT_TYPE):
    """Remove active session data from context."""
    context.user_data.pop('gemini_client', None)
    context.user_data.pop('gemini_chat', None)
    context.user_data.pop('base_resume_used', None)
    context.user_data.pop('output_dir', None)
    context.user_data.pop('guide_task', None)
    context.user_data.pop('guide_md', None)
    context.user_data.pop('guide_summary', None)
    context.user_data.pop('jd', None)
    context.user_data.pop('current_tailored_html', None)
    context.user_data.pop('current_company_name', None)
    context.user_data.pop('html_undo_stack', None)
    # Email finder state
    context.user_data.pop('email_results', None)
    context.user_data.pop('email_draft', None)
    context.user_data.pop('email_draft_contact', None)
    context.user_data.pop('email_finder_ran', None)
    context.user_data.pop('email_pdf_path', None)
    context.user_data.pop('total_usage', None)

# ─── Cleanup Job ─────────────────────────────────────────────────────────────
async def cleanup_local_files(context: ContextTypes.DEFAULT_TYPE):
    """
    Scheduled job: delete generated PDF, HTML, and MD files after 30 minutes.
    The files remain on Google Drive — only the local copies are removed.
    """
    dir_path = Path(context.job.data['dir'])
    if not dir_path.exists():
        return
    deleted = []
    for f in dir_path.iterdir():
        if f.suffix in ('.pdf', '.html', '.md'):
            try:
                f.unlink()
                deleted.append(f.name)
            except Exception as e:
                logger.warning(f"Could not delete {f}: {e}")
    if deleted:
        logger.info(f"🧹 Cleaned up local files in {dir_path}: {', '.join(deleted)}")

def schedule_cleanup(context: ContextTypes.DEFAULT_TYPE, output_dir: Path, company: str):
    """Schedule a cleanup job 30 minutes from now."""
    if context.application.job_queue:
        # Remove any existing cleanup for the same company first
        for job in context.application.job_queue.get_jobs_by_name(f'cleanup_{company}'):
            job.schedule_removal()
        context.application.job_queue.run_once(
            cleanup_local_files,
            LOCAL_CLEANUP_DELAY,
            data={'dir': str(output_dir)},
            name=f'cleanup_{company}'
        )
        logger.info(f"⏲️ Local cleanup scheduled for {company} in 30 minutes")

# ─── Command Handlers ─────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return await reject_unauthorized(update)
    await update.message.reply_text(
        "👋 *Resume Bot is online\\!*\n\n"
        "Commands:\n"
        "• /tailor — Tailor your resume to a job description\n"
        "• /done — Finish iterating and close the session\n"
        "• /cancel — Cancel the current operation\n"
        "• /status — Check bot health\n\n"
        "Use /tailor to get started\\.",
        parse_mode=constants.ParseMode.MARKDOWN_V2
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return await reject_unauthorized(update)
    gemini_ok = bool(os.environ.get('GEMINI_API_KEY'))
    drive_ok = bool(
        os.environ.get('GOOGLE_REFRESH_TOKEN') or
        (REPO_ROOT / 'token.json').exists()
    )
    msg = (
        f"✅ Bot: Running\n"
        f"{'✅' if gemini_ok else '❌'} Gemini API: {'configured' if gemini_ok else 'MISSING KEY'}\n"
        f"{'✅' if drive_ok else '⚠️'} Google Drive: {'configured' if drive_ok else 'not configured'}\n"
        f"📁 Base resumes: {len(list(BASE_RESUMES_DIR.glob('*.html')))} found\n"
        f"📂 Generated: {GENERATED_DIR}"
    )
    await update.message.reply_text(msg)

async def tailor_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return await reject_unauthorized(update)
    
    session_id = uuid.uuid4()
    context.user_data['session_id'] = session_id
    await analytics_logger.log_session_start(session_id, str(update.message.chat_id))
    
    keyboard = [
        [
            InlineKeyboardButton("⚡ Normal Priority (Flash)", callback_data='priority_normal'),
            InlineKeyboardButton("🚀 High Priority (Pro)", callback_data='priority_high')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📋 *Resume Tailor*\n\nPlease select the model priority for this resume:",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.MARKDOWN_V2
    )
    return WAITING_FOR_PRIORITY

async def tailor_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    priority = query.data.split('_')[1] # 'normal' or 'high'
    context.user_data['model_priority'] = priority
    
    model_display = "Gemini 3.1 Pro (Preview)" if priority == 'high' else "Gemini 3.5 Flash"
    
    keyboard = [
        [
            InlineKeyboardButton("Yes", callback_data='coverletter_yes'),
            InlineKeyboardButton("No", callback_data='coverletter_no')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"Selected: *{escape_md(model_display)}*\n\nWould you like to generate a tailored cover letter as well?",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.MARKDOWN_V2
    )
    return WAITING_FOR_COVER_LETTER

async def tailor_cover_letter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    wants_cover_letter = (query.data == 'coverletter_yes')
    context.user_data['generate_cover_letter'] = wants_cover_letter
    
    cl_text = "Yes" if wants_cover_letter else "No"
    
    keyboard = [
        [
            InlineKeyboardButton("Yes", callback_data='autoemail_yes'),
            InlineKeyboardButton("No", callback_data='autoemail_no')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"Cover Letter: *{cl_text}*\n\nWould you like to automatically find recruiter emails?",
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.MARKDOWN_V2
    )
    return WAITING_FOR_EMAIL_FINDER

async def tailor_auto_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    wants_auto_email = (query.data == 'autoemail_yes')
    context.user_data['auto_email_finder'] = wants_auto_email
    
    ae_text = "Yes" if wants_auto_email else "No"
    
    await query.edit_message_text(
        f"Find Emails: *{ae_text}*\n\nPlease paste the full Job Description below\\.\n\n"
        "💡 _Tip: Include the company name, role, and full JD text for best results\\._\n\n"
        "Send /cancel to abort\\.",
        parse_mode=constants.ParseMode.MARKDOWN_V2
    )
    return WAITING_FOR_JD

async def tailor_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return await reject_unauthorized(update)

    if update.message.document:
        doc = update.message.document
        if not doc.file_name.endswith('.txt'):
            await update.message.reply_text("⚠️ Please upload a valid .txt file.")
            return WAITING_FOR_JD
        file = await doc.get_file()
        file_bytes = await file.download_as_bytearray()
        jd = file_bytes.decode('utf-8', errors='ignore').strip()
    else:
        jd = update.message.text.strip()

    if len(jd) < 100:
        await update.message.reply_text(
            "⚠️ That JD seems too short. Please paste or upload the full job description."
        )
        return WAITING_FOR_JD

    status_msg = await update.message.reply_text(
        r"🔍 *Step 1/4:* Researching company & tailoring resume with Gemini\.\.\.",
        parse_mode=constants.ParseMode.MARKDOWN_V2
    )

    try:
        session_id = context.user_data.get('session_id')
        client = GeminiClient(session_id=session_id)
        
        async def ui_callback(msg: str):
            try:
                await status_msg.edit_text(msg, parse_mode=constants.ParseMode.MARKDOWN_V2)
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise

        priority = context.user_data.get('model_priority', 'normal')
        generate_cover_letter = context.user_data.get('generate_cover_letter', False)

        import asyncio
        context.user_data['jd'] = jd
        
        await ui_callback(r"🔍 *Step 1/4:* Gathering Intelligence & Company Research\.\.\.")
        guide_result = await client.generate_company_guide(jd, priority)
        research_md = guide_result.get('research_md', '')
        company_type = guide_result.get('company_type', 'product_startup')
        
        context.user_data['guide_md'] = research_md
        context.user_data['company_type'] = company_type
        context.user_data['grounding_sources'] = guide_result.get('grounding_sources', [])
        
        total_usage = context.user_data.setdefault('total_usage', {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'cost': 0.0,
            'model_used': set()
        })
        def add_usage(usage_dict):
            if not usage_dict: return
            total_usage['prompt_tokens'] += usage_dict.get('prompt_tokens', 0)
            total_usage['completion_tokens'] += usage_dict.get('completion_tokens', 0)
            total_usage['cost'] += usage_dict.get('cost', 0.0)
            if 'model_used' in usage_dict:
                total_usage['model_used'].add(usage_dict['model_used'])

        add_usage(guide_result.get('usage'))

        master_profile_path = REPO_ROOT / 'master_profile.json'
        template_path = REPO_ROOT / 'resume_template.html'
        
        if not master_profile_path.exists() or not template_path.exists():
            raise FileNotFoundError("Missing master_profile.json or resume_template.html")
            
        master_profile_json = master_profile_path.read_text(encoding='utf-8')
        template_html = template_path.read_text(encoding='utf-8')

        current_html = None
        feedback = None
        max_iterations = 3
        
        raw_response = None
        usage_data = None
        
        for iteration in range(1, max_iterations + 1):
            await ui_callback(rf"🤖 *Step 1/4:* Generating draft \(Iteration {iteration}/{max_iterations}\)\.\.\.")
            
            resp = await client.refine_resume(
                jd=jd,
                company_type=company_type,
                master_profile_json=master_profile_json,
                template_html=template_html,
                research_md=research_md,
                current_html=current_html,
                feedback=feedback,
                priority=priority
            )
            
            usage_data = resp
            add_usage(resp)
            raw_response = resp['text']
            
            if session_id:
                await analytics_logger.log_agent_trace(
                    session_id, iteration, 'generator',
                    prompt_text=f"Feedback: {feedback}" if feedback else "Initial draft",
                    raw_response=raw_response,
                    parsed_output=""
                )

            # Make sure we got a valid response format
            if not client.is_final_output(raw_response):
                raise RuntimeError("Generator did not return final output markers.\n" + raw_response)
                
            parsed = client.parse_final_response(raw_response)
            current_html = parsed['tailored_html']
            
            await ui_callback(rf"⚖️ *Step 1/4:* Critic evaluating draft \(Iteration {iteration}/{max_iterations}\)\.\.\.")
            evaluation, eval_usage = await client.evaluate_resume(
                current_html=current_html,
                master_profile_json=master_profile_json,
                jd=jd,
                company_type=company_type,
                research_md=research_md,
                priority=priority
            )
            add_usage(eval_usage)

            if session_id:
                await analytics_logger.log_evaluation(
                    session_id, iteration, evaluation.passed, str(evaluation.is_hallucinated),
                    evaluation.ats_score, evaluation.manual_score
                )
                await analytics_logger.log_agent_trace(
                    session_id, iteration, 'evaluator',
                    prompt_text="Evaluating current_html",
                    raw_response=str(evaluation.feedback),
                    parsed_output=f"Passed: {evaluation.passed}, Hallucinated: {evaluation.is_hallucinated}"
                )
            
            if evaluation.passed and not evaluation.is_hallucinated:
                await ui_callback(rf"✅ *Step 1/4:* Draft passed evaluation\! \(Iteration {iteration}\)")
                await asyncio.sleep(2)
                break
                
            feedback_str = ""
            if evaluation.is_hallucinated:
                feedback_str += "CRITICAL WARNING: Hallucinations detected. You must stick strictly to facts in the master profile.\n"
            feedback_str += "Critic Feedback to Address:\n" + "\n".join([f"- {fb}" for fb in evaluation.feedback])
            
            feedback = feedback_str
            
            if iteration == max_iterations:
                await ui_callback(rf"⚠️ *Step 1/4:* Max iterations reached\. Proceeding with current draft\.")
                await asyncio.sleep(2)

        # Save session for follow-ups
        context.user_data['gemini_client'] = client
        context.user_data['base_resume_used'] = 'master_profile.json'

        return await finalize_resume(update, context, status_msg, client, raw_response, usage=None)

    except Exception as e:
        logger.exception("Error during tailor_process")
        await status_msg.edit_text(
            f"❌ *Error:* {escape_md(str(e)[:300])}\n\nPlease try again or check /status\\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        _clear_session(context)
        return ConversationHandler.END


async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles conversational back-and-forth before the resume is generated."""
    if not is_authorized(update): return await reject_unauthorized(update)

    user_text = update.message.text.strip()
    client = context.user_data.get('gemini_client')
    chat = context.user_data.get('gemini_chat')

    if not chat or not client:
        await update.message.reply_text("⚠️ No active session. Please start over with /tailor.")
        return ConversationHandler.END

    status_msg = await update.message.reply_text(
        r"🤔 *Thinking\.\.\.*",
        parse_mode=constants.ParseMode.MARKDOWN_V2
    )

    try:
        async def ui_callback(msg: str):
            try:
                await status_msg.edit_text(msg, parse_mode=constants.ParseMode.MARKDOWN_V2)
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise

        raw_response_data = await client.send_message_with_retry(chat, user_text, ui_callback)
        raw_response = raw_response_data['text']

        if not client.is_final_output(raw_response):
            await status_msg.edit_text(
                f"🤖 *Gemini says:*\n\n{escape_md(raw_response)}\n\n_Reply with your answer, or /cancel to abort\\._",
                parse_mode=constants.ParseMode.MARKDOWN_V2
            )
            return WAITING_FOR_REPLY

        return await finalize_resume(update, context, status_msg, client, raw_response, usage=raw_response_data)

    except Exception as e:
        logger.exception("Error during handle_reply")
        await status_msg.edit_text(
            f"❌ *Error:* {escape_md(str(e)[:300])}\n\nPlease try again or check /status\\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        _clear_session(context)
        return ConversationHandler.END


async def handle_iteration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles revision requests after the resume has been generated.
    Uses a lean stateless revise_resume() call instead of the expensive chat session,
    keeping token cost flat regardless of how many revisions are made.
    Supports 'undo' to revert the last revision.
    """
    if not is_authorized(update): return await reject_unauthorized(update)

    user_text = update.message.text.strip()
    logger.info(f"handle_iteration triggered by text: {user_text}")

    client = context.user_data.get('gemini_client')
    current_html = context.user_data.get('current_tailored_html')
    company_name = context.user_data.get('current_company_name')
    jd = context.user_data.get('jd', '')
    undo_stack: list = context.user_data.get('html_undo_stack', [])

    if not client or not current_html or not company_name:
        await update.message.reply_text("⚠️ Session expired. Use /tailor to start a new one.")
        return ConversationHandler.END

    # ── Undo support ─────────────────────────────────────────────────────────
    if user_text.lower() in ('undo', '/undo', 'revert', 'undo last'):
        if not undo_stack:
            await update.message.reply_text(
                "⚠️ Nothing to undo — this is already the original version\.",
                parse_mode=constants.ParseMode.MARKDOWN_V2
            )
            return WAITING_FOR_ITERATION

        previous_html = undo_stack.pop()
        context.user_data['current_tailored_html'] = previous_html
        context.user_data['html_undo_stack'] = undo_stack

        status_msg = await update.message.reply_text(
            r"↩️ *Reverting to previous version\.\.\.*",
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        # Re-finalize with the restored HTML
        fake_raw = f"===COMPANY_NAME===\n{company_name}\n\n===TAILORED_HTML===\n{previous_html}"
        return await finalize_resume(update, context, status_msg, client, fake_raw)

    # ── Stateless revision ────────────────────────────────────────────────────
    status_msg = await update.message.reply_text(
        r"🔄 *Revising your resume\.\.\.*",
        parse_mode=constants.ParseMode.MARKDOWN_V2
    )

    try:
        session_id = context.user_data.get('session_id')
        if session_id:
            await analytics_logger.log_funnel_event(session_id, 'revision_requested')
            
        priority = context.user_data.get('model_priority', 'normal')
        raw_response_data = await client.revise_resume(
            current_html=current_html,
            company_name=company_name,
            jd=jd,
            feedback=user_text,
            priority=priority
        )
        raw_response = raw_response_data['text']

        if not client.is_final_output(raw_response):
            # Model asked a clarifying question instead of generating
            await status_msg.edit_text(
                f"🤖 *Gemini says:*\n\n{escape_md(raw_response)}\n\n_Reply with your answer, or /done to finish\\._",
                parse_mode=constants.ParseMode.MARKDOWN_V2
            )
            return WAITING_FOR_ITERATION

        # Push current HTML onto undo stack (keep max 3 snapshots)
        undo_stack.append(current_html)
        if len(undo_stack) > 3:
            undo_stack.pop(0)
        context.user_data['html_undo_stack'] = undo_stack

        return await finalize_resume(update, context, status_msg, client, raw_response, usage=raw_response_data)

    except Exception as e:
        logger.exception("Error during handle_iteration")
        await status_msg.edit_text(
            f"❌ *Error:* {escape_md(str(e)[:300])}",
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        _clear_session(context)
        return ConversationHandler.END


async def finalize_resume(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    status_msg,
    client: GeminiClient,
    raw_response: str,
    usage: dict = None
):
    """
    Parses final Gemini response, generates PDF, uploads to Drive,
    then enters WAITING_FOR_ITERATION so the user can request changes.
    Schedules local file cleanup after 30 minutes.
    """
    try:
        data = client.parse_final_response(raw_response)
        data['base_resume_used'] = context.user_data.get('base_resume_used', 'unknown')

        # Use cached guide from a previous iteration if available
        cached_guide_md = context.user_data.get('guide_md')
        cached_summary = context.user_data.get('guide_summary')
        
        total_usage = context.user_data.setdefault('total_usage', {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'cost': 0.0,
            'model_used': set()
        })
        def add_usage(usage_dict):
            if not usage_dict: return
            total_usage['prompt_tokens'] += usage_dict.get('prompt_tokens', 0)
            total_usage['completion_tokens'] += usage_dict.get('completion_tokens', 0)
            total_usage['cost'] += usage_dict.get('cost', 0.0)
            if 'model_used' in usage_dict:
                total_usage['model_used'].add(usage_dict['model_used'])
                
        if usage:
            usage['grounding_sources'] = context.user_data.get('grounding_sources', [])
            # In handle_iteration and handle_reply, usage from the recent call is passed here.
            # Only add it if it hasn't been added yet (in tailor_process it was already added,
            # but wait, let's just make sure we only add it here for handle_iteration/reply).
            # Actually, to avoid double-counting in tailor_process, we can just pass `usage=None` from tailor_process,
            # and `usage=raw_response_data` from handle_iteration.
            add_usage(usage)

        if cached_guide_md and not cached_summary:
            await status_msg.edit_text(
                f"✅ *Step 1/4:* Resume tailored\\!\n"
                f"⏳ *Step 1\\.5/4:* Finalizing guide with tailored resume\\.\\.\\.",
                parse_mode=constants.ParseMode.MARKDOWN_V2
            )
            jd = context.user_data.get('jd', '')
            priority = context.user_data.get('model_priority', 'normal')
            try:
                finalized = await client.finalize_guide(
                    jd, cached_guide_md, data['tailored_html'], priority
                )
                add_usage(finalized.get('usage'))
                data['guide_md'] = finalized.get('guide_md', '')
                data['summary'] = finalized.get('summary', '')
                context.user_data['guide_md'] = data['guide_md']
                context.user_data['guide_summary'] = data['summary']
            except Exception as e:
                logger.error(f"Guide generation failed: {e}")
        elif cached_guide_md and cached_summary:
            data['guide_md'] = cached_guide_md
            data['summary'] = cached_summary

        company = sanitize_name(data['company_name'])
        company_display = data.get('company_name_display', company)

        # Generate Cover Letter if requested
        generate_cover_letter = context.user_data.get('generate_cover_letter', False)
        if generate_cover_letter and not data.get('cover_letter'):
            await status_msg.edit_text(
                f"✅ *Step 1/4:* Resume tailored\\!\n"
                f"⏳ *Step 1\\.5/4:* Drafting Cover Letter\\.\\.\\.",
                parse_mode=constants.ParseMode.MARKDOWN_V2
            )
            try:
                jd = context.user_data.get('jd', '')
                cl_result = await client.generate_cover_letter(jd, company_display, data['tailored_html'])
                add_usage(cl_result.get('usage'))
                data['cover_letter'] = cl_result.get('cover_letter', '')
            except Exception as e:
                logger.error(f"Cover letter generation failed: {e}")

        session_id = context.user_data.get('session_id')
        if session_id:
            await analytics_logger.log_funnel_event(session_id, 'resume_tailored')
            await analytics_logger.update_session(session_id, company_name=company_display)

        await status_msg.edit_text(
            f"✅ *Step 1/4:* Resume tailored for *{escape_md(company_display)}*\\!\n"
            f"🖨️ *Step 2/4:* Generating PDF\\.\\.\\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )

        # Write files
        output_dir = GENERATED_DIR / company
        output_dir.mkdir(parents=True, exist_ok=True)
        context.user_data['output_dir'] = str(output_dir)

        html_path = output_dir / f"PurveshGandhi_Resume_{company}.html"
        pdf_path = output_dir / f"PurveshGandhi_Resume_{company}.pdf"
        guide_path = output_dir / f"{company}_Guide.md"
        cl_path = output_dir / f"{company}_Cover_Letter.txt"

        html_path.write_text(data['tailored_html'], encoding='utf-8')

        # Store current HTML state for stateless revisions + undo stack
        context.user_data['current_tailored_html'] = data['tailored_html']
        context.user_data['current_company_name'] = company
        context.user_data.setdefault('html_undo_stack', [])  # don't reset on revision, only on new session
        if data.get('guide_md'):
            guide_content = data['guide_md']
            grounding_sources = context.user_data.get('grounding_sources', [])
            if grounding_sources:
                guide_content += "\n\n---\n## Verified Search Sources\n"
                for source in grounding_sources:
                    guide_content += f"- [{source['title']}]({source['uri']})\n"
            guide_path.write_text(guide_content, encoding='utf-8')
        if data.get('cover_letter'):
            cl_path.write_text(data['cover_letter'], encoding='utf-8')

        pdf_ok = await generate_pdf(html_path, pdf_path)
        if pdf_ok and session_id:
            await analytics_logger.log_funnel_event(session_id, 'pdf_generated')

        pdf_icon = '✅' if pdf_ok else '⚠️'
        pdf_status_txt = 'generated' if pdf_ok else r'failed \(HTML saved\)'
        await status_msg.edit_text(
            f"✅ *Step 1/4:* Resume tailored\\!\n"
            f"{pdf_icon} *Step 2/4:* PDF {pdf_status_txt}\\.\n"
            f"☁️ *Step 3/4:* Uploading to Google Drive\\.\\.\\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )

        # Upload to Drive
        files_to_upload = [str(html_path)]
        if pdf_ok:
            files_to_upload.insert(0, str(pdf_path))
        if data.get('guide_md') and guide_path.exists():
            files_to_upload.append(str(guide_path))
        if data.get('cover_letter') and cl_path.exists():
            files_to_upload.append(str(cl_path))

        upload_results = {}
        try:
            import asyncio
            upload_results = await asyncio.to_thread(
                upload_files_to_company_folder, company_display, *files_to_upload
            )
        except Exception as e:
            logger.error(f"Drive upload failed: {e}")

        await status_msg.edit_text(
            f"✅ *Step 1/4:* Resume tailored\\!\n"
            f"{'✅' if pdf_ok else '⚠️'} *Step 2/4:* PDF {'generated' if pdf_ok else 'failed'}\\.\n"
            f"{'✅' if upload_results else '⚠️'} *Step 3/4:* Drive upload {'done' if upload_results else 'failed'}\\.\n"
            f"📨 *Step 4/4:* Preparing summary\\.\\.\\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )

        # Build final message
        drive_section = format_upload_results(upload_results) if upload_results else (
            "⚠️ Drive upload failed — files saved locally:\n"
            f"`{_esc_path(html_path)}`\n"
            + (f"`{_esc_path(pdf_path)}`\n" if pdf_ok else "")
            + (f"`{_esc_path(guide_path)}`\n" if data.get('guide_md') else "")
            + (f"`{_esc_path(cl_path)}`" if data.get('cover_letter') else "")
        )

        summary_section = ""
        if data.get('summary'):
            summary_section = f"\n\n💡 *Strategy:* {escape_md(data['summary'])}"
            
        usage_section = ""
        if total_usage and total_usage['prompt_tokens'] > 0:
            cost_str = f"${total_usage.get('cost', 0):.4f}"
            models_list = ", ".join(sorted(list(total_usage['model_used'])))
            is_free_tier = 'flash' in models_list.lower() and 'pro' not in models_list.lower()
            
            coverage_line = f"• Coverage: ✨ `100% Free Tier`\n" if is_free_tier else ""
            
            # Revision specific usage (if passed from handle_iteration)
            revision_section = ""
            if usage and usage.get('prompt_tokens'):
                rev_cost_str = f"${usage.get('cost', 0):.4f}"
                revision_section = (
                    f"• This Revision: `{usage.get('prompt_tokens', 0)}` in \\| `{usage.get('completion_tokens', 0)}` out \\(Cost: `{escape_md(rev_cost_str)}\\)`\n"
                )

            usage_section = (
                f"\n\n📊 *Total Session API Usage & Cost*\n"
                f"• Model: `{escape_md(models_list)}`\n"
                f"• Session Total: `{total_usage.get('prompt_tokens', 0)}` in \\| `{total_usage.get('completion_tokens', 0)}` out\n"
                f"{revision_section}"
                f"{coverage_line}"
                f"• Est\\. Cost \\(Paid Tier\\): `{escape_md(cost_str)}`"
            )

        final_msg = (
            f"🎉 *Done\\! Resume tailored for {escape_md(company_display)}*\n\n"
            f"{drive_section}"
            f"{summary_section}"
            f"{usage_section}\n\n"
            f"_Base resume used: `{_esc_path(data.get('base_resume_used', 'unknown'))}`_\n\n"
            "✏️ *Want to make any changes?* Reply with your feedback, or /done to finish\\.\n"
            "_Local files will be auto\\-deleted in 30 minutes — Drive files are permanent\\._"
        )

        await status_msg.edit_text(final_msg, parse_mode=constants.ParseMode.MARKDOWN_V2)

        if data.get('cover_letter'):
            cl_msg = f"📝 *Cover Letter:*\n\n{escape_md(data['cover_letter'])}"
            # Telegram message limit is 4096 chars; send as document if too long
            if len(cl_msg) <= 4096:
                await update.message.reply_text(cl_msg, parse_mode=constants.ParseMode.MARKDOWN_V2)
            else:
                import io
                cl_bytes = data['cover_letter'].encode('utf-8')
                await update.message.reply_document(
                    document=io.BytesIO(cl_bytes),
                    filename=f"{company}_Cover_Letter.txt",
                    caption="📝 Cover letter (sent as file — too long for a message)"
                )

        # Fallback: send PDF as attachment if Drive upload failed
        if not upload_results and pdf_ok:
            await update.message.reply_document(
                document=open(pdf_path, 'rb'),
                filename=pdf_path.name,
                caption="📄 Resume PDF (Drive upload failed)"
            )

        # Schedule local cleanup in 30 minutes
        if upload_results:
            schedule_cleanup(context, output_dir, company)

        # ── Trigger 1: Email finder (after guide + PDF + Drive all done) ──────
        # Store PDF path for later attachment when sending
        if pdf_ok:
            context.user_data['email_pdf_path'] = str(pdf_path)
        # Run in background so the main resume message appears instantly
        if context.user_data.get('auto_email_finder', False):
            import asyncio as _asyncio
            _asyncio.create_task(
                _run_email_finder_flow(update, context, is_trigger_1=True)
            )

        return WAITING_FOR_ITERATION

    except Exception as e:
        logger.exception("Error during finalize_resume")
        await status_msg.edit_text(
            f"❌ *Error finalizing:* {escape_md(str(e)[:300])}",
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        _clear_session(context)
        return ConversationHandler.END


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ends the current session. Trigger 2: remind/re-run email finder before closing."""
    if not is_authorized(update): return await reject_unauthorized(update)

    email_results: list = context.user_data.get('email_results', [])
    company_name  = context.user_data.get('current_company_name', '')
    finder_ran    = context.user_data.get('email_finder_ran', False)

    # If email finder hasn't run yet (rare: Trigger 1 failed), run it now
    wants_auto_email = context.user_data.get('auto_email_finder', False)
    if wants_auto_email and not finder_ran and company_name:
        await update.message.reply_text(
            "🔍 Running email finder before closing\.\.\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        await _run_email_finder_flow(update, context, is_trigger_1=False)
        session_id = context.user_data.get('session_id')
        if session_id: 
            await analytics_logger.log_funnel_event(session_id, 'session_closed')
            await analytics_logger.update_session(session_id, end_time=True)
        _clear_session(context)
        await update.message.reply_text(
            "✅ Session closed\\. Use /tailor whenever you need a new resume\\!",
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        return ConversationHandler.END

    # Email finder already ran — show a compact reminder
    if email_results and company_name:
        draft = context.user_data.get('email_draft')
        top_email = email_results[0].get('email', '')
        verified_icon = '✅' if email_results[0].get('verified') else '⚠️'

        reminder = (
            f"📧 *Before you go — cold outreach for {escape_md(company_name)}:*\n"
            f"{verified_icon} `{escape_md(top_email)}`"
            + (f" \\+{len(email_results)-1} more" if len(email_results) > 1 else "")
            + "\n\n"
        )
        if draft:
            reminder += "Reply /reviewemail to send, or /done again to close\."
        else:
            reminder += "Reply /done again to close\."

        await update.message.reply_text(
            reminder,
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        # Require a second /done to actually close (one-shot reminder)
        if context.user_data.get('done_reminder_shown'):
            session_id = context.user_data.get('session_id')
            if session_id: 
                await analytics_logger.log_funnel_event(session_id, 'session_closed')
                await analytics_logger.update_session(session_id, end_time=True)
            _clear_session(context)
            await update.message.reply_text(
                "✅ Session closed\\. Use /tailor whenever you need a new resume\\!",
                parse_mode=constants.ParseMode.MARKDOWN_V2
            )
            return ConversationHandler.END
        context.user_data['done_reminder_shown'] = True
        return WAITING_FOR_ITERATION

    # No email results — close cleanly
    session_id = context.user_data.get('session_id')
    if session_id: 
        await analytics_logger.log_funnel_event(session_id, 'session_closed')
        await analytics_logger.update_session(session_id, end_time=True)
    _clear_session(context)
    await update.message.reply_text(
        "✅ Session closed\\. Use /tailor whenever you need a new resume\\!",
        parse_mode=constants.ParseMode.MARKDOWN_V2
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return await reject_unauthorized(update)
    session_id = context.user_data.get('session_id')
    if session_id:
        await analytics_logger.update_session(session_id, end_time=True)
    _clear_session(context)
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    await update.message.reply_text("❓ Unknown command. Use /tailor to start.")


# ─── Email Finder Flow ────────────────────────────────────────────────────────

async def _run_email_finder_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    is_trigger_1: bool = True,
    manual_input: str | None = None,
):
    """
    Core email finder routine called from two places:
      Trigger 1 — end of finalize_resume() (background task)
      Trigger 2 — when /done is called and finder hasn't run yet
    Also reused by the /findemail standalone command.
    Sends its own messages; does NOT return a conversation state.
    """
    company_name = context.user_data.get('current_company_name', '')
    jd_text      = context.user_data.get('jd', '')
    guide_md     = context.user_data.get('guide_md', '')
    pdf_path     = context.user_data.get('email_pdf_path', '')

    # Parse LinkedIn URL or domain from manual_input if provided
    linkedin_url  = None
    person_name   = None
    company_domain = None
    if manual_input:
        text = manual_input.strip()
        if 'linkedin.com/in/' in text:
            linkedin_url = text
        elif '.' in text and ' ' not in text:
            company_domain = text  # bare domain like acme.com
        else:
            company_name = text or company_name  # treat as company name

    if not company_name and not company_domain:
        logger.warning("_run_email_finder_flow: no company name or domain available")
        return

    # Send status message
    chat_id = update.effective_chat.id
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔍 Searching for contact emails at {escape_md(company_name or company_domain)}\\.\.\\.",
        parse_mode=constants.ParseMode.MARKDOWN_V2,
    )

    try:
        result = await find_emails_async(
            company_name=company_name,
            jd_text=jd_text,
            linkedin_url=linkedin_url,
            person_name=person_name,
            company_domain=company_domain,
            session_id=context.user_data.get('session_id'),
        )
    except Exception as e:
        logger.error(f"Email finder error: {e}")
        await status_msg.edit_text("⚠️ Email finder encountered an error\. Try /findemail manually\.",
                                   parse_mode=constants.ParseMode.MARKDOWN_V2)
        return

    emails    = result.get('emails', [])
    domain_missing = result.get('domain_missing', False)

    # Store results in session
    context.user_data['email_results']  = emails
    context.user_data['email_finder_ran'] = True

    if domain_missing:
        await status_msg.edit_text(
            f"⚠️ *Couldn't resolve domain for {escape_md(company_name)}\.*\n"
            "Reply /findemail followed by the company domain \(e\.g\. `/findemail acme\.com`\)\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2,
        )
        return

    if not emails:
        await status_msg.edit_text(
            f"❌ No emails found for {escape_md(company_name)}\. "
            "Try /findemail with the LinkedIn URL of the recruiter\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2,
        )
        return

    # Format and show results
    results_text = format_email_results(emails, company_name or company_domain)
    await status_msg.edit_text(escape_md(results_text), parse_mode=constants.ParseMode.MARKDOWN_V2)

    # Draft cold email for the top contact (highest confidence)
    top_contact = emails[0]
    role = _extract_role_from_jd(jd_text)
    draft_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="✍️ Drafting your cold email\.\.\.",
        parse_mode=constants.ParseMode.MARKDOWN_V2,
    )
    draft = await draft_cold_email(
        contact=top_contact,
        company_name=company_name or company_domain,
        role=role,
        guide_md=guide_md,
        drive_link="",  # omit Drive link from email body — attach PDF instead
    )

    if not draft:
        await draft_msg.edit_text("⚠️ Couldn't draft email\. Use /findemail to retry\.",
                                  parse_mode=constants.ParseMode.MARKDOWN_V2)
        return

    context.user_data['email_draft']         = draft
    context.user_data['email_draft_contact'] = top_contact

    # Show the draft with action buttons
    await draft_msg.delete()
    await _show_email_review(context, chat_id, draft, top_contact)


def _extract_role_from_jd(jd_text: str) -> str:
    """Best-effort: extract job role from first 300 chars of JD."""
    if not jd_text:
        return "Software Engineer"
    # Look for common role patterns in the first few lines
    first_block = jd_text[:300]
    patterns = [
        r'(?:hiring|looking for|role|position|title)[:\s]+([\w\s]+?Engineer[\w\s]*)',
        r'(?:hiring|looking for|role|position|title)[:\s]+([\w\s]+?Developer[\w\s]*)',
        r'^([\w\s]+(?:Engineer|Developer|Architect|Manager|Lead))',
    ]
    for pat in patterns:
        m = re.search(pat, first_block, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()[:60]
    return "Software Engineer"


async def _show_email_review(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    draft: dict,
    contact: dict,
):
    """Send the draft email with Send / Edit / Copy / Skip inline buttons."""
    gmail_ok = is_gmail_configured()
    draft_text = format_draft_for_telegram(draft)
    preview = escape_md(draft_text)

    keyboard = [[
        InlineKeyboardButton("📤 Send" if gmail_ok else "📤 Send (setup needed)",
                             callback_data='email_send'),
        InlineKeyboardButton("✏️ Edit", callback_data='email_edit'),
    ], [
        InlineKeyboardButton("📋 Copy text", callback_data='email_copy'),
        InlineKeyboardButton("❌ Skip", callback_data='email_skip'),
    ]]
    await context.bot.send_message(
        chat_id=chat_id,
        text=preview,
        parse_mode=constants.ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def findemail_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /findemail <LinkedIn URL | domain | company name>."""
    if not is_authorized(update): return await reject_unauthorized(update)
    args = context.args or []
    manual_input = ' '.join(args).strip()
    if manual_input:
        # Input provided inline — run directly
        await _run_email_finder_flow(update, context, is_trigger_1=False,
                                     manual_input=manual_input)
        return ConversationHandler.END
    # No input — prompt user
    await update.message.reply_text(
        "🔍 *Email Finder*\n\n"
        "Send me one of:\n"
        "• LinkedIn profile URL: `https://linkedin\.com/in/name`\n"
        "• Company domain: `acme\.com`\n"
        "• Company name: `Acme Corp`\n\n"
        "Or /cancel to abort\.",
        parse_mode=constants.ParseMode.MARKDOWN_V2,
    )
    return WAITING_FOR_EMAIL_INPUT


async def findemail_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the manual input from the user in WAITING_FOR_EMAIL_INPUT state."""
    if not is_authorized(update): return await reject_unauthorized(update)
    manual_input = update.message.text.strip()
    await _run_email_finder_flow(update, context, is_trigger_1=False,
                                 manual_input=manual_input)
    return ConversationHandler.END


async def email_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline button presses on the email draft review message."""
    if not is_authorized(update): return
    query = update.callback_query
    await query.answer()
    action = query.data  # 'email_send' | 'email_edit' | 'email_copy' | 'email_skip'

    draft   = context.user_data.get('email_draft')
    contact = context.user_data.get('email_draft_contact')

    if action == 'email_skip':
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("👍 Email skipped\. Use /findemail anytime to retry\.",
                                       parse_mode=constants.ParseMode.MARKDOWN_V2)
        return

    if action == 'email_copy':
        await query.edit_message_reply_markup(reply_markup=None)
        body = draft.get('body', '') if draft else ''
        subject = draft.get('subject', '') if draft else ''
        await query.message.reply_text(
            f"📋 *Subject:* `{escape_md(subject)}`\n\n{escape_md(body)}",
            parse_mode=constants.ParseMode.MARKDOWN_V2,
        )
        return

    if action == 'email_edit':
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "✏️ What should I change? Describe your feedback and I'll revise the email\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2,
        )
        context.user_data['awaiting_email_edit'] = True
        return

    if action == 'email_send':
        if not draft or not contact:
            await query.edit_message_text("⚠️ No draft available\. Use /findemail to start again\.",
                                          parse_mode=constants.ParseMode.MARKDOWN_V2)
            return
        if not is_gmail_configured():
            await query.answer(
                "Gmail not configured. Re-run OAuth setup to enable sending.", show_alert=True
            )
            return
        await query.edit_message_reply_markup(reply_markup=None)
        sending_msg = await query.message.reply_text(
            "📤 Sending email\.\.\.", parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        pdf_path = context.user_data.get('email_pdf_path')
        result = await send_cold_email_async(
            to=contact['email'],
            subject=draft['subject'],
            body=draft['body'],
            attachment_path=pdf_path,
        )
        if result['success']:
            await sending_msg.edit_text(
                f"✅ *Email sent to `{escape_md(contact['email'])}`\\!*\n"
                f"Gmail message ID: `{escape_md(result['message_id'])}`",
                parse_mode=constants.ParseMode.MARKDOWN_V2,
            )
        else:
            await sending_msg.edit_text(
                f"❌ *Send failed:* {escape_md(result['error'][:200])}",
                parse_mode=constants.ParseMode.MARKDOWN_V2,
            )


async def email_edit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles free-text revision feedback after the user taps 'Edit'.
    Routed via the WAITING_FOR_EMAIL_EDIT state OR the awaiting_email_edit flag.
    """
    if not is_authorized(update): return await reject_unauthorized(update)
    if not context.user_data.get('awaiting_email_edit'):
        return  # not in edit mode

    feedback = update.message.text.strip()
    draft    = context.user_data.get('email_draft')
    contact  = context.user_data.get('email_draft_contact')

    if not draft:
        await update.message.reply_text(
            "⚠️ No draft to edit\\. Use /findemail to start again\\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2,
        )
        context.user_data.pop('awaiting_email_edit', None)
        return WAITING_FOR_ITERATION

    status_msg = await update.message.reply_text(
        "✍️ Revising\\.\.\\.", parse_mode=constants.ParseMode.MARKDOWN_V2
    )
    revised = await revise_cold_email(
        original_subject=draft['subject'],
        original_body=draft['body'],
        feedback=feedback,
    )
    context.user_data.pop('awaiting_email_edit', None)

    if not revised:
        await status_msg.edit_text(
            "⚠️ Revision failed\\. Try again or tap Edit on the original draft\\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2,
        )
        return WAITING_FOR_ITERATION

    context.user_data['email_draft'] = revised
    await status_msg.delete()
    await _show_email_review(context, update.effective_chat.id, revised, contact)
    return WAITING_FOR_ITERATION


async def reviewemail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-show the current email draft when user types /reviewemail."""
    if not is_authorized(update): return await reject_unauthorized(update)
    draft   = context.user_data.get('email_draft')
    contact = context.user_data.get('email_draft_contact')
    if not draft or not contact:
        await update.message.reply_text(
            "📭 No draft available\\. Run /findemail or use /tailor to generate one\\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2,
        )
        return
    await _show_email_review(context, update.effective_chat.id, draft, contact)


async def _iteration_or_email_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Dispatcher for WAITING_FOR_ITERATION free-text messages.
    Routes to email_edit_handler if user just tapped Edit, else handle_iteration.
    """
    if context.user_data.get('awaiting_email_edit'):
        return await email_edit_handler(update, context)
    return await handle_iteration(update, context)


# ─── Error Handler ────────────────────────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and notify the user if possible."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text(
                f"⚠️ Something went wrong ({type(context.error).__name__}). Please try again."
            )
        except Exception:
            pass

# ─── Keep-alive HTTP server (for Render free tier) ───────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args): pass

def start_health_server():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    logger.info(f"Health server listening on port {port}")
    server.serve_forever()

# ─── Main ─────────────────────────────────────────────────────────────────────
async def post_init(app: Application):
    logger.info("Initializing Supabase database connection...")
    await analytics_logger.init_db()

async def post_shutdown(app: Application):
    logger.info("Closing Supabase database connection...")
    await analytics_logger.close_db()

def main():
    threading.Thread(target=start_health_server, daemon=True).start()

    # Explicit timeouts — defaults (5s) are too short for real usage
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    fallbacks = [
        CommandHandler('cancel', cancel),
        MessageHandler(filters.COMMAND, cancel)
    ]

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('tailor', tailor_start),
            CommandHandler('findemail', findemail_start)
        ],
        states={
            WAITING_FOR_PRIORITY: [
                CallbackQueryHandler(tailor_priority, pattern='^priority_')
            ],
            WAITING_FOR_COVER_LETTER: [
                CallbackQueryHandler(tailor_cover_letter, pattern='^coverletter_')
            ],
            WAITING_FOR_EMAIL_FINDER: [
                CallbackQueryHandler(tailor_auto_email, pattern='^autoemail_')
            ],
            WAITING_FOR_JD: [
                MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.Document.FileExtension("txt"), tailor_process)
            ],
            WAITING_FOR_REPLY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply)
            ],
            WAITING_FOR_ITERATION: [
                CommandHandler('done', done_command),
                CommandHandler('reviewemail', reviewemail_command),
                CommandHandler('findemail', findemail_start),
                # email_edit_handler is triggered by free text when awaiting_email_edit is True
                MessageHandler(filters.TEXT & ~filters.COMMAND, _iteration_or_email_edit),
            ],
            WAITING_FOR_EMAIL_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, findemail_input)
            ],
        },
        fallbacks=fallbacks,
        conversation_timeout=600,  # 10 minutes of inactivity ends the session
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('done', done_command))
    app.add_handler(CallbackQueryHandler(email_review_callback, pattern='^email_'))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    app.add_error_handler(error_handler)

    logger.info("🤖 Bot starting with long polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
