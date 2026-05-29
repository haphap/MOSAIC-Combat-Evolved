"""PRISM cohort training orchestration (Plan ss9 / Phase 5).

Provides the infrastructure for sequential layer training within cohorts.
Within each layer, up to max_agents_concurrent agents can be trained
concurrently (Phase 5 constraint from plan section 1).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from mosaic.prism.cohorts import COHORT_CONFIGS, get_cohort


def train_cohort(
    store,
    git_ops,
    cohort_name: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    dry_run: bool = False,
    max_agents_concurrent: int = 5,
) -> dict[str, Any]:
    """Orchestrate training for one cohort.

    Sequential layer training. Within each layer, up to max_agents_concurrent
    agents can be trained concurrently (Phase 5 constraint from plan section 1).

    For MVP this is a stub that:
    1. Validates cohort exists
    2. Ensures cohort branch exists (creates if needed)
    3. Creates a cohort_run entry
    4. Returns a status dict indicating training was initiated

    Full training integration (running daily-cycles via TS) would require
    the TS orchestrator to call back -- for now this sets up the infrastructure.
    """
    cohort_info = get_cohort(cohort_name)
    start = start_date or cohort_info["start"]
    end = end_date or cohort_info["end"]

    if dry_run:
        return {
            "started": False,
            "cohort": cohort_name,
            "message": f"dry-run: would train {cohort_name} [{start} .. {end}]",
        }

    # Ensure the evolution trunk branch exists.
    ensure_cohort_branch(git_ops, cohort_name)

    # Create a cohort_run entry in the store.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = store.create_cohort_run(cohort_name, today)

    return {
        "started": True,
        "cohort": cohort_name,
        "message": f"training initiated for {cohort_name} [{start} .. {end}]",
        "run_id": run_id,
    }


def ensure_cohort_branch(git_ops, cohort_name: str) -> None:
    """Create the cohort/<name>/main evolution trunk if it doesn't exist.

    Per plan section 8 git model for Phase 5.
    """
    branch_name = f"cohort/{cohort_name}/main"
    if not git_ops.branch_exists(branch_name):
        git_ops.create_branch(branch_name, "main")


def compare_cohorts(
    store,
    metric: str = "sharpe",
    since_date: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Query cohort_runs + prompt_versions to produce comparison table.

    Returns list of {cohort, n_runs, n_mutations, n_kept, n_reverted, latest_date}.
    """
    results: list[dict[str, Any]] = []

    for cohort_name in COHORT_CONFIGS:
        runs = store.get_cohort_runs(cohort_name, since_date=since_date)
        n_runs = len(runs)
        latest_date = runs[0]["date"] if runs else None

        # Count mutations from prompt_versions table.
        versions = store.list_prompt_versions(cohort=cohort_name)
        n_mutations = len(versions)
        n_kept = sum(1 for v in versions if v.get("status") == "keep")
        n_reverted = sum(1 for v in versions if v.get("status") == "revert")

        results.append({
            "cohort": cohort_name,
            "n_runs": n_runs,
            "n_mutations": n_mutations,
            "n_kept": n_kept,
            "n_reverted": n_reverted,
            "latest_date": latest_date,
        })

    return results
