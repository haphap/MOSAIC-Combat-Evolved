"""Source-license manual review packet for RKE Phase -1 / C11."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .compliance import apply_source_license_reviews, evaluate_source_license
from .phase_minus1 import load_jsonl


LICENSE_REVIEW_PACKET_JSON_PATH = "registry/compliance/tushare_license_review_packet.json"
LICENSE_REVIEW_PACKET_MD_PATH = "registry/compliance/tushare_license_review_packet.md"
SOURCE_PATH = "registry/sources/tushare_research_reports.jsonl"
LICENSE_REVIEW_TEMPLATE_PATH = "registry/compliance/tushare_license_review_template.jsonl"

REQUIRED_REVIEW_FIELDS = (
    "approved_for_derived_claim_storage",
    "approved_for_production_runtime",
    "reviewer",
    "review_date",
)


@dataclass(frozen=True)
class LicenseReviewSourcePacket:
    source_id: str
    source_type: str
    title: str
    publish_date: str
    current_license_status: str
    reviewed: bool
    missing_review_fields: Sequence[str]
    allowed_for_sandbox: bool
    allowed_for_derived_claim_storage: bool
    allowed_for_production_runtime: bool
    policy_reasons: Sequence[str]


@dataclass(frozen=True)
class LicenseReviewPacket:
    packet_id: str
    status: str
    source_path: str
    review_path: str
    source_count: int
    review_row_count: int
    reviewed_sources: int
    pending_sources: int
    approved_for_derived_claim_storage: int
    approved_for_production_runtime: int
    current_license_status_counts: Mapping[str, int]
    source_type_counts: Mapping[str, int]
    policy_reason_counts: Mapping[str, int]
    required_review_fields: Sequence[str]
    records: Sequence[LicenseReviewSourcePacket]

    @property
    def manual_review_required(self) -> bool:
        return self.pending_sources > 0 or self.approved_for_production_runtime < self.source_count


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": 1}


def _review_by_source(reviews: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(row.get("source_id") or ""): row for row in reviews if row.get("source_id")}


def _missing_review_fields(row: Mapping[str, Any] | None) -> tuple[str, ...]:
    if row is None:
        return REQUIRED_REVIEW_FIELDS
    missing: list[str] = []
    for field in ("approved_for_derived_claim_storage", "approved_for_production_runtime"):
        if not isinstance(row.get(field), bool):
            missing.append(field)
    for field in ("reviewer", "review_date"):
        if not str(row.get(field) or "").strip():
            missing.append(field)
    return tuple(missing)


def build_license_review_packet(root: str | Path = ".") -> LicenseReviewPacket:
    root_path = Path(root)
    sources = load_jsonl(root_path / SOURCE_PATH)
    reviews = load_jsonl(root_path / LICENSE_REVIEW_TEMPLATE_PATH)
    review_lookup = _review_by_source(reviews)
    reviewed_sources = apply_source_license_reviews(
        sources,
        [row for row in reviews if not _missing_review_fields(row)],
    )
    reviewed_by_source = {str(row.get("source_id") or ""): row for row in reviewed_sources}

    records: list[LicenseReviewSourcePacket] = []
    reason_counts: Counter[str] = Counter()
    for source in sources:
        source_id = str(source.get("source_id") or "")
        review = review_lookup.get(source_id)
        missing_fields = _missing_review_fields(review)
        effective_source = reviewed_by_source.get(source_id, source)
        decision = evaluate_source_license(effective_source)
        reason_counts.update(decision.reasons)
        records.append(
            LicenseReviewSourcePacket(
                source_id=source_id,
                source_type=str(source.get("source_type") or ""),
                title=str(source.get("title") or ""),
                publish_date=str(source.get("publish_date") or ""),
                current_license_status=str(source.get("license_status") or "pending_review"),
                reviewed=not missing_fields,
                missing_review_fields=missing_fields,
                allowed_for_sandbox=decision.allowed_for_sandbox,
                allowed_for_derived_claim_storage=decision.allowed_for_derived_claim_storage,
                allowed_for_production_runtime=decision.allowed_for_production_runtime,
                policy_reasons=decision.reasons,
            )
        )

    return LicenseReviewPacket(
        packet_id="RKE-SOURCE-LICENSE-REVIEW-PACKET-20260606",
        status="manual_review_pending",
        source_path=SOURCE_PATH,
        review_path=LICENSE_REVIEW_TEMPLATE_PATH,
        source_count=len(sources),
        review_row_count=len(reviews),
        reviewed_sources=sum(record.reviewed for record in records),
        pending_sources=sum(not record.reviewed for record in records),
        approved_for_derived_claim_storage=sum(record.allowed_for_derived_claim_storage for record in records),
        approved_for_production_runtime=sum(record.allowed_for_production_runtime for record in records),
        current_license_status_counts=dict(Counter(record.current_license_status for record in records)),
        source_type_counts=dict(Counter(record.source_type for record in records)),
        policy_reason_counts=dict(reason_counts),
        required_review_fields=REQUIRED_REVIEW_FIELDS,
        records=tuple(records),
    )


def render_license_review_packet_markdown(packet: LicenseReviewPacket) -> str:
    lines = [
        "# RKE Source License Review Packet",
        "",
        f"- Status: {packet.status}",
        f"- Sources: {packet.source_count}",
        f"- Review rows: {packet.review_row_count}",
        f"- Pending sources: {packet.pending_sources}",
        f"- Approved for derived claim storage: {packet.approved_for_derived_claim_storage}",
        f"- Approved for production runtime: {packet.approved_for_production_runtime}",
        f"- Manual review required: {str(packet.manual_review_required).lower()}",
        "",
        "## Coverage",
        "",
        f"- Current license statuses: {json.dumps(dict(packet.current_license_status_counts), ensure_ascii=False, sort_keys=True)}",
        f"- Source types: {json.dumps(dict(packet.source_type_counts), ensure_ascii=False, sort_keys=True)}",
        f"- Policy reasons: {json.dumps(dict(packet.policy_reason_counts), ensure_ascii=False, sort_keys=True)}",
        "",
        "## Review Queue",
        "",
    ]
    for record in packet.records:
        missing = ", ".join(record.missing_review_fields) or "none"
        reasons = "; ".join(record.policy_reasons) or "none"
        lines.append(
            f"- {record.source_id} | {record.publish_date} | {record.current_license_status} | "
            f"reviewed={str(record.reviewed).lower()} | missing={missing} | production={record.allowed_for_production_runtime} | {reasons}"
        )
    return "\n".join(lines)


def write_license_review_packet(root: str | Path = ".") -> dict[str, str]:
    root_path = Path(root)
    packet = build_license_review_packet(root_path)
    json_result = _write_json(
        root_path / LICENSE_REVIEW_PACKET_JSON_PATH,
        {**asdict(packet), "manual_review_required": packet.manual_review_required},
    )
    md_path = root_path / LICENSE_REVIEW_PACKET_MD_PATH
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_license_review_packet_markdown(packet) + "\n", encoding="utf-8")
    return {"json": str(json_result["path"]), "markdown": str(md_path)}
