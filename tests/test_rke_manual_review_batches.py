from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    apply_gold_set_review_import,
    apply_source_license_review_import,
    build_manual_review_batch_status,
    write_manual_review_batches,
)


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _accepted_gold_row(row: dict) -> dict:
    return {
        "claim_id": row["claim_id"],
        "manual_claim_text": row.get("proposed_claim_text") or "manual claim",
        "claim_correct": True,
        "source_span_supports_claim": True,
        "direction_correct": True,
        "variable_mapping_correct": True,
        "unsupported_field_false_grounded": False,
        "reviewer": "reviewer-a",
        "review_date": "2026-06-06",
        "review_notes": "batch fixture",
    }


def _accepted_license_row(row: dict) -> dict:
    return {
        "source_id": row["source_id"],
        "approved_for_derived_claim_storage": True,
        "approved_for_production_runtime": True,
        "reviewer": "compliance",
        "review_date": "2026-06-06",
        "notes": "batch fixture",
    }


def _license_review_source_count(root: Path) -> int:
    return len(_load_jsonl(root / "registry/compliance/tushare_license_review_template.jsonl"))


def test_manual_review_batches_export_sparse_import_templates(tmp_path: Path):
    _copy_registry(tmp_path)
    source_count = _license_review_source_count(tmp_path)

    paths = write_manual_review_batches(tmp_path, gold_batch_size=12, license_batch_size=7)
    status = json.loads(Path(paths["status"]).read_text(encoding="utf-8"))
    gold_rows = _load_jsonl(Path(paths["gold_set_import_template"]))
    gold_full_rows = _load_jsonl(Path(paths["gold_set_full_import_template"]))
    license_rows = _load_jsonl(Path(paths["source_license_import_template"]))

    assert status["ready_for_manual_review"] is True
    assert status["gold_set"]["pending_rows"] == 500
    assert status["gold_set"]["exported_rows"] == 12
    assert status["gold_set"]["full_import_template_path"] == "registry/review_batches/gold_set_full_import_template.jsonl"
    assert status["source_license"]["pending_rows"] == source_count
    assert status["source_license"]["exported_rows"] == 7
    assert len(gold_rows) == 12
    assert len(gold_full_rows) == 500
    assert len(license_rows) == 7
    assert "span_preview" not in gold_rows[0]
    assert "abstract" not in gold_rows[0]
    assert "abstract" not in license_rows[0]
    assert gold_rows[0]["proposed_claim_text"]
    assert len(gold_rows[0]["proposed_claim_text"]) <= 72
    assert isinstance(gold_rows[0]["proposed_claim_text_truncated"], bool)
    assert gold_rows[0]["proposed_source_text_hash"].startswith("sha256:")
    assert gold_rows[0]["gold_set_domain"]
    assert gold_rows[0]["gold_set_domain_matches"]
    assert gold_rows[0]["proposed_review_risk_flags"]
    assert gold_rows[0]["manual_claim_text"] == ""
    assert gold_rows[0]["claim_correct"] is None
    assert license_rows[0]["approved_for_production_runtime"] is None
    assert "apply-gold-review" in status["gold_set"]["dry_run_command"]
    assert "apply-license-review" in status["source_license"]["dry_run_command"]


def test_manual_review_batch_status_moves_after_partial_import(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_template = _load_jsonl(tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl")
    license_template = _load_jsonl(tmp_path / "registry/compliance/tushare_license_review_template.jsonl")
    source_count = len(license_template)
    first_gold_id = gold_template[0]["claim_id"]
    first_license_id = license_template[0]["source_id"]
    gold_import = tmp_path / "gold_batch_import.jsonl"
    license_import = tmp_path / "license_batch_import.jsonl"
    _write_jsonl(gold_import, [_accepted_gold_row(gold_template[0])])
    _write_jsonl(license_import, [_accepted_license_row(license_template[0])])

    gold_report = apply_gold_set_review_import(tmp_path, gold_import)
    license_report = apply_source_license_review_import(tmp_path, license_import)
    status, gold_batch, license_batch = build_manual_review_batch_status(
        tmp_path,
        gold_batch_size=5,
        license_batch_size=5,
    )

    assert gold_report.accepted
    assert license_report.accepted
    assert status.gold_set.pending_rows == 499
    assert status.source_license.pending_rows == source_count - 1
    assert all(row["claim_id"] != first_gold_id for row in gold_batch)
    assert all(row["source_id"] != first_license_id for row in license_batch)
