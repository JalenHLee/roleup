"""Shared test setup: no test may reach the real Gmail or Anthropic APIs."""

import imaplib

import pytest

import src.llm_extract
import src.sources.gmail_alerts


def _blocked(*args, **kwargs):
    raise AssertionError("tests must not call real Gmail or Anthropic APIs")


@pytest.fixture(autouse=True)
def block_real_apis(monkeypatch):
    monkeypatch.setattr(src.llm_extract, "call_claude", _blocked)
    monkeypatch.setattr(src.sources.gmail_alerts, "call_claude", _blocked)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _blocked)
    monkeypatch.setattr(imaplib, "IMAP4", _blocked)
