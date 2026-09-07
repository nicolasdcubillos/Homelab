"""Evidencia sintetica: estos tests no consultan ni validan mercados reales."""

import datetime as dt
from decimal import Decimal

import pytest
from conftest import crear_usuario
from pydantic import ValidationError
from sqlalchemy import func, select

from homelab_dashboard.market_regime.models import (
    RegimeAccess,
    RegimeObservation,
    RegimeRawPayload,
    RegimeSubscription,
)
from homelab_dashboard.market_regime.repository import (
    freeze_model,
    observations_as_of,
    persist_payload,
)
from homelab_dashboard.market_regime.schemas import Observation

UTC = dt.timezone.utc
PAST = dt.datetime(2026, 6, 1, 18, tzinfo=UTC)
LATER = dt.datetime(2026, 7, 1, 18, tzinfo=UTC)


def observation(**overrides):
    values = {
        "source_id": "test",
        "series_id": "CPI",
        "period": "2026-05",
        "value": Decimal("123.456"),
        "unit": "index",
        "frequency": "monthly",
        "observed_at": dt.datetime(2026, 5, 1, tzinfo=UTC),
        "published_at": PAST,
        "available_at": PAST,
        "vintage": "2026-06-01",
        "timestamp_precision": "exact",
        "source_url": "https://www.bls.gov/test-fixture",
    }
    values.update(overrides)
    return Observation(**values)


def persist(db, item, raw=b"synthetic", when=PAST):
    return persist_payload(
        db,
        source_id="test",
        source_url=item.source_url,
        raw=raw,
        observations=[item],
        ingested_at=when,
    )


def test_ingestion_idempotente_y_decimal_exacto(db):
    assert persist(db, observation()) == 1
    assert persist(db, observation()) == 0
    assert db.scalar(select(func.count()).select_from(RegimeRawPayload)) == 1
    assert db.scalar(select(func.count()).select_from(RegimeObservation)) == 1
    assert observations_as_of(db, PAST)[0].value == Decimal("123.456")


def test_revision_no_sustituye_el_pasado(db):
    persist(db, observation())
    revised = observation(
        value=Decimal("999"), vintage="2026-07-01", published_at=LATER, available_at=LATER
    )
    persist(db, revised, b"revision-synthetic", LATER)
    assert observations_as_of(db, PAST)[0].value == Decimal("123.456")
    assert observations_as_of(db, LATER)[0].value == Decimal("999")
    assert db.scalar(select(func.count()).select_from(RegimeObservation)) == 2


def test_ingestion_tardia_no_inventa_historia_operacional(db):
    persist(db, observation(), when=LATER)
    assert observations_as_of(db, PAST) == []
    assert len(observations_as_of(db, PAST, reconstructed=True)) == 1


def test_reconstruccion_exige_publicacion_y_vintage_demostrables(db):
    persist(db, observation(published_at=None, vintage="unknown", timestamp_precision="observed"))
    assert observations_as_of(db, PAST, reconstructed=True) == []


def test_modelos_son_versiones_por_contenido(db):
    first = freeze_model(db, {"SHORT": [30, 10]})
    assert freeze_model(db, {"SHORT": [30, 10]}) == first
    assert freeze_model(db, {"SHORT": [40, 10]}) != first


def test_rechaza_nan_y_fechas_sin_zona():
    with pytest.raises(ValidationError):
        observation(value=Decimal("NaN"))
    with pytest.raises(ValidationError):
        observation(available_at=dt.datetime(2026, 6, 1))


def test_permiso_regimen_no_es_trading_y_borrado_preserva_raw(db):
    user = crear_usuario(db, "lector@ejemplo.com", status="active")
    db.add(RegimeAccess(user_id=user.id, level="viewer"))
    db.add(RegimeSubscription(user_id=user.id))
    persist(db, observation())
    db.flush()
    db.refresh(user)
    assert user.regime_level == "viewer"
    assert user.trading_level is None
    db.delete(user)
    db.flush()
    assert db.scalar(select(func.count()).select_from(RegimeSubscription)) == 0
    assert db.scalar(select(func.count()).select_from(RegimeAccess)) == 0
    assert db.scalar(select(func.count()).select_from(RegimeObservation)) == 1
