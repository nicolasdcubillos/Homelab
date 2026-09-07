"""Synthetic fixtures prove contracts and causality, not market predictive validity."""

from __future__ import annotations

import datetime as dt
import math
from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from homelab_dashboard.market_regime.config import DEFAULT_CONFIG, HORIZONS, validate_config
from homelab_dashboard.market_regime.context import (
    MacroContext,
    conditional_fx,
    conditional_rates,
    decide_context,
)
from homelab_dashboard.market_regime.features import (
    closed_bars,
    confirmed_pivots,
    inflation_rates,
    percentile,
    point_in_time,
)
from homelab_dashboard.market_regime.reports import render_report
from homelab_dashboard.market_regime.schemas import (
    CategoryResult,
    CoverageItem,
    HorizonResult,
    Observation,
    OfficialEvent,
)
from homelab_dashboard.market_regime.scoring import calculate
from homelab_dashboard.market_regime.transitions import advance_transition

UTC = dt.timezone.utc
CUTOFF = dt.datetime(2026, 9, 7, 23, tzinfo=UTC)


def observation(
    series,
    day,
    value,
    *,
    period=None,
    frequency="daily",
    unit=None,
    id=None,
    **kwargs,
):
    at = dt.datetime.combine(day, dt.time(21), UTC) if isinstance(day, dt.date) else day
    return Observation(
        id=id,
        series_id=series,
        source_id="official-fixture",
        period=period or day.isoformat(),
        value=Decimal(str(value)),
        unit=unit or DEFAULT_CONFIG["series"][series]["units"][0],
        frequency=frequency,
        observed_at=at,
        available_at=at,
        published_at=at,
        ingested_at=at,
        vintage=day.isoformat(),
        timestamp_precision="exact",
        source_url="https://example.gov/fixture",
        **kwargs,
    )


def complete_observations():
    result = []
    start = dt.date(2022, 1, 3)
    days = [start + dt.timedelta(days=x) for x in range((CUTOFF.date() - start).days)]
    days = [x for x in days if x.weekday() < 5]
    daily = (
        "US02Y",
        "US10Y",
        "USDJPY",
        "DXY",
        "VIX",
        "MOVE",
        "HY_OAS",
        "IG_OAS",
        "SPX",
        "ES",
        "NDX",
        "NQ",
        "RUSSELL",
        "DOW",
        "FED_FUNDS",
    )
    for i, day in enumerate(days):
        for series in daily:
            recent = max(0, i - len(days) + 60)
            if series in ("VIX", "MOVE"):
                value = 20 + 3 * math.sin(i / 9) - 0.002 * i + recent * 0.06
            elif series in ("HY_OAS", "IG_OAS"):
                value = 6 - i * 0.002 + recent * 0.012
            elif series in ("US02Y", "US10Y", "FED_FUNDS"):
                value = 6 - i * 0.003 + recent * 0.01 + (0.5 if series == "US10Y" else 0)
            else:
                correction = max(0, i - len(days) + 20)
                value = 100 + i * 0.1 + 4 * math.sin(i / 3) - correction * 0.7
            result.append(observation(series, day, value, id=len(result) + 1))
        if day.weekday() == 2:
            result.append(
                observation(
                    "FED_BALANCE",
                    day,
                    6000000 + i * 2000 - max(0, i - len(days) + 90) * 5000,
                    frequency="weekly",
                    id=len(result) + 1,
                )
            )
    for i in range(56):
        year, month = divmod(2022 * 12 + i, 12)
        day = dt.date(year, month + 1, 1)
        recent = max(0, i - 51)
        for series in ("CPI", "CORE_CPI", "PCE", "CORE_PCE", "AHE"):
            value = 100 + i * 0.6 - i * i * 0.003 + recent * recent * 0.02
            result.append(
                observation(
                    series,
                    day,
                    value,
                    frequency="monthly",
                    period=f"{year}-{month + 1}",
                    id=len(result) + 1,
                )
            )
        for series, value in (
            ("NFP", 150000 + 100 * i + 5 * i * i - 7 * recent * recent),
            ("UNEMPLOYMENT", 6 - i * 0.035 + recent * 0.08),
            ("JOLTS", 8000 + i * 15 - recent * 30),
        ):
            result.append(
                observation(
                    series,
                    day,
                    value,
                    frequency="monthly",
                    id=len(result) + 1,
                )
            )
    for i in range(19):
        year, month = divmod(2022 * 12 + 3 * i, 12)
        result.append(
            observation(
                "GDP",
                dt.date(year, month + 1, 1),
                2 + i * 0.15 - max(0, i - 16) * 0.3,
                frequency="quarterly",
                period=f"{year}-Q{month // 3 + 1}",
                id=len(result) + 1,
            )
        )
    return result


@pytest.fixture(scope="module")
def complete_data():
    return complete_observations()


def test_default_weights_and_validation_are_independent():
    expected = {
        "SHORT": [30, 10, 10, 15, 15, 15, 5],
        "MEDIUM": [40, 10, 10, 10, 15, 10, 5],
        "LONG": [50, 10, 5, 5, 15, 10, 5],
    }
    value = validate_config(DEFAULT_CONFIG)
    for horizon in HORIZONS:
        assert list(value["horizons"][horizon]["weights"].values()) == expected[horizon]
    value["horizons"]["SHORT"]["weights"]["MACRO"] = 20
    with pytest.raises(ValidationError):
        validate_config(value)
    assert DEFAULT_CONFIG["horizons"]["SHORT"]["weights"]["MACRO"] == 30
    for update in ({"unknown": True}, {"required_series": []}):
        with pytest.raises(ValidationError):
            validate_config({**DEFAULT_CONFIG, **update})


def test_no_data_is_not_neutral():
    snapshot = calculate([], as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    assert [x.horizon for x in snapshot.horizons] == list(HORIZONS)
    for result in snapshot.horizons:
        assert result.data_status == "SIN_DATOS"
        assert result.score is result.regime is None
        assert all(x.value is None and x.contribution is None for x in result.categories)


def test_complete_seven_contributions_and_independent_windows(complete_data):
    snapshot = calculate(complete_data, as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    for result in snapshot.horizons:
        assert result.data_status == "COMPLETO", result.missing
        assert 0 <= result.score <= 100
        assert len(result.categories) == 7
        assert abs(sum(x.contribution for x in result.categories) - result.score) <= 0.01
        assert result.calibration_status == "HEURISTICO_NO_VALIDADO"
        assert result.drivers and result.changes and result.would_change
    windows = []
    for h in snapshot.horizons:
        equity = next(x for x in h.categories if x.category == "EQUITY")
        windows.append(equity.evidence[0].observation_ids)
    assert len(windows[0]) == 40
    assert len(windows[1]) == 26
    assert len(windows[2]) == 24
    assert len({x.score for x in snapshot.horizons}) == 3
    assert snapshot.horizons[0].score < snapshot.horizons[2].score
    assert [x.regime for x in snapshot.horizons] == ["RISK_OFF", "NEUTRAL", "RISK_ON"]
    assert snapshot.horizons[2].confidence == "BAJA"
    assert any("MACRO/CREDIT" in x for x in snapshot.horizons[2].contradictions)


@pytest.mark.parametrize("series", ["MOVE", "IG_OAS", "ES", "GDP", "FED_BALANCE"])
def test_required_missing_never_renormalizes(complete_data, series):
    data = [x for x in complete_data if x.series_id != series]
    snapshot = calculate(data, as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    assert all(
        x.data_status == "INCOMPLETO" and x.score is None and x.regime is None
        for x in snapshot.horizons
    )
    assert all(any(series in item for item in h.missing) for h in snapshot.horizons)


def test_stale_invalid_and_license_blocked_abstain(complete_data):
    blocked = [
        CoverageItem(
            series_id="SPX",
            name="SPX",
            source_id="fixture",
            available=False,
            reason="BLOQUEADO_LICENCIA",
        )
    ]
    snapshot = calculate(complete_data, as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=blocked)
    assert all(h.score is None for h in snapshot.horizons)
    recent = max((x for x in complete_data if x.series_id == "MOVE"), key=lambda x: x.observed_at)
    for bad in (
        recent.model_copy(update={"unit": "USD/JPY"}),
        recent.model_copy(update={"quality": "CUARENTENA"}),
    ):
        data = [x for x in complete_data if x.id != recent.id] + [bad]
        assert all(
            h.score is None
            for h in calculate(
                data,
                as_of=CUTOFF,
                config=DEFAULT_CONFIG,
                coverage=[],
            ).horizons
        )
    late = calculate(
        complete_data,
        as_of=CUTOFF + dt.timedelta(days=100),
        config=DEFAULT_CONFIG,
        coverage=[],
    )
    assert all(h.score is None for h in late.horizons)


def test_chronology_revision_and_operational_ingestion():
    old = observation("CPI", dt.date(2025, 9, 1), 100, period="2025-9")
    october = observation("CPI", dt.date(2025, 10, 1), 101, period="2025-10")
    revision = old.model_copy(
        update={
            "value": Decimal("200"),
            "available_at": CUTOFF + dt.timedelta(days=1),
            "published_at": CUTOFF + dt.timedelta(days=1),
            "vintage": "2026-09-08",
        }
    )
    late_ingest = october.model_copy(update={"ingested_at": CUTOFF + dt.timedelta(days=1)})
    series, _ = point_in_time([october, revision, old], CUTOFF, DEFAULT_CONFIG)
    assert [x.value for x in series["CPI"]] == [Decimal("100"), Decimal("101")]
    operational, _ = point_in_time([old, late_ingest], CUTOFF, DEFAULT_CONFIG)
    reconstruction, _ = point_in_time(
        [old, late_ingest],
        CUTOFF,
        DEFAULT_CONFIG,
        reconstruction=True,
    )
    assert len(operational["CPI"]) == 1
    assert len(reconstruction["CPI"]) == 2


def test_freshness_respects_economic_period_start_and_provider_cadence():
    recently_published = [
        observation(
            "GDP",
            dt.date(2026, 4, 1),
            26000,
            frequency="quarterly",
            unit="billions of chained 2017 USD",
        ),
        observation("PCE", dt.date(2026, 7, 1), 125, frequency="monthly"),
        observation("CORE_PCE", dt.date(2026, 7, 1), 125, frequency="monthly"),
        observation("JOLTS", dt.date(2026, 7, 1), 8000, frequency="monthly"),
    ]
    data, errors = point_in_time(
        recently_published,
        dt.datetime(2026, 9, 20, 23, tzinfo=UTC),
        DEFAULT_CONFIG,
    )
    assert set(data) == {"GDP", "PCE", "CORE_PCE", "JOLTS"}
    assert not errors
    rates = [observation("FED_FUNDS", dt.date(2026, 8, 28), 5)]
    _, errors = point_in_time(rates, CUTOFF, DEFAULT_CONFIG)
    assert "DATO_OBSOLETO" in errors["FED_FUNDS"]


def test_percentile_minimum_and_no_future():
    with pytest.raises(ValueError, match="252"):
        percentile(list(range(251)), 100)
    assert percentile(list(range(252)), 126) == pytest.approx(50.1984126984)
    assert percentile([20.0] * 252, 20) == 50


def test_pivots_only_after_two_right_closes_and_open_bars_excluded():
    start = dt.date(2026, 1, 5)
    items = [
        observation("SPX", start + dt.timedelta(days=i), x)
        for i, x in enumerate([100, 101, 105, 103, 102])
    ]
    assert confirmed_pivots(items[:4]) == []
    pivots = confirmed_pivots(items)
    assert pivots[0].confirmed_at == items[4].available_at
    assert pivots[0].observed_at == items[2].observed_at
    friday = items[-1].available_at
    assert closed_bars(items, "weekly", friday) == []
    following_monday = friday + dt.timedelta(days=3)
    assert closed_bars(items, "weekly", following_monday) == [items[-1]]
    assert closed_bars(items, "monthly", following_monday) == []
    sessions = [x.observed_at.date().isoformat() for x in items] + ["2026-01-12"]
    assert closed_bars(items, "weekly", friday, sessions) == [items[-1]]


def test_gdp_levels_are_converted_not_treated_as_growth_percent(complete_data):
    from homelab_dashboard.market_regime.context import build_context

    data = [x for x in complete_data if x.series_id != "GDP"]
    level = 20000
    for i in range(19):
        year, month = divmod(2022 * 12 + 3 * i, 12)
        level *= (1 + (2 + i * 0.1) / 100) ** 0.25
        data.append(
            observation(
                "GDP",
                dt.date(year, month + 1, 1),
                level,
                frequency="quarterly",
                unit="billions of chained 2017 USD",
            )
        )
    selected, errors = point_in_time(data, CUTOFF, DEFAULT_CONFIG)
    context = build_context(
        selected,
        errors,
        DEFAULT_CONFIG["horizons"]["SHORT"],
        DEFAULT_CONFIG,
        CUTOFF,
    )
    assert not context.missing
    assert context.growth > 0
    gdp = next(x for x in context.evidence if x.series_id == "GDP")
    assert "cambio=0.1000" in gdp.reading


def test_yoy_uses_calendar_dates_not_row_offsets():
    values = [
        observation("CPI", dt.date(2024, 9, 1), 100, frequency="monthly", period="2024-9"),
        observation("CPI", dt.date(2024, 10, 1), 102, frequency="monthly", period="2024-10"),
        observation("CPI", dt.date(2025, 9, 1), 104, frequency="monthly", period="2025-9"),
    ]
    rates, used = inflation_rates(values)
    assert rates == pytest.approx([4])
    assert len(used) == 2


def test_context_counterexamples_and_conditional_rates_fx():
    healthy = MacroContext(
        name=decide_context(inflation=-1, employment=1, growth=1, policy=1),
        value=1,
    )
    inflation = MacroContext(
        name=decide_context(inflation=1, employment=1, growth=1, policy=-1),
        value=-1,
    )
    recession = MacroContext(
        name=decide_context(inflation=-1, employment=-1, growth=-1, policy=1),
        value=-1,
    )
    assert decide_context(inflation=1, employment=1, growth=1, policy=1) == "MIXTO"
    assert conditional_rates(healthy, 0.2, 0.3) > 0
    assert conditional_rates(inflation, 0.2, 0.3) < 0
    assert conditional_rates(recession, -0.2, -0.3) < 0
    assert conditional_fx(healthy, 1, 1, 1, 1) > 0
    assert conditional_fx(inflation, 1, 1, 1, 1) < 0
    assert conditional_fx(healthy, 1, -1, -1, -1) < 0


def _horizon(name="SHORT", score=80, value=1):
    return HorizonResult(
        horizon=name,
        score=score,
        regime="RISK_ON",
        data_status="COMPLETO",
        categories=[
            CategoryResult(category=k, weight=w, value=value, contribution=w, reason="fixture")
            for k, w in DEFAULT_CONFIG["horizons"][name]["weights"].items()
        ],
    )


@pytest.mark.parametrize(
    "horizon,keys",
    [
        ("SHORT", ["2026-08-03", "2026-08-04", "2026-08-05"]),
        ("MEDIUM", ["2026-W31", "2026-W32"]),
        ("LONG", ["2026-07", "2026-08"]),
    ],
)
def test_transition_persistence_and_duplicate_idempotency(horizon, keys):
    state = None
    for i, key in enumerate(keys):
        at = CUTOFF - dt.timedelta(days=len(keys) - i)
        result, state = advance_transition(_horizon(horizon), state, bar_key=key, as_of=at)
        for _ in range(10):
            repeated, unchanged = advance_transition(
                _horizon(horizon),
                state,
                bar_key=key,
                as_of=at + dt.timedelta(seconds=1),
            )
            assert unchanged == state
            assert repeated == result
        assert result.transition_status == ("ESTABLE" if i == len(keys) - 1 else "EN_TRANSICION")
    assert result.regime == "RISK_ON"
    assert state["confirmed_regime"] == "RISK_ON"


def test_transition_missing_resets_and_future_rejected():
    _, state = advance_transition(_horizon(), None, bar_key="2026-08-03", as_of=CUTOFF)
    missing = _horizon().model_copy(update={"data_status": "INCOMPLETO", "score": None})
    result, state = advance_transition(
        missing,
        state,
        bar_key="2026-08-04",
        as_of=CUTOFF + dt.timedelta(seconds=1),
    )
    assert state["count"] == 0 and state["candidate"] is None
    assert result.regime is None and result.transition_status == "NO_EVALUABLE"
    with pytest.raises(ValueError, match="futura"):
        advance_transition(_horizon(), None, bar_key="2027-01-01", as_of=CUTOFF)


def test_transition_same_bar_does_not_restore_invalid_or_old_score():
    _, state = advance_transition(_horizon(), None, bar_key="2026-08-03", as_of=CUTOFF)
    recalculated = _horizon(score=75)
    result, state = advance_transition(
        recalculated,
        state,
        bar_key="2026-08-03",
        as_of=CUTOFF,
    )
    assert result.score == 75 and state["count"] == 1
    missing = _horizon().model_copy(update={"data_status": "INCOMPLETO", "score": None})
    result, state = advance_transition(missing, state, bar_key="2026-08-03", as_of=CUTOFF)
    assert result.score is None and state["count"] == 0
    result, state = advance_transition(_horizon(), state, bar_key="2026-08-03", as_of=CUTOFF)
    assert result.score == 80 and state["count"] == 0 and result.regime is None


def test_transition_requires_superior_category_and_resets_week_gap():
    horizon = _horizon("MEDIUM")
    for category in horizon.categories:
        if category.category in ("MACRO", "CREDIT"):
            category.value = -1
    _, state = advance_transition(horizon, None, bar_key="2026-W30", as_of=CUTOFF)
    assert state["count"] == 0
    _, state = advance_transition(
        _horizon("MEDIUM"),
        state,
        bar_key="2026-W31",
        as_of=CUTOFF + dt.timedelta(seconds=1),
    )
    result, state = advance_transition(
        _horizon("MEDIUM"),
        state,
        bar_key="2026-W33",
        as_of=CUTOFF + dt.timedelta(seconds=2),
    )
    assert state["count"] == 1 and result.transition_status == "EN_TRANSICION"


def test_causal_snapshot_unchanged_by_future_releases_and_revisions(complete_data):
    original = calculate(complete_data, as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    future = [
        x.model_copy(
            update={
                "available_at": CUTOFF + dt.timedelta(days=1),
                "published_at": CUTOFF + dt.timedelta(days=1),
                "value": x.value * 2,
                "vintage": "2026-09-08",
            }
        )
        for x in complete_data[-50:]
    ]
    with_future = calculate(
        list(reversed(complete_data + future)),
        as_of=CUTOFF,
        config=DEFAULT_CONFIG,
        coverage=[],
    )
    assert original == with_future


def test_units_and_decimal_ranges_fail_closed():
    invalid = observation("CPI", dt.date(2026, 8, 1), "1e10000", frequency="monthly")
    snapshot = calculate([invalid], as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    assert all(x.score is None for x in snapshot.horizons)
    invalid = invalid.model_copy(update={"value": Decimal("1"), "period": "2026-13"})
    snapshot = calculate([invalid], as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    assert all(x.score is None for x in snapshot.horizons)


def test_report_exact_sections_brief_matrix_and_safe_html(complete_data):
    snapshot = calculate(complete_data, as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    snapshot.horizons[0].categories[0].evidence[0].source_url = 'javascript:alert("XSS")'
    snapshot.horizons[0].categories[0].evidence[0].reading = '<script>alert("XSS")</script>'
    report = render_report(snapshot, week_key="<img onerror=alert(1)>")
    assert len(report.sections) == 13
    assert [x.number for x in report.sections] == list(range(1, 14))
    assert report.brief and report.matrix
    assert "<script>" not in report.html and "<img " not in report.html
    assert 'href="javascript:' not in report.html
    assert "&lt;script&gt;" in report.html
    assert report == render_report(snapshot, week_key="<img onerror=alert(1)>")
    assert report.narrative_status == "DESHABILITADO"


def test_report_uses_only_known_official_events_and_does_not_invent_times():
    snapshot = calculate([], as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    common = {
        "source_id": "bls",
        "source_url": "https://example.gov/calendar",
        "available_at": CUTOFF - dt.timedelta(days=2),
        "published_at": CUTOFF - dt.timedelta(days=2),
    }
    upcoming = OfficialEvent(
        **common,
        event_id="next-cpi",
        title="CPI <script>unsafe</script>",
        event_at=CUTOFF + dt.timedelta(days=2),
        scheduled=True,
        timestamp_precision="exact",
    )
    date_only = OfficialEvent(
        **common,
        event_id="date-only",
        title="Empleo con fecha sin hora",
        event_at=dt.datetime(2026, 9, 10, tzinfo=UTC),
        scheduled=True,
    )
    release = OfficialEvent(
        **common,
        event_id="last-release",
        title="Empleo publicado",
        event_at=CUTOFF - dt.timedelta(days=3),
        timestamp_precision="exact",
    )
    old_fed = OfficialEvent(
        **{**common, "source_id": "fed"},
        event_id="past-minutes",
        title="Actas anteriores",
        event_at=CUTOFF - dt.timedelta(days=20),
        kind="minutes",
    )
    hidden = upcoming.model_copy(
        update={
            "event_id": "unknown-yet",
            "title": "NO CONOCIDO",
            "available_at": CUTOFF + dt.timedelta(seconds=1),
        }
    )
    unpublished = upcoming.model_copy(
        update={
            "event_id": "unpublished",
            "title": "NO PUBLICADO",
            "published_at": CUTOFF + dt.timedelta(seconds=1),
        }
    )
    far_future = upcoming.model_copy(
        update={
            "event_id": "far-future",
            "title": "FUERA DE VENTANA",
            "event_at": CUTOFF + dt.timedelta(days=20),
        }
    )
    snapshot.events = [upcoming, date_only, release, old_fed, hidden, unpublished, far_future]
    report = render_report(snapshot, week_key="2026-W37")
    assert len(report.sections) == 13
    assert "Empleo publicado" in report.sections[0].text
    assert "Empleo publicado" in report.sections[1].text
    assert "Actas anteriores" in report.sections[2].text
    assert "Actas anteriores" not in report.sections[12].text
    assert "PROGRAMADO; realizacion no confirmada" in report.sections[12].text
    assert "CPI <script>unsafe</script>" in report.sections[12].text
    assert "2026-09-10 (hora no verificada)" in report.sections[12].text
    assert "2026-09-10T00:00" not in report.text
    assert all(x not in report.text for x in ("NO CONOCIDO", "NO PUBLICADO", "FUERA DE VENTANA"))
    assert "<script>" not in report.html
    event_rows = [x for x in report.matrix if x.series_id.startswith("EVENT:")]
    assert len(event_rows) == 4
    date_evidence = next(x for x in event_rows if x.series_id.endswith(":date-only"))
    assert date_evidence.observed_at is None
    snapshot.events.reverse()
    assert render_report(snapshot, week_key="2026-W37") == report


def test_past_scheduled_event_is_not_asserted_to_have_happened():
    snapshot = calculate([], as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    snapshot.events = [
        OfficialEvent(
            source_id="fed",
            event_id="unconfirmed",
            title="Reunion prevista",
            source_url="https://example.gov/meeting",
            available_at=CUTOFF - dt.timedelta(days=5),
            event_at=CUTOFF - dt.timedelta(days=2),
            scheduled=True,
            kind="meeting",
        )
    ]
    report = render_report(snapshot, week_key="2026-W37")
    assert "realizacion no confirmada" in report.sections[0].text
    assert "Reunion prevista" not in report.sections[12].text


def test_nfci_and_futures_have_no_duplicate_numerical_weight(complete_data):
    baseline = calculate(complete_data, as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    updated = complete_data + [observation("NFCI", dt.date(2026, 9, 4), 999)]
    new = calculate(updated, as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    assert [h.score for h in baseline.horizons] == [h.score for h in new.horizons]
    futures = [
        x.model_copy(update={"value": x.value * Decimal("2")}) if x.series_id in ("ES", "NQ") else x
        for x in complete_data
    ]
    changed = calculate(futures, as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    assert [h.score for h in baseline.horizons] == [h.score for h in changed.horizons]


def test_nfci_blocked_or_not_enabled_never_exposes_active_evidence(complete_data):
    values = complete_data + [
        observation("NFCI", dt.date(2026, 9, 4), 999, id=999999),
    ]
    blocked = CoverageItem(
        series_id="NFCI",
        source_id="chicago_fed",
        name="NFCI",
        required=False,
        available=False,
        reason="BLOQUEADO_LICENCIA",
    )
    for coverage in ([], [blocked]):
        snapshot = calculate(values, as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=coverage)
        for horizon in snapshot.horizons:
            assert horizon.score is not None
            cross = next(x for x in horizon.categories if x.category == "CROSS_ASSET")
            item = next(x for x in cross.evidence if x.series_id == "NFCI")
            assert item.value is None
            assert item.observation_ids == []
            assert item.direction == "NO_EVALUABLE"
    authorized = blocked.model_copy(update={"available": True, "reason": "Derechos aprobados"})
    snapshot = calculate(values, as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[authorized])
    cross = snapshot.horizons[0].categories[-1]
    nfci = next(x for x in cross.evidence if x.series_id == "NFCI")
    assert nfci.value == 999 and nfci.observation_ids == [999999]


def test_short_history_never_makes_volatility_neutral(complete_data):
    dates = sorted({x.observed_at for x in complete_data if x.series_id == "VIX"})[-252:]
    data = [x for x in complete_data if x.series_id != "VIX" or x.observed_at in dates]
    snapshot = calculate(data, as_of=CUTOFF, config=DEFAULT_CONFIG, coverage=[])
    for h in snapshot.horizons:
        assert h.score is None
        category = next(x for x in h.categories if x.category == "VOLATILITY")
        assert category.value is category.contribution is None


def test_bad_config_rejects_nonfinite_and_core_removal():
    config = deepcopy(DEFAULT_CONFIG)
    config["horizons"]["SHORT"]["weights"]["MACRO"] = float("nan")
    with pytest.raises(ValidationError):
        validate_config(config)
    config = deepcopy(DEFAULT_CONFIG)
    config["rules"]["history_min"] = 20
    with pytest.raises(ValidationError):
        validate_config(config)
