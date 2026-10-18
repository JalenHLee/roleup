"""Eligibility flags: mark roles an undergrad (Dec 2028 grad) can't apply to.

Flag, don't delete: flagged roles stay in the data and sheet, and are only
hidden from the digest. Rules live in src/config.py.
"""

import re

from src.config import GRAD_ONLY_TITLE_PATTERNS
from src.models import Role

GRAD_ONLY = "grad-only"


def eligibility_flag(role: Role) -> str:
    """Return "grad-only" or "" (eligible)."""
    title = role.title.lower()
    if any(re.search(p, title) for p in GRAD_ONLY_TITLE_PATTERNS):
        return GRAD_ONLY
    # Simplify lists accepted degrees, e.g. ["Bachelor's", "Master's"]. A non-empty
    # list without a bachelor's degree means grad students only.
    if role.degrees and not any("bachelor" in d.lower() for d in role.degrees):
        return GRAD_ONLY
    return ""
