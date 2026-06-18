from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    apply_gold_set_review_import,
    apply_source_license_review_import,
    build_production_promotion_gate_report,
    write_production_promotion_gate_report,
)
from mosaic.rke.manual_review_import import (
    LICENSE_REVIEW_PACKET_PATH,
    LICENSE_REVIEW_TEMPLATE_PATH,
    TARGET_ROW_HASH_FIELD,
    review_row_fingerprint,
)


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")
    shutil.copytree(Path("schemas"), dst_root / "schemas")
    shutil.copytree(Path("docs"), dst_root / "docs")


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


def test_production_promotion_gate_blocks_current_registry():
    report = build_production_promotion_gate_report(".")
    blockers = " ".join(report.blockers)

    assert report.paper_trading_allowed
    assert not report.staged_production_allowed
    assert not report.production_allowed
    assert report.next_state == "paper_trading"
    assert report.direct_production_forbidden
    assert "manual gold-set review" not in blockers
    assert "source license review" not in blockers
    assert "horizon_accuracy below 0.85" in blockers
    assert "variable_mapping_accuracy below 0.80" in blockers
    assert "lockbox" in blockers


def test_production_promotion_gate_rejects_malformed_lockbox_payload(tmp_path: Path):
    _copy_registry(tmp_path)
    lockbox_path = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    lockbox_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    report = build_production_promotion_gate_report(tmp_path)
    pg09 = next(
        criterion for criterion in report.criteria if criterion.criterion_id == "PG09"
    )

    assert not report.production_allowed
    assert not pg09.passed
    assert "payload_errors=1" in pg09.evidence
    assert "lockbox review must be object" in pg09.blocker


def test_production_promotion_gate_rejects_invalid_json_payload(tmp_path: Path):
    _copy_registry(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    lockbox_path = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    completion_path.write_text("{not valid json", encoding="utf-8")
    lockbox_path.write_text("{not valid json", encoding="utf-8")

    report = build_production_promotion_gate_report(tmp_path)
    pg01 = next(
        criterion for criterion in report.criteria if criterion.criterion_id == "PG01"
    )
    pg09 = next(
        criterion for criterion in report.criteria if criterion.criterion_id == "PG09"
    )

    assert not report.production_allowed
    assert not pg01.passed
    assert not pg09.passed
    assert "completion audit must contain valid JSON" in pg01.blocker
    assert "lockbox review must contain valid JSON" in pg09.blocker


def test_production_promotion_gate_rejects_malformed_completion_payload(tmp_path: Path):
    _copy_registry(tmp_path)
    completion_path = tmp_path / "registry/audits/rke_completion_audit.json"
    completion_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    report = build_production_promotion_gate_report(tmp_path)
    pg01 = next(
        criterion for criterion in report.criteria if criterion.criterion_id == "PG01"
    )

    assert not report.production_allowed
    assert not pg01.passed
    assert "completion audit must be object" in pg01.blocker


def test_production_promotion_gate_rejects_malformed_paper_payload(tmp_path: Path):
    _copy_registry(tmp_path)
    paper_path = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    paper_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    report = build_production_promotion_gate_report(tmp_path)
    pg06 = next(
        criterion for criterion in report.criteria if criterion.criterion_id == "PG06"
    )

    assert not report.paper_trading_allowed
    assert not pg06.passed
    assert "paper-trading report must be object" in pg06.blocker


def test_production_promotion_gate_rejects_malformed_patch_payload(tmp_path: Path):
    _copy_registry(tmp_path)
    patch_path = tmp_path / "registry/patches/central_bank_paper_trading_patch.json"
    patch_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    report = build_production_promotion_gate_report(tmp_path)
    pg08 = next(
        criterion for criterion in report.criteria if criterion.criterion_id == "PG08"
    )
    pg10 = next(
        criterion for criterion in report.criteria if criterion.criterion_id == "PG10"
    )

    assert not report.paper_trading_allowed
    assert not pg08.passed
    assert not pg10.passed
    assert "promotion patch must be object" in pg08.blocker
    assert "promotion patch must be object" in pg10.blocker


def test_production_promotion_gate_allows_production_after_manual_and_lockbox_gates(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    gold_import = tmp_path / "gold_import.jsonl"
    license_import = tmp_path / "license_import.jsonl"
    _write_jsonl(gold_import, _gold_import_rows(tmp_path))
    _write_jsonl(license_import, _license_import_rows(tmp_path))
    apply_gold_set_review_import(tmp_path, gold_import)
    apply_source_license_review_import(tmp_path, license_import)
    lockbox_path = tmp_path / "registry/lockbox/central_bank_lockbox_review.json"
    lockbox = json.loads(lockbox_path.read_text(encoding="utf-8"))
    lockbox.update(
        {
            "opened_at": "2026-06-06T10:00:00+08:00",
            "opened_by": "quant_research",
            "open_count": 1,
            "result": "passed",
        }
    )
    lockbox_path.write_text(
        json.dumps(lockbox, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = write_production_promotion_gate_report(tmp_path)
    report = build_production_promotion_gate_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert report.paper_trading_allowed
    assert report.staged_production_allowed
    assert report.production_allowed
    assert report.next_state == "production"
    assert payload["production_allowed"] is True
