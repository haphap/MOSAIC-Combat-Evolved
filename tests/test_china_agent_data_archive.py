from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from mosaic.dataflows.agent_materialization import (
    AgentDataMaterializationLedger,
    SourceCaptureReceipt,
)
from mosaic.dataflows.china_agent_data_archive import (
    CHINA_ROUTE_GROUP,
    COMMODITY_ROUTE_GROUP,
    CURVE_ROUTE_GROUP,
    INSTITUTIONAL_ROUTE_GROUP,
    INSTITUTIONAL_ETF_UNIVERSE,
    _REQUIRED_COMMODITY_FAMILIES,
    ChinaAgentDataArchiveStore,
    archive_china_agent_sources as _archive_china_agent_sources_impl,
    compile_china_agent_snapshot,
    compile_china_agent_snapshots,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.macro_source_contracts import COMMODITY_FAMILY_CONTRACTS
from mosaic.dataflows.official_china_adapters import OFFICIAL_CHINA_DOCUMENT_SPECS
from mosaic.scorecard.canonical_json import canonical_hash


AS_OF = "2026-08-08"
CUTOFF = "2026-08-08T15:00:00+08:00"
SESSION = "20260807"
CAPTURED_AT = datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc)


def _official_curve_fixture(
    *, start_date: str, end_date: str, unavailable: bool = False
) -> dict:
    if unavailable:
        raise DataVendorUnavailable("official curve fixture unavailable")
    return {
        "schema_version": "mof_chinabond_government_yield_curve_v1",
        "provider": "MOF_CHINABOND",
        "source_url": ("https://yield.chinabond.com.cn/cbweb-czb-web/czb/historyQuery"),
        "yield_type": "MATURITY",
        "release_time": "17:30:00+08:00",
        "request_windows": [{"start_date": start_date, "end_date": end_date}],
        "response_hashes": [canonical_hash({"official_curve_date": end_date})],
        "rows": [
            {
                "trade_date": end_date,
                "released_at": f"{end_date}T17:30:00+08:00",
                "curve_type": "0",
                "curve_term": term,
                "yield": 1.5 + term / 25,
            }
            for term in (1, 2, 3, 5, 7, 10, 30)
        ],
    }


def archive_china_agent_sources(**kwargs):
    kwargs.setdefault("fetch_official_curve", _official_curve_fixture)
    return _archive_china_agent_sources_impl(**kwargs)


@pytest.fixture(autouse=True)
def _disable_pagination_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.dataflows import sector_archive

    monkeypatch.setattr(sector_archive.wall_time, "sleep", lambda _seconds: None)


def _observation(
    series_id: str,
    source: str,
    actual: float,
    *,
    unit: str = "percent",
) -> dict:
    return {
        "series_id": series_id,
        "source": source,
        "actual": actual,
        "unit": unit,
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
    }


def _document(document_type: str, observations: list[dict]) -> dict:
    ordinal = len(observations)
    content_hash = canonical_hash({"document_type": document_type, "ordinal": ordinal})
    return {
        "adapter_version": "official_china_adapters_v1",
        "document_type": document_type,
        "provider": "PBOC" if document_type.startswith("pboc_") else "OFFICIAL",
        "document_id": f"{document_type}-202607",
        "source_url": f"https://example.invalid/{document_type}",
        "title": document_type,
        "published_at": "2026-08-07T10:00:00+08:00",
        "release_precision": "SECOND",
        "retrieved_at": "2026-08-08T05:30:00+00:00",
        "content_hash": content_hash,
        "revision_id": f"official-cn-revision:{content_hash.removeprefix('sha256:')}",
        "branches_covered": list(
            OFFICIAL_CHINA_DOCUMENT_SPECS[document_type]["branches"]
        ),
        "observations": observations,
        "raw_payload_b64": "PGh0bWw+Zml4dHVyZTwvaHRtbD4=",
    }


def _official_documents() -> list[dict]:
    return [
        _document(
            "nbs_industrial_activity",
            [
                _observation(
                    "cn_industrial_yoy", "official.nbs_industrial_value_added", 5.1
                )
            ],
        ),
        _document(
            "nbs_fixed_asset_investment",
            [
                _observation(
                    "cn_fixed_asset_investment_yoy",
                    "official.nbs_fixed_asset_investment",
                    3.2,
                )
            ],
        ),
        _document(
            "nbs_retail_sales",
            [_observation("cn_retail_sales_yoy", "official.nbs_retail_sales", 4.0)],
        ),
        _document(
            "nbs_employment_release",
            [
                _observation(
                    "cn_urban_unemployment_rate", "official.nbs_employment_release", 5.0
                )
            ],
        ),
        _document(
            "nbs_cpi_release",
            [
                _observation(
                    "cn_cpi_official_yoy",
                    "official.nbs_price_release_verification",
                    0.6,
                )
            ],
        ),
        _document(
            "nbs_ppi_release",
            [
                _observation(
                    "cn_ppi_official_yoy",
                    "official.nbs_price_release_verification",
                    -0.8,
                )
            ],
        ),
        _document(
            "pboc_financial_statistics",
            [
                _observation(
                    "cn_tsfin_stock_yoy", "official.pboc_tsfin_flow_stock", 8.8
                ),
                _observation(
                    "cn_rmb_loan_flow",
                    "official.pboc_rmb_loans",
                    1.2,
                    unit="trillion_cny",
                ),
                _observation("cn_m2_yoy", "official.pboc_money_stock", 7.1),
            ],
        ),
        _document(
            "pboc_omo_document",
            [_observation("pboc_omo_rate", "official.pboc_omo_catalog", 1.4)],
        ),
        _document(
            "pboc_lpr_document",
            [_observation("pboc_lpr_1y", "official.pboc_lpr_catalog", 3.0)],
        ),
        _document("pboc_mpc_meeting", []),
        _document("pboc_monetary_policy_report", []),
        _document(
            "customs_monthly_trade",
            [
                _observation("cn_trade_total_yoy", "official.customs_total_trade", 5.0),
                _observation(
                    "cn_trade_exports_yoy", "official.customs_partner_trade", 6.0
                ),
                _observation(
                    "cn_trade_imports_yoy", "official.customs_partner_trade", 4.0
                ),
                _observation(
                    "cn_trade_high_tech_exports_yoy",
                    "official.customs_major_goods_trade",
                    3.0,
                ),
            ],
        ),
        _document(
            "mof_fiscal_release",
            [
                _observation(
                    "cn_fiscal_general_budget_yoy",
                    "official.mof_general_public_budget",
                    2.0,
                ),
                _observation(
                    "cn_fiscal_government_fund_yoy",
                    "official.mof_government_fund_budget",
                    -1.0,
                ),
            ],
        ),
    ]


def _contract_rows(
    exchange: str,
    fut_code: str | None = None,
    *,
    deliveries: tuple[str, ...] = ("202610", "202612"),
) -> list[dict]:
    rows = []
    required = {"SC@INE", "CU@SHFE", "AU@SHFE", "C@DCE", "M@DCE"}
    for family_id, contract in COMMODITY_FAMILY_CONTRACTS.items():
        if contract["exchange"] != exchange:
            continue
        if fut_code is None and family_id not in required:
            continue
        if fut_code is not None and contract["product_code"] != fut_code:
            continue
        for delivery in deliveries:
            suffix = delivery[2:]
            product = contract["product_code"]
            rows.append(
                {
                    "ts_code": f"{product}{suffix}.{contract['ts_code_suffix']}",
                    "symbol": f"{product}{suffix}",
                    "exchange": exchange,
                    "name": f"{family_id} {delivery}",
                    "fut_code": product,
                    "multiplier": 10,
                    "trade_unit": "contract",
                    "per_unit": 1,
                    "quote_unit": "CNY",
                    "quote_unit_desc": "cny_per_unit",
                    "d_mode_desc": "physical",
                    "list_date": "20250101",
                    "delist_date": f"{delivery}15",
                    "d_month": delivery,
                    "last_ddate": f"{delivery}20",
                }
            )
    return rows


def _fake_callbacks(
    *,
    deny_curve: bool = True,
    commodity_deliveries: tuple[str, ...] = ("202610", "202612"),
):
    counts: dict[str, int] = {}
    lock = threading.Lock()

    def increment(endpoint: str) -> None:
        with lock:
            counts[endpoint] = counts.get(endpoint, 0) + 1

    def fetch_official(**params: str) -> list[dict]:
        increment("official")
        assert params.pop("cutoff_at") == CUTOFF
        assert params in ({}, {"historical_replay": True})
        return _official_documents()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        increment(endpoint)
        if endpoint == "cn_gdp":
            return [{"quarter": "2026Q2", "gdp_yoy": 5.0}]
        if endpoint == "cn_pmi":
            return [{"month": "202607", "pmi010000": 50.2}]
        if endpoint == "cn_cpi":
            return [{"month": "202607", "nt_yoy": 0.6}]
        if endpoint == "cn_ppi":
            return [{"month": "202607", "ppi_yoy": -0.8}]
        if endpoint == "fut_basic":
            rows = _contract_rows(params["exchange"])
            if params.get("fut_code"):
                rows = [row for row in rows if row["fut_code"] == params["fut_code"]]
            return rows
        if endpoint == "fut_daily":
            requested_code = params.get("ts_code")
            exchanges = (
                ("INE", "SHFE", "DCE")
                if requested_code is not None
                else (params["exchange"],)
            )
            rows = []
            for exchange in exchanges:
                contracts = _contract_rows(exchange, deliveries=commodity_deliveries)
                if requested_code is not None:
                    contracts = [
                        contract
                        for contract in contracts
                        if contract["ts_code"] == requested_code
                    ]
                for contract in contracts:
                    rows.append(
                        {
                            "ts_code": contract["ts_code"],
                            "trade_date": SESSION,
                            "settle": 100.0 + len(rows),
                            "vol": 1000.0,
                            "oi": 2000.0,
                        }
                    )
            return rows
        if endpoint == "fut_wsr":
            if int(params.get("offset", 0)):
                return []
            rows = [
                {
                    "trade_date": SESSION,
                    "symbol": family.split("@", 1)[0],
                    "fut_name": family,
                    "warehouse": "aggregate",
                    "pre_vol": 1100.0,
                    "vol": 1200.0,
                    "vol_chg": 100.0,
                    "unit": "tonnes",
                }
                for family in ("SC@INE", "CU@SHFE", "AU@SHFE", "C@DCE", "M@DCE")
            ]
            if params.get("symbol"):
                rows = [row for row in rows if row["symbol"] == params["symbol"]]
            return rows
        if endpoint == "fund_share":
            return [
                {
                    "ts_code": params["ts_code"],
                    "trade_date": SESSION,
                    "fd_share": 100.0,
                    "fund_type": "ETF",
                    "market": "E",
                },
                {
                    "ts_code": params["ts_code"],
                    "trade_date": "20260708",
                    "fd_share": 90.0,
                    "fund_type": "ETF",
                    "market": "E",
                }
            ]
        if endpoint == "shibor":
            return [{"date": SESSION, "on": 1.4, "3m": 1.6}]
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    return counts, fetch_official, fetch_tushare


def _calendar_receipt(
    route_id: str,
    *,
    captured_at: datetime = CAPTURED_AT,
    as_of_cutoff: str = CUTOFF,
) -> SourceCaptureReceipt:
    payload = {
        "schema_version": "source_capture_receipt_v1",
        "identity": {
            "source_family": "tushare",
            "route_id": route_id,
            "request_hash": canonical_hash(
                {"route_id": route_id, "as_of": as_of_cutoff[:10]}
            ),
            "capture_id": f"test-{route_id}-{as_of_cutoff[:10]}",
        },
        "transport": {
            "redacted_url": "https://api.tushare.pro/<redacted>",
            "method": "POST",
            "query_keys": ["date"],
            "pagination_policy": "SINGLE_PAGE_EXACT_DATE",
            "page_count": 1,
        },
        "authority": {
            "provider": "tushare",
            "permission_tier": "test_fixture",
            "api_version": "pro-v1",
            "parser_version": "eco_cal_parser_v2",
        },
        "time": {
            "released_at": captured_at.isoformat(),
            "vintage_at": captured_at.isoformat(),
            "captured_at": captured_at.isoformat(),
            "knowledge_available_at": captured_at.isoformat(),
        },
        "pit": {
            "pit_mode": "OBSERVED_LIVE",
            "as_of_cutoff": as_of_cutoff,
            "eligible": True,
            "blocker_codes": [],
            "vintage_query": None,
        },
        "content": {
            "raw_content_hash": canonical_hash({"route": route_id}),
            "normalized_row_count": 1,
            "schema_hash": canonical_hash({"schema": "calendar"}),
        },
        "coverage": {
            "requested_start": AS_OF,
            "requested_end": AS_OF,
            "observed_start": AS_OF,
            "observed_end": AS_OF,
            "dimensions": {"route_id": [route_id]},
        },
        "completeness": {
            "truncated": False,
            "next_page_token_present": False,
            "duplicate_count": 0,
            "empty_result_semantics": "NON_EMPTY",
        },
        "provenance": {
            "parent_capture_hash": None,
            "previous_revision_hash": None,
            "revision_reason": None,
        },
    }
    return SourceCaptureReceipt.seal(payload)


def _archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    deny_curve: bool = True,
    captured_at: datetime = CAPTURED_AT,
    historical_replay: bool = False,
):
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(
        china_agent_data_archive, "_capture_now", lambda: captured_at
    )
    store = ChinaAgentDataArchiveStore(tmp_path / "china-agent-data.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    counts, fetch_official, fetch_tushare = _fake_callbacks(deny_curve=deny_curve)
    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        historical_replay=historical_replay,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_official_curve=lambda **params: _official_curve_fixture(
            **params, unavailable=deny_curve
        ),
        fetch_tushare=fetch_tushare,
    )
    return store, ledger, result, counts, fetch_official, fetch_tushare


def test_empty_cache_archives_three_ready_routes_and_official_curve_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, result, counts, _, _ = _archive(tmp_path, monkeypatch)

    assert set(result.routes) == {
        "official.cn_macro+tushare.cn_macro",
        "tushare.commodities",
        "tushare.institutional_flow",
        "composite.cn_rates",
    }
    assert (
        result.routes["official.cn_macro+tushare.cn_macro"].coverage_receipt.as_dict()[
            "coverage_complete"
        ]
        is True
    )
    assert (
        result.routes["tushare.commodities"].coverage_receipt.as_dict()[
            "coverage_complete"
        ]
        is True
    )
    assert (
        result.routes["tushare.institutional_flow"].coverage_receipt.as_dict()[
            "coverage_complete"
        ]
        is True
    )
    curve = result.routes["composite.cn_rates"]
    assert curve.group is None
    assert curve.coverage_receipt.as_dict()["blocker_codes"] == ["SCHEMA_DRIFT"]
    assert store.row_count() == 3
    assert counts["official"] == 1
    assert "yc_cb" not in counts
    assert counts["fund_share"] == len(INSTITUTIONAL_ETF_UNIVERSE)
    assert counts["fut_wsr"] == 5
    assert {
        row["ts_code"]
        for row in result.routes["tushare.institutional_flow"].group["fund_share_rows"]
    } == set(INSTITUTIONAL_ETF_UNIVERSE)
    institutional_group = result.routes["tushare.institutional_flow"].group
    assert counts.get("moneyflow_hsgt", 0) == 0
    assert "moneyflow_ind_ths" not in counts
    assert "daily_basic" not in counts
    assert institutional_group["route_ids"] == [INSTITUTIONAL_ROUTE_GROUP]
    assert "industry_rows" not in institutional_group
    assert "industry_history_rows" not in institutional_group
    assert "crowding_rows" not in institutional_group
    institutional_receipt = result.routes[INSTITUTIONAL_ROUTE_GROUP].source_receipts[0]
    assert institutional_receipt.as_dict()["coverage"]["dimensions"]["endpoint"] == [
        "fund_share"
    ]
    assert institutional_receipt.as_dict()["transport"]["page_count"] == len(
        INSTITUTIONAL_ETF_UNIVERSE
    )
    official_dimensions = (
        result.routes[CHINA_ROUTE_GROUP]
        .source_receipts[0]
        .as_dict()["coverage"]["dimensions"]
    )
    assert set(official_dimensions["document_type"]) == {
        "nbs_industrial_activity",
        "nbs_fixed_asset_investment",
        "nbs_retail_sales",
        "nbs_employment_release",
        "nbs_cpi_release",
        "nbs_ppi_release",
        "pboc_financial_statistics",
        "pboc_omo_document",
        "pboc_lpr_document",
        "pboc_mpc_meeting",
        "pboc_monetary_policy_report",
        "customs_monthly_trade",
        "mof_fiscal_release",
    }
    assert (
        ledger.source_status(as_of=AS_OF, route_id="tushare.commodities")["status"]
        == "READY"
    )
    commodity_receipt = result.routes["tushare.commodities"].source_receipts[0]
    assert commodity_receipt.as_dict()["transport"]["page_count"] == 20


def test_institutional_historical_replay_preserves_real_capture_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    captured_at = datetime(2026, 8, 11, 7, 40, tzinfo=timezone.utc)
    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: captured_at)
    store = ChinaAgentDataArchiveStore(tmp_path / "historical-china.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "historical-ledger.sqlite3")
    counts, fetch_official, fetch_tushare = _fake_callbacks()

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=("tushare.institutional_flow",),
        historical_replay=True,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    route = result.routes[INSTITUTIONAL_ROUTE_GROUP]
    assert route.coverage_receipt.as_dict()["coverage_complete"] is True
    assert route.group is not None
    assert route.group["historical_replay"] is True
    assert route.group["captured_at"] == captured_at.isoformat()
    assert route.group["cutoff_at"] == captured_at.isoformat()
    receipt = route.source_receipts[0].as_dict()
    assert receipt["pit"]["eligible"] is True
    assert receipt["time"]["captured_at"] == captured_at.isoformat()
    assert receipt["pit"]["as_of_cutoff"] == captured_at.isoformat()
    assert set(counts) == {"fund_share"}


def test_institutional_only_archive_and_compiler_close_one_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    captured_at = CAPTURED_AT + timedelta(days=1)
    monkeypatch.setattr(
        china_agent_data_archive,
        "_capture_now",
        lambda: captured_at,
    )
    counts, _, base_fetch_tushare = _fake_callbacks()
    fund_share_requests: list[dict[str, str]] = []

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        if endpoint == "fund_share":
            fund_share_requests.append(dict(params))
        return base_fetch_tushare(endpoint=endpoint, **params)

    store = ChinaAgentDataArchiveStore(tmp_path / "institutional-exact.sqlite3")
    ledger = AgentDataMaterializationLedger(
        tmp_path / "institutional-exact-ledger.sqlite3"
    )
    archived = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=(INSTITUTIONAL_ROUTE_GROUP,),
        historical_replay=True,
        store=store,
        ledger=ledger,
        fetch_tushare=fetch_tushare,
    )
    assert set(archived.routes) == {INSTITUTIONAL_ROUTE_GROUP}
    route = archived.routes[INSTITUTIONAL_ROUTE_GROUP]
    assert route.group is not None
    assert route.coverage_receipt.as_dict()["coverage_complete"] is True
    receipt = route.source_receipts[0].as_dict()
    knowledge_cutoff = datetime.fromisoformat(
        receipt["time"]["knowledge_available_at"]
    )
    validate_role_snapshot = china_agent_data_archive.validate_role_snapshot
    monkeypatch.setattr(
        china_agent_data_archive,
        "validate_role_snapshot",
        lambda raw, role, as_of_date: validate_role_snapshot(
            raw,
            role,
            as_of_date,
            knowledge_cutoff=knowledge_cutoff,
        ),
    )
    built = compile_china_agent_snapshots(
        archive=archived,
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
        requested_roles=("institutional_flow",),
    )
    assert set(built.snapshots) == {"institutional_flow"}
    assert len(built.build_receipts) == 1
    assert len(fund_share_requests) == len(INSTITUTIONAL_ETF_UNIVERSE) == 5
    assert {
        (request["ts_code"], request["start_date"], request["end_date"])
        for request in fund_share_requests
    } == {
        (code, "20260708", "20260807") for code in INSTITUTIONAL_ETF_UNIVERSE
    }
    assert set(counts) == {"fund_share"}
    assert counts.get("moneyflow_hsgt", 0) == 0
    assert counts["fund_share"] == len(INSTITUTIONAL_ETF_UNIVERSE)
    assert "moneyflow_ind_ths" not in counts
    assert "daily_basic" not in counts
    assert receipt["transport"]["page_count"] == 5
    assert receipt["transport"]["query_keys"] == ["end_date", "start_date", "ts_code"]
    assert receipt["content"]["normalized_row_count"] == 5
    assert receipt["coverage"]["dimensions"]["endpoint"] == ["fund_share"]
    assert receipt["coverage"]["dimensions"]["etf"] == list(INSTITUTIONAL_ETF_UNIVERSE)
    raw_rows = archived.routes[INSTITUTIONAL_ROUTE_GROUP].group["fund_share_rows"]
    assert all(
        set(row) == {"ts_code", "latest", "prior", "share_change_pct"}
        for row in raw_rows
    )
    observations = built.snapshots["institutional_flow"]["observations"]
    assert len(observations) == 5
    assert {row["series_id"] for row in observations} == {
        f"etf_share_{code.replace('.', '_')}_change"
        for code in INSTITUTIONAL_ETF_UNIVERSE
    }
    assert all(row["period_start"] == "2026-07-08" for row in observations)
    assert all(row["period_end"] == "2026-08-07" for row in observations)
    assert all(row["unit"] == "percent" for row in observations)
    assert all(row["actual"] == pytest.approx(100 / 9) for row in observations)
    assert store.row_count() == 1


@pytest.mark.parametrize(
    ("route_id", "route_group", "expected_endpoints"),
    (
        ("official.cn_macro", CHINA_ROUTE_GROUP, {"official"}),
        (
            "tushare.cn_macro",
            CHINA_ROUTE_GROUP,
            {"cn_gdp", "cn_pmi", "cn_cpi", "cn_ppi"},
        ),
        (
            COMMODITY_ROUTE_GROUP,
            COMMODITY_ROUTE_GROUP,
            {"fut_basic", "fut_daily", "fut_wsr"},
        ),
        (CURVE_ROUTE_GROUP, CURVE_ROUTE_GROUP, {"shibor"}),
    ),
)
def test_each_remaining_china_route_preserves_historical_replay_capture_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_id: str,
    route_group: str,
    expected_endpoints: set[str],
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    captured_at = datetime(2026, 8, 11, 7, 45, tzinfo=timezone.utc)
    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: captured_at)
    store = ChinaAgentDataArchiveStore(tmp_path / f"historical-{route_id}.sqlite3")
    ledger = AgentDataMaterializationLedger(
        tmp_path / f"historical-{route_id}-ledger.sqlite3"
    )
    counts, fetch_official, fetch_tushare = _fake_callbacks(deny_curve=False)

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=(route_id,),
        historical_replay=True,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    route = result.routes[route_group]
    assert route.coverage_receipt.as_dict()["coverage_complete"] is True
    assert route.group is not None
    assert route.group["route_ids"] == [route_id]
    assert route.group["historical_replay"] is True
    assert route.group["captured_at"] == captured_at.isoformat()
    assert route.group["cutoff_at"] == captured_at.isoformat()
    receipt = route.source_receipts[0].as_dict()
    assert receipt["identity"]["route_id"] == route_id
    assert receipt["time"]["captured_at"] == captured_at.isoformat()
    assert receipt["pit"]["as_of_cutoff"] == captured_at.isoformat()
    assert set(counts) == expected_endpoints
    if route_id == COMMODITY_ROUTE_GROUP:
        availability = {
            contract[field]
            for family in route.group["condition_input"]["families"]
            for contract in family["contracts"]
            for field in (
                "metadata_released_at",
                "metadata_vintage_at",
                "price_released_at",
                "price_vintage_at",
            )
        }
        assert availability == {CUTOFF}


def test_official_historical_replay_accepts_real_retrieval_after_historical_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    captured_at = datetime(2026, 8, 11, 7, 50, tzinfo=timezone.utc)
    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: captured_at)
    documents = _official_documents()
    for document in documents:
        document["retrieved_at"] = captured_at.isoformat()
    store = ChinaAgentDataArchiveStore(tmp_path / "historical-official.sqlite3")
    ledger = AgentDataMaterializationLedger(
        tmp_path / "historical-official-ledger.sqlite3"
    )

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=("official.cn_macro",),
        historical_replay=True,
        store=store,
        ledger=ledger,
        fetch_official=lambda **_params: documents,
        fetch_tushare=lambda **_params: pytest.fail(
            "official route must not call Tushare"
        ),
    )

    route = result.routes[CHINA_ROUTE_GROUP]
    assert route.coverage_receipt.as_dict()["coverage_complete"] is True
    assert route.group is not None
    assert {row["retrieved_at"] for row in route.group["official_documents"]} == {
        captured_at.isoformat()
    }
    receipt = route.source_receipts[0].as_dict()
    assert receipt["time"]["released_at"] < receipt["time"]["captured_at"]
    assert receipt["time"]["captured_at"] == captured_at.isoformat()


@pytest.mark.parametrize(
    ("route_id", "route_group", "expected_endpoints"),
    (
        ("official.cn_macro", CHINA_ROUTE_GROUP, {"official"}),
        (
            "tushare.cn_macro",
            CHINA_ROUTE_GROUP,
            {"cn_gdp", "cn_pmi", "cn_cpi", "cn_ppi"},
        ),
        (
            COMMODITY_ROUTE_GROUP,
            COMMODITY_ROUTE_GROUP,
            {"fut_basic", "fut_daily", "fut_wsr"},
        ),
        (
            INSTITUTIONAL_ROUTE_GROUP,
            INSTITUTIONAL_ROUTE_GROUP,
            {"fund_share"},
        ),
        (CURVE_ROUTE_GROUP, CURVE_ROUTE_GROUP, {"shibor"}),
    ),
)
def test_route_only_capture_calls_only_requested_china_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_id: str,
    route_group: str,
    expected_endpoints: set[str],
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / f"{route_id}.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / f"{route_id}-ledger.sqlite3")
    counts, fetch_official, fetch_tushare = _fake_callbacks(deny_curve=False)

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=(route_id,),
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    assert set(result.routes) == {route_group}
    route = result.routes[route_group]
    assert route.group is not None
    assert route.group["route_ids"] == [route_id]
    assert {
        receipt.as_dict()["identity"]["route_id"] for receipt in route.source_receipts
    } == {route_id}
    coverage = route.coverage_receipt.as_dict()
    assert coverage["required_route_ids"] == [route_id]
    assert coverage["coverage_complete"] is True
    assert set(counts) == expected_endpoints


def test_curve_route_uses_official_mof_curve_and_never_calls_yc_cb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    tushare_calls: list[tuple[str, dict[str, str]]] = []

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        tushare_calls.append((endpoint, params))
        if endpoint == "shibor":
            return [{"date": SESSION, "on": 1.4, "3m": 1.6}]
        pytest.fail(f"curve route must not call Tushare endpoint {endpoint}")

    official_calls: list[tuple[str, str]] = []

    def fetch_official_curve(*, start_date: str, end_date: str) -> dict:
        official_calls.append((start_date, end_date))
        return {
            "schema_version": "mof_chinabond_government_yield_curve_v1",
            "provider": "MOF_CHINABOND",
            "source_url": "https://yield.chinabond.com.cn/cbweb-czb-web/czb/historyQuery",
            "yield_type": "MATURITY",
            "release_time": "17:30:00+08:00",
            "request_windows": [{"start_date": start_date, "end_date": end_date}],
            "response_hashes": [canonical_hash({"fixture": SESSION})],
            "rows": [
                {
                    "trade_date": "2026-08-07",
                    "released_at": "2026-08-07T17:30:00+08:00",
                    "curve_type": "0",
                    "curve_term": term,
                    "yield": 1.5 + term / 25,
                }
                for term in (1, 2, 3, 5, 7, 10, 30)
            ],
        }

    store = ChinaAgentDataArchiveStore(tmp_path / "official-curve.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "official-curve-ledger.sqlite3")
    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=(CURVE_ROUTE_GROUP,),
        store=store,
        ledger=ledger,
        fetch_official_curve=fetch_official_curve,
        fetch_tushare=fetch_tushare,
    )

    route = result.routes[CURVE_ROUTE_GROUP]
    assert route.group is not None
    assert route.group["government_curve_source"]["provider"] == "MOF_CHINABOND"
    assert route.group["government_curve_source"]["yield_type"] == "MATURITY"
    assert official_calls == [("2026-07-08", "2026-08-07")]
    assert {row["curve_term"] for row in route.group["government_curve_rows"]} == {
        1,
        2,
        3,
        5,
        7,
        10,
        30,
    }
    assert tushare_calls == [
        ("shibor", {"start_date": "20260807", "end_date": "20260807"})
    ]
    assert store.row_count() == 1


def test_curve_route_selects_latest_complete_session_released_before_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    tushare_calls: list[dict[str, str]] = []

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        assert endpoint == "shibor"
        tushare_calls.append(params)
        return [{"date": "20260807", "on": 1.4, "3m": 1.6}]

    def fetch_official_curve(*, start_date: str, end_date: str) -> dict:
        return {
            "schema_version": "mof_chinabond_government_yield_curve_v1",
            "provider": "MOF_CHINABOND",
            "source_url": (
                "https://yield.chinabond.com.cn/cbweb-czb-web/czb/historyQuery"
            ),
            "yield_type": "MATURITY",
            "release_time": "17:30:00+08:00",
            "request_windows": [{"start_date": start_date, "end_date": end_date}],
            "response_hashes": [canonical_hash({"fixture": end_date})],
            "rows": [
                {
                    "trade_date": trade_date,
                    "released_at": f"{trade_date}T17:30:00+08:00",
                    "curve_type": "0",
                    "curve_term": term,
                    "yield": 1.5 + term / 25,
                }
                for trade_date in ("2026-08-07", "2026-08-08")
                for term in (1, 2, 3, 5, 7, 10, 30)
            ],
        }

    store = ChinaAgentDataArchiveStore(tmp_path / "curve-cutoff.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "curve-cutoff-ledger.sqlite3")
    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date="20260808",
        requested_route_ids=(CURVE_ROUTE_GROUP,),
        store=store,
        ledger=ledger,
        fetch_official_curve=fetch_official_curve,
        fetch_tushare=fetch_tushare,
    )

    group = result.routes[CURVE_ROUTE_GROUP].group
    assert group is not None
    assert group["market_session_date"] == "2026-08-07"
    assert group["government_curve_source"]["session_released_at"] == (
        "2026-08-07T17:30:00+08:00"
    )
    assert {row["trade_date"] for row in group["government_curve_rows"]} == {
        "2026-08-07"
    }
    assert tushare_calls == [{"start_date": "20260807", "end_date": "20260807"}]


def test_commodity_daily_capture_queries_only_registered_exact_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "commodity-exact.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "commodity-exact-ledger.sqlite3")
    _, fetch_official, base_fetch = _fake_callbacks(deny_curve=False)
    requests: list[tuple[str, dict[str, str]]] = []

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        if endpoint in {"fut_basic", "fut_daily", "fut_wsr"}:
            requests.append((endpoint, dict(params)))
        return base_fetch(endpoint=endpoint, **params)

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=(COMMODITY_ROUTE_GROUP,),
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    assert len(requests) == 20
    assert [endpoint for endpoint, _ in requests].count("fut_basic") == 5
    assert [endpoint for endpoint, _ in requests].count("fut_daily") == 10
    assert [endpoint for endpoint, _ in requests].count("fut_wsr") == 5
    assert all(
        set(params) == {"exchange", "fut_type", "fut_code"}
        for endpoint, params in requests
        if endpoint == "fut_basic"
    )
    expected_family_ids = tuple(_REQUIRED_COMMODITY_FAMILIES)
    expected_codes = sorted(
        row["ts_code"]
        for family_id in expected_family_ids
        for row in _contract_rows(
            COMMODITY_FAMILY_CONTRACTS[family_id]["exchange"],
            COMMODITY_FAMILY_CONTRACTS[family_id]["product_code"],
        )
    )
    daily_requests = [
        params for endpoint, params in requests if endpoint == "fut_daily"
    ]
    assert sorted(request["ts_code"] for request in daily_requests) == expected_codes
    assert all(
        set(request) == {"ts_code", "start_date", "end_date"}
        and request["start_date"] == SESSION
        and request["end_date"] == SESSION
        for request in daily_requests
    )
    inventory_requests = [
        params for endpoint, params in requests if endpoint == "fut_wsr"
    ]
    assert {tuple(sorted(params)) for params in inventory_requests} == {
        ("symbol", "trade_date")
    }
    assert {params["symbol"] for params in inventory_requests} == {
        "SC",
        "CU",
        "AU",
        "C",
        "M",
    }
    receipt = result.routes[COMMODITY_ROUTE_GROUP].source_receipts[0].as_dict()
    assert receipt["transport"]["page_count"] == 20
    assert (
        receipt["transport"]["pagination_policy"] == "EXACT_REQUEST_SET_NO_PAGINATION"
    )
    assert "offset" not in receipt["transport"]["query_keys"]
    assert "limit" not in receipt["transport"]["query_keys"]
    assert (
        result.routes[COMMODITY_ROUTE_GROUP].coverage_receipt.as_dict()[
            "coverage_complete"
        ]
        is True
    )

    _, rejecting_fetch = _fake_callbacks(deny_curve=False)[1:]

    def fetch_with_unrelated_metadata(*, endpoint: str, **params: str) -> list[dict]:
        rows = rejecting_fetch(endpoint=endpoint, **params)
        if endpoint == "fut_basic":
            rows.append(
                {
                    "ts_code": "UNRELATED999.INE",
                    "exchange": params["exchange"],
                    "fut_code": "UNRELATED",
                }
            )
        return rows

    blocked = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=(COMMODITY_ROUTE_GROUP,),
        store=ChinaAgentDataArchiveStore(tmp_path / "commodity-unrelated.sqlite3"),
        ledger=AgentDataMaterializationLedger(
            tmp_path / "commodity-unrelated-ledger.sqlite3"
        ),
        fetch_official=fetch_official,
        fetch_tushare=fetch_with_unrelated_metadata,
    )
    assert blocked.routes[COMMODITY_ROUTE_GROUP].group is None
    assert blocked.routes[COMMODITY_ROUTE_GROUP].coverage_receipt.as_dict()[
        "blocker_codes"
    ] == ["SCHEMA_DRIFT"]


def test_commodity_prepare_and_compiler_bind_only_exact_four_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import agent_stage_preparer

    calendar_routes = (
        "tushare.eco_cal.cny",
        "tushare.eco_cal.eur",
        "tushare.eco_cal.usd",
    )
    calendar_sources = tuple(_calendar_receipt(route) for route in calendar_routes)
    commodity_source = _calendar_receipt(COMMODITY_ROUTE_GROUP)
    prep_calls: list[tuple[str, dict]] = []

    class CompleteCoverage:
        @staticmethod
        def as_dict() -> dict[str, bool]:
            return {"coverage_complete": True}

    def archive_calendar(_fetch: object, **kwargs: object) -> SimpleNamespace:
        prep_calls.append(("calendar", kwargs))
        return SimpleNamespace(
            source_receipts=calendar_sources,
            coverage_receipt=CompleteCoverage(),
        )

    def archive_commodity(**kwargs: object) -> SimpleNamespace:
        prep_calls.append(("commodity", kwargs))
        return SimpleNamespace(
            routes={
                COMMODITY_ROUTE_GROUP: SimpleNamespace(
                    source_receipts=(commodity_source,),
                    coverage_receipt=CompleteCoverage(),
                )
            }
        )

    def compile_commodity(**kwargs: object) -> object:
        prep_calls.append(("compile", kwargs))
        return object()

    monkeypatch.setattr(agent_stage_preparer, "archive_eco_calendar", archive_calendar)
    monkeypatch.setattr(
        agent_stage_preparer, "archive_china_agent_sources", archive_commodity
    )
    monkeypatch.setattr(
        agent_stage_preparer, "ChinaAgentDataArchiveStore", lambda: object()
    )
    monkeypatch.setattr(
        agent_stage_preparer, "compile_china_agent_snapshots", compile_commodity
    )
    monkeypatch.setattr(
        agent_stage_preparer, "snapshot_cache_root", lambda: tmp_path / "snapshots"
    )
    monkeypatch.setattr(agent_stage_preparer, "_stage_capture_now", lambda: CAPTURED_AT)
    prep_ledger = AgentDataMaterializationLedger(tmp_path / "prepare-ledger.sqlite3")
    agent_stage_preparer.prepare_china_agent_family(
        {
            "agent_id": "commodities",
            "stage": "commodities",
            "as_of": AS_OF,
        },
        prep_ledger,
    )

    assert [name for name, _ in prep_calls] == ["calendar", "commodity", "compile"]
    assert prep_calls[0][1]["requested_route_ids"] == calendar_routes
    assert prep_calls[1][1]["requested_route_ids"] == (COMMODITY_ROUTE_GROUP,)
    assert prep_calls[2][1]["requested_roles"] == ("commodities",)
    assert prep_calls[2][1]["exact_calendar_evidence_hashes"] == tuple(
        source.receipt_hash for source in calendar_sources
    )

    monkeypatch.setattr(
        "mosaic.dataflows.china_agent_data_archive._capture_now",
        lambda: CAPTURED_AT + timedelta(days=4),
    )
    store = ChinaAgentDataArchiveStore(tmp_path / "compiler.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "compiler-ledger.sqlite3")
    _, fetch_official, fetch_tushare = _fake_callbacks(deny_curve=False)
    archived = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=(COMMODITY_ROUTE_GROUP,),
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
        historical_replay=True,
    )
    for source in calendar_sources:
        ledger.append_source_capture(source)
    built = compile_china_agent_snapshots(
        archive=archived,
        store=store,
        ledger=ledger,
        output_root=tmp_path / "compiler-snapshots",
        requested_roles=("commodities",),
        exact_calendar_evidence_hashes=tuple(
            source.receipt_hash for source in calendar_sources
        ),
    )
    assert set(built.snapshots) == {"commodities"}
    assert {
        observation["released_at"]
        for observation in built.snapshots["commodities"]["observations"]
    } == {CUTOFF}
    assert {
        observation["vintage_at"]
        for observation in built.snapshots["commodities"]["observations"]
    } == {CUTOFF}
    assert len(built.build_receipts) == 1
    build = built.build_receipts[0].as_dict()
    assert set(build["source_receipt_hashes"]) == {
        archived.routes[COMMODITY_ROUTE_GROUP].source_receipts[0].receipt_hash,
        *(source.receipt_hash for source in calendar_sources),
    }
    assert ledger.row_counts()["snapshot_build_receipts"] == 1
    assert sorted(
        path.name for path in (tmp_path / "compiler-snapshots" / AS_OF).iterdir()
    ) == ["commodities.json"]


def test_partial_macro_capture_does_not_replace_complete_group_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    store, ledger, _, _, _, _ = _archive(tmp_path, monkeypatch, deny_curve=False)
    later = CAPTURED_AT + timedelta(minutes=1)
    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: later)
    _, fetch_official, fetch_tushare = _fake_callbacks(deny_curve=False)

    partial = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=("official.cn_macro",),
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    assert partial.routes[CHINA_ROUTE_GROUP].group is not None
    assert partial.routes[CHINA_ROUTE_GROUP].group["route_ids"] == ["official.cn_macro"]
    assert store.load_route_group(AS_OF, CHINA_ROUTE_GROUP)["route_ids"] == [
        "official.cn_macro",
        "tushare.cn_macro",
    ]


def test_private_tushare_transport_normalizes_dataframe_to_row_dicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    class Frame:
        normalized = False

        def astype(self, dtype: object) -> Frame:
            assert dtype is object
            return self

        def notna(self) -> object:
            return object()

        def where(self, condition: object, replacement: None) -> Frame:
            assert condition is not None
            assert replacement is None
            self.normalized = True
            return self

        def to_dict(self, *, orient: str) -> list[dict]:
            assert orient == "records"
            return [
                {
                    "trade_date": SESSION,
                    "ts_code": "000001.SZ",
                    "net_mf_amount": 1.0,
                    "optional": None if self.normalized else float("nan"),
                }
            ]

    monkeypatch.setattr(
        china_agent_data_archive,
        "assert_endpoint_capture_preflight_allowed",
        lambda endpoint: None,
    )
    monkeypatch.setattr(
        china_agent_data_archive,
        "_query_pro",
        lambda endpoint, **params: Frame(),
    )

    assert china_agent_data_archive._private_tushare_fetch(
        endpoint="moneyflow", ts_code="000001.SZ", trade_date=SESSION
    ) == [
        {
            "trade_date": SESSION,
            "ts_code": "000001.SZ",
            "net_mf_amount": 1.0,
            "optional": None,
        }
    ]


def test_china_macro_capture_binds_exact_period_fields_and_nine_official_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    as_of = AS_OF
    cutoff = CUTOFF
    monkeypatch.setattr(
        china_agent_data_archive,
        "_capture_now",
        lambda: datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc),
    )
    store = ChinaAgentDataArchiveStore(tmp_path / "china-exact.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "china-exact-ledger.sqlite3")
    official_calls: list[dict[str, object]] = []
    macro_calls: dict[str, dict[str, str]] = {}
    macro_call_counts: dict[str, int] = {}
    china_documents = {
        "nbs_industrial_activity",
        "nbs_fixed_asset_investment",
        "nbs_retail_sales",
        "nbs_employment_release",
        "nbs_cpi_release",
        "nbs_ppi_release",
        "pboc_financial_statistics",
        "customs_monthly_trade",
        "mof_fiscal_release",
    }

    def fetch_official(**params: object) -> list[dict]:
        official_calls.append(params)
        assert set(params["document_types"]) == china_documents
        documents = _official_documents()
        for document in documents:
            document["published_at"] = "2026-07-16T10:00:00+08:00"
            document["retrieved_at"] = "2026-07-17T05:30:00+00:00"
            for observation in document["observations"]:
                observation["period_start"] = "2026-06-01"
                observation["period_end"] = "2026-06-30"
        return [
            row
            for row in documents
            if row["document_type"] in china_documents
        ]

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        if endpoint in {"cn_gdp", "cn_pmi", "cn_cpi", "cn_ppi"}:
            macro_calls[endpoint] = dict(params)
            macro_call_counts[endpoint] = macro_call_counts.get(endpoint, 0) + 1
        return {
            "cn_gdp": [{"quarter": "2026Q2", "gdp_yoy": 5.0}],
            "cn_pmi": [{"month": "202607", "pmi010000": 50.2}],
            "cn_cpi": [{"month": "202607", "nt_yoy": 0.6}],
            "cn_ppi": [{"month": "202607", "ppi_yoy": -0.8}],
        }[endpoint]

    result = archive_china_agent_sources(
        as_of_date=as_of,
        cutoff_at=cutoff,
        market_session_date=as_of,
        requested_route_ids=("official.cn_macro", "tushare.cn_macro"),
        official_document_types=tuple(sorted(china_documents)),
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    coverage = result.routes[CHINA_ROUTE_GROUP].coverage_receipt.as_dict()
    assert coverage["coverage_complete"] is True, coverage
    assert official_calls == [
        {
            "cutoff_at": cutoff,
            "document_types": tuple(sorted(china_documents)),
        }
    ]
    assert macro_calls == {
        "cn_gdp": {
            "q": "2026Q2",
            "fields": "quarter,gdp_yoy",
        },
        "cn_pmi": {"m": "202607", "fields": "month,pmi010000"},
        "cn_cpi": {"m": "202607", "fields": "month,nt_yoy"},
        "cn_ppi": {"m": "202607", "fields": "month,ppi_yoy"},
    }
    assert macro_call_counts["cn_gdp"] == 1
    china = result.routes[CHINA_ROUTE_GROUP].group
    assert china is not None
    gdp = next(
        row
        for row in china["tushare_observations"]
        if row["series_id"] == "cn_gdp_yoy"
    )
    assert gdp["period_end"] == "2026-06-30"
    with pytest.raises(china_agent_data_archive.ChinaAgentDataSchemaError):
        china_agent_data_archive._latest_macro_observation(
            "cn_gdp",
            [
                {"quarter": "2026Q2", "gdp_yoy": 5.0},
                {"quarter": "2026Q2", "gdp_yoy": 5.1},
            ],
            as_of=datetime(2026, 8, 8).date(),
            captured_at=CAPTURED_AT.isoformat(),
        )
    tushare_receipt = result.routes[CHINA_ROUTE_GROUP].source_receipts[1].as_dict()
    assert set(tushare_receipt["coverage"]["dimensions"]["request_params"]) == {
        "cn_cpi:fields=month,nt_yoy&m=202607",
        "cn_gdp:fields=quarter,gdp_yoy&q=2026Q2",
        "cn_pmi:fields=month,pmi010000&m=202607",
        "cn_ppi:fields=month,ppi_yoy&m=202607",
    }


def test_china_compiler_uses_group_receipt_when_latest_scope_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "scope-drift.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "scope-drift-ledger.sqlite3")
    _, base_official, fetch_tushare = _fake_callbacks()
    all_documents = _official_documents()
    china_documents = tuple(
        sorted(
            {
                "nbs_industrial_activity",
                "nbs_fixed_asset_investment",
                "nbs_retail_sales",
                "nbs_employment_release",
                "nbs_cpi_release",
                "nbs_ppi_release",
                "pboc_financial_statistics",
                "customs_monthly_trade",
                "mof_fiscal_release",
            }
        )
    )

    def fetch_official(**params: object) -> list[dict]:
        document_types = params.pop("document_types", None)
        assert params == {"cutoff_at": CUTOFF}
        return [
            row
            for row in all_documents
            if document_types is None or row["document_type"] in document_types
        ]

    first = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=("official.cn_macro", "tushare.cn_macro"),
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )
    second = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=("official.cn_macro", "tushare.cn_macro"),
        official_document_types=china_documents,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )
    ledger.append_source_capture(_calendar_receipt("tushare.eco_cal.cny"))

    first_receipt_hash = next(
        receipt.receipt_hash
        for receipt in first.routes[CHINA_ROUTE_GROUP].source_receipts
        if receipt.as_dict()["identity"]["route_id"] == "official.cn_macro"
    )
    second_receipt_hash = next(
        receipt.receipt_hash
        for receipt in second.routes[CHINA_ROUTE_GROUP].source_receipts
        if receipt.as_dict()["identity"]["route_id"] == "official.cn_macro"
    )
    assert first_receipt_hash != second_receipt_hash
    built = compile_china_agent_snapshot(
        archive=first,
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
    )
    assert set(built.snapshots) == {"china"}
    assert first_receipt_hash in built.build_receipts[0].as_dict()[
        "source_receipt_hashes"
    ]
    assert second_receipt_hash not in built.build_receipts[0].as_dict()[
        "source_receipt_hashes"
    ]


def test_historical_null_macro_value_does_not_hide_latest_valid_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "historical-null.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "historical-null-ledger.sqlite3")
    _, fetch_official, base_fetch = _fake_callbacks()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        if endpoint == "cn_gdp":
            return [
                {"quarter": "1952Q4", "gdp_yoy": None},
                {"quarter": "2026Q2", "gdp_yoy": 5.0},
            ]
        return base_fetch(endpoint=endpoint, **params)

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    china = result.routes[CHINA_ROUTE_GROUP]
    assert china.group is not None
    gdp = next(
        row
        for row in china.group["tushare_observations"]
        if row["series_id"] == "cn_gdp_yoy"
    )
    assert gdp["period_end"] == "2026-06-30"
    assert gdp["actual"] == 5.0


def test_physical_commodity_contract_uses_documented_per_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "per-unit.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "per-unit-ledger.sqlite3")
    _, fetch_official, base_fetch = _fake_callbacks()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        rows = base_fetch(endpoint=endpoint, **params)
        if endpoint == "fut_basic":
            for row in rows:
                row["multiplier"] = None
                row["per_unit"] = 10
        return rows

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    commodity = result.routes["tushare.commodities"]
    assert commodity.group is not None
    assert {
        contract["multiplier"]
        for family in commodity.group["condition_input"]["families"]
        for contract in family["contracts"]
    } == {10.0}


def test_commodity_does_not_fetch_third_contract_when_first_two_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "zero-volume.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "zero-volume-ledger.sqlite3")
    _, fetch_official, base_fetch = _fake_callbacks()
    daily_requests: list[str] = []

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        rows = base_fetch(endpoint=endpoint, **params)
        if endpoint == "fut_basic" and params["exchange"] == "INE":
            third = dict(rows[-1])
            third.update(
                {
                    "ts_code": "SC2701.INE",
                    "symbol": "SC2701",
                    "name": "SC@INE 202701",
                    "d_month": "202701",
                    "delist_date": "20270115",
                    "last_ddate": "20270120",
                }
            )
            rows.append(third)
        if endpoint == "fut_daily":
            daily_requests.append(params["ts_code"])
            if params["ts_code"] == "SC2610.INE":
                rows[0]["vol"] = 0.0
        return rows

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    commodity = result.routes["tushare.commodities"]
    assert commodity.group is None
    assert commodity.coverage_receipt.as_dict()["blocker_codes"] == ["SCHEMA_DRIFT"]
    assert len(daily_requests) == 10
    assert "SC2701.INE" not in daily_requests


def test_commodity_blocks_when_filtering_leaves_fewer_than_two_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "one-traded-contract.sqlite3")
    ledger = AgentDataMaterializationLedger(
        tmp_path / "one-traded-contract-ledger.sqlite3"
    )
    _, fetch_official, base_fetch = _fake_callbacks()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        rows = base_fetch(endpoint=endpoint, **params)
        if endpoint == "fut_daily" and params["ts_code"] == "SC2610.INE":
            rows[0]["vol"] = 0.0
        return rows

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    commodity = result.routes["tushare.commodities"]
    assert commodity.group is None
    assert commodity.coverage_receipt.as_dict()["blocker_codes"] == ["SCHEMA_DRIFT"]


def test_commodity_inventory_derives_previous_from_documented_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "inventory-derived.sqlite3")
    ledger = AgentDataMaterializationLedger(
        tmp_path / "inventory-derived-ledger.sqlite3"
    )
    _, fetch_official, base_fetch = _fake_callbacks()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        rows = base_fetch(endpoint=endpoint, **params)
        if endpoint == "fut_wsr":
            for row in rows:
                row["pre_vol"] = None
                row["vol_chg"] = 100.0
        return rows

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    commodity = result.routes["tushare.commodities"]
    assert commodity.group is not None
    assert {
        family["inventory"]["previous"]
        for family in commodity.group["condition_input"]["families"]
    } == {1100.0}


def test_commodity_inventory_blocks_family_without_direct_or_derivable_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "inventory-unusable.sqlite3")
    ledger = AgentDataMaterializationLedger(
        tmp_path / "inventory-unusable-ledger.sqlite3"
    )
    _, fetch_official, base_fetch = _fake_callbacks()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        rows = base_fetch(endpoint=endpoint, **params)
        if endpoint == "fut_wsr" and params.get("symbol") == "SC" and rows:
            target = rows[0]
            target["pre_vol"] = None
            target["vol_chg"] = None
        return rows

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    commodity = result.routes["tushare.commodities"]
    assert commodity.group is None
    assert commodity.coverage_receipt.as_dict()["blocker_codes"] == ["SCHEMA_DRIFT"]


def test_warm_retry_and_concurrent_same_key_are_zero_extra_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "china-agent-data.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    counts, fetch_official, fetch_tushare = _fake_callbacks(deny_curve=False)

    def capture():
        return archive_china_agent_sources(
            as_of_date=AS_OF,
            cutoff_at=CUTOFF,
            market_session_date=SESSION,
            store=store,
            ledger=ledger,
            fetch_official=fetch_official,
            fetch_tushare=fetch_tushare,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: capture(), range(4)))
    before = dict(counts)
    replay = capture()

    assert counts == before
    assert store.row_count() == 4
    assert all(route.cache_hit for route in replay.routes.values())
    assert (
        len(
            {
                tuple(
                    sorted(
                        (route_id, route.group["group_hash"])
                        for route_id, route in result.routes.items()
                    )
                )
                for result in results
            }
        )
        == 1
    )


def test_historical_forward_archive_miss_is_zero_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(
        china_agent_data_archive,
        "_capture_now",
        lambda: CAPTURED_AT + timedelta(days=1),
    )
    store = ChinaAgentDataArchiveStore(tmp_path / "china-agent-data.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    counts, fetch_official, fetch_tushare = _fake_callbacks()

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    assert counts == {}
    assert store.row_count() == 0
    assert all(route.group is None for route in result.routes.values())
    assert {
        blocker
        for route in result.routes.values()
        for blocker in route.coverage_receipt.as_dict()["blocker_codes"]
    } == {"CAPTURE_AFTER_AS_OF_CUTOFF"}


def test_future_as_of_window_is_rejected_before_transport_or_archive_insert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "china-agent-data.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    counts, fetch_official, fetch_tushare = _fake_callbacks()

    result = archive_china_agent_sources(
        as_of_date="2026-08-09",
        cutoff_at="2026-08-09T15:00:00+08:00",
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    assert counts == {}
    assert store.row_count() == 0
    assert all(route.group is None for route in result.routes.values())
    assert {
        blocker
        for route in result.routes.values()
        for blocker in route.coverage_receipt.as_dict()["blocker_codes"]
    } == {"CAPTURE_BEFORE_AS_OF_WINDOW"}


def test_partial_commodity_schema_failure_rolls_back_only_that_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "china-agent-data.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    counts, fetch_official, base_fetch = _fake_callbacks()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        rows = base_fetch(endpoint=endpoint, **params)
        if endpoint == "fut_daily" and params["ts_code"] == "SC2610.INE":
            rows[0].pop("settle")
        return rows

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    commodity = result.routes["tushare.commodities"]
    assert commodity.group is None
    assert commodity.source_receipts == ()
    assert commodity.coverage_receipt.as_dict()["blocker_codes"] == ["SCHEMA_DRIFT"]
    assert result.routes["tushare.institutional_flow"].group is not None
    assert store.row_count() == 3
    assert counts["fut_daily"] >= 1


def test_official_document_branch_drift_blocks_only_china_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "china-agent-data.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    counts, _, fetch_tushare = _fake_callbacks()

    def fetch_official(**params: str) -> list[dict]:
        counts["official"] = counts.get("official", 0) + 1
        documents = _official_documents()
        documents[0]["branches_covered"] = []
        return documents

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    china = result.routes[CHINA_ROUTE_GROUP]
    assert china.group is None
    assert china.coverage_receipt.as_dict()["blocker_codes"] == ["SCHEMA_DRIFT"]
    assert result.routes["tushare.commodities"].group is not None


@pytest.mark.parametrize(
    ("target_endpoint", "hard_cap", "blocked_route"),
    [
        ("fut_basic", 10_000, "tushare.commodities"),
    ],
)
def test_exact_endpoint_hard_caps_fail_closed_without_terminal_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_endpoint: str,
    hard_cap: int,
    blocked_route: str,
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / f"{target_endpoint}.sqlite3")
    ledger = AgentDataMaterializationLedger(
        tmp_path / f"{target_endpoint}-ledger.sqlite3"
    )
    _, fetch_official, base_fetch = _fake_callbacks(deny_curve=False)

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        rows = base_fetch(endpoint=endpoint, **params)
        if (
            target_endpoint == "fut_basic"
            and endpoint == "fut_basic"
            and params["exchange"] == "INE"
        ):
            return rows + [
                {
                    "ts_code": f"IGNORED{index}.INE",
                    "exchange": "INE",
                    "fut_code": "IGNORED",
                }
                for index in range(hard_cap - len(rows))
            ]
        return rows

    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    assert result.routes[blocked_route].group is None
    assert result.routes[blocked_route].coverage_receipt.as_dict()["blocker_codes"] == [
        "SCHEMA_DRIFT"
    ]


def test_archive_payload_hash_tamper_is_rejected_on_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _, archived, _, _, _ = _archive(tmp_path, monkeypatch, deny_curve=False)
    capture_key = archived.routes[CHINA_ROUTE_GROUP].group["capture_key"]
    with sqlite3.connect(store.path) as conn:
        conn.execute("DROP TRIGGER china_agent_capture_groups_no_update")
        conn.execute(
            "UPDATE china_agent_capture_groups SET group_hash = ? WHERE capture_key = ?",
            ("sha256:" + "0" * 64, capture_key),
        )

    with pytest.raises(ValueError, match="group hash mismatch"):
        store.load_group(capture_key)


def test_compiler_rejects_source_receipt_drift_from_frozen_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _, archived, _, _, _ = _archive(tmp_path, monkeypatch, deny_curve=False)
    drift_ledger = AgentDataMaterializationLedger(tmp_path / "drift-ledger.sqlite3")
    for route in archived.routes.values():
        for receipt in route.source_receipts:
            if receipt.as_dict()["identity"]["route_id"] == "official.cn_macro":
                payload = receipt.as_dict()
                payload["content"]["raw_content_hash"] = canonical_hash(
                    {"tampered": True}
                )
                receipt = SourceCaptureReceipt.seal(payload)
            drift_ledger.append_source_capture(receipt)

    with pytest.raises(DataVendorUnavailable, match="source receipt drift"):
        compile_china_agent_snapshots(
            archive=archived,
            store=store,
            ledger=drift_ledger,
            output_root=tmp_path / "snapshots",
        )


def test_compiler_publishes_three_ready_snapshots_and_repeatable_blocked_central_bank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, archived, counts, _, _ = _archive(tmp_path, monkeypatch)
    for route_id in (
        "tushare.eco_cal.cny",
        "tushare.eco_cal.eur",
        "tushare.eco_cal.usd",
    ):
        ledger.append_source_capture(_calendar_receipt(route_id))
    before = dict(counts)

    built = compile_china_agent_snapshots(
        archive=archived,
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
    )
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(
        china_agent_data_archive,
        "_capture_now",
        lambda: CAPTURED_AT + timedelta(seconds=1),
    )
    replay = compile_china_agent_snapshots(
        archive=archived,
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
    )
    import json

    from mosaic.dataflows.macro_snapshots import (
        load_role_snapshot,
        validate_role_snapshot,
    )

    for role, snapshot in built.snapshots.items():
        persisted = json.loads(
            (
                tmp_path / "snapshots" / snapshot["as_of_date"] / f"{role}.json"
            ).read_text(encoding="utf-8")
        )
        assert (
            validate_role_snapshot(persisted, role, snapshot["as_of_date"]) == snapshot
        )

    assert (
        load_role_snapshot(
            "institutional_flow",
            AS_OF,
            root=tmp_path / "snapshots",
            ledger=ledger,
        )
        == built.snapshots["institutional_flow"]
    )
    institutional_path = tmp_path / "snapshots" / AS_OF / "institutional_flow.json"
    tampered = json.loads(institutional_path.read_text(encoding="utf-8"))
    tampered["observations"][0]["actual"] = 123456.0
    institutional_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(
        DataVendorUnavailable,
        match="MACRO_SNAPSHOT_BUILD_RECEIPT_MISMATCH:institutional_flow",
    ):
        load_role_snapshot(
            "institutional_flow",
            AS_OF,
            root=tmp_path / "snapshots",
            ledger=ledger,
        )

    assert counts == before
    assert set(built.snapshots) == {"china", "commodities", "institutional_flow"}
    assert set(built.snapshots["commodities"]["commodity_conditions"]["families"]) == {
        "SC@INE",
        "CU@SHFE",
        "AU@SHFE",
        "C@DCE",
        "M@DCE",
    }
    assert set(built.snapshots["institutional_flow"]["component_coverage"]) == {
        "etf_share",
    }
    assert len(INSTITUTIONAL_ETF_UNIVERSE) >= 5
    by_role = {
        receipt.as_dict()["agent_id"]: receipt.as_dict()
        for receipt in built.build_receipts
    }
    assert by_role["central_bank"]["terminal_state"] == "BLOCKED"
    assert by_role["central_bank"]["output_hash"] is None
    assert by_role["central_bank"]["missing_route_ids"] == ["composite.cn_rates"]
    assert [receipt.receipt_hash for receipt in replay.build_receipts] == [
        receipt.receipt_hash for receipt in built.build_receipts
    ]
    assert ledger.row_counts()["snapshot_build_receipts"] == 4


def test_compiler_publishes_ready_central_bank_when_curve_route_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mosaic.dataflows.china_agent_data_archive._capture_now",
        lambda: CAPTURED_AT,
    )
    store = ChinaAgentDataArchiveStore(tmp_path / "china-agent-data.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    counts, _, fetch_tushare = _fake_callbacks(deny_curve=False)
    central_document_types = (
        "nbs_cpi_release",
        "nbs_industrial_activity",
        "nbs_ppi_release",
        "pboc_financial_statistics",
        "pboc_lpr_document",
        "pboc_omo_document",
    )
    documents_by_type = {row["document_type"]: row for row in _official_documents()}

    def fetch_official(**params: str) -> list[dict]:
        counts["official"] = counts.get("official", 0) + 1
        assert params.pop("cutoff_at") == CUTOFF
        assert tuple(params.pop("document_types")) == central_document_types
        assert params == {}
        return [
            documents_by_type[document_type] for document_type in central_document_types
        ]

    archived = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        requested_route_ids=("composite.cn_rates", "official.cn_macro"),
        official_document_types=central_document_types,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_official_curve=_official_curve_fixture,
        fetch_tushare=fetch_tushare,
    )
    assert set(archived.routes) == {CHINA_ROUTE_GROUP, CURVE_ROUTE_GROUP}
    assert set(
        archived.routes[CHINA_ROUTE_GROUP]
        .source_receipts[0]
        .as_dict()["coverage"]["dimensions"]["document_type"]
    ) == set(central_document_types)
    assert not any(endpoint.startswith("cn_") for endpoint in counts)

    calendar_receipt = _calendar_receipt("tushare.eco_cal.cny")
    ledger.append_source_capture(calendar_receipt)
    before = dict(counts)
    before_build_receipts = ledger.row_counts()["snapshot_build_receipts"]

    built = compile_china_agent_snapshots(
        archive=archived,
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
        requested_roles=("central_bank",),
        exact_calendar_evidence_hash=calendar_receipt.receipt_hash,
    )

    assert counts == before
    assert set(built.snapshots) == {"central_bank"}
    assert {row.as_dict()["agent_id"] for row in built.build_receipts} == {
        "central_bank"
    }
    assert ledger.row_counts()["snapshot_build_receipts"] == before_build_receipts + 1
    for role in ("china", "commodities", "institutional_flow"):
        assert not (tmp_path / "snapshots" / AS_OF / f"{role}.json").exists()
    assert (tmp_path / "snapshots" / AS_OF / "central_bank.json").exists()
    central = built.snapshots["central_bank"]
    assert {row["series_id"] for row in central["observations"]} >= {
        "pboc_omo_rate",
        "pboc_lpr_1y",
        "cn_curve_2y",
        "cn_curve_10y",
    }
    receipt = next(
        row.as_dict()
        for row in built.build_receipts
        if row.as_dict()["agent_id"] == "central_bank"
    )
    assert receipt["terminal_state"] == "READY"
    assert receipt["missing_route_ids"] == []
    assert receipt["output_hash"] == central["snapshot_hash"]
    assert calendar_receipt.receipt_hash in receipt["source_receipt_hashes"]
    omo = next(
        row for row in central["observations"] if row["series_id"] == "pboc_omo_rate"
    )
    assert omo["released_at"] == "2026-08-07T10:00:00+08:00"
    assert omo["vintage_at"] == CAPTURED_AT.isoformat()
    credit = next(
        row
        for row in central["observations"]
        if row["series_id"] == "cn_credit_summary_tsfin"
    )
    assert credit["released_at"] == "2026-08-07T10:00:00+08:00"
    assert credit["vintage_at"] == CAPTURED_AT.isoformat()
    shibor = {
        row["series_id"]: row
        for row in central["observations"]
        if row["series_id"]
        in {"domestic_liquidity_shibor_overnight", "money_market_shibor_3m"}
    }
    assert {row["released_at"] for row in shibor.values()} == {
        CAPTURED_AT.isoformat()
    }
    curve = {
        row["series_id"]: row
        for row in central["observations"]
        if row["series_id"] in {"cn_curve_2y", "cn_curve_10y"}
    }
    assert {row["released_at"] for row in curve.values()} == {
        "2026-08-07T17:30:00+08:00"
    }
    import json

    persisted = json.loads(
        (tmp_path / "snapshots" / AS_OF / "central_bank.json").read_text(
            encoding="utf-8"
        )
    )
    context_credit = next(
        row
        for row in persisted["context_observations"]
        if row["series_id"] == "china_credit_rmb_loan_flow"
    )
    assert context_credit["released_at"] == "2026-08-07T10:00:00+08:00"
    assert context_credit["vintage_at"] == CAPTURED_AT.isoformat()
    assert len(built.build_receipts) == 1
