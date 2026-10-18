"""Tests for the digest email builder (pure) and the send/skip rules. Fake data only."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.config import ROLEUP_HEADERS
from src.digest import build_digest, run_label, should_send
from src.sheet import SyncCounts

TODAY = date(2026, 10, 19)
SHEET_URL = "https://docs.google.com/spreadsheets/d/fakeSheet"
KST = ZoneInfo("Asia/Seoul")


def row(company, title, category, link="https://example.com/job/1", location="Remote",
        sources="simplify"):
    values = dict.fromkeys(ROLEUP_HEADERS, "")
    values.update(Status="New", Company=company, Title=title, Category=category,
                  Link=link, Location=location, Sources=sources)
    return values


ROWS = [
    row("Zeta Ops", "Business Operations Intern", "Operations"),
    row("Beta", "Product Marketing Intern", "PMM"),
    row("Acme", "Product Manager Intern", "PM", link="https://acme.example.com/jobs/1",
        location="New York, NY", sources="simplify, jobright"),
    row("Alpha", "APM Intern", "PM"),
    row("Odd", "Product Thing", "Mystery"),
]
COUNTS = SyncCounts(already_in_roleup=7, already_applied=2, appended_new=5, appended_hidden=1)


def build(rows=ROWS, counts=COUNTS, failures=None, parse_errors=0, label="Morning"):
    return build_digest(rows, counts, failures or {}, parse_errors, SHEET_URL, label, TODAY)


# --- subject -------------------------------------------------------------------

def test_subject_variants():
    assert build()[0] == "Roleup (Morning): 5 new roles — Oct 19"
    assert build(rows=ROWS[:1], label="Evening")[0] == "Roleup (Evening): 1 new role — Oct 19"
    assert build(rows=[])[0] == "Roleup (Morning): no new roles today — Oct 19"
    assert (build(rows=[], failures={"jobright": "HTTPError: 503"})[0]
            == "Roleup (Morning): no new roles today — Oct 19 — 1 problem")


# --- body ----------------------------------------------------------------------

def test_roles_grouped_by_category_pm_first():
    _, html, text = build()
    order = [text.index(f"{cat} (") for cat in ("PM", "PMM", "Operations", "Mystery")]
    assert order == sorted(order)
    assert text.index("Acme") < text.index("Alpha")  # by company within a category
    assert html.index("<h3>PM (2)</h3>") < html.index("<h3>PMM (1)</h3>")


def test_role_line_has_company_title_location_link_sources():
    _, html, text = build()
    assert ("  - Acme — Product Manager Intern — New York, NY — "
            "https://acme.example.com/jobs/1 — simplify, jobright") in text
    assert ('<li><b>Acme</b> — Product Manager Intern — New York, NY — '
            '<a href="https://acme.example.com/jobs/1">Apply</a> — '
            '<small>simplify, jobright</small></li>') in html


def test_counts_and_sheet_link():
    _, html, text = build()
    for line in ("New roles: 5", "Hidden added (eligibility): 1",
                 "Skipped as already applied (tracker): 2"):
        assert line in text and line in html
    assert f"Sheet: {SHEET_URL}" in text
    assert f'<a href="{SHEET_URL}">Open the Roleup sheet</a>' in html
    assert "Problems" not in text


def test_problems_section_lists_failures_and_parse_errors():
    _, html, text = build(failures={"jobright": "HTTPError: 503 Server Error"}, parse_errors=3)
    assert "Problems" in text
    assert "  - jobright: HTTPError: 503 Server Error" in text
    assert "  - Parse errors: 3 (see the Actions log)" in text
    assert "<li>jobright: HTTPError: 503 Server Error</li>" in html


def test_failed_sheet_sync_says_so():
    _, html, text = build(rows=[], counts=None, failures={"sheet": "APIError: quota"})
    assert "Sheet sync did not complete" in text and "Sheet sync did not complete" in html
    assert "sheet: APIError: quota" in text
    assert "No new roles this run." in text


def test_html_escapes_role_text():
    evil = row("<b>Evil</b> & Co", 'PM Intern <script>alert("x")</script>', "PM",
               link='https://e.example.com/?a=1&b="><script>x</script>')
    _, html, _ = build(rows=[evil], failures={"gmail": "<img src=x onerror=alert(1)>"})
    assert "<script>" not in html and "<img" not in html and "<b>Evil" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "&lt;b&gt;Evil&lt;/b&gt; &amp; Co" in html
    assert 'href="https://e.example.com/?a=1&amp;b=&quot;&gt;&lt;script&gt;x&lt;/script&gt;"' in html


def test_non_web_link_is_not_clickable():
    _, html, _ = build(rows=[row("Acme", "PM Intern", "PM", link="javascript:alert(1)")])
    assert "href=\"javascript" not in html and "javascript:alert(1)" in html


# --- run label and send rules ----------------------------------------------------

@pytest.mark.parametrize("hour, minute, label", [
    (6, 50, "Morning"), (11, 59, "Morning"), (12, 0, "Evening"), (17, 50, "Evening")])
def test_run_label_from_kst_hour(hour, minute, label):
    assert run_label(datetime(2026, 10, 19, hour, minute, tzinfo=KST)) == label


def test_morning_heartbeat_sends_with_zero_roles():
    assert should_send("Morning", 0, {})


def test_evening_with_zero_roles_and_no_failures_skips():
    assert not should_send("Evening", 0, {})


def test_evening_sends_with_new_roles_or_a_failure():
    assert should_send("Evening", 2, {})
    assert should_send("Evening", 0, {"sheet": "APIError: quota"})


def test_force_send_overrides_evening_skip():
    assert should_send("Evening", 0, {}, force=True)
