"""Phase 4C: backtest evaluation helpers (Plan ss11.5 4C).

Two functions:

  * :func:`ensure_baseline_run` -- checks whether a completed backtest_run
    already covers the given (cohort, start, end, base_commit). If not, the
    caller must trigger a ``backtest-fill`` before evaluation can proceed.

  * :func:`compute_delta` -- given a prompt_version id whose both runs (base
    and mod) are complete, reads their Sharpe metrics and records
    pre/post/delta on the version row.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def ensure_baseline_run(
    store,
    cohort: str,
    start_date: str,
    end_date: str,
    base_commit: str,
) -> dict[str, Any]:
    """Check if a completed backtest_run exists for the given parameters.

    Returns:
        {"run_id": int | None, "needs_fill": bool}

    A run is considered valid when it matches (cohort, start_date, end_date,
    prompt_commit_hash == base_commit) and has a non-null ``completed_at``.
    """
    runs = store.list_backtest_runs(cohort=cohort)
    for run in runs:
        if (
            run["start_date"] == start_date
            and run["end_date"] == end_date
            and run["prompt_commit_hash"] == base_commit
            and run["completed_at"] is not None
        ):
            return {"run_id": run["id"], "needs_fill": False}
    return {"run_id": None, "needs_fill": True}


def _find_run_sharpe(
    store,
    cohort: str,
    start_date: str,
    end_date: str,
    commit_hash: str,
) -> Optional[float]:
    """Locate a completed run matching the commit and return its sharpe.

    The sharpe is stored on the backtest_runs row via qlib stage-2
    (``backtest.run_historical``). If unavailable we fall back to None.
    """
    runs = store.list_backtest_runs(cohort=cohort)
    for run in runs:
        if (
            run["start_date"] == start_date
            and run["end_date"] == end_date
            and run["prompt_commit_hash"] == commit_hash
            and run["completed_at"] is not None
        ):
            # Try to get sharpe from the run's metrics. The qlib runner
            # stores results externally; for the MVP we check if the run
            # has a sharpe field attached (Phase 3.5E stores it via
            # BacktestMetrics). If not available, attempt stage-2 import.
            sharpe = run.get("sharpe")
            if sharpe is not None:
                return float(sharpe)
            # Fall back: try to compute from qlib if available.
            try:
                from mosaic.backtest import run_backtest

                metrics = run_backtest(run_id=run["id"], store=store)
                return float(metrics.sharpe)
            except Exception:
                # qlib not available or run has no actions -- return None
                return None
    return None


def compute_delta(
    store,
    version_id: int,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Evaluate a prompt_version by comparing base vs modification Sharpe.

    Reads the version row to get cohort, base_commit_hash, and
    modification_commit_hash. Looks up backtest_runs for each commit. If
    either run does not exist or is not complete, raises ValueError.

    On success: writes pre/post/delta to the version row via
    store.set_version_eval and appends a log entry. Returns
    {"pre_sharpe": float, "post_sharpe": float, "delta_sharpe": float}.
    """
    from mosaic.default_config import DEFAULT_CONFIG

    cfg = config if config is not None else DEFAULT_CONFIG
    cohorts_cfg = cfg.get("cohorts", {})

    version = store.get_prompt_version(version_id)
    if version is None:
        raise ValueError(f"prompt_version {version_id} not found")

    cohort = version["cohort"]
    base_commit = version["base_commit_hash"]
    mod_commit = version.get("modification_commit_hash")

    if not mod_commit:
        raise ValueError(
            f"prompt_version {version_id} has no modification_commit_hash "
            "(mutation not yet recorded)"
        )

    # Determine date range from cohort config.
    cohort_info = cohorts_cfg.get(cohort, {})
    start_date = cohort_info.get("start", "")
    end_date = cohort_info.get("end", "")
    if not start_date or not end_date:
        raise ValueError(
            f"cohort '{cohort}' not found in config.cohorts or missing start/end"
        )

    # Find completed base run.
    base_result = ensure_baseline_run(store, cohort, start_date, end_date, base_commit)
    if base_result["needs_fill"]:
        raise ValueError(
            f"no completed base backtest run for cohort={cohort}, "
            f"commit={base_commit[:8]}... (run backtest-fill first)"
        )

    # Find completed mod run.
    mod_result = ensure_baseline_run(store, cohort, start_date, end_date, mod_commit)
    if mod_result["needs_fill"]:
        raise ValueError(
            f"no completed mod backtest run for cohort={cohort}, "
            f"commit={mod_commit[:8]}... (run backtest-fill first)"
        )

    # Retrieve Sharpe for each run.
    pre_sharpe = _find_run_sharpe(store, cohort, start_date, end_date, base_commit)
    post_sharpe = _find_run_sharpe(store, cohort, start_date, end_date, mod_commit)

    if pre_sharpe is None:
        raise ValueError(
            f"cannot determine Sharpe for base run (cohort={cohort}, "
            f"commit={base_commit[:8]}...); qlib stage-2 may not have run"
        )
    if post_sharpe is None:
        raise ValueError(
            f"cannot determine Sharpe for mod run (cohort={cohort}, "
            f"commit={mod_commit[:8]}...); qlib stage-2 may not have run"
        )

    delta_sharpe = post_sharpe - pre_sharpe

    # Persist evaluation results.
    store.set_version_eval(version_id, pre_sharpe, post_sharpe, delta_sharpe)
    store.append_log(
        version_id,
        "evaluated",
        f"pre={pre_sharpe:.4f} post={post_sharpe:.4f} delta={delta_sharpe:.4f}",
    )

    logger.info(
        "compute_delta: version %d evaluated (delta=%.4f)",
        version_id,
        delta_sharpe,
    )

    return {
        "pre_sharpe": pre_sharpe,
        "post_sharpe": post_sharpe,
        "delta_sharpe": delta_sharpe,
    }
