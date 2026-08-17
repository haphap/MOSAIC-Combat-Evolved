#!/usr/bin/env python3
"""Build explicit, synthetic PIT inputs for the real-LLM structured smoke.

The generated cache is non-production and contains no vendor prose.  It lets
the 28-stage graph exercise real structured output without weakening any
production snapshot fallback or writing to the scorecard/release ledgers.
"""

from __future__ import annotations

import argparse
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
from mosaic.dataflows.macro_source_contracts import (
    COMMODITY_CONTRACT_MAP,
    COMMODITY_FAMILY_CONTRACTS,
)
from mosaic.dataflows.macro_snapshots import (
    MACRO_EVENT_ROLES,
    validate_role_snapshot,
)
from mosaic.dataflows.outcome_runtime_inputs import (
    EVENT_COVERAGE_SCHEMA_VERSION,
    OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
)
from mosaic.dataflows.role_events import build_role_event_snapshot
from mosaic.dataflows.sector_archive import (
    LOGICAL_ROUTES as SECTOR_ARCHIVE_LOGICAL_ROUTES,
    SectorArchiveStore,
)
from mosaic.dataflows.china_agent_data_archive import (
    CAPTURE_SCHEMA_VERSION as CHINA_CAPTURE_SCHEMA_VERSION,
    CURVE_ROUTE_GROUP,
    INSTITUTIONAL_ETF_UNIVERSE,
    INSTITUTIONAL_ROUTE_GROUP,
    ROUTE_GROUPS as CHINA_ROUTE_GROUPS,
    ChinaAgentDataArchiveStore,
)
from mosaic.dataflows.supply_chain_disclosures import (
    OfficialSupplyChainDisclosureArchive,
    capture_official_supply_chain_disclosures,
)
from mosaic.dataflows.sector_snapshots import (
    SECTOR_DIRECTION_CONTRACT_VERSION,
    SECTOR_DIRECTION_IDS,
    SECTOR_ETF_DIRECTION_AUTHORITY,
    SECTOR_SNAPSHOT_SCHEMA_VERSION,
    SECTOR_UNIVERSE_MANIFEST,
    _canonical_hash as _sector_canonical_hash,
)
from mosaic.rke.agent_research_context import SECTOR_AGENT_KEYWORDS
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.opportunity_authority import macro_authority_members
from mosaic.scorecard.canonical_json import canonical_hash

_FIXTURE_ARTIFACT_ROOTS = (
    "china_archive",
    "economic_calendar",
    "forward_archive",
    "gov_policy",
    "macro_snapshots",
    "outcome_runtime",
    "runtime_snapshots",
    "sector_archive",
    "sector_snapshots",
    "supply_chain_archive",
)

ELIGIBILITY_ARTIFACT_SCHEMA_VERSION = "structured_smoke_etf_eligibility_v1"
FUND_BASIC_FIELDS = "ts_code,name,fund_type,list_date,delist_date"
FUND_DAILY_FIELDS = "ts_code,trade_date,vol,amount"
TRADE_CAL_FIELDS = "exchange,cal_date,is_open"
ELIGIBILITY_PROOF_SUSPENSION_STATUS = (
    "NO_SUSPENSION_INDICATED_BY_POSITIVE_FUND_DAILY_ACTIVITY"
)
_ELIGIBILITY_ARTIFACT_RELATIVE_PATH = (
    "sector_archive/eligibility/structured_smoke_etf_eligibility.json"
)


def _canonical_hash(payload: Any) -> str:
    return canonical_hash(payload)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and value[7:] == value[7:].lower()
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _approved_etf_authority() -> dict[str, dict[str, str]]:
    rows = [
        (family["etf_ts_codes"][0], family["sector_agent_id"], family["direction_id"])
        for family in SECTOR_ETF_DIRECTION_AUTHORITY["direction_families"]
        if family["etf_ts_codes"]
    ]
    if len(rows) != 9 or len({row[0] for row in rows}) != 9:
        raise RuntimeError("structured-smoke ETF authority must contain exactly nine unique codes")
    return {
        ts_code: {"sector_agent_id": sector_agent_id, "direction_id": direction_id}
        for ts_code, sector_agent_id, direction_id in rows
    }


def _parse_artifact_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise RuntimeError(f"eligibility artifact {field} must be a date")
    try:
        if len(value) == 8 and value.isdigit():
            return datetime.strptime(value, "%Y%m%d").date()
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError(f"eligibility artifact {field} is not a date") from exc


def _validate_artifact_record(
    record: Any,
    *,
    endpoint: str,
    code: str | None,
    as_of: date,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(record, dict) or set(record) != {
        "evidence_id",
        "query",
        "fetched_at",
        "row",
        "content_hash",
        "record_hash",
    }:
        raise RuntimeError(f"eligibility artifact {endpoint} record fields mismatch")
    evidence_id = record["evidence_id"]
    if not isinstance(evidence_id, str) or not evidence_id:
        raise RuntimeError(f"eligibility artifact {endpoint} evidence_id is invalid")
    query = record["query"]
    if not isinstance(query, dict) or query.get("endpoint") != endpoint:
        raise RuntimeError(f"eligibility artifact {endpoint} query is invalid")
    fetched_at = record["fetched_at"]
    try:
        parsed_fetched_at = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"eligibility artifact {endpoint} fetched_at is invalid") from exc
    if parsed_fetched_at.tzinfo is None:
        raise RuntimeError(f"eligibility artifact {endpoint} fetched_at lacks timezone")
    row = record["row"]
    if not isinstance(row, dict) or record["content_hash"] != _canonical_hash(row):
        raise RuntimeError(f"eligibility artifact {endpoint} content hash mismatch")
    if not _is_sha256(record["record_hash"]):
        raise RuntimeError(f"eligibility artifact {endpoint} record hash is invalid")
    if record["record_hash"] != _canonical_hash(
        {key: value for key, value in record.items() if key != "record_hash"}
    ):
        raise RuntimeError(f"eligibility artifact {endpoint} record hash mismatch")
    if code is not None and row.get("ts_code") != code:
        raise RuntimeError(f"eligibility artifact {endpoint} code mismatch")
    if endpoint == "fund_basic":
        if set(row) != {
            "ts_code",
            "name",
            "fund_type",
            "list_date",
            "delist_date",
        } or query.get("params") != {
            "ts_code": code,
            "market": "E",
            "fields": FUND_BASIC_FIELDS,
        }:
            raise RuntimeError("eligibility artifact fund_basic query/row mismatch")
        if not isinstance(row["name"], str) or not row["name"].strip():
            raise RuntimeError("eligibility artifact fund_basic name is missing")
        if not isinstance(row["fund_type"], str) or not row["fund_type"].strip():
            raise RuntimeError("eligibility artifact fund_basic fund_type is empty")
        list_date = _parse_artifact_date(row["list_date"], "fund_basic.list_date")
        delist_date = (
            None
            if row["delist_date"] in (None, "")
            else _parse_artifact_date(row["delist_date"], "fund_basic.delist_date")
        )
        if list_date > as_of or (
            delist_date is not None and delist_date <= as_of
        ):
            raise RuntimeError("eligibility artifact fund_basic listing window is invalid")
    elif endpoint == "fund_daily":
        if set(row) != {"ts_code", "trade_date", "vol", "amount"} or query.get(
            "params"
        ) != {
            "ts_code": code,
            "trade_date": as_of.strftime("%Y%m%d"),
            "fields": FUND_DAILY_FIELDS,
        }:
            raise RuntimeError("eligibility artifact fund_daily query/row mismatch")
        if row["trade_date"] != as_of.strftime("%Y%m%d"):
            raise RuntimeError("eligibility artifact fund_daily date mismatch")
        for field in ("vol", "amount"):
            if isinstance(row[field], bool) or not isinstance(row[field], (int, float)):
                raise RuntimeError(f"eligibility artifact fund_daily {field} is invalid")
            if float(row[field]) <= 0:
                raise RuntimeError(f"eligibility artifact fund_daily {field} is not positive")
    elif endpoint == "trade_cal":
        if set(row) != {"exchange", "cal_date", "is_open"} or query.get(
            "params"
        ) != {
            "exchange": row.get("exchange"),
            "start_date": as_of.strftime("%Y%m%d"),
            "end_date": as_of.strftime("%Y%m%d"),
            "fields": TRADE_CAL_FIELDS,
        }:
            raise RuntimeError("eligibility artifact trade_cal query/row mismatch")
        if row["cal_date"] != as_of.strftime("%Y%m%d") or row["is_open"] != 1:
            raise RuntimeError("structured-smoke eligibility artifact calendar is not open")
    else:
        raise RuntimeError(f"eligibility artifact endpoint is unsupported: {endpoint}")
    return row, record


def _load_eligibility_artifact(path: Path, as_of: date) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("structured-smoke eligibility artifact path is invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("structured-smoke eligibility artifact is unreadable") from exc
    expected_fields = {
        "schema_version",
        "as_of_date",
        "codes",
        "fund_basic",
        "fund_daily",
        "trade_cal",
        "provenance",
        "artifact_hash",
    }
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise RuntimeError("structured-smoke eligibility artifact fields mismatch")
    if payload["schema_version"] != ELIGIBILITY_ARTIFACT_SCHEMA_VERSION or payload[
        "as_of_date"
    ] != as_of.isoformat():
        raise RuntimeError("structured-smoke eligibility artifact identity mismatch")
    authority = _approved_etf_authority()
    codes = payload["codes"]
    if codes != sorted(authority) or len(codes) != 9:
        raise RuntimeError("structured-smoke eligibility artifact code set mismatch")
    if not isinstance(payload["provenance"], dict) or not all(
        isinstance(payload["provenance"].get(field), str)
        and payload["provenance"][field].strip()
        for field in ("collector", "preflight_registry_version", "rule")
    ):
        raise RuntimeError("structured-smoke eligibility artifact provenance is missing")
    body = {key: value for key, value in payload.items() if key != "artifact_hash"}
    if not _is_sha256(payload["artifact_hash"]) or payload["artifact_hash"] != _canonical_hash(body):
        raise RuntimeError("structured-smoke eligibility artifact hash mismatch")

    if not all(
        isinstance(payload[field], list)
        for field in ("fund_basic", "fund_daily", "trade_cal")
    ):
        raise RuntimeError("structured-smoke eligibility artifact rows must be lists")
    basics: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for record in payload["fund_basic"]:
        raw_row = record.get("row") if isinstance(record, dict) else None
        record_code = raw_row.get("ts_code") if isinstance(raw_row, dict) else None
        row, normalized = _validate_artifact_record(
            record, endpoint="fund_basic", code=record_code, as_of=as_of
        )
        code = row["ts_code"]
        if code in basics or code not in authority:
            raise RuntimeError("structured-smoke eligibility artifact fund_basic set mismatch")
        basics[code] = (row, normalized)
    dailies: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for record in payload["fund_daily"]:
        raw_row = record.get("row") if isinstance(record, dict) else None
        record_code = raw_row.get("ts_code") if isinstance(raw_row, dict) else None
        row, normalized = _validate_artifact_record(
            record, endpoint="fund_daily", code=record_code, as_of=as_of
        )
        code = row["ts_code"]
        if code in dailies or code not in authority:
            raise RuntimeError("structured-smoke eligibility artifact fund_daily set mismatch")
        dailies[code] = (row, normalized)
    if set(basics) != set(authority) or set(dailies) != set(authority):
        raise RuntimeError("structured-smoke eligibility artifact endpoint coverage mismatch")

    exchanges = {code: ("SSE" if code.endswith(".SH") else "SZSE") for code in authority}
    calendars: dict[str, dict[str, Any]] = {}
    for record in payload["trade_cal"]:
        row, normalized = _validate_artifact_record(
            record, endpoint="trade_cal", code=None, as_of=as_of
        )
        exchange = row.get("exchange") if isinstance(row, dict) else None
        if exchange in calendars:
            raise RuntimeError("eligibility artifact trade_cal has duplicate exchanges")
        if exchange not in {"SSE", "SZSE"}:
            raise RuntimeError("eligibility artifact trade_cal row is invalid")
        calendars[exchange] = normalized
    if set(calendars) != {"SSE", "SZSE"}:
        raise RuntimeError("structured-smoke eligibility artifact calendar coverage mismatch")
    raw_records = (*payload["fund_basic"], *payload["fund_daily"], *payload["trade_cal"])
    raw_evidence_ids = [record["evidence_id"] for record in raw_records]
    if len(raw_evidence_ids) != len(set(raw_evidence_ids)):
        raise RuntimeError(
            "structured-smoke eligibility artifact evidence_id values must be globally unique"
        )

    evidence_rows = {
        record["evidence_id"]: record
        for record in (*payload["fund_basic"], *payload["fund_daily"], *payload["trade_cal"])
    }
    proof_by_code: dict[str, dict[str, Any]] = {}
    for code in sorted(authority):
        basic, basic_record = basics[code]
        _daily, daily_record = dailies[code]
        calendar_record = calendars[exchanges[code]]
        proof_body = {
            "ts_code": code,
            "as_of_date": as_of.isoformat(),
            "exchange": exchanges[code],
            "listing_window": {
                "list_date": basic["list_date"],
                "delist_date": basic["delist_date"],
            },
            "suspension_status": ELIGIBILITY_PROOF_SUSPENSION_STATUS,
            "security_type": "ETF",
            "tradability": "TRADABLE",
            "evidence_ids": [
                basic_record["evidence_id"],
                daily_record["evidence_id"],
                calendar_record["evidence_id"],
            ],
            "evidence_hashes": [
                basic_record["record_hash"],
                daily_record["record_hash"],
                calendar_record["record_hash"],
            ],
            "provenance": {
                "collector": payload["provenance"]["collector"],
                "preflight_registry_version": payload["provenance"][
                    "preflight_registry_version"
                ],
                "authority_hash": SECTOR_ETF_DIRECTION_AUTHORITY["authority_hash"],
                "rule": "listed ETF + open exchange + positive exact-date fund_daily activity",
            },
        }
        proof_by_code[code] = {
            **proof_body,
            "content_hash": _canonical_hash(proof_body),
        }
    return {
        "payload": payload,
        "artifact_hash": payload["artifact_hash"],
        "authority": authority,
        "proof_by_code": proof_by_code,
        "evidence_by_id": evidence_rows,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
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
            ("eu_gdp", "ecb.MNA.Q.Y.B6.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.N"),
            ("eu_hicp", "ecb.HICP.M.B6.N.000000.4D0.ANR"),
            ("eu_unemployment", "ecb.LFSI.M.B6.S.UNEHRT.TOTAL0.15_74.T"),
            (
                "eu_household_consumption",
                "ecb.MNA.Q.Y.B6.W0.S1M.S1.D.P31._Z._Z._T.EUR.LR.N",
            ),
        ),
        "central_bank": (
            ("pboc_policy_rate", "official.pboc_lpr_catalog"),
            ("domestic_liquidity_omo", "official.pboc_omo_catalog"),
            ("cn_curve_10y", "official.mof_chinabond_government_10y"),
            ("credit_condition_spread", "official.pboc_tsfin_flow_stock"),
        ),
        "us_financial_conditions": (
            ("fed_effr", "official.nyfed_effr"),
            ("DGS10", "tushare.us_tycr_nominal_curve"),
            ("BAA10Y", "ALFRED"),
            ("DTWEXBGS", "ALFRED"),
        ),
        "euro_area_financial_conditions": (
            ("ecb_policy_rate", "ecb.FM.B.U2.EUR.4F.KR.DFR.LEV"),
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
                "ecb.RDF.D.D0.Z0Z.4F.EC.DFTSV.PR",
            ),
        ),
        "commodities": (
            ("energy_oil", "tushare.fut_daily.SC@INE"),
            ("industrial_metal_copper", "tushare.fut_daily.CU@SHFE"),
            ("gold_spot", "tushare.fut_daily.AU@SHFE"),
            ("agriculture_food_index", "tushare.fut_daily.C@DCE"),
        ),
        "institutional_flow": (
            tuple(
                (
                    f"etf_share_{ticker.replace('.', '_')}_change",
                    "tushare.fund_share",
                )
                for ticker in INSTITUTIONAL_ETF_UNIVERSE
            )
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
                            "etf_share": {
                                "eligible_count": len(INSTITUTIONAL_ETF_UNIVERSE),
                                "observed_count": len(INSTITUTIONAL_ETF_UNIVERSE),
                                "coverage_ratio": 1.0,
                            }
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


def _build_sector_snapshots(
    root: Path,
    as_of: date,
    *,
    eligibility_authority_codes: set[str] | None = None,
) -> None:
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
    authority_codes = {
        (row["sector_agent_id"], row["direction_id"]): row["etf_ts_codes"]
        for row in SECTOR_ETF_DIRECTION_AUTHORITY["direction_families"]
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
            authority_codes_for_direction = authority_codes[(agent_id, direction_id)]
            use_authority_code = (
                bool(eligibility_authority_codes)
                and len(authority_codes_for_direction) == 1
                and authority_codes_for_direction[0] in eligibility_authority_codes
            )
            ts_code = (
                authority_codes_for_direction[0]
                if use_authority_code
                else f"{600000 + ticker_ordinal:06d}.SH"
            )
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
                "ts_code": ts_code,
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
            direction_quality = len(universe) - security_ordinal + 1
            authority_row = (
                eligibility_authority_codes is not None
                and security["ts_code"] in eligibility_authority_codes
            )
            unavailable = (
                eligibility_authority_codes is not None and not authority_row
            )
            scoring_row = {
                "ts_code": security["ts_code"],
                "direction_id": security["direction_id"],
                "availability_status": (
                    "UNAVAILABLE" if unavailable else "AVAILABLE"
                ),
                "unavailability_reason": (
                    "INSUFFICIENT_PIT_OBSERVATIONS" if unavailable else None
                ),
                "observation_date": released_at,
                "released_at": released_at,
                "vintage_at": released_at,
                "pit_status": "PIT_VERIFIED",
                "adjusted_return_20d": (
                    None
                    if unavailable
                    else 10.0
                    if authority_row
                    else round(0.04 * direction_quality, 6)
                ),
                "realized_volatility_20d": (
                    None
                    if unavailable
                    else 0.01
                    if authority_row
                    else round(0.08 + 0.06 * security_ordinal, 6)
                ),
                "median_amount_20d_cny": (
                    None
                    if unavailable
                    else 1_000_000_000.0
                    if authority_row
                    else float(100_000_000 - security_ordinal * 10_000)
                ),
                "net_moneyflow_20d_cny": (
                    None
                    if unavailable
                    else 1_000_000_000.0
                    if authority_row
                    else float(1_000_000 + direction_quality * 100_000)
                ),
                "observation_count": 0 if unavailable else 20,
                "required_observation_count": 20,
                "coverage_ratio": 0.0 if unavailable else 1.0,
                "evidence_ids": [
                    f"structured-smoke:sector:{agent_id}:{security['direction_id']}"
                ],
            }
            scoring_row["security_scoring_row_hash"] = _sector_canonical_hash(
                scoring_row
            )
            security_scoring_rows.append(scoring_row)
        if eligibility_authority_codes is None:
            direction_metric_rank = {
                direction_id: ordinal
                for ordinal, direction_id in enumerate(direction_ids, start=1)
            }
        else:
            validated_authority_directions = [
                direction_id
                for direction_id in direction_ids
                if len(authority_codes[(agent_id, direction_id)]) == 1
                and authority_codes[(agent_id, direction_id)][0]
                in eligibility_authority_codes
            ]
            if len(validated_authority_directions) != 1:
                raise ValueError(
                    f"{agent_id} must have exactly one validated eligibility authority direction"
                )
            metric_order = [
                validated_authority_directions[0],
                *(
                    direction_id
                    for direction_id in direction_ids
                    if direction_id != validated_authority_directions[0]
                ),
            ]
            direction_metric_rank = {
                direction_id: ordinal
                for ordinal, direction_id in enumerate(metric_order, start=1)
            }
        cards = []
        for direction_id in direction_ids:
            contract = direction_contracts[(agent_id, direction_id)]
            evidence_id = f"structured-smoke:sector:{agent_id}:{direction_id}"
            members = [row for row in universe if row["direction_id"] == direction_id]
            etf_family = {
                "etf_family_id": f"sector-etf:{agent_id}:{direction_id}",
                "direction_id": direction_id,
                "etf_ts_codes": list(authority_codes[(agent_id, direction_id)]),
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
                metric_id = metric_contract["metric_id"]
                metric_ordinal = direction_metric_rank[direction_id]
                if metric_id == "REALIZED_VOLATILITY_60D":
                    metric_value = round(0.08 + metric_ordinal * 0.08, 4)
                elif metric_id == "CURRENT_DRAWDOWN_252D":
                    metric_value = round(-0.05 - (metric_ordinal - 1) * 0.12, 4)
                else:
                    metric_value = round(0.8 - (metric_ordinal - 1) * 0.18, 4)
                metric = {
                    **metric_contract,
                    "direction_id": direction_id,
                    "availability_status": "UNAVAILABLE" if is_etf else "AVAILABLE",
                    "observation_date": as_of.isoformat() if is_etf else released_at,
                    "released_at": as_of.isoformat() if is_etf else released_at,
                    "vintage_at": as_of.isoformat() if is_etf else released_at,
                    "pit_status": "PIT_VERIFIED",
                    "value": None if is_etf else metric_value,
                    "observation_count": (
                        0 if is_etf else metric_contract["minimum_observations"]
                    ),
                    "eligible_count": (
                        len(etf_family["etf_ts_codes"])
                        if is_etf
                        else len(members)
                    ),
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
def _build_sector_archive(root: Path, as_of: date) -> Path:
    snapshot_root = root / "sector_snapshots" / as_of.isoformat()
    agent_id = "semiconductor"
    snapshot = json.loads(
        (snapshot_root / f"{agent_id}.json").read_text(encoding="utf-8")
    )
    ticker_industries: dict[str, str] = {}
    industry = f"synthetic-{agent_id}"
    for row in snapshot["eligible_security_universe"]:
        ticker_industries.setdefault(row["ts_code"], industry)
    tickers = sorted(ticker_industries)
    etfs = sorted(
        {
            ticker
            for card in snapshot["direction_cards"]
            for ticker in card["etf_family"]["etf_ts_codes"]
        }
    )
    if not tickers or not etfs:
        raise RuntimeError("structured-smoke sector archive scope is empty")

    start = as_of - timedelta(days=365)
    daily_rows: list[dict[str, Any]] = []
    for ticker_ordinal, ticker in enumerate(tickers, start=1):
        for day_ordinal in range(366):
            trading_day = start + timedelta(days=day_ordinal)
            base = 10.0 + ticker_ordinal / 10 + day_ordinal / 100
            daily_rows.append(
                {
                    "ts_code": ticker,
                    "trade_date": trading_day.strftime("%Y%m%d"),
                    "open": round(base, 4),
                    "high": round(base + 0.5, 4),
                    "low": round(base - 0.5, 4),
                    "close": round(base + 0.2, 4),
                    "pre_close": round(base + 0.1, 4),
                    "change": 0.1,
                    "pct_chg": 1.0,
                    "vol": 1_000 + day_ordinal,
                    "amount": 10_000 + day_ordinal,
                }
            )

    annual_end = f"{as_of.year - 1}1231"
    quarterly_end = f"{as_of.year}0331"
    announcement = min(as_of, date(as_of.year, 4, 30)).strftime("%Y%m%d")
    statement_rows: dict[str, list[dict[str, Any]]] = {
        "income": [],
        "cashflow": [],
        "balancesheet": [],
    }
    for ticker_ordinal, ticker in enumerate(tickers, start=1):
        for end_date in (annual_end, quarterly_end):
            common = {
                "ts_code": ticker,
                "ann_date": announcement,
                "f_ann_date": announcement,
                "end_date": end_date,
                "update_flag": "1",
            }
            statement_rows["income"].append(
                {
                    **common,
                    "revenue": float(100 + ticker_ordinal),
                    "total_revenue": float(100 + ticker_ordinal),
                    "n_income": float(8 + ticker_ordinal),
                    "rd_exp": float(2 + ticker_ordinal / 10),
                    "operate_profit": float(10 + ticker_ordinal),
                }
            )
            statement_rows["cashflow"].append(
                {**common, "n_cashflow_act": float(9 + ticker_ordinal)}
            )
            statement_rows["balancesheet"].append(
                {**common, "total_assets": float(1_000 + ticker_ordinal)}
            )

    disclosure_date = min(as_of, date(as_of.year, 7, 1)).strftime("%Y%m%d")
    report_date = date(as_of.year, 6, 30).strftime("%Y%m%d")
    fund_rows = [
        {
            "ts_code": etf,
            "ann_date": disclosure_date,
            "end_date": report_date,
            "symbol": tickers[index % len(tickers)].split(".", 1)[0],
            "stk_name": f"synthetic-holding-{index + 1}",
            "stk_mkv_ratio": 9.0,
            "stk_float_ratio": 2.0,
        }
        for index, etf in enumerate(etfs)
    ]
    api_as_of = as_of.strftime("%Y%m%d")
    daily_basic_rows = [
        {
            "ts_code": ticker,
            "trade_date": api_as_of,
            "close": float(10 + index),
            "turnover_rate": 1.0,
            "pe": float(8 + index / 10),
            "pb": 1.0,
            "ps": 1.5,
            "dv_ratio": 2.0,
            "total_mv": float(100_000 + index * 1_000),
            "circ_mv": float(80_000 + index * 1_000),
        }
        for index, ticker in enumerate(tickers, start=1)
    ]
    fina_indicator_rows = [
        {
            "ts_code": ticker,
            "ann_date": announcement,
            "end_date": quarterly_end,
            "roe": 10.0,
            "roa": 5.0,
            "grossprofit_margin": 30.0,
            "netprofit_margin": 15.0,
            "debt_to_assets": 40.0,
            "ocf_to_or": 12.0,
            "netprofit_yoy": 8.0,
        }
        for ticker in tickers
    ]
    company_rows = [
        {
            "ts_code": ticker,
            "exchange": "SSE" if ticker.endswith(".SH") else "SZSE",
            "employees": 1_000 + index,
            "introduction": f"synthetic company profile {index}",
            "main_business": f"synthetic-{ticker_industries[ticker]} business",
            "business_scope": f"synthetic-{ticker_industries[ticker]} scope",
        }
        for index, ticker in enumerate(tickers, start=1)
    ]
    main_business_rows = [
        {
            "ts_code": ticker,
            "end_date": annual_end,
            "bz_item": f"synthetic-segment-{index}",
            "bz_sales": float(60 + index),
            "bz_profit": float(12 + index),
        }
        for index, ticker in enumerate(tickers, start=1)
    ]
    forecast_rows = [
        {
            "ts_code": ticker,
            "ann_date": announcement,
            "first_ann_date": announcement,
            "end_date": quarterly_end,
            "net_profit_min": float(8 + index),
            "net_profit_max": float(10 + index),
            "p_change_min": 5.0,
            "p_change_max": 8.0,
        }
        for index, ticker in enumerate(tickers, start=1)
    ]
    express_rows = [
        {
            "ts_code": ticker,
            "ann_date": announcement,
            "end_date": quarterly_end,
            "revenue": float(100 + index),
            "n_income": float(8 + index),
        }
        for index, ticker in enumerate(tickers, start=1)
    ]
    batches = [
        {
            "endpoint": "stock_basic",
            "rows": [
                {
                    "ts_code": ticker,
                    "symbol": ticker.split(".", 1)[0],
                    "name": f"synthetic-security-{index + 1}",
                    "area": "synthetic-area",
                    "industry": ticker_industries[ticker],
                    "market": "主板",
                    "list_date": "20200101",
                    "list_status": "L",
                }
                for index, ticker in enumerate(tickers)
            ],
        },
        {"endpoint": "daily", "rows": daily_rows},
        {"endpoint": "daily_basic", "rows": daily_basic_rows},
        *(
            {"endpoint": endpoint, "rows": rows}
            for endpoint, rows in statement_rows.items()
        ),
        {"endpoint": "fina_indicator", "rows": fina_indicator_rows},
        {"endpoint": "stock_company", "rows": company_rows},
        {"endpoint": "fina_mainbz", "rows": main_business_rows},
        {"endpoint": "forecast", "rows": forecast_rows},
        {"endpoint": "express", "rows": express_rows},
        {"endpoint": "fund_portfolio", "rows": fund_rows},
    ]
    captured_at = f"{as_of.isoformat()}T16:30:00+08:00"
    capture_scope = {
        "sector_agent_ids": [agent_id],
        "security_codes": tickers,
        "etf_codes": etfs,
    }
    group = {
        "schema_version": "sector_relationship_capture_group_v2",
        "capture_key": _canonical_hash(
            {
                "fixture": "structured-smoke-sector-archive",
                "as_of": as_of.isoformat(),
                "sector_agent_id": agent_id,
            }
        ),
        "as_of_date": as_of.isoformat(),
        "cutoff_at": f"{as_of.isoformat()}T23:59:00+08:00",
        "captured_at": captured_at,
        "capture_scope": capture_scope,
        "capture_scope_hash": _canonical_hash(capture_scope),
        "requested_route_ids": list(SECTOR_ARCHIVE_LOGICAL_ROUTES),
        "base_group_hash": _canonical_hash(
            {"fixture": "structured-smoke-a-share-base", "as_of": as_of.isoformat()}
        ),
        "sessions": [
            (start + timedelta(days=index)).strftime("%Y%m%d")
            for index in range(366)
        ],
        "batches": batches,
        "page_count": len(batches),
        "normalized_row_count": sum(len(batch["rows"]) for batch in batches),
        "duplicate_counts": {},
    }
    archive_path = root / "sector_archive" / "sector_relationship.sqlite3"
    store = SectorArchiveStore(archive_path)
    store.get_or_capture(group["capture_key"], lambda: group)
    return archive_path


def _build_forward_archive(root: Path, as_of: date) -> Path:
    snapshot_root = root / "sector_snapshots" / as_of.isoformat()
    ticker_industries: dict[str, str] = {}
    direction_ids: set[str] = set()
    rke_pairs: set[tuple[str, str]] = set()
    direction_agents: dict[str, str] = {}
    rke_pair_agents: dict[tuple[str, str], str] = {}
    for agent_id in SECTOR_DIRECTION_IDS:
        snapshot = json.loads(
            (snapshot_root / f"{agent_id}.json").read_text(encoding="utf-8")
        )
        direction_ids.update(snapshot["direction_ids"])
        for direction in snapshot["direction_ids"]:
            direction_agents[direction] = agent_id
        industry = f"synthetic-{agent_id}"
        for row in snapshot["eligible_security_universe"]:
            ticker_industries.setdefault(row["ts_code"], industry)
            pair = (row["ts_code"], row["direction_id"])
            rke_pairs.add(pair)
            rke_pair_agents[pair] = agent_id
    if not ticker_industries:
        raise RuntimeError("structured-smoke forward archive scope is empty")

    publish_date = (as_of - timedelta(days=1)).isoformat()
    discovered_at = f"{as_of.isoformat()}T08:00:00+08:00"

    def research_row(
        *, source_id: str, report_type: str, query_key: str, industry: str, ts_code: str
    ) -> dict[str, Any]:
        title = f"synthetic {report_type} {query_key}"
        return {
            "source_id": source_id,
            "source_span_id": f"{source_id}:abstract",
            "source_type": "synthetic_tushare_research_report",
            "report_type": report_type,
            "query_key": query_key,
            "publish_date": publish_date,
            "discovered_at": discovered_at,
            "title": title,
            "abstract": f"{title} fixture abstract",
            "author": "synthetic analyst",
            "institution": "synthetic broker",
            "ts_code": ts_code,
            "industry": industry,
            "url": f"https://synthetic.invalid/{source_id}",
            "source_hash": _canonical_hash(
                {
                    "source_id": source_id,
                    "report_type": report_type,
                    "query_key": query_key,
                    "publish_date": publish_date,
                }
            ),
            "point_in_time_available": True,
            "license_status": "synthetic_non_production",
        }

    stock_rows = [
        research_row(
            source_id=f"structured-smoke-stock-{index}",
            report_type="个股研报",
            query_key=ticker,
            industry=industry,
            ts_code=ticker,
        )
        for index, (ticker, industry) in enumerate(
            sorted(ticker_industries.items()), start=1
        )
    ]
    broker_rows = [
        research_row(
            source_id=f"structured-smoke-industry-{index}",
            report_type="行业研报",
            query_key=industry,
            industry=industry,
            ts_code="",
        )
        for index, industry in enumerate(
            sorted(set(ticker_industries.values())), start=1
        )
    ]
    direction_rows = []
    rke_agent_by_source: dict[str, str] = {}
    for index, direction in enumerate(sorted(direction_ids), start=1):
        row = research_row(
            source_id=f"structured-smoke-direction-{index}",
            report_type="行业研报",
            query_key=direction,
            industry=direction,
            ts_code="",
        )
        direction_rows.append(row)
        if agent_id := direction_agents.get(direction):
            rke_agent_by_source[row["source_id"]] = agent_id
    rke_stock_rows = []
    for index, (ticker, direction) in enumerate(sorted(rke_pairs), start=1):
        row = research_row(
            source_id=f"structured-smoke-rke-stock-{index}",
            report_type="个股研报",
            query_key=ticker,
            industry=direction,
            ts_code=ticker,
        )
        rke_stock_rows.append(row)
        if agent_id := rke_pair_agents.get((ticker, direction)):
            rke_agent_by_source[row["source_id"]] = agent_id
    rows = [*stock_rows, *broker_rows, *direction_rows, *rke_stock_rows]
    archive_root = root / "forward_archive"
    _write_jsonl(
        archive_root / "registry/sources/tushare_research_reports.jsonl", rows
    )
    rke_rows = [*rke_stock_rows, *direction_rows]
    report_metadata = []
    forecast_claims = []
    for index, row in enumerate(rke_rows, start=1):
        report_id = f"structured-smoke-rke-report-{index}"
        is_stock = row["report_type"] == "个股研报"
        rke_agent_id = rke_agent_by_source.get(row["source_id"], "")
        report_metadata.append(
            {
                "report_id": report_id,
                "source_id": row["source_id"],
                "report_type": row["report_type"],
                "ts_code": row["ts_code"],
                "sector": row["industry"],
                "subsectors": (
                    [SECTOR_AGENT_KEYWORDS[f"sector.{rke_agent_id}"][0]]
                    if rke_agent_id
                    else []
                ),
                "publish_datetime": f"{publish_date}T09:00:00+08:00",
                "accessible_datetime": f"{publish_date}T09:00:00+08:00",
            }
        )
        forecast_claims.append(
            {
                "forecast_claim_id": f"structured-smoke-rke-claim-{index}",
                "report_id": report_id,
                "source_id": row["source_id"],
                "target": {
                    "target_type": "stock" if is_stock else "industry",
                    "target_id": row["ts_code"] if is_stock else row["industry"],
                },
                "metric_proxy_mapping": (
                    ["cashflow", "quality", "stock_forward_return"]
                    if is_stock
                    else ["industry_etf_forward_return"]
                ),
                "direction": "positive",
            }
        )
    rke_root = archive_root / "registry/report_intelligence"
    _write_jsonl(rke_root / "report_metadata.jsonl", report_metadata)
    _write_jsonl(rke_root / "forecast_claims.jsonl", forecast_claims)
    return archive_root


def _build_supply_chain_archive(root: Path, as_of: date) -> Path:
    archive_path = (
        root / "supply_chain_archive" / "official_supply_chain_disclosures.sqlite3"
    )
    archive = OfficialSupplyChainDisclosureArchive(archive_path)
    announcement_date = as_of - timedelta(days=30)
    announced_at = f"{announcement_date.isoformat()}T18:00:00+08:00"
    report_period = date(announcement_date.year - 1, 12, 31).isoformat()
    counterparties = {
        "000001.SZ": "000002.SZ",
        "000002.SZ": "000001.SZ",
    }
    for ticker, counterparty in counterparties.items():
        org_id = f"structured-smoke-{ticker[:6]}"
        document_url = (
            "https://static.cninfo.com.cn/finalpage/"
            f"{announcement_date.isoformat()}/synthetic-{ticker[:6]}.pdf"
        )
        document_content = (
            f"%PDF-1.7\nsynthetic supply-chain disclosure {ticker}\n%%EOF"
        ).encode()
        announcement = {
            "announcement_id": f"CNINFO-{ticker[:6]}-SYNTHETIC-ANNUAL",
            "ticker": ticker,
            "title": "synthetic annual report",
            "announced_at": announced_at,
            "report_period": report_period,
            "document_url": document_url,
        }

        def search_page(
            identity: dict[str, str],
            captured_as_of: str,
            page_number: int,
            *,
            expected_ticker: str = ticker,
            expected_org_id: str = org_id,
            expected_announcement: dict[str, str] = announcement,
        ) -> dict[str, Any]:
            if identity != {"ticker": expected_ticker, "org_id": expected_org_id}:
                raise AssertionError("synthetic CNINFO identity mismatch")
            if captured_as_of != as_of.isoformat():
                raise AssertionError("synthetic CNINFO as_of mismatch")
            if page_number == 1:
                return {
                    "page_number": 1,
                    "has_more": False,
                    "announcements": [expected_announcement],
                }
            return {"page_number": 2, "has_more": False, "announcements": []}

        capture_official_supply_chain_disclosures(
            archive=archive,
            ticker=ticker,
            as_of=as_of.isoformat(),
            resolve_identity=lambda requested_ticker, expected_org_id=org_id: {
                "ticker": requested_ticker,
                "org_id": expected_org_id,
            },
            search_page=search_page,
            download_document=lambda _url, content=document_content: content,
            parse_document=lambda _content, _metadata, peer=counterparty: [
                {"counterparty_ticker": peer, "counterparty_role": "supplier"}
            ],
            parser_version="structured-smoke-supply-chain-v1",
            build_query_contract=lambda identity, captured_as_of: {
                "contract_version": "cninfo_annual_report_query_v2",
                "endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                "method": "POST",
                "content_type": "application/x-www-form-urlencoded",
                "identity_endpoint": (
                    "https://www.cninfo.com.cn/new/information/topSearch/query"
                ),
                "identity_method": "POST",
                "identity_max_results": 10,
                "identity_match_policy": "UNIQUE_EXACT_CODE",
                "counterparty_match_policy": "UNIQUE_NORMALIZED_EXACT_NAME",
                "counterparty_query_limit_per_document": 10,
                "page_size": 30,
                "column": "szse",
                "tab_name": "fulltext",
                "plate": "",
                "stock": f"{identity['ticker'][:6]},{identity['org_id']}",
                "search_key": "",
                "security_id": "",
                "category": "category_ndbg_szsh",
                "trade": "",
                "start_date": (
                    date.fromisoformat(captured_as_of) - timedelta(days=5 * 365)
                ).isoformat(),
                "end_date": captured_as_of,
                "sort_name": "time",
                "sort_type": "desc",
                "highlight_titles": True,
            },
        )
    return archive_path


def _build_china_archive(root: Path, as_of: date) -> Path:
    archive_path = root / "china_archive" / "china_agent_data.sqlite3"
    store = ChinaAgentDataArchiveStore(archive_path)
    start = as_of - timedelta(days=365)
    captured_at = f"{as_of.isoformat()}T14:45:00+08:00"
    cutoff_at = f"{as_of.isoformat()}T23:59:00+08:00"
    institutional_body = {
        "schema_version": CHINA_CAPTURE_SCHEMA_VERSION,
        "capture_key": _canonical_hash(
            {"fixture": "structured-smoke-institutional", "as_of": as_of.isoformat()}
        ),
        "route_group": INSTITUTIONAL_ROUTE_GROUP,
        "route_ids": list(CHINA_ROUTE_GROUPS[INSTITUTIONAL_ROUTE_GROUP]),
        "as_of_date": as_of.isoformat(),
        "cutoff_at": cutoff_at,
        "captured_at": captured_at,
        "market_session_date": as_of.isoformat(),
        "fund_share_rows": [
            {
                "ts_code": ticker,
                "latest": {
                    "trade_date": as_of.isoformat(),
                    "fd_share": float(index * 1_000),
                },
                "prior": {
                    "trade_date": (as_of - timedelta(days=1)).isoformat(),
                    "fd_share": float(index * 900),
                },
                "share_change_pct": round((1_000 - 900) / 900 * 100, 6),
            }
            for index, ticker in enumerate(INSTITUTIONAL_ETF_UNIVERSE, start=1)
        ],
    }
    institutional_group = {
        **institutional_body,
        "group_hash": _canonical_hash(institutional_body),
    }
    store.get_or_capture(
        institutional_body["capture_key"], lambda: institutional_group
    )

    tenors = (1, 2, 3, 5, 7, 10, 30)
    government_curve_rows = [
        {
            "trade_date": (start + timedelta(days=day_ordinal)).isoformat(),
            "released_at": (
                f"{(start + timedelta(days=day_ordinal)).isoformat()}"
                "T17:30:00+08:00"
            ),
            "curve_type": "0",
            "curve_term": tenor,
            "yield": round(1.0 + tenor / 100 + day_ordinal / 10_000, 6),
        }
        for day_ordinal in range(366)
        for tenor in tenors
    ]
    latest_government_curve = {
        f"{row['curve_term']}y": row["yield"]
        for row in government_curve_rows
        if row["trade_date"] == as_of.isoformat()
    }
    curve_captured_at = f"{as_of.isoformat()}T18:00:00+08:00"
    curve_body = {
        "schema_version": CHINA_CAPTURE_SCHEMA_VERSION,
        "capture_key": _canonical_hash(
            {"fixture": "structured-smoke-curve", "as_of": as_of.isoformat()}
        ),
        "route_group": CURVE_ROUTE_GROUP,
        "route_ids": list(CHINA_ROUTE_GROUPS[CURVE_ROUTE_GROUP]),
        "as_of_date": as_of.isoformat(),
        "cutoff_at": cutoff_at,
        "captured_at": curve_captured_at,
        "market_session_date": as_of.isoformat(),
        "requested_market_session_date": as_of.isoformat(),
        "shibor": {"overnight": 1.3, "three_month": 1.6},
        "curve_history_start": start.isoformat(),
        "government_curve_rows": government_curve_rows,
        "government_curve": {
            "2y": latest_government_curve["2y"],
            "10y": latest_government_curve["10y"],
        },
        "government_curve_source": {
            "schema_version": "mof_chinabond_government_yield_curve_v1",
            "provider": "MOF_CHINABOND",
            "source_url": (
                "https://yield.chinabond.com.cn/cbweb-czb-web/czb/historyQuery"
            ),
            "yield_type": "MATURITY",
            "release_time": "17:30:00+08:00",
            "request_windows": [
                {
                    "start_date": start.isoformat(),
                    "end_date": as_of.isoformat(),
                }
            ],
            "response_hashes": [
                _canonical_hash(
                    {
                        "fixture": "structured-smoke-official-curve",
                        "start_date": start.isoformat(),
                        "end_date": as_of.isoformat(),
                    }
                )
            ],
            "session_released_at": (
                f"{as_of.isoformat()}T17:30:00+08:00"
            ),
        },
    }
    curve_group = {**curve_body, "group_hash": _canonical_hash(curve_body)}
    store.get_or_capture(curve_body["capture_key"], lambda: curve_group)
    return archive_path


def _build_policy_archive(root: Path, as_of: date) -> Path:
    policy_root = root / "gov_policy"
    published_at = (as_of - timedelta(days=1)).isoformat()
    discovered_at = f"{as_of.isoformat()}T08:30:00+08:00"
    article_id = f"structured-smoke-policy-{as_of.isoformat()}"
    row = {
        "article_id": article_id,
        "source": "synthetic gov.cn policy fixture",
        "category_id": "gongwen",
        "category": "国务院文件",
        "pub_date": published_at,
        "puborg": "国务院",
        "pcode": "synthetic-policy-1",
        "index": "",
        "childtype": "国民经济管理、国有资产监管",
        "title": "synthetic industry policy fixture",
        "summary": "synthetic policy summary without vendor prose",
        "url": f"https://synthetic.invalid/{article_id}",
        "raw_id": article_id,
        "raw_pubtime": None,
        "raw_ptime": None,
        "raw_sha256": _canonical_hash({"article_id": article_id})[7:],
        "parsed_at": discovered_at,
        "discovered_at": discovered_at,
    }
    _write_jsonl(policy_root / "parsed/policy_documents.jsonl", [row])
    return policy_root


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


def _runtime_snapshot(
    *,
    agent_id: str,
    stage: str,
    tool_id: str,
    as_of: date,
    upstream: tuple[tuple[dict[str, Any], dict[str, Any]], ...],
    constraints: dict[str, Any],
    role_context: dict[str, Any],
    candidate_universe: list[dict[str, Any]] | None = None,
    candidate_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    contract = BOUND_RUNTIME_SNAPSHOT_CONTRACTS[tool_id]
    refs = [ref for ref, _evidence in upstream]
    evidence = [row for _ref, row in upstream] + (candidate_evidence or [])
    evidence_ids = [row["evidence_id"] for row in evidence]
    constraints = {**constraints, "evidence_ids": evidence_ids}
    role_context = {**role_context, "evidence_ids": evidence_ids}
    candidate_universe = candidate_universe or []
    candidate_status = "AVAILABLE" if candidate_universe else "EMPTY_CONFIRMED"
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


def _build_runtime_snapshots(
    root: Path, as_of: date, eligibility: dict[str, Any] | None = None
) -> None:
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
    autonomous_execution = _runtime_accepted_ref(
        agent_id="autonomous_execution",
        stage="autonomous_execution",
        accepted_output_kind="EXECUTION_ASSESSMENT",
        as_of=as_of,
    )
    alpha = _runtime_accepted_ref(
        agent_id="alpha_discovery",
        stage="alpha_discovery",
        accepted_output_kind="ALPHA_DISCOVERY",
        as_of=as_of,
    )
    eligibility_evidence_rows: list[dict[str, Any]] = []
    superinvestor_candidates: list[dict[str, Any]] = []
    proposal_candidates: list[dict[str, Any]] = []
    cro_candidates: list[dict[str, Any]] = []
    execution_candidates: list[dict[str, Any]] = []
    final_candidates: list[dict[str, Any]] = []
    order_intents: list[dict[str, Any]] = []
    if eligibility is None:
        candidate_source_ref = sector[0][0]
        candidate_source_snapshot = json.loads(
            (
                root
                / "sector_snapshots"
                / as_of.isoformat()
                / f"{candidate_source_ref['agent_id']}.json"
            ).read_text(encoding="utf-8")
        )
        candidate_security = candidate_source_snapshot[
            "eligible_security_universe"
        ][0]
        candidate_ref_seed = {
            "accepted_output_id": candidate_source_ref["accepted_output_id"],
            "pick_local_id": (
                "structured-smoke:pick:"
                f"{candidate_security['direction_id']}:"
                f"{candidate_security['ts_code']}"
            ),
        }
        superinvestor_candidate = {
            "candidate_ref": "runtime-candidate:"
            + _canonical_hash(candidate_ref_seed).removeprefix("sha256:"),
            "ts_code": candidate_security["ts_code"],
            "source_output_id": candidate_source_ref["accepted_output_id"],
            "source_output_hash": candidate_source_ref["accepted_output_hash"],
            "source_sector_agent_id": candidate_source_ref["agent_id"],
            "source_direction_id": candidate_security["direction_id"],
            "source_direction": "PREFERRED",
            "metrics": {
                "conviction": 0.8,
                "signal_origin": "synthetic_structured_smoke",
            },
            "evidence_ids": list(candidate_source_ref["evidence_ids"]),
        }
        superinvestor_candidates = [superinvestor_candidate]
        candidate_ticker = superinvestor_candidate["ts_code"]
        candidate_ref = superinvestor_candidate["candidate_ref"]
        proposal_evidence_ids = list(cio_proposal[0]["evidence_ids"])
        position_ref = f"structured-smoke:position:{candidate_ticker}"
        order_intent_ref = f"structured-smoke:order-intent:{candidate_ticker}"
        buy_metrics = {
            "current_weight": 0.0,
            "target_weight": 0.1,
            "delta_weight": 0.1,
            "signal_origin": "synthetic_structured_smoke",
        }
        proposal_candidates = [
            {
                "candidate_ref": candidate_ref,
                "ts_code": candidate_ticker,
                "source_kind": "SECTOR_SELECTION",
                "current_weight": 0.0,
                "reference_target_weight": 0.1,
                "source_output_id": superinvestor_candidate["source_output_id"],
                "source_output_hash": superinvestor_candidate["source_output_hash"],
                "metrics": {
                    **superinvestor_candidate["metrics"],
                    "target_weight": 0.1,
                    "delta_weight": 0.1,
                },
                "evidence_ids": list(superinvestor_candidate["evidence_ids"]),
            }
        ]
        cro_candidates = [
            {
                "candidate_ref": candidate_ref,
                "ts_code": candidate_ticker,
                "proposal_position_ref": position_ref,
                "current_weight": 0.0,
                "proposed_target_weight": 0.1,
                "proposed_delta_weight": 0.1,
                "sector_id": superinvestor_candidate["source_sector_agent_id"],
                "metrics": buy_metrics,
                "evidence_ids": proposal_evidence_ids,
            }
        ]
        execution_candidates = [
            {
                "candidate_ref": candidate_ref,
                "ts_code": candidate_ticker,
                "order_intent_ref": order_intent_ref,
                "current_weight": 0.0,
                "target_weight": 0.1,
                "requested_delta_weight": 0.1,
                "side": "BUY",
                "metrics": buy_metrics,
                "evidence_ids": sorted(
                    {*proposal_evidence_ids, cro[0]["evidence_ids"][0]}
                ),
            }
        ]
        final_candidates = [
            {
                "candidate_ref": candidate_ref,
                "ts_code": candidate_ticker,
                "proposal_position_ref": position_ref,
                "current_weight": 0.0,
                "proposed_target_weight": 0.1,
                "proposed_delta_weight": 0.1,
                "metrics": buy_metrics,
                "evidence_ids": proposal_evidence_ids,
            }
        ]
        order_intents = [
            {
                "order_intent_ref": order_intent_ref,
                "ts_code": candidate_ticker,
                "action": "BUY",
                "requested_delta_weight": 0.1,
            }
        ]
    else:
        eligibility_evidence_rows = [
            {
                "evidence_id": f"structured-smoke:eligibility-proof:{ts_code}",
                "source_kind": "DERIVED_METRIC",
                "source_id": _ELIGIBILITY_ARTIFACT_RELATIVE_PATH,
                "metric": "pit_eligibility",
                "value": proof["tradability"],
                "unit": "status",
                "as_of": proof["as_of_date"],
                "available_at": f"{proof['as_of_date']}T07:00:00Z",
                "source_fingerprint": proof["content_hash"],
            }
            for ts_code, proof in sorted(eligibility["proof_by_code"].items())
        ]
        semiconductor_refs = [
            ref for ref, _evidence in sector if ref["agent_id"] == "semiconductor"
        ]
        if len(semiconductor_refs) != 1:
            raise RuntimeError("structured-smoke Semiconductor accepted L2 ref is ambiguous")
        candidate_source_ref = semiconductor_refs[0]
        candidate_source_snapshot = json.loads(
            (
                root
                / "sector_snapshots"
                / as_of.isoformat()
                / f"{candidate_source_ref['agent_id']}.json"
            ).read_text(encoding="utf-8")
        )
        authority_candidates = [
            (ts_code, binding)
            for ts_code, binding in eligibility["authority"].items()
            if binding["sector_agent_id"] == "semiconductor"
        ]
        if len(authority_candidates) != 1:
            raise RuntimeError("structured-smoke Semiconductor eligibility authority is ambiguous")
        authority_ticker, authority_binding = authority_candidates[0]
        direction_id = authority_binding["direction_id"]
        projection = json.loads(
            (
                root
                / "outcome_runtime"
                / as_of.isoformat()
                / "opportunities"
                / "semiconductor.json"
            ).read_text(encoding="utf-8")
        )
        shortlist = next(
            member
            for member in projection["member_refs"]
            if member["subindustry_id"] == direction_id
        )
        shortlist_codes = shortlist["security_ts_codes"]
        if len(shortlist_codes) != 1:
            raise RuntimeError(
                "structured-smoke Semiconductor eligibility shortlist is not uniquely selectable"
            )
        candidate_ticker = shortlist_codes[0]
        if candidate_ticker != authority_ticker:
            raise RuntimeError(
                "structured-smoke Semiconductor shortlist diverges from validated authority"
            )
        candidate_members = [
            row
            for row in candidate_source_snapshot["eligible_security_universe"]
            if row["ts_code"] == candidate_ticker
            and row["direction_id"] == direction_id
        ]
        if len(candidate_members) != 1:
            raise RuntimeError("structured-smoke Semiconductor shortlist membership is missing")
        candidate_scoring_rows = [
            row
            for row in candidate_source_snapshot["security_scoring_rows"]
            if row["ts_code"] == candidate_ticker
            and row["direction_id"] == direction_id
            and row["availability_status"] == "AVAILABLE"
        ]
        if len(candidate_scoring_rows) != 1:
            raise RuntimeError("structured-smoke Semiconductor shortlist row is unavailable")
        candidate_ref_seed = {
            "accepted_output_id": candidate_source_ref["accepted_output_id"],
            "source_direction_id": direction_id,
            "ts_code": candidate_ticker,
        }
        candidate_evidence_ids = sorted(
            {
                *candidate_source_ref["evidence_ids"],
                f"structured-smoke:eligibility-proof:{candidate_ticker}",
            }
        )
        superinvestor_candidate = {
            "candidate_ref": "runtime-candidate:"
            + _canonical_hash(candidate_ref_seed).removeprefix("sha256:"),
            "ts_code": candidate_ticker,
            "source_output_id": candidate_source_ref["accepted_output_id"],
            "source_output_hash": candidate_source_ref["accepted_output_hash"],
            "source_sector_agent_id": candidate_source_ref["agent_id"],
            "source_direction_id": direction_id,
            "source_direction": "PREFERRED",
            "metrics": {
                "conviction": 0.8,
                "signal_origin": "synthetic_structured_smoke",
            },
            "evidence_ids": candidate_evidence_ids,
        }
        superinvestor_candidates = [superinvestor_candidate]
        candidate_ref = superinvestor_candidate["candidate_ref"]
        proposal_evidence_ids = candidate_evidence_ids
        downstream_evidence_ids = sorted(
            {
                *cio_proposal[0]["evidence_ids"],
                f"structured-smoke:eligibility-proof:{candidate_ticker}",
            }
        )
        position_ref = f"structured-smoke:position:{candidate_ticker}"
        order_intent_ref = f"structured-smoke:order-intent:{candidate_ticker}"
        buy_metrics = {
            "current_weight": 0.0,
            "target_weight": 0.1,
            "delta_weight": 0.1,
            "signal_origin": "synthetic_structured_smoke",
        }
        proposal_candidates = [
            {
                "candidate_ref": candidate_ref,
                "ts_code": candidate_ticker,
                "source_kind": "SECTOR_SELECTION",
                "current_weight": 0.0,
                "reference_target_weight": 0.1,
                "source_output_id": superinvestor_candidate["source_output_id"],
                "source_output_hash": superinvestor_candidate["source_output_hash"],
                "metrics": {
                    **superinvestor_candidate["metrics"],
                    "target_weight": 0.1,
                    "delta_weight": 0.1,
                },
                "evidence_ids": proposal_evidence_ids,
            }
        ]
        cro_candidates = [
            {
                "candidate_ref": candidate_ref,
                "ts_code": candidate_ticker,
                "proposal_position_ref": position_ref,
                "current_weight": 0.0,
                "proposed_target_weight": 0.1,
                "proposed_delta_weight": 0.1,
                "sector_id": superinvestor_candidate["source_sector_agent_id"],
                "metrics": buy_metrics,
                "evidence_ids": downstream_evidence_ids,
            }
        ]
        execution_candidates = [
            {
                "candidate_ref": candidate_ref,
                "ts_code": candidate_ticker,
                "order_intent_ref": order_intent_ref,
                "current_weight": 0.0,
                "target_weight": 0.1,
                "requested_delta_weight": 0.1,
                "side": "BUY",
                "metrics": buy_metrics,
                "evidence_ids": sorted(
                    {*downstream_evidence_ids, cro[0]["evidence_ids"][0]}
                ),
            }
        ]
        final_candidates = [
            {
                "candidate_ref": candidate_ref,
                "ts_code": candidate_ticker,
                "proposal_position_ref": position_ref,
                "current_weight": 0.0,
                "proposed_target_weight": 0.1,
                "proposed_delta_weight": 0.1,
                "metrics": buy_metrics,
                "evidence_ids": downstream_evidence_ids,
            }
        ]
        order_intents = [
            {
                "order_intent_ref": order_intent_ref,
                "ts_code": candidate_ticker,
                "action": "BUY",
                "requested_delta_weight": 0.1,
            }
        ]
    candidate_origin_hash = _canonical_hash(superinvestor_candidates)
    position_snapshot: list[dict[str, Any]] = []
    position_snapshot_hash = _canonical_hash(position_snapshot)
    portfolio_exposure_snapshot = {
        "total_weight": 0.0,
        "sector_weights": {},
    }
    portfolio_exposure_snapshot_hash = _canonical_hash(portfolio_exposure_snapshot)
    cio_upstream = (*macro, *sector, *superinvestors, alpha)
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
                    upstream=(*macro, *sector),
                    constraints={
                        "cash_only": False,
                        "allow_new_positions": True,
                        "max_pick_count": 3,
                        "max_total_conviction": 1.0,
                        "prohibited_ts_codes": [],
                    },
                    role_context={
                        "context_kind": "SUPERINVESTOR_CANDIDATE_SELECTION",
                        "candidate_origin_set_id": "candidate-origin-set:"
                        + candidate_origin_hash.removeprefix("sha256:"),
                        "candidate_origin_set_hash": candidate_origin_hash,
                    },
                    candidate_universe=superinvestor_candidates,
                    candidate_evidence=eligibility_evidence_rows,
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
                    upstream=(*sector, *superinvestors),
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
                        "position_snapshot_hash": position_snapshot_hash,
                        "portfolio_exposure_snapshot_id": (
                            "structured-smoke:portfolio-exposure"
                        ),
                        "portfolio_exposure_snapshot_hash": portfolio_exposure_snapshot_hash,
                    },
                    candidate_universe=cro_candidates,
                    candidate_evidence=eligibility_evidence_rows,
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
                        "order_intent_set_hash": _canonical_hash(order_intents),
                        "liquidity_vintage_hash": _canonical_hash(
                            {"as_of": as_of.isoformat()}
                        ),
                    },
                    candidate_universe=execution_candidates,
                    candidate_evidence=eligibility_evidence_rows,
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
                    upstream=cio_upstream,
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
                        "position_snapshot_hash": position_snapshot_hash,
                        "previous_target_id": None,
                        "previous_target_hash": None,
                    },
                    candidate_universe=proposal_candidates,
                    candidate_evidence=eligibility_evidence_rows,
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
                    upstream=(cio_proposal, cro, autonomous_execution),
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
                        "cro_control_source": _runtime_control_source(cro[0]),
                        "execution_control_source": _runtime_control_source(
                            autonomous_execution[0]
                        ),
                    },
                    candidate_universe=final_candidates,
                    candidate_evidence=eligibility_evidence_rows,
                ),
            ),
        )
    )
    for agent_id, stage, tool_id, snapshot in snapshots:
        _write_json(target / f"{agent_id}.{stage}.{tool_id}.json", snapshot)


def build_structured_smoke_fixtures(
    root: Path,
    as_of_date: str,
    eligibility_artifact_path: Path | None = None,
) -> dict[str, str]:
    as_of = date.fromisoformat(as_of_date)
    eligibility = None
    if eligibility_artifact_path is not None:
        eligibility = _load_eligibility_artifact(
            eligibility_artifact_path.expanduser().resolve(), as_of
        )
    elif as_of < date.fromisoformat(
        SECTOR_ETF_DIRECTION_AUTHORITY["effective_from"]
    ):
        raise RuntimeError(
            "structured-smoke eligibility artifact is required before ETF authority effective_from"
        )
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
    _build_sector_snapshots(
        root,
        as_of,
        eligibility_authority_codes=(
            set(eligibility["authority"]) if eligibility is not None else None
        ),
    )
    sector_archive_path = _build_sector_archive(root, as_of)
    forward_archive_root = _build_forward_archive(root, as_of)
    supply_chain_archive_path = _build_supply_chain_archive(root, as_of)
    china_archive_path = _build_china_archive(root, as_of)
    _build_policy_archive(root, as_of)
    _build_outcome_event_coverage(root, as_of)
    _build_outcome_opportunity_projections(root, as_of)
    _build_runtime_snapshots(root, as_of, eligibility)
    if eligibility_artifact_path is not None:
        copied_artifact = root / _ELIGIBILITY_ARTIFACT_RELATIVE_PATH
        copied_artifact.parent.mkdir(parents=True, exist_ok=True)
        copied_artifact.write_text(
            json.dumps(
                eligibility["payload"], ensure_ascii=False, indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
    artifact_inventory = _fixture_artifact_inventory(root)
    marker = {
        "schema_version": "structured_smoke_fixture_bundle_v1",
        "as_of_date": as_of_date,
        "fixture_class": "SYNTHETIC_NON_PRODUCTION",
        "contains_vendor_prose": False,
        "cache_root": str(root),
        "artifact_inventory": artifact_inventory,
        "artifact_inventory_hash": _canonical_hash(artifact_inventory),
    }
    marker["bundle_hash"] = _canonical_hash(marker)
    _write_json(root / "structured_smoke_fixture_bundle.json", marker)
    return {
        "MOSAIC_CACHE_DIR": str(root),
        "MOSAIC_CHINA_AGENT_ARCHIVE_DB": str(china_archive_path),
        "MOSAIC_FORWARD_ARCHIVE_ROOT": str(forward_archive_root),
        "MOSAIC_GOV_POLICY_CACHE_DIR": str(root / "gov_policy"),
        "MOSAIC_REGISTRY_DIR": str(
            forward_archive_root / "registry/report_intelligence"
        ),
        "MOSAIC_SECTOR_ARCHIVE_PATH": str(sector_archive_path),
        "MOSAIC_SUPPLY_CHAIN_ARCHIVE_PATH": str(supply_chain_archive_path),
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
        "--eligibility-artifact",
        type=Path,
        help="validated point-in-time ETF eligibility artifact",
    )
    parser.add_argument(
        "--shell-exports",
        action="store_true",
        help="print shell-quoted export statements instead of JSON",
    )
    args = parser.parse_args()
    bindings = build_structured_smoke_fixtures(
        args.root, args.date, args.eligibility_artifact
    )
    if args.shell_exports:
        print(render_shell_exports(bindings))
    else:
        print(json.dumps(bindings, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
