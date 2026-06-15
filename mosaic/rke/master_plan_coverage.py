"""Master-plan coverage audit for RKE implementation evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .completion_acceptance import (
    EXPECTED_COMPLETION_CRITERION_IDS,
    FINAL_ACCEPTANCE_REQUIREMENTS,
    MASTER_PLAN_ACCEPTANCE_SECTION,
    MASTER_PLAN_PATH,
)
from .registry_manifest import is_public_registry_artifact


MASTER_PLAN_COVERAGE_REPORT_PATH = (
    "registry/audits/rke_master_plan_coverage_report.json"
)
REPORT_INTELLIGENCE_PATCH_COVERAGE_REPORT_PATH = (
    "registry/report_intelligence/patch_v1_5_coverage_report.json"
)
EXPERIMENT_VALIDATION_REPORT_PATH = (
    "registry/experiment_checks/experiment_validation_report.json"
)
MVP_DELIVERABLES_SECTION = "16.3"
MVP_EXIT_CRITERIA_SECTION = "16.4"
EMPTY_EVIDENCE_ALLOWED_PATHS = frozenset(
    {
        # Empty means all gold-set reviews are complete.
        "registry/review_batches/gold_set_next_import_template.jsonl",
        "registry/review_batches/gold_set_full_import_template.jsonl",
        # Empty means all source-license reviews are complete.
        "registry/review_batches/source_license_next_import_template.jsonl",
    }
)

CoverageStatus = Literal["passed", "blocked", "missing"]


@dataclass(frozen=True)
class MasterPlanCoverageRecord:
    section_id: str
    requirement: str
    status: CoverageStatus
    evidence_paths: Sequence[str]
    blocker: str


@dataclass(frozen=True)
class MasterPlanCoverageReport:
    report_id: str
    master_plan_path: str
    mvp_deliverables_section: str
    mvp_exit_criteria_section: str
    final_acceptance_section: str
    coverage_complete: bool
    ready_for_broad_rollout: bool
    passed_count: int
    blocked_count: int
    missing_count: int
    records: Sequence[MasterPlanCoverageRecord]
    mvp_deliverables_ready: bool
    mvp_deliverables_passed_count: int
    mvp_deliverables_blocked_count: int
    mvp_deliverables_missing_count: int
    mvp_deliverable_records: Sequence[MasterPlanCoverageRecord]
    mvp_exit_ready: bool
    mvp_exit_passed_count: int
    mvp_exit_blocked_count: int
    mvp_exit_missing_count: int
    mvp_exit_records: Sequence[MasterPlanCoverageRecord]
    final_acceptance_ready: bool
    final_acceptance_passed_count: int
    final_acceptance_blocked_count: int
    final_acceptance_missing_count: int
    final_acceptance_records: Sequence[MasterPlanCoverageRecord]


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


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _exists(root_path: Path, relative: str) -> bool:
    path = root_path / relative
    return path.exists() and (
        path.stat().st_size > 0 or relative in EMPTY_EVIDENCE_ALLOWED_PATHS
    )


def _evidence_status(
    root_path: Path, evidence_paths: Sequence[str]
) -> tuple[bool, bool, str]:
    public_evidence_paths = [
        path for path in evidence_paths if is_public_registry_artifact(path)
    ]
    missing = [path for path in public_evidence_paths if not _exists(root_path, path)]
    if missing:
        return False, False, f"missing evidence: {', '.join(missing)}"
    malformed = _evidence_content_errors(root_path, public_evidence_paths)
    if malformed:
        return False, _evidence_errors_are_blocking_gate_failures(malformed), "; ".join(
            malformed
        )
    return True, False, ""


def _evidence_errors_are_blocking_gate_failures(errors: Sequence[str]) -> bool:
    return bool(errors) and all(
        " accepted must be true" in error
        or " blocker_count must be zero" in error
        or " blocked phases:" in error
        or " must be deferred_by_rollout" in error
        for error in errors
    )


def _all_exist(root_path: Path, evidence_paths: Sequence[str]) -> tuple[bool, str]:
    evidence_ok, _content_error, evidence_blocker = _evidence_status(
        root_path, evidence_paths
    )
    return evidence_ok, evidence_blocker


def _evidence_content_errors(
    root_path: Path, evidence_paths: Sequence[str]
) -> tuple[str, ...]:
    errors: list[str] = []
    for relative in evidence_paths:
        path = root_path / relative
        if relative.endswith(".json"):
            errors.extend(_json_object_errors(path, relative))
        elif relative.endswith(".jsonl"):
            errors.extend(_jsonl_object_errors(path, relative))
    return tuple(errors)


def _json_object_errors(path: Path, relative: str) -> tuple[str, ...]:
    try:
        payload = _read_json(path)
    except json.JSONDecodeError as exc:
        return (f"{relative} must contain valid JSON: {exc.msg}",)
    if not isinstance(payload, Mapping):
        return (f"{relative} must be object",)
    if relative == REPORT_INTELLIGENCE_PATCH_COVERAGE_REPORT_PATH:
        return _report_intelligence_patch_coverage_errors(payload, relative)
    return ()


def _report_intelligence_patch_coverage_errors(
    payload: Mapping[str, Any],
    relative: str,
) -> tuple[str, ...]:
    errors: list[str] = []
    if payload.get("accepted") is not True:
        errors.append(f"{relative} accepted must be true")
    try:
        blocker_count = int(payload.get("blocker_count") or 0)
    except (TypeError, ValueError):
        blocker_count = 1
    if blocker_count != 0:
        errors.append(f"{relative} blocker_count must be zero")
    phase_records = payload.get("phase_records")
    if not isinstance(phase_records, list | tuple):
        errors.append(f"{relative} phase_records must be list")
        return tuple(errors)
    valid_phase_records = [
        item for item in phase_records if isinstance(item, Mapping)
    ]
    if len(valid_phase_records) != len(phase_records):
        errors.append(f"{relative} phase_records rows must be objects")
    expected_phase_ids = set("ABCDEFGH")
    observed_phase_ids = {
        str(item.get("phase_id") or "") for item in valid_phase_records
    }
    if observed_phase_ids != expected_phase_ids:
        errors.append(f"{relative} phase_records must cover Phase A-H")
    blocked_ids = [
        str(item.get("phase_id") or "")
        for item in valid_phase_records
        if str(item.get("status") or "") == "blocked"
    ]
    if blocked_ids:
        errors.append(f"{relative} blocked phases: {', '.join(blocked_ids)}")
    rollout_mode = str(payload.get("current_rollout_mode") or "")
    if rollout_mode == "shadow_tooling":
        statuses = {
            str(item.get("phase_id") or ""): str(item.get("status") or "")
            for item in valid_phase_records
        }
        for phase_id in ("G", "H"):
            if statuses.get(phase_id) != "deferred_by_rollout":
                errors.append(
                    f"{relative} Phase {phase_id} must be deferred_by_rollout in shadow_tooling"
                )
    return tuple(errors)


def _jsonl_object_errors(path: Path, relative: str) -> tuple[str, ...]:
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                return (f"{relative} row {index} must contain valid JSON: {exc.msg}",)
            if not isinstance(payload, Mapping):
                return (f"{relative} row {index} must be object",)
    return ()


def _completion_by_id(root_path: Path) -> tuple[dict[str, Mapping[str, Any]], str]:
    path = root_path / "registry/audits/rke_completion_audit.json"
    if not path.exists():
        return {}, ""
    try:
        payload = _read_json(path)
    except json.JSONDecodeError as exc:
        return {}, f"completion audit must contain valid JSON: {exc.msg}"
    if not isinstance(payload, Mapping):
        return {}, "completion audit must be object"
    master_plan_path = payload.get("master_plan_path")
    if master_plan_path != MASTER_PLAN_PATH:
        return {}, f"completion audit master_plan_path must be {MASTER_PLAN_PATH}"
    acceptance_section = payload.get("acceptance_section")
    if str(acceptance_section) != MASTER_PLAN_ACCEPTANCE_SECTION:
        return (
            {},
            f"completion audit acceptance_section must be {MASTER_PLAN_ACCEPTANCE_SECTION}",
        )
    acceptance_count = payload.get("acceptance_criteria_count")
    try:
        parsed_acceptance_count = int(acceptance_count)
    except (TypeError, ValueError):
        return {}, "completion audit acceptance_criteria_count must be an integer"
    if parsed_acceptance_count != len(EXPECTED_COMPLETION_CRITERION_IDS):
        return (
            {},
            f"completion audit acceptance_criteria_count must be {len(EXPECTED_COMPLETION_CRITERION_IDS)}",
        )
    acceptance_requirements = payload.get("acceptance_requirements")
    expected_acceptance_requirements = [
        dict(item) for item in FINAL_ACCEPTANCE_REQUIREMENTS
    ]
    if acceptance_requirements != expected_acceptance_requirements:
        return (
            {},
            "completion audit acceptance_requirements must match master plan §22 C01-C12",
        )
    criteria = payload.get("criteria") or ()
    if not isinstance(criteria, list | tuple):
        return {}, "completion audit criteria must be list"
    completion: dict[str, Mapping[str, Any]] = {}
    invalid_rows: list[str] = []
    ids: list[str] = []
    for index, row in enumerate(criteria, 1):
        if not isinstance(row, Mapping):
            invalid_rows.append(str(index))
            continue
        criterion_id = str(row.get("criterion_id"))
        ids.append(criterion_id)
        if criterion_id in completion:
            return (
                completion,
                f"completion audit criterion_id duplicated: {criterion_id}",
            )
        completion[criterion_id] = row
    if invalid_rows:
        return (
            completion,
            f"completion audit criteria row must be object at row(s): {', '.join(invalid_rows)}",
        )
    expected = list(EXPECTED_COMPLETION_CRITERION_IDS)
    if ids != expected:
        missing = [
            criterion_id for criterion_id in expected if criterion_id not in completion
        ]
        unexpected = [
            criterion_id
            for criterion_id in ids
            if criterion_id not in EXPECTED_COMPLETION_CRITERION_IDS
        ]
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        if not details:
            details.append("criteria are out of order")
        return (
            completion,
            "completion audit criteria must exactly match C01-C12 in order ("
            + "; ".join(details)
            + ")",
        )
    return completion, ""


def _record(
    root_path: Path,
    *,
    section_id: str,
    requirement: str,
    evidence_paths: Sequence[str],
    status: CoverageStatus | None = None,
    blocker: str = "",
    blocked_if_evidence_content_error: bool = False,
) -> MasterPlanCoverageRecord:
    evidence_ok, evidence_content_error, evidence_blocker = _evidence_status(
        root_path, evidence_paths
    )
    final_status: CoverageStatus = status or ("passed" if evidence_ok else "missing")
    final_blocker = blocker
    if not evidence_ok:
        if final_status == "missing" and blocker:
            final_status = "missing"
        else:
            final_status = (
                "blocked"
                if evidence_content_error and blocked_if_evidence_content_error
                else "missing"
            )
        final_blocker = "; ".join(
            item for item in (blocker, evidence_blocker) if item
        )
    return MasterPlanCoverageRecord(
        section_id=section_id,
        requirement=requirement,
        status=final_status,
        evidence_paths=tuple(evidence_paths),
        blocker=final_blocker,
    )


def _completion_record(
    root_path: Path,
    completion: Mapping[str, Mapping[str, Any]],
    criterion_id: str,
    *,
    section_id: str,
    requirement: str,
    evidence_paths: Sequence[str],
    blocked_if_failed: bool = False,
    blocked_if_evidence_content_error: bool = False,
    completion_error: str = "",
) -> MasterPlanCoverageRecord:
    row = completion.get(criterion_id, {})
    passed = row.get("passed") is True
    blocker = completion_error or str(row.get("blocker") or "")
    if completion_error:
        status: CoverageStatus = "missing"
    elif passed:
        status: CoverageStatus = "passed"
    elif blocked_if_failed and blocker:
        status = "blocked"
    else:
        status = "missing"
        if not blocker:
            blocker = f"completion criterion {criterion_id} missing or not passed"
    return _record(
        root_path,
        section_id=section_id,
        requirement=requirement,
        evidence_paths=evidence_paths,
        status=status,
        blocker=blocker,
        blocked_if_evidence_content_error=blocked_if_evidence_content_error,
    )


def _combined_completion_record(
    root_path: Path,
    completion: Mapping[str, Mapping[str, Any]],
    criterion_ids: Sequence[str],
    *,
    section_id: str,
    requirement: str,
    evidence_paths: Sequence[str],
    blocked_if_failed: bool = False,
    completion_error: str = "",
) -> MasterPlanCoverageRecord:
    if completion_error:
        return _record(
            root_path,
            section_id=section_id,
            requirement=requirement,
            evidence_paths=evidence_paths,
            status="missing",
            blocker=completion_error,
        )

    missing_ids = [
        criterion_id for criterion_id in criterion_ids if criterion_id not in completion
    ]
    rows = [completion.get(criterion_id, {}) for criterion_id in criterion_ids]
    blockers = [str(row.get("blocker") or "") for row in rows if row.get("blocker")]
    if missing_ids:
        blockers.append(f"completion criteria missing: {', '.join(missing_ids)}")
    passed = not missing_ids and all(row.get("passed") is True for row in rows)
    if passed:
        status: CoverageStatus = "passed"
        blocker = ""
    elif blocked_if_failed and blockers:
        status = "blocked"
        blocker = "; ".join(blockers)
    else:
        status = "missing"
        blocker = "; ".join(blockers) or (
            "completion criteria not passed: " + ", ".join(criterion_ids)
        )
    return _record(
        root_path,
        section_id=section_id,
        requirement=requirement,
        evidence_paths=evidence_paths,
        status=status,
        blocker=blocker,
    )


def _promotion_by_id(root_path: Path) -> tuple[dict[str, Mapping[str, Any]], str]:
    path = root_path / "registry/promotion/rke_production_promotion_gate.json"
    if not path.exists():
        return {}, "production promotion gate missing"
    try:
        payload = _read_json(path)
    except json.JSONDecodeError as exc:
        return {}, f"production promotion gate must contain valid JSON: {exc.msg}"
    if not isinstance(payload, Mapping):
        return {}, "production promotion gate must be object"
    criteria = payload.get("criteria")
    if not isinstance(criteria, list | tuple):
        return {}, "production promotion gate criteria must be list"
    promotion: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(criteria, 1):
        if not isinstance(row, Mapping):
            return (
                promotion,
                f"production promotion gate criterion row {index} must be object",
            )
        criterion_id = str(row.get("criterion_id"))
        if criterion_id in promotion:
            return (
                promotion,
                f"production promotion gate criterion_id duplicated: {criterion_id}",
            )
        promotion[criterion_id] = row
    return promotion, ""


def _promotion_record(
    root_path: Path,
    promotion: Mapping[str, Mapping[str, Any]],
    criterion_id: str,
    *,
    section_id: str,
    requirement: str,
    evidence_paths: Sequence[str],
    blocked_if_failed: bool = False,
    promotion_error: str = "",
) -> MasterPlanCoverageRecord:
    row = promotion.get(criterion_id, {})
    passed = row.get("passed") is True
    blocker = promotion_error or str(row.get("blocker") or "")
    if promotion_error:
        status: CoverageStatus = "missing"
    elif passed:
        status = "passed"
    elif blocked_if_failed and blocker:
        status = "blocked"
    else:
        status = "missing"
        if not blocker:
            blocker = f"promotion criterion {criterion_id} missing or not passed"
    return _record(
        root_path,
        section_id=section_id,
        requirement=requirement,
        evidence_paths=evidence_paths,
        status=status,
        blocker=blocker,
    )


def _load_mapping_evidence(
    root_path: Path,
    relative: str,
    label: str,
) -> tuple[Mapping[str, Any] | None, str]:
    path = root_path / relative
    if not path.exists():
        return None, f"{label} missing"
    try:
        payload = _read_json(path)
    except json.JSONDecodeError as exc:
        return None, f"{label} must contain valid JSON: {exc.msg}"
    if not isinstance(payload, Mapping):
        return None, f"{label} must be object"
    return payload, ""


def _content_record(
    root_path: Path,
    *,
    section_id: str,
    requirement: str,
    evidence_paths: Sequence[str],
    passed: bool,
    blocker: str,
    blocked_if_failed: bool = False,
) -> MasterPlanCoverageRecord:
    if passed:
        status: CoverageStatus = "passed"
        final_blocker = ""
    elif blocked_if_failed and blocker:
        status = "blocked"
        final_blocker = blocker
    else:
        status = "missing"
        final_blocker = blocker or "content gate not passed"
    return _record(
        root_path,
        section_id=section_id,
        requirement=requirement,
        evidence_paths=evidence_paths,
        status=status,
        blocker=final_blocker,
    )


def _mvp_deliverable_records(
    root_path: Path,
    completion: Mapping[str, Mapping[str, Any]],
    *,
    completion_error: str,
) -> tuple[MasterPlanCoverageRecord, ...]:
    return (
        _completion_record(
            root_path,
            completion,
            "C03",
            section_id="MVP-D1",
            requirement="Data Availability Matrix for central_bank metrics.",
            evidence_paths=(
                "registry/data_availability/central_bank_data_availability.json",
                "registry/data_availability/macro_expansion_data_availability.json",
            ),
            completion_error=completion_error,
        ),
        _completion_record(
            root_path,
            completion,
            "C02",
            section_id="MVP-D2",
            requirement="Claim extraction gold set for 50 documents / 100 claims.",
            evidence_paths=(
                "registry/gold_sets/tushare_research_reports.review_template.jsonl",
                "registry/gold_sets/tushare_research_reports.review_summary.json",
                "registry/gold_sets/tushare_research_reports.review_import_report.json",
            ),
            blocked_if_failed=True,
            completion_error=completion_error,
        ),
        _claim_checker_record(root_path),
        _rule_pack_checker_record(
            root_path,
            section_id="MVP-D4",
            requirement="One central_bank rule pack.",
            evidence_paths=(
                "registry/rule_packs/macro.central_bank.liquidity.v1.json",
                "registry/rule_checks/rule_pack_validation_report.json",
            ),
        ),
        _record(
            root_path,
            section_id="MVP-D5",
            requirement="One parameter prior family.",
            evidence_paths=(
                "registry/parameter_priors/central_bank_parameter_priors.jsonl",
            ),
        ),
        _experiment_validation_checker_record(
            root_path,
            section_id="MVP-D6",
            requirement="One pre-registered validation experiment family.",
            evidence_paths=(
                "registry/evaluation/experiment_family_registry/central_bank_liquidity_family.json",
                "registry/evaluation/pre_registration/central_bank_liquidity_preregistration.json",
                "registry/experiments/central_bank_validation_experiment_v2.json",
                EXPERIMENT_VALIDATION_REPORT_PATH,
            ),
        ),
        _completion_record(
            root_path,
            completion,
            "C04",
            section_id="MVP-D7",
            requirement="Effective N / overlap / multiple testing / cost-aware report.",
            evidence_paths=(
                "registry/experiments/central_bank_validation_experiment_v2.json",
                "registry/validation_hardening/central_bank_hardening_report.json",
                "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json",
                EXPERIMENT_VALIDATION_REPORT_PATH,
            ),
            completion_error=completion_error,
        ),
        _completion_record(
            root_path,
            completion,
            "C05",
            section_id="MVP-D8",
            requirement="Runtime rule aggregation prototype.",
            evidence_paths=(
                "registry/runtime_outputs/macro.central_bank.20260605.json",
                "schemas/rule_aggregation_policy.schema.yaml",
            ),
            completion_error=completion_error,
        ),
        _completion_record(
            root_path,
            completion,
            "C06",
            section_id="MVP-D9",
            requirement="Confidence function v1 implementation.",
            evidence_paths=(
                "schemas/confidence_policy.schema.yaml",
                "registry/runtime_outputs/macro.central_bank.20260605.json",
            ),
            completion_error=completion_error,
        ),
        _combined_completion_record(
            root_path,
            completion,
            ("C09", "C12"),
            section_id="MVP-D10",
            requirement="Paper trading output and audit viewer.",
            evidence_paths=(
                "registry/monitoring/central_bank_paper_trading_report.json",
                "registry/audits/central_bank_mvp_audit_view.json",
                "registry/audits/central_bank_mvp_audit_view.md",
            ),
            completion_error=completion_error,
        ),
    )


def _mvp_exit_records(
    root_path: Path,
    completion: Mapping[str, Mapping[str, Any]],
    *,
    completion_error: str,
) -> tuple[MasterPlanCoverageRecord, ...]:
    promotion, promotion_error = _promotion_by_id(root_path)
    return (
        _completion_record(
            root_path,
            completion,
            "C02",
            section_id="MVP-E01",
            requirement="Claim extraction gold set precision reaches the manual threshold.",
            evidence_paths=(
                "registry/gold_sets/tushare_research_reports.review_summary.json",
                "registry/audits/rke_completion_audit.json",
            ),
            blocked_if_failed=True,
            completion_error=completion_error,
        ),
        _completion_record(
            root_path,
            completion,
            "C03",
            section_id="MVP-E02",
            requirement="All production candidate proxies have PIT data.",
            evidence_paths=(
                "registry/data_availability/central_bank_data_availability.json",
                "registry/rule_packs/macro.central_bank.liquidity.v1.json",
            ),
            completion_error=completion_error,
        ),
        _pre_registered_experiment_record(root_path),
        _effective_n_record(root_path),
        _overlap_correction_record(root_path),
        _multiple_testing_record(root_path),
        _after_cost_significance_record(root_path),
        _walk_forward_record(root_path),
        _lockbox_no_misuse_record(root_path),
        _promotion_record(
            root_path,
            promotion,
            "PG06",
            section_id="MVP-E10",
            requirement="Paper trading plan is ready.",
            evidence_paths=(
                "registry/promotion/rke_production_promotion_gate.json",
                "registry/monitoring/central_bank_paper_trading_report.json",
            ),
            promotion_error=promotion_error,
        ),
        _promotion_record(
            root_path,
            promotion,
            "PG10",
            section_id="MVP-E11",
            requirement="Direct production promotion is forbidden.",
            evidence_paths=(
                "registry/promotion/rke_production_promotion_gate.json",
                "registry/patches/central_bank_paper_trading_patch.json",
            ),
            promotion_error=promotion_error,
        ),
        _combined_completion_record(
            root_path,
            completion,
            ("C06", "C09"),
            section_id="MVP-E12",
            requirement="Confidence function and actionability threshold are enforced.",
            evidence_paths=(
                "schemas/confidence_policy.schema.yaml",
                "registry/runtime_outputs/macro.central_bank.20260605.json",
                "registry/monitoring/central_bank_paper_trading_report.json",
            ),
            completion_error=completion_error,
        ),
        _completion_record(
            root_path,
            completion,
            "C07",
            section_id="MVP-E13",
            requirement="Research-only no-trade rule is enforced.",
            evidence_paths=(
                "registry/prompt_ir/macro.central_bank.json",
                "registry/runtime_outputs/sector.semiconductor.demo.20260605.json",
                "registry/prompt_checks/prompt_asset_validation_report.json",
            ),
            completion_error=completion_error,
        ),
    )


def _pre_registered_experiment_record(root_path: Path) -> MasterPlanCoverageRecord:
    relative = "registry/experiments/central_bank_validation_experiment_v2.json"
    experiment, error = _load_mapping_evidence(
        root_path, relative, "validation experiment"
    )
    passed = not error and bool(experiment and experiment.get("pre_registered") is True)
    blocker = error or "validation experiment is not marked pre_registered"
    return _content_record(
        root_path,
        section_id="MVP-E03",
        requirement="Validation experiment is pre-registered.",
        evidence_paths=(
            "registry/evaluation/pre_registration/central_bank_liquidity_preregistration.json",
            relative,
            EXPERIMENT_VALIDATION_REPORT_PATH,
        ),
        passed=passed,
        blocker=blocker,
    )


def _claim_checker_record(root_path: Path) -> MasterPlanCoverageRecord:
    evidence_paths = (
        "schemas/source_grounded_claim.schema.json",
        "registry/schemas/rke_schema_validation_report.json",
        "registry/claim_checks/claim_variable_validation_report.json",
        "registry/claim_checks/claim_grounding_validation_report.json",
    )
    missing_failures: list[str] = []
    gate_failures: list[str] = []
    for relative, label in (
        (
            "registry/schemas/rke_schema_validation_report.json",
            "schema validation report",
        ),
        (
            "registry/claim_checks/claim_variable_validation_report.json",
            "claim variable validation report",
        ),
        (
            "registry/claim_checks/claim_grounding_validation_report.json",
            "claim grounding validation report",
        ),
    ):
        report, error = _load_mapping_evidence(root_path, relative, label)
        if error:
            missing_failures.append(error)
        elif report is not None and report.get("accepted") is not True:
            gate_failures.append(f"{label} accepted must be true")
    failures = [*missing_failures, *gate_failures]
    return _content_record(
        root_path,
        section_id="MVP-D3",
        requirement="Source-grounded claim schema and verifier.",
        evidence_paths=evidence_paths,
        passed=not failures,
        blocker="; ".join(failures),
        blocked_if_failed=bool(gate_failures) and not missing_failures,
    )


def _rule_pack_checker_record(
    root_path: Path,
    *,
    section_id: str,
    requirement: str,
    evidence_paths: tuple[str, ...],
) -> MasterPlanCoverageRecord:
    failures: list[str] = []
    report, error = _load_mapping_evidence(
        root_path,
        "registry/rule_checks/rule_pack_validation_report.json",
        "rule pack validation report",
    )
    if error:
        failures.append(error)
    elif report is not None and report.get("accepted") is not True:
        failures.append("rule pack validation report accepted must be true")
    return _content_record(
        root_path,
        section_id=section_id,
        requirement=requirement,
        evidence_paths=evidence_paths,
        passed=not failures,
        blocker="; ".join(failures),
    )


def _experiment_validation_checker_record(
    root_path: Path,
    *,
    section_id: str,
    requirement: str,
    evidence_paths: tuple[str, ...],
) -> MasterPlanCoverageRecord:
    failures: list[str] = []
    report, error = _load_mapping_evidence(
        root_path,
        EXPERIMENT_VALIDATION_REPORT_PATH,
        "experiment validation report",
    )
    if error:
        failures.append(error)
    elif report is not None:
        records = report.get("records") or ()
        if report.get("accepted") is not True:
            failures.append("experiment validation report accepted must be true")
        if not isinstance(records, list | tuple) or len(records) < 4:
            failures.append("experiment validation report must include all four checks")
    return _content_record(
        root_path,
        section_id=section_id,
        requirement=requirement,
        evidence_paths=evidence_paths,
        passed=not failures,
        blocker="; ".join(failures),
    )


def _effective_n_record(root_path: Path) -> MasterPlanCoverageRecord:
    relative = "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json"
    report, error = _load_mapping_evidence(
        root_path, relative, "statistical significance report"
    )
    passed = False
    blocker = error
    if not error and report is not None:
        effective_n = _to_float(report.get("effective_n"))
        minimum = _to_float(report.get("minimum_effective_n"))
        passed = (
            effective_n is not None and minimum is not None and effective_n >= minimum
        )
        if not passed:
            blocker = f"effective_n below threshold: {effective_n} < {minimum}"
    return _content_record(
        root_path,
        section_id="MVP-E04",
        requirement="effective_n >= threshold.",
        evidence_paths=(relative, EXPERIMENT_VALIDATION_REPORT_PATH),
        passed=passed,
        blocker=blocker,
    )


def _overlap_correction_record(root_path: Path) -> MasterPlanCoverageRecord:
    relative = "registry/experiments/central_bank_validation_experiment_v2.json"
    experiment, error = _load_mapping_evidence(
        root_path, relative, "validation experiment"
    )
    sampling = dict(experiment.get("sampling_design") or {}) if experiment else {}
    policy = str(sampling.get("overlap_policy") or "")
    passed = not error and policy in {
        "block_bootstrap",
        "stationary_bootstrap",
        "newey_west",
        "non_overlapping",
    }
    blocker = error or "overlap correction policy missing or unsupported"
    return _content_record(
        root_path,
        section_id="MVP-E05",
        requirement="Overlapping windows are corrected.",
        evidence_paths=(
            relative,
            "registry/evaluation/overlap_correction/effective_n_overlap_policy.json",
            EXPERIMENT_VALIDATION_REPORT_PATH,
        ),
        passed=passed,
        blocker=blocker,
    )


def _multiple_testing_record(root_path: Path) -> MasterPlanCoverageRecord:
    relative = "registry/experiments/central_bank_validation_experiment_v2.json"
    experiment, error = _load_mapping_evidence(
        root_path, relative, "validation experiment"
    )
    mtc = dict(experiment.get("multiple_testing_control") or {}) if experiment else {}
    adjusted = _to_float(mtc.get("adjusted_q_value"))
    max_fdr = _to_float(mtc.get("max_fdr"))
    passed = (
        not error
        and mtc.get("method") == "benjamini_hochberg_fdr"
        and adjusted is not None
        and max_fdr is not None
        and adjusted <= max_fdr
    )
    blocker = error or "Benjamini-Hochberg FDR correction missing or above threshold"
    return _content_record(
        root_path,
        section_id="MVP-E06",
        requirement="Multiple testing is corrected.",
        evidence_paths=(
            relative,
            "registry/evaluation/experiment_family_registry/central_bank_liquidity_family.json",
            EXPERIMENT_VALIDATION_REPORT_PATH,
        ),
        passed=passed,
        blocker=blocker,
    )


def _after_cost_significance_record(root_path: Path) -> MasterPlanCoverageRecord:
    relative = "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json"
    report, error = _load_mapping_evidence(
        root_path, relative, "statistical significance report"
    )
    ci = dict(report.get("confidence_interval") or {}) if report else {}
    mean_effect = _to_float(report.get("mean_effect")) if report else None
    low = _to_float(ci.get("low"))
    passed = (
        not error
        and report is not None
        and report.get("accepted") is True
        and mean_effect is not None
        and mean_effect > 0
        and low is not None
        and low > 0
    )
    blocker = error or "after-cost metric is not positive with CI excluding zero"
    return _content_record(
        root_path,
        section_id="MVP-E07",
        requirement="After-cost metric is positive and confidence interval excludes zero.",
        evidence_paths=(relative, EXPERIMENT_VALIDATION_REPORT_PATH),
        passed=passed,
        blocker=blocker,
    )


def _walk_forward_record(root_path: Path) -> MasterPlanCoverageRecord:
    relative = "registry/patches/central_bank_paper_trading_patch.json"
    patch, error = _load_mapping_evidence(root_path, relative, "paper-trading patch")
    validation = dict(patch.get("validation_summary") or {}) if patch else {}
    passed = not error and validation.get("walk_forward_passed") is True
    blocker = error or "walk_forward_passed is not true"
    return _content_record(
        root_path,
        section_id="MVP-E08",
        requirement="Walk-forward validation passed.",
        evidence_paths=(
            "registry/experiments/central_bank_validation_experiment_v2.json",
            relative,
            EXPERIMENT_VALIDATION_REPORT_PATH,
        ),
        passed=passed,
        blocker=blocker,
    )


def _lockbox_no_misuse_record(root_path: Path) -> MasterPlanCoverageRecord:
    policy_relative = "registry/evaluation/lockbox/lockbox_policy.json"
    review_relative = "registry/lockbox/central_bank_lockbox_review.json"
    policy, policy_error = _load_mapping_evidence(
        root_path, policy_relative, "lockbox policy"
    )
    review, review_error = _load_mapping_evidence(
        root_path, review_relative, "lockbox review"
    )
    errors = [error for error in (policy_error, review_error) if error]
    policy_open_count = _to_float(policy.get("lockbox_open_count")) if policy else None
    review_open_count = _to_float(review.get("open_count")) if review else None
    passed = (
        not errors
        and policy_open_count is not None
        and review_open_count is not None
        and policy_open_count <= 1
        and review_open_count <= 1
    )
    blocker = "; ".join(errors) or "lockbox open_count exceeds one-time-use policy"
    return _content_record(
        root_path,
        section_id="MVP-E09",
        requirement="No lockbox misuse.",
        evidence_paths=(
            policy_relative,
            review_relative,
            EXPERIMENT_VALIDATION_REPORT_PATH,
        ),
        passed=passed,
        blocker=blocker,
    )


def build_master_plan_coverage_report(
    root: str | Path = ".",
) -> MasterPlanCoverageReport:
    root_path = Path(root)
    completion, completion_error = _completion_by_id(root_path)
    records: list[MasterPlanCoverageRecord] = []

    records.extend(
        [
            _record(
                root_path,
                section_id="Phase-1A",
                requirement="PIT data availability matrix covers central_bank and macro-expansion proxies.",
                evidence_paths=(
                    "registry/data_availability/central_bank_data_availability.json",
                    "registry/data_availability/macro_expansion_data_availability.json",
                ),
            ),
            _completion_record(
                root_path,
                completion,
                "C02",
                section_id="Phase-1B",
                requirement="Claim extraction reliability has 50-document / 100-claim manual gold-set gate.",
                evidence_paths=(
                    "registry/gold_sets/tushare_research_reports.review_template.jsonl",
                    "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl",
                    "registry/gold_sets/tushare_research_reports.review_packet.json",
                    "registry/gold_sets/tushare_research_reports.review_summary.json",
                    "registry/review_batches/manual_review_batch_status.json",
                    "registry/review_batches/manual_review_bundle_manifest.json",
                    "registry/review_batches/manual_review_progress_report.json",
                    "registry/review_batches/manual_review_runbook.md",
                    "registry/review_batches/gold_set_next_import_template.jsonl",
                    "registry/review_batches/gold_set_full_import_template.jsonl",
                    "registry/gold_sets/tushare_research_reports.review_import_report.json",
                    REPORT_INTELLIGENCE_PATCH_COVERAGE_REPORT_PATH,
                ),
                blocked_if_failed=True,
                blocked_if_evidence_content_error=True,
                completion_error=completion_error,
            ),
            _record(
                root_path,
                section_id="Phase-0",
                requirement="Experiment governance artifacts exist for baseline, preregistration, cost, lockbox, and overlap policy.",
                evidence_paths=(
                    "registry/evaluation/baselines/central_bank_baseline_versions.json",
                    "registry/evaluation/experiment_family_registry/central_bank_liquidity_family.json",
                    "registry/evaluation/pre_registration/central_bank_liquidity_preregistration.json",
                    "registry/evaluation/cost_model/cost_model_v1.json",
                    "registry/evaluation/lockbox/lockbox_policy.json",
                    "registry/evaluation/overlap_correction/effective_n_overlap_policy.json",
                    EXPERIMENT_VALIDATION_REPORT_PATH,
                    "registry/promotion/rke_promotion_dry_run_report.json",
                    "registry/promotion/rke_production_promotion_gate.json",
                    "registry/lockbox/central_bank_lockbox_review_import_report.json",
                ),
            ),
            _record(
                root_path,
                section_id="Phase-1",
                requirement="Hardened schemas and policy docs are validated.",
                evidence_paths=(
                    "registry/schemas/rke_schema_validation_report.json",
                    "registry/docs/rke_policy_doc_validation_report.json",
                    "schemas/source_metadata.schema.json",
                    "schemas/source_grounded_claim.schema.json",
                    "schemas/hypothesis.schema.json",
                    "schemas/data_availability_matrix.schema.json",
                    "schemas/rule_pack.schema.yaml",
                    "schemas/parameter_prior.schema.json",
                    "schemas/validation_experiment_v2.schema.json",
                    "schemas/production_patch.schema.json",
                    "schemas/confidence_policy.schema.yaml",
                    "schemas/rule_aggregation_policy.schema.yaml",
                    "schemas/report_intelligence_patch_v1_5_coverage_report.schema.json",
                ),
            ),
            _completion_record(
                root_path,
                completion,
                "C04",
                section_id="Phase-2",
                requirement="Central-bank validation MVP includes hardened validation, effective N, FDR, costs, CI, and DSR.",
                evidence_paths=(
                    "registry/rule_packs/macro.central_bank.liquidity.v1.json",
                    "registry/parameter_priors/central_bank_parameter_priors.jsonl",
                    "registry/experiments/central_bank_validation_experiment_v2.json",
                    "registry/validation_hardening/central_bank_hardening_report.json",
                    "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json",
                    EXPERIMENT_VALIDATION_REPORT_PATH,
                ),
                completion_error=completion_error,
            ),
            _completion_record(
                root_path,
                completion,
                "C05",
                section_id="Phase-3",
                requirement="Runtime integration provides rule aggregation, evidence binding, progress event, and downstream handoff.",
                evidence_paths=(
                    "registry/prompt_ir/macro.central_bank.json",
                    "registry/runtime_inputs/macro.central_bank.20260605.json",
                    "registry/runtime_outputs/macro.central_bank.20260605.json",
                    "registry/prompt_checks/prompt_asset_validation_report.json",
                    "registry/promotion/rke_production_promotion_gate.json",
                ),
                completion_error=completion_error,
            ),
            _completion_record(
                root_path,
                completion,
                "C09",
                section_id="Phase-4",
                requirement="Paper-trading dashboard reports live-vs-baseline, calibration, turnover, cost, alpha decay, and rollback state.",
                evidence_paths=(
                    "registry/monitoring/central_bank_paper_trading_report.json",
                    "registry/monitoring/central_bank_monitoring_diagnostics.json",
                    "registry/monitoring/central_bank_rollback_readiness_report.json",
                ),
                completion_error=completion_error,
            ),
            _record(
                root_path,
                section_id="Phase-5",
                requirement="Sector semiconductor provenance demo remains sandbox-only with disagreement evidence.",
                evidence_paths=(
                    "registry/rule_packs/sector.semiconductor.policy_substitution.v1.json",
                    "registry/rule_checks/rule_pack_validation_report.json",
                    "registry/claims/semiconductor_claims.jsonl",
                    "registry/hypotheses/semiconductor_hypotheses.jsonl",
                    "registry/disagreement/semiconductor_policy_substitution.json",
                    "registry/runtime_outputs/sector.semiconductor.demo.20260605.json",
                ),
            ),
            _record(
                root_path,
                section_id="Phase-6",
                requirement="Macro expansion plan covers additional macro families after central_bank Phase 4 readiness.",
                evidence_paths=(
                    "registry/expansion/macro_phase6_expansion.json",
                    "registry/data_availability/macro_expansion_data_availability.json",
                ),
            ),
            _record(
                root_path,
                section_id="Phase-7",
                requirement="Sector / superinvestor / decision integration contracts encode handoff, actionability, cash floor, and override audit.",
                evidence_paths=(
                    "registry/integration/phase7_layer_integration_contracts.json",
                ),
            ),
            _completion_record(
                root_path,
                completion,
                "C11",
                section_id="Compliance",
                requirement="Compliance gate blocks unauthorized reports from production runtime and can apply reviewed license decisions.",
                evidence_paths=(
                    "registry/compliance/tushare_license_review_template.jsonl",
                    "registry/compliance/tushare_license_review_packet.json",
                    "registry/compliance/tushare_license_review_summary.json",
                    "registry/compliance/source_text_redaction_report.json",
                    "registry/source_checks/source_registry_validation_report.json",
                    "registry/review_batches/source_license_next_import_template.jsonl",
                    "registry/review_batches/manual_review_bundle_manifest.json",
                    "registry/review_batches/manual_review_progress_report.json",
                    "registry/review_batches/manual_review_runbook.md",
                    "registry/review_batches/source_license_policy_template.json",
                    "registry/review_batches/source_license_review_workbook.md",
                    "registry/review_batches/source_license_policy_import_report.json",
                    "registry/handoffs/rke_operator_readiness_report.json",
                ),
                blocked_if_failed=True,
                completion_error=completion_error,
            ),
            _completion_record(
                root_path,
                completion,
                "C12",
                section_id="Audit",
                requirement="Audit viewer traces source to claim to hypothesis to rule to parameter to experiment to patch to agent output.",
                evidence_paths=(
                    "registry/audits/central_bank_mvp_audit_trace.json",
                    "registry/audits/central_bank_mvp_audit_view.json",
                    "registry/audits/central_bank_mvp_audit_view.md",
                ),
                completion_error=completion_error,
            ),
        ]
    )

    passed_count = sum(record.status == "passed" for record in records)
    blocked_count = sum(record.status == "blocked" for record in records)
    missing_count = sum(record.status == "missing" for record in records)
    mvp_deliverable_records = _mvp_deliverable_records(
        root_path,
        completion,
        completion_error=completion_error,
    )
    mvp_deliverable_passed_count = sum(
        record.status == "passed" for record in mvp_deliverable_records
    )
    mvp_deliverable_blocked_count = sum(
        record.status == "blocked" for record in mvp_deliverable_records
    )
    mvp_deliverable_missing_count = sum(
        record.status == "missing" for record in mvp_deliverable_records
    )
    mvp_deliverables_ready = (
        mvp_deliverable_missing_count == 0 and mvp_deliverable_blocked_count == 0
    )
    mvp_exit_records = _mvp_exit_records(
        root_path,
        completion,
        completion_error=completion_error,
    )
    mvp_exit_passed_count = sum(
        record.status == "passed" for record in mvp_exit_records
    )
    mvp_exit_blocked_count = sum(
        record.status == "blocked" for record in mvp_exit_records
    )
    mvp_exit_missing_count = sum(
        record.status == "missing" for record in mvp_exit_records
    )
    mvp_exit_ready = mvp_exit_missing_count == 0 and mvp_exit_blocked_count == 0
    final_acceptance_records = _final_acceptance_records(
        root_path,
        completion,
        completion_error=completion_error,
    )
    final_passed_count = sum(
        record.status == "passed" for record in final_acceptance_records
    )
    final_blocked_count = sum(
        record.status == "blocked" for record in final_acceptance_records
    )
    final_missing_count = sum(
        record.status == "missing" for record in final_acceptance_records
    )
    final_acceptance_ready = final_missing_count == 0 and final_blocked_count == 0
    return MasterPlanCoverageReport(
        report_id="RKE-MASTER-PLAN-COVERAGE-REPORT-20260606",
        master_plan_path="docs/plans/master_plan_v1_1.md",
        mvp_deliverables_section=MVP_DELIVERABLES_SECTION,
        mvp_exit_criteria_section=MVP_EXIT_CRITERIA_SECTION,
        final_acceptance_section=MASTER_PLAN_ACCEPTANCE_SECTION,
        coverage_complete=(
            missing_count == 0
            and blocked_count == 0
            and mvp_deliverable_missing_count == 0
            and mvp_deliverable_blocked_count == 0
            and mvp_exit_missing_count == 0
            and mvp_exit_blocked_count == 0
            and final_missing_count == 0
            and final_blocked_count == 0
        ),
        ready_for_broad_rollout=(
            missing_count == 0
            and blocked_count == 0
            and mvp_deliverables_ready
            and mvp_exit_ready
            and final_acceptance_ready
        ),
        passed_count=passed_count,
        blocked_count=blocked_count,
        missing_count=missing_count,
        records=tuple(records),
        mvp_deliverables_ready=mvp_deliverables_ready,
        mvp_deliverables_passed_count=mvp_deliverable_passed_count,
        mvp_deliverables_blocked_count=mvp_deliverable_blocked_count,
        mvp_deliverables_missing_count=mvp_deliverable_missing_count,
        mvp_deliverable_records=tuple(mvp_deliverable_records),
        mvp_exit_ready=mvp_exit_ready,
        mvp_exit_passed_count=mvp_exit_passed_count,
        mvp_exit_blocked_count=mvp_exit_blocked_count,
        mvp_exit_missing_count=mvp_exit_missing_count,
        mvp_exit_records=tuple(mvp_exit_records),
        final_acceptance_ready=final_acceptance_ready,
        final_acceptance_passed_count=final_passed_count,
        final_acceptance_blocked_count=final_blocked_count,
        final_acceptance_missing_count=final_missing_count,
        final_acceptance_records=tuple(final_acceptance_records),
    )


def _final_acceptance_records(
    root_path: Path,
    completion: Mapping[str, Mapping[str, Any]],
    *,
    completion_error: str,
) -> tuple[MasterPlanCoverageRecord, ...]:
    return tuple(
        _completion_record(
            root_path,
            completion,
            str(item["criterion_id"]),
            section_id=f"FinalAcceptance-{item['criterion_id']}",
            requirement=str(item["requirement"]),
            evidence_paths=("registry/audits/rke_completion_audit.json",),
            blocked_if_failed=True,
            completion_error=completion_error,
        )
        for item in FINAL_ACCEPTANCE_REQUIREMENTS
    )


def write_master_plan_coverage_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_master_plan_coverage_report(root_path)
    return _write_json(root_path / MASTER_PLAN_COVERAGE_REPORT_PATH, asdict(report))
