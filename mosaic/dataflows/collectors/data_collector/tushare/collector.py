from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set
import json
import time

import multiprocessing
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
from loguru import logger
from qlib.utils import code_to_fname, fname_to_code

try:
    import tushare as ts
except ImportError:  # pragma: no cover - optional dependency for tests without network
    ts = None

# ensure qlib scripts on path for relative imports
CUR_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = CUR_DIR.parent.parent
for p in (CUR_DIR, SCRIPTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from dump_bin import DumpDataAll, DumpDataUpdate  # noqa: E402
from data_collector.base import BaseCollector, BaseNormalize, BaseRun, Normalize  # noqa: E402
from data_collector.utils import get_calendar_list  # noqa: E402

DEFAULT_BASE_DIR = CUR_DIR  # align with yahoo collector default_base_dir
DEFAULT_QLIB_DIR = Path.home() / ".qlib" / "qlib_data"
FEATURE_SPAN_FIELDS = ("close", "open", "high", "low", "factor", "volume")
RETROACTIVE_FACTOR_LOOKBACK = 5
RETROACTIVE_FACTOR_RTOL = 1e-6
RETROACTIVE_FACTOR_ATOL = 1e-5


def _get_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required; set it as an environment variable.")
    return token.strip()


def ts_code_to_qlib_symbol(ts_code: str) -> str:
    """Convert TuShare ts_code (e.g., 000001.SZ) to qlib symbol (e.g., sz000001)."""
    if not ts_code:
        return ts_code
    parts = ts_code.split(".")
    code = parts[0]
    suffix = parts[1].lower() if len(parts) > 1 else ""
    if suffix.startswith("sz"):
        return f"sz{code}"
    if suffix.startswith("sh"):
        return f"sh{code}"
    if suffix.startswith("bj"):
        return f"bj{code}"
    return f"{suffix}{code}" if suffix else code


def _normalize_factor(series: pd.Series) -> pd.Series:
    """Normalize adj_factor so the first valid value per symbol becomes 1.0."""
    if series.empty:
        return series
    first_valid = series.dropna().iloc[0] if series.dropna().size else np.nan
    if pd.isna(first_valid) or float(first_valid) == 0:
        return pd.Series([1.0] * len(series), index=series.index)
    return series / float(first_valid)


def _normalize_first_close(series: pd.Series) -> pd.Series:
    """
    Broadcast the first valid adjusted close per symbol.

    qlib daily data uses an additional normalization step where price-like fields
    are scaled by the first valid adjusted close, so `$close / $factor` recovers
    the raw trade price and `$volume * $factor` recovers the raw volume.
    """
    if series.empty:
        return series
    valid = series.dropna()
    if valid.empty:
        return pd.Series([np.nan] * len(series), index=series.index)
    first_valid = float(valid.iloc[0])
    if first_valid == 0:
        return pd.Series([np.nan] * len(series), index=series.index)
    return pd.Series([first_valid] * len(series), index=series.index)


def rescale_normalized_df_to_bin(
    df_new: pd.DataFrame,
    df_full: pd.DataFrame,
    qlib_dir: Path,
    symbol: str,
    freq: str = "day",
) -> pd.DataFrame:
    """
    Rescale incremental normalized CSV rows to match the existing bin's
    normalization constant.

    When source CSVs are missing early dates, normalize_tushare_eod() produces
    values with a different first_close constant than the existing bin.  This
    function detects the mismatch at the overlap point and rescales the new
    data so the transition is seamless.

    Price-like fields (open/high/low/close/factor/vwap) are multiplied by
    the rescale ratio.  Volume is divided.  Amount is left unchanged.
    """
    PRICE_FIELDS = {"open", "high", "low", "close", "factor", "vwap"}
    VOLUME_FIELDS = {"volume"}

    if df_new.empty:
        return df_new

    symbol_lower = symbol.lower()
    bin_path = qlib_dir / "features" / symbol_lower / f"close.{freq}.bin"
    if not bin_path.exists():
        return df_new  # new symbol, no existing bin to match

    # Read existing bin's last value
    raw = np.fromfile(str(bin_path), dtype="<f4")
    if raw.size <= 1:
        return df_new

    cal_path = qlib_dir / "calendars" / f"{freq}.txt"
    if not cal_path.exists():
        return df_new
    calendar_lines = cal_path.read_text().strip().splitlines()
    calendar = []
    for line in calendar_lines:
        d = line.strip()
        if len(d) == 8 and "-" not in d:
            d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        calendar.append(d)

    start_idx = int(round(float(raw[0])))
    values = raw[1:]
    bin_dates = calendar[start_idx : start_idx + len(values)]
    if not bin_dates:
        return df_new

    # Find overlap: use the full normalized CSV (df_full) to locate the
    # bin's last date, since df_new only has dates AFTER the bin's last date.
    last_bin_close = float(values[-1])
    full_dates = pd.to_datetime(df_full["date"]) if not pd.api.types.is_datetime64_any_dtype(df_full["date"]) else df_full["date"]

    norm_close = None
    for offset in range(0, 10):
        if offset >= len(bin_dates):
            break
        check_date = pd.Timestamp(bin_dates[-(offset + 1)])
        match_rows = df_full[full_dates == check_date]
        if not match_rows.empty:
            candidate = float(match_rows.iloc[0]["close"])
            if candidate != 0:
                norm_close = candidate
                last_bin_close = float(values[-(offset + 1)])
                break

    if norm_close is None or norm_close == 0 or last_bin_close == 0:
        logger.warning(f"  {symbol}: cannot find overlap date for bin rescale; skipping rescale")
        return df_new

    ratio = last_bin_close / norm_close
    if abs(ratio - 1.0) < 1e-6:
        return df_new  # already aligned

    logger.info(f"  {symbol}: rescaling normalized data by {ratio:.6f} to match bin")

    result = df_new.copy()
    for col in result.columns:
        if col in PRICE_FIELDS:
            result[col] = result[col].astype(float) * ratio
        elif col in VOLUME_FIELDS:
            result[col] = result[col].astype(float) / ratio
        # amount, adjclose, date, symbol: unchanged

    return result


def normalize_tushare_eod(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize TuShare EOD dataframe to qlib-compatible CSV schema.

    Expected raw columns: ts_code, trade_date, open, high, low, close, vol, adj_factor[, amount]
    Output columns follow qlib daily conventions where price-like fields are
    standardized by the first valid adjusted close.
    """
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "volume", "amount", "factor", "change", "symbol"]
        )

    data = df.copy()
    rename_map = {"trade_date": "date", "vol": "volume"}
    data.rename(columns=rename_map, inplace=True)

    if "date" not in data.columns:
        raise ValueError("Input dataframe must contain trade_date or date column.")

    # ensure yyyymmdd strings parsed correctly even if read as int
    data["date"] = pd.to_datetime(data["date"].astype(str))

    if "ts_code" in data.columns:
        data["symbol"] = data["ts_code"].apply(ts_code_to_qlib_symbol)
    elif "symbol" in data.columns:
        data["symbol"] = data["symbol"].apply(ts_code_to_qlib_symbol)
    else:
        raise ValueError("Input dataframe must contain ts_code or symbol column.")

    data.sort_values(["symbol", "date"], inplace=True)
    if "adj_factor" not in data.columns:
        data["adj_factor"] = 1.0
    data["adj_factor"] = data.groupby("symbol")["adj_factor"].transform(lambda s: s.ffill().bfill())
    data["factor"] = data.groupby("symbol")["adj_factor"].transform(_normalize_factor).fillna(1.0)

    # CRITICAL: compute adjusted_close BEFORE any in-place price transformations.
    # raw_close is the original tushare close (not yet multiplied by factor).
    # adjclose = raw_close * adj_factor — this is the raw forward-adjusted price,
    # stored in absolute scale (NOT divided by first_close_norm1).
    # The first_close normalization only applies to $close to make it a ratio;
    # adjclose must remain in absolute scale so $adjclose/$factor recovers
    # the true forward-adjusted close = raw_close * adj_factor / first_adj_factor.
    adjusted_close = (data["close"].astype(float) * data["adj_factor"].astype(float)).copy()

    for price_col in ["open", "high", "low", "close"]:
        if price_col in data.columns:
            data[price_col] = data[price_col].astype(float) * data["factor"]

    if "volume" in data.columns:
        safe_factor = data["factor"].replace({0: np.nan})
        data["volume"] = data["volume"].astype(float) / safe_factor

    cols = ["date", "open", "high", "low", "close", "volume", "factor", "symbol"]
    if "amount" in data.columns:
        data["amount"] = data["amount"].astype(float)
        cols.insert(cols.index("factor"), "amount")

    # Calculate vwap: volume-weighted average price = amount / volume
    # Falls back to (high+low+close)/3 when volume is 0 or amount unavailable
    if {"amount", "volume"}.issubset(data.columns):
        data["vwap"] = data["amount"] / data["volume"].replace(0, np.nan)
    else:
        data["vwap"] = (data["high"] + data["low"] + data["close"]) / 3
    data["vwap"] = data["vwap"].astype(float)
    cols.append("vwap")

    first_close = data.groupby("symbol")["close"].transform(_normalize_first_close)
    price_like_cols = ["open", "high", "low", "close", "factor", "vwap"]
    for col in price_like_cols:
        if col in data.columns:
            data[col] = data[col].astype(float) / first_close
    if "volume" in data.columns:
        data["volume"] = data["volume"].astype(float) * first_close

    # adjclose: raw forward-adjusted price in absolute scale.
    # NOT divided by first_close — that normalization only applies to $close.
    data["adjclose"] = adjusted_close
    cols.append("adjclose")

    normalized = data[cols].copy()
    normalized["date"] = normalized["date"].dt.strftime("%Y-%m-%d")
    return normalized.reset_index(drop=True)


def _fetch_tushare_date_data(token: str, timeout: int, trade_date: pd.Timestamp) -> pd.DataFrame:
    """Fetch all stock EOD data for one trading day."""
    date_str = pd.Timestamp(trade_date).strftime("%Y%m%d")
    pro = ts.pro_api(token, timeout=timeout)

    daily = pro.daily(trade_date=date_str)
    if daily is None or daily.empty:
        return pd.DataFrame()

    adj = pro.adj_factor(trade_date=date_str)
    if adj is not None and not adj.empty:
        merged = pd.merge(daily, adj, on=["ts_code", "trade_date"], how="left")
    else:
        merged = daily.copy()
        merged["adj_factor"] = 1.0

    merged["symbol"] = merged["ts_code"].apply(ts_code_to_qlib_symbol)
    merged["date"] = pd.to_datetime(merged["trade_date"])
    cols = ["ts_code", "date", "open", "high", "low", "close", "vol", "amount", "adj_factor", "symbol"]
    return merged[[c for c in cols if c in merged.columns]]


def _fetch_tushare_date_data_with_retry(
    token: str,
    timeout: int,
    trade_date: pd.Timestamp,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Fetch one trading date and retry when TuShare returns an empty result."""
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            df = _fetch_tushare_date_data(token, timeout, trade_date)
            if df is None or df.empty:
                raise RuntimeError(f"Empty TuShare daily result for trading date {pd.Timestamp(trade_date).date()}")
            return df
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                logger.warning(
                    f"Fetch {pd.Timestamp(trade_date).date()} failed on attempt {attempt + 1}/{max_retries}: {e}"
                )
                time.sleep(5 * (attempt + 1))
            else:
                raise RuntimeError(
                    f"Failed to fetch trading date {pd.Timestamp(trade_date).date()} after {max_retries} attempts"
                ) from last_error
    raise RuntimeError(f"Unexpected retry state for trading date {pd.Timestamp(trade_date).date()}")


def _process_date_chunk(args) -> Set[str]:
    """Worker entrypoint for parallel date fetch; kept at module level for multiprocessing."""
    chunk_dates, token, timeout, temp_dir, safe_calls_per_minute, api_calls_per_date = args

    temp_daily_dir = Path(temp_dir) / "daily"
    temp_daily_dir.mkdir(parents=True, exist_ok=True)

    local_processed: Set[str] = set()
    local_call_count = 0
    chunk_start_time = time.time()

    for trade_date in chunk_dates:
        if local_call_count > 0 and local_call_count % 100 == 0:
            elapsed = time.time() - chunk_start_time
            expected_elapsed = local_call_count * 60 / safe_calls_per_minute
            if elapsed < expected_elapsed:
                time.sleep(min(5, expected_elapsed - elapsed))

        try:
            df = _fetch_tushare_date_data_with_retry(token, timeout, trade_date)
            local_call_count += api_calls_per_date
            date_str = pd.Timestamp(trade_date).strftime("%Y%m%d")
            df.to_csv(temp_daily_dir / f"{date_str}.csv", index=False)
            local_processed.add(pd.Timestamp(trade_date).strftime("%Y-%m-%d"))
        except Exception as e:
            logger.warning(f"Parallel fetch failed for {trade_date}: {e}")

    return local_processed


def dump_eod_to_qlib(
    data_path: Path,
    qlib_dir: Path,
    mode: str = "all",
    max_workers: int = 16,
    exclude_fields: str = "symbol,date",
    file_suffix: str = ".csv",
) -> Path:
    """
    Dump normalized EOD CSVs into qlib binary format.
    """
    qlib_dir = Path(qlib_dir).expanduser()
    qlib_dir.mkdir(parents=True, exist_ok=True)
    data_path = Path(data_path).expanduser()

    dumper_cls = DumpDataUpdate if mode.lower() == "update" else DumpDataAll
    dumper = dumper_cls(
        data_path=str(data_path),
        qlib_dir=str(qlib_dir),
        freq="day",
        max_workers=max_workers,
        date_field_name="date",
        symbol_field_name="symbol",
        exclude_fields=exclude_fields,
        file_suffix=file_suffix,
    )
    dumper.dump()
    return qlib_dir


def extend_index_instruments(qlib_dir: str | Path) -> None:
    """
    将 qlib_dir/instruments/csi*.txt 中当前成分段的 end_date 延伸到最新交易日。

    指数成分每半年调整一次（6月/12月底），平时只需延伸 end_date 即可。
    成分实际变更时需重新运行 cn_index collector 生成完整文件。
    """
    qlib_dir = Path(qlib_dir).expanduser().resolve()
    inst_dir = qlib_dir / "instruments"

    # 从 calendars/day.txt 获取最新交易日
    cal_file = qlib_dir / "calendars" / "day.txt"
    if not cal_file.exists():
        logger.warning(f"Calendar file not found: {cal_file}, skip index update")
        return
    cal_df = pd.read_csv(cal_file, header=None, names=["date"])
    latest_date = str(cal_df["date"].iloc[-1]).replace("-", "")

    for csi_file in sorted(inst_dir.glob("csi*.txt")):
        df = pd.read_csv(csi_file, sep="\t", header=None, names=["symbol", "start", "end"])
        # 找到当前最大的 end_date
        max_end = df["end"].max()
        if max_end is pd.NaT or str(max_end).replace("-", "") >= latest_date:
            continue
        mask = df["end"] == max_end
        count = mask.sum()
        df.loc[mask, "end"] = latest_date
        df.to_csv(csi_file, sep="\t", header=False, index=False)
        logger.info(f"Extended {csi_file.name}: {count} rows end_date {max_end} -> {latest_date}")


def validate_qlib_dir(qlib_dir: Path, freq: str = "day") -> Dict[str, Optional[str]]:
    """
    Lightweight validation of a qlib directory. Returns a dict with None when healthy.
    """
    qlib_dir = Path(qlib_dir).expanduser()
    results: Dict[str, Optional[str]] = {"calendars": None, "instruments": None, "features": None}

    cal_file = qlib_dir / "calendars" / f"{freq}.txt"
    if not cal_file.exists() or cal_file.stat().st_size == 0:
        results["calendars"] = f"missing calendars at {cal_file}"

    inst_file = qlib_dir / "instruments" / "all.txt"
    if not inst_file.exists() or inst_file.stat().st_size == 0:
        results["instruments"] = f"missing instruments at {inst_file}"

    feat_dir = qlib_dir / "features"
    has_bins = feat_dir.exists() and any(feat_dir.glob("*/*.bin"))
    if not has_bins:
        results["features"] = f"no feature bins under {feat_dir}"

    return results


def load_qlib_calendar(qlib_dir: str | Path, freq: str = "day") -> List[pd.Timestamp]:
    """Load qlib trading calendar as normalized timestamps."""
    cal_file = Path(qlib_dir).expanduser() / "calendars" / f"{freq}.txt"
    if not cal_file.exists():
        raise FileNotFoundError(f"calendar file not found: {cal_file}")
    df = pd.read_csv(cal_file, header=None, names=["date"], dtype=str)
    normalized = [_normalize_calendar_value(d) for d in df["date"].tolist()]
    return [pd.Timestamp(d) for d in normalized if d is not None]


def _normalize_calendar_value(value: object) -> Optional[str]:
    """Normalize a calendar token to YYYYMMDD, dropping obviously invalid dates."""
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = pd.Timestamp(text)
    except Exception:
        return None
    if dt.year < 1990 or dt.year > 2100:
        return None
    return dt.strftime("%Y%m%d")


def get_feature_span(
    feature_dir: Path,
    calendar: List[pd.Timestamp],
    freq: str = "day",
    fields: Iterable[str] = FEATURE_SPAN_FIELDS,
) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
    """
    Return the actual first/last data dates stored in feature bins.
    """
    invalid_range: Optional[tuple[int, int]] = None
    for field in fields:
        bin_path = feature_dir / f"{field}.{freq}.bin"
        if not bin_path.exists():
            continue

        raw = np.fromfile(bin_path, dtype="<f4")
        if raw.size <= 1:
            continue

        file_start_idx = int(round(float(raw[0])))
        values = raw[1:]
        valid_pos = np.flatnonzero(~np.isnan(values))
        if valid_pos.size == 0:
            continue

        first_idx = file_start_idx + int(valid_pos[0])
        last_idx = file_start_idx + int(valid_pos[-1])
        if first_idx < 0 or last_idx >= len(calendar):
            invalid_range = (first_idx, last_idx)
            continue

        return calendar[first_idx], calendar[last_idx]

    if invalid_range is not None:
        logger.warning(
            f"Skip invalid feature span for {feature_dir.name}: "
            f"[{invalid_range[0]}, {invalid_range[1]}] out of calendar range"
        )
    return None


def reconcile_instruments_from_features(
    qlib_dir: str | Path,
    freq: str = "day",
) -> Dict[str, object]:
    """
    Rebuild instruments/all.txt from actual feature bin coverage.
    """
    qlib_dir = Path(qlib_dir).expanduser().resolve()
    features_dir = qlib_dir / "features"
    inst_file = qlib_dir / "instruments" / "all.txt"
    calendar = load_qlib_calendar(qlib_dir, freq=freq)

    if not features_dir.exists():
        raise FileNotFoundError(f"features directory not found: {features_dir}")

    existing_df = pd.DataFrame(columns=["symbol", "start", "end"])
    if inst_file.exists():
        existing_df = pd.read_csv(inst_file, sep="\t", header=None, names=["symbol", "start", "end"], dtype=str)

    rows = []
    skipped_dirs: List[str] = []
    for feature_dir in sorted(features_dir.iterdir()):
        if not feature_dir.is_dir():
            continue

        span = get_feature_span(feature_dir, calendar, freq=freq)
        if span is None:
            skipped_dirs.append(feature_dir.name)
            continue

        start_dt, end_dt = span
        rows.append(
            {
                "symbol": fname_to_code(feature_dir.name).upper(),
                "start": start_dt.strftime("%Y-%m-%d"),
                "end": end_dt.strftime("%Y-%m-%d"),
            }
        )

    if not rows:
        raise RuntimeError(f"No valid feature spans found under {features_dir}")

    actual_df = pd.DataFrame(rows).sort_values("symbol").reset_index(drop=True)
    merged = existing_df.merge(actual_df, on="symbol", how="outer", suffixes=("_old", "_new"), indicator=True)
    changed = merged[
        (merged["_merge"] != "both")
        | (merged["start_old"].fillna("") != merged["start_new"].fillna(""))
        | (merged["end_old"].fillna("") != merged["end_new"].fillna(""))
    ]

    inst_file.parent.mkdir(parents=True, exist_ok=True)
    actual_df.to_csv(inst_file, sep="\t", header=False, index=False)

    last_dates = {row["symbol"]: pd.Timestamp(row["end"]) for _, row in actual_df.iterrows()}
    latest_feature_date = max(last_dates.values()) if last_dates else None
    logger.info(
        "Reconciled instruments/all.txt from features: "
        f"{len(actual_df)} symbols, {len(changed)} changed, "
        f"{int((merged['_merge'] == 'right_only').sum())} added, "
        f"{int((merged['_merge'] == 'left_only').sum())} dropped, "
        f"{len(skipped_dirs)} skipped"
    )

    return {
        "instrument_last_dates": last_dates,
        "latest_feature_date": latest_feature_date,
        "changed_count": int(len(changed)),
        "added_count": int((merged["_merge"] == "right_only").sum()),
        "dropped_count": int((merged["_merge"] == "left_only").sum()),
        "skipped_dirs": skipped_dirs,
    }


def get_csv_span(csv_file: str | Path) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return the first/last date contained in a normalized csv file."""
    csv_file = Path(csv_file)
    if not csv_file.exists():
        return None

    df = pd.read_csv(csv_file, usecols=lambda c: c in ["date", "trade_date"], low_memory=False)
    if df.empty:
        return None

    date_col = "date" if "date" in df.columns else "trade_date" if "trade_date" in df.columns else None
    if date_col is None:
        return None

    dates = pd.to_datetime(df[date_col].astype(str), errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.min(), dates.max()


def load_feature_field_series(
    feature_dir: str | Path,
    calendar: List[pd.Timestamp],
    field: str,
    freq: str = "day",
) -> Optional[pd.Series]:
    """Load one qlib feature bin into a date-indexed series."""
    feature_dir = Path(feature_dir)
    bin_path = feature_dir / f"{field}.{freq}.bin"
    if not bin_path.exists():
        return None

    raw = np.fromfile(bin_path, dtype="<f4")
    if raw.size <= 1:
        return None

    start_idx = int(round(float(raw[0])))
    values = raw[1:]
    end_idx = start_idx + len(values)
    if start_idx < 0 or end_idx > len(calendar):
        logger.warning(
            f"Skip invalid {field} series for {feature_dir.name}: "
            f"[{start_idx}, {end_idx}) out of calendar range"
        )
        return None

    index = pd.DatetimeIndex(calendar[start_idx:end_idx], name="date")
    return pd.Series(values.astype(float), index=index, name=field)


def load_normalized_csv(csv_file: str | Path, usecols=None) -> pd.DataFrame:
    """Load one normalized csv with stable date parsing and deduplication."""
    csv_file = Path(csv_file)
    df = pd.read_csv(csv_file, usecols=usecols, low_memory=False)
    if df.empty or "date" not in df.columns:
        return df

    df["date"] = pd.to_datetime(df["date"].astype(str), errors="coerce")
    df = df.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last").sort_values("date")
    return df.reset_index(drop=True)


def detect_retroactive_factor_rebuilds(
    csv_files: Iterable[str | Path],
    qlib_dir: str | Path,
    freq: str = "day",
    lookback: int = RETROACTIVE_FACTOR_LOOKBACK,
    rtol: float = RETROACTIVE_FACTOR_RTOL,
    atol: float = RETROACTIVE_FACTOR_ATOL,
) -> Dict[str, str]:
    """
    Detect symbols whose normalized factor history no longer matches existing qlib bins.

    This happens after splits/consolidations when TuShare back-adjusts historical
    `adj_factor` values but the incremental qlib update only appends new rows.
    """
    qlib_dir = Path(qlib_dir).expanduser().resolve()
    calendar = load_qlib_calendar(qlib_dir, freq=freq)
    rebuild_reasons: Dict[str, str] = {}

    for csv_file in sorted({Path(p).expanduser().resolve() for p in csv_files}):
        symbol = fname_to_code(csv_file.stem).upper()
        feature_dir = qlib_dir / "features" / symbol.lower()
        if not feature_dir.exists():
            continue

        feature_span = get_feature_span(feature_dir, calendar, freq=freq)
        if feature_span is None:
            rebuild_reasons[symbol] = "existing feature span is invalid"
            continue

        factor_df = load_normalized_csv(csv_file, usecols=lambda c: c in {"date", "factor"})
        if factor_df.empty or "factor" not in factor_df.columns:
            continue

        overlap_df = factor_df[
            (factor_df["date"] >= feature_span[0]) & (factor_df["date"] <= feature_span[1])
        ].dropna(subset=["factor"])
        if overlap_df.empty:
            continue

        expected = overlap_df.tail(max(int(lookback), 1)).set_index("date")["factor"].astype(float)
        actual = load_feature_field_series(feature_dir, calendar, "factor", freq=freq)
        if actual is None:
            rebuild_reasons[symbol] = "existing factor bin is missing"
            continue

        actual = actual.reindex(expected.index)
        if actual.isna().any():
            missing_dates = ",".join(d.strftime("%Y-%m-%d") for d in actual[actual.isna()].index[:3])
            rebuild_reasons[symbol] = f"existing factor bin misses overlap dates: {missing_dates}"
            continue

        actual_values = actual.to_numpy(dtype=float)
        expected_values = expected.to_numpy(dtype=float)
        if np.allclose(actual_values, expected_values, rtol=rtol, atol=atol, equal_nan=True):
            continue

        mismatch_idx = int(np.flatnonzero(~np.isclose(actual_values, expected_values, rtol=rtol, atol=atol))[0])
        mismatch_date = expected.index[mismatch_idx].strftime("%Y-%m-%d")
        rebuild_reasons[symbol] = (
            f"factor changed at {mismatch_date}: "
            f"bin={actual_values[mismatch_idx]:.6f}, normalized={expected_values[mismatch_idx]:.6f}"
        )

    return rebuild_reasons


def rebuild_feature_bin_from_csv(
    csv_file: str | Path,
    qlib_dir: str | Path,
    calendar: List[pd.Timestamp],
    freq: str = "day",
) -> Optional[str]:
    """Rebuild one feature directory from a normalized csv using the current qlib calendar."""
    csv_file = Path(csv_file)
    qlib_dir = Path(qlib_dir).expanduser().resolve()

    df = pd.read_csv(csv_file, low_memory=False)
    if df.empty or "date" not in df.columns:
        return None

    df["date"] = pd.to_datetime(df["date"].astype(str), errors="coerce")
    df = df.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last").sort_values("date")
    if df.empty:
        return None

    calendar_index = {dt: idx for idx, dt in enumerate(calendar)}
    start_dt = pd.Timestamp(df["date"].min())
    end_dt = pd.Timestamp(df["date"].max())
    if start_dt not in calendar_index or end_dt not in calendar_index:
        raise RuntimeError(f"{csv_file.name} date range {start_dt.date()}~{end_dt.date()} not covered by qlib calendar")

    start_idx = calendar_index[start_dt]
    end_idx = calendar_index[end_dt]
    cal_slice = pd.DatetimeIndex(calendar[start_idx : end_idx + 1], name="date")

    data_cols = [c for c in df.columns if c not in {"date", "symbol"}]
    aligned = df.set_index("date")[data_cols].reindex(cal_slice)

    symbol = fname_to_code(csv_file.stem).upper()
    feature_dir = qlib_dir / "features" / symbol.lower()
    feature_dir.mkdir(parents=True, exist_ok=True)
    for old_bin in feature_dir.glob(f"*.{freq}.bin"):
        old_bin.unlink()

    for field in data_cols:
        bin_path = feature_dir / f"{field.lower()}.{freq}.bin"
        np.hstack([start_idx, aligned[field].to_numpy(dtype="<f4", copy=False)]).astype("<f4").tofile(str(bin_path))

    return symbol


def repair_feature_bins_from_normalize(
    normalize_dir: str | Path,
    qlib_dir: str | Path,
    freq: str = "day",
    csv_files: Optional[Iterable[str | Path]] = None,
    force_symbols: Optional[Iterable[str]] = None,
) -> Dict[str, object]:
    """
    Repair qlib feature bins whose actual span disagrees with normalized csv span.
    """
    normalize_dir = Path(normalize_dir).expanduser().resolve()
    qlib_dir = Path(qlib_dir).expanduser().resolve()
    calendar = load_qlib_calendar(qlib_dir, freq=freq)
    force_symbols = {str(symbol).upper() for symbol in (force_symbols or [])}

    rebuilt: List[str] = []
    rebuilt_reasons: Dict[str, str] = {}
    checked = 0
    if csv_files is None:
        candidate_files = sorted(normalize_dir.glob("*.csv"))
    else:
        candidate_files = sorted({Path(p).expanduser().resolve() for p in csv_files})

    for csv_file in candidate_files:
        if csv_file.name == "__inc_tmp__":
            continue
        csv_span = get_csv_span(csv_file)
        if csv_span is None:
            continue
        checked += 1

        symbol = fname_to_code(csv_file.stem).upper()
        feature_span = get_feature_span(qlib_dir / "features" / symbol.lower(), calendar, freq=freq)
        needs_rebuild = symbol in force_symbols or feature_span != csv_span
        if not needs_rebuild:
            continue

        if symbol in force_symbols:
            reason = "forced rebuild"
        else:
            reason = f"feature span {feature_span} != csv span {csv_span}"

        rebuilt_symbol = rebuild_feature_bin_from_csv(csv_file, qlib_dir, calendar, freq=freq)
        if rebuilt_symbol is not None:
            rebuilt.append(rebuilt_symbol)
            rebuilt_reasons[rebuilt_symbol] = reason

    reconcile_result = reconcile_instruments_from_features(qlib_dir, freq=freq)
    logger.info(
        f"Repair feature bins from normalize: checked={checked}, rebuilt={len(rebuilt)}, "
        f"latest_feature_date={reconcile_result.get('latest_feature_date')}"
    )
    return {
        "checked_count": checked,
        "rebuilt_symbols": rebuilt,
        "rebuilt_count": len(rebuilt),
        "rebuilt_reasons": rebuilt_reasons,
        "reconcile_result": reconcile_result,
    }


class TushareCollector(BaseCollector):
    """Daily TuShare collector following the data_collector.BaseCollector contract."""

    def __init__(
        self,
        save_dir: str | Path,
        start: Optional[str] = None,
        end: Optional[str] = None,
        interval: str = "1d",
        max_workers: int = 1,
        max_collector_count: int = 2,
        delay: float = 0,
        check_data_length: Optional[int] = None,
        limit_nums: Optional[int] = None,
        token: Optional[str] = None,
        pro_client=None,
        symbols: Optional[Iterable[str]] = None,
        timeout: int = 60,
        batch_size: int = 0,
        batch_pause: float = 0,
    ):
        if ts is None:
            raise ImportError("tushare is required; install it or add it to your venv.")
        self.token = token or _get_token()
        self.timeout = timeout
        # avoid pickling non-serializable pro_client in multiprocessing; instantiate per call
        self._preset_symbols = list(symbols) if symbols else None
        self.batch_size = batch_size
        self.batch_pause = batch_pause
        self._batch_count = 0
        super().__init__(
            save_dir=save_dir,
            start=start,
            end=end,
            interval=interval,
            max_workers=max_workers,
            max_collector_count=max_collector_count,
            delay=delay,
            check_data_length=check_data_length,
            limit_nums=limit_nums,
        )

    def _simple_collector(self, symbol: str):
        """Override to add batch pause functionality."""
        self.sleep()
        df = self.get_data(symbol, self.interval, self.start_datetime, self.end_datetime)
        _result = self.NORMAL_FLAG
        if self.check_data_length > 0:
            _result = self.cache_small_data(symbol, df)
        if _result == self.NORMAL_FLAG:
            self.save_instrument(symbol, df)

        # Batch pause: sleep after every batch_size symbols
        if self.batch_size > 0 and self.batch_pause > 0:
            self._batch_count = getattr(self, '_batch_count', 0) + 1
            if self._batch_count >= self.batch_size:
                import time as time_module
                time_module.sleep(self.batch_pause)
                self._batch_count = 0

        return _result

    def get_instrument_list(self) -> List[str]:
        if self._preset_symbols:
            return list(self._preset_symbols)
        pro = ts.pro_api(self.token, timeout=self.timeout)
        # include listed, delisted, paused to avoid survivor bias
        basic = pro.stock_basic(exchange="", list_status="L,D,P", fields="ts_code")
        return basic["ts_code"].dropna().unique().tolist()

    def normalize_symbol(self, symbol: str):
        return ts_code_to_qlib_symbol(symbol)

    def get_data(
        self, symbol: str, interval: str, start_datetime: pd.Timestamp, end_datetime: pd.Timestamp
    ) -> pd.DataFrame:
        if interval != self.INTERVAL_1d:
            raise ValueError("TushareCollector currently supports only 1d interval.")

        # determine incremental start based on existing csv to support resume
        start_dt = pd.Timestamp(start_datetime)
        end_dt = pd.Timestamp(end_datetime)

        symbol_fname = code_to_fname(self.normalize_symbol(symbol))
        existing_path = Path(self.save_dir).joinpath(f"{symbol_fname}.csv")
        last_date = None
        if existing_path.exists():
            try:
                # read minimal columns for efficiency
                existing = pd.read_csv(existing_path, usecols=lambda c: c in ["date", "trade_date"])
                if "date" in existing.columns:
                    existing["date"] = pd.to_datetime(existing["date"])
                    last_date = existing["date"].max()
                elif "trade_date" in existing.columns:
                    existing["trade_date"] = pd.to_datetime(existing["trade_date"])
                    last_date = existing["trade_date"].max()
            except Exception as e:  # pragma: no cover - best effort
                logger.warning(f"read existing csv failed for {symbol_fname}: {e}")

        if last_date is not None:
            start_dt = max(start_dt, last_date + pd.Timedelta(days=1))
        if start_dt >= end_dt:
            return pd.DataFrame()

        start_str = start_dt.strftime("%Y%m%d")
        end_str = end_dt.strftime("%Y%m%d")

        pro = ts.pro_api(self.token, timeout=self.timeout)
        daily = pro.daily(ts_code=symbol, start_date=start_str, end_date=end_str)
        adj = pro.adj_factor(ts_code=symbol, start_date=start_str, end_date=end_str)

        if daily is None or daily.empty:
            return pd.DataFrame()

        merged = pd.merge(daily, adj, on=["ts_code", "trade_date"], how="left")
        cols = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "adj_factor"]
        merged = merged[[c for c in cols if c in merged.columns]]
        merged["date"] = pd.to_datetime(merged["trade_date"])
        if last_date is not None:
            merged = merged[merged["date"] > last_date]
        return merged

    def save_instrument(self, symbol, df: pd.DataFrame):
        """
        Overwrite to avoid duplicate rows on rerun: always write deduped by date.
        """
        if df is None or df.empty:
            return

        df = df.copy()
        df = df.loc[:, ~df.columns.duplicated()]
        # ensure date column exists for dedup
        if "trade_date" in df.columns:
            df["date"] = pd.to_datetime(df["trade_date"])
        elif "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        df["symbol"] = self.normalize_symbol(symbol)
        df.sort_values("date", inplace=True)
        df.drop_duplicates(subset=["date"], keep="last", inplace=True)
        if "trade_date" in df.columns:
            df.drop(columns=["trade_date"], inplace=True)

        symbol_fname = code_to_fname(df["symbol"].iloc[0])
        instrument_path = self.save_dir.joinpath(f"{symbol_fname}.csv")
        if instrument_path.exists():
            try:
                existing = pd.read_csv(instrument_path)
                existing = existing.loc[:, ~existing.columns.duplicated()]
                if "date" in existing.columns:
                    existing["date"] = pd.to_datetime(existing["date"])
                    df = pd.concat([existing, df], ignore_index=True, sort=False)
                    df = df.loc[:, ~df.columns.duplicated()]
                    df.sort_values("date", inplace=True)
                    df.drop_duplicates(subset=["date"], keep="last", inplace=True)
            except Exception as e:
                logger.warning(f"read existing csv failed for {instrument_path.name}: {e}")
        df.to_csv(instrument_path, index=False)


class TushareBatchCollector:
    """
    按日期批量获取 TuShare 数据的收集器。

    相比按股票查询，按日期查询效率更高：
    - 按股票: N只股票 x 2次API = 2N 次
    - 按日期: D个交易日 x 2次API = 2D 次 (D << N 时更高效)

    Features:
    - API 限流控制（每分钟最多 500 次调用）
    - 断点续传（通过 progress.json 记录已处理日期）
    - 增量更新（读取 instruments/all.txt 确定需要更新的日期）
    - 新股票自动检测（增量更新时发现新上市股票并补充数据）
    - 并行日期获取（可选多进程加速）
    """

    # API 限制常量
    API_CALLS_PER_MINUTE = 500
    API_ROWS_PER_CALL = 6000
    API_CALLS_PER_DATE = 2  # daily + adj_factor
    SAFE_CALLS_PER_MINUTE = 450  # 留 50 次余量

    def __init__(
        self,
        save_dir: str | Path,
        qlib_dir: str | Path,
        start: Optional[str] = None,
        end: Optional[str] = None,
        token: Optional[str] = None,
        timeout: int = 60,
        delay_per_date: float = 0.1,
        temp_dir: Optional[str | Path] = None,
        max_workers: int = 8,
    ):
        if ts is None:
            raise ImportError("tushare is required; install it or add it to your venv.")

        self.token = token or _get_token()
        self.timeout = timeout
        self.delay_per_date = delay_per_date
        self.max_workers = max_workers

        self.save_dir = Path(save_dir).expanduser().resolve()
        self.save_dir.mkdir(parents=True, exist_ok=True)

        self.qlib_dir = Path(qlib_dir).expanduser().resolve()

        # 临时目录用于存放按日期的数据
        if temp_dir:
            self.temp_dir = Path(temp_dir).expanduser().resolve()
        else:
            self.temp_dir = self.save_dir.parent / "tmp" / "batch_collector"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "daily").mkdir(parents=True, exist_ok=True)

        # 日期范围
        self.start_datetime = pd.Timestamp(start) if start else pd.Timestamp("2000-01-01")
        self.end_datetime = pd.Timestamp(end) if end else pd.Timestamp.now()
        self._start_specified = start is not None  # 标记是否明确指定了 start 参数

    def get_trading_calendar(self, prefer_api: bool = False) -> List[pd.Timestamp]:
        """
        从 TuShare 或 qlib 获取交易日历。

        Args:
            prefer_api: 如果为 True，优先使用 TuShare API 获取最新日历
        """
        # 如果指定了 prefer_api（增量更新模式），优先从 TuShare 获取
        if prefer_api:
            try:
                pro = ts.pro_api(self.token, timeout=self.timeout)
                start_str = self.start_datetime.strftime("%Y%m%d")
                end_str = self.end_datetime.strftime("%Y%m%d")
                cal_df = pro.trade_cal(
                    exchange="",
                    start_date=start_str,
                    end_date=end_str,
                    fields="cal_date,is_open"
                )
                dates = [pd.Timestamp(d) for d in cal_df.loc[cal_df["is_open"] == 1, "cal_date"].tolist()]
                if dates:
                    logger.info(f"Got {len(dates)} trading dates from TuShare API")
                    return dates
            except Exception as e:
                logger.warning(f"TuShare trade_cal failed: {e}")

        # 从 qlib 目录读取
        cal_file = self.qlib_dir / "calendars" / "day.txt"
        if cal_file.exists():
            df = pd.read_csv(cal_file, header=None, names=["date"], dtype=str)
            return [pd.Timestamp(str(d)) for d in df["date"].tolist()]

        # 从 TuShare API 获取
        try:
            pro = ts.pro_api(self.token, timeout=self.timeout)
            start_str = self.start_datetime.strftime("%Y%m%d")
            end_str = self.end_datetime.strftime("%Y%m%d")
            cal_df = pro.trade_cal(
                exchange="",
                start_date=start_str,
                end_date=end_str,
                fields="cal_date,is_open"
            )
            return [pd.Timestamp(d) for d in cal_df.loc[cal_df["is_open"] == 1, "cal_date"].tolist()]
        except Exception as e:
            logger.warning(f"TuShare trade_cal failed: {e}, fallback to get_calendar_list")
            return list(get_calendar_list("ALL"))

    def sync_calendar(self, end: Optional[str] = None) -> List[pd.Timestamp]:
        """
        同步交易日历到 qlib_dir/calendars/day.txt。

        从 TuShare API 获取交易日历，并与现有的 qlib 日历合并。
        不会删除已有日期，只追加新日期。
        """
        end_dt = pd.Timestamp(end) if end else pd.Timestamp.now()

        cal_file = self.qlib_dir / "calendars" / "day.txt"
        existing_dates: Set[str] = set()
        if cal_file.exists():
            try:
                df = pd.read_csv(cal_file, header=None, names=["date"], dtype=str)
                existing_dates = {
                    normalized
                    for normalized in (_normalize_calendar_value(d) for d in df["date"].tolist())
                    if normalized is not None
                }
                logger.info(f"Loaded {len(existing_dates)} existing calendar dates")
            except Exception as e:
                logger.warning(f"Failed to read existing calendar: {e}")

        pro = ts.pro_api(self.token, timeout=self.timeout)
        cal_df = pro.trade_cal(
            exchange="",
            start_date="20000101",
            end_date=end_dt.strftime("%Y%m%d"),
            fields="cal_date,is_open"
        )

        if cal_df is None or cal_df.empty:
            logger.warning("No calendar data from TuShare")
            return []

        trading_dates = {
            normalized
            for normalized in (
                _normalize_calendar_value(d) for d in cal_df.loc[cal_df["is_open"] == 1, "cal_date"].tolist()
            )
            if normalized is not None
        }
        all_dates = sorted(existing_dates | trading_dates)

        cal_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cal_file, "w") as f:
            for d in all_dates:
                f.write(f"{d}\n")

        logger.info(
            f"Calendar synced: {len(all_dates)} total dates, "
            f"{len(all_dates) - len(existing_dates)} new dates added"
        )
        return [pd.Timestamp(str(d)) for d in all_dates]

    def get_instrument_last_dates(self) -> Dict[str, pd.Timestamp]:
        """
        读取 instruments/all.txt，返回每只股票的最后数据日期。

        Returns:
            Dict[str, pd.Timestamp]: {symbol: last_date}
        """
        inst_file = self.qlib_dir / "instruments" / "all.txt"
        if not inst_file.exists():
            logger.warning(f"instruments file not found: {inst_file}")
            return {}

        result = {}
        try:
            df = pd.read_csv(
                inst_file,
                sep="\t",
                header=None,
                names=["symbol", "start_date", "end_date"]
            )
            for _, row in df.iterrows():
                try:
                    result[row["symbol"]] = pd.Timestamp(row["end_date"])
                except Exception:
                    continue
            logger.info(f"Loaded {len(result)} instruments from {inst_file}")
        except Exception as e:
            logger.warning(f"Failed to read instruments file: {e}")

        return result

    def detect_new_stocks(self) -> List[str]:
        """
        检测新上市股票（存在于 TuShare 但不存在于 instruments/all.txt）。
        """
        inst_file = self.qlib_dir / "instruments" / "all.txt"
        if not inst_file.exists():
            return []

        existing = set()
        try:
            df = pd.read_csv(
                inst_file,
                sep="\t",
                header=None,
                names=["symbol", "start_date", "end_date"]
            )
            existing = set(df["symbol"].tolist())
        except Exception:
            pass

        pro = ts.pro_api(self.token, timeout=self.timeout)
        basic = pro.stock_basic(exchange="", list_status="L,D,P", fields="ts_code")
        if basic is None or basic.empty:
            return []

        current_codes = basic["ts_code"].dropna().unique().tolist()
        current_symbols = {ts_code_to_qlib_symbol(code).upper(): code for code in current_codes}
        new_codes = [code for symbol, code in current_symbols.items() if symbol not in existing]

        if new_codes:
            logger.info(
                f"Detected {len(new_codes)} new stocks: "
                f"{sorted(new_codes)[:10]}{'...' if len(new_codes) > 10 else ''}"
            )

        return sorted(new_codes)

    def get_dates_to_update(
        self,
        instrument_last_dates: Dict[str, pd.Timestamp],
        trading_calendar: List[pd.Timestamp]
    ) -> List[pd.Timestamp]:
        """
        确定需要更新的交易日列表。

        策略:
        - 如果指定了 start 参数，直接使用 start 到 end 范围内的日期（增量更新模式）
        - 如果没有指定 start 且存在数据，从最早的最后日期开始更新
        - 如果是首次运行（无现有数据），返回所有交易日
        """
        # 过滤出在日期范围内的交易日
        valid_dates = [
            d for d in trading_calendar
            if self.start_datetime <= d <= self.end_datetime
        ]

        # 如果 start 参数被明确指定（非默认值），直接使用它
        if self._start_specified:
            logger.info(
                f"Start date specified, fetching dates from {self.start_datetime.strftime('%Y-%m-%d')} "
                f"to {self.end_datetime.strftime('%Y-%m-%d')}"
            )
            return valid_dates

        if not instrument_last_dates:
            logger.info("No existing instruments found, will fetch all dates")
            return valid_dates

        # 找出最早的"最后日期"
        min_last_date = min(instrument_last_dates.values())

        # 从 min_last_date 的下一天开始更新
        update_start = min_last_date + pd.Timedelta(days=1)
        update_start = max(update_start, self.start_datetime)

        dates_to_update = [d for d in valid_dates if d >= update_start]
        logger.info(
            f"Found {len(dates_to_update)} dates to update "
            f"(from {update_start.strftime('%Y-%m-%d')} to {self.end_datetime.strftime('%Y-%m-%d')})"
        )

        return dates_to_update

    def load_progress(self) -> Set[str]:
        """
        加载已处理的日期集合，用于断点续传。

        Returns:
            Set[str]: 已处理的日期集合，格式为 {"2024-01-01", ...}
        """
        progress_file = self.temp_dir / "progress.json"
        if not progress_file.exists():
            return set()

        try:
            with open(progress_file, "r") as f:
                data = json.load(f)
            processed = set(data.get("processed_dates", []))
            logger.info(f"Loaded progress: {len(processed)} dates already processed")
            return processed
        except Exception as e:
            logger.warning(f"Failed to load progress: {e}")
            return set()

    def save_progress(self, processed_dates: Set[str]):
        """保存已处理的日期集合"""
        progress_file = self.temp_dir / "progress.json"
        try:
            data = {
                "processed_dates": sorted(list(processed_dates)),
                "last_update": pd.Timestamp.now().isoformat(),
                "config": {
                    "start": self.start_datetime.strftime("%Y-%m-%d"),
                    "end": self.end_datetime.strftime("%Y-%m-%d")
                }
            }
            with open(progress_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save progress: {e}")

    def fetch_date_data(self, trade_date: pd.Timestamp) -> pd.DataFrame:
        """
        获取指定日期的所有股票数据。

        调用 TuShare API:
        1. pro.daily(trade_date='20240101')
        2. pro.adj_factor(trade_date='20240101')
        3. 合并并转换 symbol 格式
        """
        return _fetch_tushare_date_data(self.token, self.timeout, trade_date)

    def save_date_data(self, df: pd.DataFrame, trade_date: pd.Timestamp):
        """将日期数据保存到临时文件"""
        if df.empty:
            return

        date_str = trade_date.strftime("%Y%m%d")
        file_path = self.temp_dir / "daily" / f"{date_str}.csv"
        df.to_csv(file_path, index=False)

    def split_and_merge(self):
        """
        将临时目录中的日期数据按股票分割并合并到最终文件。
        """
        temp_daily_dir = self.temp_dir / "daily"
        all_date_files = list(temp_daily_dir.glob("*.csv"))

        if not all_date_files:
            logger.info("No date files to process")
            return

        logger.info(f"Loading {len(all_date_files)} date files...")

        # 汇总所有数据
        all_data = []
        for f in all_date_files:
            try:
                df = pd.read_csv(f, parse_dates=["date"])
                all_data.append(df)
            except Exception as e:
                logger.warning(f"Failed to read {f}: {e}")

        if not all_data:
            logger.warning("No data loaded from temp files")
            return

        combined = pd.concat(all_data, ignore_index=True)

        # 按 symbol 分组
        logger.info(f"Grouping {len(combined)} records by symbol...")
        grouped = combined.groupby("symbol")

        # 对每个 symbol 合并并保存
        def process_symbol(args):
            symbol, df = args
            symbol_fname = code_to_fname(symbol)
            target_path = self.save_dir / f"{symbol_fname}.csv"

            # 读取现有数据
            if target_path.exists():
                try:
                    existing = pd.read_csv(target_path, parse_dates=["date"])
                    existing = existing.loc[:, ~existing.columns.duplicated()]
                    df = pd.concat([existing, df], ignore_index=True)
                except Exception:
                    pass

            # 去重并排序
            df = df.loc[:, ~df.columns.duplicated()]
            df = df.drop_duplicates(subset=["date"], keep="last")
            df = df.sort_values("date")

            # 保存
            df.to_csv(target_path, index=False)
            return symbol

        # 使用并行处理
        logger.info(f"Processing {len(grouped)} symbols...")
        results = list(map(process_symbol, [(name, group) for name, group in grouped]))
        logger.info(f"Saved {len(results)} symbol files")

    def cleanup_temp_files(self, keep_progress: bool = False):
        """清理临时文件"""
        daily_dir = self.temp_dir / "daily"
        if daily_dir.exists():
            shutil.rmtree(daily_dir)
            daily_dir.mkdir(parents=True, exist_ok=True)

        if not keep_progress:
            progress_file = self.temp_dir / "progress.json"
            if progress_file.exists():
                progress_file.unlink()

    def collector_data(
        self,
        prefer_api: bool = False,
        detect_new_stocks: bool = True,
        parallel_dates: bool = True,
    ):
        """
        主入口：批量收集数据。

        Args:
            prefer_api: 如果为 True，优先使用 TuShare API 获取最新日历（增量更新时使用）
            detect_new_stocks: 是否检测新上市股票
            parallel_dates: 是否并行获取日期数据

        流程:
        1. 获取交易日历
        2. 获取股票最后日期
        3. 检测新股票（如启用）
        4. 确定需要更新的日期
        5. 加载进度（断点续传）
        6. 日期循环获取数据（支持并行）
        7. 分割并合并数据
        8. 清理临时文件
        """
        logger.info("Starting TushareBatchCollector...")

        # 1. 获取交易日历
        trading_calendar = self.get_trading_calendar(prefer_api=prefer_api)
        logger.info(f"Loaded {len(trading_calendar)} trading dates")

        # 2. 获取股票最后日期
        instrument_last_dates = self.get_instrument_last_dates()

        # 3. 检测新股票（如启用）
        new_stocks = []
        if detect_new_stocks and instrument_last_dates:
            new_stocks = self.detect_new_stocks()
            if new_stocks:
                self.fetch_new_stock_data(new_stocks)

        # 4. 确定需要更新的日期
        dates_to_update = self.get_dates_to_update(instrument_last_dates, trading_calendar)

        if not dates_to_update:
            logger.info("No dates to update")
            return

        # 5. 加载进度（断点续传）
        processed_dates = self.load_progress()
        dates_to_fetch = [
            d for d in dates_to_update
            if d.strftime("%Y-%m-%d") not in processed_dates
        ]

        if not dates_to_fetch:
            logger.info("All dates already processed")
        else:
            logger.info(f"Fetching data for {len(dates_to_fetch)} dates...")
            if parallel_dates and len(dates_to_fetch) > 5:
                processed_dates = self.fetch_dates_parallel(
                    dates_to_fetch,
                    processed_dates,
                    max_workers=self.max_workers,
                )
            else:
                processed_dates = self._fetch_dates_sequential(dates_to_fetch, processed_dates)
            self.save_progress(processed_dates)

            missing_dates = sorted(
                d.strftime("%Y-%m-%d") for d in dates_to_fetch if d.strftime("%Y-%m-%d") not in processed_dates
            )
            if missing_dates:
                logger.warning(
                    f"Skipped {len(missing_dates)} trading dates with no saved data: "
                    f"{missing_dates[:10]}{'...' if len(missing_dates) > 10 else ''}"
                )

        # 7. 分割并合并数据
        logger.info("Splitting and merging data by symbol...")
        self.split_and_merge()

        # 8. 清理临时文件
        self.cleanup_temp_files(keep_progress=False)

        logger.info("TushareBatchCollector finished successfully!")

    def fetch_with_retry(self, trade_date: pd.Timestamp, max_retries: int = 3) -> pd.DataFrame:
        """带重试机制的日期数据获取"""
        return _fetch_tushare_date_data_with_retry(self.token, self.timeout, trade_date, max_retries=max_retries)

    def fetch_new_stock_data(
        self,
        new_stock_codes: List[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> None:
        """获取新上市股票的历史数据。"""
        if not new_stock_codes:
            return

        pro = ts.pro_api(self.token, timeout=self.timeout)

        try:
            listing_dates = {}
            for i in range(0, len(new_stock_codes), 100):
                basic = pro.stock_basic(
                    ts_code=",".join(new_stock_codes[i:i + 100]),
                    fields="ts_code,list_date"
                )
                if basic is None or basic.empty:
                    continue
                listing_dates.update(
                    {
                        row["ts_code"]: pd.Timestamp(row["list_date"])
                        for _, row in basic.iterrows()
                        if row["list_date"]
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to get stock listing dates: {e}")
            listing_dates = {}

        logger.info(f"Fetching historical data for {len(new_stock_codes)} new stocks...")

        for i, ts_code in enumerate(new_stock_codes):
            stock_start = listing_dates.get(ts_code, "20000101")
            if start:
                stock_start = max(pd.Timestamp(start), stock_start)

            if i > 0 and i % 50 == 0:
                time.sleep(60 / self.SAFE_CALLS_PER_MINUTE)

            try:
                start_dt = max(pd.Timestamp(stock_start), self.start_datetime)
                end_dt = pd.Timestamp(end) if end else self.end_datetime
                if start_dt >= end_dt:
                    continue

                symbol = ts_code_to_qlib_symbol(ts_code)
                symbol_fname = code_to_fname(symbol)
                target_path = self.save_dir / f"{symbol_fname}.csv"

                daily = pro.daily(
                    ts_code=ts_code,
                    start_date=start_dt.strftime("%Y%m%d"),
                    end_date=end_dt.strftime("%Y%m%d"),
                )
                if daily is None or daily.empty:
                    continue

                adj = pro.adj_factor(
                    ts_code=ts_code,
                    start_date=start_dt.strftime("%Y%m%d"),
                    end_date=end_dt.strftime("%Y%m%d"),
                )
                if adj is not None and not adj.empty:
                    merged = pd.merge(daily, adj, on=["ts_code", "trade_date"], how="left")
                else:
                    merged = daily.copy()
                    merged["adj_factor"] = 1.0

                merged["date"] = pd.to_datetime(merged["trade_date"])
                merged["symbol"] = symbol
                cols = ["ts_code", "date", "open", "high", "low", "close", "vol", "amount", "adj_factor", "symbol"]
                merged = merged[[c for c in cols if c in merged.columns]]

                if target_path.exists():
                    existing = pd.read_csv(target_path, parse_dates=["date"])
                    merged = pd.concat([existing, merged], ignore_index=True)
                    merged = merged.loc[:, ~merged.columns.duplicated()]
                    merged = merged.drop_duplicates(subset=["date"], keep="last")
                    merged = merged.sort_values("date")

                merged.to_csv(target_path, index=False)

                if (i + 1) % 20 == 0:
                    logger.info(f"Progress: {i + 1}/{len(new_stock_codes)} new stocks processed")
            except Exception as e:
                logger.warning(f"Failed to fetch data for {ts_code}: {e}")

        logger.info(f"Completed fetching data for {len(new_stock_codes)} new stocks")

    def fetch_dates_parallel(
        self,
        dates_to_fetch: List[pd.Timestamp],
        processed_dates: Set[str],
        max_workers: int = 4,
    ) -> Set[str]:
        """并行获取多个日期的数据。"""
        if max_workers <= 1 or len(dates_to_fetch) <= 1:
            return self._fetch_dates_sequential(dates_to_fetch, processed_dates)

        logger.info(f"Using parallel fetch with {max_workers} workers for {len(dates_to_fetch)} dates")

        chunk_size = max(1, len(dates_to_fetch) // max_workers)
        chunks = [
            dates_to_fetch[i:i + chunk_size]
            for i in range(0, len(dates_to_fetch), chunk_size)
        ]

        all_processed = processed_dates.copy()
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    _process_date_chunk,
                    (
                        chunk,
                        self.token,
                        self.timeout,
                        str(self.temp_dir),
                        self.SAFE_CALLS_PER_MINUTE,
                        self.API_CALLS_PER_DATE,
                    ),
                )
                for chunk in chunks
            ]
            for future in futures:
                try:
                    result = future.result(timeout=300)
                    all_processed.update(result)
                except Exception as e:
                    logger.error(f"Chunk processing failed: {e}")

        return all_processed

    def _fetch_dates_sequential(
        self,
        dates_to_fetch: List[pd.Timestamp],
        processed_dates: Set[str],
    ) -> Set[str]:
        """串行获取日期数据（原逻辑）。"""
        start_time = time.time()
        call_count = 0
        progress_interval = 10

        for i, trade_date in enumerate(dates_to_fetch):
            elapsed = time.time() - start_time
            expected_calls = call_count * self.API_CALLS_PER_DATE

            if expected_calls > 0 and elapsed > 0:
                actual_rate = expected_calls / (elapsed / 60)
                if actual_rate > self.SAFE_CALLS_PER_MINUTE:
                    sleep_time = 60 - (elapsed % 60) + 1
                    logger.info(f"Rate limit reached, sleeping {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    start_time = time.time()
                    call_count = 0

            try:
                df = self.fetch_with_retry(trade_date)
                call_count += self.API_CALLS_PER_DATE

                self.save_date_data(df, trade_date)
                processed_dates.add(trade_date.strftime("%Y-%m-%d"))

                if (i + 1) % progress_interval == 0:
                    self.save_progress(processed_dates)
                    logger.info(
                        f"Progress: {i + 1}/{len(dates_to_fetch)} dates, "
                        f"{len(df)} records for latest date"
                    )
            except Exception as e:
                logger.error(f"Failed to fetch data for {trade_date}: {e}")

            if self.delay_per_date > 0:
                time.sleep(self.delay_per_date)

        return processed_dates


class TushareNormalize1d(BaseNormalize):
    """Normalize raw TuShare CSVs to qlib day-level format."""

    def _get_calendar_list(self) -> Iterable[pd.Timestamp]:
        token = os.environ.get("TUSHARE_TOKEN")
        if ts is not None and token:
            try:
                pro = ts.pro_api(token)
                today = pd.Timestamp.now().strftime("%Y%m%d")
                cal_df = pro.trade_cal(exchange="", start_date="20000101", end_date=today, fields="cal_date,is_open")
                cal_list = cal_df.loc[cal_df["is_open"] == 1, "cal_date"].map(pd.Timestamp).tolist()
                if cal_list:
                    return cal_list
            except Exception as e:  # pragma: no cover - network dependent
                logger.warning(f"TuShare trade_cal failed, fallback to default calendar: {e}")
        return get_calendar_list("ALL")

    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        return normalize_tushare_eod(df)


class Run(BaseRun):
    collector_class_name = "TushareCollector"
    normalize_class_name = "TushareNormalize1d"
    default_base_dir = DEFAULT_BASE_DIR
    region = "CN"

    def __init__(
        self,
        source_dir=None,
        normalize_dir=None,
        max_workers: int = 1,
        interval: str = "1d",
        max_collector_count: int = 2,
        batch_size: int = 0,
        batch_pause: float = 0,
    ):
        self.max_collector_count = max_collector_count
        self.batch_size = batch_size
        self.batch_pause = batch_pause
        super().__init__(source_dir=source_dir, normalize_dir=normalize_dir, max_workers=max_workers, interval=interval)

    def download_data(self, **kwargs):
        """
        Download raw TuShare daily data into source_dir.
        Pass token=..., symbols=..., start=..., end=... when needed.
        """
        return super().download_data(**kwargs)

    def normalize_data(self, date_field_name: str = "date", symbol_field_name: str = "symbol", **kwargs):
        """Normalize raw CSVs into factor-adjusted CSVs under normalize_dir."""
        return super().normalize_data(date_field_name=date_field_name, symbol_field_name=symbol_field_name, **kwargs)

    def _sync_incremental_normalize_to_bin(
        self,
        qlib_data_1d_dir: str | Path,
        baseline_last_data_date: pd.Timestamp,
        target_end_date: pd.Timestamp,
        worker_count: int,
        instrument_last_dates: Optional[Dict[str, pd.Timestamp]] = None,
        freq: str = "day",
    ) -> Dict[str, object]:
        """
        Sync normalized CSV data into qlib bins.

        Append-only updates remain fast for normal symbols. If a corporate action
        caused retroactive factor changes, the affected symbol is rebuilt from the
        full normalized csv so price/factor/volume stay continuous.
        """
        qlib_data_1d_dir = Path(qlib_data_1d_dir).expanduser().resolve()
        normalize_dir = Path(self.normalize_dir)
        inc_dir = normalize_dir / "__inc_tmp__"
        instrument_last_dates = {
            str(symbol).upper(): pd.Timestamp(last_date)
            for symbol, last_date in (instrument_last_dates or {}).items()
        }
        default_last_date = pd.Timestamp("1900-01-01")

        updated_csv_files: List[Path] = []
        append_csv_files: List[Path] = []
        rebuild_reasons: Dict[str, str] = {}
        repair_result: Optional[Dict[str, object]] = None

        if inc_dir.exists():
            shutil.rmtree(inc_dir)
        inc_dir.mkdir(parents=True, exist_ok=True)

        try:
            for csv_file in normalize_dir.glob("*.csv"):
                try:
                    df = load_normalized_csv(csv_file)
                    if df.empty or "date" not in df.columns:
                        continue
                    symbol = fname_to_code(csv_file.stem).upper()
                    symbol_last_date = instrument_last_dates.get(symbol, default_last_date)
                    df_new = df[(df["date"] > symbol_last_date) & (df["date"] <= target_end_date)]
                    if df_new.empty:
                        continue
                    updated_csv_files.append(csv_file)
                except Exception as e:
                    logger.warning(f"Failed to scan normalized csv {csv_file}: {e}")

            if not updated_csv_files:
                logger.info("No incremental data found; skip dump.")
                return {
                    "updated_count": 0,
                    "append_count": 0,
                    "rebuild_reasons": {},
                    "repair_result": None,
                }

            rebuild_reasons = detect_retroactive_factor_rebuilds(updated_csv_files, qlib_data_1d_dir, freq=freq)
            if rebuild_reasons:
                logger.warning(
                    "Detected retroactive factor changes; full rebuild required for "
                    f"{len(rebuild_reasons)} symbols: "
                    f"{sorted(rebuild_reasons)[:10]}{'...' if len(rebuild_reasons) > 10 else ''}"
                )

            for csv_file in updated_csv_files:
                symbol = fname_to_code(csv_file.stem).upper()
                if symbol in rebuild_reasons:
                    continue

                try:
                    df = load_normalized_csv(csv_file)
                    if df.empty or "date" not in df.columns:
                        continue
                    symbol_last_date = instrument_last_dates.get(symbol, default_last_date)
                    df_new = df[(df["date"] > symbol_last_date) & (df["date"] <= target_end_date)].copy()
                    if df_new.empty:
                        continue
                    # Rescale to match existing bin's normalization constant
                    df_new = rescale_normalized_df_to_bin(
                        df_new, df, qlib_data_1d_dir, symbol, freq=freq
                    )
                    df_new["date"] = df_new["date"].dt.strftime("%Y-%m-%d")
                    df_new.to_csv(inc_dir / csv_file.name, index=False)
                    append_csv_files.append(csv_file)
                except Exception as e:
                    logger.warning(f"Failed to stage incremental csv {csv_file}: {e}")

            if append_csv_files:
                _dump = DumpDataUpdate(
                    data_path=inc_dir,
                    qlib_dir=qlib_data_1d_dir,
                    exclude_fields="symbol,date",
                    max_workers=worker_count,
                )
                _dump.dump()
            else:
                logger.info("All updated symbols require full rebuild; skip append-only dump.")

            repair_result = repair_feature_bins_from_normalize(
                normalize_dir=normalize_dir,
                qlib_dir=qlib_data_1d_dir,
                freq=freq,
                csv_files=updated_csv_files,
                force_symbols=set(rebuild_reasons),
            )
            return {
                "updated_count": len(updated_csv_files),
                "append_count": len(append_csv_files),
                "rebuild_reasons": rebuild_reasons,
                "repair_result": repair_result,
            }
        finally:
            shutil.rmtree(inc_dir, ignore_errors=True)

    def dump_to_bin(
        self,
        qlib_dir: str | Path = DEFAULT_QLIB_DIR,
        mode: str = "all",
        max_workers: Optional[int] = None,
        exclude_fields: str = "symbol,date",
    ):
        """Dump normalized CSVs to qlib bin format."""
        workers = max_workers if max_workers is not None else self.max_workers
        return dump_eod_to_qlib(
            data_path=self.normalize_dir,
            qlib_dir=qlib_dir,
            mode=mode,
            max_workers=workers,
            exclude_fields=exclude_fields,
        )

    def download_today_data(
        self,
        max_collector_count=2,
        delay=0.5,
        check_data_length=None,
        limit_nums=None,
    ):
        """Download today's data (closed interval start, open interval end)."""
        start = pd.Timestamp.now().date()
        end = (pd.Timestamp(start) + pd.Timedelta(days=1)).date()
        return self.download_data(
            max_collector_count=max_collector_count,
            delay=delay,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            check_data_length=check_data_length,
            limit_nums=limit_nums,
        )

    def update_data_to_bin(
        self,
        qlib_data_1d_dir: str,
        end_date: str = None,
        check_data_length: int = None,
        delay: float = 1,
        exists_skip: bool = False,
    ):
        """
        Incrementally update an existing qlib dir using new TuShare data.
        """
        if self.interval.lower() != "1d":
            logger.warning("Currently only 1d interval incremental update is supported.")

        from qlib.utils import exists_qlib_data

        qlib_data_1d_dir = str(Path(qlib_data_1d_dir).expanduser().resolve())
        if not exists_qlib_data(qlib_data_1d_dir):
            raise RuntimeError(
                f"qlib_data_1d_dir not found or incomplete: {qlib_data_1d_dir}; "
                "build baseline with TuShare first (download_data -> normalize_data -> dump_to_bin), "
                "then rerun update_data_to_bin."
            )

        calendar_df = pd.read_csv(Path(qlib_data_1d_dir).joinpath("calendars/day.txt"), header=None, names=["date"], dtype=str)
        calendar_df["date"] = pd.to_datetime(calendar_df["date"].astype(str), format="mixed")
        reconcile_result = reconcile_instruments_from_features(qlib_data_1d_dir)
        instrument_last_dates = reconcile_result.get("instrument_last_dates", {})
        latest_feature_date = reconcile_result.get("latest_feature_date")
        baseline_last_data_date = latest_feature_date if latest_feature_date is not None else pd.Timestamp(str(calendar_df.iloc[-1, 0]))

        if end_date is None:
            end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
        target_end_date = pd.Timestamp(end_date)

        # Filter to only stocks that need updating (incremental mode)
        target_date = target_end_date
        inst_file = Path(qlib_data_1d_dir) / "instruments" / "all.txt"
        outdated_symbols = None
        trading_date_ts = baseline_last_data_date
        
        if inst_file.exists():
            outdated = []
            with open(inst_file) as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) >= 3:
                        symbol, _start_d, end_d = parts[0], parts[1], parts[2]
                        try:
                            end_ts = pd.Timestamp(end_d)
                            if end_ts < target_date:
                                outdated.append(symbol)
                        except Exception:
                            pass
            
            if outdated:
                outdated_last_dates = [
                    instrument_last_dates.get(symbol.upper(), baseline_last_data_date) for symbol in outdated
                ]
                if outdated_last_dates:
                    trading_date_ts = min(outdated_last_dates)
                logger.info(
                    f"Incremental update: {len(outdated)} stocks need updating "
                    f"(actual last date: {baseline_last_data_date.strftime('%Y-%m-%d')}, target: {end_date})"
                )
                outdated_symbols = outdated

        future_cal = calendar_df[calendar_df["date"] > trading_date_ts]
        if not future_cal.empty:
            trading_date_ts = future_cal.iloc[0]["date"]
        trading_date = trading_date_ts.strftime("%Y-%m-%d")

        self.download_data(
            delay=delay,
            start=trading_date,
            end=end_date,
            check_data_length=check_data_length,
            max_collector_count=self.max_collector_count,
            symbols=outdated_symbols,
        )

        self.normalize_data()
        sync_result = self._sync_incremental_normalize_to_bin(
            qlib_data_1d_dir=qlib_data_1d_dir,
            baseline_last_data_date=baseline_last_data_date,
            target_end_date=target_end_date,
            worker_count=self.max_workers,
            instrument_last_dates=instrument_last_dates,
        )

        repair_result = sync_result.get("repair_result") if sync_result else None
        reconcile_result = repair_result.get("reconcile_result") if repair_result else None
        if reconcile_result is None:
            reconcile_result = reconcile_instruments_from_features(qlib_data_1d_dir)
        logger.info(
            "Incremental update reconciled instruments from current feature bins: "
            f"latest_feature_date={reconcile_result.get('latest_feature_date')}"
        )

        # 延伸指数成分 end_date 到最新交易日
        extend_index_instruments(qlib_data_1d_dir)

    def pipeline(
        self,
        qlib_dir: str | Path = DEFAULT_QLIB_DIR,
        token: Optional[str] = None,
        symbols: Optional[Iterable[str]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ):
        """
        One-shot pipeline: download -> normalize -> dump.
        """
        self.download_data(token=token, symbols=symbols, start=start, end=end)
        self.normalize_data()
        qlib_dir = Path(qlib_dir).expanduser().resolve() if qlib_dir else Path(DEFAULT_QLIB_DIR).expanduser()
        result = self.dump_to_bin(qlib_dir=qlib_dir)
        extend_index_instruments(qlib_dir)
        return result

    def sync_calendar(
        self,
        qlib_dir: str | Path = DEFAULT_QLIB_DIR,
        end: Optional[str] = None,
    ):
        """同步交易日历到 qlib 目录。"""
        collector = TushareBatchCollector(
            save_dir=self.source_dir,
            qlib_dir=qlib_dir,
        )
        collector.sync_calendar(end=end)

    def download_data_batch(
        self,
        qlib_dir: str | Path = DEFAULT_QLIB_DIR,
        start: Optional[str] = None,
        end: Optional[str] = None,
        token: Optional[str] = None,
        delay_per_date: float = 0.1,
        max_workers: int = 8,
        prefer_api: bool = False,
        detect_new_stocks: bool = True,
        parallel_dates: bool = True,
    ):
        """
        使用批量模式下载数据（按日期批量获取，效率更高）。

        相比 download_data()，效率提升约 4 倍：
        - 按股票: N只股票 x 2次API = 2N 次
        - 按日期: D个交易日 x 2次API = 2D 次

        Args:
            qlib_dir: qlib 数据目录，用于读取 instruments/all.txt 和 calendars/day.txt
            start: 开始日期 (YYYY-MM-DD)
            end: 结束日期 (YYYY-MM-DD)
            token: TuShare API token
            delay_per_date: 每个日期间隔（秒），控制 API 调用频率
            max_workers: 分割数据时的并行工作数
            prefer_api: 如果为 True，优先使用 TuShare API 获取最新日历
            detect_new_stocks: 是否检测并获取新上市股票的数据
            parallel_dates: 是否并行获取日期数据
        """
        collector = TushareBatchCollector(
            save_dir=self.source_dir,
            qlib_dir=qlib_dir,
            start=start,
            end=end,
            token=token,
            delay_per_date=delay_per_date,
            max_workers=max_workers,
        )
        collector.collector_data(
            prefer_api=prefer_api,
            detect_new_stocks=detect_new_stocks,
            parallel_dates=parallel_dates,
        )

    def update_data_to_bin_batch(
        self,
        qlib_data_1d_dir: str,
        end_date: str = None,
        start_date: str = None,
        delay_per_date: float = 0.1,
        detect_new_stocks: bool = True,
        max_workers: Optional[int] = None,
    ):
        """
        增量更新（批量模式）。

        1. 读取 calendars/day.txt 确定最后日期
        2. 只更新最后日期之后的数据
        3. 自动检测并补充新上市股票数据
        4. 快速合并到现有数据
        5. 导出为 qlib 二进制格式

        Args:
            qlib_data_1d_dir: qlib 数据目录
            end_date: 结束日期，默认为当前日期
            start_date: 起始日期，默认为自动计算（从最早缺失日期开始）
            delay_per_date: 每个日期间隔（秒）
            detect_new_stocks: 是否检测并获取新上市股票的数据
        """
        from qlib.utils import exists_qlib_data

        qlib_data_1d_dir = str(Path(qlib_data_1d_dir).expanduser().resolve())
        if not exists_qlib_data(qlib_data_1d_dir):
            raise RuntimeError(
                f"qlib_data_1d_dir not found or incomplete: {qlib_data_1d_dir}; "
                "build baseline with TuShare first "
                "(download_data_batch -> normalize_data -> dump_to_bin), "
                "then rerun update_data_to_bin_batch."
            )

        # 读取日历，并先用真实 features 覆盖范围修正 instruments/all.txt
        calendar_df = pd.read_csv(
            Path(qlib_data_1d_dir) / "calendars" / "day.txt",
            header=None,
            names=["date"],
            dtype=str,
        )
        calendar_df["date"] = pd.to_datetime(calendar_df["date"].astype(str), format="mixed")
        last_cal_date = pd.Timestamp(str(calendar_df["date"].iloc[-1]))

        reconcile_result = reconcile_instruments_from_features(qlib_data_1d_dir)
        instrument_last_dates = reconcile_result.get("instrument_last_dates", {})
        latest_feature_date = reconcile_result.get("latest_feature_date")
        baseline_last_data_date = latest_feature_date if latest_feature_date is not None else last_cal_date

        if end_date is None:
            end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
        target_end_date = pd.Timestamp(end_date)

        # 如果用户显式指定了 start_date，直接使用它覆盖默认计算逻辑
        if start_date is not None and str(start_date).strip() != "":
            override_start = pd.Timestamp(start_date)
            logger.info(
                f"Override start_date specified: fetching from {override_start.strftime('%Y-%m-%d')} "
                f"to {end_date} (ignoring instrument_last_dates)"
            )
            future_cal = calendar_df[calendar_df["date"] >= override_start]
            if not future_cal.empty:
                start_date = str(future_cal.iloc[0]["date"].strftime("%Y-%m-%d"))
            else:
                start_date = override_start.strftime("%Y-%m-%d")
        else:
            future_cal = calendar_df[calendar_df["date"] > baseline_last_data_date]
            if not future_cal.empty:
                start_date = str(future_cal.iloc[0]["date"].strftime("%Y-%m-%d"))
            else:
                start_date = baseline_last_data_date.strftime("%Y-%m-%d")

        worker_count = max_workers if max_workers is not None else self.max_workers
        logger.info(
            "Starting batch incremental update from "
            f"{start_date} to {end_date} "
            f"(actual feature last date: {baseline_last_data_date.strftime('%Y-%m-%d')})..."
        )

        # 使用批量收集器下载数据（从日历最后日期开始，优先使用 API 获取最新日历）
        self.download_data_batch(
            qlib_dir=qlib_data_1d_dir,
            start=start_date,
            end=end_date,
            delay_per_date=delay_per_date,
            max_workers=worker_count,
            prefer_api=True,  # 增量更新时优先使用 API 获取最新日历
            detect_new_stocks=detect_new_stocks,
            parallel_dates=True,
        )

        # 标准化数据
        self.normalize_data()
        sync_result = self._sync_incremental_normalize_to_bin(
            qlib_data_1d_dir=qlib_data_1d_dir,
            baseline_last_data_date=baseline_last_data_date,
            target_end_date=target_end_date,
            worker_count=worker_count,
            instrument_last_dates=instrument_last_dates,
        )

        repair_result = sync_result.get("repair_result") if sync_result else None
        reconcile_result = repair_result.get("reconcile_result") if repair_result else None
        if reconcile_result is None:
            reconcile_result = reconcile_instruments_from_features(qlib_data_1d_dir)
        logger.info(
            "Batch incremental update reconciled instruments from current feature bins: "
            f"latest_feature_date={reconcile_result.get('latest_feature_date')}"
        )

        # 延伸指数成分 end_date 到最新交易日
        extend_index_instruments(qlib_data_1d_dir)

        logger.info("Batch incremental update completed!")

    def pipeline_batch(
        self,
        qlib_dir: str | Path = DEFAULT_QLIB_DIR,
        start: Optional[str] = None,
        end: Optional[str] = None,
        token: Optional[str] = None,
        delay_per_date: float = 0.1,
        max_workers: Optional[int] = None,
    ):
        """
        一键批量流程：批量下载 -> 标准化 -> 导出二进制。

        效率比 pipeline() 高约 4 倍。
        """
        worker_count = max_workers if max_workers is not None else 8
        self.download_data_batch(
            qlib_dir=qlib_dir,
            start=start,
            end=end,
            token=token,
            delay_per_date=delay_per_date,
            max_workers=worker_count,
        )
        self.normalize_data()
        qlib_dir = Path(qlib_dir).expanduser().resolve() if qlib_dir else Path(DEFAULT_QLIB_DIR).expanduser()
        result = self.dump_to_bin(qlib_dir=qlib_dir, max_workers=worker_count)
        extend_index_instruments(qlib_dir)
        return result


if __name__ == "__main__":  # pragma: no cover - CLI entry
    import fire

    fire.Fire(Run)
