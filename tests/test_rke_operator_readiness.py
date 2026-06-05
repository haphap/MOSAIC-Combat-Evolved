from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import build_operator_readiness_report, write_operator_readiness_report
from mosaic.rke.cli import main


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_operator_readiness_accepts_current_review_bundle():
    report = build_operator_readiness_report(".")
    checks = {check.check_id: check for check in report.checks}

    assert report.accepted
    assert report.failure_count == 0
    assert checks["required_registry_valid"].passed
    assert checks["handoff_ready_for_operator"].passed
    assert checks["manual_batch_templates_match_status"].passed
    assert checks["manual_import_templates_are_sparse"].passed
    assert checks["lockbox_template_requires_human_decision"].passed
    assert checks["source_license_policy_template_requires_human_decision"].passed
    assert checks["blank_source_license_policy_import_is_rejected"].passed
    assert checks["blank_bundle_dry_run_does_not_promote"].passed
    assert checks["promotion_gate_still_blocks_production"].passed
    assert checks["source_text_redaction_clean"].passed


def test_operator_readiness_detects_long_source_text_in_import_template(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_import = tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl"
    rows = _load_jsonl(gold_import)
    rows[0]["abstract"] = "long source text must not appear in sparse import templates"
    _write_jsonl(gold_import, rows)

    report = build_operator_readiness_report(tmp_path)
    sparse = next(check for check in report.checks if check.check_id == "manual_import_templates_are_sparse")

    assert not report.accepted
    assert not sparse.passed
    assert "long source-text field" in sparse.blocker


def test_operator_readiness_detects_filled_policy_template(tmp_path: Path):
    _copy_registry(tmp_path)
    result = write_operator_readiness_report(tmp_path)
    policy_path = tmp_path / "registry/review_batches/source_license_policy_template.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["approved_for_production_runtime"] = True
    policy_path.write_text(
        json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_operator_readiness_report(tmp_path)
    policy_check = next(
        check
        for check in report.checks
        if check.check_id == "source_license_policy_template_requires_human_decision"
    )

    assert result["accepted"] is True
    assert not report.accepted
    assert not policy_check.passed
    assert "policy template" in policy_check.blocker


def test_operator_readiness_rejects_blank_source_license_policy_import(tmp_path: Path):
    _copy_registry(tmp_path)

    report = build_operator_readiness_report(tmp_path)
    policy_import = next(
        check for check in report.checks if check.check_id == "blank_source_license_policy_import_is_rejected"
    )
    import_report = json.loads(
        (tmp_path / "registry/review_batches/source_license_policy_import_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert report.accepted
    assert policy_import.passed
    assert import_report["accepted"] is False
    assert import_report["dry_run"] is True
    assert import_report["output_rows"] == 0
    assert "reviewer required" in import_report["blockers"]
    assert not (tmp_path / "registry/review_batches/source_license_policy_import.jsonl").exists()


def test_write_operator_readiness_report_outputs_registry_artifact(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_operator_readiness_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert result["accepted"] is True
    assert payload["accepted"] is True
    assert payload["failure_count"] == 0
    assert "registry/review_batches/gold_set_full_import_template.jsonl" in payload["generated_paths"]
    assert "registry/review_batches/source_license_policy_import_report.json" in payload["generated_paths"]
    assert (tmp_path / "registry/handoffs/rke_operator_readiness_report.json").exists()
    assert (tmp_path / "registry/review_batches/gold_set_full_import_template.jsonl").exists()
    assert (tmp_path / "registry/review_batches/source_license_policy_import_report.json").exists()


def test_cli_operator_readiness_writes_report(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("operator-readiness", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert (tmp_path / "registry/handoffs/rke_operator_readiness_report.json").exists()
