from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from mosaic.rke import (
    build_source_text_redaction_report,
    write_source_text_redaction_report,
)
from mosaic.rke.source_text_redaction import TEXT_MATCH_MIN_CHARS, _normalize_for_match


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")


def _first_tushare_abstract_snippet(root: Path, size: int = 160) -> str:
    source_path = root / "registry/sources/tushare_research_reports.jsonl"
    for line in source_path.read_text(encoding="utf-8").splitlines():
        abstract = str(json.loads(line).get("abstract") or "")
        if len("".join(abstract.split())) >= 100:
            return abstract[:size]
    raise AssertionError("expected at least one long Tushare abstract")


def _current_source_text_count(root: Path) -> int:
    source_path = root / "registry/sources/tushare_research_reports.jsonl"
    return sum(
        1
        for line in source_path.read_text(encoding="utf-8").splitlines()
        if len(_normalize_for_match(str(json.loads(line).get("abstract") or "")))
        >= TEXT_MATCH_MIN_CHARS
    )


def test_source_text_redaction_accepts_current_registry():
    report = build_source_text_redaction_report(".")

    assert report.accepted
    assert report.failure_count == 0
    assert report.malformed_source_row_count == 0
    assert report.blockers == ()
    assert report.source_text_count == _current_source_text_count(Path("."))
    assert report.fingerprint_count > report.source_text_count
    assert report.checked_path_count > 0
    assert report.min_match_chars == 80


def test_source_text_redaction_rejects_runtime_long_source_text(tmp_path: Path):
    _copy_registry(tmp_path)
    snippet = _first_tushare_abstract_snippet(tmp_path)
    runtime_path = tmp_path / "registry/runtime_outputs/source_text_leak.json"
    runtime_path.write_text(
        json.dumps({"bad_runtime_context": snippet}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = build_source_text_redaction_report(tmp_path)
    payload = json.dumps(asdict(report), ensure_ascii=False)

    assert not report.accepted
    assert report.failure_count >= 1
    assert any(record.artifact_path == "registry/runtime_outputs/source_text_leak.json" for record in report.records)
    assert snippet not in payload
    assert "matched_chunk_hashes" in payload


def test_source_text_redaction_reports_malformed_source_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    source_count = sum(1 for line in source_path.read_text(encoding="utf-8").splitlines() if line.strip())
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + json.dumps(["not", "an", "object"]) + "\n",
        encoding="utf-8",
    )

    report = build_source_text_redaction_report(tmp_path)
    result = write_source_text_redaction_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert not report.accepted
    assert report.failure_count == 0
    assert report.malformed_source_row_count == 1
    assert f"source registry row must be object at row(s): {source_count + 1}" in report.blockers
    assert payload["accepted"] is False
    assert payload["malformed_source_row_count"] == 1
    assert payload["blockers"] == list(report.blockers)


def test_source_text_redaction_reports_malformed_json_source_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    source_path.write_text(source_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8")

    report = build_source_text_redaction_report(tmp_path)
    result = write_source_text_redaction_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert not report.accepted
    assert report.failure_count == 0
    assert report.malformed_source_row_count == 1
    assert any("tushare_research_reports.jsonl row" in blocker for blocker in report.blockers)
    assert any("must contain valid JSON" in blocker for blocker in report.blockers)
    assert payload["accepted"] is False
    assert payload["malformed_source_row_count"] == 1
    assert payload["blockers"] == list(report.blockers)


def test_source_text_redaction_writer_outputs_report(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_source_text_redaction_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert payload["accepted"] is True
    assert payload["failure_count"] == 0
    assert payload["malformed_source_row_count"] == 0
    assert payload["blockers"] == []
    assert payload["source_text_count"] == _current_source_text_count(tmp_path)
    assert payload["allowed_raw_text_paths"]
