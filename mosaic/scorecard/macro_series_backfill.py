"""Backfill scorecard macro_series from existing macro dataflow adapters."""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from mosaic.dataflows import macro_data
from mosaic.dataflows.agent_materialization import SourceCaptureReceipt
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.scorecard.canonical_json import canonical_hash
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
        source="mof_chinabond",
        endpoint_name="historyQuery",
        instrument="10Y.CN",
        value_columns=("yield", "cn_10y_pct", "curve_yield", "value"),
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

ALFRED_SCORECARD_SERIES_MAP: Mapping[str, str] = {
    "VIXCLS": "VIX",
}

_TUSHARE_TREASURY_SCORECARD_FIELDS: Mapping[str, str] = {
    "US10Y": "y10",
    "US2Y": "y2",
    "US3M": "m3",
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
    if spec.series_id == "CN10Y":
        try:
            return float(str(row.get("curve_term") or "")) == 10.0
        except ValueError:
            return False
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


def project_alfred_capture_to_macro_series(
    *,
    group: Mapping[str, Any],
    source_receipt: SourceCaptureReceipt,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Project a receipt-bound ALFRED archive through the existing scorecard store."""
    receipt = SourceCaptureReceipt.from_dict(source_receipt.as_dict()).as_dict()
    if receipt["identity"]["route_id"] != "alfred.us_macro":
        raise ValueError("ALFRED projection requires an alfred.us_macro receipt")
    if not receipt["pit"]["eligible"]:
        raise ValueError("ALFRED projection requires a PIT-eligible source receipt")
    if group.get("schema_version") != "us_macro_capture_group_v1":
        raise ValueError("ALFRED projection capture schema drift")
    alfred = group.get("alfred")
    if not isinstance(alfred, Mapping):
        raise ValueError("ALFRED projection raw content is missing")
    if receipt["content"]["raw_content_hash"] != canonical_hash(alfred):
        raise ValueError("ALFRED projection source receipt raw content mismatch")
    try:
        cutoff = datetime.fromisoformat(
            str(receipt["pit"]["as_of_cutoff"]).replace("Z", "+00:00")
        )
        as_of_date = datetime.strptime(str(group["as_of_date"]), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("ALFRED projection has invalid as-of metadata") from exc
    if cutoff.date() != as_of_date:
        raise ValueError("ALFRED projection receipt as-of does not match capture")

    by_series: dict[str, Mapping[str, Any]] = {}
    for item in alfred.get("series", []):
        if not isinstance(item, Mapping):
            raise ValueError("ALFRED projection series entry is malformed")
        series_id = str(item.get("series_id") or "")
        if series_id in by_series:
            raise ValueError("ALFRED projection has duplicate provider series")
        by_series[series_id] = item
    missing = sorted(set(ALFRED_SCORECARD_SERIES_MAP) - set(by_series))
    if missing:
        raise ValueError(f"ALFRED projection is missing required series: {missing}")

    rows: list[dict[str, Any]] = []
    projected: list[str] = []
    for provider_series_id, series_id in sorted(ALFRED_SCORECARD_SERIES_MAP.items()):
        item = by_series[provider_series_id]
        payload = item.get("payload")
        if not isinstance(payload, Mapping) or canonical_hash(payload) != item.get(
            "payload_hash"
        ):
            raise ValueError("ALFRED projection provider payload hash mismatch")
        observations = payload.get("observations")
        if not isinstance(observations, list):
            raise ValueError("ALFRED projection provider observations are malformed")
        series_rows = 0
        for observation in observations:
            if not isinstance(observation, Mapping):
                raise ValueError("ALFRED projection observation is malformed")
            try:
                observed = datetime.strptime(
                    str(observation["date"]), "%Y-%m-%d"
                ).date()
            except (KeyError, ValueError) as exc:
                raise ValueError("ALFRED projection observation date is invalid") from exc
            raw_value = observation.get("value")
            if observed > as_of_date or raw_value in {None, "", "."}:
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError("ALFRED projection observation is not numeric") from exc
            if not math.isfinite(value):
                raise ValueError("ALFRED projection observation is not finite")
            rows.append(
                {
                    "series_id": series_id,
                    "source": "alfred",
                    "endpoint_name": "fred_series_observations",
                    "instrument": provider_series_id,
                    "date": observed.isoformat(),
                    "value": value,
                    "as_of_date": as_of_date.isoformat(),
                    "fetched_at": group["captured_at"],
                    "metadata": {
                        "backfill_source": "receipt_bound_alfred_projection",
                        "capture_key": group["capture_key"],
                        "provider_series_id": provider_series_id,
                        "raw_payload_hash": item["payload_hash"],
                        "source_receipt_hash": receipt["receipt_hash"],
                        "vintage_date": item["vintage_date"],
                    },
                }
            )
            series_rows += 1
        if series_rows == 0:
            raise ValueError(
                f"ALFRED projection has no usable observations for {provider_series_id}"
            )
        projected.append(series_id)
    rows.sort(key=lambda row: (row["series_id"], row["date"]))
    store = ScorecardStore(Path(db_path).expanduser() if db_path else None)
    inserted = store.append_macro_series(rows)
    return {
        "accepted": inserted == len(rows),
        "db_path": str(store.db_path),
        "inserted_rows": inserted,
        "projected_series_ids": sorted(projected),
        "source_receipt_hash": receipt["receipt_hash"],
    }


def project_tushare_capture_to_macro_series(
    *,
    group: Mapping[str, Any],
    source_receipts: Sequence[SourceCaptureReceipt],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Project sealed Tushare US curve/FX rows through the existing specs/store."""
    if group.get("schema_version") != "us_macro_capture_group_v1":
        raise ValueError("Tushare projection capture schema drift")
    tushare = group.get("tushare")
    if not isinstance(tushare, Mapping):
        raise ValueError("Tushare projection raw content is missing")
    receipts = {
        receipt.as_dict()["identity"]["route_id"]: receipt.as_dict()
        for receipt in source_receipts
        if receipt.as_dict()["identity"]["route_id"]
        in {"tushare.fx_daily", "tushare.us_tycr"}
    }
    if set(receipts) != {"tushare.fx_daily", "tushare.us_tycr"}:
        raise ValueError("Tushare projection requires both US source receipts")
    try:
        as_of_date = datetime.strptime(str(group["as_of_date"]), "%Y-%m-%d").date()
    except (KeyError, ValueError) as exc:
        raise ValueError("Tushare projection has invalid as-of metadata") from exc

    for endpoint in ("fx_daily", "us_tycr"):
        source = tushare.get(endpoint)
        receipt = receipts[f"tushare.{endpoint}"]
        if not isinstance(source, Mapping):
            raise ValueError(f"Tushare projection is missing {endpoint}")
        if not receipt["pit"]["eligible"]:
            raise ValueError(f"Tushare projection requires eligible {endpoint} receipt")
        try:
            cutoff = datetime.fromisoformat(
                str(receipt["pit"]["as_of_cutoff"]).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                f"Tushare projection {endpoint} receipt cutoff is invalid"
            ) from exc
        if cutoff.date() != as_of_date:
            raise ValueError(f"Tushare projection {endpoint} receipt as-of mismatch")
        if receipt["time"]["captured_at"] != group.get("captured_at"):
            raise ValueError(f"Tushare projection {endpoint} capture time mismatch")
        if receipt["content"]["raw_content_hash"] != source.get("payload_hash"):
            raise ValueError(f"Tushare projection {endpoint} receipt content mismatch")

    rows: list[dict[str, Any]] = []
    projected: list[str] = []
    treasury = tushare["us_tycr"]
    treasury_receipt = receipts["tushare.us_tycr"]
    for series_id, field in sorted(_TUSHARE_TREASURY_SCORECARD_FIELDS.items()):
        spec = MACRO_SERIES_BACKFILL_SPECS[series_id]
        series_rows = 0
        for source_row in treasury.get("rows", []):
            observed_text = _normalise_date(source_row.get("date"))
            if not observed_text:
                raise ValueError("Tushare projection us_tycr date is invalid")
            observed = datetime.strptime(observed_text, "%Y-%m-%d").date()
            if observed > as_of_date:
                continue
            if source_row.get(field) in {None, ""}:
                continue
            try:
                value = float(source_row[field])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Tushare projection us_tycr.{field} is not numeric"
                ) from exc
            if not math.isfinite(value):
                raise ValueError(f"Tushare projection us_tycr.{field} is not finite")
            rows.append(
                {
                    "series_id": series_id,
                    "source": spec.source,
                    "endpoint_name": spec.endpoint_name,
                    "instrument": spec.instrument,
                    "date": observed_text,
                    "value": value,
                    "as_of_date": as_of_date.isoformat(),
                    "fetched_at": group["captured_at"],
                    "metadata": {
                        "backfill_source": "receipt_bound_tushare_projection",
                        "capture_key": group["capture_key"],
                        "raw_payload_hash": treasury["payload_hash"],
                        "source_receipt_hash": treasury_receipt["receipt_hash"],
                        "provider_field": field,
                    },
                }
            )
            series_rows += 1
        if series_rows == 0:
            raise ValueError(f"Tushare projection has no usable rows for {series_id}")
        projected.append(series_id)

    fx = tushare["fx_daily"]
    fx_receipt = receipts["tushare.fx_daily"]
    fx_spec = MACRO_SERIES_BACKFILL_SPECS["USDCNY"]
    fx_rows = 0
    for source_row in fx.get("rows", []):
        observed_text = _normalise_date(source_row.get("trade_date"))
        if not observed_text:
            raise ValueError("Tushare projection fx_daily date is invalid")
        observed = datetime.strptime(observed_text, "%Y-%m-%d").date()
        if observed > as_of_date:
            continue
        if source_row.get("bid_close") in {None, ""} or source_row.get(
            "ask_close"
        ) in {None, ""}:
            continue
        try:
            bid = float(source_row["bid_close"])
            ask = float(source_row["ask_close"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "Tushare projection fx_daily midpoint is not numeric"
            ) from exc
        if not math.isfinite(bid) or not math.isfinite(ask):
            raise ValueError("Tushare projection fx_daily midpoint is not finite")
        rows.append(
            {
                "series_id": "USDCNY",
                "source": fx_spec.source,
                "endpoint_name": fx_spec.endpoint_name,
                "instrument": fx_spec.instrument,
                "date": observed_text,
                "value": (bid + ask) / 2,
                "as_of_date": as_of_date.isoformat(),
                "fetched_at": group["captured_at"],
                "metadata": {
                    "backfill_source": "receipt_bound_tushare_projection",
                    "capture_key": group["capture_key"],
                    "raw_payload_hash": fx["payload_hash"],
                    "source_receipt_hash": fx_receipt["receipt_hash"],
                    "provider_field": "bid_close+ask_close midpoint",
                },
            }
        )
        fx_rows += 1
    if fx_rows == 0:
        raise ValueError("Tushare projection has no usable rows for USDCNY")
    projected.append("USDCNY")

    rows.sort(key=lambda row: (row["series_id"], row["date"]))
    store = ScorecardStore(Path(db_path).expanduser() if db_path else None)
    inserted = store.append_macro_series(rows)
    return {
        "accepted": inserted == len(rows),
        "db_path": str(store.db_path),
        "inserted_rows": inserted,
        "projected_series_ids": sorted(projected),
        "source_receipt_hashes": sorted(
            receipt["receipt_hash"] for receipt in receipts.values()
        ),
    }


__all__ = [
    "ALFRED_SCORECARD_SERIES_MAP",
    "MACRO_SERIES_BACKFILL_SPECS",
    "backfill_macro_series",
    "project_alfred_capture_to_macro_series",
    "project_tushare_capture_to_macro_series",
]
