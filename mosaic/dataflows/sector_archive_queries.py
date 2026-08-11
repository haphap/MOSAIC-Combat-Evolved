"""Read restored Sector adaptive queries from one trusted PIT archive group."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from mosaic.dataflows.exceptions import DataVendorUnavailable, MissingEtfHoldings
from mosaic.dataflows.tushare import (
    _build_balance_sheet_summary,
    _build_cashflow_summary,
    _build_income_statement_summary,
    _filter_statement,
    _normalize_ts_code,
    _render_etf_holdings,
    _render_indicator_frame,
    _render_statement_frame,
    _render_stock_data,
)


_STATEMENTS = {
    "get_balance_sheet": (
        "balancesheet",
        "balance sheet",
        _build_balance_sheet_summary,
    ),
    "get_cashflow": ("cashflow", "cashflow", _build_cashflow_summary),
    "get_income_statement": (
        "income",
        "income statement",
        _build_income_statement_summary,
    ),
}


class SectorArchiveQueryReader:
    """Preserve legacy string outputs while replacing live transport with archive reads."""

    def __init__(self, *, store: Any) -> None:
        self.store = store

    def _group(
        self,
        as_of: str,
        *,
        required_route_ids: Sequence[str],
        required_security_code: str,
    ) -> dict[str, Any]:
        try:
            group = self.store.load_group(
                as_of,
                required_route_ids=required_route_ids,
                required_security_code=required_security_code,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise DataVendorUnavailable(
                f"no exact Sector archive is available for {as_of}"
            ) from exc
        if not isinstance(group, Mapping) or group.get("as_of_date") != as_of:
            raise DataVendorUnavailable("Sector archive group as_of does not match query")
        captured_at = group.get("captured_at")
        if not isinstance(captured_at, str) or not captured_at:
            raise DataVendorUnavailable("Sector archive group has no capture timestamp")
        return dict(group)

    @staticmethod
    def _rows(group: Mapping[str, Any], endpoint: str) -> list[dict[str, Any]]:
        batches = [
            batch
            for batch in group.get("batches", ())
            if isinstance(batch, Mapping) and batch.get("endpoint") == endpoint
        ]
        if len(batches) != 1 or not isinstance(batches[0].get("rows"), Sequence):
            raise DataVendorUnavailable(f"Sector archive {endpoint} batch is unavailable")
        rows = batches[0]["rows"]
        if any(not isinstance(row, Mapping) for row in rows):
            raise DataVendorUnavailable(f"Sector archive {endpoint} rows are invalid")
        return [dict(row) for row in rows]

    @staticmethod
    def _price_frame(
        group: Mapping[str, Any],
        *,
        ticker: str,
        date_from: str | None = None,
        date_to: str,
    ) -> pd.DataFrame:
        start_api = date_from.replace("-", "") if date_from else None
        end_api = date_to.replace("-", "")
        rows = [
            row
            for row in SectorArchiveQueryReader._rows(group, "daily")
            if str(row.get("ts_code")) == ticker
            and (start_api is None or str(row.get("trade_date", "")) >= start_api)
            and str(row.get("trade_date", "")) <= end_api
        ]
        if not rows:
            raise DataVendorUnavailable(
                f"no archived daily rows for {ticker} through {date_to}"
            )
        return pd.DataFrame(rows)

    def __call__(self, method: str, *route_args: Any) -> str:
        if method == "get_stock_data":
            ticker = _normalize_ts_code(str(route_args[0]))
            date_from, date_to = str(route_args[1]), str(route_args[2])
            group = self._group(
                date_to,
                required_route_ids=("tushare.sector_market",),
                required_security_code=ticker,
            )
            return _render_stock_data(
                self._price_frame(
                    group,
                    ticker=ticker,
                    date_from=date_from,
                    date_to=date_to,
                ),
                ts_code=ticker,
                start_date=date_from,
                end_date=date_to,
                retrieved_at=str(group["captured_at"]),
            )

        if method == "get_indicators":
            ticker = _normalize_ts_code(str(route_args[0]))
            indicator, as_of, lookback = (
                str(route_args[1]),
                str(route_args[2]),
                int(route_args[3]),
            )
            group = self._group(
                as_of,
                required_route_ids=("tushare.sector_market",),
                required_security_code=ticker,
            )
            frame = self._price_frame(group, ticker=ticker, date_to=as_of).rename(
                columns={
                    "trade_date": "Date",
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "vol": "Volume",
                }
            )
            frame["Date"] = pd.to_datetime(frame["Date"], format="%Y%m%d")
            frame = frame.sort_values("Date", ascending=True)
            return _render_indicator_frame(
                frame[["Date", "Open", "High", "Low", "Close", "Volume"]],
                indicator=indicator,
                curr_date=as_of,
                look_back_days=lookback,
            )

        if method in _STATEMENTS:
            ticker = _normalize_ts_code(str(route_args[0]))
            frequency, as_of = str(route_args[1]), str(route_args[2])
            group = self._group(
                as_of,
                required_route_ids=("tushare.sector_fundamentals",),
                required_security_code=ticker,
            )
            endpoint, title, summary_builder = _STATEMENTS[method]
            rows = [
                row
                for row in self._rows(group, endpoint)
                if str(row.get("ts_code")) == ticker
            ]
            if not rows:
                raise DataVendorUnavailable(
                    f"Sector archive {endpoint} has no rows for {ticker}"
                )
            filtered = _filter_statement(pd.DataFrame(rows), frequency, as_of)
            if filtered is None or filtered.empty:
                raise DataVendorUnavailable(
                    f"Sector archive {endpoint} has no PIT-eligible rows for {ticker}"
                )
            return _render_statement_frame(
                filtered,
                title=f"Tushare {title} for {ticker} ({frequency})",
                summary_builder=summary_builder,
                retrieved_at=str(group["captured_at"]),
            )

        if method == "get_etf_holdings":
            ticker = _normalize_ts_code(str(route_args[0]))
            as_of = str(route_args[1])
            group = self._group(
                as_of,
                required_route_ids=("tushare.sector_market",),
                required_security_code=ticker,
            )
            rows = [
                row
                for row in self._rows(group, "fund_portfolio")
                if str(row.get("ts_code")) == ticker
            ]
            if not rows:
                raise DataVendorUnavailable(
                    f"Sector archive fund_portfolio has no rows for {ticker}"
                )
            frame = pd.DataFrame(rows)
            stock_names = {
                str(row.get("ts_code")): str(row.get("name"))
                for row in self._rows(group, "stock_basic")
                if row.get("ts_code") and row.get("name")
            }
            if "stk_name" not in frame.columns:
                frame["stk_name"] = ""
            if "symbol" in frame.columns:
                missing = frame["stk_name"].fillna("").astype(str).str.strip().eq("")
                frame.loc[missing, "stk_name"] = frame.loc[missing, "symbol"].map(
                    stock_names
                ).fillna("")
            try:
                return _render_etf_holdings(
                    frame,
                    ts_code=ticker,
                    curr_date=as_of,
                    retrieved_at=str(group["captured_at"]),
                )
            except MissingEtfHoldings as exc:
                raise DataVendorUnavailable(str(exc)) from exc

        raise ValueError(f"Sector archive reader does not own route method {method}")


__all__ = ["SectorArchiveQueryReader"]
