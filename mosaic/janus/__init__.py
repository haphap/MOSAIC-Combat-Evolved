"""MOSAIC JANUS meta-weighting layer (Plan §11.7, Phase 6).

Port of ATLAS ``janus.py`` to MOSAIC's 7 PRISM regime cohorts + SQLite store.
See :mod:`mosaic.janus.meta` for the meta-weighting / blend / regime logic.
"""

from mosaic.janus.meta import (
    blend_recommendations,
    cohort_accuracy,
    compute_cohort_weights,
    regime_signal,
    run_daily,
    softmax_with_constraints,
)

__all__ = [
    "blend_recommendations",
    "cohort_accuracy",
    "compute_cohort_weights",
    "regime_signal",
    "run_daily",
    "softmax_with_constraints",
]
