"""Role-matched primary outcome inventory for the ten v2 Macro agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from mosaic.scorecard.macro_aggregation import MACRO_AGENTS


# Kept only so old stored rows remain readable.  V2 primary contracts do not
# silently fall back to it when a role path is unavailable.
BENCHMARK_FALLBACK_LABEL = "legacy_benchmark_fallback_5d"


@dataclass(frozen=True)
class MacroLabelSpec:
    agent: str
    label_type: str
    data_source: str
    available_now: bool
    fallback_label: Optional[str]
    implementation_status: str
    primary_order: int = 0
    maturity_horizon_trading_days: int = 5
    rank_scope: str = ""
    outcome_contract_version: str = "macro_transmission_outcome_v2"

    @property
    def primary_ready(self) -> bool:
        return self.available_now and self.implementation_status == "implemented"

    def as_dict(self) -> dict:
        return asdict(self)


def _spec(agent: str, label: str, source: str) -> MacroLabelSpec:
    return MacroLabelSpec(
        agent=agent,
        label_type=label,
        data_source=source,
        available_now=True,
        fallback_label=None,
        implementation_status="implemented",
        rank_scope=f"macro_{agent}",
    )


MACRO_LABEL_INVENTORY: tuple[MacroLabelSpec, ...] = (
    _spec(
        "china",
        "china_macro_transmission_a_share_path_5d",
        "five equal PIT China transmission subpaths",
    ),
    _spec(
        "us_economy",
        "us_economic_cycle_a_share_path_5d",
        "four equal PIT US real-economy A-share transmission subpaths",
    ),
    _spec(
        "eu_economy",
        "eu_economic_cycle_a_share_path_5d",
        "four equal PIT EU27 real-economy A-share transmission subpaths",
    ),
    _spec(
        "central_bank",
        "pboc_rate_liquidity_a_share_path_5d",
        "four equal PIT PBOC/rates/liquidity/credit A-share subpaths",
    ),
    _spec(
        "us_financial_conditions",
        "us_financial_conditions_a_share_path_5d",
        "Fed, US curve, credit stress, and USD/CNY PIT subpaths",
    ),
    _spec(
        "euro_area_financial_conditions",
        "euro_area_financial_conditions_a_share_path_5d",
        "ECB, euro curve, bank credit, and EUR stress PIT subpaths",
    ),
    _spec(
        "commodities",
        "commodity_a_share_transmission_path_5d",
        "energy, industrial metals, gold, and agriculture PIT subpaths",
    ),
    _spec(
        "geopolitical",
        "geopolitical_transmission_a_share_path_5d",
        "verified affected-channel basket and equal-weight risk-appetite path",
    ),
    _spec(
        "market_breadth",
        "market_breadth_confirmation_5d",
        "50% breadth composite change plus 50% PIT equal-weight relative return",
    ),
    _spec(
        "institutional_flow",
        "institutional_flow_followthrough_5d",
        "50% deterministic flow continuation plus 50% top-minus-bottom flow basket",
    ),
)

if tuple(spec.agent for spec in MACRO_LABEL_INVENTORY) != MACRO_AGENTS:
    raise RuntimeError("Macro label inventory must match the canonical v2 roster")
if len({spec.label_type for spec in MACRO_LABEL_INVENTORY}) != len(MACRO_LABEL_INVENTORY):
    raise RuntimeError("Macro primary labels must be unique")


def list_macro_label_inventory() -> list[dict]:
    return [spec.as_dict() for spec in MACRO_LABEL_INVENTORY]


def primary_label_for_agent(
    agent: str, full_label_sources_enabled: bool = True
) -> Optional[MacroLabelSpec]:
    if not full_label_sources_enabled:
        return None
    return next((spec for spec in MACRO_LABEL_INVENTORY if spec.agent == agent), None)


__all__ = [
    "BENCHMARK_FALLBACK_LABEL",
    "MACRO_LABEL_INVENTORY",
    "MacroLabelSpec",
    "list_macro_label_inventory",
    "primary_label_for_agent",
]
