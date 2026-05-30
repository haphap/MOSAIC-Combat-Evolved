"""Phase 7M.1 — agent-to-agent swarm interaction engine (Plan §11.8.1).

The §11.8 reflexivity overlay is a *per-asset feedback kernel*: each asset's
return reacts only to its own trailing returns. It is NOT interacting agents.

This module adds the first genuinely interactive engine — an OASIS-lite swarm:
a population of representative actor *classes* share a **blackboard** (the
market environment). Each round, every actor reads the blackboard reflecting
the **prior round's aggregate behaviour** (last return, running sentiment, net
positioning), decides a demand, and writes it back; the aggregated net demand
moves the price and updates the blackboard for the next round. So actor B's
move at round t depends on what actors A…Z collectively did at t-1 — real
agent-to-agent interaction mediated by a shared environment, with emergent
herding / capitulation arising rather than being hand-coded.

Still pure numpy, deterministic (seed), no LLM — that's Tier-1; LLM personas +
memory are 7M.3 / 7M.2. **Opt-in**: the Monte-Carlo engine (§11.8) stays the
default; this runs only when ``mirofish.engine == 'swarm'`` (config / RPC / CLI).

Output is the same scenario dict shape as ``scenarios.generate_scenario`` (so
``score_recommendation`` + the trainer work unchanged) plus an ``emergence``
block (herding index, disagreement, sentiment) and ``engine='swarm'``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

import numpy as np

from mosaic.mirofish.scenarios import (
    ASSET_PARAMS,
    DEFAULT_START_PRICES,
    SCENARIO_TYPES,
    _final_state,
    _generate_events,
    _SCENARIO_MULT,
    _SCENARIO_NAME,
    _SCENARIO_PROB,
)

# Representative actor classes: population share + behavioural parameters.
# Each stands for many real participants (游资/北向/量化/散户/...), not literal
# agents — the swarm interaction is at the class level over the shared board.
ACTOR_CLASSES: dict[str, dict[str, float]] = {
    "momentum": {"share": 0.30, "trend": 1.0, "sentiment": 0.6, "contrarian": 0.0},
    "contrarian": {"share": 0.20, "trend": -0.8, "sentiment": -0.4, "contrarian": 0.0},
    "herding": {"share": 0.25, "trend": 0.3, "sentiment": 1.2, "contrarian": 0.0},
    "value": {"share": 0.15, "trend": 0.0, "sentiment": -0.2, "contrarian": 1.0},
    "noise": {"share": 0.10, "trend": 0.0, "sentiment": 0.0, "contrarian": 0.0},
}

_PRICE_IMPACT = 0.04   # net-demand → daily-return conversion (kept contractive)
_SENTIMENT_DECAY = 0.7  # running sentiment is an EWMA of recent returns
_MAX_DAILY = 0.10       # clamp a single day's swarm-driven return for stability


class SwarmEngine:
    """Interface so a real OASIS/CAMEL-AI adapter can slot in later (§11.8.1)."""

    def generate_all_scenarios(
        self,
        start_prices: Optional[Mapping[str, float]],
        num_days: int,
        seed: Optional[int],
        scenarios: Optional[list[str]],
    ) -> list[dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError


class LocalSwarmEngine(SwarmEngine):
    """Zero-dependency numpy swarm: actors interact via a shared blackboard."""

    def _simulate_ticker(
        self,
        ticker: str,
        start_price: float,
        scenario_type: str,
        num_days: int,
        rng: np.random.Generator,
    ) -> tuple[list[float], list[float], dict[str, float]]:
        params = ASSET_PARAMS.get(ticker, {"vol": 0.20, "drift": 0.05})
        daily_vol = params["vol"] / np.sqrt(252)
        # Scenario bias nudges the actor population's baseline lean.
        bias = _SCENARIO_MULT.get(scenario_type, 1.0) * 0.0015

        names = list(ACTOR_CLASSES)
        shares = np.array([ACTOR_CLASSES[n]["share"] for n in names])

        # Blackboard: the shared environment actors observe (prior round).
        last_return = 0.0
        sentiment = 0.0   # EWMA of returns = "crowd mood" on the board
        prices = [float(start_price)]
        eff_returns: list[float] = []
        herding_series: list[float] = []
        cur = start_price

        for _ in range(num_days):
            # Each actor class reads the SHARED board (last_return + sentiment),
            # not its own private history → genuine agent-to-agent coupling.
            demands = np.empty(len(names))
            for i, n in enumerate(names):
                a = ACTOR_CLASSES[n]
                cum_dev = cur / start_price - 1.0
                idio = rng.standard_normal() * daily_vol if n == "noise" else 0.0
                demands[i] = (
                    a["trend"] * last_return
                    + a["sentiment"] * sentiment
                    - a["contrarian"] * cum_dev * 0.10
                    + bias
                    + idio
                )
            net_demand = float(np.dot(shares, demands))
            # Disagreement / herding read off the share-weighted action split.
            pos = float(np.dot(shares, demands > 0))
            herding = abs(2 * pos - 1.0)  # 0 = split, 1 = unanimous
            herding_series.append(herding)

            r = float(np.clip(_PRICE_IMPACT * net_demand + rng.standard_normal() * daily_vol * 0.3, -_MAX_DAILY, _MAX_DAILY))
            cur *= (1 + r)
            prices.append(float(cur))
            eff_returns.append(r)
            # Update the board for the next round (this is the feedback write).
            last_return = r
            sentiment = _SENTIMENT_DECAY * sentiment + (1 - _SENTIMENT_DECAY) * np.sign(r) * min(abs(r) * 10, 1.0)

        metrics = {
            "herding_index": round(float(np.mean(herding_series)), 4) if herding_series else 0.0,
            "final_sentiment": round(float(sentiment), 4),
        }
        return prices, eff_returns, metrics

    def generate_scenario(
        self,
        scenario_type: str,
        start_prices: Optional[Mapping[str, float]] = None,
        num_days: int = 30,
        seed: Optional[int] = None,
        start_date: Optional[str] = None,
    ) -> dict[str, Any]:
        if scenario_type not in SCENARIO_TYPES:
            raise ValueError(f"scenario_type must be one of {SCENARIO_TYPES}, got {scenario_type!r}")
        prices = dict(start_prices or DEFAULT_START_PRICES)
        start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime(2024, 1, 1)
        rng = np.random.default_rng(seed)

        paths: dict[str, dict] = {}
        herd: list[float] = []
        for t in prices:
            series, eff, m = self._simulate_ticker(t, prices[t], scenario_type, num_days, rng)
            herd.append(m["herding_index"])
            paths[t] = {
                "ticker": t,
                "start_price": float(prices[t]),
                "prices": series,
                "cumulative_return": series[-1] / series[0] - 1,
                "volatility": float(np.std(eff) * np.sqrt(252)) if eff else 0.0,
            }

        ev_rng = np.random.default_rng(seed)
        return {
            "scenario_type": scenario_type,
            "scenario_name": _SCENARIO_NAME[scenario_type],
            "probability": _SCENARIO_PROB[scenario_type],
            "num_days": num_days,
            "engine": "swarm",
            "reflexive": True,  # the swarm IS reflexive by construction
            "price_paths": paths,
            "events": _generate_events(scenario_type, num_days, start, ev_rng),
            "final_state": _final_state(paths),
            "emergence": {
                "n_actor_classes": len(ACTOR_CLASSES),
                "herding_index": round(float(np.mean(herd)), 4) if herd else 0.0,
            },
        }

    def generate_all_scenarios(
        self,
        start_prices: Optional[Mapping[str, float]] = None,
        num_days: int = 30,
        seed: Optional[int] = None,
        scenarios: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        types = scenarios or list(SCENARIO_TYPES)
        out = []
        for i, st in enumerate(types):
            s = None if seed is None else seed + i
            out.append(self.generate_scenario(st, start_prices, num_days, s))
        return out
