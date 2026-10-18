"""Canonicalize job links: one stable URL per posting, with tracking removed.

Used before dedupe and before anything is printed, so tracking tokens
(which can identify the recipient) never reach public logs.
"""

import re
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from src.config import TRACKING_PARAMS

_TRACKING = {p.lower() for p in TRACKING_PARAMS}
# /jobs/view/<id>, /comm/jobs/view/<id>, or /jobs/view/<slug>-<id>
_LINKEDIN_JOB_RE = re.compile(r"^(?:/comm)?/jobs/view/(?:[^/]*-)?(\d+)(?:/|$)")


def canonicalize(url: str) -> str:
    """Return the canonical form of a job URL (pure, idempotent)."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()

    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        m = _LINKEDIN_JOB_RE.match(parts.path)
        if m:
            return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"

    # Filter the raw "k=v" segments so kept params stay byte-for-byte unchanged.
    kept = [seg for seg in parts.query.split("&") if seg and not _is_tracking(seg)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(kept), ""))


def _is_tracking(segment: str) -> bool:
    key = unquote_plus(segment.partition("=")[0]).lower()
    return key.startswith("utm_") or key in _TRACKING
