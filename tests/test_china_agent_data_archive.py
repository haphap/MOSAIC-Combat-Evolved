from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mosaic.dataflows.agent_materialization import (
    AgentDataMaterializationLedger,
    SourceCaptureReceipt,
)
from mosaic.dataflows.china_agent_data_archive import (
    CHINA_ROUTE_GROUP,
    INSTITUTIONAL_ETF_UNIVERSE,
    ChinaAgentDataArchiveStore,
    archive_china_agent_sources,
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
            [_observation("cn_industrial_yoy", "official.nbs_industrial_value_added", 5.1)],
        ),
        _document(
            "nbs_fixed_asset_investment",
            [_observation("cn_fixed_asset_investment_yoy", "official.nbs_fixed_asset_investment", 3.2)],
        ),
        _document(
            "nbs_retail_sales",
            [_observation("cn_retail_sales_yoy", "official.nbs_retail_sales", 4.0)],
        ),
        _document(
            "nbs_employment_release",
            [_observation("cn_urban_unemployment_rate", "official.nbs_employment_release", 5.0)],
        ),
        _document(
            "nbs_cpi_release",
            [_observation("cn_cpi_official_yoy", "official.nbs_price_release_verification", 0.6)],
        ),
        _document(
            "nbs_ppi_release",
            [_observation("cn_ppi_official_yoy", "official.nbs_price_release_verification", -0.8)],
        ),
        _document(
            "pboc_financial_statistics",
            [
                _observation("cn_tsfin_stock_yoy", "official.pboc_tsfin_flow_stock", 8.8),
                _observation("cn_rmb_loan_flow", "official.pboc_rmb_loans", 1.2, unit="trillion_cny"),
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
                _observation("cn_trade_exports_yoy", "official.customs_partner_trade", 6.0),
                _observation("cn_trade_imports_yoy", "official.customs_partner_trade", 4.0),
                _observation("cn_trade_high_tech_exports_yoy", "official.customs_major_goods_trade", 3.0),
            ],
        ),
        _document(
            "mof_fiscal_release",
            [
                _observation("cn_fiscal_general_budget_yoy", "official.mof_general_public_budget", 2.0),
                _observation("cn_fiscal_government_fund_yoy", "official.mof_government_fund_budget", -1.0),
            ],
        ),
    ]


def _contract_rows(exchange: str) -> list[dict]:
    rows = []
    required = {"SC@INE", "CU@SHFE", "AU@SHFE", "C@DCE", "M@DCE"}
    for family_id, contract in COMMODITY_FAMILY_CONTRACTS.items():
        if family_id not in required or contract["exchange"] != exchange:
            continue
        for delivery, suffix in (("202610", "2610"), ("202612", "2612")):
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


def _fake_callbacks(*, deny_curve: bool = True):
    counts: dict[str, int] = {}
    lock = threading.Lock()

    def increment(endpoint: str) -> None:
        with lock:
            counts[endpoint] = counts.get(endpoint, 0) + 1

    def fetch_official(**params: str) -> list[dict]:
        increment("official")
        assert params == {"cutoff_at": CUTOFF}
        return _official_documents()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        increment(endpoint)
        if endpoint == "cn_gdp":
            return [{"quarter": "2026Q2", "gdp_yoy": 5.0}]
        if endpoint == "cn_pmi":
            return [{"MONTH": "202607", "PMI010000": 50.2}]
        if endpoint == "cn_cpi":
            return [{"month": "202607", "nt_yoy": 0.6}]
        if endpoint == "cn_ppi":
            return [{"month": "202607", "ppi_yoy": -0.8}]
        if endpoint == "fut_basic":
            return _contract_rows(params["exchange"])
        if endpoint == "fut_daily":
            rows = []
            for contract in _contract_rows(params["exchange"]):
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
            return [
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
        if endpoint == "moneyflow_hsgt":
            return [{"trade_date": SESSION, "north_money": 12.5, "hgt": 6.0, "sgt": 6.5}]
        if endpoint == "moneyflow_ind_ths":
            if int(params.get("offset", 0)):
                return []
            return [
                {
                    "trade_date": SESSION,
                    "ts_code": "881155.TI",
                    "industry": "银行",
                    "lead_stock": "浦发银行",
                    "close": 100.0,
                    "pct_change": 1.0,
                    "company_num": 42,
                    "pct_change_stock": 2.0,
                    "close_price": 12.0,
                    "net_buy_amount": 20.0,
                    "net_sell_amount": 10.0,
                    "net_amount": 10.0,
                },
                {
                    "trade_date": SESSION,
                    "ts_code": "881121.TI",
                    "industry": "电子",
                    "lead_stock": "海康威视",
                    "close": 90.0,
                    "pct_change": -1.0,
                    "company_num": 50,
                    "pct_change_stock": -2.0,
                    "close_price": 20.0,
                    "net_buy_amount": 8.0,
                    "net_sell_amount": 10.0,
                    "net_amount": -2.0,
                },
            ]
        if endpoint == "fund_share":
            return [
                {
                    "ts_code": params["ts_code"],
                    "trade_date": SESSION,
                    "fd_share": 100.0,
                    "fund_type": "ETF",
                    "market": "E",
                }
            ]
        if endpoint == "daily_basic":
            return [
                {"ts_code": "000001.SZ", "trade_date": SESSION, "turnover_rate": 2.0, "volume_ratio": 1.1},
                {"ts_code": "600000.SH", "trade_date": SESSION, "turnover_rate": 1.5, "volume_ratio": 0.9},
            ]
        if endpoint == "shibor":
            return [{"date": SESSION, "on": 1.4, "3m": 1.6}]
        if endpoint == "yc_cb":
            if deny_curve:
                raise PermissionError("yc_cb disabled by recorded permission receipt")
            return [
                {
                    "trade_date": SESSION,
                    "curve_type": "0",
                    "curve_term": float(term),
                    "yield": 1.5 + term / 25,
                }
                for term in (1, 2, 3, 5, 7, 10, 30)
            ]
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    return counts, fetch_official, fetch_tushare


def _calendar_receipt(route_id: str) -> SourceCaptureReceipt:
    payload = {
        "schema_version": "source_capture_receipt_v1",
        "identity": {
            "source_family": "tushare",
            "route_id": route_id,
            "request_hash": canonical_hash({"route_id": route_id, "as_of": AS_OF}),
            "capture_id": f"test-{route_id}-{AS_OF}",
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
            "released_at": "2026-08-08T05:30:00+00:00",
            "vintage_at": "2026-08-08T05:30:00+00:00",
            "captured_at": "2026-08-08T05:30:00+00:00",
            "knowledge_available_at": "2026-08-08T05:30:00+00:00",
        },
        "pit": {
            "pit_mode": "OBSERVED_LIVE",
            "as_of_cutoff": CUTOFF,
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


def _archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, deny_curve: bool = True):
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "china-agent-data.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    counts, fetch_official, fetch_tushare = _fake_callbacks(deny_curve=deny_curve)
    result = archive_china_agent_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        market_session_date=SESSION,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )
    return store, ledger, result, counts, fetch_official, fetch_tushare


def test_empty_cache_archives_three_ready_routes_and_curve_permission_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, result, counts, _, _ = _archive(tmp_path, monkeypatch)

    assert set(result.routes) == {
        "official.cn_macro+tushare.cn_macro",
        "tushare.commodities",
        "tushare.institutional_flow",
        "tushare.shibor_yield_curve",
    }
    assert result.routes["official.cn_macro+tushare.cn_macro"].coverage_receipt.as_dict()["coverage_complete"] is True
    assert result.routes["tushare.commodities"].coverage_receipt.as_dict()["coverage_complete"] is True
    assert result.routes["tushare.institutional_flow"].coverage_receipt.as_dict()["coverage_complete"] is True
    curve = result.routes["tushare.shibor_yield_curve"]
    assert curve.group is None
    assert curve.coverage_receipt.as_dict()["blocker_codes"] == ["PERMISSION_DENIED"]
    assert store.row_count() == 3
    assert counts["official"] == 1
    assert counts["yc_cb"] == 1
    assert counts["fund_share"] == len(INSTITUTIONAL_ETF_UNIVERSE)
    assert counts["fut_wsr"] == 4
    assert {
        row["ts_code"]
        for row in result.routes["tushare.institutional_flow"].group[
            "fund_share_rows"
        ]
    } == set(INSTITUTIONAL_ETF_UNIVERSE)
    institutional_group = result.routes["tushare.institutional_flow"].group
    assert institutional_group["industry_history_start"] == "2026-06-08"
    assert {row["trade_date"] for row in institutional_group["industry_history_rows"]} == {
        f"{SESSION[:4]}-{SESSION[4:6]}-{SESSION[6:]}"
    }
    assert institutional_group["industry_transport_call_count"] == 4
    assert institutional_group["industry_transport_call_count"] == counts[
        "moneyflow_ind_ths"
    ]
    official_dimensions = result.routes[CHINA_ROUTE_GROUP].source_receipts[0].as_dict()[
        "coverage"
    ]["dimensions"]
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
    assert ledger.source_status(as_of=AS_OF, route_id="tushare.commodities")["status"] == "READY"
    commodity_receipt = result.routes["tushare.commodities"].source_receipts[0]
    assert commodity_receipt.as_dict()["transport"]["page_count"] == 10


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
                    "north_money": 1.0,
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
        endpoint="moneyflow_hsgt", trade_date=SESSION
    ) == [{"trade_date": SESSION, "north_money": 1.0, "optional": None}]


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


def test_commodity_ignores_zero_volume_contract_when_two_traded_contracts_remain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "zero-volume.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "zero-volume-ledger.sqlite3")
    _, fetch_official, base_fetch = _fake_callbacks()

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
        if endpoint == "fut_daily" and params["exchange"] == "INE":
            rows[0]["vol"] = 0.0
            rows.append(
                {
                    "ts_code": "SC2701.INE",
                    "trade_date": SESSION,
                    "settle": 102.0,
                    "vol": 1000.0,
                    "oi": 2000.0,
                }
            )
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
    sc = next(
        family
        for family in commodity.group["condition_input"]["families"]
        if family["family_id"] == "SC@INE"
    )
    assert len(sc["contracts"]) == 2
    assert all(contract["volume"] > 0 for contract in sc["contracts"])


def test_commodity_blocks_when_filtering_leaves_fewer_than_two_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "one-traded-contract.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "one-traded-contract-ledger.sqlite3")
    _, fetch_official, base_fetch = _fake_callbacks()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        rows = base_fetch(endpoint=endpoint, **params)
        if endpoint == "fut_daily" and params["exchange"] == "INE":
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
    assert commodity.coverage_receipt.as_dict()["blocker_codes"] == [
        "SCHEMA_DRIFT"
    ]


def test_commodity_inventory_derives_previous_from_documented_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "inventory-derived.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "inventory-derived-ledger.sqlite3")
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
    ledger = AgentDataMaterializationLedger(tmp_path / "inventory-unusable-ledger.sqlite3")
    _, fetch_official, base_fetch = _fake_callbacks()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        rows = base_fetch(endpoint=endpoint, **params)
        if endpoint == "fut_wsr" and rows:
            target = next(row for row in rows if row["symbol"] == "SC")
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
    assert commodity.coverage_receipt.as_dict()["blocker_codes"] == [
        "SCHEMA_DRIFT"
    ]


def test_institutional_crowding_keeps_only_complete_metric_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "crowding-partial.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "crowding-partial-ledger.sqlite3")
    _, fetch_official, base_fetch = _fake_callbacks()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        rows = base_fetch(endpoint=endpoint, **params)
        if endpoint == "daily_basic":
            rows[0]["volume_ratio"] = None
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

    institutional = result.routes["tushare.institutional_flow"]
    assert institutional.group is not None
    assert institutional.group["crowding_rows"] == [
        {"ts_code": "600000.SH", "turnover_rate": 1.5, "volume_ratio": 0.9}
    ]


def test_institutional_crowding_requires_one_complete_metric_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "crowding-empty.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "crowding-empty-ledger.sqlite3")
    _, fetch_official, base_fetch = _fake_callbacks()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        rows = base_fetch(endpoint=endpoint, **params)
        if endpoint == "daily_basic":
            for row in rows:
                row["volume_ratio"] = None
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

    institutional = result.routes["tushare.institutional_flow"]
    assert institutional.group is None
    assert institutional.coverage_receipt.as_dict()["blocker_codes"] == [
        "SCHEMA_DRIFT"
    ]


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
    assert len(
        {
            tuple(
                sorted(
                    (route_id, route.group["group_hash"])
                    for route_id, route in result.routes.items()
                )
            )
            for result in results
        }
    ) == 1


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
        if endpoint == "fut_daily" and params["exchange"] == "INE":
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
    assert store.row_count() == 2
    assert counts["fut_daily"] >= 1


def test_commodity_inventory_rejects_rows_after_terminal_short_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import china_agent_data_archive

    monkeypatch.setattr(china_agent_data_archive, "_capture_now", lambda: CAPTURED_AT)
    store = ChinaAgentDataArchiveStore(tmp_path / "hidden-inventory-page.sqlite3")
    ledger = AgentDataMaterializationLedger(
        tmp_path / "hidden-inventory-page-ledger.sqlite3"
    )
    _, fetch_official, base_fetch = _fake_callbacks()
    offsets: list[int] = []

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        if endpoint == "fut_wsr":
            offset = int(params.get("offset", 0))
            offsets.append(offset)
            rows = base_fetch(endpoint=endpoint, **{**params, "offset": 0})
            return rows if offset == 0 else [rows[0]]
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

    commodity = result.routes["tushare.commodities"]
    assert commodity.group is None
    assert commodity.coverage_receipt.as_dict()["blocker_codes"] == [
        "SCHEMA_DRIFT"
    ]
    assert offsets == [0, 5]


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
        ("moneyflow_hsgt", 300, "tushare.institutional_flow"),
        ("moneyflow_ind_ths", 5_000, "tushare.institutional_flow"),
        ("daily_basic", 6_000, "tushare.institutional_flow"),
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
        if target_endpoint == "moneyflow_hsgt" and endpoint == "moneyflow_hsgt":
            return rows * hard_cap
        if (
            target_endpoint == "moneyflow_ind_ths"
            and endpoint == "moneyflow_ind_ths"
        ):
            return [
                {
                    "trade_date": SESSION,
                    "industry": f"industry-{index}",
                    "net_amount": float(index),
                }
                for index in range(hard_cap)
            ]
        if target_endpoint == "daily_basic" and endpoint == "daily_basic":
            return [
                {
                    "ts_code": f"{index:06d}.SZ",
                    "trade_date": SESSION,
                    "turnover_rate": 1.0,
                    "volume_ratio": 1.0,
                }
                for index in range(hard_cap)
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
    assert result.routes[blocked_route].coverage_receipt.as_dict()[
        "blocker_codes"
    ] == ["SCHEMA_DRIFT"]


def test_archive_payload_hash_tamper_is_rejected_on_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _, archived, _, _, _ = _archive(
        tmp_path, monkeypatch, deny_curve=False
    )
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
    store, _, archived, _, _, _ = _archive(
        tmp_path, monkeypatch, deny_curve=False
    )
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
            (tmp_path / "snapshots" / snapshot["as_of_date"] / f"{role}.json").read_text(
                encoding="utf-8"
            )
        )
        assert validate_role_snapshot(
            persisted, role, snapshot["as_of_date"]
        ) == snapshot

    assert load_role_snapshot(
        "institutional_flow",
        AS_OF,
        root=tmp_path / "snapshots",
        ledger=ledger,
    ) == built.snapshots["institutional_flow"]
    institutional_path = (
        tmp_path / "snapshots" / AS_OF / "institutional_flow.json"
    )
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
        "market_wide_flow",
        "sector_rotation",
        "etf_share",
        "crowding",
    }
    assert len(INSTITUTIONAL_ETF_UNIVERSE) >= 5
    by_role = {receipt.as_dict()["agent_id"]: receipt.as_dict() for receipt in built.build_receipts}
    assert by_role["central_bank"]["terminal_state"] == "BLOCKED"
    assert by_role["central_bank"]["output_hash"] is None
    assert by_role["central_bank"]["missing_route_ids"] == ["tushare.shibor_yield_curve"]
    assert [receipt.receipt_hash for receipt in replay.build_receipts] == [
        receipt.receipt_hash for receipt in built.build_receipts
    ]
    assert ledger.row_counts()["snapshot_build_receipts"] == 4


def test_compiler_publishes_ready_central_bank_when_curve_route_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, archived, counts, _, _ = _archive(
        tmp_path, monkeypatch, deny_curve=False
    )
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

    assert counts == before
    assert set(built.snapshots) == {
        "china",
        "central_bank",
        "commodities",
        "institutional_flow",
    }
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
