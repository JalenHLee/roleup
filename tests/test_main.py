"""Tests for main: public-safe formatting, failure isolation, and the digest step."""

import imaplib
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import src.main
from src.config import ROLEUP_HEADERS
from src.main import (SourceResult, describe_failure, format_email_report, format_role,
                      run_digest, run_sources)
from src.models import Role
from src.sheet import SyncCounts
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


# --- digest step -----------------------------------------------------------------

MORNING = datetime(2026, 10, 19, 6, 50, tzinfo=ZoneInfo("Asia/Seoul"))
EVENING = datetime(2026, 10, 19, 17, 50, tzinfo=ZoneInfo("Asia/Seoul"))
BODY_MARKER = "Qwertz Unique Title Marker"


def appended_row(status="New", title=BODY_MARKER):
    values = dict.fromkeys(ROLEUP_HEADERS, "")
    values.update(Status=status, Company="Fakeco", Title=title, Category="PM",
                  Link="https://fakeco.example.com/jobs/1")
    return [values[h] for h in ROLEUP_HEADERS]


class Outbox:
    def __init__(self):
        self.sent = []

    def __call__(self, subject, html, text):
        self.sent.append((subject, html, text))


def test_run_digest_lists_only_new_rows_and_reports_counts_only():
    outbox = Outbox()
    status, failure = run_digest([appended_row(), appended_row("Hidden", "Hidden One")],
                                 None, {}, 0, now=MORNING, send=outbox)
    assert (status, failure) == ("digest sent (Morning): 1 new roles", None)
    [(subject, html, text)] = outbox.sent
    assert subject.startswith("Roleup (Morning): 1 new role —")
    assert BODY_MARKER in text and "Hidden One" not in text


def test_run_digest_evening_nothing_new_skips():
    outbox = Outbox()
    assert run_digest([], None, {}, 0, now=EVENING, send=outbox) == (
        "digest skipped (Evening, nothing new)", None)
    assert outbox.sent == []


def test_run_digest_evening_force_sends():
    outbox = Outbox()
    status, _ = run_digest([], None, {}, 0, now=EVENING, send=outbox, force=True)
    assert status == "digest sent (Evening): 0 new roles" and len(outbox.sent) == 1


def test_run_digest_send_failure_is_isolated_and_masked(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake pw 1234")

    def broken(*args):
        raise OSError("SMTP auth failed for fake pw 1234")

    status, failure = run_digest([], None, {}, 0, now=MORNING, send=broken)
    assert status == "digest failed (Morning)"
    assert failure == "OSError: SMTP auth failed for <GMAIL_APP_PASSWORD>"


@pytest.mark.parametrize("value, expected", [("true", True), ("True", True), ("false", False),
                                             ("", False)])
def test_force_send_env(monkeypatch, value, expected):
    monkeypatch.setenv("ROLEUP_FORCE_SEND", value)
    assert src.main.force_send() is expected


def run_main_with_digest(monkeypatch, sheet_result, now=MORNING, send=None):
    """main with fake sources, a stubbed sheet sync, and a fake mail outbox."""
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.setenv("SHEET_ID", "fakeSheetId123")
    monkeypatch.setenv("GMAIL_ADDRESS", "bot@fake.example")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake app password")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(src.main, "active_sources", lambda: {
        "simplify": ok_source("Acme", "simplify")})
    monkeypatch.setattr(src.main, "run_sheet_sync", lambda result: sheet_result)
    monkeypatch.setattr(src.main, "run_now", lambda: now)
    outbox = Outbox()
    monkeypatch.setattr(src.main.mailer, "send_email", send or outbox)
    return src.main.main(), outbox


def test_main_sends_digest_even_when_sheet_sync_fails(monkeypatch, capsys):
    code, outbox = run_main_with_digest(monkeypatch, ([], None, "APIError: quota exceeded"))
    assert code == 1
    [(subject, _, text)] = outbox.sent
    assert subject.endswith("— 1 problem")
    assert "sheet: APIError: quota exceeded" in text
    assert "Sheet sync did not complete" in text
    out = capsys.readouterr().out
    assert "=== Digest email ===\ndigest sent (Morning): 0 new roles" in out
    assert "  - sheet: APIError: quota exceeded" in out


def test_main_never_prints_the_digest_body(monkeypatch, capsys):
    code, outbox = run_main_with_digest(
        monkeypatch, ([appended_row()], SyncCounts(appended_new=1), None))
    assert code == 0
    [(subject, html, text)] = outbox.sent
    assert BODY_MARKER in text
    out = capsys.readouterr().out
    assert "digest sent (Morning): 1 new roles" in out
    for leaked in (BODY_MARKER, subject, "fakeSheetId123", "docs.google.com", "Apply"):
        assert leaked not in out


def test_main_evening_nothing_new_skips_digest(monkeypatch, capsys):
    code, outbox = run_main_with_digest(monkeypatch, ([], SyncCounts(), None), now=EVENING)
    assert code == 0 and outbox.sent == []
    assert "digest skipped (Evening, nothing new)" in capsys.readouterr().out


def test_main_digest_failure_exits_1(monkeypatch, capsys):

    def broken(*args):
        raise OSError("connection refused")

    code, _ = run_main_with_digest(monkeypatch, ([], SyncCounts(), None), send=broken)
    assert code == 1
    out = capsys.readouterr().out
    assert "digest failed (Morning)" in out
    assert "  - digest: OSError: connection refused" in out
