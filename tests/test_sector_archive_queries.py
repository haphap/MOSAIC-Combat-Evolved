from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.sector_archive_queries import SectorArchiveQueryReader
from mosaic.scorecard.canonical_json import canonical_hash


AS_OF = "2026-07-09"
CAPTURED_AT = "2026-07-09T16:30:00+08:00"


class _Store:
    def __init__(self, group: dict[str, Any]) -> None:
        self.group = group
        self.calls: list[str] = []

    def load_group(self, as_of_date: str) -> dict[str, Any]:
        self.calls.append(as_of_date)
        if as_of_date != AS_OF:
            raise FileNotFoundError(as_of_date)
        return self.group


def _batch(endpoint: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"endpoint": endpoint, "rows": rows}


def _group() -> dict[str, Any]:
    start = date(2025, 10, 1)
    prices = []
    for index in range(282):
        day = start + timedelta(days=index)
        prices.append(
            {
                "ts_code": "600000.SH",
                "trade_date": day.strftime("%Y%m%d"),
                "open": 10 + index / 100,
                "high": 10.5 + index / 100,
                "low": 9.5 + index / 100,
                "close": 10.2 + index / 100,
                "pre_close": 10.1 + index / 100,
                "change": 0.1,
                "pct_chg": 1.0,
                "vol": 1000 + index,
                "amount": 10000 + index,
            }
        )
    statement_common = {
        "ts_code": "600000.SH",
        "ann_date": "20260430",
        "f_ann_date": "20260430",
        "end_date": "20260331",
        "update_flag": "1",
    }
    group = {
        "schema_version": "sector_relationship_capture_group_v2",
        "capture_key": canonical_hash({"capture": AS_OF}),
        "as_of_date": AS_OF,
        "cutoff_at": "2026-07-09T23:59:00+08:00",
        "captured_at": CAPTURED_AT,
        "base_group_hash": canonical_hash({"base": AS_OF}),
        "sessions": [row["trade_date"] for row in prices],
        "batches": [
            _batch("stock_basic", [{"ts_code": "600000.SH", "name": "浦发银行"}]),
            _batch("daily", prices),
            _batch(
                "income",
                [
                    {
                        **statement_common,
                        "revenue": 100.0,
                        "n_income": 8.0,
                    }
                ],
            ),
            _batch("cashflow", [{**statement_common, "n_cashflow_act": 9.0}]),
            _batch("balancesheet", [{**statement_common, "total_assets": 1000.0}]),
            _batch(
                "fund_portfolio",
                [
                    {
                        "ts_code": "512800.SH",
                        "ann_date": "20260701",
                        "end_date": "20260630",
                        "symbol": "600000.SH",
                        "stk_name": "浦发银行",
                        "stk_mkv_ratio": 9.1,
                        "stk_float_ratio": 2.1,
                    }
                ],
            ),
        ],
        "page_count": 5,
        "normalized_row_count": len(prices) + 5,
        "duplicate_counts": {},
    }
    return group


def test_sector_archive_reader_preserves_market_indicator_statement_and_etf_outputs() -> None:
    store = _Store(_group())
    reader = SectorArchiveQueryReader(store=store)

    stock = reader("get_stock_data", "600000.SH", "2026-07-01", AS_OF)
    assert "# Tushare stock data for 600000.SH" in stock
    assert "2026-07-09" in stock
    assert "2026-06-30" not in stock

    indicator = reader("get_indicators", "600000.SH", "rsi", AS_OF, 20)
    assert "## rsi values" in indicator
    assert "2026-07-09:" in indicator

    income = reader("get_income_statement", "600000.SH", "quarterly", AS_OF)
    balance = reader("get_balance_sheet", "600000.SH", "quarterly", AS_OF)
    cashflow = reader("get_cashflow", "600000.SH", "quarterly", AS_OF)
    assert "Tushare income statement for 600000.SH (quarterly)" in income
    assert "Tushare balance sheet for 600000.SH (quarterly)" in balance
    assert "Tushare cashflow for 600000.SH (quarterly)" in cashflow

    holdings = reader("get_etf_holdings", "512800.SH", AS_OF)
    assert "Disclosure Date: 20260701" in holdings
    assert "600000.SH" in holdings
    assert store.calls == [AS_OF] * 6


def test_sector_archive_reader_fails_closed_for_missing_date_ticker_or_endpoint() -> None:
    reader = SectorArchiveQueryReader(store=_Store(_group()))
    with pytest.raises(DataVendorUnavailable, match="no exact Sector archive"):
        reader("get_stock_data", "600000.SH", "2026-07-01", "2026-07-08")
    with pytest.raises(DataVendorUnavailable, match="no archived daily rows"):
        reader("get_stock_data", "000001.SZ", "2026-07-01", AS_OF)
    broken = _group()
    broken["batches"] = [
        batch for batch in broken["batches"] if batch["endpoint"] != "balancesheet"
    ]
    with pytest.raises(DataVendorUnavailable, match="balancesheet batch"):
        SectorArchiveQueryReader(store=_Store(broken))(
            "get_balance_sheet", "600000.SH", "quarterly", AS_OF
        )
