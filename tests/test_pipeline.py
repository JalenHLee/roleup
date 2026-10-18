"""Tests for pipeline.run_pipeline: each layer drops or hides the right roles."""

from datetime import date

from src.pipeline import run_pipeline
from src.models import Role


def make_role(title="Product Manager Intern", company="Acme", location="New York, NY",
              source="simplify", term="Summer 2027", degrees=()):
    link = f"https://{source}.example.com/{company}/{abs(hash((title, location)))}"
    return Role(company=company, title=title, location=location, link=link, sources=[source],
                date_posted=date(2026, 10, 1), term=term, degrees=list(degrees), links=[link])


def test_each_layer():
    roles = [
        make_role("Product Manager Intern"),                                   # digest
        make_role("Product Manager Intern", source="jobright", term="unknown",
                  location="Seattle, WA"),                                     # merges with ^
        make_role("Spring 2027 Product Intern", company="B"),                  # term (strong, tagged S27)
        make_role("Product Co-op", company="C", source="jobright", term="unknown"),  # term (weak)
        make_role("Product Management Intern/Co-op", company="D"),             # kept: weak + tagged S27
        make_role("Software Engineer Intern", company="E"),                    # filter
        make_role("Systematic Strategy Intern", company="F"),                  # filter (category exclude)
        make_role("Growth Intern", company="G", location="London, UK"),        # location
        make_role("Growth Intern", company="H", location="Toronto, ON; Austin, TX"),  # kept: mixed
        make_role("MBA Product Manager Intern", company="I"),                  # hidden: title
        make_role("Strategy Intern", company="J", degrees=["Master's", "PhD"]),  # hidden: degrees
    ]
    r = run_pipeline(roles)

    assert {x.company for x in r.dropped_term} == {"B", "C"}
    assert {x.company for x in r.dropped_filter} == {"E", "F"}
    assert len(r.kept) == 7 and len(r.merged) == 6  # the two Acme listings merged
    assert [x.company for x in r.dropped_location] == ["G"]
    assert {x.company for x in r.hidden} == {"I", "J"}
    assert all(x.eligibility_flag == "grad-only" for x in r.hidden)
    assert {x.company for x in r.digest} == {"Acme", "D", "H"}
    assert all(x.eligibility_flag == "" for x in r.digest)

    [acme] = [x for x in r.digest if x.company == "Acme"]
    assert acme.sources == ["simplify", "jobright"]
    assert acme.location == "New York, NY; Seattle, WA"


def test_location_sees_all_merged_locations():
    # Toronto alone would be dropped, but the merged role also has a US location.
    r = run_pipeline([
        make_role(location="Toronto, ON, Canada"),
        make_role(location="Chicago, IL", source="jobright", term="unknown"),
    ])
    assert r.dropped_location == [] and len(r.digest) == 1


def test_empty_input():
    r = run_pipeline([])
    assert r.digest == r.hidden == r.dropped_term == []
