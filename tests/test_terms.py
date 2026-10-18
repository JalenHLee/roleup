"""Tests for terms: infer_term, and the strong/weak off-cycle check used by the term layer."""

import pytest

from src.terms import infer_term, is_off_cycle

S27, UNKNOWN = "Summer 2027", "unknown"


@pytest.mark.parametrize("title, expected", [
    ("Product Manager Intern (Summer 2027)", S27),
    ("AI Product Manager Intern - 2027 Summer (MBA)", S27),
    ("Product Management Intern (Fall 2026/Spring- Summer 2027)", S27),
    ("Product Manager Intern", UNKNOWN),
    ("Product Manager Intern 2027", UNKNOWN),
    ("Product Manager Intern - Fall 2026", UNKNOWN),  # inference only; the term layer drops it
])
def test_infer_term(title, expected):
    assert infer_term(title) == expected


@pytest.mark.parametrize("title, term", [
    # Strong patterns, any word order: dropped even when the source tagged Summer 2027.
    ("2026 Fall Part-Time Technical Product Specialist", UNKNOWN),
    ("Spring 2027 IT Ecommerce Product Owner Intern", S27),  # Simplify-tagged Summer 2027
    ("Spring 2027 Product Intern", S27),
    ("Product Intern - 2027 Spring", UNKNOWN),
    ("Product Manager Intern - Fall 2026", S27),
    ("Product Strategy Analyst Project Intern - 2026 Start", UNKNOWN),
    ("Product Intern - Winter 2027", S27),
    ("Off-Cycle Product Intern", S27),
    ("Product Intern (Off Cycle)", UNKNOWN),
    # Weak patterns: dropped only when the term is unknown.
    ("Product Co-op", UNKNOWN),
    ("Product Manager Co op", UNKNOWN),
    ("Product Coop 2027", UNKNOWN),
    ("Part-Time Product Intern", UNKNOWN),
    ("Part Time Product Intern", UNKNOWN),
])
def test_off_cycle_dropped(title, term):
    assert is_off_cycle(title, term)


@pytest.mark.parametrize("title, term", [
    ("Product Management Intern (Fall 2026/Spring- Summer 2027)", UNKNOWN),  # names Summer 2027
    ("Product Co-op - Summer 2027", UNKNOWN),
    ("Product Management Intern/Co-op", S27),  # weak + source-tagged Summer 2027: kept
    ("Part-Time Product Intern", S27),
    ("Product Manager Intern", UNKNOWN),
    ("Product Manager Intern", S27),
    ("Springfield Product Intern", UNKNOWN),  # "spring" alone isn't a term
    ("Cooper Product Intern", UNKNOWN),  # "coop" needs a word boundary
])
def test_not_off_cycle(title, term):
    assert not is_off_cycle(title, term)
