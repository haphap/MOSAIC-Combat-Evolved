"""``mirofish.*`` JSON-RPC handlers (Plan §11.8 / Phase 7).

Exposes the synthetic-futures forward-training engine to the TS orchestrator:

    * mirofish.generate_scenarios   -- numpy Monte-Carlo scenario set
    * mirofish.score_recommendation -- score an agent rec vs a scenario path
    * mirofish.record_run           -- persist a forward-training run (isolated)
    * mirofish.get_history          -- recent mirofish_runs rows

Python owns scenario generation + scoring + persistence; TS owns the LLM
agent-recommendation step. Scenarios cross the bridge as JSON dicts (no numpy).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..protocol import INVALID_PARAMS, RpcError
from ..registry import method


def _store():
    from mosaic.scorecard import get_store

    return get_store()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _opt_int(params: dict, key: str, default: int, *, min_value: int = 1) -> int:
    v = params.get(key, default)
    if not isinstance(v, int) or isinstance(v, bool) or v < min_value:
        raise RpcError(INVALID_PARAMS, f"'{key}' must be an integer >= {min_value}")
    return v


def _opt_seed(params: dict) -> Any:
    seed = params.get("seed")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        raise RpcError(INVALID_PARAMS, "'seed' must be an integer when provided")
    return seed


@method("mirofish.generate_scenarios")
def mirofish_generate_scenarios(params: dict[str, Any]) -> dict[str, Any]:
    """Generate the Monte-Carlo scenario set (base/bull/bear/tail_up/tail_down)."""
    num_days = _opt_int(params, "num_days", 30)
    seed = _opt_seed(params)
    scenarios = params.get("scenarios")
    if scenarios is not None and (
        not isinstance(scenarios, list) or not all(isinstance(s, str) for s in scenarios)
    ):
        raise RpcError(INVALID_PARAMS, "'scenarios' must be a list of strings")
    start_prices = params.get("start_prices")
    if start_prices is not None and not isinstance(start_prices, dict):
        raise RpcError(INVALID_PARAMS, "'start_prices' must be an object")
    reflexivity = bool(params.get("reflexivity", False))

    # Lazy import after validation so deps-light callers (and bad-param tests)
    # don't pay the numpy import / hit ModuleNotFoundError before rejection.
    from mosaic.mirofish import generate_all_scenarios

    try:
        out = generate_all_scenarios(
            start_prices=start_prices, num_days=num_days, seed=seed,
            scenarios=scenarios, reflexivity=reflexivity,
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    return {"scenarios": out}


@method("mirofish.score_recommendation")
def mirofish_score_recommendation(params: dict[str, Any]) -> dict[str, Any]:
    """Score an agent recommendation against a scenario's realised paths."""
    rec = params.get("recommendation")
    scenario = params.get("scenario")
    if not isinstance(rec, dict):
        raise RpcError(INVALID_PARAMS, "'recommendation' must be an object")
    if not isinstance(scenario, dict):
        raise RpcError(INVALID_PARAMS, "'scenario' must be an object")

    from mosaic.mirofish import score_recommendation  # lazy: validate first

    return {"score": score_recommendation(rec, scenario)}


@method("mirofish.record_run")
def mirofish_record_run(params: dict[str, Any]) -> dict[str, Any]:
    """Persist a synthetic forward-training run (isolated from real P&L)."""
    import json

    agent = params.get("agent")
    scenario_type = params.get("scenario_type")
    if not isinstance(agent, str) or not agent.strip():
        raise RpcError(INVALID_PARAMS, "'agent' must be a non-empty string")
    if not isinstance(scenario_type, str) or not scenario_type.strip():
        raise RpcError(INVALID_PARAMS, "'scenario_type' must be a non-empty string")
    date = params.get("date") or _today()
    if not isinstance(date, str):
        raise RpcError(INVALID_PARAMS, "'date' must be a string")
    avg_score = params.get("avg_score")
    if avg_score is not None and (not isinstance(avg_score, (int, float)) or isinstance(avg_score, bool)):
        raise RpcError(INVALID_PARAMS, "'avg_score' must be a number")
    n_scenarios = _opt_int(params, "n_scenarios", 0, min_value=0)
    detail = params.get("detail")
    detail_json = json.dumps(detail) if detail is not None else None

    run_id = _store().record_mirofish_run(
        date=date,
        agent=agent.strip(),
        scenario_type=scenario_type.strip(),
        n_scenarios=n_scenarios,
        avg_score=float(avg_score) if avg_score is not None else None,
        detail_json=detail_json,
    )
    return {"id": run_id}


@method("mirofish.get_history")
def mirofish_get_history(params: dict[str, Any]) -> dict[str, Any]:
    """Recent mirofish_runs rows (newest first)."""
    days = _opt_int(params, "days", 30)
    return {"history": _store().get_mirofish_history(days)}
