"""Tombstone for the legacy Delta-Sharpe prompt promoter.

The production promotion edge was removed in v2. Historical replay uses the
explicit isolated-sandbox RPC and does not call this module.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


def decide(
    store: Any,
    git_ops: Any,
    version: dict[str, Any],
    config: Optional[Mapping[str, Any]] = None,
) -> str:
    """Reject direct promotion; production changes use Prompt Release."""
    del store, git_ops, version, config
    raise RuntimeError(
        "legacy Delta-Sharpe promotion is disabled; use Prompt Release"
    )


__all__ = ["decide"]
