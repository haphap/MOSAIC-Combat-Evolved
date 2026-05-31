"""
Qlib local data vendor for TradingAgents.

Reads OHLCV data directly from qlib's binary feature files without requiring
qlib to be installed. Falls back gracefully when data is unavailable.

Qlib stores split-adjusted OHLCV values and normalizes prices on the first
trading day of each stock. To surface user-facing prices and compute technical
indicators on the same scale as the live market, prices are restored via
``original_price = adjusted_price / factor`` and volumes via
``original_volume = adjusted_volume * factor``.

Binary format (per feature file):
  - Bytes 0-3: float32 representing the start calendar index
  - Bytes 4+:  float32 values, one per trading day from that calendar index
"""
import os
import struct
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from stockstats import wrap

from .exceptions import DataVendorUnavailable

# ---------------------------------------------------------------------------
# Data path discovery
# ---------------------------------------------------------------------------

_CANDIDATE_PATHS = [
    "~/.qlib/qlib_data/cn_data",
    "~/SynologyDrive/Project/qlib/qlib_data/cn_data",
    "~/qlib_data/cn_data",
]


def _find_qlib_data_path() -> Optional[Path]:
    """Return the first existing qlib cn_data directory, or None."""
    env_path = os.environ.get("QLIB_CN_DATA_PATH")
    if env_path:
        p = Path(env_path).expanduser()
        if p.is_dir():
            return p

    for candidate in _CANDIDATE_PATHS:
        p = Path(candidate).expanduser()
        if (p / "calendars" / "day.txt").exists() and (p / "features").is_dir():
            return p
    return None


_cached_data_path: Optional[Path] = None


def _get_data_path() -> Path:
    """Return qlib data path, caching only successful lookups."""
    global _cached_data_path
    if _cached_data_path is not None:
        return _cached_data_path
    path = _find_qlib_data_path()
    if path is None:
        raise DataVendorUnavailable(
            "Qlib CN data not found. Set QLIB_CN_DATA_PATH or place data at ~/.qlib/qlib_data/cn_data"
        )
    _cached_data_path = path
    return path


# ETF data lives in a sibling ``cn_etf`` dataset (same calendar as cn_data, but
# separate features/ tree). We route ETF instruments there. ETF SH/SZ codes do
# not overlap stock prefixes: ETFs are sh5x/sz1x, stocks are sh6x/sz0x/sz3x.
_CANDIDATE_ETF_PATHS = [
    "~/.qlib/qlib_data/cn_etf",
    "~/SynologyDrive/Project/qlib/qlib_data/cn_etf",
    "~/qlib_data/cn_etf",
]
_cached_etf_path: Optional[Path] = None
_ETF_SH_PREFIXES = ("5",)   # sh51xxxx / sh50xxxx / sh56xxxx / sh58xxxx ...
_ETF_SZ_PREFIXES = ("1",)   # sz15xxxx / sz16xxxx / sz18xxxx ...


def _find_qlib_etf_path() -> Optional[Path]:
    env_path = os.environ.get("QLIB_CN_ETF_PATH")
    if env_path:
        p = Path(env_path).expanduser()
        if (p / "features").is_dir():
            return p
    for candidate in _CANDIDATE_ETF_PATHS:
        p = Path(candidate).expanduser()
        if (p / "features").is_dir():
            return p
    return None


def _get_etf_path() -> Optional[Path]:
    global _cached_etf_path
    if _cached_etf_path is None:
        _cached_etf_path = _find_qlib_etf_path()
    return _cached_etf_path


def _is_etf_instrument(instrument: str) -> bool:
    """ETF iff sh5xxxxx or sz1xxxxx (disjoint from stock prefixes sh6/sz0/sz3)."""
    inst = instrument.lower()
    if inst.startswith("sh") and inst[2:3] in _ETF_SH_PREFIXES:
        return True
    if inst.startswith("sz") and inst[2:3] in _ETF_SZ_PREFIXES:
        return True
    return False


def _feature_root_for(instrument: str) -> Path:
    """Pick cn_etf for ETF instruments (when available), else cn_data."""
    if _is_etf_instrument(instrument):
        etf = _get_etf_path()
        if etf is not None:
            return etf
    return _get_data_path()


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_calendar() -> list[datetime]:
    """Load trading calendar as a list of datetime objects.

    Handles both YYYYMMDD and YYYY-MM-DD formats (some files mix them).
    """
    cal_file = _get_data_path() / "calendars" / "day.txt"
    dates = []
    with open(cal_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if "-" in line:
                dates.append(datetime.strptime(line, "%Y-%m-%d"))
            else:
                dates.append(datetime.strptime(line, "%Y%m%d"))
    return dates


def _calendar_last_day() -> Optional[pd.Timestamp]:
    cal = _load_calendar()
    if not cal:
        return None
    return pd.Timestamp(cal[-1])


def _last_weekday_on_or_before(date_value: pd.Timestamp) -> pd.Timestamp:
    probe = pd.Timestamp(date_value)
    while probe.weekday() >= 5:
        probe -= pd.Timedelta(days=1)
    return probe


def _ensure_local_calendar_covers(end_date: str) -> None:
    """Raise when the local qlib trading calendar stops before *end_date*."""
    calendar_last_day = _calendar_last_day()
    if calendar_last_day is None:
        return

    requested_end = pd.Timestamp(datetime.strptime(end_date, "%Y-%m-%d"))
    if requested_end <= calendar_last_day:
        return

    # Weekend requests are still valid as long as local data reaches the prior Friday.
    if requested_end.weekday() >= 5:
        covered_weekday = _last_weekday_on_or_before(requested_end)
        if calendar_last_day >= covered_weekday:
            return

    raise DataVendorUnavailable(
        "Qlib local trading calendar is stale: last local trading day is "
        f"{calendar_last_day.strftime('%Y-%m-%d')}, requested through {end_date}."
    )


def _date_to_cal_range(start_date: str, end_date: str) -> tuple[int, int]:
    """Return (start_idx, end_idx) inclusive in calendar for given date range."""
    cal = _load_calendar()
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # Binary search for first date >= start_dt
    lo, hi = 0, len(cal) - 1
    start_idx = len(cal)
    while lo <= hi:
        mid = (lo + hi) // 2
        if cal[mid] >= start_dt:
            start_idx = mid
            hi = mid - 1
        else:
            lo = mid + 1

    # Binary search for last date <= end_dt
    lo, hi = 0, len(cal) - 1
    end_idx = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if cal[mid] <= end_dt:
            end_idx = mid
            lo = mid + 1
        else:
            hi = mid - 1

    return start_idx, end_idx


# ---------------------------------------------------------------------------
# Ticker normalisation
# ---------------------------------------------------------------------------

def _to_qlib_instrument(symbol: str) -> str:
    """
    Convert ticker to qlib instrument name (lowercase directory name).

    Examples:
      601899.SH  -> sh601899
      000858.SZ  -> sz000858
      600519.SS  -> sh600519   (SS -> SH)
      0700.HK    -> hk00700

    Raises DataVendorUnavailable for non-A-share / non-HK tickers.
    """
    raw = symbol.strip().upper()

    # Normalise exchange suffix aliases
    _ALIAS = {"SS": "SH", "SSE": "SH", "SZSE": "SZ", "BSE": "BJ", "HKG": "HK", "SEHK": "HK"}

    if "." in raw:
        code, exch = raw.rsplit(".", 1)
        exch = _ALIAS.get(exch, exch)
    else:
        raise DataVendorUnavailable(f"Cannot determine exchange for ticker '{symbol}'")

    supported = {"SH", "SZ", "BJ", "HK"}
    if exch not in supported:
        raise DataVendorUnavailable(
            f"Ticker '{symbol}' (exchange={exch}) is not a CN/HK stock; qlib local data only supports {supported}."
        )

    # HK stock codes are 5 digits (e.g., 0700.HK → hk00700)
    if exch == "HK":
        code = code.zfill(5)

    return f"{exch.lower()}{code}"


# ---------------------------------------------------------------------------
# Binary feature reader
# ---------------------------------------------------------------------------

def _read_feature(
    instrument: str, field: str, start_date: str, end_date: str
) -> pd.Series:
    """
    Read a single feature field for an instrument over [start_date, end_date].

    Returns a pd.Series with DatetimeIndex. Empty Series if no data.
    """
    data_path = _feature_root_for(instrument)
    bin_path = data_path / "features" / instrument / f"{field}.day.bin"

    if not bin_path.exists():
        return pd.Series(dtype="float64", name=field)

    with open(bin_path, "rb") as f:
        raw = f.read()

    if len(raw) < 4:
        return pd.Series(dtype="float64", name=field)

    # First 4 bytes: float32 calendar start index
    file_start_idx = int(round(struct.unpack("<f", raw[:4])[0]))
    values = np.frombuffer(raw[4:], dtype="<f4").astype("float64")

    cal = _load_calendar()
    file_end_idx = file_start_idx + len(values) - 1

    # Requested range
    req_start_idx, req_end_idx = _date_to_cal_range(start_date, end_date)

    # Intersect
    actual_start = max(req_start_idx, file_start_idx)
    actual_end = min(req_end_idx, file_end_idx)

    if actual_start > actual_end:
        return pd.Series(dtype="float64", name=field)

    slice_start = actual_start - file_start_idx
    slice_end = actual_end - file_start_idx + 1
    data_slice = values[slice_start:slice_end]
    dates = [cal[i] for i in range(actual_start, actual_end + 1)]

    series = pd.Series(data_slice, index=pd.DatetimeIndex(dates), name=field)
    # Drop NaN rows (qlib uses NaN for missing trading days)
    return series.dropna()


def _expected_last_trading_day(end_date: str) -> Optional[pd.Timestamp]:
    """Return the last trading day on or before *end_date*."""
    _, end_idx = _date_to_cal_range(end_date, end_date)
    if end_idx < 0:
        return None
    return pd.Timestamp(_load_calendar()[end_idx])


def _drop_incomplete_market_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows with a complete daily bar."""
    if df.empty:
        return df

    required_cols = [col for col in ["open", "high", "low", "close", "volume"] if col in df.columns]
    if required_cols:
        df = df.dropna(subset=required_cols, how="any")
    return df


def _restore_original_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Convert qlib-adjusted OHLCV values back to original market scale."""
    if df.empty or "factor" not in df.columns:
        return df

    restored = df.copy()
    factor = pd.to_numeric(restored["factor"], errors="coerce")
    valid_factor = factor.notna() & (factor != 0)
    if not valid_factor.all():
        restored = restored.loc[valid_factor].copy()
        factor = factor.loc[valid_factor]

    for col in ["open", "high", "low", "close"]:
        if col in restored.columns:
            restored[col] = pd.to_numeric(restored[col], errors="coerce") / factor

    if "volume" in restored.columns:
        restored["volume"] = pd.to_numeric(restored["volume"], errors="coerce") * factor

    restored.index = pd.DatetimeIndex(restored.index)
    return restored.drop(columns=["factor"])


def _ensure_local_data_is_current(df: pd.DataFrame, instrument: str, end_date: str) -> None:
    """Raise when local qlib data is stale relative to the requested end date."""
    if df.empty:
        return

    _ensure_local_calendar_covers(end_date)
    expected_last_day = _expected_last_trading_day(end_date)
    if expected_last_day is None:
        return

    latest_available = pd.Timestamp(df.index.max())
    if latest_available < expected_last_day:
        raise DataVendorUnavailable(
            f"Qlib local data for '{instrument}' is incomplete: latest complete bar is "
            f"{latest_available.strftime('%Y-%m-%d')}, requested through {expected_last_day.strftime('%Y-%m-%d')}."
        )


def _load_ohlcv(
    instrument: str, start_date: str, end_date: str
) -> pd.DataFrame:
    """Load OHLCV + Amount DataFrame for an instrument."""
    fields = ["open", "high", "low", "close", "volume", "amount", "factor"]
    series_dict = {}
    for field in fields:
        s = _read_feature(instrument, field, start_date, end_date)
        series_dict[field] = s

    df = pd.DataFrame(series_dict)
    df.index.name = "Date"
    df = _restore_original_ohlcv(df)
    return _drop_incomplete_market_rows(df)


# ---------------------------------------------------------------------------
# Public vendor functions (matching tushare.py signatures)
# ---------------------------------------------------------------------------

def get_stock(symbol: str, start_date: str, end_date: str) -> str:
    """
    Return OHLCV data for *symbol* between *start_date* and *end_date* as CSV.

    Raises DataVendorUnavailable when data cannot be found locally.
    """
    instrument = _to_qlib_instrument(symbol)
    df = _load_ohlcv(instrument, start_date, end_date)

    if df.empty:
        raise DataVendorUnavailable(
            f"No qlib local data for '{instrument}' between {start_date} and {end_date}."
        )
    _ensure_local_data_is_current(df, instrument, end_date)

    output = df.copy()
    output.index = output.index.strftime("%Y-%m-%d")
    output.columns = [c.capitalize() for c in output.columns]
    output.index.name = "Date"
    output = output.reset_index()

    header = f"Qlib local stock data for {symbol} from {start_date} to {end_date}"
    return header + "\n" + output.to_csv(index=False)


def _load_price_frame(
    symbol: str, curr_date: str, look_back_days: int = 260
) -> pd.DataFrame:
    """
    Load price DataFrame needed by get_indicator (stockstats format).

    Raises DataVendorUnavailable if insufficient data.
    """
    instrument = _to_qlib_instrument(symbol)
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    df = _load_ohlcv(instrument, start_date, curr_date)

    if df.empty or len(df) < 5:
        raise DataVendorUnavailable(
            f"Insufficient qlib local data for '{instrument}' before {curr_date}."
        )
    _ensure_local_data_is_current(df, instrument, curr_date)

    # Rename to match stockstats expectations
    df = df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    })
    df["Date"] = df.index
    return df.reset_index(drop=True)


_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50 SMA: A medium-term trend indicator.",
    "close_200_sma": "200 SMA: A long-term trend benchmark.",
    "close_10_ema": "10 EMA: A responsive short-term average.",
    "macd": "MACD: Computes momentum via differences of EMAs.",
    "macds": "MACD Signal: An EMA smoothing of the MACD line.",
    "macdh": "MACD Histogram: Shows the gap between the MACD line and its signal.",
    "rsi": "RSI: Measures momentum to flag overbought/oversold conditions.",
    "boll": "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands.",
    "boll_ub": "Bollinger Upper Band: Typically 2 standard deviations above the middle line.",
    "boll_lb": "Bollinger Lower Band: Typically 2 standard deviations below the middle line.",
    "atr": "ATR: Averages true range to measure volatility.",
    "vwma": "VWMA: A moving average weighted by volume.",
    "mfi": "MFI: Uses both price and volume to measure buying and selling pressure.",
}


def get_indicator(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int,
) -> str:
    """
    Compute a technical indicator for *symbol* using qlib local OHLCV data.

    Raises DataVendorUnavailable if local data is insufficient.
    """
    if indicator not in _INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"Indicator '{indicator}' is not supported. Choose from: {list(_INDICATOR_DESCRIPTIONS.keys())}"
        )

    current_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = current_dt - timedelta(days=look_back_days)

    stats_df = wrap(_load_price_frame(symbol, curr_date))
    stats_df["Date"] = pd.to_datetime(stats_df["Date"]).dt.strftime("%Y-%m-%d")
    # Trigger computation
    _ = stats_df[indicator]

    lines = []
    probe_dt = current_dt
    while probe_dt >= start_dt:
        date_str = probe_dt.strftime("%Y-%m-%d")
        row = stats_df[stats_df["Date"] == date_str]
        if row.empty:
            lines.append(f"{date_str}: N/A: Not a trading day (weekend or holiday)")
        else:
            value = row.iloc[0][indicator]
            if pd.isna(value):
                lines.append(f"{date_str}: N/A")
            else:
                lines.append(f"{date_str}: {value}")
        probe_dt -= timedelta(days=1)

    return (
        f"## {indicator} values from {start_dt.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
        + "\n".join(lines)
        + "\n\n"
        + _INDICATOR_DESCRIPTIONS[indicator]
    )
