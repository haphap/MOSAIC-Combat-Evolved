"""A-share trading calendar helper (Plan §11.3 sub-step 3B).

Provides ``next_trading_day(date_str, n)`` for the scorecard's forward-return
horizon alignment. A-share trading days exclude weekends + ~12-15 mainland
public holidays per year, so calendar arithmetic doesn't suffice.

Backed by Tushare's ``pro.trade_cal`` (SSE exchange) with an in-memory cache
keyed by year. Caller is expected to call once per session — repeat calls
are cheap (cache hit returns immediately).

If Tushare is unavailable, falls back to a Mon-Fri "trading day = weekday"
approximation. The fallback is logged so the operator notices.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# In-memory cache of ``date -> is_trading_day`` (boolean) covering one
# rolling year window. Refreshed lazily.
_calendar_cache: dict[date, bool] = {}
_cache_loaded_for: tuple[date, date] | None = None

# Cap (PR #3 review hotfix #5): every ``_ensure_cache`` call may expand the
# window by 60 days, so a long-running daemon (e.g. autoresearch cron) that
# walks across many widely-separated dates could grow the cache without
# bound. 5000 entries ≈ 14 years of trading days — far more than any single
# cohort backtest needs. When this is exceeded we drop the cache and force
# a fresh refetch on the next query. The bounds in ``_cache_loaded_for``
# are also reset so existing entries don't get stale-served.
_CACHE_MAX_ENTRIES = 5000


def _parse_date(date_str: str) -> date:
    """Accept YYYY-MM-DD or YYYYMMDD; raise on anything else."""
    s = date_str.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date string '{date_str}'; expected YYYY-MM-DD or YYYYMMDD")


def _format_yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _format_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _ensure_cache(start: date, end: date) -> None:
    """Lazily populate ``_calendar_cache`` covering [start, end].

    If the requested range is not fully contained in the cache, re-fetch.

    Cap behaviour (PR #3 review hotfix #5): when the cache is already
    large (> ½ of ``_CACHE_MAX_ENTRIES``) and a new fetch is needed, drop
    the existing cache and fetch only the request window — don't merge
    with old bounds. This keeps memory bounded in long-running daemons
    that walk widely-separated dates.
    """
    global _cache_loaded_for
    if _cache_loaded_for and _cache_loaded_for[0] <= start and end <= _cache_loaded_for[1]:
        return

    # Cap: if cache is already large, evict before fetching a new window
    # (so the merged window doesn't blow past the cap).
    cache_was_capped = len(_calendar_cache) > _CACHE_MAX_ENTRIES // 2
    if cache_was_capped:
        logger.info(
            "calendar cache evicted (had %d entries, cap=%d) before fetching new window",
            len(_calendar_cache),
            _CACHE_MAX_ENTRIES,
        )
        _calendar_cache.clear()
        _cache_loaded_for = None

    # Pull a generous window around the request to avoid frequent re-fetches.
    # When we just evicted, fetch only the request window (don't merge with
    # the cleared bounds — that would defeat the cap).
    if _cache_loaded_for and not cache_was_capped:
        fetch_start = min(start, _cache_loaded_for[0])
        fetch_end = max(end, _cache_loaded_for[1])
    else:
        fetch_start = start
        fetch_end = end
    fetch_start = fetch_start - timedelta(days=30)
    fetch_end = fetch_end + timedelta(days=30)

    df = _fetch_trade_cal_via_tushare(fetch_start, fetch_end)
    if df is None or df.empty:
        # Fallback to weekday approximation
        logger.warning(
            "trade_cal unavailable; falling back to Mon-Fri weekday approximation "
            "for [%s, %s]. Forward-return alignment will mis-handle public holidays.",
            fetch_start,
            fetch_end,
        )
        cur = fetch_start
        while cur <= fetch_end:
            _calendar_cache[cur] = cur.weekday() < 5
            cur += timedelta(days=1)
    else:
        # df has cal_date (YYYYMMDD) + is_open (0/1)
        for _, row in df.iterrows():
            cal_date_str = str(row["cal_date"])
            d = _parse_date(cal_date_str)
            _calendar_cache[d] = bool(int(row["is_open"]))

    _cache_loaded_for = (fetch_start, fetch_end)


def _fetch_trade_cal_via_tushare(start: date, end: date) -> Optional[pd.DataFrame]:
    """Pull SSE trade calendar from Tushare. Returns None if unavailable."""
    try:
        from mosaic.dataflows.tushare import _get_pro_client  # type: ignore[attr-defined]

        pro = _get_pro_client()
    except Exception as exc:
        logger.info("Tushare unavailable for trade_cal: %s", exc)
        return None
    try:
        df = pro.trade_cal(
            exchange="SSE",
            start_date=_format_yyyymmdd(start),
            end_date=_format_yyyymmdd(end),
            fields="cal_date,is_open",
        )
        return df
    except Exception as exc:
        logger.warning("Tushare trade_cal call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_trading_day(date_str: str) -> bool:
    """Return True if ``date_str`` is an A-share trading day."""
    d = _parse_date(date_str)
    _ensure_cache(d, d)
    return _calendar_cache.get(d, d.weekday() < 5)


def next_trading_day(date_str: str, n: int = 1) -> str:
    """Return the date string ``n`` trading days after ``date_str`` (YYYY-MM-DD).

    ``n=0`` returns ``date_str`` if it is a trading day, else the next
    trading day. ``n>0`` skips ``n`` trading days forward. Negative ``n``
    isn't supported (caller should use ``previous_trading_day``).

    Examples (assuming standard week, no holidays):
        next_trading_day("2024-06-24", 0)  → "2024-06-24"  (Mon)
        next_trading_day("2024-06-24", 5)  → "2024-07-01"  (next Mon)
        next_trading_day("2024-06-22", 0)  → "2024-06-24"  (Sat → roll forward)
    """
    if n < 0:
        raise ValueError("n must be >= 0; use previous_trading_day for n<0")
    d = _parse_date(date_str)
    _ensure_cache(d, d + timedelta(days=max(n * 2, 30)))

    cur = d
    # First make sure cur itself is a trading day
    while not _calendar_cache.get(cur, cur.weekday() < 5):
        cur += timedelta(days=1)
    if n == 0:
        return _format_iso(cur)

    skipped = 0
    while skipped < n:
        cur += timedelta(days=1)
        # Refresh cache window if we walk past it
        if _cache_loaded_for and cur > _cache_loaded_for[1]:
            _ensure_cache(cur, cur + timedelta(days=60))
        if _calendar_cache.get(cur, cur.weekday() < 5):
            skipped += 1
    return _format_iso(cur)


def previous_trading_day(date_str: str, n: int = 1) -> str:
    """Mirror of ``next_trading_day`` for n trading days backward."""
    if n < 0:
        raise ValueError("n must be >= 0")
    d = _parse_date(date_str)
    _ensure_cache(d - timedelta(days=max(n * 2, 30)), d)

    cur = d
    while not _calendar_cache.get(cur, cur.weekday() < 5):
        cur -= timedelta(days=1)
    if n == 0:
        return _format_iso(cur)

    skipped = 0
    while skipped < n:
        cur -= timedelta(days=1)
        if _cache_loaded_for and cur < _cache_loaded_for[0]:
            _ensure_cache(cur - timedelta(days=60), cur)
        if _calendar_cache.get(cur, cur.weekday() < 5):
            skipped += 1
    return _format_iso(cur)


def clear_cache() -> None:
    """Drop the in-memory calendar cache (used by tests)."""
    global _cache_loaded_for
    _calendar_cache.clear()
    _cache_loaded_for = None


def populate_cache_for_test(days: dict[str, bool]) -> None:
    """Test hook: pre-populate the cache without hitting Tushare.

    ``days`` maps YYYY-MM-DD strings to is_open booleans. After this call,
    ``_cache_loaded_for`` is pinned to (date.min, date.max) so that any
    subsequent ``_ensure_cache`` request short-circuits — preventing the
    real Tushare path from overwriting the test fixture if the requested
    horizon walks outside the populated days. Unknown dates fall back to
    the Mon-Fri heuristic via ``_calendar_cache.get(d, d.weekday() < 5)``.
    """
    global _cache_loaded_for
    _calendar_cache.clear()
    parsed = {_parse_date(k): v for k, v in days.items()}
    _calendar_cache.update(parsed)
    # Pin to the full representable range so _ensure_cache never re-fetches.
    _cache_loaded_for = (date.min, date.max)
