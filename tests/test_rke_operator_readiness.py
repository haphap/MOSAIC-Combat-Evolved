from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import mosaic.rke.operator_readiness as operator_readiness_module
from mosaic.rke import (
    build_operator_readiness_report,
    write_manual_review_batches,
    write_operator_readiness_report,
)
from mosaic.rke.cli import main
from mosaic.rke.operator_handoff import build_operator_handoff
from mosaic.rke.operator_readiness import (
    _handoff_command_sequence_complete,
    _promotion_gate_state_consistency,
)
from mosaic.rke.review_progress import write_manual_review_runbook
from mosaic.rke.temp_paths import RKE_OPERATOR_TMP_ENV_PREFIX


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")
    _reset_gold_review_rows(
        dst_root / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    _reset_source_license_review_rows(
        dst_root / "registry/compliance/tushare_license_review_template.jsonl"
    )
    write_manual_review_batches(dst_root)


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _reset_gold_review_rows(path: Path) -> None:
    rows = _load_jsonl(path)
    for row in rows:
        row["manual_claim_text"] = ""
        row["claim_correct"] = None
        row["source_span_supports_claim"] = None
        row["direction_correct"] = None
        row["target_correct"] = None
        row["horizon_correct"] = None
        row["variable_mapping_correct"] = None
        row["unsupported_field_false_grounded"] = None
        row["reviewer"] = ""
        row["review_date"] = ""
        row["review_notes"] = ""
    _write_jsonl(path, rows)


def _reset_source_license_review_rows(path: Path) -> None:
    rows = _load_jsonl(path)
    for row in rows:
        row["approved_for_derived_claim_storage"] = None
        row["approved_for_production_runtime"] = None
        row["reviewer"] = ""
        row["review_date"] = ""
        row["notes"] = ""
    _write_jsonl(path, rows)


def _append_jsonl_value(path: Path, value) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def test_operator_readiness_accepts_current_review_bundle(tmp_path: Path):
    _copy_registry(tmp_path)
    report = build_operator_readiness_report(tmp_path)
    checks = {check.check_id: check for check in report.checks}

    failures = {
        check.check_id: {"evidence": check.evidence, "blocker": check.blocker}
        for check in report.checks
        if not check.passed
    }
    assert report.accepted, failures
    assert report.failure_count == 0
    assert report.check_count == 18
    assert "registry/review_batches/gold_set_review_workbook.md" in report.generated_paths
    assert "registry/review_batches/gold_set_review_assist.jsonl" in report.generated_paths
    assert "registry/review_batches/gold_set_review_assist.md" in report.generated_paths
    assert "registry/review_batches/gold_set_review_evidence.jsonl" in report.generated_paths
    assert "registry/review_batches/gold_set_review_evidence.md" in report.generated_paths
    assert "registry/review_batches/source_license_review_workbook.md" in report.generated_paths
    assert (
        "registry/report_intelligence/analytical_footprint_review_assist.jsonl"
        in report.generated_paths
    )
    assert (
        "registry/report_intelligence/analytical_footprint_review_evidence.jsonl"
        in report.generated_paths
    )
    assert (
        "registry/report_intelligence/analytical_footprint_review_evidence.md"
        in report.generated_paths
    )
    assert (
        "registry/report_intelligence/analytical_footprint_review_workbook.md"
        in report.generated_paths
    )
    assert "registry/review_batches/manual_review_progress_report.json" in report.generated_paths
    assert "registry/review_batches/manual_review_runbook.md" in report.generated_paths
    assert "registry/review_batches/lockbox_review_checklist.md" in report.generated_paths
    assert "registry/review_batches/manual_review_bundle_manifest.json" in report.generated_paths
    assert checks["required_registry_valid"].passed
    assert checks["handoff_ready_for_operator"].passed
    assert checks["handoff_command_sequence_complete"].passed
    assert "steps=19" in checks["handoff_command_sequence_complete"].evidence
    assert checks["manual_review_runbook_promotion_policy_consistent"].passed
    assert (
        "source_license_already_passed="
        in checks["manual_review_runbook_promotion_policy_consistent"].evidence
    )
    assert checks["manual_batch_templates_match_status"].passed
    assert checks["manual_batch_promotion_inputs_separated"].passed
    assert checks["manual_import_templates_are_sparse"].passed
    assert checks["manual_import_templates_have_provenance"].passed
    assert checks["blank_full_gold_set_import_is_rejected"].passed
    assert checks["lockbox_template_requires_human_decision"].passed
    assert checks["blank_lockbox_import_is_rejected"].passed
    assert checks["lockbox_upstream_cli_guard_enforced"].passed
    assert checks["source_license_policy_template_requires_human_decision"].passed
    assert checks["blank_source_license_policy_import_is_rejected"].passed
    assert checks["blank_bundle_dry_run_does_not_promote"].passed
    assert checks["manual_review_bundle_manifest_current"].passed
    assert checks["promotion_gate_state_consistent"].passed
    assert checks["source_text_redaction_clean"].passed


def test_operator_readiness_no_write_uses_generated_temp_support_artifacts(
    tmp_path: Path,
    capsys,
):
    _copy_registry(tmp_path)
    write_manual_review_runbook(tmp_path)
    stale_template_paths = (
        tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl",
        tmp_path / "registry/review_batches/gold_set_full_import_template.jsonl",
    )
    for path in stale_template_paths:
        path.write_text("", encoding="utf-8")

    code = main(("operator-readiness", "--root", str(tmp_path), "--no-write"))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    checks = {check["check_id"]: check for check in output["checks"]}
    assert checks["manual_batch_templates_match_status"]["passed"] is True
    assert checks["manual_import_templates_have_provenance"]["passed"] is True
    assert checks["blank_full_gold_set_import_is_rejected"]["passed"] is True
    for path in stale_template_paths:
        assert path.read_text(encoding="utf-8") == ""


def test_promotion_gate_state_consistency_accepts_future_production_state():
    promotion = SimpleNamespace(
        criteria=tuple(
            SimpleNamespace(criterion_id=f"PG{index:02d}", passed=True)
            for index in range(1, 11)
        ),
        paper_trading_allowed=True,
        staged_production_allowed=True,
        production_allowed=True,
        direct_production_forbidden=False,
        next_state="production",
        blockers=(),
    )

    passed, evidence, blocker = _promotion_gate_state_consistency(promotion)

    assert passed, {"evidence": evidence, "blocker": blocker}


def test_promotion_gate_state_consistency_rejects_bypassed_production_state():
    promotion = SimpleNamespace(
        criteria=tuple(
            SimpleNamespace(criterion_id=f"PG{index:02d}", passed=(index < 9))
            for index in range(1, 11)
        ),
        paper_trading_allowed=True,
        staged_production_allowed=True,
        production_allowed=True,
        direct_production_forbidden=False,
        next_state="production",
        blockers=("lockbox has not passed",),
    )

    passed, evidence, blocker = _promotion_gate_state_consistency(promotion)

    assert not passed
    assert "expected_next_state=staged_production" in evidence
    assert blocker == "promotion gate state is inconsistent with PG01-PG10 criteria"


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


def test_operator_readiness_reports_malformed_json_import_template_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_import = tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl"
    expected_row = len(gold_import.read_text(encoding="utf-8").splitlines()) + 1
    gold_import.write_text(gold_import.read_text(encoding="utf-8") + "{\n", encoding="utf-8")

    report = build_operator_readiness_report(tmp_path)
    batch = next(check for check in report.checks if check.check_id == "manual_batch_templates_match_status")
    sparse = next(check for check in report.checks if check.check_id == "manual_import_templates_are_sparse")
    provenance = next(
        check for check in report.checks if check.check_id == "manual_import_templates_have_provenance"
    )

    assert not report.accepted
    assert not batch.passed
    assert not sparse.passed
    assert not provenance.passed
    assert f"gold_set_next_import_template.jsonl row {expected_row} must contain valid JSON" in batch.blocker
    assert f"gold_set_next_import_template.jsonl row {expected_row} must contain valid JSON" in sparse.blocker
    assert f"gold_set_next_import_template.jsonl row {expected_row} must contain valid JSON" in provenance.blocker


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
    assert import_report["applied_rows"] == 0
    assert import_report["input_rows"] == import_report["rejected_rows"]
    assert import_report["input_rows"] > 0
    assert (
        f"{import_report['input_rows']} review rows failed validation"
        in import_report["blockers"]
    )


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


def test_operator_readiness_detects_lockbox_upstream_guard_drift(tmp_path: Path, monkeypatch):
    _copy_registry(tmp_path)
    monkeypatch.setattr(
        operator_readiness_module,
        "lockbox_upstream_review_blockers",
        lambda _root: (),
    )

    report = build_operator_readiness_report(tmp_path)
    guard = next(
        check
        for check in report.checks
        if check.check_id == "lockbox_upstream_cli_guard_enforced"
    )

    assert not report.accepted
    assert not guard.passed
    assert guard.blocker == "lockbox upstream CLI guard does not match manual gate readiness"


def test_operator_readiness_requires_actions_only_preflight():
    handoff = build_operator_handoff(".")
    stale_preflight = replace(
        handoff.command_sequence[0],
        command=f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke review-progress --root .",
    )
    stale_handoff = replace(
        handoff,
        command_sequence=(stale_preflight, *handoff.command_sequence[1:]),
    )

    sequence_ok, _, sequence_blocker = _handoff_command_sequence_complete(stale_handoff)

    assert not sequence_ok
    assert "review-progress preflight must use the action queue" in sequence_blocker


def test_operator_readiness_requires_no_write_promotion_status_steps():
    handoff = build_operator_handoff(".")
    stale_steps = tuple(
        replace(
            step,
            command=f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke promotion-status --root .",
        )
        if step.step_id == "promotion-status-final"
        else step
        for step in handoff.command_sequence
    )
    stale_handoff = replace(handoff, command_sequence=stale_steps)

    sequence_ok, _, sequence_blocker = _handoff_command_sequence_complete(stale_handoff)

    assert not sequence_ok
    assert "promotion-status-final must use promotion-status --no-write" in sequence_blocker


def test_operator_readiness_detects_stale_runbook_promotion_policy(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    write_operator_readiness_report(tmp_path)
    runbook_path = tmp_path / "registry/review_batches/manual_review_runbook.md"
    runbook = runbook_path.read_text(encoding="utf-8")
    stale_runbook = runbook.replace(
        " --license-input registry/review_batches/source_license_policy_import.jsonl ",
        " ",
        1,
    )
    assert stale_runbook != runbook
    runbook_path.write_text(stale_runbook, encoding="utf-8")

    report = build_operator_readiness_report(
        tmp_path,
        write_supporting_artifacts=False,
    )
    runbook_check = next(
        check
        for check in report.checks
        if check.check_id == "manual_review_runbook_promotion_policy_consistent"
    )

    assert not report.accepted
    assert not runbook_check.passed
    assert "license_input=False" in runbook_check.evidence
    assert "must be built and passed" in runbook_check.blocker


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
    assert "registry/review_batches/gold_set_review_workbook.md" in payload["generated_paths"]
    assert "registry/review_batches/gold_set_review_assist.jsonl" in payload["generated_paths"]
    assert "registry/review_batches/gold_set_review_assist.md" in payload["generated_paths"]
    assert "registry/review_batches/gold_set_review_evidence.jsonl" in payload["generated_paths"]
    assert "registry/review_batches/gold_set_review_evidence.md" in payload["generated_paths"]
    assert "registry/review_batches/source_license_review_workbook.md" in payload["generated_paths"]
    assert (
        "registry/report_intelligence/analytical_footprint_review_assist.jsonl"
        in payload["generated_paths"]
    )
    assert (
        "registry/report_intelligence/analytical_footprint_review_evidence.jsonl"
        in payload["generated_paths"]
    )
    assert (
        "registry/report_intelligence/analytical_footprint_review_evidence.md"
        in payload["generated_paths"]
    )
    assert (
        "registry/report_intelligence/analytical_footprint_review_workbook.md"
        in payload["generated_paths"]
    )
    assert "registry/review_batches/manual_review_progress_report.json" in payload["generated_paths"]
    assert "registry/review_batches/manual_review_runbook.md" in payload["generated_paths"]
    assert "registry/review_batches/lockbox_review_checklist.md" in payload["generated_paths"]
    assert "registry/gold_sets/tushare_research_reports.review_import_report.json" in payload["generated_paths"]
    assert "registry/review_batches/source_license_policy_import_report.json" in payload["generated_paths"]
    assert "registry/lockbox/central_bank_lockbox_review_import_report.json" in payload["generated_paths"]
    assert "registry/review_batches/manual_review_bundle_manifest.json" in payload["generated_paths"]
    assert dry_run_payload["mutated_original_registry"] is False
    steps = {step["review_kind"]: step for step in dry_run_payload["steps"]}
    if dry_run_payload["accepted"]:
        assert dry_run_payload["production_allowed_after_simulation"] is True
        assert dry_run_payload["after_next_state"] == "production"
        assert {step["result"] for step in steps.values()} == {"already_applied"}
    else:
        assert dry_run_payload["production_allowed_after_simulation"] is False
        assert dry_run_payload["after_next_state"] == "paper_trading"
        assert steps["gold_set"]["result"] == "not_provided"
        assert steps["footprint_review"]["result"] == "not_provided"
        assert steps["source_license"]["result"] == "already_applied"
        assert steps["lockbox"]["result"] == "not_provided"
    assert bundle_payload["accepted"] is True
    assert bundle_payload["artifact_count"] >= 11
    assert (tmp_path / "registry/handoffs/rke_operator_readiness_report.json").exists()
    assert (tmp_path / "registry/review_batches/gold_set_full_import_template.jsonl").exists()
    assert (tmp_path / "registry/review_batches/gold_set_review_workbook.md").exists()
    assert (tmp_path / "registry/review_batches/gold_set_review_assist.jsonl").exists()
    assert (tmp_path / "registry/review_batches/gold_set_review_assist.md").exists()
    assert (tmp_path / "registry/review_batches/source_license_review_workbook.md").exists()
    assert (tmp_path / "registry/review_batches/manual_review_progress_report.json").exists()
    assert (tmp_path / "registry/review_batches/manual_review_runbook.md").exists()
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


def test_cli_operator_readiness_no_write_preserves_existing_artifacts(
    tmp_path: Path, capsys
):
    _copy_registry(tmp_path)
    main(("operator-readiness", "--root", str(tmp_path)))
    capsys.readouterr()
    tracked_paths = [
        tmp_path / "registry/handoffs/rke_operator_readiness_report.json",
        tmp_path / "registry/handoffs/rke_operator_handoff.json",
        tmp_path / "registry/review_batches/manual_review_progress_report.json",
        tmp_path / "registry/review_batches/manual_review_runbook.md",
        tmp_path / "registry/review_batches/manual_review_bundle_manifest.json",
        tmp_path / "registry/gold_sets/tushare_research_reports.review_import_report.json",
        tmp_path / "registry/review_batches/source_license_policy_import_report.json",
        tmp_path / "registry/lockbox/central_bank_lockbox_review_import_report.json",
        tmp_path / "registry/promotion/rke_promotion_dry_run_report.json",
    ]
    before_mtimes = {path: path.stat().st_mtime_ns for path in tracked_paths}

    code = main(("operator-readiness", "--root", str(tmp_path), "--no-write"))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert {path: path.stat().st_mtime_ns for path in tracked_paths} == before_mtimes


def test_cli_operator_readiness_no_write_skips_private_source_blobs(
    tmp_path: Path,
    capsys,
):
    _copy_registry(tmp_path)
    main(("operator-readiness", "--root", str(tmp_path)))
    capsys.readouterr()
    for relative_path in (
        "registry/sources/tushare_research_reports.jsonl",
        "registry/sources/tushare_research_reports.manifest.json",
        "registry/sources/tushare_research_reports.gold_candidates.jsonl",
    ):
        (tmp_path / relative_path).unlink()

    code = main(("operator-readiness", "--root", str(tmp_path), "--no-write"))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
