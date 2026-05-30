"""A/B comparison: swarm vs montecarlo MiroFish engines (Plan §11.8.1 gate).

Both engines are *synthetic* — there is no real ground truth to score
predictive accuracy against. So we don't ask "which predicts better"; we ask
the falsifiable structural question that decides whether the swarm is worth its
complexity (7M.2+):

    Does the swarm produce return STRUCTURE that i.i.d. Monte-Carlo provably
    cannot — namely reflexive feedback signatures?

Metrics on each engine's daily returns (pooled over seeds × scenarios, per
asset then averaged):
  * ret_autocorr_lag1  — lag-1 autocorrelation of returns. The fingerprint of
    reflexive feedback (today's move conditions tomorrow's). MC draws returns
    i.i.d. → expected ≈ 0; a swarm with momentum/herding → materially nonzero.
  * vol_clustering     — lag-1 autocorrelation of SQUARED returns (ARCH effect:
    big moves cluster). MC ≈ 0; reflexive crowds → positive.
  * excess_kurtosis    — fat tails (Fisher; normal = 0). Crowd cascades → fatter.
  * cum_return_std     — cross-path dispersion of the cumulative return.

Pure numpy, deterministic given the seed list. Runnable: ``python -m
mosaic.mirofish.ab_compare``.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from mosaic.mirofish import generate_all_scenarios
from mosaic.mirofish.swarm import LocalSwarmEngine

_PROBE_TICKER = "000300.SH"


def _daily_returns(path: dict) -> np.ndarray:
    prices = np.asarray(path["prices"], dtype=float)
    return np.diff(prices) / prices[:-1]


def _autocorr_lag1(x: np.ndarray) -> float:
    if x.size < 3:
        return 0.0
    x = x - x.mean()
    denom = float(np.dot(x, x))
    if denom <= 1e-18:
        return 0.0
    return float(np.dot(x[:-1], x[1:]) / denom)


def _excess_kurtosis(x: np.ndarray) -> float:
    if x.size < 4:
        return 0.0
    m = x.mean()
    s2 = float(np.mean((x - m) ** 2))
    if s2 <= 1e-18:
        return 0.0
    return float(np.mean((x - m) ** 4) / (s2 * s2) - 3.0)


def _engine_metrics(paths_returns: list[np.ndarray], cum_returns: list[float]) -> dict[str, float]:
    if not paths_returns:
        return {"ret_autocorr_lag1": 0.0, "vol_clustering": 0.0, "excess_kurtosis": 0.0,
                "cum_return_std": 0.0, "n_paths": 0}
    ac = float(np.mean([_autocorr_lag1(r) for r in paths_returns]))
    vc = float(np.mean([_autocorr_lag1(r * r) for r in paths_returns]))
    ek = float(np.mean([_excess_kurtosis(r) for r in paths_returns]))
    return {
        "ret_autocorr_lag1": round(ac, 4),
        "vol_clustering": round(vc, 4),
        "excess_kurtosis": round(ek, 4),
        "cum_return_std": round(float(np.std(cum_returns)), 4),
        "n_paths": len(paths_returns),
    }


def _collect(engine: str, seeds: list[int], num_days: int, scenarios: Optional[list[str]]) -> dict[str, float]:
    swarm = LocalSwarmEngine()
    rets: list[np.ndarray] = []
    cum: list[float] = []
    for seed in seeds:
        if engine == "swarm":
            scns = swarm.generate_all_scenarios(num_days=num_days, seed=seed, scenarios=scenarios)
        else:
            scns = generate_all_scenarios(num_days=num_days, seed=seed, scenarios=scenarios)
        for s in scns:
            p = s["price_paths"].get(_PROBE_TICKER)
            if not p:
                continue
            rets.append(_daily_returns(p))
            cum.append(float(p["cumulative_return"]))
    return _engine_metrics(rets, cum)


def compare_engines(
    n_seeds: int = 100,
    num_days: int = 30,
    scenarios: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Run both engines over ``n_seeds`` × scenario types and return structural
    metrics + a verdict on the lag-1 autocorrelation gap (the decisive signal)."""
    seeds = list(range(n_seeds))
    mc = _collect("montecarlo", seeds, num_days, scenarios)
    sw = _collect("swarm", seeds, num_days, scenarios)
    return {
        "config": {"n_seeds": n_seeds, "num_days": num_days, "probe_ticker": _PROBE_TICKER},
        "montecarlo": mc,
        "swarm": sw,
        "autocorr_gap": round(sw["ret_autocorr_lag1"] - mc["ret_autocorr_lag1"], 4),
    }


def main() -> None:  # pragma: no cover - manual run
    import json

    print(json.dumps(compare_engines(), indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
