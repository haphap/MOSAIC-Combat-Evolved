from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import build_rollback_readiness_report, write_rollback_readiness_report
from mosaic.rke.cli import main


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")


def test_rollback_readiness_covers_soft_hard_and_compliance_paths():
    report = build_rollback_readiness_report(".")
    checks = {check.check_id: check for check in report.checks}

    assert report.accepted
    assert report.check_count == 5
    assert report.failure_count == 0
    assert checks["soft_rollback_alpha_decay"].rollback_type == "soft"
    assert checks["soft_rollback_alpha_decay"].action == "reduce_weight_and_revalidate"
    assert checks["hard_rollback_negative_alpha"].rollback_type == "hard"
    assert checks["hard_rollback_negative_alpha"].action == "rollback"
    assert (
        checks["compliance_rollback_blocks_runtime_retrieval"].rollback_type
        == "compliance"
    )
    assert checks["promotion_gate_respects_rollback_blocks"].passed


def test_rollback_readiness_requires_patch_rollback_rule(tmp_path: Path):
    _copy_registry(tmp_path)
    patch_path = tmp_path / "registry/patches/central_bank_paper_trading_patch.json"
    patch = json.loads(patch_path.read_text(encoding="utf-8"))
    patch.pop("rollback_rule")
    patch_path.write_text(
        json.dumps(patch, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_rollback_readiness_report(tmp_path)
    patch_check = next(
        check
        for check in report.checks
        if check.check_id == "patch_has_slow_decay_rollback_rule"
    )

    assert not report.accepted
    assert not patch_check.passed
    assert "rollback rule is incomplete" in patch_check.blocker


def test_rollback_readiness_reads_monitoring_diagnostics_artifact(tmp_path: Path):
    _copy_registry(tmp_path)
    diagnostics_path = (
        tmp_path / "registry/monitoring/central_bank_monitoring_diagnostics.json"
    )
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    for scenario in diagnostics["scenarios"]:
        if scenario["scenario_id"] == "alpha_decay":
            scenario["result"]["state"] = "production"
            scenario["result"]["action"] = "none"
    diagnostics_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_rollback_readiness_report(tmp_path)
    soft_check = next(
        check
        for check in report.checks
        if check.check_id == "soft_rollback_alpha_decay"
    )

    assert not report.accepted
    assert not soft_check.passed
    assert "soft rollback" in soft_check.blocker


def test_rollback_readiness_reports_malformed_monitoring_diagnostics(tmp_path: Path):
    _copy_registry(tmp_path)
    diagnostics_path = (
        tmp_path / "registry/monitoring/central_bank_monitoring_diagnostics.json"
    )
    diagnostics_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    report = build_rollback_readiness_report(tmp_path)
    checks = {check.check_id: check for check in report.checks}

    assert not report.accepted
    assert not checks["soft_rollback_alpha_decay"].passed
    assert not checks["hard_rollback_negative_alpha"].passed
    assert (
        "monitoring diagnostics must be object"
        in checks["soft_rollback_alpha_decay"].blocker
    )
    assert (
        "monitoring diagnostics must be object"
        in checks["hard_rollback_negative_alpha"].blocker
    )


def test_rollback_readiness_reports_malformed_patch_payload(tmp_path: Path):
    _copy_registry(tmp_path)
    patch_path = tmp_path / "registry/patches/central_bank_paper_trading_patch.json"
    patch_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    report = build_rollback_readiness_report(tmp_path)
    patch_check = next(
        check
        for check in report.checks
        if check.check_id == "patch_has_slow_decay_rollback_rule"
    )

    assert not report.accepted
    assert not patch_check.passed
    assert "promotion patch must be object" in patch_check.blocker


def test_rollback_readiness_reports_malformed_compliance_payloads(tmp_path: Path):
    _copy_registry(tmp_path)
    source_validation_path = (
        tmp_path / "registry/source_checks/source_registry_validation_report.json"
    )
    license_path = tmp_path / "registry/compliance/tushare_license_review_summary.json"
    source_validation_path.write_text(
        json.dumps(["not", "an", "object"]), encoding="utf-8"
    )
    license_path.write_text(json.dumps("not an object"), encoding="utf-8")

    report = build_rollback_readiness_report(tmp_path)
    compliance_check = next(
        check
        for check in report.checks
        if check.check_id == "compliance_rollback_blocks_runtime_retrieval"
    )

    assert not report.accepted
    assert not compliance_check.passed
    assert (
        "source registry validation report must be object" in compliance_check.blocker
    )
    assert "source license review summary must be object" in compliance_check.blocker


def test_write_rollback_readiness_report_outputs_registry_artifact(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_rollback_readiness_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert result["accepted"] is True
    assert payload["accepted"] is True
    assert payload["failure_count"] == 0
    assert (
        tmp_path / "registry/monitoring/central_bank_rollback_readiness_report.json"
    ).exists()


def test_cli_rollback_readiness_writes_report(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("rollback-readiness", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["check_count"] == 5
    assert (
        tmp_path / "registry/monitoring/central_bank_rollback_readiness_report.json"
    ).exists()
