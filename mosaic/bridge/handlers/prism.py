"""``prism.*`` JSON-RPC handlers (Plan ss9 / Phase 5).

Exposes PRISM 7-cohort training orchestration to the TS front-end:

    * prism.list_cohorts   -- list all 7 cohorts with status info
    * prism.train_cohort   -- initiate training for a cohort
    * prism.cohort_status  -- get status for a specific cohort
    * prism.compare_cohorts-- compare cohorts by metric
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..protocol import INVALID_PARAMS, RpcError
from ..registry import method


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store():
    """Lazy-import scorecard store singleton."""
    from mosaic.scorecard import get_store

    return get_store()


def _repo_root() -> Path:
    """Repo root; ``MOSAIC_REPO_ROOT`` override lets tests point at a tmp repo."""
    env = os.getenv("MOSAIC_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[3]


def _git():
    from mosaic.autoresearch.git_ops import GitOps

    return GitOps(_repo_root())


def _require_str(params: dict, key: str) -> str:
    val = params.get(key)
    if not isinstance(val, str) or not val.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return val.strip()


# ---------------------------------------------------------------------------
# prism.list_cohorts
# ---------------------------------------------------------------------------


@method("prism.list_cohorts")
def prism_list_cohorts(params: dict[str, Any]) -> dict[str, Any]:
    """List all 7 cohorts with status info."""
    from mosaic.prism.cohorts import list_cohorts

    store = _store()
    git = _git()

    cohorts = []
    for c in list_cohorts():
        name = c["name"]
        branch_name = f"cohort/{name}/main"
        has_branch = git.branch_exists(branch_name)
        summary = store.get_cohort_status_summary(name)

        cohorts.append({
            "name": name,
            "start": c["start"],
            "end": c["end"],
            "description": c["description"],
            "has_branch": has_branch,
            "n_runs": summary["n_runs"],
            "last_run_date": summary["last_date"],
        })

    return {"cohorts": cohorts}


# ---------------------------------------------------------------------------
# prism.train_cohort
# ---------------------------------------------------------------------------


@method("prism.train_cohort")
def prism_train_cohort(params: dict[str, Any]) -> dict[str, Any]:
    """Initiate training for a cohort.

    Params:
        cohort_name: str
        start_date:  str | None
        end_date:    str | None
        dry_run:     bool | None
    """
    from mosaic.prism.trainer import train_cohort

    cohort_name = _require_str(params, "cohort_name")
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    dry_run = bool(params.get("dry_run", False))

    if start_date is not None and not isinstance(start_date, str):
        raise RpcError(INVALID_PARAMS, "'start_date' must be a string")
    if end_date is not None and not isinstance(end_date, str):
        raise RpcError(INVALID_PARAMS, "'end_date' must be a string")

    store = _store()
    git = _git()

    result = train_cohort(
        store=store,
        git_ops=git,
        cohort_name=cohort_name,
        start_date=start_date,
        end_date=end_date,
        dry_run=dry_run,
    )

    return result


# ---------------------------------------------------------------------------
# prism.cohort_status
# ---------------------------------------------------------------------------


@method("prism.cohort_status")
def prism_cohort_status(params: dict[str, Any]) -> dict[str, Any]:
    """Get status for a specific cohort.

    Params:
        cohort_name: str
    """
    from mosaic.prism.cohorts import get_cohort

    cohort_name = _require_str(params, "cohort_name")

    # Validate cohort exists.
    get_cohort(cohort_name)

    store = _store()
    return store.get_cohort_status_summary(cohort_name)


# ---------------------------------------------------------------------------
# prism.compare_cohorts
# ---------------------------------------------------------------------------


@method("prism.compare_cohorts")
def prism_compare_cohorts(params: dict[str, Any]) -> dict[str, Any]:
    """Compare cohorts by metric.

    Params:
        metric: str | None  (default 'sharpe')
        since:  str | None  (YYYY-MM-DD filter)
    """
    from mosaic.prism.trainer import compare_cohorts

    metric = params.get("metric", "sharpe")
    since = params.get("since")

    if not isinstance(metric, str):
        raise RpcError(INVALID_PARAMS, "'metric' must be a string")
    if since is not None and not isinstance(since, str):
        raise RpcError(INVALID_PARAMS, "'since' must be a string")

    store = _store()
    comparisons = compare_cohorts(store, metric=metric, since_date=since)

    return {"comparisons": comparisons}
