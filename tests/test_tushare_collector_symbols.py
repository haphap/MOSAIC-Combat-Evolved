"""Symbol conversion rules for the vendored Tushare stock collector."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

pytest.importorskip("qlib")
pytest.importorskip("loguru")

import mosaic.dataflows.collectors.data_collector.tushare.collector as collector_module  # noqa: E402
import mosaic.dataflows.collectors.data_collector.tushare_etf.collector as etf_collector_module  # noqa: E402
from mosaic.dataflows.collectors.data_collector.tushare_etf.collector import (  # noqa: E402
    TushareBatchCollector as EtfBatchCollector,
)
from mosaic.dataflows.collectors.data_collector.tushare.collector import (  # noqa: E402
    TushareBatchCollector,
    is_queryable_incremental_symbol,
    qlib_symbol_to_ts_code,
    ts_code_to_qlib_symbol,
)


def test_legacy_bse_symbols_are_not_queried_incrementally():
    assert not is_queryable_incremental_symbol("BJ430017")
    assert not is_queryable_incremental_symbol("bj830799")
    assert not is_queryable_incremental_symbol("BJ870508")
    assert not is_queryable_incremental_symbol("870508.BJ")


def test_current_bse_and_mainland_symbols_remain_queryable():
    assert is_queryable_incremental_symbol("BJ920001")
    assert is_queryable_incremental_symbol("920001.BJ")
    assert is_queryable_incremental_symbol("SH600519")
    assert is_queryable_incremental_symbol("SZ000001")


def test_qlib_symbol_to_tushare_code_roundtrip():
    assert qlib_symbol_to_ts_code("SZ000001") == "000001.SZ"
    assert qlib_symbol_to_ts_code("SH600519") == "600519.SH"
    assert qlib_symbol_to_ts_code("BJ920001") == "920001.BJ"
    assert ts_code_to_qlib_symbol("920001.BJ") == "bj920001"


def test_parallel_chunk_timeout_is_bounded_and_configurable(monkeypatch):
    dates = [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")]

    stock_collector = TushareBatchCollector.__new__(TushareBatchCollector)
    stock_collector.timeout = 300
    assert stock_collector._parallel_chunk_timeout_seconds(dates, safe_calls_per_worker=100) >= 300

    etf_collector = EtfBatchCollector.__new__(EtfBatchCollector)
    etf_collector.timeout = 300
    assert etf_collector._parallel_chunk_timeout_seconds(dates, safe_calls_per_worker=100) >= 300

    monkeypatch.setenv("MOSAIC_TUSHARE_PARALLEL_CHUNK_TIMEOUT_SECONDS", "42")
    assert stock_collector._parallel_chunk_timeout_seconds(dates, safe_calls_per_worker=100) == 42
    assert etf_collector._parallel_chunk_timeout_seconds(dates, safe_calls_per_worker=100) == 42


def test_etf_default_start_reads_env_at_constructor_time(monkeypatch, tmp_path):
    monkeypatch.setattr(etf_collector_module, "ts", object())
    monkeypatch.setenv("MOSAIC_ETF_ANALYSIS_START_DATE", "2006-01-04")

    collector = EtfBatchCollector(
        save_dir=tmp_path / "raw",
        qlib_dir=tmp_path / "qlib",
        token="token",
    )

    assert collector.start_datetime == pd.Timestamp("2006-01-04")


def test_fetch_new_stock_history_batches_multiple_ts_codes(monkeypatch, tmp_path):
    class FakePro:
        def __init__(self):
            self.daily_calls = []
            self.adj_calls = []

        def stock_basic(self, ts_code, fields):
            return pd.DataFrame(
                {
                    "ts_code": ts_code.split(","),
                    "list_date": ["20260101"] * len(ts_code.split(",")),
                }
            )

        def daily(self, ts_code, start_date, end_date):
            self.daily_calls.append((ts_code, start_date, end_date))
            rows = []
            for code in ts_code.split(","):
                rows.extend(
                    [
                        {
                            "ts_code": code,
                            "trade_date": "20260102",
                            "open": 1.0,
                            "high": 1.1,
                            "low": 0.9,
                            "close": 1.0,
                            "vol": 100.0,
                            "amount": 1000.0,
                        },
                        {
                            "ts_code": code,
                            "trade_date": "20260105",
                            "open": 2.0,
                            "high": 2.1,
                            "low": 1.9,
                            "close": 2.0,
                            "vol": 200.0,
                            "amount": 2000.0,
                        },
                    ]
                )
            return pd.DataFrame(rows)

        def adj_factor(self, ts_code, start_date, end_date):
            self.adj_calls.append((ts_code, start_date, end_date))
            rows = []
            for code in ts_code.split(","):
                rows.extend(
                    [
                        {"ts_code": code, "trade_date": "20260102", "adj_factor": 1.0},
                        {"ts_code": code, "trade_date": "20260105", "adj_factor": 1.0},
                    ]
                )
            return pd.DataFrame(rows)

    fake_pro = FakePro()
    monkeypatch.setattr(
        collector_module,
        "ts",
        SimpleNamespace(pro_api=lambda token, timeout: fake_pro),
    )

    collector = TushareBatchCollector.__new__(TushareBatchCollector)
    collector.token = "token"
    collector.timeout = 60
    collector.save_dir = tmp_path
    collector.start_datetime = pd.Timestamp("2026-01-01")
    collector.end_datetime = pd.Timestamp("2026-01-05")

    collector.fetch_new_stock_data(["000001.SZ", "000002.SZ"], start="2026-01-01", end="2026-01-05")

    assert fake_pro.daily_calls == [("000001.SZ,000002.SZ", "20260101", "20260105")]
    assert fake_pro.adj_calls == [("000001.SZ,000002.SZ", "20260101", "20260105")]

    first = pd.read_csv(tmp_path / "sz000001.csv")
    second = pd.read_csv(tmp_path / "sz000002.csv")
    assert first["ts_code"].tolist() == ["000001.SZ", "000001.SZ"]
    assert second["ts_code"].tolist() == ["000002.SZ", "000002.SZ"]
