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


def _append_jsonl_value(path: Path, value) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def test_operator_readiness_accepts_current_review_bundle():
    report = build_operator_readiness_report(".")
    checks = {check.check_id: check for check in report.checks}

    assert report.accepted
    assert report.failure_count == 0
    assert report.check_count == 14
    assert "registry/promotion/rke_promotion_dry_run_report.json" in report.generated_paths
    assert "registry/review_batches/manual_review_bundle_manifest.json" in report.generated_paths
    assert checks["required_registry_valid"].passed
    assert checks["handoff_ready_for_operator"].passed
    assert checks["manual_batch_templates_match_status"].passed
    assert checks["manual_import_templates_are_sparse"].passed
    assert checks["manual_import_templates_have_provenance"].passed
    assert checks["blank_full_gold_set_import_is_rejected"].passed
    assert checks["lockbox_template_requires_human_decision"].passed
    assert checks["blank_lockbox_import_is_rejected"].passed
    assert checks["source_license_policy_template_requires_human_decision"].passed
    assert checks["blank_source_license_policy_import_is_rejected"].passed
    assert checks["blank_bundle_dry_run_does_not_promote"].passed
    assert checks["manual_review_bundle_manifest_current"].passed
    assert checks["promotion_gate_still_blocks_production"].passed
    assert checks["source_text_redaction_clean"].passed


def test_operator_readiness_reports_malformed_required_registry_artifact(tmp_path: Path):
    _copy_registry(tmp_path)
    required_jsonl = tmp_path / "registry/claims/semiconductor_claims.jsonl"
    required_jsonl.write_text("{\n", encoding="utf-8")

    report = build_operator_readiness_report(tmp_path)
    required = next(check for check in report.checks if check.check_id == "required_registry_valid")

    assert not report.accepted
    assert not required.passed
    assert "invalid=1" in required.evidence
    assert "registry/claims/semiconductor_claims.jsonl row 1 must contain valid JSON" in required.blocker


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


def test_operator_readiness_detects_long_source_text_in_policy_template(tmp_path: Path):
    _copy_registry(tmp_path)
    write_operator_readiness_report(tmp_path)
    policy_path = tmp_path / "registry/review_batches/source_license_policy_template.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["source_text"] = "long source text must not appear in sparse policy templates"
    policy_path.write_text(
        json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_operator_readiness_report(tmp_path)
    sparse = next(check for check in report.checks if check.check_id == "manual_import_templates_are_sparse")

    assert not report.accepted
    assert not sparse.passed
    assert "long source-text field" in sparse.blocker


def test_operator_readiness_detects_nested_source_text_in_policy_template(tmp_path: Path):
    _copy_registry(tmp_path)
    write_operator_readiness_report(tmp_path)
    policy_path = tmp_path / "registry/review_batches/source_license_policy_template.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["review_context"] = {
        "source_span_text": "nested source text must not appear in sparse policy templates"
    }
    policy_path.write_text(
        json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_operator_readiness_report(tmp_path)
    sparse = next(check for check in report.checks if check.check_id == "manual_import_templates_are_sparse")

    assert not report.accepted
    assert not sparse.passed
    assert "review_context.source_span_text" in sparse.evidence


def test_operator_readiness_detects_long_source_text_in_lockbox_template(tmp_path: Path):
    _copy_registry(tmp_path)
    write_operator_readiness_report(tmp_path)
    lockbox_path = tmp_path / "registry/review_batches/lockbox_review_next_import_template.json"
    lockbox = json.loads(lockbox_path.read_text(encoding="utf-8"))
    lockbox["abstract"] = "long source text must not appear in sparse lockbox templates"
    lockbox_path.write_text(
        json.dumps(lockbox, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_operator_readiness_report(tmp_path)
    sparse = next(check for check in report.checks if check.check_id == "manual_import_templates_are_sparse")

    assert not report.accepted
    assert not sparse.passed
    assert "long source-text field" in sparse.blocker


def test_operator_readiness_detects_missing_manual_template_provenance(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_import = tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl"
    rows = _load_jsonl(gold_import)
    rows[0].pop("target_row_hash")
    _write_jsonl(gold_import, rows)

    report = build_operator_readiness_report(tmp_path)
    provenance = next(
        check for check in report.checks if check.check_id == "manual_import_templates_have_provenance"
    )

    assert not report.accepted
    assert not provenance.passed
    assert "provenance" in provenance.blocker


def test_operator_readiness_reports_malformed_import_template_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_import = tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl"
    expected_row = len(gold_import.read_text(encoding="utf-8").splitlines()) + 1
    _append_jsonl_value(gold_import, "not an object")

    report = build_operator_readiness_report(tmp_path)
    sparse = next(check for check in report.checks if check.check_id == "manual_import_templates_are_sparse")
    provenance = next(
        check for check in report.checks if check.check_id == "manual_import_templates_have_provenance"
    )

    assert not report.accepted
    assert not sparse.passed
    assert not provenance.passed
    assert f"gold_set_next_import_template.jsonl row {expected_row} must be object" in sparse.evidence
    assert "manual import template row must be object" in sparse.blocker
    assert "manual import template row must be object" in provenance.blocker


def test_operator_readiness_reports_invalid_lockbox_template_json(tmp_path: Path):
    _copy_registry(tmp_path)
    lockbox_path = tmp_path / "registry/review_batches/lockbox_review_next_import_template.json"
    lockbox_path.write_text("{", encoding="utf-8")

    report = build_operator_readiness_report(tmp_path)
    sparse = next(check for check in report.checks if check.check_id == "manual_import_templates_are_sparse")
    provenance = next(
        check for check in report.checks if check.check_id == "manual_import_templates_have_provenance"
    )
    lockbox = next(
        check for check in report.checks if check.check_id == "lockbox_template_requires_human_decision"
    )

    assert not report.accepted
    assert not sparse.passed
    assert not provenance.passed
    assert not lockbox.passed
    assert "lockbox_review_next_import_template.json must contain valid JSON" in sparse.evidence
    assert "lockbox_review_next_import_template.json must contain valid JSON" in provenance.evidence
    assert "lockbox_review_next_import_template.json must contain valid JSON" in lockbox.blocker


def test_operator_readiness_reports_invalid_source_license_policy_json(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "registry/review_batches/source_license_policy_template.json"
    policy_path.write_text("{", encoding="utf-8")

    report = build_operator_readiness_report(tmp_path)
    sparse = next(check for check in report.checks if check.check_id == "manual_import_templates_are_sparse")
    provenance = next(
        check for check in report.checks if check.check_id == "manual_import_templates_have_provenance"
    )
    policy = next(
        check
        for check in report.checks
        if check.check_id == "source_license_policy_template_requires_human_decision"
    )
    policy_import = next(
        check for check in report.checks if check.check_id == "blank_source_license_policy_import_is_rejected"
    )

    assert not report.accepted
    assert not sparse.passed
    assert not provenance.passed
    assert not policy.passed
    assert not policy_import.passed
    assert "source_license_policy_template.json must contain valid JSON" in sparse.evidence
    assert "source_license_policy_template.json must contain valid JSON" in provenance.evidence
    assert "source_license_policy_template.json must contain valid JSON" in policy.blocker
    assert "accepted=False" in policy_import.evidence


def test_operator_readiness_reports_malformed_manual_review_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    _append_jsonl_value(
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl",
        "not an object",
    )

    report = build_operator_readiness_report(tmp_path)
    batch = next(check for check in report.checks if check.check_id == "manual_batch_templates_match_status")

    assert not report.accepted
    assert not batch.passed
    assert "batch_blockers=" in batch.evidence
    assert "gold-set review row must be object" in batch.blocker


def test_operator_readiness_reports_malformed_lockbox_target(tmp_path: Path):
    _copy_registry(tmp_path)
    target_path = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    target_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    report = build_operator_readiness_report(tmp_path)
    lockbox = next(
        check for check in report.checks if check.check_id == "lockbox_template_requires_human_decision"
    )

    assert not report.accepted
    assert not lockbox.passed
    assert "lockbox target must be object" in lockbox.blocker
    assert "expected_error=lockbox target must be object" in lockbox.evidence


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


def test_operator_readiness_reports_invalid_redaction_artifact_json(tmp_path: Path):
    _copy_registry(tmp_path)
    redaction_path = tmp_path / "registry/compliance/source_text_redaction_report.json"
    redaction_path.write_text("{", encoding="utf-8")

    report = build_operator_readiness_report(tmp_path)
    redaction = next(check for check in report.checks if check.check_id == "source_text_redaction_clean")

    assert not report.accepted
    assert not redaction.passed
    assert "source_text_redaction_report.json must contain valid JSON" in redaction.blocker


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


def test_operator_readiness_rejects_blank_full_gold_set_import(tmp_path: Path):
    _copy_registry(tmp_path)

    report = build_operator_readiness_report(tmp_path)
    full_gold = next(
        check for check in report.checks if check.check_id == "blank_full_gold_set_import_is_rejected"
    )
    import_report = json.loads(
        (tmp_path / "registry/gold_sets/tushare_research_reports.review_import_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert report.accepted
    assert full_gold.passed
    assert import_report["accepted"] is False
    assert import_report["dry_run"] is True
    assert import_report["input_rows"] == 500
    assert import_report["applied_rows"] == 0
    assert import_report["rejected_rows"] == 500
    assert "500 review rows failed validation" in import_report["blockers"]


def test_operator_readiness_rejects_blank_lockbox_import(tmp_path: Path):
    _copy_registry(tmp_path)

    report = build_operator_readiness_report(tmp_path)
    lockbox = next(
        check for check in report.checks if check.check_id == "blank_lockbox_import_is_rejected"
    )
    import_report = json.loads(
        (tmp_path / "registry/lockbox/central_bank_lockbox_review_import_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert report.accepted
    assert lockbox.passed
    assert import_report["accepted"] is False
    assert import_report["applied"] is False
    assert import_report["dry_run"] is True
    assert import_report["next_state"] == "paper_trading"
    assert "result required" in import_report["rejected_reasons"]


def test_write_operator_readiness_report_outputs_registry_artifact(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_operator_readiness_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    dry_run_payload = json.loads(
        (tmp_path / "registry/promotion/rke_promotion_dry_run_report.json").read_text(
            encoding="utf-8"
        )
    )
    bundle_payload = json.loads(
        (tmp_path / "registry/review_batches/manual_review_bundle_manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert result["accepted"] is True
    assert payload["accepted"] is True
    assert payload["failure_count"] == 0
    assert "registry/review_batches/gold_set_full_import_template.jsonl" in payload["generated_paths"]
    assert "registry/gold_sets/tushare_research_reports.review_import_report.json" in payload["generated_paths"]
    assert "registry/review_batches/source_license_policy_import_report.json" in payload["generated_paths"]
    assert "registry/lockbox/central_bank_lockbox_review_import_report.json" in payload["generated_paths"]
    assert "registry/promotion/rke_promotion_dry_run_report.json" in payload["generated_paths"]
    assert "registry/review_batches/manual_review_bundle_manifest.json" in payload["generated_paths"]
    assert dry_run_payload["accepted"] is False
    assert dry_run_payload["mutated_original_registry"] is False
    assert dry_run_payload["production_allowed_after_simulation"] is False
    assert dry_run_payload["after_next_state"] == "paper_trading"
    assert {
        step["review_kind"] for step in dry_run_payload["steps"] if step["provided"]
    } == {"gold_set", "source_license", "lockbox"}
    assert bundle_payload["accepted"] is True
    assert bundle_payload["artifact_count"] >= 16
    assert (tmp_path / "registry/handoffs/rke_operator_readiness_report.json").exists()
    assert (tmp_path / "registry/review_batches/gold_set_full_import_template.jsonl").exists()
    assert (tmp_path / "registry/gold_sets/tushare_research_reports.review_import_report.json").exists()
    assert (tmp_path / "registry/review_batches/source_license_policy_import_report.json").exists()
    assert (tmp_path / "registry/lockbox/central_bank_lockbox_review_import_report.json").exists()
    assert (tmp_path / "registry/promotion/rke_promotion_dry_run_report.json").exists()
    assert (tmp_path / "registry/review_batches/manual_review_bundle_manifest.json").exists()


def test_cli_operator_readiness_writes_report(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("operator-readiness", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert (tmp_path / "registry/handoffs/rke_operator_readiness_report.json").exists()
