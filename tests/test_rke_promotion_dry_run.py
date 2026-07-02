from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_lockbox_review_import_template,
    build_promotion_dry_run_report,
    write_manual_review_batches,
    write_promotion_dry_run_report,
)
from mosaic.rke.cli import main
from mosaic.rke.manual_review_import import (
    LICENSE_REVIEW_PACKET_PATH,
    LICENSE_REVIEW_TEMPLATE_PATH,
    TARGET_ROW_HASH_FIELD,
    review_row_fingerprint,
)
from mosaic.rke.report_intelligence import build_analytical_footprint_review_rows


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")
    shutil.copytree(Path("schemas"), dst_root / "schemas")
    shutil.copytree(Path("docs"), dst_root / "docs")
    _reset_lockbox_target(dst_root)
    _reset_gold_review_rows(
        dst_root / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    write_manual_review_batches(dst_root)
    footprint_template = (
        dst_root
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    _write_jsonl(
        footprint_template,
        build_analytical_footprint_review_rows(
            _load_jsonl(
                dst_root / "registry/report_intelligence/analytical_footprints.jsonl"
            ),
            existing_template_path=footprint_template,
        ),
    )


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
    _write_json(target, row)


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
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
            "target_correct": True,
            "horizon_correct": True,
            "variable_mapping_correct": True,
            "unsupported_field_false_grounded": False,
            "reviewer": "reviewer-a",
            "review_date": "2026-06-06",
            "review_notes": "fixture approval",
        }
        for row in _load_jsonl(
            root / "registry/review_batches/gold_set_full_import_template.jsonl"
        )
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
        for row in _load_jsonl(
            root / "registry/compliance/tushare_license_review_template.jsonl"
        )
    ]


def _footprint_import_rows(root: Path) -> list[dict]:
    rows = _load_jsonl(
        root / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    for row in rows:
        row.update(
            {
                "footprint_correct": True,
                "source_span_supports_footprint": True,
                "metric_mapping_correct": True,
                "inferred_steps_tagged_correctly": True,
                "unknowns_used_when_uncertain": True,
                "no_proprietary_text_leakage": True,
                "manual_error_tags": [],
                "reviewer": "reviewer-a",
                "review_date": "2026-06-06",
                "review_notes": "fixture approval",
            }
        )
    return rows


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


def test_promotion_dry_run_simulates_full_manual_gate_pass_without_mutating_root(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    lockbox_target = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    original_lockbox = lockbox_target.read_text(encoding="utf-8")
    gold_input = tmp_path / "gold_import.jsonl"
    footprint_input = tmp_path / "footprint_import.jsonl"
    license_input = tmp_path / "license_import.jsonl"
    lockbox_input = tmp_path / "lockbox_import.json"
    _write_jsonl(gold_input, _gold_import_rows(tmp_path))
    _write_jsonl(footprint_input, _footprint_import_rows(tmp_path))
    _write_jsonl(license_input, _license_import_rows(tmp_path))
    _write_json(lockbox_input, _passed_lockbox_review(tmp_path))

    report = build_promotion_dry_run_report(
        tmp_path,
        gold_input=gold_input,
        footprint_input=footprint_input,
        license_input=license_input,
        lockbox_input=lockbox_input,
    )

    assert report.accepted
    assert report.mutated_original_registry is False
    assert report.before_next_state == "staged_production"
    assert report.after_next_state == "production"
    assert report.staged_production_allowed_after_simulation is True
    assert report.production_allowed_after_simulation is True
    assert report.after_blockers == ()
    assert {step.review_kind for step in report.steps} == {
        "gold_set",
        "footprint_review",
        "source_license",
        "lockbox",
    }
    assert lockbox_target.read_text(encoding="utf-8") == original_lockbox


def test_promotion_dry_run_reports_missing_inputs():
    report = build_promotion_dry_run_report(".")
    steps = {step.review_kind: step for step in report.steps}

    assert set(steps) == {"gold_set", "footprint_review", "source_license", "lockbox"}
    assert all(not step.provided for step in report.steps)
    assert steps["gold_set"].result == "already_applied"
    assert steps["gold_set"].accepted
    assert steps["footprint_review"].result in {"already_applied", "not_provided"}
    assert steps["footprint_review"].accepted is (
        steps["footprint_review"].result == "already_applied"
    )
    assert steps["source_license"].result == "already_applied"
    assert steps["source_license"].accepted
    assert steps["lockbox"].result == "already_applied"
    assert steps["lockbox"].accepted
    assert report.accepted is all(step.accepted for step in report.steps)
    assert report.production_allowed_after_simulation is (
        report.after_next_state == "production"
    )


def test_promotion_dry_run_rejects_partial_valid_bundle(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_input = tmp_path / "gold_import.jsonl"
    _write_jsonl(gold_input, _gold_import_rows(tmp_path))

    report = build_promotion_dry_run_report(tmp_path, gold_input=gold_input)
    steps = {step.review_kind: step for step in report.steps}

    assert not report.accepted
    assert steps["gold_set"].provided
    assert steps["gold_set"].accepted
    assert not steps["footprint_review"].provided
    assert steps["footprint_review"].result in {"already_applied", "not_provided"}
    assert steps["footprint_review"].accepted is (
        steps["footprint_review"].result == "already_applied"
    )
    assert not steps["source_license"].provided
    assert steps["source_license"].accepted
    assert steps["source_license"].result == "already_applied"
    assert not steps["lockbox"].provided
    assert not report.production_allowed_after_simulation


def test_promotion_dry_run_uses_already_applied_source_license_gate(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_input = tmp_path / "gold_import.jsonl"
    footprint_input = tmp_path / "footprint_import.jsonl"
    lockbox_input = tmp_path / "lockbox_import.json"
    _write_jsonl(gold_input, _gold_import_rows(tmp_path))
    _write_jsonl(footprint_input, _footprint_import_rows(tmp_path))
    _write_json(lockbox_input, _passed_lockbox_review(tmp_path))

    report = build_promotion_dry_run_report(
        tmp_path,
        gold_input=gold_input,
        footprint_input=footprint_input,
        lockbox_input=lockbox_input,
    )
    steps = {step.review_kind: step for step in report.steps}

    assert report.accepted
    assert report.after_next_state == "production"
    assert report.production_allowed_after_simulation is True
    assert steps["source_license"].result == "already_applied"
    assert not steps["source_license"].provided
    assert steps["source_license"].accepted


def test_write_promotion_dry_run_report_outputs_file(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_promotion_dry_run_report(tmp_path)
    payload = json.loads(
        (tmp_path / "registry/promotion/rke_promotion_dry_run_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert result["accepted"] is False
    assert Path(result["path"]).exists()
    assert payload["mutated_original_registry"] is False


def test_cli_promotion_dry_run_validates_inputs(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    gold_input = tmp_path / "gold_import.jsonl"
    footprint_input = tmp_path / "footprint_import.jsonl"
    license_input = tmp_path / "license_import.jsonl"
    lockbox_input = tmp_path / "lockbox_import.json"
    _write_jsonl(gold_input, _gold_import_rows(tmp_path))
    _write_jsonl(footprint_input, _footprint_import_rows(tmp_path))
    _write_jsonl(license_input, _license_import_rows(tmp_path))
    _write_json(lockbox_input, _passed_lockbox_review(tmp_path))

    code = main(
        (
            "promotion-dry-run",
            "--root",
            str(tmp_path),
            "--gold-input",
            str(gold_input),
            "--footprint-input",
            str(footprint_input),
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
