from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_source_registry_validation_report,
    write_source_registry_validation_report,
)
from mosaic.rke.source_registry_validation import SOURCE_REGISTRY_PATHS


def _copy_registry(src_root: Path, dst_root: Path) -> None:
    shutil.copytree(src_root / "registry", dst_root / "registry")


def _source_rows(root: Path, relative_path: str) -> list[dict[str, object]]:
    path = root / relative_path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _expected_source_counts(root: Path) -> tuple[int, int, int]:
    rows = [row for relative_path in SOURCE_REGISTRY_PATHS for row in _source_rows(root, relative_path)]
    unique_source_ids = {str(row.get("source_id") or "") for row in rows}
    return len(rows), len(unique_source_ids), len(rows) - len(unique_source_ids)


def test_source_registry_validation_accepts_sandbox_but_reports_production_blockers():
    report = build_source_registry_validation_report(".")
    reference_count, unique_count, duplicate_count = _expected_source_counts(Path("."))
    tushare_count = len(_source_rows(Path("."), "registry/sources/tushare_research_reports.jsonl"))

    assert report.accepted_for_sandbox
    assert not report.accepted_for_production
    assert report.failure_count == 0
    assert report.source_reference_count == reference_count
    assert report.unique_source_count == unique_count
    assert report.duplicate_reference_count == duplicate_count
    assert report.production_blocker_count == tushare_count


def test_source_registry_validation_rejects_missing_ingest_timestamp(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    source_path = tmp_path / "registry/sources/central_bank_sources.jsonl"
    row = json.loads(source_path.read_text(encoding="utf-8").splitlines()[0])
    row.pop("ingest_time", None)
    source_path.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    report = build_source_registry_validation_report(tmp_path)
    record = next(item for item in report.records if item.source_id == "SRC-CB-20260605-0001")

    assert not report.accepted_for_sandbox
    assert "ingest_time or discovered_at required" in record.failures


def test_source_registry_validation_rejects_non_object_source_rows(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    source_path = tmp_path / "registry/sources/central_bank_sources.jsonl"
    existing = source_path.read_text(encoding="utf-8")
    source_path.write_text(existing + json.dumps(["not", "an", "object"]) + "\n", encoding="utf-8")

    report = build_source_registry_validation_report(tmp_path)
    record = next(item for item in report.records if item.source_id.startswith("<non-object-row-"))

    assert not report.accepted_for_sandbox
    assert "source registry row must be object" in record.failures
    assert "source registry row must be object" in record.production_blockers


def test_source_registry_validation_rejects_non_object_license_review_rows(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    review_rows = review_path.read_text(encoding="utf-8").splitlines()
    review_path.write_text(
        "\n".join([*review_rows, json.dumps("not an object")]) + "\n",
        encoding="utf-8",
    )

    report = build_source_registry_validation_report(tmp_path)
    record = next(
        item for item in report.records if item.source_id.startswith("<license-review-non-object-row-")
    )

    assert not report.accepted_for_sandbox
    assert record.source_paths == ("registry/compliance/tushare_license_review_template.jsonl",)
    assert "source-license review row must be object" in record.failures


def test_source_registry_validation_writer_outputs_report(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)

    result = write_source_registry_validation_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert payload["accepted_for_sandbox"] is True
    assert payload["accepted_for_production"] is False
    assert payload["failure_count"] == 0
