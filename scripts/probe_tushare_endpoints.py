#!/usr/bin/env python3
"""Run permission/schema probes for the closed Tushare endpoint registry.

Only request metadata, row counts and response hashes are persisted.  Vendor
rows and the token never leave process memory.  A successful one-shot probe is
recorded as ``PRECHECK_REQUIRED``; it does not activate production use without
the endpoint-specific PIT and coverage audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tushare as ts

from mosaic.dataflows.tushare_catalog import (
    OPERATOR_DISABLED_PERMISSION_ENDPOINTS,
    TUSHARE_ENDPOINT_IDS,
)
from mosaic.dataflows.economic_calendar import (
    ECO_CAL_CAPTURE_CONTRACT_VERSION,
    ECO_CAL_EXPECTED_COLUMNS,
    ECO_CAL_REGISTERED_CURRENCIES,
    ECO_CAL_REGISTERED_ROUTES,
    EconomicCalendarStore,
    preflight_eco_calendar_coverage,
)

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PATH = ROOT / "registry" / "data_sources" / "tushare_endpoint_preflight_v2.json"
PRIVATE_PATH = (
    ROOT / ".mosaic" / "cache" / "tushare_endpoint_preflight" / "live_checks.json"
)
ECO_CAL_PROBE_DB = PRIVATE_PATH.parent / "eco_cal_coverage_probe.sqlite3"

PROBES: dict[str, dict[str, Any]] = {
    "cn_pmi": {},
    "cn_gdp": {},
    "cn_cpi": {},
    "cn_ppi": {},
    "shibor": {"start_date": "20260701", "end_date": "20260717"},
    "shibor_quote": {"start_date": "20260701", "end_date": "20260717"},
    "yc_cb": {"trade_date": "20260716"},
    "us_tycr": {"start_date": "20260701", "end_date": "20260717"},
    "trade_cal": {
        "exchange": "SSE",
        "start_date": "20260701",
        "end_date": "20260717",
    },
    "stock_basic": {"exchange": "", "list_status": "L"},
    "stock_st": {"trade_date": "20260716"},
    "daily": {"trade_date": "20260716"},
    "daily_basic": {"trade_date": "20260716"},
    "adj_factor": {"trade_date": "20260716"},
    "suspend_d": {"trade_date": "20260716"},
    "stk_limit": {"trade_date": "20260716"},
    "index_basic": {"market": "SSE"},
    "index_classify": {"level": "L2", "src": "SW2021"},
    "index_member_all": {"l2_code": "801012.SI"},
    "index_daily": {
        "ts_code": "000001.SH",
        "start_date": "20260701",
        "end_date": "20260717",
    },
    "index_weight": {
        "index_code": "000300.SH",
        "start_date": "20260601",
        "end_date": "20260630",
    },
    "fund_basic": {"market": "E"},
    "etf_index": {},
    "fund_daily": {
        "ts_code": "510300.SH",
        "start_date": "20260701",
        "end_date": "20260717",
    },
    "fund_adj": {
        "ts_code": "510300.SH",
        "start_date": "20260701",
        "end_date": "20260717",
    },
    "fund_nav": {
        "ts_code": "510300.SH",
        "start_date": "20260701",
        "end_date": "20260717",
    },
    "fund_share": {
        "ts_code": "510300.SH",
        "start_date": "20260701",
        "end_date": "20260717",
    },
    "fund_portfolio": {"ts_code": "510300.SH"},
    "fut_basic": {"exchange": "INE", "fut_type": "1"},
    "fut_daily": {
        "ts_code": "SC2608.INE",
        "start_date": "20260701",
        "end_date": "20260717",
    },
    "fx_obasic": {},
    "fx_daily": {"start_date": "20260701", "end_date": "20260717"},
    "moneyflow": {"trade_date": "20260716"},
    "moneyflow_ind_ths": {"trade_date": "20260716"},
    "top_list": {"trade_date": "20260716"},
    "top10_holders": {"ts_code": "000001.SZ"},
    "top10_floatholders": {"ts_code": "000001.SZ"},
    "stock_company": {"ts_code": "000001.SZ"},
    "fina_indicator": {
        "ts_code": "000001.SZ",
        "start_date": "20250101",
        "end_date": "20260717",
    },
    "forecast": {"ann_date": "20260715"},
    "express": {"ann_date": "20260715"},
    "income": {
        "ts_code": "000001.SZ",
        "start_date": "20250101",
        "end_date": "20260717",
    },
    "balancesheet": {
        "ts_code": "000001.SZ",
        "start_date": "20250101",
        "end_date": "20260717",
    },
    "cashflow": {
        "ts_code": "000001.SZ",
        "start_date": "20250101",
        "end_date": "20260717",
    },
    "fina_mainbz": {"ts_code": "000001.SZ", "type": "D"},
    "disclosure_date": {"end_date": "20260630"},
    "research_report": {"trade_date": "20260716"},
}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def response_hash(frame: Any) -> str:
    payload = frame.to_json(orient="split", date_format="iso", force_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def disabled_row(endpoint: str, checked_at: str) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "status": "DISABLED_PERMISSION_DENIED",
        "permission_checked_at": checked_at,
        "permission_evidence_id": "operator_confirmed_permission_denied_v1",
        "schema_contract_version": "permission_denial_only_v1",
        "request_contract": {},
        "expected_columns": [],
        "observed_row_count": 0,
        "permission_result": "PERMISSION_DENIED",
        "pit_assessment": "NOT_APPLICABLE",
        "raw_payload_committed": False,
        "response_content_hash": None,
        "permission_error_class": "OPERATOR_CONFIRMED_PERMISSION_DENIED",
        "coverage_smoke": {
            "scope_kind": "DISABLED_NO_REQUEST",
            "date": checked_at[:10],
            "registered_currency_count": 0,
            "query_count": 0,
            "raw_row_count": 0,
            "deduplicated_row_count": 0,
            "truncated_leaf_count": 0,
            "status": "EMPTY_RESPONSE",
        },
    }


def live_row(
    pro: Any, endpoint: str, request: dict[str, Any], checked_at: str
) -> dict[str, Any]:
    try:
        frame = getattr(pro, endpoint)(**request)
    except (
        Exception
    ) as exc:  # Tushare exposes permission failures as generic Exception.
        message = str(exc)
        denied = "没有接口" in message and "访问权限" in message
        return {
            "endpoint": endpoint,
            "status": "DISABLED_PERMISSION_DENIED" if denied else "PRECHECK_REQUIRED",
            "permission_checked_at": checked_at,
            "permission_evidence_id": f"tushare-live-probe:{endpoint}:{checked_at}",
            "schema_contract_version": f"tushare_{endpoint}_unverified_schema_v1",
            "request_contract": request,
            "expected_columns": [],
            "observed_row_count": 0,
            "permission_result": "PERMISSION_DENIED" if denied else "EMPTY_RESPONSE",
            "pit_assessment": "NOT_APPLICABLE" if denied else "LOCAL_CAPTURE_ONLY",
            "raw_payload_committed": False,
            "response_content_hash": None,
            "permission_error_class": type(exc).__name__,
            "coverage_smoke": {
                "scope_kind": "PERMISSION_SCHEMA_SAMPLE",
                "date": checked_at[:10],
                "registered_currency_count": 0,
                "query_count": 1,
                "raw_row_count": 0,
                "deduplicated_row_count": 0,
                "truncated_leaf_count": 0,
                "status": "EMPTY_RESPONSE",
            },
        }
    columns = [str(column) for column in frame.columns]
    count = len(frame)
    truncation_risk = endpoint == "fund_portfolio" and count >= 8000
    result = (
        "TRUNCATION_RISK"
        if truncation_risk
        else "NON_EMPTY_RESPONSE"
        if count
        else "EMPTY_RESPONSE"
    )
    smoke_status = (
        "TRUNCATION_RISK"
        if truncation_risk
        else "PERMISSION_SCHEMA_ONLY"
        if count
        else "EMPTY_RESPONSE"
    )
    return {
        "endpoint": endpoint,
        "status": "PRECHECK_REQUIRED",
        "permission_checked_at": checked_at,
        "permission_evidence_id": f"tushare-live-probe:{endpoint}:{checked_at}",
        "schema_contract_version": f"tushare_{endpoint}_observed_schema_v1",
        "request_contract": request,
        "expected_columns": columns,
        "observed_row_count": count,
        "permission_result": result,
        "pit_assessment": "LOCAL_CAPTURE_ONLY",
        "raw_payload_committed": False,
        "response_content_hash": response_hash(frame),
        "permission_error_class": None,
        "coverage_smoke": {
            "scope_kind": "PERMISSION_SCHEMA_SAMPLE",
            "date": checked_at[:10],
            "registered_currency_count": 0,
            "query_count": 1,
            "raw_row_count": count,
            "deduplicated_row_count": count,
            "truncated_leaf_count": 1 if truncation_risk else 0,
            "status": smoke_status,
        },
    }


def eco_cal_live_row(pro: Any, checked_at: str, probe_date: str) -> dict[str, Any]:
    """Run the exact production route contract without persisting rows publicly."""
    try:
        batch = preflight_eco_calendar_coverage(
            pro.eco_cal,
            start_date=probe_date,
            end_date=probe_date,
            retrieved_at=checked_at,
            store=EconomicCalendarStore(ECO_CAL_PROBE_DB),
        )
    except Exception as exc:  # Tushare exposes permission failures as generic Exception.
        message = str(exc)
        denied = "没有接口" in message and "访问权限" in message
        row = disabled_row("eco_cal", checked_at) if denied else None
        if row is not None:
            row["permission_evidence_id"] = f"tushare-live-probe:eco_cal:{checked_at}"
            row["permission_error_class"] = type(exc).__name__
            return row
        return {
            "endpoint": "eco_cal",
            "status": "PRECHECK_REQUIRED",
            "permission_checked_at": checked_at,
            "permission_evidence_id": f"tushare-live-probe:eco_cal:{checked_at}",
            "schema_contract_version": ECO_CAL_CAPTURE_CONTRACT_VERSION,
            "request_contract": {
                "date": probe_date,
                "routes": [list(route) for route in ECO_CAL_REGISTERED_ROUTES],
                "routing": "EXACT_DATE_DOCUMENTED_COUNTRY_WITH_EXPECTED_CURRENCY",
            },
            "expected_columns": list(ECO_CAL_EXPECTED_COLUMNS),
            "observed_row_count": 0,
            "permission_result": "EMPTY_RESPONSE",
            "pit_assessment": "LOCAL_CAPTURE_ONLY",
            "raw_payload_committed": False,
            "response_content_hash": None,
            "permission_error_class": type(exc).__name__,
            "coverage_smoke": {
                "scope_kind": "EXACT_DATE_CURRENCY_COVERAGE",
                "date": probe_date,
                "registered_currency_count": len(ECO_CAL_REGISTERED_CURRENCIES),
                "query_count": 0,
                "raw_row_count": 0,
                "deduplicated_row_count": 0,
                "truncated_leaf_count": 0,
                "status": "EMPTY_RESPONSE",
            },
        }

    requests = batch["requests"]
    truncated_leaf_count = sum(
        request.get("leaf_status") == "TRUNCATED" for request in requests
    )
    observed_row_count = sum(int(request["row_count"]) for request in requests)
    complete = (
        batch["status"] == "COMPLETE"
        and len(requests) == len(ECO_CAL_REGISTERED_CURRENCIES)
        and truncated_leaf_count == 0
        and observed_row_count > 0
    )
    return {
        "endpoint": "eco_cal",
        "status": "ACTIVE_VERIFIED" if complete else "PRECHECK_REQUIRED",
        "permission_checked_at": checked_at,
        "permission_evidence_id": f"tushare-live-coverage-probe:eco_cal:{checked_at}",
        "schema_contract_version": ECO_CAL_CAPTURE_CONTRACT_VERSION,
        "request_contract": {
            "date": probe_date,
            "routes": [list(route) for route in ECO_CAL_REGISTERED_ROUTES],
            "routing": "EXACT_DATE_DOCUMENTED_COUNTRY_WITH_EXPECTED_CURRENCY",
        },
        "expected_columns": list(ECO_CAL_EXPECTED_COLUMNS),
        "observed_row_count": observed_row_count,
        "permission_result": (
            "NON_EMPTY_RESPONSE"
            if complete
            else "TRUNCATION_RISK"
            if truncated_leaf_count
            else "NON_EMPTY_RESPONSE"
            if observed_row_count
            else "EMPTY_RESPONSE"
        ),
        "pit_assessment": "LOCAL_CAPTURE_ONLY",
        "raw_payload_committed": False,
        "response_content_hash": canonical_hash(batch["raw_row_hashes"]),
        "permission_error_class": None,
        "coverage_smoke": {
            "scope_kind": "EXACT_DATE_CURRENCY_COVERAGE",
            "date": probe_date,
            "registered_currency_count": len(ECO_CAL_REGISTERED_CURRENCIES),
            "query_count": batch["query_count"],
            "raw_row_count": batch["raw_row_count"],
            "deduplicated_row_count": batch["deduplicated_row_count"],
            "truncated_leaf_count": truncated_leaf_count,
            "status": (
                "COMPLETE"
                if complete
                else "TRUNCATION_RISK"
                if truncated_leaf_count
                else "PERMISSION_SCHEMA_ONLY"
                if observed_row_count
                else "EMPTY_RESPONSE"
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-out", type=Path, default=PUBLIC_PATH)
    parser.add_argument("--private-out", type=Path, default=PRIVATE_PATH)
    parser.add_argument(
        "--endpoint",
        action="append",
        choices=TUSHARE_ENDPOINT_IDS,
        help="Probe only this endpoint and preserve the other recorded checks",
    )
    parser.add_argument(
        "--eco-cal-date",
        default="2020-04-10",
        help="Known event date used for the exact eco_cal coverage probe (YYYY-MM-DD)",
    )
    args = parser.parse_args()
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise SystemExit("TUSHARE_TOKEN is required")
    previous = json.loads(PUBLIC_PATH.read_text(encoding="utf-8"))
    rows_by_endpoint = {row["endpoint"]: row for row in previous["checks"]}
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    pro = ts.pro_api(token)
    selected = set(args.endpoint or TUSHARE_ENDPOINT_IDS)
    for endpoint in TUSHARE_ENDPOINT_IDS:
        if endpoint not in selected:
            continue
        if endpoint == "eco_cal":
            rows_by_endpoint[endpoint] = eco_cal_live_row(
                pro, checked_at, args.eco_cal_date
            )
            continue
        if endpoint in OPERATOR_DISABLED_PERMISSION_ENDPOINTS:
            rows_by_endpoint[endpoint] = disabled_row(endpoint, checked_at)
            continue
        rows_by_endpoint[endpoint] = live_row(
            pro, endpoint, PROBES[endpoint], checked_at
        )
    missing = set(TUSHARE_ENDPOINT_IDS) - set(rows_by_endpoint)
    if missing:
        raise SystemExit(f"preflight artifact lacks endpoint checks: {sorted(missing)}")
    rows = [rows_by_endpoint[endpoint] for endpoint in TUSHARE_ENDPOINT_IDS]
    rows.sort(key=lambda row: TUSHARE_ENDPOINT_IDS.index(row["endpoint"]))
    payload = {
        "schema_version": "tushare_endpoint_preflight_v2",
        "registry_version": "tushare_endpoint_registry_v2",
        "generated_at": checked_at,
        "checks": rows,
    }
    payload["artifact_hash"] = canonical_hash(payload)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    args.private_out.parent.mkdir(parents=True, exist_ok=True)
    args.private_out.write_text(encoded, encoding="utf-8")
    args.public_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_out.write_text(encoded, encoding="utf-8")
    summary = {
        "active": [
            row["endpoint"] for row in rows if row["status"] == "ACTIVE_VERIFIED"
        ],
        "permission_denied": [
            row["endpoint"]
            for row in rows
            if row["status"] == "DISABLED_PERMISSION_DENIED"
        ],
        "schema_sampled": [
            row["endpoint"]
            for row in rows
            if row["status"] == "PRECHECK_REQUIRED"
            and row["permission_result"] == "NON_EMPTY_RESPONSE"
        ],
        "still_incomplete": [
            row["endpoint"]
            for row in rows
            if row["status"] == "PRECHECK_REQUIRED"
            and row["permission_result"] != "NON_EMPTY_RESPONSE"
        ],
        "artifact_hash": payload["artifact_hash"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
