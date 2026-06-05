from __future__ import annotations

import json
import shutil
from pathlib import Path

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
    license_gate = next(gate for gate in handoff.gates if gate.review_kind == "source_license")
    lockbox = next(gate for gate in handoff.gates if gate.review_kind == "lockbox")
    assert gold.pending_rows == 500
    assert license_gate.pending_rows == 9812
    assert lockbox.import_template_path == "registry/review_batches/lockbox_review_next_import_template.json"
    assert "apply-lockbox-review" in lockbox.dry_run_command


def test_lockbox_review_import_template_requires_human_decision():
    template = build_lockbox_review_import_template(".")

    assert template["experiment_family_id"] == "FAM-CB-LIQUIDITY-2026Q2"
    assert template["experiment_id"] == "EXP-CB-20260605-0001"
    assert template["result"] == ""
    assert template["opened_at"] == ""
    assert template["opened_by"] == ""
    assert template["open_count"] is None
    assert template["parameter_search_after_open"] is False
    assert template["rule_design_after_open"] is False


def test_write_operator_handoff_outputs_json_markdown_and_lockbox_template(tmp_path: Path):
    _copy_registry(tmp_path)

    paths = write_operator_handoff(tmp_path)
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    lockbox_template = json.loads(
        Path(paths["lockbox_import_template"]).read_text(encoding="utf-8")
    )
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

    assert payload["ready_for_operator_review"] is True
    assert payload["production_allowed"] is False
    assert "promotion-dry-run" in payload["promotion_dry_run_command"]
    assert len(payload["gates"]) == 3
    assert lockbox_template["result"] == ""
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
    assert (tmp_path / "registry/review_batches/lockbox_review_next_import_template.json").exists()
