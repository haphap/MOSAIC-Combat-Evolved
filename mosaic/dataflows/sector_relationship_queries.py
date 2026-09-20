"""Trusted prepare-side adapters for staged Sector/Relationship queries."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from mosaic.dataflows.interface import route_to_vendor
from mosaic.dataflows.staged_query_receipts import (
    validate_staged_query_source_receipt,
)
from mosaic.scorecard.canonical_json import canonical_hash


ReceiptAuthority = Callable[[dict[str, Any]], Sequence[Mapping[str, Any]]]
DigestBuilder = Callable[[str, str, dict[str, Any]], Mapping[str, Any]]
SourceEvidenceAuthority = Callable[
    [str, Mapping[str, Any], str, Mapping[str, Any], Sequence[str]],
    Sequence[Mapping[str, Any]] | None,
]
SourcePreparer = Callable[[str, Mapping[str, Any]], None]

_DIGEST_TOOLS = {
    "get_broker_research",
    "get_industry_policy_digest",
    "get_stock_research",
}
_INDEX_CODE_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ|CSI)$")
DIRECT_VENDOR_TOOL_IDS = frozenset(
    {
        "get_balance_sheet",
        "get_broker_research",
        "get_cashflow",
        "get_etf_holdings",
        "get_fundamentals",
        "get_income_statement",
        "get_indicators",
        "get_industry_moneyflow",
        "get_sector_index_membership",
        "get_stock_data",
        "get_stock_research",
        "get_yield_curve_cn",
    }
)
_ROUTE_BY_TOOL = {
    "get_rke_research_context": "private.rke_report_intelligence",
    "get_industry_policy_digest": "official.govcn_policy",
    "get_broker_research": "private.tushare_research_reports",
    "get_etf_holdings": "tushare.etf_holdings",
    "get_stock_data": "tushare.sector_market",
    "get_indicators": "tushare.sector_market",
    "get_industry_moneyflow": "tushare.institutional_flow",
    "get_yield_curve_cn": "composite.cn_rates",
    "get_fundamentals": "tushare.sector_fundamentals",
    "get_income_statement": "tushare.sector_fundamentals",
    "get_balance_sheet": "tushare.sector_fundamentals",
    "get_cashflow": "tushare.sector_fundamentals",
    "get_stock_research": "private.tushare_research_reports",
    "get_supply_chain_evidence": "official.company_supply_chain_disclosures",
    "get_sector_index_membership": "tushare.sector_market",
}
_PIT_MODE_BY_ROUTE = {
    "official.company_supply_chain_disclosures": "AUTHORITATIVE_VINTAGE_REPLAY",
    "official.govcn_policy": "OBSERVED_LIVE",
    "private.rke_report_intelligence": "DERIVED_FROM_PIT_ARCHIVE",
    "private.tushare_research_reports": "DERIVED_FROM_PIT_ARCHIVE",
    "tushare.etf_holdings": "AUTHORITATIVE_VINTAGE_REPLAY",
    "tushare.institutional_flow": "OBSERVED_LIVE",
    "tushare.sector_fundamentals": "OBSERVED_LIVE",
    "tushare.sector_market": "OBSERVED_LIVE",
    "composite.cn_rates": "OBSERVED_LIVE",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _required_payload(value: Any, field: str = "payload") -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def build_query_descriptor(
    tool_id: str, args: Mapping[str, Any], payload: str
) -> dict[str, str]:
    route_id = _ROUTE_BY_TOOL[tool_id]
    return {
        "tool_id": tool_id,
        "route_id": route_id,
        "as_of": _query_as_of(tool_id, args),
        "request_hash": canonical_hash(args),
        "content_hash": canonical_hash({"text": payload}),
        "pit_mode": _PIT_MODE_BY_ROUTE[route_id],
    }


def _legacy_call(tool_id: str, args: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    if tool_id == "get_sector_index_membership":
        return "get_index_weight", (
            args["index_code"],
            args["start_date"],
            args["end_date"],
        )
    if tool_id == "get_industry_policy_digest":
        route_args: tuple[Any, ...] = (
            args["as_of"],
            args["lookback_days"],
            args["source"],
        )
        if "topic" in args:
            route_args += (args["topic"],)
        return "get_industry_policy", route_args
    if tool_id in {"get_broker_research", "get_stock_research"}:
        return tool_id, (
            args["ticker"],
            args["date_from"],
            args["date_to"],
            args["max_reports"],
        )
    if tool_id == "get_etf_holdings":
        return tool_id, (args["etf"], args["as_of"])
    if tool_id == "get_stock_data":
        return tool_id, (args["ticker"], args["date_from"], args["date_to"])
    if tool_id == "get_indicators":
        return tool_id, (
            args["ticker"],
            args["indicator"],
            args["as_of"],
            args["lookback"],
        )
    if tool_id == "get_industry_moneyflow":
        return tool_id, (
            args["as_of"],
            args["lookback"],
            ",".join(args["industry_filters"]),
        )
    if tool_id == "get_yield_curve_cn":
        return tool_id, (args["as_of"], args["lookback"])
    if tool_id == "get_fundamentals":
        return tool_id, (args["ticker"], args["as_of"])
    if tool_id in {"get_income_statement", "get_balance_sheet", "get_cashflow"}:
        return tool_id, (args["ticker"], args["frequency"], args["as_of"])
    raise ValueError(f"no trusted legacy route adapter for {tool_id}")


def _query_as_of(tool_id: str, args: Mapping[str, Any]) -> str:
    if "as_of" in args:
        return str(args["as_of"])
    if tool_id in {"get_broker_research", "get_stock_research", "get_stock_data"}:
        return str(args["date_to"])
    raise ValueError(f"cannot resolve query as_of for {tool_id}")


def _parse_sector_trade_date(value: Any) -> date:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:]))
        except ValueError as exc:
            raise ValueError("sector index membership trade_date is invalid") from exc
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("sector index membership trade_date is invalid") from exc


def _csv_rows_with_header(raw: str) -> list[dict[str, str]]:
    required_columns = {"index_code", "trade_date", "con_code", "weight"}
    lines = raw.splitlines()
    header_index = None
    for index, line in enumerate(lines):
        fields = next(csv.reader([line]), [])
        if required_columns <= set(fields):
            header_index = index
            break
    if header_index is None:
        return []
    return list(csv.DictReader(io.StringIO("\n".join(lines[header_index:]))))


def _compact_sector_index_membership(raw: str, args: Mapping[str, Any]) -> str:
    index_code = args.get("index_code")
    as_of = args.get("as_of")
    start_date = args.get("start_date")
    end_date = args.get("end_date")
    if (
        not isinstance(index_code, str)
        or _INDEX_CODE_PATTERN.fullmatch(index_code) is None
        or not isinstance(as_of, str)
        or not isinstance(start_date, str)
        or not isinstance(end_date, str)
    ):
        raise ValueError("sector index membership request identity is invalid")
    as_of_date = date.fromisoformat(as_of)
    previous_month_start = (as_of_date.replace(day=1) - timedelta(days=1)).replace(day=1)
    if (start_date, end_date) != (
        previous_month_start.isoformat(),
        as_of_date.isoformat(),
    ):
        raise ValueError(
            "sector index membership request must cover previous month through as_of"
        )
    rows = _csv_rows_with_header(raw)
    if not rows:
        raise ValueError("sector index membership returned no rows")
    members_by_date: dict[date, list[dict[str, Any]]] = {}
    tickers_by_date: dict[date, set[str]] = {}
    for row in rows:
        if row.get("index_code") != index_code:
            raise ValueError("sector index membership index identity mismatch")
        trade_date = _parse_sector_trade_date(row.get("trade_date"))
        if trade_date > as_of_date:
            continue
        try:
            weight = float(row.get("weight"))
        except (TypeError, ValueError) as exc:
            raise ValueError("sector index membership weight is invalid") from exc
        con_code = row.get("con_code")
        if not isinstance(con_code, str) or not re.fullmatch(
            r"[0-9]{6}\.(SH|SZ|BJ)", con_code
        ):
            raise ValueError("sector index membership ticker is invalid")
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("sector index membership weight is invalid")
        seen_tickers = tickers_by_date.setdefault(trade_date, set())
        if con_code in seen_tickers:
            raise ValueError("sector index membership contains duplicate tickers")
        seen_tickers.add(con_code)
        members_by_date.setdefault(trade_date, []).append(
            {"ticker": con_code, "weight": weight}
        )
    if not members_by_date:
        raise ValueError("sector index membership has no PIT snapshot")
    selected_trade_date = max(members_by_date)
    selected = members_by_date[selected_trade_date]
    return _canonical_json(
        {
            "index_code": index_code,
            "selected_trade_date": selected_trade_date.isoformat(),
            "members": sorted(selected, key=lambda row: row["ticker"]),
        }
    )


def _compact_etf_holdings(raw: str, *, top_n: int) -> str:
    lines = raw.splitlines()
    summary: dict[str, str] = {}
    for line in lines:
        if ":" in line and not line.startswith("#"):
            key, value = line.split(":", 1)
            if key.strip() and value.strip():
                summary[key.strip()] = value.strip()
    header_index = next(
        (index for index, line in enumerate(lines) if line.startswith("ts_code,")),
        None,
    )
    if header_index is None:
        return _canonical_json(
            {
                "kind": "etf_holdings_candidates",
                "status": "SOURCE_FORMAT_UNAVAILABLE",
                "note_hash": canonical_hash({"text": raw}),
                "candidates": [],
            }
        )
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
    candidates = []
    for rank, row in enumerate(reader, start=1):
        if rank > top_n:
            break
        candidates.append(
            {
                "rank": rank,
                "ticker": row.get("symbol") or row.get("stk_code") or "",
                "name": row.get("stk_name") or "",
                "weight_pct": _optional_number(row.get("stk_mkv_ratio")),
                "float_ratio_pct": _optional_number(row.get("stk_float_ratio")),
            }
        )
    return _canonical_json(
        {
            "kind": "etf_holdings_candidates",
            "status": "READY" if candidates else "TRUE_EMPTY",
            "etf": summary.get("Ticker"),
            "disclosure_date": summary.get("Disclosure Date"),
            "report_date": summary.get("Report Date"),
            "candidates": candidates,
            "usage": "candidate_pool_only_verify_at_most_3_tickers",
        }
    )


def _optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


class SectorRelationshipQueryMaterializer:
    """Map canonical PR6 arguments to prepare-only collectors and attest results."""

    def __init__(
        self,
        *,
        receipt_authority: ReceiptAuthority,
        route_caller: Callable[..., Any] = route_to_vendor,
        digest_builder: DigestBuilder | None = None,
        rke_materializer: Callable[[dict[str, Any]], Mapping[str, Any]] | None = None,
        supply_chain_archive: Any | None = None,
        source_evidence_authority: SourceEvidenceAuthority | None = None,
        source_preparer: SourcePreparer | None = None,
    ) -> None:
        self.route_caller = route_caller
        self.receipt_authority = receipt_authority
        self.digest_builder = digest_builder
        self.rke_materializer = rke_materializer
        self.supply_chain_archive = supply_chain_archive
        self.source_evidence_authority = source_evidence_authority
        self.source_preparer = source_preparer

    def __call__(self, tool_id: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_id not in _ROUTE_BY_TOOL:
            raise ValueError(f"unknown staged Sector/Relationship tool: {tool_id}")
        if not isinstance(args, dict):
            raise ValueError("materializer args must be an object")
        if tool_id == "get_supply_chain_evidence":
            if self.supply_chain_archive is None:
                raise ValueError("authoritative supply-chain archive is unavailable")
            result = self.supply_chain_archive.materialize(
                ticker=args["ticker"], as_of=args["as_of"]
            )
            if set(result) != {"payload", "source_receipt_hashes"}:
                raise ValueError("supply-chain archive returned an invalid materialization")
            receipt_hashes = result["source_receipt_hashes"]
            if (
                not isinstance(receipt_hashes, Sequence)
                or isinstance(receipt_hashes, (str, bytes))
                or not receipt_hashes
            ):
                raise ValueError(
                    "supply-chain materialization requires source receipt hashes"
                )
            return dict(result)

        if tool_id in _DIGEST_TOOLS and self.digest_builder is None:
            raise ValueError(f"{tool_id} requires a trusted frozen digest builder")
        if tool_id == "get_rke_research_context":
            if self.rke_materializer is None:
                raise ValueError("authoritative RKE materializer is unavailable")
            result = self.rke_materializer(dict(args))
            if not isinstance(result, Mapping) or set(result) != {"payload", "source_receipt_hashes"}:
                raise ValueError("RKE authority returned an invalid materialization")
            _required_payload(result["payload"], "RKE payload")
            hashes = result["source_receipt_hashes"]
            if not isinstance(hashes, Sequence) or isinstance(hashes, (str, bytes)) or not hashes:
                raise ValueError("RKE materialization requires source receipt hashes")
            return dict(result)

        if tool_id == "get_industry_policy_digest" and self.source_preparer is not None:
            self.source_preparer(tool_id, dict(args))
        method, route_args = _legacy_call(tool_id, args)
        raw_payload = _required_payload(self.route_caller(method, *route_args))

        if tool_id == "get_sector_index_membership":
            raw_payload = _compact_sector_index_membership(raw_payload, args)

        descriptor = build_query_descriptor(tool_id, args, raw_payload)
        source_receipts = None
        if self.source_evidence_authority is not None:
            source_receipts = self.source_evidence_authority(
                tool_id,
                dict(args),
                raw_payload,
                dict(descriptor),
                (),
            )
        if source_receipts is None:
            source_receipts = self.receipt_authority(dict(descriptor))
        if not isinstance(source_receipts, Sequence) or isinstance(
            source_receipts, (str, bytes)
        ):
            raise ValueError("receipt authority must return a receipt array")
        if not source_receipts and tool_id not in DIRECT_VENDOR_TOOL_IDS:
            raise ValueError("materialized query requires at least one eligible source receipt")
        receipt_hashes = sorted(
            {
                validate_staged_query_source_receipt(
                    receipt,
                    expected_descriptor=descriptor,
                    require_eligible=True,
                )
                for receipt in source_receipts
            }
        )

        payload = raw_payload
        derivation: dict[str, Any] | None = None
        if tool_id in _DIGEST_TOOLS:
            digest = self.digest_builder(tool_id, raw_payload, dict(args))
            if not isinstance(digest, Mapping) or set(digest) != {
                "digest",
                "model_hash",
                "prompt_hash",
            }:
                raise ValueError(
                    "trusted digest builder must return digest, model_hash and prompt_hash"
                )
            digest_text = _required_payload(digest["digest"], "digest")
            model_hash = str(digest["model_hash"])
            prompt_hash = str(digest["prompt_hash"])
            for name, value in (("model_hash", model_hash), ("prompt_hash", prompt_hash)):
                if not value.startswith("sha256:") or len(value) != 71:
                    raise ValueError(f"trusted digest {name} must be a sha256 identifier")
            payload = digest_text
            derivation = {
                "derivation_contract_version": "frozen_research_digest_lineage_v1",
                "model_hash": model_hash,
                "prompt_hash": prompt_hash,
                "source_payload_hash": descriptor["content_hash"],
            }
        elif tool_id == "get_etf_holdings":
            payload = _compact_etf_holdings(raw_payload, top_n=args["top_n"])
        result = {"payload": payload, "source_receipt_hashes": receipt_hashes}
        if derivation is not None:
            result["derivation"] = derivation
        return result


__all__ = ["DIRECT_VENDOR_TOOL_IDS", "SectorRelationshipQueryMaterializer"]
