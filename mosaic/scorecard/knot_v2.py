"""Read-only tombstone for the retired KNOT authority protocol."""

from __future__ import annotations

from typing import Any, NoReturn


def _legacy_protocol_disabled(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise RuntimeError("legacy_knot_protocol_read_only")


def private_knot_runtime_available() -> bool:
    return False


def __getattr__(name: str) -> Any:
    if name.startswith("_"):
        raise AttributeError(name)
    return _legacy_protocol_disabled
