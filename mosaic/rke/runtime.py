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
        return tuple(failures)


@dataclass(frozen=True)
class RuntimeInference:
    inference_id: str
    statement: str
    evidence_ids: Sequence[str]
    rule_ids: Sequence[str]
    source_claim_ids: Sequence[str] = field(default_factory=tuple)


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


@dataclass(frozen=True)
class RuntimeOutputCheckResult:
    accepted: bool
    reasons: tuple[str, ...]


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
    inference_by_id = {item.inference_id: item for item in output.inferences}

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
            failures.append(f"{evidence.evidence_id}: unverified source_claim_ids {sorted(unverified)}")

    for inference in output.inferences:
        if not inference.evidence_ids:
            failures.append(f"{inference.inference_id}: evidence_ids required")
        if not inference.rule_ids:
            failures.append(f"{inference.inference_id}: rule_ids required")
        missing_evidence = set(inference.evidence_ids) - set(evidence_by_id)
        if missing_evidence:
            failures.append(f"{inference.inference_id}: unknown evidence_ids {sorted(missing_evidence)}")
        if set(inference.rule_ids) - set(output.research_rule_ids_used):
            failures.append(f"{inference.inference_id}: rule_ids not declared in research_rule_ids_used")

    independent_sources = {
        (item.source_type, item.source_tool, item.metric) for item in output.evidence_ledger
    }
    for recommendation in output.recommendations:
        if not recommendation.inference_ids:
            failures.append(f"{recommendation.recommendation_id}: inference_ids required")
        missing_inferences = set(recommendation.inference_ids) - set(inference_by_id)
        if missing_inferences:
            failures.append(
                f"{recommendation.recommendation_id}: unknown inference_ids {sorted(missing_inferences)}"
            )
        if recommendation.confidence > confidence_cap:
            failures.append(f"{recommendation.recommendation_id}: confidence exceeds cap")
        if recommendation.confidence >= 0.75 and len(independent_sources) < 2:
            failures.append(
                f"{recommendation.recommendation_id}: high confidence requires two independent evidence sources"
            )
        if research_only and recommendation.actionability not in {"no_trade", "monitor_only"}:
            failures.append(f"{recommendation.recommendation_id}: research-only output must not be actionable")

    if output.rule_aggregation_summary.get("has_opposing_rules"):
        if not output.rule_aggregation_summary.get("conflict_objects"):
            failures.append("opposing rules require conflict_objects")
    if output.rule_aggregation_summary.get("correlated_rule_duplicate_count", 0) > 0:
        if not output.rule_aggregation_summary.get("deduped_rule_groups"):
            failures.append("correlated rule duplicates require deduped_rule_groups")

    return RuntimeOutputCheckResult(accepted=not failures, reasons=tuple(failures))
