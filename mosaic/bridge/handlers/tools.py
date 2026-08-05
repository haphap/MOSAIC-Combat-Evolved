"""Capability-bound ``tools.*`` JSON-RPC handlers.

Only the runtime controller may prepare a bundle.  Model-visible ``tools.list``
and ``tools.call`` require the signed envelope and expose only zero-argument
role snapshots from that already-materialised bundle.  Raw vendor tools remain
ordinary Python helpers and are never registered on this RPC surface.
"""

from __future__ import annotations

import importlib
from typing import Any, Iterable

from langchain_core.tools import BaseTool

from mosaic.bridge.tool_capabilities import get_capability_store
from mosaic.dataflows.exceptions import DataVendorUnavailable

from ..protocol import (
    DATA_VENDOR_UNAVAILABLE,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    TOOL_EXECUTION_ERROR,
    RpcError,
)
from ..registry import method

# Kept as a non-RPC discovery helper for direct unit tests of legacy Python
# utilities.  The empty module registry is the security boundary: none of
# those arbitrary-query tools are model-callable through the bridge.
_TOOL_MODULES: tuple[str, ...] = ()
_SKIPPED_TOOL_MODULES: list[tuple[str, str]] = []


def _iter_module_tools(module_path: str) -> Iterable[BaseTool]:
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:  # pragma: no cover - diagnostic path
        _SKIPPED_TOOL_MODULES.append((module_path, repr(exc)))
        return ()
    found: list[BaseTool] = []
    seen_ids: set[int] = set()
    for value in vars(module).values():
        if isinstance(value, BaseTool) and id(value) not in seen_ids:
            seen_ids.add(id(value))
            found.append(value)
    return found


def _require_capability(params: dict[str, Any]) -> dict[str, Any]:
    capability = params.get("capability")
    if not isinstance(capability, dict):
        raise RpcError(INVALID_PARAMS, "a signed 'capability' object is required")
    return capability


@method("tools.prepare_capability")
def tools_prepare_capability(params: dict[str, Any]) -> dict[str, Any]:
    """Materialise a frozen bundle and issue its short-lived capability."""
    try:
        return get_capability_store().prepare(params)
    except DataVendorUnavailable as exc:
        raise RpcError(DATA_VENDOR_UNAVAILABLE, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except RpcError:
        raise
    except Exception as exc:
        raise RpcError(TOOL_EXECUTION_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("tools.list")
def tools_list(params: dict[str, Any]) -> list[dict[str, Any]]:
    """List only the zero-argument tools allowed by one signed capability."""
    capability = _require_capability(params)
    try:
        return get_capability_store().list_tools(capability)
    except (TypeError, ValueError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc


@method("tools.issue_capability")
def tools_issue_capability(params: dict[str, Any]) -> dict[str, Any]:
    """Issue a distinct node handle for an already-materialised root bundle."""
    try:
        return get_capability_store().issue_for_bundle(params)
    except (TypeError, ValueError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(TOOL_EXECUTION_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("tools.call")
def tools_call(params: dict[str, Any]) -> dict[str, Any]:
    """Return one immutable bundle payload; collectors are never called here."""
    capability = _require_capability(params)
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise RpcError(INVALID_PARAMS, "tools.call requires a non-empty 'name'")
    args = params.get("args", {})
    if not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, "'args' must be an object")
    try:
        return {"text": get_capability_store().call_tool(capability, name, args)}
    except ValueError as exc:
        message = str(exc)
        code = METHOD_NOT_FOUND if "not allowed by this capability" in message else INVALID_PARAMS
        raise RpcError(code, message) from exc
    except Exception as exc:
        raise RpcError(TOOL_EXECUTION_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("tools.terminate_capability")
def tools_terminate_capability(params: dict[str, Any]) -> dict[str, bool]:
    """Append a terminal event immediately after the bound node finishes."""
    capability = _require_capability(params)
    reason = params.get("reason", "node_finished")
    try:
        get_capability_store().terminate(capability, reason)
    except (TypeError, ValueError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    return {"terminated": True}


@method("tools.record_model_usage")
def tools_record_model_usage(params: dict[str, Any]) -> dict[str, Any]:
    """Append one provider-reported model subcall to the server-owned ledger."""
    if set(params) != {"capability", "usage_report"}:
        raise RpcError(
            INVALID_PARAMS,
            "tools.record_model_usage requires exactly capability and usage_report",
        )
    capability = _require_capability(params)
    usage_report = params.get("usage_report")
    if not isinstance(usage_report, dict):
        raise RpcError(INVALID_PARAMS, "'usage_report' must be an object")
    try:
        return get_capability_store().record_sector_model_usage(
            capability_envelope=capability,
            usage_report=usage_report,
        )
    except (TypeError, ValueError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(TOOL_EXECUTION_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("tools.finalize_model_usage")
def tools_finalize_model_usage(params: dict[str, Any]) -> dict[str, Any]:
    """Sign the server-derived raw usage summary before capability termination."""
    if set(params) != {"capability"}:
        raise RpcError(
            INVALID_PARAMS,
            "tools.finalize_model_usage requires exactly capability",
        )
    capability = _require_capability(params)
    try:
        return get_capability_store().finalize_sector_model_usage(
            capability_envelope=capability
        )
    except (TypeError, ValueError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(TOOL_EXECUTION_ERROR, f"{type(exc).__name__}: {exc}") from exc


__all__ = [
    "_SKIPPED_TOOL_MODULES",
    "_TOOL_MODULES",
    "_iter_module_tools",
    "tools_call",
    "tools_finalize_model_usage",
    "tools_issue_capability",
    "tools_list",
    "tools_prepare_capability",
    "tools_record_model_usage",
    "tools_terminate_capability",
]
