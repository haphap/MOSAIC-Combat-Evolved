"""Audit long sell-side source text exposure outside RKE sandbox artifacts."""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase_minus1 import load_jsonl


TUSHARE_SOURCE_PATH = "registry/sources/tushare_research_reports.jsonl"
SOURCE_TEXT_REDACTION_REPORT_PATH = "registry/compliance/source_text_redaction_report.json"

TEXT_MATCH_MIN_CHARS = 80
TEXT_MATCH_STRIDE_CHARS = 40

ALLOWED_RAW_TEXT_PATHS = (
    "registry/sources/tushare_research_reports.jsonl",
    "registry/sources/tushare_research_reports.gold_candidates.jsonl",
    "registry/gold_sets/tushare_research_reports.review_template.jsonl",
    "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl",
)

ALLOWED_RAW_TEXT_GLOBS = (
    "registry/gold_sets/tushare_research_reports.review_packet.*",
)

SCANNED_PATH_GLOBS = (
    "registry/**/*.json",
    "registry/**/*.jsonl",
    "registry/**/*.md",
    "registry/**/*.log",
    "registry/**/*.txt",
    "docs/**/*.md",
    "prompts/**/*.md",
    "mosaic/**/*.py",
    "mosaic-ts/src/**/*.ts",
    "mosaic-ts/src/**/*.tsx",
)


@dataclass(frozen=True)
class SourceTextExposureRecord:
    artifact_path: str
    source_id: str
    source_hash: str
    publish_date: str
    matched_chunk_count: int
    matched_chunk_hashes: Sequence[str]
    failure: str


@dataclass(frozen=True)
class SourceTextRedactionReport:
    report_id: str
    accepted: bool
    failure_count: int
    source_path: str
    source_text_count: int
    malformed_source_row_count: int
    fingerprint_count: int
    checked_path_count: int
    skipped_allowed_path_count: int
    min_match_chars: int
    scanned_path_globs: Sequence[str]
    allowed_raw_text_paths: Sequence[str]
    allowed_raw_text_globs: Sequence[str]
    blockers: Sequence[str]
    records: Sequence[SourceTextExposureRecord]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _split_mapping_rows(rows: Sequence[Any]) -> tuple[list[Mapping[str, Any]], tuple[int, ...]]:
    valid_rows: list[Mapping[str, Any]] = []
    invalid_row_numbers: list[int] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid_rows.append(row)
        else:
            invalid_row_numbers.append(index)
    return valid_rows, tuple(invalid_row_numbers)


def _normalize_for_match(text: str) -> str:
    normalized = text.replace("\\n", "").replace("\\r", "").replace("\\t", "")
    normalized = normalized.replace("\u3000", "")
    return re.sub(r"\s+", "", normalized)


def _short_hash(text: str) -> str:
    return "sha256:" + sha256(text.encode("utf-8")).hexdigest()[:16]


def _matches_any(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _allowed_raw_text_path(path: str) -> bool:
    return path in ALLOWED_RAW_TEXT_PATHS or _matches_any(path, ALLOWED_RAW_TEXT_GLOBS)


def _iter_scanned_paths(root_path: Path) -> tuple[tuple[str, Path], int]:
    found: dict[str, Path] = {}
    skipped_allowed = 0
    for pattern in SCANNED_PATH_GLOBS:
        for path in root_path.glob(pattern):
            if not path.is_file():
                continue
            relative = path.relative_to(root_path).as_posix()
            if _allowed_raw_text_path(relative):
                skipped_allowed += 1
                continue
            found[relative] = path
    return tuple(sorted(found.items())), skipped_allowed


def _source_text_fingerprints(
    root_path: Path,
) -> tuple[tuple[tuple[str, Mapping[str, str]], ...], int, tuple[int, ...]]:
    source_path = root_path / TUSHARE_SOURCE_PATH
    if not source_path.exists():
        return (), 0, ()

    fingerprints: dict[str, Mapping[str, str]] = {}
    source_text_count = 0
    rows, invalid_rows = _split_mapping_rows(load_jsonl(source_path))
    for row in rows:
        abstract = _normalize_for_match(str(row.get("abstract") or ""))
        if len(abstract) < TEXT_MATCH_MIN_CHARS:
            continue
        source_text_count += 1
        starts = list(range(0, max(len(abstract) - TEXT_MATCH_MIN_CHARS + 1, 1), TEXT_MATCH_STRIDE_CHARS))
        last_start = max(len(abstract) - TEXT_MATCH_MIN_CHARS, 0)
        if last_start not in starts:
            starts.append(last_start)
        metadata = {
            "source_id": str(row.get("source_id") or ""),
            "source_hash": str(row.get("source_hash") or ""),
            "publish_date": str(row.get("publish_date") or ""),
        }
        for start in starts:
            chunk = abstract[start : start + TEXT_MATCH_MIN_CHARS]
            if len(chunk) >= TEXT_MATCH_MIN_CHARS:
                fingerprints.setdefault(chunk, metadata)
    return (
        tuple(sorted(fingerprints.items(), key=lambda item: (item[1]["source_id"], item[0]))),
        source_text_count,
        invalid_rows,
    )


def build_source_text_redaction_report(root: str | Path = ".") -> SourceTextRedactionReport:
    root_path = Path(root)
    fingerprints, source_text_count, invalid_source_rows = _source_text_fingerprints(root_path)
    fingerprint_lookup = dict(fingerprints)
    scanned_paths, skipped_allowed = _iter_scanned_paths(root_path)
    records: list[SourceTextExposureRecord] = []
    blockers: list[str] = []
    if invalid_source_rows:
        blockers.append(
            "source registry row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_source_rows)
        )

    for relative, path in scanned_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        normalized = _normalize_for_match(text)
        matches_by_source: dict[tuple[str, str, str], list[str]] = {}
        if len(normalized) < TEXT_MATCH_MIN_CHARS:
            continue
        for start in range(0, len(normalized) - TEXT_MATCH_MIN_CHARS + 1):
            chunk = normalized[start : start + TEXT_MATCH_MIN_CHARS]
            metadata = fingerprint_lookup.get(chunk)
            if metadata is None:
                continue
            key = (
                metadata["source_id"],
                metadata["source_hash"],
                metadata["publish_date"],
            )
            matches_by_source.setdefault(key, []).append(_short_hash(chunk))
        for (source_id, source_hash, publish_date), chunk_hashes in sorted(matches_by_source.items()):
            records.append(
                SourceTextExposureRecord(
                    artifact_path=relative,
                    source_id=source_id,
                    source_hash=source_hash,
                    publish_date=publish_date,
                    matched_chunk_count=len(set(chunk_hashes)),
                    matched_chunk_hashes=tuple(sorted(set(chunk_hashes))[:20]),
                    failure="long Tushare research-report text appears outside approved sandbox artifacts",
                )
            )

    return SourceTextRedactionReport(
        report_id="RKE-SOURCE-TEXT-REDACTION-REPORT-20260606",
        accepted=not records and not blockers,
        failure_count=len(records),
        source_path=TUSHARE_SOURCE_PATH,
        source_text_count=source_text_count,
        malformed_source_row_count=len(invalid_source_rows),
        fingerprint_count=len(fingerprints),
        checked_path_count=len(scanned_paths),
        skipped_allowed_path_count=skipped_allowed,
        min_match_chars=TEXT_MATCH_MIN_CHARS,
        scanned_path_globs=SCANNED_PATH_GLOBS,
        allowed_raw_text_paths=ALLOWED_RAW_TEXT_PATHS,
        allowed_raw_text_globs=ALLOWED_RAW_TEXT_GLOBS,
        blockers=tuple(blockers),
        records=tuple(records),
    )


def write_source_text_redaction_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_source_text_redaction_report(root_path)
    return _write_json(root_path / SOURCE_TEXT_REDACTION_REPORT_PATH, asdict(report))
