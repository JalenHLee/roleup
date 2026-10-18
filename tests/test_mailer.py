"""Tests for the SMTP mailer, with a fake SMTP class (no network)."""

from src import mailer
from src.config import SMTP_HOST, SMTP_PORT


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.logins, self.sent = [], []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.logins.append((user, password))

    def send_message(self, msg):
        self.sent.append(msg)


def test_send_email_logs_in_and_sends_multipart(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setenv("GMAIL_ADDRESS", "bot@fake.example")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake app password")

    mailer.send_email("Subj", "<p>hi</p>", "hi", smtp_class=FakeSMTP)

    [smtp] = FakeSMTP.instances
    assert (smtp.host, smtp.port) == (SMTP_HOST, SMTP_PORT) == ("smtp.gmail.com", 465)
    assert smtp.timeout
    assert smtp.logins == [("bot@fake.example", "fake app password")]
    [msg] = smtp.sent
    assert msg["Subject"] == "Subj"
    assert msg["From"] == msg["To"] == "bot@fake.example"  # DIGEST_TO unset -> self
    assert msg.get_body(("plain",)).get_content().strip() == "hi"
    assert msg.get_body(("html",)).get_content().strip() == "<p>hi</p>"


def test_digest_to_overrides_recipient(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "bot@fake.example")
    monkeypatch.setenv("DIGEST_TO", "me@fake.example")
    assert mailer.build_message("s", "<p>h</p>", "t")["To"] == "me@fake.example"
