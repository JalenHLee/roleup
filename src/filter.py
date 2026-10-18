"""Role filter: decide whether a title is a product-adjacent internship.

v1 prefers recall over precision. Keyword rules live in src/config.py.
"""

import re

from src.config import (
    CATEGORY_EXCLUDES,
    CATEGORY_RULES,
    EXCLUDE_PATTERNS,
    NON_INTERN_PATTERNS,
    STRONG_PM_PATTERNS,
)
from src.models import Role


def _matches(title: str, patterns: list[str]) -> bool:
    return any(re.search(p, title) for p in patterns)


def is_relevant(role: Role) -> str | None:
    """Return the role's category (e.g. "PM", "Growth"), or None to drop it."""
    title = role.title.lower()

    # 1. Senior / full-time roles are not internships.
    if _matches(title, NON_INTERN_PATTERNS):
        return None

    # 2. Engineering, design, data science, etc., unless it's clearly a PM role.
    if _matches(title, EXCLUDE_PATTERNS) and not _matches(title, STRONG_PM_PATTERNS):
        return None

    # 3. First matching category wins, unless that category excludes the title
    #    (e.g. "Systematic Strategy" is not Strategy); then later rules get a chance.
    for category, patterns in CATEGORY_RULES:
        if _matches(title, patterns) and not _matches(title, CATEGORY_EXCLUDES.get(category, [])):
            return category
    return None
