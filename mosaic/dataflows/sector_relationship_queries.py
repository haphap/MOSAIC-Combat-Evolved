"""Trusted prepare-side adapters for staged Sector/Relationship queries."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from mosaic.agents.utils.rke_research_tools import format_rke_runtime_context
from mosaic.dataflows.interface import route_to_vendor
from mosaic.dataflows.staged_query_receipts import (
    validate_staged_query_source_receipt,
)
from mosaic.rke.agent_research_context import build_rke_agent_research_materialization
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
}
_PIT_MODE_BY_ROUTE = {
    "official.company_supply_chain_disclosures": "AUTHORITATIVE_VINTAGE_REPLAY",
    "official.govcn_policy": "DERIVED_FROM_PIT_ARCHIVE",
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


def _default_rke_renderer(args: dict[str, Any]) -> Mapping[str, Any]:
    materialization = build_rke_agent_research_materialization(
        agent_id=args["agent_id"],
        as_of_date=args["as_of"],
        layer=args["layer"],
        ticker=args.get("ticker", ""),
        sector=args.get("sector", ""),
        max_items=args["max_items"],
    )
    return {
        "payload": format_rke_runtime_context(materialization["context"]),
        "source_ids": materialization["source_ids"],
    }


def _legacy_call(tool_id: str, args: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
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
        rke_renderer: Callable[[dict[str, Any]], Any] = _default_rke_renderer,
        supply_chain_archive: Any | None = None,
        source_evidence_authority: SourceEvidenceAuthority | None = None,
        source_preparer: SourcePreparer | None = None,
    ) -> None:
        self.route_caller = route_caller
        self.receipt_authority = receipt_authority
        self.digest_builder = digest_builder
        self.rke_renderer = rke_renderer
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
        source_ids: tuple[str, ...] = ()
        if tool_id == "get_rke_research_context":
            rendered = self.rke_renderer(dict(args))
            if isinstance(rendered, Mapping):
                if set(rendered) != {"payload", "source_ids"}:
                    raise ValueError("trusted RKE renderer returned an invalid materialization")
                raw_payload = _required_payload(rendered["payload"], "RKE payload")
                raw_source_ids = rendered["source_ids"]
                if not isinstance(raw_source_ids, Sequence) or isinstance(
                    raw_source_ids, (str, bytes)
                ):
                    raise ValueError("trusted RKE renderer source_ids must be an array")
                source_ids = tuple(str(value) for value in raw_source_ids)
            else:
                raw_payload = _required_payload(rendered, "RKE payload")
        else:
            if (
                tool_id == "get_industry_policy_digest"
                and self.source_preparer is not None
            ):
                self.source_preparer(tool_id, dict(args))
            method, route_args = _legacy_call(tool_id, args)
            raw_payload = _required_payload(self.route_caller(method, *route_args))

        as_of = _query_as_of(tool_id, args)
        route_id = _ROUTE_BY_TOOL[tool_id]
        descriptor = {
            "tool_id": tool_id,
            "route_id": route_id,
            "as_of": as_of,
            "request_hash": canonical_hash(args),
            "content_hash": canonical_hash({"text": raw_payload}),
            "pit_mode": _PIT_MODE_BY_ROUTE[route_id],
        }
        source_receipts = None
        if self.source_evidence_authority is not None:
            source_receipts = self.source_evidence_authority(
                tool_id,
                dict(args),
                raw_payload,
                dict(descriptor),
                source_ids,
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
