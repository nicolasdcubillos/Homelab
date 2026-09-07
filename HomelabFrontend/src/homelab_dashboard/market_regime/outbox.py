"""Entrega acotada, privacidad revalidada y conciliación de resultados ambiguos."""

from __future__ import annotations

import datetime as dt
import html
import random
import threading
from urllib.parse import urlsplit

from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import aliased

from ..db import utcnow
from ..models import User
from ..notifications.acs import SendResult, send
from .models import (
    RegimeLicense,
    RegimeObservation,
    RegimeOutbox,
    RegimeReport,
    RegimeRun,
    RegimeSnapshot,
)
from .repository import evidence_ids as _observation_ids
from .subscriptions import destination_hash, eligible_destination

MAX_ATTEMPTS = 4
TTL = dt.timedelta(hours=48)
LEASE = dt.timedelta(seconds=180)
RETRY_SECONDS = (60, 300, 1800)
RETRYABLE = ("PENDIENTE", "ERROR_REINTENTABLE", "BLOQUEADO")
HEARTBEAT_SECONDS = 30


def notification_allowed(db, report: RegimeReport, now: dt.datetime) -> bool:
    from .catalog import LICENSES, SERIES, SOURCES

    snapshot_ids = report.data.get("snapshot_ids") or [report.snapshot_id]
    snapshots = [db.get(RegimeSnapshot, identifier) for identifier in snapshot_ids]
    if report.snapshot_id not in snapshot_ids or any(
        snapshot is None or snapshot.mode != "OPERACIONAL" for snapshot in snapshots
    ):
        return False
    sources = {
        item.get("source_id")
        for snapshot in snapshots
        for item in snapshot.data.get("coverage", [])
        if item.get("available")
    }
    sources.update(
        event.get("source_id")
        for snapshot in snapshots
        for event in snapshot.data.get("events", [])
    )
    try:
        ids = _observation_ids(report.data)
        for snapshot in snapshots:
            ids |= _observation_ids(snapshot.data)
    except ValueError:
        return False
    if ids:
        observations = db.execute(
            select(
                RegimeObservation.id,
                RegimeObservation.source_id,
                RegimeObservation.series_id,
            ).where(RegimeObservation.id.in_(ids))
        ).all()
        if {row.id for row in observations} != ids:
            return False
        sources.update(row.source_id for row in observations)
        for row in observations:
            metadata = SERIES.get(row.series_id)
            if metadata is None:
                return False
            # El mirror FRED o un adaptador de importación no heredan derechos del propietario.
            if metadata.get("license_status") == "BLOQUEADO_LICENCIA":
                sources.add(metadata.get("source_id"))
    # La entrega externa de importaciones queda deshabilitada en la primera version.
    if any(source.restricted and source.id in sources for source in SOURCES):
        return False
    for source in sources:
        if not source:
            return False
        license = db.scalar(
            select(RegimeLicense)
            .where(
                RegimeLicense.source_id == source,
            )
            .order_by(RegimeLicense.created_at.desc(), RegimeLicense.id.desc())
            .limit(1)
        )
        if license is not None:
            if license.revoked_at is not None or (
                license.valid_until is not None and license.valid_until <= now
            ):
                return False
            permissions = license.permissions
        else:
            permissions = LICENSES.get(source, {})
        # El catálogo usa nombres largos; RegimeLicense/CLI usa display/derived/notification.
        # Si se guardaran ambas formas, cualquier denegación explícita prevalece.
        for keys in (
            ("storage",),
            ("processing",),
            ("shared_display", "display"),
            ("derivatives", "derived"),
            ("external_notification", "notification"),
        ):
            values = [permissions[key] for key in keys if key in permissions]
            if not values or not all(value is True for value in values):
                return False
    return True


def _claim(session_factory, now: dt.datetime) -> tuple[str, int] | None:
    with session_factory() as db:
        # Una caída después de iniciar HTTP es ambigua, incluso si no dejó receipt.
        db.execute(
            update(RegimeOutbox)
            .where(
                RegimeOutbox.status == "ENVIANDO",
                or_(RegimeOutbox.lease_until <= now, RegimeOutbox.lease_until.is_(None)),
            )
            .values(
                status="INCIERTO",
                lease_until=None,
                detail="Lease de envío vencido; requiere conciliación sin reintento ciego.",
            )
        )
        db.execute(
            update(RegimeOutbox)
            .where(
                RegimeOutbox.status.in_(RETRYABLE),
                or_(RegimeOutbox.created_at <= now - TTL, RegimeOutbox.attempts >= MAX_ATTEMPTS),
            )
            .values(
                status="ERROR_FINAL",
                lease_until=None,
                detail="Se agotaron los cuatro intentos o las 48 horas de vigencia.",
            )
        )
        candidate = (
            select(RegimeOutbox.id)
            .where(
                RegimeOutbox.status.in_(RETRYABLE),
                or_(RegimeOutbox.next_attempt_at.is_(None), RegimeOutbox.next_attempt_at <= now),
                RegimeOutbox.created_at > now - TTL,
                RegimeOutbox.attempts < MAX_ATTEMPTS,
            )
            .order_by(RegimeOutbox.created_at, RegimeOutbox.id)
            .limit(1)
            .scalar_subquery()
        )
        active = aliased(RegimeOutbox)
        row = db.execute(
            update(RegimeOutbox)
            .where(
                RegimeOutbox.id == candidate,
                ~exists(
                    select(active.id).where(
                        active.status == "ENVIANDO",
                        active.lease_until > now,
                    )
                ),
                ~exists(
                    select(RegimeRun.id).where(
                        RegimeRun.status == "EJECUTANDO",
                        RegimeRun.lease_until > now,
                    )
                ),
            )
            .values(status="ENVIANDO", lease_until=now + LEASE)
            .returning(
                RegimeOutbox.id,
                RegimeOutbox.attempts,
            ),
            execution_options={"synchronize_session": False},
        ).first()
        db.commit()
        return (row.id, row.attempts) if row else None


def _finish(
    session_factory, delivery_id: str, attempt: int, result: SendResult, *, cancelled: bool = False
) -> None:
    now = utcnow()
    status = "CANCELADO" if cancelled else result.status
    next_attempt = None
    if status == "ERROR_REINTENTABLE":
        if attempt >= MAX_ATTEMPTS:
            status = "ERROR_FINAL"
        else:
            delay = RETRY_SECONDS[max(0, attempt - 1)] * random.uniform(1, 1.2)
            delay = max(delay, result.retry_after or 0)
            next_attempt = now + dt.timedelta(seconds=delay)
    elif status == "BLOQUEADO":
        next_attempt = now + dt.timedelta(minutes=5)
    with session_factory() as db:
        db.execute(
            update(RegimeOutbox)
            .where(
                RegimeOutbox.id == delivery_id,
                RegimeOutbox.status == "ENVIANDO",
                RegimeOutbox.attempts == attempt,
            )
            .values(
                status=status,
                lease_until=None,
                next_attempt_at=next_attempt,
                provider_id=result.provider_id,
                detail=result.detail,
                attempts=attempt if result.attempted else max(0, attempt - 1),
            )
        )
        db.commit()


def _heartbeat(session_factory, delivery_id: str, attempt: int, stopped: threading.Event) -> None:
    while not stopped.wait(HEARTBEAT_SECONDS):
        now = utcnow()
        with session_factory() as db:
            updated = db.execute(
                update(RegimeOutbox)
                .where(
                    RegimeOutbox.id == delivery_id,
                    RegimeOutbox.attempts == attempt,
                    RegimeOutbox.status == "ENVIANDO",
                    RegimeOutbox.lease_until > now,
                )
                .values(lease_until=now + LEASE)
            )
            db.commit()
            if not updated.rowcount:
                return


def _message(report: RegimeReport, settings, channel: str) -> dict:
    title = str(report.data.get("title", "Informe semanal de régimen de mercado"))
    text = str(report.data.get("text", ""))
    rendered = str(report.data.get("html", ""))
    brief = str(report.data.get("brief", ""))
    base = settings.public_base_url.rstrip("/")
    try:
        parsed = urlsplit(base)
    except ValueError:
        parsed = None
    if (
        parsed is not None
        and parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and not any(ord(char) < 32 for char in base)
    ):
        url = base + "/regimen"
        text += f"\n\nInforme y preferencias (requiere iniciar sesión): {url}"
        rendered += (
            f'<p><a href="{html.escape(url, quote=True)}">'
            "Ver informe y preferencias (requiere iniciar sesión)</a></p>"
        )
        brief += f"\n{url}"
    return {
        "subject": title,
        "text": brief[:1024] if channel == "whatsapp" else text,
        "html": rendered,
    }


def process_outbox(session_factory, settings) -> int:
    """Máximo cinco entregas por ciclo. Ninguna transacción permanece abierta en HTTP."""
    config = getattr(settings, "regime", settings)
    count = 0
    for _ in range(5):
        claim = _claim(session_factory, utcnow())
        if claim is None:
            break
        delivery_id, attempt = claim
        result = None
        cancelled = False
        message = None
        destination = None
        channel = None
        with session_factory() as db:
            delivery = db.get(RegimeOutbox, delivery_id)
            if delivery is None or delivery.status != "ENVIANDO":
                continue
            channel = delivery.channel
            user = db.get(User, delivery.user_id)
            destination = eligible_destination(db, user, channel) if user else None
            report = db.get(RegimeReport, delivery.report_id)
            if (
                not destination
                or destination_hash(channel, destination) != delivery.destination_hash
            ):
                result = SendResult(
                    "BLOQUEADO", detail="Acceso, destino o consentimiento revocado."
                )
                cancelled = True
            elif not config.enabled or not config.deliveries_enabled:
                result = SendResult(
                    "BLOQUEADO", detail="Entregas deshabilitadas por configuración."
                )
            elif report is None or not notification_allowed(db, report, utcnow()):
                result = SendResult(
                    "BLOQUEADO", detail="Sin licencia vigente de notificación externa."
                )
            elif channel == "whatsapp" and not config.whatsapp_template_approved:
                result = SendResult("BLOQUEADO", detail="Plantilla financiera no aprobada.")
            else:
                message = _message(report, config, channel)
                incremented = db.execute(
                    update(RegimeOutbox)
                    .where(
                        RegimeOutbox.id == delivery_id,
                        RegimeOutbox.status == "ENVIANDO",
                        RegimeOutbox.attempts == attempt,
                        RegimeOutbox.lease_until > utcnow(),
                        RegimeOutbox.created_at > utcnow() - TTL,
                    )
                    .values(attempts=attempt + 1)
                )
                if not incremented.rowcount:
                    db.rollback()
                    continue
                attempt += 1
                db.commit()
        if result is None:
            stopped = threading.Event()
            heartbeat = threading.Thread(
                target=_heartbeat,
                args=(session_factory, delivery_id, attempt, stopped),
                name="regime-delivery-heartbeat",
                daemon=True,
            )
            heartbeat.start()
            try:
                result = send(config, channel=channel, destination=destination, **message)
            finally:
                stopped.set()
                heartbeat.join()
        _finish(session_factory, delivery_id, attempt, result, cancelled=cancelled)
        count += 1
    return count
