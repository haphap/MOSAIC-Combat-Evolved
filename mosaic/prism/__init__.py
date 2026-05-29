"""MOSAIC PRISM package (Plan ss9 / Phase 5).

7-cohort training orchestration: evolution trunk git model, per-cohort
sequential layer training, and comparison analytics.
"""

from mosaic.prism.cohorts import (
    COHORT_CONFIGS,
    get_cohort,
    get_cohort_prompt_dir,
    list_cohorts,
)
from mosaic.prism.trainer import (
    compare_cohorts,
    ensure_cohort_branch,
    train_cohort,
)

__all__ = [
    "COHORT_CONFIGS",
    "compare_cohorts",
    "ensure_cohort_branch",
    "get_cohort",
    "get_cohort_prompt_dir",
    "list_cohorts",
    "train_cohort",
]
