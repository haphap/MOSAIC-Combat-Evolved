from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mosaic.rke import (
    build_lockbox_review_import_template,
    build_operator_handoff,
    write_operator_handoff,
)
from mosaic.rke.cli import main
from mosaic.rke.review_progress import (
    build_manual_review_progress,
    manual_review_gate_batch_overview,
)
from mosaic.rke.temp_paths import RKE_OPERATOR_TMP_ENV_PREFIX


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")
    _reset_lockbox_target(dst_root)


def _reset_lockbox_target(root: Path) -> None:
    target = root / "registry/lockbox/central_bank_lockbox_review.json"
    row = json.loads(target.read_text(encoding="utf-8"))
    row.update(
        {
            "open_count": 0,
            "opened_at": "",
            "opened_by": "",
            "parameter_search_after_open": False,
            "result": "not_opened",
            "rule_design_after_open": False,
        }
    )
    target.write_text(
        json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_operator_handoff_summarizes_remaining_manual_gates():
    handoff = build_operator_handoff(".")
    progress = build_manual_review_progress(".")
    progress_gold = next(gate for gate in progress.gates if gate.review_kind == "gold_set")
    progress_footprint = next(
        gate for gate in progress.gates if gate.review_kind == "footprint_review"
    )
    expected_gold_pending_rows = int(
        progress_gold.current_batch_status.get("pending_rows") or 0
    )
    expected_gold_evidence_command = progress_gold.next_batch_commands.get(
        "evidence",
        (
            f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke write-gold-review-evidence "
            "--root . --limit 50 --offset 0 --review-input "
            "registry/review_batches/gold_set_reviewed.jsonl"
        ),
    )
    expected_gold_batch_overview = manual_review_gate_batch_overview(progress_gold)
    expected_footprint_batch_overview = manual_review_gate_batch_overview(
        progress_footprint
    )

    assert handoff.handoff_id == "RKE-OPERATOR-HANDOFF-20260606"
    assert handoff.paper_trading_allowed is True
    assert handoff.production_allowed is True
    assert handoff.direct_production_forbidden is False
    assert handoff.ready_for_operator_review is True
    assert handoff.run_order == tuple(step.step_id for step in handoff.command_sequence)
    assert handoff.run_order[:5] == (
        "review-progress-preflight",
        "prepare-gold-review",
        "write-gold-review-evidence",
        "fill-gold-review",
        "dry-run-gold-review",
    )
    assert handoff.run_order[-3:] == (
        "promotion-dry-run",
        "apply-lockbox-review",
        "promotion-status-final",
    )
    assert "promotion-dry-run" in handoff.promotion_dry_run_command
    assert handoff.command_sequence[0].command == (
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke review-progress --root . "
        "--actions-only --no-write"
    )
    assert not any(
        step.phase == "source_license" for step in handoff.command_sequence
    )
    assert any(
        step.step_id == "promotion-status-before-lockbox"
        and step.command
        == f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke promotion-status --root . --no-write"
        for step in handoff.command_sequence
    )
    assert any(
        step.step_id == "write-footprint-review-assist"
        and step.command
        == (
            f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke write-footprint-review-assist "
            "--root . --review-input "
            "registry/report_intelligence/analytical_footprint_review_batch.jsonl"
        )
        for step in handoff.command_sequence
    )
    assert any(
        step.step_id == "write-footprint-review-evidence"
        and step.command.startswith(
            f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke write-footprint-review-evidence "
            "--root . --limit "
        )
        and " --offset 0 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl"
        in step.command
        for step in handoff.command_sequence
    )
    assert any(
        step.step_id == "write-gold-review-evidence"
        and step.command == expected_gold_evidence_command
        for step in handoff.command_sequence
    )
    assert {gate.review_kind for gate in handoff.gates} == {
        "gold_set",
        "footprint_review",
        "source_license",
        "lockbox",
    }
    gold = next(gate for gate in handoff.gates if gate.review_kind == "gold_set")
    license_gate = next(
        gate for gate in handoff.gates if gate.review_kind == "source_license"
    )
    footprint = next(
        gate for gate in handoff.gates if gate.review_kind == "footprint_review"
    )
    lockbox = next(gate for gate in handoff.gates if gate.review_kind == "lockbox")
    assert gold.pending_rows == expected_gold_pending_rows
    assert gold.passed
    assert gold.blocker == ""
    assert (
        gold.full_import_template_path
        == "registry/review_batches/gold_set_full_import_template.jsonl"
    )
    assert gold.prepare_command == (
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke prepare-gold-review --root . --full"
    )
    assert gold.reviewed_policy_path == "registry/review_batches/gold_set_full_reviewed.jsonl"
    assert gold.review_aids["promotion_import_path"] == (
        "registry/review_batches/gold_set_full_reviewed.jsonl"
    )
    assert "manual_claim_text" in gold.field_contract["required_fields"]
    assert gold.batch_overview == expected_gold_batch_overview
    assert "gold_set_full_reviewed.jsonl" in gold.dry_run_command
    assert "gold_set_full_reviewed.jsonl" in handoff.promotion_dry_run_command
    assert "gold_set_full_import_template.jsonl" not in handoff.promotion_dry_run_command
    assert gold.exported_rows == expected_gold_pending_rows
    assert footprint.pending_rows == progress_footprint.pending_rows
    assert footprint.passed is progress_footprint.ready_for_promotion
    assert (
        footprint.import_template_path
        == "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    assert (
        footprint.reviewed_policy_path
        == "registry/report_intelligence/analytical_footprint_reviewed.jsonl"
    )
    assert "prepare-footprint-review" in footprint.prepare_command
    assert footprint.review_aids["fill_import_path"] == (
        "registry/report_intelligence/analytical_footprint_review_batch.jsonl"
    )
    assert "review_notes" in footprint.field_contract["required_fields"]
    assert footprint.batch_overview == expected_footprint_batch_overview
    if "promotion_input_path" in footprint.batch_overview:
        assert footprint.batch_overview["promotion_input_path"] == (
            "registry/report_intelligence/analytical_footprint_reviewed.jsonl"
        )
    assert (
        footprint.workbook_path
        == "registry/report_intelligence/analytical_footprint_review_workbook.md"
    )
    assert "apply-footprint-review" in footprint.dry_run_command
    assert "analytical_footprint_reviewed.jsonl" in footprint.dry_run_command
    assert "analytical_footprint_reviewed.jsonl" in handoff.promotion_dry_run_command
    assert "gold_set_reviewed.jsonl" in gold.operator_note
    assert "analytical_footprint_review_batch.jsonl" in footprint.operator_note
    assert license_gate.pending_rows == 0
    assert (
        license_gate.workbook_path
        == "registry/review_batches/source_license_review_workbook.md"
    )
    assert (
        license_gate.policy_template_path
        == "registry/review_batches/source_license_policy_template.json"
    )
    assert (
        license_gate.reviewed_policy_path
        == "registry/review_batches/source_license_policy_reviewed.json"
    )
    assert license_gate.prepare_command == (
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke prepare-license-policy-review --root ."
    )
    assert license_gate.review_aids["fill_policy_path"] == (
        "registry/review_batches/source_license_policy_reviewed.json"
    )
    assert license_gate.batch_overview == {}
    assert "approved_for_production_runtime" in license_gate.field_contract[
        "required_fields"
    ]
    assert "source_license_policy_reviewed.json" in license_gate.dry_run_command
    assert "build-license-review-import" in license_gate.apply_command
    assert "source_license_policy_reviewed.json" in license_gate.apply_command
    assert "source_license_policy_reviewed.json" not in handoff.promotion_dry_run_command
    assert "--license-input" not in handoff.promotion_dry_run_command
    assert (
        lockbox.import_template_path
        == "registry/review_batches/lockbox_review_next_import_template.json"
    )
    assert lockbox.workbook_path == "registry/review_batches/lockbox_review_checklist.md"
    assert lockbox.reviewed_policy_path == "registry/review_batches/lockbox_reviewed.json"
    assert lockbox.prepare_command == (
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke prepare-lockbox-review --root ."
    )
    assert lockbox.review_aids["fill_import_path"] == (
        "registry/review_batches/lockbox_reviewed.json"
    )
    assert lockbox.field_contract["allowed_results"] == ["failed", "passed"]
    assert lockbox.batch_overview == {}
    assert "apply-lockbox-review" in lockbox.dry_run_command
    assert "lockbox_reviewed.json" in lockbox.dry_run_command
    assert "lockbox_reviewed.json" in handoff.promotion_dry_run_command
    assert "lockbox_review_next_import_template.json" not in handoff.promotion_dry_run_command
    assert "gold-set, analytical-footprint, and source-license gates pass" in (
        lockbox.operator_note
    )


def test_lockbox_review_import_template_requires_human_decision():
    template = build_lockbox_review_import_template(".")

    assert template["experiment_family_id"] == "FAM-CB-LIQUIDITY-2026Q2"
    assert template["experiment_id"] == "EXP-CB-20260605-0001"
    assert (
        template["target_review_path"]
        == "registry/lockbox/central_bank_lockbox_review.json"
    )
    assert (
        template["review_context_ref"]
        == "registry/evaluation/lockbox/lockbox_policy.json"
    )
    assert template["target_row_hash"].startswith("sha256:")
    assert template["review_context_hash"].startswith("sha256:")
    assert template["result"] == ""
    assert template["opened_at"] == ""
    assert template["opened_by"] == ""
    assert template["open_count"] is None
    assert template["parameter_search_after_open"] is False
    assert template["rule_design_after_open"] is False


def test_lockbox_review_import_template_rejects_non_object_target(tmp_path: Path):
    _copy_registry(tmp_path)
    target_path = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    target_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(ValueError, match="lockbox target must be object"):
        build_lockbox_review_import_template(tmp_path)


def test_lockbox_review_import_template_rejects_invalid_json_target(tmp_path: Path):
    _copy_registry(tmp_path)
    target_path = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    target_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="lockbox target must contain valid JSON"):
        build_lockbox_review_import_template(tmp_path)


def test_write_operator_handoff_surfaces_bad_lockbox_template_inputs(tmp_path: Path):
    _copy_registry(tmp_path)
    target_path = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    target_path.write_text("{not valid json", encoding="utf-8")

    paths = write_operator_handoff(tmp_path)
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    lockbox_template = json.loads(
        Path(paths["lockbox_import_template"]).read_text(encoding="utf-8")
    )
    lockbox_gate = next(
        gate for gate in payload["gates"] if gate["review_kind"] == "lockbox"
    )

    assert payload["ready_for_operator_review"] is True
    assert lockbox_template["template_status"] == "invalid"
    assert (
        "lockbox target must contain valid JSON" in lockbox_template["template_blocker"]
    )
    assert "lockbox review must contain valid JSON" in lockbox_gate["blocker"]


def test_write_operator_handoff_outputs_json_markdown_and_lockbox_template(
    tmp_path: Path,
):
    _copy_registry(tmp_path)

    paths = write_operator_handoff(tmp_path)
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    progress_payload = json.loads(
        Path(paths["manual_review_progress_report"]).read_text(encoding="utf-8")
    )
    lockbox_template = json.loads(
        Path(paths["lockbox_import_template"]).read_text(encoding="utf-8")
    )
    policy_template = json.loads(
        Path(paths["source_license_policy_template"]).read_text(encoding="utf-8")
    )
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

    assert payload["ready_for_operator_review"] is True
    assert payload["production_allowed"] is False
    assert "promotion-dry-run" in payload["promotion_dry_run_command"]
    assert payload["run_order"] == [step["step_id"] for step in payload["command_sequence"]]
    assert payload["run_order"][0] == "review-progress-preflight"
    assert payload["command_sequence"][0]["command"] == (
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke review-progress --root . "
        "--actions-only --no-write"
    )
    assert payload["run_order"][-1] == "promotion-status-final"
    assert "gold_set_full_reviewed.jsonl" in payload["promotion_dry_run_command"]
    assert "source_license_policy_import.jsonl" not in payload["promotion_dry_run_command"]
    assert "source_license_policy_reviewed.json" not in payload["promotion_dry_run_command"]
    assert "analytical_footprint_reviewed.jsonl" in payload["promotion_dry_run_command"]
    assert "lockbox_reviewed.json" in payload["promotion_dry_run_command"]
    license_gate = next(gate for gate in payload["gates"] if gate["review_kind"] == "source_license")
    gold_gate = next(gate for gate in payload["gates"] if gate["review_kind"] == "gold_set")
    footprint_gate = next(gate for gate in payload["gates"] if gate["review_kind"] == "footprint_review")
    lockbox_gate = next(gate for gate in payload["gates"] if gate["review_kind"] == "lockbox")
    progress_batch_overview_by_kind = {
        gate["review_kind"]: gate["batch_overview"]
        for gate in progress_payload["gates"]
    }
    assert gold_gate["prepare_command"] == (
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke prepare-gold-review --root . --full"
    )
    assert gold_gate["reviewed_policy_path"] == "registry/review_batches/gold_set_full_reviewed.jsonl"
    assert gold_gate["review_aids"]["promotion_import_path"] == (
        "registry/review_batches/gold_set_full_reviewed.jsonl"
    )
    assert "manual_claim_text" in gold_gate["field_contract"]["required_fields"]
    assert (
        gold_gate["batch_overview"]
        == progress_batch_overview_by_kind["gold_set"]
    )
    assert license_gate["prepare_command"] == (
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke prepare-license-policy-review --root ."
    )
    assert license_gate["review_aids"]["fill_policy_path"] == (
        "registry/review_batches/source_license_policy_reviewed.json"
    )
    assert "approved_for_production_runtime" in license_gate["field_contract"][
        "required_fields"
    ]
    assert license_gate["batch_overview"] == {}
    assert "build-license-review-import" in license_gate["apply_command"]
    assert "source_license_policy_reviewed.json" in license_gate["apply_command"]
    assert "prepare-footprint-review" in footprint_gate["prepare_command"]
    assert footprint_gate["review_aids"]["fill_import_path"] == (
        "registry/report_intelligence/analytical_footprint_review_batch.jsonl"
    )
    assert "review_notes" in footprint_gate["field_contract"]["required_fields"]
    assert (
        footprint_gate["batch_overview"]
        == progress_batch_overview_by_kind["footprint_review"]
    )
    assert (
        footprint_gate["workbook_path"]
        == "registry/report_intelligence/analytical_footprint_review_workbook.md"
    )
    assert "apply-footprint-review" in footprint_gate["dry_run_command"]
    assert (
        footprint_gate["reviewed_policy_path"]
        == "registry/report_intelligence/analytical_footprint_reviewed.jsonl"
    )
    assert "gold_set_reviewed.jsonl" in gold_gate["operator_note"]
    assert "analytical_footprint_review_batch.jsonl" in footprint_gate["operator_note"]
    assert lockbox_gate["prepare_command"] == (
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke prepare-lockbox-review --root ."
    )
    assert lockbox_gate["review_aids"]["fill_import_path"] == (
        "registry/review_batches/lockbox_reviewed.json"
    )
    assert lockbox_gate["field_contract"]["allowed_results"] == ["failed", "passed"]
    assert lockbox_gate["batch_overview"] == {}
    assert lockbox_gate["workbook_path"] == "registry/review_batches/lockbox_review_checklist.md"
    assert lockbox_gate["reviewed_policy_path"] == "registry/review_batches/lockbox_reviewed.json"
    assert "gold-set, analytical-footprint, and source-license gates pass" in (
        lockbox_gate["operator_note"]
    )
    assert len(payload["gates"]) == 4
    assert lockbox_template["result"] == ""
    assert lockbox_template["target_row_hash"].startswith("sha256:")
    assert lockbox_template["review_context_hash"].startswith("sha256:")
    assert policy_template["approved_for_production_runtime"] is None
    assert policy_template["matched_row_count"] == 0
    assert paths["source_license_review_workbook"].endswith(
        "registry/review_batches/source_license_review_workbook.md"
    )
    assert (
        tmp_path / "registry/review_batches/source_license_review_workbook.md"
    ).exists()
    assert paths["manual_review_progress_report"].endswith(
        "registry/review_batches/manual_review_progress_report.json"
    )
    assert (
        tmp_path / "registry/review_batches/manual_review_progress_report.json"
    ).exists()
    assert license_gate["workbook_path"] == "registry/review_batches/source_license_review_workbook.md"
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
    assert paths["lockbox_review_checklist"].endswith(
        "registry/review_batches/lockbox_review_checklist.md"
    )
    lockbox_checklist = (
        tmp_path / "registry/review_batches/lockbox_review_checklist.md"
    )
    assert lockbox_checklist.exists()
    assert "one-time final holdout gate" in lockbox_checklist.read_text(
        encoding="utf-8"
    )
    assert paths["manual_review_runbook"].endswith(
        "registry/review_batches/manual_review_runbook.md"
    )
    assert (tmp_path / "registry/review_batches/manual_review_runbook.md").exists()
    assert "source_license_policy_template.json" in markdown
    assert "source_license_review_workbook.md" in markdown
    assert "manual_review_runbook.md" in markdown
    assert "Review aids:" in markdown
    assert "Field contract:" in markdown
    assert "Batch overview:" in markdown
    assert "current_batch_review_field_workload:" not in markdown
    assert "lockbox has not been opened" in markdown
    assert "manual_claim_text" in markdown
    assert "analytical_footprint_review_batch.jsonl" in markdown
    assert "## Command Sequence" in markdown
    assert "fill-source-license-policy" not in markdown
    assert "promotion-status-before-lockbox" in markdown
    assert "source_license_policy_reviewed.json" in markdown
    assert "build-license-review-import" in markdown
    assert "prepare-license-policy-review" in markdown
    assert "prepare-gold-review" in markdown
    assert "prepare-lockbox-review" in markdown
    assert "gold-set, analytical-footprint, and source-license gates pass" in markdown
    assert "gold_set_review_workbook.md" in markdown
    assert "gold_set_review_assist.md" in markdown
    assert "gold_set_review_evidence.md" in markdown
    assert "gold_set_full_reviewed.jsonl" in markdown
    assert "gold_set_full_import_template.jsonl" in markdown
    assert "lockbox_review_checklist.md" in markdown
    assert "lockbox_reviewed.json" in markdown
    assert markdown.startswith("# RKE Operator Handoff")


def test_cli_operator_handoff_writes_package(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("operator-handoff", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["handoff"]["ready_for_operator_review"] is True
    assert output["handoff"]["production_allowed"] is False
    assert (tmp_path / "registry/handoffs/rke_operator_handoff.json").exists()
    assert (tmp_path / "registry/handoffs/rke_operator_handoff.md").exists()
    assert (
        tmp_path / "registry/review_batches/gold_set_full_import_template.jsonl"
    ).exists()
    assert (tmp_path / "registry/review_batches/gold_set_review_workbook.md").exists()
    assert (tmp_path / "registry/review_batches/gold_set_review_assist.jsonl").exists()
    assert (tmp_path / "registry/review_batches/gold_set_review_assist.md").exists()
    assert (
        tmp_path / "registry/review_batches/lockbox_review_next_import_template.json"
    ).exists()
    assert (
        tmp_path / "registry/review_batches/source_license_policy_template.json"
    ).exists()
    assert (
        tmp_path / "registry/review_batches/source_license_review_workbook.md"
    ).exists()
    assert (
        tmp_path / "registry/review_batches/manual_review_progress_report.json"
    ).exists()
    assert (tmp_path / "registry/review_batches/manual_review_runbook.md").exists()
