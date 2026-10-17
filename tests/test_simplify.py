"""Tests for sources.simplify.parse_listings using fake listings."""

from datetime import date

from src.sources.simplify import parse_listings


def make_listing(**overrides) -> dict:
    listing = {
        "id": "fake-1",
        "company_name": "Acme Corp",
        "title": "Product Manager Intern",
        "url": "https://example.com/job/1",
        "locations": ["New York, NY"],
        "date_posted": 1788220800,  # 2026-09-01 00:00 UTC
        "terms": ["Summer 2027"],
        "active": True,
        "is_visible": True,
        "category": "Product",
        "degrees": ["Bachelor's"],
    }
    listing.update(overrides)
    return listing


def test_parses_basic_listing():
    roles, errors = parse_listings([make_listing()])
    assert errors == []
    [role] = roles
    assert role.company == "Acme Corp"
    assert role.title == "Product Manager Intern"
    assert role.link == "https://example.com/job/1"
    assert role.source == "simplify"
    assert role.date_posted == date(2026, 9, 1)
    assert role.term == "Summer 2027"
    assert role.degrees == ["Bachelor's"]
    assert role.source_category == "Product"
    assert role.category is None


def test_drops_inactive_and_hidden():
    roles, errors = parse_listings([
        make_listing(active=False),
        make_listing(is_visible=False),
    ])
    assert roles == [] and errors == []


def test_drops_off_target_terms():
    roles, _ = parse_listings([
        make_listing(terms=["Fall 2026"]),
        make_listing(terms=["Summer 2026"]),
        make_listing(terms=["Winter 2027", "Spring 2027"]),
    ])
    assert roles == []


def test_na_term_becomes_unknown():
    roles, _ = parse_listings([make_listing(terms=["N/A"])])
    assert roles[0].term == "unknown"


def test_multi_term_listing_keeps_target_term():
    roles, _ = parse_listings([make_listing(terms=["Fall 2026", "Summer 2027"])])
    assert roles[0].term == "Summer 2027"


def test_joins_multiple_locations():
    roles, _ = parse_listings([make_listing(locations=["New York, NY", "Remote in USA"])])
    assert roles[0].location == "New York, NY; Remote in USA"


def test_malformed_listing_is_reported_not_dropped():
    bad = make_listing(id="bad-1")
    del bad["title"]
    roles, errors = parse_listings([bad, make_listing()])
    assert len(roles) == 1
    assert len(errors) == 1 and "bad-1" in errors[0]
