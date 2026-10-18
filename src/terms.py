"""Recruiting term from titles: inference for sources without a term field, and
the off-cycle check the pipeline's term layer applies to every source."""

import re

from src.config import TITLE_OFF_CYCLE_STRONG, TITLE_OFF_CYCLE_WEAK, TITLE_TARGET_TERM_PATTERNS

TARGET_TERM = "Summer 2027"


def _matches(title: str, patterns: list[str]) -> bool:
    t = title.lower()
    return any(re.search(p, t) for p in patterns)


def infer_term(title: str) -> str:
    """Return "Summer 2027" if the title says so, else "unknown"."""
    return TARGET_TERM if _matches(title, TITLE_TARGET_TERM_PATTERNS) else "unknown"


def is_off_cycle(title: str, term: str) -> bool:
    """True if the role should be dropped as off-cycle.

    A title naming Summer 2027 is never off-cycle. Strong patterns (Fall 2026,
    Winter, 2026 Start, ...) drop regardless of the source's term. Weak patterns
    (co-op, part-time) drop only when the term is unknown, so a role the source
    tagged Summer 2027 survives.
    """
    if _matches(title, TITLE_TARGET_TERM_PATTERNS):
        return False
    if _matches(title, TITLE_OFF_CYCLE_STRONG):
        return True
    return term != TARGET_TERM and _matches(title, TITLE_OFF_CYCLE_WEAK)
