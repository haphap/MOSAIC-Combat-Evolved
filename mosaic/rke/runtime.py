"""Runtime output contracts and checkers for RKE-enabled agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class EvidenceLedgerItem:
    evidence_id: str
    source_type: str
    source_tool: str
    metric: str
    value: Any
    unit: str
    as_of: str
    freshness_days: int
    direction: str
    fallback: bool
    confidence_impact: str
    source_claim_ids: Sequence[str] = field(default_factory=tuple)
    evidence_type: str = ""
    metric_candidate_id: str = ""
    analysis_recipe_id: str = ""
    report_footprint_ids: Sequence[str] = field(default_factory=tuple)
    tool_proposal_id: str = ""

    def validate(self) -> tuple[str, ...]:
        failures: list[str] = []
        for name in (
            "evidence_id",
            "source_type",
            "source_tool",
            "metric",
            "unit",
            "as_of",
            "direction",
            "confidence_impact",
        ):
            if getattr(self, name) in {None, ""}:
                failures.append(f"{self.evidence_id or '<missing>'}: {name} required")
        if self.value is None:
            failures.append(f"{self.evidence_id}: value required")
        if self.freshness_days < 0:
            failures.append(f"{self.evidence_id}: freshness_days cannot be negative")
        if self.evidence_type == "research_prior_not_current_data":
            failures.append(
                f"{self.evidence_id}: research priors must use research_support_ledger"
            )
        if self.evidence_type and self.evidence_type not in {
            "current_tool_data",
            "tool_output",
            "source_grounded_claim",
        }:
            failures.append(f"{self.evidence_id}: unsupported evidence_type")
        if self.source_type in {"tool_output", "current_tool_data"}:
            if self.evidence_type and self.evidence_type != "current_tool_data":
                failures.append(
                    f"{self.evidence_id}: tool evidence_type must be current_tool_data"
                )
        if self.analysis_recipe_id and not self.metric_candidate_id:
            failures.append(
                f"{self.evidence_id}: analysis_recipe_id requires metric_candidate_id"
            )
        if self.tool_proposal_id and not self.metric_candidate_id:
            failures.append(
                f"{self.evidence_id}: tool_proposal_id requires metric_candidate_id"
            )
        return tuple(failures)


@dataclass(frozen=True)
class ResearchSupportItem:
    research_support_id: str
    evidence_type: str
    source_claim_ids: Sequence[str]
    viewpoint_cluster_ids: Sequence[str]
    source_weight_bucket: str
    method_pattern_ids: Sequence[str]
    allowed_use: str
    cannot_support_action_without_current_data: bool = True

    def validate(self) -> tuple[str, ...]:
        failures: list[str] = []
        for name in (
            "research_support_id",
            "evidence_type",
            "source_weight_bucket",
            "allowed_use",
        ):
            if getattr(self, name) in {None, ""}:
                failures.append(
                    f"{self.research_support_id or '<missing>'}: {name} required"
                )
        if self.evidence_type != "research_prior_not_current_data":
            failures.append(
                f"{self.research_support_id}: evidence_type must be research_prior_not_current_data"
            )
        if self.allowed_use != "prior_and_explanation_only":
            failures.append(
                f"{self.research_support_id}: allowed_use must be prior_and_explanation_only"
            )
        if self.cannot_support_action_without_current_data is not True:
            failures.append(
                f"{self.research_support_id}: cannot_support_action_without_current_data must be true"
            )
        return tuple(failures)


@dataclass(frozen=True)
class RuntimeInference:
    inference_id: str
    statement: str
    evidence_ids: Sequence[str]
    rule_ids: Sequence[str]
    source_claim_ids: Sequence[str] = field(default_factory=tuple)
    research_support_ids: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class RuntimeRecommendation:
    recommendation_id: str
    statement: str
    inference_ids: Sequence[str]
    confidence: float
    actionability: str


@dataclass(frozen=True)
class ProgressEvent:
    agent_id: str
    layer: str
    status: str
    tools_used: Sequence[str]
    evidence_count: int
    fallback_count: int
    missing_count: int
    schema_valid: bool
    confidence: float


@dataclass(frozen=True)
class RuntimeAgentOutput:
    evidence_ledger: Sequence[EvidenceLedgerItem]
    research_rule_ids_used: Sequence[str]
    source_claim_ids_used: Sequence[str]
    hypothesis_ids_used: Sequence[str]
    inferences: Sequence[RuntimeInference]
    recommendations: Sequence[RuntimeRecommendation]
    uncertainties: Sequence[str]
    confidence_components: Mapping[str, float]
    rule_aggregation_summary: Mapping[str, Any]
    downstream_handoff: Mapping[str, Any]
    progress_event: ProgressEvent
    research_support_ledger: Sequence[ResearchSupportItem] = field(default_factory=tuple)
    confidence_policy_trace: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeOutputCheckResult:
    accepted: bool
    reasons: tuple[str, ...]


V15_CONFIDENCE_COMPONENTS = (
    "data_confidence",
    "research_weight_confidence",
    "empirical_validation_confidence",
    "method_tool_confidence",
    "regime_match_confidence",
)


def _confidence_component_failures(
    components: Mapping[str, float],
) -> tuple[list[str], dict[str, float]]:
    failures: list[str] = []
    parsed: dict[str, float] = {}
    if "research_confidence" in components:
        failures.append(
            "confidence_components.research_confidence is legacy; use research_weight_confidence"
        )
    for component in V15_CONFIDENCE_COMPONENTS:
        if component not in components:
            failures.append(f"confidence_components.{component} required")
            continue
        try:
            value = float(components[component])
        except (TypeError, ValueError):
            failures.append(f"confidence_components.{component} must be numeric")
            continue
        if value < 0.0 or value > 1.0:
            failures.append(f"confidence_components.{component} must be between 0 and 1")
            continue
        parsed[component] = value
    return failures, parsed


def check_runtime_output(
    output: RuntimeAgentOutput,
    *,
    verified_claim_ids: set[str],
    confidence_cap: float,
    research_only: bool = False,
) -> RuntimeOutputCheckResult:
    """Validate evidence/inference/recommendation binding and actionability."""
    failures: list[str] = []
    evidence_by_id = {item.evidence_id: item for item in output.evidence_ledger}
    research_support_by_id = {
        item.research_support_id: item for item in output.research_support_ledger
    }
    inference_by_id = {item.inference_id: item for item in output.inferences}
    component_failures, confidence_components = _confidence_component_failures(
        output.confidence_components
    )
    failures.extend(component_failures)

    if output.progress_event.evidence_count != len(output.evidence_ledger):
        failures.append("progress_event evidence_count does not match evidence ledger")
    if not output.progress_event.schema_valid:
        failures.append("progress_event schema_valid is false")
    if not output.downstream_handoff.get("agent_id"):
        failures.append("downstream_handoff.agent_id required")
    if not output.downstream_handoff.get("summary"):
        failures.append("downstream_handoff.summary required")

    for evidence in output.evidence_ledger:
        failures.extend(evidence.validate())
        unverified = set(evidence.source_claim_ids) - verified_claim_ids
        if unverified:
            failures.append(
                f"{evidence.evidence_id}: unverified source_claim_ids {sorted(unverified)}"
            )

    for support in output.research_support_ledger:
        failures.extend(support.validate())
        unverified = set(support.source_claim_ids) - verified_claim_ids
        if unverified:
            failures.append(
                f"{support.research_support_id}: unverified source_claim_ids {sorted(unverified)}"
            )

    for inference in output.inferences:
        if not inference.evidence_ids and not inference.research_support_ids:
            failures.append(
                f"{inference.inference_id}: evidence_ids or research_support_ids required"
            )
        if not inference.rule_ids:
            failures.append(f"{inference.inference_id}: rule_ids required")
        missing_evidence = set(inference.evidence_ids) - set(evidence_by_id)
        if missing_evidence:
            failures.append(
                f"{inference.inference_id}: unknown evidence_ids {sorted(missing_evidence)}"
            )
        missing_support = set(inference.research_support_ids) - set(
            research_support_by_id
        )
        if missing_support:
            failures.append(
                f"{inference.inference_id}: unknown research_support_ids {sorted(missing_support)}"
            )
        if set(inference.rule_ids) - set(output.research_rule_ids_used):
            failures.append(
                f"{inference.inference_id}: rule_ids not declared in research_rule_ids_used"
            )

    independent_sources = {
        (item.source_type, item.source_tool, item.metric)
        for item in output.evidence_ledger
    }
    for recommendation in output.recommendations:
        if not recommendation.inference_ids:
            failures.append(
                f"{recommendation.recommendation_id}: inference_ids required"
            )
        missing_inferences = set(recommendation.inference_ids) - set(inference_by_id)
        if missing_inferences:
            failures.append(
                f"{recommendation.recommendation_id}: unknown inference_ids {sorted(missing_inferences)}"
            )
        if recommendation.confidence > confidence_cap:
            failures.append(
                f"{recommendation.recommendation_id}: confidence exceeds cap"
            )
        if recommendation.confidence >= 0.75 and len(independent_sources) < 2:
            failures.append(
                f"{recommendation.recommendation_id}: high confidence requires two independent evidence sources"
            )
        recommendation_inferences = [
            inference_by_id[inference_id]
            for inference_id in recommendation.inference_ids
            if inference_id in inference_by_id
        ]
        current_data_evidence_ids = {
            evidence_id
            for inference in recommendation_inferences
            for evidence_id in inference.evidence_ids
            if evidence_by_id.get(evidence_id)
            and evidence_by_id[evidence_id].source_type in {
                "tool_output",
                "current_tool_data",
            }
        }
        research_support_ids = {
            support_id
            for inference in recommendation_inferences
            for support_id in inference.research_support_ids
        }
        if len(confidence_components) == len(V15_CONFIDENCE_COMPONENTS):
            effective_data_confidence = confidence_components["data_confidence"]
            if research_support_ids and not current_data_evidence_ids:
                effective_data_confidence = min(effective_data_confidence, 0.50)
            max_confidence = min(
                effective_data_confidence,
                confidence_components["research_weight_confidence"],
                confidence_components["empirical_validation_confidence"],
                confidence_components["method_tool_confidence"],
                confidence_components["regime_match_confidence"],
                confidence_cap,
            )
            if recommendation.confidence > max_confidence:
                failures.append(
                    f"{recommendation.recommendation_id}: confidence exceeds v1.5 min-components cap"
                )
        if research_support_ids and not current_data_evidence_ids:
            if recommendation.actionability not in {"no_trade", "monitor_only"}:
                failures.append(
                    f"{recommendation.recommendation_id}: research support cannot be actionable without current tool data"
                )
        if research_only and recommendation.actionability not in {
            "no_trade",
            "monitor_only",
        }:
            failures.append(
                f"{recommendation.recommendation_id}: research-only output must not be actionable"
            )

    if output.rule_aggregation_summary.get("has_opposing_rules"):
        if not output.rule_aggregation_summary.get("conflict_objects"):
            failures.append("opposing rules require conflict_objects")
    if output.rule_aggregation_summary.get("correlated_rule_duplicate_count", 0) > 0:
        if not output.rule_aggregation_summary.get("deduped_rule_groups"):
            failures.append("correlated rule duplicates require deduped_rule_groups")

    return RuntimeOutputCheckResult(accepted=not failures, reasons=tuple(failures))
