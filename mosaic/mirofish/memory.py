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

Pure numpy/stdlib, deterministic. Runnable: ``python -m mosaic.mirofish.memory``.
"""

from __future__ import annotations

import abc
from typing import Any

import numpy as np

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
    same drift control as the A/B-lift canary), captured value = mean signed
    demeaned-forward earned per scenario (0 when abstaining):
      * stateless: always bets with the early trend (activity 1.0).
      * memory:    bets with the trend only where recall is warm and |r| > thr.

    Decisive result: memory_activity(swarm) ≫ memory_activity(MC), and the
    learned correlation recovers the A/B-lift split (swarm ≫ MC) online.
    """
    out: dict[str, Any] = {"config": {"n_seeds": n_seeds, "num_days": num_days,
                                      "threshold": threshold}, "engines": {}}
    for engine in ("montecarlo", "swarm"):
        scen_cache = [_scenarios(engine, seed, num_days) for seed in range(n_seeds)]
        # per-type forward mean for demeaning the *captured* return
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
        s_cap = m_cap = 0.0
        m_active = 0
        n = 0
        for scns in scen_cache:
            for s in scns:
                prices = s["price_paths"][_PROBE]["prices"]
                st = s["scenario_type"]
                trend = _early_trend(prices)
                fwd_dm = _forward(prices) - fwd_mean[st]

                s_cap += float(np.sign(trend)) * fwd_dm

                r, cnt = mem.recall(st)
                if cnt >= _WARMUP and abs(r) > threshold:
                    side = float(np.sign(r)) * float(np.sign(trend))
                    m_cap += side * fwd_dm
                    m_active += 1

                mem.remember(st, trend, _forward(prices))
                n += 1

        learned = {st: round(mem.recall(st)[0], 4) for st in fwd_mean}
        out["engines"][engine] = {
            "stateless_activity": 1.0,
            "stateless_captured": round(s_cap / n, 5),
            "memory_activity": round(m_active / n, 4),
            "memory_captured": round(m_cap / n, 5),
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
