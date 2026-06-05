"""Mutation and production-patch governance for RKE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from .p0 import LearnableParameter, validate_target_path


def _path_matches(pattern: str, path: str) -> bool:
    if pattern == path:
        return True
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
        if any(_path_matches(pattern, target_path) for pattern in self.forbidden_paths):
            return False
        return any(_path_matches(pattern, target_path) for pattern in self.allowed_paths)


@dataclass(frozen=True)
class MutationProposal:
    mutation_id: str
    proposal_type: Literal["parameter_update", "predicate_update", "confidence_cap_update"]
    agent_id: str
    target_path: str
    operation: Literal["replace", "append", "tighten", "relax"]
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
    operation: Literal["replace", "append", "tighten", "relax"]
    target_path: str
    old_value: Any
    new_value: Any
    allowed_by_evolution_targets: bool
    validation_summary: Mapping[str, Any]
    rollback_rule: Mapping[str, Any]


@dataclass(frozen=True)
class PatchValidationResult:
    accepted: bool
    reasons: tuple[str, ...]


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
    target = validate_target_path(patch.target_path)
    if not target["valid"]:
        reasons.extend(str(reason) for reason in target["reasons"])
    if not evolution_targets.allows(patch.target_path):
        reasons.append("target_path is outside allowed evolution targets or inside forbidden paths")
    if patch.target_path not in current_registry:
        reasons.append("target_path not found in current registry")
    elif current_registry[patch.target_path] != patch.old_value:
        reasons.append("old_value does not match current registry")
    parameter = parameter_types.get(patch.target_path)
    if parameter is None:
        reasons.append("target_path has no registered parameter type")
    else:
        reasons.extend(parameter.validate_value(patch.new_value))
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
    return PatchValidationResult(accepted=not reasons, reasons=tuple(reasons))


def default_evolution_targets() -> EvolutionTargets:
    return EvolutionTargets(
        allowed_paths=(
            "/rule_packs/*/rules/*/learnable_parameters/*/value",
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
    )
