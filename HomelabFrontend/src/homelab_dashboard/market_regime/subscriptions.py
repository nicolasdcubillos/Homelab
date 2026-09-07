"""Opt-in privado ligado al contacto actual, nunca a preferencias de watchers."""

from __future__ import annotations

import hashlib

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from ..config_service import destinos_de
from ..db import utcnow
from ..models import NotificationChannel, User
from .models import RegimeOutbox, RegimeReport, RegimeSubscription, new_id

CHANNELS = ("email", "whatsapp")
CONSENT_VERSION = "market-regime-v1"
CONSENT_TEXT = (
    "Acepto recibir el informe semanal informativo de régimen de mercado en este destino. "
    "No es asesoramiento financiero ni una recomendación individual. Puedo darme de baja "
    "en cualquier momento desde mis preferencias."
)
PENDING_STATUSES = ("PENDIENTE", "ERROR_REINTENTABLE", "BLOQUEADO")


def destination_hash(channel: str, destination: str) -> str:
    return hashlib.sha256(f"{channel}\0{destination}".encode("utf-8")).hexdigest()


def has_access(user: User | None) -> bool:
    return bool(
        user is not None and user.can_run_jobs and user.regime_level in ("viewer", "operator")
    )


def _contacts(db: Session, user: User) -> tuple[dict, dict]:
    destinations = destinos_de(db, user.id)
    rows = db.scalars(select(NotificationChannel).where(NotificationChannel.user_id == user.id))
    revisions = {row.channel: f"{row.id}:{row.updated_at.isoformat()}" for row in rows}
    return destinations, revisions


def consent_valid(
    subscription: RegimeSubscription, channel: str, destination: str, revision: str
) -> bool:
    consent = (subscription.consents or {}).get(channel, {})
    return bool(
        subscription.enabled
        and getattr(subscription, channel, False)
        and destination
        and consent.get("version") == CONSENT_VERSION
        and consent.get("destination_hash") == destination_hash(channel, destination)
        and consent.get("contact_revision") == revision
        and consent.get("accepted_at")
    )


def eligible_destination(db: Session, user: User, channel: str) -> str | None:
    if channel not in CHANNELS or not has_access(user):
        return None
    subscription = db.get(RegimeSubscription, user.id)
    if subscription is None:
        return None
    destinations, revisions = _contacts(db, user)
    destination = destinations.get(channel, "")
    return (
        destination
        if consent_valid(subscription, channel, destination, revisions.get(channel, ""))
        else None
    )


def _invalidate(
    db: Session, subscription: RegimeSubscription, destinations: dict, revisions: dict
) -> None:
    consents = dict(subscription.consents or {})
    for channel in CHANNELS:
        consent = consents.get(channel)
        if consent and (
            consent.get("destination_hash")
            != destination_hash(channel, destinations.get(channel, ""))
            or consent.get("contact_revision") != revisions.get(channel)
            or consent.get("version") != CONSENT_VERSION
        ):
            consents.pop(channel)
            setattr(subscription, channel, False)
        if not subscription.enabled or not getattr(subscription, channel):
            db.execute(
                update(RegimeOutbox)
                .where(
                    RegimeOutbox.user_id == subscription.user_id,
                    RegimeOutbox.channel == channel,
                    RegimeOutbox.status.in_(PENDING_STATUSES),
                )
                .values(status="CANCELADO", detail="Suscripción o consentimiento no vigente.")
            )
    subscription.consents = consents


def get_subscription(db: Session, user: User) -> dict:
    destinations, revisions = _contacts(db, user)
    subscription = db.get(RegimeSubscription, user.id)
    if subscription is not None:
        _invalidate(db, subscription, destinations, revisions)
    return {
        "enabled": bool(subscription and subscription.enabled),
        "email": bool(subscription and subscription.email),
        "whatsapp": bool(subscription and subscription.whatsapp),
        "horizons": subscription.horizons if subscription else ["SHORT", "MEDIUM", "LONG"],
        "email_ready": bool(destinations.get("email")),
        "whatsapp_ready": bool(destinations.get("whatsapp")),
        "detail": CONSENT_TEXT,
        "consent_version": CONSENT_VERSION,
    }


def update_subscription(db: Session, user: User, data: dict) -> dict:
    if not has_access(user):
        raise ValueError("El usuario no tiene acceso activo al módulo.")
    allowed = {
        "enabled",
        "email",
        "whatsapp",
        "horizons",
        "consent_email",
        "consent_whatsapp",
        "accept_consent",
    }
    if data.keys() - allowed:
        raise ValueError("Preferencia desconocida; solo puedes modificar tu suscripción.")
    for field in allowed - {"horizons"}:
        if field in data and not isinstance(data[field], bool):
            raise ValueError("Las preferencias y consentimientos deben ser booleanos.")
    if "horizons" in data and (
        not isinstance(data["horizons"], list)
        or not data["horizons"]
        or any(h not in ("SHORT", "MEDIUM", "LONG") for h in data["horizons"])
        or len(set(data["horizons"])) != len(data["horizons"])
    ):
        raise ValueError("Selecciona horizontes válidos sin duplicados.")
    subscription = db.get(RegimeSubscription, user.id)
    if subscription is None:
        subscription = RegimeSubscription(
            user_id=user.id, enabled=False, email=False, whatsapp=False, consents={}
        )
        db.add(subscription)
        db.flush()
    destinations, revisions = _contacts(db, user)
    _invalidate(db, subscription, destinations, revisions)
    consents = dict(subscription.consents)
    for channel in CHANNELS:
        consent = data.get("consent_" + channel)
        if data.get("accept_consent") is True and data.get(channel) is True:
            consent = True
        if consent is True:
            if not destinations.get(channel):
                raise ValueError("Configura primero el destino del canal en Ajustes.")
            consents[channel] = {
                "destination_hash": destination_hash(channel, destinations[channel]),
                "contact_revision": revisions[channel],
                "version": CONSENT_VERSION,
                "text": CONSENT_TEXT,
                "accepted_at": utcnow().isoformat(),
            }
        elif consent is False or data.get(channel) is False:
            consents.pop(channel, None)
            setattr(subscription, channel, False)
    subscription.consents = consents
    for field in ("enabled", "email", "whatsapp", "horizons"):
        if field in data:
            setattr(subscription, field, data[field])
    for channel in CHANNELS:
        if getattr(subscription, channel) and channel not in consents:
            raise ValueError("Es necesario aceptar explícitamente el consentimiento del canal.")
    subscription.updated_at = utcnow()
    _invalidate(db, subscription, destinations, revisions)
    db.flush()
    return get_subscription(db, user)


def enqueue_report(db: Session, report: RegimeReport) -> int:
    """Se invoca dentro de la misma transacción que crea el informe canónico."""
    db.flush()
    count = 0
    subscriptions = db.scalars(
        select(RegimeSubscription).where(RegimeSubscription.enabled.is_(True))
    )
    for subscription in subscriptions:
        user = db.get(User, subscription.user_id)
        if not has_access(user):
            continue
        for channel in CHANNELS:
            destination = eligible_destination(db, user, channel)
            if not destination:
                continue
            result = db.execute(
                insert(RegimeOutbox)
                .values(
                    id=new_id(),
                    report_id=report.id,
                    user_id=user.id,
                    channel=channel,
                    destination_hash=destination_hash(channel, destination),
                    status="PENDIENTE",
                    attempts=0,
                    created_at=utcnow(),
                    detail="",
                )
                .on_conflict_do_nothing(index_elements=["report_id", "user_id", "channel"])
            )
            count += result.rowcount
    return count
