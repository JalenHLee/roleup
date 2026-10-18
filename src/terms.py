"""Infer a role's recruiting term from its title, for sources with no term field."""

import re

from src.config import TITLE_OFF_CYCLE_PATTERNS, TITLE_TARGET_TERM_PATTERNS


def infer_term(title: str) -> str | None:
    """Return "Summer 2027", "unknown", or None for an off-cycle role to drop."""
    t = title.lower()
    if any(re.search(p, t) for p in TITLE_TARGET_TERM_PATTERNS):
        return "Summer 2027"
    if any(re.search(p, t) for p in TITLE_OFF_CYCLE_PATTERNS):
        return None
    return "unknown"
