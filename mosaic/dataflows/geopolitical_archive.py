"""Trusted geopolitical archive projection into Agent materialization receipts."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .agent_materialization import (
    AgentDataMaterializationLedger,
    RouteCoverageReceipt,
    SnapshotBuildReceipt,
    SourceCaptureReceipt,
    load_agent_data_route_manifest,
)
from .cross_runtime_json import canonical_hash, canonical_json
from .exceptions import DataVendorUnavailable
from .geopolitical_events import (
    GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
    REQUIRED_SOURCE_IDS,
    ROLE_SNAPSHOT_SCHEMA_VERSION,
    GeopoliticalEventStore,
    build_geopolitical_role_snapshot,
    promote_geopolitical_manifest,
)

GEOPOLITICAL_LOGICAL_ROUTE_ID = "geopolitical.required_coverage"
GEOPOLITICAL_TOOL_ID = "get_geopolitical_events_snapshot"
GEOPOLITICAL_COMPILER_VERSION = "geopolitical_agent_compiler_v1"
_CALENDAR_ROUTE_IDS = (
    "tushare.eco_cal.cny",
    "tushare.eco_cal.eur",
    "tushare.eco_cal.usd",
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class GeopoliticalMaterializationResult:
    source_receipt: SourceCaptureReceipt | None
    coverage_receipt: RouteCoverageReceipt
    build_receipt: SnapshotBuildReceipt
    snapshot: dict[str, Any] | None


def _as_of_cutoff(as_of_date: str) -> datetime:
    local = date.fromisoformat(as_of_date)
    return datetime.combine(local, time(15, 0), tzinfo=_SHANGHAI).astimezone(
        timezone.utc
    )


def _required_routes() -> list[str]:
    matches = [
        row["required_route_ids"]
        for row in load_agent_data_route_manifest()["bindings"]
        if row["agent_id"] == "geopolitical"
        and row["stage"] == "geopolitical"
        and row["tool_id"] == GEOPOLITICAL_TOOL_ID
    ]
    if len(matches) != 1:
        raise RuntimeError("missing exact geopolitical materialization binding")
    return list(matches[0])


def _coverage_receipt(
    *,
    as_of_date: str,
    cutoff: datetime,
    source_receipt: SourceCaptureReceipt | None,
    blocker_codes: Sequence[str] = (),
    window_start: datetime | None = None,
) -> RouteCoverageReceipt:
    if source_receipt is None:
        status = "CAPTURE_REJECTED"
        capture_hash = None
        blockers = sorted(set(blocker_codes or ("INCOMPLETE_COVERAGE",)))
    else:
        source = source_receipt.as_dict()
        status = (
            "TRUE_EMPTY"
            if source["content"]["normalized_row_count"] == 0
            else "SUCCESS"
        )
        capture_hash = source_receipt.receipt_hash
        blockers = []
    core = {
        "as_of_date": as_of_date,
        "cutoff": cutoff.isoformat(),
        "capture_receipt_hash": capture_hash,
        "status": status,
        "blocker_codes": blockers,
    }
    return RouteCoverageReceipt.seal(
        {
            "schema_version": "route_coverage_receipt_v1",
            "coverage_id": (
                "geopolitical-coverage:"
                + canonical_hash(core).removeprefix("sha256:")
            ),
            "window": {
                "start": (window_start or cutoff).isoformat(),
                "end": cutoff.isoformat(),
                "timezone": "UTC",
            },
            "required_route_ids": [GEOPOLITICAL_LOGICAL_ROUTE_ID],
            "route_results": [
                {
                    "route_id": GEOPOLITICAL_LOGICAL_ROUTE_ID,
                    "capture_receipt_hash": capture_hash,
                    "status": status,
                }
            ],
            "coverage_complete": source_receipt is not None,
            "blocker_codes": blockers,
        }
    )


def _aggregate_source_receipt(
    *,
    as_of_date: str,
    cutoff: datetime,
    snapshot: Mapping[str, Any],
    store: GeopoliticalEventStore,
    source_capture_ids: Sequence[str] | None = None,
    license_decisions: Mapping[str, Mapping[str, Any]] | None = None,
) -> SourceCaptureReceipt:
    direct = source_capture_ids is not None
    if direct:
        capture_ids = set(source_capture_ids or ())
        if len(capture_ids) != len(REQUIRED_SOURCE_IDS):
            raise DataVendorUnavailable(
                "geopolitical aggregate capture lacks exact source closure"
            )
        captures = {
            capture_id: store.source_capture(capture_id) for capture_id in capture_ids
        }
        if {
            str(row["source_id"]) for row in captures.values()
        } != set(REQUIRED_SOURCE_IDS) or any(
            row["parse_result"] != "SUCCESS" for row in captures.values()
        ):
            raise DataVendorUnavailable(
                "geopolitical aggregate capture has failed source lineage"
            )
        if not isinstance(license_decisions, Mapping) or set(
            license_decisions
        ) != set(REQUIRED_SOURCE_IDS):
            raise DataVendorUnavailable(
                "geopolitical aggregate capture lacks exact license lineage"
            )
        receipt_rows: list[dict[str, Any]] = []
        window_end = max(
            datetime.fromisoformat(row["poll_completed_at"])
            for row in captures.values()
        )
        window_start = window_end
    else:
        receipts = store.latest_continuous_preflight_receipts(cutoff)
        if set(receipts) != set(REQUIRED_SOURCE_IDS):
            raise DataVendorUnavailable(
                "geopolitical aggregate capture lacks all required source receipts"
            )
        receipt_rows = [receipts[source_id] for source_id in sorted(receipts)]
        capture_ids = {
            capture_id
            for receipt in receipt_rows
            for capture_id in receipt["slot_capture_ids"]
        }
        captures = {
            row["source_capture_id"]: row
            for row in store.source_captures_as_of(cutoff)
            if row["source_capture_id"] in capture_ids
        }
        if set(captures) != capture_ids:
            raise DataVendorUnavailable(
                "geopolitical aggregate capture has missing source archive lineage"
            )
        window_start = min(
            datetime.fromisoformat(row["window_started_at"]) for row in receipt_rows
        )
        window_end = max(
            datetime.fromisoformat(row["window_completed_at"]) for row in receipt_rows
        )
        if window_end > cutoff:
            raise DataVendorUnavailable(
                "geopolitical aggregate capture exceeds the decision cutoff"
            )
    publication_count = sum(
        int(captures[capture_id]["publication_count"])
        for capture_id in sorted(captures)
    )
    page_count = sum(
        int(captures[capture_id]["page_count"])
        for capture_id in sorted(captures)
    )
    raw_hash = canonical_hash(
        {
            "preflight_receipt_hashes": [
                row["receipt_hash"] for row in receipt_rows
            ],
            "source_capture_hashes": [
                captures[capture_id]["capture_hash"]
                for capture_id in sorted(captures)
            ],
            "license_decision_hashes": [
                license_decisions[source_id]["decision_hash"]
                for source_id in sorted(REQUIRED_SOURCE_IDS)
            ]
            if direct
            else [],
            "snapshot_hash": snapshot["snapshot_hash"],
        }
    )
    request_hash = canonical_hash(
        {
            "route_id": GEOPOLITICAL_LOGICAL_ROUTE_ID,
            "as_of_date": as_of_date,
            "cutoff": cutoff.isoformat(),
            "preflight_receipt_hashes": [
                row["receipt_hash"] for row in receipt_rows
            ],
            "source_capture_ids": sorted(captures),
            "license_decision_ids": [
                license_decisions[source_id]["decision_id"]
                for source_id in sorted(REQUIRED_SOURCE_IDS)
            ]
            if direct
            else [],
            "license_decision_hashes": [
                license_decisions[source_id]["decision_hash"]
                for source_id in sorted(REQUIRED_SOURCE_IDS)
            ]
            if direct
            else [],
        }
    )
    captured_at = window_end.isoformat()
    published_dates = [
        str(event["published_at"])[:10]
        for event in snapshot.get("events", ())
        if event.get("published_at") is not None
    ]
    observed_start = min(published_dates) if published_dates else None
    observed_end = max(published_dates) if published_dates else None
    return SourceCaptureReceipt.seal(
        {
            "schema_version": "source_capture_receipt_v1",
            "identity": {
                "source_family": "geopolitical",
                "route_id": GEOPOLITICAL_LOGICAL_ROUTE_ID,
                "request_hash": request_hash,
                "capture_id": (
                    "geopolitical-agent:"
                    + request_hash.removeprefix("sha256:")
                ),
            },
            "transport": {
                "redacted_url": "https://official-geopolitical-source.invalid/<allowlisted-source>",
                "method": "GET",
                "query_keys": ["source_id"],
                "pagination_policy": "source-specific-terminal-v1",
                "page_count": page_count,
            },
            "authority": {
                "provider": "geopolitical",
                "permission_tier": "public-license-verified",
                "api_version": "source-manifest-v2",
                "parser_version": GEOPOLITICAL_COMPILER_VERSION,
            },
            "time": {
                "released_at": captured_at,
                "vintage_at": captured_at,
                "captured_at": captured_at,
                "knowledge_available_at": captured_at,
            },
            "pit": {
                "pit_mode": "OBSERVED_LIVE",
                "as_of_cutoff": captured_at,
                "eligible": True,
                "blocker_codes": [],
                "vintage_query": None,
            },
            "content": {
                "raw_content_hash": raw_hash,
                "normalized_row_count": publication_count,
                "schema_hash": canonical_hash(
                    {
                        "compiler_version": GEOPOLITICAL_COMPILER_VERSION,
                        "role_snapshot_schema": ROLE_SNAPSHOT_SCHEMA_VERSION,
                    }
                ),
            },
            "coverage": {
                "requested_start": (
                    as_of_date if direct else window_start.date().isoformat()
                ),
                "requested_end": as_of_date,
                "observed_start": observed_start,
                "observed_end": observed_end,
                "dimensions": {
                    "source_id": sorted(REQUIRED_SOURCE_IDS),
                    "source_capture_id": sorted(captures),
                    **(
                        {
                            "license_decision_id": sorted(
                                license_decisions[source_id]["decision_id"]
                                for source_id in sorted(REQUIRED_SOURCE_IDS)
                            ),
                            "license_decision_hash": sorted(
                                license_decisions[source_id]["decision_hash"]
                                for source_id in sorted(REQUIRED_SOURCE_IDS)
                            ),
                        }
                        if direct
                        else {
                            "preflight_receipt_id": sorted(
                                row["receipt_id"] for row in receipt_rows
                            )
                        }
                    ),
                },
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": 0,
                "empty_result_semantics": (
                    "NON_EMPTY" if publication_count else "TRUE_EMPTY"
                ),
            },
            "provenance": {
                "parent_capture_hash": None,
                "previous_revision_hash": None,
                "revision_reason": None,
            },
        }
    )


def _build_receipt(
    *,
    as_of_date: str,
    cutoff: datetime,
    source_hashes: Sequence[str],
    snapshot: Mapping[str, Any] | None,
    missing_routes: Sequence[str],
    blocker_codes: Sequence[str],
) -> SnapshotBuildReceipt:
    required = _required_routes()
    missing = sorted(set(missing_routes))
    blockers = sorted(set(blocker_codes))
    output_hash = str(snapshot["snapshot_hash"]) if snapshot is not None else None
    identity = {
        "as_of_date": as_of_date,
        "source_hashes": sorted(set(source_hashes)),
        "output_hash": output_hash,
        "missing_routes": missing,
        "blocker_codes": blockers,
    }
    now = datetime.now(timezone.utc).isoformat()
    return SnapshotBuildReceipt.seal(
        {
            "schema_version": "snapshot_build_receipt_v1",
            "build_id": (
                "geopolitical-agent-build:"
                + canonical_hash(identity).removeprefix("sha256:")
            ),
            "agent_id": "geopolitical",
            "stage": "geopolitical",
            "tool_id": GEOPOLITICAL_TOOL_ID,
            "as_of": as_of_date,
            "as_of_cutoff": cutoff.isoformat(),
            "source_receipt_hashes": sorted(set(source_hashes)),
            "compiler_version": GEOPOLITICAL_COMPILER_VERSION,
            "output_contract_version": ROLE_SNAPSHOT_SCHEMA_VERSION,
            "output_path": f"geopolitical_agent_snapshots/{as_of_date}/geopolitical.json",
            "output_hash": output_hash,
            "pit_mode": "MIXED_AUTHORITY",
            "earliest_trustworthy_date": as_of_date if snapshot is not None else None,
            "required_route_ids": required,
            "missing_route_ids": missing,
            "terminal_state": "READY" if snapshot is not None else "BLOCKED",
            "blocker_codes": blockers,
            "build_started_at": now,
            "build_finished_at": now,
        }
    )


def _available_calendar_hashes(
    ledger: AgentDataMaterializationLedger, *, as_of_date: str
) -> tuple[list[str], list[str]]:
    hashes: list[str] = []
    missing: list[str] = []
    for route_id in _CALENDAR_ROUTE_IDS:
        status = ledger.source_status(as_of=as_of_date, route_id=route_id)
        if status["status"] == "READY" and status["capture_receipt_hash"]:
            hashes.append(str(status["capture_receipt_hash"]))
        else:
            missing.append(route_id)
    return hashes, missing


def _write_snapshot(
    output_root: Path, *, as_of_date: str, snapshot: Mapping[str, Any]
) -> None:
    destination = output_root / as_of_date / "geopolitical.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (canonical_json(dict(snapshot)) + "\n").encode()
    if destination.exists():
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataVendorUnavailable(
                "existing geopolitical agent snapshot is unreadable"
            ) from exc
        if existing != dict(snapshot):
            raise DataVendorUnavailable(
                "refusing to replace a different geopolitical agent snapshot"
            )
        return
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, destination)


def materialize_geopolitical_snapshot(
    *,
    as_of_date: str,
    event_store: GeopoliticalEventStore,
    ledger: AgentDataMaterializationLedger,
    manifest: Mapping[str, Any] | None = None,
    output_root: Path,
    capture_group: Mapping[str, Any] | None = None,
    license_decisions: Mapping[str, Mapping[str, Any]] | None = None,
) -> GeopoliticalMaterializationResult:
    """Publish the logical route and build receipt without performing transport."""
    cutoff = _as_of_cutoff(as_of_date)
    base = manifest or GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    direct = capture_group is not None
    runtime_manifest = base
    capture_ids: tuple[str, ...] | None = None
    capture_cutoff = cutoff
    source_receipt: SourceCaptureReceipt | None = None
    snapshot: dict[str, Any] | None = None
    if direct:
        source_results = capture_group.get("source_results")
        if isinstance(source_results, list):
            successful = [
                row
                for row in source_results
                if isinstance(row, Mapping) and row.get("status") == "SUCCESS"
            ]
            source_ids = [str(row["source_id"]) for row in successful]
            ids = [str(row["source_capture_id"]) for row in successful]
            if (
                len(successful) == len(REQUIRED_SOURCE_IDS)
                and set(source_ids) == set(REQUIRED_SOURCE_IDS)
                and len(ids) == len(set(ids))
            ):
                capture_ids = tuple(ids)
                capture_cutoff = max(
                    datetime.fromisoformat(
                        event_store.source_capture(capture_id)["poll_completed_at"]
                    )
                    for capture_id in capture_ids
                )
    else:
        trusted_receipts = event_store.latest_continuous_preflight_receipts(cutoff)
        runtime_manifest = promote_geopolitical_manifest(
            base, receipts=trusted_receipts, store=event_store
        )
    if capture_ids is not None or (
        not direct and runtime_manifest["manifest_readiness"] == "READY"
    ):
        try:
            snapshot = build_geopolitical_role_snapshot(
                as_of_date,
                store=event_store,
                manifest=runtime_manifest,
                direct_source_capture_ids=capture_ids,
                license_decisions=license_decisions,
            )
            source_receipt = _aggregate_source_receipt(
                as_of_date=as_of_date,
                cutoff=cutoff,
                snapshot=snapshot,
                store=event_store,
                source_capture_ids=capture_ids,
                license_decisions=license_decisions,
            )
        except DataVendorUnavailable:
            snapshot = None
            source_receipt = None

    coverage = _coverage_receipt(
        as_of_date=as_of_date,
        cutoff=capture_cutoff,
        source_receipt=source_receipt,
        blocker_codes=("INCOMPLETE_COVERAGE",),
        window_start=cutoff if direct else None,
    )
    if source_receipt is None:
        ledger.append_route_coverage(coverage)
    else:
        ledger.append_capture_group((source_receipt,), coverage)

    calendar_hashes, missing_calendars = _available_calendar_hashes(
        ledger, as_of_date=as_of_date
    )
    source_hashes = [coverage.receipt_hash, *calendar_hashes]
    missing_routes = list(missing_calendars)
    blockers: list[str] = []
    if source_receipt is None:
        missing_routes.append(GEOPOLITICAL_LOGICAL_ROUTE_ID)
        blockers.append("INCOMPLETE_COVERAGE")
    if missing_calendars:
        blockers.append("REQUIRED_ROUTE_MISSING")
    ready_snapshot = snapshot if not missing_routes else None
    build = _build_receipt(
        as_of_date=as_of_date,
        cutoff=capture_cutoff,
        source_hashes=source_hashes,
        snapshot=ready_snapshot,
        missing_routes=missing_routes,
        blocker_codes=blockers,
    )
    persisted = ledger.append_or_reuse_snapshot_build(build)
    if ready_snapshot is not None:
        _write_snapshot(
            output_root, as_of_date=as_of_date, snapshot=ready_snapshot
        )
    return GeopoliticalMaterializationResult(
        source_receipt=source_receipt,
        coverage_receipt=coverage,
        build_receipt=persisted,
        snapshot=ready_snapshot,
    )


__all__ = [
    "GEOPOLITICAL_COMPILER_VERSION",
    "GEOPOLITICAL_LOGICAL_ROUTE_ID",
    "GEOPOLITICAL_TOOL_ID",
    "GeopoliticalMaterializationResult",
    "materialize_geopolitical_snapshot",
]
