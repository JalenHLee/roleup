"""Tests for eligibility.eligibility_flag."""

from datetime import date

import pytest

from src.eligibility import eligibility_flag
from src.models import Role


def make_role(title, degrees=()):
    return Role(company="Acme", title=title, location="Remote", link="https://example.com/1",
                sources=["simplify"], date_posted=date(2026, 10, 1), term="Summer 2027",
                degrees=list(degrees))


@pytest.mark.parametrize("title", [
    "MBA Product Manager Intern",
    "Product Manager Intern (MS or MBA)",
    "Master's Product Intern",
    "Masters Product Strategy Intern",
    "Graduate Intern - Product",
    "Grad Intern, Strategy",
    "PhD Product Intern",
    "Ph.D. Product Research Intern",
])
def test_grad_only_titles(title):
    assert eligibility_flag(make_role(title)) == "grad-only"


@pytest.mark.parametrize("title", [
    "Product Manager Intern",
    "Product Intern (BS/MS)",  # BS allowed
    "Undergraduate Product Intern",
    "Product Manager Intern - Graduate Programs Team",  # "graduate" not followed by intern
])
def test_eligible_titles(title):
    assert eligibility_flag(make_role(title)) == ""


@pytest.mark.parametrize("degrees, expected", [
    (["Master's", "PhD"], "grad-only"),
    (["PhD"], "grad-only"),
    (["Master's"], "grad-only"),
    (["Bachelor's", "Master's"], ""),
    (["Bachelor's"], ""),
    ([], ""),  # unknown: not flagged
])
def test_simplify_degrees(degrees, expected):
    assert eligibility_flag(make_role("Product Manager Intern", degrees)) == expected
