"""US location check: keep a role unless every one of its locations is clearly non-US.

Rules live in src/config.py. Unclear locations ("Remote", "SF", "") are kept:
prefer recall in v1.
"""

import re

from src.config import NON_US_LOCATION_PATTERNS, US_LOCATION_PATTERNS, US_STATES

LOCATION_SEP = ";"
_STATE_CODE_RE = re.compile(r",\s*([A-Za-z]{2})\b")
_STATE_NAMES = {name.lower() for name in US_STATES.values()}


def _is_us(segment: str) -> bool:
    s = segment.lower()
    if any(re.search(p, s) for p in US_LOCATION_PATTERNS):
        return True
    # "City, ST" or "City, ST, ..." with a real US state code.
    if any(code.upper() in US_STATES for code in _STATE_CODE_RE.findall(segment)):
        return True
    # "City, State" with a full state name (word-bounded, e.g. not "Washingtonville").
    return any(re.search(rf"\b{re.escape(name)}\b", s) for name in _STATE_NAMES)


def _is_non_us(segment: str) -> bool:
    s = segment.lower()
    return any(re.search(p, s) for p in NON_US_LOCATION_PATTERNS)


def is_us_or_unclear(location: str) -> bool:
    """True if any location segment is US or unclear; False only if all are non-US."""
    segments = [seg.strip() for seg in location.split(LOCATION_SEP) if seg.strip()]
    if not segments:
        return True  # no location given: unclear, keep
    return any(_is_us(seg) or not _is_non_us(seg) for seg in segments)
