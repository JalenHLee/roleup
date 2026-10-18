"""Ingest job-alert emails (LinkedIn, Early Career Radar) from one Gmail label.

Reads the label over IMAP with an app password, then has an LLM pull roles out of
each email. Never touches the job sites themselves.

Privacy: this repo (and so its Actions logs) is public. Logs and errors name only
an email's Message-ID and sender domain, never its subject, body, or full address.
"""

import email
import imaplib
import logging
import os
from datetime import date, timedelta
from email import policy
from email.utils import parseaddr, parsedate_to_datetime

from bs4 import BeautifulSoup

from src.config import EMAIL_LOOKBACK_DAYS, GMAIL_LABEL, SENDER_SOURCES
from src.llm_extract import LLM, call_claude, extract_roles
from src.models import Role

log = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
REQUIRED_ENV = ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")
# IMAP dates need English month names regardless of the machine's locale.
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fetch_roles() -> tuple[list[Role], list[str]]:
    """Real run: read the label and extract roles with Claude."""
    return parse_emails(fetch_emails(), call_claude)


def fetch_emails(imap_cls=None, today: date | None = None) -> list[dict]:
    """Return emails from the last EMAIL_LOOKBACK_DAYS in GMAIL_LABEL, as dicts.

    Opens the label read-only and fetches with BODY.PEEK, so emails stay unread.
    Missing credentials, a failed login, or a missing label raise.
    `imap_cls` defaults to imaplib.IMAP4_SSL; tests pass a fake.
    """
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing env vars: {', '.join(missing)}")

    since = (today or date.today()) - timedelta(days=EMAIL_LOOKBACK_DAYS)
    since_str = f"{since.day:02d}-{MONTHS[since.month - 1]}-{since.year}"

    emails = []
    with (imap_cls or imaplib.IMAP4_SSL)(IMAP_HOST) as imap:
        imap.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        status, _ = imap.select(f'"{GMAIL_LABEL}"', readonly=True)
        if status != "OK":
            raise RuntimeError(f"could not open Gmail label {GMAIL_LABEL!r}")

        status, data = imap.search(None, "SINCE", since_str)
        if status != "OK":
            raise RuntimeError("IMAP search failed")
        for num in data[0].split():
            status, msg_data = imap.fetch(num, "(BODY.PEEK[])")
            if status != "OK":
                raise RuntimeError(f"IMAP fetch failed for message {num!r}")
            emails.append(parse_message(msg_data[0][1]))
    return emails


def parse_message(raw: bytes) -> dict:
    """Turn a raw RFC 822 email into {message_id, sender, subject, date, text}.

    Prefers the HTML part (converted to text with links kept inline), else plain text.
    `date` is None if the Date header is missing or unparseable.
    """
    msg = email.message_from_bytes(raw, policy=policy.default)

    body = msg.get_body(preferencelist=("html", "plain"))
    if body is None:
        text = ""
    elif body.get_content_type() == "text/html":
        text = html_to_text(body.get_content())
    else:
        text = body.get_content()

    try:
        sent = parsedate_to_datetime(msg["Date"]).date()
    except (TypeError, ValueError):
        sent = None

    return {
        "message_id": (msg["Message-ID"] or "").strip(),
        "sender": parseaddr(msg["From"] or "")[1].lower(),
        "subject": msg["Subject"] or "",
        "date": sent,
        "text": text,
    }


def html_to_text(html: str) -> str:
    """Convert HTML to plain text, writing each link as "text (url)" so URLs survive."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True)
        a.replace_with(f"{label} ({a['href']})" if label else a["href"])
    lines = (line.strip() for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


def parse_emails(emails: list[dict], llm: LLM) -> tuple[list[Role], list[str]]:
    """Extract roles from each email with `llm`. Returns (roles, errors).

    Pure apart from the injected llm. Unknown senders, undated emails, LLM
    failures, and invalid items are all reported as errors, never dropped silently.
    """
    roles: list[Role] = []
    errors: list[str] = []

    for msg in emails:
        domain = _domain(msg.get("sender", ""))
        ref = f"email {msg.get('message_id') or '?'} from {domain or '?'}"

        source = source_for_domain(domain)
        if source is None:
            errors.append(f"{ref}: unknown sender domain")
            continue
        if msg.get("date") is None:
            errors.append(f"{ref}: missing or bad Date header")
            continue

        try:
            found, item_errors = extract_roles(msg["text"], source, msg["date"], llm)
        except Exception as e:  # any LLM/API failure is reported for this email only
            found, item_errors = [], [f"LLM call failed: {type(e).__name__}: {e}"]

        roles.extend(found)
        for err in item_errors:
            log.warning("Failed to parse %s: %s", ref, err)
            errors.append(f"{ref}: {err}")

    return roles, errors


def source_for_domain(domain: str) -> str | None:
    """Map a sender domain to a source name; subdomains match (e.linkedin.com)."""
    for known, source in SENDER_SOURCES.items():
        if domain == known or domain.endswith("." + known):
            return source
    return None


def _domain(address: str) -> str:
    return address.rpartition("@")[2].lower()
