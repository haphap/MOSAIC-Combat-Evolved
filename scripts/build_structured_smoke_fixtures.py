#!/usr/bin/env python3
"""Build explicit, synthetic PIT inputs for the real-LLM structured smoke.

The generated cache is non-production and contains no vendor prose.  It lets
the 29-stage graph exercise real structured output without weakening any
production snapshot fallback or writing to the scorecard/release ledgers.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mosaic.dataflows.economic_calendar import (
    ECO_CAL_EXPECTED_COLUMNS,
    ECO_CAL_REGISTERED_CURRENCIES,
    EconomicCalendarStore,
    collect_eco_calendar,
)
from mosaic.dataflows.geopolitical_events import (
    GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
    REQUIRED_SOURCE_IDS,
    GeopoliticalEventStore,
    coverage_query_key,
    scope_query_hash,
    validate_geopolitical_manifest,
)
from mosaic.dataflows.sector_snapshots import (
    RELATIONSHIP_SNAPSHOT_SCHEMA_VERSION,
    SECTOR_DIRECTION_CONTRACT_VERSION,
    SECTOR_DIRECTION_IDS,
    SECTOR_SNAPSHOT_SCHEMA_VERSION,
)


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _macro_observation(
    *, series_id: str, source: str, as_of: date, ordinal: int
) -> dict[str, Any]:
    released = datetime.combine(
        as_of - timedelta(days=1),
        datetime.min.time(),
        tzinfo=timezone.utc,
    ).isoformat()
    period_end = as_of - timedelta(days=2)
    return {
        "series_id": series_id,
        "period_start": period_end.replace(day=1).isoformat(),
        "period_end": period_end.isoformat(),
        "released_at": released,
        "vintage_at": released,
        "actual": round(100.0 + ordinal * 0.7, 4),
        "previous": round(99.5 + ordinal * 0.7, 4),
        "expected": round(99.8 + ordinal * 0.7, 4),
        "unit": "synthetic_index",
        "source": source,
        "pit_status": "AVAILABLE_AS_OF",
        "evidence_id": f"structured-smoke:macro:{series_id}:{as_of.isoformat()}",
    }


def _build_macro_snapshots(root: Path, as_of: date) -> None:
    role_series: dict[str, tuple[tuple[str, str], ...]] = {
        "china": (
            ("cn_gdp", "tushare"),
            ("cn_cpi", "tushare"),
            ("cn_credit", "tushare"),
            ("cn_export", "tushare"),
            ("cn_fiscal", "tushare"),
        ),
        "us_economy": (
            ("us_gdp", "official"),
            ("us_cpi", "official"),
            ("us_payroll", "official"),
            ("us_retail", "official"),
        ),
        "eu_economy": (
            ("eurostat_gdp", "eurostat"),
            ("eurostat_hicp", "eurostat"),
            ("eurostat_employment", "eurostat"),
            ("eurostat_retail", "eurostat"),
        ),
        "central_bank": (
            ("pboc_policy_rate", "tushare"),
            ("domestic_liquidity_omo", "tushare"),
            ("cn_curve_10y", "tushare"),
            ("credit_condition_spread", "tushare"),
        ),
        "us_financial_conditions": (
            ("fed_balance_sheet", "official"),
            ("us_curve_10y", "official"),
            ("us_credit_spread", "official"),
            ("broad_dollar_index", "official"),
        ),
        "euro_area_financial_conditions": (
            ("ecb_policy_rate", "ecb"),
            ("euro_area_curve_10y", "ecb"),
            ("euro_area_bank_credit_growth", "ecb"),
            ("euro_area_financial_stress_ciss", "ecb"),
        ),
        "commodities": (
            ("energy_oil", "tushare"),
            ("industrial_metal_copper", "tushare"),
            ("gold_spot", "tushare"),
            ("agriculture_food_index", "tushare"),
        ),
        "institutional_flow": (("market_flow_all_share", "tushare"),),
    }
    snapshot_dir = root / "macro_snapshots" / as_of.isoformat()
    for role, series in role_series.items():
        _write_json(
            snapshot_dir / f"{role}.json",
            {
                "schema_version": "macro_role_snapshot_v2",
                "role": role,
                "as_of_date": as_of.isoformat(),
                "observations": [
                    _macro_observation(
                        series_id=series_id,
                        source=source,
                        as_of=as_of,
                        ordinal=ordinal,
                    )
                    for ordinal, (series_id, source) in enumerate(series, start=1)
                ],
                "events": [],
                "fixture_class": "SYNTHETIC_NON_PRODUCTION",
            },
        )


def _build_economic_calendar(root: Path, as_of: date) -> None:
    compact_date = as_of.strftime("%Y%m%d")

    def fetch(**request: str) -> list[dict[str, str]]:
        values = {
            "date": compact_date,
            "time": "09:30",
            "currency": request["currency"],
            "country": "economic_activity",
            "event": f"{as_of.year}年{as_of.month:02d}月 synthetic industrial production",
            "value": "101.2",
            "pre_value": "100.7",
            "fore_value": "100.9",
        }
        return [{column: values[column] for column in ECO_CAL_EXPECTED_COLUMNS}]

    collect_eco_calendar(
        fetch,
        start_date=as_of.isoformat(),
        end_date=as_of.isoformat(),
        retrieved_at=f"{as_of.isoformat()}T10:00:00+08:00",
        store=EconomicCalendarStore(root / "economic_calendar" / "eco_cal.sqlite3"),
        currencies=ECO_CAL_REGISTERED_CURRENCIES,
    )


def _ready_geopolitical_manifest(as_of: date) -> dict[str, Any]:
    payload = copy.deepcopy(GEOPOLITICAL_INITIAL_SOURCE_MANIFEST)
    started = as_of - timedelta(days=30)
    for row in payload["registrations"]:
        if row["source_id"] not in REQUIRED_SOURCE_IDS:
            continue
        row["registration_status"] = "ACTIVE_VERIFIED"
        row["preflight"] = {
            **row["preflight"],
            "status": "READY",
            "observed_continuous_days": 30,
            "window_started_at": f"{started.isoformat()}T00:00:00Z",
            "window_completed_at": f"{as_of.isoformat()}T00:00:00Z",
            "availability_ratio": 0.999,
            "p95_capture_lag_minutes": 12.0,
            "schema_verified": True,
            "pagination_verified": True,
            "publication_time_verified": True,
            "license_verified": True,
            "evidence_id": f"structured-smoke:geo-preflight:{row['source_id']}",
        }
    for route in payload["coverage_routes"]:
        if route["applicability"] != "APPLICABLE":
            continue
        route["route_status"] = "ACTIVE_VERIFIED"
        route["coverage_route_hash"] = _canonical_hash(
            {key: value for key, value in route.items() if key != "coverage_route_hash"}
        )
    payload["manifest_readiness"] = "READY"
    payload["readiness_blockers"] = []
    payload["coverage_scope_hash"] = _canonical_hash(
        {
            "coverage_scope_version": payload["coverage_scope_version"],
            "watchlist_actor_ids": payload["watchlist_actor_ids"],
            "watchlist_region_ids": payload["watchlist_region_ids"],
            "coverage_routes": payload["coverage_routes"],
        }
    )
    payload["manifest_hash"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "manifest_hash"}
    )
    return validate_geopolitical_manifest(payload)


def _build_geopolitical_cache(root: Path, as_of: date) -> Path:
    target = root / "geopolitical_events"
    manifest = _ready_geopolitical_manifest(as_of)
    manifest_path = target / "structured_smoke_ready_manifest.json"
    _write_json(manifest_path, manifest)
    store = GeopoliticalEventStore(target / "events.sqlite3")
    adapters = {row["source_id"]: row for row in manifest["adapter_contracts"]}
    ordinal = 0
    for route in manifest["coverage_routes"]:
        if route["applicability"] != "APPLICABLE":
            continue
        for source_id in route["required_source_ids"]:
            ordinal += 1
            adapter = adapters[source_id]
            query_hash = scope_query_hash(route, adapter)
            query_key = coverage_query_key(route, source_id, query_hash)
            store.append_poll_observation(
                {
                    "observation_id": f"structured-smoke-poll-{ordinal:05d}",
                    "coverage_route_id": route["coverage_route_id"],
                    "coverage_route_hash": route["coverage_route_hash"],
                    "source_id": source_id,
                    "scope_query_hash": query_hash,
                    "coverage_query_key": query_key,
                    "poll_started_at": f"{as_of.isoformat()}T15:44:00Z",
                    "poll_completed_at": f"{as_of.isoformat()}T15:45:00Z",
                    "http_status": 200,
                    "row_count": 0,
                    "pagination_complete": True,
                    "truncated": False,
                    "schema_hash": adapter["expected_response_schema_hash"],
                    "response_content_hash": _canonical_hash(
                        {"query": query_key, "rows": []}
                    ),
                    "parse_result": "SUCCESS",
                    "error_class": None,
                    "coverage_evidence_id": f"structured-smoke:geo-coverage:{query_key}",
                },
                manifest=manifest,
            )
    return manifest_path


def _business_days_ending(as_of: date, count: int) -> list[date]:
    days: list[date] = []
    current = as_of
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current -= timedelta(days=1)
    return sorted(days)


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_market_breadth(root: Path, as_of: date) -> None:
    target = root / "market_breadth"
    trading_days = _business_days_ending(as_of, 320)
    tickers = [f"{index:06d}.SZ" for index in range(1, 41)]
    _write_csv(
        target / "stock_basic.csv",
        ("ts_code", "list_date", "delist_date"),
        [
            {
                "ts_code": ticker,
                "list_date": (trading_days[0] - timedelta(days=365)).strftime("%Y%m%d"),
                "delist_date": "",
            }
            for ticker in tickers
        ],
    )
    daily_rows: list[dict[str, Any]] = []
    factor_rows: list[dict[str, Any]] = []
    prices = {ticker: 8.0 + index * 0.15 for index, ticker in enumerate(tickers)}
    for day_index, trading_day in enumerate(trading_days):
        for ticker_index, ticker in enumerate(tickers):
            pre_close = prices[ticker]
            daily_return = ((ticker_index % 9) - 4) * 0.0008 + ((day_index % 7) - 3) * 0.0004
            close = max(1.0, pre_close * (1.0 + daily_return))
            prices[ticker] = close
            daily_rows.append(
                {
                    "ts_code": ticker,
                    "trade_date": trading_day.strftime("%Y%m%d"),
                    "close": f"{close:.6f}",
                    "pre_close": f"{pre_close:.6f}",
                    "amount": f"{1_000_000 + ticker_index * 17_000 + day_index * 1_300:.2f}",
                }
            )
            factor_rows.append(
                {
                    "ts_code": ticker,
                    "trade_date": trading_day.strftime("%Y%m%d"),
                    "adj_factor": "1.0",
                }
            )
    _write_csv(
        target / "daily.csv",
        ("ts_code", "trade_date", "close", "pre_close", "amount"),
        daily_rows,
    )
    _write_csv(
        target / "adj_factor.csv",
        ("ts_code", "trade_date", "adj_factor"),
        factor_rows,
    )


def _build_sector_snapshots(root: Path, as_of: date) -> None:
    target = root / "sector_snapshots" / as_of.isoformat()
    for agent_id, direction_ids in SECTOR_DIRECTION_IDS.items():
        cards = []
        evidence_catalog = []
        for ordinal, direction_id in enumerate(direction_ids, start=1):
            evidence_id = f"structured-smoke:sector:{agent_id}:{direction_id}"
            cards.append(
                {
                    "direction_id": direction_id,
                    "fundamentals": {"score": round(0.35 + ordinal * 0.03, 4)},
                    "valuation": {"score": round(0.55 - ordinal * 0.02, 4)},
                    "basket_technicals": {"score": round(0.45 + ordinal * 0.01, 4)},
                    "risk_asymmetry": {"score": round(0.50 - ordinal * 0.01, 4)},
                    "etf_price_confirmation": {"state": "MIXED", "return_20d": 0.0},
                    "etf_share_flow_confirmation": {"state": "MIXED", "change_20d": 0.0},
                    "evidence_ids": [evidence_id],
                }
            )
            evidence_catalog.append(
                {
                    "evidence_id": evidence_id,
                    "source": "synthetic_structured_smoke",
                    "as_of": as_of.isoformat(),
                }
            )
        _write_json(
            target / f"{agent_id}.json",
            {
                "schema_version": SECTOR_SNAPSHOT_SCHEMA_VERSION,
                "sector_agent_id": agent_id,
                "as_of_date": as_of.isoformat(),
                "direction_contract_version": SECTOR_DIRECTION_CONTRACT_VERSION,
                "direction_ids": list(direction_ids),
                "direction_cards": cards,
                "eligible_security_universe": [],
                "evidence_catalog": evidence_catalog,
                "fixture_class": "SYNTHETIC_NON_PRODUCTION",
            },
        )
    _write_json(
        target / "relationship_mapper.json",
        {
            "schema_version": RELATIONSHIP_SNAPSHOT_SCHEMA_VERSION,
            "as_of_date": as_of.isoformat(),
            "frozen_security_domain_hash": _canonical_hash([]),
            "relationships": [
                {
                    "edge_candidate_id": "structured-smoke-edge-1",
                    "source_entity": "energy",
                    "target_entity": "industrials",
                    "edge_type": "INPUT_COST",
                    "activation_trigger": "synthetic smoke trigger",
                    "evidence_ids": ["structured-smoke:relationship:1"],
                }
            ],
            "prediction_opportunity_set": {
                "candidate_generation_contract_version": "relationship_candidate_generation_v1",
                "scoring_contract_version": "relationship_graph_validation_20d_v1",
                "ordered_opportunities": [
                    {
                        "edge_candidate_id": "structured-smoke-edge-1",
                        "source_entity": "energy",
                        "target_entity": "industrials",
                        "edge_type": "INPUT_COST",
                        "materiality_weight": 1.0,
                        "matched_non_edge_set_id": "structured-smoke-non-edge-1",
                        "matched_non_edge_set_hash": _canonical_hash(
                            ["structured-smoke-non-edge-1"]
                        ),
                    }
                ],
            },
            "evidence_catalog": [
                {
                    "evidence_id": "structured-smoke:relationship:1",
                    "source": "synthetic_structured_smoke",
                    "as_of": as_of.isoformat(),
                }
            ],
            "fixture_class": "SYNTHETIC_NON_PRODUCTION",
        },
    )


def _build_runtime_snapshots(root: Path, as_of: date) -> None:
    target = root / "runtime_snapshots" / as_of.isoformat()
    bindings = {
        "druckenmiller": (("druckenmiller", "get_superinvestor_candidate_snapshot"),),
        "munger": (("munger", "get_superinvestor_candidate_snapshot"),),
        "burry": (("burry", "get_superinvestor_candidate_snapshot"),),
        "ackman": (("ackman", "get_superinvestor_candidate_snapshot"),),
        "cro": (("cro", "get_cro_risk_snapshot"),),
        "alpha_discovery": (("alpha_discovery", "get_alpha_candidate_snapshot"),),
        "autonomous_execution": (("autonomous_execution", "get_execution_snapshot"),),
        "cio": (
            ("cio_proposal", "get_cio_decision_snapshot"),
            ("cio_final", "get_cio_decision_snapshot"),
        ),
    }
    for agent_id, stage_tools in bindings.items():
        for stage, tool_id in stage_tools:
            evidence_id = f"structured-smoke:runtime:{agent_id}:{stage}"
            _write_json(
                target / f"{agent_id}.{stage}.{tool_id}.json",
                {
                    "contract_version": "structured_smoke_runtime_snapshot_v1",
                    "agent_id": agent_id,
                    "stage": stage,
                    "as_of": as_of.isoformat(),
                    "fixture_class": "SYNTHETIC_NON_PRODUCTION",
                    "candidate_universe": [],
                    "constraints": {"cash_only": True, "allow_new_positions": False},
                    "evidence_catalog": [
                        {
                            "evidence_id": evidence_id,
                            "source": "synthetic_structured_smoke",
                            "as_of": as_of.isoformat(),
                        }
                    ],
                },
            )


def build_structured_smoke_fixtures(root: Path, as_of_date: str) -> dict[str, str]:
    as_of = date.fromisoformat(as_of_date)
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    _build_macro_snapshots(root, as_of)
    _build_economic_calendar(root, as_of)
    manifest_path = _build_geopolitical_cache(root, as_of)
    _build_market_breadth(root, as_of)
    _build_sector_snapshots(root, as_of)
    _build_runtime_snapshots(root, as_of)
    marker = {
        "schema_version": "structured_smoke_fixture_bundle_v1",
        "as_of_date": as_of_date,
        "fixture_class": "SYNTHETIC_NON_PRODUCTION",
        "contains_vendor_prose": False,
        "cache_root": str(root),
        "geopolitical_manifest": str(manifest_path),
    }
    marker["bundle_hash"] = _canonical_hash(marker)
    _write_json(root / "structured_smoke_fixture_bundle.json", marker)
    return {
        "MOSAIC_CACHE_DIR": str(root),
        "MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST": str(manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    bindings = build_structured_smoke_fixtures(args.root, args.date)
    print(json.dumps(bindings, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
