"""Experiment-governance checker for hardened RKE validation contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


EXPERIMENT_VALIDATION_REPORT_PATH = (
    "registry/experiment_checks/experiment_validation_report.json"
)
EXPERIMENT_PATH = "registry/experiments/central_bank_validation_experiment_v2.json"
PREREGISTRATION_PATH = (
    "registry/evaluation/pre_registration/central_bank_liquidity_preregistration.json"
)
FAMILY_PATH = (
    "registry/evaluation/experiment_family_registry/central_bank_liquidity_family.json"
)
OVERLAP_PATH = "registry/evaluation/overlap_correction/effective_n_overlap_policy.json"
COST_MODEL_PATH = "registry/evaluation/cost_model/cost_model_v1.json"
LOCKBOX_POLICY_PATH = "registry/evaluation/lockbox/lockbox_policy.json"
HARDENING_PATH = "registry/validation_hardening/central_bank_hardening_report.json"
STATISTICAL_SIGNIFICANCE_PATH = "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json"

ALLOWED_OVERLAP_METHODS = {
    "non_overlapping",
    "block_bootstrap",
    "stationary_bootstrap",
    "newey_west",
}
ALLOWED_REGIME_GATE_STATUSES = {
    "insufficient_data",
    "auxiliary_evidence",
    "regime_specific_gate",
}


@dataclass(frozen=True)
class ExperimentValidationRecord:
    check_id: str
    artifact_paths: Sequence[str]
    accepted: bool
    failures: Sequence[str]
    details: Mapping[str, Any]


@dataclass(frozen=True)
class ExperimentValidationReport:
    report_id: str
    records: Sequence[ExperimentValidationRecord]

    @property
    def accepted(self) -> bool:
        return all(record.accepted for record in self.records)

    @property
    def failure_count(self) -> int:
        return sum(len(record.failures) for record in self.records)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _record(
    check_id: str,
    artifact_paths: Sequence[str],
    failures: Sequence[str],
    details: Mapping[str, Any] | None = None,
) -> ExperimentValidationRecord:
    return ExperimentValidationRecord(
        check_id=check_id,
        artifact_paths=tuple(artifact_paths),
        accepted=not failures,
        failures=tuple(failures),
        details=dict(details or {}),
    )


def _read_json_object(
    path: Path, relative: str
) -> tuple[Mapping[str, Any] | None, str]:
    if not path.exists():
        return None, f"{relative}: missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"{relative} must contain valid JSON: {exc.msg}"
    if not isinstance(payload, Mapping):
        return None, f"{relative} must be object"
    return payload, ""


def _load_artifacts(
    root_path: Path,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    artifacts: dict[str, Mapping[str, Any]] = {}
    errors: dict[str, str] = {}
    for relative in (
        EXPERIMENT_PATH,
        PREREGISTRATION_PATH,
        FAMILY_PATH,
        OVERLAP_PATH,
        COST_MODEL_PATH,
        LOCKBOX_POLICY_PATH,
        HARDENING_PATH,
        STATISTICAL_SIGNIFICANCE_PATH,
    ):
        payload, error = _read_json_object(root_path / relative, relative)
        if error:
            errors[relative] = error
        elif payload is not None:
            artifacts[relative] = payload
    return artifacts, errors


def _artifact_failures(errors: Mapping[str, str], paths: Sequence[str]) -> list[str]:
    return [errors[path] for path in paths if path in errors]


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _registration_contract_record(
    artifacts: Mapping[str, Mapping[str, Any]],
    errors: Mapping[str, str],
) -> ExperimentValidationRecord:
    paths = (EXPERIMENT_PATH, PREREGISTRATION_PATH, FAMILY_PATH)
    failures = _artifact_failures(errors, paths)
    experiment = artifacts.get(EXPERIMENT_PATH, {})
    prereg = artifacts.get(PREREGISTRATION_PATH, {})
    family = artifacts.get(FAMILY_PATH, {})

    experiment_id = str(experiment.get("experiment_id") or "").strip()
    family_id = str(experiment.get("experiment_family_id") or "").strip()
    frozen_hash = str(experiment.get("frozen_spec_hash") or "").strip()
    if EXPERIMENT_PATH not in errors:
        if not experiment_id:
            failures.append("experiment_id required")
        if not family_id:
            failures.append("experiment_family_id required")
        if experiment.get("pre_registered") is not True:
            failures.append("experiment must be marked pre_registered")
        if not frozen_hash.startswith("sha256:"):
            failures.append("experiment frozen_spec_hash must start with sha256:")

    if PREREGISTRATION_PATH not in errors:
        if prereg.get("experiment_id") != experiment_id:
            failures.append("pre-registration experiment_id must match experiment")
        if prereg.get("frozen_spec_hash") != frozen_hash:
            failures.append("pre-registration frozen_spec_hash must match experiment")
        if prereg.get("protocol_status") != "frozen":
            failures.append("pre-registration protocol_status must be frozen")
        if prereg.get("freeze_required_before_results") is not True:
            failures.append("pre-registration must require freeze before results")
        if prereg.get("validation_results_seen_before_freeze") is not False:
            failures.append(
                "pre-registration must not see validation results before freeze"
            )

    if FAMILY_PATH not in errors:
        experiment_ids = tuple(str(item) for item in family.get("experiment_ids") or ())
        selected = str(family.get("selected_experiment_id") or "").strip()
        if family.get("family_id") != family_id:
            failures.append("experiment family_id must match experiment_family_id")
        if selected != experiment_id:
            failures.append("selected_experiment_id must match experiment_id")
        if experiment_id not in set(experiment_ids):
            failures.append("experiment_id must belong to experiment_ids")
        if family.get("correction_scope") != family_id:
            failures.append("family correction_scope must match family_id")

    return _record(
        "EXPERIMENT-REGISTRATION-CONTRACT",
        paths,
        failures,
        {
            "experiment_id": experiment_id,
            "experiment_family_id": family_id,
            "selected_experiment_id": family.get("selected_experiment_id"),
            "protocol_status": prereg.get("protocol_status"),
            "frozen_spec_hash": frozen_hash,
        },
    )


def _governance_policy_record(
    artifacts: Mapping[str, Mapping[str, Any]],
    errors: Mapping[str, str],
) -> ExperimentValidationRecord:
    paths = (
        EXPERIMENT_PATH,
        FAMILY_PATH,
        OVERLAP_PATH,
        COST_MODEL_PATH,
        LOCKBOX_POLICY_PATH,
    )
    failures = _artifact_failures(errors, paths)
    experiment = artifacts.get(EXPERIMENT_PATH, {})
    family = artifacts.get(FAMILY_PATH, {})
    overlap = artifacts.get(OVERLAP_PATH, {})
    cost = artifacts.get(COST_MODEL_PATH, {})
    lockbox = artifacts.get(LOCKBOX_POLICY_PATH, {})

    experiment_id = str(experiment.get("experiment_id") or "").strip()
    family_id = str(experiment.get("experiment_family_id") or "").strip()
    sampling = dict(experiment.get("sampling_design") or {})
    mtc = dict(experiment.get("multiple_testing_control") or {})
    acceptance = dict(experiment.get("acceptance_rule") or {})
    validation = dict(experiment.get("validation_design") or {})

    effective_n = _to_int(sampling.get("effective_n"))
    minimum_effective_n = _to_int(sampling.get("minimum_effective_n"))
    horizon_days = _to_int(sampling.get("horizon_days"))
    overlap_policy = str(sampling.get("overlap_policy") or "")
    if EXPERIMENT_PATH not in errors:
        if effective_n is None or minimum_effective_n is None:
            failures.append(
                "sampling_design effective_n and minimum_effective_n required"
            )
        elif effective_n < minimum_effective_n:
            failures.append("sampling_design effective_n below minimum_effective_n")
        if overlap_policy not in ALLOWED_OVERLAP_METHODS:
            failures.append("sampling_design overlap_policy unsupported")
        if acceptance.get("cost_model_required") is not True:
            failures.append("acceptance_rule cost_model_required must be true")
        if validation.get("walk_forward_required") is not True:
            failures.append("validation_design walk_forward_required must be true")
        if validation.get("lockbox_required_for_final_promotion") is not True:
            failures.append(
                "validation_design lockbox_required_for_final_promotion must be true"
            )

    adjusted_q = _to_float(mtc.get("adjusted_q_value"))
    max_fdr = _to_float(mtc.get("max_fdr"))
    if EXPERIMENT_PATH not in errors:
        if not str(mtc.get("method") or "").strip():
            failures.append("multiple_testing_control method required")
        if mtc.get("family_scope") != family_id:
            failures.append("multiple_testing_control family_scope must match family")
        if adjusted_q is None or max_fdr is None:
            failures.append(
                "multiple_testing_control adjusted_q_value/max_fdr required"
            )
        elif adjusted_q > max_fdr:
            failures.append("multiple_testing_control adjusted_q_value exceeds max_fdr")

    if FAMILY_PATH not in errors:
        if family.get("multiple_testing_method") != mtc.get("method"):
            failures.append("family multiple_testing_method must match experiment")
        if family.get("correction_scope") != family_id:
            failures.append("family correction_scope must match experiment family")
        family_adjusted = _to_float(family.get("adjusted_q_value"))
        family_max = _to_float(family.get("max_fdr"))
        if family_adjusted != adjusted_q or family_max != max_fdr:
            failures.append("family FDR thresholds must match experiment")

    if OVERLAP_PATH not in errors:
        accepted_methods = {
            str(item) for item in overlap.get("accepted_overlap_methods") or ()
        }
        if overlap.get("experiment_id") != experiment_id:
            failures.append("overlap policy experiment_id must match experiment")
        if overlap.get("gate_status") != "passed":
            failures.append("overlap policy gate_status must be passed")
        if overlap.get("overlap_policy") != overlap_policy:
            failures.append("overlap policy method must match experiment")
        if overlap_policy not in accepted_methods:
            failures.append("overlap policy method must be in accepted_overlap_methods")
        if _to_int(overlap.get("effective_n")) != effective_n:
            failures.append("overlap policy effective_n must match experiment")
        if _to_int(overlap.get("minimum_effective_n")) != minimum_effective_n:
            failures.append("overlap policy minimum_effective_n must match experiment")
        if _to_int(overlap.get("horizon_days")) != horizon_days:
            failures.append("overlap policy horizon_days must match experiment")

    primary_metric = str(acceptance.get("primary_metric") or "")
    net_alpha = _to_float(cost.get("net_alpha_after_cost"))
    min_net_alpha = _to_float(cost.get("min_net_alpha"))
    if COST_MODEL_PATH not in errors:
        if cost.get("experiment_id") != experiment_id:
            failures.append("cost model experiment_id must match experiment")
        if cost.get("primary_metric") != primary_metric:
            failures.append("cost model primary_metric must match experiment")
        if not str(cost.get("primary_metric") or "").startswith("net_alpha_after_cost"):
            failures.append("cost model primary_metric must be after-cost")
        if net_alpha is None or min_net_alpha is None:
            failures.append("cost model net_alpha_after_cost/min_net_alpha required")
        elif net_alpha <= min_net_alpha:
            failures.append("cost model net_alpha_after_cost must exceed min_net_alpha")
        if cost.get("calibration_must_not_degrade") is not True:
            failures.append("cost model calibration_must_not_degrade must be true")
        turnover = _to_float(cost.get("turnover_delta"))
        max_turnover = _to_float(cost.get("max_turnover_delta"))
        if (
            turnover is not None
            and max_turnover is not None
            and turnover > max_turnover
        ):
            failures.append("cost model turnover_delta exceeds max_turnover_delta")
        drawdown = _to_float(cost.get("drawdown_worsening"))
        max_drawdown = _to_float(cost.get("max_drawdown_worsening"))
        if (
            drawdown is not None
            and max_drawdown is not None
            and drawdown > max_drawdown
        ):
            failures.append(
                "cost model drawdown_worsening exceeds max_drawdown_worsening"
            )

    if LOCKBOX_POLICY_PATH not in errors:
        if lockbox.get("experiment_id") != experiment_id:
            failures.append("lockbox policy experiment_id must match experiment")
        if lockbox.get("walk_forward_required") is not True:
            failures.append("lockbox policy walk_forward_required must be true")
        if lockbox.get("lockbox_required_for_final_promotion") is not True:
            failures.append("lockbox policy final-promotion requirement must be true")
        if lockbox.get("direct_production_allowed") is not False:
            failures.append("lockbox policy must forbid direct production")

    return _record(
        "EXPERIMENT-GOVERNANCE-POLICIES",
        paths,
        failures,
        {
            "effective_n": effective_n,
            "minimum_effective_n": minimum_effective_n,
            "horizon_days": horizon_days,
            "overlap_policy": overlap_policy,
            "multiple_testing_method": mtc.get("method"),
            "adjusted_q_value": adjusted_q,
            "max_fdr": max_fdr,
            "primary_metric": primary_metric,
            "net_alpha_after_cost": net_alpha,
            "min_net_alpha": min_net_alpha,
            "lockbox_policy_status": lockbox.get("policy_status"),
        },
    )


def _validation_results_record(
    artifacts: Mapping[str, Mapping[str, Any]],
    errors: Mapping[str, str],
) -> ExperimentValidationRecord:
    paths = (EXPERIMENT_PATH, STATISTICAL_SIGNIFICANCE_PATH, HARDENING_PATH)
    failures = _artifact_failures(errors, paths)
    experiment = artifacts.get(EXPERIMENT_PATH, {})
    statistical = artifacts.get(STATISTICAL_SIGNIFICANCE_PATH, {})
    hardening = artifacts.get(HARDENING_PATH, {})

    experiment_id = str(experiment.get("experiment_id") or "").strip()
    acceptance = dict(experiment.get("acceptance_rule") or {})
    primary_metric = str(acceptance.get("primary_metric") or "")

    if STATISTICAL_SIGNIFICANCE_PATH not in errors:
        ci = dict(statistical.get("confidence_interval") or {})
        low = _to_float(ci.get("low"))
        effective_n = _to_int(statistical.get("effective_n"))
        minimum_effective_n = _to_int(statistical.get("minimum_effective_n"))
        if statistical.get("experiment_id") != experiment_id:
            failures.append("statistical report experiment_id must match experiment")
        if statistical.get("metric_name") != primary_metric:
            failures.append("statistical report metric_name must match primary_metric")
        if statistical.get("accepted") is not True:
            failures.append("statistical report accepted must be true")
        if statistical.get("failures"):
            failures.append("statistical report failures must be empty")
        if (
            effective_n is None
            or minimum_effective_n is None
            or effective_n < minimum_effective_n
        ):
            failures.append("statistical report effective_n below minimum")
        if low is None or low <= 0:
            failures.append(
                "statistical after-cost confidence interval must exclude zero"
            )

    if HARDENING_PATH not in errors:
        ablation = dict(hardening.get("ablation_checks") or {})
        if hardening.get("experiment_id") != experiment_id:
            failures.append("hardening report experiment_id must match experiment")
        if ablation.get("accepted") is not True:
            failures.append("hardening ablation checks must be accepted")
        if hardening.get("horizon_metric_failures"):
            failures.append("hardening horizon_metric_failures must be empty")
        if hardening.get("precision_failures"):
            failures.append("hardening precision_failures must be empty")
        if (
            hardening.get("statistical_significance_ref")
            != STATISTICAL_SIGNIFICANCE_PATH
        ):
            failures.append(
                "hardening statistical_significance_ref must point to report"
            )

    return _record(
        "EXPERIMENT-VALIDATION-RESULTS",
        paths,
        failures,
        {
            "experiment_id": experiment_id,
            "primary_metric": primary_metric,
            "statistical_accepted": statistical.get("accepted"),
            "confidence_interval_low": dict(
                statistical.get("confidence_interval") or {}
            ).get("low"),
            "deflated_sharpe_ratio": statistical.get("deflated_sharpe_ratio"),
            "ablation_accepted": dict(hardening.get("ablation_checks") or {}).get(
                "accepted"
            ),
        },
    )


def _regime_bucket_rules_record(
    artifacts: Mapping[str, Mapping[str, Any]],
    errors: Mapping[str, str],
) -> ExperimentValidationRecord:
    paths = (EXPERIMENT_PATH, HARDENING_PATH)
    failures = _artifact_failures(errors, paths)
    experiment = artifacts.get(EXPERIMENT_PATH, {})
    hardening = artifacts.get(HARDENING_PATH, {})
    validation = dict(experiment.get("validation_design") or {})
    pooling = dict(hardening.get("regime_partial_pooling") or {})
    effects = pooling.get("regime_effects") or {}

    if (
        EXPERIMENT_PATH not in errors
        and validation.get("partial_pooling_required") is not True
    ):
        failures.append("validation_design partial_pooling_required must be true")
    if HARDENING_PATH not in errors:
        if not isinstance(effects, Mapping) or not effects:
            failures.append("regime_partial_pooling regime_effects required")
            effects = {}
        for regime, raw_effect in effects.items():
            if not isinstance(raw_effect, Mapping):
                failures.append(f"{regime}: regime effect must be object")
                continue
            effective_n = _to_int(raw_effect.get("effective_n"))
            gate_status = str(raw_effect.get("gate_status") or "")
            raw_delta = _to_float(raw_effect.get("raw_delta"))
            shrunk_delta = _to_float(raw_effect.get("shrunk_delta"))
            if effective_n is None or effective_n < 0:
                failures.append(f"{regime}: effective_n must be non-negative integer")
            if gate_status not in ALLOWED_REGIME_GATE_STATUSES:
                failures.append(f"{regime}: gate_status unsupported")
            if raw_delta is None or shrunk_delta is None:
                failures.append(f"{regime}: raw_delta and shrunk_delta required")

    diagnostic_failures = tuple(str(item) for item in pooling.get("failures") or ())
    insufficient_bucket_count = sum(
        1
        for effect in effects.values()
        if isinstance(effect, Mapping)
        and effect.get("gate_status") == "insufficient_data"
    )
    return _record(
        "EXPERIMENT-REGIME-BUCKET-RULES",
        paths,
        failures,
        {
            "partial_pooling_required": validation.get("partial_pooling_required"),
            "regime_count": len(effects) if isinstance(effects, Mapping) else 0,
            "insufficient_bucket_count": insufficient_bucket_count,
            "diagnostic_failure_count": len(diagnostic_failures),
            "diagnostic_failures": diagnostic_failures,
            "allowed_gate_statuses": tuple(sorted(ALLOWED_REGIME_GATE_STATUSES)),
        },
    )


def build_experiment_validation_report(
    root: str | Path = ".",
) -> ExperimentValidationReport:
    root_path = Path(root)
    artifacts, errors = _load_artifacts(root_path)
    return ExperimentValidationReport(
        report_id="RKE-EXPERIMENT-VALIDATION-REPORT-20260606",
        records=(
            _registration_contract_record(artifacts, errors),
            _governance_policy_record(artifacts, errors),
            _validation_results_record(artifacts, errors),
            _regime_bucket_rules_record(artifacts, errors),
        ),
    )


def write_experiment_validation_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_experiment_validation_report(root_path)
    return _write_json(
        root_path / EXPERIMENT_VALIDATION_REPORT_PATH,
        {
            **asdict(report),
            "accepted": report.accepted,
            "failure_count": report.failure_count,
        },
    )
