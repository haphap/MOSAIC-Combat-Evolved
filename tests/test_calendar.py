"""Tests for mosaic.dataflows.calendar (Plan §11.3 sub-step 3B helper)."""

from __future__ import annotations

import pytest

from mosaic.dataflows import calendar as cal


@pytest.fixture(autouse=True)
def _reset_cache():
    cal.clear_cache()
    yield
    cal.clear_cache()


def _five_weekdays_starting(monday_iso: str, with_friday_holiday: bool = False) -> dict:
    """Build a 14-day calendar starting from a Monday.

    Returns a {YYYY-MM-DD: is_open} dict suitable for populate_cache_for_test.
    Closes weekends; optionally closes the second Friday (mimics a public holiday).
    """
    from datetime import datetime, timedelta

    base = datetime.strptime(monday_iso, "%Y-%m-%d").date()
    days: dict[str, bool] = {}
    for i in range(14):
        d = base + timedelta(days=i)
        is_open = d.weekday() < 5
        # Close the second Friday (i=11) → simulates a holiday on day 11
        if with_friday_holiday and i == 11:
            is_open = False
        days[d.isoformat()] = is_open
    return days


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParse:
    def test_iso_format(self):
        cal.populate_cache_for_test({"2024-06-24": True})
        assert cal.is_trading_day("2024-06-24") is True

    def test_yyyymmdd_format(self):
        cal.populate_cache_for_test({"2024-06-24": True})
        assert cal.is_trading_day("20240624") is True

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            cal.is_trading_day("not-a-date")


# ---------------------------------------------------------------------------
# next_trading_day / previous_trading_day with no holidays
# ---------------------------------------------------------------------------


class TestVanillaCalendar:
    """No public holidays — every Mon-Fri is a trading day."""

    def setup_method(self):
        # Monday 2024-06-24 → Sunday 2024-07-07 (14 days)
        cal.populate_cache_for_test(_five_weekdays_starting("2024-06-24"))

    def test_n_zero_on_trading_day_returns_self(self):
        assert cal.next_trading_day("2024-06-24", 0) == "2024-06-24"

    def test_n_zero_on_weekend_rolls_forward(self):
        # 2024-06-22 = Saturday → next trading day = Monday 2024-06-24
        assert cal.next_trading_day("2024-06-22", 0) == "2024-06-24"
        assert cal.next_trading_day("2024-06-23", 0) == "2024-06-24"  # Sunday

    def test_one_trading_day_skips_weekends(self):
        # Friday + 1 trading day → next Monday
        assert cal.next_trading_day("2024-06-28", 1) == "2024-07-01"

    def test_five_trading_days_from_monday(self):
        # Mon 06-24 + 5 trading days → next Mon 07-01
        assert cal.next_trading_day("2024-06-24", 5) == "2024-07-01"

    def test_previous_trading_day(self):
        # Tuesday - 1 trading day → previous Monday
        assert cal.previous_trading_day("2024-06-25", 1) == "2024-06-24"

    def test_previous_skips_weekend(self):
        # Monday - 1 → previous Friday
        assert cal.previous_trading_day("2024-07-01", 1) == "2024-06-28"

    def test_negative_n_rejected(self):
        with pytest.raises(ValueError):
            cal.next_trading_day("2024-06-24", -1)
        with pytest.raises(ValueError):
            cal.previous_trading_day("2024-06-24", -1)


# ---------------------------------------------------------------------------
# Holiday handling (the value-add over weekday math)
# ---------------------------------------------------------------------------


class TestHolidayAware:
    def setup_method(self):
        cal.populate_cache_for_test(
            _five_weekdays_starting("2024-06-24", with_friday_holiday=True)
        )

    def test_5d_skips_holiday(self):
        # 2024-06-24 + 5 trading days, but second Friday (07-05) is a holiday.
        # Trading days: Mon 24, Tue 25, Wed 26, Thu 27, Fri 28, Mon 7-1, Tue 7-2,
        # Wed 7-3, Thu 7-4, Fri 7-5 (HOLIDAY), Mon 7-8...
        # 5 trading days from Mon 24 = Mon 7-1 (✓ — 5 trading days).
        assert cal.next_trading_day("2024-06-24", 5) == "2024-07-01"

    def test_landing_on_holiday_continues_forward(self):
        # 2024-07-01 (Mon) + 4 trading days would naively be Fri 07-05 but
        # that's the holiday → should land on Mon 07-08
        assert cal.next_trading_day("2024-07-01", 4) == "2024-07-08"


# ---------------------------------------------------------------------------
# Fallback to Mon-Fri when calendar not pre-populated
# ---------------------------------------------------------------------------


class TestFallback:
    def test_unknown_date_uses_weekday_heuristic(self, monkeypatch):
        # Disable Tushare path → only weekday fallback active
        monkeypatch.setattr(
            cal,
            "_fetch_trade_cal_via_tushare",
            lambda start, end: None,
        )
        # 2024-06-22 = Saturday → not trading
        assert cal.is_trading_day("2024-06-22") is False
        # 2024-06-24 = Monday → trading
        assert cal.is_trading_day("2024-06-24") is True
