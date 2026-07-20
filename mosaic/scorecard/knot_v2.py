"""Fail-closed public adapter for the private KNOT runtime."""

from __future__ import annotations

from typing import Any

from mosaic.autoresearch.private_knot_runtime import load_private_knot_module


def _private_module():
    return load_private_knot_module("knot_engine", "mosaic_knot.knot_v2")


def private_knot_runtime_available() -> bool:
    try:
        _private_module()
    except RuntimeError:
        return False
    return True


def __getattr__(name: str) -> Any:
    if name.startswith("_"):
        raise AttributeError(name)
    try:
        return getattr(_private_module(), name)
    except AttributeError as exc:
        raise AttributeError(name) from exc
