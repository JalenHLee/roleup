"""Tests for dedupe: role_id normalization and cross-source merging."""

from datetime import date

import pytest

from src.dedupe import (dedupe, make_role_id, normalize_company, normalize_title, role_id_from,
                        strip_redundant_suffix, strip_title_location)
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


def test_links_differing_only_by_tracking_merge_into_one():
    [merged] = dedupe([
        make_role(source="jobright",
                  link="https://www.linkedin.com/comm/jobs/view/42/?trackingId=a&trk=eml"),
        make_role(source="jobright", link="https://www.linkedin.com/jobs/view/42/?refId=b"),
    ])
    assert merged.links == ["https://www.linkedin.com/jobs/view/42/"]
    assert merged.link == "https://www.linkedin.com/jobs/view/42/"


# --- quality-pass normalization -------------------------------------------------

def test_holdings_suffix_merges():
    roles = dedupe([make_role(company="Blackhawk Network", source="simplify"),
                    make_role(company="Blackhawk Network Holdings", source="jobright")])
    assert len(roles) == 1 and roles[0].sources == ["simplify", "jobright"]


def test_white_cap_canada_alias():
    assert normalize_company("White Cap Canada") == normalize_company("White Cap")


def test_multiple_teams_noise_merges():
    roles = dedupe([
        make_role(company="Coinbase", title="Associate Product Manager Intern - Multiple Teams"),
        make_role(company="Coinbase", title="Associate Product Manager Intern", source="jobright"),
    ])
    assert len(roles) == 1


def test_trailing_title_location_merges():
    roles = dedupe([
        make_role(company="Nissan", title="Cross Car Line Feature Strategy Intern"),
        make_role(company="Nissan Motor Corporation", source="jobright",
                  title="Cross Car Line Feature Strategy Intern - Summer 2027 - Franklin, TN"),
    ])
    assert len(roles) == 1


@pytest.mark.parametrize("title, expected", [
    ("Product Intern - Franklin, TN", "Product Intern"),
    ("Product Intern – Austin, Texas", "Product Intern"),
    ("Product Intern - Payments, Risk", "Product Intern - Payments, Risk"),  # not a US state
    ("Product Intern - New York, NY", "Product Intern"),
])
def test_strip_title_location(title, expected):
    assert strip_title_location(title) == expected


def test_mba_variant_still_does_not_merge():
    roles = dedupe([
        make_role(company="Acme", title="MBA Product Manager Intern - Multiple Teams"),
        make_role(company="Acme", title="Product Manager Intern - Multiple Teams"),
        make_role(company="Acme Holdings", title="Product Manager Intern (MBA) - Austin, TX"),
    ])
    # The non-MBA role merges with nothing; MBA roles never join it.
    [non_mba] = [r for r in roles if "MBA" not in r.title]
    assert non_mba.role_id == "acme|product manager"
    assert all("mba" in r.role_id for r in roles if r is not non_mba)


def test_redundant_suffix_merges_q2_titles():
    roles = dedupe([
        make_role(company="Q2", title="Product Operations Intern - Product Operations"),
        make_role(company="Q2", title="2027 Summer Internship - Product Operations", source="jobright"),
    ])
    assert len(roles) == 1 and roles[0].sources == ["simplify", "jobright"]


@pytest.mark.parametrize("title, expected", [
    ("Product Operations Intern - Product Operations", "Product Operations Intern"),
    ("Product Intern – product", "Product Intern"),  # en dash, case-insensitive
    ("Product Intern - Payments", "Product Intern - Payments"),  # new word: kept
    ("2027 Summer Internship - Product Operations", "2027 Summer Internship - Product Operations"),
    ("Product Intern", "Product Intern"),
])
def test_strip_redundant_suffix(title, expected):
    assert strip_redundant_suffix(title) == expected


# --- trailing location parenthetical (role_id only) ---------------------------

def test_icf_location_parentheticals_share_a_role_id():
    # Live failure: the same ICF posting, with its location list rewritten between alerts.
    a = role_id_from("ICF", "Product Management Intern (New York, NY; Boston, MA)")
    b = role_id_from("ICF", "Product Management Intern (New York; New Jersey; Boston)")
    assert a == b == role_id_from("ICF", "Product Management Intern")


@pytest.mark.parametrize("title", [
    "Product Intern (Payments)",
    "PM Intern (MBA)",
    "Product Intern (MBA; New York, NY)",  # degree marker: a separate role
    "Product Intern (In Person)",  # "In" isn't Indiana
])
def test_non_location_parentheticals_are_kept(title):
    assert role_id_from("Acme", title) != role_id_from("Acme", title.rsplit(" (", 1)[0])


def test_state_name_parenthetical_is_stripped():
    assert (role_id_from("Acme", "Growth Intern (Texas)")
            == role_id_from("Acme", "Growth Intern"))
