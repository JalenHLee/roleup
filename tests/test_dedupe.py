"""Tests for dedupe: role_id normalization and cross-source merging."""

from datetime import date

import pytest

from src.dedupe import dedupe, make_role_id, normalize_company, normalize_title
from src.models import Role


def make_role(company="Acme", title="Product Manager Intern", location="New York, NY",
              source="simplify", link=None, posted=date(2026, 9, 1), term="Summer 2027"):
    link = link or f"https://{source}.example.com/{abs(hash((company, title, location)))}"
    return Role(company=company, title=title, location=location, link=link,
                sources=[source], date_posted=posted, term=term, links=[link])


# --- normalization ---------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Product Management Intern (Summer 2027)", "product management"),
    ("Product Management Intern, 2027 Summer U.S.", "product management"),
    ("Product Manager Internship – 2027 Start", "product manager"),
    ("Product Manager Intern 2027", "product manager"),  # bare year
    ("2026-2027 Product Intern", "product"),  # bare years in a range
    ("  APM   Intern  ", "apm"),
])
def test_normalize_title(raw, expected):
    assert normalize_title(raw) == expected


@pytest.mark.parametrize("raw", ["MBA Product Manager Intern", "Product Manager Intern (MBA)"])
def test_normalize_title_keeps_degree_markers(raw):
    assert "mba" in normalize_title(raw)


@pytest.mark.parametrize("raw, expected", [
    ("Acme, Inc.", "acme"),
    ("Acme LLC", "acme"),
    ("Acme Corp.", "acme"),
    ("Acme Group Ltd", "acme"),
    ("Nissan Motor Corporation", "nissan"),  # COMPANY_ALIASES
    ("Nissan", "nissan"),
])
def test_normalize_company(raw, expected):
    assert normalize_company(raw) == expected


# --- merging ---------------------------------------------------------------

def test_same_role_across_sources_merges():
    a = make_role("Acme, Inc.", "Product Management Intern (Summer 2027)",
                  location="New York, NY", source="simplify",
                  link="https://acme.example.com/jobs/1", posted=date(2026, 9, 10))
    b = make_role("Acme", "Product Management Intern, 2027 Summer U.S.",
                  location="San Francisco, CA; New York, NY", source="jobright",
                  link="https://jobright.ai/jobs/info/1", posted=date(2026, 9, 5))
    [merged] = dedupe([b, a])
    assert merged.sources == ["jobright", "simplify"]
    assert merged.location == "San Francisco, CA; New York, NY"  # deduped
    assert merged.date_posted == date(2026, 9, 5)  # earliest
    assert merged.link == "https://acme.example.com/jobs/1"  # Simplify preferred
    assert merged.links == ["https://acme.example.com/jobs/1", "https://jobright.ai/jobs/info/1"]
    assert merged.company == "Acme, Inc."  # display fields from Simplify
    assert merged.role_id == make_role_id(a) == make_role_id(b)


def test_different_titles_same_company_do_not_merge():
    roles = dedupe([
        make_role(title="Product Manager Intern"),
        make_role(title="Product Marketing Intern"),
        make_role(title="MBA Product Manager Intern"),
    ])
    assert len(roles) == 3


def test_same_title_different_companies_do_not_merge():
    assert len(dedupe([make_role(company="Acme"), make_role(company="Globex")])) == 2


def test_keeps_all_links_for_distinct_postings():
    # Two postings, same company + title, different job IDs: keep both links.
    roles = dedupe([
        make_role(link="https://acme.example.com/jobs/1", location="New York, NY"),
        make_role(link="https://acme.example.com/jobs/2", location="Purchase, NY"),
        make_role(link="https://acme.example.com/jobs/1", location="New York, NY"),
    ])
    [merged] = roles
    assert merged.links == ["https://acme.example.com/jobs/1", "https://acme.example.com/jobs/2"]
    assert merged.link == "https://acme.example.com/jobs/1"
    assert merged.sources == ["simplify"]
    assert merged.location == "New York, NY; Purchase, NY"


def test_primary_link_is_first_seen_without_simplify():
    roles = dedupe([
        make_role(source="jobright", link="https://jobright.ai/a"),
        make_role(source="jobright", link="https://jobright.ai/b"),
    ])
    assert roles[0].link == "https://jobright.ai/a"
    assert roles[0].links == ["https://jobright.ai/a", "https://jobright.ai/b"]


def test_known_term_beats_unknown():
    [merged] = dedupe([
        make_role(source="jobright", term="unknown"),
        make_role(source="simplify", term="Summer 2027"),
    ])
    assert merged.term == "Summer 2027"


def test_inputs_not_mutated():
    a, b = make_role(source="simplify"), make_role(source="jobright")
    dedupe([a, b])
    assert a.sources == ["simplify"] and a.role_id == ""
