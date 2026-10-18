"""Tests for the Google Sheet sync, against an in-memory fake spreadsheet.

All company names, positions, and links are fake.
"""

from datetime import date

import gspread
import pytest

import src.main
import src.sheet
from src.config import ROLEUP_HEADERS, ROLEUP_STATUSES, ROLEUP_TAB, TRACKER_TAB
from src.main import SourceResult
from src.models import Role
from src.pipeline import run_pipeline
from src.sheet import ensure_roleup_tab, plan_sync, read_tracker, sync

TODAY = date(2026, 10, 19)
TRACKER_HEADERS = ["Apply Date", "Company", "Stage", "Position", "LinkedIn Referrals",
                   "Project?", "Response Date", "Job URL", "Referral?"]


# --- fakes ----------------------------------------------------------------------

class FakeWorksheet:
    def __init__(self, title, values=None, sheet_id=0, read_only=False):
        self.title = title
        self.values = [list(row) for row in values or []]
        self.id = sheet_id
        self.read_only = read_only
        self.appends = []  # one entry per append_rows call

    def get_all_values(self):
        return [list(row) for row in self.values]

    def _write(self):
        if self.read_only:
            raise AssertionError(f"wrote to read-only tab {self.title!r}")

    def update(self, range_name=None, values=None, **kwargs):
        self._write()
        assert range_name == "A1"
        if self.values:
            self.values[0] = list(values[0])
        else:
            self.values.append(list(values[0]))

    def append_rows(self, values, **kwargs):
        self._write()
        assert kwargs.get("value_input_option") == "RAW"
        self.appends.append(values)
        self.values.extend(list(row) for row in values)

    def __getattr__(self, name):
        # Any other gspread method (delete_rows, update_cell, clear, ...) is a write we never expect.
        raise AssertionError(f"unexpected worksheet call {name!r} on {self.title!r}")


class FakeSpreadsheet:
    def __init__(self, tracker_rows, roleup_rows=None):
        self.tabs = {TRACKER_TAB: FakeWorksheet(
            TRACKER_TAB, [TRACKER_HEADERS] + tracker_rows, sheet_id=1, read_only=True)}
        if roleup_rows is not None:
            self.tabs[ROLEUP_TAB] = FakeWorksheet(ROLEUP_TAB, roleup_rows, sheet_id=2)
        self.requests = []
        self.added = []

    def worksheet(self, title):
        if title not in self.tabs:
            raise gspread.WorksheetNotFound(title)
        return self.tabs[title]

    def add_worksheet(self, title, rows, cols):
        self.added.append(title)
        self.tabs[title] = FakeWorksheet(title, sheet_id=99)
        return self.tabs[title]

    def batch_update(self, body):
        self.requests.extend(body["requests"])

    @property
    def roleup(self):
        return self.tabs[ROLEUP_TAB]


def tracker_row(company, position, url=""):
    return ["2026-10-01", company, "Rejected", position, "", "", "", url, ""]


def role(company, title, link, source="simplify", degrees=None):
    return Role(company=company, title=title, location="Remote", link=link, sources=[source],
                date_posted=date(2026, 10, 1), term="Summer 2027", degrees=degrees or [],
                links=[link])


def pipeline(*roles):
    return run_pipeline(list(roles))


def rows_as_dicts(ws):
    header, *rows = ws.values
    return [dict(zip(header, row)) for row in rows]


ACME = role("Acme Inc", "Product Manager Intern", "https://acme.example.com/jobs/1")
GLOBEX = role("Globex", "Product Operations Intern", "https://globex.example.com/jobs/2")
INITECH_MBA = role("Initech", "MBA Product Manager Intern", "https://initech.example.com/jobs/3")


# --- tab creation --------------------------------------------------------------

def test_creates_roleup_tab_with_headers_dropdown_and_frozen_row():
    ss = FakeSpreadsheet([])
    ws = ensure_roleup_tab(ss)

    assert ss.added == [ROLEUP_TAB]
    assert ws.values == [ROLEUP_HEADERS]
    assert ROLEUP_HEADERS[:3] == ["Status", "First Seen", "Posted"] and len(ROLEUP_HEADERS) == 14

    validation = next(r["setDataValidation"] for r in ss.requests if "setDataValidation" in r)
    status_col = ROLEUP_HEADERS.index("Status")
    # Whole column from row 2 down: no endRowIndex.
    assert validation["range"] == {"sheetId": 99, "startRowIndex": 1,
                                   "startColumnIndex": status_col, "endColumnIndex": status_col + 1}
    values = [v["userEnteredValue"] for v in validation["rule"]["condition"]["values"]]
    assert values == ROLEUP_STATUSES == ["New", "Applied", "Skip", "Hidden"]

    frozen = next(r["updateSheetProperties"] for r in ss.requests if "updateSheetProperties" in r)
    assert frozen["properties"] == {"sheetId": 99, "gridProperties": {"frozenRowCount": 1}}


def test_existing_roleup_tab_is_left_alone():
    ss = FakeSpreadsheet([], roleup_rows=[ROLEUP_HEADERS])
    assert ensure_roleup_tab(ss) is ss.roleup
    assert ss.added == [] and ss.requests == []


# --- tracker (read-only) -------------------------------------------------------

def test_tracker_hides_role_by_role_id():
    # Decorated differently from the posting, same role_id after normalization.
    ss = FakeSpreadsheet([tracker_row("Acme", "Product Manager Intern, Summer 2027")])
    counts = sync(ss, pipeline(ACME, GLOBEX), TODAY)

    assert counts.already_applied == 1 and counts.appended_new == 1
    assert [r["Company"] for r in rows_as_dicts(ss.roleup)] == ["Globex"]


def test_tracker_hides_role_by_canonical_url():
    linkedin = role("Hooli", "Growth Intern", "https://www.linkedin.com/jobs/view/4000000001/",
                    source="linkedin")
    ss = FakeSpreadsheet([tracker_row(
        "Hooli (via agency)", "Some Other Name",
        "https://www.linkedin.com/comm/jobs/view/4000000001/?trackingId=abc&refId=x")])
    counts = sync(ss, pipeline(linkedin), TODAY)

    assert counts.already_applied == 1 and counts.appended_new == 0
    assert ss.roleup.appends == []


def test_every_tracker_row_counts_whatever_the_stage():
    rows = [tracker_row("Acme", "Product Manager Intern"), tracker_row("Globex", "Product Operations Intern")]
    rows[0][2], rows[1][2] = "", "Offer"
    ids, _ = read_tracker(FakeSpreadsheet(rows))
    assert ids == {"acme|product manager", "globex|product operations"}


def test_tracker_columns_found_by_header_name():
    ss = FakeSpreadsheet([])
    ss.tabs[TRACKER_TAB].values = [["Job URL", "Position", "Company"],
                                   ["https://acme.example.com/jobs/1?utm_source=x", "PM Intern", "Acme"]]
    ids, urls = read_tracker(ss)
    assert ids == {"acme|pm"}
    assert urls == {"https://acme.example.com/jobs/1"}


def test_tracker_missing_header_fails_loudly():
    ss = FakeSpreadsheet([])
    ss.tabs[TRACKER_TAB].values = [["Company", "Stage"]]
    with pytest.raises(ValueError, match="Position"):
        read_tracker(ss)


def test_tracker_tab_is_never_written():
    # The fake tracker raises on any write; a full sync must not trip it.
    ss = FakeSpreadsheet([tracker_row("Acme", "Product Manager Intern")])
    sync(ss, pipeline(ACME, GLOBEX, INITECH_MBA), TODAY)
    assert ss.tabs[TRACKER_TAB].values[1] == tracker_row("Acme", "Product Manager Intern")


# --- Roleup tab (append-only) ----------------------------------------------------

def test_new_row_fields():
    ss = FakeSpreadsheet([])
    other = "https://globex.example.com/jobs/2b"
    globex = role("Globex", "Product Operations Intern", "https://globex.example.com/jobs/2")
    globex_jr = role("Globex", "Product Operations Intern", other, source="jobright")
    globex_jr.date_posted = date(2026, 9, 28)
    sync(ss, pipeline(globex, globex_jr), TODAY)

    [row] = rows_as_dicts(ss.roleup)
    assert row == {
        "Status": "New", "First Seen": "2026-10-19", "Posted": "2026-09-28",
        "Category": "Operations", "Company": "Globex", "Title": "Product Operations Intern",
        "Location": "Remote", "Term": "Summer 2027", "Sources": "simplify, jobright",
        "Link": "https://globex.example.com/jobs/2", "Other Links": other,
        "Eligibility": "", "Notes": "", "Role ID": "globex|product operations",
    }


def test_first_seen_is_the_injected_today():
    rows, _ = plan_sync(pipeline(ACME), set(), set(), set(), today=date(2027, 1, 5))
    assert rows[0][ROLEUP_HEADERS.index("First Seen")] == "2027-01-05"
    assert rows[0][ROLEUP_HEADERS.index("Posted")] == "2026-10-01"


def test_grad_only_role_appended_as_hidden():
    ss = FakeSpreadsheet([])
    counts = sync(ss, pipeline(ACME, INITECH_MBA), TODAY)

    assert (counts.appended_new, counts.appended_hidden) == (1, 1)
    hidden = [r for r in rows_as_dicts(ss.roleup) if r["Company"] == "Initech"]
    assert hidden[0]["Status"] == "Hidden" and hidden[0]["Eligibility"] == "grad-only"


def test_existing_roleup_rows_not_duplicated_and_user_edits_preserved():
    ss = FakeSpreadsheet([])
    sync(ss, pipeline(ACME), TODAY)
    # The user marks the role Applied and adds a note.
    edited = list(ss.roleup.values[1])
    edited[ROLEUP_HEADERS.index("Status")] = "Applied"
    edited[ROLEUP_HEADERS.index("Notes")] = "fake note"
    ss.roleup.values[1] = edited

    counts = sync(ss, pipeline(ACME, GLOBEX), date(2026, 10, 20))

    assert counts.already_in_roleup == 1 and counts.appended_new == 1
    assert ss.roleup.values[1] == edited  # untouched
    assert [r["Company"] for r in rows_as_dicts(ss.roleup)] == ["Acme Inc", "Globex"]


def test_one_append_call_per_run():
    ss = FakeSpreadsheet([])
    sync(ss, pipeline(ACME, GLOBEX, INITECH_MBA), TODAY)
    assert len(ss.roleup.appends) == 1 and len(ss.roleup.appends[0]) == 3


def test_plan_sync_is_idempotent():
    result = pipeline(ACME, GLOBEX, INITECH_MBA)
    rows, first = plan_sync(result, set(), set(), set(), TODAY)
    assert len(rows) == 3

    ids = {row[ROLEUP_HEADERS.index("Role ID")] for row in rows}
    rows2, second = plan_sync(result, ids, set(), set(), TODAY)
    assert rows2 == []
    assert (second.already_in_roleup, second.appended_new, second.appended_hidden) == (3, 0, 0)


def test_sync_twice_appends_once():
    ss = FakeSpreadsheet([])
    sync(ss, pipeline(ACME, GLOBEX), TODAY)
    counts = sync(ss, pipeline(ACME, GLOBEX), TODAY)
    assert len(ss.roleup.appends) == 1
    assert (counts.appended_new, counts.appended_hidden) == (0, 0)


def test_formula_like_title_is_appended_raw():
    # FakeWorksheet.append_rows asserts value_input_option="RAW".
    ss = FakeSpreadsheet([])
    sync(ss, pipeline(role("Acme", "=HYPERLINK(\"x\") Product Intern", "https://a.example.com/9")), TODAY)
    assert rows_as_dicts(ss.roleup)[0]["Title"].startswith("=HYPERLINK")


# --- main: public-safe output and isolation --------------------------------------

def run_main(monkeypatch, open_spreadsheet):
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON",
                       '{"private_key": "-----FAKE KEY-----", "client_email": "bot@fake.example"}')
    monkeypatch.setenv("SHEET_ID", "fakeSheetId123")
    monkeypatch.setattr(src.main, "active_sources", lambda: {
        "simplify": lambda: SourceResult([ACME, GLOBEX, INITECH_MBA], [])})
    monkeypatch.setattr(src.sheet, "open_spreadsheet", open_spreadsheet)
    return src.main.main()


def test_main_prints_counts_and_no_tracker_content(monkeypatch, capsys):
    ss = FakeSpreadsheet([
        tracker_row("Zyxwv Tracker Co", "Secret Position Q", "https://zyxwv.example.com/apply/77"),
        tracker_row("Acme", "Product Manager Intern"),
    ])
    assert run_main(monkeypatch, lambda: ss) == 0

    out = capsys.readouterr().out
    assert ("=== Sheet sync ===\n"
            "already in Roleup tab: 0\n"
            "skipped as already applied (tracker): 1\n"
            "appended New: 1\n"
            "appended Hidden: 1\n") in out
    for secret in ("Zyxwv", "Secret Position", "zyxwv.example.com", "fakeSheetId123", "FAKE KEY"):
        assert secret not in out


def test_main_sheet_failure_is_isolated_and_masked(monkeypatch, capsys):
    def broken():
        raise RuntimeError("cannot open fakeSheetId123 as bot@fake.example")

    assert run_main(monkeypatch, broken) == 1

    out = capsys.readouterr().out
    assert "digest: 2 roles" in out  # the rest of the report still printed
    assert "=== Source failures (1) ===" in out
    assert ("  - sheet: RuntimeError: cannot open <SHEET_ID> as "
            "<service account client_email>") in out
    assert "fakeSheetId123" not in out and "bot@fake.example" not in out


def test_main_skips_sheet_without_env(monkeypatch, capsys):
    monkeypatch.setattr(src.main, "active_sources", lambda: {
        "simplify": lambda: SourceResult([ACME], [])})
    assert src.main.main() == 0
    out = capsys.readouterr().out
    assert "Sheet sync skipped: missing env vars: GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID" in out
    assert "=== Sheet sync ===" not in out
