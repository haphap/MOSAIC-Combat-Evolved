"""Private-cache inputs for pre-run outcome scheduling and opportunity freezing."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS


EVENT_COVERAGE_SCHEMA_VERSION = "verified_event_coverage_snapshot_v2"
OPPORTUNITY_PROJECTION_SCHEMA_VERSION = "evaluation_opportunity_projection_v2"
_FAILURE_CODES = {
    "CONTRACT_MISMATCH",
    "EMPTY_REQUIRED_OPPORTUNITY_SET",
    "PIT_UNVERIFIED",
    "REQUIRED_DATA_UNAVAILABLE",
    "SOURCE_COVERAGE_UNHEALTHY",
}


def outcome_runtime_cache_root() -> Path:
    explicit = os.getenv("MOSAIC_OUTCOME_RUNTIME_DIR")
    if explicit:
        return Path(explicit).expanduser()
    cache = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache / "outcome_runtime"


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _read_hashed(path: Path, schema_version: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required outcome runtime input is unavailable: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read outcome runtime input {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != schema_version:
        raise ValueError(f"outcome runtime input schema mismatch: {path}")
    supplied = payload.get("snapshot_hash")
    without_hash = {key: value for key, value in payload.items() if key != "snapshot_hash"}
    if supplied != canonical_hash(without_hash):
        raise ValueError(f"outcome runtime input hash mismatch: {path}")
    return payload


def load_verified_event_coverage(
    as_of: str,
    *,
    root: Path | None = None,
) -> dict[str, Mapping[str, Any]]:
    """Load a complete event-trigger coverage denominator; absence is not no-event."""
    runtime_root = root or outcome_runtime_cache_root()
    payload = _read_hashed(
        runtime_root / as_of[:10] / "event_coverage.json",
        EVENT_COVERAGE_SCHEMA_VERSION,
    )
    if (
        payload.get("as_of") != as_of
        or payload.get("pit_status") != "VERIFIED"
        or _timestamp(payload.get("generated_at"), "event coverage generated_at")
        > _timestamp(as_of, "as_of")
    ):
        raise ValueError("event coverage snapshot is not PIT-aligned to the run")
    event_agents = {
        agent_id
        for agent_id, contract in OUTCOME_CONTRACTS.items()
        if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
    }
    coverage = payload.get("event_coverage")
    if not isinstance(coverage, dict) or set(coverage) != event_agents:
        raise ValueError("event coverage must contain the exact event-triggered Agent roster")
    return coverage


def load_evaluation_opportunity_projection(
    as_of: str,
    agent_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Load one deterministic pre-run opportunity projection for a scheduled Agent."""
    if agent_id not in OUTCOME_CONTRACTS:
        raise ValueError(f"unknown outcome Agent {agent_id!r}")
    runtime_root = root or outcome_runtime_cache_root()
    payload = _read_hashed(
        runtime_root / as_of[:10] / "opportunities" / f"{agent_id}.json",
        OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
    )
    if (
        payload.get("agent_id") != agent_id
        or payload.get("as_of") != as_of
        or payload.get("pit_status") != "VERIFIED"
        or _timestamp(payload.get("generated_at"), "opportunity generated_at")
        > _timestamp(as_of, "as_of")
    ):
        raise ValueError("evaluation opportunity projection is not PIT-aligned")
    predicate = payload.get("qualification_predicate_version")
    if not isinstance(predicate, str) or not predicate:
        raise ValueError("evaluation opportunity projection lacks its predicate version")
    source_evidence = payload.get("source_evidence_by_required_source_id")
    required_sources = set(OUTCOME_CONTRACTS[agent_id]["required_source_ids"])
    if not isinstance(source_evidence, dict) or set(source_evidence) != required_sources:
        raise ValueError("opportunity source evidence does not cover required_source_ids")
    flattened: list[str] = []
    for source_id in sorted(required_sources):
        values = source_evidence[source_id]
        if not isinstance(values, list) or not values or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise ValueError(f"opportunity source {source_id} lacks evidence")
        flattened.extend(values)
    if len(flattened) != len(set(flattened)):
        raise ValueError("opportunity source evidence IDs must be globally unique")
    status = payload.get("projection_status")
    if status == "AVAILABLE":
        members = payload.get("member_refs")
        if not isinstance(members, list) or any(not isinstance(item, dict) for item in members):
            raise ValueError("AVAILABLE opportunity projection has invalid members")
        if payload.get("error_codes") not in (None, []):
            raise ValueError("AVAILABLE opportunity projection cannot carry error codes")
    elif status == "GENERATION_FAILURE":
        if payload.get("member_refs") not in (None, []):
            raise ValueError("failed opportunity projection cannot carry members")
        errors = payload.get("error_codes")
        if (
            not isinstance(errors, list)
            or not errors
            or any(error not in _FAILURE_CODES for error in errors)
        ):
            raise ValueError("failed opportunity projection has invalid error codes")
    else:
        raise ValueError("unknown evaluation opportunity projection status")
    return payload


__all__ = [
    "EVENT_COVERAGE_SCHEMA_VERSION",
    "OPPORTUNITY_PROJECTION_SCHEMA_VERSION",
    "load_evaluation_opportunity_projection",
    "load_verified_event_coverage",
    "outcome_runtime_cache_root",
]
