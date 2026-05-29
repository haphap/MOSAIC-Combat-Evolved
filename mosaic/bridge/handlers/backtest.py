"""``backtest.*`` JSON-RPC handlers.

The TypeScript caller owns the agent graph (LangGraph.js) and is responsible
for producing the ``analyze_candidate_pool``-shaped payload for every
rebalance date. This bridge wraps the existing Backtrader engine using a thin
shim that returns those precomputed payloads.

This means the bridge does not need to call back into TS during a backtest:
TS pre-computes all signals up front, then submits the entire bundle and
receives the ``BacktraderBacktestResult`` back as JSON.

Phase 0 Day 1 status: stubs registered; calls fail with ``BACKTEST_ERROR``
until ``mosaic.backtest.backtrader_engine`` is ported in Phase 8.
"""

from __future__ import annotations

import math
from typing import Any

from ..protocol import BACKTEST_ERROR, INVALID_PARAMS, RpcError
from ..registry import method


# ----------------------------------------------------------- signal shim


class _PrecomputedSignalGraph:
    """Duck-typed stand-in for a LangGraph consumed by Backtrader.

    Provides exactly what ``run_candidate_pool_backtest`` reads:
      * ``analyze_candidate_pool(tickers, decision_date, force_refresh=False)``
      * ``_resolve_benchmark_ticker(ticker)`` (fallback only)
    """

    def __init__(
        self,
        signals_by_date: dict[str, list[dict[str, Any]]],
        default_benchmark_ticker: str | None,
    ) -> None:
        self._signals_by_date = signals_by_date
        self._default_benchmark_ticker = default_benchmark_ticker

    def analyze_candidate_pool(
        self,
        tickers: list[str],
        decision_date: str,
        *,
        force_refresh: bool = False,  # noqa: ARG002 (signature contract)
    ) -> list[dict[str, Any]]:
        bucket = self._signals_by_date.get(str(decision_date))
        if bucket is None:
            raise RpcError(
                BACKTEST_ERROR,
                f"No precomputed signals for decision_date {decision_date!r}. "
                "TS must produce signals for every rebalance date before calling backtest.run_candidate_pool.",
            )
        wanted = set(tickers)
        result = [item for item in bucket if item.get("ticker") in wanted]
        if len(result) != len(wanted):
            missing = wanted - {item.get("ticker") for item in bucket}
            raise RpcError(
                BACKTEST_ERROR,
                f"Missing precomputed signals on {decision_date}: {sorted(missing)}",
            )
        return result

    def _resolve_benchmark_ticker(self, ticker: str) -> str:
        # Only consulted when caller passes benchmark_tickers=None and len(tickers)==1.
        # TS should normally pass benchmark_tickers explicitly; this is a fallback.
        if self._default_benchmark_ticker:
            return self._default_benchmark_ticker
        if "." in ticker:
            suffix = ticker.rsplit(".", 1)[-1].upper()
            if suffix in {"SH", "SZ", "BJ", "SS", "SSE", "SZSE", "BSE"}:
                return "510300.SH"
            if suffix in {"HK", "HKG", "SEHK"}:
                return "2800.HK"
        return "SPY"


# ------------------------------------------------------- JSON sanitizer


def _jsonable(value: Any) -> Any:
    """Recursively replace NaN / +-Infinity with None so the response is strict JSON."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


# ----------------------------------------------------------- validation


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return value


def _opt_int(params: dict[str, Any], key: str, default: int) -> int:
    value = params.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a positive integer")
    return value


def _opt_float(params: dict[str, Any], key: str, default: float) -> float:
    value = params.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be numeric")
    return float(value)


def _str_list(params: dict[str, Any], key: str, *, required: bool) -> list[str]:
    value = params.get(key)
    if value is None:
        if required:
            raise RpcError(INVALID_PARAMS, f"'{key}' is required")
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be an array of strings")
    return [v for v in value if v.strip()]


# --------------------------------------------------------- main handler


@method("backtest.run_candidate_pool")
def backtest_run_candidate_pool(params: dict[str, Any]) -> dict[str, Any]:
    """Run a Backtrader candidate-pool backtest with TS-precomputed signals.

    Required params:
      * ``tickers``: list[str]
      * ``start_date``, ``end_date``: ISO yyyy-mm-dd
      * ``signals``: object keyed by decision_date → list of analyze_candidate_pool payloads

    Optional params (with defaults matching ``run_candidate_pool_backtest``):
      ``rebalance_interval_days`` (21), ``top_k`` (3),
      ``execution_timing`` ("same_close"), ``initial_cash`` (1_000_000),
      ``commission`` (0), ``slippage_perc`` (0), ``cash_buffer_pct`` (0),
      ``benchmark_tickers`` (list[str] | None), ``force_refresh`` (false),
      ``default_benchmark_ticker`` (str | None — fallback for shim).
    """
    tickers = _str_list(params, "tickers", required=True)
    if not tickers:
        raise RpcError(INVALID_PARAMS, "'tickers' must contain at least one ticker")
    start_date = _require_str(params, "start_date")
    end_date = _require_str(params, "end_date")

    signals = params.get("signals")
    if not isinstance(signals, dict):
        raise RpcError(INVALID_PARAMS, "'signals' must be an object keyed by decision_date")
    for decision_date, bucket in signals.items():
        if not isinstance(decision_date, str):
            raise RpcError(INVALID_PARAMS, "'signals' keys must be date strings")
        if not isinstance(bucket, list):
            raise RpcError(
                INVALID_PARAMS,
                f"'signals[{decision_date}]' must be an array of payloads",
            )

    benchmark_tickers_raw = params.get("benchmark_tickers")
    benchmark_tickers: list[str] | None
    if benchmark_tickers_raw is None:
        benchmark_tickers = None
    else:
        benchmark_tickers = _str_list(params, "benchmark_tickers", required=False)

    default_benchmark = params.get("default_benchmark_ticker")
    if default_benchmark is not None and not isinstance(default_benchmark, str):
        raise RpcError(INVALID_PARAMS, "'default_benchmark_ticker' must be a string")

    force_refresh = bool(params.get("force_refresh", False))

    shim = _PrecomputedSignalGraph(signals, default_benchmark)

    # Lazy import — backtrader / pandas are heavy.
    try:
        from mosaic.backtest.backtrader_engine import run_candidate_pool_backtest
    except ImportError as exc:
        raise RpcError(
            BACKTEST_ERROR,
            "mosaic.backtest.backtrader_engine not yet available (Phase 8).",
        ) from exc

    try:
        result = run_candidate_pool_backtest(
            shim,
            tickers,
            start_date,
            end_date,
            rebalance_interval_days=_opt_int(params, "rebalance_interval_days", 21),
            top_k=_opt_int(params, "top_k", 3),
            execution_timing=str(params.get("execution_timing", "same_close")),
            initial_cash=_opt_float(params, "initial_cash", 1_000_000.0),
            commission=_opt_float(params, "commission", 0.0),
            slippage_perc=_opt_float(params, "slippage_perc", 0.0),
            cash_buffer_pct=_opt_float(params, "cash_buffer_pct", 0.0),
            benchmark_tickers=benchmark_tickers,
            force_refresh=force_refresh,
        )
    except RpcError:
        raise
    except Exception as exc:
        raise RpcError(BACKTEST_ERROR, f"{type(exc).__name__}: {exc}") from exc

    return _jsonable(result.to_dict())


# --------------------------------------------------------- Phase 3.5C: two-stage backtest cache


def _store():
    """Lazy-import scorecard store to keep this module's import graph thin."""
    from mosaic.scorecard import ScorecardStore

    return ScorecardStore()


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
