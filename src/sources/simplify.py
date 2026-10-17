"""Ingest the SimplifyJobs internship list from its structured listings JSON."""

import logging
from datetime import datetime, timezone

import requests

from src.config import SIMPLIFY_LISTINGS_URL, TARGET_TERMS
from src.models import Role

log = logging.getLogger(__name__)


def fetch_roles() -> tuple[list[Role], list[str]]:
    """Download Simplify's listings and return (roles, parse_errors).

    Network or JSON failures raise: an empty list would look like "no new roles".
    """
    resp = requests.get(SIMPLIFY_LISTINGS_URL, timeout=30)
    resp.raise_for_status()
    return parse_listings(resp.json())


def parse_listings(listings: list[dict]) -> tuple[list[Role], list[str]]:
    """Turn raw Simplify listings into Roles.

    Keeps only active, visible listings in one of TARGET_TERMS.
    Malformed listings are logged and returned as errors, never dropped silently.
    """
    roles: list[Role] = []
    errors: list[str] = []

    for i, listing in enumerate(listings):
        if not (listing.get("active") and listing.get("is_visible")):
            continue

        term = _pick_term(listing.get("terms") or [])
        if term is None:
            continue

        try:
            roles.append(Role(
                company=listing["company_name"],
                title=listing["title"],
                location="; ".join(listing.get("locations") or []),
                link=listing["url"],
                sources=["simplify"],
                date_posted=datetime.fromtimestamp(
                    listing["date_posted"], tz=timezone.utc
                ).date(),
                term=term,
                degrees=list(listing.get("degrees") or []),
                source_category=listing.get("category") or "",
                links=[listing["url"]],
            ))
        except (KeyError, TypeError, ValueError, OSError) as e:
            msg = f"simplify listing #{i} (id={listing.get('id')}): {type(e).__name__}: {e}"
            log.warning("Failed to parse %s", msg)
            errors.append(msg)

    return roles, errors


def _pick_term(terms: list[str]) -> str | None:
    """Return the first target term this listing has ("N/A" -> "unknown"), else None."""
    for target in TARGET_TERMS:
        if target in terms:
            return "unknown" if target == "N/A" else target
    return None
