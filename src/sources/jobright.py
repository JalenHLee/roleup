"""Ingest Jobright's PM internship list by parsing its README markdown table."""

import logging
import re
from datetime import date, datetime

import requests

from src.config import (
    JOBRIGHT_OFF_CYCLE_PATTERNS,
    JOBRIGHT_README_URL,
    JOBRIGHT_TARGET_TERM_PATTERNS,
)
from src.models import Role

log = logging.getLogger(__name__)

# The table header we expect. If Jobright changes it, parsing fails loudly.
HEADER_PREFIX = "| Company | Job Title |"
EXPECTED_COLUMNS = 5  # Company, Job Title, Location, Work Model, Date Posted
SAME_COMPANY = "↳"
LINK_RE = re.compile(r"^\[(.+?)\]\((\S+?)\)$")


def fetch_roles(today: date | None = None) -> tuple[list[Role], list[str]]:
    """Download Jobright's README and return (roles, parse_errors).

    Network failures and a missing table raise: an empty list would look like "no new roles".
    """
    resp = requests.get(JOBRIGHT_README_URL, timeout=30)
    resp.raise_for_status()
    return parse_readme(resp.text, today or date.today())


def parse_readme(text: str, today: date) -> tuple[list[Role], list[str]]:
    """Turn Jobright README text into Roles.

    `today` anchors the year for dates like "Sep 23". Off-cycle titles
    (Fall 2026, Winter, Spring, Co-op) are skipped. Malformed rows are logged
    and returned as errors, never dropped silently.
    Raises ValueError if the job table is not found.
    """
    lines = text.splitlines()
    try:
        header_idx = next(i for i, line in enumerate(lines) if line.startswith(HEADER_PREFIX))
    except StopIteration:
        raise ValueError("Jobright README: job table header not found") from None

    roles: list[Role] = []
    errors: list[str] = []
    company = None  # last real company name, for "↳" rows

    # Skip the header and the "| --- |" separator; the table ends at the first non-row line.
    for line_no, line in enumerate(lines[header_idx + 2:], start=header_idx + 3):
        if not line.startswith("|"):
            break
        try:
            cells = _split_row(line)
            company_cell, title_cell, location, _work_model, posted = cells

            if company_cell == SAME_COMPANY:
                if company is None:
                    raise ValueError("'↳' row with no company above it")
            else:
                company = _link_text(company_cell)

            title, link = _parse_title(title_cell)
            term = _infer_term(title)
            if term is None:
                continue  # off-cycle internship

            roles.append(Role(
                company=company,
                title=title,
                location=location,
                link=link,
                sources=["jobright"],
                date_posted=_infer_date(posted, today),
                term=term,
                links=[link],
            ))
        except ValueError as e:
            msg = f"jobright README line {line_no}: {e}"
            log.warning("Failed to parse %s", msg)
            errors.append(msg)

    return roles, errors


def _split_row(line: str) -> list[str]:
    """Split a markdown table row into stripped cells with bold markers removed."""
    cells = [c.strip().replace("**", "").strip() for c in line.strip().strip("|").split("|")]
    if len(cells) != EXPECTED_COLUMNS:
        raise ValueError(f"expected {EXPECTED_COLUMNS} columns, got {len(cells)}")
    return cells


def _link_text(cell: str) -> str:
    """Return the text of a markdown link, or the cell itself if it's plain text."""
    m = LINK_RE.match(cell)
    text = m.group(1) if m else cell
    if not text:
        raise ValueError("empty company")
    return text


def _parse_title(cell: str) -> tuple[str, str]:
    """Return (title, url) from a title cell, which must be a markdown link."""
    m = LINK_RE.match(cell)
    if not m:
        raise ValueError(f"title is not a link: {cell!r}")
    return m.group(1).strip(), m.group(2)


def _infer_term(title: str) -> str | None:
    """Return "Summer 2027", "unknown", or None for an off-cycle role to drop."""
    t = title.lower()
    if any(re.search(p, t) for p in JOBRIGHT_TARGET_TERM_PATTERNS):
        return "Summer 2027"
    if any(re.search(p, t) for p in JOBRIGHT_OFF_CYCLE_PATTERNS):
        return None
    return "unknown"


def _infer_date(text: str, today: date) -> date:
    """Turn "Sep 23" into the most recent such date on or before `today`."""
    try:
        # Parse with the year included so "Feb 29" works in leap years.
        posted = datetime.strptime(f"{text} {today.year}", "%b %d %Y").date()
    except ValueError:
        posted = None
    if posted is None or posted > today:
        try:
            posted = datetime.strptime(f"{text} {today.year - 1}", "%b %d %Y").date()
        except ValueError:
            raise ValueError(f"unparseable date: {text!r}") from None
    return posted
