"""Send the digest email over Gmail SMTP (SSL) with the Gmail app password.

From GMAIL_ADDRESS to DIGEST_TO (defaults to GMAIL_ADDRESS). Credentials and
addresses come from env vars only. The SMTP class is injected so tests never
touch the network.
"""

import os
import smtplib
from email.message import EmailMessage

from src.config import SMTP_HOST, SMTP_PORT, SMTP_TIMEOUT_SECONDS


def build_message(subject: str, html: str, text: str) -> EmailMessage:
    sender = os.environ["GMAIL_ADDRESS"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = os.environ.get("DIGEST_TO") or sender
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send_email(subject: str, html: str, text: str, smtp_class=None) -> None:
    """Send one multipart (text + HTML) email. Raises on any SMTP error."""
    msg = build_message(subject, html, text)
    smtp_class = smtp_class or smtplib.SMTP_SSL  # looked up at call time, so tests can block it
    with smtp_class(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        smtp.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        smtp.send_message(msg)
