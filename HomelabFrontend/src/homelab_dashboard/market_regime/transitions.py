"""Pure transition state machine; its caller atomically persists the returned state."""

from __future__ import annotations

import datetime as dt
import re
from copy import deepcopy

from .config import DEFAULT_CONFIG, TransitionConfig
from .features import sign, utc
from .schemas import HorizonResult


def _bar_date(key: str, horizon: str) -> dt.date:
    if horizon == "MEDIUM" and re.fullmatch(r"\d{4}-W\d{2}", key):
        return dt.date.fromisocalendar(int(key[:4]), int(key[-2:]), 1)
    if horizon == "LONG" and re.fullmatch(r"\d{4}-\d{2}", key):
        return dt.date.fromisoformat(key + "-01")
    day = dt.date.fromisoformat(key)
    if horizon == "MEDIUM":
        return day - dt.timedelta(days=day.weekday())
    return day.replace(day=1) if horizon == "LONG" else day


def _target(score: float, confirmed: str | None, rules: dict) -> str:
    if confirmed == "RISK_ON" and score >= rules["exit_on"]:
        return "RISK_ON"
    if confirmed == "RISK_OFF" and score <= rules["exit_off"]:
        return "RISK_OFF"
    return (
        "RISK_ON"
        if score >= rules["entry_on"]
        else "RISK_OFF"
        if score <= rules["entry_off"]
        else "NEUTRAL"
    )


def _aligned(current: HorizonResult, target: str, minimum: int) -> bool:
    direction = 1 if target == "RISK_ON" else -1 if target == "RISK_OFF" else 0
    categories = [
        x.category
        for x in current.categories
        if x.category != "CROSS_ASSET"
        and x.value is not None
        and (sign(x.value) == direction if direction else abs(x.value) <= 0.5)
    ]
    return len(categories) >= minimum and bool({"MACRO", "CREDIT"} & set(categories))


def advance_transition(
    current: HorizonResult,
    previous_state: dict | None,
    *,
    bar_key: str,
    as_of: dt.datetime,
) -> tuple[HorizonResult, dict]:
    """Supply ``previous_state['rules'] = config['transition']`` on model activation.

    ``bar_key`` identifies a closed daily session, ISO week, or calendar month.
    DB uniqueness/leases and the verified calendar remain the caller's responsibility.
    Rules travel in the persisted state so a replay never silently changes thresholds.
    """
    cutoff = utc(as_of)
    state = deepcopy(previous_state or {})
    rules = TransitionConfig.model_validate(
        state.get("rules", DEFAULT_CONFIG["transition"]),
    ).model_dump()
    state["rules"] = rules
    if state.get("horizon", current.horizon) != current.horizon:
        raise ValueError("No se comparte estado entre horizontes.")
    state["horizon"] = current.horizon
    day = _bar_date(bar_key, current.horizon)
    if day > cutoff.date():
        raise ValueError("Barra futura no cerrada.")
    old_day = (
        _bar_date(state["last_bar_key"], current.horizon) if state.get("last_bar_key") else None
    )
    previous_asof = dt.datetime.fromisoformat(state["as_of"]) if state.get("as_of") else None
    if old_day is not None and (day < old_day or (previous_asof and cutoff < previous_asof)):
        raise ValueError("No se avanza ni reconstruye una transicion retroactivamente.")
    if old_day is not None and day == old_day:
        if current.data_status != "COMPLETO" or current.score is None:
            result = current.model_copy(deep=True)
            result.regime = None
            result.previous_regime = state.get("confirmed_regime")
            result.transition_status = "NO_EVALUABLE"
            result.changes = ["Datos insuficientes: candidato reiniciado sin contar otra barra."]
            state.update(
                candidate=None,
                count=0,
                as_of=cutoff.isoformat(),
                result=result.model_dump(mode="json"),
            )
            return result, state
        confirmed = state.get("confirmed_regime")
        target = _target(current.score, confirmed, rules)
        result = current.model_copy(deep=True)
        frozen = state.get("result", {})
        result.previous_regime = frozen.get("previous_regime", confirmed)
        result.regime = confirmed
        aligned = _aligned(current, target, rules["aligned_categories"])
        if target != state.get("candidate") or not aligned:
            state.update(candidate=None, count=0)
        result.transition_status = "ESTABLE" if target == confirmed else "EN_TRANSICION"
        result.changes = frozen.get(
            "changes", ["Recalculo sin nueva barra; no avanza persistencia."]
        )
        if frozen.get("transition_status") == "NO_EVALUABLE" or not state.get("count"):
            if target != confirmed:
                result.changes = ["Recalculo elegible; candidato espera un nuevo cierre."]
        state["result"] = result.model_dump(mode="json")
        return result, state
    result = current.model_copy(deep=True)
    confirmed = state.get("confirmed_regime")
    result.previous_regime = confirmed
    state.update(last_bar_key=bar_key, as_of=cutoff.isoformat())
    if current.data_status != "COMPLETO" or current.score is None:
        state.update(candidate=None, count=0)
        result.regime = None
        result.transition_status = "NO_EVALUABLE"
        result.changes = [
            "Datos insuficientes: candidato reiniciado, sin borrar estado confirmado."
        ]
    else:
        target = _target(current.score, confirmed, rules)
        consecutive = True
        if old_day and current.horizon == "MEDIUM":
            consecutive = (day - old_day).days == 7
        elif old_day and current.horizon == "LONG":
            consecutive = (day.year - old_day.year) * 12 + day.month - old_day.month == 1
        elif old_day and state.get("expected_previous_bar"):
            consecutive = state["expected_previous_bar"] == old_day.isoformat()
        if not consecutive:
            state.update(candidate=None, count=0)
        if target == confirmed:
            state.update(candidate=None, count=0)
            result.regime = confirmed
            result.transition_status = "ESTABLE"
            result.changes = ["Estado confirmado conservado por histeresis."]
        else:
            aligned = _aligned(current, target, rules["aligned_categories"])
            count = state.get("count", 0) + 1 if state.get("candidate") == target else 1
            state.update(candidate=target if aligned else None, count=count if aligned else 0)
            if aligned and count >= rules["persistence"][current.horizon]:
                state.update(confirmed_regime=target, candidate=None, count=0)
                result.regime = target
                result.transition_status = "ESTABLE"
                result.changes = [f"Cambio confirmado {confirmed or 'sin estado'} -> {target}."]
            else:
                result.regime = confirmed
                result.transition_status = "EN_TRANSICION"
                result.changes = [
                    f"Candidato {target}: {state['count']}/"
                    f"{rules['persistence'][current.horizon]} cierres; alineacion={aligned}."
                ]
    state["result"] = result.model_dump(mode="json")
    return result, state
