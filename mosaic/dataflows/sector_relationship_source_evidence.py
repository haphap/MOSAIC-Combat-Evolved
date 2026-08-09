"""Authoritative non-live receipts for Sector/Relationship query materialization."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.receipt_store = receipt_store
        self.sector_archive_store = sector_archive_store
        self.china_archive_store = china_archive_store
        self.forward_archive_reader = forward_archive_reader
        self.clock = clock or (lambda: datetime.now(timezone.utc))

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
        upstream = self.forward_archive_reader.source_receipt(
            tool_id,
            args,
            raw_payload,
            descriptor,
        ).as_dict()
        return seal_staged_query_source_receipt(
            descriptor,
            knowledge_available_at=str(upstream["time"]["knowledge_available_at"]),
            captured_at=str(upstream["time"]["captured_at"]),
            upstream_evidence_hashes=(str(upstream["receipt_hash"]),),
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
        upstream = china_archive_source_receipt(group, route_id).as_dict()
        knowledge_at = str(upstream["time"]["knowledge_available_at"])
        captured_at = str(upstream["time"]["captured_at"])
        return seal_staged_query_source_receipt(
            descriptor,
            knowledge_available_at=knowledge_at,
            captured_at=captured_at,
            upstream_evidence_hashes=(str(upstream["receipt_hash"]),),
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
        upstream = sector_archive_source_receipt(group, upstream_route).as_dict()
        upstream_hash = str(upstream["receipt_hash"])
        captured_at = str(upstream["time"]["captured_at"])
        if tool_id == "get_etf_holdings":
            disclosure = _timestamp(
                _summary_field(raw_payload, "Disclosure Date"),
                field="ETF disclosure date",
                date_at_end=True,
            )
            as_of_end = datetime.combine(
                date.fromisoformat(as_of), time.max, tzinfo=_SHANGHAI
            )
            if disclosure > as_of_end:
                raise DataVendorUnavailable("ETF disclosure date is after query as_of")
            return seal_staged_query_source_receipt(
                descriptor,
                knowledge_available_at=disclosure.isoformat(),
                captured_at=captured_at,
                upstream_evidence_hashes=(upstream_hash,),
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
        captured = _aware_now(self.clock)
        if captured < disclosure:
            raise DataVendorUnavailable("ETF disclosure was captured before its release date")
        return seal_staged_query_source_receipt(
            descriptor,
            knowledge_available_at=disclosure.isoformat(),
            captured_at=captured.isoformat(),
            upstream_evidence_hashes=(
                canonical_hash(
                    {
                        "disclosure_date": disclosure.isoformat(),
                        "raw_payload_hash": descriptor["content_hash"],
                        "route_id": descriptor["route_id"],
                    }
                ),
            ),
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

        return seal_staged_query_source_receipt(
            descriptor,
            knowledge_available_at=max(knowledge_values).isoformat(),
            captured_at=max(capture_values).isoformat(),
            upstream_evidence_hashes=tuple(sorted(set(upstream_evidence))),
        )


__all__ = ["SectorRelationshipSourceEvidenceAuthority"]
