from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_policy_doc_validation_report,
    write_policy_doc_validation_report,
)
from mosaic.rke.cli import main


def _copy_docs_and_registry(tmp_path: Path) -> None:
    shutil.copytree(Path("docs"), tmp_path / "docs")
    shutil.copytree(Path("registry"), tmp_path / "registry")


def test_policy_doc_validation_accepts_current_docs():
    report = build_policy_doc_validation_report(".")

    assert report.accepted
    assert report.failure_count == 0
    assert {record.path for record in report.records} == {
        "docs/plans/master_plan_v1_1.md",
        "docs/plans/rke_phase_minus_1_plan.md",
        "docs/claim_extraction_guidelines.md",
        "docs/validation_policy.md",
        "docs/confidence_policy.md",
        "docs/compliance_policy.md",
    }


def test_policy_doc_validation_rejects_missing_marker(tmp_path: Path):
    _copy_docs_and_registry(tmp_path)
    path = tmp_path / "docs/compliance_policy.md"
    path.write_text("# Compliance\n", encoding="utf-8")

    report = build_policy_doc_validation_report(tmp_path)
    record = next(record for record in report.records if record.path == "docs/compliance_policy.md")

    assert not report.accepted
    assert not record.accepted
    assert "Manual License Review" in record.missing_markers


def test_policy_doc_validation_writer_and_cli(tmp_path: Path, capsys):
    _copy_docs_and_registry(tmp_path)

    result = write_policy_doc_validation_report(tmp_path)
    code = main(("policy-doc-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert Path(result["path"]).exists()
    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert (tmp_path / "registry/docs/rke_policy_doc_validation_report.json").exists()
