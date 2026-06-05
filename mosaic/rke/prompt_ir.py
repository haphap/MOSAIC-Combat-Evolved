"""Prompt IR contracts for RKE-aware MOSAIC agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

from .governance import EvolutionTargets


@dataclass(frozen=True)
class ToolRequirement:
    name: str
    freshness_max_days: int
    required: bool = True


@dataclass(frozen=True)
class FallbackTool:
    name: str
    confidence_cap: float


@dataclass(frozen=True)
class RoleContract:
    responsibility: str
    may_decide: Sequence[str]
    must_not_decide: Sequence[str]


@dataclass(frozen=True)
class PromptIRContract:
    agent_id: str
    layer: Literal["macro", "sector", "superinvestor", "decision"]
    cohort: str
    prompt_version: str
    role_contract: RoleContract
    required_tools: Sequence[ToolRequirement]
    fallback_tools: Sequence[FallbackTool]
    research_rule_pack_refs: Sequence[str]
    confidence_policy_ref: str
    rule_aggregation_policy_ref: str
    output_schema_ref: str
    progress_event_schema_ref: str
    handoff_schema_ref: str
    evolution_targets: EvolutionTargets
    guardrails: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class NormalizedToolOutput:
    tool_call_id: str
    tool_name: str
    metric: str
    value: Any
    unit: str
    as_of: str
    freshness_days: int
    lookback_window_days: int
    fallback: bool
    quality_flags: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class AgentRuntimeInput:
    agent_id: str
    runtime_date: str
    tool_outputs_normalized: Sequence[NormalizedToolOutput]
    active_rule_packs: Sequence[str]
    current_regime: Mapping[str, str]
    rule_validation_scores: Mapping[str, Mapping[str, Any]]


def build_central_bank_prompt_ir() -> PromptIRContract:
    """Build the central_bank Prompt IR contract required by the MVP."""
    return PromptIRContract(
        agent_id="macro.central_bank",
        layer="macro",
        cohort="cohort_default",
        prompt_version="0.3.2-rke",
        role_contract=RoleContract(
            responsibility="Generate central-bank and liquidity regime signals.",
            may_decide=(
                "liquidity_regime",
                "policy_window_signal",
                "confidence_cap",
            ),
            must_not_decide=(
                "final_portfolio_sizing",
                "single_stock_recommendation",
            ),
        ),
        required_tools=(
            ToolRequirement(name="get_pboc_ops", freshness_max_days=1, required=True),
        ),
        fallback_tools=(
            FallbackTool(name="liquidity_proxy_from_rates", confidence_cap=0.60),
        ),
        research_rule_pack_refs=("macro.central_bank.liquidity.v1",),
        confidence_policy_ref="confidence_policy.v1",
        rule_aggregation_policy_ref="rule_aggregation_policy.v1",
        output_schema_ref="agent_output_schema.v2",
        progress_event_schema_ref="progress_event.v1",
        handoff_schema_ref="downstream_handoff.v1",
        evolution_targets=EvolutionTargets(
            allowed_paths=(
                "/rule_packs/*/rules/*/learnable_parameters/*/value",
                "/rule_packs/*/rules/*/confidence_policy/*",
                "/rule_packs/*/rules/*/predicate/*",
            ),
            forbidden_paths=(
                "/role_contract",
                "/tool_contract/required_tools",
                "/output_schema_ref",
                "/evidence_schema",
                "/guardrails",
                "/compliance_gates",
                "/validation_acceptance_standards",
            ),
        ),
        guardrails=(
            "research_reports_are_prior_not_signal",
            "research_only_no_trade",
            "no_direct_production_promotion",
        ),
    )


def build_central_bank_runtime_input() -> AgentRuntimeInput:
    return AgentRuntimeInput(
        agent_id="macro.central_bank",
        runtime_date="2026-06-05",
        tool_outputs_normalized=(
            NormalizedToolOutput(
                tool_call_id="TC-CB-20260605-0001",
                tool_name="get_pboc_ops",
                metric="pboc_net_injection_7d",
                value=12500,
                unit="CNY 100mn",
                as_of="2026-06-05",
                freshness_days=0,
                lookback_window_days=7,
                fallback=False,
            ),
        ),
        active_rule_packs=("macro.central_bank.liquidity.v1",),
        current_regime={
            "risk_appetite": "neutral",
            "volatility": "normal",
            "liquidity": "supportive",
        },
        rule_validation_scores={
            "macro.central_bank.soft.001": {
                "validation_status": "paper_trading",
                "empirical_confidence_bin": "medium",
                "allowed_max_adjustment": 0.10,
            }
        },
    )


def validate_prompt_ir_contract(contract: PromptIRContract) -> tuple[str, ...]:
    failures: list[str] = []
    if not contract.agent_id.startswith(f"{contract.layer}."):
        failures.append("agent_id must start with layer")
    if not contract.cohort:
        failures.append("cohort required")
    if not contract.role_contract.responsibility:
        failures.append("role_contract.responsibility required")
    if contract.layer == "macro":
        required_forbidden_decisions = {"final_portfolio_sizing", "single_stock_recommendation"}
        missing = required_forbidden_decisions - set(contract.role_contract.must_not_decide)
        if missing:
            failures.append(f"macro role_contract must_not_decide missing {sorted(missing)}")
    required_tool_names = {tool.name for tool in contract.required_tools if tool.required}
    if "get_pboc_ops" not in required_tool_names and contract.agent_id == "macro.central_bank":
        failures.append("macro.central_bank requires get_pboc_ops")
    for tool in contract.required_tools:
        if tool.freshness_max_days < 0:
            failures.append(f"{tool.name}: freshness_max_days cannot be negative")
    for fallback in contract.fallback_tools:
        if fallback.confidence_cap > 0.60:
            failures.append(f"{fallback.name}: fallback confidence_cap must be <= 0.60")
    if not contract.research_rule_pack_refs:
        failures.append("research_rule_pack_refs required")
    for ref_name, value in (
        ("confidence_policy_ref", contract.confidence_policy_ref),
        ("rule_aggregation_policy_ref", contract.rule_aggregation_policy_ref),
        ("output_schema_ref", contract.output_schema_ref),
        ("progress_event_schema_ref", contract.progress_event_schema_ref),
        ("handoff_schema_ref", contract.handoff_schema_ref),
    ):
        if not value:
            failures.append(f"{ref_name} required")
    forbidden = set(contract.evolution_targets.forbidden_paths)
    for required_path in (
        "/role_contract",
        "/tool_contract/required_tools",
        "/output_schema_ref",
        "/evidence_schema",
        "/guardrails",
    ):
        if required_path not in forbidden:
            failures.append(f"{required_path} must be forbidden from automatic evolution")
    return tuple(failures)
