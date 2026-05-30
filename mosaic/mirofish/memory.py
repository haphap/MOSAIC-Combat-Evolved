"""Minimal 7M.2 memory prototype + its lift measurement (Plan §11.8.1).

The A/B-lift gate found the swarm carries a modest-but-real exploitable forward
signal — early-trend → forward-return correlation ≈ +0.10 per scenario_type,
vs ≈ 0 for i.i.d. Monte-Carlo. This prototype asks the one question that gates
the full 7M.2 build:

    Does cross-round MEMORY convert that forward signal into selective value —
    and correctly learn there is NOTHING to exploit under Monte-Carlo?

``LocalAgentMemory`` is the first concrete sketch of the eventual ``AgentMemory``
interface (``remember`` / ``recall``). Per context (here the ``scenario_type``)
it maintains an ONLINE Pearson correlation between the early-window trend and the
realised forward return — i.e. it *learns from experience* how predictive the
early trend is in each regime. (Correlation, not covariance/payoff: it normalises
out the swarm's compressed dispersion and is exactly the quantity the A/B-lift
canary separates the engines on.)

A memory-driven policy then bets WITH the early trend only where memory has both
enough observations AND a clear learned correlation (``|r| > threshold``), taking
the sign of ``r``; elsewhere it ABSTAINS. The value of memory is *selectivity*:
it should be active under the swarm (there is an edge to find) and abstain under
Monte-Carlo (there is not) — whereas a stateless trend-follower bets everywhere.

DESIGN CEILING (why the verdict is NO-GO, not a tuning miss): under the swarm
every per-context correlation is positive (~0.10), so sign(r)=+1 and this policy
degenerates to "trend-follow when warm+confident, else abstain" — a *subset* of
the stateless trend-follower's actions. Its best case is therefore to *match*
stateless on a uniformly-trending edge; it can only beat stateless if some
contexts warranted FADING the trend, or if over-betting in the no-edge regime
were penalised. A value-adding memory iteration thus needs context-differentiated
/ fade signals or an over-bet-penalising objective (§11.8.1 restart condition #2).

Pure numpy/stdlib, deterministic. Runnable: ``python -m mosaic.mirofish.memory``.
"""

from __future__ import annotations

import abc
from typing import Any

import numpy as np

from mosaic.mirofish import score_recommendation
from mosaic.mirofish.ab_lift import _DECISION_FRAC, _PROBE, _scenarios

_WARMUP = 8              # min observations per context before memory will act
_CORR_THRESHOLD = 0.05  # |learned correlation| above which the policy bets
                        # (between MC ≈0.02 and swarm ≈0.10 — see A/B-lift gate)


class AgentMemory(abc.ABC):
    """Sketch of the §11.8.1 AgentMemory interface (Tier-1 local; a Zep/Graph
    adapter can implement the same two methods later)."""

    @abc.abstractmethod
    def remember(self, context: str, signal: float, outcome: float) -> None:
        """Record one experience: in ``context`` we observed ``signal`` (the
        early-window trend) and the realised ``outcome`` (forward return)."""

    @abc.abstractmethod
    def recall(self, context: str) -> tuple[float, int]:
        """Return (learned_correlation, n_observations) for ``context``."""


class LocalAgentMemory(AgentMemory):
    """Per-context online Pearson correlation between signal and outcome, via
    running sums (deterministic, O(1) per update)."""

    def __init__(self) -> None:
        # context → [n, Σx, Σy, Σxx, Σyy, Σxy]
        self._s: dict[str, list[float]] = {}

    def remember(self, context: str, signal: float, outcome: float) -> None:
        a = self._s.setdefault(context, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        x, y = float(signal), float(outcome)
        a[0] += 1
        a[1] += x
        a[2] += y
        a[3] += x * x
        a[4] += y * y
        a[5] += x * y

    def recall(self, context: str) -> tuple[float, int]:
        a = self._s.get(context)
        if a is None or a[0] < 2:
            return 0.0, int(a[0]) if a else 0
        n, sx, sy, sxx, syy, sxy = a
        cov = n * sxy - sx * sy
        vx = n * sxx - sx * sx
        vy = n * syy - sy * sy
        if vx <= 0 or vy <= 0:
            return 0.0, int(n)
        return float(cov / np.sqrt(vx * vy)), int(n)


def _early_trend(prices: list[float]) -> float:
    k = max(1, int(len(prices) * _DECISION_FRAC))
    p = prices[: k + 1]
    return p[-1] / p[0] - 1.0 if len(p) >= 2 and p[0] > 0 else 0.0


def _forward(prices: list[float]) -> float:
    k = max(1, int(len(prices) * _DECISION_FRAC))
    return prices[-1] / prices[k] - 1.0 if k + 1 < len(prices) and prices[k] > 0 else 0.0


def measure_memory_lift(
    n_seeds: int = 150,
    num_days: int = 30,
    threshold: float = _CORR_THRESHOLD,
) -> dict[str, Any]:
    """Walk scenarios in seed order (online): each round both policies decide on
    the early window, then memory learns from the realised forward return.

    Reports, per engine, with forward returns demeaned per scenario_type (the
    same drift control as the A/B-lift canary; the demean baseline is GLOBAL —
    a full pre-pass over all seeds — applied equally to both policies for scoring
    only, and never feeds the causal decision):
      * stateless: always bets with the early trend (activity 1.0).
      * memory:    bets with the trend only where recall is warm and |r| > thr.

    Three reproducible metrics back the NO-GO verdict (§11.8.1):
      * captured        — mean signed demeaned-forward earned (0 when abstaining);
      * info_ratio      — risk-adjusted: mean / std of the per-scenario capture
                          series (selectivity should cut wasted variance);
      * scorer_mean     — mean real ``score_recommendation`` when memory SIZES
                          CONVICTION (0.9 where warm+confident else 0.1, side by
                          sign(r)) vs stateless always-0.9-with-trend.

    Decisive result: memory learns the split online (corr swarm ≫ MC) and acts
    selectively, yet beats stateless on NONE of the three.
    """
    out: dict[str, Any] = {"config": {"n_seeds": n_seeds, "num_days": num_days,
                                      "threshold": threshold}, "engines": {}}
    for engine in ("montecarlo", "swarm"):
        scen_cache = [_scenarios(engine, seed, num_days) for seed in range(n_seeds)]
        # per-type forward mean for demeaning the *captured* return (global baseline)
        fwd_sum: dict[str, float] = {}
        fwd_cnt: dict[str, int] = {}
        for scns in scen_cache:
            for s in scns:
                f = _forward(s["price_paths"][_PROBE]["prices"])
                st = s["scenario_type"]
                fwd_sum[st] = fwd_sum.get(st, 0.0) + f
                fwd_cnt[st] = fwd_cnt.get(st, 0) + 1
        fwd_mean = {st: fwd_sum[st] / fwd_cnt[st] for st in fwd_sum}

        mem = LocalAgentMemory()
        s_caps: list[float] = []   # per-scenario capture series (for info ratio)
        m_caps: list[float] = []
        s_scores: list[float] = []  # real-scorer conviction-sizing series
        m_scores: list[float] = []
        m_active = 0
        for scns in scen_cache:
            for s in scns:
                prices = s["price_paths"][_PROBE]["prices"]
                st = s["scenario_type"]
                trend = _early_trend(prices)
                fwd_dm = _forward(prices) - fwd_mean[st]
                direction = "BUY" if trend > 0 else "SELL"

                s_caps.append(float(np.sign(trend)) * fwd_dm)
                # stateless: always high-conviction with the trend.
                s_scores.append(score_recommendation(
                    {"recommendation": direction, "tickers": [_PROBE], "conviction": 0.9},
                    s, path_aware=True))

                r, cnt = mem.recall(st)
                warm = cnt >= _WARMUP and abs(r) > threshold
                if warm:
                    side = float(np.sign(r)) * float(np.sign(trend))
                    m_caps.append(side * fwd_dm)
                    m_active += 1
                else:
                    m_caps.append(0.0)
                # memory: high conviction only where warm+confident; side by sign(r).
                m_dir = direction if r >= 0 else ("SELL" if direction == "BUY" else "BUY")
                m_scores.append(score_recommendation(
                    {"recommendation": m_dir, "tickers": [_PROBE],
                     "conviction": 0.9 if warm else 0.1}, s, path_aware=True))

                mem.remember(st, trend, _forward(prices))

        n = len(s_caps)
        learned = {st: round(mem.recall(st)[0], 4) for st in fwd_mean}

        def _ir(xs: list[float]) -> float:
            a = np.asarray(xs)
            return round(float(a.mean() / a.std()), 4) if a.std() > 0 else 0.0

        out["engines"][engine] = {
            "stateless_activity": 1.0,
            "stateless_captured": round(float(np.mean(s_caps)), 5),
            "memory_activity": round(m_active / n, 4),
            "memory_captured": round(float(np.mean(m_caps)), 5),
            "stateless_info_ratio": _ir(s_caps),
            "memory_info_ratio": _ir(m_caps),
            "stateless_scorer_mean": round(float(np.mean(s_scores)), 4),
            "memory_scorer_mean": round(float(np.mean(m_scores)), 4),
            "learned_corr_by_type": learned,
            "mean_learned_corr": round(float(np.mean(list(learned.values()))), 4),
            "n": n,
        }
    return out


def main() -> None:  # pragma: no cover - manual run
    import json

    print(json.dumps(measure_memory_lift(), indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
