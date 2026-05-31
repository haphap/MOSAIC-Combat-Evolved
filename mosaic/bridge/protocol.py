"""JSON-RPC 2.0 protocol types used by the MOSAIC sidecar.

Wire format: newline-delimited JSON. One JSON value per line, both directions.
Stdout is the protocol channel — the server never writes anything else there.
All logging and stack traces go to stderr.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Standard JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Server-defined codes (-32000 .. -32099 reserved for implementation-defined)
TOOL_EXECUTION_ERROR = -32001  # underlying @tool / dataflow raised
BACKTEST_REJECTED = -32002     # _apply_backtest_date_bounds blocked the call
DATA_VENDOR_UNAVAILABLE = -32003
CONFIG_ERROR = -32010
PAPER_ERROR = -32020
BACKTEST_ERROR = -32030
# MOSAIC-specific extensions (Phase 3+ scorecard, Phase 4 autoresearch, Phase 5 PRISM, Phase 6 JANUS, Phase 7 MiroFish)
SCORECARD_ERROR = -32040
AUTORESEARCH_ERROR = -32050
PRISM_ERROR = -32060
JANUS_ERROR = -32070
MIROFISH_ERROR = -32080
DATA_ERROR = -32090


@dataclass(frozen=True)
class RpcError(Exception):
    """Raised by handlers to signal a JSON-RPC error response.

    The server catches this and emits a well-formed ``{"error": ...}`` envelope.
    Any other exception becomes ``INTERNAL_ERROR`` with the traceback in
    ``error.data`` (and is logged to stderr).
    """

    code: int
    message: str
    data: Any = None

    def __str__(self) -> str:
        return f"RpcError({self.code}): {self.message}"


def make_error_payload(code: int, message: str, data: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": int(code), "message": str(message)}
    if data is not None:
        payload["data"] = data
    return payload
