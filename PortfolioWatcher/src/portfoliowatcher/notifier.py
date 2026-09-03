"""Notifier plug-in system: WhatsApp and Email over ACS, plus a Telegram channel.

Mirrors the StockWatcher pattern (ABC + registry) so alternative channels can
be added without touching callers.

Notification-destination contract (do not change without reading this)
---------------------------------------------------------------------
The destination of a run is resolved with this precedence, highest first:

1. ``options["to"]`` passed to :func:`build_notifier` — what the CLI's
   ``--notify-to`` flag fills in. Explicit, per-invocation, never shared.
2. Process environment (``WHATSAPP_TO`` / ``EMAIL_TO``).
3. Values loaded from a ``.env`` file.

Step 2 beating step 3 is what makes multi-tenant callers safe: HomelabDashboard
runs one PortfolioWatcher subprocess per user and injects that user's
destination through ``env=``, while the repo's shared ``.env`` only carries
common secrets (ACS, Azure OpenAI). ``cli.py`` therefore calls ``load_dotenv()``
with its default ``override=False``. **Never switch that to
``load_dotenv(override=True)``** without revisiting this contract: doing so
would let the shared file's ``WHATSAPP_TO``/``EMAIL_TO`` win and every user's
alerts would be delivered to the VM owner. ``tests/test_cli.py`` pins this.
"""

from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from html import escape as html_escape

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


def parse_recipients(raw: str | None) -> list[str]:
    """Split a comma/semicolon separated destination string into a clean list."""
    if not raw:
        return []
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


def _env_list(name: str) -> list[str]:
    return parse_recipients(os.getenv(name))


def _resolve_recipients(explicit: str | list[str] | None, env_name: str) -> list[str]:
    """Apply the destination precedence documented at the top of this module.

    ``explicit`` comes from ``build_notifier(..., options)`` — i.e. the CLI's
    ``--notify-to`` — and always wins. Only when it is absent do we fall back to
    the process environment (which itself already wins over ``.env``).
    """
    if isinstance(explicit, str):
        explicit = parse_recipients(explicit)
    return list(explicit) if explicit else _env_list(env_name)


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
        self.recipients: list[str] = _resolve_recipients(options.get("to"), "WHATSAPP_TO")
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


class EmailNotifier(Notifier):
    """Sends the rendered report by email via Azure Communication Services.

    Same ACS resource as :class:`WhatsAppNotifier` — Email is a separate linked
    capability on it — so this channel needs no extra provider or billing
    account. Unlike WhatsApp it has no template approval step: an Azure-managed
    domain (``*.azurecomm.net``) provisions in minutes, which makes it the
    zero-setup fallback when a user has no WhatsApp destination. Mirrors
    StockWatcher's ``notifiers/email.py`` so both repos share the same keys.

    The report is plain text, so it is sent as ``plainText`` and mirrored into a
    minimal escaped HTML body for clients that prefer it.

    Environment:
        ``ACS_CONNECTION_STRING``  ACS resource connection string
        ``ACS_EMAIL_SENDER``       verified sender, e.g.
                                   ``DoNotReply@<guid>.azurecomm.net``
        ``EMAIL_TO``               destination address(es), comma-separated
        ``EMAIL_SUBJECT``          subject line (default provided)
    """

    name = "email"

    def __init__(self, options: dict | None = None) -> None:
        options = options or {}
        self.connection_string = options.get("connection_string") or os.getenv(
            "ACS_CONNECTION_STRING"
        )
        self.sender = options.get("sender") or os.getenv("ACS_EMAIL_SENDER")
        self.recipients: list[str] = _resolve_recipients(options.get("to"), "EMAIL_TO")
        self.subject = options.get("subject") or os.getenv(
            "EMAIL_SUBJECT", "PortfolioWatcher: informe de portafolio"
        )
        self._client = None

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
            raise NotifierError("Email notifier is not configured; missing " + ", ".join(missing))

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from azure.communication.email import EmailClient
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise NotifierError(
                "azure-communication-email is required for the email notifier "
                "(pip install 'portfoliowatcher[azure]')"
            ) from exc
        self._client = EmailClient.from_connection_string(self.connection_string)
        return self._client

    async def send(self, message: str) -> None:
        self._require_config()
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: str) -> None:
        client = self._get_client()
        try:
            poller = client.begin_send(self._build_message(message))
            result = poller.result()
        except Exception as exc:  # pragma: no cover - network
            raise NotifierError(f"Email send failed: {exc}") from exc
        log.info(
            "email sent: status=%s to %s recipient(s)",
            getattr(result, "status", "unknown"),
            len(self.recipients),
        )

    def _build_message(self, message: str) -> dict:
        body_html = html_escape(message).replace("\n", "<br>")
        return {
            "senderAddress": self.sender,
            "recipients": {"to": [{"address": address} for address in self.recipients]},
            "content": {
                "subject": self.subject,
                "plainText": message,
                "html": f"<html><body>{body_html}</body></html>",
            },
        }

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None and hasattr(client, "close"):
            await asyncio.to_thread(client.close)


class TelegramNotifier(Notifier):
    """Simpler alternative channel — Telegram bot API over plain HTTP.

    Kept as a second concrete channel so switching away from ACS never means
    rewriting callers. Uses ``httpx`` (already a hard dependency) instead of a
    Telegram SDK: the ``sendMessage`` endpoint is a single POST.

    Environment:
        ``TELEGRAM_BOT_TOKEN``  bot token from @BotFather
        ``TELEGRAM_CHAT_ID``    destination chat id
    """

    name = "telegram"

    api_base = "https://api.telegram.org"

    def __init__(self, options: dict | None = None) -> None:
        options = options or {}
        self.bot_token = options.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
        # ``chat_id`` follows the same precedence as the other channels: the
        # explicit per-invocation option first, environment second.
        self.chat_id = options.get("chat_id") or options.get("to") or os.getenv("TELEGRAM_CHAT_ID")
        if isinstance(self.chat_id, list):
            self.chat_id = self.chat_id[0] if self.chat_id else None

    async def send(self, message: str) -> None:
        if not self.bot_token or not self.chat_id:
            raise NotifierError(
                "Telegram notifier is not configured; set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
            )
        import httpx

        url = f"{self.api_base}/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": str(self.chat_id), "text": message}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NotifierError(f"Telegram send failed: {exc}") from exc
        log.info("telegram sent to chat %s", self.chat_id)


register_notifier("console", lambda options: ConsoleNotifier())
register_notifier("whatsapp", lambda options: WhatsAppNotifier(options))
register_notifier("email", lambda options: EmailNotifier(options))
register_notifier("telegram", lambda options: TelegramNotifier(options))
