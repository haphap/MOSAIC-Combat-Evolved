from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set
import json
import time

import multiprocessing
from concurrent.futures import ProcessPoolExecutor, TimeoutError

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
DEFAULT_ETF_ANALYSIS_START_DATE = "2005-02-23"
FEATURE_SPAN_FIELDS = ("close", "open", "high", "low", "factor", "volume")


def _get_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required; set it as an environment variable.")
    return token.strip()


def _default_etf_analysis_start_date() -> str:
    configured = os.environ.get("MOSAIC_ETF_ANALYSIS_START_DATE", DEFAULT_ETF_ANALYSIS_START_DATE)
    return configured.strip() or DEFAULT_ETF_ANALYSIS_START_DATE


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


def qlib_symbol_to_ts_code(symbol: str) -> str:
    """Convert qlib symbol (e.g., sh510300) to TuShare ts_code (510300.SH)."""
    if not symbol or "." in symbol:
        return symbol
    normalized = symbol.strip()
    prefix = normalized[:2].upper()
    code = normalized[2:]
    if prefix in {"SZ", "SH", "BJ"} and code.isdigit():
        return f"{code}.{prefix}"
    return symbol


def _estimate_business_rows(start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> int:
    if start_dt > end_dt:
        return 0
    return max(1, len(pd.bdate_range(start_dt.normalize(), end_dt.normalize())))


def _normalize_factor(series: pd.Series) -> pd.Series:
    """Normalize adj_factor so the first valid value per symbol becomes 1.0."""
    if series.empty:
        return series
    first_valid = series.dropna().iloc[0] if series.dropna().size else np.nan
    if pd.isna(first_valid) or float(first_valid) == 0:
        return pd.Series([1.0] * len(series), index=series.index)
    return series / float(first_valid)


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
    Output columns: date, open, high, low, close, volume, amount, factor, symbol
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

    # CRITICAL: compute raw_close BEFORE any factor transformations.
    # raw_close is the original tushare close before factor multiplication.
    # adjclose = raw_close * adj_factor — the forward-adjusted close in absolute scale.
    raw_close = data["close"].astype(float).copy()

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

    # adjclose: raw forward-adjusted close in absolute scale.
    # = raw_close * adj_factor (not divided by factor)
    data["adjclose"] = (raw_close * data["adj_factor"].astype(float)).astype(float)
    cols.append("adjclose")

    normalized = data[cols].copy()
    normalized["date"] = normalized["date"].dt.strftime("%Y-%m-%d")
    return normalized.reset_index(drop=True)


# 模块级缓存：货币基金代码集合
_MONEY_FUND_CODES: Optional[Set[str]] = None


def _get_money_fund_codes(token: str, timeout: int) -> Set[str]:
    """获取所有货币基金代码，只调一次 API（缓存在模块变量）。"""
    global _MONEY_FUND_CODES
    if _MONEY_FUND_CODES is not None:
        return _MONEY_FUND_CODES
    try:
        pro = ts.pro_api(token, timeout=timeout)
        all_dfs = []
        for status in ["L", "D", "N", "I", "O"]:
            df = pro.fund_basic(status=status, fields="ts_code,fund_type")
            if df is not None and not df.empty:
                all_dfs.append(df)
        combined = pd.concat(all_dfs).drop_duplicates("ts_code")
        money = combined[combined["fund_type"].str.contains("货币", na=False)]
        _MONEY_FUND_CODES = set(money["ts_code"].dropna().tolist())
    except Exception:
        _MONEY_FUND_CODES = set()
    return _MONEY_FUND_CODES


def _fetch_tushare_date_data(token: str, timeout: int, trade_date: pd.Timestamp) -> pd.DataFrame:
    """Fetch all ETF EOD data for one trading day. Excludes .OF (场外基金) and 货币基金."""
    date_str = pd.Timestamp(trade_date).strftime("%Y%m%d")
    pro = ts.pro_api(token, timeout=timeout)

    daily = pro.fund_daily(trade_date=date_str)
    if daily is None or daily.empty:
        return pd.DataFrame()

    # 过滤场外基金(.OF) — 只保留交易所上市ETF
    daily = daily[~daily["ts_code"].str.endswith(".OF")]

    # 过滤货币基金 — 使用缓存的货币基金代码集
    money_codes = _get_money_fund_codes(token, timeout)
    if money_codes:
        daily = daily[~daily["ts_code"].isin(money_codes)]

    if daily.empty:
        return pd.DataFrame()

    adj = pro.fund_adj(trade_date=date_str)
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
    """Fetch one trading date and retry transient TuShare/network failures."""
    for attempt in range(max_retries):
        try:
            return _fetch_tushare_date_data(token, timeout, trade_date)
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Fetch {pd.Timestamp(trade_date).date()} failed on attempt "
                    f"{attempt + 1}/{max_retries}: {e}"
                )
                time.sleep(5 * (attempt + 1))
            else:
                raise
    return pd.DataFrame()


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
            if not df.empty:
                date_str = pd.Timestamp(trade_date).strftime("%Y%m%d")
                df.to_csv(temp_daily_dir / f"{date_str}.csv", index=False)
            local_processed.add(pd.Timestamp(trade_date).strftime("%Y-%m-%d"))
        except Exception as e:
            logger.warning(f"Parallel fetch failed for {trade_date}: {e}")

    return local_processed


def _terminate_process_pool(executor: ProcessPoolExecutor) -> None:
    processes = getattr(executor, "_processes", None) or {}
    for process in list(processes.values()):
        try:
            if process.is_alive():
                process.terminate()
        except Exception:
            continue
    for process in list(processes.values()):
        try:
            process.join(timeout=5)
        except Exception:
            continue


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

    We prefer close.day.bin and fall back to other fields if needed. The first
    float32 in each qlib bin is the start calendar index; remaining values align
    with subsequent trading days, with NaN used for missing dates.
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

    This makes instruments metadata match the real qlib feature data, which is
    critical for correct incremental-update start date selection.
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


def rebuild_feature_bin_from_csv(
    csv_file: str | Path,
    qlib_dir: str | Path,
    calendar: List[pd.Timestamp],
    freq: str = "day",
) -> Optional[str]:
    """
    Rebuild one feature directory from a normalized csv using the current qlib calendar.
    """
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
) -> Dict[str, object]:
    """
    Repair qlib feature bins whose actual span disagrees with normalized csv span.

    This is a self-healing step for historical runs that dumped bins while the
    qlib calendar file was corrupted.
    """
    normalize_dir = Path(normalize_dir).expanduser().resolve()
    qlib_dir = Path(qlib_dir).expanduser().resolve()
    calendar = load_qlib_calendar(qlib_dir, freq=freq)

    rebuilt: List[str] = []
    checked = 0
    for csv_file in sorted(normalize_dir.glob("*.csv")):
        if csv_file.name == "__inc_tmp__":
            continue
        csv_span = get_csv_span(csv_file)
        if csv_span is None:
            continue
        checked += 1

        symbol = fname_to_code(csv_file.stem).upper()
        feature_span = get_feature_span(qlib_dir / "features" / symbol.lower(), calendar, freq=freq)
        if feature_span == csv_span:
            continue

        rebuilt_symbol = rebuild_feature_bin_from_csv(csv_file, qlib_dir, calendar, freq=freq)
        if rebuilt_symbol is not None:
            rebuilt.append(rebuilt_symbol)

    reconcile_result = reconcile_instruments_from_features(qlib_dir, freq=freq)
    logger.info(
        f"Repair feature bins from normalize: checked={checked}, rebuilt={len(rebuilt)}, "
        f"latest_feature_date={reconcile_result.get('latest_feature_date')}"
    )
    return {
        "checked_count": checked,
        "rebuilt_symbols": rebuilt,
        "rebuilt_count": len(rebuilt),
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
        try:
            df = self.get_data(symbol, self.interval, self.start_datetime, self.end_datetime)
        except Exception as exc:
            logger.warning(f"collector failed for {symbol}: {type(exc).__name__}: {exc}")
            return "ERROR"
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
        basic = pro.etf_basic(exchange="", list_status="L,D,P", fields="ts_code")
        codes = basic["ts_code"].dropna().unique().tolist()
        # 过滤掉场外基金(.OF)
        codes = [c for c in codes if not c.endswith(".OF")]
        return codes

    def normalize_symbol(self, symbol: str):
        return ts_code_to_qlib_symbol(qlib_symbol_to_ts_code(symbol))

    def get_data(
        self, symbol: str, interval: str, start_datetime: pd.Timestamp, end_datetime: pd.Timestamp
    ) -> pd.DataFrame:
        if interval != self.INTERVAL_1d:
            raise ValueError("TushareCollector currently supports only 1d interval.")

        # determine incremental start based on existing csv to support resume
        start_dt = pd.Timestamp(start_datetime)
        end_dt = pd.Timestamp(end_datetime)

        ts_code = qlib_symbol_to_ts_code(symbol)
        symbol_fname = code_to_fname(self.normalize_symbol(ts_code))
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
        daily = pro.fund_daily(ts_code=ts_code, start_date=start_str, end_date=end_str)
        adj = pro.fund_adj(ts_code=ts_code, start_date=start_str, end_date=end_str)

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
        # 列去重（防御性，避免 amount/amount.1 重复列）
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
    - 新ETF自动检测（增量更新时发现新上市ETF并补充数据）
    - 并行日期获取（可选多进程加速）
    """

    # API 限制常量
    API_CALLS_PER_MINUTE = 500
    API_ROWS_PER_CALL = 6000
    API_CALLS_PER_DATE = 2  # daily + adj_factor
    API_CODES_PER_HISTORY_CALL = 100
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
        self.start_datetime = pd.Timestamp(start) if start else pd.Timestamp(_default_etf_analysis_start_date())
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

        Args:
            end: 结束日期，默认为当前日期

        Returns:
            合并后的交易日列表
        """
        end_dt = pd.Timestamp(end) if end else pd.Timestamp.now()

        # 读取现有日历
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

        # 从 TuShare 获取日历
        pro = ts.pro_api(self.token, timeout=self.timeout)
        start_str = "20000101"
        end_str = end_dt.strftime("%Y%m%d")

        cal_df = pro.trade_cal(
            exchange="",
            start_date=start_str,
            end_date=end_str,
            fields="cal_date,is_open"
        )

        if cal_df is None or cal_df.empty:
            logger.warning("No calendar data from TuShare")
            return []

        # 提取交易日
        trading_dates = {
            normalized
            for normalized in (
                _normalize_calendar_value(d) for d in cal_df.loc[cal_df["is_open"] == 1, "cal_date"].tolist()
            )
            if normalized is not None
        }

        # 合并
        all_dates = existing_dates | trading_dates
        all_dates_sorted = sorted(all_dates)

        # 保存
        cal_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cal_file, "w") as f:
            for d in all_dates_sorted:
                f.write(f"{d}\n")

        new_count = len(all_dates) - len(existing_dates)
        logger.info(
            f"Calendar synced: {len(all_dates)} total dates, "
            f"{new_count} new dates added"
        )

        return [pd.Timestamp(str(d)) for d in all_dates_sorted]

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

    def detect_new_etfs(self) -> List[str]:
        """
        检测新上市的ETF（存在于 TuShare 但不存在于 instruments/all.txt）。

        Returns:
            List[str]: 新ETF的 ts_code 列表
        """
        inst_file = self.qlib_dir / "instruments" / "all.txt"
        if not inst_file.exists():
            return []

        # 读取现有 ETF 列表
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

        # 从 TuShare 获取当前 ETF 列表（仅上市状态的）
        pro = ts.pro_api(self.token, timeout=self.timeout)
        basic = pro.etf_basic(fields="ts_code,status")
        if basic is None or basic.empty:
            return []

        # 过滤：只保留上市状态的ETF，剔除退市(status=D)和已下市的
        if "status" in basic.columns:
            basic = basic[basic["status"] == "L"]

        current_codes = basic["ts_code"].dropna().unique().tolist()
        # 过滤掉场外基金(.OF)，只保留交易所交易的ETF
        exchange_codes = [c for c in current_codes if not c.endswith(".OF")]
        current_symbols = {ts_code_to_qlib_symbol(code).upper(): code for code in exchange_codes}
        new_codes = [code for symbol, code in current_symbols.items() if symbol not in existing]

        if new_codes:
            logger.info(f"Detected {len(new_codes)} new ETFs: {sorted(new_codes)[:10]}{'...' if len(new_codes) > 10 else ''}")

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
        processed: Set[str] = set()
        progress_file = self.temp_dir / "progress.json"
        if progress_file.exists():
            try:
                with open(progress_file, "r") as f:
                    data = json.load(f)
                processed.update(data.get("processed_dates", []))
            except Exception as e:
                logger.warning(f"Failed to load progress: {e}")

        daily_dir = self.temp_dir / "daily"
        if daily_dir.exists():
            for csv_file in daily_dir.glob("*.csv"):
                try:
                    processed.add(pd.Timestamp(csv_file.stem).strftime("%Y-%m-%d"))
                except Exception:
                    continue

        logger.info(f"Loaded progress: {len(processed)} dates already processed")
        return processed

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
        1. pro.fund_daily(trade_date='20240101')
        2. pro.fund_adj(trade_date='20240101')
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
        过滤掉 .OF (场外基金) 和货币基金。
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

        # 过滤掉 .OF (场外基金) 和货币基金
        money_codes = _get_money_fund_codes(self.token, self.timeout)
        invalid_patterns = {".OF", ".of"}
        if money_codes:
            # 把 ts_code 转回 symbol 格式做过滤
            for ts_code in money_codes:
                parts = ts_code.split(".")
                invalid_patterns.add(parts[0].zfill(6) + "." + parts[1].lower())

        # symbol 格式如 sz159001, sh511990
        combined = combined[~combined["symbol"].str.lower().str.endswith(".of")]
        if invalid_patterns:
            mask = ~combined["symbol"].isin(invalid_patterns)
            combined = combined[mask]

        if combined.empty:
            logger.info("No valid data after filtering .OF/money funds")
            return

        # 按 symbol 分组
        logger.info(f"Grouping {len(combined)} records by symbol (filtered)...")
        grouped = combined.groupby("symbol")

        # 对每个 symbol 合并并保存
        def process_symbol(args):
            symbol, df = args
            # 最终安全过滤：跳过 .OF 和已知货币基金
            if symbol.lower().endswith(".of"):
                return None
            if money_codes:
                ts_code = symbol[2:].zfill(6) + "." + symbol[:2].upper()
                if ts_code in money_codes:
                    return None

            symbol_fname = code_to_fname(symbol)
            target_path = self.save_dir / f"{symbol_fname}.csv"

            # 读取现有数据并过滤 .OF/货币基金
            if target_path.exists():
                try:
                    existing = pd.read_csv(target_path, parse_dates=["date"])
                    existing = existing.loc[:, ~existing.columns.duplicated()]
                    # 过滤掉 .OF 和货币基金
                    existing = existing[~existing["symbol"].str.lower().str.endswith(".of")]
                    if money_codes:
                        existing_ts = existing["symbol"].apply(
                            lambda s: s[2:].zfill(6) + "." + s[:2].upper()
                        )
                        existing = existing[~existing_ts.isin(money_codes)]
                    df = pd.concat([existing, df], ignore_index=True)
                except Exception:
                    pass

            # 行去重并排序
            df = df.loc[:, ~df.columns.duplicated()]  # 列去重（防御性）
            df = df.drop_duplicates(subset=["date"], keep="last")
            df = df.sort_values("date")

            # 保存
            df.to_csv(target_path, index=False)
            return symbol

        # 使用并行处理
        logger.info(f"Processing {len(grouped)} symbols...")
        results = [r for r in map(process_symbol, [(name, group) for name, group in grouped]) if r is not None]
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

    def collector_data(self, prefer_api: bool = False, detect_new_etfs: bool = True, parallel_dates: bool = True):
        """
        主入口：批量收集数据。

        Args:
            prefer_api: 如果为 True，优先使用 TuShare API 获取最新日历（增量更新时使用）
            detect_new_etfs: 是否检测新上市的ETF
            parallel_dates: 是否并行获取日期数据

        流程:
        1. 获取交易日历
        2. 获取股票最后日期
        3. 检测新ETF（如启用）
        4. 确定需要更新的日期
        5. 加载进度（断点续传）
        6. 日期循环获取数据（支持并行）
        7. 分割并合并数据
        8. 清理临时文件
        """
        logger.info("Starting TushareBatchCollector...")

        # 1. 获取交易日历
        # 全量构建时优先从 API 获取，避免读取空的本地日历文件
        trading_calendar = self.get_trading_calendar(prefer_api=True)
        logger.info(f"Loaded {len(trading_calendar)} trading dates")

        # 2. 获取股票最后日期
        instrument_last_dates = self.get_instrument_last_dates()

        # 3. 检测新ETF（如启用）
        # 注意：首次全量构建时 instrument_last_dates 为空，仍需检测并下载所有ETF
        new_etfs = []
        if detect_new_etfs:
            if instrument_last_dates:
                new_etfs = self.detect_new_etfs()
            else:
                # 首次全量构建：获取所有交易所ETF（过滤场外基金）
                logger.info("No existing instruments detected, fetching all ETFs from TuShare...")
                pro = ts.pro_api(self.token, timeout=self.timeout)
                basic = pro.etf_basic(fields="ts_code")
                if basic is not None and not basic.empty:
                    all_codes = basic["ts_code"].dropna().unique().tolist()
                    # 过滤掉场外基金(.OF)，只保留交易所交易的ETF
                    new_etfs = [c for c in all_codes if not c.endswith(".OF")]
                    logger.info(f"Found {len(new_etfs)} exchange-traded ETFs from TuShare (filtered {len(all_codes) - len(new_etfs)} .OF funds)")
            if new_etfs:
                # 获取新ETF的历史数据
                self.fetch_new_etf_data(new_etfs)

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

            # 6. 获取数据（支持并行）
            if parallel_dates and len(dates_to_fetch) > 5:
                processed_dates = self.fetch_dates_parallel(
                    dates_to_fetch,
                    processed_dates,
                    max_workers=self.max_workers,
                )
            else:
                processed_dates = self._fetch_dates_sequential(dates_to_fetch, processed_dates)

            # 最终保存进度
            self.save_progress(processed_dates)

        # 7. 分割并合并数据
        logger.info("Splitting and merging data by symbol...")
        self.split_and_merge()

        # 8. 清理临时文件
        self.cleanup_temp_files(keep_progress=False)

        logger.info("TushareBatchCollector finished successfully!")

    def fetch_with_retry(self, trade_date: pd.Timestamp, max_retries: int = 3) -> pd.DataFrame:
        """带重试机制的日期数据获取"""
        for attempt in range(max_retries):
            try:
                return self.fetch_date_data(trade_date)
            except Exception as e:
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed for {trade_date}: {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))
                else:
                    logger.error(f"All retries exhausted for {trade_date}")
                    raise
        return pd.DataFrame()

    def fetch_new_etf_data(
        self,
        new_etf_codes: List[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> None:
        """
        获取新ETF的历史数据。

        Args:
            new_etf_codes: 新ETF的 ts_code 列表
            start: 开始日期，默认为ETF上市日期（通过 etf_basic 获取）
            end: 结束日期，默认为当前日期
        """
        if not new_etf_codes:
            return

        pro = ts.pro_api(self.token, timeout=self.timeout)

        # 获取ETF上市日期信息
        try:
            listing_dates = {}
            for i in range(0, len(new_etf_codes), 100):
                basic = pro.etf_basic(
                    ts_code=",".join(new_etf_codes[i:i + 100]),
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
            logger.warning(f"Failed to get ETF listing dates: {e}")
            listing_dates = {}

        history_requests = []
        for ts_code in new_etf_codes:
            etf_start = listing_dates.get(ts_code, "20000101")
            listing_dt = pd.Timestamp(etf_start)
            if start:
                etf_start = max(pd.Timestamp(start), listing_dt)

            start_dt = max(pd.Timestamp(etf_start), self.start_datetime)
            end_dt = pd.Timestamp(end) if end else self.end_datetime
            if start_dt >= end_dt:
                continue

            symbol = ts_code_to_qlib_symbol(ts_code)
            symbol_fname = code_to_fname(symbol)
            history_requests.append(
                {
                    "ts_code": ts_code,
                    "symbol": symbol,
                    "target_path": self.save_dir / f"{symbol_fname}.csv",
                    "listing_dt": listing_dt,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                }
            )

        batches = self._plan_history_batches(history_requests)
        logger.info(
            f"Fetching historical data for {len(history_requests)} new ETF windows "
            f"in {len(batches)} TuShare batches..."
        )

        processed_symbols: Set[str] = set()
        call_count = 0
        rate_window_start = time.time()
        for batch_idx, batch in enumerate(batches):
            elapsed = time.time() - rate_window_start
            if call_count > 0 and elapsed > 0:
                actual_rate = call_count / (elapsed / 60)
                if actual_rate > self.SAFE_CALLS_PER_MINUTE:
                    sleep_time = 60 - (elapsed % 60) + 1
                    logger.info(f"Rate limit reached, sleeping {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    rate_window_start = time.time()
                    call_count = 0

            batch_codes = [item["ts_code"] for item in batch]
            start_str = min(item["start_dt"] for item in batch).strftime("%Y%m%d")
            end_str = max(item["end_dt"] for item in batch).strftime("%Y%m%d")
            try:
                daily = pro.fund_daily(
                    ts_code=",".join(batch_codes),
                    start_date=start_str,
                    end_date=end_str,
                )
                call_count += 1
                if daily is None or daily.empty:
                    continue

                adj = pro.fund_adj(
                    ts_code=",".join(batch_codes),
                    start_date=start_str,
                    end_date=end_str,
                )
                call_count += 1

                if adj is not None and not adj.empty:
                    merged = pd.merge(daily, adj, on=["ts_code", "trade_date"], how="left")
                else:
                    merged = daily.copy()
                    merged["adj_factor"] = 1.0
                merged["date"] = pd.to_datetime(merged["trade_date"])
                merged["symbol"] = merged["ts_code"].apply(ts_code_to_qlib_symbol)

                cols = ["ts_code", "date", "open", "high", "low", "close",
                        "vol", "amount", "adj_factor", "symbol"]
                merged = merged[[c for c in cols if c in merged.columns]]

                for item in batch:
                    symbol_rows = merged[merged["ts_code"] == item["ts_code"]].copy()
                    if symbol_rows.empty:
                        continue
                    symbol_rows = symbol_rows[
                        (symbol_rows["date"] >= item["start_dt"])
                        & (symbol_rows["date"] <= item["end_dt"])
                    ]
                    if symbol_rows.empty:
                        continue

                    target_path = item["target_path"]
                    if target_path.exists():
                        existing = pd.read_csv(target_path, parse_dates=["date"])
                        symbol_rows = pd.concat([existing, symbol_rows], ignore_index=True)
                        symbol_rows = symbol_rows.loc[:, ~symbol_rows.columns.duplicated()]
                    symbol_rows = symbol_rows.drop_duplicates(subset=["date"], keep="last")
                    symbol_rows = symbol_rows.sort_values("date")
                    symbol_rows.to_csv(target_path, index=False)
                    processed_symbols.add(item["ts_code"])

                if (batch_idx + 1) % 10 == 0:
                    logger.info(
                        f"Progress: {batch_idx + 1}/{len(batches)} history batches, "
                        f"{len(processed_symbols)} symbols with data"
                    )

            except Exception as e:
                logger.warning(f"Failed to fetch ETF history batch {batch_codes[:5]}: {e}")

        logger.info(f"Completed fetching data for {len(processed_symbols)}/{len(history_requests)} new ETFs")

    def _plan_history_batches(self, history_requests: List[dict]) -> List[List[dict]]:
        max_rows = max(1, int(self.API_ROWS_PER_CALL))
        max_codes = max(1, int(self.API_CODES_PER_HISTORY_CALL))
        batches: List[List[dict]] = []
        current: List[dict] = []

        for request in sorted(history_requests, key=lambda item: (item["start_dt"], item["end_dt"], item["ts_code"])):
            candidate = current + [request]
            if current and (
                len(candidate) > max_codes
                or self._estimate_history_batch_rows(candidate) > max_rows
            ):
                batches.append(current)
                current = [request]
            else:
                current = candidate

        if current:
            batches.append(current)
        return batches

    def _estimate_history_batch_rows(self, batch: List[dict]) -> int:
        if not batch:
            return 0
        api_start = min(item["start_dt"] for item in batch)
        api_end = max(item["end_dt"] for item in batch)
        total = 0
        for item in batch:
            effective_start = max(pd.Timestamp(item.get("listing_dt", item["start_dt"])), api_start)
            total += _estimate_business_rows(effective_start, api_end)
        return total

    def _parallel_chunk_timeout_seconds(self, chunk: List[pd.Timestamp], safe_calls_per_worker: int) -> int:
        override = os.environ.get("MOSAIC_TUSHARE_PARALLEL_CHUNK_TIMEOUT_SECONDS")
        if override:
            try:
                value = int(override)
                if value > 0:
                    return value
            except ValueError:
                logger.warning(f"Ignoring invalid MOSAIC_TUSHARE_PARALLEL_CHUNK_TIMEOUT_SECONDS={override!r}")

        rate_limit_floor = len(chunk) * self.API_CALLS_PER_DATE * 60 / max(1, safe_calls_per_worker)
        per_date_budget = min(10, max(5, int(self.timeout / 30) if self.timeout else 5))
        return int(max(300, rate_limit_floor + len(chunk) * per_date_budget + 120))

    def fetch_dates_parallel(
        self,
        dates_to_fetch: List[pd.Timestamp],
        processed_dates: Set[str],
        max_workers: int = 4,
    ) -> Set[str]:
        """
        并行获取多个日期的数据。

        Args:
            dates_to_fetch: 待获取的日期列表
            processed_dates: 已处理日期集合
            max_workers: 并行工作进程数

        Returns:
            更新后的已处理日期集合
        """
        if max_workers <= 1 or len(dates_to_fetch) <= 1:
            # 回退到串行模式
            return self._fetch_dates_sequential(dates_to_fetch, processed_dates)

        logger.info(f"Using parallel fetch with {max_workers} workers for {len(dates_to_fetch)} dates")

        # 将日期分组，每个 worker 处理一组日期
        chunk_size = max(1, len(dates_to_fetch) // max_workers)
        chunks = [
            dates_to_fetch[i:i + chunk_size]
            for i in range(0, len(dates_to_fetch), chunk_size)
        ]

        all_processed = processed_dates.copy()
        safe_calls_per_worker = max(1, self.SAFE_CALLS_PER_MINUTE // max_workers)
        executor = ProcessPoolExecutor(max_workers=max_workers)
        timed_out = False
        futures = []
        try:
            futures = [
                executor.submit(
                    _process_date_chunk,
                    (
                        chunk,
                        self.token,
                        self.timeout,
                        str(self.temp_dir),
                        safe_calls_per_worker,
                        self.API_CALLS_PER_DATE,
                    ),
                )
                for chunk in chunks
            ]
            for future, chunk in zip(futures, chunks):
                try:
                    chunk_timeout = self._parallel_chunk_timeout_seconds(chunk, safe_calls_per_worker)
                    result = future.result(timeout=chunk_timeout)
                    all_processed.update(result)
                except TimeoutError:
                    timed_out = True
                    logger.error(
                        f"Chunk processing timed out after {chunk_timeout}s "
                        f"for {len(chunk)} dates; aborting parallel ingest"
                    )
                    for pending in futures:
                        pending.cancel()
                    _terminate_process_pool(executor)
                    break
                except Exception as e:
                    logger.error(f"Chunk processing failed: {e}")
        finally:
            executor.shutdown(wait=not timed_out, cancel_futures=True)

        if timed_out:
            raise RuntimeError("parallel Tushare ETF date fetch timed out")

        return all_processed

    def _fetch_dates_sequential(
        self,
        dates_to_fetch: List[pd.Timestamp],
        processed_dates: Set[str],
    ) -> Set[str]:
        """串行获取日期数据（原逻辑）"""
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
                df = self.fetch_date_data(trade_date)
                call_count += self.API_CALLS_PER_DATE

                if df.empty:
                    logger.warning(f"No data for {trade_date.strftime('%Y-%m-%d')}")
                else:
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
        latest_feature_date = reconcile_result.get("latest_feature_date")
        baseline_last_data_date = latest_feature_date if latest_feature_date is not None else pd.Timestamp(str(calendar_df.iloc[-1, 0]))

        future_cal = calendar_df[calendar_df["date"] > baseline_last_data_date]
        if not future_cal.empty:
            trading_date_ts = future_cal.iloc[0]["date"]
        else:
            trading_date_ts = baseline_last_data_date
        trading_date = trading_date_ts.strftime("%Y-%m-%d")
        if end_date is None:
            end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
        target_end_date = pd.Timestamp(end_date)

        # Filter to only stocks that need updating (incremental mode)
        target_date = target_end_date
        inst_file = Path(qlib_data_1d_dir) / "instruments" / "all.txt"
        outdated_symbols = None
        if inst_file.exists():
            outdated = []
            with open(inst_file) as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 3:
                        symbol, _start_d, end_d = parts[0], parts[1], parts[2]
                        try:
                            end_ts = pd.Timestamp(end_d)
                            if end_ts < target_date:
                                outdated.append(symbol)
                        except Exception:
                            pass

            if outdated:
                logger.info(
                    f"Incremental update: {len(outdated)} stocks need updating "
                    f"(actual last date: {baseline_last_data_date.strftime('%Y-%m-%d')}, target: {end_date})"
                )
                outdated_symbols = outdated

        self.download_data(
            delay=delay,
            start=trading_date,
            end=end_date,
            check_data_length=check_data_length,
            max_collector_count=self.max_collector_count,
            symbols=outdated_symbols,
        )

        self.normalize_data()

        # 准备仅含增量日期的临时目录，减少 dump 工作量
        normalize_dir = Path(self.normalize_dir)
        inc_dir = normalize_dir.joinpath("__inc_tmp__")
        if inc_dir.exists():
            shutil.rmtree(inc_dir)
        inc_dir.mkdir(parents=True, exist_ok=True)

        last_date = baseline_last_data_date
        has_data = False
        for csv_file in normalize_dir.glob("*.csv"):
            df = pd.read_csv(csv_file)
            if "date" not in df.columns:
                continue
            df["date"] = pd.to_datetime(df["date"])
            df_new = df[(df["date"] > last_date) & (df["date"] <= target_end_date)]
            if df_new.empty:
                continue
            # Rescale to match existing bin's normalization constant
            symbol = fname_to_code(csv_file.stem).upper()
            df_new = rescale_normalized_df_to_bin(
                df_new, df, qlib_data_1d_dir, symbol, freq="day"
            )
            has_data = True
            df_new.to_csv(inc_dir.joinpath(csv_file.name), index=False)

        if not has_data:
            shutil.rmtree(inc_dir, ignore_errors=True)
            logger.info("No incremental data found; skip dump.")
        else:
            _dump = DumpDataUpdate(
                data_path=inc_dir,
                qlib_dir=qlib_data_1d_dir,
                exclude_fields="symbol,date",
                max_workers=self.max_workers,
            )
            _dump.dump()
            shutil.rmtree(inc_dir, ignore_errors=True)

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
        """
        同步交易日历到 qlib 目录。

        从 TuShare API 获取交易日历，并与现有的 qlib 日历合并。

        Args:
            qlib_dir: qlib 数据目录
            end: 结束日期，默认为当前日期
        """
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
        timeout: int = 60,
        delay_per_date: float = 0.1,
        max_workers: int = 8,
        prefer_api: bool = False,
        detect_new_etfs: bool = True,
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
            detect_new_etfs: 是否检测并获取新上市ETF的数据
            parallel_dates: 是否并行获取日期数据
        """
        collector = TushareBatchCollector(
            save_dir=self.source_dir,
            qlib_dir=qlib_dir,
            start=start,
            end=end,
            token=token,
            timeout=timeout,
            delay_per_date=delay_per_date,
            max_workers=max_workers,
        )
        collector.collector_data(
            prefer_api=prefer_api,
            detect_new_etfs=detect_new_etfs,
            parallel_dates=parallel_dates,
        )

    def update_data_to_bin_batch(
        self,
        qlib_data_1d_dir: str,
        end_date: str = None,
        timeout: int = 60,
        delay_per_date: float = 0.1,
        detect_new_etfs: bool = True,
        max_workers: Optional[int] = None,
    ):
        """
        增量更新（批量模式）。

        1. 读取 calendars/day.txt 确定最后日期
        2. 只更新最后日期之后的数据
        3. 自动检测并补充新上市ETF数据
        4. 快速合并到现有数据
        5. 导出为 qlib 二进制格式

        Args:
            qlib_data_1d_dir: qlib 数据目录
            end_date: 结束日期，默认为当前日期
            delay_per_date: 每个日期间隔（秒）
            detect_new_etfs: 是否检测并获取新上市ETF的数据
            max_workers: 日期抓取与 dump 的并行工作数，默认为当前配置
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
        latest_feature_date = reconcile_result.get("latest_feature_date")
        baseline_last_data_date = latest_feature_date if latest_feature_date is not None else last_cal_date

        future_cal = calendar_df[calendar_df["date"] > baseline_last_data_date]
        if not future_cal.empty:
            start_date = str(future_cal.iloc[0]["date"].strftime("%Y-%m-%d"))
        else:
            start_date = baseline_last_data_date.strftime("%Y-%m-%d")

        if end_date is None:
            end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
        target_end_date = pd.Timestamp(end_date)

        logger.info(
            "Starting batch incremental update from "
            f"{start_date} to {end_date} "
            f"(actual feature last date: {baseline_last_data_date.strftime('%Y-%m-%d')})..."
        )

        worker_count = max_workers if max_workers is not None else self.max_workers

        # 使用批量收集器下载数据（从日历最后日期开始，优先使用 API 获取最新日历）
        self.download_data_batch(
            qlib_dir=qlib_data_1d_dir,
            start=start_date,
            end=end_date,
            timeout=timeout,
            delay_per_date=delay_per_date,
            max_workers=worker_count,
            prefer_api=True,  # 增量更新时优先使用 API 获取最新日历
            detect_new_etfs=detect_new_etfs,
            parallel_dates=False,
        )

        # 标准化数据
        self.normalize_data()

        normalize_dir = Path(self.normalize_dir)
        inc_dir = normalize_dir / "__inc_tmp__"
        if inc_dir.exists():
            shutil.rmtree(inc_dir)
        inc_dir.mkdir(parents=True, exist_ok=True)

        has_data = False
        for csv_file in normalize_dir.glob("*.csv"):
            try:
                df = pd.read_csv(csv_file)
                if "date" not in df.columns:
                    continue
                df["date"] = pd.to_datetime(df["date"])
                df_new = df[(df["date"] > baseline_last_data_date) & (df["date"] <= target_end_date)]
                if df_new.empty:
                    continue
                has_data = True
                df_new.to_csv(inc_dir / csv_file.name, index=False)
            except Exception as e:
                logger.warning(f"Failed to process {csv_file}: {e}")

        if not has_data:
            shutil.rmtree(inc_dir, ignore_errors=True)
            logger.info("No incremental data found; skip dump.")
        else:
            # 使用 DumpDataUpdate 更新
            _dump = DumpDataUpdate(
                data_path=inc_dir,
                qlib_dir=qlib_data_1d_dir,
                exclude_fields="symbol,date",
                max_workers=worker_count,
            )
            _dump.dump()
            shutil.rmtree(inc_dir, ignore_errors=True)

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
        timeout: int = 60,
        delay_per_date: float = 0.1,
        max_workers: Optional[int] = None,
        detect_new_etfs: bool = True,
        parallel_dates: bool = True,
    ):
        """
        一键批量流程：批量下载 -> 标准化 -> 导出二进制。

        效率比 pipeline() 高约 4 倍。
        """
        worker_count = max_workers if max_workers is not None else self.max_workers
        self.download_data_batch(
            qlib_dir=qlib_dir,
            start=start,
            end=end,
            token=token,
            timeout=timeout,
            delay_per_date=delay_per_date,
            max_workers=worker_count,
            detect_new_etfs=detect_new_etfs,
            parallel_dates=parallel_dates,
        )
        self.normalize_data()
        qlib_dir = Path(qlib_dir).expanduser().resolve() if qlib_dir else Path(DEFAULT_QLIB_DIR).expanduser()
        result = self.dump_to_bin(qlib_dir=qlib_dir, max_workers=worker_count)
        extend_index_instruments(qlib_dir)
        return result


if __name__ == "__main__":  # pragma: no cover - CLI entry
    import fire

    fire.Fire(Run)
