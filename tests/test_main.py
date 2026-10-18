"""Tests for main's public-log formatting: nothing identifying reaches the output."""

from datetime import date

from src.main import format_email_report, format_role
from src.models import Role
from src.sources.gmail_alerts import EmailResult, short_id

RAW_LINK = ("https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=Ab12%3D%3D"
            "&refId=xYz&midToken=AQH-fake&otpToken=fakeOtp&trk=eml")


def test_format_role_shows_only_canonical_link():
    role = Role(
        company="Acme Robotics", title="Product Manager Intern", location="New York, NY",
        link=RAW_LINK, sources=["linkedin"], date_posted=date(2026, 10, 16),
        term="Summer 2027", category="PM", links=[RAW_LINK, RAW_LINK + "&lipi=x"],
    )
    line = format_role(role)
    assert line == ("[PM] Acme Robotics | Product Manager Intern | New York, NY | linkedin | "
                    "https://www.linkedin.com/jobs/view/4012345678/")
    for token in ("trackingId", "refId", "midToken", "otpToken", "trk", "/comm/", "lipi"):
        assert token not in line


def test_format_email_report_lines_and_totals():
    mid = "<fake-linkedin-001@example.com>"
    report = [
        EmailResult("linkedin.com", short_id(mid), "linkedin", roles=3, errors=1),
        EmailResult("e.linkedin.com", short_id("<b@example.com>"), "linkedin", roles=2, errors=0),
        EmailResult("example.com", short_id("<c@example.com>"), None, roles=0, errors=1),
    ]
    lines = format_email_report(report)
    assert lines[0] == f"  linkedin.com  #{short_id(mid)}  roles: 3  errors: 1"
    assert "  total linkedin: 2 emails, 5 roles, 1 errors" in lines
    assert "  total unknown sender: 1 emails, 0 roles, 1 errors" in lines
    assert not any("fake-linkedin-001" in line or "@" in line for line in lines)
