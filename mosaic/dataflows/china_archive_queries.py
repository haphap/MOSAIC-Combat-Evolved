"""Read restored China adaptive queries from existing trusted PIT archives."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

import pandas as pd

from mosaic.dataflows.china_agent_data_archive import (
    CURVE_ROUTE_GROUP,
    INSTITUTIONAL_ROUTE_GROUP,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.macro_data import _df_to_markdown_csv


class ChinaArchiveQueryReader:
    """Render industry flow and government curve without live transport."""

    def __init__(self, *, store: Any) -> None:
        self.store = store

    def _group(self, as_of: str, route_group: str) -> dict[str, Any]:
        try:
            group = self.store.load_route_group(as_of, route_group)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise DataVendorUnavailable(
                f"no exact China archive is available for {route_group} at {as_of}"
            ) from exc
        if (
            not isinstance(group, Mapping)
            or group.get("as_of_date") != as_of
            or group.get("route_group") != route_group
        ):
            raise DataVendorUnavailable("China archive route/as_of identity drift")
        return dict(group)

    @staticmethod
    def _window(as_of: str, lookback: int) -> tuple[date, date]:
        if lookback < 1:
            raise DataVendorUnavailable("lookback must be >= 1")
        end = date.fromisoformat(as_of)
        return end - timedelta(days=lookback), end

    @staticmethod
    def _rows(group: Mapping[str, Any], field: str) -> list[dict[str, Any]]:
        rows = group.get(field)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise DataVendorUnavailable(f"China archive lacks {field}")
        if any(not isinstance(row, Mapping) for row in rows):
            raise DataVendorUnavailable(f"China archive {field} is malformed")
        return [dict(row) for row in rows]

    def __call__(self, method: str, *route_args: Any) -> str:
        if method == "get_industry_moneyflow":
            as_of, lookback, industries = (
                str(route_args[0]),
                int(route_args[1]),
                str(route_args[2]),
            )
            start, end = self._window(as_of, lookback)
            group = self._group(as_of, INSTITUTIONAL_ROUTE_GROUP)
            if date.fromisoformat(str(group.get("industry_history_start"))) > start:
                raise DataVendorUnavailable(
                    "China industry archive does not cover the requested lookback"
                )
            rows = [
                row
                for row in self._rows(group, "industry_history_rows")
                if start <= date.fromisoformat(str(row.get("trade_date"))) <= end
            ]
            if not rows:
                raise DataVendorUnavailable(
                    "China industry archive has no rows in the requested window"
                )
            frame = pd.DataFrame(rows)
            subtitle = (
                "Source: Tushare moneyflow_ind_ths (同花顺行业). "
                "net_amount = 行业净流入; positive = main funds rotating in."
            )
            tokens = [
                token.strip()
                for token in re.split(r"[,，、]", industries)
                if token.strip()
            ]
            if tokens:
                pattern = "|".join(re.escape(token) for token in tokens)
                matched = frame[
                    frame["industry"].astype(str).str.contains(pattern, na=False)
                ]
                if not matched.empty:
                    frame = matched
                    subtitle += (
                        " Filtered to industries matching: " + ", ".join(tokens) + "."
                    )
                else:
                    subtitle += (
                        " (No THS industry matched "
                        + ", ".join(tokens)
                        + " — showing all; check the 同花顺行业 name.)"
                    )
            return _df_to_markdown_csv(
                frame.sort_values(["trade_date", "industry"], ascending=[False, True]),
                title=(
                    "行业资金流向 / Industry Money Flow "
                    f"({start.isoformat()} → {end.isoformat()})"
                ),
                subtitle=subtitle,
                empty_note="No industry moneyflow rows in the archived window.",
            )

        if method == "get_yield_curve_cn":
            as_of, lookback = str(route_args[0]), int(route_args[1])
            start, end = self._window(as_of, lookback)
            group = self._group(as_of, CURVE_ROUTE_GROUP)
            if date.fromisoformat(str(group.get("curve_history_start"))) > start:
                raise DataVendorUnavailable(
                    "China curve archive does not cover the requested lookback"
                )
            rows = [
                row
                for row in self._rows(group, "government_curve_rows")
                if start <= date.fromisoformat(str(row.get("trade_date"))) <= end
            ]
            if not rows:
                raise DataVendorUnavailable(
                    "China curve archive has no rows in the requested window"
                )
            return _df_to_markdown_csv(
                pd.DataFrame(rows).sort_values(
                    ["trade_date", "curve_term"], ascending=[False, True]
                ),
                title=(
                    "中国国债收益率曲线 / CN Treasury Yield Curve "
                    f"({start.isoformat()} → {end.isoformat()})"
                ),
                subtitle=(
                    "Source: MOF/ChinaBond official maturity curve. "
                    "Yields in percent. Tenors: "
                    "1y/2y/3y/5y/7y/10y/30y benchmarks."
                ),
                empty_note="No official curve rows in the archived window.",
            )

        raise ValueError(f"China archive reader does not own route method {method}")


__all__ = ["ChinaArchiveQueryReader"]
