from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

def register(mcp) -> None:
    @mcp.tool(
        annotations={
            "title": "Send a notification",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True
        }
    )
    def send_notification(to: str, subject: str, body: str, attachment_path: str | None = None) -> dict:
        """Send a notification email or message to the NOC team.
        
        Args:
            to: Recipient address (e.g., noc@nt.co.th)
            subject: The subject of the notification
            body: The main content/summary to send
            attachment_path: Optional path to a report file to attach
        """
        backend = os.getenv("NOTIFIER_BACKEND", "email")

        if backend == "email":
            msg = EmailMessage()
            msg.set_content(body)
            msg["Subject"] = subject
            msg["From"] = "mcp-agent@nt.co.th"
            msg["To"] = to

            if attachment_path:
                path = Path(attachment_path)
                if path.exists():
                    msg.add_attachment(
                        path.read_bytes(),
                        maintype="text",
                        subtype=path.suffix.lstrip('.') or "plain",
                        filename=path.name
                    )

            try:
                with smtplib.SMTP("localhost", 1025) as server:
                    server.send_message(msg)
                return {"ok": True, "method": "email", "status": f"Sent successfully to {to}"}
            except Exception as e:
                return {"ok": False, "error": f"Failed to send email: {e}"}

        elif backend == "telegram":
            return {"ok": True, "method": "telegram", "status": "Telegram backend selected (Mock)"}

        return {"ok": False, "error": f"Unknown backend: {backend}"}