"""WhatsApp notifier backed by Azure Communication Services Advanced Messaging.

ACS is deliberately chosen over Twilio: Meta bills WhatsApp conversations
through Azure, so alerts draw down the existing Azure credit (~$0.01 per
utility-template message).

Business-initiated messages require a Meta-approved **utility** template.  See
``docs/whatsapp-template.md`` for the exact body to submit in WhatsApp Manager.
Until approval lands, run with ``--dry-run`` (console notifier) or set
``WHATSAPP_MODE=text`` to use free-form session messages, which only work
inside the 24h window opened by an inbound message from the user.

Environment:
    ``ACS_CONNECTION_STRING``       ACS resource connection string
    ``ACS_CHANNEL_REGISTRATION_ID`` WhatsApp channel GUID
    ``WHATSAPP_TO``                 destination in E.164 (e.g. ``+573001234567``)
    ``WHATSAPP_TEMPLATE_NAME``      approved template name
    ``WHATSAPP_TEMPLATE_LANG``      template language (default ``es``)
    ``WHATSAPP_MODE``               ``template`` (default) or ``text``
"""

from __future__ import annotations

import asyncio
import logging
import os

from ..models import Alert, Hit
from .base import (
    Notifier,
    NotifierError,
    batch_groups,
    group_hits,
    register_notifier,
    render_text,
    summarize,
)

log = logging.getLogger(__name__)

#: Order matters: it must line up with the template's body placeholders.
TEMPLATE_PARAMS = ("product", "variant", "price", "store")
BUTTON_PARAM = "url_suffix"


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


class WhatsAppNotifier(Notifier):
    """Send batched restock alerts over WhatsApp via ACS."""

    name = "whatsapp"

    def __init__(self, options: dict | None = None) -> None:
        options = options or {}
        self.connection_string = options.get("connection_string") or os.getenv(
            "ACS_CONNECTION_STRING"
        )
        self.channel_id = options.get("channel_registration_id") or os.getenv(
            "ACS_CHANNEL_REGISTRATION_ID"
        )
        self.recipients: list[str] = options.get("to") or _env_list("WHATSAPP_TO")
        self.template_name = options.get("template_name") or os.getenv(
            "WHATSAPP_TEMPLATE_NAME", "stockwatcher_restock"
        )
        self.template_lang = options.get("template_lang") or os.getenv(
            "WHATSAPP_TEMPLATE_LANG", "es"
        )
        self.mode = (options.get("mode") or os.getenv("WHATSAPP_MODE", "template")).lower()
        self.max_hits_per_message = int(options.get("max_hits_per_message", 6))
        self.max_messages_per_run = int(options.get("max_messages_per_run", 5))
        self._client = None

    # ------------------------------------------------------------------ setup

    def _require_config(self) -> None:
        missing = [
            label
            for label, value in (
                ("ACS_CONNECTION_STRING", self.connection_string),
                ("ACS_CHANNEL_REGISTRATION_ID", self.channel_id),
                ("WHATSAPP_TO", self.recipients),
            )
            if not value
        ]
        if missing:
            raise NotifierError(
                "WhatsApp notifier is not configured; missing " + ", ".join(missing)
            )

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from azure.communication.messages import NotificationMessagesClient
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise NotifierError(
                "azure-communication-messages is required for the whatsapp notifier "
                "(pip install 'stockwatcher[azure]')"
            ) from exc
        self._client = NotificationMessagesClient.from_connection_string(self.connection_string)
        return self._client

    # ---------------------------------------------------------------- sending

    async def send(self, alert: Alert) -> None:
        if alert.is_empty:
            return
        self._require_config()
        batches = batch_groups(group_hits(alert.hits), self.max_hits_per_message)
        if len(batches) > self.max_messages_per_run:
            log.warning(
                "capping WhatsApp messages at %s (had %s batches)",
                self.max_messages_per_run,
                len(batches),
            )
            batches = batches[: self.max_messages_per_run]
        for batch in batches:
            await asyncio.to_thread(self._send_batch, batch)

    def _send_batch(self, hits: list[Hit]) -> None:
        client = self._get_client()
        content = self._text_content(hits) if self.mode == "text" else self._template_content(hits)
        try:
            response = client.send(content)
        except Exception as exc:  # pragma: no cover - network
            raise NotifierError(f"WhatsApp send failed: {exc}") from exc
        receipts = getattr(response, "receipts", None) or []
        log.info("whatsapp sent: %s receipt(s) for %s hit(s)", len(receipts), len(hits))

    def _text_content(self, hits: list[Hit]):
        from azure.communication.messages.models import TextNotificationContent

        return TextNotificationContent(
            channel_registration_id=self.channel_id,
            to=self.recipients,
            content=render_text(hits),
        )

    def _template_content(self, hits: list[Hit]):
        from azure.communication.messages.models import (
            MessageTemplate,
            MessageTemplateText,
            TemplateNotificationContent,
            WhatsAppMessageTemplateBindings,
            WhatsAppMessageTemplateBindingsButton,
            WhatsAppMessageTemplateBindingsComponent,
        )

        params = summarize(hits)
        values = [MessageTemplateText(name=name, text=params[name]) for name in TEMPLATE_PARAMS]
        bindings_body = [
            WhatsAppMessageTemplateBindingsComponent(ref_value=name) for name in TEMPLATE_PARAMS
        ]

        buttons = []
        url_suffix = _url_suffix(params["url"])
        if url_suffix:
            values.append(MessageTemplateText(name=BUTTON_PARAM, text=url_suffix))
            buttons = [
                WhatsAppMessageTemplateBindingsButton(sub_type="url", ref_value=BUTTON_PARAM)
            ]

        template = MessageTemplate(
            name=self.template_name,
            language=self.template_lang,
            template_values=values,
            bindings=WhatsAppMessageTemplateBindings(body=bindings_body, buttons=buttons),
        )
        return TemplateNotificationContent(
            channel_registration_id=self.channel_id,
            to=self.recipients,
            template=template,
        )

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None and hasattr(client, "close"):
            await asyncio.to_thread(client.close)


def _url_suffix(url: str) -> str:
    """Meta URL buttons take a *suffix* appended to the template's base URL.

    We register the base as ``https://`` in WhatsApp Manager, so the dynamic
    part is everything after the scheme.
    """
    if not url:
        return ""
    return url.split("://", 1)[-1]


register_notifier("whatsapp", lambda options: WhatsAppNotifier(options))
