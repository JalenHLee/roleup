"""Tests for sources.jobright.parse_readme using a fake README fixture."""

from datetime import date
from pathlib import Path

import pytest

from src.sources.jobright import _infer_date, parse_readme

FIXTURE = Path(__file__).parent / "fixtures" / "jobright_readme.md"
TODAY = date(2026, 10, 17)


@pytest.fixture
def parsed():
    return parse_readme(FIXTURE.read_text(), TODAY)


def by_title(roles, title):
    [role] = [r for r in roles if r.title == title]
    return role


def test_parses_links_and_fields(parsed):
    roles, _ = parsed
    role = by_title(roles, "Product Manager Intern (Summer 2027)")
    assert role.company == "Acme"  # link text, not the company URL
    assert role.link == "https://jobright.ai/jobs/info/aaa1?utm_source=git"  # title's URL
    assert role.links == [role.link]
    assert role.location == "New York, NY, United States"
    assert role.sources == ["jobright"]
    assert role.date_posted == date(2026, 10, 17)
    assert role.term == "Summer 2027"


def test_arrow_row_inherits_company_above(parsed):
    roles, _ = parsed
    assert by_title(roles, "Growth Intern - 2027 Summer").company == "Acme"
    assert by_title(roles, "Associate Product Manager Intern").company == "Globex Inc."


def test_plain_text_company(parsed):
    roles, _ = parsed
    title = "Product Management Intern (Fall 2026/Spring- Summer 2027)"
    assert by_title(roles, title).company == "Initech"


def test_off_cycle_roles_kept_for_the_term_layer(parsed):
    # The parser no longer drops off-cycle titles; the pipeline's term layer does,
    # so every drop is counted in one place (see test_pipeline.py).
    roles, errors = parsed
    co_op = by_title(roles, "Product Manager Spring Co-op 2027")
    assert co_op.term == "unknown"
    assert by_title(roles, "Strategy Intern - Winter 2027").company == "Umbrella"
    assert not any("Co-op" in e or "Winter" in e for e in errors)


def test_company_link_with_space_before_paren_is_plain_text():
    text = (
        "| Company | Job Title | Location | Work Model | Date Posted |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| **[Fortune Brands Innovations](https://www.fbin.com )** | "
        "**[Product Management Intern](https://jobright.ai/jobs/info/fff1 )** | "
        "Deerfield, IL, United States | Hybrid | Oct 15 |\n"
    )
    [role], errors = parse_readme(text, TODAY)
    assert errors == []
    assert role.company == "Fortune Brands Innovations"
    assert role.link == "https://jobright.ai/jobs/info/fff1"


def test_no_term_in_title_is_unknown(parsed):
    roles, _ = parsed
    assert by_title(roles, "Associate Product Manager Intern").term == "unknown"


def test_malformed_row_is_reported_not_dropped(parsed):
    roles, errors = parsed
    assert len(roles) == 6  # 7 rows, 1 malformed
    assert len(errors) == 1 and "title is not a link" in errors[0]


def test_missing_table_raises():
    with pytest.raises(ValueError, match="table header not found"):
        parse_readme("# README\n\nNo table here.\n", TODAY)


def test_arrow_first_row_is_an_error():
    text = (
        "| Company | Job Title | Location | Work Model | Date Posted |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| ↳ | **[Product Intern](https://jobright.ai/x)** | NY | On Site | Oct 1 |\n"
    )
    roles, errors = parse_readme(text, TODAY)
    assert roles == [] and len(errors) == 1


@pytest.mark.parametrize("text, today, expected", [
    ("Oct 17", date(2026, 10, 17), date(2026, 10, 17)),  # today
    ("Sep 23", date(2026, 10, 17), date(2026, 9, 23)),
    ("Dec 30", date(2027, 1, 5), date(2026, 12, 30)),  # across New Year
    ("Feb 29", date(2028, 3, 1), date(2028, 2, 29)),  # leap day
])
def test_infer_date_most_recent_past(text, today, expected):
    assert _infer_date(text, today) == expected


def test_infer_date_bad_text_raises():
    with pytest.raises(ValueError):
        _infer_date("yesterday", TODAY)
