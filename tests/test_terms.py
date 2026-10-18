"""Tests for terms.infer_term (shared by Jobright and alert emails)."""

import pytest

from src.terms import infer_term


@pytest.mark.parametrize("title, expected", [
    ("Product Manager Intern (Summer 2027)", "Summer 2027"),
    ("AI Product Manager Intern - 2027 Summer (MBA)", "Summer 2027"),
    ("Product Management Intern (Fall 2026/Spring- Summer 2027)", "Summer 2027"),
    ("Product Manager Intern", "unknown"),
    ("Product Manager Intern 2027", "unknown"),
    ("Product Manager Intern - Fall 2026", None),
    ("Product Intern - Winter 2027", None),
    ("Spring 2027 Product Owner Intern", None),
    ("Product Manager Co-op", None),
    ("Product Manager Coop 2027", None),
])
def test_infer_term(title, expected):
    assert infer_term(title) == expected
