"""
email_sender.py — Gmail API sender for cold outreach emails.

Reuses the existing token.json / credentials.json OAuth setup already
configured for Google Drive — no new OAuth flow needed.

Phase 2 feature: email sending is optional. The bot always shows the draft
first and only sends after explicit /sendemail confirmation.
"""

import os
import base64
import logging
import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ─── Paths (same pattern as drive_client.py) ────────────────────────────────
_BOT_DIR = Path(__file__).parent
_REPO_ROOT = _BOT_DIR.parent
TOKEN_FILE = _REPO_ROOT / "token.json"
CREDENTIALS_FILE = _REPO_ROOT / "credentials.json"

# Gmail send scope — must be present in token.json
_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _build_gmail_service():
    """
    Build and return an authenticated Gmail API service client.
    Reuses token.json. Raises RuntimeError if credentials are missing
    or the token doesn't include the gmail.send scope.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError(
            f"google-api-python-client not installed: {e}\n"
            "Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )

    if not TOKEN_FILE.exists():
        raise RuntimeError(
            f"token.json not found at {TOKEN_FILE}. "
            "Run the OAuth setup (node upload_to_drive.js --setup) first."
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), _GMAIL_SCOPES)

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Persist refreshed token
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            logger.info("email_sender: token refreshed")
        except Exception as e:
            raise RuntimeError(f"Failed to refresh Gmail OAuth token: {e}")

    if not creds or not creds.valid:
        raise RuntimeError(
            "Gmail OAuth token is invalid or missing 'gmail.send' scope. "
            "Re-run OAuth setup to include Gmail permissions."
        )

    return build("gmail", "v1", credentials=creds)


def _build_mime_message(
    to: str,
    subject: str,
    body: str,
    attachment_path: str | None = None,
    sender_display: str = "Purvesh Gandhi",
) -> MIMEMultipart:
    """
    Construct the MIME email message.
    Optionally attaches a PDF resume file.
    """
    msg = MIMEMultipart()
    msg["to"] = to
    msg["subject"] = subject
    msg["from"] = sender_display  # Display name (Gmail uses authenticated account)

    msg.attach(MIMEText(body, "plain", "utf-8"))

    if attachment_path:
        attachment_path = Path(attachment_path)
        if attachment_path.exists():
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{attachment_path.name}"',
            )
            msg.attach(part)
            logger.info(f"email_sender: attached {attachment_path.name}")
        else:
            logger.warning(f"email_sender: attachment not found — {attachment_path}")

    return msg


def send_cold_email(
    to: str,
    subject: str,
    body: str,
    attachment_path: str | None = None,
) -> dict:
    """
    Send a cold email via Gmail API.

    Args:
        to:              Recipient email address
        subject:         Email subject line
        body:            Plain text email body
        attachment_path: Optional path to PDF resume file

    Returns:
        {"success": True, "message_id": "...", "error": None}
        or
        {"success": False, "message_id": None, "error": "<reason>"}
    """
    try:
        service = _build_gmail_service()
        mime_msg = _build_mime_message(to, subject, body, attachment_path)
        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
        result = service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()
        message_id = result.get("id", "unknown")
        logger.info(f"email_sender: sent to {to} — Gmail message ID: {message_id}")
        return {"success": True, "message_id": message_id, "error": None}
    except RuntimeError as e:
        logger.error(f"email_sender: config error — {e}")
        return {"success": False, "message_id": None, "error": str(e)}
    except Exception as e:
        logger.error(f"email_sender: send failed — {e}")
        return {"success": False, "message_id": None, "error": str(e)}


async def send_cold_email_async(
    to: str,
    subject: str,
    body: str,
    attachment_path: str | None = None,
) -> dict:
    """Async wrapper for send_cold_email() — safe to await in bot handlers."""
    return await asyncio.to_thread(
        send_cold_email,
        to=to,
        subject=subject,
        body=body,
        attachment_path=attachment_path,
    )


def is_gmail_configured() -> bool:
    """
    Quick check: does a valid token.json exist that could support Gmail sending?
    Used by the bot's /status command and to show/hide the Send button.
    """
    return TOKEN_FILE.exists()
