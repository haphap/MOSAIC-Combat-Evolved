"""``cache.*`` JSON-RPC handlers wrapping ``mosaic.cache_manager.CacheManager``.

Phase 0 Day 1 status: stubs registered; calls return ``CONFIG_ERROR`` until
``mosaic.cache_manager`` lands in Phase 0 Day 2.
"""

from __future__ import annotations

from typing import Any

from ..protocol import CONFIG_ERROR, INVALID_PARAMS, RpcError
from ..registry import method


_VALID_CATEGORIES = {"api", "agent_data", "signals", "snapshots", "checkpoints", "all"}


def _manager():
    # Imported lazily so importing the bridge doesn't import the cache layer.
    try:
        from mosaic.cache_manager import CacheManager
        from mosaic.dataflows.config import get_config
    except ImportError as exc:
        raise RpcError(
            CONFIG_ERROR,
            "mosaic.cache_manager / dataflows.config not yet available "
            "(Phase 0 Day 2).",
        ) from exc

    return CacheManager(get_config())


@method("cache.stats")
def cache_stats(_params: dict[str, Any]) -> dict[str, Any]:
    return _manager().stats()


@method("cache.cleanup")
def cache_cleanup(params: dict[str, Any]) -> dict[str, Any]:
    days = params.get("days")
    category = params.get("category", "all")
    if not isinstance(days, int) or days < 0:
        raise RpcError(INVALID_PARAMS, "'days' must be a non-negative integer")
    if category not in _VALID_CATEGORIES:
        raise RpcError(
            INVALID_PARAMS,
            f"'category' must be one of {sorted(_VALID_CATEGORIES)}",
        )
    return _manager().cleanup(days, category)


@method("cache.clear")
def cache_clear(params: dict[str, Any]) -> dict[str, Any]:
    category = params.get("category")
    if category not in _VALID_CATEGORIES:
        raise RpcError(
            INVALID_PARAMS,
            f"'category' must be one of {sorted(_VALID_CATEGORIES)}",
        )
    return _manager().clear(category)


@method("cache.details")
def cache_details(params: dict[str, Any]) -> dict[str, Any]:
    category = params.get("category")
    page = params.get("page", 1)
    page_size = params.get("page_size", 20)
    if category not in _VALID_CATEGORIES - {"all"}:
        raise RpcError(
            INVALID_PARAMS,
            "'category' must be one of api/agent_data/signals/snapshots/checkpoints",
        )
    if not isinstance(page, int) or page < 1:
        raise RpcError(INVALID_PARAMS, "'page' must be a positive integer")
    if not isinstance(page_size, int) or page_size < 1:
        raise RpcError(INVALID_PARAMS, "'page_size' must be a positive integer")
    return _manager().details(category, page=page, page_size=page_size)
