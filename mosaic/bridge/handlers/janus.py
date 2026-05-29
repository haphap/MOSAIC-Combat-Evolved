"""``janus.*`` JSON-RPC handlers (Plan §11.7 / Phase 6).

Exposes the JANUS meta-weighting layer to the TS front-end:

    * janus.run_daily   -- full cycle: weights + regime + blended recs, persisted
    * janus.get_weights -- cohort weights + 30d accuracy only (no blend)
    * janus.regime      -- regime signal only
    * janus.get_history -- recent janus_runs rows (TUI weight-drift chart)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..protocol import INVALID_PARAMS, RpcError
from ..registry import method

_DEFAULT_WINDOW = 30


def _store():
    from mosaic.scorecard import get_store

    return get_store()


def _cohorts_and_configs():
    from mosaic.prism.cohorts import COHORT_CONFIGS

    return list(COHORT_CONFIGS.keys()), COHORT_CONFIGS


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _opt_date(params: dict) -> str:
    d = params.get("date")
    if d is not None and not isinstance(d, str):
        raise RpcError(INVALID_PARAMS, "'date' must be a string (YYYY-MM-DD)")
    return d or _today()


def _opt_window(params: dict) -> int:
    w = params.get("window_days", _DEFAULT_WINDOW)
    if not isinstance(w, int) or isinstance(w, bool) or w < 1:
        raise RpcError(INVALID_PARAMS, "'window_days' must be a positive integer")
    return w


@method("janus.run_daily")
def janus_run_daily(params: dict[str, Any]) -> dict[str, Any]:
    """Full daily JANUS cycle (weights + regime + blend), persisted."""
    from mosaic.janus import run_daily

    date = _opt_date(params)
    window = _opt_window(params)
    cohorts, configs = _cohorts_and_configs()
    now_iso = f"{date}T00:00:00+00:00"
    return run_daily(_store(), cohorts, date, now_iso=now_iso,
                     window_days=window, cohort_configs=configs)


@method("janus.get_weights")
def janus_get_weights(params: dict[str, Any]) -> dict[str, Any]:
    """Cohort weights + accuracy only (no recommendation blend)."""
    from mosaic.janus import compute_cohort_weights

    date = _opt_date(params)
    window = _opt_window(params)
    cohorts, _ = _cohorts_and_configs()
    weights, accuracy = compute_cohort_weights(
        _store(), cohorts, f"{date}T00:00:00+00:00", window
    )
    return {
        "date": date,
        "cohort_weights": {k: round(v, 4) for k, v in weights.items()},
        "cohort_accuracy": {
            k: {"hit_rate": round(v["hit_rate"], 4), "sharpe": round(v["sharpe"], 4), "n": v["n"]}
            for k, v in accuracy.items()
        },
    }


@method("janus.regime")
def janus_regime(params: dict[str, Any]) -> dict[str, Any]:
    """Regime signal only (dominant cohort + concentration)."""
    from mosaic.janus import compute_cohort_weights, regime_signal

    date = _opt_date(params)
    window = _opt_window(params)
    cohorts, configs = _cohorts_and_configs()
    weights, _ = compute_cohort_weights(_store(), cohorts, f"{date}T00:00:00+00:00", window)
    return {"date": date, **regime_signal(weights, configs)}


@method("janus.get_history")
def janus_get_history(params: dict[str, Any]) -> dict[str, Any]:
    """Recent janus_runs rows (newest first)."""
    days = params.get("days", _DEFAULT_WINDOW)
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise RpcError(INVALID_PARAMS, "'days' must be a positive integer")
    return {"history": _store().get_janus_history(days)}
