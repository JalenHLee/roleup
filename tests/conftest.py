"""Shared test setup: no test may reach the real Gmail, Anthropic, Google, or SMTP servers."""

import imaplib
import smtplib

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
    monkeypatch.setattr(smtplib, "SMTP_SSL", _blocked)
    monkeypatch.setattr(smtplib, "SMTP", _blocked)
    # main's Gmail source, sheet sync, and digest run only with these set;
    # a developer's shell must not leak in.
    for name in ("GOOGLE_SERVICE_ACCOUNT_JSON", "SHEET_ID", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD",
                 "ANTHROPIC_API_KEY", "DIGEST_TO", "ROLEUP_FORCE_SEND"):
        monkeypatch.delenv(name, raising=False)
