"""MiroFish synthetic-futures scenario engine (Plan §11.8, Phase 7).

Port of ATLAS ``mirofish_futures_generator.py`` adapted to A-share regime
ETFs/indices. Pure numpy — no LLM, no network. Generates correlated
Monte-Carlo price paths under five scenario types (base / bull / bear /
tail_up / tail_down) with event injection, and scores an agent recommendation
against a scenario's realised paths.

Used by the forward-training loop (Plan §11.8 7C): TS drives the LLM
agent-recommendation step; this module owns scenario generation + scoring.
``seed`` makes every path reproducible for the ``--fake-llm`` smoke + tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

import numpy as np

# A-share regime asset basket (replaces ATLAS's SPY/QQQ/TLT/GLD/XLE/VXX/HYG).
# Annualized vol / drift, tuned to A-share regime characteristics.
ASSET_PARAMS: dict[str, dict[str, Any]] = {
    "000300.SH": {"vol": 0.22, "drift": 0.05, "name": "沪深300 / CSI 300"},
    "510050.SH": {"vol": 0.20, "drift": 0.05, "name": "上证50ETF / SSE 50"},
    "159915.SZ": {"vol": 0.32, "drift": 0.06, "name": "创业板ETF / ChiNext"},
    "511010.SH": {"vol": 0.05, "drift": 0.03, "name": "国债ETF / Treasury"},
    "518880.SH": {"vol": 0.16, "drift": 0.03, "name": "黄金ETF / Gold"},
    "512880.SH": {"vol": 0.40, "drift": 0.04, "name": "证券ETF / Brokers (hi-beta)"},
    "513050.SH": {"vol": 0.38, "drift": 0.05, "name": "中概互联 / China Internet"},
}

# Pairwise correlations (A-share structure: equities cluster, bonds/gold hedge).
CORRELATIONS: dict[tuple[str, str], float] = {
    ("000300.SH", "510050.SH"): 0.92,
    ("000300.SH", "159915.SZ"): 0.78,
    ("000300.SH", "512880.SH"): 0.80,
    ("000300.SH", "513050.SH"): 0.65,
    ("000300.SH", "511010.SH"): -0.25,
    ("000300.SH", "518880.SH"): 0.05,
    ("159915.SZ", "513050.SH"): 0.70,
    ("159915.SZ", "512880.SH"): 0.62,
    ("510050.SH", "512880.SH"): 0.72,
    ("511010.SH", "518880.SH"): 0.30,
    ("511010.SH", "512880.SH"): -0.30,
    ("518880.SH", "159915.SZ"): 0.05,
}

# Default start prices (rough levels; the orchestrator can pass live ones).
DEFAULT_START_PRICES: dict[str, float] = {
    "000300.SH": 3500.0,
    "510050.SH": 2.85,
    "159915.SZ": 2.10,
    "511010.SH": 113.0,
    "518880.SH": 5.80,
    "512880.SH": 1.05,
    "513050.SH": 1.35,
}

SCENARIO_TYPES = ("base", "bull", "bear", "tail_up", "tail_down")
_SCENARIO_PROB = {"base": 0.50, "bull": 0.20, "bear": 0.20, "tail_up": 0.05, "tail_down": 0.05}
_SCENARIO_MULT = {"base": 1.0, "bull": 1.5, "bear": -1.2, "tail_up": 2.5, "tail_down": -2.0}
_SCENARIO_NAME = {
    "base": "Base Case — Consensus Path",
    "bull": "Bull Case — Risk-On Rally",
    "bear": "Bear Case — Risk-Off Correction",
    "tail_up": "Tail Risk — Melt-Up",
    "tail_down": "Tail Risk — Crash",
}

# Equity/risk vs safe-haven buckets for scenario drift shaping.
_RISK_ASSETS = {"000300.SH", "510050.SH", "159915.SZ", "512880.SH", "513050.SH"}
_HAVEN_ASSETS = {"511010.SH", "518880.SH"}


def _correlation_matrix(tickers: list[str]) -> np.ndarray:
    n = len(tickers)
    m = np.eye(n)
    for i, a in enumerate(tickers):
        for j, b in enumerate(tickers):
            if i == j:
                continue
            m[i, j] = CORRELATIONS.get((a, b)) or CORRELATIONS.get((b, a)) or 0.0
    return m


def _nearest_pd(corr: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """Nearest positive-definite correlation matrix.

    A hand-specified correlation matrix needn't be PD, and the symmetric
    eigendecomposition reconstruction (unlike a raw SVD round-trip) must be
    repaired to keep a unit diagonal. We clip eigenvalues to ``eps``, rebuild,
    then rescale to unit diagonal so it's a valid correlation matrix Cholesky
    can factor.
    """
    sym = (corr + corr.T) / 2
    vals, vecs = np.linalg.eigh(sym)
    vals = np.clip(vals, eps, None)
    rebuilt = (vecs * vals) @ vecs.T
    d = np.sqrt(np.diag(rebuilt))
    rebuilt = rebuilt / np.outer(d, d)
    # Symmetrise + nudge the diagonal to guarantee strict PD for Cholesky.
    rebuilt = (rebuilt + rebuilt.T) / 2
    np.fill_diagonal(rebuilt, 1.0)
    return rebuilt


def generate_correlated_returns(
    tickers: list[str],
    num_days: int,
    adjustments: Optional[Mapping[str, float]] = None,
    seed: Optional[int] = None,
) -> dict[str, np.ndarray]:
    """Correlated daily returns via Cholesky on the nearest-PD correlation matrix."""
    adjustments = adjustments or {}
    rng = np.random.default_rng(seed)
    corr = _nearest_pd(_correlation_matrix(tickers))
    L = np.linalg.cholesky(corr)

    Z = rng.standard_normal((len(tickers), num_days))
    correlated = L @ Z

    out: dict[str, np.ndarray] = {}
    for i, t in enumerate(tickers):
        p = ASSET_PARAMS.get(t, {"vol": 0.20, "drift": 0.05})
        daily_vol = p["vol"] / np.sqrt(252)
        daily_drift = p["drift"] / 252
        adj = adjustments.get(t, 0.0) / num_days
        out[t] = daily_drift + adj + daily_vol * correlated[i]
    return out


def _scenario_adjustments(scenario_type: str) -> dict[str, float]:
    """Drift adjustments per asset bucket for a scenario type."""
    mult = _SCENARIO_MULT.get(scenario_type, 1.0)
    adj: dict[str, float] = {}
    for t in ASSET_PARAMS:
        if scenario_type in ("bear", "tail_down"):
            adj[t] = -0.10 * abs(mult) if t in _RISK_ASSETS else 0.06 * abs(mult)
        elif scenario_type in ("bull", "tail_up"):
            adj[t] = 0.10 * mult if t in _RISK_ASSETS else -0.02 * mult
        else:  # base
            adj[t] = 0.0
    return adj


_EVENTS = [
    {"day": 5, "event": "政策窗口 / Policy window", "impact": "HIGH"},
    {"day": 10, "event": "业绩集中披露 / Earnings cluster", "impact": "HIGH"},
    {"day": 18, "event": "限售解禁 / Lockup expiry", "impact": "MEDIUM"},
    {"day": 25, "event": "FOMC 外溢 / Fed spillover", "impact": "MEDIUM"},
]


def _generate_events(scenario_type: str, num_days: int, start: datetime, rng: np.random.Generator) -> list[dict]:
    events = [
        {**e, "date": (start + timedelta(days=e["day"])).strftime("%Y-%m-%d")}
        for e in _EVENTS
        if e["day"] <= num_days
    ]
    if scenario_type in ("tail_up", "tail_down"):
        shock_day = int(rng.integers(5, max(6, min(20, num_days))))
        events.append({
            "day": shock_day,
            "date": (start + timedelta(days=shock_day)).strftime("%Y-%m-%d"),
            "event": "黑天鹅冲击 / Black-swan shock",
            "impact": "EXTREME",
        })
    return sorted(events, key=lambda x: x["day"])


def _final_state(paths: dict[str, dict]) -> dict[str, Any]:
    csi = paths.get("000300.SH", {}).get("cumulative_return", 0.0)
    if csi > 0.10:
        regime, narrative = "RISK_ON", "强势上行，风险偏好主导"
    elif csi < -0.10:
        regime, narrative = "RISK_OFF", "急跌回调，防御占优"
    else:
        regime, narrative = "NEUTRAL", "区间震荡，选股市场"
    return {"regime": regime, "narrative": narrative, "csi300_return": round(csi, 4)}


# ── reflexivity overlay (Plan §11.8) ────────────────────────────────────────
#
# Canonical MiroFish (666ghj/MiroFish) is a *swarm* reflexivity engine: many
# persona agents interact + socially evolve (OASIS/CAMEL-AI), and the
# *collective* shapes the trajectory. A full GraphRAG+memory swarm is out of
# scope for this port (Plan §11.8 "不在范围"; roadmap in §11.8.1).
#
# This is a much narrower, deterministic stand-in. Mathematically it is a
# **per-asset reflexive feedback kernel**: a fixed weighted blend of four
# heterogeneous demand-response functions (momentum / contrarian / herding /
# value) maps an asset's *own* trailing returns to a same-day demand that
# **feeds back into** its next return (price → demand → price). It captures the
# *defining* mechanic the ATLAS i.i.d. Monte-Carlo lacked — a reflexive loop
# rather than a random walk — but it is NOT interacting agents, has no memory,
# and no cross-asset/collective coupling (each asset's kernel sees only itself).
# True agent-to-agent interaction + memory is Phase 7M (Plan §11.8.1).
#
# Each response function maps the trailing window return to a same-day demand:
#   momentum   chases recent moves (amplifies trends → bubbles/crashes)
#   contrarian fades recent moves (dampens / mean-reverts)
#   herding    piles into whichever side is winning (nonlinear, threshold)
#   value      leans against large cumulative deviations from start
# Weights = relative population share of each response type (not literal agents).
REFLEX_RESPONSE_WEIGHTS = {"momentum": 0.35, "contrarian": 0.25, "herding": 0.20, "value": 0.20}
_REFLEX_GAIN = 0.6  # overall feedback strength (kept modest to stay stable)
_REFLEX_WINDOW = 3  # trailing days the kernel reacts to


def _reflex_demand(trailing: list[float], cum_dev: float) -> float:
    """Net demand (return perturbation) from recent price action."""
    recent = sum(trailing) if trailing else 0.0
    momentum = recent
    contrarian = -recent
    herding = (1.0 if recent > 0 else -1.0) * min(abs(recent) * 2.0, 0.05) if trailing else 0.0
    value = -cum_dev * 0.10
    return (
        REFLEX_RESPONSE_WEIGHTS["momentum"] * momentum
        + REFLEX_RESPONSE_WEIGHTS["contrarian"] * contrarian
        + REFLEX_RESPONSE_WEIGHTS["herding"] * herding
        + REFLEX_RESPONSE_WEIGHTS["value"] * value
    )


def _build_path_reflexive(start_price: float, base_returns: np.ndarray) -> tuple[list[float], list[float]]:
    """Build a price path where actor demand feeds back into each day's return.

    Returns (prices, effective_returns). Deterministic given base_returns.
    """
    prices = [float(start_price)]
    eff_returns: list[float] = []
    cur = start_price
    for i, base in enumerate(base_returns):
        trailing = eff_returns[max(0, i - _REFLEX_WINDOW):i]
        cum_dev = cur / start_price - 1.0
        r = float(base) + _REFLEX_GAIN * _reflex_demand(trailing, cum_dev)
        cur *= (1 + r)
        prices.append(float(cur))
        eff_returns.append(r)
    return prices, eff_returns


def generate_scenario(
    scenario_type: str,
    start_prices: Optional[Mapping[str, float]] = None,
    num_days: int = 30,
    seed: Optional[int] = None,
    start_date: Optional[str] = None,
    reflexivity: bool = False,
) -> dict[str, Any]:
    """Generate one scenario dict (JSON-serialisable; crosses the bridge)."""
    if scenario_type not in SCENARIO_TYPES:
        raise ValueError(f"scenario_type must be one of {SCENARIO_TYPES}, got {scenario_type!r}")
    prices = dict(start_prices or DEFAULT_START_PRICES)
    tickers = list(prices.keys())
    start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime(2024, 1, 1)

    returns = generate_correlated_returns(
        tickers, num_days, _scenario_adjustments(scenario_type), seed
    )

    paths: dict[str, dict] = {}
    for t in tickers:
        if reflexivity:
            series, eff = _build_path_reflexive(prices[t], returns[t])
            vol = float(np.std(eff) * np.sqrt(252)) if eff else 0.0
        else:
            series = [float(prices[t])]
            cur = prices[t]
            for r in returns[t]:
                cur *= (1 + r)
                series.append(float(cur))
            vol = float(np.std(returns[t]) * np.sqrt(252))
        paths[t] = {
            "ticker": t,
            "start_price": float(prices[t]),
            "prices": series,
            "cumulative_return": series[-1] / series[0] - 1,
            "volatility": vol,
        }

    rng = np.random.default_rng(seed)
    return {
        "scenario_type": scenario_type,
        "scenario_name": _SCENARIO_NAME[scenario_type],
        "probability": _SCENARIO_PROB[scenario_type],
        "num_days": num_days,
        "reflexive": reflexivity,
        "price_paths": paths,
        "events": _generate_events(scenario_type, num_days, start, rng),
        "final_state": _final_state(paths),
    }


def generate_all_scenarios(
    start_prices: Optional[Mapping[str, float]] = None,
    num_days: int = 30,
    seed: Optional[int] = None,
    scenarios: Optional[list[str]] = None,
    reflexivity: bool = False,
) -> list[dict[str, Any]]:
    """All five scenario types; per-scenario seed offset keeps each distinct
    yet reproducible from the base ``seed``."""
    types = scenarios or list(SCENARIO_TYPES)
    out = []
    for i, st in enumerate(types):
        s = None if seed is None else seed + i
        out.append(generate_scenario(st, start_prices, num_days, s, reflexivity=reflexivity))
    return out


_LONG = {"BUY", "LONG"}
_SHORT = {"SELL", "SHORT", "REDUCE"}


def score_recommendation(recommendation: Mapping[str, Any], scenario: Mapping[str, Any]) -> float:
    """Score a rec against a scenario's realised paths → [0, 1].

    Port of ATLAS scoring: direction × cumulative return averaged over the
    rec's tickers, mapped so +20% ≈ 1.0 / -20% ≈ 0.0 / flat = 0.5, then a
    conviction reward/penalty (wrong high-conviction hurts more).
    """
    if not isinstance(recommendation, Mapping) or recommendation.get("error"):
        return 0.0
    direction = str(recommendation.get("recommendation", "HOLD")).upper()
    tickers = recommendation.get("tickers") or []
    conviction = float(recommendation.get("conviction", 0.5))
    paths = scenario.get("price_paths", {})

    total, count = 0.0, 0
    for t in tickers:
        p = paths.get(t)
        if not p:
            continue
        ret = float(p.get("cumulative_return", 0.0))
        if direction in _LONG:
            total += ret
        elif direction in _SHORT:
            total -= ret
        count += 1
    if count == 0:
        return 0.5  # neutral when no actionable picks (HOLD or unknown tickers)

    avg = total / count
    score = 0.5 + (avg / 0.40)
    score = max(0.0, min(1.0, score))
    if avg < 0:
        score *= (1 - conviction * 0.3)
    else:
        score = min(1.0, score * (1 + conviction * 0.2))
    return score
