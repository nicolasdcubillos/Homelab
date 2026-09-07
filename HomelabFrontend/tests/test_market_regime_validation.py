from __future__ import annotations

import datetime as dt
from bisect import bisect_left
from copy import deepcopy

import pytest
from test_market_regime_engine import CUTOFF, complete_observations, observation

from homelab_dashboard.market_regime.config import DEFAULT_CONFIG
from homelab_dashboard.market_regime.schemas import HorizonResult, SnapshotData
from homelab_dashboard.market_regime.validation import (
    _forward_end,
    _label,
    _official_records,
    _thresholds,
    run_backtest,
)


def prices(count=400):
    start = dt.date(2020, 1, 1)
    dates = []
    day = start
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return [observation("SPX", day, 100 + i * 0.05 + (i % 13) * 0.3) for i, day in enumerate(dates)]


def fake_scores(records, *, as_of, config, coverage, reconstruction):
    assert reconstruction
    return SnapshotData(
        as_of=as_of,
        model_version=config["model_version"],
        coverage=[],
        context="synthetic score to isolate split machinery; not model validation",
        mode="RECONSTRUCCION",
        horizons=[
            HorizonResult(horizon=h, data_status="COMPLETO", score=70, regime="RISK_ON")
            for h in ("SHORT", "MEDIUM", "LONG")
        ],
    )


def test_empty_backtest_honestly_abstains():
    result = run_backtest([], config=DEFAULT_CONFIG, as_of=CUTOFF)
    assert result["status"] == "HISTORIA_INSUFICIENTE"
    assert result["calibration_status"] == "HEURISTICO_NO_VALIDADO"
    assert result["mode"] == "RECONSTRUCCION"
    for h in result["horizons"].values():
        assert h["folds"] == [] and h["effective_nonoverlapping"] == 0
        assert "MOVE" in h["missing_series"]


def test_official_reconstruction_ignores_ingestion_but_not_release():
    item = prices(1)[0]
    late = item.model_copy(
        update={
            "ingested_at": CUTOFF,
            "available_at": CUTOFF,
        }
    )
    records, excluded = _official_records([late], [], item.observed_at + dt.timedelta(days=1))
    assert not excluded and records[0].available_at == item.published_at
    unknown = late.model_copy(update={"vintage": "unknown"})
    assert _official_records([unknown], [], CUTOFF)[0] == []
    future = late.model_copy(update={"published_at": CUTOFF + dt.timedelta(days=1)})
    assert _official_records([future], [], CUTOFF)[0] == []


def test_date_vintage_requires_next_verified_session():
    data = prices(3)
    item = data[0].model_copy(update={"timestamp_precision": "date"})
    assert _official_records([item], [], CUTOFF)[0] == []
    records, _ = _official_records(
        [item, data[1]],
        [x.observed_at.date().isoformat() for x in data],
        CUTOFF,
    )
    assert records[0].available_at == data[1].observed_at


def test_labels_train_only_and_adverse_precedence():
    train = [{"return": float(i), "drawdown": float(10 - i)} for i in range(10)]
    thresholds = _thresholds(train, DEFAULT_CONFIG["validation"])
    assert thresholds["return_on"] == pytest.approx(5.4)
    assert _label({"return": 10, "drawdown": 0}, thresholds) == "RISK_ON"
    assert _label({"return": 10, "drawdown": 10}, thresholds) == "RISK_OFF"
    assert _label({"return": 4, "drawdown": 5}, thresholds) == "NEUTRAL"
    assert thresholds == _thresholds(train, DEFAULT_CONFIG["validation"])


def test_targets_are_actual_sessions_weeks_months():
    data = prices(400)
    dates = [x.observed_at.date() for x in data]
    assert _forward_end(dates, 0, "SHORT", 12) == 12
    medium = _forward_end(dates, 0, "MEDIUM", 8)
    assert (dates[medium] - dates[0]).days >= 56
    long = _forward_end(dates, 0, "LONG", 12)
    assert dates[long].year == dates[0].year + 1


def test_real_walk_forward_purges_mature_labels_and_embargo(monkeypatch):
    from homelab_dashboard.market_regime import validation

    monkeypatch.setattr(validation, "_calculate", fake_scores)
    data = prices(650)
    config = deepcopy(DEFAULT_CONFIG)
    config["validation"].update(train_min=5, test_size=10, sample_stride=3)
    config["rules"]["verified_sessions"] = [x.observed_at.date().isoformat() for x in data]
    cutoff = data[-1].observed_at
    result = run_backtest(data, config=config, as_of=cutoff)
    short = result["horizons"]["SHORT"]
    assert len(short["folds"]) >= 3
    assert short["metrics"]["n"] > 0 and short["immature_excluded"] > 0
    assert short["status"] == "DIAGNOSTICO_FUERA_DE_MUESTRA"
    assert short["effective_nonoverlapping"] >= 30
    dates = [x.observed_at.date() for x in data]
    for name, horizon in result["horizons"].items():
        for fold in horizon["folds"]:
            assert fold["train_latest_label"] < fold["fit_cutoff"]
            assert fold["train_latest_available"] < fold["fit_cutoff"]
            assert fold["train_latest_label"][:10] < fold["embargo_before"]
            assert fold["purged_or_embargoed"] > 0
            for sample in fold["samples"]:
                assert sample["issued_at"] < sample["entry_at"] < sample["label_end"]
                assert sample["label_end"] <= cutoff.isoformat()
                entry = dates.index(dt.datetime.fromisoformat(sample["entry_at"]).date())
                end = dates.index(dt.datetime.fromisoformat(sample["label_end"]).date())
                assert end == _forward_end(dates, entry, name, horizon["target_bars"])
    assert result["horizons"]["LONG"]["status"] == "HISTORIA_INSUFICIENTE"
    assert short["effective_nonoverlapping"] < short["metrics"]["n"]
    assert short["metrics"]["always_neutral_accuracy"] is not None


def test_no_vintage_never_generates_fake_folds():
    data = [x.model_copy(update={"vintage": "unknown"}) for x in prices(100)]
    result = run_backtest(data, config=DEFAULT_CONFIG, as_of=CUTOFF)
    assert result["excluded_observations"]["VINTAGE_OFICIAL_AUSENTE"] == 100
    assert all(h["folds"] == [] for h in result["horizons"].values())


def test_future_labels_cannot_change_training_thresholds(monkeypatch):
    from homelab_dashboard.market_regime import validation

    monkeypatch.setattr(validation, "_calculate", fake_scores)
    data = prices(350)
    config = deepcopy(DEFAULT_CONFIG)
    config["validation"].update(train_min=5, test_size=10, sample_stride=3)
    config["rules"]["verified_sessions"] = [x.observed_at.date().isoformat() for x in data]
    original = run_backtest(data, config=config, as_of=CUTOFF)
    first = original["horizons"]["SHORT"]["folds"][0]
    changed = [
        x.model_copy(update={"value": x.value * 2})
        if x.observed_at.isoformat() >= first["test_start"]
        else x
        for x in data
    ]
    result = run_backtest(changed, config=config, as_of=CUTOFF)
    assert result["horizons"]["SHORT"]["folds"][0]["thresholds"] == first["thresholds"]


def test_real_engine_backtest_reports_exploratory_limits():
    config = deepcopy(DEFAULT_CONFIG)
    config["validation"].update(train_min=5, test_size=2, sample_stride=100)
    data = complete_observations()
    config["rules"]["verified_sessions"] = sorted(
        {x.observed_at.date().isoformat() for x in data if x.series_id == "SPX"}
    )
    result = run_backtest(data, config=config, as_of=CUTOFF)
    short = result["horizons"]["SHORT"]
    assert short["folds"]
    assert short["metrics"]["classified"] > 0
    assert result["status"] == "HISTORIA_INSUFICIENTE"
    assert short["block_return_dispersion"] is None


def test_alternating_missing_sessions_cannot_stretch_short_target(monkeypatch):
    from homelab_dashboard.market_regime import validation

    def must_not_score(*args, **kwargs):
        pytest.fail("No window with missing required closes may be scored.")

    monkeypatch.setattr(validation, "_calculate", must_not_score)
    complete = prices(650)
    config = deepcopy(DEFAULT_CONFIG)
    config["rules"]["verified_sessions"] = [x.observed_at.date().isoformat() for x in complete]
    config["validation"].update(train_min=5, test_size=2, sample_stride=1)
    result = run_backtest(complete[::2], config=config, as_of=complete[-1].observed_at)
    for horizon in result["horizons"].values():
        assert horizon["mature_samples"] == 0
        assert horizon["folds"] == []
        assert horizon["missing_closes_excluded"] > 0
        assert horizon["status"] == "HISTORIA_INSUFICIENTE"


@pytest.mark.parametrize("horizon,gap_kind", [
    ("SHORT", "day"),
    ("MEDIUM", "week"),
    ("LONG", "month"),
])
def test_missing_day_week_or_month_excludes_entire_windows(monkeypatch, horizon, gap_kind):
    from homelab_dashboard.market_regime import validation

    monkeypatch.setattr(validation, "_calculate", fake_scores)
    complete = prices(1200)
    dates = [x.observed_at.date() for x in complete]
    gap_anchor = dates[650]
    gap = {
        day for day in dates
        if (day == gap_anchor if gap_kind == "day" else
            day.isocalendar()[:2] == gap_anchor.isocalendar()[:2] if gap_kind == "week" else
            (day.year, day.month) == (gap_anchor.year, gap_anchor.month))
    }
    config = deepcopy(DEFAULT_CONFIG)
    config["rules"]["verified_sessions"] = [day.isoformat() for day in dates]
    config["validation"].update(train_min=5, test_size=2, sample_stride=5)
    data = [x for x in complete if x.observed_at.date() not in gap]
    result = run_backtest(data, config=config, as_of=complete[-1].observed_at)
    selected = result["horizons"][horizon]
    assert selected["missing_closes_excluded"] > 0
    assert selected["folds"], "Complete windows outside the gap must remain evaluable."
    surviving = [row for fold in selected["folds"] for row in fold["samples"]]
    assert surviving
    for row in surviving:
        issue = dt.datetime.fromisoformat(row["issued_at"]).date()
        entry = dt.datetime.fromisoformat(row["entry_at"]).date()
        end = dt.datetime.fromisoformat(row["label_end"]).date()
        entry_index = bisect_left(dates, entry)
        assert entry_index == bisect_left(dates, issue) + 1
        expected_end = _forward_end(dates, entry_index, horizon, selected["target_bars"])
        assert end == dates[expected_end]
        assert not gap.intersection(dates[entry_index:expected_end + 1])
    if horizon == "SHORT":
        for fold in selected["folds"]:
            fit_day = dt.datetime.fromisoformat(fold["fit_cutoff"]).date()
            fit_index = dates.index(fit_day)
            assert fold["embargo_before"] == dates[max(0, fit_index - 12)].isoformat()


def test_missing_exit_close_is_not_replaced_by_next_available_price(monkeypatch):
    from homelab_dashboard.market_regime import validation

    monkeypatch.setattr(validation, "_calculate", fake_scores)
    complete = prices(100)
    config = deepcopy(DEFAULT_CONFIG)
    config["rules"]["verified_sessions"] = [x.observed_at.date().isoformat() for x in complete]
    config["validation"].update(train_min=5, test_size=2, sample_stride=1)
    baseline = run_backtest(complete, config=config, as_of=complete[-1].observed_at)
    first = baseline["horizons"]["SHORT"]["folds"][0]["samples"][0]
    missing_end = dt.datetime.fromisoformat(first["label_end"])
    result = run_backtest(
        [x for x in complete if x.observed_at != missing_end],
        config=config, as_of=complete[-1].observed_at,
    )
    assert result["horizons"]["SHORT"]["missing_closes_excluded"] > 0
    survivors = [
        row for fold in result["horizons"]["SHORT"]["folds"] for row in fold["samples"]
    ]
    assert all(row["issued_at"] != first["issued_at"] for row in survivors)


def test_unverified_calendar_cannot_generate_labels(monkeypatch):
    from homelab_dashboard.market_regime import validation

    monkeypatch.setattr(validation, "_calculate", fake_scores)
    result = run_backtest(prices(100), config=DEFAULT_CONFIG, as_of=CUTOFF)
    for horizon in result["horizons"].values():
        assert horizon["mature_samples"] == 0
        assert horizon["folds"] == []
        assert horizon["unverified_calendar_excluded"] > 0
