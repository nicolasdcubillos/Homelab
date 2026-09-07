"""ACS opcional: destinatario explícito y receipts, no promesas de entrega.

Los envíos generan cargos ACS y, en WhatsApp, cargos Meta según la plantilla.
Habilitar el recurso o disponer del SDK no implica gratuidad.
"""

from __future__ import annotations

import datetime as dt
import importlib
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import urlsplit

from ..market_regime.settings import RegimeSettings

DeliveryStatus = Literal["ACEPTADO", "ERROR_REINTENTABLE", "ERROR_FINAL", "INCIERTO", "BLOQUEADO"]


@dataclass(frozen=True)
class SendResult:
    status: DeliveryStatus
    provider_id: str | None = None
    detail: str = ""
    retry_after: float | None = None
    attempted: bool = True


@dataclass(frozen=True)
class ChannelReadiness:
    status: Literal["LISTO", "BLOQUEADO"]
    detail: str
    sdk_available: bool


def readiness(settings: RegimeSettings, channel: str) -> ChannelReadiness:
    """Preflight local para doctor; no crea clientes, operaciones ni solicitudes."""
    if channel not in ("email", "whatsapp"):
        return ChannelReadiness("BLOQUEADO", "Canal no compatible.", False)
    try:
        errors = importlib.import_module("azure.core.exceptions")
        for name in ("HttpResponseError", "ServiceRequestError", "ServiceResponseError"):
            getattr(errors, name)
        package, client = (
            ("azure.communication.email", "EmailClient")
            if channel == "email"
            else ("azure.communication.messages", "NotificationMessagesClient")
        )
        getattr(importlib.import_module(package), client)
        if channel == "whatsapp":
            models = importlib.import_module("azure.communication.messages.models")
            for name in (
                "MessageTemplate",
                "MessageTemplateText",
                "TemplateNotificationContent",
                "WhatsAppMessageTemplateBindings",
                "WhatsAppMessageTemplateBindingsComponent",
            ):
                getattr(models, name)
    except (ImportError, AttributeError):
        return ChannelReadiness("BLOQUEADO", "SDK ACS opcional no instalado o incompatible.", False)
    if not settings.enabled or not settings.deliveries_enabled:
        return ChannelReadiness("BLOQUEADO", "Entregas deshabilitadas por configuración.", True)
    if not settings.acs_connection_string:
        return ChannelReadiness("BLOQUEADO", "Credenciales ACS no configuradas.", True)
    if channel == "email" and not settings.acs_email_sender:
        return ChannelReadiness("BLOQUEADO", "Remitente email no configurado.", True)
    if channel == "whatsapp" and not (
        settings.acs_channel_id
        and settings.whatsapp_template_name
        and settings.whatsapp_template_language
        and settings.whatsapp_template_approved
    ):
        return ChannelReadiness("BLOQUEADO", "Falta canal o plantilla financiera aprobada.", True)
    return ChannelReadiness(
        "LISTO", "Preflight local; autenticación, destino y aceptación no verificados.", True
    )


def _blocked(detail: str) -> SendResult:
    return SendResult("BLOQUEADO", detail=detail, attempted=False)


def _field(value, name: str):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _receipt_id(value) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 256 else None


def _http_failure(exc) -> SendResult:
    status = getattr(exc, "status_code", None)
    if status == 429:
        retry_after = None
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", {}) or {}
        try:
            retry_after = max(0.0, min(float(headers.get("Retry-After", "0")), 172800))
        except (TypeError, ValueError):
            try:
                due = parsedate_to_datetime(headers.get("Retry-After", ""))
                if due.tzinfo is not None:
                    retry_after = max(
                        0.0, min((due - dt.datetime.now(dt.timezone.utc)).total_seconds(), 172800)
                    )
            except (TypeError, ValueError, OverflowError):
                pass
        return SendResult(
            "ERROR_REINTENTABLE", detail="ACS limitó la solicitud.", retry_after=retry_after
        )
    if status in (400, 401, 403, 404, 422):
        return SendResult("BLOQUEADO", detail="ACS rechazó la configuración o plantilla.")
    # Una respuesta 5xx tampoco demuestra que el proveedor no haya aceptado el envío.
    return SendResult(
        "INCIERTO", detail="ACS no confirmó el resultado; conciliar antes de reenviar."
    )


def send(
    settings: RegimeSettings,
    *,
    channel: str,
    destination: str,
    subject: str,
    text: str,
    html: str = "",
) -> SendResult:
    """No usa variables globales ni destinatarios compartidos ni retries del SDK."""
    if not settings.enabled or not settings.deliveries_enabled:
        return _blocked("Entregas deshabilitadas por configuración.")
    if not settings.acs_connection_string:
        return _blocked("Credenciales ACS no configuradas.")
    if channel == "email":
        if not settings.acs_email_sender or not re.fullmatch(
            r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+", destination
        ):
            return _blocked("Remitente o destino email inválido.")
    elif channel == "whatsapp":
        if not (
            settings.whatsapp_template_approved
            and settings.whatsapp_template_name
            and settings.whatsapp_template_language
            and settings.acs_channel_id
            and re.fullmatch(r"\+[1-9]\d{7,14}", destination)
        ):
            return _blocked("Falta destino o plantilla financiera aprobada.")
    else:
        return _blocked("Canal no compatible.")
    try:
        from azure.core.exceptions import (
            HttpResponseError,
            ServiceRequestError,
            ServiceResponseError,
        )

        if channel == "email":
            from azure.communication.email import EmailClient

            client_type = EmailClient
            payload = {
                "senderAddress": settings.acs_email_sender,
                "recipients": {"to": [{"address": destination}]},
                "content": {"subject": subject, "plainText": text, "html": html},
            }
        else:
            from azure.communication.messages import NotificationMessagesClient
            from azure.communication.messages.models import (
                MessageTemplate,
                MessageTemplateText,
                TemplateNotificationContent,
                WhatsAppMessageTemplateBindings,
                WhatsAppMessageTemplateBindingsComponent,
            )

            client_type = NotificationMessagesClient
            payload = TemplateNotificationContent(
                channel_registration_id=settings.acs_channel_id,
                to=[destination],
                template=MessageTemplate(
                    name=settings.whatsapp_template_name,
                    language=settings.whatsapp_template_language,
                    template_values=[MessageTemplateText(name="body", text=text)],
                    bindings=WhatsAppMessageTemplateBindings(
                        body=[WhatsAppMessageTemplateBindingsComponent(ref_value="body")]
                    ),
                ),
            )
            # Algunos SDK ignoran kwargs desconocidos en vez de rechazarlos.
            # Verificar la forma resultante antes de crear el cliente o hacer HTTP.
            template = payload.template
            if (
                payload.channel_registration_id != settings.acs_channel_id
                or payload.to != [destination]
                or template.name != settings.whatsapp_template_name
                or template.language != settings.whatsapp_template_language
                or len(template.template_values) != 1
                or template.template_values[0].name != "body"
                or template.template_values[0].text != text
                or len(template.bindings.body) != 1
                or template.bindings.body[0].ref_value != "body"
            ):
                return _blocked("El SDK no construyó la plantilla esperada.")
        client = client_type.from_connection_string(
            settings.acs_connection_string,
            retry_total=0,
            connection_timeout=settings.timeout,
            read_timeout=settings.timeout,
        )
    except ImportError:
        return _blocked("SDK ACS opcional no instalado o incompatible.")
    except (ValueError, TypeError, AttributeError):
        return _blocked("Configuración o API de plantilla ACS incompatible.")

    provider_id = None
    try:
        if channel == "email":

            def capture_operation(response):
                nonlocal provider_id
                headers = getattr(response.http_response, "headers", {})
                provider_id = _receipt_id(headers.get("operation-id")) or provider_id
                location = headers.get("operation-location")
                if isinstance(location, str):
                    provider_id = (
                        _receipt_id(urlsplit(location).path.rstrip("/").rsplit("/", 1)[-1])
                        or provider_id
                    )

            # Guardar la aceptación 202 sin dejar un poller/hilo de SDK en segundo plano.
            poller = client.begin_send(payload, raw_response_hook=capture_operation, polling=False)
            response = poller.result(timeout=settings.timeout)
            provider_id = _receipt_id(_field(response, "id")) or provider_id
            status = _field(response, "status")
            if status in ("Failed", "Canceled"):
                return SendResult("ERROR_FINAL", provider_id, "ACS informó una operación fallida.")
            if status not in ("NotStarted", "Running", "Succeeded") or not provider_id:
                return SendResult("INCIERTO", provider_id, "ACS no confirmó aceptación con ID.")
        else:
            response = client.send(payload)
            receipts = _field(response, "receipts") or []
            if len(receipts) != 1:
                return SendResult("INCIERTO", detail="ACS no devolvió un receipt individual.")
            recipient = _field(receipts[0], "to")
            if recipient is not None and recipient != destination:
                return SendResult("INCIERTO", detail="El receipt ACS no coincide con el destino.")
            provider_id = _receipt_id(_field(receipts[0], "message_id"))
            if provider_id is None:
                return SendResult("INCIERTO", detail="Receipt ACS sin ID de mensaje.")
        return SendResult("ACEPTADO", provider_id, "Aceptado por ACS; entrega no confirmada.")
    except HttpResponseError as exc:
        result = _http_failure(exc)
        if provider_id is not None and result.status == "ERROR_REINTENTABLE":
            return SendResult("INCIERTO", provider_id, "Operación conocida; conciliar su estado.")
        return SendResult(result.status, provider_id, result.detail, result.retry_after)
    except ServiceRequestError:
        # RequestsTransport tambien usa esta excepcion si falla leer el body de un 202.
        return SendResult("INCIERTO", provider_id, "Solicitud ambigua; requiere conciliación.")
    except (ServiceResponseError, TimeoutError):
        return SendResult("INCIERTO", provider_id, "Respuesta ambigua; requiere conciliación.")
    except (ValueError, TypeError, AttributeError):
        return SendResult("INCIERTO", provider_id, "Respuesta SDK inválida; requiere conciliación.")
    finally:
        try:
            client.close()
        except (HttpResponseError, ServiceRequestError, ServiceResponseError, OSError):
            pass
