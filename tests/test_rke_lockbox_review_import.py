from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    apply_gold_set_review_import,
    apply_lockbox_review_import,
    apply_source_license_review_import,
    build_production_promotion_gate_report,
)
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


def _write_json(path: Path, row: dict) -> None:
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _passed_lockbox_review() -> dict:
    return {
        "experiment_family_id": "FAM-CB-LIQUIDITY-2026Q2",
        "experiment_id": "EXP-CB-20260605-0001",
        "opened_at": "2026-06-06T10:00:00+08:00",
        "opened_by": "quant_research",
        "open_count": 1,
        "result": "passed",
        "parameter_search_after_open": False,
        "rule_design_after_open": False,
        "notes": "fixture lockbox pass",
    }


def _gold_import_rows(root: Path) -> list[dict]:
    return [
        {
            "claim_id": row["claim_id"],
            "manual_claim_text": row.get("proposed_claim_text") or "manual claim",
            "claim_correct": True,
            "source_span_supports_claim": True,
            "direction_correct": True,
            "variable_mapping_correct": True,
            "unsupported_field_false_grounded": False,
            "reviewer": "reviewer-a",
            "review_date": "2026-06-06",
            "review_notes": "fixture approval",
        }
        for row in _load_jsonl(root / "registry/gold_sets/tushare_research_reports.review_template.jsonl")
    ]


def _license_import_rows(root: Path) -> list[dict]:
    return [
        {
            "source_id": row["source_id"],
            "approved_for_derived_claim_storage": True,
            "approved_for_production_runtime": True,
            "reviewer": "compliance",
            "review_date": "2026-06-06",
            "notes": "fixture approval",
        }
        for row in _load_jsonl(root / "registry/compliance/tushare_license_review_template.jsonl")
    ]


def test_apply_lockbox_review_import_dry_run_does_not_modify_target(tmp_path: Path):
    _copy_registry(tmp_path)
    target = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    original = target.read_text(encoding="utf-8")
    import_path = tmp_path / "lockbox_review.json"
    _write_json(import_path, _passed_lockbox_review())

    report = apply_lockbox_review_import(tmp_path, import_path, dry_run=True)

    assert report.accepted
    assert not report.applied
    assert report.production_allowed
    assert target.read_text(encoding="utf-8") == original


def test_apply_lockbox_review_import_records_failed_review_without_promotion(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_failed.json"
    failed = {**_passed_lockbox_review(), "result": "failed", "notes": "fixture lockbox failure"}
    _write_json(import_path, failed)

    report = apply_lockbox_review_import(tmp_path, import_path)
    promotion = build_production_promotion_gate_report(tmp_path)

    assert report.accepted
    assert report.applied
    assert not report.production_allowed
    assert "lockbox failed" in report.policy_reasons
    assert not promotion.production_allowed
    assert "lockbox failed" in " ".join(promotion.blockers)


def test_apply_lockbox_review_import_rejects_mismatched_experiment(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_bad.json"
    bad = {**_passed_lockbox_review(), "experiment_id": "EXP-OTHER"}
    _write_json(import_path, bad)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert not report.applied
    assert any("experiment_id" in reason for reason in report.rejected_reasons)


def test_apply_lockbox_review_import_rejects_missing_experiment_identity(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_missing_identity.json"
    bad = _passed_lockbox_review()
    bad.pop("experiment_id")
    _write_json(import_path, bad)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert not report.applied
    assert "experiment_id required" in report.rejected_reasons


def test_lockbox_review_import_allows_production_after_manual_gates(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_import = tmp_path / "gold_import.jsonl"
    license_import = tmp_path / "license_import.jsonl"
    lockbox_import = tmp_path / "lockbox_review.json"
    _write_jsonl(gold_import, _gold_import_rows(tmp_path))
    _write_jsonl(license_import, _license_import_rows(tmp_path))
    _write_json(lockbox_import, _passed_lockbox_review())

    apply_gold_set_review_import(tmp_path, gold_import)
    apply_source_license_review_import(tmp_path, license_import)
    lockbox_report = apply_lockbox_review_import(tmp_path, lockbox_import)
    promotion = build_production_promotion_gate_report(tmp_path)

    assert lockbox_report.accepted
    assert promotion.staged_production_allowed
    assert promotion.production_allowed
    assert promotion.next_state == "production"


def test_cli_apply_lockbox_review_import(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review.json"
    _write_json(import_path, _passed_lockbox_review())

    code = main(("apply-lockbox-review", "--root", str(tmp_path), "--input", str(import_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["applied"] is True
    assert (tmp_path / "registry/lockbox/central_bank_lockbox_review_import_report.json").exists()
