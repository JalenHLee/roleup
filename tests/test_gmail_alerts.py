"""Tests for sources.gmail_alerts with fake emails, a fake llm, and a fake IMAP server."""

import json
from datetime import date
from pathlib import Path

import pytest

from src.sources.gmail_alerts import (
    EmailResult,
    fetch_emails,
    html_to_text,
    parse_emails,
    parse_message,
    short_id,
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


# Link IDs follow the order links appear in each fixture email.
LINKEDIN_JSON = {"roles": [
    {"company": "Acme Robotics", "title": "Product Manager Intern (Summer 2027)",
     "location": "New York, NY", "link_id": "L1"},
    {"company": "Globex", "title": "Growth Intern", "location": "Remote", "link_id": "L2"},
]}
RADAR_JSON = {"roles": [
    {"company": "Initech", "title": "Associate Product Manager Intern, Summer 2027",
     "location": "Austin, TX", "link_id": "L1"},
]}
LINKEDIN_ID = short_id("<fake-linkedin-001@example.com>")
RADAR_ID = short_id("<fake-radar-001@example.com>")


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
    roles, errors, report = parse_emails(
        [parse_message(LINKEDIN_RAW), parse_message(RADAR_RAW)], llm)
    assert errors == []
    assert [(r.company, r.sources, r.link) for r in roles] == [
        ("Acme Robotics", ["linkedin"], "https://www.linkedin.com/jobs/view/1111111111/"),
        ("Globex", ["linkedin"], "https://www.linkedin.com/jobs/view/2222222222/"),
        ("Initech", ["early-career-radar"], "https://jobs.example.com/initech/apm-intern-2027"),
    ]
    assert roles[2].date_posted == date(2026, 10, 17)
    assert report == [
        EmailResult("linkedin.com", LINKEDIN_ID, "linkedin", roles=2, errors=0),
        EmailResult("mail.earlycareerradar.com", RADAR_ID, "early-career-radar", roles=1, errors=0),
    ]


def test_short_id_is_stable_hash():
    assert short_id("<fake-linkedin-001@example.com>") == LINKEDIN_ID
    assert len(LINKEDIN_ID) == 8 and LINKEDIN_ID != RADAR_ID
    assert "fake" not in LINKEDIN_ID
    assert short_id("") == "????????"


def test_unknown_sender_is_error_and_llm_not_called():
    msg = parse_message(LINKEDIN_RAW) | {"sender": "a.friend@example.com"}
    llm = canned_llm({})
    roles, errors, report = parse_emails([msg], llm)
    assert roles == [] and llm.calls == 0
    assert errors == [f"email #{LINKEDIN_ID} from example.com: unknown sender domain"]
    assert report == [EmailResult("example.com", LINKEDIN_ID, None, roles=0, errors=1)]


def test_missing_date_is_error():
    msg = parse_message(RADAR_RAW) | {"date": None}
    roles, errors, report = parse_emails([msg], canned_llm({}))
    assert roles == [] and len(errors) == 1 and "Date" in errors[0]
    assert report[0].errors == 1


def test_llm_failure_is_error_for_that_email_only():
    def flaky_llm(prompt):
        if "linkedin" in prompt:
            raise RuntimeError("overloaded")
        return json.dumps(RADAR_JSON)

    roles, errors, report = parse_emails(
        [parse_message(LINKEDIN_RAW), parse_message(RADAR_RAW)], flaky_llm)
    assert [r.company for r in roles] == ["Initech"]
    assert len(errors) == 1 and "LLM call failed" in errors[0] and f"#{LINKEDIN_ID}" in errors[0]
    assert [(r.roles, r.errors) for r in report] == [(0, 1), (1, 0)]


def test_item_errors_use_hashed_id_never_message_id():
    bad = {"roles": [{"company": "Acme", "title": "PM Intern", "location": "", "link_id": "L9"},
                     RADAR_JSON["roles"][0]]}
    roles, errors, report = parse_emails([parse_message(RADAR_RAW)], canned_llm({"Initech": bad}))
    assert [r.company for r in roles] == ["Initech"]  # other role kept
    assert errors == [f"email #{RADAR_ID} from mail.earlycareerradar.com: "
                      "role #0 (PM Intern): unknown link_id 'L9'"]
    assert "fake-radar-001" not in errors[0]
    assert report == [EmailResult("mail.earlycareerradar.com", RADAR_ID, "early-career-radar",
                                  roles=1, errors=1)]


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


# --- Q2 case: company on its own line and in "Company · Location" -------------

Q2_RAW = (FIXTURES / "linkedin_q2_alert.eml").read_bytes()
Q2_TITLE = "2027 Summer Internship - Product Operations"


def test_q2_email_text_has_title_company_and_location_lines():
    text = parse_message(Q2_RAW)["text"].splitlines()
    i = next(n for n, line in enumerate(text) if line.startswith(Q2_TITLE))
    assert text[i + 1] == "Q2"
    assert text[i + 2] == "Q2 · Austin, Texas, United States"


def test_q2_expected_structure_validates():
    llm = canned_llm({"3333333333": {"roles": [
        {"company": "Q2", "title": Q2_TITLE, "location": "Austin, Texas, United States",
         "link_id": "L1"}]}})
    [role], errors, [result] = parse_emails([parse_message(Q2_RAW)], llm)
    assert errors == [] and result.title_fixes == []
    assert (role.company, role.title, role.location) == ("Q2", Q2_TITLE, "Austin, Texas, United States")
    assert role.link == "https://www.linkedin.com/jobs/view/3333333333/"
    assert role.term == "Summer 2027"


def test_q2_company_appended_to_title_is_stripped_and_counted():
    llm = canned_llm({"3333333333": {"roles": [
        {"company": "Q2", "title": Q2_TITLE + " Q2", "location": "Austin, Texas, United States",
         "link_id": "L1"}]}})
    [role], errors, [result] = parse_emails([parse_message(Q2_RAW)], llm)
    assert errors == [] and role.title == Q2_TITLE
    assert result.title_fixes == [(Q2_TITLE + " Q2", Q2_TITLE)]


def test_q2_empty_company_recovered_from_subtitle_and_counted():
    # Live failure: company "" and "Q2" appended to the title.
    llm = canned_llm({"3333333333": {"roles": [
        {"company": "", "title": Q2_TITLE + " Q2", "location": "",
         "subtitle": "Q2 · Austin, Texas, United States", "link_id": "L1"}]}})
    [role], errors, [result] = parse_emails([parse_message(Q2_RAW)], llm)
    assert errors == []
    assert (role.company, role.title, role.location) == ("Q2", Q2_TITLE, "Austin, Texas, United States")
    assert result.company_recoveries == 1
    assert result.title_fixes == [(Q2_TITLE + " Q2", Q2_TITLE)]


def test_prompt_tells_llm_not_to_append_company():
    llm = canned_llm({})
    llm_prompts = []
    parse_emails([parse_message(Q2_RAW)], lambda p: llm_prompts.append(p) or llm(p))
    [prompt] = llm_prompts
    assert '"Company · Location"' in prompt
    assert "never add the company name to the title" in prompt
