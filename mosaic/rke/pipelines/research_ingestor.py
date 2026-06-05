"""Research ingestor pipeline component."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..p0 import ResearchSourceMetadata, canonical_json_hash


@dataclass(frozen=True)
class SourceSpan:
    source_span_id: str
    text: str
    ordinal: int


@dataclass(frozen=True)
class IngestedDocument:
    metadata: ResearchSourceMetadata
    spans: Sequence[SourceSpan]

    @property
    def source_spans(self) -> dict[str, str]:
        return {span.source_span_id: span.text for span in self.spans}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _span_text(row: Mapping[str, Any]) -> str:
    explicit = _clean_text(row.get("source_span_text"))
    if explicit:
        return explicit
    parts = [
        _clean_text(row.get("title")),
        _clean_text(row.get("abstract")),
    ]
    return "\n\n".join(part for part in parts if part)


def ingest_source_row(row: Mapping[str, Any], *, default_license_status: str = "pending_review") -> IngestedDocument:
    """Normalize a source row into metadata and source spans.

    The ingestor preserves source meaning: it only copies title/abstract/span
    text and computes missing IDs/hashes from stable source fields.
    """
    span_text = _span_text(row)
    source_hash = _clean_text(row.get("source_hash")) or canonical_json_hash(
        {
            "source_type": row.get("source_type"),
            "publish_date": row.get("publish_date"),
            "title": row.get("title"),
            "span_text": span_text,
        }
    )
    source_id = _clean_text(row.get("source_id")) or f"SRC-RKE-{source_hash.split(':', 1)[-1][:16]}"
    source_span_id = _clean_text(row.get("source_span_id")) or f"{source_id}:span-0001"
    metadata = ResearchSourceMetadata(
        source_id=source_id,
        source_type=_clean_text(row.get("source_type")) or "unknown",
        publish_date=_clean_text(row.get("publish_date")),
        ingest_time=_clean_text(row.get("ingest_time") or row.get("discovered_at")),
        license_status=_clean_text(row.get("license_status")) or default_license_status,
        point_in_time_available=bool(row.get("point_in_time_available")),
        source_hash=source_hash,
    )
    spans = (SourceSpan(source_span_id=source_span_id, text=span_text, ordinal=1),)
    return IngestedDocument(metadata=metadata, spans=spans)
