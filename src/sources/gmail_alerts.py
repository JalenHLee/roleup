"""Ingest job-alert emails (LinkedIn, Early Career Radar) from one Gmail label.

Reads the label over IMAP with an app password, then has an LLM pull roles out of
each email. Never touches the job sites themselves.

Privacy: this repo (and so its Actions logs) is public. Logs, errors and the
per-email report name an email only by its sender domain and a short hash of its
Message-ID, never its Message-ID, subject, body, or full address.
"""

import email
import hashlib
import imaplib
import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from email import policy
from email.utils import parseaddr, parsedate_to_datetime

from bs4 import BeautifulSoup

from src.config import EMAIL_LOOKBACK_DAYS, GMAIL_LABEL, SENDER_SOURCES
from src.llm_extract import LLM, extract_roles
from src.models import Role

log = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
REQUIRED_ENV = ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")
# IMAP dates need English month names regardless of the machine's locale.
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass
class EmailResult:
    """One line of the per-email report. Safe to print: no identifying content."""

    domain: str  # sender domain, e.g. "linkedin.com"
    short_id: str  # short hash of the Message-ID
    source: str | None  # e.g. "linkedin"; None for an unknown sender
    roles: int  # valid roles extracted (before the role filter)
    errors: int
    # (before, after) titles where the company-suffix guard fired. Job titles only.
    title_fixes: list[tuple[str, str]] = field(default_factory=list)


def short_id(message_id: str) -> str:
    """First 8 hex chars of sha256(Message-ID): stable across runs, not reversible."""
    return hashlib.sha256(message_id.encode()).hexdigest()[:8] if message_id else "????????"


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


def parse_emails(
    emails: list[dict], llm: LLM
) -> tuple[list[Role], list[str], list[EmailResult]]:
    """Extract roles from each email with `llm`. Returns (roles, errors, report).

    Pure apart from the injected llm. Unknown senders, undated emails, LLM
    failures, and invalid items are all reported as errors, never dropped silently.
    `report` has one EmailResult per email.
    """
    roles: list[Role] = []
    errors: list[str] = []
    report: list[EmailResult] = []

    for msg in emails:
        domain = _domain(msg.get("sender", "")) or "?"
        sid = short_id(msg.get("message_id", ""))
        ref = f"email #{sid} from {domain}"
        source = source_for_domain(domain)

        fixes: list[tuple[str, str]] = []
        if source is None:
            found, email_errors = [], ["unknown sender domain"]
        elif msg.get("date") is None:
            found, email_errors = [], ["missing or bad Date header"]
        else:
            try:
                found, email_errors, fixes = extract_roles(msg["text"], source, msg["date"], llm)
            except Exception as e:  # any LLM/API failure is reported for this email only
                found, email_errors = [], [f"LLM call failed: {type(e).__name__}: {e}"]

        roles.extend(found)
        for err in email_errors:
            log.warning("Failed to parse %s: %s", ref, err)
            errors.append(f"{ref}: {err}")
        report.append(EmailResult(domain, sid, source, len(found), len(email_errors), fixes))

    return roles, errors, report


def source_for_domain(domain: str) -> str | None:
    """Map a sender domain to a source name; subdomains match (e.linkedin.com)."""
    for known, source in SENDER_SOURCES.items():
        if domain == known or domain.endswith("." + known):
            return source
    return None


def _domain(address: str) -> str:
    return address.rpartition("@")[2].lower()
