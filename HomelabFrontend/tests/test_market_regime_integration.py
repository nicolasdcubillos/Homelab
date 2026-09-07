"""Integracion con evidencia sintetica; ninguna prueba realiza HTTP ni envia mensajes."""

import datetime as dt
import json
from copy import deepcopy

import pytest
from sqlalchemy import event, select

from homelab_dashboard.db import make_session_factory
from homelab_dashboard.market_regime import providers, service
from homelab_dashboard.market_regime.catalog import SOURCES
from homelab_dashboard.market_regime.cli import _import_authorized
from homelab_dashboard.market_regime.models import (
    RegimeLicense,
    RegimeModelVersion,
    RegimeObservation,
    RegimeRawPayload,
    RegimeRun,
    RegimeSnapshot,
    RegimeSourceState,
    RegimeTransition,
)
from homelab_dashboard.market_regime.providers.base import CollectedPayload, CollectionResult
from homelab_dashboard.market_regime.repository import observations_as_of
from homelab_dashboard.market_regime.schemas import Observation

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 9, 4, 21, 30, tzinfo=UTC)
T1 = T0 + dt.timedelta(seconds=5)


@pytest.mark.parametrize("weekly", [False, True])
def test_corte_manual_post_http_y_semanal_fijo(db, settings, monkeypatch, weekly):
    factory = make_session_factory(db.get_bind())
    clock = [T0]
    monkeypatch.setattr(service, "utcnow", lambda: clock[0])
    source = next(item for item in SOURCES if item.id == "treasury")
    monkeypatch.setattr(service, "source_infos", lambda *_: [source])

    def collect(*args, **kwargs):
        clock[0] = T1
        item = Observation(
            source_id="treasury",
            series_id="US02Y",
            period="2026-09-04",
            value="4.12",
            unit="percent",
            frequency="daily",
            observed_at=T0 - dt.timedelta(hours=2),
            available_at=T0,
            ingested_at=T0,
            published_at=None,
            vintage="unknown",
            timestamp_precision="observed",
            source_url="https://home.treasury.gov/test",
        )
        return CollectionResult(
            "treasury",
            "DISPONIBLE",
            "Sintetico",
            [
                CollectedPayload("treasury", item.source_url, b"synthetic-treasury", [item]),
            ],
        )

    monkeypatch.setattr(providers, "collect_source", collect)
    # Mantener el catalogo completo durante cobertura, acotar solo ingestion.
    original_coverage = service.coverage

    def coverage(session, configured, cutoff):
        with monkeypatch.context() as local:
            local.setattr(service, "source_infos", lambda *_: deepcopy(SOURCES))
            return original_coverage(session, configured, cutoff)

    monkeypatch.setattr(service, "coverage", coverage)
    run = service.enqueue_run(db, kind="report" if weekly else "ingest")
    run.status = "EJECUTANDO"
    run.attempts, run.lease_until = 1, T1 + dt.timedelta(minutes=3)
    db.commit()
    service.execute_run(factory, settings, run.id, attempt=1)
    db.expire_all()
    stored_run = db.get(RegimeRun, run.id)
    assert stored_run.status == "INCOMPLETO", stored_run.detail
    snapshot = db.get(RegimeSnapshot, stored_run.result["snapshot_id"])
    item = db.scalar(select(RegimeObservation))
    assert item.ingested_at == T1
    assert snapshot.as_of == (T0 if weekly else T1)
    assert len(observations_as_of(db, snapshot.as_of)) == (0 if weekly else 1)
    treasury = next(row for row in snapshot.data["coverage"] if row["series_id"] == "US02Y")
    assert treasury["available"] is not weekly
    assert all(row["score"] is None for row in snapshot.data["horizons"])
    assert db.get(RegimeSourceState, "treasury").daily_requests == 9


def test_modelo_congela_codigo_calendario_y_reinicia_reglas(db, settings):
    cutoff = dt.datetime.now(UTC) + dt.timedelta(minutes=1)
    first = service.build_snapshot(db, settings, cutoff)
    model = db.get(RegimeModelVersion, first.model_id)
    assert len(model.data["implementation_sha256"]) == 64
    sessions = model.data["engine"]["rules"]["verified_sessions"]
    assert "2026-09-07" not in sessions
    assert "2026-09-04" in sessions
    config = service.get_config(db)
    changed = deepcopy(config.data)
    changed["transition"]["entry_on"] = 70
    config.data = changed
    second = service.build_snapshot(db, settings, cutoff + dt.timedelta(minutes=1))
    assert first.model_id != second.model_id
    state = db.get(RegimeTransition, "SHORT").state
    assert state["model_id"] == second.model_id
    assert state["rules"]["entry_on"] == 70
    assert state["expected_previous_bar"] is not None


def test_asof_materializa_solo_ultima_revision_elegible(db):
    raw = RegimeRawPayload(
        source_id="treasury",
        sha256="a" * 64,
        source_url="https://home.treasury.gov/test",
        compressed=b"",
        ingested_at=T0,
    )
    db.add(raw)
    db.flush()
    rows = []
    for period in range(10):
        for revision in range(100):
            when = T0 + dt.timedelta(seconds=revision)
            rows.append(
                {
                    "raw_id": raw.id,
                    "source_id": "treasury",
                    "series_id": "US02Y",
                    "period": f"2026-08-{period + 1:02d}",
                    "value": str(revision),
                    "unit": "percent",
                    "frequency": "daily",
                    "observed_at": T0,
                    "available_at": when,
                    "ingested_at": when,
                    "published_at": when,
                    "vintage": str(revision),
                    "timestamp_precision": "exact",
                    "source_url": raw.source_url,
                    "raw_hash": f"{revision:064x}",
                    "quality": "OK",
                }
            )
    db.execute(RegimeObservation.__table__.insert(), rows)
    db.commit()
    loaded = []

    def on_load(instance, context):
        loaded.append(instance.id)

    event.listen(RegimeObservation, "load", on_load)
    try:
        values = observations_as_of(db, T0 + dt.timedelta(seconds=50))
    finally:
        event.remove(RegimeObservation, "load", on_load)
    assert len(values) == len(loaded) == 10
    assert {item.value for item in values} == {50}


def test_importacion_estricta_vincula_aprobacion_y_revocacion(db, tmp_path):
    approval = RegimeLicense(
        source_id="licensed_market",
        reference="Contrato sintetico; sin derechos reales",
        evidence_sha256="b" * 64,
        valid_until=dt.datetime.now(UTC) + dt.timedelta(days=1),
        permissions=dict.fromkeys(("storage", "processing", "display", "derived"), True),
    )
    db.add(approval)
    db.flush()
    body = {
        "manifest": {
            "schema_version": "1",
            "provider": "Prueba sintetica",
            "source_url": "https://example.com/licensed-data",
            "terms_url": "https://example.com/terms",
            "license_id": approval.id,
            "license_evidence_sha256": "b" * 64,
            "attribution": "SINTETICO",
            "permissions": ["storage", "processing", "shared_display", "derivatives"],
        },
        "observations": [
            {
                "series_id": "SPX",
                "period": "2026-09-04",
                "value": "6000",
                "unit": "index points",
                "frequency": "daily",
                "observed_at": T0.isoformat(),
                "bar_closed": True,
            }
        ],
    }
    path = tmp_path / "authorized.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    assert _import_authorized(db, path)["observations_added"] == 1
    observations = observations_as_of(db, dt.datetime.now(UTC))
    assert len(service.usable_observations(db, observations)) == 1
    approval.revoked_at = dt.datetime.now(UTC)
    assert service.usable_observations(db, observations) == []
    with pytest.raises(ValueError, match="licencia exacta"):
        _import_authorized(db, path)


@pytest.mark.parametrize("failure", [False, True])
def test_intento_sin_lease_no_sobrescribe_recuperacion(db, settings, monkeypatch, failure):
    factory = make_session_factory(db.get_bind())
    run = service.enqueue_run(db, kind="ingest")
    run.status, run.attempts = "EJECUTANDO", 1
    run.lease_until = dt.datetime.now(UTC) + dt.timedelta(minutes=3)
    db.commit()
    identifier = run.id

    def takeover(*args, **kwargs):
        with factory() as session:
            recovered = session.get(RegimeRun, identifier)
            recovered.attempts = 2
            recovered.lease_until = dt.datetime.now(UTC) + dt.timedelta(minutes=3)
            session.commit()
        if failure:
            raise ValueError("Error del intento anterior.")
        return {}

    monkeypatch.setattr(service, "ingest_sources", takeover)
    service.execute_run(factory, settings, identifier, attempt=1)
    db.expire_all()
    recovered = db.get(RegimeRun, identifier)
    assert recovered.status == "EJECUTANDO"
    assert recovered.attempts == 2 and recovered.lease_until is not None
    assert db.scalar(select(RegimeSnapshot.id)) is None


def test_informe_revalida_licencia_de_su_comparacion_anterior(db, settings):
    cutoff = dt.datetime.now(UTC) + dt.timedelta(minutes=1)
    license_row = RegimeLicense(
        source_id="licensed_market",
        reference="Sintetico",
        permissions=dict.fromkeys(("storage", "processing", "display", "derived"), True),
    )
    db.add(license_row)
    prior = service.build_snapshot(db, settings, cutoff)
    prior_data = deepcopy(prior.data)
    for row in prior_data["coverage"]:
        if row["series_id"] == "SPX":
            row["available"] = True
    prior.data = prior_data
    current = service.build_snapshot(db, settings, cutoff + dt.timedelta(minutes=1))
    report = service.build_report(db, current, week_key="synthetic-week")
    assert report.data["snapshot_ids"] == [current.id, prior.id]
    assert service.can_display_report(db, report)
    license_row.revoked_at = dt.datetime.now(UTC)
    assert service.can_display_snapshot(db, current)
    assert not service.can_display_snapshot(db, prior)
    assert not service.can_display_report(db, report)


def test_recopilacion_automatica_antes_del_corte_no_retrofecha(db, settings):
    from dataclasses import replace
    from unittest.mock import Mock

    from homelab_dashboard.market_regime.dispatcher import RegimeDispatcher

    config = service.get_config(db)
    config.enabled = True
    settings = replace(settings, regime=replace(settings.regime, enabled=True))
    dispatcher = RegimeDispatcher(settings, make_session_factory(db.get_bind()), Mock())
    dispatcher._enqueue(db, T0 - dt.timedelta(minutes=25))
    db.flush()
    runs = db.scalars(select(RegimeRun).where(RegimeRun.kind == "ingest")).all()
    assert len(runs) == 2
    assert all(run.cutoff is None for run in runs)
    assert any(run.dedupe_key.startswith("preclose-ingest:") for run in runs)


def test_reporte_automatico_no_descarga_despues_de_su_corte(db, settings, monkeypatch):
    from unittest.mock import Mock

    from homelab_dashboard.market_regime.models import RegimeReport
    from homelab_dashboard.market_regime.outbox import notification_allowed

    late = T0 + dt.timedelta(minutes=6)
    monkeypatch.setattr(service, "utcnow", lambda: late)
    collection = Mock(side_effect=AssertionError("No recopilar despues del corte fijo."))
    monkeypatch.setattr(service, "ingest_sources", collection)
    run = service.enqueue_run(db, kind="report", cutoff=T0)
    run.status, run.attempts = "EJECUTANDO", 1
    run.lease_until = late + dt.timedelta(minutes=3)
    db.commit()
    service.execute_run(make_session_factory(db.get_bind()), settings, run.id, attempt=1)
    db.expire_all()
    assert db.get(RegimeRun, run.id).status == "INCOMPLETO"
    report = db.get(RegimeReport, db.get(RegimeRun, run.id).result["report_id"])
    snapshot = db.get(RegimeSnapshot, report.snapshot_id)
    assert snapshot.mode == "OPERACIONAL" and snapshot.as_of == T0
    assert notification_allowed(db, report, late)
    collection.assert_not_called()


def test_revision_publicada_mas_nueva_gana_a_importacion_tardia(db):
    from homelab_dashboard.market_regime.config import DEFAULT_CONFIG
    from homelab_dashboard.market_regime.features import point_in_time
    from homelab_dashboard.market_regime.repository import _observation, persist_payload

    available = T0 + dt.timedelta(days=3)
    for index, (value, publication) in enumerate(
        (
            ("5100", T0),
            ("5000", T0 - dt.timedelta(days=1)),
        )
    ):
        item = Observation(
            source_id="licensed_market",
            series_id="SPX",
            period="2026-09-03",
            value=value,
            unit="index points",
            frequency="daily",
            observed_at=T0 - dt.timedelta(days=1),
            published_at=publication,
            available_at=available,
            vintage=publication.date().isoformat(),
            timestamp_precision="exact",
            source_url="https://example.com/synthetic",
        )
        persist_payload(
            db,
            source_id=item.source_id,
            source_url=item.source_url,
            raw=value.encode(),
            observations=[item],
            ingested_at=available + dt.timedelta(seconds=index),
        )
    cutoff = available + dt.timedelta(minutes=1)
    all_rows = [_observation(row) for row in db.scalars(select(RegimeObservation))]
    selected, errors = point_in_time(all_rows, cutoff, DEFAULT_CONFIG)
    assert not errors
    assert observations_as_of(db, cutoff)[0].value == selected["SPX"][0].value == 5100
