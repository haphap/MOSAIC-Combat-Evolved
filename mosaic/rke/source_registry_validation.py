"""Source registry validation gate for RKE source-checker requirements."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .compliance import apply_source_license_reviews, evaluate_source_license
from .phase_minus1 import load_jsonl


SOURCE_REGISTRY_PATHS = (
    "registry/sources/central_bank_sources.jsonl",
    "registry/sources/tushare_research_reports.jsonl",
    "registry/sources/semiconductor_demo_sources.jsonl",
)
SOURCE_LICENSE_REVIEW_PATH = "registry/compliance/tushare_license_review_template.jsonl"
SOURCE_VALIDATION_REPORT_PATH = "registry/source_checks/source_registry_validation_report.json"


@dataclass(frozen=True)
class SourceRegistryValidationRecord:
    source_id: str
    source_paths: Sequence[str]
    accepted_for_sandbox: bool
    accepted_for_production: bool
    failures: Sequence[str]
    production_blockers: Sequence[str]


@dataclass(frozen=True)
class SourceRegistryValidationReport:
    report_id: str
    source_paths: Sequence[str]
    source_reference_count: int
    unique_source_count: int
    duplicate_reference_count: int
    accepted_for_sandbox: bool
    accepted_for_production: bool
    failure_count: int
    production_blocker_count: int
    records: Sequence[SourceRegistryValidationRecord]


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
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": 1}


def _license_row_reviewed(row: Mapping[str, Any]) -> bool:
    return (
        isinstance(row.get("approved_for_derived_claim_storage"), bool)
        and isinstance(row.get("approved_for_production_runtime"), bool)
        and bool(str(row.get("reviewer") or "").strip())
        and bool(str(row.get("review_date") or "").strip())
    )


def _invalid_row_record(
    *,
    source_id: str,
    source_path: str,
    reason: str,
) -> SourceRegistryValidationRecord:
    return SourceRegistryValidationRecord(
        source_id=source_id,
        source_paths=(source_path,),
        accepted_for_sandbox=False,
        accepted_for_production=False,
        failures=(reason,),
        production_blockers=(reason,),
    )


def _load_sources(
    root_path: Path,
) -> tuple[list[tuple[str, Mapping[str, Any]]], list[SourceRegistryValidationRecord]]:
    rows: list[tuple[str, Mapping[str, Any]]] = []
    invalid_records: list[SourceRegistryValidationRecord] = []
    for relative in SOURCE_REGISTRY_PATHS:
        path = root_path / relative
        if not path.exists():
            continue
        for index, row in enumerate(load_jsonl(path), 1):
            if isinstance(row, Mapping):
                rows.append((relative, row))
            else:
                invalid_records.append(
                    _invalid_row_record(
                        source_id=f"<non-object-row-{relative}:{index}>",
                        source_path=relative,
                        reason="source registry row must be object",
                    )
                )
    review_path = root_path / SOURCE_LICENSE_REVIEW_PATH
    if review_path.exists() and rows:
        reviews: list[Mapping[str, Any]] = []
        for index, row in enumerate(load_jsonl(review_path), 1):
            if not isinstance(row, Mapping):
                invalid_records.append(
                    _invalid_row_record(
                        source_id=f"<license-review-non-object-row-{index}>",
                        source_path=SOURCE_LICENSE_REVIEW_PATH,
                        reason="source-license review row must be object",
                    )
                )
                continue
            if _license_row_reviewed(row):
                reviews.append(row)
        if reviews:
            reviewed_rows = apply_source_license_reviews([row for _, row in rows], reviews)
            rows = [(path, dict(reviewed_row)) for (path, _), reviewed_row in zip(rows, reviewed_rows, strict=True)]
    return rows, invalid_records


def _timestamp(row: Mapping[str, Any]) -> str:
    return str(row.get("ingest_time") or row.get("discovered_at") or "").strip()


def _validate_source_group(
    source_id: str,
    entries: Sequence[tuple[str, Mapping[str, Any]]],
) -> SourceRegistryValidationRecord:
    failures: list[str] = []
    production_blockers: list[str] = []
    source_paths = tuple(sorted({path for path, _ in entries}))
    rows = [row for _, row in entries]
    first = rows[0] if rows else {}

    if not source_id:
        failures.append("source_id required")
    for field in ("source_type", "publish_date", "source_hash", "license_status"):
        values = {str(row.get(field) or "").strip() for row in rows}
        if "" in values:
            failures.append(f"{field} required")
        if len(values - {""}) > 1:
            failures.append(f"{field} differs across duplicate source references")
    if not any(_timestamp(row) for row in rows):
        failures.append("ingest_time or discovered_at required")
    if any(row.get("point_in_time_available") is not True for row in rows):
        failures.append("point_in_time_available must be true")
    hashes = {str(row.get("source_hash") or "") for row in rows}
    if any(not value.startswith("sha256:") for value in hashes):
        failures.append("source_hash must be sha256:<digest>")

    decision = evaluate_source_license(first)
    if not decision.allowed_for_ingest:
        failures.extend(decision.reasons)
    if not decision.allowed_for_sandbox:
        failures.append("source is not allowed for sandbox use")
    if not decision.allowed_for_production_runtime:
        production_blockers.extend(decision.reasons or ("source is not production-approved",))

    return SourceRegistryValidationRecord(
        source_id=source_id or "<missing-source-id>",
        source_paths=source_paths,
        accepted_for_sandbox=not failures and decision.allowed_for_sandbox,
        accepted_for_production=not failures and decision.allowed_for_production_runtime,
        failures=tuple(failures),
        production_blockers=tuple(production_blockers),
    )


def build_source_registry_validation_report(root: str | Path = ".") -> SourceRegistryValidationReport:
    root_path = Path(root)
    entries, invalid_records = _load_sources(root_path)
    grouped: dict[str, list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    for path, row in entries:
        grouped[str(row.get("source_id") or "")].append((path, row))
    records = tuple(
        [
            *invalid_records,
            *[
                _validate_source_group(source_id, grouped[source_id])
                for source_id in sorted(grouped)
            ],
        ]
    )
    invalid_source_reference_count = sum(
        1
        for record in invalid_records
        if record.source_paths and record.source_paths[0] in SOURCE_REGISTRY_PATHS
    )
    source_reference_count = len(entries) + invalid_source_reference_count
    unique_source_record_count = len(grouped) + invalid_source_reference_count
    failure_count = sum(len(record.failures) for record in records)
    production_blocker_count = sum(len(record.production_blockers) for record in records)
    return SourceRegistryValidationReport(
        report_id="RKE-SOURCE-REGISTRY-VALIDATION-REPORT-20260606",
        source_paths=SOURCE_REGISTRY_PATHS,
        source_reference_count=source_reference_count,
        unique_source_count=len(records),
        duplicate_reference_count=max(source_reference_count - unique_source_record_count, 0),
        accepted_for_sandbox=bool(records) and failure_count == 0,
        accepted_for_production=bool(records) and failure_count == 0 and production_blocker_count == 0,
        failure_count=failure_count,
        production_blocker_count=production_blocker_count,
        records=records,
    )


def write_source_registry_validation_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_source_registry_validation_report(root_path)
    return _write_json(root_path / SOURCE_VALIDATION_REPORT_PATH, asdict(report))
