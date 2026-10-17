"""Tests for filter.is_relevant using fake roles."""

from datetime import date

import pytest

from src.filter import is_relevant
from src.models import Role


def make_role(title: str) -> Role:
    return Role(
        company="Acme Corp",
        title=title,
        location="Remote",
        link="https://example.com/job",
        sources=["test"],
        date_posted=date(2026, 9, 1),
        term="Summer 2027",
    )


@pytest.mark.parametrize("title, expected", [
    ("Product Manager Intern", "PM"),
    ("Associate Product Manager Intern", "PM"),
    ("APM Intern", "PM"),
    ("Product Analyst Intern", "PM"),
    ("Product Intern", "PM"),
    ("Technical Product Manager Intern", "PM"),
    ("Product Manager Intern - Engineering Platform", "PM"),  # strong PM beats "engineering"
    ("MBA Product Management Intern", "PM"),  # eligibility is handled elsewhere
    ("Product Manager Intern - Scaled Growth", "PM"),  # PM rule comes before Growth
    ("Product Operations Intern", "Operations"),
    ("Business Operations Intern", "Operations"),
    ("Strategy & Operations Intern", "Operations"),
    ("BizOps Intern", "Operations"),
    ("Sales Ops Intern", "Operations"),
    ("Growth Intern", "Growth"),
    ("Corporate Strategy Intern", "Strategy"),
    ("Product Marketing Intern", "PMM"),
    ("Product Marketing Manager Intern", "PMM"),  # PMM rule comes before PM
    ("Product Solutions Intern", "Product (other)"),
    ("Offering Management Intern", "PM"),
])
def test_keeps_relevant_titles(title, expected):
    assert is_relevant(make_role(title)) == expected


@pytest.mark.parametrize("title", [
    "Product Design Intern",
    "Operations Software Engineering Intern",
    "Backend Software Engineer Intern - Product Infrastructure",
    "Data Science Intern - Product",
    "Quantitative Strategy Developer Intern",
    "Software Engineer Intern - Growth",
    "UX Research Intern",
    "Marketing Intern",
    "Brand Marketing Intern",
    "Social Media Intern",
    "Senior Product Manager",
    "Sr. Product Manager",
    "Staff Product Manager",
    "VP, Product Strategy",
    "Hardware Engineering Intern",
    "Machine Learning Intern",
    "Accounting Intern",
    "ML Ops & Automation Intern",
    "MLOps Intern",
    "Options Strategy Intern",
    "Store Operations Data Analyst Intern",
])
def test_drops_irrelevant_titles(title):
    assert is_relevant(make_role(title)) is None


@pytest.mark.parametrize("title", [
    "Staffing Operations Intern",  # "staff" inside "staffing" is not seniority
    "VPN Product Intern",  # "vp" inside "vpn" is not seniority
])
def test_short_seniority_patterns_use_word_boundaries(title):
    assert is_relevant(make_role(title)) is not None


def test_ops_pattern_uses_word_boundary():
    # "ops" inside "Workshops" must not count as Operations.
    assert is_relevant(make_role("Workshops Intern")) is None
