from __future__ import annotations

import pandas as pd

from mosaic.dataflows import tushare


def _fund_basic_rows(count: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_code": f"51030{i}.SH",
                "name": f"ETF{i}",
                "market": "E",
                "fund_type": "股票型",
                "invest_type": "被动指数型",
                "benchmark": "沪深300",
                "list_date": f"2024{i + 1:02d}01",
            }
            for i in range(count)
        ]
    )


def test_get_etf_universe_caps_factor_enrichment(monkeypatch):
    tushare.clear_pro_client_cache()
    monkeypatch.setattr(tushare, "_ETF_UNIVERSE_MAX_ENRICHED_ROWS", 3)
    monkeypatch.setattr(tushare, "_query_pro", lambda api_name, **_: _fund_basic_rows(10))

    enriched: list[str] = []

    def fake_factor_snapshot(ts_code: str, curr_date: str) -> dict[str, object]:
        enriched.append(ts_code)
        return {
            "latest_trade_date": curr_date.replace("-", ""),
            "latest_close": 1.23,
            "factor_status": "ok",
        }

    monkeypatch.setattr(tushare, "_latest_etf_factor_snapshot", fake_factor_snapshot)

    out = tushare.get_etf_universe(curr_date="2024-12-31", limit=10)

    assert len(enriched) == 3
    assert "Enriched rows: 3 of 10" in out
    assert "not_enriched; enrichment_cap=3" in out
    assert "latest_close" in out


def test_get_etf_universe_reuses_fund_basic_and_factor_cache(monkeypatch):
    tushare.clear_pro_client_cache()
    monkeypatch.setattr(tushare, "_ETF_UNIVERSE_MAX_ENRICHED_ROWS", 2)

    fund_basic_calls: list[str] = []

    def fake_query(api_name: str, **_) -> pd.DataFrame:
        fund_basic_calls.append(api_name)
        return _fund_basic_rows(4)

    enriched: list[tuple[str, str]] = []

    def fake_factor_snapshot(ts_code: str, curr_date: str) -> dict[str, object]:
        enriched.append((ts_code, curr_date))
        return {"factor_status": "ok", "latest_close": 2.0}

    monkeypatch.setattr(tushare, "_query_pro", fake_query)
    monkeypatch.setattr(tushare, "_latest_etf_factor_snapshot", fake_factor_snapshot)

    tushare.get_etf_universe(curr_date="2024-12-31", limit=4)
    tushare.get_etf_universe(curr_date="2024-12-31", limit=4)

    assert fund_basic_calls == ["fund_basic"]
    assert len(enriched) == 2


def test_get_etf_universe_defaults_to_exchange_traded_non_money_funds(monkeypatch):
    tushare.clear_pro_client_cache()
    monkeypatch.setattr(tushare, "_ETF_UNIVERSE_MAX_ENRICHED_ROWS", 0)
    monkeypatch.setattr(
        tushare,
        "_query_pro",
        lambda api_name, **_: pd.DataFrame(
            [
                {
                    "ts_code": "510300.SH",
                    "name": "沪深300ETF",
                    "market": "E",
                    "fund_type": "股票型",
                    "invest_type": "被动指数型",
                    "benchmark": "沪深300",
                    "list_date": "20240101",
                },
                {
                    "ts_code": "000001.OF",
                    "name": "普通开放式基金",
                    "market": "O",
                    "fund_type": "混合型",
                    "invest_type": "主动型",
                    "benchmark": "偏股混合",
                    "list_date": "20240101",
                },
                {
                    "ts_code": "511990.SH",
                    "name": "华宝添益货币ETF",
                    "market": "E",
                    "fund_type": "货币型",
                    "invest_type": "被动型",
                    "benchmark": "货币市场",
                    "list_date": "20240101",
                },
            ]
        ),
    )

    out = tushare.get_etf_universe(curr_date="2024-12-31", limit=10)

    assert "510300.SH" in out
    assert "000001.OF" not in out
    assert "511990.SH" not in out
    assert "Market filter: E (default exchange-traded ETF universe)" in out
