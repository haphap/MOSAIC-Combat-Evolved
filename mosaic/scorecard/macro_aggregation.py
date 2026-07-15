"""Python mirror of the deterministic six-group Layer-1 aggregation."""

from __future__ import annotations

import math
from typing import Any, Mapping

MACRO_FACTOR_GROUPS: dict[str, tuple[str, ...]] = {
    "china_economy": ("china",),
    "us_economy": ("us_economy",),
    "policy_liquidity": ("central_bank",),
    "financial_conditions": ("dollar", "yield_curve"),
    "exogenous_real_shocks": ("commodities", "geopolitical"),
    "market_confirmation": ("volatility", "market_breadth", "institutional_flow"),
}
MACRO_AGENTS = tuple(agent for agents in MACRO_FACTOR_GROUPS.values() for agent in agents)
STANCE_THRESHOLD = 0.3


class MacroAggregationRejectedError(ValueError):
    pass


def _agent_signal(output: Mapping[str, Any]) -> float:
    direction = output.get("direction")
    sign = 1 if direction == "SUPPORTIVE" else (-1 if direction == "ADVERSE" else 0)
    strength = int(output.get("strength", 0))
    if direction == "NEUTRAL" and strength != 0:
        raise MacroAggregationRejectedError("NEUTRAL requires strength=0")
    if direction != "NEUTRAL" and strength not in range(1, 6):
        raise MacroAggregationRejectedError("non-neutral direction requires strength in 1..5")
    return sign * strength / 5.0


def aggregate_macro_transmissions(
    outputs: Mapping[str, Mapping[str, Any]],
    darwinian_weights: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    missing = [
        agent for agent in MACRO_AGENTS
        if agent not in outputs or outputs[agent].get("agent") != agent
    ]
    if missing:
        raise MacroAggregationRejectedError(
            f"formal macro aggregation requires all 10 accepted agents; missing: {', '.join(missing)}"
        )
    weights = darwinian_weights or {}
    agent_rows: list[dict[str, Any]] = []
    for group, agents in MACRO_FACTOR_GROUPS.items():
        for agent in agents:
            output = outputs[agent]
            raw_weight = weights.get(agent, 1.0)
            if isinstance(raw_weight, Mapping):
                raw_weight = raw_weight.get("weight", 1.0)
            weight = float(raw_weight)
            if not math.isfinite(weight) or weight <= 0:
                weight = 1.0
            confidence = float(output.get("confidence", 0.0))
            agent_rows.append(
                {
                    "agent": agent,
                    "group": group,
                    "signal": _agent_signal(output),
                    "confidence": confidence,
                    "darwinian_weight": weight,
                    "effective_reliability": confidence * weight,
                }
            )

    groups: list[dict[str, Any]] = []
    for group, agents in MACRO_FACTOR_GROUPS.items():
        members = [row for row in agent_rows if row["group"] == group]
        total_reliability = sum(row["effective_reliability"] for row in members)
        direction = (
            sum(row["effective_reliability"] * row["signal"] for row in members)
            / total_reliability
            if total_reliability > 0
            else 0.0
        )
        groups.append(
            {
                "group": group,
                "agent_count": len(agents),
                "direction": direction,
                "reliability": total_reliability / len(agents),
                "effective_weight": 0.0,
            }
        )
    denominator = sum(group["reliability"] for group in groups)
    for group in groups:
        group["effective_weight"] = (
            group["reliability"] / denominator if denominator > 0 else 1 / len(groups)
        )
    score = sum(group["effective_weight"] * group["direction"] for group in groups)
    stance = "BULLISH" if score > STANCE_THRESHOLD else (
        "BEARISH" if score < -STANCE_THRESHOLD else "NEUTRAL"
    )
    return {"score": score, "stance": stance, "agents": agent_rows, "groups": groups}


__all__ = [
    "MACRO_AGENTS",
    "MACRO_FACTOR_GROUPS",
    "STANCE_THRESHOLD",
    "MacroAggregationRejectedError",
    "aggregate_macro_transmissions",
]
