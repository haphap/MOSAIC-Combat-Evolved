from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_source_registry_validation_report,
    write_source_registry_validation_report,
)


def _copy_registry(src_root: Path, dst_root: Path) -> None:
    shutil.copytree(src_root / "registry", dst_root / "registry")


def test_source_registry_validation_accepts_sandbox_but_reports_production_blockers():
    report = build_source_registry_validation_report(".")

    assert report.accepted_for_sandbox
    assert not report.accepted_for_production
    assert report.failure_count == 0
    assert report.unique_source_count == 208
    assert report.duplicate_reference_count == 1
    assert report.production_blocker_count == 207


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


def test_source_registry_validation_writer_outputs_report(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)

    result = write_source_registry_validation_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert payload["accepted_for_sandbox"] is True
    assert payload["accepted_for_production"] is False
    assert payload["failure_count"] == 0
