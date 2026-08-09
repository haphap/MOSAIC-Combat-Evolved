"""Closed server-side router for prepare-time archive query readers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class TrustedArchiveQueryRouter:
    """Dispatch only to an explicitly registered archive reader; never fall back live."""

    def __init__(self, owners: Mapping[str, Callable[..., str]]) -> None:
        if not owners or any(not method or not callable(owner) for method, owner in owners.items()):
            raise ValueError("trusted archive query owners are invalid")
        self.owners = dict(owners)

    def __call__(self, method: str, *args: Any) -> str:
        owner = self.owners.get(method)
        if owner is None:
            raise ValueError(f"no trusted archive owns route method {method}")
        return owner(method, *args)


__all__ = ["TrustedArchiveQueryRouter"]
