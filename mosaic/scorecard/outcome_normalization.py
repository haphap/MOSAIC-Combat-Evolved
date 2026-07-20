"""Versioned point-in-time normalization authority for Darwinian labels."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS


_REPO_ROOT = Path(__file__).resolve().parents[2]
OUTCOME_NORMALIZATION_REGISTRY_PATH = (
    _REPO_ROOT
    / "registry"
    / "prompt_checks"
    / "outcome_normalization_registry_v1.json"
)
OUTCOME_NORMALIZATION_SCHEMA_PATH = (
    _REPO_ROOT / "schemas" / "outcome_normalization_registry_v1.schema.json"
)


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def load_outcome_normalization_registry(
    path: Path = OUTCOME_NORMALIZATION_REGISTRY_PATH,
    schema_path: Path = OUTCOME_NORMALIZATION_SCHEMA_PATH,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.absolute_path) or "$"
        raise RuntimeError(
            f"outcome normalization registry schema violation at {location}: "
            f"{first.message}"
        )
    supplied_hash = payload.get("registry_hash")
    body = {key: value for key, value in payload.items() if key != "registry_hash"}
    if supplied_hash != canonical_hash(body):
        raise RuntimeError("outcome normalization registry hash mismatch")

    expected_contracts = {
        str(contract["normalization_contract_version"])
        for contract in OUTCOME_CONTRACTS.values()
    }
    seen_keys: set[tuple[str, str]] = set()
    covered: set[str] = set()
    entries_by_contract: dict[str, list[dict[str, Any]]] = {}
    for index, entry in enumerate(payload["entries"]):
        contract_version = str(entry["normalization_contract_version"])
        effective_at = str(entry["effective_at"])
        key = (contract_version, effective_at)
        if key in seen_keys:
            raise RuntimeError("outcome normalization entries must be unique")
        seen_keys.add(key)
        covered.add(contract_version)
        entries_by_contract.setdefault(contract_version, []).append(dict(entry))
        effective = _timestamp(effective_at, f"entries[{index}].effective_at")
        scale = entry["scale"]
        if (
            isinstance(scale, bool)
            or not isinstance(scale, (int, float))
            or not math.isfinite(float(scale))
            or float(scale) <= 0
        ):
            raise RuntimeError("outcome normalization scale must be finite and positive")
        authority = entry["scale_authority"]
        sample_count = entry["calibration_sample_count"]
        window_end_raw = entry["calibration_window_end"]
        if authority == "PRE_REGISTERED_COLD_START_UNIT_SCALE":
            if sample_count != 0 or window_end_raw is not None or float(scale) != 1.0:
                raise RuntimeError("cold-start normalization entry semantics drift")
        else:
            if window_end_raw is None:
                raise RuntimeError("calibrated normalization entry lacks a PIT window")
            if sample_count < 30:
                raise RuntimeError(
                    "calibrated normalization entry requires at least 30 PIT samples"
                )
            if _timestamp(window_end_raw, "calibration_window_end") > effective:
                raise RuntimeError("normalization calibration window exceeds effective_at")
    if covered != expected_contracts:
        raise RuntimeError("outcome normalization registry contract coverage drift")
    for contract_version, entries in entries_by_contract.items():
        ordered = sorted(
            entries,
            key=lambda entry: _timestamp(entry["effective_at"], "effective_at"),
        )
        cold_starts = [
            entry
            for entry in ordered
            if entry["scale_authority"] == "PRE_REGISTERED_COLD_START_UNIT_SCALE"
        ]
        if len(cold_starts) != 1 or ordered[0] is not cold_starts[0]:
            raise RuntimeError(
                f"{contract_version} must begin with exactly one cold-start release"
            )
    return payload


def resolve_outcome_normalization_reference(
    agent_id: str,
    opportunity_as_of: str,
    *,
    registry_path: Path = OUTCOME_NORMALIZATION_REGISTRY_PATH,
    schema_path: Path = OUTCOME_NORMALIZATION_SCHEMA_PATH,
) -> dict[str, Any]:
    contract = OUTCOME_CONTRACTS.get(agent_id)
    if contract is None:
        raise ValueError(f"unknown outcome Agent {agent_id!r}")
    cutoff = _timestamp(opportunity_as_of, "opportunity_as_of")
    source = load_outcome_normalization_registry(registry_path, schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    contract_version = str(contract["normalization_contract_version"])
    candidates = [
        dict(entry)
        for entry in source.get("entries", [])
        if entry.get("normalization_contract_version") == contract_version
        and _timestamp(entry.get("effective_at"), "normalization effective_at") <= cutoff
    ]
    if not candidates:
        raise ValueError(
            f"no PIT normalization release for {agent_id} at {opportunity_as_of}"
        )
    candidates.sort(key=lambda entry: _timestamp(entry["effective_at"], "effective_at"))
    entry = candidates[-1]
    entry_hash = canonical_hash(entry)
    body = {
        "normalization_reference_id": (
            f"outcome-normalization:{contract_version}:{entry_hash.removeprefix('sha256:')}"
        ),
        "normalization_contract_version": contract_version,
        "normalization_registry_version": source["registry_version"],
        "normalization_registry_hash": source["registry_hash"],
        "normalization_registry_schema_hash": canonical_hash(schema),
        "normalization_entry_hash": entry_hash,
        "normalization_authority": entry["scale_authority"],
        "normalization_effective_at": entry["effective_at"],
        "cutoff": cutoff.isoformat(),
        "calibration_sample_count": entry["calibration_sample_count"],
        "calibration_window_end": entry["calibration_window_end"],
        "scale": float(entry["scale"]),
    }
    return {**body, "normalization_reference_hash": canonical_hash(body)}


__all__ = [
    "OUTCOME_NORMALIZATION_REGISTRY_PATH",
    "OUTCOME_NORMALIZATION_SCHEMA_PATH",
    "load_outcome_normalization_registry",
    "resolve_outcome_normalization_reference",
]
