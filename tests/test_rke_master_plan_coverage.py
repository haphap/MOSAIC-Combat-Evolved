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
    shutil.copytree(Path("schemas"), tmp_path / "schemas")


def test_master_plan_coverage_reports_only_manual_blockers():
    report = build_master_plan_coverage_report(".")

    assert report.report_id == "RKE-MASTER-PLAN-COVERAGE-REPORT-20260606"
    assert report.coverage_complete
    assert not report.ready_for_broad_rollout
    assert report.missing_count == 0
    assert report.blocked_count == 2
    blocked = {record.section_id: record for record in report.records if record.status == "blocked"}
    assert set(blocked) == {"Phase-1B", "Compliance"}
    assert "manual gold-set review still required" in blocked["Phase-1B"].blocker
    assert "source license review still pending" in blocked["Compliance"].blocker
    audit = next(record for record in report.records if record.section_id == "Audit")
    assert "registry/audits/central_bank_mvp_audit_view.json" in audit.evidence_paths
    assert "registry/audits/central_bank_mvp_audit_view.md" in audit.evidence_paths
    phase_4 = next(record for record in report.records if record.section_id == "Phase-4")
    assert "registry/monitoring/central_bank_monitoring_diagnostics.json" in phase_4.evidence_paths
    assert "registry/monitoring/central_bank_rollback_readiness_report.json" in phase_4.evidence_paths
    phase_0 = next(record for record in report.records if record.section_id == "Phase-0")
    assert "registry/lockbox/central_bank_lockbox_review_import_report.json" in phase_0.evidence_paths
    assert "registry/promotion/rke_promotion_dry_run_report.json" in phase_0.evidence_paths
    phase_1b = next(record for record in report.records if record.section_id == "Phase-1B")
    assert "registry/review_batches/manual_review_bundle_manifest.json" in phase_1b.evidence_paths
    assert "registry/review_batches/manual_review_runbook.md" in phase_1b.evidence_paths
    assert "registry/review_batches/gold_set_full_import_template.jsonl" in phase_1b.evidence_paths
    assert "registry/gold_sets/tushare_research_reports.review_import_report.json" in phase_1b.evidence_paths
    compliance = next(record for record in report.records if record.section_id == "Compliance")
    assert "registry/handoffs/rke_operator_readiness_report.json" in compliance.evidence_paths
    assert "registry/review_batches/manual_review_bundle_manifest.json" in compliance.evidence_paths
    assert "registry/review_batches/manual_review_runbook.md" in compliance.evidence_paths
    assert "registry/review_batches/source_license_policy_template.json" in compliance.evidence_paths
    assert "registry/review_batches/source_license_policy_import_report.json" in compliance.evidence_paths


def test_master_plan_coverage_detects_missing_phase_artifact(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    (tmp_path / "registry/experiments/central_bank_validation_experiment_v2.json").unlink()

    report = build_master_plan_coverage_report(tmp_path)
    phase_2 = next(record for record in report.records if record.section_id == "Phase-2")

    assert not report.coverage_complete
    assert report.missing_count >= 1
    assert phase_2.status == "missing"
    assert "central_bank_validation_experiment_v2.json" in phase_2.blocker


def test_master_plan_coverage_reports_invalid_direct_json_evidence(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    data_matrix = tmp_path / "registry/data_availability/central_bank_data_availability.json"
    data_matrix.write_text("{", encoding="utf-8")

    report = build_master_plan_coverage_report(tmp_path)
    phase_1a = next(record for record in report.records if record.section_id == "Phase-1A")

    assert not report.coverage_complete
    assert phase_1a.status == "missing"
    assert "central_bank_data_availability.json must contain valid JSON" in phase_1a.blocker


def test_master_plan_coverage_reports_invalid_direct_jsonl_evidence(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    claims = tmp_path / "registry/claims/semiconductor_claims.jsonl"
    expected_row = len(claims.read_text(encoding="utf-8").splitlines()) + 1
    claims.write_text(claims.read_text(encoding="utf-8") + "{\n", encoding="utf-8")

    report = build_master_plan_coverage_report(tmp_path)
    phase_5 = next(record for record in report.records if record.section_id == "Phase-5")

    assert not report.coverage_complete
    assert phase_5.status == "missing"
    assert f"semiconductor_claims.jsonl row {expected_row} must contain valid JSON" in phase_5.blocker


def test_master_plan_coverage_malformed_blocked_evidence_is_missing(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    gold_import = tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl"
    gold_import.write_text("{\n", encoding="utf-8")

    report = build_master_plan_coverage_report(tmp_path)
    phase_1b = next(record for record in report.records if record.section_id == "Phase-1B")

    assert not report.coverage_complete
    assert phase_1b.status == "missing"
    assert "gold_set_next_import_template.jsonl row 1 must contain valid JSON" in phase_1b.blocker


def test_master_plan_coverage_reports_invalid_completion_audit_json(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    completion_path.write_text("{", encoding="utf-8")

    report = build_master_plan_coverage_report(tmp_path)
    phase_2 = next(record for record in report.records if record.section_id == "Phase-2")
    compliance = next(record for record in report.records if record.section_id == "Compliance")

    assert not report.coverage_complete
    assert not report.ready_for_broad_rollout
    assert report.missing_count >= 6
    assert phase_2.status == "missing"
    assert compliance.status == "missing"
    assert "completion audit must contain valid JSON" in phase_2.blocker
    assert "completion audit must contain valid JSON" in compliance.blocker


def test_master_plan_coverage_reports_non_object_completion_audit(tmp_path: Path):
    _copy_registry_and_schemas(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    completion_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    report = build_master_plan_coverage_report(tmp_path)
    phase_3 = next(record for record in report.records if record.section_id == "Phase-3")

    assert not report.coverage_complete
    assert phase_3.status == "missing"
    assert "completion audit must be object" in phase_3.blocker


def test_master_plan_coverage_reports_malformed_completion_criteria_rows(tmp_path: Path):
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


def test_master_plan_coverage_writer_and_cli(tmp_path: Path, capsys):
    _copy_registry_and_schemas(tmp_path)

    result = write_master_plan_coverage_report(tmp_path)
    code = main(("master-plan-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert Path(result["path"]).exists()
    assert code == 0
    assert output["coverage_complete"] is True
    assert output["ready_for_broad_rollout"] is False
    assert output["blocked_count"] == 2
