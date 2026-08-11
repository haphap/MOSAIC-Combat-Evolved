"""Route-version eligibility authority for all-Agent materialization cycles."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from mosaic.scorecard.canonical_json import canonical_hash

from .agent_materialization import (
    AgentDataMaterializationLedger,
    RouteEligibilityReceipt,
    SourceCaptureReceipt,
    load_agent_data_route_manifest,
    route_eligibility_checker_version,
)
from .calendar import verified_trading_calendar_snapshot


MOF_CHINABOND_LICENSE_RECEIPT_ENV = (
    "MOSAIC_MOF_CHINABOND_LICENSE_RECEIPT_PATH"
)
_MOF_CHINABOND_ROUTE_ID = "composite.cn_rates"
_MOF_CHINABOND_SOURCE_ID = "official.mof_chinabond_government_yield_curve"
_MOF_CHINABOND_LICENSE_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "route_id",
        "source_id",
        "decision",
        "authorization_scope",
        "reviewer",
        "decided_at",
        "receipt_hash",
    }
)


def production_license_receipt_ref(
    *, route_id: str, evaluated_at: str
) -> str | None:
    """Return the validated private production-license receipt hash, if any."""
    if route_id != _MOF_CHINABOND_ROUTE_ID:
        return None
    configured = os.getenv(MOF_CHINABOND_LICENSE_RECEIPT_ENV)
    if not configured:
        return None
    try:
        payload = json.loads(Path(configured).expanduser().read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != _MOF_CHINABOND_LICENSE_FIELDS:
            return None
        if (
            payload["schema_version"] != "source_license_decision_receipt_v1"
            or payload["route_id"] != _MOF_CHINABOND_ROUTE_ID
            or payload["source_id"] != _MOF_CHINABOND_SOURCE_ID
            or payload["decision"] != "APPROVED_FOR_PRODUCTION_USE"
            or payload["authorization_scope"] != "production_analysis"
            or not isinstance(payload["receipt_id"], str)
            or not payload["receipt_id"].strip()
            or not isinstance(payload["reviewer"], str)
            or not payload["reviewer"].strip()
        ):
            return None
        decided_at = datetime.fromisoformat(str(payload["decided_at"]))
        evaluation_time = datetime.fromisoformat(evaluated_at)
        if (
            decided_at.tzinfo is None
            or evaluation_time.tzinfo is None
            or decided_at > evaluation_time
        ):
            return None
        receipt_hash = payload["receipt_hash"]
        body = {key: value for key, value in payload.items() if key != "receipt_hash"}
        if receipt_hash != canonical_hash(body):
            return None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return str(receipt_hash)


@dataclass(frozen=True)
class ReceiptContractPolicy:
    authority_provider: str
    permission_tier: str
    api_version: str
    pagination_policy: str
    required_dimensions: tuple[tuple[str, tuple[str, ...]], ...] = ()
    require_parent_capture: bool = False


def _policy(
    authority_provider: str,
    permission_tier: str,
    api_version: str,
    pagination_policy: str,
    *,
    required_dimensions: Mapping[str, Sequence[str]] | None = None,
    require_parent_capture: bool = False,
) -> ReceiptContractPolicy:
    return ReceiptContractPolicy(
        authority_provider=authority_provider,
        permission_tier=permission_tier,
        api_version=api_version,
        pagination_policy=pagination_policy,
        required_dimensions=tuple(
            (key, tuple(sorted(set(values))))
            for key, values in sorted((required_dimensions or {}).items())
        ),
        require_parent_capture=require_parent_capture,
    )


@dataclass(frozen=True)
class RouteEligibilityCheckerSpec:
    route_id: str
    contract_version: str

    @property
    def checker_version(self) -> str:
        return route_eligibility_checker_version(self.contract_version)

    @property
    def receipt_policy(self) -> ReceiptContractPolicy:
        return _CONTRACT_RECEIPT_POLICIES[self.contract_version]


_CHECKER_SPECS = (
    RouteEligibilityCheckerSpec("alfred.us_macro", "alfred_us_macro_v1"),
    RouteEligibilityCheckerSpec(
        "ecb.eu_real_economy", "ecb_eu_real_economy_history_v1"
    ),
    RouteEligibilityCheckerSpec("ecb.euro_macro", "ecb_euro_macro_v2"),
    RouteEligibilityCheckerSpec(
        "geopolitical.required_coverage", "geopolitical_required_coverage_v1"
    ),
    RouteEligibilityCheckerSpec("market.euro_fx", "euro_fx_market_v1"),
    RouteEligibilityCheckerSpec(
        "market.us_conditions", "us_market_conditions_v1"
    ),
    RouteEligibilityCheckerSpec("official.cn_macro", "official_cn_macro_v1"),
    RouteEligibilityCheckerSpec(
        "official.company_supply_chain_disclosures",
        "company_supply_chain_disclosures_v1",
    ),
    RouteEligibilityCheckerSpec(
        "official.govcn_policy", "govcn_policy_forward_archive_v1"
    ),
    RouteEligibilityCheckerSpec(
        "official.us_policy", "official_us_policy_v1"
    ),
    RouteEligibilityCheckerSpec(
        "private.rke_report_intelligence", "rke_agent_research_context_pit_v1"
    ),
    RouteEligibilityCheckerSpec(
        "private.tushare_research_reports",
        "private_research_report_forward_archive_v1",
    ),
    RouteEligibilityCheckerSpec(
        "runtime.accepted_outputs", "runtime_accepted_outputs_v1"
    ),
    RouteEligibilityCheckerSpec(
        "runtime.account_positions_policy", "runtime_account_positions_policy_v1"
    ),
    RouteEligibilityCheckerSpec(
        "runtime.candidate_scope", "runtime_candidate_scope_v1"
    ),
    RouteEligibilityCheckerSpec(
        "runtime.market_liquidity", "runtime_market_liquidity_v1"
    ),
    RouteEligibilityCheckerSpec(
        "tushare.a_share_breadth", "tushare_a_share_breadth_v1"
    ),
    RouteEligibilityCheckerSpec("tushare.cn_macro", "tushare_cn_macro_v1"),
    RouteEligibilityCheckerSpec(
        "tushare.commodities", "tushare_commodities_v1"
    ),
    RouteEligibilityCheckerSpec(
        "tushare.eco_cal.cny", "tushare_eco_cal_cny_v1"
    ),
    RouteEligibilityCheckerSpec(
        "tushare.eco_cal.eur", "tushare_eco_cal_eur_v1"
    ),
    RouteEligibilityCheckerSpec(
        "tushare.eco_cal.usd", "tushare_eco_cal_usd_v1"
    ),
    RouteEligibilityCheckerSpec(
        "tushare.etf_holdings", "tushare_etf_holdings_disclosure_v1"
    ),
    RouteEligibilityCheckerSpec(
        "tushare.fx_daily", "tushare_fx_daily_usd_cnh_v1"
    ),
    RouteEligibilityCheckerSpec(
        "tushare.institutional_flow", "tushare_institutional_flow_v1"
    ),
    RouteEligibilityCheckerSpec(
        "tushare.relationship_graph", "tushare_relationship_graph_v1"
    ),
    RouteEligibilityCheckerSpec(
        "tushare.sector_fundamentals", "tushare_sector_fundamentals_v1"
    ),
    RouteEligibilityCheckerSpec(
        "tushare.sector_market", "tushare_sector_market_v1"
    ),
    RouteEligibilityCheckerSpec(
        "composite.cn_rates", "composite_cn_rates_mof_chinabond_v1"
    ),
    RouteEligibilityCheckerSpec(
        "tushare.us_tycr", "tushare_us_tycr_nominal_curve_v1"
    ),
)

_CONTRACT_RECEIPT_POLICIES = {
    "alfred_us_macro_v1": _policy(
        "ALFRED",
        "api_key_env",
        "fred-v1",
        "EXACT_SERIES_VINTAGE_SET",
        required_dimensions={"series_id": (), "vintage_date": ()},
    ),
    "ecb_eu_real_economy_history_v1": _policy(
        "ECB",
        "public",
        "data-api-v1",
        "ONE_BOUNDED_QUERY_PER_REGISTERED_SERIES",
        required_dimensions={"series_id": ()},
    ),
    "ecb_euro_macro_v2": _policy(
        "ECB",
        "public",
        "data-api-v1",
        "ONE_BOUNDED_QUERY_PER_REGISTERED_SERIES",
        required_dimensions={"series_id": ()},
    ),
    "geopolitical_required_coverage_v1": _policy(
        "geopolitical",
        "public-license-verified",
        "source-manifest-v2",
        "source-specific-terminal-v1",
        required_dimensions={"preflight_receipt_id": (), "source_id": ()},
    ),
    "euro_fx_market_v1": _policy(
        "tushare",
        "configured-runtime",
        "pro-v1",
        "SINGLE_BOUNDED_QUERY",
        required_dimensions={"instrument_id": ("EURUSD.FXCM",)},
    ),
    "us_market_conditions_v1": _policy(
        "NY_FED",
        "public",
        "markets-rates-v1",
        "TWO_EXACT_RATE_WINDOWS",
        required_dimensions={"rate_type": ("EFFR", "SOFR")},
    ),
    "official_cn_macro_v1": _policy(
        "official_cn",
        "public",
        "public-web-v1",
        "REGISTERED_BOUNDED_REQUEST_SET",
        required_dimensions={"document_type": ()},
    ),
    "company_supply_chain_disclosures_v1": _policy(
        "cninfo",
        "official_public_disclosure",
        "cninfo-public-v1",
        "BOUNDED_CNINFO_ANNUAL_REPORT_QUERY_V1",
        required_dimensions={
            "route_id": ("official.company_supply_chain_disclosures",)
        },
        require_parent_capture=True,
    ),
    "govcn_policy_forward_archive_v1": _policy(
        "govcn",
        "trusted_local_forward_archive",
        "archive-v1",
        "PRIVATE_FORWARD_ARCHIVE_EXACT_SELECTION",
        required_dimensions={"route_id": ("official.govcn_policy",)},
        require_parent_capture=True,
    ),
    "official_us_policy_v1": _policy(
        "FEDERAL_RESERVE",
        "public",
        "federal-reserve-rss",
        "SINGLE_RSS_FEED",
        required_dimensions={"document_type": ("FOMC_STATEMENT",)},
    ),
    "rke_agent_research_context_pit_v1": _policy(
        "local_private_rke",
        "trusted_private_archive",
        "rke-v1",
        "EXACT_PRIVATE_SOURCE_SET_V1",
        required_dimensions={"route_id": ("private.rke_report_intelligence",)},
        require_parent_capture=True,
    ),
    "private_research_report_forward_archive_v1": _policy(
        "tushare",
        "trusted_local_forward_archive",
        "archive-v1",
        "PRIVATE_FORWARD_ARCHIVE_EXACT_SELECTION",
        required_dimensions={
            "route_id": ("private.tushare_research_reports",)
        },
        require_parent_capture=True,
    ),
    "runtime_accepted_outputs_v1": _policy(
        "mosaic_runtime",
        "trusted_process_memory",
        "runtime_accepted_outputs_v1",
        "SINGLE_FROZEN_RUNTIME_OBJECT",
    ),
    "runtime_account_positions_policy_v1": _policy(
        "mosaic_runtime",
        "trusted_process_memory",
        "runtime_account_positions_policy_v1",
        "SINGLE_FROZEN_RUNTIME_OBJECT",
    ),
    "runtime_candidate_scope_v1": _policy(
        "mosaic_runtime",
        "trusted_process_memory",
        "runtime_candidate_scope_v1",
        "SINGLE_FROZEN_RUNTIME_OBJECT",
    ),
    "runtime_market_liquidity_v1": _policy(
        "mosaic_runtime",
        "trusted_process_memory",
        "runtime_market_liquidity_v1",
        "SINGLE_FROZEN_RUNTIME_OBJECT",
    ),
    "tushare_a_share_breadth_v1": _policy(
        "tushare",
        "route_preflight_verified",
        "pro-v1",
        "OFFSET_UNTIL_SHORT_PAGE",
        required_dimensions={
            "endpoint": (),
            "market": ("BSE", "SSE", "SZSE"),
        },
    ),
    "tushare_cn_macro_v1": _policy(
        "tushare",
        "configured-runtime",
        "pro-v1",
        "REGISTERED_BOUNDED_REQUEST_SET",
        required_dimensions={"endpoint": ()},
    ),
    "tushare_commodities_v1": _policy(
        "tushare",
        "configured-runtime",
        "pro-v1",
        "REGISTERED_REQUEST_SET_WITH_OFFSET_TERMINAL_CONFIRMATION",
        required_dimensions={"family_id": ()},
    ),
    "tushare_eco_cal_cny_v1": _policy(
        "tushare",
        "token_preflight_verified",
        "pro-v1",
        "SINGLE_PAGE_EXACT_DATE",
        required_dimensions={"country": (), "currency": ("CNY",)},
    ),
    "tushare_eco_cal_eur_v1": _policy(
        "tushare",
        "token_preflight_verified",
        "pro-v1",
        "SINGLE_PAGE_EXACT_DATE",
        required_dimensions={
            "country": (),
            "currency": ("EUR", "BGN", "CZK", "DKK", "HUF", "PLN", "RON", "SEK"),
        },
    ),
    "tushare_eco_cal_usd_v1": _policy(
        "tushare",
        "token_preflight_verified",
        "pro-v1",
        "SINGLE_PAGE_EXACT_DATE",
        required_dimensions={"country": (), "currency": ("USD",)},
    ),
    "tushare_etf_holdings_disclosure_v1": _policy(
        "tushare",
        "trusted_private_archive",
        "pro-v1",
        "FROZEN_ETF_DISCLOSURE_SELECTION_V1",
        required_dimensions={"route_id": ("tushare.etf_holdings",)},
        require_parent_capture=True,
    ),
    "tushare_fx_daily_usd_cnh_v1": _policy(
        "tushare",
        "capture_preflight_verified",
        "pro-v1",
        "SINGLE_WINDOW_RESPONSE",
        required_dimensions={
            "endpoint": ("fx_daily",),
            "instrument": ("USDCNH.FXCM",),
        },
    ),
    "tushare_institutional_flow_v1": _policy(
        "tushare",
        "configured-runtime",
        "pro-v1",
        "REGISTERED_BOUNDED_REQUEST_SET",
        required_dimensions={
            "endpoint": (
                "daily_basic",
                "fund_share",
                "moneyflow_hsgt",
                "moneyflow_ind_ths",
            ),
            "etf": (),
        },
    ),
    "tushare_relationship_graph_v1": _policy(
        "tushare",
        "route_preflight_verified",
        "pro-v1",
        "ENDPOINT_SPECIFIC_COMPLETENESS_V1",
        required_dimensions={"logical_route": ("tushare.relationship_graph",)},
        require_parent_capture=True,
    ),
    "tushare_sector_fundamentals_v1": _policy(
        "tushare",
        "route_preflight_verified",
        "pro-v1",
        "ENDPOINT_SPECIFIC_COMPLETENESS_V1",
        required_dimensions={
            "logical_route": ("tushare.sector_fundamentals",)
        },
        require_parent_capture=True,
    ),
    "tushare_sector_market_v1": _policy(
        "tushare",
        "route_preflight_verified",
        "pro-v1",
        "ENDPOINT_SPECIFIC_COMPLETENESS_V1",
        required_dimensions={"logical_route": ("tushare.sector_market",)},
        require_parent_capture=True,
    ),
    "composite_cn_rates_mof_chinabond_v1": _policy(
        "composite",
        "public/configured-runtime",
        "mof-chinabond-history-v1/tushare-pro-v1",
        "REGISTERED_BOUNDED_REQUEST_SET",
        required_dimensions={
            "component": (
                "mof_chinabond_maturity_curve",
                "tushare_shibor",
            ),
            "tenor": (
                "10y",
                "1y",
                "2y",
                "30y",
                "3m",
                "3y",
                "5y",
                "7y",
                "overnight",
            )
        },
    ),
    "tushare_us_tycr_nominal_curve_v1": _policy(
        "tushare",
        "capture_preflight_verified",
        "pro-v1",
        "SINGLE_WINDOW_RESPONSE",
        required_dimensions={"endpoint": ("us_tycr",), "series_id": ()},
    ),
}

ROUTE_ELIGIBILITY_CHECKERS = {
    spec.contract_version: spec for spec in _CHECKER_SPECS
}


def _validate_checker_registry() -> None:
    manifest = load_agent_data_route_manifest()
    expected = {
        (route["route_id"], route["contract_version"])
        for route in manifest["routes"]
    }
    actual = {(spec.route_id, spec.contract_version) for spec in _CHECKER_SPECS}
    if (
        actual != expected
        or len(ROUTE_ELIGIBILITY_CHECKERS) != len(expected)
        or set(_CONTRACT_RECEIPT_POLICIES)
        != {route["contract_version"] for route in manifest["routes"]}
    ):
        raise RuntimeError("route eligibility checker registry drift")


_validate_checker_registry()


def _route(route_id: str) -> Mapping[str, Any]:
    route = next(
        (
            value
            for value in load_agent_data_route_manifest()["routes"]
            if value["route_id"] == route_id
        ),
        None,
    )
    if route is None:
        raise ValueError(f"unknown Agent data route: {route_id}")
    return route


def _receipt_interval(payload: Mapping[str, Any]) -> tuple[date, date] | None:
    coverage = payload["coverage"]
    requested_start = date.fromisoformat(coverage["requested_start"])
    requested_end = date.fromisoformat(coverage["requested_end"])
    route_id = str(payload["identity"]["route_id"])
    is_true_empty = (
        payload["completeness"]["empty_result_semantics"] == "TRUE_EMPTY"
    )
    if route_id == "official.us_policy" and is_true_empty:
        return None
    if (
        payload["pit"]["pit_mode"]
        in {"AUTHORITATIVE_VINTAGE_REPLAY", "DERIVED_FROM_PIT_ARCHIVE"}
        or is_true_empty
    ):
        return (
            requested_start,
            requested_end,
        )
    if coverage["observed_start"] is None or coverage["observed_end"] is None:
        return None
    observed_start = date.fromisoformat(coverage["observed_start"])
    observed_end = date.fromisoformat(coverage["observed_end"])
    if (
        route_id == "official.us_policy"
        and observed_start <= requested_end
        and observed_end <= requested_end
    ):
        return requested_start, requested_end
    if route_id in {
        "market.euro_fx",
        "market.us_conditions",
        "tushare.fx_daily",
    }:
        lag_days = (requested_end - observed_end).days
        if 0 <= lag_days <= 4:
            return requested_start, requested_end
    return observed_start, observed_end


def _requested_interval(payload: Mapping[str, Any]) -> tuple[date, date]:
    coverage = payload["coverage"]
    return (
        date.fromisoformat(coverage["requested_start"]),
        date.fromisoformat(coverage["requested_end"]),
    )


def _mapped_blockers(values: list[str]) -> list[str]:
    mapping = {
        "PERMISSION_DENIED": "PERMISSION_DENIED",
        "TRANSPORT_TIMEOUT": "TIMEOUT",
        "SCHEMA_DRIFT": "SCHEMA_DRIFT",
        "STALE_SOURCE": "STALE",
        "TRUNCATED": "REVISION_GAP",
        "INCOMPLETE_COVERAGE": "REVISION_GAP",
        "LEAF_AUDIT_INCOMPLETE": "REVISION_GAP",
    }
    return sorted({mapping.get(value, "OUTSIDE_COVERAGE") for value in values})


def _receipt_contract_blockers(
    spec: RouteEligibilityCheckerSpec,
    payload: Mapping[str, Any],
) -> list[str]:
    policy = spec.receipt_policy
    authority = payload["authority"]
    blockers: set[str] = set()
    if authority["permission_tier"] != policy.permission_tier:
        blockers.add("PERMISSION_DENIED")
    if (
        authority["provider"] != policy.authority_provider
        or authority["api_version"] != policy.api_version
        or payload["transport"]["pagination_policy"]
        != policy.pagination_policy
    ):
        blockers.add("SCHEMA_DRIFT")
    dimensions = payload["coverage"]["dimensions"]
    for key, expected_values in policy.required_dimensions:
        actual_values = dimensions.get(key)
        if not actual_values or (
            expected_values and tuple(actual_values) != expected_values
        ):
            blockers.add("REVISION_GAP")
    if (
        policy.require_parent_capture
        and payload["provenance"]["parent_capture_hash"] is None
    ):
        blockers.add("REVISION_GAP")
    return sorted(blockers)


def _merge_intervals(
    intervals: Sequence[tuple[date, date]],
) -> list[tuple[date, date]]:
    merged: list[tuple[date, date]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + timedelta(days=1):
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _intersect_intervals(
    left: Sequence[tuple[date, date]],
    right: Sequence[tuple[date, date]],
) -> list[tuple[date, date]]:
    intersections: list[tuple[date, date]] = []
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        start = max(left[left_index][0], right[right_index][0])
        end = min(left[left_index][1], right[right_index][1])
        if start <= end:
            intersections.append((start, end))
        if left[left_index][1] <= right[right_index][1]:
            left_index += 1
        else:
            right_index += 1
    return _merge_intervals(intersections)


def _route_coverage_at(
    *,
    ledger: AgentDataMaterializationLedger,
    route_id: str,
    evaluation_time: datetime,
) -> tuple[list[tuple[date, date]], list[str], list[str]]:
    route = _route(route_id)
    spec = ROUTE_ELIGIBILITY_CHECKERS[route["contract_version"]]
    receipts = ledger.source_capture_receipts_for_route(route_id=route_id)
    intervals: list[tuple[date, date]] = []
    refs: list[str] = []
    blockers: list[str] = []
    evaluation_date = evaluation_time.date()
    for receipt in receipts:
        payload = receipt.as_dict()
        if (
            datetime.fromisoformat(payload["time"]["knowledge_available_at"])
            > evaluation_time
        ):
            continue
        if not payload["pit"]["eligible"]:
            blockers.extend(_mapped_blockers(payload["pit"]["blocker_codes"]))
            continue
        contract_blockers = _receipt_contract_blockers(spec, payload)
        if contract_blockers:
            blockers.extend(contract_blockers)
            continue
        interval = _receipt_interval(payload)
        if interval is None or interval[0] > evaluation_date:
            continue
        intervals.append((interval[0], min(interval[1], evaluation_date)))
        refs.append(receipt.receipt_hash)
    if intervals:
        return _merge_intervals(intervals), sorted(set(refs)), []
    if not receipts:
        return [], [], ["MISSING_ARCHIVE"]
    return [], [], sorted(set(blockers)) or ["OUTSIDE_COVERAGE"]


def _interval_payload(
    intervals: Sequence[tuple[date, date]],
) -> list[dict[str, str]]:
    return [
        {"start": start.isoformat(), "end": end.isoformat()}
        for start, end in intervals
    ]


def earliest_agent_source_ready_date(
    *,
    ledger: AgentDataMaterializationLedger,
    evaluated_at: str,
) -> dict[str, Any]:
    """Find the earliest verified trading date with replay-source closure."""
    evaluation_time = datetime.fromisoformat(evaluated_at)
    manifest = load_agent_data_route_manifest()
    source_route_ids = sorted(
        route["route_id"]
        for route in manifest["routes"]
        if route["pit_strategy"] != "LOCAL_RUNTIME_AUTHORITY"
    )
    runtime_precheck_route_ids = [
        "runtime.account_positions_policy",
        "runtime.market_liquidity",
    ]
    pending_runtime_route_ids = [
        "runtime.accepted_outputs",
        "runtime.candidate_scope",
    ]
    if len(source_route_ids) != 26:
        raise RuntimeError("Agent source route closure drift")

    route_blockers: dict[str, list[str]] = {}
    route_receipt_refs: dict[str, list[str]] = {}
    common: list[tuple[date, date]] | None = None
    for route_id in [*source_route_ids, *runtime_precheck_route_ids]:
        intervals, refs, blockers = _route_coverage_at(
            ledger=ledger,
            route_id=route_id,
            evaluation_time=evaluation_time,
        )
        route_receipt_refs[route_id] = refs
        if blockers:
            route_blockers[route_id] = blockers
            continue
        common = intervals if common is None else _intersect_intervals(common, intervals)

    result: dict[str, Any] = {
        "schema_version": "agent_earliest_ready_date_v1",
        "status": "BLOCKED",
        "earliest_ready_date": None,
        "evaluated_at": evaluated_at,
        "source_route_count": len(source_route_ids),
        "source_route_ids": source_route_ids,
        "runtime_precheck_route_ids": runtime_precheck_route_ids,
        "pending_runtime_route_ids": pending_runtime_route_ids,
        "eligible_intervals": _interval_payload(common or []),
        "route_blockers": route_blockers,
        "blockers": [],
        "route_receipt_refs": route_receipt_refs,
        "calendar_snapshot_hash": None,
    }
    if route_blockers:
        result["blockers"] = ["ROUTE_ARCHIVE_GAP"]
        return result
    if not common:
        result["blockers"] = ["NO_COMMON_COVERAGE"]
        return result

    calendar = verified_trading_calendar_snapshot(
        common[0][0].isoformat(),
        evaluation_time.date().isoformat(),
        as_of=evaluated_at,
    )
    result["calendar_snapshot_hash"] = calendar["snapshot_hash"]
    trading_dates = sorted(str(value) for value in calendar["trading_dates"])
    earliest = next(
        (
            value
            for value in trading_dates
            if any(
                start <= date.fromisoformat(value) <= end for start, end in common
            )
        ),
        None,
    )
    if earliest is None:
        result["blockers"] = ["NO_TRADING_DATE_IN_COMMON_COVERAGE"]
        return result
    result["status"] = "READY"
    result["earliest_ready_date"] = earliest
    return result


def _new_receipt(
    *,
    route: Mapping[str, Any],
    target_date: str,
    evaluated_at: str,
    status: str,
    intervals: list[dict[str, str]],
    selected_refs: list[str],
    blockers: list[str],
    knowledge_available_at: str | None,
    cycle_run_id: str | None,
    license_receipt_ref: str | None = None,
) -> RouteEligibilityReceipt:
    manifest = load_agent_data_route_manifest()
    payload = {
            "schema_version": "route_eligibility_receipt_v1",
            "route_id": route["route_id"],
            "contract_version": route["contract_version"],
            "route_manifest_hash": manifest["manifest_hash"],
            "checker_version": route_eligibility_checker_version(
                route["contract_version"]
            ),
            "cycle_run_id": cycle_run_id,
            "target_date": target_date,
            "eligible_intervals": intervals,
            "selected_receipt_refs": sorted(selected_refs),
            "freshness": {
                "status": (
                    "FRESH"
                    if status == "READY"
                    else ("STALE" if "STALE" in blockers else "UNKNOWN")
                ),
                "knowledge_available_at": knowledge_available_at,
            },
            "status": status,
            "blockers": sorted(blockers),
            "evaluated_at": evaluated_at,
        }
    if license_receipt_ref is not None:
        payload["license_receipt_ref"] = license_receipt_ref
    return RouteEligibilityReceipt.seal(payload)


def evaluate_route_eligibility(
    *,
    ledger: AgentDataMaterializationLedger,
    route_id: str,
    target_date: str,
    evaluated_at: str,
    cycle_run_id: str | None = None,
    require_production_license: bool = False,
) -> RouteEligibilityReceipt:
    target = date.fromisoformat(target_date)
    evaluation_time = datetime.fromisoformat(evaluated_at)
    route = _route(route_id)
    spec = ROUTE_ELIGIBILITY_CHECKERS.get(route["contract_version"])
    if spec is None or spec.route_id != route_id:
        raise ValueError("route eligibility checker registry mismatch")
    receipts = ledger.source_capture_receipts_for_route(route_id=route_id)
    eligible: list[tuple[SourceCaptureReceipt, tuple[date, date]]] = []
    blocked: list[tuple[SourceCaptureReceipt, list[str]]] = []
    for receipt in receipts:
        payload = receipt.as_dict()
        if (
            datetime.fromisoformat(payload["time"]["knowledge_available_at"])
            > evaluation_time
        ):
            continue
        requested_start, requested_end = _requested_interval(payload)
        if not requested_start <= target <= requested_end:
            continue
        interval = _receipt_interval(payload)
        if payload["pit"]["eligible"] and interval is not None:
            if interval[0] <= target <= interval[1]:
                contract_blockers = _receipt_contract_blockers(spec, payload)
                if contract_blockers:
                    blocked.append((receipt, contract_blockers))
                else:
                    eligible.append((receipt, interval))
        elif not payload["pit"]["eligible"]:
            blocked.append(
                (receipt, _mapped_blockers(payload["pit"]["blocker_codes"]))
            )
    if eligible:
        receipt, interval = eligible[0]
        payload = receipt.as_dict()
        license_receipt_ref = (
            production_license_receipt_ref(
                route_id=route_id,
                evaluated_at=evaluated_at,
            )
            if require_production_license and route_id == _MOF_CHINABOND_ROUTE_ID
            else None
        )
        if require_production_license and route_id == _MOF_CHINABOND_ROUTE_ID and (
            license_receipt_ref is None
        ):
            return _new_receipt(
                route=route,
                target_date=target_date,
                evaluated_at=evaluated_at,
                status="BLOCKED",
                intervals=[],
                selected_refs=[receipt.receipt_hash],
                blockers=["LICENSE_REVIEW_REQUIRED"],
                knowledge_available_at=payload["time"]["knowledge_available_at"],
                cycle_run_id=cycle_run_id,
            )
        return _new_receipt(
            route=route,
            target_date=target_date,
            evaluated_at=evaluated_at,
            status="READY",
            intervals=[
                {"start": interval[0].isoformat(), "end": interval[1].isoformat()}
            ],
            selected_refs=[receipt.receipt_hash],
            blockers=[],
            knowledge_available_at=payload["time"]["knowledge_available_at"],
            cycle_run_id=cycle_run_id,
            license_receipt_ref=license_receipt_ref,
        )
    if blocked:
        receipt, blockers = blocked[0]
        payload = receipt.as_dict()
        return _new_receipt(
            route=route,
            target_date=target_date,
            evaluated_at=evaluated_at,
            status="BLOCKED",
            intervals=[],
            selected_refs=[receipt.receipt_hash],
            blockers=blockers or ["OUTSIDE_COVERAGE"],
            knowledge_available_at=payload["time"]["knowledge_available_at"],
            cycle_run_id=cycle_run_id,
        )
    blocker = (
        "LOCAL_RUNTIME_MISSING"
        if route["pit_strategy"] == "LOCAL_RUNTIME_AUTHORITY"
        else ("MISSING_ARCHIVE" if not receipts else "OUTSIDE_COVERAGE")
    )
    return _new_receipt(
        route=route,
        target_date=target_date,
        evaluated_at=evaluated_at,
        status="BLOCKED",
        intervals=[],
        selected_refs=[],
        blockers=[blocker],
        knowledge_available_at=None,
        cycle_run_id=cycle_run_id,
    )


def evaluate_agent_cycle_preflight(
    *,
    ledger: AgentDataMaterializationLedger,
    target_date: str,
    evaluated_at: str,
    require_production_license: bool = False,
) -> dict[str, Any]:
    manifest = load_agent_data_route_manifest()
    return _evaluate_agent_routes(
        ledger=ledger,
        target_date=target_date,
        evaluated_at=evaluated_at,
        routes=manifest["routes"],
        schema_version="agent_cycle_preflight_v1",
        ready_status="READY",
        pending_runtime_route_ids=[],
        cycle_run_id=None,
        require_production_license=require_production_license,
    )


def evaluate_runtime_stage_admission(
    *,
    ledger: AgentDataMaterializationLedger,
    agent_id: str,
    stage: str,
    target_date: str,
    evaluated_at: str,
    cycle_run_id: str,
    source_receipt_hashes: Sequence[str],
) -> dict[str, str]:
    """Seal current-run runtime eligibility from the selected stage builds."""
    if not cycle_run_id:
        raise ValueError("cycle_run_id must be non-empty")
    target = date.fromisoformat(target_date)
    evaluation_time = datetime.fromisoformat(evaluated_at)
    manifest = load_agent_data_route_manifest()
    runtime_route_ids = {
        route["route_id"]
        for route in manifest["routes"]
        if route["pit_strategy"] == "LOCAL_RUNTIME_AUTHORITY"
    }
    bindings = [
        binding
        for binding in manifest["bindings"]
        if binding["agent_id"] == agent_id and binding["stage"] == stage
    ]
    if not bindings:
        raise ValueError(f"unknown Agent/stage: {agent_id}/{stage}")
    required = sorted(
        {
            route_id
            for binding in bindings
            for route_id in binding["required_route_ids"]
            if route_id in runtime_route_ids
        }
    )
    if not required:
        return {}
    candidates: dict[str, list[SourceCaptureReceipt]] = {
        route_id: [] for route_id in required
    }
    for receipt_hash in sorted(set(source_receipt_hashes)):
        receipt = ledger.source_capture_receipt(receipt_hash=receipt_hash)
        if receipt is None:
            continue
        route_id = receipt.as_dict()["identity"]["route_id"]
        if route_id in candidates:
            candidates[route_id].append(receipt)
    missing = sorted(
        route_id for route_id, receipts in candidates.items() if len(receipts) != 1
    )
    if missing:
        raise ValueError(
            "runtime stage admission requires one exact current-build receipt for "
            + ", ".join(missing)
        )
    result: dict[str, str] = {}
    for route_id in required:
        source = candidates[route_id][0]
        payload = source.as_dict()
        knowledge_at = payload["time"]["knowledge_available_at"]
        interval = _receipt_interval(payload)
        if (
            not payload["pit"]["eligible"]
            or interval is None
            or not interval[0] <= target <= interval[1]
            or datetime.fromisoformat(knowledge_at) > evaluation_time
        ):
            raise ValueError(f"runtime source is not PIT eligible: {route_id}")
        receipt = _new_receipt(
            route=_route(route_id),
            target_date=target_date,
            evaluated_at=evaluated_at,
            status="READY",
            intervals=[
                {"start": interval[0].isoformat(), "end": interval[1].isoformat()}
            ],
            selected_refs=[source.receipt_hash],
            blockers=[],
            knowledge_available_at=knowledge_at,
            cycle_run_id=cycle_run_id,
        )
        ledger.append_route_eligibility(receipt)
        result[route_id] = receipt.receipt_hash
    return result


def evaluate_agent_source_admission(
    *,
    ledger: AgentDataMaterializationLedger,
    target_date: str,
    evaluated_at: str,
    cycle_run_id: str | None = None,
    require_production_license: bool = False,
) -> dict[str, Any]:
    """Seal the 26 external-source checks required before the first stage."""
    manifest = load_agent_data_route_manifest()
    routes = [
        route
        for route in manifest["routes"]
        if route["pit_strategy"] != "LOCAL_RUNTIME_AUTHORITY"
    ]
    pending_runtime_route_ids = sorted(
        route["route_id"]
        for route in manifest["routes"]
        if route["pit_strategy"] == "LOCAL_RUNTIME_AUTHORITY"
    )
    if len(routes) != 26 or len(pending_runtime_route_ids) != 4:
        raise RuntimeError("Agent source/runtime route partition drift")
    return _evaluate_agent_routes(
        ledger=ledger,
        target_date=target_date,
        evaluated_at=evaluated_at,
        routes=routes,
        schema_version="agent_source_admission_v1",
        ready_status="SOURCE_READY_PENDING_RUNTIME",
        pending_runtime_route_ids=pending_runtime_route_ids,
        cycle_run_id=cycle_run_id,
        require_production_license=require_production_license,
    )


def _evaluate_agent_routes(
    *,
    ledger: AgentDataMaterializationLedger,
    target_date: str,
    evaluated_at: str,
    routes: list[Mapping[str, Any]],
    schema_version: str,
    ready_status: str,
    pending_runtime_route_ids: list[str],
    cycle_run_id: str | None,
    require_production_license: bool,
) -> dict[str, Any]:
    manifest = load_agent_data_route_manifest()
    receipts: dict[str, RouteEligibilityReceipt] = {}
    for route in routes:
        receipt = evaluate_route_eligibility(
            ledger=ledger,
            route_id=route["route_id"],
            target_date=target_date,
            evaluated_at=evaluated_at,
            cycle_run_id=cycle_run_id,
            require_production_license=require_production_license,
        )
        ledger.append_route_eligibility(receipt)
        receipts[route["route_id"]] = receipt
    required_by_stage: dict[tuple[str, str], set[str]] = {}
    for binding in manifest["bindings"]:
        key = (binding["agent_id"], binding["stage"])
        required_by_stage.setdefault(key, set()).update(binding["required_route_ids"])
    stages = []
    for (agent_id, stage), required in sorted(required_by_stage.items()):
        route_ids = sorted(required)
        evaluated_route_ids = [
            route_id for route_id in route_ids if route_id in receipts
        ]
        pending_route_ids = [
            route_id
            for route_id in route_ids
            if route_id in pending_runtime_route_ids
        ]
        blockers = sorted(
            route_id
            for route_id in evaluated_route_ids
            if receipts[route_id].as_dict()["status"] != "READY"
        )
        if blockers:
            stage_status = "BLOCKED"
        elif pending_route_ids:
            stage_status = "SOURCE_READY_PENDING_RUNTIME"
        else:
            stage_status = ready_status
        stages.append(
            {
                "agent_id": agent_id,
                "stage": stage,
                "required_route_ids": route_ids,
                "required_source_route_ids": evaluated_route_ids,
                "pending_runtime_route_ids": pending_route_ids,
                "eligibility_receipt_hashes": {
                    route_id: receipts[route_id].receipt_hash
                    for route_id in evaluated_route_ids
                },
                "status": stage_status,
                "blocked_route_ids": blockers,
            }
        )
    blocked_routes = [
        {
            "route_id": route_id,
            "blockers": receipt.as_dict()["blockers"],
        }
        for route_id, receipt in sorted(receipts.items())
        if receipt.as_dict()["status"] != "READY"
    ]
    ready = not blocked_routes
    result = {
        "schema_version": schema_version,
        "route_manifest_hash": manifest["manifest_hash"],
        "target_date": target_date,
        "evaluated_at": evaluated_at,
        "route_count": len(receipts),
        "stage_count": len(stages),
        "status": ready_status if ready else "BLOCKED",
        "would_materialize": ready,
        "blocked_routes": blocked_routes,
        "eligibility_receipt_hashes": {
            route_id: receipt.receipt_hash
            for route_id, receipt in sorted(receipts.items())
        },
        "stages": stages,
    }
    if pending_runtime_route_ids:
        result["runtime_route_count"] = len(pending_runtime_route_ids)
        result["pending_runtime_route_ids"] = pending_runtime_route_ids
    return result


__all__ = [
    "ROUTE_ELIGIBILITY_CHECKERS",
    "RouteEligibilityCheckerSpec",
    "evaluate_agent_cycle_preflight",
    "evaluate_route_eligibility",
]
