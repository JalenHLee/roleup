"""Shared test setup: no test may reach the real Gmail, Anthropic, or Google APIs."""

import imaplib

import gspread
import pytest

import src.llm_extract
import src.sheet


def _blocked(*args, **kwargs):
    raise AssertionError("tests must not call real Gmail, Anthropic, or Google APIs")


@pytest.fixture(autouse=True)
def block_real_apis(monkeypatch):
    monkeypatch.setattr(src.llm_extract, "call_claude", _blocked)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _blocked)
    monkeypatch.setattr(imaplib, "IMAP4", _blocked)
    monkeypatch.setattr(src.sheet, "open_spreadsheet", _blocked)
    monkeypatch.setattr(gspread, "authorize", _blocked)
    # main's sheet sync runs only with these set; a developer's shell must not leak in.
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("SHEET_ID", raising=False)
