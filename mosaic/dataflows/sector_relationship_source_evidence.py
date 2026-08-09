"""Authoritative non-live receipts for Sector/Relationship query materialization."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mosaic.dataflows.agent_materialization import (
    AgentDataMaterializationLedger,
    SourceCaptureReceipt,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.china_agent_data_archive import (
    CURVE_ROUTE_GROUP,
    INSTITUTIONAL_ROUTE_GROUP,
    china_archive_source_receipt,
)
from mosaic.dataflows.sector_archive import sector_archive_source_receipt
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.dataflows.staged_query_receipts import seal_staged_query_source_receipt
from mosaic.scorecard.canonical_json import canonical_hash


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_RKE_SOURCE_PATHS = (
    "registry/sources/tushare_research_reports.jsonl",
    "registry/sources/local_macro_strategy_reports.jsonl",
)
_SECTOR_ARCHIVE_ENDPOINT_BY_TOOL = {
    "get_balance_sheet": "balancesheet",
    "get_cashflow": "cashflow",
    "get_etf_holdings": "fund_portfolio",
    "get_income_statement": "income",
    "get_indicators": "daily",
    "get_stock_data": "daily",
}
_CHINA_ARCHIVE_ROUTE_BY_TOOL = {
    "get_industry_moneyflow": INSTITUTIONAL_ROUTE_GROUP,
    "get_yield_curve_cn": CURVE_ROUTE_GROUP,
}
_FORWARD_ARCHIVE_TOOLS = {
    "get_broker_research",
    "get_industry_policy_digest",
    "get_stock_research",
}


def _aware_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("source evidence clock must return an aware datetime")
    return value


def _timestamp(value: Any, *, field: str, date_at_end: bool = False) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise DataVendorUnavailable(f"{field} is unavailable")
    try:
        if len(raw) == 8 and raw.isdigit():
            parsed_date = datetime.strptime(raw, "%Y%m%d").date()
            return datetime.combine(
                parsed_date,
                time.max if date_at_end else time.min,
                tzinfo=_SHANGHAI,
            )
        if len(raw) == 10:
            parsed_date = date.fromisoformat(raw)
            return datetime.combine(
                parsed_date,
                time.max if date_at_end else time.min,
                tzinfo=_SHANGHAI,
            )
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DataVendorUnavailable(f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DataVendorUnavailable(f"{field} must include a timezone")
    return parsed


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("row must be an object")
            rows.append(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(f"RKE source archive is malformed: {path.name}") from exc
    return rows


def _summary_field(raw_payload: str, field: str) -> str:
    for line in raw_payload.splitlines():
        if ":" not in line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        if key.strip() == field:
            return value.strip()
    return ""


class SectorRelationshipSourceEvidenceAuthority:
    """Seal ETF vintage and RKE archive evidence without exposing private lineage."""

    def __init__(
        self,
        *,
        root: str | Path,
        receipt_store: StagedQueryReceiptStore,
        sector_archive_store: Any | None = None,
        china_archive_store: Any | None = None,
        forward_archive_reader: Any | None = None,
        agent_data_ledger: AgentDataMaterializationLedger | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.receipt_store = receipt_store
        self.sector_archive_store = sector_archive_store
        self.china_archive_store = china_archive_store
        self.forward_archive_reader = forward_archive_reader
        self.agent_data_ledger = agent_data_ledger
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _register_source(self, receipt: SourceCaptureReceipt) -> str:
        if self.agent_data_ledger is not None:
            return self.agent_data_ledger.append_source_capture(receipt)
        return receipt.receipt_hash

    def __call__(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        raw_payload: str,
        descriptor: Mapping[str, Any],
        source_ids: Sequence[str],
    ) -> list[dict[str, Any]] | None:
        if (
            self.sector_archive_store is not None
            and tool_id in _SECTOR_ARCHIVE_ENDPOINT_BY_TOOL
        ):
            receipt = self._sector_archive_receipt(
                tool_id, raw_payload, descriptor
            )
        elif (
            self.china_archive_store is not None
            and tool_id in _CHINA_ARCHIVE_ROUTE_BY_TOOL
        ):
            receipt = self._china_archive_receipt(tool_id, descriptor)
        elif (
            self.forward_archive_reader is not None
            and tool_id in _FORWARD_ARCHIVE_TOOLS
        ):
            receipt = self._forward_archive_receipt(
                tool_id, args, raw_payload, descriptor
            )
        elif tool_id == "get_etf_holdings":
            receipt = self._etf_receipt(raw_payload, descriptor)
        elif tool_id == "get_rke_research_context":
            receipt = self._rke_receipt(source_ids, descriptor)
        else:
            return None
        self.receipt_store.register(receipt)
        return self.receipt_store.resolve(descriptor)

    def _forward_archive_receipt(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        raw_payload: str,
        descriptor: Mapping[str, Any],
    ) -> dict[str, Any]:
        if descriptor.get("pit_mode") != "DERIVED_FROM_PIT_ARCHIVE":
            raise DataVendorUnavailable("forward archive query PIT mode is invalid")
        upstream_receipt = self.forward_archive_reader.source_receipt(
            tool_id,
            args,
            raw_payload,
            descriptor,
        )
        upstream_hash = self._register_source(upstream_receipt)
        upstream = upstream_receipt.as_dict()
        return seal_staged_query_source_receipt(
            descriptor,
            knowledge_available_at=str(upstream["time"]["knowledge_available_at"]),
            captured_at=str(upstream["time"]["captured_at"]),
            upstream_evidence_hashes=(upstream_hash,),
        )

    def _china_archive_receipt(
        self,
        tool_id: str,
        descriptor: Mapping[str, Any],
    ) -> dict[str, Any]:
        route_id = _CHINA_ARCHIVE_ROUTE_BY_TOOL[tool_id]
        as_of = str(descriptor.get("as_of") or "")
        if descriptor.get("route_id") != route_id:
            raise DataVendorUnavailable("China archive query route mapping is invalid")
        try:
            group = self.china_archive_store.load_route_group(as_of, route_id)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise DataVendorUnavailable(
                f"no exact China archive source receipt is available for {as_of}"
            ) from exc
        upstream_receipt = china_archive_source_receipt(group, route_id)
        upstream_hash = self._register_source(upstream_receipt)
        upstream = upstream_receipt.as_dict()
        knowledge_at = str(upstream["time"]["knowledge_available_at"])
        captured_at = str(upstream["time"]["captured_at"])
        return seal_staged_query_source_receipt(
            descriptor,
            knowledge_available_at=knowledge_at,
            captured_at=captured_at,
            upstream_evidence_hashes=(upstream_hash,),
        )

    def _sector_archive_receipt(
        self,
        tool_id: str,
        raw_payload: str,
        descriptor: Mapping[str, Any],
    ) -> dict[str, Any]:
        as_of = str(descriptor.get("as_of") or "")
        try:
            group = self.sector_archive_store.load_group(as_of)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise DataVendorUnavailable(
                f"no exact Sector archive source receipt is available for {as_of}"
            ) from exc
        endpoint = _SECTOR_ARCHIVE_ENDPOINT_BY_TOOL[tool_id]
        batches = [
            batch
            for batch in group.get("batches", ())
            if isinstance(batch, Mapping) and batch.get("endpoint") == endpoint
        ]
        if len(batches) != 1:
            raise DataVendorUnavailable(
                f"Sector archive source receipt lacks {endpoint} coverage"
            )
        upstream_route = (
            "tushare.sector_fundamentals"
            if tool_id == "get_etf_holdings"
            else str(descriptor.get("route_id") or "")
        )
        upstream_receipt = sector_archive_source_receipt(group, upstream_route)
        upstream_hash = self._register_source(upstream_receipt)
        upstream = upstream_receipt.as_dict()
        captured_at = str(upstream["time"]["captured_at"])
        if tool_id == "get_etf_holdings":
            return self._etf_receipt(
                raw_payload,
                descriptor,
                captured_at=_timestamp(captured_at, field="Sector archive captured_at"),
                parent_capture_hash=upstream_hash,
            )
        if descriptor.get("pit_mode") != "OBSERVED_LIVE":
            raise DataVendorUnavailable("Sector archive query PIT mode is invalid")
        knowledge_at = str(upstream["time"]["knowledge_available_at"])
        return seal_staged_query_source_receipt(
            descriptor,
            knowledge_available_at=knowledge_at,
            captured_at=captured_at,
            upstream_evidence_hashes=(upstream_hash,),
        )

    def _etf_receipt(
        self,
        raw_payload: str,
        descriptor: Mapping[str, Any],
        *,
        captured_at: datetime | None = None,
        parent_capture_hash: str | None = None,
    ) -> dict[str, Any]:
        if descriptor.get("pit_mode") != "AUTHORITATIVE_VINTAGE_REPLAY":
            raise DataVendorUnavailable("ETF disclosure receipt PIT mode is invalid")
        disclosure_raw = _summary_field(raw_payload, "Disclosure Date")
        try:
            disclosure = _timestamp(
                disclosure_raw,
                field="ETF disclosure date",
                date_at_end=True,
            )
        except DataVendorUnavailable as exc:
            raise DataVendorUnavailable("ETF disclosure date is unavailable or invalid") from exc
        as_of_end = datetime.combine(
            date.fromisoformat(str(descriptor["as_of"])), time.max, tzinfo=_SHANGHAI
        )
        if disclosure > as_of_end:
            raise DataVendorUnavailable("ETF disclosure date is after query as_of")
        captured = captured_at or _aware_now(self.clock)
        if captured < disclosure:
            raise DataVendorUnavailable("ETF disclosure was captured before its release date")
        as_of = str(descriptor["as_of"])
        data_lines = [
            line
            for line in raw_payload.splitlines()
            if line.strip() and "," in line and not line.startswith("ts_code,")
        ]
        row_count = len(data_lines)
        source = SourceCaptureReceipt.seal(
            {
                "schema_version": "source_capture_receipt_v1",
                "identity": {
                    "source_family": "tushare",
                    "route_id": "tushare.etf_holdings",
                    "request_hash": descriptor["request_hash"],
                    "capture_id": "etf-holdings:"
                    + canonical_hash(
                        {
                            "request_hash": descriptor["request_hash"],
                            "content_hash": descriptor["content_hash"],
                            "disclosure": disclosure.isoformat(),
                        }
                    ).removeprefix("sha256:"),
                },
                "transport": {
                    "redacted_url": "private://tushare/etf-holdings",
                    "method": "FILE",
                    "query_keys": ["as_of", "etf", "top_n"],
                    "pagination_policy": "FROZEN_ETF_DISCLOSURE_SELECTION_V1",
                    "page_count": 1,
                },
                "authority": {
                    "provider": "tushare",
                    "permission_tier": "trusted_private_archive",
                    "api_version": "pro-v1",
                    "parser_version": "etf_holdings_query_v1",
                },
                "time": {
                    "released_at": disclosure.isoformat(),
                    "vintage_at": disclosure.isoformat(),
                    "captured_at": captured.isoformat(),
                    "knowledge_available_at": disclosure.isoformat(),
                },
                "pit": {
                    "pit_mode": "AUTHORITATIVE_VINTAGE_REPLAY",
                    "as_of_cutoff": as_of_end.isoformat(),
                    "eligible": True,
                    "blocker_codes": [],
                    "vintage_query": {
                        "as_of": as_of,
                        "disclosure_date": disclosure.date().isoformat(),
                    },
                },
                "content": {
                    "raw_content_hash": descriptor["content_hash"],
                    "normalized_row_count": row_count,
                    "schema_hash": canonical_hash(
                        {
                            "parser_version": "etf_holdings_query_v1",
                            "route_id": descriptor["route_id"],
                        }
                    ),
                },
                "coverage": {
                    "requested_start": disclosure.date().isoformat(),
                    "requested_end": as_of,
                    "observed_start": (
                        disclosure.date().isoformat() if row_count else None
                    ),
                    "observed_end": (
                        disclosure.date().isoformat() if row_count else None
                    ),
                    "dimensions": {"route_id": ["tushare.etf_holdings"]},
                },
                "completeness": {
                    "truncated": False,
                    "next_page_token_present": False,
                    "duplicate_count": 0,
                    "empty_result_semantics": (
                        "NON_EMPTY" if row_count else "TRUE_EMPTY"
                    ),
                },
                "provenance": {
                    "parent_capture_hash": parent_capture_hash
                    or canonical_hash(
                        {
                            "route_id": descriptor["route_id"],
                            "content_hash": descriptor["content_hash"],
                            "disclosure": disclosure.isoformat(),
                        }
                    ),
                    "previous_revision_hash": None,
                    "revision_reason": None,
                },
            }
        )
        upstream_hash = self._register_source(source)
        return seal_staged_query_source_receipt(
            descriptor,
            knowledge_available_at=disclosure.isoformat(),
            captured_at=captured.isoformat(),
            upstream_evidence_hashes=(upstream_hash,),
        )

    def _rke_receipt(
        self,
        source_ids: Sequence[str],
        descriptor: Mapping[str, Any],
    ) -> dict[str, Any]:
        if descriptor.get("pit_mode") != "DERIVED_FROM_PIT_ARCHIVE":
            raise DataVendorUnavailable("RKE source receipt PIT mode is invalid")
        selected = tuple(sorted(set(str(value).strip() for value in source_ids if str(value).strip())))
        if not selected:
            raise DataVendorUnavailable("RKE source lineage is empty and has no coverage receipt")

        source_by_id: dict[str, Mapping[str, Any]] = {}
        for relative in _RKE_SOURCE_PATHS:
            for row in _read_jsonl(self.root / relative):
                source_id = str(row.get("source_id") or "").strip()
                if source_id and source_id in source_by_id and source_by_id[source_id] != row:
                    raise DataVendorUnavailable("RKE source archive has conflicting source ids")
                if source_id:
                    source_by_id[source_id] = row
        metadata_by_source = {
            str(row.get("source_id") or "").strip(): row
            for row in _read_jsonl(
                self.root / "registry/report_intelligence/report_metadata.jsonl"
            )
            if str(row.get("source_id") or "").strip()
        }

        missing = [source_id for source_id in selected if source_id not in source_by_id]
        if missing:
            raise DataVendorUnavailable("RKE source lineage is not closed by the private archive")

        as_of_end = datetime.combine(
            date.fromisoformat(str(descriptor["as_of"])), time.max, tzinfo=_SHANGHAI
        )
        knowledge_values: list[datetime] = []
        capture_values: list[datetime] = []
        upstream_evidence: list[str] = []
        for source_id in selected:
            source = source_by_id[source_id]
            metadata = metadata_by_source.get(source_id, {})
            knowledge = _timestamp(
                metadata.get("accessible_datetime")
                or metadata.get("publish_datetime")
                or source.get("publish_datetime")
                or source.get("publish_date"),
                field="RKE source knowledge time",
                date_at_end=True,
            )
            captured = _timestamp(
                source.get("discovered_at"),
                field="RKE source discovered_at",
            )
            if knowledge > as_of_end:
                raise DataVendorUnavailable("RKE source knowledge is after query as_of")
            if captured < knowledge:
                raise DataVendorUnavailable("RKE source capture precedes knowledge availability")
            knowledge_values.append(knowledge)
            capture_values.append(captured)
            upstream_evidence.append(
                canonical_hash({"source": dict(source), "metadata": dict(metadata)})
            )

        knowledge_at = max(knowledge_values)
        captured_at = max(capture_values)
        archive_hash = canonical_hash(sorted(set(upstream_evidence)))
        source = SourceCaptureReceipt.seal(
            {
                "schema_version": "source_capture_receipt_v1",
                "identity": {
                    "source_family": "local_private_rke",
                    "route_id": "private.rke_report_intelligence",
                    "request_hash": descriptor["request_hash"],
                    "capture_id": "private-rke:"
                    + canonical_hash(
                        {
                            "request_hash": descriptor["request_hash"],
                            "content_hash": descriptor["content_hash"],
                            "archive_hash": archive_hash,
                        }
                    ).removeprefix("sha256:"),
                },
                "transport": {
                    "redacted_url": "private://rke/report-intelligence",
                    "method": "FILE",
                    "query_keys": ["as_of", "source_ids"],
                    "pagination_policy": "EXACT_PRIVATE_SOURCE_SET_V1",
                    "page_count": 1,
                },
                "authority": {
                    "provider": "local_private_rke",
                    "permission_tier": "trusted_private_archive",
                    "api_version": "rke-v1",
                    "parser_version": "rke_source_evidence_v1",
                },
                "time": {
                    "released_at": knowledge_at.isoformat(),
                    "vintage_at": knowledge_at.isoformat(),
                    "captured_at": captured_at.isoformat(),
                    "knowledge_available_at": knowledge_at.isoformat(),
                },
                "pit": {
                    "pit_mode": "AUTHORITATIVE_VINTAGE_REPLAY",
                    "as_of_cutoff": as_of_end.isoformat(),
                    "eligible": True,
                    "blocker_codes": [],
                    "vintage_query": {
                        "archive_hash": archive_hash,
                        "as_of": str(descriptor["as_of"]),
                    },
                },
                "content": {
                    "raw_content_hash": descriptor["content_hash"],
                    "normalized_row_count": len(selected),
                    "schema_hash": canonical_hash(
                        {
                            "parser_version": "rke_source_evidence_v1",
                            "route_id": descriptor["route_id"],
                        }
                    ),
                },
                "coverage": {
                    "requested_start": min(value.date() for value in knowledge_values).isoformat(),
                    "requested_end": str(descriptor["as_of"]),
                    "observed_start": min(value.date() for value in knowledge_values).isoformat(),
                    "observed_end": max(value.date() for value in knowledge_values).isoformat(),
                    "dimensions": {"route_id": ["private.rke_report_intelligence"]},
                },
                "completeness": {
                    "truncated": False,
                    "next_page_token_present": False,
                    "duplicate_count": 0,
                    "empty_result_semantics": "NON_EMPTY",
                },
                "provenance": {
                    "parent_capture_hash": archive_hash,
                    "previous_revision_hash": None,
                    "revision_reason": None,
                },
            }
        )
        upstream_hash = self._register_source(source)
        return seal_staged_query_source_receipt(
            descriptor,
            knowledge_available_at=knowledge_at.isoformat(),
            captured_at=captured_at.isoformat(),
            upstream_evidence_hashes=(upstream_hash,),
        )


__all__ = ["SectorRelationshipSourceEvidenceAuthority"]
