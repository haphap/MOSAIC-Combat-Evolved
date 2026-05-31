"""``data.*`` JSON-RPC handlers — qlib-data incremental update (Request #2).

Wraps ``mosaic.dataflows.qlib_ingest`` so the TS front-end can refresh the
local qlib datasets (cn_data / cn_etf) without dropping to a raw
``python -m mosaic.dataflows.qlib_ingest`` invocation.

Surface:
    * data.incremental(kind, end[, timeout]) → append latest trading days
    * data.validate(kind[, gap_threshold]) → quality report + skip manifest

The actual fetch runs the vendored collector in a child process and needs the
``ingest`` (+ ``data`` + ``backtest``) extras installed; absent deps surface as
DATA_ERROR rather than crashing the bridge.
"""

from __future__ import annotations

from typing import Any

from ..protocol import DATA_ERROR, INVALID_PARAMS, RpcError
from ..registry import method

_KINDS = ("stock", "etf")


def _require_kind(params: dict[str, Any]) -> str:
    kind = params.get("kind", "stock")
    if kind not in _KINDS:
        raise RpcError(INVALID_PARAMS, f"'kind' must be one of {_KINDS}, got {kind!r}")
    return kind


def _require_str(params: dict[str, Any], key: str) -> str:
    val = params.get(key)
    if not isinstance(val, str) or not val.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return val.strip()


@method("data.incremental")
def data_incremental(params: dict[str, Any]) -> dict[str, Any]:
    """Append the latest trading days to an existing qlib dataset.

    Params:
        kind: "stock" (cn_data) | "etf" (cn_etf), default "stock"
        end:  str (YYYY-MM-DD) — fetch through this date
        timeout: int seconds per request (optional, default 120)

    Returns ``{kind, returncode, qlib_dir, ok}``.
    """
    kind = _require_kind(params)
    end = _require_str(params, "end")
    timeout = params.get("timeout", 120)
    if not isinstance(timeout, int) or timeout < 1:
        raise RpcError(INVALID_PARAMS, "'timeout' must be a positive integer")

    try:
        from mosaic.dataflows.qlib_ingest import CollectorNotFound, ingest_incremental
    except ImportError as exc:
        raise RpcError(DATA_ERROR, f"qlib_ingest unavailable: {exc}") from exc

    try:
        outcome = ingest_incremental(
            end=end, kind=kind, timeout=timeout, stream_stdout=False
        )
    except CollectorNotFound as exc:
        raise RpcError(DATA_ERROR, str(exc)) from exc
    except FileNotFoundError as exc:
        raise RpcError(DATA_ERROR, str(exc)) from exc
    except Exception as exc:
        raise RpcError(DATA_ERROR, f"{type(exc).__name__}: {exc}") from exc

    return {
        "kind": kind,
        "returncode": outcome.returncode,
        "qlib_dir": str(outcome.qlib_dir) if outcome.qlib_dir else None,
        "ok": outcome.returncode == 0,
    }


@method("data.validate")
def data_validate(params: dict[str, Any]) -> dict[str, Any]:
    """Validate an ingested qlib dataset + (re)write the skip manifest.

    Params:
        kind: "stock" | "etf", default "stock"
        gap_threshold: float (optional, default 0.01)

    Returns the validation summary dict from ``validate_after_ingest``.
    """
    kind = _require_kind(params)
    gap_threshold = params.get("gap_threshold", 0.01)
    if not isinstance(gap_threshold, (int, float)) or isinstance(gap_threshold, bool):
        raise RpcError(INVALID_PARAMS, "'gap_threshold' must be numeric")

    try:
        from mosaic.dataflows.qlib_ingest import (
            DEFAULT_QLIB_DATA_DIR,
            DEFAULT_QLIB_ETF_DATA_DIR,
            validate_after_ingest,
        )
    except ImportError as exc:
        raise RpcError(DATA_ERROR, f"qlib_ingest unavailable: {exc}") from exc

    qlib_dir = DEFAULT_QLIB_ETF_DATA_DIR if kind == "etf" else DEFAULT_QLIB_DATA_DIR
    try:
        return validate_after_ingest(qlib_dir=qlib_dir, gap_threshold=float(gap_threshold))
    except FileNotFoundError as exc:
        raise RpcError(DATA_ERROR, str(exc)) from exc
    except Exception as exc:
        raise RpcError(DATA_ERROR, f"{type(exc).__name__}: {exc}") from exc
