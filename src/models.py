"""Shared data types."""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Role:
    """One internship posting, normalized across sources."""

    company: str
    title: str
    location: str  # multiple locations joined with "; "
    link: str  # primary link: the Simplify link if any, else the first seen
    sources: list[str]  # e.g. ["simplify", "jobright"]
    date_posted: date
    term: str  # e.g. "Summer 2027", or "unknown" when the source says N/A
    degrees: list[str] = field(default_factory=list)  # for eligibility (Day 4)
    source_category: str = ""  # the source's own category, e.g. Simplify's "Product"
    category: str | None = None  # set by filter.is_relevant
    # Every distinct posting link. Two postings can share company + title
    # (different job IDs), so dedupe keeps them all rather than hiding one.
    links: list[str] = field(default_factory=list)
    role_id: str = ""  # set by dedupe.dedupe; the sheet's row key (Day 4)
