"""Macro transmission roster and validation.

The v2 runtime deliberately has no Macro factor bundle or stance.  This module
keeps the historical import location for readers, but production callers may
only validate and preserve the ten independent accepted transmissions.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


MACRO_AGENTS = (
    "china",
    "us_economy",
    "eu_economy",
    "central_bank",
    "us_financial_conditions",
    "euro_area_financial_conditions",
    "commodities",
    "geopolitical",
    "market_breadth",
    "institutional_flow",
)
TOMBSTONED_MACRO_AGENTS = (
    "dollar",
    "yield_curve",
    "volatility",
    "emerging_markets",
    "news_sentiment",
)


class MacroAggregationRetiredError(RuntimeError):
    """Raised when a caller attempts to recreate a retired Macro stance."""


class MacroTransmissionRejectedError(ValueError):
    """Raised when the ten-slot accepted transmission set is invalid."""


def _validate_signal(agent: str, output: Mapping[str, Any]) -> None:
    direction = output.get("direction")
    strength = output.get("strength")
    confidence = output.get("confidence")
    if direction not in {"SUPPORTIVE", "NEUTRAL", "ADVERSE"}:
        raise MacroTransmissionRejectedError(f"invalid direction for {agent}: {direction!r}")
    if not isinstance(strength, int) or isinstance(strength, bool) or strength not in range(6):
        raise MacroTransmissionRejectedError(f"invalid strength for {agent}: {strength!r}")
    if direction == "NEUTRAL" and strength != 0:
        raise MacroTransmissionRejectedError(f"NEUTRAL requires strength=0 for {agent}")
    if direction != "NEUTRAL" and strength == 0:
        raise MacroTransmissionRejectedError(
            f"non-neutral direction requires strength in 1..5 for {agent}"
        )
    if not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)):
        raise MacroTransmissionRejectedError(f"invalid confidence for {agent}")
    if not 0 <= float(confidence) <= 1:
        raise MacroTransmissionRejectedError(f"confidence outside [0,1] for {agent}")


def validate_macro_transmissions(
    outputs: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Return the exact ten accepted slots in canonical order without aggregation."""
    if set(outputs) != set(MACRO_AGENTS):
        missing = sorted(set(MACRO_AGENTS) - set(outputs))
        extra = sorted(set(outputs) - set(MACRO_AGENTS))
        raise MacroTransmissionRejectedError(
            f"exact Macro roster required; missing={missing}, extra={extra}"
        )
    accepted: list[Mapping[str, Any]] = []
    for agent in MACRO_AGENTS:
        output = outputs[agent]
        identity = output.get("agent_id", output.get("agent"))
        if identity != agent:
            raise MacroTransmissionRejectedError(f"identity mismatch for {agent}")
        _validate_signal(agent, output)
        accepted.append(output)
    return tuple(accepted)


def aggregate_macro_transmissions(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Hard-stop the retired six-factor/stance API."""
    raise MacroAggregationRetiredError(
        "Macro aggregation is retired; consume ten accepted transmissions directly"
    )


__all__ = [
    "MACRO_AGENTS",
    "TOMBSTONED_MACRO_AGENTS",
    "MacroAggregationRetiredError",
    "MacroTransmissionRejectedError",
    "aggregate_macro_transmissions",
    "validate_macro_transmissions",
]
