from __future__ import annotations

import sys
from types import ModuleType
from datetime import date, timedelta

import pytest

from mosaic.dataflows.a_share_archive import (
    ASharePaginationError,
    AShareSchemaError,
    HISTORY_CALENDAR_DAYS,
    _api_date,
    _calendar_sessions,
    _response_rows,
    _validate_session_closure,
    fetch_a_share_tushare_endpoint,
)


def test_bounded_a_share_helpers_preserve_sector_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    as_of = date(2026, 8, 7)
    start = as_of - timedelta(days=HISTORY_CALENDAR_DAYS)
    rows = [
        {
            "cal_date": _api_date(start + timedelta(days=offset)),
            "is_open": 1,
        }
        for offset in range(HISTORY_CALENDAR_DAYS + 1)
    ]
    sessions = _calendar_sessions(rows, start_date=start, as_of_date=as_of)
    assert sessions[0] == _api_date(start)
    assert sessions[-1] == "20260807"
    assert _response_rows([{"value": float("nan")}]) == [{"value": None}]

    batches = [
        {"endpoint": endpoint, "rows": [{"trade_date": sessions[-1], "ts_code": "510300.SH"}]}
        for endpoint in ("daily", "adj_factor", "daily_basic")
    ]
    _validate_session_closure(batches, [sessions[-1]])

    calls: list[tuple[str, dict[str, str]]] = []
    tushare = ModuleType("mosaic.dataflows.tushare")
    tushare._query_pro = lambda endpoint, **params: calls.append((endpoint, params)) or ["ok"]
    monkeypatch.setitem(sys.modules, "mosaic.dataflows.tushare", tushare)
    assert fetch_a_share_tushare_endpoint("daily", trade_date="20260807") == ["ok"]
    assert calls == [("daily", {"trade_date": "20260807"})]
    assert issubclass(ASharePaginationError, RuntimeError)
    assert issubclass(AShareSchemaError, RuntimeError)


def test_bounded_session_closure_rejects_missing_adjustment() -> None:
    session = "20260807"
    with pytest.raises(RuntimeError, match="adjustment factors"):
        _validate_session_closure(
            [
                {"endpoint": "daily", "rows": [{"trade_date": session, "ts_code": "510300.SH"}]},
                {"endpoint": "adj_factor", "rows": []},
                {
                    "endpoint": "daily_basic",
                    "rows": [{"trade_date": session, "ts_code": "510300.SH"}],
                },
            ],
            [session],
        )
