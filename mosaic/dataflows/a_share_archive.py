"""Bounded A-share helpers shared by Sector capture routes."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any


HISTORY_CALENDAR_DAYS = 500
MIN_CAPTURE_SESSIONS = 60 - 1 + 252


class AShareArchiveError(RuntimeError):
    """Base class for bounded A-share source failures."""


class AShareSchemaError(AShareArchiveError):
    """The provider response violated the frozen parser schema."""


class ASharePaginationError(AShareArchiveError):
    """A paginated query did not prove its terminal page."""


class AShareIncompleteCoverage(AShareArchiveError):
    """The bounded source set does not close its required window."""


class AShareNonTradingDay(AShareArchiveError):
    """The requested as-of is not an open SSE session."""


def _api_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _row_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        return _row_value(item())
    if isinstance(value, Mapping):
        return {str(key): _row_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_row_value(item) for item in value]
    return str(value)


def _response_rows(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"):
        records = value.to_dict(orient="records")
    elif isinstance(value, Mapping):
        raise ConnectionError("Tushare returned a non-tabular response")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        records = list(value)
    else:
        raise AShareSchemaError("Tushare response must be a table or row sequence")
    if not all(isinstance(row, Mapping) for row in records):
        raise AShareSchemaError("Tushare response rows must be objects")
    return [{str(key): _row_value(item) for key, item in row.items()} for row in records]


def _calendar_sessions(
    rows: Sequence[Mapping[str, Any]],
    *,
    start_date: date,
    as_of_date: date,
) -> list[str]:
    by_date: dict[date, int] = {}
    for row in rows:
        try:
            day = datetime.strptime(str(row["cal_date"]), "%Y%m%d").date()
            is_open = int(row["is_open"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AShareSchemaError("trade_cal contains invalid calendar rows") from exc
        if day in by_date or is_open not in {0, 1}:
            raise AShareSchemaError("trade_cal contains duplicate or invalid sessions")
        if start_date <= day <= as_of_date:
            by_date[day] = is_open
    expected = [
        start_date + timedelta(days=offset)
        for offset in range((as_of_date - start_date).days + 1)
    ]
    if set(by_date) != set(expected):
        raise AShareIncompleteCoverage("trade_cal is not calendar-date exhaustive")
    if by_date[as_of_date] != 1:
        raise AShareNonTradingDay(as_of_date.isoformat())
    sessions = [_api_date(day) for day in expected if by_date[day] == 1]
    if len(sessions) < MIN_CAPTURE_SESSIONS:
        raise AShareIncompleteCoverage("trade_cal has insufficient breadth history")
    return sessions


def _codes_by_session(batch: Mapping[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for row in batch["rows"]:
        result.setdefault(str(row["trade_date"]), set()).add(str(row["ts_code"]))
    return result


def _validate_session_closure(
    batches: Sequence[Mapping[str, Any]],
    sessions: Sequence[str],
) -> None:
    by_endpoint = {str(batch["endpoint"]): batch for batch in batches}
    daily = _codes_by_session(by_endpoint["daily"])
    adjusted = _codes_by_session(by_endpoint["adj_factor"])
    daily_basic = _codes_by_session(by_endpoint["daily_basic"])
    for session in sessions:
        daily_codes = daily.get(session, set())
        if not daily_codes <= adjusted.get(session, set()):
            raise AShareIncompleteCoverage(
                "adjustment factors do not cover the daily market rows"
            )
        if daily_basic.get(session, set()) != daily_codes:
            raise AShareIncompleteCoverage(
                "daily-basic rows do not match the daily market rows"
            )


def fetch_a_share_tushare_endpoint(endpoint: str, **params: Any) -> Any:
    """Production transport adapter; authorization stays with the bounded owner."""
    from mosaic.dataflows.tushare import _query_pro  # noqa: PLC0415

    return _query_pro(endpoint, **params)


__all__ = [
    "ASharePaginationError",
    "AShareSchemaError",
    "HISTORY_CALENDAR_DAYS",
    "fetch_a_share_tushare_endpoint",
]
