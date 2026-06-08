"""Mutation and production-patch governance for RKE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from .p0 import LearnableParameter, validate_target_path


def _path_matches(pattern: str, path: str, *, allow_prefix: bool = False) -> bool:
    if pattern == path:
        return True
    if allow_prefix and "*" not in pattern:
        return path.startswith(f"{pattern.rstrip('/')}/")
    pattern_parts = pattern.strip("/").split("/")
    path_parts = path.strip("/").split("/")
    if len(pattern_parts) != len(path_parts):
        return False
    return all(p == "*" or p == actual for p, actual in zip(pattern_parts, path_parts))


@dataclass(frozen=True)
class EvolutionTargets:
    allowed_paths: Sequence[str]
    forbidden_paths: Sequence[str]

    def allows(self, target_path: str) -> bool:
        if any(
            _path_matches(pattern, target_path, allow_prefix=True)
            for pattern in self.forbidden_paths
        ):
            return False
        return any(_path_matches(pattern, target_path) for pattern in self.allowed_paths)


@dataclass(frozen=True)
class MutationProposal:
    mutation_id: str
    proposal_type: Literal[
        "parameter_update",
        "predicate_update",
        "confidence_cap_update",
        "source_weight_policy_update",
        "method_pattern_runtime_promotion",
        "metric_candidate_alias_merge",
        "registry_status_update",
        "research_prior_update",
    ]
    agent_id: str
    target_path: str
    operation: Literal["replace", "append", "tighten", "relax", "merge_alias"]
    old_value: Any
    new_value: Any
    source_experiment_id: str
    expected_effect: Mapping[str, Any]
    risk: str
    rollback_condition: Mapping[str, Any]


@dataclass(frozen=True)
class ProductionPatch:
    patch_id: str
    source_experiment_id: str
    operation: Literal["replace", "append", "tighten", "relax", "merge_alias"]
    target_path: str
    old_value: Any
    new_value: Any
    allowed_by_evolution_targets: bool
    validation_summary: Mapping[str, Any]
    rollback_rule: Mapping[str, Any]
    patch_type: str = ""


@dataclass(frozen=True)
class PatchValidationResult:
    accepted: bool
    reasons: tuple[str, ...]


RULE_PARAMETER_MARKER = "/learnable_parameters/"

V15_ALLOWED_EVOLUTION_PATHS: tuple[str, ...] = (
    "/research_weighting/source_profiles/*/weight_policy",
    "/research_weighting/viewpoint_profiles/*/weight_policy",
    "/research_weighting/method_profiles/*/priority_policy",
    "/weighted_research_retriever/ranking_weights/*",
    "/weighted_research_retriever/diversity_policy/*",
    "/metric_candidate_registry/*/aliases",
    "/metric_candidate_registry/*/priority_bucket",
    "/method_pattern_registry/*/status",
    "/tool_gap_registry/*/priority_bucket",
    "/data_acquisition_proposals/*/status",
    "/tool_design_proposals/*/status",
    "/analysis_recipe_registry/*/runtime_mode",
    "/analysis_recipe_registry/*/validation_status",
    "/prompt_ir/tool_contracts/candidate_tools/*",
    "/rule_packs/*/research_prior",
)

DEFAULT_ALLOWED_EVOLUTION_PATHS: tuple[str, ...] = (
    "/rule_packs/*/rules/*/learnable_parameters/*/value",
    "/rule_packs/*/rules/*/confidence_policy/*",
    "/rule_packs/*/rules/*/predicate/*",
    *V15_ALLOWED_EVOLUTION_PATHS,
)

DEFAULT_FORBIDDEN_EVOLUTION_PATHS: tuple[str, ...] = (
    "/role_contract",
    "/tool_contract/required_tools",
    "/prompt_ir/tool_contracts/required_tools",
    "/output_schema_ref",
    "/evidence_schema",
    "/guardrails",
    "/compliance_gates",
    "/validation_acceptance_standards",
    "/sector_score",
    "/portfolio_sizing",
    "/action_policy",
    "/prompt_ir/action_policy",
    "/report_intelligence/forecast_claims/*/claim_provenance",
    "/report_intelligence/analytical_footprints/*/source_grounded",
    "/source_claims/*/claim_provenance",
    "/evidence_ledger/current_tool_data",
)


def _target_path_failures(target_path: str) -> list[str]:
    if not target_path.startswith("/"):
        return ["target_path must be absolute"]
    if "//" in target_path or target_path.endswith("/"):
        return ["target_path is not canonical"]
    if RULE_PARAMETER_MARKER in target_path:
        target = validate_target_path(target_path)
        return [str(reason) for reason in target.get("reasons", ())] if not target["valid"] else []
    return []


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _patch_summary_section(
    patch: ProductionPatch | MutationProposal,
    name: str,
) -> Mapping[str, Any]:
    summary = (
        patch.validation_summary
        if isinstance(patch, ProductionPatch)
        else patch.expected_effect
    )
    return _as_mapping(_as_mapping(summary).get(name))


def _patch_evidence(patch: ProductionPatch | MutationProposal) -> Mapping[str, Any]:
    return _patch_summary_section(patch, "evidence") or _as_mapping(
        patch.validation_summary if isinstance(patch, ProductionPatch) else patch.expected_effect
    )


def _patch_constraints(patch: ProductionPatch | MutationProposal) -> Mapping[str, Any]:
    return _patch_summary_section(patch, "constraints")


def _v15_report_intelligence_patch_failures(
    patch: ProductionPatch | MutationProposal,
) -> list[str]:
    failures: list[str] = []
    evidence = _patch_evidence(patch)
    constraints = _patch_constraints(patch)
    if _path_matches(
        "/research_weighting/source_profiles/*/weight_policy",
        patch.target_path,
    ) or _path_matches(
        "/research_weighting/viewpoint_profiles/*/weight_policy",
        patch.target_path,
    ):
        n_effective = _as_float(evidence.get("n_effective"))
        fdr_passed = evidence.get("fdr_passed")
        validation_method = str(evidence.get("validation_method") or "")
        if n_effective is None or n_effective < 30:
            failures.append("source/viewpoint weight updates require n_effective >= 30")
        if fdr_passed is not True:
            failures.append("source/viewpoint weight updates require fdr_passed=true")
        if "overlap_adjusted" not in validation_method:
            failures.append(
                "source/viewpoint weight updates require overlap-adjusted validation evidence"
            )
        if constraints.get("pit_only") is not True:
            failures.append("source/viewpoint weight updates require constraints.pit_only=true")
        if constraints.get("requires_shadow_mode_first") is not True:
            failures.append(
                "source/viewpoint weight updates require shadow mode before runtime use"
            )
        max_multiplier = _as_float(constraints.get("max_multiplier"))
        new_value = _as_mapping(getattr(patch, "new_value", {}))
        weight_multiplier = _as_float(new_value.get("weight_multiplier"))
        if max_multiplier is None or max_multiplier > 1.5:
            failures.append("source/viewpoint weight updates require max_multiplier <= 1.5")
        if (
            weight_multiplier is not None
            and max_multiplier is not None
            and weight_multiplier > max_multiplier
        ):
            failures.append("new weight_multiplier exceeds constraints.max_multiplier")
    if _path_matches(
        "/analysis_recipe_registry/*/runtime_mode",
        patch.target_path,
    ):
        effective_n = _as_float(evidence.get("effective_n"))
        if getattr(patch, "new_value", None) not in {"shadow_only", "paper_trading"}:
            failures.append("analysis recipe runtime_mode promotion cannot target production")
        if evidence.get("tool_correctness_tests_passed") is not True:
            failures.append("method promotion requires tool_correctness_tests_passed=true")
        if str(evidence.get("pit_validation_status") or "") not in {
            "passed",
            "passed_with_caution",
        }:
            failures.append("method promotion requires PIT validation pass evidence")
        if effective_n is None or effective_n < 30:
            failures.append("method promotion requires effective_n >= 30")
        if constraints.get("no_direct_sizing") is not True:
            failures.append("method promotion requires constraints.no_direct_sizing=true")
        if constraints.get("requires_current_data") is not True:
            failures.append("method promotion requires constraints.requires_current_data=true")
        confidence_cap = _as_float(constraints.get("confidence_cap"))
        if confidence_cap is None or confidence_cap > 0.65:
            failures.append("method promotion requires confidence_cap <= 0.65")
    if _path_matches("/metric_candidate_registry/*/aliases", patch.target_path):
        if patch.operation != "merge_alias":
            failures.append("metric candidate alias updates require merge_alias operation")
        required_matches = (
            "raw_source_match",
            "unit_match",
            "frequency_match",
            "transformation_match",
        )
        for field in required_matches:
            if evidence.get(field) is not True:
                failures.append(f"metric candidate alias merge requires {field}=true")
        if evidence.get("human_review_required") is not True:
            failures.append("metric candidate alias merge requires human_review_required=true")
        if evidence.get("human_review_status") != "approved":
            failures.append("metric candidate alias merge requires approved human review")
        forbidden_if = set(str(item) for item in evidence.get("forbidden_if") or ())
        triggered = forbidden_if.intersection(
            {"proxy_only", "unit_mismatch", "frequency_mismatch", "unknown_raw_source"}
        )
        if triggered:
            failures.append(
                "metric candidate alias merge forbidden by evidence: "
                + ", ".join(sorted(triggered))
            )
    return failures


def validate_patch(
    patch: ProductionPatch | MutationProposal,
    *,
    current_registry: Mapping[str, Any],
    parameter_types: Mapping[str, LearnableParameter],
    evolution_targets: EvolutionTargets,
    valid_experiment_ids: set[str],
    allowed_promotion_states: set[str] | None = None,
) -> PatchValidationResult:
    """Validate a mutation/patch against master-plan patch rules."""
    allowed_promotion_states = allowed_promotion_states or {
        "validated",
        "paper_trading",
        "staged_production",
    }
    reasons: list[str] = []
    reasons.extend(_target_path_failures(patch.target_path))
    if not evolution_targets.allows(patch.target_path):
        reasons.append("target_path is outside allowed evolution targets or inside forbidden paths")
    if patch.target_path not in current_registry:
        reasons.append("target_path not found in current registry")
    elif current_registry[patch.target_path] != patch.old_value:
        reasons.append("old_value does not match current registry")
    parameter = parameter_types.get(patch.target_path)
    if parameter is None and RULE_PARAMETER_MARKER in patch.target_path:
        reasons.append("target_path has no registered parameter type")
    elif parameter is not None:
        reasons.extend(parameter.validate_value(patch.new_value))
    elif patch.operation == "replace" and type(patch.old_value) is not type(patch.new_value):
        reasons.append("new_value type must match old_value for non-parameter replace")
    elif patch.operation in {"append", "merge_alias"} and not isinstance(
        patch.old_value, (list, tuple)
    ):
        reasons.append("append/merge_alias requires list-like old_value")
    if patch.source_experiment_id not in valid_experiment_ids:
        reasons.append("source_experiment_id is not valid")
    rollback = (
        patch.rollback_rule if isinstance(patch, ProductionPatch) else patch.rollback_condition
    )
    if not rollback:
        reasons.append("rollback rule is required")
    if isinstance(patch, ProductionPatch):
        if not patch.allowed_by_evolution_targets:
            reasons.append("patch declares allowed_by_evolution_targets=false")
        promotion_state = str(patch.validation_summary.get("promotion_state") or "")
        if promotion_state not in allowed_promotion_states:
            reasons.append("promotion state does not allow patch")
    reasons.extend(_v15_report_intelligence_patch_failures(patch))
    return PatchValidationResult(accepted=not reasons, reasons=tuple(reasons))


def default_evolution_targets() -> EvolutionTargets:
    return EvolutionTargets(
        allowed_paths=DEFAULT_ALLOWED_EVOLUTION_PATHS,
        forbidden_paths=DEFAULT_FORBIDDEN_EVOLUTION_PATHS,
    )
