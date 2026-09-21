"""RKE research-context JSON-RPC handlers."""

from __future__ import annotations

from typing import Any

from mosaic.rke.agent_research_context import build_rke_agent_research_context

from ..protocol import INVALID_PARAMS, RpcError
from ..registry import method


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return value.strip()


def _optional_str(params: dict[str, Any], key: str, default: str = "") -> str:
    value = params.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a string")
    return value.strip()


def _positive_int(params: dict[str, Any], key: str, default: int) -> int:
    value = params.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a positive integer")
    return value


@method("rke.agentResearchContext")
def rke_agent_research_context(params: dict[str, Any]) -> dict[str, Any]:
    """Return redacted ranked RKE research context for one downstream agent."""
    return build_rke_agent_research_context(
        root=_optional_str(params, "root", "."),
        registry_dir=_optional_str(params, "registry_dir"),
        agent_id=_require_str(params, "agent_id"),
        as_of_date=_optional_str(params, "as_of_date"),
        layer=_optional_str(params, "layer"),
        ticker=_optional_str(params, "ticker"),
        sector=_optional_str(params, "sector"),
        max_items=_positive_int(params, "max_items", 12),
    )
