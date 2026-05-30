"""Backtest signal model + state→signal builder (Plan §4.1 / Phase 8 刀2).

Ported from ETFAgents ``backtest/signals.py`` — slimmed to exactly what
``PaperTradingEngine.suggest_order_from_signal`` needs (``ticker`` /
``target_weight_pct`` / ``rating``) plus the full ``BacktestSignal`` dataclass
field contract (so ``BacktestSignal(**signal_dict)`` round-trips unchanged).

``build_state_backtest_signal`` keeps the original primary path: return a
signal dict the agent pipeline already attached to state
(``backtest_signal`` / ``portfolio_backtest_signal`` / ``trader_backtest_signal``).
The fallback synthesises a rating-only signal from the state's allocation text.

NOT ported (no caller in MOSAIC yet — the markdown/structured-plan extraction
that turns raw LLM text into triggers/risk rules belongs with the decision-layer
integration, depends on ``agents.schemas`` which MOSAIC lacks): the trader /
portfolio / candidate builders and their text-parsing helpers.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

_DEFAULT_TARGET_WEIGHT_PCT = {
    "BUY": 35.0,
    "OVERWEIGHT": 25.0,
    "HOLD": 15.0,
    "UNDERWEIGHT": 5.0,
    "SELL": 0.0,
}

_RATING_PATTERNS = (
    ("BUY", re.compile(r"(?:buy|买入)", re.IGNORECASE)),
    ("OVERWEIGHT", re.compile(r"(?:overweight|增持)", re.IGNORECASE)),
    ("HOLD", re.compile(r"(?:hold|持有)", re.IGNORECASE)),
    ("UNDERWEIGHT", re.compile(r"(?:underweight|减持)", re.IGNORECASE)),
    ("SELL", re.compile(r"(?:sell|卖出)", re.IGNORECASE)),
)


@dataclass
class BacktestTriggerRule:
    metric: str
    op: str
    threshold: float | tuple[float, float]
    action: str
    delta_pct: float | None = None
    target_weight_pct: float | None = None
    note: str = ""


@dataclass
class BacktestRiskRule:
    metric: str
    op: str
    threshold: float | tuple[float, float]
    action: str
    max_weight_pct: float | None = None
    min_weight_pct: float | None = None
    note: str = ""


@dataclass
class BacktestSignal:
    ticker: str
    decision_date: str
    source: str
    source_section: str
    rating: str
    target_weight_pct: float | None = None
    target_weight_min_pct: float | None = None
    target_weight_max_pct: float | None = None
    weight_source: str = "unknown"
    execution_delay: str = "next_open"
    starter_size_text: str = ""
    add_triggers: list[BacktestTriggerRule] = field(default_factory=list)
    reduce_triggers: list[BacktestTriggerRule] = field(default_factory=list)
    exit_triggers: list[BacktestTriggerRule] = field(default_factory=list)
    rebalance_triggers: list[BacktestTriggerRule] = field(default_factory=list)
    risk_rules: list[BacktestRiskRule] = field(default_factory=list)
    add_conditions: list[str] = field(default_factory=list)
    reduce_conditions: list[str] = field(default_factory=list)
    exit_conditions: list[str] = field(default_factory=list)
    rebalance_conditions: list[str] = field(default_factory=list)
    risk_controls: list[str] = field(default_factory=list)
    monitoring_points: list[str] = field(default_factory=list)
    signal_text_snapshot: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_rating(text: str) -> str:
    content = (text or "").strip()
    if not content:
        return "HOLD"
    if content.upper() in _DEFAULT_TARGET_WEIGHT_PCT:
        return content.upper()
    for rating, pattern in _RATING_PATTERNS:
        if pattern.search(content):
            return rating
    return "HOLD"


def _get_state_value(state: Mapping[str, Any], key: str, default: Any = None) -> Any:
    aliases = {
        "asset_of_interest": ("company_of_interest",),
        "final_allocation_decision": ("final_trade_decision",),
        "trader_allocation_plan": ("trader_investment_plan",),
        "research_allocation_plan": ("investment_plan",),
    }
    for candidate in (key, *aliases.get(key, ())):
        value = state.get(candidate)
        if value not in (None, ""):
            return value
    return default


def build_state_backtest_signal(
    state: Mapping[str, Any],
    *,
    default_ticker: str | None = None,
    default_trade_date: str | None = None,
) -> dict[str, Any]:
    """Return the agent pipeline's attached signal dict if present, else a
    rating-only fallback signal whose target weight defaults from the rating."""
    for key in ("backtest_signal", "portfolio_backtest_signal", "trader_backtest_signal"):
        existing = state.get(key)
        if isinstance(existing, Mapping) and existing:
            return dict(existing)

    ticker = default_ticker or str(_get_state_value(state, "asset_of_interest", "unknown") or "unknown")
    trade_date = str(_get_state_value(state, "trade_date", default_trade_date or ""))
    rating = _parse_rating(
        str(
            _get_state_value(state, "final_allocation_decision", "")
            or _get_state_value(state, "trader_allocation_plan", "")
            or _get_state_value(state, "research_allocation_plan", "")
        )
    )
    weight = _DEFAULT_TARGET_WEIGHT_PCT.get(rating)
    return BacktestSignal(
        ticker=ticker,
        decision_date=trade_date,
        source="state_fallback",
        source_section="rating_only",
        rating=rating,
        target_weight_pct=weight,
        target_weight_min_pct=weight,
        target_weight_max_pct=weight,
        weight_source="rating_default",
    ).to_dict()
