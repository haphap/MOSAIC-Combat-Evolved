"""Tushare research-report ingestion for RKE Phase -1.

The agent-facing report tools return Markdown. RKE needs structured,
point-in-time source rows that can feed source-grounded claim extraction. This
module calls Tushare ``pro.research_report`` and persists sanitized JSONL rows
with source IDs, span IDs, hashes, publication dates, and discovery timestamps.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from mosaic.dataflows.tushare import _RESEARCH_REPORT_FIELDS, _get_pro_client

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
