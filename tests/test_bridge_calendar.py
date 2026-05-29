"""Tests for calendar.* JSON-RPC handlers (PR #4 review hotfix #2)."""

from __future__ import annotations

import pytest

from mosaic.bridge import handlers as _handlers_pkg  # noqa: F401
from mosaic.bridge.protocol import RpcError
from mosaic.bridge.registry import get_handler
from mosaic.dataflows import calendar as cal_module


def dispatch(method: str, params: dict):
    handler = get_handler(method)
    if handler is None:
        raise AssertionError(f"method '{method}' not registered")
    return handler(params)


@pytest.fixture(autouse=True)
def _reset_calendar_cache():
    cal_module.clear_cache()
    yield
    cal_module.clear_cache()


def _populate_with_friday_holiday():
    """Mon 2024-06-24 → Sun 2024-07-07; second Friday (07-05) is a holiday."""
    from datetime import datetime, timedelta

    base = datetime.strptime("2024-06-24", "%Y-%m-%d").date()
    days = {}
    for i in range(14):
        d = base + timedelta(days=i)
        is_open = d.weekday() < 5
        if i == 11:  # second Friday → holiday
            is_open = False
        days[d.isoformat()] = is_open
    cal_module.populate_cache_for_test(days)


# ---------------------------------------------------------------------------
# calendar.list_trading_days
# ---------------------------------------------------------------------------


class TestListTradingDays:
    def test_basic_range(self):
        _populate_with_friday_holiday()
        result = dispatch(
            "calendar.list_trading_days",
            {"start": "2024-06-24", "end": "2024-06-28"},
        )
        # Mon-Fri = 5 trading days
        assert result["trading_days"] == [
            "2024-06-24",
            "2024-06-25",
            "2024-06-26",
            "2024-06-27",
            "2024-06-28",
        ]

    def test_filters_weekends(self):
        _populate_with_friday_holiday()
        result = dispatch(
            "calendar.list_trading_days",
            {"start": "2024-06-22", "end": "2024-06-25"},  # Sat-Tue
        )
        # Only Mon + Tue
        assert result["trading_days"] == ["2024-06-24", "2024-06-25"]

    def test_filters_holidays(self):
        _populate_with_friday_holiday()
        # Range spanning the second Friday holiday (07-05)
        result = dispatch(
            "calendar.list_trading_days",
            {"start": "2024-07-04", "end": "2024-07-08"},
        )
        # Thu open, Fri closed, Sat-Sun closed, Mon open
        # But our cache only covers up to 07-07; Mon 07-08 falls back to weekday math
        # → True. The handler walks day-by-day so the result depends on cache coverage.
        assert "2024-07-04" in result["trading_days"]
        assert "2024-07-05" not in result["trading_days"]  # holiday
        assert "2024-07-06" not in result["trading_days"]  # Sat
        assert "2024-07-07" not in result["trading_days"]  # Sun

    def test_empty_range(self):
        result = dispatch(
            "calendar.list_trading_days",
            {"start": "2024-06-28", "end": "2024-06-24"},  # end before start
        )
        assert result["trading_days"] == []

    def test_invalid_date_format(self):
        with pytest.raises(RpcError, match="invalid date format"):
            dispatch(
                "calendar.list_trading_days",
                {"start": "not-a-date", "end": "2024-06-28"},
            )

    def test_missing_params(self):
        with pytest.raises(RpcError, match="non-empty string"):
            dispatch("calendar.list_trading_days", {"start": "2024-06-24"})

    def test_single_day_window(self):
        _populate_with_friday_holiday()
        result = dispatch(
            "calendar.list_trading_days",
            {"start": "2024-06-24", "end": "2024-06-24"},  # Mon
        )
        assert result["trading_days"] == ["2024-06-24"]


# ---------------------------------------------------------------------------
# calendar.is_trading_day
# ---------------------------------------------------------------------------


class TestIsTradingDay:
    def test_weekday(self):
        _populate_with_friday_holiday()
        result = dispatch("calendar.is_trading_day", {"date": "2024-06-24"})
        assert result == {"is_trading": True}

    def test_weekend(self):
        _populate_with_friday_holiday()
        result = dispatch("calendar.is_trading_day", {"date": "2024-06-22"})
        assert result == {"is_trading": False}

    def test_holiday(self):
        _populate_with_friday_holiday()
        result = dispatch("calendar.is_trading_day", {"date": "2024-07-05"})
        assert result == {"is_trading": False}


# ---------------------------------------------------------------------------
# calendar.next_trading_day
# ---------------------------------------------------------------------------


class TestNextTradingDay:
    def test_n_zero_on_trading_day(self):
        _populate_with_friday_holiday()
        result = dispatch(
            "calendar.next_trading_day",
            {"date": "2024-06-24", "n": 0},
        )
        assert result == {"date": "2024-06-24"}

    def test_n_default_is_one(self):
        _populate_with_friday_holiday()
        result = dispatch("calendar.next_trading_day", {"date": "2024-06-24"})
        assert result == {"date": "2024-06-25"}

    def test_skips_holiday(self):
        _populate_with_friday_holiday()
        # Thu 07-04 + 1 trading day → skip Fri (holiday) + weekend → Mon 07-08
        result = dispatch(
            "calendar.next_trading_day",
            {"date": "2024-07-04", "n": 1},
        )
        assert result == {"date": "2024-07-08"}

    def test_negative_n_rejected(self):
        with pytest.raises(RpcError, match="non-negative"):
            dispatch("calendar.next_trading_day", {"date": "2024-06-24", "n": -1})


# ---------------------------------------------------------------------------
# Method registration
# ---------------------------------------------------------------------------


def test_calendar_methods_registered():
    from mosaic.bridge.registry import all_methods

    expected = {
        "calendar.list_trading_days",
        "calendar.is_trading_day",
        "calendar.next_trading_day",
    }
    assert expected.issubset(set(all_methods()))
