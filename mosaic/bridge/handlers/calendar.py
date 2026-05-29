"""``calendar.*`` JSON-RPC handlers (PR #4 review hotfix #2).

Exposes ``mosaic.dataflows.calendar`` to the TS front-end so the
backtest CLIs can enumerate true A-share trading days (vs Mon-Fri
weekday approximation that wasted LLM calls on holidays).

Surface:
    * calendar.list_trading_days(start, end) → {trading_days: [str]}
    * calendar.is_trading_day(date) → {is_trading: bool}
    * calendar.next_trading_day(date, n) → {date: str}
"""

from __future__ import annotations

from typing import Any

from ..protocol import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from ..registry import method


def _require_str(params: dict, key: str) -> str:
    val = params.get(key)
    if not isinstance(val, str) or not val.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return val.strip()


@method("calendar.list_trading_days")
def calendar_list_trading_days(params: dict[str, Any]) -> dict[str, Any]:
    """Enumerate A-share trading days in [start, end] (inclusive on both).

    Params:
        start: str (YYYY-MM-DD)
        end:   str (YYYY-MM-DD)

    Returns:
        {"trading_days": ["YYYY-MM-DD", ...]}

    Empty list when start > end. Uses Tushare ``pro.trade_cal`` (SSE) under
    the hood with a Mon-Fri weekday fallback when Tushare unavailable —
    the fallback path is logged at WARNING in the bridge.
    """
    start = _require_str(params, "start")
    end = _require_str(params, "end")
    try:
        from datetime import datetime, timedelta

        from mosaic.dataflows.calendar import is_trading_day
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"calendar import failed: {exc}") from exc

    try:
        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, f"invalid date format (expected YYYY-MM-DD): {exc}") from exc

    if s > e:
        return {"trading_days": []}

    out: list[str] = []
    cur = s
    while cur <= e:
        try:
            if is_trading_day(cur.isoformat()):
                out.append(cur.isoformat())
        except Exception:
            # Hard-failure on a single date is unexpected; the helper
            # already falls back to Mon-Fri internally. Don't crash the
            # whole enumeration.
            pass
        cur += timedelta(days=1)
    return {"trading_days": out}


@method("calendar.is_trading_day")
def calendar_is_trading_day(params: dict[str, Any]) -> dict[str, Any]:
    """Return whether a single date is an A-share trading day."""
    date = _require_str(params, "date")
    try:
        from mosaic.dataflows.calendar import is_trading_day
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"calendar import failed: {exc}") from exc
    try:
        return {"is_trading": bool(is_trading_day(date))}
    except Exception as exc:
        raise RpcError(INVALID_PARAMS, f"{type(exc).__name__}: {exc}") from exc


@method("calendar.next_trading_day")
def calendar_next_trading_day(params: dict[str, Any]) -> dict[str, Any]:
    """Return ``date + n`` trading days (forward).

    ``n=0`` snaps to the next trading day if ``date`` is itself a holiday.
    Use negative ``n`` semantics not supported here; use a separate RPC
    if needed (mosaic.dataflows.calendar.previous_trading_day exists).
    """
    date = _require_str(params, "date")
    n = params.get("n", 1)
    if not isinstance(n, int) or n < 0:
        raise RpcError(INVALID_PARAMS, "'n' must be a non-negative integer")
    try:
        from mosaic.dataflows.calendar import next_trading_day
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"calendar import failed: {exc}") from exc
    try:
        return {"date": next_trading_day(date, n)}
    except Exception as exc:
        raise RpcError(INVALID_PARAMS, f"{type(exc).__name__}: {exc}") from exc
