"""Phase -1 feasibility helpers for RKE.

Phase -1 is not production validation. It audits source corpora and prepares
gold-set sampling so the team can decide whether schema freeze is justified.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


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
