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
import shlex
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mosaic.bridge.tool_capabilities import (
    AGENTS_BY_LAYER,
    BOUND_RUNTIME_SNAPSHOT_CONTRACTS,
    STANDARD_SECTOR_AGENTS,
    SUPERINVESTOR_AGENTS,
)
from mosaic.dataflows.economic_calendar import (
    ECO_CAL_EXPECTED_COLUMNS,
    ECO_CAL_REGISTERED_CURRENCIES,
    ECO_CAL_REGISTERED_ROUTES,
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
from mosaic.dataflows.macro_source_contracts import (
    COMMODITY_CONTRACT_MAP,
    COMMODITY_FAMILY_CONTRACTS,
)
from mosaic.dataflows.macro_snapshots import (
    MACRO_EVENT_ROLES,
    validate_role_snapshot,
)
from mosaic.dataflows.market_breadth import render_market_breadth_snapshot
from mosaic.dataflows.outcome_runtime_inputs import (
    EVENT_COVERAGE_SCHEMA_VERSION,
    OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
)
from mosaic.dataflows.role_events import build_role_event_snapshot
from mosaic.dataflows.sector_snapshots import (
    RELATIONSHIP_SNAPSHOT_SCHEMA_VERSION,
    SECTOR_DIRECTION_CONTRACT_VERSION,
    SECTOR_DIRECTION_IDS,
    SECTOR_ETF_DIRECTION_AUTHORITY,
    SECTOR_SNAPSHOT_SCHEMA_VERSION,
    SECTOR_UNIVERSE_MANIFEST,
    _canonical_hash as _sector_canonical_hash,
)
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.opportunity_authority import macro_authority_members
from mosaic.scorecard.canonical_json import canonical_hash

_FIXTURE_ARTIFACT_ROOTS = (
    "economic_calendar",
    "geopolitical_events",
    "macro_snapshots",
    "market_breadth",
    "outcome_runtime",
    "runtime_snapshots",
    "sector_snapshots",
)


def _canonical_hash(payload: Any) -> str:
    return canonical_hash(payload)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fixture_artifact_inventory(root: Path) -> list[dict[str, str]]:
    inventory: list[dict[str, str]] = []
    for directory_name in _FIXTURE_ARTIFACT_ROOTS:
        directory = root / directory_name
        if not directory.is_dir() or directory.is_symlink():
            raise RuntimeError(
                f"structured-smoke fixture directory is invalid: {directory}"
            )
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise RuntimeError(
                    f"structured-smoke fixture cannot contain symlinks: {path}"
                )
            if path.is_dir():
                continue
            if not path.is_file():
                raise RuntimeError(
                    f"structured-smoke fixture must contain only regular files: {path}"
                )
            relative_path = path.relative_to(root).as_posix()
            inventory.append(
                {
                    "relative_path": relative_path,
                    "content_sha256": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
                }
            )
    return sorted(inventory, key=lambda row: row["relative_path"])


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


def _synthetic_commodity_conditions(as_of: date) -> dict[str, Any]:
    trade_date = as_of
    while trade_date.weekday() >= 5:
        trade_date -= timedelta(days=1)
    captured_at = (
        datetime.combine(
            trade_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        .replace(hour=6)
        .isoformat()
    )
    required_families = (
        family_id
        for component in COMMODITY_CONTRACT_MAP.values()
        for family_id in component["required_families"]
    )
    families: list[dict[str, Any]] = []
    for family_ordinal, family_id in enumerate(required_families, start=1):
        source = COMMODITY_FAMILY_CONTRACTS[family_id]
        delivery_dates = [
            (as_of + timedelta(days=offset)).replace(day=20) for offset in (60, 120)
        ]
        contracts: list[dict[str, Any]] = []
        for contract_ordinal, delivery_date in enumerate(delivery_dates, start=1):
            symbol = f"{source['product_code']}{delivery_date:%y%m}"
            evidence_key = f"{family_id}:{delivery_date:%Y-%m}"
            contracts.append(
                {
                    "ts_code": f"{symbol}.{source['ts_code_suffix']}",
                    "symbol": symbol,
                    "exchange": source["exchange"],
                    "name": f"synthetic {family_id} {delivery_date:%Y-%m}",
                    "fut_code": source["product_code"],
                    "multiplier": 1,
                    "trade_unit": "synthetic_contract",
                    "quote_unit": "synthetic_price",
                    "list_date": (as_of - timedelta(days=365)).isoformat(),
                    "delist_date": delivery_date.replace(day=15).isoformat(),
                    "delivery_month": delivery_date.strftime("%Y-%m"),
                    "last_delivery_date": delivery_date.isoformat(),
                    "trade_date": trade_date.isoformat(),
                    "settle": 100.0 + family_ordinal + contract_ordinal,
                    "volume": 1000.0 + contract_ordinal,
                    "open_interest": 2000.0 + contract_ordinal,
                    "metadata_released_at": captured_at,
                    "metadata_vintage_at": captured_at,
                    "price_released_at": captured_at,
                    "price_vintage_at": captured_at,
                    "metadata_source": source["contract_metadata_source"],
                    "price_source": source["daily_settlement_source"],
                    "pit_status": "AVAILABLE_AS_OF",
                    "metadata_evidence_id": (
                        f"structured-smoke:commodity:metadata:{evidence_key}"
                    ),
                    "price_evidence_id": (
                        f"structured-smoke:commodity:settlement:{evidence_key}"
                    ),
                }
            )
        families.append(
            {
                "family_id": family_id,
                "component": source["component"],
                "contracts": contracts,
                "inventory": {
                    "series_id": f"inventory_{family_id.replace('@', '_')}",
                    "family_id": family_id,
                    "observation_date": trade_date.isoformat(),
                    "released_at": captured_at,
                    "vintage_at": captured_at,
                    "actual": 1000.0 + family_ordinal,
                    "previous": 999.0 + family_ordinal,
                    "unit": "synthetic_inventory_unit",
                    "source": source["inventory_source"],
                    "pit_status": "AVAILABLE_AS_OF",
                    "evidence_id": (
                        f"structured-smoke:commodity:inventory:{family_id}:"
                        f"{trade_date.isoformat()}"
                    ),
                },
            }
        )
    return {
        "schema_version": "commodity_condition_inputs_v1",
        "as_of_date": as_of.isoformat(),
        "market_session_date": trade_date.isoformat(),
        "families": families,
    }


def _build_macro_snapshots(root: Path, as_of: date) -> None:
    role_series: dict[str, tuple[tuple[str, str], ...]] = {
        "china": (
            ("cn_gdp", "tushare.cn_gdp"),
            ("cn_cpi", "tushare.cn_cpi"),
            ("cn_credit", "official.pboc_tsfin_flow_stock"),
            ("cn_export", "official.customs_total_trade"),
            ("cn_fiscal", "official.mof_general_public_budget"),
        ),
        "us_economy": (
            ("GDPC1", "ALFRED"),
            ("CPIAUCSL", "ALFRED"),
            ("PAYEMS", "ALFRED"),
            ("RSAFS", "ALFRED"),
        ),
        "eu_economy": (
            ("eurostat_gdp", "eurostat.namq_10_gdp"),
            ("eurostat_hicp", "eurostat.prc_hicp_minr"),
            ("eurostat_employment", "eurostat.une_rt_m"),
            ("eurostat_retail", "eurostat.sts_trtu_m"),
        ),
        "central_bank": (
            ("pboc_policy_rate", "official.pboc_lpr_catalog"),
            ("domestic_liquidity_omo", "official.pboc_omo_catalog"),
            ("cn_curve_10y", "tushare.yc_cb_cn_government_10y"),
            ("credit_condition_spread", "official.pboc_tsfin_flow_stock"),
        ),
        "us_financial_conditions": (
            ("fed_balance_sheet", "official.fomc_statement"),
            ("us_curve_10y", "tushare.us_tycr_nominal_curve"),
            ("BAA10Y", "ALFRED"),
            ("DTWEXBGS", "ALFRED"),
        ),
        "euro_area_financial_conditions": (
            ("ecb_policy_rate", "official.ecb_decision_statement"),
            (
                "euro_area_curve_10y",
                "ecb.YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
            ),
            (
                "euro_area_bank_credit_growth",
                "ecb.BSI.M.U2.Y.U.A20T.A.I.U2.2240.Z01.A",
            ),
            (
                "euro_area_financial_stress_ciss",
                "ecb.CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX",
            ),
        ),
        "commodities": (
            ("energy_oil", "tushare.fut_daily.SC@INE"),
            ("industrial_metal_copper", "tushare.fut_daily.CU@SHFE"),
            ("gold_spot", "tushare.fut_daily.AU@SHFE"),
            ("agriculture_food_index", "tushare.fut_daily.C@DCE"),
        ),
        "institutional_flow": (
            ("market_flow_all_share", "tushare.moneyflow_hsgt"),
            ("sector_rotation_all_share", "tushare.moneyflow_ind_ths"),
            ("etf_share_all_share", "tushare.fund_share"),
            ("crowding_all_share", "tushare.daily_basic"),
        ),
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
                **(
                    {
                        "context_observations": [
                            _macro_observation(
                                series_id=series_id,
                                source=source,
                                as_of=as_of,
                                ordinal=ordinal,
                            )
                            for ordinal, (series_id, source) in enumerate(
                                (
                                    role_series["china"][:3]
                                    if role == "central_bank"
                                    else role_series[
                                        "us_economy"
                                        if role == "us_financial_conditions"
                                        else "eu_economy"
                                    ]
                                ),
                                start=101,
                            )
                        ]
                    }
                    if role
                    in {
                        "central_bank",
                        "us_financial_conditions",
                        "euro_area_financial_conditions",
                    }
                    else {}
                ),
                "events": [],
                **(
                    {"commodity_conditions": _synthetic_commodity_conditions(as_of)}
                    if role == "commodities"
                    else {}
                ),
                **(
                    {
                        "component_coverage": {
                            component: {
                                "eligible_count": 100,
                                "observed_count": 100,
                                "coverage_ratio": 1.0,
                            }
                            for component in (
                                "market_wide_flow",
                                "sector_rotation",
                                "etf_share",
                                "crowding",
                            )
                        }
                    }
                    if role == "institutional_flow"
                    else {}
                ),
                "fixture_class": "SYNTHETIC_NON_PRODUCTION",
            },
        )


def _build_economic_calendar(root: Path, as_of: date) -> None:
    compact_date = as_of.strftime("%Y%m%d")

    def fetch(**request: str) -> list[dict[str, str]]:
        currency_by_country = dict(
            (country, currency) for currency, country in ECO_CAL_REGISTERED_ROUTES
        )
        values = {
            "date": compact_date,
            "time": "09:30",
            "currency": currency_by_country[request["country"]],
            "country": request["country"],
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


def _nonproduction_geopolitical_manifest(as_of: date) -> dict[str, Any]:
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
    payload["manifest_readiness"] = "PREFLIGHT_REQUIRED"
    payload["readiness_blockers"] = [
        f"{source_id}:{reason}"
        for source_id in sorted(REQUIRED_SOURCE_IDS)
        for reason in (
            "source_specific_parser_missing",
            "continuous_preflight_receipt_verifier_missing",
        )
    ]
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
    manifest = _nonproduction_geopolitical_manifest(as_of)
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
                    "poll_started_at": f"{as_of.isoformat()}T06:44:00Z",
                    "poll_completed_at": f"{as_of.isoformat()}T06:45:00Z",
                    "http_status": 200,
                    "row_count": 0,
                    "pagination_complete": True,
                    "truncated": False,
                    "schema_hash": adapter["expected_response_schema_hash"],
                    "response_content_hash": _canonical_hash(
                        {"query": query_key, "rows": []}
                    ),
                    "ingestion_mode": "NON_PRODUCTION_CALLBACK",
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


def _write_csv(
    path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_market_breadth(root: Path, as_of: date) -> None:
    target = root / "market_breadth"
    trading_days = _business_days_ending(as_of, 320)
    # Structured smoke accepts any ISO date, including weekends used by the
    # bridge protocol suite. Keep the bundle explicitly synthetic while giving
    # its PIT snapshot an observation at the requested boundary.
    if trading_days[-1] != as_of:
        trading_days.append(as_of)
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
            daily_return = ((ticker_index % 9) - 4) * 0.0008 + (
                (day_index % 7) - 3
            ) * 0.0004
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
    released_at = (as_of - timedelta(days=1)).isoformat()
    in_date = (as_of - timedelta(days=365)).isoformat()
    metric_contracts = SECTOR_UNIVERSE_MANIFEST["direction_metric_registry"]
    plans = {
        row["sector_agent_id"]: row
        for row in SECTOR_UNIVERSE_MANIFEST["membership_query_plans"]
    }
    direction_contracts = {
        (row["sector_agent_id"], row["direction_id"]): row
        for row in SECTOR_UNIVERSE_MANIFEST["direction_contracts"]
    }
    ticker_ordinal = 0
    for agent_id, direction_ids in SECTOR_DIRECTION_IDS.items():
        plan = plans[agent_id]
        code_levels = {
            branch["classification_code"]: branch["parameter"]
            for branch in plan["branches"]
        }
        universe = []
        evidence_catalog = []
        for direction_id in direction_ids:
            ticker_ordinal += 1
            contract = direction_contracts[(agent_id, direction_id)]
            classification_code = contract["included_classification_codes"][0]
            classification_field = code_levels[classification_code]
            evidence_id = f"structured-smoke:sector:{agent_id}:{direction_id}"
            evidence = {
                "evidence_id": evidence_id,
                "evidence_kind": "SYNTHETIC_PIT_DIRECTION",
                "source_id": "synthetic_structured_smoke",
                "source_endpoint": "synthetic_sector_fixture",
                "observation_date": released_at,
                "released_at": released_at,
                "vintage_at": released_at,
                "pit_status": "PIT_VERIFIED",
                "content_hash": _sector_canonical_hash(
                    {
                        "agent_id": agent_id,
                        "direction_id": direction_id,
                        "as_of": as_of.isoformat(),
                    }
                ),
            }
            evidence["evidence_record_hash"] = _sector_canonical_hash(evidence)
            evidence_catalog.append(evidence)
            security = {
                "ts_code": f"{600000 + ticker_ordinal:06d}.SH",
                "direction_id": direction_id,
                "l1_code": None,
                "l2_code": None,
                "l3_code": None,
                "in_date": in_date,
                "out_date": None,
                "released_at": released_at,
                "vintage_at": released_at,
                "pit_status": "PIT_VERIFIED",
                "evidence_ids": [evidence_id],
            }
            security[classification_field] = classification_code
            security["membership_row_hash"] = _sector_canonical_hash(security)
            universe.append(security)
        universe.sort(key=lambda row: (row["direction_id"], row["ts_code"]))
        security_scoring_rows = []
        for security_ordinal, security in enumerate(universe, start=1):
            scoring_row = {
                "ts_code": security["ts_code"],
                "direction_id": security["direction_id"],
                "availability_status": "AVAILABLE",
                "unavailability_reason": None,
                "observation_date": released_at,
                "released_at": released_at,
                "vintage_at": released_at,
                "pit_status": "PIT_VERIFIED",
                "adjusted_return_20d": (
                    1e-7 if security_ordinal == 1 else round(0.01 * security_ordinal, 6)
                ),
                "realized_volatility_20d": round(0.12 + 0.005 * security_ordinal, 6),
                "median_amount_20d_cny": float(100_000_000 - security_ordinal * 10_000),
                "net_moneyflow_20d_cny": float(1_000_000 + security_ordinal * 10_000),
                "observation_count": 20,
                "required_observation_count": 20,
                "coverage_ratio": 1.0,
                "evidence_ids": [
                    f"structured-smoke:sector:{agent_id}:{security['direction_id']}"
                ],
            }
            scoring_row["security_scoring_row_hash"] = _sector_canonical_hash(
                scoring_row
            )
            security_scoring_rows.append(scoring_row)
        cards = []
        for ordinal, direction_id in enumerate(direction_ids, start=1):
            contract = direction_contracts[(agent_id, direction_id)]
            evidence_id = f"structured-smoke:sector:{agent_id}:{direction_id}"
            members = [row for row in universe if row["direction_id"] == direction_id]
            etf_family = {
                "etf_family_id": f"sector-etf:{agent_id}:{direction_id}",
                "direction_id": direction_id,
                "etf_ts_codes": [],
                "selection_date": as_of.isoformat(),
                "released_at": as_of.isoformat(),
                "vintage_at": as_of.isoformat(),
                "pit_status": "PIT_VERIFIED",
                "direction_authority_version": SECTOR_ETF_DIRECTION_AUTHORITY[
                    "authority_version"
                ],
                "direction_authority_hash": SECTOR_ETF_DIRECTION_AUTHORITY[
                    "authority_hash"
                ],
                "direction_authority_effective_from": SECTOR_ETF_DIRECTION_AUTHORITY[
                    "effective_from"
                ],
                "direction_authority_effective_to": SECTOR_ETF_DIRECTION_AUTHORITY[
                    "effective_to"
                ],
                "evidence_ids": [evidence_id],
            }
            etf_family["etf_family_hash"] = _sector_canonical_hash(etf_family)
            metrics = []
            for metric_contract in metric_contracts:
                is_etf = metric_contract["metric_family"] == "ETF_CONFIRMATION"
                metric = {
                    **metric_contract,
                    "direction_id": direction_id,
                    "availability_status": "UNAVAILABLE" if is_etf else "AVAILABLE",
                    "observation_date": as_of.isoformat() if is_etf else released_at,
                    "released_at": as_of.isoformat() if is_etf else released_at,
                    "vintage_at": as_of.isoformat() if is_etf else released_at,
                    "pit_status": "PIT_VERIFIED",
                    "value": None if is_etf else round(0.25 + ordinal * 0.01, 4),
                    "observation_count": (
                        0 if is_etf else metric_contract["minimum_observations"]
                    ),
                    "eligible_count": 0 if is_etf else len(members),
                    "observed_count": 0 if is_etf else len(members),
                    "coverage_ratio": 0.0 if is_etf else 1.0,
                    "etf_family_id": etf_family["etf_family_id"] if is_etf else None,
                    "etf_family_hash": etf_family["etf_family_hash"]
                    if is_etf
                    else None,
                    "evidence_ids": [evidence_id],
                }
                metric["metric_observation_hash"] = _sector_canonical_hash(metric)
                metrics.append(metric)
            card = {
                "direction_id": direction_id,
                "direction_contract_hash": contract["direction_contract_hash"],
                "membership_query_plan_id": plan["query_plan_id"],
                "membership_query_plan_hash": plan["query_plan_hash"],
                "eligible_count": len(members),
                "membership_hash": _sector_canonical_hash(members),
                "readiness_status": "READY",
                "etf_family": etf_family,
                "metrics": metrics,
                "evidence_ids": [evidence_id],
            }
            card["direction_card_hash"] = _sector_canonical_hash(card)
            cards.append(card)
        snapshot = {
            "schema_version": SECTOR_SNAPSHOT_SCHEMA_VERSION,
            "fixture_class": "SYNTHETIC_NON_PRODUCTION",
            "sector_universe_manifest_hash": SECTOR_UNIVERSE_MANIFEST["manifest_hash"],
            "sector_agent_id": agent_id,
            "as_of_date": as_of.isoformat(),
            "direction_contract_version": SECTOR_DIRECTION_CONTRACT_VERSION,
            "direction_metric_registry_version": SECTOR_UNIVERSE_MANIFEST[
                "direction_metric_registry_version"
            ],
            "direction_metric_registry_hash": SECTOR_UNIVERSE_MANIFEST[
                "direction_metric_registry_hash"
            ],
            "membership_query_plan_id": plan["query_plan_id"],
            "membership_query_plan_version": plan["query_plan_version"],
            "membership_query_plan_hash": plan["query_plan_hash"],
            "membership_pit_status": "PIT_VERIFIED",
            "membership_observed_at": released_at,
            "direction_ids": list(direction_ids),
            "direction_cards": cards,
            "eligible_security_universe": universe,
            "eligible_count": len(universe),
            "membership_hash": _sector_canonical_hash(universe),
            "security_scoring_contract_version": SECTOR_UNIVERSE_MANIFEST[
                "security_scoring_contract"
            ]["scoring_contract_version"],
            "security_scoring_contract_hash": SECTOR_UNIVERSE_MANIFEST[
                "security_scoring_contract"
            ]["scoring_contract_hash"],
            "security_scoring_rows": security_scoring_rows,
            "security_scoring_rows_hash": _sector_canonical_hash(security_scoring_rows),
            "evidence_catalog": sorted(
                evidence_catalog, key=lambda row: row["evidence_id"]
            ),
        }
        snapshot["snapshot_hash"] = _sector_canonical_hash(snapshot)
        _write_json(target / f"{agent_id}.json", snapshot)
    relationship_evidence = {
        "evidence_id": "structured-smoke:relationship:1",
        "evidence_kind": "SYNTHETIC_RELATIONSHIP_RECORD",
        "source_id": "synthetic_structured_smoke",
        "source_endpoint": "synthetic_relationship_fixture",
        "observation_date": released_at,
        "released_at": released_at,
        "vintage_at": released_at,
        "pit_status": "PIT_VERIFIED",
        "content_hash": _sector_canonical_hash(
            {"fixture": "relationship-source-batch"}
        ),
    }
    relationship_evidence["evidence_record_hash"] = _sector_canonical_hash(
        relationship_evidence
    )
    relationship_row = {
        "edge_candidate_id": "structured-smoke-edge-1",
        "source_entity": "synthetic-holder",
        "source_entity_type": "HOLDER",
        "target_entity": "000001.SZ",
        "target_entity_type": "PIT_ELIGIBLE_SECURITY",
        "target_sector_id": "sector-energy",
        "edge_type": "SHAREHOLDING",
        "activation_trigger": "synthetic smoke trigger",
        "observation_date": released_at,
        "released_at": released_at,
        "vintage_at": released_at,
        "pit_status": "PIT_VERIFIED",
        "evidence_ids": [relationship_evidence["evidence_id"]],
    }
    relationship_row["relationship_row_hash"] = _sector_canonical_hash(relationship_row)
    matched_non_edges = [
        {
            "source_entity": "synthetic-holder",
            "source_entity_type": "HOLDER",
            "target_entity": "000002.SZ",
            "target_entity_type": "PIT_ELIGIBLE_SECURITY",
            "target_sector_id": "sector-energy",
            "edge_type": "SHAREHOLDING",
            "materiality_bucket": "MEDIUM",
        }
    ]
    relationship_snapshot = {
        "schema_version": RELATIONSHIP_SNAPSHOT_SCHEMA_VERSION,
        "as_of_date": as_of.isoformat(),
        "frozen_holder_domain_hash": _sector_canonical_hash(["synthetic-holder"]),
        "frozen_security_domain_hash": _sector_canonical_hash(
            ["000001.SZ", "000002.SZ"]
        ),
        "relationships": [relationship_row],
        "prediction_opportunity_set": {
            "candidate_generation_contract_version": "relationship_candidate_generation_v1",
            "scoring_contract_version": "relationship_graph_validation_20d_v1",
            "ordered_opportunities": [
                {
                    "edge_candidate_id": "structured-smoke-edge-1",
                    "source_entity": "synthetic-holder",
                    "source_entity_type": "HOLDER",
                    "target_entity": "000001.SZ",
                    "target_entity_type": "PIT_ELIGIBLE_SECURITY",
                    "target_sector_id": "sector-energy",
                    "edge_type": "SHAREHOLDING",
                    "materiality_weight": 1.0,
                    "materiality_bucket": "MEDIUM",
                    "matched_non_edge_set_id": "structured-smoke-non-edge-1",
                    "matched_non_edge_set_hash": _sector_canonical_hash(
                        matched_non_edges
                    ),
                    "matched_non_edges": matched_non_edges,
                }
            ],
        },
        "evidence_catalog": [relationship_evidence],
        "evidence_catalog_hash": _sector_canonical_hash([relationship_evidence]),
        "fixture_class": "SYNTHETIC_NON_PRODUCTION",
    }
    relationship_snapshot["snapshot_hash"] = _sector_canonical_hash(
        relationship_snapshot
    )
    _write_json(target / "relationship_mapper.json", relationship_snapshot)


def _structured_smoke_event_id(agent_id: str, as_of: date) -> str:
    return f"structured-smoke:event:{agent_id}:{as_of.isoformat()}"


def _build_outcome_event_coverage(root: Path, as_of: date) -> None:
    event_coverage: dict[str, dict[str, Any]] = {}
    for agent_id, contract in sorted(OUTCOME_CONTRACTS.items()):
        schedule = contract["sample_schedule"]
        if schedule["kind"] != "EVENT_TRIGGERED":
            continue
        event_id = _structured_smoke_event_id(agent_id, as_of)
        event_coverage[agent_id] = {
            "coverage_status": "COMPLETE",
            "coverage_evidence_ids": [
                f"structured-smoke:event-coverage:{agent_id}:{as_of.isoformat()}"
            ],
            "event_registry_version": schedule["event_registry_version"],
            "event_priority_version": schedule["event_priority_version"],
            "candidates": [
                {
                    "event_id": event_id,
                    "causal_dedupe_key": f"structured-smoke:causal:{event_id}",
                    "event_registry_version": schedule["event_registry_version"],
                    "event_priority_version": schedule["event_priority_version"],
                    "priority_rank": 0,
                    "published_at": f"{as_of.isoformat()}T14:58:00+08:00",
                    "source_evidence_ids": [
                        f"structured-smoke:event-evidence:{agent_id}:{as_of.isoformat()}"
                    ],
                    "pit_status": "VERIFIED",
                }
            ],
        }
    without_hash = {
        "schema_version": EVENT_COVERAGE_SCHEMA_VERSION,
        "as_of": f"{as_of.isoformat()}T15:00:00+08:00",
        "generated_at": f"{as_of.isoformat()}T14:59:00+08:00",
        "pit_status": "VERIFIED",
        "event_coverage": event_coverage,
    }
    _write_json(
        root / "outcome_runtime" / as_of.isoformat() / "event_coverage.json",
        {**without_hash, "snapshot_hash": _canonical_hash(without_hash)},
    )


def _synthetic_macro_authority_snapshot(
    root: Path,
    *,
    agent_id: str,
    as_of: date,
) -> dict[str, Any]:
    if agent_id == "geopolitical":
        return {
            "snapshot_hash": _canonical_hash(
                {
                    "fixture_class": "SYNTHETIC_NON_PRODUCTION",
                    "agent_id": agent_id,
                    "as_of": as_of.isoformat(),
                }
            )
        }
    if agent_id == "market_breadth":
        return json.loads(
            render_market_breadth_snapshot(
                as_of.isoformat(), root / "market_breadth"
            )
        )
    raw = json.loads(
        (root / "macro_snapshots" / as_of.isoformat() / f"{agent_id}.json")
        .read_text(encoding="utf-8")
    )
    snapshot = validate_role_snapshot(raw, agent_id, as_of.isoformat())
    if agent_id in MACRO_EVENT_ROLES:
        snapshot["role_event_snapshot"] = build_role_event_snapshot(
            agent_id,
            as_of.isoformat(),
            store=EconomicCalendarStore(
                root / "economic_calendar" / "eco_cal.sqlite3"
            ),
        )
        snapshot["snapshot_hash"] = _canonical_hash(
            {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
        )
    return snapshot


def _build_outcome_opportunity_projections(root: Path, as_of: date) -> None:
    """Build hash-bound L1-L3 denominators with the production member shapes."""
    as_of_timestamp = f"{as_of.isoformat()}T15:00:00+08:00"
    generated_at = f"{as_of.isoformat()}T14:59:00+08:00"
    target = root / "outcome_runtime" / as_of.isoformat() / "opportunities"
    scoring_contract = SECTOR_UNIVERSE_MANIFEST["security_scoring_contract"]
    shortlist_limit = scoring_contract["shortlist_maximum_size_per_direction"]

    for agent_id, contract in sorted(OUTCOME_CONTRACTS.items()):
        layer = contract["layer"]
        if layer == "DECISION":
            continue
        if contract["evaluation_object_type"] == "MACRO_TRANSMISSION":
            snapshot = _synthetic_macro_authority_snapshot(
                root, agent_id=agent_id, as_of=as_of
            )
            member_refs: list[dict[str, Any]] = macro_authority_members(
                agent_id=agent_id,
                snapshot=snapshot,
                schedule_slot={
                    "trigger_event": (
                        {"event_id": _structured_smoke_event_id(agent_id, as_of)}
                        if contract["sample_schedule"]["kind"]
                        == "EVENT_TRIGGERED"
                        else None
                    )
                },
            )
        elif contract["evaluation_object_type"] == "SECTOR_TILT_PICKS":
            snapshot = json.loads(
                (root / "sector_snapshots" / as_of.isoformat() / f"{agent_id}.json")
                .read_text(encoding="utf-8")
            )
            scoring_rows = snapshot["security_scoring_rows"]
            member_refs = []
            for direction_id in snapshot["direction_ids"]:
                rows = sorted(
                    (
                        row
                        for row in scoring_rows
                        if row["direction_id"] == direction_id
                        and row["availability_status"] == "AVAILABLE"
                    ),
                    key=lambda row: (-row["median_amount_20d_cny"], row["ts_code"]),
                )[:shortlist_limit]
                shortlist_hash = _canonical_hash(
                    {
                        "direction_id": direction_id,
                        "security_scoring_contract_version": scoring_contract[
                            "scoring_contract_version"
                        ],
                        "security_scoring_contract_hash": scoring_contract[
                            "scoring_contract_hash"
                        ],
                        "rows": rows,
                    }
                )
                member_refs.append(
                    {
                        "subindustry_id": direction_id,
                        "security_shortlist_id": (
                            f"sector-shortlist:{direction_id}:{shortlist_hash[-16:]}"
                        ),
                        "security_shortlist_hash": shortlist_hash,
                        "security_ts_codes": [row["ts_code"] for row in rows],
                    }
                )
        elif contract["evaluation_object_type"] == "RELATIONSHIP_EDGES":
            snapshot = json.loads(
                (
                    root
                    / "sector_snapshots"
                    / as_of.isoformat()
                    / "relationship_mapper.json"
                ).read_text(encoding="utf-8")
            )
            member_refs = [
                {
                    "edge_candidate_id": row["edge_candidate_id"],
                    "materiality_weight": row["materiality_weight"],
                }
                for row in snapshot["prediction_opportunity_set"][
                    "ordered_opportunities"
                ]
            ]
        elif contract["evaluation_object_type"] == "SUPERINVESTOR_PICKS":
            # The exact L2-derived candidate universe is unavailable until the
            # corresponding L3 stage boundary; this artifact proves readiness only.
            member_refs = []
        else:  # pragma: no cover - the public L1-L3 roster closes this branch
            raise RuntimeError(f"unsupported L1-L3 opportunity type for {agent_id}")

        source_evidence = {
            source_id: [f"structured-smoke:opportunity:{agent_id}:{source_id}"]
            for source_id in contract["required_source_ids"]
        }
        without_hash = {
            "schema_version": OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
            "agent_id": agent_id,
            "as_of": as_of_timestamp,
            "generated_at": generated_at,
            "pit_status": "VERIFIED",
            "projection_status": "AVAILABLE",
            "qualification_predicate_version": contract[
                "opportunity_set_contract_version"
            ],
            "member_refs": member_refs,
            "source_evidence_by_required_source_id": source_evidence,
            "error_codes": [],
        }
        _write_json(
            target / f"{agent_id}.json",
            {**without_hash, "snapshot_hash": _canonical_hash(without_hash)},
        )


def _runtime_accepted_ref(
    *, agent_id: str, stage: str, accepted_output_kind: str, as_of: date
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = {
        "agent_id": agent_id,
        "stage": stage,
        "accepted_output_kind": accepted_output_kind,
        "as_of": as_of.isoformat(),
    }
    accepted_output_id = f"structured-smoke:accepted:{agent_id}:{stage}"
    accepted_output_hash = _canonical_hash(identity)
    evidence_id = f"structured-smoke:evidence:{agent_id}:{stage}"
    return (
        {
            "accepted_output_id": accepted_output_id,
            "accepted_output_hash": accepted_output_hash,
            "accepted_output_kind": accepted_output_kind,
            "agent_id": agent_id,
            "stage": stage,
            "as_of": as_of.isoformat(),
            "evidence_ids": [evidence_id],
        },
        {
            "evidence_id": evidence_id,
            "source_kind": "ACCEPTED_OUTPUT",
            "source_id": accepted_output_id,
            "metric": "accepted_output",
            "value": accepted_output_kind,
            "unit": "state",
            "as_of": as_of.isoformat(),
            "available_at": f"{as_of.isoformat()}T07:00:00Z",
            "source_fingerprint": accepted_output_hash,
        },
    )


def _runtime_control_source(ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_status": "ACCEPTED_OUTPUT",
        "agent_id": ref["agent_id"],
        "accepted_output_kind": ref["accepted_output_kind"],
        "accepted_output_id": ref["accepted_output_id"],
        "accepted_output_hash": ref["accepted_output_hash"],
        "stage_skip_id": None,
        "stage_skip_hash": None,
    }


def _runtime_skipped_control_source(
    *, agent_id: str, accepted_output_kind: str, as_of: date
) -> dict[str, Any]:
    stage_skip_id = f"structured-smoke:stage-skip:{agent_id}:{as_of.isoformat()}"
    return {
        "source_status": "NO_EVALUATION_OBJECT",
        "agent_id": agent_id,
        "accepted_output_kind": accepted_output_kind,
        "accepted_output_id": None,
        "accepted_output_hash": None,
        "stage_skip_id": stage_skip_id,
        "stage_skip_hash": _canonical_hash(
            {"stage_skip_id": stage_skip_id, "as_of": as_of.isoformat()}
        ),
    }


def _runtime_snapshot(
    *,
    agent_id: str,
    stage: str,
    tool_id: str,
    as_of: date,
    upstream: tuple[tuple[dict[str, Any], dict[str, Any]], ...],
    constraints: dict[str, Any],
    role_context: dict[str, Any],
) -> dict[str, Any]:
    contract = BOUND_RUNTIME_SNAPSHOT_CONTRACTS[tool_id]
    refs = [ref for ref, _evidence in upstream]
    evidence = [row for _ref, row in upstream]
    evidence_ids = [row["evidence_id"] for row in evidence]
    constraints = {**constraints, "evidence_ids": evidence_ids}
    role_context = {**role_context, "evidence_ids": evidence_ids}
    candidate_universe: list[dict[str, Any]] = []
    candidate_status = "EMPTY_CONFIRMED"
    candidate_universe_hash = _canonical_hash(
        {
            "candidate_status": candidate_status,
            "candidate_universe": candidate_universe,
        }
    )
    candidate_universe_id = f"structured-smoke:candidates:{agent_id}:{stage}"
    constraint_set_id = f"structured-smoke:constraints:{agent_id}:{stage}"
    constraint_set_hash = _canonical_hash(constraints)
    candidate_scope = {
        "candidate_universe_id": candidate_universe_id,
        "candidate_universe_hash": candidate_universe_hash,
        "constraint_set_id": constraint_set_id,
        "constraint_set_hash": constraint_set_hash,
    }
    snapshot = {
        "schema_version": contract,
        "contract_version": contract,
        "snapshot_id": f"structured-smoke:snapshot:{agent_id}:{stage}",
        "snapshot_hash": "",
        "graph_run_id": "standalone_tool_materialization",
        "agent_id": agent_id,
        "stage": stage,
        "as_of": as_of.isoformat(),
        "generated_at": f"{as_of.isoformat()}T07:00:00Z",
        "pit_status": "VERIFIED",
        "candidate_scope": candidate_scope,
        "candidate_scope_hash": _canonical_hash(candidate_scope),
        "candidate_universe_id": candidate_universe_id,
        "candidate_universe_hash": candidate_universe_hash,
        "candidate_status": candidate_status,
        "candidate_universe": candidate_universe,
        "constraint_set_id": constraint_set_id,
        "constraint_set_hash": constraint_set_hash,
        "constraints": constraints,
        "role_context": role_context,
        "role_context_hash": _canonical_hash(role_context),
        "upstream_accepted_output_refs": refs,
        "evidence_ledger": evidence,
    }
    snapshot["snapshot_hash"] = _canonical_hash(
        {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    )
    return snapshot


def _build_runtime_snapshots(root: Path, as_of: date) -> None:
    target = root / "runtime_snapshots" / as_of.isoformat()
    macro = tuple(
        _runtime_accepted_ref(
            agent_id=agent_id,
            stage=agent_id,
            accepted_output_kind="MACRO_TRANSMISSION",
            as_of=as_of,
        )
        for agent_id in AGENTS_BY_LAYER["macro"]
    )
    sector = tuple(
        _runtime_accepted_ref(
            agent_id=agent_id,
            stage=agent_id,
            accepted_output_kind="STANDARD_SECTOR_SELECTION",
            as_of=as_of,
        )
        for agent_id in STANDARD_SECTOR_AGENTS
    )
    relationship = _runtime_accepted_ref(
        agent_id="relationship_mapper",
        stage="relationship_mapper",
        accepted_output_kind="RELATIONSHIP_GRAPH",
        as_of=as_of,
    )
    superinvestors = tuple(
        _runtime_accepted_ref(
            agent_id=agent_id,
            stage=agent_id,
            accepted_output_kind="SUPERINVESTOR_SELECTION",
            as_of=as_of,
        )
        for agent_id in SUPERINVESTOR_AGENTS
    )
    cio_proposal = _runtime_accepted_ref(
        agent_id="cio",
        stage="cio_proposal",
        accepted_output_kind="CIO_PROPOSAL",
        as_of=as_of,
    )
    cro = _runtime_accepted_ref(
        agent_id="cro",
        stage="cro",
        accepted_output_kind="CRO_RISK_REVIEW",
        as_of=as_of,
    )
    alpha = _runtime_accepted_ref(
        agent_id="alpha_discovery",
        stage="alpha_discovery",
        accepted_output_kind="ALPHA_DISCOVERY",
        as_of=as_of,
    )

    snapshots: list[tuple[str, str, str, dict[str, Any]]] = []
    for agent_id in SUPERINVESTOR_AGENTS:
        snapshots.append(
            (
                agent_id,
                agent_id,
                "get_superinvestor_candidate_snapshot",
                _runtime_snapshot(
                    agent_id=agent_id,
                    stage=agent_id,
                    tool_id="get_superinvestor_candidate_snapshot",
                    as_of=as_of,
                    upstream=(*macro, *sector, relationship),
                    constraints={
                        "cash_only": True,
                        "allow_new_positions": False,
                        "max_pick_count": 3,
                        "max_total_conviction": 1.0,
                        "prohibited_ts_codes": [],
                    },
                    role_context={
                        "context_kind": "SUPERINVESTOR_CANDIDATE_SELECTION",
                        "candidate_origin_set_id": "structured-smoke:sector-origins",
                        "candidate_origin_set_hash": _canonical_hash([]),
                    },
                ),
            )
        )

    snapshots.extend(
        (
            (
                "alpha_discovery",
                "alpha_discovery",
                "get_alpha_candidate_snapshot",
                _runtime_snapshot(
                    agent_id="alpha_discovery",
                    stage="alpha_discovery",
                    tool_id="get_alpha_candidate_snapshot",
                    as_of=as_of,
                    upstream=(*sector, relationship, *superinvestors),
                    constraints={
                        "cash_only": True,
                        "allow_new_positions": False,
                        "max_novel_pick_count": 5,
                        "excluded_selected_ts_codes": [],
                    },
                    role_context={
                        "context_kind": "ALPHA_NOVELTY_SEARCH",
                        "superinvestor_selection_set_id": (
                            "structured-smoke:superinvestor-selections"
                        ),
                        "superinvestor_selection_set_hash": _canonical_hash(
                            [ref[0]["accepted_output_id"] for ref in superinvestors]
                        ),
                        "excluded_security_set_id": (
                            "structured-smoke:excluded-securities"
                        ),
                        "excluded_security_set_hash": _canonical_hash([]),
                    },
                ),
            ),
            (
                "cro",
                "cro",
                "get_cro_risk_snapshot",
                _runtime_snapshot(
                    agent_id="cro",
                    stage="cro",
                    tool_id="get_cro_risk_snapshot",
                    as_of=as_of,
                    upstream=(cio_proposal,),
                    constraints={
                        "max_total_target_weight": 1.0,
                        "max_single_name_weight": 0.1,
                        "max_sector_weight": 0.3,
                        "restricted_ts_codes": [],
                    },
                    role_context={
                        "context_kind": "CRO_PROPOSAL_RISK_REVIEW",
                        "proposal_accepted_output_id": cio_proposal[0][
                            "accepted_output_id"
                        ],
                        "proposal_accepted_output_hash": cio_proposal[0][
                            "accepted_output_hash"
                        ],
                        "position_snapshot_id": "structured-smoke:positions",
                        "position_snapshot_hash": _canonical_hash([]),
                        "portfolio_exposure_snapshot_id": (
                            "structured-smoke:portfolio-exposure"
                        ),
                        "portfolio_exposure_snapshot_hash": _canonical_hash({}),
                    },
                ),
            ),
            (
                "autonomous_execution",
                "autonomous_execution",
                "get_execution_snapshot",
                _runtime_snapshot(
                    agent_id="autonomous_execution",
                    stage="autonomous_execution",
                    tool_id="get_execution_snapshot",
                    as_of=as_of,
                    upstream=(cio_proposal, cro),
                    constraints={
                        "execution_mode": "PAPER",
                        "max_slippage_bps": 50.0,
                        "max_participation_rate": 0.1,
                        "min_trade_weight": 0.001,
                        "max_slice_count": 10,
                        "prohibited_ts_codes": [],
                    },
                    role_context={
                        "context_kind": "EXECUTION_ORDER_FEASIBILITY",
                        "proposal_accepted_output_id": cio_proposal[0][
                            "accepted_output_id"
                        ],
                        "proposal_accepted_output_hash": cio_proposal[0][
                            "accepted_output_hash"
                        ],
                        "cro_control_source": _runtime_control_source(cro[0]),
                        "order_intent_set_id": "structured-smoke:order-intents",
                        "order_intent_set_hash": _canonical_hash([]),
                        "liquidity_vintage_hash": _canonical_hash(
                            {"as_of": as_of.isoformat()}
                        ),
                    },
                ),
            ),
            (
                "cio",
                "cio_proposal",
                "get_cio_decision_snapshot",
                _runtime_snapshot(
                    agent_id="cio",
                    stage="cio_proposal",
                    tool_id="get_cio_decision_snapshot",
                    as_of=as_of,
                    upstream=(*macro, *sector, relationship, *superinvestors, alpha),
                    constraints={
                        "max_total_target_weight": 1.0,
                        "min_cash_weight": 0.0,
                        "max_single_name_weight": 0.1,
                        "restricted_ts_codes": [],
                    },
                    role_context={
                        "context_kind": "CIO_PORTFOLIO_DECISION",
                        "decision_stage": "PROPOSAL",
                        "position_snapshot_id": "structured-smoke:positions",
                        "position_snapshot_hash": _canonical_hash([]),
                        "previous_target_id": None,
                        "previous_target_hash": None,
                    },
                ),
            ),
            (
                "cio",
                "cio_final",
                "get_cio_decision_snapshot",
                _runtime_snapshot(
                    agent_id="cio",
                    stage="cio_final",
                    tool_id="get_cio_decision_snapshot",
                    as_of=as_of,
                    upstream=(cio_proposal,),
                    constraints={
                        "max_total_target_weight": 1.0,
                        "min_cash_weight": 0.0,
                        "max_single_name_weight": 0.1,
                        "restricted_ts_codes": [],
                    },
                    role_context={
                        "context_kind": "CIO_PORTFOLIO_DECISION",
                        "decision_stage": "FINAL",
                        "proposal_accepted_output_id": cio_proposal[0][
                            "accepted_output_id"
                        ],
                        "proposal_accepted_output_hash": cio_proposal[0][
                            "accepted_output_hash"
                        ],
                        "cro_control_source": _runtime_skipped_control_source(
                            agent_id="cro",
                            accepted_output_kind="CRO_RISK_REVIEW",
                            as_of=as_of,
                        ),
                        "execution_control_source": _runtime_skipped_control_source(
                            agent_id="autonomous_execution",
                            accepted_output_kind="EXECUTION_ASSESSMENT",
                            as_of=as_of,
                        ),
                    },
                ),
            ),
        )
    )
    for agent_id, stage, tool_id, snapshot in snapshots:
        _write_json(target / f"{agent_id}.{stage}.{tool_id}.json", snapshot)


def build_structured_smoke_fixtures(root: Path, as_of_date: str) -> dict[str, str]:
    as_of = date.fromisoformat(as_of_date)
    requested_root = root.expanduser()
    if requested_root.is_symlink():
        raise RuntimeError("structured-smoke fixture root cannot be a symlink")
    root = requested_root.resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise RuntimeError(
            "structured-smoke fixture root must be a fresh empty directory"
        )
    root.mkdir(parents=True, exist_ok=True)
    _build_macro_snapshots(root, as_of)
    _build_economic_calendar(root, as_of)
    manifest_path = _build_geopolitical_cache(root, as_of)
    _build_market_breadth(root, as_of)
    _build_sector_snapshots(root, as_of)
    _build_outcome_event_coverage(root, as_of)
    _build_outcome_opportunity_projections(root, as_of)
    _build_runtime_snapshots(root, as_of)
    artifact_inventory = _fixture_artifact_inventory(root)
    marker = {
        "schema_version": "structured_smoke_fixture_bundle_v1",
        "as_of_date": as_of_date,
        "fixture_class": "SYNTHETIC_NON_PRODUCTION",
        "contains_vendor_prose": False,
        "cache_root": str(root),
        "geopolitical_manifest": str(manifest_path),
        "geopolitical_manifest_hash": json.loads(
            manifest_path.read_text(encoding="utf-8")
        )["manifest_hash"],
        "artifact_inventory": artifact_inventory,
        "artifact_inventory_hash": _canonical_hash(artifact_inventory),
    }
    marker["bundle_hash"] = _canonical_hash(marker)
    _write_json(root / "structured_smoke_fixture_bundle.json", marker)
    return {
        "MOSAIC_CACHE_DIR": str(root),
        "MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST": str(manifest_path),
        "MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS": "structured_smoke",
        "MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH": marker["bundle_hash"],
    }


def render_shell_exports(bindings: dict[str, str]) -> str:
    return "\n".join(
        f"export {key}={shlex.quote(value)}" for key, value in sorted(bindings.items())
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--shell-exports",
        action="store_true",
        help="print shell-quoted export statements instead of JSON",
    )
    args = parser.parse_args()
    bindings = build_structured_smoke_fixtures(args.root, args.date)
    if args.shell_exports:
        print(render_shell_exports(bindings))
    else:
        print(json.dumps(bindings, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
