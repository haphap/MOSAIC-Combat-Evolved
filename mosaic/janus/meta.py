"""JANUS — meta-weighting layer over the 7 PRISM regime cohorts (Plan §11.7).

Port of ATLAS ``janus.py`` adapted from its 2 time-window cohorts (JSON files)
to MOSAIC's 7 regime cohorts (SQLite ``scorecard.db``). JANUS:

  * scores each cohort's recent CIO predictions (rolling hit_rate + Sharpe);
  * turns scores into cohort weights via a feasibility-aware softmax with
    floor/ceiling constraints (ATLAS used MIN=0.2 — infeasible at N=7, so the
    floor/ceiling scale with N here);
  * emits a regime signal from the dominant cohort + weight concentration;
  * blends same-ticker CIO recommendations across cohorts by weight, flagging
    direction conflicts as ``contested``.

Pure functions over a ``ScorecardStore`` — no LLM, no network.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

# Raw weight constraints (ATLAS parity); made feasibility-aware in
# ``softmax_with_constraints`` so any cohort count N normalises cleanly.
MIN_WEIGHT = 0.2
MAX_WEIGHT = 0.8
ROLLING_WINDOW_DAYS = 30
# Weight concentration above uniform beyond this → CONCENTRATED regime.
CONCENTRATION_THRESHOLD = 0.10
_ANNUALIZATION = math.sqrt(252.0)

# Long / short direction sets for hit-rate scoring (A-share: SELL/REDUCE ≈ exit).
_LONG_ACTIONS = {"LONG", "BUY"}
_SHORT_ACTIONS = {"SHORT", "SELL", "REDUCE"}


def _since(now_iso: str, window_days: int) -> str:
    base = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    return (base - timedelta(days=window_days)).date().isoformat()


def cohort_accuracy(
    store,
    cohort: str,
    now_iso: str,
    window_days: int = ROLLING_WINDOW_DAYS,
) -> dict[str, float]:
    """Rolling hit-rate + annualized Sharpe of a cohort's scored CIO picks.

    Falls back to a neutral prior (hit_rate=0.5, sharpe=0.0) when there are no
    scored CIO rows in the window — so a cold cohort gets equal footing.
    """
    rows = store.list_scored(cohort=cohort, agent="cio", since_date=_since(now_iso, window_days))
    rows = [r for r in rows if r.get("forward_return_5d") is not None]
    if not rows:
        return {"hit_rate": 0.5, "sharpe": 0.0, "n": 0}

    weighted_returns: list[float] = []
    hits = 0
    for r in rows:
        ret = float(r["forward_return_5d"])
        action = str(r.get("action") or "").upper()
        # Conviction proxy: target_weight_pct (CIO conviction is NULL per R-A2).
        strength = float(r.get("target_weight_pct") or 0.0) / 100.0
        if action in _SHORT_ACTIONS:
            is_hit = ret < 0
            weighted_returns.append(strength * (-ret))
        else:  # treat LONG/BUY/HOLD/unknown as long-biased
            is_hit = ret > 0
            weighted_returns.append(strength * ret)
        if is_hit:
            hits += 1

    hit_rate = hits / len(rows)
    sharpe = 0.0
    if len(weighted_returns) >= 2:
        mean = sum(weighted_returns) / len(weighted_returns)
        var = sum((x - mean) ** 2 for x in weighted_returns) / (len(weighted_returns) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std) * _ANNUALIZATION if std > 0 else 0.0
    return {"hit_rate": hit_rate, "sharpe": sharpe, "n": len(rows)}


def softmax_with_constraints(scores: Mapping[str, float]) -> dict[str, float]:
    """Softmax ``scores`` → weights summing to 1, with feasibility-aware
    floor/ceiling. ATLAS's fixed MIN=0.2 is infeasible at N>5 (N×0.2>1), so the
    floor is ``min(MIN_WEIGHT, 0.5/N)`` and the ceiling ``max(MAX_WEIGHT,
    1.5/N)`` — identical behaviour at N=2, always normalisable at any N."""
    if not scores:
        return {}
    n = len(scores)
    floor = min(MIN_WEIGHT, 0.5 / n)
    ceil = max(MAX_WEIGHT, 1.5 / n)

    mx = max(scores.values())
    exp = {k: math.exp(v - mx) for k, v in scores.items()}
    total = sum(exp.values()) or 1.0
    w = {k: v / total for k, v in exp.items()}

    # Clamp to [floor, ceil] then renormalise the *unclamped* mass across the
    # still-free entries, iterating to a fixed point. A single floor→renorm→
    # ceiling→renorm pass (ATLAS) can leave a floored weight back below the
    # floor after the ceiling renorm; iterating until stable fixes that.
    for _ in range(50):
        clamped = {k: min(max(v, floor), ceil) for k, v in w.items()}
        total = sum(clamped.values())
        renorm = {k: v / total for k, v in clamped.items()}
        if all(floor - 1e-9 <= v <= ceil + 1e-9 for v in renorm.values()):
            return renorm
        w = renorm
    return w


def compute_cohort_weights(
    store,
    cohorts: list[str],
    now_iso: str,
    window_days: int = ROLLING_WINDOW_DAYS,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Return ``(weights, accuracy_by_cohort)``. Score = 0.5·hit_rate +
    0.5·normalized_sharpe (ATLAS blend)."""
    accuracy: dict[str, dict[str, float]] = {}
    raw: dict[str, float] = {}
    for c in cohorts:
        m = cohort_accuracy(store, c, now_iso, window_days)
        accuracy[c] = m
        norm_sharpe = max(0.0, min(1.0, (m["sharpe"] + 1.0) / 2.0))
        raw[c] = 0.5 * m["hit_rate"] + 0.5 * norm_sharpe
    return softmax_with_constraints(raw), accuracy


def regime_signal(
    weights: Mapping[str, float],
    cohort_configs: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> dict[str, Any]:
    """Regime = the dominant (highest-weight) cohort + concentration.

    ATLAS used a 2-cohort short-vs-long differential; with 7 regime cohorts the
    informative signal is *which regime cohort the meta-layer currently trusts*
    plus how concentrated that trust is (vs a uniform 1/N split).
    """
    if not weights:
        return {"dominant_cohort": None, "regime_label": "UNKNOWN", "concentration": 0.0}
    dominant = max(weights, key=lambda k: weights[k])
    n = len(weights)
    concentration = weights[dominant] - (1.0 / n)
    label_src = (cohort_configs or {}).get(dominant, {})
    regime_label = str(label_src.get("description") or dominant)
    return {
        "dominant_cohort": dominant,
        "regime_label": regime_label,
        "concentration": round(concentration, 4),
        "concentration_state": (
            "CONCENTRATED" if concentration > CONCENTRATION_THRESHOLD else "DIFFUSE"
        ),
    }


def _latest_cio_picks(store, cohort: str, date: str) -> list[dict[str, Any]]:
    """CIO recommendation rows for a cohort on ``date``."""
    return [
        r
        for r in store.list_recommendations(cohort=cohort, agent="cio", date=date)
        if r.get("ticker")
    ]


def blend_recommendations(
    store,
    weights: Mapping[str, float],
    date: str,
) -> dict[str, Any]:
    """Blend same-ticker CIO recommendations across cohorts by weight.

    Port of ATLAS ``blend_recommendations`` + ``_blend_ticker_recommendations``:
    weighted long/short conviction (using target_weight_pct as strength), the
    higher side wins, and a direction conflict halves the loser off the winner
    and flags ``contested``.
    """
    by_ticker: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for cohort, w in weights.items():
        if w <= 0:
            continue
        for rec in _latest_cio_picks(store, cohort, date):
            by_ticker.setdefault(rec["ticker"], []).append((cohort, rec))

    blended: list[dict[str, Any]] = []
    contested: list[str] = []
    for ticker, entries in by_ticker.items():
        long_w = 0.0
        short_w = 0.0
        breakdown: dict[str, Any] = {}
        for cohort, rec in entries:
            w = weights.get(cohort, 0.0)
            strength = float(rec.get("target_weight_pct") or 0.0)
            action = str(rec.get("action") or "LONG").upper()
            if action in _SHORT_ACTIONS:
                short_w += strength * w
            else:
                long_w += strength * w
            breakdown[cohort] = {
                "action": action,
                "target_weight_pct": rec.get("target_weight_pct"),
                "weight": round(w, 4),
            }
        is_contested = long_w > 0 and short_w > 0
        if long_w >= short_w:
            direction, base, opp = "LONG", long_w, short_w
        else:
            direction, base, opp = "SHORT", short_w, long_w
        conviction = max(0.0, base - opp * 0.5) if is_contested else base
        if is_contested:
            contested.append(ticker)
        blended.append({
            "ticker": ticker,
            "direction": direction,
            "blended_weight_pct": round(conviction, 2),
            "contested": is_contested,
            "cohort_breakdown": breakdown,
        })

    blended.sort(key=lambda x: x["blended_weight_pct"], reverse=True)
    return {"blended_recommendations": blended, "contested_tickers": contested}


def run_daily(
    store,
    cohorts: list[str],
    date: str,
    now_iso: Optional[str] = None,
    window_days: int = ROLLING_WINDOW_DAYS,
    cohort_configs: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> dict[str, Any]:
    """Full daily JANUS cycle → output dict, persisted to ``janus_runs``."""
    import json

    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    weights, accuracy = compute_cohort_weights(store, cohorts, now_iso, window_days)
    regime = regime_signal(weights, cohort_configs)
    blend = blend_recommendations(store, weights, date)

    output = {
        "date": date,
        "cohort_weights": {k: round(v, 4) for k, v in weights.items()},
        "regime": regime,
        "cohort_accuracy": {
            k: {"hit_rate": round(v["hit_rate"], 4), "sharpe": round(v["sharpe"], 4), "n": v["n"]}
            for k, v in accuracy.items()
        },
        "blended_recommendations": blend["blended_recommendations"],
        "contested_tickers": blend["contested_tickers"],
    }

    store.record_janus_run(
        date=date,
        weights_json=json.dumps(output["cohort_weights"]),
        regime_label=regime["regime_label"],
        dominant_cohort=regime["dominant_cohort"],
        concentration=regime["concentration"],
        n_blended=len(blend["blended_recommendations"]),
        n_contested=len(blend["contested_tickers"]),
    )
    return output
