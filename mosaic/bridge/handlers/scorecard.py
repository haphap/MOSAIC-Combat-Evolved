"""``scorecard.*`` JSON-RPC handlers (Plan §11.3 sub-step 3D).

Surface (Plan §11.3 design decision #10 — scorecard / darwinian namespaces):
    * scorecard.append           (state: dict) → {ingested: int}
    * scorecard.score_pending    (cohort: str, today: str) → outcome dict
    * scorecard.list_skill       (cohort: str, since?: str)
                                 → [{agent, mean_alpha_5d, sharpe_window, n_obs}]

The TypeScript front-end calls scorecard.append at end of each
`pnpm dev daily-cycle` run (the CLI passes the final state dict). Score
cron (operator-driven, daily after market close) calls scorecard.score_pending
followed by darwinian.compute. List_skill is read-only — used by the
`pnpm dev scorecard` CLI in 3E.

Note (PR #3 review hotfix #4): this handler returns ``sharpe_window``,
NOT ``sharpe_30d``. The window is determined by the ``since`` parameter
(all-time when omitted) — it does NOT match the rolling 30-day Sharpe in
``darwinian.compute``. The two are intentionally different views of the
same data; the field name reflects that.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Optional

from ..protocol import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from ..registry import method


# Annualization constant — must match scorecard.weights.ANNUALIZATION
# (sqrt(252/5) for 5d-period Sharpe → annualized).
_ANNUALIZATION = math.sqrt(252.0 / 5.0)


def _store():
    """Lazy-import so `mosaic.bridge` doesn't pull SQLite at startup.

    §14 R-T4: returns the cached singleton (one SQLite connection factory
    per db_path) instead of a fresh ScorecardStore per call.
    """
    from mosaic.scorecard import get_store

    return get_store()


def _require_str(params: dict, key: str) -> str:
    val = params.get(key)
    if not isinstance(val, str) or not val.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return val.strip()


# ---------------------------------------------------------------------------
# scorecard.append
# ---------------------------------------------------------------------------


@method("scorecard.append")
def scorecard_append(params: dict[str, Any]) -> dict[str, Any]:
    """Ingest a daily-cycle final state into the recommendations table.

    Params:
        state: dict — the final DailyCycleState as serialised by the
                      `pnpm dev daily-cycle` CLI (must include
                      active_cohort + as_of_date + layer{2,3,4}_outputs).

    Returns:
        {"ingested": <int>} — number of recommendation rows upserted
                              (0 if state has no ticker-bearing outputs).
    """
    state = params.get("state")
    if not isinstance(state, dict):
        raise RpcError(INVALID_PARAMS, "'state' must be an object")
    try:
        n = _store().append_from_state(state)
    except ValueError as exc:
        # expand_state_to_recommendations raises ValueError when as_of_date is missing
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc
    return {"ingested": n}


# ---------------------------------------------------------------------------
# scorecard.score_pending
# ---------------------------------------------------------------------------


@method("scorecard.score_pending")
def scorecard_score_pending(params: dict[str, Any]) -> dict[str, Any]:
    """Run the forward-return scorer over pending rows in the cohort.

    Params:
        cohort: str
        today:  str (YYYY-MM-DD)

    Returns:
        {"scored": <int>, "skipped_immature": <int>, "skipped_missing": <int>}
        — counts as produced by ``Scorer.score_pending``.
    """
    cohort = _require_str(params, "cohort")
    today = _require_str(params, "today")

    try:
        from mosaic.scorecard import Scorer
    except ImportError as exc:
        raise RpcError(INTERNAL_ERROR, f"scorecard package not importable: {exc}") from exc

    try:
        scorer = Scorer(_store())
        return scorer.score_pending(cohort=cohort, today=today)
    except RpcError:
        raise
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# scorecard.list_skill
# ---------------------------------------------------------------------------


@method("scorecard.list_skill")
def scorecard_list_skill(params: dict[str, Any]) -> dict[str, Any]:
    """Aggregate per-agent skill metrics from scored recommendations.

    Params:
        cohort: str
        since:  str (YYYY-MM-DD, optional) — restrict to rows with date >= since

    Returns:
        {"rows": [
            {"agent": ..., "mean_alpha_5d": float, "sharpe_window": float | None,
             "n_obs": int},
            ...
        ]}

    Note (PR #3 review hotfix #4): ``sharpe_window`` is computed from ALL
    scored rows since ``since`` (or all-time when since omitted) — the
    window is whatever the caller asked for, not necessarily 30 days.
    Use ``darwinian.get_weights`` for the canonical rolling-30-calendar-day
    Sharpe.
    """
    cohort = _require_str(params, "cohort")
    since: Optional[str] = params.get("since") or None
    if since is not None and not isinstance(since, str):
        raise RpcError(INVALID_PARAMS, "'since' must be a string when provided")

    try:
        rows = _store().list_scored(cohort=cohort, since_date=since)
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc

    by_agent: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        alpha = row.get("alpha_5d")
        if alpha is None:
            continue
        agent = row.get("agent")
        if not agent:
            continue
        by_agent[agent].append(float(alpha))

    out: list[dict[str, Any]] = []
    for agent, alphas in sorted(by_agent.items()):
        n = len(alphas)
        mean = sum(alphas) / n if n > 0 else 0.0
        sharpe: Optional[float] = None
        if n >= 5:
            var = sum((a - mean) ** 2 for a in alphas) / max(n - 1, 1)
            std = math.sqrt(var)
            sharpe = 0.0 if std == 0 else (mean / std) * _ANNUALIZATION
        out.append(
            {
                "agent": agent,
                "mean_alpha_5d": mean,
                "sharpe_window": sharpe,
                "n_obs": n,
            }
        )

    return {"rows": out}
