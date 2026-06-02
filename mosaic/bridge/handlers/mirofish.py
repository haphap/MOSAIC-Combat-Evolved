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

from ..protocol import INTERNAL_ERROR, INVALID_PARAMS, RpcError
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
    """Generate the scenario set (base/bull/bear/tail_up/tail_down).

    ``engine``: 'montecarlo' (default), 'swarm' (Phase 7M.1 agent-to-agent), or
    'oasis' (7M Step 3 — a deployed 666ghj/MiroFish service via HTTP; needs
    MOSAIC_MIROFISH_URL). When omitted, falls back to ``config.mirofish.engine``
    (default montecarlo). Swarm ignores ``reflexivity`` (it is reflexive by design).
    """
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

    max_rounds = params.get("max_rounds")
    if max_rounds is not None and (
        not isinstance(max_rounds, int) or isinstance(max_rounds, bool) or max_rounds <= 0
    ):
        raise RpcError(INVALID_PARAMS, "'max_rounds' must be a positive integer")

    engine = params.get("engine")
    if engine is None:
        from mosaic.default_config import DEFAULT_CONFIG

        engine = DEFAULT_CONFIG.get("mirofish", {}).get("engine", "montecarlo")
    if engine not in ("montecarlo", "swarm", "oasis"):
        raise RpcError(INVALID_PARAMS, "'engine' must be 'montecarlo', 'swarm' or 'oasis'")

    # Lazy import after validation so deps-light callers (and bad-param tests)
    # don't pay the numpy import / hit ModuleNotFoundError before rejection.
    try:
        if engine == "oasis":
            from mosaic.mirofish.oasis import MiroFishUnavailable, OasisMiroFishEngine

            try:
                out = OasisMiroFishEngine(max_rounds=max_rounds).generate_all_scenarios(
                    start_prices=start_prices, num_days=num_days, seed=seed, scenarios=scenarios
                )
            except MiroFishUnavailable as exc:
                raise RpcError(INTERNAL_ERROR, f"oasis engine: {exc}") from exc
        elif engine == "swarm":
            from mosaic.mirofish.swarm import LocalSwarmEngine

            out = LocalSwarmEngine().generate_all_scenarios(
                start_prices=start_prices, num_days=num_days, seed=seed, scenarios=scenarios
            )
        else:
            from mosaic.mirofish import generate_all_scenarios

            out = generate_all_scenarios(
                start_prices=start_prices, num_days=num_days, seed=seed,
                scenarios=scenarios, reflexivity=reflexivity,
            )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    return {"scenarios": out, "engine": engine}


@method("mirofish.score_recommendation")
def mirofish_score_recommendation(params: dict[str, Any]) -> dict[str, Any]:
    """Score an agent recommendation against a scenario's realised paths.

    ``scorer``: 'terminal' (default) or 'path_aware' (direction-adjusted equity
    curve with a max-drawdown penalty). When omitted, falls back to
    ``config.mirofish.scorer`` (default terminal). Validated before lazy import.
    """
    rec = params.get("recommendation")
    scenario = params.get("scenario")
    if not isinstance(rec, dict):
        raise RpcError(INVALID_PARAMS, "'recommendation' must be an object")
    if not isinstance(scenario, dict):
        raise RpcError(INVALID_PARAMS, "'scenario' must be an object")

    scorer = params.get("scorer")
    if scorer is None:
        from mosaic.default_config import DEFAULT_CONFIG

        scorer = DEFAULT_CONFIG.get("mirofish", {}).get("scorer", "terminal")
    if scorer not in ("terminal", "path_aware"):
        raise RpcError(INVALID_PARAMS, "'scorer' must be 'terminal' or 'path_aware'")

    from mosaic.mirofish import score_recommendation  # lazy: validate first

    return {"score": score_recommendation(rec, scenario, path_aware=scorer == "path_aware")}


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


@method("mirofish.save_context")
def mirofish_save_context(params: dict[str, Any]) -> dict[str, Any]:
    """Derive a compact prompt-ready context from a scenario set and persist it
    as the latest MiroFish context for ``date`` (Phase 7M Step 1)."""
    scenarios = params.get("scenarios")
    if not isinstance(scenarios, list) or not all(isinstance(s, dict) for s in scenarios):
        raise RpcError(INVALID_PARAMS, "'scenarios' must be a list of scenario objects")
    if not scenarios:
        raise RpcError(INVALID_PARAMS, "'scenarios' must be non-empty")
    date = params.get("date") or _today()
    if not isinstance(date, str):
        raise RpcError(INVALID_PARAMS, "'date' must be a string")

    from mosaic.mirofish.context import derive_context  # deps-light: no numpy

    context = derive_context(scenarios)
    _store().save_mirofish_context(date=date, context=context)
    return {"date": date, "context": context}


@method("mirofish.get_context")
def mirofish_get_context(params: dict[str, Any]) -> dict[str, Any]:
    """Return the latest persisted MiroFish context (or null). Optional
    ``as_of_date`` (YYYY-MM-DD) bounds to ``date <= as_of_date`` (anti-lookahead
    for backtests)."""
    as_of_date = params.get("as_of_date")
    if as_of_date is not None and not isinstance(as_of_date, str):
        raise RpcError(INVALID_PARAMS, "'as_of_date' must be a string when provided")
    return {"context": _store().get_latest_mirofish_context(as_of_date)}
