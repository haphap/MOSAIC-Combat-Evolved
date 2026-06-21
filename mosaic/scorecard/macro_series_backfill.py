"""Backfill scorecard macro_series from existing macro dataflow adapters."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from mosaic.dataflows import macro_data
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.scorecard.store import ScorecardStore


@dataclass(frozen=True)
class MacroSeriesBackfillSpec:
    series_id: str
    fetch_kind: str
    source: str
    endpoint_name: str
    instrument: str
    vendor_series_id: str = ""
    ts_code: str = ""
    value_columns: tuple[str, ...] = ("value", "close", "settle")


MACRO_SERIES_BACKFILL_SPECS: Mapping[str, MacroSeriesBackfillSpec] = {
    "US10Y": MacroSeriesBackfillSpec(
        series_id="US10Y",
        fetch_kind="tushare_macro_series",
        vendor_series_id="DGS10",
        source="tushare",
        endpoint_name="us_tycr",
        instrument="DGS10",
    ),
    "US2Y": MacroSeriesBackfillSpec(
        series_id="US2Y",
        fetch_kind="tushare_macro_series",
        vendor_series_id="DGS2",
        source="tushare",
        endpoint_name="us_tycr",
        instrument="DGS2",
    ),
    "US3M": MacroSeriesBackfillSpec(
        series_id="US3M",
        fetch_kind="tushare_macro_series",
        vendor_series_id="DGS3MO",
        source="tushare",
        endpoint_name="us_tycr",
        instrument="DGS3MO",
    ),
    "USDCNY": MacroSeriesBackfillSpec(
        series_id="USDCNY",
        fetch_kind="usdcny",
        source="tushare",
        endpoint_name="fx_daily",
        instrument="USDCNH.FXCM",
        value_columns=("value", "close", "bid_close", "ask_close"),
    ),
    "COPPER": MacroSeriesBackfillSpec(
        series_id="COPPER",
        fetch_kind="commodity_prices",
        source="tushare",
        endpoint_name="fut_daily",
        instrument="CU.SHF",
        ts_code="CU.SHF",
        value_columns=("close", "settle", "value"),
    ),
    "CRUDE_OIL": MacroSeriesBackfillSpec(
        series_id="CRUDE_OIL",
        fetch_kind="commodity_prices",
        source="tushare",
        endpoint_name="fut_daily",
        instrument="SC.INE",
        ts_code="SC.INE",
        value_columns=("close", "settle", "value"),
    ),
    "GOLD_SPOT": MacroSeriesBackfillSpec(
        series_id="GOLD_SPOT",
        fetch_kind="commodity_prices",
        source="tushare",
        endpoint_name="fut_daily",
        instrument="AU.SHF",
        ts_code="AU.SHF",
        value_columns=("close", "settle", "value"),
    ),
    "CN10Y": MacroSeriesBackfillSpec(
        series_id="CN10Y",
        fetch_kind="yield_curve_cn",
        source="tushare",
        endpoint_name="yc_cb",
        instrument="10Y.CN",
        value_columns=("cn_10y_pct", "curve_yield", "value"),
    ),
    "VIX": MacroSeriesBackfillSpec(
        series_id="VIX",
        fetch_kind="yfinance_index",
        source="yfinance",
        endpoint_name="download",
        instrument="^VIX",
        value_columns=("close", "value"),
    ),
}


def _normalise_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).strftime(
                "%Y-%m-%d"
            )
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text[:19]).date().isoformat()
    except ValueError:
        return ""


def _lookback_days(start_date: str, end_date: str) -> int:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return max((end - start).days, 0)


def _markdown_csv_rows(markdown_csv: str) -> list[dict[str, str]]:
    csv_lines = [
        line
        for line in str(markdown_csv or "").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not csv_lines or "," not in csv_lines[0]:
        return []
    return list(csv.DictReader(io.StringIO("\n".join(csv_lines))))


def _row_matches_spec(row: Mapping[str, str], spec: MacroSeriesBackfillSpec) -> bool:
    if not spec.ts_code:
        return True
    return str(row.get("ts_code") or "").strip().upper() == spec.ts_code.upper()


def _row_date(row: Mapping[str, str]) -> str:
    for field in ("date", "trade_date", "stat_date", "datetime", "time", "日期"):
        if field in row:
            date_key = _normalise_date(row.get(field))
            if date_key:
                return date_key
    return ""


def _row_value(row: Mapping[str, str], spec: MacroSeriesBackfillSpec) -> float | None:
    bid = row.get("bid_close")
    ask = row.get("ask_close")
    if bid not in {None, ""} and ask not in {None, ""}:
        try:
            return (float(bid) + float(ask)) / 2.0
        except ValueError:
            pass
    for field in spec.value_columns:
        value = row.get(field)
        if value in {None, ""}:
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return None


def _fetch_markdown_csv(
    spec: MacroSeriesBackfillSpec,
    *,
    start_date: str,
    end_date: str,
    fetchers: Mapping[str, Callable[..., str]],
) -> str:
    if spec.fetch_kind == "tushare_macro_series":
        fetcher = fetchers.get(spec.fetch_kind, macro_data.get_tushare_macro_series)
        return fetcher(spec.vendor_series_id, start_date=start_date, end_date=end_date)
    look_back_days = _lookback_days(start_date, end_date)
    if spec.fetch_kind == "usdcny":
        fetcher = fetchers.get(spec.fetch_kind, macro_data.get_usdcny)
        return fetcher(end_date, look_back_days=look_back_days)
    if spec.fetch_kind == "commodity_prices":
        fetcher = fetchers.get(spec.fetch_kind, macro_data.get_commodity_prices)
        return fetcher(end_date, look_back_days=look_back_days)
    if spec.fetch_kind == "yield_curve_cn":
        fetcher = fetchers.get(spec.fetch_kind, macro_data.get_yield_curve_cn)
        return fetcher(end_date, look_back_days=look_back_days)
    if spec.fetch_kind == "realized_volatility":
        fetcher = fetchers.get(spec.fetch_kind, macro_data.get_realized_volatility)
        return fetcher(end_date, top_n=max(look_back_days + 7, 30))
    if spec.fetch_kind == "yfinance_index":
        fetcher = fetchers.get(spec.fetch_kind, macro_data.get_ivx)
        return fetcher(end_date, look_back_days=look_back_days, index_symbol=spec.instrument)
    raise DataVendorUnavailable(f"unsupported macro series fetch kind: {spec.fetch_kind}")


def _series_rows_from_markdown_csv(
    markdown_csv: str,
    *,
    spec: MacroSeriesBackfillSpec,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _markdown_csv_rows(markdown_csv):
        if not _row_matches_spec(row, spec):
            continue
        date_key = _row_date(row)
        value = _row_value(row, spec)
        if not date_key or value is None:
            continue
        rows.append(
            {
                "series_id": spec.series_id,
                "source": spec.source,
                "endpoint_name": spec.endpoint_name,
                "instrument": spec.instrument,
                "date": date_key,
                "value": value,
                "as_of_date": date_key,
                "metadata": {
                    "backfill_source": "macro_series_backfill",
                    "source_endpoint": spec.endpoint_name,
                    "vendor_series_id": spec.vendor_series_id,
                    "ts_code": spec.ts_code,
                },
            }
        )
    return rows


def backfill_macro_series(
    *,
    start_date: str,
    end_date: str,
    series_ids: Sequence[str] = (),
    db_path: str | Path | None = None,
    fetchers: Mapping[str, Callable[..., str]] | None = None,
) -> dict[str, Any]:
    selected_series_ids = tuple(
        dict.fromkeys(str(item).strip().upper() for item in series_ids if str(item).strip())
    ) or tuple(MACRO_SERIES_BACKFILL_SPECS)
    store = ScorecardStore(Path(db_path).expanduser() if db_path else None)
    fetchers = fetchers or {}
    inserted_rows = 0
    fetched_rows = 0
    series_counts: dict[str, int] = {}
    failures: list[dict[str, str]] = []
    for series_id in selected_series_ids:
        spec = MACRO_SERIES_BACKFILL_SPECS.get(series_id)
        if spec is None:
            failures.append({"series_id": series_id, "error": "unsupported_series_id"})
            continue
        try:
            markdown_csv = _fetch_markdown_csv(
                spec,
                start_date=start_date,
                end_date=end_date,
                fetchers=fetchers,
            )
            rows = _series_rows_from_markdown_csv(markdown_csv, spec=spec)
        except Exception as exc:
            failures.append({"series_id": series_id, "error": str(exc)})
            continue
        fetched_rows += len(rows)
        inserted = store.append_macro_series(rows)
        inserted_rows += inserted
        series_counts[series_id] = inserted
    return {
        "accepted": not failures and inserted_rows > 0,
        "db_path": str(store.db_path),
        "requested_series_ids": list(selected_series_ids),
        "fetched_rows": fetched_rows,
        "inserted_rows": inserted_rows,
        "series_counts": series_counts,
        "failures": failures,
    }


__all__ = [
    "MACRO_SERIES_BACKFILL_SPECS",
    "backfill_macro_series",
]
