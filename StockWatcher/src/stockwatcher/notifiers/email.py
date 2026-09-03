"""Email notifier backed by Azure Communication Services Email.

Chosen as the zero-setup fallback to WhatsApp: an Azure-managed email domain
(``*.azurecomm.net``) provisions in minutes via the CLI, with no Meta Business
Manager verification or template approval required. One email is sent per
run with every hit, batched (WhatsApp instead batches per store/price group
to respect Meta's per-message limits; email has no such constraint).

Environment:
    ``ACS_CONNECTION_STRING``  ACS resource connection string (same resource
                                used for WhatsApp; Email is a separate linked
                                capability on it)
    ``ACS_EMAIL_SENDER``       verified sender, e.g.
                                ``DoNotReply@<guid>.azurecomm.net``
    ``EMAIL_TO``               destination address(es), comma-separated;
                                overridden by ``--notify-to``
    ``EMAIL_SUBJECT``          subject line (default provided)
"""

from __future__ import annotations

import asyncio
import logging
import os

from ..models import Alert, Hit
from .base import Notifier, NotifierError, env_list, group_hits, register_notifier, render_text

log = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    """Send one batched restock email per run via ACS Email."""

    name = "email"

    def __init__(self, options: dict | None = None) -> None:
        options = options or {}
        self.connection_string = options.get("connection_string") or os.getenv(
            "ACS_CONNECTION_STRING"
        )
        self.sender = options.get("sender") or os.getenv("ACS_EMAIL_SENDER")
        # ``options["to"]`` is the destination the caller resolved with
        # :func:`stockwatcher.notifiers.base.resolve_destinations` (``--notify-to``
        # first, then the process environment, then the YAML).  Reading
        # ``EMAIL_TO`` here is only the fallback for a notifier built directly,
        # and *must* stay lower priority: see that function for why
        # ``load_dotenv(override=True)`` would cross users' alerts.
        self.recipients: list[str] = options.get("to") or env_list("EMAIL_TO")
        self.subject = options.get("subject") or os.getenv(
            "EMAIL_SUBJECT", "StockWatcher: nuevo stock disponible"
        )
        self._client = None

    # ------------------------------------------------------------------ setup

    def _require_config(self) -> None:
        missing = [
            label
            for label, value in (
                ("ACS_CONNECTION_STRING", self.connection_string),
                ("ACS_EMAIL_SENDER", self.sender),
                ("EMAIL_TO", self.recipients),
            )
            if not value
        ]
        if missing:
            raise NotifierError(
                "Email notifier is not configured; missing " + ", ".join(missing)
            )

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from azure.communication.email import EmailClient
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise NotifierError(
                "azure-communication-email is required for the email notifier "
                "(pip install 'stockwatcher[azure]')"
            ) from exc
        self._client = EmailClient.from_connection_string(self.connection_string)
        return self._client

    # ---------------------------------------------------------------- sending

    async def send(self, alert: Alert) -> None:
        if alert.is_empty:
            return
        self._require_config()
        await asyncio.to_thread(self._send_all, alert.hits)
        self.messages_sent += 1

    def _send_all(self, hits: list[Hit]) -> None:
        client = self._get_client()
        groups = group_hits(hits)
        body_lines = [render_text(g) for g in groups]
        plain_text = "\n\n".join(body_lines)
        html = "<br><br>".join(
            line.replace("\n", "<br>") for line in body_lines
        )
        message = {
            "senderAddress": self.sender,
            "recipients": {"to": [{"address": addr} for addr in self.recipients]},
            "content": {
                "subject": self.subject,
                "plainText": plain_text,
                "html": f"<html><body>{html}</body></html>",
            },
        }
        try:
            poller = client.begin_send(message)
            result = poller.result()
        except Exception as exc:  # pragma: no cover - network
            raise NotifierError(f"Email send failed: {exc}") from exc
        log.info(
            "email sent: status=%s to=%s (%s hit group(s))",
            getattr(result, "status", "unknown"),
            self.recipients,
            len(groups),
        )

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None and hasattr(client, "close"):
            await asyncio.to_thread(client.close)


register_notifier("email", lambda options: EmailNotifier(options), destination_env="EMAIL_TO")
