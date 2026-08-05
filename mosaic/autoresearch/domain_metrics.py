"""Read-only tombstone for the retired domain-knob metric protocol."""

from __future__ import annotations

from typing import Any, NoReturn


def _retired(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise RuntimeError("legacy_knot_protocol_read_only")


def __getattr__(name: str) -> Any:
    if name.startswith("_"):
        raise AttributeError(name)
    return _retired
