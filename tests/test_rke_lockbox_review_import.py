from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    apply_gold_set_review_import,
    apply_lockbox_review_import,
    apply_source_license_review_import,
    build_lockbox_review_import_template,
    build_production_promotion_gate_report,
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
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def test_apply_lockbox_review_import_dry_run_does_not_modify_target(tmp_path: Path):
    _copy_registry(tmp_path)
    target = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    original = target.read_text(encoding="utf-8")
    import_path = tmp_path / "lockbox_review.json"
    _write_json(import_path, _passed_lockbox_review(tmp_path))

    report = apply_lockbox_review_import(tmp_path, import_path, dry_run=True)

    assert report.accepted
    assert not report.applied
    assert report.production_allowed
    assert target.read_text(encoding="utf-8") == original


def test_apply_lockbox_review_import_records_failed_review_without_promotion(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_failed.json"
    failed = {
        **_passed_lockbox_review(tmp_path),
        "result": "failed",
        "notes": "fixture lockbox failure",
    }
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
    bad = {**_passed_lockbox_review(tmp_path), "experiment_id": "EXP-OTHER"}
    _write_json(import_path, bad)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert not report.applied
    assert any("experiment_id" in reason for reason in report.rejected_reasons)


def test_apply_lockbox_review_import_rejects_missing_experiment_identity(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_missing_identity.json"
    bad = _passed_lockbox_review(tmp_path)
    bad.pop("experiment_id")
    _write_json(import_path, bad)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert not report.applied
    assert "experiment_id required" in report.rejected_reasons


def test_apply_lockbox_review_import_rejects_non_object_input(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_array.json"
    import_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert not report.applied
    assert report.result == ""
    assert report.rejected_reasons == ("lockbox review import must be object",)
    assert (tmp_path / "registry/lockbox/central_bank_lockbox_review_import_report.json").exists()


def test_apply_lockbox_review_import_rejects_invalid_json_input(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_bad.json"
    import_path.write_text("{", encoding="utf-8")

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert not report.applied
    assert any("lockbox review import must contain valid JSON" in reason for reason in report.rejected_reasons)
    assert (tmp_path / "registry/lockbox/central_bank_lockbox_review_import_report.json").exists()


def test_apply_lockbox_review_import_rejects_invalid_json_target(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review.json"
    _write_json(import_path, _passed_lockbox_review(tmp_path))
    (tmp_path / "registry/lockbox/central_bank_lockbox_review.json").write_text("{", encoding="utf-8")

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert not report.applied
    assert any("lockbox target must contain valid JSON" in reason for reason in report.rejected_reasons)
    assert (tmp_path / "registry/lockbox/central_bank_lockbox_review_import_report.json").exists()


def test_lockbox_review_import_allows_production_after_manual_gates(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_import = tmp_path / "gold_import.jsonl"
    license_import = tmp_path / "license_import.jsonl"
    lockbox_import = tmp_path / "lockbox_review.json"
    _write_jsonl(gold_import, _gold_import_rows(tmp_path))
    _write_jsonl(license_import, _license_import_rows(tmp_path))
    _write_json(lockbox_import, _passed_lockbox_review(tmp_path))

    apply_gold_set_review_import(tmp_path, gold_import)
    apply_source_license_review_import(tmp_path, license_import)
    lockbox_report = apply_lockbox_review_import(tmp_path, lockbox_import)
    promotion = build_production_promotion_gate_report(tmp_path)

    assert lockbox_report.accepted
    assert promotion.staged_production_allowed
    assert promotion.production_allowed
    assert promotion.next_state == "production"


def test_apply_lockbox_review_import_rejects_reopening_existing_lockbox(tmp_path: Path):
    _copy_registry(tmp_path)
    first_import = tmp_path / "lockbox_review_first.json"
    second_import = tmp_path / "lockbox_review_second.json"
    _write_json(first_import, _passed_lockbox_review(tmp_path))

    first_report = apply_lockbox_review_import(tmp_path, first_import)
    _write_json(second_import, _passed_lockbox_review(tmp_path))

    second_report = apply_lockbox_review_import(tmp_path, second_import)

    assert first_report.accepted
    assert first_report.applied
    assert not second_report.accepted
    assert not second_report.applied
    assert "lockbox target has already been opened" in second_report.rejected_reasons


def test_cli_apply_lockbox_review_import(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review.json"
    _write_json(import_path, _passed_lockbox_review(tmp_path))

    code = main(("apply-lockbox-review", "--root", str(tmp_path), "--input", str(import_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["applied"] is True
    assert (tmp_path / "registry/lockbox/central_bank_lockbox_review_import_report.json").exists()


def test_apply_lockbox_review_import_rejects_stale_target_fingerprint(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_stale_target.json"
    row = _passed_lockbox_review(tmp_path)
    target_path = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    target = json.loads(target_path.read_text(encoding="utf-8"))
    target["notes"] = "changed after lockbox review template export"
    _write_json(target_path, target)
    _write_json(import_path, row)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert not report.applied
    assert "target_row_hash does not match current lockbox review target" in report.rejected_reasons


def test_apply_lockbox_review_import_rejects_stale_context_fingerprint(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_stale_context.json"
    row = _passed_lockbox_review(tmp_path)
    policy_path = tmp_path / "registry/evaluation/lockbox/lockbox_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["policy_status"] = "changed-after-template-export"
    _write_json(policy_path, policy)
    _write_json(import_path, row)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert not report.applied
    assert "review_context_hash does not match current lockbox review context" in report.rejected_reasons


def test_apply_lockbox_review_import_rejects_legacy_import_without_provenance(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_legacy.json"
    legacy = {
        "experiment_family_id": "FAM-CB-LIQUIDITY-2026Q2",
        "experiment_id": "EXP-CB-20260605-0001",
        "opened_at": "2026-06-06T10:00:00+08:00",
        "opened_by": "quant_research",
        "open_count": 1,
        "result": "passed",
        "parameter_search_after_open": False,
        "rule_design_after_open": False,
        "notes": "legacy fixture lockbox pass",
    }
    _write_json(import_path, legacy)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert "target_review_path must match registry/lockbox/central_bank_lockbox_review.json" in report.rejected_reasons
    assert "target_row_hash does not match current lockbox review target" in report.rejected_reasons


def test_apply_lockbox_review_import_rejects_forbidden_source_text_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_with_source_text.json"
    row = _passed_lockbox_review(tmp_path)
    row["abstract"] = "long source text must stay out of lockbox review imports"
    _write_json(import_path, row)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert "abstract forbidden in lockbox review import" in report.rejected_reasons


def test_apply_lockbox_review_import_rejects_nested_forbidden_source_text_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_with_nested_source_text.json"
    row = _passed_lockbox_review(tmp_path)
    row["review_context"] = {
        "source_span_text": "nested source text must stay out of lockbox review imports"
    }
    _write_json(import_path, row)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert "review_context.source_span_text forbidden in lockbox review import" in report.rejected_reasons


def test_apply_lockbox_review_import_rejects_unexpected_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_with_unexpected_field.json"
    row = _passed_lockbox_review(tmp_path)
    row["extra_context"] = "reviewer accidentally pasted non-template context"
    _write_json(import_path, row)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert "extra_context unexpected in lockbox review import" in report.rejected_reasons


def test_apply_lockbox_review_import_rejects_non_string_review_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_with_non_string_fields.json"
    row = _passed_lockbox_review(tmp_path)
    row["opened_by"] = ["not", "a", "string"]
    row["notes"] = {"note": "not a string"}
    _write_json(import_path, row)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert "opened_by must be string" in report.rejected_reasons
    assert "notes must be string" in report.rejected_reasons


def test_apply_lockbox_review_import_rejects_opened_at_without_time_or_timezone(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_with_bad_opened_at.json"
    row = _passed_lockbox_review(tmp_path)
    row["opened_at"] = "2026-06-06"
    _write_json(import_path, row)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert "opened_at must be ISO-8601 datetime with timezone" in report.rejected_reasons


def test_apply_lockbox_review_import_rejects_opened_at_without_timezone(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "lockbox_review_with_timezone_free_opened_at.json"
    row = _passed_lockbox_review(tmp_path)
    row["opened_at"] = "2026-06-06T10:00:00"
    _write_json(import_path, row)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert "opened_at must be ISO-8601 datetime with timezone" in report.rejected_reasons


def test_apply_lockbox_review_import_rejects_not_opened_result(tmp_path: Path):
    _copy_registry(tmp_path)
    target = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    original = target.read_text(encoding="utf-8")
    import_path = tmp_path / "lockbox_review_not_opened.json"
    row = _passed_lockbox_review(tmp_path)
    row["result"] = "not_opened"
    row["open_count"] = 0
    _write_json(import_path, row)

    report = apply_lockbox_review_import(tmp_path, import_path)

    assert not report.accepted
    assert not report.applied
    assert "lockbox review import result must be passed or failed" in report.rejected_reasons
    assert target.read_text(encoding="utf-8") == original
