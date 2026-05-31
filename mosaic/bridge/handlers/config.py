"""``config.*`` JSON-RPC handlers.

Wraps ``mosaic.dataflows.config`` so the TS side can read ``DEFAULT_CONFIG``
once at startup and push back any merged overrides before issuing tool calls.

Phase 0 Day 1 status:
  * ``config.default`` works — pulls from ``mosaic.default_config``.
  * ``config.get`` / ``config.set`` raise ``CONFIG_ERROR`` until
    ``mosaic.dataflows.config`` lands in Phase 0 Day 2.
"""

from __future__ import annotations

import copy
from typing import Any

from ..protocol import CONFIG_ERROR, INVALID_PARAMS, RpcError
from ..registry import method


@method("config.default")
def config_default(_params: dict[str, Any]) -> dict[str, Any]:
    """Return ``mosaic.default_config.DEFAULT_CONFIG`` (deep-copied)."""
    from mosaic.default_config import DEFAULT_CONFIG

    return copy.deepcopy(DEFAULT_CONFIG)


@method("config.get")
def config_get(_params: dict[str, Any]) -> dict[str, Any]:
    """Return the active runtime config for this bridge process."""
    try:
        from mosaic.dataflows.config import get_config
    except ImportError as exc:
        raise RpcError(
            CONFIG_ERROR,
            "mosaic.dataflows.config not yet available "
            "(Phase 0 Day 2). Use config.default for now.",
        ) from exc

    return get_config()


@method("config.set")
def config_set(params: dict[str, Any]) -> dict[str, Any]:
    """Replace the active runtime config. Shape::

        { "config": { ... } }

    Returns the new active config (post-merge with defaults).
    """
    cfg = params.get("config")
    if cfg is None:
        raise RpcError(INVALID_PARAMS, "config.set requires a 'config' object")
    if not isinstance(cfg, dict):
        raise RpcError(INVALID_PARAMS, "'config' must be an object")

    try:
        from mosaic.dataflows.config import get_config, set_config
    except ImportError as exc:
        raise RpcError(
            CONFIG_ERROR,
            "mosaic.dataflows.config not yet available "
            "(Phase 0 Day 2). Use config.default for now.",
        ) from exc

    try:
        set_config(cfg)
    except Exception as exc:
        raise RpcError(CONFIG_ERROR, f"{type(exc).__name__}: {exc}") from exc
    return get_config()


@method("config.save")
def config_save(params: dict[str, Any]) -> dict[str, Any]:
    """Persist config to ~/.mosaic/config.json + apply it. Shape::

        { "config": { ... } }

    Returns the new active config. Unlike config.set (process-only), this
    survives restarts and is loaded by every sidecar at startup.
    """
    cfg = params.get("config")
    if cfg is None:
        raise RpcError(INVALID_PARAMS, "config.save requires a 'config' object")
    if not isinstance(cfg, dict):
        raise RpcError(INVALID_PARAMS, "'config' must be an object")

    try:
        from mosaic.dataflows.config import save_config
    except ImportError as exc:
        raise RpcError(
            CONFIG_ERROR,
            "mosaic.dataflows.config not yet available (Phase 0 Day 2).",
        ) from exc

    try:
        return save_config(cfg)
    except Exception as exc:
        raise RpcError(CONFIG_ERROR, f"{type(exc).__name__}: {exc}") from exc
