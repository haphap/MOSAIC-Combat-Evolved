"""Master-plan coverage audit for RKE implementation evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


MASTER_PLAN_COVERAGE_REPORT_PATH = "registry/audits/rke_master_plan_coverage_report.json"

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
    coverage_complete: bool
    ready_for_broad_rollout: bool
    passed_count: int
    blocked_count: int
    missing_count: int
    records: Sequence[MasterPlanCoverageRecord]


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
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": 1}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _exists(root_path: Path, relative: str) -> bool:
    path = root_path / relative
    return path.exists() and path.stat().st_size > 0


def _all_exist(root_path: Path, evidence_paths: Sequence[str]) -> tuple[bool, str]:
    missing = [path for path in evidence_paths if not _exists(root_path, path)]
    if missing:
        return False, f"missing evidence: {', '.join(missing)}"
    return True, ""


def _completion_by_id(root_path: Path) -> dict[str, Mapping[str, Any]]:
    path = root_path / "registry/audits/rke_completion_audit.json"
    if not path.exists():
        return {}
    payload = _read_json(path)
    return {str(row.get("criterion_id")): row for row in payload.get("criteria", ())}


def _record(
    root_path: Path,
    *,
    section_id: str,
    requirement: str,
    evidence_paths: Sequence[str],
    status: CoverageStatus | None = None,
    blocker: str = "",
) -> MasterPlanCoverageRecord:
    evidence_ok, evidence_blocker = _all_exist(root_path, evidence_paths)
    final_status: CoverageStatus = status or ("passed" if evidence_ok else "missing")
    final_blocker = blocker
    if not evidence_ok and final_status != "blocked":
        final_status = "missing"
        final_blocker = evidence_blocker
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
) -> MasterPlanCoverageRecord:
    row = completion.get(criterion_id, {})
    passed = row.get("passed") is True
    blocker = str(row.get("blocker") or "")
    if passed:
        status: CoverageStatus = "passed"
    elif blocked_if_failed and blocker:
        status = "blocked"
    else:
        status = "missing"
    return _record(
        root_path,
        section_id=section_id,
        requirement=requirement,
        evidence_paths=evidence_paths,
        status=status,
        blocker=blocker,
    )


def build_master_plan_coverage_report(root: str | Path = ".") -> MasterPlanCoverageReport:
    root_path = Path(root)
    completion = _completion_by_id(root_path)
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
                requirement="Claim extraction reliability has 50-document / 500-claim manual gold-set gate.",
                evidence_paths=(
                    "registry/gold_sets/tushare_research_reports.review_template.jsonl",
                    "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl",
                    "registry/gold_sets/tushare_research_reports.review_packet.json",
                    "registry/gold_sets/tushare_research_reports.review_summary.json",
                    "registry/review_batches/manual_review_batch_status.json",
                    "registry/review_batches/gold_set_next_import_template.jsonl",
                ),
                blocked_if_failed=True,
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
                    "registry/promotion/rke_production_promotion_gate.json",
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
                ),
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
                ),
            ),
            _record(
                root_path,
                section_id="Phase-5",
                requirement="Sector semiconductor provenance demo remains sandbox-only with disagreement evidence.",
                evidence_paths=(
                    "registry/rule_packs/sector.semiconductor.policy_substitution.v1.json",
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
                evidence_paths=("registry/integration/phase7_layer_integration_contracts.json",),
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
                    "registry/handoffs/rke_operator_readiness_report.json",
                ),
                blocked_if_failed=True,
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
            ),
        ]
    )

    passed_count = sum(record.status == "passed" for record in records)
    blocked_count = sum(record.status == "blocked" for record in records)
    missing_count = sum(record.status == "missing" for record in records)
    return MasterPlanCoverageReport(
        report_id="RKE-MASTER-PLAN-COVERAGE-REPORT-20260606",
        master_plan_path="docs/master_plan_v1_1.md",
        coverage_complete=missing_count == 0,
        ready_for_broad_rollout=missing_count == 0 and blocked_count == 0,
        passed_count=passed_count,
        blocked_count=blocked_count,
        missing_count=missing_count,
        records=tuple(records),
    )


def write_master_plan_coverage_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_master_plan_coverage_report(root_path)
    return _write_json(root_path / MASTER_PLAN_COVERAGE_REPORT_PATH, asdict(report))
