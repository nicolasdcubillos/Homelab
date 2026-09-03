from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import respx

from portfoliowatcher.notifier import (
    EmailNotifier,
    NotifierError,
    TelegramNotifier,
    WhatsAppNotifier,
    available_notifiers,
    build_notifier,
    parse_recipients,
)

ACS_VARS = (
    "ACS_CONNECTION_STRING",
    "ACS_CHANNEL_REGISTRATION_ID",
    "ACS_EMAIL_SENDER",
    "WHATSAPP_TO",
    "EMAIL_TO",
    "EMAIL_SUBJECT",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Never let the developer's real .env leak into notifier assertions."""
    for name in ACS_VARS:
        monkeypatch.delenv(name, raising=False)


class FakePoller:
    def result(self):
        return SimpleNamespace(status="Succeeded")


class FakeEmailClient:
    """Stand-in for azure.communication.email.EmailClient — no network, no SDK."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False

    def begin_send(self, message: dict) -> FakePoller:
        self.sent.append(message)
        return FakePoller()

    def close(self) -> None:
        self.closed = True


def _email_notifier(monkeypatch, **options) -> tuple[EmailNotifier, FakeEmailClient]:
    monkeypatch.setenv("ACS_CONNECTION_STRING", "endpoint=https://acs.example.com/;accesskey=k")
    monkeypatch.setenv("ACS_EMAIL_SENDER", "DoNotReply@example.azurecomm.net")
    notifier = EmailNotifier(options)
    client = FakeEmailClient()
    notifier._client = client
    return notifier, client


# ------------------------------------------------------------------- registry


def test_email_notifier_is_registered():
    assert "email" in available_notifiers()
    assert isinstance(build_notifier("email"), EmailNotifier)


def test_registry_still_exposes_the_other_channels():
    assert set(available_notifiers()) >= {"console", "email", "telegram", "whatsapp"}


def test_parse_recipients_accepts_commas_and_semicolons():
    assert parse_recipients("a@x.com, b@x.com; c@x.com") == ["a@x.com", "b@x.com", "c@x.com"]
    assert parse_recipients("") == []
    assert parse_recipients(None) == []


# --------------------------------------------------------------------- email


async def test_email_notifier_sends_via_acs(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "user@example.com, other@example.com")
    notifier, client = _email_notifier(monkeypatch)

    await notifier.send("Informe semanal\nSegunda línea")

    assert len(client.sent) == 1
    message = client.sent[0]
    assert message["senderAddress"] == "DoNotReply@example.azurecomm.net"
    assert message["recipients"]["to"] == [
        {"address": "user@example.com"},
        {"address": "other@example.com"},
    ]
    assert message["content"]["subject"] == "PortfolioWatcher: informe de portafolio"
    assert message["content"]["plainText"] == "Informe semanal\nSegunda línea"
    assert "Informe semanal<br>Segunda línea" in message["content"]["html"]


async def test_email_notifier_escapes_html_body(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "user@example.com")
    notifier, client = _email_notifier(monkeypatch)

    await notifier.send("riesgo <b>alto</b> & revisión")

    html = client.sent[0]["content"]["html"]
    assert "&lt;b&gt;alto&lt;/b&gt;" in html
    assert "&amp;" in html
    # the plain text part keeps the original characters untouched
    assert client.sent[0]["content"]["plainText"] == "riesgo <b>alto</b> & revisión"


def test_email_notifier_reads_subject_from_env(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "user@example.com")
    monkeypatch.setenv("EMAIL_SUBJECT", "Asunto propio")
    notifier, _ = _email_notifier(monkeypatch)
    assert notifier.subject == "Asunto propio"


async def test_email_notifier_reports_missing_configuration(monkeypatch):
    notifier = EmailNotifier()
    with pytest.raises(NotifierError) as excinfo:
        await notifier.send("hola")
    message = str(excinfo.value)
    assert "ACS_CONNECTION_STRING" in message
    assert "ACS_EMAIL_SENDER" in message
    assert "EMAIL_TO" in message


async def test_email_notifier_closes_its_client(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "user@example.com")
    notifier, client = _email_notifier(monkeypatch)
    await notifier.aclose()
    assert client.closed is True
    assert notifier._client is None


# -------------------------------------------------- destination precedence


def test_email_option_to_beats_env(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "owner-of-the-vm@example.com")
    notifier, _ = _email_notifier(monkeypatch, to=["user@example.com"])
    assert notifier.recipients == ["user@example.com"]


def test_email_option_to_accepts_a_raw_string(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "owner-of-the-vm@example.com")
    notifier, _ = _email_notifier(monkeypatch, to="a@example.com, b@example.com")
    assert notifier.recipients == ["a@example.com", "b@example.com"]


def test_whatsapp_option_to_beats_env(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TO", "+570000000000")
    notifier = WhatsAppNotifier({"to": ["+573001112233"]})
    assert notifier.recipients == ["+573001112233"]


def test_whatsapp_falls_back_to_env_when_no_option(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TO", "+573001112233; +573004445566")
    notifier = WhatsAppNotifier()
    assert notifier.recipients == ["+573001112233", "+573004445566"]


def test_build_notifier_forwards_the_destination_option(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "owner-of-the-vm@example.com")
    monkeypatch.setenv("WHATSAPP_TO", "+570000000000")
    assert build_notifier("email", {"to": ["user@example.com"]}).recipients == ["user@example.com"]
    assert build_notifier("whatsapp", {"to": ["+573001112233"]}).recipients == ["+573001112233"]


def test_build_notifier_rejects_unknown_channel():
    with pytest.raises(NotifierError):
        build_notifier("carrier-pigeon")


# ------------------------------------------------------------------ telegram


@respx.mock
async def test_telegram_notifier_posts_send_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "555")
    route = respx.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    await TelegramNotifier().send("hola")

    assert route.called
    assert json.loads(route.calls.last.request.read()) == {"chat_id": "555", "text": "hola"}


@respx.mock
async def test_telegram_notifier_wraps_http_errors(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "555")
    respx.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
        return_value=httpx.Response(400, json={"ok": False})
    )

    with pytest.raises(NotifierError):
        await TelegramNotifier().send("hola")


async def test_telegram_notifier_requires_configuration():
    with pytest.raises(NotifierError):
        await TelegramNotifier().send("hola")
