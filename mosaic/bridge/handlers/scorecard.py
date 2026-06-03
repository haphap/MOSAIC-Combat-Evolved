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


def _config() -> dict[str, Any]:
    try:
        from mosaic.dataflows.config import get_config

        return get_config()
    except Exception:
        from mosaic.default_config import DEFAULT_CONFIG

        return DEFAULT_CONFIG


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
        {"ingested": <int>, "macro_ingested": <int>} — recommendation rows +
        Layer 1 macro_signals rows upserted.
    """
    state = params.get("state")
    if not isinstance(state, dict):
        raise RpcError(INVALID_PARAMS, "'state' must be an object")
    try:
        store = _store()
        n = store.append_from_state(state)
        macro_n = store.append_macro_signals_from_state(state)
    except ValueError as exc:
        # expand_* raises ValueError when as_of_date is missing
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc
    return {"ingested": n, "macro_ingested": macro_n}


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
        recommendation counts (``scored`` / ``skipped_immature`` /
        ``skipped_missing``) merged with macro counts (``macro_scored`` /
        ``macro_skipped_immature`` / ``macro_skipped_missing``).
    """
    cohort = _require_str(params, "cohort")
    today = _require_str(params, "today")

    try:
        from mosaic.scorecard import Scorer
        from mosaic.scorecard.scorer import MacroScorer
    except ImportError as exc:
        raise RpcError(INTERNAL_ERROR, f"scorecard package not importable: {exc}") from exc

    try:
        store = _store()
        ar_cfg = (_config().get("autoresearch", {}) or {})
        result = dict(Scorer(store).score_pending(cohort=cohort, today=today))
        result.update(
            MacroScorer(
                store,
                neutral_band=ar_cfg.get("macro_neutral_band"),
                agent_specific_labels_enabled=ar_cfg.get(
                    "macro_agent_specific_labels_enabled"
                ),
            ).score_pending(cohort=cohort, today=today)
        )
        return result
    except RpcError:
        raise
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# scorecard.list_macro_skill (autoresearch macro plan, Phase 3)
# ---------------------------------------------------------------------------


@method("scorecard.list_macro_skill")
def scorecard_list_macro_skill(params: dict[str, Any]) -> dict[str, Any]:
    """Aggregate per-agent macro skill from scored ``macro_signals``.

    Params: cohort (str), since (str YYYY-MM-DD, optional).
    Returns {"rows": [{agent, n_obs, mean_raw_macro_score_5d, hit_rate_5d,
             mean_effective_macro_score_5d, mean_influence_weight_equal,
             sharpe_window, latest_signal_date}, ...]}.
    """
    cohort = _require_str(params, "cohort")
    since: Optional[str] = params.get("since") or None
    if since is not None and not isinstance(since, str):
        raise RpcError(INVALID_PARAMS, "'since' must be a string when provided")
    try:
        return {"rows": _store().list_macro_skill(cohort=cohort, since=since)}
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


@method("scorecard.latest_cio_actions")
def scorecard_latest_cio_actions(params: dict[str, Any]) -> dict[str, Any]:
    """The most recent CIO portfolio actions for a cohort — "what to trade
    today" (ticker / action / target_weight_pct / rationale / date)."""
    cohort = _require_str(params, "cohort")
    try:
        return _store().get_latest_cio_actions(cohort)
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("scorecard.win_rate")
def scorecard_win_rate(params: dict[str, Any]) -> dict[str, Any]:
    """Per-ticker directional hit rate over scored CIO picks
    (sign(action)·forward_return_5d > 0). Optional ``since`` (YYYY-MM-DD) and
    ``agent`` (default 'cio')."""
    cohort = _require_str(params, "cohort")
    since: Optional[str] = params.get("since") or None
    if since is not None and not isinstance(since, str):
        raise RpcError(INVALID_PARAMS, "'since' must be a string when provided")
    agent = params.get("agent") or "cio"
    if not isinstance(agent, str):
        raise RpcError(INVALID_PARAMS, "'agent' must be a string when provided")
    try:
        return {"rows": _store().compute_win_rate(cohort, since_date=since, agent=agent)}
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc
