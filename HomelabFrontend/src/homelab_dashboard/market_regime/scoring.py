"""Pure, abstention-first, seven-category regime evaluation."""

from __future__ import annotations

import datetime as dt

from .config import CATEGORIES, HORIZONS, validate_config
from .context import build_context, conditional_fx, conditional_rates
from .features import (
    closed_bars,
    drawdown,
    evidence,
    evolution,
    level_change,
    percentile,
    period_date,
    point_in_time,
    quantile,
    sign,
    structure,
    utc,
)
from .schemas import CategoryResult, CoverageItem, HorizonResult, Observation, SnapshotData


def raw_regime(score: float) -> str:
    return "RISK_OFF" if score < 40 else "RISK_ON" if score > 60 else "NEUTRAL"


def _category(name: str, weight: float, value: float | None, reason: str, items=()):
    return CategoryResult(
        category=name,
        weight=weight,
        value=value,
        contribution=weight * (value + 1) / 2 if value is not None else None,
        reason=reason,
        evidence=list(items),
    )


def _require(data, errors, names, minimum=1):
    missing = []
    for name in names:
        if name in errors:
            missing.append(f"{name}: {errors[name]}")
        elif len(data.get(name, [])) < minimum:
            missing.append(f"{name}: HISTORIA_INSUFICIENTE ({minimum} cierres requeridos).")
    if missing:
        raise ValueError(" ".join(missing))


def _volatility(data, bars, errors, horizon, rules):
    names = ("VIX", "MOVE")
    _require(data, errors, names, rules["history_min"] + 1)
    values, readings = [], []
    low, elevated, stress, extreme = rules["volatility_quantiles"]
    table = rules["volatility_values"]
    for name in names:
        items = data[name]
        if any(x.frequency != "daily" for x in items):
            raise ValueError(f"{name}: referencia requiere sesiones diarias.")
        selected = items[-rules["history_max"] - 1 :]
        reference = [float(x.value) for x in selected[:-1]]
        latest = float(selected[-1].value)
        rank = percentile(reference, latest, minimum=rules["history_min"])
        changes = [abs(b - a) for a, b in zip(reference, reference[1:])]
        rapid_threshold = quantile(changes, rules["rapid_quantile"] / 100)
        change, used = level_change(bars[name], horizon["change_bars"])
        last_change = latest - reference[-1]
        rapid = abs(last_change) >= rapid_threshold and abs(last_change) > 0
        tail = [float(x.value) for x in selected[-rules["persistence_bars"] - 1 :]]
        persistent = all(sign(b - a) == sign(change) for a, b in zip(tail, tail[1:]))
        if rank >= extreme:
            value, band = table["extreme"], "EXTREMO"
        elif rank >= stress:
            value, band = table["stress"], "ESTRES"
        elif rank >= elevated:
            value, band = table["elevated"], "ELEVADO"
        else:
            value = (
                table["normal_falling_persistent"]
                if change < 0 and persistent
                else table["unresolved"]
            )
            band = "MUY_BAJO" if rank < low else "NORMAL"
        if rapid and last_change > 0:
            value = min(value, table["rapid_increase"])
        values.append(value)
        readings.append(
            evidence(
                name,
                selected + used,
                f"{band}; percentil={rank:.2f}, n_previo={len(reference)}; "
                f"cambio_{horizon['change_bars']}_{horizon['bar_frequency']}={change:.4f}; "
                f"rapido={rapid}; persistencia={persistent}; nivel bajo solo no favorece riesgo.",
                value,
            )
        )
    pair = rules["pair_weights"]
    return values[0] * pair["first"] + values[1] * pair["second"], readings


def _credit(data, bars, errors, horizon, rules):
    names = ("HY_OAS", "IG_OAS")
    _require(data, errors, names, rules["history_min"] + 1)
    if period_date(data[names[0]][-1]) != period_date(data[names[1]][-1]):
        raise ValueError("HY_OAS/IG_OAS: cierres no comparables en fecha.")
    values, readings = [], []
    for name in names:
        items = data[name][-rules["history_max"] - 1 :]
        if any(x.frequency != "daily" for x in items):
            raise ValueError(f"{name}: referencia requiere sesiones diarias.")
        rank = percentile(
            [float(x.value) for x in items[:-1]],
            float(items[-1].value),
            minimum=rules["history_min"],
        )
        change, used = level_change(bars[name], horizon["change_bars"])
        progress = evolution([float(x.value) for x in used], rules["direction_epsilon"])
        value = -progress.direction
        if rank >= rules["credit_stress_quantile"] and change >= 0:
            value = -1
        readings.append(
            evidence(
                name,
                items + used,
                f"percentil OAS={rank:.2f}; cambio={change:.4f} {items[-1].unit}; "
                f"persistencia={progress.persistence:.2f}; no se confunde nivel con precio.",
                value,
            )
        )
        values.append(value)
    pair = rules["pair_weights"]
    return values[0] * pair["first"] + values[1] * pair["second"], readings


def _equity(bars, errors, horizon, rules):
    names = ("SPX", "ES", "NDX", "NQ", "RUSSELL", "DOW")
    _require(bars, errors, names, horizon["structure_bars"])
    readings, values = [], {}
    for name in names:
        items = bars[name][-horizon["structure_bars"] :]
        value, reading = structure(items, side=rules["pivot_side"])
        dd, duration = drawdown([float(x.value) for x in items])
        change = float(items[-1].value / items[0].value) - 1
        readings.append(
            evidence(
                name,
                items,
                f"{horizon['bar_frequency']}, {len(items)} cierres; {reading}; "
                f"retorno_precio={change:.4%}; drawdown={dd:.4%}; duracion={duration} barras."
                + (" Confirmador, peso numerico cero." if name in ("ES", "NQ") else ""),
                value,
            )
        )
        if name not in ("ES", "NQ"):
            current_drawdown = float(items[-1].value / max(x.value for x in items)) - 1
            derived = evidence(
                f"{name}:DRAWDOWN",
                items,
                f"Retroceso vigente desde maximo de ventana={current_drawdown:.4%}; "
                "transformacion de cierres, no otro aporte numerico.",
                current_drawdown,
            )
            derived.value = current_drawdown
            derived.unit = "fraction"
            readings.append(derived)
        values[name] = value
    value = sum(values[name] * weight for name, weight in rules["equity_weights"].items())
    contradictions = []
    for index, future in (("SPX", "ES"), ("NDX", "NQ")):
        if sign(values[index]) != sign(values[future]):
            contradictions.append(f"{index}/{future}: estructura divergente; futuro no suma peso.")
    spx = {period_date(x): x for x in bars["SPX"]}
    russell = [x for x in bars["RUSSELL"] if period_date(x) in spx]
    if len(russell) < horizon["structure_bars"]:
        raise ValueError("RUSSELL/SPX: historia de fuerza relativa sincronizada insuficiente.")
    used = russell[-horizon["structure_bars"] :]
    first, last = used[0], used[-1]
    relative = (last.value / spx[period_date(last)].value) / (
        first.value / spx[period_date(first)].value
    ) - 1
    readings.append(
        evidence(
            "RUSSELL/SPX",
            used + [spx[period_date(x)] for x in used],
            f"fuerza relativa={float(relative):.4%}; diagnostico, sin duplicar indices.",
            float(relative),
        )
    )
    return value, readings, contradictions


def _cross(categories, data, errors):
    base = {x.category: x for x in categories}
    if any(x.value is None for x in categories):
        raise ValueError("Relaciones tasas/FX/volatilidad/credito-equity no evaluables.")
    majority = sign(sum(x.value * x.weight for x in categories))
    conflict = sign(base["MACRO"].value) * sign(base["CREDIT"].value) < 0
    confirmations, readings = 0, []
    equity_sign = sign(base["EQUITY"].value)
    for name in ("RATES", "FX", "VOLATILITY", "CREDIT"):
        direction = sign(base[name].value)
        agrees = direction == equity_sign == majority and majority != 0
        confirmations += int(agrees)
        lineage = [e for c in (base[name], base["EQUITY"]) for e in c.evidence]
        relation = f"{name}-EQUITY"
        reading = (
            "CONFIRMACION"
            if agrees
            else "CONTRADICCION"
            if direction * equity_sign < 0
            else "MIXTA"
        )
        readings.append(evidence(relation, [], reading, majority if agrees else 0))
        readings[-1].observation_ids = sorted(
            {oid for item in lineage for oid in item.observation_ids}
        )
        readings[-1].available_at = max(
            (item.available_at for item in lineage if item.available_at),
            default=None,
        )
    value = 0 if conflict else majority * confirmations / 4
    reason = (
        "Macro y credito contradicen; interaccion cero."
        if conflict
        else f"{confirmations}/4 relaciones confirman direccion {majority}; sin re-sumar niveles."
    )
    if data.get("NFCI") and "NFCI" not in errors:
        readings.append(
            evidence(
                "NFCI",
                data["NFCI"][-1:],
                "Diagnostico de condiciones financieras, PESO CERO; habilitacion explicita.",
                0,
            )
        )
    else:
        readings.append(
            evidence(
                "NFCI",
                [],
                errors.get("NFCI", "SIN_DATOS") + "; diagnostico de peso cero.",
                None,
            )
        )
    return value, reason, readings


def _calculate(
    observations: list[Observation],
    *,
    as_of: dt.datetime,
    config: dict,
    coverage: list[CoverageItem],
    reconstruction: bool = False,
) -> SnapshotData:
    config = validate_config(config)
    cutoff = utc(as_of)
    data, errors = point_in_time(observations, cutoff, config, reconstruction=reconstruction)
    required = set(config["required_series"]) | {x.series_id for x in coverage if x.required}
    for item in coverage:
        if not item.available:
            errors[item.series_id] = item.reason or "REQUISITO_NO_DISPONIBLE"
    if not any(x.series_id == "NFCI" and x.available for x in coverage):
        errors.setdefault("NFCI", "DIAGNOSTICO_NO_HABILITADO: requiere derechos explicitos.")
    global_missing = [
        f"{name}: {errors.get(name, 'SIN_DATOS')}"
        for name in sorted(required)
        if name in errors or not data.get(name)
    ]
    results, contexts = [], []
    rules = config["rules"]
    for name in HORIZONS:
        horizon = config["horizons"][name]
        weights = horizon["weights"]
        bars = {
            k: closed_bars(v, horizon["bar_frequency"], cutoff, rules["verified_sessions"])
            for k, v in data.items()
        }
        context = build_context(data, errors, horizon, config, cutoff)
        contexts.append(f"{name}: {context.name}")
        categories = [
            _category(
                "MACRO",
                weights["MACRO"],
                context.value,
                context.name
                + (
                    "; " + " ".join(context.missing)
                    if context.missing
                    else "; hipotesis conjunta, no atribucion causal."
                ),
                context.evidence,
            )
        ]
        contradictions = list(context.contradictions)
        computed = {}
        for category, function in (("VOLATILITY", _volatility), ("CREDIT", _credit)):
            try:
                value, readings = function(data, bars, errors, horizon, rules)
                reason = "Reglas de nivel, cambio y persistencia conjuntas."
                if readings[0].direction != readings[1].direction:
                    contradictions.append(f"{category}: componentes divergentes.")
            except (ValueError, KeyError) as exc:
                value, readings, reason = None, [], str(exc)
            computed[category] = _category(category, weights[category], value, reason, readings)
        try:
            _require(bars, errors, ("US02Y", "US10Y"), horizon["change_bars"] + 1)
            common = sorted(
                set(period_date(x) for x in bars["US02Y"])
                & set(period_date(x) for x in bars["US10Y"])
            )
            if len(common) < horizon["change_bars"] + 1 or period_date(
                bars["US02Y"][-1]
            ) != period_date(bars["US10Y"][-1]):
                raise ValueError("US02Y/US10Y: niveles de fechas no comparables.")
            aligned = {
                k: [x for x in bars[k] if period_date(x) in common] for k in ("US02Y", "US10Y")
            }
            two, two_used = level_change(aligned["US02Y"], horizon["change_bars"])
            ten, ten_used = level_change(aligned["US10Y"], horizon["change_bars"])
            value = conditional_rates(context, two, ten, rules)
            slope = float(ten_used[-1].value - two_used[-1].value)
            curve = (
                "steepening"
                if ten - two > 0
                else "flattening"
                if ten - two < 0
                else "sin cambio de pendiente"
            )
            move = "bear" if two > 0 and ten > 0 else "bull" if two < 0 and ten < 0 else "mixta"
            reason = f"{context.name}; {move} {curve}; 2s10s={slope:.4f} puntos porcentuales."
            readings = [
                evidence(k, used, f"cambio de nivel={change:.4f}; {reason}", value)
                for k, used, change in (("US02Y", two_used, two), ("US10Y", ten_used, ten))
            ]
        except (ValueError, KeyError) as exc:
            value, readings, reason = None, [], str(exc)
        computed["RATES"] = _category("RATES", weights["RATES"], value, reason, readings)
        try:
            _require(bars, errors, ("DXY", "USDJPY"), horizon["structure_bars"])
            fx = {}
            readings = []
            for series in ("DXY", "USDJPY"):
                used = bars[series][-horizon["structure_bars"] :]
                delta, tail = level_change(used, horizon["change_bars"])
                progress = evolution([float(x.value) for x in tail], rules["direction_epsilon"])
                structural, explanation = structure(used, side=rules["pivot_side"])
                fx[series] = (
                    structural * rules["pair_weights"]["first"]
                    + progress.direction * rules["pair_weights"]["second"]
                )
                readings.append(
                    evidence(
                        series,
                        used,
                        f"{explanation}; estructura={structural}; cambio={delta:.4f}; "
                        f"persistencia={progress.persistence:.2f}; convencion {used[-1].unit}."
                        + (
                            " H.10 fixing de mediodia NY, no cierre spot "
                            "ni cotizacion en tiempo real."
                            if series == "USDJPY"
                            else ""
                        ),
                        0,
                    )
                )
            value = conditional_fx(
                context,
                fx["DXY"],
                fx["USDJPY"],
                computed["CREDIT"].value,
                computed["VOLATILITY"].value,
                rules,
            )
            reason = f"{context.name}; USD condicionado a macro y confirmadores, no signo fijo."
            for item in readings:
                item.direction = "FAVORABLE" if value > 0 else "ADVERSA" if value < 0 else "MIXTA"
        except (ValueError, KeyError) as exc:
            value, readings, reason = None, [], str(exc)
        computed["FX"] = _category("FX", weights["FX"], value, reason, readings)
        try:
            value, readings, equity_conflicts = _equity(bars, errors, horizon, rules)
            contradictions.extend(equity_conflicts)
            reason = "Indices ponderados; ES/NQ y fuerza relativa solo confirmacion."
        except (ValueError, KeyError) as exc:
            value, readings, reason = None, [], str(exc)
        computed["EQUITY"] = _category("EQUITY", weights["EQUITY"], value, reason, readings)
        categories.extend(computed[k] for k in CATEGORIES[1:-1])
        if context.value is not None and computed["EQUITY"].value is not None:
            if sign(context.value) * sign(computed["EQUITY"].value) < 0:
                contradictions.append("MACRO/EQUITY: mercado y evidencia superior se contradicen.")
        try:
            value, reason, readings = _cross(categories, data, errors)
            if (
                context.value is not None
                and computed["CREDIT"].value is not None
                and sign(context.value) * sign(computed["CREDIT"].value) < 0
            ):
                contradictions.append("MACRO/CREDIT: evidencia superior y credito discrepan.")
            contradictions.extend(
                f"{item.series_id}: contradiccion cross-asset; ids={item.observation_ids}."
                for item in readings
                if item.reading == "CONTRADICCION"
            )
        except ValueError as exc:
            value, readings, reason = None, [], str(exc)
        categories.append(_category("CROSS_ASSET", weights["CROSS_ASSET"], value, reason, readings))
        missing = sorted(
            set(
                global_missing
                + context.missing
                + [f"{x.category}: {x.reason}" for x in categories if x.value is None]
            )
        )
        score = None if missing else sum(x.contribution for x in categories)
        status = "SIN_DATOS" if not data else "INCOMPLETO" if missing else "COMPLETO"
        precision = all(
            x.timestamp_precision == "exact" and x.ingested_at is not None
            for k in required
            for x in data.get(k, [])
        )
        confidence = (
            "NO_EVALUABLE"
            if score is None
            else "BAJA"
            if contradictions
            else "ALTA"
            if precision
            else "MEDIA"
        )
        drivers = [
            f"{x.category}: valor={x.value:+.3f}, aporte={x.contribution:.3f}; {x.reason}"
            for x in sorted(
                (x for x in categories if x.value is not None),
                key=lambda x: abs(x.value * x.weight),
                reverse=True,
            )[:3]
        ]
        drivers.append(
            f"Calidad: cobertura={'completa' if not global_missing else 'incompleta'}, "
            f"frescura={'insuficiente' if required.intersection(errors) else 'sin incidencias'}, "
            f"precision_temporal={'exacta' if precision else 'limitada'}, "
            f"acuerdo={'contradicciones' if contradictions else 'sin conflicto detectado'}, "
            f"historia={'suficiente' if score is not None else 'no certificable'}; no es acierto."
        )
        transition = config["transition"]
        would_change = [f"Completar/actualizar: {item}" for item in missing] or [
            f"{name}: entrada On >= {transition['entry_on']}, Off <= "
            f"{transition['entry_off']}; >= {transition['aligned_categories']} categorias, "
            "incluida MACRO o CREDIT, deben alinearse.",
            f"Persistir {transition['persistence'][name]} cierres nuevos "
            f"{horizon['bar_frequency']}; sin contar recalculos.",
            "Reevaluar GDP/empleo junto a CPI/PCE y FED_FUNDS/FED_BALANCE; "
            "credito y volatilidad deben confirmar, no reemplazar macro.",
        ]
        results.append(
            HorizonResult(
                horizon=name,
                data_status=status,
                score=score,
                regime=raw_regime(score) if score is not None else None,
                confidence=confidence,
                categories=categories,
                drivers=drivers,
                contradictions=contradictions,
                changes=[
                    "Sin snapshot anterior comparable; cambios interpublicacion en evidencia."
                ],
                would_change=would_change,
                missing=missing,
            )
        )
    return SnapshotData(
        as_of=cutoff,
        model_version=config["model_version"],
        horizons=results,
        coverage=coverage,
        context=" | ".join(contexts),
        mode="RECONSTRUCCION" if reconstruction else "OPERACIONAL",
    )


def calculate(
    observations: list[Observation],
    *,
    as_of: dt.datetime,
    config: dict,
    coverage: list[CoverageItem],
) -> SnapshotData:
    return _calculate(observations, as_of=as_of, config=config, coverage=coverage)
