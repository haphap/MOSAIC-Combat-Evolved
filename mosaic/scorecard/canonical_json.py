"""Compatibility import for the shared cross-runtime JCS authority."""

from mosaic.dataflows.cross_runtime_json import (
    CANONICAL_JSON_CONTRACT_VERSION,
    canonical_hash,
    canonical_json,
)


__all__ = [
    "CANONICAL_JSON_CONTRACT_VERSION",
    "canonical_hash",
    "canonical_json",
]
