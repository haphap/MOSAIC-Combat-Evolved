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
    phase_1b = next(record for record in report.records if record.section_id == "Phase-1B")
    assert "registry/review_batches/gold_set_full_import_template.jsonl" in phase_1b.evidence_paths
    compliance = next(record for record in report.records if record.section_id == "Compliance")
    assert "registry/handoffs/rke_operator_readiness_report.json" in compliance.evidence_paths
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
