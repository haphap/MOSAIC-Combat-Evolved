"""MOSAIC scorecard package (Plan §11.3 sub-step 3A+).

Records every daily-cycle agent recommendation, scores them against forward
returns, and computes Darwinian weights per (cohort, agent).

The Python sidecar owns the SQLite + return-fetch flow because it already
has the Tushare / akshare / FRED data plumbing. The TypeScript front-end
calls into this package via JSON-RPC handlers (Plan §11.3 sub-step 3D).
"""

from mosaic.scorecard.scorer import (
    DEFAULT_BENCHMARK,
    HORIZON_5D,
    HORIZON_21D,
    ScoreOutcome,
    Scorer,
)
from mosaic.scorecard.macro_labels import (
    BENCHMARK_FALLBACK_LABEL,
    MACRO_LABEL_INVENTORY,
    MacroLabelSpec,
    list_macro_label_inventory,
    primary_label_for_agent,
)
from mosaic.scorecard.macro_path_labels import (
    PRIMARY_LABEL_CONFIGS,
    MacroPathLabelConfig,
    MacroPathOutcome,
    compute_basket_path_label,
    compute_drawdown_aware_path_label,
    compute_relative_path_label,
)
from mosaic.scorecard.store import (
    DEFAULT_DB_PATH,
    MACRO_AGENTS,
    PendingMacroRow,
    PendingRow,
    ScorecardStore,
    expand_state_to_macro_signals,
    expand_state_to_recommendations,
)
from mosaic.scorecard.weights import (
    MIN_OBS_FOR_SHARPE,
    WEIGHT_MAX,
    WEIGHT_MIN,
    compute_weights,
)

# §14 R-T4: module-level store singleton keyed by db_path. Phase 4
# autoresearch calls SQLite at high frequency (trigger / log / version
# state machine); re-instantiating ScorecardStore per RPC (and re-running
# CREATE TABLE IF NOT EXISTS) is wasteful. All bridge handlers should call
# get_store() instead of ScorecardStore() directly.
_STORE_CACHE: dict[str, ScorecardStore] = {}


def get_store(db_path=None) -> ScorecardStore:
    """Return a cached ScorecardStore for ``db_path`` (default DB when None)."""
    key = str(db_path) if db_path is not None else str(DEFAULT_DB_PATH)
    store = _STORE_CACHE.get(key)
    if store is None:
        store = ScorecardStore(db_path=db_path)
        _STORE_CACHE[key] = store
    return store


def reset_store_cache() -> None:
    """Test helper — drop cached stores so a fresh tmp DB is picked up."""
    _STORE_CACHE.clear()


__all__ = [
    "DEFAULT_BENCHMARK",
    "DEFAULT_DB_PATH",
    "BENCHMARK_FALLBACK_LABEL",
    "HORIZON_5D",
    "HORIZON_21D",
    "MACRO_LABEL_INVENTORY",
    "MACRO_AGENTS",
    "MIN_OBS_FOR_SHARPE",
    "MacroLabelSpec",
    "MacroPathLabelConfig",
    "MacroPathOutcome",
    "PendingMacroRow",
    "PendingRow",
    "PRIMARY_LABEL_CONFIGS",
    "ScoreOutcome",
    "Scorer",
    "ScorecardStore",
    "WEIGHT_MAX",
    "WEIGHT_MIN",
    "compute_weights",
    "compute_basket_path_label",
    "compute_drawdown_aware_path_label",
    "compute_relative_path_label",
    "expand_state_to_macro_signals",
    "expand_state_to_recommendations",
    "get_store",
    "list_macro_label_inventory",
    "primary_label_for_agent",
    "reset_store_cache",
]
