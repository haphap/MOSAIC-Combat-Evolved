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


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")


def test_operator_handoff_summarizes_remaining_manual_gates():
    handoff = build_operator_handoff(".")

    assert handoff.handoff_id == "RKE-OPERATOR-HANDOFF-20260606"
    assert handoff.paper_trading_allowed is True
    assert handoff.production_allowed is False
    assert handoff.direct_production_forbidden is True
    assert handoff.ready_for_operator_review is True
    assert handoff.run_order == (
        "promotion-dry-run",
        "gold_set",
        "source_license",
        "promotion-status",
        "lockbox",
    )
    assert "promotion-dry-run" in handoff.promotion_dry_run_command
    assert {gate.review_kind for gate in handoff.gates} == {
        "gold_set",
        "source_license",
        "lockbox",
    }
    gold = next(gate for gate in handoff.gates if gate.review_kind == "gold_set")
    license_gate = next(
        gate for gate in handoff.gates if gate.review_kind == "source_license"
    )
    lockbox = next(gate for gate in handoff.gates if gate.review_kind == "lockbox")
    assert gold.pending_rows == 500
    assert (
        gold.full_import_template_path
        == "registry/review_batches/gold_set_full_import_template.jsonl"
    )
    assert gold.prepare_command == "mosaic-rke prepare-gold-review --root . --full"
    assert gold.reviewed_policy_path == "registry/review_batches/gold_set_full_reviewed.jsonl"
    assert gold.exported_rows == 500
    assert "gold_set_full_reviewed.jsonl" in gold.dry_run_command
    assert "gold_set_full_reviewed.jsonl" in handoff.promotion_dry_run_command
    assert "gold_set_full_import_template.jsonl" not in handoff.promotion_dry_run_command
    assert license_gate.pending_rows == 9812
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
    assert license_gate.prepare_command == "mosaic-rke prepare-license-policy-review --root ."
    assert "source_license_policy_reviewed.json" in license_gate.dry_run_command
    assert "source_license_policy_reviewed.json" in handoff.promotion_dry_run_command
    assert (
        lockbox.import_template_path
        == "registry/review_batches/lockbox_review_next_import_template.json"
    )
    assert lockbox.reviewed_policy_path == "registry/review_batches/lockbox_reviewed.json"
    assert lockbox.prepare_command == "mosaic-rke prepare-lockbox-review --root ."
    assert "apply-lockbox-review" in lockbox.dry_run_command
    assert "lockbox_reviewed.json" in lockbox.dry_run_command
    assert "lockbox_reviewed.json" in handoff.promotion_dry_run_command
    assert "lockbox_review_next_import_template.json" not in handoff.promotion_dry_run_command


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
    assert "gold_set_full_reviewed.jsonl" in payload["promotion_dry_run_command"]
    assert "source_license_policy_import.jsonl" in payload["promotion_dry_run_command"]
    assert "source_license_policy_reviewed.json" in payload["promotion_dry_run_command"]
    assert "lockbox_reviewed.json" in payload["promotion_dry_run_command"]
    license_gate = next(gate for gate in payload["gates"] if gate["review_kind"] == "source_license")
    gold_gate = next(gate for gate in payload["gates"] if gate["review_kind"] == "gold_set")
    lockbox_gate = next(gate for gate in payload["gates"] if gate["review_kind"] == "lockbox")
    assert gold_gate["prepare_command"] == "mosaic-rke prepare-gold-review --root . --full"
    assert gold_gate["reviewed_policy_path"] == "registry/review_batches/gold_set_full_reviewed.jsonl"
    assert license_gate["prepare_command"] == "mosaic-rke prepare-license-policy-review --root ."
    assert lockbox_gate["prepare_command"] == "mosaic-rke prepare-lockbox-review --root ."
    assert lockbox_gate["reviewed_policy_path"] == "registry/review_batches/lockbox_reviewed.json"
    assert len(payload["gates"]) == 3
    assert lockbox_template["result"] == ""
    assert lockbox_template["target_row_hash"].startswith("sha256:")
    assert lockbox_template["review_context_hash"].startswith("sha256:")
    assert policy_template["approved_for_production_runtime"] is None
    assert policy_template["matched_row_count"] == 9812
    assert paths["source_license_review_workbook"].endswith(
        "registry/review_batches/source_license_review_workbook.md"
    )
    assert (
        tmp_path / "registry/review_batches/source_license_review_workbook.md"
    ).exists()
    assert license_gate["workbook_path"] == "registry/review_batches/source_license_review_workbook.md"
    assert "registry/review_batches/source_license_review_workbook.md" in payload["generated_paths"]
    assert "source_license_policy_template.json" in markdown
    assert "source_license_review_workbook.md" in markdown
    assert "source_license_policy_reviewed.json" in markdown
    assert "prepare-license-policy-review" in markdown
    assert "prepare-gold-review" in markdown
    assert "prepare-lockbox-review" in markdown
    assert "gold_set_review_workbook.md" in markdown
    assert "gold_set_full_reviewed.jsonl" in markdown
    assert "gold_set_full_import_template.jsonl" in markdown
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
    assert (
        tmp_path / "registry/review_batches/lockbox_review_next_import_template.json"
    ).exists()
    assert (
        tmp_path / "registry/review_batches/source_license_policy_template.json"
    ).exists()
    assert (
        tmp_path / "registry/review_batches/source_license_review_workbook.md"
    ).exists()
