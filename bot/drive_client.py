"""
drive_client.py — Uploads files to Google Drive using the Node.js upload_to_drive.js script.

Calls the script via subprocess so we reuse the same auth logic in both
local and Render environments.
"""

import os
import json
import subprocess
import logging
import re

logger = logging.getLogger(__name__)

def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


# Path to upload_to_drive.js relative to this file
_UPLOAD_SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'upload_to_drive.js')


def upload_files(*file_paths: str, folder_name: str = None) -> dict:
    """
    Upload one or more files to Google Drive, optionally inside a named subfolder.

    Returns a dict:
    {
        "files": [
            {"name": "file.pdf", "viewLink": "https://...", "downloadLink": "https://..."},
            {"name": "file.html", "error": "some error message"},
        ],
        "folderLink": "https://drive.google.com/drive/folders/..."  # if folder_name given
    }
    """
    valid_paths = [p for p in file_paths if p and os.path.exists(p)]
    if not valid_paths:
        logger.warning("No valid files to upload.")
        return {"files": []}

    # Build command: optionally prepend --folder <name>
    cmd = ['node', _UPLOAD_SCRIPT]
    if folder_name:
        cmd += ['--folder', folder_name]
    cmd += valid_paths

    logger.info(f"Running Drive upload: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',   # force UTF-8 — Node.js outputs emoji that Windows cp1252 can't decode
            errors='replace',   # replace any undecodable bytes instead of crashing
            timeout=120,
            env={**os.environ}
        )

        if result.returncode != 0:
            logger.error(f"upload_to_drive.js stderr: {result.stderr}")
            raise RuntimeError(f"Drive upload script failed: {result.stderr[:300]}")

        # Parse the JSON output line
        for line in result.stdout.splitlines():
            if line.startswith('\U0001f4e6 UPLOAD_RESULTS_JSON:'):
                json_str = line.replace('\U0001f4e6 UPLOAD_RESULTS_JSON:', '').strip()
                return json.loads(json_str)

        logger.warning("No UPLOAD_RESULTS_JSON line found in script output.")
        logger.debug("Script stdout: " + result.stdout)
        return {"files": []}

    except subprocess.TimeoutExpired:
        logger.error("Drive upload timed out after 120s")
        raise RuntimeError("Google Drive upload timed out. Check your credentials.")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse upload results JSON: {e}")
        return {"files": []}


def upload_files_to_company_folder(company_name: str, *file_paths: str) -> dict:
    """Convenience wrapper — uploads files into a per-company subfolder."""
    return upload_files(*file_paths, folder_name=company_name)


def format_upload_results(result: dict) -> str:
    """Format upload results as a Telegram-friendly message."""
    files = result.get('files', [])
    folder_link = result.get('folderLink')

    if not files and not folder_link:
        return "\u26a0\ufe0f No files were uploaded to Google Drive\\."

    lines = ["\U0001f4c1 *Google Drive Files:*\n"]

    if folder_link:
        folder_link_esc = folder_link.replace('\\', '\\\\').replace(')', '\\)')
        lines.append(f"\U0001f4c2 [Open Company Folder]({folder_link_esc})\n")

    icons = {'.pdf': '\U0001f4c4', '.html': '\U0001f310', '.md': '\U0001f4cb', '.txt': '\U0001f4dd'}

    for r in files:
        ext = os.path.splitext(r.get('name', ''))[1].lower()
        icon = icons.get(ext, '\U0001f4ce')
        
        if 'error' in r:
            name_backticks = r.get('name', '').replace('\\', '\\\\').replace('`', '\\`')
            lines.append(f"{icon} `{name_backticks}` \u2014 \u274c Upload failed: {escape_md(r['error'])}")
        else:
            name_esc = escape_md(r.get('name', ''))
            url_esc = r['viewLink'].replace('\\', '\\\\').replace(')', '\\)')
            lines.append(f"{icon} [{name_esc}]({url_esc})")

    return '\n'.join(lines)
