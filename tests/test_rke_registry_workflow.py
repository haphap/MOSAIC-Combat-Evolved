from __future__ import annotations

import json
import shutil
from pathlib import Path

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
    original_gold = gold_review.read_text(encoding="utf-8")
    license_review = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    original_license = license_review.read_text(encoding="utf-8")

    result = run_full_rke_refresh(tmp_path, preserve_review_templates=True)
    manifest = build_registry_manifest(tmp_path)

    assert result.manifest_valid
    assert manifest.valid
    assert gold_review.read_text(encoding="utf-8") == original_gold
    assert license_review.read_text(encoding="utf-8") == original_license
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
    assert len(license_review.read_text(encoding="utf-8").splitlines()) == 65
