from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mosaic.rke import (
    build_registry_manifest,
    run_full_rke_refresh,
    validate_required_registry,
    write_registry_manifest,
)


def _copy_registry(src_root: Path, dst_root: Path) -> None:
    shutil.copytree(src_root / "registry", dst_root / "registry")


def test_required_registry_files_are_present_in_repo():
    missing, empty = validate_required_registry(".")

    assert missing == ()
    assert empty == ()


def test_registry_manifest_tracks_hashes_and_required_artifacts(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)

    result = write_registry_manifest(tmp_path)
    manifest = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert result["valid"] is True
    assert manifest["manifest_id"] == "RKE-REGISTRY-MANIFEST-20260606"
    assert manifest["artifact_count"] >= 30
    assert manifest["missing_required"] == []
    assert all(item["sha256"].startswith("sha256:") for item in manifest["artifacts"])


def test_full_refresh_preserves_existing_review_templates(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    gold_review = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    gold_rows = [json.loads(line) for line in gold_review.read_text(encoding="utf-8").splitlines()]
    gold_rows[0]["manual_claim_text"] = "reviewer-entered claim"
    gold_rows[0]["claim_correct"] = True
    gold_review.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in gold_rows),
        encoding="utf-8",
    )
    license_review = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    original_license = license_review.read_text(encoding="utf-8")

    result = run_full_rke_refresh(tmp_path, preserve_review_templates=True)
    manifest = build_registry_manifest(tmp_path)

    assert result.manifest_valid
    assert manifest.valid
    refreshed_gold = [json.loads(line) for line in gold_review.read_text(encoding="utf-8").splitlines()]
    assert refreshed_gold[0]["manual_claim_text"] == "reviewer-entered claim"
    assert refreshed_gold[0]["claim_correct"] is True
    assert refreshed_gold[0]["proposed_claim_text"]
    assert license_review.read_text(encoding="utf-8") == original_license
    assert "gold_candidate_claims" in result.outputs
    assert "manual_review_batch_status" in result.outputs
    assert "manual_review_gold_set_import_template" in result.outputs
    assert "manual_review_gold_set_full_import_template" in result.outputs
    assert "manual_review_source_license_import_template" in result.outputs
    assert "audit_trace_view.json" in result.outputs
    assert "audit_trace_view.markdown" in result.outputs
    assert "operator_handoff.json" in result.outputs
    assert "operator_handoff.markdown" in result.outputs
    assert "lockbox_review_import_template" in result.outputs
    assert "lockbox_review_import_report" in result.outputs
    assert "gold_set_full_import_template" in result.outputs
    assert "gold_review_import_report" in result.outputs
    assert "source_license_policy_template" in result.outputs
    assert "source_license_policy_import_report" in result.outputs
    assert "manual_review_bundle_manifest" in result.outputs
    assert "promotion_dry_run_report" in result.outputs
    assert "rollback_readiness_report" in result.outputs
    assert "operator_readiness_report" in result.outputs
    assert "production_promotion_gate" in result.outputs
    assert "production_monitor_diagnostics" in result.outputs
    assert "registry_manifest" in result.outputs


def test_full_refresh_recreates_missing_review_templates(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    gold_review = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    license_review = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    gold_review.unlink()
    license_review.unlink()

    result = run_full_rke_refresh(tmp_path, preserve_review_templates=True)

    assert result.manifest_valid
    assert gold_review.exists()
    assert license_review.exists()
    assert len(gold_review.read_text(encoding="utf-8").splitlines()) == 500
    source_rows = (tmp_path / "registry/sources/tushare_research_reports.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(license_review.read_text(encoding="utf-8").splitlines()) == len(source_rows)


def test_full_refresh_rejects_malformed_gold_candidate_rows(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    candidates_path = tmp_path / "registry/sources/tushare_research_reports.gold_candidates.jsonl"
    expected_row = len(candidates_path.read_text(encoding="utf-8").splitlines()) + 1
    candidates_path.write_text(
        candidates_path.read_text(encoding="utf-8") + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=rf"gold candidate row must be object at row\(s\): {expected_row}",
    ):
        run_full_rke_refresh(tmp_path, preserve_review_templates=False)
