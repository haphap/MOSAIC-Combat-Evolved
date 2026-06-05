"""Tushare research-report ingestion for RKE Phase -1.

The agent-facing report tools return Markdown. RKE needs structured,
point-in-time source rows that can feed source-grounded claim extraction. This
module calls Tushare ``pro.research_report`` and persists sanitized JSONL rows
with source IDs, span IDs, hashes, publication dates, and discovery timestamps.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from mosaic.dataflows.tushare import _RESEARCH_REPORT_FIELDS, _get_pro_client

from .audit_viewer import write_audit_trace_view
from .completion_auditor import write_completion_audit
from .compliance import write_source_license_review_template
from .claim_vocabulary import write_claim_variable_validation_report, write_claim_variable_vocabulary
from .dashboard_reports import write_dashboard_reports
from .gold_candidate_claims import write_gold_candidate_claims
from .gold_review_packet import write_gold_review_packet
from .license_review_packet import write_license_review_packet
from .manual_review_batches import write_manual_review_batches
from .operator_handoff import write_operator_handoff
from .operator_readiness import write_operator_readiness_report
from .master_plan_coverage import write_master_plan_coverage_report
from .monitoring_diagnostics import write_production_monitor_diagnostics
from .phase_minus1 import (
    audit_research_report_corpus,
    load_jsonl,
    select_gold_set_candidates,
    write_gold_set_candidates,
    write_gold_set_review_template,
)
from .policy_doc_validation import write_policy_doc_validation_report
from .prompt_asset_validation import write_prompt_asset_validation_report
from .promotion_gate import write_production_promotion_gate_report
from .registry_manifest import write_registry_manifest
from .review_gates import write_gold_set_review_summary, write_source_license_review_summary
from .rollback_readiness import write_rollback_readiness_report
from .schema_validation import write_schema_validation_report
from .source_registry_validation import write_source_registry_validation_report
from .source_text_redaction import write_source_text_redaction_report
from .validation_hardening import (
    write_statistical_significance_report,
    write_validation_hardening_report,
)

ReportKind = Literal["stock", "industry"]
TUSHARE_RESEARCH_REPORT_PAGE_SIZE = 1000


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _api_date(date: str) -> str:
    return date.replace("-", "")


def _published_date(value: object) -> str:
    raw = str(value or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + sha256(encoded).hexdigest()


@dataclass(frozen=True)
class RkeResearchReport:
    source_id: str
    source_span_id: str
    source_type: str
    report_type: str
    query_key: str
    publish_date: str
    discovered_at: str
    title: str
    abstract: str
    author: str
    institution: str
    ts_code: str
    industry: str
    url: str
    source_hash: str
    point_in_time_available: bool = True
    license_status: str = "pending_review"

    @property
    def source_span_text(self) -> str:
        parts = [
            self.title,
            self.abstract,
        ]
        return "\n\n".join(part for part in parts if part)


@dataclass(frozen=True)
class TushareResearchReportRefreshResult:
    root: str
    source_rows: int
    rows_with_abstract: int
    gold_candidate_rows: int
    gold_review_template_updated: bool
    license_review_template_updated: bool
    publish_date_min: str | None
    publish_date_max: str | None
    report_type_counts: Mapping[str, int]
    query_key_counts: Mapping[str, int]
    completion_ready_for_broad_rollout: bool
    manifest_valid: bool
    outputs: Mapping[str, str]


def normalize_research_report_row(
    row: Mapping[str, Any],
    *,
    report_type: str,
    query_key: str,
    discovered_at: str,
) -> RkeResearchReport:
    title = str(row.get("title") or "").strip()
    abstract = str(row.get("abstr") or "").strip()
    publish_date = _published_date(row.get("trade_date"))
    ts_code = str(row.get("ts_code") or "").strip()
    industry = str(row.get("ind_name") or "").strip()
    institution = str(row.get("inst_csname") or "").strip()
    author = str(row.get("author") or "").strip()
    url = str(row.get("url") or "").strip()
    hash_payload = {
        "report_type": report_type,
        "query_key": query_key,
        "publish_date": publish_date,
        "title": title,
        "abstract": abstract,
        "institution": institution,
        "ts_code": ts_code,
        "industry": industry,
        "url": url,
    }
    source_hash = _stable_hash(hash_payload)
    digest = source_hash.split("sha256:", 1)[1][:16]
    source_id = f"SRC-TSRR-{publish_date.replace('-', '') or 'UNKNOWN'}-{digest}"
    return RkeResearchReport(
        source_id=source_id,
        source_span_id=f"{source_id}:abstract",
        source_type="tushare_research_report",
        report_type=report_type,
        query_key=query_key,
        publish_date=publish_date,
        discovered_at=discovered_at,
        title=title,
        abstract=abstract,
        author=author,
        institution=institution,
        ts_code=ts_code,
        industry=industry,
        url=url,
        source_hash=source_hash,
    )


def _df_to_records(df: Any) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    return list(df.to_dict("records"))


def _fetch_research_report_pages(
    client: Any,
    *,
    max_reports_per_query: int,
    **params: Any,
) -> list[dict[str, Any]]:
    """Fetch Tushare research_report pages until the local cap or exhaustion.

    The endpoint documents larger row limits, but live calls can still return a
    fixed 1000-row page. Explicit offset paging prevents silent truncation when
    a date window has more than one page of reports.
    """
    if max_reports_per_query <= 0:
        raise ValueError("max_reports_per_query must be positive")

    page_size = min(max_reports_per_query, TUSHARE_RESEARCH_REPORT_PAGE_SIZE)
    records: list[dict[str, Any]] = []
    offset = 0
    while len(records) < max_reports_per_query:
        page = _df_to_records(
            client.research_report(
                **params,
                limit=page_size,
                offset=offset,
            )
        )
        if not page:
            break
        remaining = max_reports_per_query - len(records)
        records.extend(page[:remaining])
        if len(page) < page_size:
            break
        offset += page_size
    return records


def _chunked(values: Sequence[str], size: int) -> list[tuple[str, ...]]:
    if size <= 0:
        raise ValueError("stock_query_batch_size must be positive")
    normalized = tuple(str(value or "").strip() for value in values if str(value or "").strip())
    return [normalized[index : index + size] for index in range(0, len(normalized), size)]


def _date_windows(start_date: str, end_date: str, chunk_days: int) -> list[tuple[str, str]]:
    if chunk_days <= 0:
        raise ValueError("date_chunk_days must be positive")
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ValueError("start_date must be on or before end_date")

    windows: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=chunk_days - 1), end)
        windows.append((_api_date(cursor.isoformat()), _api_date(window_end.isoformat())))
        cursor = window_end + timedelta(days=1)
    return windows


def _broad_query_key(row: Mapping[str, Any], report_type: str) -> str:
    ts_code = str(row.get("ts_code") or "").strip()
    if ts_code:
        return ts_code
    industry = str(row.get("ind_name") or "").strip()
    if industry:
        return industry
    return report_type


def _fetch_stock_batch_records(
    client: Any,
    stock_batch: Sequence[str],
    *,
    start_api: str,
    end_api: str,
    max_reports_per_query: int,
) -> list[dict[str, Any]]:
    batch_key = ",".join(stock_batch)
    records: list[dict[str, Any]] = []
    try:
        records = _fetch_research_report_pages(
            client,
            ts_code=batch_key,
            start_date=start_api,
            end_date=end_api,
            report_type="个股研报",
            fields=_RESEARCH_REPORT_FIELDS,
            max_reports_per_query=max_reports_per_query,
        )
    except Exception:
        if len(stock_batch) == 1:
            raise

    if records or len(stock_batch) == 1:
        return records[:max_reports_per_query]

    # Some Tushare endpoints document comma-separated ``ts_code`` support, but
    # research_report can return zero rows for a batch while single-code queries
    # return data. Preserve correctness by falling back when the whole batch is
    # empty.
    fallback_records: list[dict[str, Any]] = []
    for ts_code in stock_batch:
        fallback_records.extend(
            _fetch_research_report_pages(
                client,
                ts_code=ts_code,
                start_date=start_api,
                end_date=end_api,
                report_type="个股研报",
                fields=_RESEARCH_REPORT_FIELDS,
                max_reports_per_query=max_reports_per_query,
            )
        )
    return fallback_records[:max_reports_per_query]


def _fetch_industry_records(
    client: Any,
    industry: str,
    *,
    start_api: str,
    end_api: str,
    max_reports_per_query: int,
) -> list[dict[str, Any]]:
    return _fetch_research_report_pages(
        client,
        ind_name=industry,
        start_date=start_api,
        end_date=end_api,
        report_type="行业研报",
        fields=_RESEARCH_REPORT_FIELDS,
        max_reports_per_query=max_reports_per_query,
    )


def _fetch_report_type_records(
    client: Any,
    report_type: str,
    *,
    start_api: str,
    end_api: str,
    max_reports_per_query: int,
) -> list[dict[str, Any]]:
    return _fetch_research_report_pages(
        client,
        start_date=start_api,
        end_date=end_api,
        report_type=report_type,
        fields=_RESEARCH_REPORT_FIELDS,
        max_reports_per_query=max_reports_per_query,
    )


def fetch_tushare_research_reports(
    *,
    stock_codes: Sequence[str] = (),
    industry_keywords: Sequence[str] = (),
    report_types: Sequence[str] = (),
    start_date: str,
    end_date: str,
    max_reports_per_query: int = 100,
    stock_query_batch_size: int = 50,
    date_chunk_days: int = 31,
    discovered_at: str | None = None,
    pro: Any | None = None,
) -> list[RkeResearchReport]:
    """Fetch stock and/or industry research reports from Tushare.

    ``stock_codes`` should be Tushare codes such as ``600519.SH``. Industry
    keywords are passed to Tushare's ``ind_name`` field. Stock codes are batched
    into comma-separated ``ts_code`` queries because Tushare supports fetching
    multiple stock-report codes per request. ``report_types`` query full-market
    reports by date window, which is the preferred mode for corpus collection.
    """
    client = pro or _get_pro_client()
    stamp = discovered_at or _utc_now()
    start_api = _api_date(start_date)
    end_api = _api_date(end_date)
    reports: list[RkeResearchReport] = []

    for report_type in tuple(str(value or "").strip() for value in report_types if str(value or "").strip()):
        for window_start_api, window_end_api in _date_windows(start_date, end_date, date_chunk_days):
            for row in _fetch_report_type_records(
                client,
                report_type,
                start_api=window_start_api,
                end_api=window_end_api,
                max_reports_per_query=max_reports_per_query,
            ):
                reports.append(
                    normalize_research_report_row(
                        row,
                        report_type=report_type,
                        query_key=_broad_query_key(row, report_type),
                        discovered_at=stamp,
                    )
                )

    for stock_batch in _chunked(stock_codes, stock_query_batch_size):
        records = _fetch_stock_batch_records(
            client,
            stock_batch,
            start_api=start_api,
            end_api=end_api,
            max_reports_per_query=max_reports_per_query,
        )
        for row in records:
            reports.append(
                normalize_research_report_row(
                    row,
                    report_type="个股研报",
                    query_key=str(row.get("ts_code") or "").strip() or ",".join(stock_batch),
                    discovered_at=stamp,
                )
            )

    for industry in industry_keywords:
        records = _fetch_industry_records(
            client,
            industry,
            start_api=start_api,
            end_api=end_api,
            max_reports_per_query=max_reports_per_query,
        )
        for row in records:
            reports.append(
                normalize_research_report_row(
                    row,
                    report_type="行业研报",
                    query_key=industry,
                    discovered_at=stamp,
                )
            )

    deduped: dict[str, RkeResearchReport] = {}
    for report in reports:
        deduped.setdefault(report.source_hash, report)
    return sorted(deduped.values(), key=lambda item: (item.publish_date, item.source_id), reverse=True)


def write_research_reports_jsonl(
    reports: Iterable[RkeResearchReport],
    output_path: str | Path,
) -> dict[str, Any]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(report) for report in reports]
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"path": str(path), "rows": len(rows)}


def _template_has_manual_values(path: Path, fields: Sequence[str]) -> bool:
    if not path.exists():
        return False
    for row in load_jsonl(path):
        for field in fields:
            if row.get(field) not in (None, ""):
                return True
    return False


def _existing_discovered_at_by_hash(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    discovered: dict[str, str] = {}
    for row in load_jsonl(path):
        source_hash = str(row.get("source_hash") or "").strip()
        discovered_at = str(row.get("discovered_at") or "").strip()
        if source_hash and discovered_at:
            discovered[source_hash] = discovered_at
    return discovered


def _preserve_existing_discovery_times(
    reports: Sequence[RkeResearchReport],
    existing_discovered_at: Mapping[str, str],
) -> list[RkeResearchReport]:
    preserved: list[RkeResearchReport] = []
    for report in reports:
        discovered_at = existing_discovered_at.get(report.source_hash)
        preserved.append(replace(report, discovered_at=discovered_at) if discovered_at else report)
    return preserved


def _write_research_report_manifest(
    *,
    output_path: Path,
    source_path: Path,
    start_date: str,
    end_date: str,
    stock_codes: Sequence[str],
    industry_keywords: Sequence[str],
    report_types: Sequence[str],
    max_reports_per_query: int,
    stock_query_batch_size: int,
    date_chunk_days: int,
    row_count: int,
    rows_with_abstract: int,
    publish_date_min: str | None,
    publish_date_max: str | None,
    report_type_counts: Mapping[str, int],
    query_key_counts: Mapping[str, int],
    ingested_at: str,
) -> dict[str, Any]:
    payload = {
        "corpus_id": f"CORPUS-TSRR-{end_date.replace('-', '')}-001",
        "ingested_at": ingested_at,
        "license_status": "pending_review",
        "max_reports_per_query": max_reports_per_query,
        "stock_query_batch_size": stock_query_batch_size,
        "date_chunk_days": date_chunk_days,
        "not_yet": [
            "not a passed gold set",
            "not production runtime input",
            "not a trading signal",
        ],
        "output_path": str(source_path),
        "phase_minus_1_use": [
            "source pool for claim extraction reliability spike",
            "source metadata and span ID fixture",
            "manual gold-set sampling input",
        ],
        "point_in_time_note": (
            "Rows are stamped with discovered_at at ingestion time; sell-side usage remains "
            "sandbox-only until compliance review."
        ),
        "publish_date_max": publish_date_max,
        "publish_date_min": publish_date_min,
        "query_key_counts": dict(query_key_counts),
        "query_set": {
            "industry_keywords": list(industry_keywords),
            "report_types": list(report_types),
            "stock_codes": list(stock_codes),
        },
        "query_window": {
            "end_date": end_date,
            "start_date": start_date,
        },
        "report_type_counts": dict(report_type_counts),
        "row_count": row_count,
        "rows_with_abstract": rows_with_abstract,
        "source": "tushare.pro.research_report",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(output_path), "rows": 1}


def refresh_tushare_research_report_registry(
    root: str | Path = ".",
    *,
    stock_codes: Sequence[str],
    industry_keywords: Sequence[str],
    report_types: Sequence[str] = (),
    start_date: str,
    end_date: str,
    max_reports_per_query: int = 6000,
    stock_query_batch_size: int = 50,
    date_chunk_days: int = 31,
    preserve_review_templates: bool = True,
    discovered_at: str | None = None,
    pro: Any | None = None,
) -> TushareResearchReportRefreshResult:
    """Fetch Tushare reports and refresh dependent Phase -1 registry artifacts."""
    if not stock_codes and not industry_keywords and not report_types:
        raise ValueError("at least one stock code, industry keyword, or report type is required")
    if max_reports_per_query <= 0:
        raise ValueError("max_reports_per_query must be positive")
    if stock_query_batch_size <= 0:
        raise ValueError("stock_query_batch_size must be positive")
    if date_chunk_days <= 0:
        raise ValueError("date_chunk_days must be positive")

    root_path = Path(root)
    ingested_at = discovered_at or _utc_now()
    reports = fetch_tushare_research_reports(
        stock_codes=stock_codes,
        industry_keywords=industry_keywords,
        report_types=report_types,
        start_date=start_date,
        end_date=end_date,
        max_reports_per_query=max_reports_per_query,
        stock_query_batch_size=stock_query_batch_size,
        date_chunk_days=date_chunk_days,
        discovered_at=ingested_at,
        pro=pro,
    )
    if not reports:
        raise RuntimeError("Tushare research_report returned zero rows; registry was not refreshed")

    outputs: dict[str, str] = {}
    source_path = root_path / "registry/sources/tushare_research_reports.jsonl"
    if discovered_at is None:
        reports = _preserve_existing_discovery_times(
            reports,
            _existing_discovered_at_by_hash(source_path),
        )
    source_result = write_research_reports_jsonl(reports, source_path)
    outputs["source"] = str(source_result["path"])

    source_rows = load_jsonl(source_path)
    audit = audit_research_report_corpus(source_rows)
    report_type_counts = Counter(str(row.get("report_type") or "") for row in source_rows)
    query_key_counts = Counter(str(row.get("query_key") or "") for row in source_rows)

    candidates = select_gold_set_candidates(source_rows, max_documents=50)
    gold_candidates_path = root_path / "registry/sources/tushare_research_reports.gold_candidates.jsonl"
    gold_candidates_result = write_gold_set_candidates(candidates, gold_candidates_path)
    outputs["gold_candidates"] = str(gold_candidates_result["path"])

    gold_review_path = root_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    gold_review_updated = False
    gold_review_has_manual_values = _template_has_manual_values(
        gold_review_path,
        (
            "manual_claim_text",
            "claim_correct",
            "source_span_supports_claim",
            "direction_correct",
            "variable_mapping_correct",
            "unsupported_field_false_grounded",
            "reviewer",
            "review_notes",
        ),
    )
    if not preserve_review_templates or not gold_review_has_manual_values:
        gold_review_result = write_gold_set_review_template(
            candidates,
            gold_review_path,
            claims_per_document=10,
        )
        outputs["gold_review_template"] = str(gold_review_result["path"])
        gold_review_updated = True

    license_review_path = root_path / "registry/compliance/tushare_license_review_template.jsonl"
    license_review_updated = False
    license_review_has_manual_values = _template_has_manual_values(
        license_review_path,
        (
            "approved_for_derived_claim_storage",
            "approved_for_production_runtime",
            "reviewer",
            "review_date",
            "notes",
        ),
    )
    if not preserve_review_templates or not license_review_has_manual_values:
        license_review_result = write_source_license_review_template(source_rows, license_review_path)
        outputs["license_review_template"] = str(license_review_result["path"])
        license_review_updated = True

    manifest_result = _write_research_report_manifest(
        output_path=root_path / "registry/sources/tushare_research_reports.manifest.json",
        source_path=Path("registry/sources/tushare_research_reports.jsonl"),
        start_date=start_date,
        end_date=end_date,
        stock_codes=stock_codes,
        industry_keywords=industry_keywords,
        report_types=report_types,
        max_reports_per_query=max_reports_per_query,
        stock_query_batch_size=stock_query_batch_size,
        date_chunk_days=date_chunk_days,
        row_count=audit.row_count,
        rows_with_abstract=audit.rows_with_abstract,
        publish_date_min=audit.publish_date_min,
        publish_date_max=audit.publish_date_max,
        report_type_counts=report_type_counts,
        query_key_counts=query_key_counts,
        ingested_at=ingested_at,
    )
    outputs["source_manifest"] = str(manifest_result["path"])

    gold_summary_result = write_gold_set_review_summary(root_path)
    license_summary_result = write_source_license_review_summary(root_path)
    license_packet_result = write_license_review_packet(root_path)
    review_batches_result = write_manual_review_batches(root_path)
    claim_vocabulary_result = write_claim_variable_vocabulary(root_path)
    gold_candidate_claims_result = write_gold_candidate_claims(root_path)
    gold_packet_result = write_gold_review_packet(root_path)
    claim_variable_summary_result = write_claim_variable_validation_report(root_path)
    source_validation_result = write_source_registry_validation_report(root_path)
    schema_summary_result = write_schema_validation_report(root_path)
    validation_hardening_result = write_validation_hardening_report(root_path)
    statistical_significance_result = write_statistical_significance_report(root_path)
    monitoring_diagnostics_result = write_production_monitor_diagnostics(root_path)
    prompt_asset_summary_result = write_prompt_asset_validation_report(root_path)
    policy_doc_summary_result = write_policy_doc_validation_report(root_path)
    source_text_redaction_result = write_source_text_redaction_report(root_path)
    audit_trace_view_result = write_audit_trace_view(root_path)
    completion_result = write_completion_audit(root_path)
    promotion_gate_result = write_production_promotion_gate_report(root_path)
    operator_handoff_result = write_operator_handoff(root_path)
    rollback_readiness_result = write_rollback_readiness_report(root_path)
    operator_readiness_result = write_operator_readiness_report(root_path)
    master_plan_coverage_result = write_master_plan_coverage_report(root_path)
    dashboard_result = write_dashboard_reports(root_path)
    registry_manifest_result = write_registry_manifest(root_path)
    outputs["gold_review_summary"] = str(gold_summary_result["path"])
    outputs["gold_review_packet.json"] = gold_packet_result["json"]
    outputs["gold_review_packet.markdown"] = gold_packet_result["markdown"]
    outputs["license_review_summary"] = str(license_summary_result["path"])
    outputs["license_review_packet.json"] = license_packet_result["json"]
    outputs["license_review_packet.markdown"] = license_packet_result["markdown"]
    outputs["manual_review_batch_status"] = review_batches_result["status"]
    outputs["manual_review_gold_set_import_template"] = review_batches_result["gold_set_import_template"]
    outputs["manual_review_gold_set_full_import_template"] = review_batches_result["gold_set_full_import_template"]
    outputs["manual_review_source_license_import_template"] = review_batches_result["source_license_import_template"]
    outputs["claim_variable_vocabulary"] = str(claim_vocabulary_result["path"])
    outputs["gold_candidate_claims"] = gold_candidate_claims_result["candidate_claims"]
    outputs["gold_candidate_claims_summary"] = gold_candidate_claims_result["summary"]
    outputs["claim_variable_validation_report"] = str(claim_variable_summary_result["path"])
    outputs["source_registry_validation_report"] = str(source_validation_result["path"])
    outputs["schema_validation_report"] = str(schema_summary_result["path"])
    outputs["validation_hardening_report"] = str(validation_hardening_result["path"])
    outputs["statistical_significance_report"] = str(statistical_significance_result["path"])
    outputs["production_monitor_diagnostics"] = str(monitoring_diagnostics_result["path"])
    outputs["prompt_asset_validation_report"] = str(prompt_asset_summary_result["path"])
    outputs["policy_doc_validation_report"] = str(policy_doc_summary_result["path"])
    outputs["source_text_redaction_report"] = str(source_text_redaction_result["path"])
    outputs["audit_trace_view.json"] = audit_trace_view_result["json"]
    outputs["audit_trace_view.markdown"] = audit_trace_view_result["markdown"]
    outputs["completion_audit"] = str(completion_result["path"])
    outputs["production_promotion_gate"] = str(promotion_gate_result["path"])
    outputs["operator_handoff.json"] = operator_handoff_result["json"]
    outputs["operator_handoff.markdown"] = operator_handoff_result["markdown"]
    outputs["lockbox_review_import_template"] = operator_handoff_result["lockbox_import_template"]
    outputs["lockbox_review_import_report"] = (
        "registry/lockbox/central_bank_lockbox_review_import_report.json"
    )
    outputs["gold_set_full_import_template"] = operator_handoff_result["gold_set_full_import_template"]
    outputs["gold_review_import_report"] = (
        "registry/gold_sets/tushare_research_reports.review_import_report.json"
    )
    outputs["source_license_policy_template"] = operator_handoff_result["source_license_policy_template"]
    outputs["rollback_readiness_report"] = str(rollback_readiness_result["path"])
    outputs["operator_readiness_report"] = str(operator_readiness_result["path"])
    outputs["source_license_policy_import_report"] = (
        "registry/review_batches/source_license_policy_import_report.json"
    )
    outputs["promotion_dry_run_report"] = (
        "registry/promotion/rke_promotion_dry_run_report.json"
    )
    outputs["master_plan_coverage_report"] = str(master_plan_coverage_result["path"])
    outputs.update({f"dashboard.{key}": value for key, value in dashboard_result.items()})
    outputs["registry_manifest"] = str(registry_manifest_result["path"])

    return TushareResearchReportRefreshResult(
        root=str(root_path),
        source_rows=audit.row_count,
        rows_with_abstract=audit.rows_with_abstract,
        gold_candidate_rows=int(gold_candidates_result["rows"]),
        gold_review_template_updated=gold_review_updated,
        license_review_template_updated=license_review_updated,
        publish_date_min=audit.publish_date_min,
        publish_date_max=audit.publish_date_max,
        report_type_counts=dict(report_type_counts),
        query_key_counts=dict(query_key_counts),
        completion_ready_for_broad_rollout=bool(completion_result["ready_for_broad_rollout"]),
        manifest_valid=bool(registry_manifest_result["valid"]),
        outputs=outputs,
    )
