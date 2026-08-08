"""Receipts for PR6 staged adaptive-query source materialization.

These receipts deliberately remain separate from the active route ledger until
the PR12 atomic activation gate.  They bind an exact request and captured
content hash to a point-in-time eligible source route without publishing query
arguments or source prose.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from mosaic.scorecard.canonical_json import canonical_hash


SCHEMA_VERSION = "staged_query_source_receipt_v1"
_SHA_PREFIX = "sha256:"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PIT_MODES = {
    "AUTHORITATIVE_VINTAGE_REPLAY",
    "DERIVED_FROM_PIT_ARCHIVE",
    "OBSERVED_LIVE",
}
_DESCRIPTOR_FIELDS = {
    "tool_id",
    "route_id",
    "as_of",
    "request_hash",
    "content_hash",
    "pit_mode",
}
_RECEIPT_FIELDS = {
    "schema_version",
    *_DESCRIPTOR_FIELDS,
    "knowledge_available_at",
    "captured_at",
    "eligible",
    "blocker_codes",
    "receipt_hash",
}


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _required_sha256(value: Any, field: str) -> str:
    text = _required_text(value, field)
    if (
        not text.startswith(_SHA_PREFIX)
        or len(text) != 71
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise ValueError(f"{field} must be a sha256 identifier")
    return text


def _timestamp(value: Any, field: str) -> datetime:
    text = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _validated_descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _DESCRIPTOR_FIELDS:
        raise ValueError("staged source descriptor fields do not match the contract")
    as_of = _required_text(value["as_of"], "as_of")
    date.fromisoformat(as_of)
    pit_mode = _required_text(value["pit_mode"], "pit_mode")
    if pit_mode not in _PIT_MODES:
        raise ValueError("unsupported staged source receipt pit_mode")
    return {
        "tool_id": _required_text(value["tool_id"], "tool_id"),
        "route_id": _required_text(value["route_id"], "route_id"),
        "as_of": as_of,
        "request_hash": _required_sha256(value["request_hash"], "request_hash"),
        "content_hash": _required_sha256(value["content_hash"], "content_hash"),
        "pit_mode": pit_mode,
    }


def seal_staged_query_source_receipt(
    descriptor: Mapping[str, Any],
    *,
    knowledge_available_at: str,
    captured_at: str,
    blocker_codes: Sequence[str] = (),
) -> dict[str, Any]:
    """Seal a staged receipt after a trusted collector captures real content."""

    body_descriptor = _validated_descriptor(descriptor)
    knowledge = _timestamp(knowledge_available_at, "knowledge_available_at")
    captured = _timestamp(captured_at, "captured_at")
    blockers = list(blocker_codes)
    if (
        any(not isinstance(code, str) or not code for code in blockers)
        or blockers != sorted(set(blockers))
    ):
        raise ValueError("blocker_codes must be sorted, unique non-empty strings")
    body = {
        "schema_version": SCHEMA_VERSION,
        **body_descriptor,
        "knowledge_available_at": knowledge.isoformat(),
        "captured_at": captured.isoformat(),
        "eligible": not blockers,
        "blocker_codes": blockers,
    }
    receipt = {**body, "receipt_hash": canonical_hash(body)}
    validate_staged_query_source_receipt(
        receipt,
        expected_descriptor=body_descriptor,
        require_eligible=False,
    )
    return receipt


def validate_staged_query_source_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_descriptor: Mapping[str, Any],
    require_eligible: bool = True,
) -> str:
    """Validate hash, PIT cutoff and exact request/content descriptor binding."""

    if not isinstance(receipt, Mapping) or set(receipt) != _RECEIPT_FIELDS:
        raise ValueError("staged source receipt fields do not match the contract")
    expected = _validated_descriptor(expected_descriptor)
    actual_descriptor = {field: receipt[field] for field in _DESCRIPTOR_FIELDS}
    if _validated_descriptor(actual_descriptor) != expected:
        raise ValueError("staged source receipt descriptor mismatch")
    if receipt["schema_version"] != SCHEMA_VERSION:
        raise ValueError("staged source receipt schema_version mismatch")
    blockers = receipt["blocker_codes"]
    if (
        not isinstance(blockers, list)
        or any(not isinstance(code, str) or not code for code in blockers)
        or blockers != sorted(set(blockers))
    ):
        raise ValueError("staged source receipt blocker_codes are invalid")
    eligible = receipt["eligible"]
    if not isinstance(eligible, bool) or eligible != (not blockers):
        raise ValueError("staged source receipt eligibility contradicts blocker_codes")
    body = {key: receipt[key] for key in receipt if key != "receipt_hash"}
    receipt_hash = _required_sha256(receipt["receipt_hash"], "receipt_hash")
    if receipt_hash != canonical_hash(body):
        raise ValueError("staged source receipt hash mismatch")

    knowledge = _timestamp(receipt["knowledge_available_at"], "knowledge_available_at")
    captured = _timestamp(receipt["captured_at"], "captured_at")
    if captured < knowledge:
        raise ValueError("staged source receipt capture precedes knowledge availability")
    if expected["pit_mode"] == "OBSERVED_LIVE" and captured != knowledge:
        raise ValueError(
            "staged source receipt OBSERVED_LIVE capture time must equal "
            "knowledge_available_at"
        )
    as_of_end = datetime.combine(
        date.fromisoformat(expected["as_of"]), time.max, tzinfo=_SHANGHAI
    )
    if knowledge > as_of_end:
        raise ValueError("staged source receipt knowledge is after query as_of")
    if require_eligible and not eligible:
        raise ValueError("staged source receipt is not PIT eligible")
    return receipt_hash


__all__ = [
    "SCHEMA_VERSION",
    "seal_staged_query_source_receipt",
    "validate_staged_query_source_receipt",
]
