"""Fail-closed public adapter for the private KNOT runtime."""

from __future__ import annotations

from typing import Any

from mosaic.autoresearch.private_knot_runtime import load_private_knot_module

_LEGACY_WRITE_NAMES = frozenset(
    {
        "append_knot_cio_dependency_blocked_audit",
        "append_knot_cio_proposal_ref",
        "append_knot_control_dependency_result",
        "append_knot_pair_side_execution_result",
        "append_knot_research_score_record",
        "append_knot_sector_inference_cost_audit",
        "finalize_knot_pair",
        "freeze_knot_pair_input",
        "preregister_knot_pair_assignment",
        "publish_knot_nomination_audit",
        "publish_knot_promotion_batch",
        "publish_knot_promotion_revision",
        "publish_knot_research_schedule",
        "publish_knot_rollback_revision",
        "register_knot_research_track",
    }
)


def _legacy_write_disabled(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("legacy_knot_protocol_read_only")


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
    if name in _LEGACY_WRITE_NAMES:
        return _legacy_write_disabled
    try:
        return getattr(_private_module(), name)
    except AttributeError as exc:
        raise AttributeError(name) from exc
