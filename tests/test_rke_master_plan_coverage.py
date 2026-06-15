from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_master_plan_coverage_report,
    write_master_plan_coverage_report,
)
from mosaic.rke.cli import main


def _copy_registry_and_schemas(tmp_path: Path) -> None:
    shutil.copytree(Path("registry"), tmp_path / "registry")
    shutil.copytree(Path("docs"), tmp_path / "docs")
    shutil.copytree(Path("schemas"), tmp_path / "schemas")


def test_master_plan_coverage_reports_current_registry_ready():
    report = build_master_plan_coverage_report(".")

    assert report.report_id == "RKE-MASTER-PLAN-COVERAGE-REPORT-20260606"
    assert not report.coverage_complete
    assert not report.ready_for_broad_rollout
    assert report.missing_count == 0
    assert report.blocked_count == 1
    assert report.mvp_deliverables_section == "16.3"
    assert report.mvp_exit_criteria_section == "16.4"
    assert report.mvp_deliverables_passed_count == 9
    assert report.mvp_deliverables_blocked_count == 1
    assert report.mvp_deliverables_missing_count == 0
    assert not report.mvp_deliverables_ready
    assert report.mvp_exit_passed_count == 12
    assert report.mvp_exit_blocked_count == 1
    assert report.mvp_exit_missing_count == 0
    assert not report.mvp_exit_ready
    assert report.final_acceptance_section == "22"
    assert report.final_acceptance_passed_count == 11
    assert report.final_acceptance_blocked_count == 1
    assert report.final_acceptance_missing_count == 0
    assert not report.final_acceptance_ready
    phase_1b = next(
        record for record in report.records if record.section_id == "Phase-1B"
    )
    assert phase_1b.status == "blocked"
    assert "manual gold-set review still required" in phase_1b.blocker
    assert "patch_v1_5_coverage_report.json accepted must be true" in phase_1b.blocker
    assert "blocked phases: B, D" in phase_1b.blocker
    assert all(
        record.status == "passed"
        for record in report.records
        if record.section_id != "Phase-1B"
    )
    assert all(
        record.status == "passed"
        for record in report.mvp_deliverable_records
        if record.section_id != "MVP-D2"
    )
    mvp_d2 = next(
        record
        for record in report.mvp_deliverable_records
        if record.section_id == "MVP-D2"
    )
    assert mvp_d2.status == "blocked"
    assert "manual gold-set review still required" in mvp_d2.blocker
    mvp_d3 = next(
        record
        for record in report.mvp_deliverable_records
        if record.section_id == "MVP-D3"
    )
    assert mvp_d3.status == "passed"
    assert all(
        record.status == "passed"
        for record in report.mvp_exit_records
        if record.section_id != "MVP-E01"
    )
    assert (
        next(record for record in report.mvp_exit_records if record.section_id == "MVP-E01").status
        == "blocked"
    )
    assert all(
        record.status == "passed"
        for record in report.final_acceptance_records
        if record.section_id != "FinalAcceptance-C02"
    )
    assert (
        next(
            record
            for record in report.final_acceptance_records
            if record.section_id == "FinalAcceptance-C02"
        ).status
        == "blocked"
    )
    assert all(
        record.evidence_paths == ("registry/audits/rke_completion_audit.json",)
        for record in report.final_acceptance_records
    )
    audit = next(record for record in report.records if record.section_id == "Audit")
    assert "registry/audits/central_bank_mvp_audit_view.json" in audit.evidence_paths
    assert "registry/audits/central_bank_mvp_audit_view.md" in audit.evidence_paths
    phase_4 = next(
        record for record in report.records if record.section_id == "Phase-4"
    )
    assert (
        "registry/monitoring/central_bank_monitoring_diagnostics.json"
        in phase_4.evidence_paths
    )
    assert (
        "registry/monitoring/central_bank_rollback_readiness_report.json"
        in phase_4.evidence_paths
    )
    phase_0 = next(
        record for record in report.records if record.section_id == "Phase-0"
    )
    assert (
        "registry/lockbox/central_bank_lockbox_review_import_report.json"
        in phase_0.evidence_paths
    )
    assert (
        "registry/promotion/rke_promotion_dry_run_report.json" in phase_0.evidence_paths
    )
    assert (
        "registry/review_batches/manual_review_bundle_manifest.json"
        in phase_1b.evidence_paths
    )
    assert "registry/review_batches/manual_review_runbook.md" in phase_1b.evidence_paths
    assert (
        "registry/review_batches/gold_set_full_import_template.jsonl"
        in phase_1b.evidence_paths
    )
    assert (
        "registry/gold_sets/tushare_research_reports.review_import_report.json"
        in phase_1b.evidence_paths
    )
    assert (
        "registry/report_intelligence/patch_v1_5_coverage_report.json"
        in phase_1b.evidence_paths
    )
    phase_1 = next(record for record in report.records if record.section_id == "Phase-1")
    assert (
        "schemas/report_intelligence_patch_v1_5_coverage_report.schema.json"
        in phase_1.evidence_paths
    )
    compliance = next(
        record for record in report.records if record.section_id == "Compliance"
    )
    assert (
        "registry/handoffs/rke_operator_readiness_report.json"
        in compliance.evidence_paths
    )
    assert (
        "registry/review_batches/manual_review_bundle_manifest.json"
        in compliance.evidence_paths
    )
    assert (
        "registry/review_batches/manual_review_runbook.md" in compliance.evidence_paths
    )
    assert (
        "registry/review_batches/source_license_policy_template.json"
        in compliance.evidence_paths
    )
    assert (
        "registry/review_batches/source_license_policy_import_report.json"
        in compliance.evidence_paths
    )


def test_master_plan_coverage_detects_missing_phase_artifact(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    (
        tmp_path / "registry/experiments/central_bank_validation_experiment_v2.json"
    ).unlink()

    report = build_master_plan_coverage_report(tmp_path)
    phase_2 = next(
        record for record in report.records if record.section_id == "Phase-2"
    )

    assert not report.coverage_complete
    assert report.missing_count >= 1
    assert phase_2.status == "missing"
    assert "central_bank_validation_experiment_v2.json" in phase_2.blocker


def test_master_plan_coverage_claim_checker_ignores_unrelated_schema_gate(
    tmp_path: Path,
):
    _copy_registry_and_schemas(tmp_path)
    schema_report_path = tmp_path / "registry/schemas/rke_schema_validation_report.json"
    schema_report = json.loads(schema_report_path.read_text(encoding="utf-8"))
    assert schema_report["accepted"] is False

    report = build_master_plan_coverage_report(tmp_path)
    mvp_d3 = next(
        record
        for record in report.mvp_deliverable_records
        if record.section_id == "MVP-D3"
    )

    assert mvp_d3.status == "passed"


def test_master_plan_coverage_claim_checker_blocks_source_claim_schema_failure(
    tmp_path: Path,
):
    _copy_registry_and_schemas(tmp_path)
    schema_report_path = tmp_path / "registry/schemas/rke_schema_validation_report.json"
    schema_report = json.loads(schema_report_path.read_text(encoding="utf-8"))
    for record in schema_report["records"]:
        if record.get("schema_path") == "schemas/source_grounded_claim.schema.json":
            record["accepted"] = False
            record["failures"] = ["claim row missing source span"]
            break
    schema_report_path.write_text(
        json.dumps(schema_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_master_plan_coverage_report(tmp_path)
    mvp_d3 = next(
        record
        for record in report.mvp_deliverable_records
        if record.section_id == "MVP-D3"
    )

    assert mvp_d3.status == "blocked"
    assert "source_grounded_claim schema failed" in mvp_d3.blocker
    assert "claim row missing source span" in mvp_d3.blocker


def test_master_plan_coverage_reports_invalid_direct_json_evidence(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    data_matrix = (
        tmp_path / "registry/data_availability/central_bank_data_availability.json"
    )
    data_matrix.write_text("{", encoding="utf-8")

    report = build_master_plan_coverage_report(tmp_path)
    phase_1a = next(
        record for record in report.records if record.section_id == "Phase-1A"
    )

    assert not report.coverage_complete
    assert phase_1a.status == "missing"
    assert (
        "central_bank_data_availability.json must contain valid JSON"
        in phase_1a.blocker
    )


def test_master_plan_coverage_rejects_blocked_report_intelligence_patch(
    tmp_path: Path,
):
    _copy_registry_and_schemas(tmp_path)
    coverage_path = (
        tmp_path / "registry/report_intelligence/patch_v1_5_coverage_report.json"
    )
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["accepted"] = False
    coverage["blocker_count"] = 1
    coverage["blocked_phase_ids"] = ["B"]
    coverage["phase_records"][1]["status"] = "blocked"
    coverage_path.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_master_plan_coverage_report(tmp_path)
    phase_1b = next(
        record for record in report.records if record.section_id == "Phase-1B"
    )

    assert not report.coverage_complete
    assert phase_1b.status == "blocked"
    assert "patch_v1_5_coverage_report.json accepted must be true" in phase_1b.blocker
    assert "blocked phases: B" in phase_1b.blocker


def test_master_plan_coverage_reports_invalid_direct_jsonl_evidence(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    claims = tmp_path / "registry/claims/semiconductor_claims.jsonl"
    expected_row = len(claims.read_text(encoding="utf-8").splitlines()) + 1
    claims.write_text(claims.read_text(encoding="utf-8") + "{\n", encoding="utf-8")

    report = build_master_plan_coverage_report(tmp_path)
    phase_5 = next(
        record for record in report.records if record.section_id == "Phase-5"
    )

    assert not report.coverage_complete
    assert phase_5.status == "missing"
    assert (
        f"semiconductor_claims.jsonl row {expected_row} must contain valid JSON"
        in phase_5.blocker
    )


def test_master_plan_coverage_malformed_blocked_evidence_is_missing(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    patch_coverage = (
        tmp_path / "registry/report_intelligence/patch_v1_5_coverage_report.json"
    )
    patch_coverage.write_text("{\n", encoding="utf-8")

    report = build_master_plan_coverage_report(tmp_path)
    phase_1b = next(
        record for record in report.records if record.section_id == "Phase-1B"
    )

    assert not report.coverage_complete
    assert phase_1b.status == "missing"
    assert "patch_v1_5_coverage_report.json must contain valid JSON" in phase_1b.blocker


def test_master_plan_coverage_reports_invalid_completion_audit_json(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    completion_path.write_text("{", encoding="utf-8")

    report = build_master_plan_coverage_report(tmp_path)
    phase_2 = next(
        record for record in report.records if record.section_id == "Phase-2"
    )
    compliance = next(
        record for record in report.records if record.section_id == "Compliance"
    )

    assert not report.coverage_complete
    assert not report.ready_for_broad_rollout
    assert report.missing_count >= 6
    assert report.final_acceptance_missing_count == 12
    assert phase_2.status == "missing"
    assert compliance.status == "missing"
    assert "completion audit must contain valid JSON" in phase_2.blocker
    assert "completion audit must contain valid JSON" in compliance.blocker


def test_master_plan_coverage_reports_non_object_completion_audit(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    completion_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    report = build_master_plan_coverage_report(tmp_path)
    phase_3 = next(
        record for record in report.records if record.section_id == "Phase-3"
    )

    assert not report.coverage_complete
    assert phase_3.status == "missing"
    assert "completion audit must be object" in phase_3.blocker


def test_master_plan_coverage_reports_malformed_completion_criteria_rows(
    tmp_path: Path,
):
    _copy_registry_and_schemas(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["criteria"].append("not an object")
    completion_path.write_text(
        json.dumps(completion, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_master_plan_coverage_report(tmp_path)
    audit = next(record for record in report.records if record.section_id == "Audit")

    assert not report.coverage_complete
    assert audit.status == "missing"
    assert "completion audit criteria row must be object" in audit.blocker


def test_master_plan_coverage_rejects_duplicate_completion_criterion_id(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["criteria"][1]["criterion_id"] = "C01"
    completion_path.write_text(
        json.dumps(completion, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_master_plan_coverage_report(tmp_path)
    phase_2 = next(
        record for record in report.records if record.section_id == "Phase-2"
    )

    assert not report.coverage_complete
    assert phase_2.status == "missing"
    assert "completion audit criterion_id duplicated: C01" in phase_2.blocker


def test_master_plan_coverage_rejects_out_of_order_completion_criteria(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["criteria"][0], completion["criteria"][1] = (
        completion["criteria"][1],
        completion["criteria"][0],
    )
    completion_path.write_text(
        json.dumps(completion, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_master_plan_coverage_report(tmp_path)
    phase_2 = next(
        record for record in report.records if record.section_id == "Phase-2"
    )

    assert not report.coverage_complete
    assert phase_2.status == "missing"
    assert "criteria are out of order" in phase_2.blocker


def test_master_plan_coverage_rejects_wrong_completion_acceptance_metadata(
    tmp_path: Path,
):
    _copy_registry_and_schemas(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["acceptance_criteria_count"] = 11
    completion_path.write_text(
        json.dumps(completion, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_master_plan_coverage_report(tmp_path)
    compliance = next(
        record for record in report.records if record.section_id == "Compliance"
    )

    assert not report.coverage_complete
    assert compliance.status == "missing"
    assert report.final_acceptance_missing_count == 12
    assert "completion audit acceptance_criteria_count must be 12" in compliance.blocker


def test_master_plan_coverage_rejects_missing_completion_acceptance_metadata(
    tmp_path: Path,
):
    _copy_registry_and_schemas(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion.pop("master_plan_path", None)
    completion_path.write_text(
        json.dumps(completion, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_master_plan_coverage_report(tmp_path)
    phase_3 = next(
        record for record in report.records if record.section_id == "Phase-3"
    )

    assert not report.coverage_complete
    assert phase_3.status == "missing"
    assert (
        "completion audit master_plan_path must be docs/plans/master_plan_v1_1.md"
        in phase_3.blocker
    )


def test_master_plan_coverage_rejects_drifted_completion_acceptance_requirements(
    tmp_path: Path,
):
    _copy_registry_and_schemas(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["acceptance_requirements"][0]["requirement"] = "drifted"
    completion_path.write_text(
        json.dumps(completion, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_master_plan_coverage_report(tmp_path)
    final_c01 = next(
        record
        for record in report.final_acceptance_records
        if record.section_id == "FinalAcceptance-C01"
    )

    assert not report.coverage_complete
    assert not report.final_acceptance_ready
    assert report.final_acceptance_missing_count == 12
    assert final_c01.status == "missing"
    assert "acceptance_requirements must match master plan §22" in final_c01.blocker


def test_master_plan_coverage_writer_and_cli(tmp_path: Path, capsys):
    _copy_registry_and_schemas(tmp_path)

    result = write_master_plan_coverage_report(tmp_path)
    code = main(("master-plan-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert Path(result["path"]).exists()
    assert code == 2
    assert output["coverage_complete"] is False
    assert output["ready_for_broad_rollout"] is False
    assert output["blocked_count"] == 1
    assert output["missing_count"] == 0
    assert output["mvp_deliverables_section"] == "16.3"
    assert output["mvp_deliverables_blocked_count"] == 0
    assert output["mvp_deliverables_missing_count"] == 0
    assert output["mvp_exit_criteria_section"] == "16.4"
    assert output["mvp_exit_blocked_count"] == 0
    assert output["final_acceptance_section"] == "22"
    assert output["final_acceptance_blocked_count"] == 0
