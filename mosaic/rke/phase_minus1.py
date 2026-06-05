"""Phase -1 feasibility helpers for RKE.

Phase -1 is not production validation. It audits source corpora and prepares
gold-set sampling so the team can decide whether schema freeze is justified.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .p0 import ClaimExtractionGoldSet


REQUIRED_SOURCE_ROW_FIELDS = {
    "source_id",
    "source_span_id",
    "source_type",
    "publish_date",
    "discovered_at",
    "title",
    "abstract",
    "source_hash",
    "point_in_time_available",
    "license_status",
}


@dataclass(frozen=True)
class CorpusAudit:
    row_count: int
    rows_with_abstract: int
    report_type_counts: Mapping[str, int]
    query_key_counts: Mapping[str, int]
    publish_date_min: str | None
    publish_date_max: str | None
    missing_required_fields: Mapping[str, tuple[str, ...]]
    duplicate_source_hashes: tuple[str, ...]
    production_blockers: tuple[str, ...]

    @property
    def ready_for_gold_set_sampling(self) -> bool:
        return (
            self.row_count > 0
            and self.rows_with_abstract == self.row_count
            and not self.missing_required_fields
            and not self.duplicate_source_hashes
        )


@dataclass(frozen=True)
class GoldSetReviewRecord:
    source_id: str
    source_span_id: str
    claim_id: str
    document_id: str
    claim_correct: bool
    source_span_supports_claim: bool
    direction_correct: bool
    variable_mapping_correct: bool
    unsupported_field_false_grounded: bool


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def audit_research_report_corpus(rows: Sequence[Mapping[str, Any]]) -> CorpusAudit:
    report_type_counts = Counter(str(row.get("report_type") or "") for row in rows)
    query_key_counts = Counter(str(row.get("query_key") or "") for row in rows)
    publish_dates = sorted(str(row.get("publish_date") or "") for row in rows if row.get("publish_date"))
    hash_counts = Counter(str(row.get("source_hash") or "") for row in rows)
    duplicate_hashes = tuple(sorted(hash_value for hash_value, count in hash_counts.items() if hash_value and count > 1))

    missing: dict[str, tuple[str, ...]] = {}
    blockers: list[str] = []
    for row in rows:
        source_id = str(row.get("source_id") or f"row-{len(missing)}")
        row_missing = tuple(sorted(field for field in REQUIRED_SOURCE_ROW_FIELDS if row.get(field) in (None, "")))
        if row_missing:
            missing[source_id] = row_missing
        if row.get("license_status") != "approved":
            blockers.append(f"{source_id}: license_status={row.get('license_status')} blocks production")
        if row.get("point_in_time_available") is not True:
            blockers.append(f"{source_id}: point_in_time_available is not true")

    return CorpusAudit(
        row_count=len(rows),
        rows_with_abstract=sum(bool(str(row.get("abstract") or "").strip()) for row in rows),
        report_type_counts=dict(report_type_counts),
        query_key_counts=dict(query_key_counts),
        publish_date_min=publish_dates[0] if publish_dates else None,
        publish_date_max=publish_dates[-1] if publish_dates else None,
        missing_required_fields=missing,
        duplicate_source_hashes=duplicate_hashes,
        production_blockers=tuple(blockers),
    )


def select_gold_set_candidates(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_documents: int = 50,
) -> list[dict[str, Any]]:
    """Select a balanced deterministic sample by query key and report type."""
    if max_documents <= 0:
        return []
    ordered = sorted(
        rows,
        key=lambda row: (
            str(row.get("query_key") or ""),
            str(row.get("report_type") or ""),
            str(row.get("publish_date") or ""),
            str(row.get("source_id") or ""),
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    buckets: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in ordered:
        buckets.setdefault((str(row.get("query_key") or ""), str(row.get("report_type") or "")), []).append(row)
    while len(selected) < max_documents:
        progressed = False
        for bucket in sorted(buckets):
            candidates = buckets[bucket]
            while candidates:
                row = candidates.pop(0)
                source_id = str(row.get("source_id") or "")
                if source_id and source_id not in seen:
                    selected.append(dict(row))
                    seen.add(source_id)
                    progressed = True
                    break
            if len(selected) >= max_documents:
                break
        if not progressed:
            break
    return selected


def write_gold_set_candidates(
    candidates: Iterable[Mapping[str, Any]],
    output_path: str | Path,
) -> dict[str, Any]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(candidates)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"path": str(path), "rows": len(rows)}


def build_gold_set_review_template(
    candidates: Sequence[Mapping[str, Any]],
    *,
    claims_per_document: int = 10,
    span_preview_chars: int = 600,
) -> list[dict[str, Any]]:
    """Create blank manual-review rows from sampled source documents."""
    if claims_per_document <= 0:
        raise ValueError("claims_per_document must be positive")
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        source_id = str(candidate.get("source_id") or "")
        span_id = str(candidate.get("source_span_id") or f"{source_id}:abstract")
        text = str(candidate.get("abstract") or candidate.get("source_span_text") or "")
        for idx in range(1, claims_per_document + 1):
            rows.append(
                {
                    "source_id": source_id,
                    "source_span_id": span_id,
                    "claim_id": f"GOLD-{source_id}-{idx:03d}",
                    "document_id": source_id,
                    "span_preview": text[:span_preview_chars],
                    "manual_claim_text": "",
                    "claim_correct": None,
                    "source_span_supports_claim": None,
                    "direction_correct": None,
                    "variable_mapping_correct": None,
                    "unsupported_field_false_grounded": None,
                    "reviewer": "",
                    "review_notes": "",
                }
            )
    return rows


def write_gold_set_review_template(
    candidates: Sequence[Mapping[str, Any]],
    output_path: str | Path,
    *,
    claims_per_document: int = 10,
) -> dict[str, Any]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = build_gold_set_review_template(candidates, claims_per_document=claims_per_document)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"path": str(path), "rows": len(rows)}


def evaluate_gold_set_reviews(
    records: Sequence[GoldSetReviewRecord | Mapping[str, Any]],
    *,
    gold_set_id: str,
) -> ClaimExtractionGoldSet:
    normalized: list[dict[str, Any]] = [
        asdict(record) if isinstance(record, GoldSetReviewRecord) else dict(record)
        for record in records
    ]
    n = len(normalized)
    if n == 0:
        return ClaimExtractionGoldSet(
            gold_set_id=gold_set_id,
            sample_size_documents=0,
            sample_size_claims=0,
            claim_precision=0.0,
            source_span_support_precision=0.0,
            direction_accuracy=0.0,
            variable_mapping_accuracy=0.0,
            unsupported_field_false_grounding_rate=1.0,
        )
    documents = {str(record.get("document_id") or record.get("source_id") or "") for record in normalized}

    def rate(field: str) -> float:
        return round(sum(record.get(field) is True for record in normalized) / n, 6)

    return ClaimExtractionGoldSet(
        gold_set_id=gold_set_id,
        sample_size_documents=len(documents - {""}),
        sample_size_claims=n,
        claim_precision=rate("claim_correct"),
        source_span_support_precision=rate("source_span_supports_claim"),
        direction_accuracy=rate("direction_correct"),
        variable_mapping_accuracy=rate("variable_mapping_correct"),
        unsupported_field_false_grounding_rate=round(
            sum(record.get("unsupported_field_false_grounded") is True for record in normalized) / n,
            6,
        ),
    )
