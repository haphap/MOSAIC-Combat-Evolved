"""A/B-lift measurement: the final gate before full 7M.2 (Plan §11.8.1).

The earlier A/B gate proved the swarm produces reflexive return *structure*
(lag-1 autocorr ≈ +0.16) and the path-aware scorer can *see* path shape. This
asks the payoff question: does that structure translate into an **exploitable,
differently-ranked training signal** — the precondition for memory (7M.2) to add
anything?

Both engines are synthetic (no ground truth), so we don't measure prediction
accuracy. Instead we run fixed, deterministic rule-based **policies** (no LLM)
that each DECIDE on an early window of the path (no look-ahead) and are then
scored on the full realised path, crossing engine × scorer:

  * trend_follower — early-window up → BUY, down → SELL. Under i.i.d. MC the
    early trend carries ~no information; under the swarm's autocorrelation it
    predicts → this policy is the canary for exploitable reflexive signal.
  * mean_reverter — the opposite bet.
  * always_buy / always_hold — direction-blind baselines.

Reported per regime:
  * mean score per policy;
  * discrimination = best-policy mean − worst-policy mean (how strongly the
    regime separates good from bad behaviour — a sharper training gradient);
  * trend_follower − always_hold (does early trend become exploitable?);
  * Spearman rank-correlation of the policy ranking vs the montecarlo+terminal
    baseline (< 1 ⇒ the regime reorders agents ⇒ adds signal a trainer would
    actually chase).

Pure numpy/stdlib, deterministic. Runnable: ``python -m mosaic.mirofish.ab_lift``.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from mosaic.mirofish import generate_all_scenarios, score_recommendation
from mosaic.mirofish.swarm import LocalSwarmEngine

_PROBE = "000300.SH"
_DECISION_FRAC = 0.25  # policies see only the first 25% of the path when deciding


def _early_trend(prices: list[float]) -> float:
    k = max(1, int(len(prices) * _DECISION_FRAC))
    p = prices[: k + 1]
    return p[-1] / p[0] - 1.0 if len(p) >= 2 and p[0] > 0 else 0.0


def _rec(direction: str) -> dict[str, Any]:
    return {"recommendation": direction, "tickers": [_PROBE], "conviction": 0.6}


# Each policy: scenario → recommendation, using only the early window.
POLICIES: dict[str, Callable[[dict], dict]] = {
    "trend_follower": lambda s: _rec("BUY" if _early_trend(s["price_paths"][_PROBE]["prices"]) > 0 else "SELL"),
    "mean_reverter": lambda s: _rec("SELL" if _early_trend(s["price_paths"][_PROBE]["prices"]) > 0 else "BUY"),
    "always_buy": lambda s: _rec("BUY"),
    "always_hold": lambda s: _rec("HOLD"),
}


def _scenarios(engine: str, seed: int, num_days: int) -> list[dict]:
    if engine == "swarm":
        return LocalSwarmEngine().generate_all_scenarios(num_days=num_days, seed=seed)
    return generate_all_scenarios(num_days=num_days, seed=seed)


def _regime_scores(engine: str, path_aware: bool, seeds: list[int], num_days: int) -> dict[str, float]:
    """Mean score per policy over all (seed × scenario) under one regime."""
    totals = {name: 0.0 for name in POLICIES}
    n = 0
    for seed in seeds:
        scns = _scenarios(engine, seed, num_days)
        for s in scns:
            for name, policy in POLICIES.items():
                totals[name] += score_recommendation(policy(s), s, path_aware=path_aware)
        n += len(scns)
    return {name: round(t / n, 4) for name, t in totals.items()}


def _spearman(order_a: list[str], rank_b: dict[str, int]) -> float:
    """Spearman ρ between ranking implied by order_a and rank_b (both over the
    same policy names)."""
    names = list(order_a)
    a = np.array([i for i, _ in enumerate(names)], dtype=float)
    b = np.array([rank_b[n] for n in names], dtype=float)
    if np.std(a) == 0 or np.std(b) == 0:
        return 1.0
    return float(round(np.corrcoef(a, b)[0, 1], 4))


def _ranking(scores: dict[str, float]) -> list[str]:
    return [n for n, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]


def _forward_signal(engine: str, seeds: list[int], num_days: int) -> dict[str, float]:
    """Clean canary, free of the policy harness's drift/conditioning contamination:
    correlation between the EARLY-window return and the POST-window return on the
    probe, across scenarios. > 0 ⇒ early trend predicts the future ⇒ exploitable
    reflexive signal a memory model (7M.2) could learn; ≈ 0 ⇒ nothing to learn.
    Demeaned per scenario-type so it measures within-regime continuation, not the
    bull/bear drift both engines share."""
    early: dict[str, list[float]] = {}
    fwd: dict[str, list[float]] = {}
    for seed in seeds:
        for s in _scenarios(engine, seed, num_days):
            prices = s["price_paths"][_PROBE]["prices"]
            k = max(1, int(len(prices) * _DECISION_FRAC))
            if k + 1 >= len(prices) or prices[0] <= 0 or prices[k] <= 0:
                continue
            st = s["scenario_type"]
            early.setdefault(st, []).append(prices[k] / prices[0] - 1.0)
            fwd.setdefault(st, []).append(prices[-1] / prices[k] - 1.0)
    a, b = [], []
    for st in early:
        ea, fa = np.array(early[st]), np.array(fwd[st])
        a.extend((ea - ea.mean()).tolist())
        b.extend((fa - fa.mean()).tolist())
    a, b = np.array(a), np.array(b)
    if a.size < 3 or np.std(a) == 0 or np.std(b) == 0:
        return {"early_vs_forward_corr": 0.0, "n": int(a.size)}
    return {"early_vs_forward_corr": float(round(np.corrcoef(a, b)[0, 1], 4)), "n": int(a.size)}


def measure_lift(n_seeds: int = 100, num_days: int = 30) -> dict[str, Any]:
    seeds = list(range(n_seeds))
    regimes = {
        "montecarlo+terminal": ("montecarlo", False),
        "montecarlo+path_aware": ("montecarlo", True),
        "swarm+terminal": ("swarm", False),
        "swarm+path_aware": ("swarm", True),
    }
    out: dict[str, Any] = {"config": {"n_seeds": n_seeds, "num_days": num_days,
                                      "decision_frac": _DECISION_FRAC}, "regimes": {},
                           "forward_signal": {
                               "montecarlo": _forward_signal("montecarlo", seeds, num_days),
                               "swarm": _forward_signal("swarm", seeds, num_days),
                           }}
    baseline_rank: dict[str, int] | None = None
    for label, (engine, pa) in regimes.items():
        scores = _regime_scores(engine, pa, seeds, num_days)
        ranking = _ranking(scores)
        if baseline_rank is None:  # first regime is montecarlo+terminal
            baseline_rank = {n: i for i, n in enumerate(ranking)}
        out["regimes"][label] = {
            "scores": scores,
            "ranking": ranking,
            "discrimination": round(max(scores.values()) - min(scores.values()), 4),
            "trend_minus_hold": round(scores["trend_follower"] - scores["always_hold"], 4),
            "rank_corr_vs_baseline": _spearman(ranking, baseline_rank),
        }
    return out


def main() -> None:  # pragma: no cover - manual run
    import json

    print(json.dumps(measure_lift(), indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
