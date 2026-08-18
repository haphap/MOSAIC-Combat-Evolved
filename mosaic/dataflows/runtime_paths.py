"""Context-local runtime path isolation for non-production materialization."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator


_RUNTIME_ROOT_OVERRIDE: ContextVar[Path | None] = ContextVar(
    "agent_runtime_root_override",
    default=None,
)


def isolated_agent_runtime_path(relative_path: str | Path) -> Path | None:
    """Return an isolated path when the current context has an override."""
    root = _RUNTIME_ROOT_OVERRIDE.get()
    return None if root is None else root / relative_path


def agent_cache_root() -> Path:
    """Resolve the active cache root without mutating process environment."""
    isolated = _RUNTIME_ROOT_OVERRIDE.get()
    if isolated is not None:
        return isolated
    return Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()


@contextmanager
def agent_runtime_root_override(root: Path) -> Iterator[None]:
    """Isolate runtime writes for the current task or thread context."""
    token = _RUNTIME_ROOT_OVERRIDE.set(root.expanduser())
    try:
        yield
    finally:
        _RUNTIME_ROOT_OVERRIDE.reset(token)


__all__ = [
    "agent_cache_root",
    "agent_runtime_root_override",
    "isolated_agent_runtime_path",
]
