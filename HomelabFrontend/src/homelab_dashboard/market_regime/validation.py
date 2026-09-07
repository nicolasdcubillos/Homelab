"""Purged expanding walk-forward diagnostics, explicitly not production calibration."""

from __future__ import annotations

import calendar
import datetime as dt
from bisect import bisect_left, bisect_right
from collections import Counter
from statistics import mean

from .config import HORIZONS, validate_config
from .features import drawdown, period_date, quantile, utc
from .schemas import Observation
from .scoring import _calculate, raw_regime

LABELS = ("RISK_OFF", "NEUTRAL", "RISK_ON")


def _months(day: dt.date, count: int) -> dt.date:
    index = day.year * 12 + day.month - 1 + count
    year, month = divmod(index, 12)
    return dt.date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _forward_end(dates: list[dt.date], entry: int, horizon: str, count: int) -> int:
    if horizon == "SHORT":
        return entry + count
    end = (
        dates[entry] + dt.timedelta(weeks=count)
        if horizon == "MEDIUM"
        else _months(dates[entry], count)
    )
    return bisect_left(dates, end)


def _embargo_start(
    dates: list[dt.date],
    test_start: int,
    horizon: str,
    bars: int,
) -> dt.date:
    if horizon == "SHORT":
        return dates[max(0, test_start - bars)]
    if horizon == "MEDIUM":
        return dates[test_start] - dt.timedelta(weeks=bars)
    return _months(dates[test_start], -bars)


def _thresholds(train: list[dict], config: dict) -> dict:
    returns = [x["return"] for x in train]
    drawdowns = [x["drawdown"] for x in train]
    return {
        "return_on": quantile(returns, config["return_favorable_quantile"]),
        "return_off": quantile(returns, config["return_adverse_quantile"]),
        "drawdown_on": quantile(drawdowns, config["drawdown_favorable_quantile"]),
        "drawdown_off": quantile(drawdowns, config["drawdown_adverse_quantile"]),
    }


def _label(sample: dict, thresholds: dict) -> str:
    if (
        sample["return"] <= thresholds["return_off"]
        or sample["drawdown"] >= thresholds["drawdown_off"]
    ):
        return "RISK_OFF"
    if (
        sample["return"] >= thresholds["return_on"]
        and sample["drawdown"] <= thresholds["drawdown_on"]
    ):
        return "RISK_ON"
    return "NEUTRAL"


def _metrics(rows: list[dict]) -> dict:
    eligible = [x for x in rows if x["prediction"] is not None]
    confusion = {truth: {pred: 0 for pred in LABELS} for truth in LABELS}
    for row in eligible:
        confusion[row["label"]][row["prediction"]] += 1
    per_class = {}
    for label in LABELS:
        tp = confusion[label][label]
        fn = sum(confusion[label].values()) - tp
        fp = sum(confusion[x][label] for x in LABELS if x != label)
        tn = len(eligible) - tp - fn - fp
        per_class[label] = {
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "false_positive_rate": fp / (fp + tn) if fp + tn else None,
            "false_negative_rate": fn / (fn + tp) if fn + tp else None,
        }
    distributions = {}
    for regime in LABELS:
        selected = [x for x in eligible if x["prediction"] == regime]
        returns = [x["return"] for x in selected]
        distributions[regime] = {
            "n": len(selected),
            "mean_return": mean(returns) if returns else None,
            "p20": quantile(returns, 0.2) if returns else None,
            "median": quantile(returns, 0.5) if returns else None,
            "p80": quantile(returns, 0.8) if returns else None,
            "mean_drawdown": mean(x["drawdown"] for x in selected) if selected else None,
        }
    return {
        "n": len(rows),
        "classified": len(eligible),
        "abstentions": len(rows) - len(eligible),
        "coverage": len(eligible) / len(rows) if rows else 0,
        "confusion": confusion,
        "per_class": per_class,
        "conditional_returns": distributions,
        "unconditional": {
            "mean_return": mean(x["return"] for x in rows) if rows else None,
            "mean_drawdown": mean(x["drawdown"] for x in rows) if rows else None,
        },
        "always_neutral_accuracy": (
            sum(x["label"] == "NEUTRAL" for x in rows) / len(rows) if rows else None
        ),
        "model_accuracy": (
            sum(x["label"] == x["prediction"] for x in eligible) / len(eligible)
            if eligible
            else None
        ),
        "transition_rate": (
            sum(a["prediction"] != b["prediction"] for a, b in zip(eligible, eligible[1:]))
            / (len(eligible) - 1)
            if len(eligible) > 1
            else None
        ),
    }


def _nonoverlapping(rows: list[dict]) -> list[dict]:
    selected = []
    last_end = None
    for row in sorted(rows, key=lambda x: x["entry_at"]):
        if row["prediction"] is not None and (last_end is None or row["entry_at"] > last_end):
            selected.append(row)
            last_end = row["label_end"]
    return selected


def _interval(rows: list[dict], minimum: int) -> dict | None:
    """Contiguous nonoverlapping blocks, not a misleading iid observation interval."""
    if len(rows) < minimum:
        return None
    block_size = max(2, int(len(rows) ** 0.5))
    blocks = [rows[i : i + block_size] for i in range(0, len(rows), block_size)]
    if len(blocks[-1]) != block_size:
        blocks.pop()
    means = [mean(x["return"] for x in block) for block in blocks]
    if len(means) < 3:
        return None
    return {
        "method": "dispersion empirica p5-p95 de medias por bloques contiguos; no IC de acierto",
        "block_size": block_size,
        "blocks": len(means),
        "low": quantile(means, 0.05),
        "high": quantile(means, 0.95),
    }


def _official_records(
    observations: list[Observation],
    sessions: list[str],
    as_of: dt.datetime,
) -> tuple[list[Observation], Counter]:
    valid, excluded = [], Counter()
    dates = [dt.date.fromisoformat(x) for x in sessions]
    session_closes = {}
    for item in observations:
        if item.series_id == "SPX" and item.quality == "OK" and item.observed_at <= as_of:
            session_closes[period_date(item)] = item.observed_at
    for item in observations:
        if item.vintage in ("", "unknown", "current", "revised") or item.published_at is None:
            excluded["VINTAGE_OFICIAL_AUSENTE"] += 1
            continue
        available = item.published_at
        if item.timestamp_precision == "date":
            next_index = bisect_right(dates, available.date())
            next_day = dates[next_index] if next_index < len(dates) else None
            if next_day is None or next_day not in session_closes:
                excluded["CALENDARIO_VINTAGE_FECHA_AUSENTE"] += 1
                continue
            # The next verified close is later than the open and therefore conservative.
            available = max(available, session_closes[next_day])
        elif item.timestamp_precision != "exact":
            excluded["PUBLICACION_NO_DEMOSTRABLE"] += 1
            continue
        if available > as_of or item.observed_at > as_of:
            excluded["POSTERIOR_AL_CORTE"] += 1
            continue
        valid.append(
            item.model_copy(
                update={
                    "available_at": available,
                    "published_at": available,
                    "timestamp_precision": "exact",
                }
            )
        )
    return valid, excluded


def run_backtest(
    observations: list[Observation],
    *,
    config: dict,
    as_of: dt.datetime,
) -> dict:
    config = validate_config(config)
    cutoff = utc(as_of)
    settings = config["validation"]
    records, excluded = _official_records(
        observations,
        config["rules"]["verified_sessions"],
        cutoff,
    )
    price_versions = {}
    for item in records:
        if (
            item.series_id == "SPX"
            and item.quality == "OK"
            and item.value > 0
            and item.unit in config["series"]["SPX"]["units"]
        ):
            day = period_date(item)
            price_versions.setdefault(day, []).append(item)
    # Earliest official close vintage, not a retrospectively adjusted final-price series.
    prices = [
        min(versions, key=lambda x: (x.available_at, x.vintage, x.raw_hash))
        for _, versions in sorted(price_versions.items())
    ]
    dates = [period_date(x) for x in prices]
    timestamps = [x.observed_at for x in prices]
    limitations = [
        "HEURISTICO_NO_VALIDADO: ejecucion retrospectiva no valida ni promociona el modelo.",
        "RECONSTRUCCION con vintages oficiales, no historia operacional de la aplicacion.",
        "Retorno de precio SPX, NO retorno total: dividendos/ajustes no incluidos en el contrato.",
        "Derechos y autenticidad del manifiesto de vintages deben verificarse fuera del motor.",
        "Predicciones de bandas brutas; no simula ejecucion, costes ni ordenes.",
        "Sensibilidad de horizontes requiere corridas separadas, no se selecciona sobre el test.",
    ]
    calendar_set = set(config["rules"]["verified_sessions"])
    calendar_ok = bool(dates) and all(x.isoformat() in calendar_set for x in dates)
    if not calendar_ok:
        limitations.append("CALENDARIO_NO_DISPONIBLE: sesiones SPX no verificadas completamente.")
    if excluded:
        limitations.append(
            "Vintages/fechas excluidas: "
            + ", ".join(f"{k}={v}" for k, v in sorted(excluded.items()))
        )
    by_horizon = {}
    snapshots = {}
    for horizon in HORIZONS:
        target = config["horizons"][horizon]["target_bars"]
        samples = []
        immature = 0
        for index in range(0, max(0, len(prices) - 1), settings["sample_stride"]):
            issued_at = max(prices[index].observed_at, prices[index].available_at)
            entry = bisect_right(timestamps, issued_at)
            if entry >= len(prices):
                immature += 1
                continue
            end = _forward_end(dates, entry, horizon, target)
            if (
                end >= len(prices)
                or prices[end].available_at > cutoff
                or prices[end].observed_at > cutoff
            ):
                immature += 1
                continue
            path = [float(x.value) for x in prices[entry : end + 1]]
            if issued_at not in snapshots:
                snapshots[issued_at] = _calculate(
                    records,
                    as_of=issued_at,
                    config=config,
                    coverage=[],
                    reconstruction=True,
                )
            result = next(x for x in snapshots[issued_at].horizons if x.horizon == horizon)
            samples.append(
                {
                    "index": index,
                    "issued_at": issued_at.isoformat(),
                    "entry_at": prices[entry].observed_at.isoformat(),
                    "label_end": prices[end].observed_at.isoformat(),
                    "label_available_at": max(
                        x.available_at for x in prices[entry : end + 1]
                    ).isoformat(),
                    "return": path[-1] / path[0] - 1,
                    "drawdown": drawdown(path)[0],
                    "score": result.score,
                    "prediction": raw_regime(result.score) if result.score is not None else None,
                    "missing": result.missing,
                }
            )
        folds, evaluated = [], []
        start = settings["train_min"]
        while start < len(samples):
            test = samples[start : start + settings["test_size"]]
            if len(test) < settings["test_size"]:
                break
            fit_cutoff = test[0]["issued_at"]
            embargo_date = _embargo_start(
                dates,
                test[0]["index"],
                horizon,
                settings["embargo_bars"][horizon],
            )
            train = [
                x
                for x in samples[:start]
                if x["label_end"] < fit_cutoff
                and x["label_available_at"] < fit_cutoff
                and dt.datetime.fromisoformat(x["label_end"]).date() < embargo_date
            ]
            if len(train) < settings["train_min"]:
                start += settings["test_size"]
                continue
            thresholds = _thresholds(train, settings)
            rows = [{**x, "label": _label(x, thresholds)} for x in test]
            # No test labels/returns feed the current fold's frozen quantiles.
            evaluated.extend(rows)
            folds.append(
                {
                    "fold": len(folds) + 1,
                    "fit_cutoff": fit_cutoff,
                    "train_count": len(train),
                    "purged_or_embargoed": start - len(train),
                    "train_latest_label": max(x["label_end"] for x in train),
                    "train_latest_available": max(x["label_available_at"] for x in train),
                    "embargo_before": embargo_date.isoformat(),
                    "embargo_bars": settings["embargo_bars"][horizon],
                    "test_start": test[0]["issued_at"],
                    "test_end": test[-1]["issued_at"],
                    "thresholds": thresholds,
                    "metrics": _metrics(rows),
                    "samples": rows,
                }
            )
            start += settings["test_size"]
        independent = _nonoverlapping(evaluated)
        eligible_folds = sum(x["metrics"]["classified"] > 0 for x in folds)
        sufficient = (
            eligible_folds >= settings["min_folds"]
            and len(independent) >= settings["min_nonoverlapping"]
            and calendar_ok
        )
        missing_series = sorted(set(config["required_series"]) - {x.series_id for x in records})
        by_horizon[horizon] = {
            "status": "DIAGNOSTICO_FUERA_DE_MUESTRA" if sufficient else "HISTORIA_INSUFICIENTE",
            "target_bars": target,
            "folds": folds,
            "eligible_folds": eligible_folds,
            "mature_samples": len(samples),
            "immature_excluded": immature,
            "effective_nonoverlapping": len(independent),
            "overlapping_classified": sum(x["prediction"] is not None for x in evaluated)
            - len(independent),
            "metrics": _metrics(evaluated),
            "block_return_dispersion": _interval(independent, settings["min_nonoverlapping"]),
            "missing_series": missing_series,
            "limitations": (
                []
                if sufficient
                else [
                    f"Requiere >= {settings['min_folds']} folds elegibles y "
                    f">= {settings['min_nonoverlapping']} ventanas maduras no solapadas, "
                    "ademas de calendario, cobertura e historia causal suficientes."
                ]
            ),
        }
    return {
        "status": (
            "DIAGNOSTICO_FUERA_DE_MUESTRA"
            if all(x["status"] != "HISTORIA_INSUFICIENTE" for x in by_horizon.values())
            else "HISTORIA_INSUFICIENTE"
        ),
        "mode": "RECONSTRUCCION",
        "as_of": cutoff.isoformat(),
        "model_version": config["model_version"],
        "calibration_status": "HEURISTICO_NO_VALIDADO",
        "config": config,
        "horizons": by_horizon,
        "limitations": limitations,
        "excluded_observations": dict(excluded),
        "dataset": {
            "observations": len(records),
            "spx_sessions": len(prices),
            "raw_hashes": sorted({x.raw_hash for x in records if x.raw_hash}),
            "sources": sorted({x.source_id for x in records}),
            "vintages": sorted({x.vintage for x in records}),
        },
    }
