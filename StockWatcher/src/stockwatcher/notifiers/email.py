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
import html
import logging
import os
from collections.abc import Sequence

from ..models import Alert, Hit
from .base import Notifier, NotifierError, env_list, group_hits, register_notifier, summarize

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
        message = {
            "senderAddress": self.sender,
            "recipients": {"to": [{"address": addr} for addr in self.recipients]},
            "content": {
                "subject": self.subject,
                "plainText": render_plain_text(groups),
                "html": render_html(groups),
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


# --------------------------------------------------------------------- design
#
# Same visual system as HomelabFrontend (see ``frontend/src/styles/theme.css``):
# a single restrained accent, status colour only where it carries meaning, and
# depth from shadow/border rather than colour noise.  Email clients strip
# ``oklch()``/custom properties and most CSS resets, so the tokens are
# hard-coded here as the closest sRGB hex equivalents and every rule is
# inlined — no ``<style>`` block, since Gmail's inbox view drops it.

_BG = "#f2f2f6"
_SURFACE = "#ffffff"
_BORDER = "#e4e4ea"
_FG = "#1f1f24"
_FG_SECONDARY = "#6b6b74"
_FG_TERTIARY = "#8f8f98"
_ACCENT = "#4f46e5"
_WARN = "#92600b"
_WARN_SOFT = "#fbf1de"
_FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _image_cell(image_url: str, alt: str) -> str:
    if image_url:
        return (
            f"<img src=\"{_esc(image_url)}\" alt=\"{_esc(alt)}\" width=\"96\" height=\"96\" "
            "style=\"display:block;width:96px;height:96px;border-radius:12px;"
            f"object-fit:cover;background-color:{_BORDER};border:1px solid {_BORDER};\">"
        )
    # No photo available for this store/provider: a quiet placeholder keeps
    # every card the same width instead of the text creeping under a gap.
    return (
        f"<div style=\"width:96px;height:96px;border-radius:12px;background-color:{_BORDER};"
        f"border:1px solid {_BORDER};\"></div>"
    )


def _card_html(hits: Sequence[Hit]) -> str:
    params = summarize(hits)
    mismatch = not all(h.color_matched for h in hits)
    badge = (
        f"<span style=\"display:inline-block;margin-top:8px;padding:3px 10px;"
        f"border-radius:999px;background-color:{_WARN_SOFT};color:{_WARN};"
        "font-size:12px;font-weight:600;\">Color fuera de preferencia</span>"
        if mismatch
        else ""
    )
    return f"""
<tr>
  <td style="padding:0 24px 16px 24px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
      style="background-color:{_SURFACE};border:1px solid {_BORDER};border-radius:16px;">
      <tr>
        <td style="padding:20px;" width="96">
          {_image_cell(params['image'], params['product'])}
        </td>
        <td style="padding:20px 20px 20px 0;vertical-align:top;">
          <div style="font-size:15px;font-weight:600;color:{_FG};line-height:1.35;">
            {_esc(params['product'])}
          </div>
          <div style="margin-top:4px;font-size:13px;color:{_FG_SECONDARY};">
            {_esc(params['store'])} &middot; talla {_esc(params['variant'])}
          </div>
          <div style="margin-top:10px;font-size:16px;font-weight:700;color:{_ACCENT};">
            {_esc(params['price'])}
          </div>
          {badge}
          <div style="margin-top:14px;">
            <a href="{_esc(params['url'])}"
              style="display:inline-block;padding:9px 18px;border-radius:10px;
              background-color:{_ACCENT};color:#ffffff;font-size:13px;font-weight:600;
              text-decoration:none;">Ver producto</a>
          </div>
        </td>
      </tr>
    </table>
  </td>
</tr>"""


def render_html(groups: Sequence[Sequence[Hit]]) -> str:
    """Full HTML document for one run's worth of restock groups."""
    count = len(groups)
    subtitle = "1 producto disponible" if count == 1 else f"{count} productos disponibles"
    cards = "".join(_card_html(g) for g in groups)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StockWatcher</title>
</head>
<body style="margin:0;padding:0;background-color:{_BG};font-family:{_FONT};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
  style="background-color:{_BG};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
  style="width:600px;max-width:100%;">
  <tr>
    <td style="padding:0 24px 24px 24px;">
      <div style="font-size:20px;font-weight:700;color:{_FG};letter-spacing:-0.01em;">
        StockWatcher
      </div>
      <div style="margin-top:4px;font-size:14px;color:{_FG_SECONDARY};">{_esc(subtitle)}</div>
    </td>
  </tr>
  {cards}
  <tr>
    <td style="padding:8px 24px 0 24px;border-top:1px solid {_BORDER};">
      <div style="padding-top:16px;font-size:12px;color:{_FG_TERTIARY};line-height:1.5;">
        Mensaje automático de StockWatcher. Los precios y la disponibilidad pueden cambiar
        entre la detección y tu compra.
      </div>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def render_plain_text(groups: Sequence[Sequence[Hit]]) -> str:
    """Plain-text alternative for clients that don't render HTML."""
    lines: list[str] = []
    for hits in groups:
        params = summarize(hits)
        flag = "" if all(h.color_matched for h in hits) else " (color fuera de preferencia)"
        lines.append(
            f"{params['product']} - talla {params['variant']} - {params['price']}\n"
            f"{params['store']}{flag}\n{params['url']}"
        )
    return "\n\n".join(lines)


register_notifier("email", lambda options: EmailNotifier(options), destination_env="EMAIL_TO")
