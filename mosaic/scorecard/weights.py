"""Darwinian weights compute (Plan §11.3 sub-step 3C).

Reads scored rows from ``ScorecardStore.list_scored``, computes per-agent
rolling Sharpe over 30 / 90 trading-day windows, projects to a continuous
weight in [0.3, 2.5], and upserts the (cohort, agent, date) row in
``darwinian_weights``.

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
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Trading-day windows
WINDOW_30 = 30
WINDOW_90 = 90

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


def compute_weights(store, cohort: str, today: str) -> dict:
    """Compute and upsert darwinian_weights rows for every agent that has
    scored recommendations in ``cohort``.

    Returns ``{"written": int, "agents_uniform_fallback": int}``.

    ``today`` (YYYY-MM-DD) is the as-of date written into the
    darwinian_weights rows. Caller decides when to invoke (typically end
    of trading day after Scorer has run).
    """
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
        rows_30 = _filter_recent(rows, today, WINDOW_30)
        rows_90 = _filter_recent(rows, today, WINDOW_90)
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
                "date": today,
                "weight": weight,
                "rolling_sharpe_30": s_30,
                "rolling_sharpe_90": stats["sharpe_90"],
                "quartile": quartile,
            }
        )

    n_written = store.upsert_darwinian_weights(rows_to_upsert)
    return {
        "written": n_written,
        "agents_uniform_fallback": fallback_count,
    }
