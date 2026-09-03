"""Notifier plug-in system: WhatsApp (ACS) is the primary channel, Telegram a stub.

Mirrors the StockWatcher pattern (ABC + registry) so alternative channels can
be added without touching callers.
"""

from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Callable

log = logging.getLogger(__name__)


class NotifierError(RuntimeError):
    """Delivery failed. Callers should log and continue, never crash a run."""


class Notifier(ABC):
    """Delivers a rendered message string somewhere."""

    name: str = "base"

    @abstractmethod
    async def send(self, message: str) -> None: ...

    async def aclose(self) -> None:
        """Release notifier-owned resources."""


NotifierFactory = Callable[[dict], Notifier]

_REGISTRY: dict[str, NotifierFactory] = {}


def register_notifier(name: str, factory: NotifierFactory) -> None:
    _REGISTRY[name.lower()] = factory


def available_notifiers() -> list[str]:
    return sorted(_REGISTRY)


def build_notifier(name: str, options: dict | None = None) -> Notifier:
    factory = _REGISTRY.get(name.lower())
    if factory is None:
        raise NotifierError(
            f"unknown notifier {name!r} (known: {', '.join(available_notifiers()) or 'none'})"
        )
    return factory(options or {})


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


class ConsoleNotifier(Notifier):
    """Prints to stdout. Used for --dry-run / local development."""

    name = "console"

    async def send(self, message: str) -> None:
        print(message)


class WhatsAppNotifier(Notifier):
    """Sends messages over WhatsApp via Azure Communication Services.

    Same integration pattern as StockWatcher's whatsapp notifier: ACS bills
    WhatsApp conversations through Azure, so it draws down existing Azure
    credit instead of a separate Twilio account. Business-initiated messages
    require a Meta-approved *utility* template; free-form ``text`` mode only
    works inside the 24h window opened by an inbound user message.

    Environment:
        ``ACS_CONNECTION_STRING``       ACS resource connection string
        ``ACS_CHANNEL_REGISTRATION_ID`` WhatsApp channel GUID
        ``WHATSAPP_TO``                 destination(s) in E.164, comma-separated
        ``WHATSAPP_TEMPLATE_NAME``      approved template name
        ``WHATSAPP_TEMPLATE_LANG``      template language (default ``es``)
        ``WHATSAPP_MODE``               ``template`` (default) or ``text``
    """

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
            "WHATSAPP_TEMPLATE_NAME", "portfoliowatcher_alert"
        )
        self.template_lang = options.get("template_lang") or os.getenv(
            "WHATSAPP_TEMPLATE_LANG", "es"
        )
        self.mode = (options.get("mode") or os.getenv("WHATSAPP_MODE", "template")).lower()
        self._client = None

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
                "(pip install 'portfoliowatcher[azure]')"
            ) from exc
        self._client = NotificationMessagesClient.from_connection_string(self.connection_string)
        return self._client

    async def send(self, message: str) -> None:
        self._require_config()
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: str) -> None:
        client = self._get_client()
        content = self._text_content(message) if self.mode == "text" else self._template_content(
            message
        )
        try:
            response = client.send(content)
        except Exception as exc:  # pragma: no cover - network
            raise NotifierError(f"WhatsApp send failed: {exc}") from exc
        receipts = getattr(response, "receipts", None) or []
        log.info("whatsapp sent: %s receipt(s)", len(receipts))

    def _text_content(self, message: str):
        from azure.communication.messages.models import TextNotificationContent

        return TextNotificationContent(
            channel_registration_id=self.channel_id,
            to=self.recipients,
            content=message,
        )

    def _template_content(self, message: str):
        from azure.communication.messages.models import (
            MessageTemplate,
            MessageTemplateText,
            TemplateNotificationContent,
            WhatsAppMessageTemplateBindings,
            WhatsAppMessageTemplateBindingsComponent,
        )

        values = [MessageTemplateText(name="body", text=message)]
        bindings_body = [WhatsAppMessageTemplateBindingsComponent(ref_value="body")]
        template = MessageTemplate(
            name=self.template_name,
            language=self.template_lang,
            template_values=values,
            bindings=WhatsAppMessageTemplateBindings(body=bindings_body),
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


class TelegramNotifier(Notifier):
    """Stub for a simpler alternative channel — Telegram bot API.

    Not yet wired to a real HTTP call; implement ``send`` with a POST to
    ``https://api.telegram.org/bot<token>/sendMessage`` when ready to use.
    Kept here so the ``Notifier`` abstraction has a second concrete channel
    and switching away from WhatsApp only means implementing this method.

    Environment:
        ``TELEGRAM_BOT_TOKEN``  bot token from @BotFather
        ``TELEGRAM_CHAT_ID``    destination chat id
    """

    name = "telegram"

    def __init__(self, options: dict | None = None) -> None:
        options = options or {}
        self.bot_token = options.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = options.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID")

    async def send(self, message: str) -> None:
        if not self.bot_token or not self.chat_id:
            raise NotifierError(
                "Telegram notifier is not configured; set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
            )
        raise NotImplementedError(
            "TelegramNotifier is a stub — implement the sendMessage HTTP call before using it"
        )


register_notifier("console", lambda options: ConsoleNotifier())
register_notifier("whatsapp", lambda options: WhatsAppNotifier(options))
register_notifier("telegram", lambda options: TelegramNotifier(options))
