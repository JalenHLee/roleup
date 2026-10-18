"""Tests for sources.gmail_alerts with fake emails, a fake llm, and a fake IMAP server."""

import json
from datetime import date
from pathlib import Path

import pytest

from src.sources.gmail_alerts import (
    fetch_emails,
    html_to_text,
    parse_emails,
    parse_message,
    source_for_domain,
)

FIXTURES = Path(__file__).parent / "fixtures"
LINKEDIN_RAW = (FIXTURES / "linkedin_alert.eml").read_bytes()
RADAR_RAW = (FIXTURES / "radar_alert.eml").read_bytes()


def canned_llm(by_marker: dict[str, dict]):
    """Fake llm: reply with the canned JSON whose marker text appears in the prompt."""
    def llm(prompt):
        llm.calls += 1
        for marker, response in by_marker.items():
            if marker in prompt:
                return json.dumps(response)
        return json.dumps({"roles": []})
    llm.calls = 0
    return llm


LINKEDIN_JSON = {"roles": [
    {"company": "Acme Robotics", "title": "Product Manager Intern (Summer 2027)",
     "location": "New York, NY",
     "link": "https://www.linkedin.com/comm/jobs/view/1111111111/?trk=fake&ref=alert"},
    {"company": "Globex", "title": "Growth Intern", "location": "Remote",
     "link": "https://www.linkedin.com/comm/jobs/view/2222222222/?trk=fake"},
]}
RADAR_JSON = {"roles": [
    {"company": "Initech", "title": "Associate Product Manager Intern, Summer 2027",
     "location": "Austin, TX", "link": "https://jobs.example.com/initech/apm-intern-2027"},
]}


# --- HTML to text -------------------------------------------------------------

def test_html_to_text_keeps_links_inline():
    text = html_to_text(
        '<p>See <a href="https://jobs.example.com/1?a=1&amp;b=2">PM Intern</a> now.</p>'
        '<a href="https://jobs.example.com/2"><img src="x.png"></a>'
        "<script>track()</script><style>p{}</style>"
    )
    assert "PM Intern (https://jobs.example.com/1?a=1&b=2)" in text  # &amp; unescaped
    assert "https://jobs.example.com/2" in text  # link with no text keeps the bare URL
    assert "track()" not in text and "p{}" not in text


# --- parse_message --------------------------------------------------------------

def test_parse_message_linkedin_prefers_html():
    msg = parse_message(LINKEDIN_RAW)
    assert msg["message_id"] == "<fake-linkedin-001@example.com>"
    assert msg["sender"] == "jobalerts-noreply@linkedin.com"
    assert msg["subject"] == '2 new jobs for "product manager intern"'
    assert msg["date"] == date(2026, 10, 16)
    assert "Plain-text version" not in msg["text"]
    assert ("Product Manager Intern (Summer 2027) "
            "(https://www.linkedin.com/comm/jobs/view/1111111111/?trk=fake&ref=alert)") in msg["text"]


def test_parse_message_radar():
    msg = parse_message(RADAR_RAW)
    assert msg["sender"] == "hello@mail.earlycareerradar.com"
    assert msg["date"] == date(2026, 10, 17)  # date in the sender's own timezone
    assert "(https://jobs.example.com/initech/apm-intern-2027)" in msg["text"]


def test_parse_message_bad_date_is_none():
    raw = b"From: a@linkedin.com\r\nDate: not a date\r\n\r\nhello\r\n"
    msg = parse_message(raw)
    assert msg["date"] is None and msg["text"].strip() == "hello"


# --- parse_emails ---------------------------------------------------------------

@pytest.mark.parametrize("domain, expected", [
    ("linkedin.com", "linkedin"),
    ("e.linkedin.com", "linkedin"),
    ("mail.earlycareerradar.com", "early-career-radar"),
    ("notlinkedin.com", None),  # suffix match needs a dot boundary
    ("example.com", None),
])
def test_source_for_domain(domain, expected):
    assert source_for_domain(domain) == expected


def test_parse_emails_both_senders():
    llm = canned_llm({"1111111111": LINKEDIN_JSON, "apm-intern-2027": RADAR_JSON})
    roles, errors = parse_emails([parse_message(LINKEDIN_RAW), parse_message(RADAR_RAW)], llm)
    assert errors == []
    assert [(r.company, r.sources) for r in roles] == [
        ("Acme Robotics", ["linkedin"]),
        ("Globex", ["linkedin"]),
        ("Initech", ["early-career-radar"]),
    ]
    assert roles[2].date_posted == date(2026, 10, 17)


def test_unknown_sender_is_error_and_llm_not_called():
    msg = parse_message(LINKEDIN_RAW) | {"sender": "a.friend@example.com"}
    llm = canned_llm({})
    roles, errors = parse_emails([msg], llm)
    assert roles == [] and llm.calls == 0
    assert len(errors) == 1 and "unknown sender" in errors[0]
    assert "a.friend" not in errors[0]  # only the domain is reported


def test_missing_date_is_error():
    msg = parse_message(RADAR_RAW) | {"date": None}
    roles, errors = parse_emails([msg], canned_llm({}))
    assert roles == [] and len(errors) == 1 and "Date" in errors[0]


def test_llm_failure_is_error_for_that_email_only():
    def flaky_llm(prompt):
        if "linkedin" in prompt:
            raise RuntimeError("overloaded")
        return json.dumps(RADAR_JSON)

    roles, errors = parse_emails([parse_message(LINKEDIN_RAW), parse_message(RADAR_RAW)], flaky_llm)
    assert [r.company for r in roles] == ["Initech"]
    assert len(errors) == 1 and "LLM call failed" in errors[0] and "fake-linkedin-001" in errors[0]


def test_item_errors_are_prefixed_with_email_ref():
    bad = {"roles": [{"company": "Acme", "title": "PM Intern", "location": "",
                      "link": "https://made-up.example.com/job"}]}
    _, errors = parse_emails([parse_message(RADAR_RAW)], canned_llm({"Initech": bad}))
    assert errors == ["email <fake-radar-001@example.com> from mail.earlycareerradar.com: "
                      "role #0 (PM Intern): link not found in email"]


# --- fetch_emails (fake IMAP) --------------------------------------------------

class FakeIMAP:
    """Records calls; serves two fixture emails."""

    def __init__(self, host):
        self.host, self.calls = host, []
        FakeIMAP.last = self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append(("logout",))

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"2"]

    def search(self, charset, *criteria):
        self.calls.append(("search", *criteria))
        return "OK", [b"1 2"]

    def fetch(self, num, parts):
        self.calls.append(("fetch", num, parts))
        raw = LINKEDIN_RAW if num == b"1" else RADAR_RAW
        return "OK", [(b"header", raw)]


@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "student@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake-app-password")


def test_fetch_emails_reads_label_read_only(fake_env):
    emails = fetch_emails(imap_cls=FakeIMAP, today=date(2026, 10, 18))
    imap = FakeIMAP.last
    assert imap.host == "imap.gmail.com"
    assert ("login", "student@example.com", "fake-app-password") in imap.calls
    assert ("select", '"job-alerts"', True) in imap.calls
    assert ("search", "SINCE", "16-Oct-2026") in imap.calls  # 2-day lookback
    assert all(c[2] == "(BODY.PEEK[])" for c in imap.calls if c[0] == "fetch")  # stay unread
    assert imap.calls[-1] == ("logout",)
    assert [e["message_id"] for e in emails] == [
        "<fake-linkedin-001@example.com>", "<fake-radar-001@example.com>"]


def test_fetch_emails_missing_env_raises(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake-app-password")
    with pytest.raises(RuntimeError, match="GMAIL_ADDRESS"):
        fetch_emails(imap_cls=FakeIMAP)


def test_fetch_emails_missing_label_raises(fake_env):
    class NoLabelIMAP(FakeIMAP):
        def select(self, mailbox, readonly=False):
            return "NO", [b"[NONEXISTENT] Unknown Mailbox"]

    with pytest.raises(RuntimeError, match="job-alerts"):
        fetch_emails(imap_cls=NoLabelIMAP)


def test_real_apis_are_blocked_in_tests(fake_env):
    # Sanity check on conftest: the default IMAP class is the blocked stub.
    with pytest.raises(AssertionError, match="must not call"):
        fetch_emails()
