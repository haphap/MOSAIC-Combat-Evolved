"""Tombstone for the pre-KNOT Delta-Sharpe prompt promoter.

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
    """Reject every direct promotion attempt; production promotion is KNOT-only."""
    del store, git_ops, version, config
    raise RuntimeError(
        "legacy Delta-Sharpe promotion is disabled; use a KNOT promotion batch"
    )


__all__ = ["decide"]
