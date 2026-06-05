"""Phase 0 experiment-governance registry artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class BaselineVersionRegistry:
    registry_id: str
    agent_id: str
    baseline_version: str
    candidate_version: str
    baseline_prompt_ref: str
    candidate_prompt_ref: str
    baseline_output_ref: str
    candidate_output_ref: str
    historical_snapshot_refs: Sequence[str]


@dataclass(frozen=True)
class ExperimentFamilyRegistry:
    family_id: str
    agent_id: str
    rule_ids: Sequence[str]
    parameter_paths: Sequence[str]
    experiment_ids: Sequence[str]
    selected_experiment_id: str
    multiple_testing_method: str
    max_fdr: float
    adjusted_q_value: float
    correction_scope: str
    promotion_scope: str


@dataclass(frozen=True)
class PreRegistrationProtocol:
    protocol_id: str
    experiment_id: str
    registered_at: str
    frozen_spec_hash: str
    frozen_fields: Sequence[str]
    validation_results_seen_before_freeze: bool
    freeze_required_before_results: bool
    protocol_status: str


@dataclass(frozen=True)
class CostModelV1:
    model_id: str
    experiment_id: str
    primary_metric: str
    gross_alpha: float
    estimated_transaction_cost: float
    slippage: float
    net_alpha_after_cost: float
    min_net_alpha: float
    turnover_delta: float
    max_turnover_delta: float
    drawdown_worsening: float
    max_drawdown_worsening: float
    calibration_must_not_degrade: bool


@dataclass(frozen=True)
class EffectiveNOverlapPolicy:
    policy_id: str
    experiment_id: str
    signal_unit: str
    horizon_days: int
    nominal_n: int
    effective_n: int
    minimum_effective_n: int
    overlap_policy: str
    block_length_days: int | None
    accepted_overlap_methods: Sequence[str]
    gate_status: str


@dataclass(frozen=True)
class LockboxPolicyRegistry:
    policy_id: str
    experiment_id: str
    walk_forward_required: bool
    lockbox_required_for_final_promotion: bool
    lockbox_open_count: int
    lockbox_passed: bool
    direct_production_allowed: bool
    next_state_if_pass: str
    policy_status: str


@dataclass(frozen=True)
class ExperimentGovernanceBundle:
    baseline_versions: BaselineVersionRegistry
    experiment_family: ExperimentFamilyRegistry
    pre_registration: PreRegistrationProtocol
    cost_model: CostModelV1
    effective_n_overlap_policy: EffectiveNOverlapPolicy
    lockbox_policy: LockboxPolicyRegistry


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_experiment_governance_bundle(root: str | Path = ".") -> ExperimentGovernanceBundle:
    root_path = Path(root)
    experiment = _read_json(root_path / "registry/experiments/central_bank_validation_experiment_v2.json")
    acceptance = dict(experiment.get("acceptance_rule") or {})
    sampling = dict(experiment.get("sampling_design") or {})
    mtc = dict(experiment.get("multiple_testing_control") or {})
    validation = dict(experiment.get("validation_design") or {})
    promotion = dict(experiment.get("promotion_policy") or {})

    experiment_id = str(experiment["experiment_id"])
    agent_id = str(experiment["agent_id"])
    family_id = str(experiment["experiment_family_id"])
    baseline_version = str(experiment["baseline_version"])
    candidate_version = str(experiment["candidate_version"])

    cost_model = CostModelV1(
        model_id="COST-MODEL-V1-CB-LIQUIDITY-20260606",
        experiment_id=experiment_id,
        primary_metric=str(acceptance.get("primary_metric") or ""),
        gross_alpha=float(acceptance.get("gross_alpha") or 0.0),
        estimated_transaction_cost=float(acceptance.get("estimated_transaction_cost") or 0.0),
        slippage=float(acceptance.get("slippage") or 0.0),
        net_alpha_after_cost=float(acceptance.get("net_alpha_after_cost") or 0.0),
        min_net_alpha=float(acceptance.get("min_net_alpha") or 0.0),
        turnover_delta=float(acceptance.get("turnover_delta") or 0.0),
        max_turnover_delta=float(acceptance.get("turnover_not_worse_than") or 0.0),
        drawdown_worsening=float(acceptance.get("drawdown_worsening") or 0.0),
        max_drawdown_worsening=float(acceptance.get("max_drawdown_not_worse_than") or 0.0),
        calibration_must_not_degrade=bool(acceptance.get("calibration_must_not_degrade")),
    )
    return ExperimentGovernanceBundle(
        baseline_versions=BaselineVersionRegistry(
            registry_id="BASELINE-VERSIONS-CB-LIQUIDITY-20260606",
            agent_id=agent_id,
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            baseline_prompt_ref="registry/prompt_ir/macro.central_bank.json",
            candidate_prompt_ref="registry/prompt_ir/macro.central_bank.json",
            baseline_output_ref="registry/runtime_outputs/macro.central_bank.20260605.json",
            candidate_output_ref="registry/runtime_outputs/macro.central_bank.20260605.json",
            historical_snapshot_refs=("registry/monitoring/central_bank_paper_trading_report.json",),
        ),
        experiment_family=ExperimentFamilyRegistry(
            family_id=family_id,
            agent_id=agent_id,
            rule_ids=tuple(experiment.get("rule_ids") or ()),
            parameter_paths=tuple(experiment.get("parameter_paths") or ()),
            experiment_ids=(experiment_id,),
            selected_experiment_id=experiment_id,
            multiple_testing_method=str(mtc.get("method") or ""),
            max_fdr=float(mtc.get("max_fdr") or 0.0),
            adjusted_q_value=float(mtc.get("adjusted_q_value") or 1.0),
            correction_scope=str(mtc.get("family_scope") or family_id),
            promotion_scope="paper_trading_only_until_lockbox_and_manual_gates_pass",
        ),
        pre_registration=PreRegistrationProtocol(
            protocol_id="PREREG-CB-LIQUIDITY-20260606",
            experiment_id=experiment_id,
            registered_at=str(experiment.get("pre_registration_time") or ""),
            frozen_spec_hash=str(experiment.get("frozen_spec_hash") or ""),
            frozen_fields=(
                "rule_ids",
                "parameter_paths",
                "candidate_values",
                "primary_metric",
                "data_requirements",
                "sampling_design",
                "multiple_testing_control",
                "acceptance_rule",
                "validation_design",
            ),
            validation_results_seen_before_freeze=False,
            freeze_required_before_results=True,
            protocol_status="frozen",
        ),
        cost_model=cost_model,
        effective_n_overlap_policy=EffectiveNOverlapPolicy(
            policy_id="EFFECTIVE-N-OVERLAP-CB-LIQUIDITY-20260606",
            experiment_id=experiment_id,
            signal_unit=str(sampling.get("signal_unit") or ""),
            horizon_days=int(sampling.get("horizon_days") or 0),
            nominal_n=int(sampling.get("nominal_n") or 0),
            effective_n=int(sampling.get("effective_n") or 0),
            minimum_effective_n=int(sampling.get("minimum_effective_n") or 0),
            overlap_policy=str(sampling.get("overlap_policy") or ""),
            block_length_days=sampling.get("block_length_days"),
            accepted_overlap_methods=(
                "non_overlapping",
                "block_bootstrap",
                "stationary_bootstrap",
                "newey_west",
            ),
            gate_status=(
                "passed"
                if int(sampling.get("effective_n") or 0)
                >= int(sampling.get("minimum_effective_n") or 10**9)
                else "failed"
            ),
        ),
        lockbox_policy=LockboxPolicyRegistry(
            policy_id="LOCKBOX-POLICY-CB-LIQUIDITY-20260606",
            experiment_id=experiment_id,
            walk_forward_required=bool(validation.get("walk_forward_required")),
            lockbox_required_for_final_promotion=bool(
                validation.get("lockbox_required_for_final_promotion")
            ),
            lockbox_open_count=0,
            lockbox_passed=False,
            direct_production_allowed=bool(promotion.get("allow_direct_production")),
            next_state_if_pass=str(promotion.get("next_state_if_pass") or ""),
            policy_status="paper_trading_only",
        ),
    )


def validate_experiment_governance_bundle(bundle: ExperimentGovernanceBundle) -> tuple[str, ...]:
    failures: list[str] = []
    family = bundle.experiment_family
    prereg = bundle.pre_registration
    cost = bundle.cost_model
    overlap = bundle.effective_n_overlap_policy
    lockbox = bundle.lockbox_policy

    if family.selected_experiment_id not in set(family.experiment_ids):
        failures.append("selected experiment must belong to experiment family")
    if family.correction_scope != family.family_id:
        failures.append("multiple-testing correction scope must match family_id")
    if family.adjusted_q_value > family.max_fdr:
        failures.append("family adjusted q-value exceeds max_fdr")
    if prereg.validation_results_seen_before_freeze:
        failures.append("pre-registration saw validation results before freeze")
    if not prereg.frozen_spec_hash.startswith("sha256:"):
        failures.append("pre-registration frozen_spec_hash required")
    if cost.net_alpha_after_cost <= cost.min_net_alpha:
        failures.append("cost model net alpha below threshold")
    if not cost.primary_metric.startswith("net_alpha_after_cost"):
        failures.append("cost model primary metric must be after-cost")
    if overlap.overlap_policy not in set(overlap.accepted_overlap_methods):
        failures.append("overlap policy method is not accepted")
    if overlap.effective_n < overlap.minimum_effective_n:
        failures.append("effective_n below minimum_effective_n")
    if not lockbox.walk_forward_required:
        failures.append("walk-forward policy required")
    if not lockbox.lockbox_required_for_final_promotion:
        failures.append("lockbox policy required for final promotion")
    if lockbox.direct_production_allowed:
        failures.append("direct production promotion is forbidden")
    return tuple(failures)


def write_experiment_governance_registry(root: str | Path = ".") -> dict[str, str]:
    root_path = Path(root)
    bundle = build_experiment_governance_bundle(root_path)
    outputs = {
        "baseline_versions": root_path
        / "registry/evaluation/baselines/central_bank_baseline_versions.json",
        "experiment_family": root_path
        / "registry/evaluation/experiment_family_registry/central_bank_liquidity_family.json",
        "pre_registration": root_path
        / "registry/evaluation/pre_registration/central_bank_liquidity_preregistration.json",
        "cost_model": root_path / "registry/evaluation/cost_model/cost_model_v1.json",
        "effective_n_overlap_policy": root_path
        / "registry/evaluation/overlap_correction/effective_n_overlap_policy.json",
        "lockbox_policy": root_path / "registry/evaluation/lockbox/lockbox_policy.json",
    }
    for key, path in outputs.items():
        _write_json(path, asdict(getattr(bundle, key)))
    return {key: str(path) for key, path in outputs.items()}
