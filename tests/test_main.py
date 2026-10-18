"""Tests for main: public-safe formatting and source failure isolation."""

import imaplib
from datetime import date

import pytest

import src.main
from src.main import SourceResult, describe_failure, format_email_report, format_role, run_sources
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


# --- source failure isolation -------------------------------------------------

# Captured at import: conftest replaces imaplib.IMAP4 with a stub during tests.
IMAP_ERROR = imaplib.IMAP4.error


def fake_role(company: str, source: str) -> Role:
    return Role(company=company, title="Product Manager Intern", location="Remote",
                link=f"https://{source}.example.com/{company}", sources=[source],
                date_posted=date(2026, 10, 1), term="Summer 2027",
                links=[f"https://{source}.example.com/{company}"])


def ok_source(company: str, source: str):
    return lambda: SourceResult([fake_role(company, source)], [])


def failing_source():
    # Real-shaped failure: imaplib raises this on a bad app password.
    raise IMAP_ERROR("b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'")


def test_failing_source_does_not_stop_the_others():
    results, failures = run_sources({
        "simplify": ok_source("Acme", "simplify"),
        "gmail": failing_source,
        "jobright": ok_source("Globex", "jobright"),
    })
    assert sorted(results) == ["jobright", "simplify"]  # sources after the failure still ran
    assert [r.company for r in results["jobright"].roles] == ["Globex"]
    assert failures == {
        "gmail": "error: b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'"}


def test_describe_failure_masks_secret_values_and_caps_length(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    msg = describe_failure(RuntimeError("login abcd efgh ijkl mnop rejected " + "x" * 400))
    assert "abcd efgh" not in msg and "<GMAIL_APP_PASSWORD>" in msg
    assert msg.startswith("RuntimeError: ") and msg.endswith("...")
    assert len(msg) < 350


@pytest.mark.parametrize("gmail, expected_code", [(failing_source, 1), (None, 0)])
def test_main_exit_code(monkeypatch, capsys, gmail, expected_code):
    sources = {"simplify": ok_source("Acme", "simplify"), "jobright": ok_source("Globex", "jobright")}
    if gmail:
        sources["gmail"] = gmail
    monkeypatch.setattr(src.main, "active_sources", lambda: sources)

    assert src.main.main() == expected_code

    out = capsys.readouterr().out
    # Everything is still printed, failure or not.
    assert "Acme | Product Manager Intern" in out
    assert "Globex | Product Manager Intern" in out
    assert "digest: 2 roles" in out
    if expected_code:
        assert "=== Source failures (1) ===" in out
        assert "  - gmail: error: b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'" in out
    else:
        assert "=== Source failures (0) ===\n  (none)" in out
