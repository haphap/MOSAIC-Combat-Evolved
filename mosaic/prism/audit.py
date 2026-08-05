"""Read-only summaries for historical PRISM cohort runs."""

from __future__ import annotations

from typing import Any

from mosaic.prism.cohorts import COHORT_CONFIGS


def compare_cohorts(
    store,
    metric: str = "sharpe",
    since_date: str | None = None,
) -> list[dict[str, Any]]:
    """Summarize immutable cohort-run and legacy prompt-version history."""
    del metric  # The historical store currently exposes one comparable score.
    results: list[dict[str, Any]] = []
    for cohort_name in COHORT_CONFIGS:
        runs = store.get_cohort_runs(cohort_name, since_date=since_date)
        versions = store.list_prompt_versions(cohort=cohort_name)
        results.append(
            {
                "cohort": cohort_name,
                "n_runs": len(runs),
                "n_mutations": len(versions),
                "n_kept": sum(1 for row in versions if row.get("status") == "keep"),
                "n_reverted": sum(
                    1 for row in versions if row.get("status") == "revert"
                ),
                "latest_date": runs[0]["date"] if runs else None,
            }
        )
    return results
