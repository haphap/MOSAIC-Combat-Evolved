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
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from mosaic.dataflows.tushare import _RESEARCH_REPORT_FIELDS, _get_pro_client

from .completion_auditor import write_completion_audit
from .compliance import write_source_license_review_template
from .claim_vocabulary import write_claim_variable_validation_report, write_claim_variable_vocabulary
from .dashboard_reports import write_dashboard_reports
from .gold_review_packet import write_gold_review_packet
from .phase_minus1 import (
    audit_research_report_corpus,
    load_jsonl,
    select_gold_set_candidates,
    write_gold_set_candidates,
    write_gold_set_review_template,
)
from .prompt_asset_validation import write_prompt_asset_validation_report
from .registry_manifest import write_registry_manifest
from .review_gates import write_gold_set_review_summary, write_source_license_review_summary
from .schema_validation import write_schema_validation_report
from .source_registry_validation import write_source_registry_validation_report
from .validation_hardening import (
    write_statistical_significance_report,
    write_validation_hardening_report,
)

ReportKind = Literal["stock", "industry"]


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


def fetch_tushare_research_reports(
    *,
    stock_codes: Sequence[str] = (),
    industry_keywords: Sequence[str] = (),
    start_date: str,
    end_date: str,
    max_reports_per_query: int = 100,
    discovered_at: str | None = None,
    pro: Any | None = None,
) -> list[RkeResearchReport]:
    """Fetch stock and/or industry research reports from Tushare.

    ``stock_codes`` should be Tushare codes such as ``600519.SH``. Industry
    keywords are passed to Tushare's ``ind_name`` field.
    """
    client = pro or _get_pro_client()
    stamp = discovered_at or _utc_now()
    start_api = _api_date(start_date)
    end_api = _api_date(end_date)
    reports: list[RkeResearchReport] = []

    for ts_code in stock_codes:
        df = client.research_report(
            ts_code=ts_code,
            start_date=start_api,
            end_date=end_api,
            report_type="个股研报",
            fields=_RESEARCH_REPORT_FIELDS,
        )
        records = _df_to_records(df)
        for row in records[:max_reports_per_query]:
            reports.append(
                normalize_research_report_row(
                    row,
                    report_type="个股研报",
                    query_key=ts_code,
                    discovered_at=stamp,
                )
            )

    for industry in industry_keywords:
        df = client.research_report(
            ind_name=industry,
            start_date=start_api,
            end_date=end_api,
            report_type="行业研报",
            fields=_RESEARCH_REPORT_FIELDS,
        )
        records = _df_to_records(df)
        for row in records[:max_reports_per_query]:
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
    max_reports_per_query: int,
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
    start_date: str,
    end_date: str,
    max_reports_per_query: int = 6000,
    preserve_review_templates: bool = True,
    discovered_at: str | None = None,
    pro: Any | None = None,
) -> TushareResearchReportRefreshResult:
    """Fetch Tushare reports and refresh dependent Phase -1 registry artifacts."""
    if not stock_codes and not industry_keywords:
        raise ValueError("at least one stock code or industry keyword is required")
    if max_reports_per_query <= 0:
        raise ValueError("max_reports_per_query must be positive")

    root_path = Path(root)
    ingested_at = discovered_at or _utc_now()
    reports = fetch_tushare_research_reports(
        stock_codes=stock_codes,
        industry_keywords=industry_keywords,
        start_date=start_date,
        end_date=end_date,
        max_reports_per_query=max_reports_per_query,
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
        max_reports_per_query=max_reports_per_query,
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
    claim_vocabulary_result = write_claim_variable_vocabulary(root_path)
    gold_packet_result = write_gold_review_packet(root_path)
    claim_variable_summary_result = write_claim_variable_validation_report(root_path)
    source_validation_result = write_source_registry_validation_report(root_path)
    schema_summary_result = write_schema_validation_report(root_path)
    validation_hardening_result = write_validation_hardening_report(root_path)
    statistical_significance_result = write_statistical_significance_report(root_path)
    prompt_asset_summary_result = write_prompt_asset_validation_report(root_path)
    completion_result = write_completion_audit(root_path)
    dashboard_result = write_dashboard_reports(root_path)
    registry_manifest_result = write_registry_manifest(root_path)
    outputs["gold_review_summary"] = str(gold_summary_result["path"])
    outputs["gold_review_packet.json"] = gold_packet_result["json"]
    outputs["gold_review_packet.markdown"] = gold_packet_result["markdown"]
    outputs["license_review_summary"] = str(license_summary_result["path"])
    outputs["claim_variable_vocabulary"] = str(claim_vocabulary_result["path"])
    outputs["claim_variable_validation_report"] = str(claim_variable_summary_result["path"])
    outputs["source_registry_validation_report"] = str(source_validation_result["path"])
    outputs["schema_validation_report"] = str(schema_summary_result["path"])
    outputs["validation_hardening_report"] = str(validation_hardening_result["path"])
    outputs["statistical_significance_report"] = str(statistical_significance_result["path"])
    outputs["prompt_asset_validation_report"] = str(prompt_asset_summary_result["path"])
    outputs["completion_audit"] = str(completion_result["path"])
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
