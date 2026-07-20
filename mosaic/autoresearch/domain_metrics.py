"""Fail-closed public adapter for private domain-knob metric calculators."""

from __future__ import annotations

from typing import Any

from .private_knot_runtime import load_private_knot_module


def _private_module():
    return load_private_knot_module("domain_metrics", "mosaic_knot.domain_metrics")


def __getattr__(name: str) -> Any:
    if name.startswith("_"):
        raise AttributeError(name)
    try:
        return getattr(_private_module(), name)
    except AttributeError as exc:
        raise AttributeError(name) from exc
