"""MOSAIC scorecard package (Plan §11.3 sub-step 3A+).

Records every daily-cycle agent recommendation, scores them against forward
returns, and computes Darwinian weights per (cohort, agent).

The Python sidecar owns the SQLite + return-fetch flow because it already
has the Tushare / akshare / FRED data plumbing. The TypeScript front-end
calls into this package via JSON-RPC handlers (Plan §11.3 sub-step 3D).
"""

from mosaic.scorecard.store import (
    DEFAULT_DB_PATH,
    PendingRow,
    ScorecardStore,
    expand_state_to_recommendations,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "PendingRow",
    "ScorecardStore",
    "expand_state_to_recommendations",
]
