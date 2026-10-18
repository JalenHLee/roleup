"""Google Sheet sync: append new roles to the Roleup tab, skipping applied ones.

Rules:
  - The tracker tab (config TRACKER_TAB) is READ-ONLY. Every row counts as already
    applied; roles are matched by role_id (Company + Position, same normalization
    as dedupe) or by any canonical link (Job URL).
  - The Roleup tab is APPEND-ONLY: existing rows are never modified or deleted, so
    the user's edits (Status, Notes) are never overwritten. One batched append per run.
  - Nothing here prints. main prints only the counts (Actions logs are public).

open_spreadsheet is the only network entry point; everything else takes the
spreadsheet object as a parameter, so tests pass an in-memory fake.
"""

import json
import os
from dataclasses import dataclass
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

from src.config import (
    ROLEUP_HEADERS,
    ROLEUP_ID_HEADER,
    ROLEUP_STATUSES,
    ROLEUP_TAB,
    TRACKER_COMPANY_HEADER,
    TRACKER_POSITION_HEADER,
    TRACKER_TAB,
    TRACKER_URL_HEADER,
)
from src.dedupe import role_id_from
from src.links import canonicalize
from src.models import Role
from src.pipeline import PipelineResult

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
STATUS_NEW = "New"
STATUS_HIDDEN = "Hidden"  # eligibility-flagged: in the sheet, not in the digest


@dataclass
class SyncCounts:
    already_in_roleup: int = 0
    already_applied: int = 0  # matched the tracker tab
    appended_new: int = 0
    appended_hidden: int = 0


def open_spreadsheet() -> gspread.Spreadsheet:
    """Open the spreadsheet from GOOGLE_SERVICE_ACCOUNT_JSON (a JSON string) and SHEET_ID."""
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds).open_by_key(os.environ["SHEET_ID"])


def _column(headers: list[str], name: str, tab: str) -> int:
    """Index of a header in row 1 (whitespace-insensitive). Missing -> fail loudly."""
    cleaned = [h.strip() for h in headers]
    if name not in cleaned:
        raise ValueError(f"{tab!r} tab has no {name!r} header in row 1")
    return cleaned.index(name)


def _cell(row: list[str], i: int) -> str:
    return row[i].strip() if i < len(row) else ""  # the API drops trailing blank cells


def read_tracker(spreadsheet) -> tuple[set[str], set[str]]:
    """Return (applied role_ids, applied canonical URLs) from the tracker tab. Read-only."""
    values = spreadsheet.worksheet(TRACKER_TAB).get_all_values()
    headers = values[0] if values else []
    company = _column(headers, TRACKER_COMPANY_HEADER, TRACKER_TAB)
    position = _column(headers, TRACKER_POSITION_HEADER, TRACKER_TAB)
    url = _column(headers, TRACKER_URL_HEADER, TRACKER_TAB)

    applied_ids, applied_urls = set(), set()
    for row in values[1:]:
        if _cell(row, company) and _cell(row, position):
            applied_ids.add(role_id_from(_cell(row, company), _cell(row, position)))
        if _cell(row, url):
            applied_urls.add(canonicalize(_cell(row, url)))
    return applied_ids, applied_urls


def ensure_roleup_tab(spreadsheet):
    """Return the Roleup worksheet, creating it (headers, Status dropdown, frozen row 1) if missing."""
    try:
        return spreadsheet.worksheet(ROLEUP_TAB)
    except gspread.WorksheetNotFound:
        pass

    ws = spreadsheet.add_worksheet(title=ROLEUP_TAB, rows=1000, cols=len(ROLEUP_HEADERS))
    ws.update(range_name="A1", values=[ROLEUP_HEADERS])
    status_col = ROLEUP_HEADERS.index("Status")
    spreadsheet.batch_update({"requests": [
        {"setDataValidation": {
            # No endRowIndex: the whole column from row 2 down, so appended rows
            # beyond the initial grid keep the dropdown.
            "range": {"sheetId": ws.id, "startRowIndex": 1,
                      "startColumnIndex": status_col, "endColumnIndex": status_col + 1},
            "rule": {
                "condition": {"type": "ONE_OF_LIST",
                              "values": [{"userEnteredValue": s} for s in ROLEUP_STATUSES]},
                "strict": True,
                "showCustomUi": True,
            },
        }},
        {"updateSheetProperties": {
            "properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }},
    ]})
    return ws


def read_roleup_ids(worksheet) -> set[str]:
    """role_ids already in the Roleup tab (any Status)."""
    values = worksheet.get_all_values()
    col = _column(values[0] if values else [], ROLEUP_ID_HEADER, ROLEUP_TAB)
    return {_cell(row, col) for row in values[1:] if _cell(row, col)}


def _row(role: Role, status: str, today: date) -> list[str]:
    links = role.links or [role.link]
    fields = {
        "Status": status,
        "First Seen": today.isoformat(),  # the run that first added the row
        "Posted": role.date_posted.isoformat(),
        "Category": role.category or "",
        "Company": role.company,
        "Title": role.title,
        "Location": role.location,
        "Term": role.term,
        "Sources": ", ".join(role.sources),
        "Link": role.link,
        "Other Links": ", ".join(link for link in links if link != role.link),
        "Eligibility": role.eligibility_flag,
        "Notes": "",
        "Role ID": role.role_id,
    }
    return [fields[h] for h in ROLEUP_HEADERS]


def plan_sync(
    pipeline_result: PipelineResult,
    roleup_ids: set[str],
    applied_ids: set[str],
    applied_urls: set[str],
    today: date,
) -> tuple[list[list[str]], SyncCounts]:
    """Pure: the rows to append and the counts. Digest roles are "New", hidden ones "Hidden"."""
    counts = SyncCounts()
    rows = []
    seen = set(roleup_ids)  # also guards a role_id repeating within this batch
    batches = [(pipeline_result.digest, STATUS_NEW), (pipeline_result.hidden, STATUS_HIDDEN)]
    for roles, status in batches:
        for role in sorted(roles, key=lambda r: (r.category or "", r.company.lower())):
            if role.role_id in seen:
                counts.already_in_roleup += 1
                continue
            links = {canonicalize(link) for link in (role.links or [role.link])}
            if role.role_id in applied_ids or links & applied_urls:
                counts.already_applied += 1
                continue
            seen.add(role.role_id)
            rows.append(_row(role, status, today))
            if status == STATUS_NEW:
                counts.appended_new += 1
            else:
                counts.appended_hidden += 1
    return rows, counts


def sync(spreadsheet, pipeline_result: PipelineResult, today: date) -> SyncCounts:
    """Read the tracker, ensure the Roleup tab, and append new rows in one call."""
    applied_ids, applied_urls = read_tracker(spreadsheet)
    worksheet = ensure_roleup_tab(spreadsheet)
    rows, counts = plan_sync(pipeline_result, read_roleup_ids(worksheet),
                             applied_ids, applied_urls, today)
    if rows:
        # RAW: values are stored as typed text, so a title like "=HYPERLINK(...)"
        # from an alert email is never evaluated as a formula.
        worksheet.append_rows(rows, value_input_option="RAW",
                              insert_data_option="INSERT_ROWS", table_range="A1")
    return counts
