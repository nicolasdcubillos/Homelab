"""Calendario, persistencia concurrente y ACS simulado: nunca envía mensajes reales."""

from __future__ import annotations

import datetime as dt
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from homelab_dashboard.db import Base, create_db_engine, make_session_factory
from homelab_dashboard.market_regime import calendar, dispatcher, outbox, subscriptions
from homelab_dashboard.market_regime.models import (
    RegimeAccess,
    RegimeConfig,
    RegimeLicense,
    RegimeModelVersion,
    RegimeOutbox,
    RegimeReport,
    RegimeRun,
    RegimeSnapshot,
    RegimeSubscription,
)
from homelab_dashboard.market_regime.repository import observations_as_of, persist_payload
from homelab_dashboard.market_regime.schemas import Observation
from homelab_dashboard.market_regime.settings import RegimeSettings, load_regime_settings
from homelab_dashboard.models import NotificationChannel, User
from homelab_dashboard.notifications import acs

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 11, 21, 35, tzinfo=UTC)


def stamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        ("2026-01-09T12:00", "2026-01-09T22:30"),
        ("2026-07-10T12:00", "2026-07-10T21:30"),
        ("2026-03-06T12:00", "2026-03-06T22:30"),
        ("2026-03-13T12:00", "2026-03-13T21:30"),
        ("2026-10-30T12:00", "2026-10-30T21:30"),
        ("2026-11-06T12:00", "2026-11-06T22:30"),
        ("2026-04-02T12:00", "2026-04-02T21:30"),
        ("2026-07-02T12:00", "2026-07-02T21:30"),
        ("2026-11-27T12:00", "2026-11-27T19:30"),
        ("2026-12-24T12:00", "2026-12-24T19:30"),
        ("2026-12-31T12:00", "2026-12-31T22:30"),
        ("2027-12-23T12:00", "2027-12-23T22:30"),
        ("2027-12-31T12:00", "2027-12-31T22:30"),
        ("2028-01-07T12:00", "2028-01-07T22:30"),
        ("2028-11-24T12:00", "2028-11-24T19:30"),
    ],
)
def test_weekly_official_closes_and_dst(now, expected):
    _, cutoff = calendar.weekly_schedule(stamp(now))
    assert cutoff == stamp(expected)
    assert calendar.due_week(cutoff)[1] == cutoff


def test_calendar_range_catchup_and_no_historical_guessing():
    due = calendar.due_week(stamp("2026-09-14T12:00"))
    assert due == ("2026-W37", stamp("2026-09-11T21:30"))
    assert calendar.due_week(stamp("2026-09-18T21:29")) == due
    assert calendar.due_week(stamp("2026-09-18T21:30"))[0] == "2026-W38"
    assert calendar.due_week(stamp("2025-12-31T12:00")) is None
    assert calendar.due_week(stamp("2029-01-05T12:00")) is None
    assert calendar.bar_key("SHORT", stamp("2025-12-31T23:00")) is None
    with pytest.raises(calendar.CalendarUnavailable):
        calendar.weekly_schedule(stamp("2029-01-01T12:00"))
    with pytest.raises(ValueError, match="zona"):
        calendar.weekly_schedule(dt.datetime(2026, 9, 11))


def test_bars_only_close_when_complete_and_calendar_fingerprint():
    assert calendar.bar_key("SHORT", stamp("2026-09-11T19:59")) == "2026-09-10"
    assert calendar.bar_key("SHORT", stamp("2026-09-11T20:00")) == "2026-09-11"
    assert calendar.bar_key("MEDIUM", stamp("2026-09-11T19:59")) == "2026-W36"
    assert calendar.bar_key("MEDIUM", stamp("2026-09-11T20:00")) == "2026-W37"
    assert calendar.bar_key("LONG", stamp("2026-09-30T19:59")) == "2026-08"
    assert calendar.bar_key("LONG", stamp("2026-09-30T20:00")) == "2026-09"
    assert calendar.bar_key("LONG", stamp("2026-01-01T12:00")) is None
    assert calendar.session_close(dt.date(2028, 7, 3)) == stamp("2028-07-03T17:00")
    assert len(calendar.load_calendar().sha256) == 64
    assert calendar.session_close(dt.date(2026, 7, 2)) == stamp("2026-07-02T20:00")
    assert calendar.session_close(dt.date(2027, 12, 23)) == stamp("2027-12-23T21:00")
    assert calendar.session_close(dt.date(2027, 12, 31)) == stamp("2027-12-31T21:00")
    assert {
        day for day in calendar.load_calendar().data["early_closes"] if day.startswith("2027")
    } == {"2027-11-26"}


def test_exceptional_closure_changes_schedule_without_algorithm_change(monkeypatch):
    verified = calendar.load_calendar()
    data = dict(verified.data, exceptional_closures=["2026-09-11"])
    monkeypatch.setattr(calendar, "load_calendar", lambda: calendar.NyseCalendar(data, "fixture"))
    assert calendar.weekly_schedule(stamp("2026-09-10T12:00"))[1] == stamp("2026-09-10T21:30")
    assert calendar.bar_key("SHORT", stamp("2026-09-11T23:00")) == "2026-09-10"


def test_settings_default_off_secret_repr_and_frozen(monkeypatch):
    baseline = load_regime_settings()
    assert not baseline.enabled and not baseline.deliveries_enabled
    assert not baseline.whatsapp_template_approved
    monkeypatch.setenv("DASHBOARD_REGIME_BLS_KEY", "synthetic-secret")
    monkeypatch.setenv("ACS_CONNECTION_STRING", "must-not-use-shared-secret")
    monkeypatch.setenv("DASHBOARD_REGIME_TIMEOUT", "nan")
    with pytest.raises(ValueError, match="DASHBOARD_REGIME_TIMEOUT"):
        load_regime_settings()
    monkeypatch.delenv("DASHBOARD_REGIME_TIMEOUT")
    settings = load_regime_settings()
    assert settings.bls_key == "synthetic-secret"
    assert settings.acs_connection_string == ""
    assert "synthetic-secret" not in repr(settings)
    assert settings.timeout == 20
    with pytest.raises(FrozenInstanceError):
        settings.enabled = True


@pytest.fixture()
def factory(tmp_path):
    engine = create_db_engine(tmp_path / "regime-operations.sqlite")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture()
def clock(monkeypatch):
    value = [NOW]
    monkeypatch.setattr(dispatcher, "utcnow", lambda: value[0])
    monkeypatch.setattr(outbox, "utcnow", lambda: value[0])
    monkeypatch.setattr(subscriptions, "utcnow", lambda: value[0])
    return value


def test_h41_release_after_early_weekly_cutoff_is_not_future_evidence(factory):
    # Fixture temporal sintético, no una publicación H.4.1 real.
    _, cutoff = calendar.weekly_schedule(stamp("2026-12-24T12:00"))
    assert cutoff == stamp("2026-12-24T19:30")  # 14:30 NY
    publication = stamp("2026-12-24T21:30")  # 16:30 NY, posterior al corte
    ingestion = publication + dt.timedelta(minutes=1)
    source_url = "https://www.federalreserve.gov/releases/h41/current/h41.htm"
    observation = Observation(
        source_id="fed",
        series_id="FED_BALANCE",
        period="2026-12-23",
        value="6000000",
        unit="millions of USD",
        frequency="weekly",
        observed_at=stamp("2026-12-23T21:00"),
        published_at=publication,
        available_at=publication,
        ingested_at=ingestion,
        vintage="synthetic-v1",
        timestamp_precision="exact",
        source_url=source_url,
    )
    with factory() as db:
        persist_payload(
            db,
            source_id="fed",
            source_url=source_url,
            raw=b"synthetic H41 timing fixture",
            observations=[observation],
            ingested_at=ingestion,
        )
        db.commit()
        assert observations_as_of(db, cutoff) == []
        assert observations_as_of(db, cutoff, reconstructed=True) == []
        assert len(observations_as_of(db, ingestion)) == 1


def seed(factory, *, channel="email", consent=True):
    with factory() as db:
        user = User(
            id="user-a",
            email="login@example.org",
            password_hash="not-used",
            status="active",
            role="user",
            must_change_password=False,
        )
        db.add(user)
        db.flush()
        db.add(RegimeAccess(user_id=user.id, level="viewer"))
        contact = NotificationChannel(
            id="contact-a",
            user_id=user.id,
            channel=channel,
            destination="individual@example.org" if channel == "email" else "+15555550123",
            updated_at=NOW,
        )
        db.add(contact)
        db.add(RegimeConfig(id=1, enabled=True))
        db.add(RegimeModelVersion(id="model", data={}))
        db.flush()
        db.add(
            RegimeSnapshot(
                id="snapshot",
                as_of=NOW,
                model_id="model",
                mode="OPERACIONAL",
                sha256="a" * 64,
                data={"coverage": [{"source_id": "treasury", "available": True}]},
            )
        )
        db.flush()
        report = RegimeReport(
            id="report",
            week_key="2026-W37",
            snapshot_id="snapshot",
            sha256="b" * 64,
            data={
                "title": "Informe sintético",
                "brief": "INCOMPLETO",
                "text": "Solo prueba",
                "html": "<p>Solo prueba</p>",
            },
        )
        db.add(report)
        db.flush()
        if consent:
            subscriptions.update_subscription(
                db,
                user,
                {
                    "enabled": True,
                    channel: True,
                    "accept_consent": True,
                },
            )
        db.commit()


def enqueue(factory):
    with factory() as db:
        count = subscriptions.enqueue_report(db, db.get(RegimeReport, "report"))
        db.commit()
        return count


def row(factory):
    with factory() as db:
        return db.scalar(select(RegimeOutbox))


def test_subscription_defaults_no_fallback_and_explicit_consent(factory, clock):
    seed(factory, consent=False)
    with factory() as db:
        user = db.get(User, "user-a")
        assert subscriptions.get_subscription(db, user)["enabled"] is False
        assert subscriptions.eligible_destination(db, user, "email") is None
        with pytest.raises(ValueError, match="consentimiento"):
            subscriptions.update_subscription(db, user, {"enabled": True, "email": True})
        db.rollback()
        db.delete(db.get(NotificationChannel, "contact-a"))
        db.commit()
        with pytest.raises(ValueError, match="destino"):
            subscriptions.update_subscription(
                db,
                user,
                {
                    "enabled": True,
                    "email": True,
                    "accept_consent": True,
                },
            )
    assert enqueue(factory) == 0


def test_subscription_matches_public_api_contract_exactly(factory, clock):
    from homelab_dashboard.market_regime.api_models import SubscriptionIn, SubscriptionOut

    seed(factory, consent=False)
    request = SubscriptionIn(enabled=True, email=True, accept_consent=True)
    with factory() as db:
        response = subscriptions.update_subscription(
            db, db.get(User, "user-a"), request.model_dump()
        )
        assert set(response) == set(SubscriptionOut.model_fields)
        parsed = SubscriptionOut.model_validate(response)
        assert parsed.email and parsed.email_ready
        assert parsed.consent_version == "market-regime-v1"
        db.commit()
    with factory() as db:
        assert subscriptions.get_subscription(db, db.get(User, "user-a")) == response


def test_subscription_bound_to_contact_revision_and_outbox_dedupe(factory, clock):
    seed(factory)
    assert enqueue(factory) == 1
    assert enqueue(factory) == 0
    with factory() as db:
        user = db.get(User, "user-a")
        subscription = db.get(RegimeSubscription, user.id)
        assert subscription.consents["email"]["version"] == subscriptions.CONSENT_VERSION
        contact = db.get(NotificationChannel, "contact-a")
        # Incluso restaurar el mismo destino después de editarlo no revive el opt-in.
        contact.updated_at = NOW + dt.timedelta(seconds=1)
        db.flush()
        assert subscriptions.get_subscription(db, user)["email"] is False
        db.commit()
    assert row(factory).status == "CANCELADO"


@pytest.mark.parametrize(
    "change", ["destination", "access", "suspended", "password", "unsubscribe"]
)
def test_outbox_revalidates_private_permissions(factory, clock, monkeypatch, change):
    seed(factory)
    enqueue(factory)
    with factory() as db:
        if change == "destination":
            db.get(NotificationChannel, "contact-a").destination = "changed@example.org"
        elif change == "access":
            db.delete(db.get(RegimeAccess, "user-a"))
        elif change == "suspended":
            db.get(User, "user-a").status = "suspended"
        elif change == "password":
            db.get(User, "user-a").must_change_password = True
        else:
            subscriptions.update_subscription(db, db.get(User, "user-a"), {"enabled": False})
        db.commit()
    sender = Mock()
    monkeypatch.setattr(outbox, "send", sender)
    outbox.process_outbox(factory, RegimeSettings(enabled=True, deliveries_enabled=True))
    sender.assert_not_called()
    assert row(factory).status == "CANCELADO"


@pytest.mark.parametrize("block", ["flag", "template", "license", "revoked"])
def test_outbox_blocks_without_network(factory, clock, monkeypatch, block):
    seed(factory, channel="whatsapp" if block == "template" else "email")
    enqueue(factory)
    settings = RegimeSettings(enabled=True, deliveries_enabled=block != "flag")
    with factory() as db:
        if block == "license":
            db.get(RegimeSnapshot, "snapshot").data = {
                "coverage": [{"source_id": "licensed_market", "available": True}]
            }
        if block == "revoked":
            db.add(
                RegimeLicense(
                    source_id="treasury",
                    reference="synthetic-revocation",
                    permissions={"external_notification": True},
                    revoked_at=NOW,
                )
            )
        db.commit()
    sender = Mock()
    monkeypatch.setattr(outbox, "send", sender)
    assert outbox.process_outbox(factory, settings) == 1
    sender.assert_not_called()
    assert row(factory).status == "BLOQUEADO"
    assert row(factory).attempts == 0


@pytest.mark.parametrize("long_names", [False, True])
def test_notification_license_accepts_cli_and_catalog_names(factory, clock, long_names):
    seed(factory)
    permissions = {"storage": True, "processing": True}
    permissions.update(
        {
            "shared_display" if long_names else "display": True,
            "derivatives" if long_names else "derived": True,
            "external_notification" if long_names else "notification": True,
        }
    )
    with factory() as db:
        license = RegimeLicense(
            source_id="treasury",
            reference="synthetic-license",
            permissions=permissions,
            valid_until=NOW + dt.timedelta(days=1),
        )
        db.add(license)
        db.flush()
        report = db.get(RegimeReport, "report")
        assert outbox.notification_allowed(db, report, NOW)
        license.permissions = dict(permissions, external_notification=False)
        db.flush()
        assert not outbox.notification_allowed(db, report, NOW)


@pytest.mark.parametrize("ids", [[], [99999], [True], ["1"]])
def test_numeric_evidence_requires_valid_persisted_ids(factory, clock, ids):
    seed(factory)
    with factory() as db:
        report = db.get(RegimeReport, "report")
        report.data = dict(
            report.data, matrix=[{"series_id": "CPI", "value": 123, "observation_ids": ids}]
        )
        assert not outbox.notification_allowed(db, report, NOW)


def test_event_notification_rights_are_also_revalidated(factory, clock):
    seed(factory)
    with factory() as db:
        snapshot = db.get(RegimeSnapshot, "snapshot")
        snapshot.data = dict(snapshot.data, events=[{"source_id": "authorized_import"}])
        assert not outbox.notification_allowed(db, db.get(RegimeReport, "report"), NOW)


@pytest.mark.parametrize("source_id", ["authorized_import", "licensed_market", "chicago_fed"])
def test_generic_source_grant_cannot_replace_payload_license_binding(factory, clock, source_id):
    seed(factory)
    with factory() as db:
        snapshot = db.get(RegimeSnapshot, "snapshot")
        snapshot.data = {"coverage": [{"source_id": source_id, "available": True}]}
        db.add(
            RegimeLicense(
                source_id=source_id,
                reference="synthetic generic source approval",
                permissions={
                    "storage": True,
                    "processing": True,
                    "shared_display": True,
                    "derivatives": True,
                    "external_notification": True,
                },
            )
        )
        db.flush()
        assert not outbox.notification_allowed(db, db.get(RegimeReport, "report"), NOW)


@pytest.mark.parametrize(("series", "allowed"), [("CPI", True), ("NFCI", False), ("HY_OAS", False)])
def test_fred_mirror_does_not_grant_rights_to_ice_or_nfci(factory, clock, series, allowed):
    seed(factory)
    with factory() as db:
        observation = Observation(
            source_id="fred",
            series_id=series,
            period="2026-09-01",
            value="1",
            unit="index",
            frequency="monthly",
            observed_at=NOW,
            available_at=NOW,
            published_at=NOW,
            source_url="https://fred.stlouisfed.org/",
        )
        persist_payload(
            db,
            source_id="fred",
            source_url=observation.source_url,
            raw=b"synthetic stored mirror fixture",
            observations=[observation],
            ingested_at=NOW,
        )
        persisted = observations_as_of(db, NOW)[0]
        report = db.get(RegimeReport, "report")
        report.data = dict(
            report.data,
            matrix=[{"series_id": series, "value": 1, "observation_ids": [persisted.id]}],
        )
        assert outbox.notification_allowed(db, report, NOW) is allowed


def test_outbox_acceptance_is_not_delivery_and_one_recipient(factory, clock, monkeypatch):
    seed(factory)
    enqueue(factory)
    sender = Mock(return_value=acs.SendResult("ACEPTADO", "actual-operation-id", "Aceptado"))
    monkeypatch.setattr(outbox, "send", sender)
    settings = RegimeSettings(
        enabled=True, deliveries_enabled=True, public_base_url="https://dashboard.example.org"
    )
    assert outbox.process_outbox(factory, settings) == 1
    delivery = row(factory)
    assert delivery.status == "ACEPTADO" and delivery.provider_id == "actual-operation-id"
    assert sender.call_args.kwargs["destination"] == "individual@example.org"
    assert "/regimen" in sender.call_args.kwargs["text"]
    assert outbox.process_outbox(factory, settings) == 0
    sender.assert_called_once()


def test_outbox_releases_transaction_before_network(factory, clock, monkeypatch):
    seed(factory)
    enqueue(factory)

    def send_without_lock(*_args, **_kwargs):
        with factory() as db:
            config = db.get(RegimeConfig, 1)
            config.version += 1
            db.commit()
        return acs.SendResult("ACEPTADO", "receipt")

    monkeypatch.setattr(outbox, "send", send_without_lock)
    assert (
        outbox.process_outbox(factory, RegimeSettings(enabled=True, deliveries_enabled=True)) == 1
    )
    with factory() as db:
        assert db.get(RegimeConfig, 1).version == 2


def test_outbox_retry_four_attempts_backoff_and_ttl(factory, clock, monkeypatch):
    seed(factory)
    enqueue(factory)
    sender = Mock(return_value=acs.SendResult("ERROR_REINTENTABLE", detail="Sin conexión"))
    monkeypatch.setattr(outbox, "send", sender)
    settings = RegimeSettings(enabled=True, deliveries_enabled=True)
    for attempt, delay in enumerate((60, 300, 1800), start=1):
        assert outbox.process_outbox(factory, settings) == 1
        delivery = row(factory)
        assert delivery.attempts == attempt
        assert delivery.next_attempt_at >= clock[0] + dt.timedelta(seconds=delay)
        assert outbox.process_outbox(factory, settings) == 0
        clock[0] = delivery.next_attempt_at
    assert outbox.process_outbox(factory, settings) == 1
    assert row(factory).attempts == 4 and row(factory).status == "ERROR_FINAL"
    assert sender.call_count == 4
    assert outbox.process_outbox(factory, settings) == 0


def test_missing_sdk_does_not_consume_network_attempts(factory, clock, monkeypatch):
    seed(factory)
    enqueue(factory)
    monkeypatch.setattr(
        outbox,
        "send",
        Mock(
            return_value=acs.SendResult(
                "BLOQUEADO",
                detail="SDK no instalado",
                attempted=False,
            )
        ),
    )
    settings = RegimeSettings(enabled=True, deliveries_enabled=True)
    for _ in range(5):
        assert outbox.process_outbox(factory, settings) == 1
        assert row(factory).status == "BLOQUEADO" and row(factory).attempts == 0
        clock[0] += dt.timedelta(minutes=5)


def test_expired_delivery_and_orphan_send_are_not_retried(factory, clock, monkeypatch):
    seed(factory)
    enqueue(factory)
    sender = Mock()
    monkeypatch.setattr(outbox, "send", sender)
    with factory() as db:
        delivery = db.scalar(select(RegimeOutbox))
        delivery.status = "ENVIANDO"
        delivery.attempts = 1
        delivery.lease_until = NOW - dt.timedelta(seconds=1)
        db.commit()
    settings = RegimeSettings(enabled=True, deliveries_enabled=True)
    assert outbox.process_outbox(factory, settings) == 0
    assert row(factory).status == "INCIERTO"
    with factory() as db:
        delivery = db.scalar(select(RegimeOutbox))
        delivery.status = "PENDIENTE"
        delivery.created_at = NOW - dt.timedelta(hours=48)
        db.commit()
    assert outbox.process_outbox(factory, settings) == 0
    assert row(factory).status == "ERROR_FINAL"
    sender.assert_not_called()


def test_ambiguous_send_is_never_retried(factory, clock, monkeypatch):
    seed(factory)
    enqueue(factory)
    sender = Mock(return_value=acs.SendResult("INCIERTO", "operation", "Conciliar"))
    monkeypatch.setattr(outbox, "send", sender)
    settings = RegimeSettings(enabled=True, deliveries_enabled=True)
    assert outbox.process_outbox(factory, settings) == 1
    clock[0] += dt.timedelta(hours=1)
    assert outbox.process_outbox(factory, settings) == 0
    assert row(factory).status == "INCIERTO"
    sender.assert_called_once()


def test_outbox_atomic_claim_across_independent_workers(factory, clock):
    seed(factory)
    enqueue(factory)
    barrier = threading.Barrier(2)

    def compete():
        barrier.wait()
        return outbox._claim(factory, NOW)

    with ThreadPoolExecutor(max_workers=2) as workers:
        claims = list(workers.map(lambda _: compete(), range(2)))
    assert sum(claim is not None for claim in claims) == 1


def test_dispatcher_atomic_single_module_claim_and_orphan_recovery(factory, clock):
    with factory() as db:
        db.add_all([RegimeRun(id=f"run-{n}", kind="snapshot", requested_at=NOW) for n in range(2)])
        db.commit()
    barrier = threading.Barrier(2)

    def compete():
        queue = dispatcher.RegimeDispatcher(RegimeSettings(), factory, Mock())
        barrier.wait()
        with factory() as db:
            claim = queue._claim(db, NOW)
            db.commit()
            return claim

    with ThreadPoolExecutor(max_workers=2) as workers:
        claims = list(workers.map(lambda _: compete(), range(2)))
    assert sum(claim is not None for claim in claims) == 1
    run_id = next(claim[0] for claim in claims if claim)
    queue = dispatcher.RegimeDispatcher(RegimeSettings(), factory, Mock())
    for expected in (2, 3):
        with factory() as db:
            db.get(RegimeRun, run_id).lease_until = NOW - dt.timedelta(seconds=1)
            db.commit()
        with factory() as db:
            assert queue._claim(db, NOW) == (run_id, expected)
            db.commit()
    with factory() as db:
        db.get(RegimeRun, run_id).lease_until = NOW - dt.timedelta(seconds=1)
        db.commit()
    with factory() as db:
        claim = queue._claim(db, NOW)
        db.commit()
        assert db.get(RegimeRun, run_id).status == "ERROR"
        assert claim[0] != run_id


def test_dispatcher_tick_is_light_and_scheduler_disabled_is_respected(factory, clock):
    with factory() as db:
        db.add(RegimeRun(id="manual", kind="snapshot", requested_at=NOW))
        db.commit()
    entered, release = threading.Event(), threading.Event()

    def execute(run_id, attempt):
        assert run_id == "manual"
        entered.set()
        assert release.wait(5)
        with factory() as db:
            run = db.get(RegimeRun, run_id)
            assert run.status == "EJECUTANDO"
            run.status = "COMPLETO"
            run.lease_until = None
            db.commit()

    settings = SimpleNamespace(regime=RegimeSettings(), scheduler_enabled=False)
    queue = dispatcher.RegimeDispatcher(settings, factory, execute)
    try:
        assert queue.tick() == 0 and not entered.is_set()
        settings.scheduler_enabled = True
        assert queue.tick() == 1
        assert entered.wait(3)
        assert queue.tick() == 0
    finally:
        release.set()
        queue.shutdown()
    with factory() as db:
        assert db.get(RegimeRun, "manual").status == "COMPLETO"


@pytest.mark.parametrize("process_enabled", [False, True])
@pytest.mark.parametrize("kind", ["ingest", "snapshot", "report"])
def test_manual_queue_keeps_cutoff_unset_with_automation_disabled(
    factory, clock, process_enabled, kind
):
    queued_at = NOW - dt.timedelta(minutes=5)
    with factory() as db:
        db.add(RegimeConfig(id=1, enabled=False))
        db.add(RegimeRun(id="manual-off", kind=kind, requested_at=queued_at, cutoff=None))
        db.commit()

    def execute(run_id, attempt):
        with factory() as db:
            run = db.get(RegimeRun, run_id)
            assert run.status == "EJECUTANDO" and run.attempts == 1
            assert run.requested_at == queued_at
            assert run.cutoff is None
            clock[0] += dt.timedelta(seconds=45)  # Simula el fin de HTTP tras esperar en la cola.
            run.status = "INCOMPLETO"
            run.finished_at = clock[0]
            run.lease_until = None
            db.commit()

    queue = dispatcher.RegimeDispatcher(
        SimpleNamespace(regime=RegimeSettings(enabled=process_enabled), scheduler_enabled=True),
        factory,
        execute,
    )
    try:
        assert queue.tick() == 1
    finally:
        queue.shutdown()
    with factory() as db:
        runs = list(db.scalars(select(RegimeRun)))
        assert len(runs) == 1 and runs[0].status == "INCOMPLETO"
        assert runs[0].cutoff is None
        assert runs[0].finished_at > runs[0].requested_at


def test_dispatcher_schedule_dedupes_and_only_latest_report(factory, clock):
    seed(factory, consent=False)
    queue = dispatcher.RegimeDispatcher(RegimeSettings(enabled=True), factory, Mock())
    with factory() as db:
        db.add(
            RegimeRun(
                kind="report",
                cutoff=NOW - dt.timedelta(days=14),
                dedupe_key="report:2026-W35",
                requested_at=NOW,
            )
        )
        db.commit()
        queue._enqueue(db, NOW)
        queue._enqueue(db, NOW)
        db.commit()
        rows = list(db.scalars(select(RegimeRun)))
        assert len(rows) == 4
        pending = [r for r in rows if r.status == "PENDIENTE"]
        assert {r.kind for r in pending} == {"ingest", "snapshot", "report"}
        assert next(r for r in pending if r.kind == "report").cutoff == stamp("2026-09-11T21:30")
        assert next(r for r in rows if r.dedupe_key.endswith("W35")).status == "ERROR"
        db.get(RegimeConfig, 1).enabled = False
        queue._enqueue(db, NOW + dt.timedelta(days=1))
        db.commit()
        assert len(list(db.scalars(select(RegimeRun)))) == 4


def test_active_outbox_and_run_exclude_each_other_across_processes(factory, clock):
    seed(factory)
    enqueue(factory)
    queue = dispatcher.RegimeDispatcher(RegimeSettings(), factory, Mock())
    with factory() as db:
        db.add(RegimeRun(id="run", kind="snapshot", requested_at=NOW))
        db.commit()
        assert queue._claim(db, NOW) == ("run", 1)
        db.commit()
    assert outbox._claim(factory, NOW) is None
    with factory() as db:
        db.get(RegimeRun, "run").status = "PENDIENTE"
        db.get(RegimeRun, "run").lease_until = None
        db.commit()
    assert outbox._claim(factory, NOW) is not None
    with factory() as db:
        assert queue._claim(db, NOW) is None


def test_heartbeats_renew_only_current_claim(factory, clock):
    seed(factory)
    enqueue(factory)

    class OneHeartbeat:
        def __init__(self):
            self.calls = 0

        def wait(self, _seconds):
            self.calls += 1
            return self.calls > 1

    delivery_id, attempt = outbox._claim(factory, NOW)
    clock[0] += dt.timedelta(seconds=60)
    outbox._heartbeat(factory, delivery_id, attempt, OneHeartbeat())
    assert row(factory).lease_until == clock[0] + outbox.LEASE
    with factory() as db:
        delivery = db.get(RegimeOutbox, delivery_id)
        delivery.status = "ACEPTADO"
        delivery.lease_until = None
        db.add(RegimeRun(id="run", kind="snapshot", requested_at=NOW))
        db.commit()
    queue = dispatcher.RegimeDispatcher(RegimeSettings(), factory, Mock())
    with factory() as db:
        run_id, attempt = queue._claim(db, clock[0])
        db.commit()
    clock[0] += dt.timedelta(seconds=60)
    queue._heartbeat(run_id, attempt, OneHeartbeat())
    with factory() as db:
        assert db.get(RegimeRun, run_id).lease_until == clock[0] + dt.timedelta(seconds=180)
        db.get(RegimeRun, run_id).attempts = attempt + 1
        db.commit()
    clock[0] += dt.timedelta(seconds=20)
    queue._heartbeat(run_id, attempt, OneHeartbeat())
    with factory() as db:
        assert db.get(RegimeRun, run_id).lease_until == clock[0] + dt.timedelta(seconds=160)


@pytest.fixture()
def azure(monkeypatch):
    names = [
        "azure",
        "azure.core",
        "azure.core.exceptions",
        "azure.communication",
        "azure.communication.email",
        "azure.communication.messages",
        "azure.communication.messages.models",
    ]
    modules = {name: ModuleType(name) for name in names}
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    errors = modules["azure.core.exceptions"]
    for name in ("HttpResponseError", "ServiceRequestError", "ServiceResponseError"):
        setattr(errors, name, type(name, (Exception,), {}))
    email, whatsapp = Mock(), Mock()
    modules["azure.communication.email"].EmailClient = Mock(
        from_connection_string=Mock(return_value=email)
    )
    modules["azure.communication.messages"].NotificationMessagesClient = Mock(
        from_connection_string=Mock(return_value=whatsapp)
    )
    models = modules["azure.communication.messages.models"]
    for name in (
        "MessageTemplate",
        "MessageTemplateText",
        "TemplateNotificationContent",
        "WhatsAppMessageTemplateBindings",
        "WhatsAppMessageTemplateBindingsComponent",
    ):
        setattr(models, name, Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs)))
    settings = RegimeSettings(
        enabled=True,
        deliveries_enabled=True,
        acs_connection_string="synthetic",
        acs_email_sender="sender@example.org",
        acs_channel_id="channel",
        whatsapp_template_name="approved_financial_report",
        whatsapp_template_approved=True,
    )
    return SimpleNamespace(
        email=email,
        whatsapp=whatsapp,
        settings=settings,
        models=models,
        errors=errors,
        modules=modules,
    )


def test_acs_email_preserves_operation_and_disables_sdk_retries(azure):
    azure.email.begin_send.return_value.result.return_value = {
        "id": "actual-email-operation",
        "status": "Succeeded",
    }
    result = acs.send(
        azure.settings,
        channel="email",
        destination="one@example.org",
        subject="Informe",
        text="Texto",
        html="<p>Texto</p>",
    )
    assert result.status == "ACEPTADO" and result.provider_id == "actual-email-operation"
    payload = azure.email.begin_send.call_args.args[0]
    assert azure.email.begin_send.call_args.kwargs["polling"] is False
    assert payload["recipients"] == {"to": [{"address": "one@example.org"}]}
    options = azure.modules["azure.communication.email"].EmailClient.from_connection_string
    assert options.call_args.kwargs["retry_total"] == 0
    azure.email.close.assert_called_once()


def test_acs_whatsapp_template_and_actual_receipt(azure):
    azure.whatsapp.send.return_value = SimpleNamespace(
        receipts=[SimpleNamespace(message_id="actual-whatsapp-receipt")]
    )
    result = acs.send(
        azure.settings,
        channel="whatsapp",
        destination="+15555550123",
        subject="Informe",
        text="Brief",
    )
    assert result.status == "ACEPTADO" and result.provider_id == "actual-whatsapp-receipt"
    payload = azure.whatsapp.send.call_args.args[0]
    assert payload.to == ["+15555550123"]
    assert payload.template.language == "es"
    assert payload.template.template_values[0].text == "Brief"
    assert payload.template.bindings.body[0].ref_value == "body"


def test_acs_incompatible_template_blocks_before_network(azure):
    azure.models.MessageTemplate.side_effect = TypeError("SDK incompatible: private-data")
    result = acs.send(
        azure.settings,
        channel="whatsapp",
        destination="+15555550123",
        subject="Informe",
        text="Brief",
    )
    assert result.status == "BLOQUEADO"
    assert "private-data" not in result.detail
    azure.whatsapp.send.assert_not_called()


def test_acs_silently_ignored_template_fields_block_before_network(azure):
    azure.models.MessageTemplate.side_effect = lambda **_kw: SimpleNamespace(
        name="ignored", language="es", template_values=[], bindings=None
    )
    result = acs.send(
        azure.settings,
        channel="whatsapp",
        destination="+15555550123",
        subject="Informe",
        text="Brief",
    )
    assert result.status == "BLOQUEADO"
    azure.whatsapp.send.assert_not_called()


@pytest.mark.parametrize("status", ["NotStarted", "Running"])
def test_email_initial_202_is_acceptance_not_delivery(azure, status):
    azure.email.begin_send.return_value.result.return_value = {"id": "actual-id", "status": status}
    result = acs.send(
        azure.settings,
        channel="email",
        destination="one@example.org",
        subject="Informe",
        text="Texto",
    )
    assert result.status == "ACEPTADO" and result.provider_id == "actual-id"


def test_acs_rate_limit_retry_after_and_malformed_receipt(azure):
    error = azure.errors.HttpResponseError("private url")
    error.status_code = 429
    error.response = SimpleNamespace(headers={"Retry-After": "600"})
    azure.whatsapp.send.side_effect = error
    result = acs.send(
        azure.settings,
        channel="whatsapp",
        destination="+15555550123",
        subject="Informe",
        text="Brief",
    )
    assert result.status == "ERROR_REINTENTABLE" and result.retry_after == 600
    azure.whatsapp.send.side_effect = None
    azure.whatsapp.send.return_value = SimpleNamespace(receipts=[SimpleNamespace(message_id=None)])
    result = acs.send(
        azure.settings,
        channel="whatsapp",
        destination="+15555550123",
        subject="Informe",
        text="Brief",
    )
    assert result.status == "INCIERTO"


def test_acs_timeout_retains_actual_operation_and_never_assumes_delivery(azure):
    def begin(_payload, raw_response_hook, polling):
        assert polling is False
        raw_response_hook(
            SimpleNamespace(
                http_response=SimpleNamespace(
                    headers={
                        "operation-location": "https://acs.example.org/emails/operations/op-123?api-version=x"
                    }
                )
            )
        )
        return SimpleNamespace(result=Mock(side_effect=TimeoutError("private destination")))

    azure.email.begin_send.side_effect = begin
    result = acs.send(
        azure.settings,
        channel="email",
        destination="one@example.org",
        subject="Informe",
        text="Texto",
    )
    assert result.status == "INCIERTO" and result.provider_id == "op-123"
    assert "private destination" not in result.detail


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("ServiceRequestError", "ERROR_REINTENTABLE"),
        ("ServiceResponseError", "INCIERTO"),
    ],
)
def test_acs_distinguishes_safe_connection_failure_and_ambiguous_response(azure, error, expected):
    azure.whatsapp.send.side_effect = getattr(azure.errors, error)("private token")
    result = acs.send(
        azure.settings,
        channel="whatsapp",
        destination="+15555550123",
        subject="Informe",
        text="Brief",
    )
    assert result.status == expected and "private token" not in result.detail


def test_acs_disabled_unapproved_and_missing_sdk_are_noops(azure, monkeypatch):
    for settings in (
        replace(azure.settings, deliveries_enabled=False),
        replace(azure.settings, whatsapp_template_approved=False),
    ):
        assert (
            acs.send(
                settings, channel="whatsapp", destination="+15555550123", subject="", text=""
            ).status
            == "BLOQUEADO"
        )
    monkeypatch.setitem(sys.modules, "azure.communication.messages", None)
    assert (
        acs.send(
            azure.settings, channel="whatsapp", destination="+15555550123", subject="", text=""
        ).status
        == "BLOQUEADO"
    )
    azure.whatsapp.send.assert_not_called()


def test_acs_local_readiness_never_constructs_clients_or_does_network(azure, monkeypatch):
    assert acs.readiness(azure.settings, "email").status == "LISTO"
    assert acs.readiness(azure.settings, "whatsapp").status == "LISTO"
    assert (
        acs.readiness(replace(azure.settings, whatsapp_template_approved=False), "whatsapp").status
        == "BLOQUEADO"
    )
    assert acs.readiness(replace(azure.settings, enabled=False), "email").status == "BLOQUEADO"
    monkeypatch.setitem(sys.modules, "azure.communication.messages", None)
    missing = acs.readiness(azure.settings, "whatsapp")
    assert missing.status == "BLOQUEADO" and not missing.sdk_available
    azure.modules[
        "azure.communication.email"
    ].EmailClient.from_connection_string.assert_not_called()
    azure.modules[
        "azure.communication.messages"
    ].NotificationMessagesClient.from_connection_string.assert_not_called()
    azure.email.begin_send.assert_not_called()
    azure.whatsapp.send.assert_not_called()
