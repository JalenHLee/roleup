"""Merge the same role found in several sources into one Role.

role_id = normalized company + normalized title. Location is NOT part of it:
same company + title is one application, and sources format locations differently.
Word lists live in src/config.py.
"""

import re

from src.config import (
    COMPANY_ALIASES,
    ROLE_ID_COMPANY_SUFFIXES,
    ROLE_ID_INTERN_WORDS,
    ROLE_ID_TERM_PHRASES,
    ROLE_ID_TITLE_NOISE,
    US_STATES,
)
from src.links import canonicalize
from src.models import Role

PREFERRED_LINK_SOURCE = "simplify"  # Jobright links go through jobright.ai
LOCATION_SEP = "; "
# A trailing " - City, ST" / " - City, State" (hyphen or en/em dash) on a title.
TITLE_LOCATION_SUFFIX_RE = re.compile(r"\s+[-–—]\s+[^-–—,]+,\s*([A-Za-z .]+?)\s*$")
_STATE_NAMES = {name.lower() for name in US_STATES.values()}
# A trailing " - X" suffix (hyphen or en/em dash), X without further dashes.
TITLE_DASH_SUFFIX_RE = re.compile(r"\s+[-–—]\s+([^-–—]+?)\s*$")


def _remove_words(text: str, phrases: list[str]) -> str:
    for phrase in phrases:
        text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text)
    return text


def _clean(text: str) -> str:
    """Lowercase and turn punctuation (incl. "–", "（）", ".") into spaces."""
    return re.sub(r"[^\w\s]|_", " ", text.lower())


def _collapse(text: str) -> str:
    return " ".join(text.split())


def normalize_company(company: str) -> str:
    name = _collapse(_remove_words(_clean(company), ROLE_ID_COMPANY_SUFFIXES))
    return COMPANY_ALIASES.get(name, name)


def strip_title_location(title: str) -> str:
    """Drop a trailing " - Franklin, TN" style suffix, only for a real US state.

    So "Product Intern - Payments, Risk" is left alone.
    """
    m = TITLE_LOCATION_SUFFIX_RE.search(title)
    if m and (m.group(1).upper() in US_STATES or m.group(1).lower() in _STATE_NAMES):
        return title[:m.start()]
    return title


def strip_redundant_suffix(title: str) -> str:
    """Drop a trailing " - X" when every word of X already appears earlier in the title.

    "Product Operations Intern - Product Operations" -> "Product Operations Intern";
    "Product Intern - Payments" is left alone.
    """
    m = TITLE_DASH_SUFFIX_RE.search(title)
    if not m:
        return title
    head = title[:m.start()]
    suffix_words = set(_clean(m.group(1)).split())
    if suffix_words and suffix_words <= set(_clean(head).split()):
        return head
    return title


def normalize_title(title: str) -> str:
    text = _clean(strip_redundant_suffix(strip_title_location(title)))
    text = _remove_words(text, ROLE_ID_TERM_PHRASES)
    text = re.sub(r"\b20\d\d\b", " ", text)  # bare years, e.g. "Intern 2027"
    text = _remove_words(text, ROLE_ID_INTERN_WORDS)
    text = _remove_words(text, ROLE_ID_TITLE_NOISE)
    return _collapse(text)


def make_role_id(role: Role) -> str:
    return f"{normalize_company(role.company)}|{normalize_title(role.title)}"


def _unique(items: list[str]) -> list[str]:
    """Drop duplicates and empties, keeping first-seen order."""
    return [x for x in dict.fromkeys(items) if x]


def _merge(group: list[Role], role_id: str) -> Role:
    """Combine roles sharing a role_id. Display fields come from Simplify if present."""
    preferred = [r for r in group if PREFERRED_LINK_SOURCE in r.sources]
    base = preferred[0] if preferred else group[0]
    # Preferred-source roles first, so their link becomes the primary one.
    ordered = preferred + [r for r in group if PREFERRED_LINK_SOURCE not in r.sources]

    # Compare canonical links, so one posting with different tracking params is one link.
    links = _unique([canonicalize(link) for r in ordered for link in (r.links or [r.link])])
    locations = _unique([loc.strip() for r in group for loc in r.location.split(LOCATION_SEP)])
    known_terms = [r.term for r in group if r.term != "unknown"]

    return Role(
        company=base.company,
        title=base.title,
        location=LOCATION_SEP.join(locations),
        link=links[0],
        sources=_unique([s for r in group for s in r.sources]),
        date_posted=min(r.date_posted for r in group),
        term=known_terms[0] if known_terms else "unknown",
        degrees=_unique([d for r in group for d in r.degrees]),
        source_category=next((r.source_category for r in ordered if r.source_category), ""),
        category=next((r.category for r in ordered if r.category), None),
        links=links,
        role_id=role_id,
    )


def dedupe(roles: list[Role]) -> list[Role]:
    """Return one merged Role per role_id, in first-seen order. Inputs are not mutated."""
    groups: dict[str, list[Role]] = {}
    for role in roles:
        groups.setdefault(make_role_id(role), []).append(role)
    return [_merge(group, role_id) for role_id, group in groups.items()]
