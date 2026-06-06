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
from mosaic.rke.manual_review_import import (
    LICENSE_REVIEW_PACKET_PATH,
    LICENSE_REVIEW_TEMPLATE_PATH,
    TARGET_ROW_HASH_FIELD,
    review_row_fingerprint,
)


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


def _accepted_gold_template_row(row: dict) -> dict:
    out = dict(row)
    out.update(
        {
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
    )
    return out


def _accepted_license_template_row(row: dict) -> dict:
    out = dict(row)
    out.update(
        {
            "approved_for_derived_claim_storage": True,
            "approved_for_production_runtime": True,
            "reviewer": "compliance",
            "review_date": "2026-06-06",
            "notes": "fixture approval",
        }
    )
    return out


def _gold_import_rows(root: Path) -> list[dict]:
    rows = _load_jsonl(root / "registry/review_batches/gold_set_full_import_template.jsonl")
    return [_accepted_gold_template_row(row) for row in rows]


def _license_import_rows(root: Path) -> list[dict]:
    rows = _load_jsonl(root / "registry/compliance/tushare_license_review_template.jsonl")
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


def test_apply_gold_set_review_import_rejects_mismatched_template_references(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "gold_import_bad_refs.jsonl"
    row = _accepted_gold_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl")[0]
    )
    row["target_review_path"] = "registry/gold_sets/other_review_template.jsonl"
    row["source_id"] = "SRC-WRONG"
    _write_jsonl(import_path, [row])

    report = apply_gold_set_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert report.applied_rows == 0
    assert "target_review_path must match registry/gold_sets/tushare_research_reports.review_template.jsonl" in reasons
    assert "source_id does not match target review row" in reasons


def test_apply_gold_set_review_import_rejects_stale_target_row_hash(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "gold_import_stale_hash.jsonl"
    row = _accepted_gold_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl")[0]
    )
    target_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    target_rows = _load_jsonl(target_path)
    target_rows[0]["proposed_claim_text"] = "changed after reviewer exported import template"
    _write_jsonl(target_path, target_rows)
    _write_jsonl(import_path, [row])

    report = apply_gold_set_review_import(tmp_path, import_path)

    assert not report.accepted
    assert "target_row_hash does not match target review row" in set(report.invalid_rows[0].reasons)


def test_apply_gold_set_review_import_rejects_legacy_import_without_provenance(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "gold_import_legacy.jsonl"
    target_row = _load_jsonl(tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl")[0]
    legacy = {
        "claim_id": target_row["claim_id"],
        "manual_claim_text": target_row.get("proposed_claim_text") or "manual claim",
        "claim_correct": True,
        "source_span_supports_claim": True,
        "direction_correct": True,
        "variable_mapping_correct": True,
        "unsupported_field_false_grounded": False,
        "reviewer": "reviewer-a",
        "review_date": "2026-06-06",
        "review_notes": "legacy fixture",
    }
    _write_jsonl(import_path, [legacy])

    report = apply_gold_set_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert "target_review_path required" in reasons
    assert "target_row_hash required" in reasons


def test_apply_gold_set_review_import_rejects_forbidden_source_text_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "gold_import_with_source_text.jsonl"
    row = _accepted_gold_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl")[0]
    )
    row["abstract"] = "long source text must stay out of sparse manual imports"
    _write_jsonl(import_path, [row])

    report = apply_gold_set_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert "abstract forbidden in manual review import" in reasons


def test_apply_gold_set_review_import_rejects_nested_forbidden_source_text_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "gold_import_with_nested_source_text.jsonl"
    row = _accepted_gold_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl")[0]
    )
    row["review_context"] = {"source_text": "nested source text must stay out of sparse manual imports"}
    _write_jsonl(import_path, [row])

    report = apply_gold_set_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert "review_context.source_text forbidden in manual review import" in reasons


def test_apply_gold_set_review_import_rejects_unexpected_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "gold_import_with_unexpected_field.jsonl"
    row = _accepted_gold_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl")[0]
    )
    row["extra_context"] = "reviewer accidentally pasted non-template context"
    _write_jsonl(import_path, [row])

    report = apply_gold_set_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert "extra_context unexpected in manual review import" in reasons


def test_apply_gold_set_review_import_rejects_non_string_review_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "gold_import_with_non_string_fields.jsonl"
    row = _accepted_gold_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl")[0]
    )
    row["manual_claim_text"] = ["not", "a", "string"]
    row["review_notes"] = {"note": "not a string"}
    _write_jsonl(import_path, [row])

    report = apply_gold_set_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert "manual_claim_text must be string" in reasons
    assert "review_notes must be string" in reasons


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


def test_apply_license_review_import_rejects_mismatched_template_references(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "license_import_bad_refs.jsonl"
    row = _accepted_license_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/source_license_next_import_template.jsonl")[0]
    )
    row["review_context_ref"] = "registry/compliance/other_license_packet.json"
    row["publish_date"] = "1999-01-01"
    _write_jsonl(import_path, [row])

    report = apply_source_license_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert report.applied_rows == 0
    assert "review_context_ref must match registry/compliance/tushare_license_review_packet.json" in reasons
    assert "publish_date does not match target review row" in reasons


def test_apply_license_review_import_rejects_stale_target_row_hash(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "license_import_stale_hash.jsonl"
    row = _accepted_license_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/source_license_next_import_template.jsonl")[0]
    )
    target_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    target_rows = _load_jsonl(target_path)
    target_rows[0]["title"] = "changed after reviewer exported import template"
    _write_jsonl(target_path, target_rows)
    _write_jsonl(import_path, [row])

    report = apply_source_license_review_import(tmp_path, import_path)

    assert not report.accepted
    assert "target_row_hash does not match target review row" in set(report.invalid_rows[0].reasons)


def test_apply_license_review_import_rejects_legacy_import_without_provenance(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "license_import_legacy.jsonl"
    target_row = _load_jsonl(tmp_path / "registry/compliance/tushare_license_review_template.jsonl")[0]
    legacy = {
        "source_id": target_row["source_id"],
        "approved_for_derived_claim_storage": True,
        "approved_for_production_runtime": True,
        "reviewer": "compliance",
        "review_date": "2026-06-06",
        "notes": "legacy fixture",
    }
    _write_jsonl(import_path, [legacy])

    report = apply_source_license_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert "target_review_path required" in reasons
    assert "target_row_hash required" in reasons


def test_apply_license_review_import_rejects_forbidden_source_text_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "license_import_with_source_text.jsonl"
    row = _accepted_license_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/source_license_next_import_template.jsonl")[0]
    )
    row["source_text"] = "long source text must stay out of sparse manual imports"
    _write_jsonl(import_path, [row])

    report = apply_source_license_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert "source_text forbidden in manual review import" in reasons


def test_apply_license_review_import_rejects_nested_forbidden_source_text_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "license_import_with_nested_source_text.jsonl"
    row = _accepted_license_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/source_license_next_import_template.jsonl")[0]
    )
    row["review_context"] = {"full_text": "nested source text must stay out of sparse manual imports"}
    _write_jsonl(import_path, [row])

    report = apply_source_license_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert "review_context.full_text forbidden in manual review import" in reasons


def test_apply_license_review_import_rejects_unexpected_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "license_import_with_unexpected_field.jsonl"
    row = _accepted_license_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/source_license_next_import_template.jsonl")[0]
    )
    row["extra_context"] = "reviewer accidentally pasted non-template context"
    _write_jsonl(import_path, [row])

    report = apply_source_license_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert "extra_context unexpected in manual review import" in reasons


def test_apply_license_review_import_rejects_non_string_review_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "license_import_with_non_string_fields.jsonl"
    row = _accepted_license_template_row(
        _load_jsonl(tmp_path / "registry/review_batches/source_license_next_import_template.jsonl")[0]
    )
    row["reviewer"] = {"name": "not a string"}
    row["notes"] = ["not", "a", "string"]
    _write_jsonl(import_path, [row])

    report = apply_source_license_review_import(tmp_path, import_path)
    reasons = set(report.invalid_rows[0].reasons)

    assert not report.accepted
    assert "reviewer must be string" in reasons
    assert "notes must be string" in reasons


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
