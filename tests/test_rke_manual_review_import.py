from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    apply_gold_set_review_import,
    apply_source_license_review_import,
    audit_master_plan_completion,
    build_source_registry_validation_report,
    summarize_gold_set_review,
    summarize_source_license_review,
)
from mosaic.rke.cli import main


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _gold_import_rows(root: Path) -> list[dict]:
    rows = _load_jsonl(root / "registry/gold_sets/tushare_research_reports.review_template.jsonl")
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
        for row in rows
    ]


def _license_import_rows(root: Path) -> list[dict]:
    rows = _load_jsonl(root / "registry/compliance/tushare_license_review_template.jsonl")
    return [
        {
            "source_id": row["source_id"],
            "approved_for_derived_claim_storage": True,
            "approved_for_production_runtime": True,
            "reviewer": "compliance",
            "review_date": "2026-06-06",
            "notes": "fixture approval",
        }
        for row in rows
    ]


def test_apply_gold_set_review_import_passes_c02_when_all_rows_reviewed(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "gold_import.jsonl"
    _write_jsonl(import_path, _gold_import_rows(tmp_path))

    report = apply_gold_set_review_import(tmp_path, import_path)
    summary = summarize_gold_set_review(tmp_path)
    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert report.accepted
    assert report.applied_rows == 500
    assert not report.blockers
    assert summary.review_complete
    assert summary.passed
    assert by_id["C02"].passed
    assert not by_id["C11"].passed
    assert (tmp_path / "registry/gold_sets/tushare_research_reports.review_import_report.json").exists()


def test_apply_gold_set_review_import_dry_run_does_not_modify_template(tmp_path: Path):
    _copy_registry(tmp_path)
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    original = review_path.read_text(encoding="utf-8")
    import_path = tmp_path / "gold_import.jsonl"
    _write_jsonl(import_path, _gold_import_rows(tmp_path))

    report = apply_gold_set_review_import(tmp_path, import_path, dry_run=True)

    assert report.accepted
    assert report.applied_rows == 0
    assert review_path.read_text(encoding="utf-8") == original


def test_apply_license_review_import_passes_c11_and_source_production_gate(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "license_import.jsonl"
    license_rows = _license_import_rows(tmp_path)
    _write_jsonl(import_path, license_rows)

    report = apply_source_license_review_import(tmp_path, import_path)
    summary = summarize_source_license_review(tmp_path)
    source_validation = build_source_registry_validation_report(tmp_path)
    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert report.accepted
    assert report.applied_rows == len(license_rows)
    assert summary.review_complete
    assert summary.passed
    assert source_validation.accepted_for_production
    assert source_validation.production_blocker_count == 0
    assert by_id["C11"].passed
    assert not by_id["C02"].passed
    assert (tmp_path / "registry/compliance/tushare_license_review_import_report.json").exists()


def test_apply_license_review_import_rejects_duplicate_or_invalid_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "license_import_bad.jsonl"
    rows = _license_import_rows(tmp_path)[:2]
    rows.append({**rows[0], "reviewer": ""})
    _write_jsonl(import_path, rows)

    report = apply_source_license_review_import(tmp_path, import_path)
    summary = summarize_source_license_review(tmp_path)

    assert not report.accepted
    assert report.applied_rows == 0
    assert report.duplicate_ids == (rows[0]["source_id"],)
    assert report.invalid_rows
    assert not summary.review_complete


def test_cli_apply_review_import_commands(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    gold_import = tmp_path / "gold_import.jsonl"
    license_import = tmp_path / "license_import.jsonl"
    license_rows = _license_import_rows(tmp_path)
    _write_jsonl(gold_import, _gold_import_rows(tmp_path))
    _write_jsonl(license_import, license_rows)

    gold_code = main(("apply-gold-review", "--root", str(tmp_path), "--input", str(gold_import)))
    gold_output = json.loads(capsys.readouterr().out)
    license_code = main(
        ("apply-license-review", "--root", str(tmp_path), "--input", str(license_import))
    )
    license_output = json.loads(capsys.readouterr().out)

    assert gold_code == 0
    assert gold_output["accepted"] is True
    assert gold_output["applied_rows"] == 500
    assert license_code == 0
    assert license_output["accepted"] is True
    assert license_output["applied_rows"] == len(license_rows)
