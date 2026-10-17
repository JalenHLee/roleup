"""Shared data types."""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Role:
    """One internship posting, normalized across sources."""

    company: str
    title: str
    location: str  # multiple locations joined with "; "
    link: str
    source: str  # e.g. "simplify"
    date_posted: date
    term: str  # e.g. "Summer 2027", or "unknown" when the source says N/A
    degrees: list[str] = field(default_factory=list)  # for eligibility (Day 4)
    source_category: str = ""  # the source's own category, e.g. Simplify's "Product"
    category: str | None = None  # set by filter.is_relevant
