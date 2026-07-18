"""Controller-only runtime data adapters.

These methods are not LangChain/model tools.  The graph controller supplies a
frozen candidate ticker and PIT cutoff while constructing a stage snapshot.
"""

from __future__ import annotations

from typing import Any

from mosaic.agents.utils.technical_tools import get_stock_data
from mosaic.dataflows.config import backtest_context

from ..protocol import INVALID_PARAMS, TOOL_EXECUTION_ERROR, RpcError
from ..registry import method


def _required_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return value.strip()


@method("runtime_data.stock_market_snapshot")
def runtime_stock_market_snapshot(params: dict[str, Any]) -> dict[str, str]:
    """Fetch one controller-selected ticker for pre-stage snapshot freezing."""
    ticker = _required_str(params, "ticker")
    start_date = _required_str(params, "start_date")
    as_of_date = _required_str(params, "as_of_date")
    mode = params.get("mode", "live")
    if mode not in ("live", "backtest"):
        raise RpcError(INVALID_PARAMS, "'mode' must be live or backtest")
    try:
        with backtest_context(as_of_date, mode=mode):
            text = get_stock_data.invoke(
                {"symbol": ticker, "start_date": start_date, "end_date": as_of_date}
            )
    except Exception as exc:
        raise RpcError(TOOL_EXECUTION_ERROR, f"{type(exc).__name__}: {exc}") from exc
    return {"text": text if isinstance(text, str) else str(text)}


__all__ = ["runtime_stock_market_snapshot"]
