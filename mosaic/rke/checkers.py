"""Unified checker entry points for RKE master-plan gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .governance import EvolutionTargets, ProductionPatch, validate_patch
from .p0 import (
    DataAvailabilityMatrix,
    LearnableParameter,
    ResearchSourceMetadata,
    RulePack,
    SourceGroundedClaim,
    ValidationExperimentV2,
    evaluate_validation_experiment,
    verify_source_grounded_claim,
)
from .runtime import RuntimeAgentOutput, check_runtime_output


@dataclass(frozen=True)
class CheckerResult:
    checker_name: str
    accepted: bool
    reasons: tuple[str, ...]
    metadata: Mapping[str, Any]


def check_source_metadata(source: ResearchSourceMetadata) -> CheckerResult:
    failures = source.gate_failures()
    return CheckerResult(
        checker_name="source_checker",
        accepted=not failures,
        reasons=failures,
        metadata={"source_id": source.source_id, "license_status": source.license_status},
    )


def check_claim_grounding(
    claim: SourceGroundedClaim,
    *,
    source_spans: Mapping[str, str],
    controlled_variables: set[str],
) -> CheckerResult:
    result = verify_source_grounded_claim(
        claim,
        source_spans=source_spans,
        controlled_variables=controlled_variables,
    )
    return CheckerResult(
        checker_name="claim_checker",
        accepted=result.accepted,
        reasons=result.reasons,
        metadata={
            "claim_id": claim.claim_id,
            "eligible_for_rule_compiler": result.eligible_for_rule_compiler,
        },
    )


def check_rule_pack(
    rule_pack: RulePack,
    *,
    data_matrix: DataAvailabilityMatrix,
    known_claim_ids: set[str],
    known_hypothesis_ids: set[str],
    production: bool = False,
) -> CheckerResult:
    failures = rule_pack.gate_failures(
        data_matrix=data_matrix,
        known_claim_ids=known_claim_ids,
        known_hypothesis_ids=known_hypothesis_ids,
        production=production,
    )
    return CheckerResult(
        checker_name="rule_pack_checker",
        accepted=not failures,
        reasons=failures,
        metadata={"rule_pack_id": rule_pack.rule_pack_id, "rule_count": len(rule_pack.rules)},
    )


def check_experiment(
    experiment: ValidationExperimentV2,
    *,
    data_matrix: DataAvailabilityMatrix,
) -> CheckerResult:
    decision = evaluate_validation_experiment(experiment, data_matrix=data_matrix)
    return CheckerResult(
        checker_name="experiment_checker",
        accepted=not decision.failure_reasons,
        reasons=decision.failure_reasons,
        metadata={
            "experiment_id": experiment.experiment_id,
            "status": decision.status,
            "paper_trading_allowed": decision.paper_trading_allowed,
            "production_allowed": decision.production_allowed,
        },
    )


def check_production_patch(
    patch: ProductionPatch,
    *,
    current_registry: Mapping[str, Any],
    parameter_types: Mapping[str, LearnableParameter],
    evolution_targets: EvolutionTargets,
    valid_experiment_ids: set[str],
) -> CheckerResult:
    result = validate_patch(
        patch,
        current_registry=current_registry,
        parameter_types=parameter_types,
        evolution_targets=evolution_targets,
        valid_experiment_ids=valid_experiment_ids,
    )
    return CheckerResult(
        checker_name="patch_checker",
        accepted=result.accepted,
        reasons=result.reasons,
        metadata={"target_path": patch.target_path, "source_experiment_id": patch.source_experiment_id},
    )


def check_agent_runtime_output(
    output: RuntimeAgentOutput,
    *,
    verified_claim_ids: set[str],
    confidence_cap: float,
    research_only: bool = False,
) -> CheckerResult:
    result = check_runtime_output(
        output,
        verified_claim_ids=verified_claim_ids,
        confidence_cap=confidence_cap,
        research_only=research_only,
    )
    return CheckerResult(
        checker_name="runtime_output_checker",
        accepted=result.accepted,
        reasons=result.reasons,
        metadata={
            "evidence_count": len(output.evidence_ledger),
            "recommendation_count": len(output.recommendations),
        },
    )
