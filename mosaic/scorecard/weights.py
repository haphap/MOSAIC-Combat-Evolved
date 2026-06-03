"""Darwinian weights compute (Plan §11.3 sub-step 3C).

Reads scored rows from ``ScorecardStore.list_scored``, computes per-agent
rolling Sharpe over 30 / 90 **calendar-day** windows, projects to a
continuous weight in [0.3, 2.5], and upserts the (cohort, agent, date) row
in ``darwinian_weights``.

**Window semantics — calendar days, not trading days** (PR #3 review hotfix):
The cutoff is computed via ``today - timedelta(days=N)``, which is calendar
days. At daily-cycle cadence (one alpha_5d per trading day) this gives
≈ N × 5/7 trading observations. We accept the calendar-day approximation
because (a) it's simpler, (b) it's robust against missed cycles (a
holiday-shortened week still has ~21 calendar-day observations even when
trading days are thin), and (c) the Sharpe estimate is dominated by sample
size rather than the precise window edge.

Weight formula (plan §11.3 design decision #6):

    weight = clip(0.5 + rolling_sharpe_30d, 0.3, 2.5)

Empty / insufficient data fallback (plan §11.3 design decision #7):

    n_obs < MIN_OBS_FOR_SHARPE → weight = 1.0 uniform across all agents
    in the cohort. Matches Phase 2 stub behaviour exactly so the first
    30 days of a cohort don't have Phase 3 weights perturbing the
    portfolio.

Caveat (documented for Phase 4 autoresearch):

    alpha_5d observations come from daily recommendations with
    OVERLAPPING 5-day forward windows (today's window vs tomorrow's
    differ by 4 of 5 days). This biases std(alpha_5d) downward and
    therefore Sharpe upward. We accept the bias for MVP — Phase 4 can
    switch to non-overlapping 5d windows or Newey-West variance.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Calendar-day windows. Re-named from WINDOW_30/WINDOW_90 in the PR #3
# review hotfix to make the (calendar, not trading) semantic explicit.
CALENDAR_DAYS_30 = 30
CALENDAR_DAYS_90 = 90

# Below this number of scored observations, we don't trust Sharpe.
MIN_OBS_FOR_SHARPE = 5

# Annualization: 252 trading days / 5d horizon = 50.4 periods per year.
# sqrt of that is the multiplier turning a per-period (5d) Sharpe into an
# annualized one.
ANNUALIZATION = math.sqrt(252.0 / 5.0)

# Weight formula bounds (plan §11.3 design decision #6).
WEIGHT_MIN = 0.3
WEIGHT_MAX = 2.5
WEIGHT_INTERCEPT = 0.5

# Quartile fallback when a single agent has too few observations.
DEFAULT_QUARTILE = 4

WEIGHT_START = 1.0
TOP_MULTIPLIER = 1.05
BOTTOM_MULTIPLIER = 0.95


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _sharpe(alphas: list[float]) -> Optional[float]:
    """Annualized Sharpe from a list of 5d alphas; None when n < MIN_OBS."""
    if len(alphas) < MIN_OBS_FOR_SHARPE:
        return None
    n = len(alphas)
    mean = sum(alphas) / n
    var = sum((a - mean) ** 2 for a in alphas) / max(n - 1, 1)
    std = math.sqrt(var)
    if std == 0:
        # All alphas identical → undefined Sharpe; treat as 0 (neutral).
        return 0.0
    return (mean / std) * ANNUALIZATION


def _filter_recent(rows: list[dict], today_iso: str, window_days: int) -> list[dict]:
    """Keep rows whose ``date`` falls in ``[today - window_days, today]``."""
    today = datetime.strptime(today_iso, "%Y-%m-%d").date()
    cutoff = today - timedelta(days=window_days)
    out: list[dict] = []
    for r in rows:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError, TypeError):
            continue
        if cutoff <= d <= today and r.get("alpha_5d") is not None:
            out.append(r)
    return out


def _cutoff_date(today_iso: str, window_days: int) -> str:
    today_date = datetime.strptime(today_iso, "%Y-%m-%d").date()
    return (today_date - timedelta(days=window_days)).isoformat()


def _darwinian_cfg(config: Optional[dict[str, Any]]) -> dict[str, Any]:
    if config is None:
        try:
            from mosaic.default_config import DEFAULT_CONFIG

            config = DEFAULT_CONFIG
        except Exception:  # noqa: BLE001
            config = {}
    return dict((config or {}).get("darwinian", {}) or {})


def _layer_by_agent() -> dict[str, str]:
    try:
        from mosaic.bridge.handlers.prompts import _LAYER_BY_AGENT

        return dict(_LAYER_BY_AGENT)
    except Exception:  # noqa: BLE001
        return {}


def _assign_quartiles(sorted_agents: list[str]) -> dict[str, int]:
    n_ranked = len(sorted_agents)
    return {
        agent: min(int(i * 4 / max(n_ranked, 1)) + 1, 4)
        for i, agent in enumerate(sorted_agents)
    }


def _previous_weight(previous: dict[str, dict[str, Any]], agent: str, start: float) -> float:
    row = previous.get(agent)
    if row and row.get("weight") is not None:
        return float(row["weight"])
    return start


def compute_weights(
    store,
    cohort: str,
    today: str,
    config: Optional[dict[str, Any]] = None,
) -> dict:
    """Compute and upsert darwinian_weights rows for every agent that has
    scored recommendations in ``cohort``.

    Returns ``{"written": int, "agents_uniform_fallback": int}``.

    ``today`` (YYYY-MM-DD) is the as-of date written into the
    darwinian_weights rows. Caller decides when to invoke (typically end
    of trading day after Scorer has run).
    """
    dcfg = _darwinian_cfg(config)
    if bool(dcfg.get("weight_rewrite_enabled", False)):
        return _compute_evolutionary_weights(store, cohort, today, dcfg)

    return _compute_sharpe_weights(store, cohort, today)


def _compute_sharpe_weights(store, cohort: str, today: str) -> dict:
    """Legacy rolling-Sharpe projection. Default path until Phase 9 is gated on."""
    # Pull *all* scored rows for the cohort once and bucket per agent.
    all_scored = store.list_scored(cohort)
    if not all_scored:
        return {"written": 0, "agents_uniform_fallback": 0}

    by_agent: dict[str, list[dict]] = {}
    for row in all_scored:
        by_agent.setdefault(row["agent"], []).append(row)

    # Compute 30d and 90d Sharpe per agent.
    per_agent_sharpe: dict[str, dict[str, Optional[float]]] = {}
    for agent, rows in by_agent.items():
        rows_30 = _filter_recent(rows, today, CALENDAR_DAYS_30)
        rows_90 = _filter_recent(rows, today, CALENDAR_DAYS_90)
        per_agent_sharpe[agent] = {
            "n_30": len(rows_30),
            "sharpe_30": _sharpe([r["alpha_5d"] for r in rows_30]),
            "sharpe_90": _sharpe([r["alpha_5d"] for r in rows_90]),
        }

    # Quartile assignment: rank agents by sharpe_30 (None → bottom).
    # Sort descending so quartile 1 = top.
    agents_with_sharpe = [
        (a, s["sharpe_30"]) for a, s in per_agent_sharpe.items() if s["sharpe_30"] is not None
    ]
    agents_with_sharpe.sort(key=lambda t: t[1], reverse=True)
    n_ranked = len(agents_with_sharpe)
    quartiles: dict[str, int] = {}
    for i, (agent, _) in enumerate(agents_with_sharpe):
        # Standard quartile: 1 = top 25%, 4 = bottom 25%.
        q = min(int(i * 4 / max(n_ranked, 1)) + 1, 4)
        quartiles[agent] = q

    # Build rows + write
    rows_to_upsert: list[dict] = []
    fallback_count = 0
    for agent, stats in per_agent_sharpe.items():
        s_30 = stats["sharpe_30"]
        if s_30 is None:
            weight = 1.0
            fallback_count += 1
            quartile = DEFAULT_QUARTILE
        else:
            weight = _clip(WEIGHT_INTERCEPT + s_30, WEIGHT_MIN, WEIGHT_MAX)
            quartile = quartiles.get(agent, DEFAULT_QUARTILE)

        rows_to_upsert.append(
            {
                "cohort": cohort,
                "agent": agent,
                "layer": _layer_by_agent().get(agent),
                "date": today,
                "weight": weight,
                "rolling_sharpe_30": s_30,
                "rolling_sharpe_90": stats["sharpe_90"],
                "quartile": quartile,
                "performance_metric": "rolling_sharpe_30",
                "performance_value": s_30,
                "rank_scope": "recommendation",
                "update_action": "legacy_sharpe",
                "n_obs": stats["n_30"],
                "source_table": "recommendations",
                "source_date": today,
            }
        )

    n_written = store.upsert_darwinian_weights(rows_to_upsert)
    return {
        "written": n_written,
        "agents_uniform_fallback": fallback_count,
    }


def _collect_recommendation_candidates(
    store,
    cohort: str,
    today: str,
    min_obs: int,
) -> list[dict[str, Any]]:
    since = _cutoff_date(today, CALENDAR_DAYS_30)
    rows = store.list_scored(cohort, since_date=since)
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("alpha_5d") is None:
            continue
        by_agent.setdefault(row["agent"], []).append(row)

    layer_by_agent = _layer_by_agent()
    candidates: list[dict[str, Any]] = []
    for agent, recs in by_agent.items():
        values = [float(r["alpha_5d"]) for r in recs if r.get("alpha_5d") is not None]
        if not values:
            continue
        candidates.append(
            {
                "agent": agent,
                "layer": layer_by_agent.get(agent),
                "rank_scope": "recommendation",
                "performance_metric": "alpha_5d_mean_30d",
                "performance_value": sum(values) / len(values),
                "n_obs": len(values),
                "eligible": len(values) >= min_obs,
                "source_table": "recommendations",
                "source_date": max(r["date"] for r in recs),
            }
        )
    return candidates


def _collect_macro_candidates(
    store,
    cohort: str,
    today: str,
    min_obs: int,
) -> list[dict[str, Any]]:
    since = _cutoff_date(today, CALENDAR_DAYS_30)
    try:
        rows = store.list_scored_macro(cohort, since_date=since)
    except AttributeError:
        return []
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("raw_macro_score_5d") is None:
            continue
        by_agent.setdefault(row["agent"], []).append(row)

    candidates: list[dict[str, Any]] = []
    for agent, recs in by_agent.items():
        values = [
            float(r["raw_macro_score_5d"])
            for r in recs
            if r.get("raw_macro_score_5d") is not None
        ]
        if not values:
            continue
        candidates.append(
            {
                "agent": agent,
                "layer": "macro",
                "rank_scope": "macro",
                "performance_metric": "raw_macro_score_5d",
                "performance_value": sum(values) / len(values),
                "n_obs": len(values),
                "eligible": len(values) >= min_obs,
                "source_table": "macro_signals",
                "source_date": max(r["date"] for r in recs),
            }
        )
    return candidates


def _compute_evolutionary_weights(
    store,
    cohort: str,
    today: str,
    cfg: dict[str, Any],
) -> dict:
    start = float(cfg.get("weight_start", WEIGHT_START))
    floor = float(cfg.get("weight_floor", WEIGHT_MIN))
    ceiling = float(cfg.get("weight_ceiling", WEIGHT_MAX))
    top_multiplier = float(cfg.get("top_multiplier", TOP_MULTIPLIER))
    bottom_multiplier = float(cfg.get("bottom_multiplier", BOTTOM_MULTIPLIER))
    min_ranked = int(cfg.get("min_ranked_agents_per_scope", 8))
    min_obs = int(cfg.get("min_scored_observations_per_agent", 10))
    min_macro_matured = int(cfg.get("min_matured_agents_for_update", 8))

    candidates = [
        *_collect_macro_candidates(store, cohort, today, min_obs),
        *_collect_recommendation_candidates(store, cohort, today, min_obs),
    ]
    previous = store.get_darwinian_weights(cohort, before_date=today)

    previous_only_agents = sorted(set(previous) - {c["agent"] for c in candidates})
    layer_by_agent = _layer_by_agent()
    for agent in previous_only_agents:
        prev = previous[agent]
        candidates.append(
            {
                "agent": agent,
                "layer": prev.get("layer") or layer_by_agent.get(agent),
                "rank_scope": prev.get("rank_scope") or (
                    "macro" if (prev.get("layer") or layer_by_agent.get(agent)) == "macro"
                    else "recommendation"
                ),
                "performance_metric": prev.get("performance_metric"),
                "performance_value": None,
                "n_obs": 0,
                "eligible": False,
                "source_table": prev.get("source_table"),
                "source_date": prev.get("source_date"),
            }
        )

    if not candidates:
        return {"written": 0, "agents_uniform_fallback": 0}

    by_scope: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_scope.setdefault(str(candidate["rank_scope"]), []).append(candidate)

    rows_to_upsert: list[dict[str, Any]] = []
    fallback_count = 0
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for scope, scope_candidates in by_scope.items():
        eligible = [
            c for c in scope_candidates
            if c.get("eligible") and c.get("performance_value") is not None
        ]
        min_scope_ranked = min_macro_matured if scope == "macro" else min_ranked
        can_rank = len(eligible) >= min_scope_ranked
        ranked_agents = [
            c["agent"]
            for c in sorted(
                eligible,
                key=lambda c: float(c["performance_value"]),
                reverse=True,
            )
        ]
        quartiles = _assign_quartiles(ranked_agents) if can_rank else {}

        for candidate in scope_candidates:
            agent = candidate["agent"]
            prev_weight = _previous_weight(previous, agent, start)
            if agent not in previous:
                fallback_count += 1
            quartile = quartiles.get(agent)
            if not can_rank or quartile is None:
                weight = prev_weight
                update_action = "skipped"
            elif quartile == 1:
                weight = _clip(prev_weight * top_multiplier, floor, ceiling)
                update_action = "up"
            elif quartile == 4:
                weight = _clip(prev_weight * bottom_multiplier, floor, ceiling)
                update_action = "down"
            else:
                weight = prev_weight
                update_action = "unchanged"

            rows_to_upsert.append(
                {
                    "cohort": cohort,
                    "agent": agent,
                    "layer": candidate.get("layer"),
                    "date": today,
                    "weight": weight,
                    "previous_weight": prev_weight,
                    "performance_metric": candidate.get("performance_metric"),
                    "performance_value": candidate.get("performance_value"),
                    "normalized_performance": candidate.get("performance_value"),
                    "rank_scope": scope,
                    "rolling_sharpe_30": None,
                    "rolling_sharpe_90": None,
                    "quartile": quartile,
                    "update_action": update_action,
                    "n_obs": int(candidate.get("n_obs") or 0),
                    "source_table": candidate.get("source_table"),
                    "source_date": candidate.get("source_date"),
                    "updated_at": updated_at,
                }
            )

    n_written = store.upsert_darwinian_weights(rows_to_upsert)
    return {"written": n_written, "agents_uniform_fallback": fallback_count}
