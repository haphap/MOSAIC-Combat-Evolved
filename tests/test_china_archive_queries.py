from __future__ import annotations

from typing import Any

import pytest

from mosaic.dataflows.china_archive_queries import ChinaArchiveQueryReader
from mosaic.dataflows.exceptions import DataVendorUnavailable


AS_OF = "2026-07-09"


class _Store:
    def __init__(self, groups: dict[str, dict[str, Any]]) -> None:
        self.groups = groups
        self.calls: list[tuple[str, str]] = []

    def load_route_group(self, as_of_date: str, route_group: str) -> dict[str, Any]:
        self.calls.append((as_of_date, route_group))
        if as_of_date != AS_OF or route_group not in self.groups:
            raise FileNotFoundError((as_of_date, route_group))
        return self.groups[route_group]


def _groups() -> dict[str, dict[str, Any]]:
    return {
        "tushare.institutional_flow": {
            "as_of_date": AS_OF,
            "route_group": "tushare.institutional_flow",
            "captured_at": "2026-07-09T14:30:00+08:00",
            "industry_history_start": "2026-05-10",
            "industry_history_rows": [
                {
                    "trade_date": "2026-07-08",
                    "industry": "银行",
                    "net_amount": 9.0,
                    "lead_stock": "浦发银行",
                },
                {
                    "trade_date": "2026-07-09",
                    "industry": "银行",
                    "net_amount": 10.0,
                    "lead_stock": "浦发银行",
                },
                {
                    "trade_date": "2026-07-09",
                    "industry": "电子",
                    "net_amount": -2.0,
                    "lead_stock": "海康威视",
                },
            ],
        },
        "composite.cn_rates": {
            "as_of_date": AS_OF,
            "route_group": "composite.cn_rates",
            "captured_at": "2026-07-09T14:31:00+08:00",
            "curve_history_start": "2025-07-09",
            "government_curve_rows": [
                {
                    "trade_date": "2026-07-08",
                    "curve_type": "0",
                    "curve_term": term,
                    "yield": 1.5 + term / 25,
                }
                for term in (1, 2, 3, 5, 7, 10, 30)
            ],
        },
    }


def test_china_archive_reader_preserves_industry_filter_and_curve_outputs() -> None:
    store = _Store(_groups())
    reader = ChinaArchiveQueryReader(store=store)

    industry = reader("get_industry_moneyflow", AS_OF, 5, "银行")
    assert "Industry Money Flow" in industry
    assert "银行" in industry
    assert "电子" not in industry

    curve = reader("get_yield_curve_cn", AS_OF, 30)
    assert "CN Treasury Yield Curve" in curve
    assert "MOF/ChinaBond official maturity curve" in curve
    assert ",30,2.7" in curve
    assert store.calls == [
        (AS_OF, "tushare.institutional_flow"),
        (AS_OF, "composite.cn_rates"),
    ]


def test_china_archive_reader_fails_closed_for_missing_or_short_history() -> None:
    reader = ChinaArchiveQueryReader(store=_Store(_groups()))
    with pytest.raises(DataVendorUnavailable, match="no exact China archive"):
        reader("get_yield_curve_cn", "2026-07-08", 30)
    short = _groups()
    short["composite.cn_rates"]["curve_history_start"] = "2026-07-01"
    with pytest.raises(DataVendorUnavailable, match="does not cover"):
        ChinaArchiveQueryReader(store=_Store(short))(
            "get_yield_curve_cn", AS_OF, 30
        )
