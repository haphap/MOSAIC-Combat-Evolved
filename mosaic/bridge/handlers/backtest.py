"""``backtest.*`` JSON-RPC handlers.

Backtest = qlib two-stage vectorized engine (Plan §11.4): TS fills the
``backtest_actions`` cache (create_run → append_actions → complete_run), then
``run_historical`` replays it through qlib. (Phase 8 dropped the backtrader
candidate-pool path; backtest is qlib-only.)
"""

from __future__ import annotations

from typing import Any

from ..protocol import BACKTEST_ERROR, INVALID_PARAMS, RpcError
from ..registry import method


# ----------------------------------------------------------- validation


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return value


def _opt_float(params: dict[str, Any], key: str, default: float) -> float:
    value = params.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be numeric")
    return float(value)


# --------------------------------------------------------- Phase 3.5C: two-stage backtest cache


def _store():
    """Lazy-import scorecard store to keep this module's import graph thin.

    §14 R-T4: use the cached singleton.
    """
    from mosaic.scorecard import get_store

    return get_store()


@method("backtest.create_run")
def backtest_create_run(params: dict[str, Any]) -> dict[str, Any]:
    """Open a new backtest run row (Plan §11.4 sub-step 3.5C).

    Params:
        cohort:              str
        start_date:          str (YYYY-MM-DD)
        end_date:            str (YYYY-MM-DD)
        prompt_commit_hash:  str — opaque tag tying this run to a prompt
                                   version (Phase 4 git mutation hash;
                                   for now any deterministic id works).

    Returns:
        {"run_id": <int>}

    Idempotent: same (cohort, start_date, end_date, prompt_commit_hash) →
    same run_id (UPSERT).
    """
    cohort = _require_str(params, "cohort")
    start_date = _require_str(params, "start_date")
    end_date = _require_str(params, "end_date")
    prompt_commit_hash = _require_str(params, "prompt_commit_hash")
    try:
        run_id = _store().create_backtest_run(
            cohort=cohort,
            start_date=start_date,
            end_date=end_date,
            prompt_commit_hash=prompt_commit_hash,
        )
    except Exception as exc:
        raise RpcError(BACKTEST_ERROR, f"{type(exc).__name__}: {exc}") from exc
    return {"run_id": run_id}


@method("backtest.append_actions")
def backtest_append_actions(params: dict[str, Any]) -> dict[str, Any]:
    """Push one trade-day's portfolio_actions into a backtest run.

    Params:
        run_id:     int
        trade_date: str (YYYY-MM-DD)
        actions:    list of {ticker, action, target_weight, [holding_period],
                             [dissent_notes]} — same shape as
                    ``state.portfolio_actions``.

    Returns:
        {"appended": <int>} — rows actually written (after schema filtering).

    Idempotent: re-appending the same (run_id, trade_date, ticker) updates
    action / target_weight / holding_period / dissent_notes via ON CONFLICT
    DO UPDATE.
    """
    run_id = params.get("run_id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise RpcError(INVALID_PARAMS, "'run_id' must be a positive integer")
    trade_date = _require_str(params, "trade_date")
    actions = params.get("actions")
    if not isinstance(actions, list):
        raise RpcError(INVALID_PARAMS, "'actions' must be an array")
    try:
        n = _store().append_backtest_actions(
            run_id=run_id, trade_date=trade_date, actions=actions
        )
    except Exception as exc:
        raise RpcError(BACKTEST_ERROR, f"{type(exc).__name__}: {exc}") from exc
    return {"appended": n}


@method("backtest.complete_run")
def backtest_complete_run(params: dict[str, Any]) -> dict[str, Any]:
    """Mark a backtest run as fully populated (stage-1 done).

    After this is called, Phase 3.5D's qlib runner can replay actions
    from the table without worrying about partial coverage.
    """
    run_id = params.get("run_id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise RpcError(INVALID_PARAMS, "'run_id' must be a positive integer")
    try:
        _store().complete_backtest_run(run_id)
    except Exception as exc:
        raise RpcError(BACKTEST_ERROR, f"{type(exc).__name__}: {exc}") from exc
    return {"ok": True}


@method("backtest.get_run")
def backtest_get_run(params: dict[str, Any]) -> dict[str, Any]:
    """Fetch a backtest run row + summary stats."""
    run_id = params.get("run_id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise RpcError(INVALID_PARAMS, "'run_id' must be a positive integer")
    store = _store()
    try:
        run = store.get_backtest_run(run_id)
    except Exception as exc:
        raise RpcError(BACKTEST_ERROR, f"{type(exc).__name__}: {exc}") from exc
    if run is None:
        raise RpcError(BACKTEST_ERROR, f"backtest run {run_id} not found")
    # Cheap aggregate: action count
    actions = store.get_backtest_actions(run_id)
    run["action_count"] = len(actions)
    distinct_dates = sorted({a["trade_date"] for a in actions})
    run["distinct_trade_days"] = len(distinct_dates)
    run["first_trade_date"] = distinct_dates[0] if distinct_dates else None
    run["last_trade_date"] = distinct_dates[-1] if distinct_dates else None
    return run


@method("backtest.list_runs")
def backtest_list_runs(params: dict[str, Any]) -> dict[str, Any]:
    """List backtest runs, optionally filtered by cohort + since timestamp."""
    cohort = params.get("cohort")
    if cohort is not None and not isinstance(cohort, str):
        raise RpcError(INVALID_PARAMS, "'cohort' must be a string when provided")
    since = params.get("since")
    if since is not None and not isinstance(since, str):
        raise RpcError(INVALID_PARAMS, "'since' must be a string when provided")
    try:
        runs = _store().list_backtest_runs(cohort=cohort, since=since)
    except Exception as exc:
        raise RpcError(BACKTEST_ERROR, f"{type(exc).__name__}: {exc}") from exc
    return {"runs": runs}


# --------------------------------------------------------- Phase 3.5E: stage-2 qlib trigger


@method("backtest.run_historical")
def backtest_run_historical(params: dict[str, Any]) -> dict[str, Any]:
    """Stage-2 of the two-stage backtest: replay cached actions through qlib.

    Params:
        run_id:              int — must reference an existing row in
                                   ``backtest_runs`` with at least one
                                   appended action (stage-1 must have run).
        initial_cash:        float (optional, default 1_000_000.0)
        benchmark:           str (optional, default "SH000300")
        open_cost:           float (optional, default 0.0003)
        close_cost:          float (optional, default 0.0013)
        deal_price:          str (optional, default "close")

    Returns:
        BacktestMetrics dict — see ``mosaic.backtest.qlib_runner.BacktestMetrics``.

    Raises BACKTEST_ERROR with actionable message when:
      - run_id not found
      - qlib data dir missing (point to ingest setup)
      - run has no cached actions (run --fill first)
    """
    run_id = params.get("run_id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise RpcError(INVALID_PARAMS, "'run_id' must be a positive integer")

    initial_cash = _opt_float(params, "initial_cash", 1_000_000.0)
    benchmark = params.get("benchmark", "SH000300")
    if not isinstance(benchmark, str) or not benchmark.strip():
        raise RpcError(INVALID_PARAMS, "'benchmark' must be a non-empty string")
    open_cost = _opt_float(params, "open_cost", 0.0003)
    close_cost = _opt_float(params, "close_cost", 0.0013)
    deal_price = params.get("deal_price", "close")
    if not isinstance(deal_price, str):
        raise RpcError(INVALID_PARAMS, "'deal_price' must be a string")

    try:
        from mosaic.backtest import QlibInitError, run_backtest
    except ImportError as exc:
        raise RpcError(
            BACKTEST_ERROR,
            f"backtest package import failed: {type(exc).__name__}: {exc}. "
            "Did you install pyqlib? See plan §11.4 sub-step 3.5A.",
        ) from exc

    try:
        metrics = run_backtest(
            run_id=run_id,
            store=_store(),
            initial_cash=initial_cash,
            benchmark=benchmark,
            open_cost=open_cost,
            close_cost=close_cost,
            deal_price=deal_price,
        )
    except QlibInitError as exc:
        raise RpcError(BACKTEST_ERROR, f"qlib init failed: {exc}") from exc
    except ValueError as exc:
        # run_id not found / no cached actions — surface as BACKTEST_ERROR
        raise RpcError(BACKTEST_ERROR, str(exc)) from exc
    except Exception as exc:
        raise RpcError(BACKTEST_ERROR, f"{type(exc).__name__}: {exc}") from exc

    return metrics.to_dict()
