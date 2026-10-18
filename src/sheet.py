"""Google Sheet sync: append new roles to the Roleup tab, skipping applied ones.

Rules:
  - The tracker tab (config TRACKER_TAB) is READ-ONLY. Every row counts as already
    applied; roles are matched by role_id (Company + Position, same normalization
    as dedupe) or by any canonical link (Job URL).
  - The Roleup tab is APPEND-ONLY: existing rows are never modified or deleted, so
    the user's edits (Status, Notes) are never overwritten. One batched append per run.
  - Identity: a role is already in the Roleup tab if its role_id OR any of its
    canonical links is there. Links (e.g. LinkedIn /jobs/view/<id>/) stay stable
    when the alert-email AI's text varies between runs.
  - The user owns the layout: rows are written by header name in row 1's order;
    unknown columns stay blank; an existing tab's validation/formatting is never
    touched. The bot only ever writes Status "New" or "Hidden".
  - Nothing here prints. main prints only the counts (Actions logs are public).

open_spreadsheet is the only network entry point; everything else takes the
spreadsheet object as a parameter, so tests pass an in-memory fake.
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

from src.config import (
    ROLEUP_HEADERS,
    ROLEUP_HIDDEN_HEADERS,
    ROLEUP_ID_HEADER,
    ROLEUP_LINK_HEADER,
    ROLEUP_OTHER_LINKS_HEADER,
    ROLEUP_REQUIRED_HEADERS,
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
LINK_SPLIT_RE = re.compile(r",\s+")  # Other Links is ", "-separated


@dataclass
class SyncCounts:
    already_in_roleup: int = 0  # same role_id
    already_in_roleup_by_link: int = 0  # different role_id, but a link is already there
    already_applied: int = 0  # matched the tracker tab
    appended_new: int = 0
    appended_hidden: int = 0


def open_spreadsheet() -> gspread.Spreadsheet:
    """Open the spreadsheet from GOOGLE_SERVICE_ACCOUNT_JSON (a JSON string) and SHEET_ID."""
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds).open_by_key(os.environ["SHEET_ID"])


@dataclass
class RoleupIndex:
    """What the Roleup tab already holds: role_ids and canonical links."""

    ids: set[str] = field(default_factory=set)
    links: set[str] = field(default_factory=set)


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
    """Return the Roleup worksheet, creating it if missing.

    Only a fresh tab gets the layout: headers, a Status dropdown, a frozen header
    row, and the ROLEUP_HIDDEN_HEADERS columns hidden. An existing tab is returned
    untouched: no header, validation, or formatting change, ever.
    """
    try:
        return spreadsheet.worksheet(ROLEUP_TAB)
    except gspread.WorksheetNotFound:
        pass

    ws = spreadsheet.add_worksheet(title=ROLEUP_TAB, rows=1000, cols=len(ROLEUP_HEADERS))
    ws.update(range_name="A1", values=[ROLEUP_HEADERS])
    status_col = ROLEUP_HEADERS.index("Status")
    requests = [
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
    ]
    for name in ROLEUP_HIDDEN_HEADERS:
        col = ROLEUP_HEADERS.index(name)
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": col, "endIndex": col + 1},
            "properties": {"hiddenByUser": True},
            "fields": "hiddenByUser",
        }})
    spreadsheet.batch_update({"requests": requests})
    return ws


def roleup_headers(values: list[list[str]]) -> list[str]:
    """Row 1 of the Roleup tab, trimmed. Missing required headers -> fail loudly."""
    headers = [h.strip() for h in values[0]] if values else []
    missing = [h for h in ROLEUP_REQUIRED_HEADERS if h not in headers]
    if missing:
        raise ValueError(f"{ROLEUP_TAB!r} tab is missing required headers: {', '.join(missing)}")
    return headers


def read_roleup(values: list[list[str]]) -> RoleupIndex:
    """Index the Roleup tab's rows (any Status): role_ids and canonical links.

    ids holds each row's stored Role ID and also role_id_from(Company, Title)
    recomputed now, so a change to role_id normalization never re-appends old rows.
    """
    headers = roleup_headers(values)
    id_col = headers.index(ROLEUP_ID_HEADER)
    company_col, title_col = headers.index("Company"), headers.index("Title")
    link_cols = [headers.index(ROLEUP_LINK_HEADER)]
    if ROLEUP_OTHER_LINKS_HEADER in headers:
        link_cols.append(headers.index(ROLEUP_OTHER_LINKS_HEADER))

    index = RoleupIndex()
    for row in values[1:]:
        if _cell(row, id_col):
            index.ids.add(_cell(row, id_col))
        if _cell(row, company_col) and _cell(row, title_col):
            index.ids.add(role_id_from(_cell(row, company_col), _cell(row, title_col)))
        for col in link_cols:
            for link in LINK_SPLIT_RE.split(_cell(row, col)):
                if link.strip():
                    index.links.add(canonicalize(link))
    return index


def _record(role: Role, status: str, today: date) -> dict[str, str]:
    """One role as {header name: value}; laid out by the tab's own header order later."""
    links = role.links or [role.link]
    return {
        "Status": status,
        "Company": role.company,
        "Title": role.title,
        "Category": role.category or "",
        "Location": role.location,
        "Posted": role.date_posted.isoformat(),
        "Link": role.link,
        "Notes": "",
        "First Seen": today.isoformat(),  # the run that first added the row
        "Term": role.term,
        "Sources": ", ".join(role.sources),
        "Other Links": ", ".join(link for link in links if link != role.link),
        "Eligibility": role.eligibility_flag,
        "Role ID": role.role_id,
    }


def ordered_row(record: dict[str, str], headers: list[str]) -> list[str]:
    """Lay a record out in the tab's header order. Unknown columns stay blank; a
    repeated header name is filled only in its first column."""
    row, filled = [], set()
    for h in headers:
        row.append("" if h in filled else record.get(h, ""))
        if h in record:
            filled.add(h)
    return row


def plan_sync(
    pipeline_result: PipelineResult,
    roleup: RoleupIndex,
    applied_ids: set[str],
    applied_urls: set[str],
    today: date,
) -> tuple[list[dict[str, str]], SyncCounts]:
    """Pure: the records to append and the counts. Digest roles are "New", hidden ones "Hidden".

    A role is skipped if its role_id or any canonical link is already in the Roleup
    tab (or earlier in this batch), or if it matches the tracker.
    """
    counts = SyncCounts()
    records = []
    seen_ids, seen_links = set(roleup.ids), set(roleup.links)
    batches = [(pipeline_result.digest, STATUS_NEW), (pipeline_result.hidden, STATUS_HIDDEN)]
    for roles, status in batches:
        for role in sorted(roles, key=lambda r: (r.category or "", r.company.lower())):
            links = {canonicalize(link) for link in (role.links or [role.link])}
            if role.role_id in seen_ids:
                counts.already_in_roleup += 1
                continue
            if links & seen_links:
                counts.already_in_roleup_by_link += 1
                continue
            if role.role_id in applied_ids or links & applied_urls:
                counts.already_applied += 1
                continue
            seen_ids.add(role.role_id)
            seen_links |= links
            records.append(_record(role, status, today))
            if status == STATUS_NEW:
                counts.appended_new += 1
            else:
                counts.appended_hidden += 1
    return records, counts


def sync(
    spreadsheet, pipeline_result: PipelineResult, today: date,
) -> tuple[list[dict[str, str]], SyncCounts]:
    """Read the tracker, ensure the Roleup tab, and append new rows in one call.

    Returns (the records actually appended, counts); the digest lists exactly those.
    """
    applied_ids, applied_urls = read_tracker(spreadsheet)
    worksheet = ensure_roleup_tab(spreadsheet)
    values = worksheet.get_all_values()
    headers = roleup_headers(values)  # before planning, so a bad tab fails before any write
    records, counts = plan_sync(pipeline_result, read_roleup(values),
                                applied_ids, applied_urls, today)
    if records:
        # RAW: values are stored as typed text, so a title like "=HYPERLINK(...)"
        # from an alert email is never evaluated as a formula.
        worksheet.append_rows([ordered_row(r, headers) for r in records],
                              value_input_option="RAW",
                              insert_data_option="INSERT_ROWS", table_range="A1")
    return records, counts
