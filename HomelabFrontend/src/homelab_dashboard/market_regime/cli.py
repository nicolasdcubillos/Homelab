"""Operaciones locales explicitas; ningun comando envia mensajes."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import select, text

from ..db import create_db_engine, make_session_factory, utcnow
from ..migrate import current_revision, head_revision
from ..settings import load_settings
from . import service
from .models import (
    RegimeBacktestRun,
    RegimeConfig,
    RegimeLicense,
    RegimeOutbox,
    RegimeRun,
    RegimeSnapshot,
)
from .providers.base import ProviderError
from .repository import observations_for_validation, persist_payload
from .schemas import SnapshotData


def configure_parser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="regime_command", required=True)
    doctor = sub.add_parser("doctor", help="estado local, sin red ni mensajes")
    doctor.add_argument("--json", action="store_true")
    for name in ("ingest", "snapshot"):
        sub.add_parser(name)
    report = sub.add_parser("report")
    report.add_argument("--dry-run", action="store_true")
    sub.add_parser("backtest")
    imported = sub.add_parser("import-authorized")
    imported.add_argument("path", type=Path)
    license_parser = sub.add_parser("record-license")
    license_parser.add_argument("--source", required=True)
    license_parser.add_argument("--reference", required=True)
    license_parser.add_argument("--evidence-sha256", required=True)
    license_parser.add_argument("--expires", required=True)
    license_parser.add_argument("--allow-notification", action="store_true")
    parser.set_defaults(func=run_cli)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=True, default=str, indent=2))


def _doctor(settings, factory) -> int:
    from ..notifications.acs import readiness
    from .calendar import weekly_schedule

    if current_revision(settings) != head_revision():
        _print({"status": "ERROR", "detail": "La base requiere migracion."})
        return 1
    with factory() as db:
        config = db.get(RegimeConfig, 1)
        coverage = service.coverage(db, settings, utcnow())
        sources = service.source_infos(db, settings)
    next_due = weekly_schedule(utcnow())
    missing = [item.series_id for item in coverage if item.required and not item.available]
    _print(
        {
            "status": "INCOMPLETO" if missing else "COMPLETO",
            "schema": current_revision(settings),
            "engine_enabled": settings.regime.enabled,
            "schedule_enabled": bool(config and config.enabled),
            "deliveries_enabled": settings.regime.deliveries_enabled,
            "no_messages_sent": True,
            "notifications": {
                channel: asdict(readiness(settings.regime, channel))
                for channel in ("email", "whatsapp")
            },
            "missing": missing,
            "next_report_at": next_due[1],
            "sources": [
                {"id": item.id, "status": item.status, "detail": item.detail} for item in sources
            ],
        }
    )
    return 2 if missing else 0


def _import_authorized(db, path: Path) -> dict:
    from .catalog import SERIES
    from .providers.authorized_import import parse_authorized_import
    from .providers.http import MAX_PAYLOAD_BYTES

    if path.stat().st_size > MAX_PAYLOAD_BYTES:
        raise ValueError("La importacion excede 8 MiB.")
    raw = path.read_bytes()
    manifest, payload = parse_authorized_import(raw, "json", now=utcnow())
    approval = db.get(RegimeLicense, manifest.license_id)
    if (
        approval is None
        or approval.evidence_sha256 != manifest.license_evidence_sha256
        or approval.revoked_at is not None
        or approval.valid_until is None
        or approval.valid_until <= utcnow()
        or not all(
            approval.permissions.get(use) is True
            for use in ("storage", "processing", "display", "derived")
        )
        or any(
            SERIES[item.series_id]["source_id"] != approval.source_id
            for item in payload.observations
        )
    ):
        raise ValueError("La licencia exacta, su evidencia o su alcance no autorizan el archivo.")
    count = persist_payload(
        db,
        source_id=payload.source_id,
        source_url=payload.source_url,
        raw=raw,
        observations=payload.observations,
        ingested_at=utcnow(),
        license_id=approval.id,
    )
    return {"observations_added": count, "source_id": payload.source_id, "license_id": approval.id}


def run_cli(args: argparse.Namespace) -> int:
    settings = load_settings()
    if not settings.db_path.is_file():
        _print({"status": "ERROR", "detail": "La base no existe; ejecuta migrate primero."})
        return 1
    engine = create_db_engine(settings.db_path)
    factory = make_session_factory(engine)
    try:
        command = args.regime_command
        if command == "doctor":
            return _doctor(settings, factory)
        if current_revision(settings) != head_revision():
            raise ValueError("Aplica las migraciones antes de ejecutar el modulo.")
        if command == "record-license":
            from .catalog import SOURCES

            if args.source not in {item.id for item in SOURCES}:
                raise ValueError("Fuente desconocida.")
            if not re.fullmatch(r"[0-9a-f]{64}", args.evidence_sha256):
                raise ValueError("Se requiere SHA-256 de la evidencia revisada, en hexadecimal.")
            expires = dt.datetime.fromisoformat(args.expires.replace("Z", "+00:00"))
            if expires.tzinfo is None or expires <= utcnow():
                raise ValueError("La vigencia debe ser futura e incluir zona horaria.")
            with factory() as db:
                row = RegimeLicense(
                    source_id=args.source,
                    reference=args.reference,
                    evidence_sha256=args.evidence_sha256,
                    valid_until=expires,
                    permissions={
                        "storage": True,
                        "processing": True,
                        "display": True,
                        "derived": True,
                        "notification": args.allow_notification,
                    },
                )
                db.add(row)
                db.commit()
                _print(
                    {"license_id": row.id, "detail": "Registro administrativo; no compra permisos."}
                )
            return 0
        if command == "import-authorized":
            with factory() as db:
                result = _import_authorized(db, args.path)
                db.commit()
            _print(result)
            return 0
        if command == "backtest":
            from .validation import run_backtest

            with factory() as db:
                config = service.get_config(db)
                inputs = service.usable_observations(db, observations_for_validation(db))
                result = run_backtest(
                    inputs,
                    config=service.effective_config(config.data),
                    as_of=utcnow(),
                )
                db.add(RegimeBacktestRun(data=result))
                db.commit()
            _print(result)
            return 0
        if command == "report" and args.dry_run:
            from .calendar import due_week, weekly_schedule
            from .reports import render_report

            with factory() as db:
                snapshot = db.scalar(
                    select(RegimeSnapshot).order_by(RegimeSnapshot.as_of.desc()).limit(1)
                )
                if snapshot is None:
                    raise ValueError("No hay snapshot; ejecuta ingest o snapshot primero.")
                if not service.can_display_snapshot(db, snapshot):
                    raise ValueError("La evidencia del snapshot ya no tiene derechos de difusion.")
                week = due_week(utcnow()) or weekly_schedule(utcnow())
                report = render_report(SnapshotData.model_validate(snapshot.data), week_key=week[0])
            _print(report.model_dump(mode="json"))
            return 0
        with factory() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            active = db.scalar(
                select(RegimeRun.id)
                .where(RegimeRun.status.in_(["PENDIENTE", "EJECUTANDO"]))
                .limit(1)
            )
            sending = db.scalar(
                select(RegimeOutbox.id)
                .where(RegimeOutbox.status == "ENVIANDO", RegimeOutbox.lease_until > utcnow())
                .limit(1)
            )
            if active or sending:
                raise ValueError("Hay una ejecucion pendiente o activa; no se inicia otra.")
            run = service.enqueue_run(db, kind=command)
            run.status, run.started_at = "EJECUTANDO", utcnow()
            run.lease_until = utcnow() + dt.timedelta(seconds=180)
            run.attempts = 1
            db.commit()
            identifier = run.id
        from .dispatcher import RegimeDispatcher

        dispatcher = RegimeDispatcher(
            settings,
            factory,
            execute=lambda run_id, attempt: service.execute_run(
                factory,
                settings,
                run_id,
                attempt=attempt,
            ),
        )
        dispatcher._work((identifier, 1), deliveries=False)
        with factory() as db:
            run = db.get(RegimeRun, identifier)
            _print({"id": run.id, "status": run.status, "detail": run.detail, "result": run.result})
            return 1 if run.status == "ERROR" else 2 if run.status == "INCOMPLETO" else 0
    except (ValueError, OSError, ProviderError) as exc:
        print(f"Regimen: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
