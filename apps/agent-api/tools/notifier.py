"""Notification delivery with swappable backends.

The curriculum asks for an agent that can send email. The production system
this workshop models sends Telegram alerts instead. Rather than pick one, the
agent calls a single `notify()` and the backend is configuration.

That indirection is the actual lesson: the agent should describe WHAT to send
and to WHOM, never how the transport works. Changing channel then costs one
environment variable rather than a rewrite of the agent.

Backends:
  mailhog   SMTP to the local MailHog container. Nothing leaves the machine.
            Inspect delivered mail at http://localhost:8025
  telegram  a local mock endpoint with the same shape as the Telegram bot API,
            so the call site matches production without needing a real token.
  console   print to stdout. Used by tests.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

import httpx

BACKEND = os.getenv("NOTIFIER_BACKEND", "mailhog")
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
NOTIFY_TO = os.getenv("NOTIFY_TO", "noc@example.local")
TELEGRAM_MOCK_URL = os.getenv("TELEGRAM_MOCK_URL", "http://localhost:8099/telegram")


def _send_mailhog(subject: str, body: str, to: str, attachment: str | None) -> dict:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "ai-assistant@nt.local"
    message["To"] = to
    message.set_content(body)

    if attachment and os.path.exists(attachment):
        with open(attachment, "rb") as handle:
            data = handle.read()
        message.add_attachment(
            data, maintype="text", subtype="plain",
            filename=os.path.basename(attachment),
        )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.send_message(message)

    return {"ok": True, "backend": "mailhog", "to": to,
            "inspect_at": "http://localhost:8025"}


def _send_telegram(subject: str, body: str, to: str) -> dict:
    payload = {"chat_id": to, "text": f"*{subject}*\n\n{body}", "parse_mode": "Markdown"}
    response = httpx.post(TELEGRAM_MOCK_URL, json=payload, timeout=10)
    response.raise_for_status()
    return {"ok": True, "backend": "telegram", "to": to}


def notify(subject: str, body: str, to: str | None = None,
           attachment: str | None = None) -> dict:
    """Send a notification through the configured backend.

    Args:
        subject: short headline
        body: message text
        to: recipient. Defaults to the configured NOC address or chat.
        attachment: optional path to a generated report file
    """
    to = to or NOTIFY_TO
    try:
        if BACKEND == "mailhog":
            return _send_mailhog(subject, body, to, attachment)
        if BACKEND == "telegram":
            return _send_telegram(subject, body, to)
        print(f"\n[NOTIFY] to={to}\nsubject={subject}\n{body}\n")
        return {"ok": True, "backend": "console", "to": to}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "backend": BACKEND, "error": f"{type(exc).__name__}: {exc}"}
