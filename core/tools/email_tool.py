"""
ARIA - Email Tool
==================

Send emails via SMTP.
Supports plain text and HTML emails with optional attachments.
Requires SMTP configuration in config.yaml or environment variables.

Config example (config.yaml):
    email:
      smtp_host: "smtp.gmail.com"
      smtp_port: 587
      smtp_user: "${EMAIL_USER}"
      smtp_password: "${EMAIL_PASSWORD}"
      from_address: "aria@example.com"
      from_name: "ARIA"
      use_tls: true
"""

import logging
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.email")


def _resolve_env(value: str) -> str:
    """Resolve ${ENV_VAR} references in config values."""
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        env_name = value[2:-1]
        return os.environ.get(env_name, value)
    return value


class EmailTool(ToolBase):
    """Send emails via SMTP."""

    name = "email"
    description = (
        "Send emails to one or more recipients. "
        "Actions: send (compose and send), test (verify SMTP connection). "
        "Requires SMTP configuration in config.yaml or environment variables."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action: send or test",
            required=True,
            enum=["send", "test"],
        ),
        ToolParam(
            name="to",
            type="string",
            description="Recipient email address(es), comma-separated",
            required=False,
        ),
        ToolParam(
            name="subject",
            type="string",
            description="Email subject line",
            required=False,
        ),
        ToolParam(
            name="body",
            type="string",
            description="Email body (plain text)",
            required=False,
        ),
        ToolParam(
            name="html",
            type="string",
            description="Email body (HTML, optional alternative to body)",
            required=False,
        ),
        ToolParam(
            name="attachment",
            type="string",
            description="Path to file to attach (optional)",
            required=False,
        ),
    ]

    def __init__(self, context=None):
        super().__init__(context)
        self._config = self._load_config()

    def _load_config(self) -> dict:
        """Load SMTP config from context or environment."""
        config = self.context.get("config", {})
        email_config = config.get("email", {})

        return {
            "smtp_host": _resolve_env(email_config.get("smtp_host", os.environ.get("SMTP_HOST", ""))),
            "smtp_port": int(email_config.get("smtp_port", os.environ.get("SMTP_PORT", "587"))),
            "smtp_user": _resolve_env(email_config.get("smtp_user", os.environ.get("SMTP_USER", ""))),
            "smtp_password": _resolve_env(email_config.get("smtp_password", os.environ.get("SMTP_PASSWORD", ""))),
            "from_address": _resolve_env(email_config.get("from_address", os.environ.get("EMAIL_FROM", ""))),
            "from_name": email_config.get("from_name", "ARIA"),
            "use_tls": email_config.get("use_tls", True),
        }

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]

        if action == "test":
            return self._test_connection()
        elif action == "send":
            return self._send(kwargs)

        return ToolResult(success=False, error=f"Unknown action: {action}")

    def _test_connection(self) -> ToolResult:
        """Test SMTP connection."""
        cfg = self._config
        if not cfg["smtp_host"]:
            return ToolResult(
                success=False,
                error="SMTP not configured. Set smtp_host in config.yaml or SMTP_HOST env var.",
            )

        try:
            if cfg["use_tls"]:
                server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=10)
                server.starttls()
            else:
                server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=10)

            if cfg["smtp_user"] and cfg["smtp_password"]:
                server.login(cfg["smtp_user"], cfg["smtp_password"])

            server.quit()

            return ToolResult(
                success=True,
                output=f"SMTP connection OK: {cfg['smtp_host']}:{cfg['smtp_port']}",
                data={"host": cfg["smtp_host"], "port": cfg["smtp_port"]},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"SMTP connection failed: {e}")

    def _send(self, kwargs) -> ToolResult:
        """Send an email."""
        cfg = self._config

        if not cfg["smtp_host"]:
            return ToolResult(
                success=False,
                error="SMTP not configured. Set smtp_host in config.yaml or SMTP_HOST env var.",
            )

        to = kwargs.get("to")
        subject = kwargs.get("subject", "(no subject)")
        body = kwargs.get("body", "")
        html = kwargs.get("html")
        attachment = kwargs.get("attachment")

        if not to:
            return ToolResult(success=False, error="Missing 'to' (recipient email)")

        # Validate email addresses
        recipients = [addr.strip() for addr in to.split(",")]
        for addr in recipients:
            if not re.match(r"[^@]+@[^@]+\.[^@]+", addr):
                return ToolResult(success=False, error=f"Invalid email address: {addr}")

        # Build message
        from_addr = cfg["from_address"] or cfg["smtp_user"]
        if not from_addr:
            return ToolResult(success=False, error="No from_address or smtp_user configured")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{cfg['from_name']} <{from_addr}>"
        msg["To"] = ", ".join(recipients)

        # Add body
        if body:
            msg.attach(MIMEText(body, "plain", "utf-8"))
        if html:
            msg.attach(MIMEText(html, "html", "utf-8"))
        if not body and not html:
            msg.attach(MIMEText("", "plain", "utf-8"))

        # Add attachment
        if attachment:
            attachment = os.path.expanduser(attachment)
            if not os.path.isfile(attachment):
                return ToolResult(success=False, error=f"Attachment not found: {attachment}")
            try:
                with open(attachment, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={os.path.basename(attachment)}",
                    )
                    msg.attach(part)
            except Exception as e:
                return ToolResult(success=False, error=f"Failed to attach file: {e}")

        # Send
        try:
            if cfg["use_tls"]:
                server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=15)
                server.starttls()
            else:
                server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=15)

            if cfg["smtp_user"] and cfg["smtp_password"]:
                server.login(cfg["smtp_user"], cfg["smtp_password"])

            server.sendmail(from_addr, recipients, msg.as_string())
            server.quit()

            return ToolResult(
                success=True,
                output=f"Email sent to {', '.join(recipients)}: {subject}",
                data={
                    "to": recipients,
                    "subject": subject,
                    "from": from_addr,
                    "has_attachment": bool(attachment),
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to send email: {e}")
