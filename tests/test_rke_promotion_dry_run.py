from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_lockbox_review_import_template,
    build_promotion_dry_run_report,
    write_promotion_dry_run_report,
)
from mosaic.rke.cli import main
from mosaic.rke.manual_review_import import (
    LICENSE_REVIEW_PACKET_PATH,
    LICENSE_REVIEW_TEMPLATE_PATH,
    TARGET_ROW_HASH_FIELD,
    review_row_fingerprint,
)


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")
    shutil.copytree(Path("schemas"), dst_root / "schemas")


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_json(path: Path, row: dict) -> None:
    path.write_text(
        json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _gold_import_rows(root: Path) -> list[dict]:
    return [
        {
            **row,
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
        for row in _load_jsonl(root / "registry/review_batches/gold_set_full_import_template.jsonl")
    ]


def _license_import_rows(root: Path) -> list[dict]:
    return [
        {
            "source_id": row["source_id"],
            TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
            "source_type": str(row.get("source_type") or ""),
            "title": str(row.get("title") or ""),
            "publish_date": str(row.get("publish_date") or ""),
            "current_license_status": str(row.get("current_license_status") or ""),
            "review_context_ref": LICENSE_REVIEW_PACKET_PATH,
            "target_review_path": LICENSE_REVIEW_TEMPLATE_PATH,
            "approved_for_derived_claim_storage": True,
            "approved_for_production_runtime": True,
            "reviewer": "compliance",
            "review_date": "2026-06-06",
            "notes": "fixture approval",
        }
        for row in _load_jsonl(root / "registry/compliance/tushare_license_review_template.jsonl")
    ]


def _passed_lockbox_review(root: Path) -> dict:
    return {
        **build_lockbox_review_import_template(root),
        "opened_at": "2026-06-06T10:00:00+08:00",
        "opened_by": "quant_research",
        "open_count": 1,
        "result": "passed",
        "parameter_search_after_open": False,
        "rule_design_after_open": False,
        "notes": "fixture lockbox pass",
    }


def test_promotion_dry_run_simulates_full_manual_gate_pass_without_mutating_root(tmp_path: Path):
    _copy_registry(tmp_path)
    lockbox_target = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    original_lockbox = lockbox_target.read_text(encoding="utf-8")
    gold_input = tmp_path / "gold_import.jsonl"
    license_input = tmp_path / "license_import.jsonl"
    lockbox_input = tmp_path / "lockbox_import.json"
    _write_jsonl(gold_input, _gold_import_rows(tmp_path))
    _write_jsonl(license_input, _license_import_rows(tmp_path))
    _write_json(lockbox_input, _passed_lockbox_review(tmp_path))

    report = build_promotion_dry_run_report(
        tmp_path,
        gold_input=gold_input,
        license_input=license_input,
        lockbox_input=lockbox_input,
    )

    assert report.accepted
    assert report.mutated_original_registry is False
    assert report.before_next_state == "paper_trading"
    assert report.after_next_state == "production"
    assert report.staged_production_allowed_after_simulation is True
    assert report.production_allowed_after_simulation is True
    assert report.after_blockers == ()
    assert {step.review_kind for step in report.steps} == {"gold_set", "source_license", "lockbox"}
    assert lockbox_target.read_text(encoding="utf-8") == original_lockbox


def test_promotion_dry_run_reports_missing_inputs():
    report = build_promotion_dry_run_report(".")

    assert not report.accepted
    assert not report.production_allowed_after_simulation
    assert {step.review_kind for step in report.steps} == {"gold_set", "source_license", "lockbox"}
    assert all(not step.provided for step in report.steps)
    assert all(step.result == "not_provided" for step in report.steps)


def test_write_promotion_dry_run_report_outputs_file(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_promotion_dry_run_report(tmp_path)
    payload = json.loads((tmp_path / "registry/promotion/rke_promotion_dry_run_report.json").read_text(encoding="utf-8"))

    assert result["accepted"] is False
    assert Path(result["path"]).exists()
    assert payload["mutated_original_registry"] is False


def test_cli_promotion_dry_run_validates_inputs(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    gold_input = tmp_path / "gold_import.jsonl"
    license_input = tmp_path / "license_import.jsonl"
    lockbox_input = tmp_path / "lockbox_import.json"
    _write_jsonl(gold_input, _gold_import_rows(tmp_path))
    _write_jsonl(license_input, _license_import_rows(tmp_path))
    _write_json(lockbox_input, _passed_lockbox_review(tmp_path))

    code = main(
        (
            "promotion-dry-run",
            "--root",
            str(tmp_path),
            "--gold-input",
            str(gold_input),
            "--license-input",
            str(license_input),
            "--lockbox-input",
            str(lockbox_input),
            "--write-report",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["production_allowed_after_simulation"] is True
    assert (tmp_path / "registry/promotion/rke_promotion_dry_run_report.json").exists()
