"""Prompt IR contracts for RKE-aware MOSAIC agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose
from typing import Any, Literal, Mapping, Sequence

from .governance import EvolutionTargets, default_evolution_targets
from .p0 import LearnableParameter, RulePack


@dataclass(frozen=True)
class ToolRequirement:
    name: str
    freshness_max_days: int
    required: bool = True
    metric_ids: Sequence[str] = field(default_factory=tuple)
    metric_candidate_ids: Sequence[str] = field(default_factory=tuple)
    analysis_recipe_ids: Sequence[str] = field(default_factory=tuple)
    pit_required_for_backtest: bool = False
    fallback_confidence_cap: float | None = None
    lineage: Mapping[str, Any] = field(default_factory=dict)


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


def _parameter_type_for_knobs(parameter: LearnableParameter) -> str:
    if parameter.type == "float":
        return "number"
    return parameter.type


def _normalize_horizon(days: tuple[int, int]) -> str:
    if days[0] == days[1]:
        return f"{days[0]}d"
    return f"{days[0]}-{days[1]}d"


def _research_knob_metadata(parameter: LearnableParameter) -> Mapping[str, Any]:
    metadata = parameter.metadata.get("research_knob")
    return metadata if isinstance(metadata, Mapping) else {}


def _rule_pack_path(rule_pack: RulePack, rule_id: str, parameter_name: str) -> str:
    return (
        f"/rule_packs/{rule_pack.rule_pack_id}/rules/{rule_id}"
        f"/learnable_parameters/{parameter_name}/value"
    )


def build_research_knobs_projection(
    contract: PromptIRContract,
    rule_packs: Sequence[RulePack],
    *,
    rke_promotion_gate_passed: bool = False,
) -> Mapping[str, Any]:
    """Project Prompt IR and rule-pack learnable parameters into research-knobs v1."""
    tool_by_name = {tool.name: tool for tool in contract.required_tools}
    evidence_registry: dict[str, dict[str, Any]] = {}
    raw_weights: dict[str, float] = {}
    mutation_targets: list[dict[str, Any]] = []
    prediction_targets: list[dict[str, Any]] = []
    lookbacks: dict[str, Any] = {}
    excluded_channels: list[str] = []

    for rule_pack in rule_packs:
        if rule_pack.agent_id != contract.agent_id:
            continue
        for rule in rule_pack.rules.values():
            prediction_targets.append(
                {
                    "id": rule.rule_id,
                    "target_variable": rule.metric_proxies[-1] if rule.metric_proxies else rule.rule_id,
                    "horizon": _normalize_horizon(rule.horizon_days),
                    "allowed_outputs": ["negative", "neutral", "positive"],
                }
            )
            for parameter_name, parameter in rule.learnable_parameters.items():
                path = _rule_pack_path(rule_pack, rule.rule_id, parameter_name)
                target: dict[str, Any] = {
                    "path": path,
                    "type": _parameter_type_for_knobs(parameter),
                }
                if parameter.min is not None:
                    target["min"] = parameter.min
                if parameter.max is not None:
                    target["max"] = parameter.max
                mutation_targets.append(target)

                if parameter_name.endswith("_window_days"):
                    lookbacks[parameter_name] = parameter.value

                knob = _research_knob_metadata(parameter)
                if knob.get("kind") != "evidence_channel_weight":
                    continue
                evidence_key = str(knob.get("evidence_key") or "")
                tool_name = str(knob.get("tool") or "")
                metric = str(knob.get("metric") or "")
                if not evidence_key:
                    continue
                if knob.get("requires_rke_promotion_gate") and not rke_promotion_gate_passed:
                    excluded_channels.append(evidence_key)
                    raw_weights[evidence_key] = 0.0
                    continue
                tool = tool_by_name.get(tool_name)
                evidence_registry[evidence_key] = {
                    "tool": tool_name,
                    "metric": metric,
                    "current_data": bool(knob.get("current_data", True)),
                    "primary": bool(knob.get("primary", False)),
                }
                if tool is not None and tool.fallback_confidence_cap is not None:
                    evidence_registry[evidence_key]["fallback_confidence_cap"] = (
                        tool.fallback_confidence_cap
                    )
                raw_weights[evidence_key] = float(parameter.value)

    total_weight = sum(value for value in raw_weights.values() if value > 0.0)
    evidence_weights = {
        key: (value / total_weight if total_weight else 0.0)
        for key, value in sorted(raw_weights.items())
    }
    required_evidence = [
        key
        for key, value in evidence_registry.items()
        if value.get("current_data") and value.get("primary")
    ]
    return {
        "schema_version": "research_knobs_v1",
        "layer": contract.layer,
        "agent": contract.agent_id,
        "research_scope": {
            "must_cover": list(contract.role_contract.may_decide),
            "must_not_cover": list(contract.role_contract.must_not_decide),
        },
        "prediction_targets": prediction_targets,
        "evidence_registry": evidence_registry,
        "evidence_weights": evidence_weights,
        "lookbacks": lookbacks,
        "thresholds": {},
        "confidence_caps": {
            "missing_current_data": {
                "cap": 0.55,
                "trigger": "missing_required_evidence",
                "enforcement": "code",
                "required_evidence": required_evidence,
            },
            "fallback_primary_tool": {
                "cap": min(
                    (tool.fallback_confidence_cap for tool in contract.required_tools if tool.fallback_confidence_cap is not None),
                    default=0.60,
                ),
                "trigger": "primary_tool_failed_or_fallback",
                "enforcement": "code",
                "required_evidence": required_evidence,
            },
        },
        "tie_breaks": [],
        "mutation_targets": mutation_targets,
        "projection_metadata": {
            "source": "prompt_ir_rule_pack_projection",
            "excluded_channels": excluded_channels,
        },
    }


def validate_research_knobs_projection(
    knobs: Mapping[str, Any],
    contract: PromptIRContract,
) -> tuple[str, ...]:
    """Validate the Prompt IR research-knobs projection contract."""
    failures: list[str] = []
    if knobs.get("schema_version") != "research_knobs_v1":
        failures.append("schema_version must be research_knobs_v1")
    if knobs.get("agent") != contract.agent_id:
        failures.append("agent must match Prompt IR agent_id")
    if knobs.get("layer") != contract.layer:
        failures.append("layer must match Prompt IR layer")

    registry = knobs.get("evidence_registry")
    weights = knobs.get("evidence_weights")
    if not isinstance(registry, Mapping) or not registry:
        failures.append("evidence_registry required")
        registry = {}
    if not isinstance(weights, Mapping) or not weights:
        failures.append("evidence_weights required")
        weights = {}
    if set(weights) - set(registry):
        failures.append("evidence_weights keys must exist in evidence_registry")
    tool_by_name = {tool.name: tool for tool in contract.required_tools}
    for key, entry in registry.items():
        if not isinstance(entry, Mapping):
            failures.append(f"{key}: evidence_registry entry must be object")
            continue
        tool = tool_by_name.get(str(entry.get("tool") or ""))
        if tool is None:
            failures.append(f"{key}: tool must exist in Prompt IR required_tools")
            continue
        metric = str(entry.get("metric") or "")
        if metric not in set(tool.metric_ids):
            failures.append(f"{key}: metric must exist in ToolRequirement.metric_ids")
    total = 0.0
    for key, value in weights.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            failures.append(f"{key}: evidence weight must be number")
            continue
        if value < 0.0:
            failures.append(f"{key}: evidence weight must be non-negative")
        total += float(value)
    if weights and not isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        failures.append("evidence_weights must sum to 1.0")

    for target in knobs.get("mutation_targets") or ():
        if not isinstance(target, Mapping):
            failures.append("mutation target must be object")
            continue
        path = str(target.get("path") or "")
        if path.startswith("/research_weighting/source_profiles/"):
            failures.append("evidence weights must not target report-source reliability paths")
        if not contract.evolution_targets.allows(path):
            failures.append(f"{path}: mutation target not allowed by Prompt IR governance")
    return tuple(failures)


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
            ToolRequirement(
                name="get_pboc_ops",
                freshness_max_days=1,
                required=True,
                metric_ids=("pboc_net_injection_7d",),
                metric_candidate_ids=("METRIC-CB-PBOC-NET-INJECTION-7D",),
                analysis_recipe_ids=("RECIPE-CB-LIQUIDITY-IMPULSE",),
                pit_required_for_backtest=True,
                fallback_confidence_cap=0.60,
                lineage={
                    "report_footprint_ids": ("AFP-CB-LIQUIDITY-IMPULSE",),
                    "tool_proposal_id": "TDP-CB-PBOC-OMO",
                },
            ),
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
        evolution_targets=default_evolution_targets(),
        guardrails=(
            "research_reports_are_prior_not_signal",
            "research_only_no_trade",
            "no_direct_production_promotion",
            "production_blocked_until_manual_gold_license_and_lockbox_gates_pass",
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
        if tool.fallback_confidence_cap is not None and tool.fallback_confidence_cap > 0.60:
            failures.append(f"{tool.name}: fallback_confidence_cap must be <= 0.60")
        if tool.pit_required_for_backtest and not tool.metric_candidate_ids:
            failures.append(
                f"{tool.name}: pit_required_for_backtest requires metric_candidate_ids"
            )
        if tool.metric_candidate_ids and not tool.metric_ids:
            failures.append(f"{tool.name}: metric_candidate_ids require metric_ids")
        if tool.analysis_recipe_ids and not tool.metric_candidate_ids:
            failures.append(
                f"{tool.name}: analysis_recipe_ids require metric_candidate_ids"
            )
        if tool.lineage:
            report_footprint_ids = tool.lineage.get("report_footprint_ids")
            if report_footprint_ids is not None and not isinstance(
                report_footprint_ids,
                (list, tuple),
            ):
                failures.append(
                    f"{tool.name}: lineage.report_footprint_ids must be a sequence"
                )
            if tool.lineage.get("tool_proposal_id") and not tool.metric_candidate_ids:
                failures.append(
                    f"{tool.name}: lineage.tool_proposal_id requires metric_candidate_ids"
                )
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
