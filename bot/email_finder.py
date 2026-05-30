"""
email_finder.py — 5-layer waterfall email finder for job poster / recruiter contacts.

Layer 1: Tomba.io    — LinkedIn URL → verified email (primary)
Layer 2: Snov.io     — LinkedIn URL → email (secondary, different DB)
Layer 3: Hunter.io   — Name + domain → specific person email
Layer 4: Hunter.io   — Domain-wide recruiter search
Layer 5: Pattern Guess + ZeroBounce SMTP verification (zero-cost fallback)

All layers are credit-conserving: only move to the next layer on failure.
"""

import os
import re
import time
import logging
import asyncio
from urllib.parse import urlparse
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

LOG_FILE = Path(__file__).parent.parent / "email_finder.log"

# ─── API Keys ────────────────────────────────────────────────────────────────
TOMBA_API_KEY    = os.environ.get("TOMBA_API_KEY", "")
TOMBA_API_SECRET = os.environ.get("TOMBA_API_SECRET", "")
SNOV_CLIENT_ID   = os.environ.get("SNOV_CLIENT_ID", "")
SNOV_CLIENT_SECRET = os.environ.get("SNOV_CLIENT_SECRET", "")
HUNTER_API_KEY   = os.environ.get("HUNTER_API_KEY", "")
ZEROBOUNCE_KEY   = os.environ.get("ZEROBOUNCE_KEY", "")
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")  # for domain inference


# ─── Logging helper ──────────────────────────────────────────────────────────
def _log(msg: str, level: str = "INFO"):
    import datetime
    ts = datetime.datetime.now().isoformat()
    line = f"[{ts}] [{level}] {msg}"
    logger.info(msg) if level == "INFO" else logger.warning(msg)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ─── Domain Extraction ───────────────────────────────────────────────────────
def _clean_domain(raw: str) -> str:
    """Strip protocol, www, and path from a URL to get bare domain."""
    raw = raw.strip().lower()
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    domain = parsed.netloc or parsed.path
    domain = re.sub(r"^www\.", "", domain)
    domain = domain.split("/")[0].split("?")[0]
    return domain


_SKIP_DOMAINS = {
    "linkedin.com", "indeed.com", "glassdoor.com", "google.com",
    "twitter.com", "facebook.com", "instagram.com", "youtube.com",
    "naukri.com", "wellfound.com", "angel.co",
}


def _gemini_infer_domain(company_name: str) -> str | None:
    """
    Ask Gemini to infer the official website domain from a company name.
    Uses a cheap single-turn generate_content call (no chat session needed).
    Returns a bare domain like 'company.com' or None on failure.
    """
    if not GEMINI_API_KEY:
        return None
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            f"What is the official website domain of the company '{company_name}'? "
            "Reply with ONLY the bare domain (e.g. 'stripe.com') and nothing else. "
            "If you are not sure, reply with 'unknown'."
        )
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
        )
        raw = (response.text or "").strip().lower()
        if raw and raw != "unknown" and "." in raw and len(raw) < 60:
            return _clean_domain(raw)
    except Exception as e:
        _log(f"Gemini domain inference failed: {e}", "WARNING")
    return None


def extract_company_domain(company_name: str, jd_text: str = "") -> str | None:
    """
    Extract the company's domain using a 3-step approach:
    1. Find any company-looking URL embedded in the JD text
    2. Ask Gemini to infer it from the company name
    3. Return None → bot will prompt the user
    """
    # Step 1: scan JD text for URLs that aren't job boards
    urls = re.findall(r'https?://(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', jd_text)
    for raw_url in urls:
        domain = _clean_domain(raw_url)
        if domain and not any(skip in domain for skip in _SKIP_DOMAINS):
            _log(f"Domain extracted from JD text: {domain}")
            return domain

    # Step 2: Gemini inference
    domain = _gemini_infer_domain(company_name)
    if domain:
        _log(f"Domain inferred by Gemini: {domain}")
        return domain

    _log(f"Could not extract domain for '{company_name}'", "WARNING")
    return None


# ─── Layer 1: Tomba.io ───────────────────────────────────────────────────────
def find_by_linkedin_tomba(linkedin_url: str) -> dict | None:
    """
    Layer 1: LinkedIn URL → verified email via Tomba.io.
    Pay-only-for-results: no credit consumed on a miss.
    """
    if not (TOMBA_API_KEY and TOMBA_API_SECRET):
        _log("Tomba.io: API key or secret not set — skipping Layer 1", "WARNING")
        return None
    try:
        resp = requests.get(
            "https://api.tomba.io/v1/linkedin",
            params={"url": linkedin_url},
            headers={
                "X-Tomba-Key": TOMBA_API_KEY,
                "X-Tomba-Secret": TOMBA_API_SECRET,
                "Content-Type": "application/json"
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            email = data.get("email", "")
            if email:
                result = {
                    "email": email,
                    "name": f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(),
                    "title": data.get("position", ""),
                    "company": data.get("company", ""),
                    "source": "Tomba.io (LinkedIn match)",
                    "confidence": "high",
                    "verified": True,
                }
                _log(f"Tomba.io hit: {email}")
                return result
            _log("Tomba.io: no email returned for this LinkedIn URL")
        elif resp.status_code in (401, 403):
            _log(f"Tomba.io: HTTP {resp.status_code} — out of credits or invalid key", "WARNING")
        elif resp.status_code == 429:
            _log("Tomba.io: rate-limited — skipping", "WARNING")
        else:
            _log(f"Tomba.io: unexpected HTTP {resp.status_code}", "WARNING")
    except requests.RequestException as e:
        _log(f"Tomba.io request error: {e}", "WARNING")
    return None


# ─── Layer 2: Snov.io ────────────────────────────────────────────────────────
def _snov_get_token() -> str | None:
    """Obtain OAuth access token for Snov.io API."""
    try:
        resp = requests.post(
            "https://api.snov.io/v1/oauth/access_token",
            data={
                "grant_type": "client_credentials",
                "client_id": SNOV_CLIENT_ID,
                "client_secret": SNOV_CLIENT_SECRET,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
        _log(f"Snov.io token error: HTTP {resp.status_code}", "WARNING")
    except requests.RequestException as e:
        _log(f"Snov.io token request failed: {e}", "WARNING")
    return None


def find_by_linkedin_snov(linkedin_url: str) -> dict | None:
    """
    Layer 2: LinkedIn URL → email via Snov.io (async-poll API).
    Separate credit pool from Tomba — increases combined hit rate.
    """
    if not (SNOV_CLIENT_ID and SNOV_CLIENT_SECRET):
        _log("Snov.io: credentials not set — skipping Layer 2", "WARNING")
        return None

    token = _snov_get_token()
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Submit LinkedIn URL for enrichment
        start_resp = requests.post(
            "https://api.snov.io/v2/li-profiles-by-urls/start",
            json={"urls": [linkedin_url]},
            headers=headers,
            timeout=10,
        )
        if start_resp.status_code != 200:
            _log(f"Snov.io start failed: HTTP {start_resp.status_code}", "WARNING")
            return None

        hash_id = start_resp.json().get("hash")
        if not hash_id:
            _log("Snov.io: no hash returned from start request", "WARNING")
            return None

        # Poll for results up to 4 times (2s apart = max 8s wait)
        for attempt in range(4):
            time.sleep(2)
            result_resp = requests.get(
                "https://api.snov.io/v2/li-profiles-by-urls/results",
                params={"hash": hash_id},
                headers=headers,
                timeout=10,
            )
            if result_resp.status_code == 200:
                profiles = result_resp.json().get("data", [])
                if profiles and profiles[0].get("emails"):
                    p = profiles[0]
                    email = p["emails"][0]["email"]
                    result = {
                        "email": email,
                        "name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                        "title": p.get("position", ""),
                        "company": p.get("currentCompanyName", ""),
                        "source": "Snov.io (LinkedIn enrichment)",
                        "confidence": "high",
                        "verified": True,
                    }
                    _log(f"Snov.io hit: {email} (attempt {attempt + 1})")
                    return result
            _log(f"Snov.io poll attempt {attempt + 1}: not ready yet")

        _log("Snov.io: polling exhausted — no result")
    except requests.RequestException as e:
        _log(f"Snov.io request error: {e}", "WARNING")
    return None


# ─── Layer 3: Hunter.io — Name + Domain ──────────────────────────────────────
def find_by_name_domain(first: str, last: str, domain: str) -> dict | None:
    """
    Layer 3: Name + domain → specific person email via Hunter.io Email Finder.
    Uses the unified 50 credits/month pool.
    """
    if not HUNTER_API_KEY:
        _log("Hunter.io: API key not set — skipping Layer 3", "WARNING")
        return None
    if not (first and last and domain):
        _log("Hunter.io Layer 3: missing name or domain — skipping")
        return None
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/email-finder",
            params={
                "first_name": first,
                "last_name": last,
                "domain": domain,
                "api_key": HUNTER_API_KEY,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            email = data.get("email", "")
            score = data.get("score", 0)
            if email:
                result = {
                    "email": email,
                    "name": f"{first} {last}".strip(),
                    "title": data.get("position", ""),
                    "company": domain,
                    "source": "Hunter.io (name + domain)",
                    "confidence": score,
                    "verified": score >= 80,
                }
                _log(f"Hunter.io Layer 3 hit: {email} (score={score})")
                return result
            _log("Hunter.io Layer 3: no email found for this name+domain")
        elif resp.status_code in (401, 403):
            _log(f"Hunter.io: HTTP {resp.status_code} — invalid key or 0 credits", "WARNING")
        else:
            _log(f"Hunter.io Layer 3: HTTP {resp.status_code}", "WARNING")
    except requests.RequestException as e:
        _log(f"Hunter.io Layer 3 request error: {e}", "WARNING")
    return None


# ─── Layer 4: Hunter.io — Domain Recruiter Search ────────────────────────────
_RECRUITER_KW = {"recruit", "talent", "hr", "people", "hiring", "acquisition", "workforce"}


def find_recruiters_by_domain(domain: str) -> list[dict]:
    """
    Layer 4: Domain-wide search for HR/recruiter emails via Hunter.io.
    Uses same 50-credit monthly pool as Layer 3.
    Returns up to 3 best results, preferring recruiter-titled contacts.
    """
    if not HUNTER_API_KEY:
        _log("Hunter.io: API key not set — skipping Layer 4", "WARNING")
        return []
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={
                "domain": domain,
                "limit": 10,
                "api_key": HUNTER_API_KEY,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            _log(f"Hunter.io Layer 4: HTTP {resp.status_code}", "WARNING")
            return []

        emails = resp.json().get("data", {}).get("emails", [])
        if not emails:
            _log("Hunter.io Layer 4: no emails in domain search result")
            return []

        # Strictly filter for recruiter/HR titles; NO fallback to generic contacts
        recruiter_hits = [
            e for e in emails
            if any(kw in e.get("position", "").lower() for kw in _RECRUITER_KW)
        ]
        
        if not recruiter_hits:
            _log("Hunter.io Layer 4: no recruiter/HR contacts found in top results. Stopping to prevent mailing founders.")
            return []

        final_list = recruiter_hits[:3]

        results = []
        for e in final_list:
            email = e.get("value", "")
            if not email:
                continue
            confidence = e.get("confidence", 0)
            results.append({
                "email": email,
                "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                "title": e.get("position", "HR Department"),
                "company": domain,
                "source": "Hunter.io (domain search)",
                "confidence": confidence,
                "verified": confidence >= 80,
            })
        _log(f"Hunter.io Layer 4: found {len(results)} contacts for {domain}")
        return results
    except requests.RequestException as e:
        _log(f"Hunter.io Layer 4 request error: {e}", "WARNING")
    return []


# ─── Layer 5: Pattern Guess + ZeroBounce ─────────────────────────────────────
def _get_company_email_pattern(domain: str) -> str | None:
    """
    Fetch Hunter.io domain metadata to get the company's dominant email pattern.
    This is free metadata — does not consume search credits.
    Example return: '{first}.{last}'
    """
    if not HUNTER_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "limit": 1, "api_key": HUNTER_API_KEY},
            timeout=10,
        )
        if resp.status_code == 200:
            pattern = resp.json().get("data", {}).get("pattern")
            if pattern:
                _log(f"Company email pattern for {domain}: {pattern}")
            return pattern
    except requests.RequestException:
        pass
    return None


def _generate_email_patterns(first: str, last: str, domain: str,
                              known_pattern: str | None = None) -> list[str]:
    """
    Generate a ranked list of email pattern candidates.
    If the company's known pattern is provided, it is tried first.
    """
    f, l = first.lower(), last.lower()
    fi = f[0] if f else ""

    # All known corporate patterns ranked by global frequency
    all_patterns = [
        f"{f}.{l}@{domain}",    # john.doe     — most common globally
        f"{fi}{l}@{domain}",    # jdoe
        f"{f}{l}@{domain}",     # johndoe
        f"{f}@{domain}",        # john
        f"{fi}.{l}@{domain}",   # j.doe
        f"{f}_{l}@{domain}",    # john_doe
        f"{l}@{domain}",        # doe
        f"{l}{f}@{domain}",     # doejohn
        f"{l}.{f}@{domain}",    # doe.john
        f"{f}{l[0]}@{domain}" if l else "",  # johnd
    ]
    all_patterns = [p for p in all_patterns if p]  # remove empty strings

    if known_pattern:
        # Build the email from the known pattern format and move to front
        patterned = (
            known_pattern
            .replace("{first}", f)
            .replace("{last}", l)
            .replace("{f.last}", f"{fi}.{l}")
            .replace("{flast}", f"{fi}{l}")
        )
        if "@" not in patterned:
            patterned = f"{patterned}@{domain}"
        if patterned in all_patterns:
            all_patterns.remove(patterned)
        all_patterns.insert(0, patterned)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for p in all_patterns:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _verify_email_zerobounce(email: str) -> tuple[bool, str]:
    """
    Verify an email address via ZeroBounce SMTP probe.
    Returns (is_usable, status) where status is:
      'valid'     → confirmed deliverable ✅
      'catch-all' → server accepts all mail ⚠️ (usable but uncertain)
      'invalid'   → hard bounce — skip ❌
      'unknown'   → could not determine
      'error'     → API failure
    Consumes 1 ZeroBounce credit per call.
    """
    if not ZEROBOUNCE_KEY:
        _log("ZeroBounce: API key not set — skipping SMTP verification", "WARNING")
        return False, "error"
    try:
        resp = requests.get(
            "https://api.zerobounce.net/v2/validate",
            params={"api_key": ZEROBOUNCE_KEY, "email": email, "ip_address": ""},
            timeout=15,
        )
        if resp.status_code != 200:
            _log(f"ZeroBounce: HTTP {resp.status_code} for {email}", "WARNING")
            return False, "error"
        status = resp.json().get("status", "unknown")
        is_usable = status in ("valid", "catch-all")
        _log(f"ZeroBounce: {email} → {status}")
        return is_usable, status
    except requests.RequestException as e:
        _log(f"ZeroBounce request error: {e}", "WARNING")
        return False, "error"


def find_by_pattern_guess(first: str, last: str, domain: str) -> list[dict]:
    """
    Layer 5: Generate email patterns and optionally verify via ZeroBounce.

    If ZEROBOUNCE_KEY is set:   verifies each pattern via SMTP, stops on first
                                'valid' hit to conserve monthly credits.
    If ZEROBOUNCE_KEY is empty: returns the top 3 ranked patterns unverified
                                with a clear ⚠️ label — user can manually check.
    """
    if not (first and last and domain):
        _log("Pattern guesser: missing first/last/domain — skipping Layer 5")
        return []

    known_pattern = _get_company_email_pattern(domain)
    candidates = _generate_email_patterns(first, last, domain, known_pattern)

    # ── ZeroBounce disabled: return top 3 patterns unverified ────────────────
    if not ZEROBOUNCE_KEY:
        _log("ZeroBounce disabled — returning top 3 pattern guesses unverified")
        results = []
        for email in candidates[:3]:
            results.append({
                "email": email,
                "name": f"{first} {last}",
                "title": "Unknown",
                "company": domain,
                "source": "Pattern Guess (unverified)",
                "confidence": "low",
                "verified": False,
                "smtp_status": "unverified",
            })
        return results

    # ── ZeroBounce enabled: verify each pattern via SMTP ─────────────────────
    results = []
    for email in candidates:
        usable, status = _verify_email_zerobounce(email)
        if usable:
            results.append({
                "email": email,
                "name": f"{first} {last}",
                "title": "Unknown",
                "company": domain,
                "source": "Pattern Guess + ZeroBounce SMTP",
                "confidence": "high" if status == "valid" else "medium",
                "verified": status == "valid",
                "smtp_status": status,
            })
            if status == "valid":
                break  # Confirmed hit — stop to conserve ZeroBounce credits

    return results


# ─── Orchestrator ─────────────────────────────────────────────────────────────
def find_emails(
    company_name: str,
    jd_text: str = "",
    linkedin_url: str | None = None,
    person_name: str | None = None,
    company_domain: str | None = None,
) -> dict:
    """
    Main waterfall orchestrator.

    Args:
        company_name:   Company name from JD (e.g. "Stripe")
        jd_text:        Full JD text (used for domain extraction)
        linkedin_url:   LinkedIn profile URL of the job poster (optional)
        person_name:    Full name of the poster e.g. "John Doe" (optional)
        company_domain: Pre-resolved domain (optional; skips extraction)

    Returns:
        {
          "emails": [list of email dicts],
          "domain": "company.com" | None,
          "domain_missing": True/False,
          "layers_tried": ["Layer 1", ...],
        }
    """
    _log(f"Email finder started — company='{company_name}' linkedin='{linkedin_url}' name='{person_name}'")
    results: list[dict] = []
    layers_tried: list[str] = []

    # Parse name parts
    first, last = "", ""
    if person_name:
        parts = person_name.strip().split()
        first = parts[0] if parts else ""
        last = parts[-1] if len(parts) > 1 else ""

    # ── Layer 1: Tomba.io LinkedIn ────────────────────────────────────────────
    if linkedin_url:
        layers_tried.append("Layer 1 (Tomba.io)")
        hit = find_by_linkedin_tomba(linkedin_url)
        if hit:
            _log("Waterfall stopping at Layer 1 — high-confidence hit")
            return {"emails": [hit], "domain": company_domain, "domain_missing": False, "layers_tried": layers_tried}

    # ── Layer 2: Snov.io LinkedIn ─────────────────────────────────────────────
    if linkedin_url:
        layers_tried.append("Layer 2 (Snov.io)")
        hit = find_by_linkedin_snov(linkedin_url)
        if hit:
            _log("Waterfall stopping at Layer 2 — high-confidence hit")
            return {"emails": [hit], "domain": company_domain, "domain_missing": False, "layers_tried": layers_tried}

    # ── Domain resolution (needed for Layers 3–5) ─────────────────────────────
    domain = company_domain or extract_company_domain(company_name, jd_text)
    if not domain:
        _log("Domain could not be resolved — cannot continue to Layers 3–5", "WARNING")
        return {"emails": [], "domain": None, "domain_missing": True, "layers_tried": layers_tried}

    # ── Layer 3: Hunter.io name + domain ──────────────────────────────────────
    if first and last:
        layers_tried.append("Layer 3 (Hunter.io name+domain)")
        hit = find_by_name_domain(first, last, domain)
        if hit:
            results.append(hit)

    # ── Layer 4: Hunter.io domain recruiter search ────────────────────────────
    if not results:
        layers_tried.append("Layer 4 (Hunter.io domain search)")
        hits = find_recruiters_by_domain(domain)
        results.extend(hits)

    # ── Layer 5: Pattern guess (+ ZeroBounce if configured) ──────────────────
    if not results and first and last:
        label = "Layer 5 (Pattern Guess)" if not ZEROBOUNCE_KEY else "Layer 5 (Pattern + ZeroBounce)"
        layers_tried.append(label)
        hits = find_by_pattern_guess(first, last, domain)
        results.extend(hits)

    _log(f"Waterfall complete — {len(results)} email(s) found via {layers_tried}")
    return {
        "emails": results,
        "domain": domain,
        "domain_missing": False,
        "layers_tried": layers_tried,
    }


# ─── Async wrapper (for use in bot.py async handlers) ────────────────────────
import analytics_logger

async def find_emails_async(
    company_name: str,
    jd_text: str = "",
    linkedin_url: str | None = None,
    person_name: str | None = None,
    company_domain: str | None = None,
    session_id = None,
) -> dict:
    """
    Async wrapper around find_emails() so it can be awaited from bot handlers
    without blocking the event loop.
    """
    result = await asyncio.to_thread(
        find_emails,
        company_name=company_name,
        jd_text=jd_text,
        linkedin_url=linkedin_url,
        person_name=person_name,
        company_domain=company_domain,
    )
    if session_id:
        domain = result.get('domain', '') or ''
        layers_tried = result.get('layers_tried', [])
        successful_layer = layers_tried[-1] if result.get('emails') and layers_tried else ''
        emails_found = [e.get('email') for e in result.get('emails', [])]
        credits_used = {}
        await analytics_logger.log_email_search(
            session_id=session_id,
            domain=domain,
            layers_tried=layers_tried,
            successful_layer=successful_layer or '',
            emails_found=emails_found,
            credits_used=credits_used
        )
    return result


# ─── Formatting helper (shared by bot.py and standalone use) ─────────────────
def format_email_results(results: list[dict], company_name: str) -> str:
    """
    Format the email results list into a Telegram-ready plain text block
    (no MarkdownV2 — caller should escape as needed).
    """
    if not results:
        return f"❌ No emails found for {company_name}.\nTry checking LinkedIn manually."

    lines = [f"📧 Emails found for {company_name}:\n"]
    for i, r in enumerate(results, 1):
        verified_icon = "✅" if r.get("verified") else "⚠️"
        confidence = r.get("confidence", "?")
        conf_str = f"{confidence}%" if isinstance(confidence, int) else str(confidence).capitalize()
        smtp = r.get("smtp_status", "")
        smtp_str = f" | SMTP: {smtp}" if smtp else ""

        lines.append(f"{i}. {r['email']}")
        if r.get("name"):
            lines.append(f"   👤 {r['name']}" + (f" — {r['title']}" if r.get("title") else ""))
        lines.append(f"   🔍 {r['source']}")
        lines.append(f"   {verified_icon} Confidence: {conf_str}{smtp_str}")
        lines.append("")

    return "\n".join(lines).rstrip()
