"""Trusted stage publication immediately before capability preparation."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from mosaic.scorecard.canonical_json import canonical_hash

from .a_share_archive import (
    AShareArchiveStore,
    archive_a_share_breadth,
    compile_a_share_breadth_snapshot,
    fetch_a_share_tushare_endpoint,
)
from .agent_materialization import (
    AgentDataMaterializationLedger,
    MaterializationAttemptReceipt,
    SnapshotBuildReceipt,
    SourceCaptureReceipt,
    load_agent_data_route_manifest,
    materialization_lock_key,
    open_agent_data_materialization_ledger,
)
from .bound_runtime_snapshots import (
    bound_runtime_snapshot_relative_path,
    compile_bound_runtime_snapshot,
    publish_bound_runtime_snapshot,
    runtime_snapshot_root,
)
from .china_agent_data_archive import (
    CURVE_ROUTE_GROUP,
    INSTITUTIONAL_ROUTE_GROUP,
    LOGICAL_ROUTES as CHINA_AGENT_ROUTE_IDS,
    ChinaAgentDataArchiveStore,
    _private_tushare_fetch as _china_tushare_fetch,
    archive_china_agent_sources,
    compile_china_agent_snapshots,
)
from .economic_calendar import EconomicCalendarStore
from .exceptions import DataVendorUnavailable
from .europe_macro_archive import (
    EuropeMacroArchiveStore,
    LOGICAL_ROUTES as EUROPE_MACRO_ROUTE_IDS,
    _private_tushare_fetch as _europe_tushare_fetch,
    archive_europe_macro_sources,
    compile_europe_macro_snapshots,
)
from .geopolitical_archive import materialize_geopolitical_snapshot
from .geopolitical_events import GeopoliticalEventStore, geopolitical_store_path
from .geopolitical_source_adapters import capture_required_geopolitical_sources
from .frozen_adaptive_queries import (
    CALL_TIME_ARGUMENT_CONTRACT,
    FrozenAdaptiveQueryStore,
)
from .macro_snapshots import snapshot_cache_root
from .role_events import ROLE_EVENT_SNAPSHOT_VERSION, build_role_event_snapshot
from .route_eligibility import (
    evaluate_runtime_stage_admission,
    production_license_receipt_ref,
)
from .runtime_paths import agent_cache_root, agent_runtime_root_override
from .sector_archive import (
    LOGICAL_ROUTES as SECTOR_ARCHIVE_ROUTE_IDS,
    STANDARD_SECTOR_AGENT_IDS,
    SectorArchiveStore,
    archive_sector_relationship,
    compile_sector_relationship_core_snapshots,
)
from .source_archive import archive_eco_calendar
from .staged_query_receipt_store import StagedQueryReceiptStore
from .us_macro_archive import (
    LOGICAL_ROUTES as US_MACRO_ROUTE_IDS,
    USMacroArchiveStore,
    _private_tushare_fetch as _us_tushare_fetch,
    archive_us_macro_sources,
    compile_us_macro_snapshots,
)


MATERIALIZATION_CONTRACT_VERSION = "agent_materialization_contract_v1"
ADAPTIVE_QUERY_COMPILER_VERSION = "trusted_adaptive_query_compiler_v1"
ADAPTIVE_QUERY_OUTPUT_CONTRACT_VERSION = "frozen_adaptive_query_tool_bundle_v1"
ROLE_EVENT_COMPILER_VERSION = "trusted_role_event_build_compiler_v1"
BOUND_RUNTIME_COMPILER_VERSION = "trusted_bound_runtime_snapshot_compiler_v1"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DEFERRED_REQUEST_ONLY_MARKER = "_mosaic_deferred_request_only"
_DEFERRED_TOOL_IDS = "_mosaic_deferred_tool_ids"
_DEFERRED_REQUEST_ONLY_SENTINEL = object()
FamilyStagePreparer = Callable[
    [Mapping[str, Any], AgentDataMaterializationLedger], Any
]


def trusted_deferred_request_only_request(
    request: Mapping[str, Any], *, tool_ids: Sequence[str]
) -> dict[str, Any]:
    """Mark one in-process stage request as deferred without trusting caller fields."""

    normalized = dict(request)
    tools = tuple(tool_ids)
    if not tools or len(tools) != len(set(tools)) or any(
        not isinstance(tool_id, str) or not tool_id for tool_id in tools
    ):
        raise ValueError("deferred request-only tool ids are invalid")
    normalized[_DEFERRED_REQUEST_ONLY_MARKER] = _DEFERRED_REQUEST_ONLY_SENTINEL
    normalized[_DEFERRED_TOOL_IDS] = tools
    return normalized


def _deferred_request_only_tool_ids(
    request: Mapping[str, Any],
) -> tuple[str, ...] | None:
    if request.get(_DEFERRED_REQUEST_ONLY_MARKER) is not _DEFERRED_REQUEST_ONLY_SENTINEL:
        return None
    tool_ids = request.get(_DEFERRED_TOOL_IDS)
    if (
        not isinstance(tool_ids, tuple)
        or not tool_ids
        or len(tool_ids) != len(set(tool_ids))
        or any(not isinstance(tool_id, str) or not tool_id for tool_id in tool_ids)
    ):
        raise ValueError("deferred request-only tool ids are invalid")
    return tool_ids
_CHINA_FAMILY_STAGES = (
    ("central_bank", "central_bank"),
    ("china", "china"),
    ("commodities", "commodities"),
    ("institutional_flow", "institutional_flow"),
)
_US_FAMILY_STAGES = (
    ("us_economy", "us_economy"),
    ("us_financial_conditions", "us_financial_conditions"),
)
_EUROPE_FAMILY_STAGES = (
    ("eu_economy", "eu_economy"),
    ("euro_area_financial_conditions", "euro_area_financial_conditions"),
)
_GEOPOLITICAL_FAMILY_STAGES = (("geopolitical", "geopolitical"),)
_MARKET_BREADTH_FAMILY_STAGES = (("market_breadth", "market_breadth"),)
_SECTOR_ROLE_EVENT_STAGES = (
    "semiconductor",
    "technology",
    "energy",
    "consumer",
    "industrials",
    "real_estate_construction",
    "financials",
    "agriculture",
)
_SECTOR_RELATIONSHIP_FAMILY_STAGES = tuple(
    (stage, stage)
    for stage in (
        "semiconductor",
        "technology",
        "energy",
        "biotech",
        "consumer",
        "industrials",
        "real_estate_construction",
        "financials",
        "agriculture",
    )
)
_BOUND_RUNTIME_FAMILY_STAGES = (
    ("ackman", "ackman"),
    ("burry", "burry"),
    ("druckenmiller", "druckenmiller"),
    ("munger", "munger"),
    ("alpha_discovery", "alpha_discovery"),
    ("cio", "cio_proposal"),
    ("cro", "cro"),
    ("autonomous_execution", "autonomous_execution"),
    ("cio", "cio_final"),
)
_BOUND_RUNTIME_TOOL_IDS = frozenset(
    {
        "get_alpha_candidate_snapshot",
        "get_cio_decision_snapshot",
        "get_cro_risk_snapshot",
        "get_execution_snapshot",
        "get_superinvestor_candidate_snapshot",
    }
)
_BOUND_ROLE_EVENT_STAGES = frozenset(
    {
        ("alpha_discovery", "alpha_discovery"),
        ("cro", "cro"),
        ("autonomous_execution", "autonomous_execution"),
    }
)
SOURCE_ADMISSION_FAMILY_STAGE_GROUPS = (
    (("china", "china"), _CHINA_FAMILY_STAGES),
    (("us_economy", "us_economy"), _US_FAMILY_STAGES),
    (("eu_economy", "eu_economy"), _EUROPE_FAMILY_STAGES),
    (("geopolitical", "geopolitical"), _GEOPOLITICAL_FAMILY_STAGES),
    (("market_breadth", "market_breadth"), _MARKET_BREADTH_FAMILY_STAGES),
    (("semiconductor", "semiconductor"), _SECTOR_RELATIONSHIP_FAMILY_STAGES),
)
US_MACRO_OBSERVATION_WINDOW_POLICY = "previous_calendar_year_start_v1"


def _required_text(request: Mapping[str, Any], field: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _historical_replay(request: Mapping[str, Any]) -> bool:
    value = request.get("historical_replay", False)
    if not isinstance(value, bool):
        raise ValueError("historical_replay must be a boolean")
    return value


def _stage_bindings(agent_id: str, stage: str) -> list[dict[str, Any]]:
    bindings = [
        binding
        for binding in load_agent_data_route_manifest()["bindings"]
        if binding["agent_id"] == agent_id and binding["stage"] == stage
    ]
    if not bindings:
        raise ValueError(f"unknown Agent/stage materialization binding: {agent_id}/{stage}")
    return sorted(bindings, key=lambda binding: binding["tool_id"])


def _runtime_route_projection(
    *,
    route_id: str,
    agent_id: str,
    stage: str,
    as_of: str,
    graph_run_id: str,
    candidate_scope: Mapping[str, Any],
    accepted_output_refs: list[Mapping[str, Any]],
    accepted_output_records: list[Mapping[str, Any]],
    runtime_state: Mapping[str, Any],
) -> dict[str, Any]:
    identity = {
        "agent_id": agent_id,
        "stage": stage,
        "as_of": as_of,
        "graph_run_id": graph_run_id,
    }
    if route_id == "runtime.accepted_outputs":
        return {
            **identity,
            "accepted_output_refs": accepted_output_refs,
            "accepted_output_records": accepted_output_records,
        }
    if route_id == "runtime.candidate_scope":
        return {**identity, "candidate_scope": dict(candidate_scope)}
    if route_id == "runtime.account_positions_policy":
        fields = {
            key: runtime_state[key]
            for key in (
                "current_positions",
                "decision_policy_release",
                "previous_target_state",
            )
            if key in runtime_state
        }
        return {**identity, "captured_at": runtime_state.get("captured_at"), **fields}
    if route_id == "runtime.market_liquidity":
        fields = {
            key: value
            for key, value in runtime_state.items()
            if key
            not in {
                "captured_at",
                "current_positions",
                "decision_policy_release",
                "previous_target_state",
            }
        }
        return {**identity, "captured_at": runtime_state.get("captured_at"), **fields}
    raise DataVendorUnavailable(f"unsupported bound runtime route {route_id}")


def _runtime_source_receipt(
    *,
    route_id: str,
    projection: Mapping[str, Any],
    as_of: str,
    captured_at: str,
) -> SourceCaptureReceipt:
    route = next(
        (
            row
            for row in load_agent_data_route_manifest()["routes"]
            if row["route_id"] == route_id
        ),
        None,
    )
    if route is None or route["source_family"] != "runtime":
        raise DataVendorUnavailable("bound runtime route manifest drift")
    content_hash = canonical_hash(dict(projection))
    identity = {
        "route_id": route_id,
        "as_of": as_of,
        "captured_at": captured_at,
        "content_hash": content_hash,
    }
    return SourceCaptureReceipt.seal(
        {
            "schema_version": "source_capture_receipt_v1",
            "identity": {
                "source_family": "runtime",
                "route_id": route_id,
                "request_hash": canonical_hash(identity),
                "capture_id": "runtime-capture:"
                + canonical_hash(identity).removeprefix("sha256:"),
            },
            "transport": {
                "redacted_url": "local-runtime://bound-authority",
                "method": "FILE",
                "query_keys": ["agent_id", "as_of", "graph_run_id", "stage"],
                "pagination_policy": "SINGLE_FROZEN_RUNTIME_OBJECT",
                "page_count": 1,
            },
            "authority": {
                "provider": "mosaic_runtime",
                "permission_tier": "trusted_process_memory",
                "api_version": str(route["contract_version"]),
                "parser_version": "bound_runtime_projection_v1",
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
                "raw_content_hash": content_hash,
                "normalized_row_count": 1,
                "schema_hash": canonical_hash(
                    {
                        "route_id": route_id,
                        "contract_version": route["contract_version"],
                        "projection_fields": sorted(projection),
                    }
                ),
            },
            "coverage": {
                "requested_start": as_of,
                "requested_end": as_of,
                "observed_start": as_of,
                "observed_end": as_of,
                "dimensions": {},
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": 0,
                "empty_result_semantics": "NON_EMPTY",
            },
            "provenance": {
                "parent_capture_hash": None,
                "previous_revision_hash": None,
                "revision_reason": None,
            },
        }
    )


def prepare_bound_runtime_family(
    request: Mapping[str, Any],
    ledger: AgentDataMaterializationLedger,
    *,
    output_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Compile one exact in-run snapshot and seal its local runtime lineage."""
    agent_id = _required_text(request, "agent_id")
    stage = _required_text(request, "stage")
    as_of = _required_text(request, "as_of")
    graph_run_id = _required_text(request, "graph_run_id")
    if (agent_id, stage) not in _BOUND_RUNTIME_FAMILY_STAGES:
        raise DataVendorUnavailable(f"unsupported bound runtime stage {agent_id}/{stage}")
    runtime_inputs = request.get("runtime_inputs")
    candidate_scope = request.get("candidate_scope")
    if not isinstance(runtime_inputs, Mapping) or set(runtime_inputs) != {
        "accepted_output_refs",
        "accepted_output_records",
        "bound_runtime_state",
    }:
        raise DataVendorUnavailable("bound runtime inputs do not form the exact producer contract")
    if not isinstance(candidate_scope, Mapping) or set(candidate_scope) != {
        "accepted_output_refs"
    }:
        raise DataVendorUnavailable("bound runtime candidate scope is invalid")
    accepted_output_refs = runtime_inputs["accepted_output_refs"]
    accepted_output_records = runtime_inputs["accepted_output_records"]
    runtime_state = runtime_inputs["bound_runtime_state"]
    if (
        not isinstance(accepted_output_refs, list)
        or not all(isinstance(row, Mapping) for row in accepted_output_refs)
        or not isinstance(accepted_output_records, list)
        or not all(isinstance(row, Mapping) for row in accepted_output_records)
        or not isinstance(runtime_state, Mapping)
        or "captured_at" in runtime_state
        or candidate_scope["accepted_output_refs"] != accepted_output_refs
    ):
        raise DataVendorUnavailable("bound runtime producer closure is invalid")

    bound_bindings = [
        binding
        for binding in _stage_bindings(agent_id, stage)
        if binding["tool_id"] in _BOUND_RUNTIME_TOOL_IDS
    ]
    if len(bound_bindings) != 1:
        raise DataVendorUnavailable("bound runtime tool binding is ambiguous")
    binding = bound_bindings[0]
    tool_id = str(binding["tool_id"])
    root = output_root or runtime_snapshot_root()
    relative_path = bound_runtime_snapshot_relative_path(
        agent_id=agent_id,
        stage=stage,
        tool_id=tool_id,
        as_of=as_of,
        graph_run_id=graph_run_id,
    )
    existing_path = root / relative_path
    if existing_path.is_file():
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataVendorUnavailable("cannot reuse bound runtime snapshot") from exc
        if not isinstance(existing, Mapping):
            raise DataVendorUnavailable("existing bound runtime snapshot is invalid")
        generated_at = _required_text(existing, "generated_at")
    else:
        generated = (clock or (lambda: datetime.now(timezone.utc)))()
        if generated.tzinfo is None or generated.utcoffset() is None:
            raise ValueError("bound runtime producer clock must be timezone-aware")
        generated_at = generated.astimezone(timezone.utc).isoformat()

    def compile_at(timestamp: str) -> tuple[dict[str, Any], dict[str, Any]]:
        captured = {**runtime_state, "captured_at": timestamp}
        return (
            compile_bound_runtime_snapshot(
                agent_id=agent_id,
                stage=stage,
                as_of=as_of,
                graph_run_id=graph_run_id,
                accepted_output_refs=accepted_output_refs,
                accepted_output_records=accepted_output_records,
                runtime_state=captured,
                generated_at=timestamp,
            ),
            captured,
        )

    snapshot, captured_runtime_state = compile_at(generated_at)
    try:
        published = publish_bound_runtime_snapshot(
            snapshot,
            tool_id=tool_id,
            output_root=root,
        )
    except DataVendorUnavailable as exc:
        if str(exc) != "immutable bound runtime snapshot collision":
            raise
        try:
            winning_snapshot = json.loads(existing_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as read_exc:
            raise DataVendorUnavailable("cannot reuse bound runtime snapshot") from read_exc
        if not isinstance(winning_snapshot, Mapping):
            raise DataVendorUnavailable("existing bound runtime snapshot is invalid")
        generated_at = _required_text(winning_snapshot, "generated_at")
        snapshot, captured_runtime_state = compile_at(generated_at)
        published = publish_bound_runtime_snapshot(
            snapshot,
            tool_id=tool_id,
            output_root=root,
        )
    source_receipt_hashes: list[str] = []
    for route_id in sorted(binding["required_route_ids"]):
        projection = _runtime_route_projection(
            route_id=route_id,
            agent_id=agent_id,
            stage=stage,
            as_of=as_of,
            graph_run_id=graph_run_id,
            candidate_scope=candidate_scope,
            accepted_output_refs=accepted_output_refs,
            accepted_output_records=accepted_output_records,
            runtime_state=captured_runtime_state,
        )
        source_receipt_hashes.append(
            ledger.append_source_capture(
                _runtime_source_receipt(
                    route_id=route_id,
                    projection=projection,
                    as_of=as_of,
                    captured_at=generated_at,
                )
            )
        )
    source_receipt_hashes.sort()
    build_identity = {
        "agent_id": agent_id,
        "stage": stage,
        "tool_id": tool_id,
        "as_of": as_of,
        "graph_run_id": graph_run_id,
        "output_hash": published["output_hash"],
        "source_receipt_hashes": source_receipt_hashes,
    }
    build = SnapshotBuildReceipt.seal(
        {
            "schema_version": "snapshot_build_receipt_v1",
            "build_id": "bound-runtime-build:"
            + canonical_hash(build_identity).removeprefix("sha256:"),
            "agent_id": agent_id,
            "stage": stage,
            "tool_id": tool_id,
            "as_of": as_of,
            "as_of_cutoff": generated_at,
            "source_receipt_hashes": source_receipt_hashes,
            "compiler_version": BOUND_RUNTIME_COMPILER_VERSION,
            "output_contract_version": str(snapshot["contract_version"]),
            "output_path": str(published["output_path"]),
            "output_hash": str(published["output_hash"]),
            "pit_mode": "OBSERVED_LIVE",
            "earliest_trustworthy_date": as_of,
            "required_route_ids": sorted(binding["required_route_ids"]),
            "missing_route_ids": [],
            "terminal_state": "READY",
            "blocker_codes": [],
            "build_started_at": generated_at,
            "build_finished_at": generated_at,
        }
    )
    stored_build = ledger.append_or_reuse_snapshot_build(build)
    role_cache_status: str | None = None
    if (agent_id, stage) in _BOUND_ROLE_EVENT_STAGES:
        role_ready_before = ledger.ready_snapshot_build_receipts(
            agent_id=agent_id,
            stage=stage,
            tool_id="get_role_event_snapshot",
            as_of=as_of,
        )
        calendar_store = EconomicCalendarStore()
        calendar = archive_eco_calendar(
            partial(_china_tushare_fetch, endpoint="eco_cal"),
            as_of_date=as_of,
            captured_at=_stage_capture_now().astimezone(timezone.utc).isoformat(),
            store=calendar_store,
            ledger=ledger,
        )
        compile_role_event_builds(
            archive=calendar,
            store=calendar_store,
            ledger=ledger,
            agent_ids=(agent_id,),
        )
        if not calendar.coverage_receipt.as_dict()["coverage_complete"]:
            raise DataVendorUnavailable("economic calendar archive is blocked")
        role_cache_status = "HIT" if len(role_ready_before) == 1 else "MISS"
    cache_status = str(published["cache_status"])
    if role_cache_status is not None and role_cache_status != cache_status:
        cache_status = "MIXED"
    return {
        **published,
        "cache_status": cache_status,
        "source_receipt_hashes": source_receipt_hashes,
        "build_receipt_hash": stored_build.receipt_hash,
    }


def publish_ready_stage_materialization(
    request: Mapping[str, Any],
    *,
    ledger: AgentDataMaterializationLedger,
    clock: Callable[[], datetime] | None = None,
    cache_status: str = "HIT",
) -> dict[str, Any]:
    """Atomically publish one stage from its already-sealed READY builds."""
    graph_run_id = _required_text(request, "graph_run_id")
    run_slot_id = _required_text(request, "run_slot_id")
    run_id = _required_text(request, "run_id")
    node_id = _required_text(request, "node_id")
    agent_id = _required_text(request, "agent_id")
    stage = _required_text(request, "stage")
    as_of = _required_text(request, "as_of")
    materialization_request_id = _required_text(request, "materialization_request_id")
    runtime_inputs = request.get("runtime_inputs", {})
    candidate_scope = request.get("candidate_scope")
    if not isinstance(runtime_inputs, Mapping):
        raise ValueError("runtime_inputs must be an object")
    if candidate_scope is not None and not isinstance(candidate_scope, Mapping):
        raise ValueError("candidate_scope must be an object or null")
    if cache_status not in {"HIT", "MISS", "MIXED"}:
        raise ValueError("cache_status must be HIT, MISS, or MIXED")
    expected_output_hashes = request.get("tool_payload_hashes")
    if expected_output_hashes is not None and not isinstance(
        expected_output_hashes, Mapping
    ):
        raise ValueError("tool_payload_hashes must be an object")
    tool_ids, build_receipts, source_receipts = _ready_stage_receipts(
        ledger=ledger,
        agent_id=agent_id,
        stage=stage,
        as_of=as_of,
        expected_output_hashes=expected_output_hashes,
    )
    now = (clock or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
    runtime_route_eligibility_receipt_hashes = evaluate_runtime_stage_admission(
        ledger=ledger,
        agent_id=agent_id,
        stage=stage,
        target_date=as_of,
        evaluated_at=now.isoformat(),
        cycle_run_id=graph_run_id,
        source_receipt_hashes=sorted(
            {
                receipt_hash
                for receipt_hashes in source_receipts.values()
                for receipt_hash in receipt_hashes
            }
        ),
    )
    candidate_scope_hash = canonical_hash(
        dict(candidate_scope) if candidate_scope is not None else {}
    )
    runtime_input_hash = canonical_hash(dict(runtime_inputs))
    lock_key = materialization_lock_key(
        agent_id=agent_id,
        stage=stage,
        as_of=as_of,
        requested_tool_ids=tool_ids,
        candidate_scope_hash=candidate_scope_hash,
        runtime_input_hash=runtime_input_hash,
        contract_version=MATERIALIZATION_CONTRACT_VERSION,
    )
    finished_at = now.isoformat()
    attempt_id = "attempt:" + canonical_hash(
        {
            "materialization_request_id": materialization_request_id,
            "lock_key": lock_key,
        }
    ).removeprefix("sha256:")
    owner = "trusted-preparer:" + canonical_hash(
        {"materialization_request_id": materialization_request_id}
    ).removeprefix("sha256:")
    attempt = MaterializationAttemptReceipt.seal(
        {
            "schema_version": "materialization_attempt_receipt_v1",
            "attempt_id": attempt_id,
            "materialization_request_id": materialization_request_id,
            "graph_run_id": graph_run_id,
            "run_slot_id": run_slot_id,
            "run_id": run_id,
            "node_id": node_id,
            "agent_id": agent_id,
            "stage": stage,
            "as_of": as_of,
            "requested_tool_ids": tool_ids,
            "candidate_scope_hash": candidate_scope_hash,
            "runtime_input_hash": runtime_input_hash,
            "contract_version": MATERIALIZATION_CONTRACT_VERSION,
            "source_receipts": source_receipts,
            "build_receipts": build_receipts,
            "cache_status": cache_status,
            "lock": {
                "key": lock_key,
                "owner": owner,
                "acquired_at": finished_at,
                "lease_expires_at": (now + timedelta(minutes=5)).isoformat(),
                "heartbeat_at": finished_at,
                "retry_count": 0,
                "recovered_from_owner": None,
            },
            "freshness": {
                "policy_version": "sealed_build_pit_v1",
                "max_age_seconds": 0,
                "status": "NOT_APPLICABLE",
                "checked_at": finished_at,
            },
            "terminal_state": "READY",
            "blocker_codes": [],
            "started_at": finished_at,
            "finished_at": finished_at,
        }
    )
    receipt_hash = ledger.append_materialization_attempt(attempt)
    return {
        "agent_id": agent_id,
        "stage": stage,
        "as_of": as_of,
        "status": "READY",
        "tool_ids": tool_ids,
        "build_receipt_hashes": build_receipts,
        "materialization_attempt_receipt_hash": receipt_hash,
        "runtime_route_eligibility_receipt_hashes": (
            runtime_route_eligibility_receipt_hashes
        ),
        "cache_status": cache_status,
    }


def _ready_stage_receipts(
    *,
    ledger: AgentDataMaterializationLedger,
    agent_id: str,
    stage: str,
    as_of: str,
    expected_output_hashes: Mapping[str, Any] | None = None,
    tool_ids: Sequence[str] | None = None,
) -> tuple[list[str], dict[str, str], dict[str, list[str]]]:
    bindings = _stage_bindings(agent_id, stage)
    if tool_ids is None:
        selected_tool_ids = [binding["tool_id"] for binding in bindings]
    else:
        selected_tool_ids = list(tool_ids)
        available_tool_ids = {binding["tool_id"] for binding in bindings}
        if (
            selected_tool_ids != sorted(set(selected_tool_ids))
            or not set(selected_tool_ids) <= available_tool_ids
        ):
            raise ValueError("stage receipt tool subset is invalid")
        bindings = [
            binding
            for binding in bindings
            if binding["tool_id"] in set(selected_tool_ids)
        ]
    build_receipts: dict[str, str] = {}
    source_receipts: dict[str, list[str]] = {}
    for binding in bindings:
        tool_id = binding["tool_id"]
        ready = ledger.ready_snapshot_build_receipts(
            agent_id=agent_id,
            stage=stage,
            tool_id=tool_id,
            as_of=as_of,
        )
        if tool_id in _BOUND_RUNTIME_TOOL_IDS and expected_output_hashes is not None:
            expected_output_hash = expected_output_hashes.get(tool_id)
            ready = tuple(
                build
                for build in ready
                if build.as_dict()["output_hash"] == expected_output_hash
            )
        if not ready:
            raise DataVendorUnavailable(
                f"no READY build for {agent_id}/{stage}/{tool_id} on {as_of}"
            )
        if len(ready) != 1:
            raise DataVendorUnavailable(
                f"ambiguous READY builds for {agent_id}/{stage}/{tool_id} on {as_of}"
            )
        build = ready[0]
        build_payload = build.as_dict()
        if build_payload["required_route_ids"] != sorted(
            binding["required_route_ids"]
        ):
            raise DataVendorUnavailable(
                f"READY build route contract drift for {agent_id}/{stage}/{tool_id}"
            )
        build_receipts[tool_id] = build.receipt_hash
        source_receipts[tool_id] = list(build_payload["source_receipt_hashes"])
    return selected_tool_ids, build_receipts, source_receipts


def _coverage_start(source: Mapping[str, Any]) -> str:
    coverage = source.get("coverage")
    if not isinstance(coverage, Mapping):
        raise DataVendorUnavailable("upstream source receipt has no coverage")
    for field in ("observed_start", "requested_start"):
        value = coverage.get(field)
        if isinstance(value, str) and value:
            try:
                return date.fromisoformat(value[:10]).isoformat()
            except ValueError:
                continue
    raise DataVendorUnavailable("upstream source receipt has no trustworthy start")


def compile_adaptive_query_builds(
    *,
    agent_id: str,
    stage: str,
    as_of: str,
    adaptive_query: Mapping[str, Any],
    ledger: AgentDataMaterializationLedger,
    adaptive_query_store: FrozenAdaptiveQueryStore,
    staged_receipt_store: StagedQueryReceiptStore,
    clock: Callable[[], datetime] | None = None,
) -> tuple[SnapshotBuildReceipt, ...]:
    """Promote frozen query lineage into exact per-tool READY builds."""

    if not isinstance(adaptive_query, Mapping):
        raise ValueError("adaptive_query must be an object")
    bundle_id = _required_text(adaptive_query, "bundle_id")
    bundle_hash = _required_text(adaptive_query, "bundle_hash")
    evidence = adaptive_query_store.bundle_evidence(bundle_id)
    if (
        evidence["bundle_hash"] != bundle_hash
        or evidence["agent_id"] != agent_id
        or evidence["stage"] != stage
        or evidence["as_of"] != as_of
    ):
        raise DataVendorUnavailable("adaptive query evidence binding mismatch")

    bindings = {
        binding["tool_id"]: binding for binding in _stage_bindings(agent_id, stage)
    }
    entries_by_tool: dict[str, list[dict[str, Any]]] = {}
    for raw_entry in evidence["entries"]:
        entry = dict(raw_entry)
        tool_id = str(entry["tool_id"])
        if tool_id not in bindings:
            raise DataVendorUnavailable("adaptive query tool is outside stage bindings")
        entries_by_tool.setdefault(tool_id, []).append(entry)

    now = (clock or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
    cutoff = datetime.combine(
        date.fromisoformat(as_of), time.max, tzinfo=_SHANGHAI
    ).isoformat()
    builds: list[SnapshotBuildReceipt] = []
    for tool_id in sorted(entries_by_tool):
        binding = bindings[tool_id]
        required_routes = sorted(binding["required_route_ids"])
        source_hashes: set[str] = set()
        source_pit_modes: set[str] = set()
        coverage_starts: list[str] = []
        output_entries: list[dict[str, Any]] = []
        for entry in entries_by_tool[tool_id]:
            output_entries.append(
                {
                    key: entry[key]
                    for key in (
                        "request_hash",
                        "call_mode",
                        "payload_hash",
                        "source_receipt_set_hash",
                    )
                }
            )
            for staged_hash in entry["source_receipt_hashes"]:
                staged = staged_receipt_store.receipt_by_hash(staged_hash)
                if (
                    staged["tool_id"] != tool_id
                    or staged["as_of"] != as_of
                    or staged["request_hash"] != entry["request_hash"]
                    or staged["route_id"] not in required_routes
                ):
                    raise DataVendorUnavailable(
                        "staged query receipt binding mismatch"
                    )
                upstream_hashes = staged["upstream_evidence_hashes"]
                if not upstream_hashes:
                    raise DataVendorUnavailable(
                        "staged query receipt has no promoted upstream source"
                    )
                for upstream_hash in upstream_hashes:
                    source = ledger.source_capture_receipt(
                        receipt_hash=upstream_hash
                    )
                    if source is None:
                        raise DataVendorUnavailable(
                            "upstream source receipt is unavailable in AgentData ledger"
                        )
                    source_payload = source.as_dict()
                    if source_payload["identity"]["route_id"] != staged["route_id"]:
                        raise DataVendorUnavailable(
                            "upstream source receipt route mismatch"
                        )
                    if not source_payload["pit"]["eligible"]:
                        raise DataVendorUnavailable(
                            "upstream source receipt is not PIT eligible"
                        )
                    source_hashes.add(source.receipt_hash)
                    source_pit_modes.add(source_payload["pit"]["pit_mode"])
                    coverage_starts.append(_coverage_start(source_payload))

        if not source_hashes or not coverage_starts:
            raise DataVendorUnavailable("adaptive query tool has no promoted sources")
        aggregate = {
            "output_contract_version": ADAPTIVE_QUERY_OUTPUT_CONTRACT_VERSION,
            "bundle_id": bundle_id,
            "bundle_hash": bundle_hash,
            "agent_id": agent_id,
            "stage": stage,
            "tool_id": tool_id,
            "as_of": as_of,
            "entries": output_entries,
        }
        output_hash = canonical_hash(aggregate)
        build_id = "adaptive:" + canonical_hash(
            {
                **aggregate,
                "source_receipt_hashes": sorted(source_hashes),
                "required_route_ids": required_routes,
            }
        ).removeprefix("sha256:")
        build = SnapshotBuildReceipt.seal(
            {
                "schema_version": "snapshot_build_receipt_v1",
                "build_id": build_id,
                "agent_id": agent_id,
                "stage": stage,
                "tool_id": tool_id,
                "as_of": as_of,
                "as_of_cutoff": cutoff,
                "source_receipt_hashes": sorted(source_hashes),
                "compiler_version": ADAPTIVE_QUERY_COMPILER_VERSION,
                "output_contract_version": ADAPTIVE_QUERY_OUTPUT_CONTRACT_VERSION,
                "output_path": (
                    f"runtime_queries/{as_of}/{bundle_id}/"
                    f"{agent_id}-{stage}-{tool_id}.json"
                ),
                "output_hash": output_hash,
                "pit_mode": (
                    next(iter(source_pit_modes))
                    if len(source_pit_modes) == 1
                    else "MIXED_AUTHORITY"
                ),
                "earliest_trustworthy_date": max(coverage_starts),
                "required_route_ids": required_routes,
                "missing_route_ids": [],
                "terminal_state": "READY",
                "blocker_codes": [],
                "build_started_at": now.isoformat(),
                "build_finished_at": now.isoformat(),
            }
        )
        builds.append(ledger.append_or_reuse_snapshot_build(build))
    return tuple(builds)


class TrustedAgentStagePreparer:
    """Warm-first dispatcher that ensures sources and initial stage builds."""

    def __init__(
        self,
        *,
        ledger_factory: Callable[[], AgentDataMaterializationLedger],
        family_preparers: Mapping[tuple[str, str], FamilyStagePreparer],
        clock: Callable[[], datetime] | None = None,
        always_prepare_stages: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.ledger_factory = ledger_factory
        self.family_preparers = dict(family_preparers)
        self.clock = clock
        self.always_prepare_stages = frozenset(always_prepare_stages)

    def __call__(self, request: Mapping[str, Any]) -> dict[str, Any]:
        ledger = self.ledger_factory()
        agent_id = _required_text(request, "agent_id")
        stage = _required_text(request, "stage")
        as_of = _required_text(request, "as_of")
        stage_key = (agent_id, stage)
        if stage_key not in self.always_prepare_stages:
            try:
                _ready_stage_receipts(
                    ledger=ledger,
                    agent_id=agent_id,
                    stage=stage,
                    as_of=as_of,
                )
                return {
                    "agent_id": agent_id,
                    "stage": stage,
                    "as_of": as_of,
                    "cache_status": "HIT",
                }
            except DataVendorUnavailable as exc:
                if not str(exc).startswith("no READY build for "):
                    raise

        family_preparer = self.family_preparers.get(stage_key)
        if family_preparer is None:
            raise DataVendorUnavailable(
                f"no registered family preparer for {agent_id}/{stage}"
            )
        prepared = family_preparer(request, ledger)
        cache_status = (
            str(prepared.get("cache_status", "MISS"))
            if isinstance(prepared, Mapping)
            else "MISS"
        )
        if cache_status not in {"HIT", "MISS", "MIXED"}:
            raise ValueError("family preparer returned an invalid cache_status")
        return {
            "agent_id": agent_id,
            "stage": stage,
            "as_of": as_of,
            "cache_status": cache_status,
        }


class TrustedAgentStageFinalizer:
    """Publish a stage only after every capability payload is materialized."""

    def __init__(
        self,
        *,
        ledger_factory: Callable[[], AgentDataMaterializationLedger],
        clock: Callable[[], datetime] | None = None,
        adaptive_query_store: FrozenAdaptiveQueryStore | None = None,
        staged_receipt_store: StagedQueryReceiptStore | None = None,
    ) -> None:
        if (adaptive_query_store is None) != (staged_receipt_store is None):
            raise ValueError(
                "adaptive_query_store and staged_receipt_store must be configured together"
            )
        self.ledger_factory = ledger_factory
        self.clock = clock
        self.adaptive_query_store = adaptive_query_store
        self.staged_receipt_store = staged_receipt_store

    def __call__(self, context: Mapping[str, Any]) -> dict[str, Any]:
        preparation = context.get("stage_preparation")
        if not isinstance(preparation, Mapping):
            raise ValueError("stage_preparation must be an object")
        cache_status = preparation.get("cache_status")
        if cache_status not in {"HIT", "MISS", "MIXED"}:
            raise ValueError("stage_preparation cache_status is invalid")
        ledger = self.ledger_factory()
        adaptive_query = context.get("adaptive_query")
        if isinstance(adaptive_query, Mapping) and adaptive_query.get("deferred") is True:
            agent_id = _required_text(context, "agent_id")
            stage = _required_text(context, "stage")
            as_of = _required_text(context, "as_of")
            deferred_tool_ids = context.get("deferred_tool_ids")
            initial_tool_ids = context.get("initial_snapshot_tool_ids")
            payload_hashes = context.get("tool_payload_hashes")
            projection = adaptive_query.get("public_projection")
            if (
                preparation.get("ensure_mode") != "enforce"
                or preparation.get("agent_id") != agent_id
                or preparation.get("stage") != stage
                or preparation.get("as_of") != as_of
                or not isinstance(deferred_tool_ids, list)
                or not deferred_tool_ids
                or deferred_tool_ids != sorted(set(deferred_tool_ids))
                or not isinstance(initial_tool_ids, list)
                or initial_tool_ids != sorted(set(initial_tool_ids))
                or not isinstance(payload_hashes, Mapping)
                or not isinstance(projection, Mapping)
                or projection.get("call_contract") != CALL_TIME_ARGUMENT_CONTRACT
                or projection.get("bundle_id") != adaptive_query.get("bundle_id")
                or projection.get("bundle_hash") != adaptive_query.get("bundle_hash")
                or projection.get("agent_id") != agent_id
                or projection.get("stage") != stage
                or projection.get("as_of") != as_of
            ):
                raise ValueError("deferred stage finalization authority is invalid")
            stage_tool_ids = {
                binding["tool_id"] for binding in _stage_bindings(agent_id, stage)
            }
            if (
                set(deferred_tool_ids) & set(initial_tool_ids)
                or set(deferred_tool_ids) | set(initial_tool_ids) != stage_tool_ids
                or set(payload_hashes) != stage_tool_ids
            ):
                raise ValueError("deferred stage finalization tool closure mismatch")
            ready_tool_ids, build_receipts, source_receipts = (
                _ready_stage_receipts(
                    ledger=ledger,
                    agent_id=agent_id,
                    stage=stage,
                    as_of=as_of,
                    expected_output_hashes=payload_hashes,
                    tool_ids=initial_tool_ids,
                )
            )
            if (
                ready_tool_ids != initial_tool_ids
                or set(build_receipts) != set(initial_tool_ids)
                or set(source_receipts) != set(initial_tool_ids)
            ):
                raise ValueError("deferred initial snapshot closure is invalid")
            # READY here is an internal split closure only. It is not a persisted
            # full-stage materialization attempt and carries no attempt authority.
            published = {
                "agent_id": agent_id,
                "stage": stage,
                "as_of": as_of,
                "status": "READY",
                "tool_ids": ready_tool_ids,
                "build_receipt_hashes": build_receipts,
                "materialization_attempt_receipt_hash": None,
                "cache_status": str(cache_status),
            }
            return {
                **published,
                "deferred_tool_ids": list(deferred_tool_ids),
                "deferred_query_bundle_hash": adaptive_query["bundle_hash"],
                "deferred_query_call_contract": CALL_TIME_ARGUMENT_CONTRACT,
            }
        if adaptive_query is not None:
            if self.adaptive_query_store is None or self.staged_receipt_store is None:
                raise DataVendorUnavailable(
                    "adaptive stage finalization requires evidence stores"
                )
            compile_adaptive_query_builds(
                agent_id=_required_text(context, "agent_id"),
                stage=_required_text(context, "stage"),
                as_of=_required_text(context, "as_of"),
                adaptive_query=adaptive_query,
                ledger=ledger,
                adaptive_query_store=self.adaptive_query_store,
                staged_receipt_store=self.staged_receipt_store,
                clock=self.clock,
            )
        return publish_ready_stage_materialization(
            context,
            ledger=ledger,
            clock=self.clock,
            cache_status=str(cache_status),
        )


def _stage_capture_now() -> datetime:
    return datetime.now(timezone.utc)


def compile_role_event_builds(
    *,
    archive: Any,
    store: EconomicCalendarStore,
    ledger: AgentDataMaterializationLedger,
    agent_ids: tuple[str, ...],
) -> tuple[SnapshotBuildReceipt, ...]:
    """Seal exact role-event builds for the selected active consumers."""
    coverage = archive.coverage_receipt.as_dict()
    as_of = str(coverage["window"]["start"])[:10]
    date.fromisoformat(as_of)
    as_of_cutoff = str(coverage["window"]["end"])
    complete = bool(coverage["coverage_complete"])
    source_by_route = {
        receipt.as_dict()["identity"]["route_id"]: receipt
        for receipt in archive.source_receipts
    }
    if complete != bool(source_by_route):
        raise ValueError("calendar source receipts contradict route coverage")
    now = _stage_capture_now().astimezone(timezone.utc).isoformat()
    builds: list[SnapshotBuildReceipt] = []
    for agent_id in agent_ids:
        binding = next(
            binding
            for binding in _stage_bindings(agent_id, agent_id)
            if binding["tool_id"] == "get_role_event_snapshot"
        )
        required_routes = sorted(binding["required_route_ids"])
        if complete:
            if not set(required_routes) <= set(source_by_route):
                raise ValueError("calendar source receipt closure drift")
            snapshot = build_role_event_snapshot(agent_id, as_of, store=store)
            if snapshot["coverage"]["coverage_completeness"] != "COMPLETE":
                raise DataVendorUnavailable("role-event calendar coverage is incomplete")
            source_hashes = sorted(
                source_by_route[route_id].receipt_hash
                for route_id in required_routes
            )
            output_hash = str(snapshot["role_event_snapshot_hash"])
            missing_routes: list[str] = []
            blocker_codes: list[str] = []
        else:
            source_hashes = [archive.coverage_receipt.receipt_hash]
            output_hash = None
            missing_routes = required_routes
            blocker_codes = sorted(set(coverage["blocker_codes"]))
        identity = {
            "agent_id": agent_id,
            "as_of": as_of,
            "source_receipt_hashes": source_hashes,
            "output_hash": output_hash,
            "missing_route_ids": missing_routes,
            "blocker_codes": blocker_codes,
        }
        receipt = SnapshotBuildReceipt.seal(
            {
                "schema_version": "snapshot_build_receipt_v1",
                "build_id": (
                    "sector-role-event-build:"
                    + canonical_hash(identity).removeprefix("sha256:")
                ),
                "agent_id": agent_id,
                "stage": agent_id,
                "tool_id": "get_role_event_snapshot",
                "as_of": as_of,
                "as_of_cutoff": as_of_cutoff,
                "source_receipt_hashes": source_hashes,
                "compiler_version": ROLE_EVENT_COMPILER_VERSION,
                "output_contract_version": ROLE_EVENT_SNAPSHOT_VERSION,
                "output_path": f"role_events/{as_of}/{agent_id}.json",
                "output_hash": output_hash,
                "pit_mode": "OBSERVED_LIVE",
                "earliest_trustworthy_date": as_of if complete else None,
                "required_route_ids": required_routes,
                "missing_route_ids": missing_routes,
                "terminal_state": "READY" if complete else "BLOCKED",
                "blocker_codes": blocker_codes,
                "build_started_at": now,
                "build_finished_at": now,
            }
        )
        builds.append(ledger.append_or_reuse_snapshot_build(receipt))
    return tuple(builds)


def compile_sector_role_event_builds(
    *,
    archive: Any,
    store: EconomicCalendarStore,
    ledger: AgentDataMaterializationLedger,
) -> tuple[SnapshotBuildReceipt, ...]:
    """Seal exact role-event builds for the eight bound Sector consumers."""
    return compile_role_event_builds(
        archive=archive,
        store=store,
        ledger=ledger,
        agent_ids=_SECTOR_ROLE_EVENT_STAGES,
    )


def _prepare_china_agent_archive(
    *,
    as_of: str,
    ledger: AgentDataMaterializationLedger,
    requested_route_ids: tuple[str, ...] | None = None,
    historical_replay: bool = False,
) -> None:
    store = ChinaAgentDataArchiveStore()
    archive = archive_china_agent_sources(
        as_of_date=as_of,
        cutoff_at=f"{as_of}T15:00:00+08:00",
        market_session_date=as_of,
        **(
            {"requested_route_ids": requested_route_ids}
            if requested_route_ids is not None
            else {}
        ),
        **({"historical_replay": True} if historical_replay else {}),
        store=store,
        ledger=ledger,
    )
    if requested_route_ids is not None:
        captured_routes = {
            receipt.as_dict()["identity"]["route_id"]
            for route in archive.routes.values()
            for receipt in route.source_receipts
        }
        if captured_routes != set(requested_route_ids) or any(
            not route.coverage_receipt.as_dict()["coverage_complete"]
            for route in archive.routes.values()
        ):
            raise DataVendorUnavailable(
                "China route-only archive is blocked",
                reason_code="CHINA_ROUTE_CAPTURE_BLOCKED",
            )
        return
    compile_china_agent_snapshots(
        archive=archive,
        store=store,
        ledger=ledger,
        output_root=snapshot_cache_root(),
    )


def prepare_china_agent_family(
    request: Mapping[str, Any],
    ledger: AgentDataMaterializationLedger,
) -> None:
    """Reuse the trusted calendar and China archive/compiler for four stages."""
    as_of = _required_text(request, "as_of")
    route_id = request.get("route_id")
    if isinstance(route_id, str) and route_id in CHINA_AGENT_ROUTE_IDS:
        _prepare_china_agent_archive(
            as_of=as_of,
            ledger=ledger,
            requested_route_ids=(route_id,),
            historical_replay=_historical_replay(request),
        )
        return
    captured_at = _stage_capture_now().astimezone(timezone.utc).isoformat()
    calendar = archive_eco_calendar(
        partial(_china_tushare_fetch, endpoint="eco_cal"),
        as_of_date=as_of,
        captured_at=captured_at,
        **({"as_of_cutoff": captured_at} if _historical_replay(request) else {}),
        **(
            {"requested_route_ids": (str(route_id),)}
            if route_id == "tushare.eco_cal.cny"
            else {}
        ),
        store=EconomicCalendarStore(),
        ledger=ledger,
    )
    if not calendar.coverage_receipt.as_dict()["coverage_complete"]:
        raise DataVendorUnavailable("economic calendar archive is blocked")
    if route_id == "tushare.eco_cal.cny":
        return
    _prepare_china_agent_archive(
        as_of=as_of,
        ledger=ledger,
        historical_replay=_historical_replay(request),
    )


def prepare_sector_relationship_family(
    request: Mapping[str, Any],
    ledger: AgentDataMaterializationLedger,
) -> None:
    """Reuse existing archives to build one standard Sector's initial data."""
    as_of = _required_text(request, "as_of")
    agent_id = _required_text(request, "agent_id")
    historical_replay = _historical_replay(request)
    route_only = request.get("route_id") in SECTOR_ARCHIVE_ROUTE_IDS
    route_id = str(request["route_id"]) if route_only else None
    if agent_id in STANDARD_SECTOR_AGENT_IDS:
        requested_route_ids = (
            (route_id,)
            if route_only
            else ("tushare.sector_fundamentals", "tushare.sector_market")
        )
        requested_agent_ids = (agent_id,)
    else:
        raise ValueError("agent is outside the standard Sector stage roster")
    if not route_only:
        captured_at = _stage_capture_now().astimezone(timezone.utc).isoformat()
        calendar_store = EconomicCalendarStore()
        calendar = archive_eco_calendar(
            partial(_china_tushare_fetch, endpoint="eco_cal"),
            as_of_date=as_of,
            captured_at=captured_at,
            as_of_cutoff=captured_at if historical_replay else None,
            store=calendar_store,
            ledger=ledger,
        )
        compile_sector_role_event_builds(
            archive=calendar,
            store=calendar_store,
            ledger=ledger,
        )
        if not calendar.coverage_receipt.as_dict()["coverage_complete"]:
            raise DataVendorUnavailable("economic calendar archive is blocked")

    sector_store = SectorArchiveStore()
    sector_archive = archive_sector_relationship(
        fetch_a_share_tushare_endpoint,
        as_of_date=as_of,
        cutoff_at=f"{as_of}T23:59:59+08:00",
        historical_replay=historical_replay,
        requested_route_ids=requested_route_ids,
        requested_agent_ids=requested_agent_ids,
        store=sector_store,
        ledger=ledger,
    )
    if not sector_archive.coverage_receipt.as_dict()["coverage_complete"]:
        raise DataVendorUnavailable(
            "sector relationship archive is blocked",
            reason_code="SECTOR_RELATIONSHIP_ARCHIVE_BLOCKED",
        )
    if route_only:
        return
    compile_sector_relationship_core_snapshots(
        sector_archive,
        ledger=ledger,
        output_root=snapshot_cache_root(),
    )
    china_route_ids = [INSTITUTIONAL_ROUTE_GROUP]
    if agent_id == "financials":
        china_route_ids.append(CURVE_ROUTE_GROUP)
    _prepare_china_agent_archive(
        as_of=as_of,
        ledger=ledger,
        requested_route_ids=tuple(china_route_ids),
    )


def us_macro_observation_start(as_of: str) -> str:
    """Return the versioned US Macro window start for one as-of date."""
    as_of_date = date.fromisoformat(as_of)
    return date(as_of_date.year - 1, 1, 1).isoformat()


def prepare_us_macro_family(
    request: Mapping[str, Any],
    ledger: AgentDataMaterializationLedger,
) -> None:
    """Reuse the trusted calendar and US archive/compiler for two stages."""
    as_of = _required_text(request, "as_of")
    route_id = request.get("route_id")
    if route_id in US_MACRO_ROUTE_IDS:
        store = USMacroArchiveStore()
        archive = archive_us_macro_sources(
            as_of_date=as_of,
            cutoff_at=f"{as_of}T15:00:00+08:00",
            observation_start=us_macro_observation_start(as_of),
            requested_route_ids=(str(route_id),),
            **(
                {"historical_replay": True}
                if _historical_replay(request)
                else {}
            ),
            store=store,
            ledger=ledger,
        )
        if not any(
            receipt.as_dict()["identity"]["route_id"] == route_id
            for receipt in archive.source_receipts
        ):
            raise DataVendorUnavailable(
                "US macro route-only capture is blocked",
                reason_code=(
                    "US_MACRO_AUTHORITATIVE_REPLAY_BLOCKED"
                    if route_id == "alfred.us_macro"
                    else "US_MACRO_ROUTE_CAPTURE_BLOCKED"
                ),
            )
        return
    captured_at = _stage_capture_now().astimezone(timezone.utc).isoformat()
    calendar = archive_eco_calendar(
        partial(_us_tushare_fetch, endpoint="eco_cal"),
        as_of_date=as_of,
        captured_at=captured_at,
        **({"as_of_cutoff": captured_at} if _historical_replay(request) else {}),
        **(
            {"requested_route_ids": (str(route_id),)}
            if route_id == "tushare.eco_cal.usd"
            else {}
        ),
        store=EconomicCalendarStore(),
        ledger=ledger,
    )
    if not calendar.coverage_receipt.as_dict()["coverage_complete"]:
        raise DataVendorUnavailable("economic calendar archive is blocked")
    if request.get("route_id") == "tushare.eco_cal.usd":
        return
    store = USMacroArchiveStore()
    archive = archive_us_macro_sources(
        as_of_date=as_of,
        cutoff_at=f"{as_of}T15:00:00+08:00",
        observation_start=us_macro_observation_start(as_of),
        **(
            {"historical_replay": True} if _historical_replay(request) else {}
        ),
        store=store,
        ledger=ledger,
    )
    if (
        not archive.coverage_receipt.as_dict()["coverage_complete"]
        or archive.group is None
    ):
        raise DataVendorUnavailable("US macro archive is blocked")
    compile_us_macro_snapshots(
        capture_key=archive.group["capture_key"],
        store=store,
        ledger=ledger,
        output_root=snapshot_cache_root(),
    )


def prepare_europe_macro_family(
    request: Mapping[str, Any],
    ledger: AgentDataMaterializationLedger,
) -> None:
    """Reuse the trusted calendar and Europe archive/compiler for two stages."""
    as_of = _required_text(request, "as_of")
    route_id = request.get("route_id")
    if route_id in EUROPE_MACRO_ROUTE_IDS:
        store = EuropeMacroArchiveStore()
        archive = archive_europe_macro_sources(
            as_of_date=as_of,
            cutoff_at=f"{as_of}T15:00:00+08:00",
            observation_start=us_macro_observation_start(as_of),
            requested_route_ids=(str(route_id),),
            **(
                {"historical_replay": True}
                if _historical_replay(request)
                else {}
            ),
            store=store,
            ledger=ledger,
        )
        if not any(
            receipt.as_dict()["identity"]["route_id"] == route_id
            for receipt in archive.source_receipts
        ):
            raise DataVendorUnavailable(
                "Europe macro route-only capture is blocked",
                reason_code=(
                    "EUROPE_MACRO_AUTHORITATIVE_REPLAY_BLOCKED"
                    if route_id in {"ecb.eu_real_economy", "ecb.euro_macro"}
                    else "EUROPE_MACRO_ROUTE_CAPTURE_BLOCKED"
                ),
            )
        return
    captured_at = _stage_capture_now().astimezone(timezone.utc).isoformat()
    calendar = archive_eco_calendar(
        partial(_europe_tushare_fetch, endpoint="eco_cal"),
        as_of_date=as_of,
        captured_at=captured_at,
        **({"as_of_cutoff": captured_at} if _historical_replay(request) else {}),
        **(
            {"requested_route_ids": (str(route_id),)}
            if route_id == "tushare.eco_cal.eur"
            else {}
        ),
        store=EconomicCalendarStore(),
        ledger=ledger,
    )
    if not calendar.coverage_receipt.as_dict()["coverage_complete"]:
        raise DataVendorUnavailable("economic calendar archive is blocked")
    if request.get("route_id") == "tushare.eco_cal.eur":
        return
    store = EuropeMacroArchiveStore()
    archive = archive_europe_macro_sources(
        as_of_date=as_of,
        cutoff_at=f"{as_of}T15:00:00+08:00",
        observation_start=us_macro_observation_start(as_of),
        **(
            {"historical_replay": True}
            if _historical_replay(request)
            else {}
        ),
        store=store,
        ledger=ledger,
    )
    if (
        not archive.coverage_receipt.as_dict()["coverage_complete"]
        or archive.group is None
    ):
        raise DataVendorUnavailable("Europe macro archive is blocked")
    compile_europe_macro_snapshots(
        capture_key=archive.group["capture_key"],
        store=store,
        ledger=ledger,
        output_root=snapshot_cache_root(),
    )


def prepare_geopolitical_family(
    request: Mapping[str, Any],
    ledger: AgentDataMaterializationLedger,
) -> None:
    """Capture every Geo source, then reuse existing preflight authority to build."""
    as_of = _required_text(request, "as_of")
    event_store = GeopoliticalEventStore(geopolitical_store_path())
    capture_required_geopolitical_sources(store=event_store)
    result = materialize_geopolitical_snapshot(
        as_of_date=as_of,
        event_store=event_store,
        ledger=ledger,
        output_root=snapshot_cache_root(),
    )
    if result.build_receipt.as_dict()["terminal_state"] != "READY":
        raise DataVendorUnavailable("geopolitical archive is blocked")


def prepare_market_breadth_family(
    request: Mapping[str, Any],
    ledger: AgentDataMaterializationLedger,
) -> None:
    """Reuse the trusted A-share archive and deterministic breadth compiler."""
    as_of = _required_text(request, "as_of")
    archive = archive_a_share_breadth(
        fetch_a_share_tushare_endpoint,
        as_of_date=as_of,
        cutoff_at=f"{as_of}T16:00:00+08:00",
        historical_replay=_historical_replay(request),
        store=AShareArchiveStore(),
        ledger=ledger,
    )
    build = compile_a_share_breadth_snapshot(
        archive,
        as_of_date=as_of,
        ledger=ledger,
    )
    if build.as_dict()["terminal_state"] != "READY":
        raise DataVendorUnavailable(
            "A-share breadth archive is blocked",
            reason_code="A_SHARE_BREADTH_ARCHIVE_BLOCKED",
        )


def _ensure_agent_stage_materialization_core(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    return TrustedAgentStagePreparer(
        ledger_factory=lambda: open_agent_data_materialization_ledger(create=True),
        family_preparers={
            **{key: prepare_china_agent_family for key in _CHINA_FAMILY_STAGES},
            **{key: prepare_us_macro_family for key in _US_FAMILY_STAGES},
            **{
                key: prepare_europe_macro_family for key in _EUROPE_FAMILY_STAGES
            },
            **{
                key: prepare_geopolitical_family
                for key in _GEOPOLITICAL_FAMILY_STAGES
            },
            **{
                key: prepare_market_breadth_family
                for key in _MARKET_BREADTH_FAMILY_STAGES
            },
            **{
                key: prepare_sector_relationship_family
                for key in _SECTOR_RELATIONSHIP_FAMILY_STAGES
            },
            **{key: prepare_bound_runtime_family for key in _BOUND_RUNTIME_FAMILY_STAGES},
        },
        always_prepare_stages=_BOUND_RUNTIME_FAMILY_STAGES,
    )(request)


def prepare_agent_stage_materialization_current_namespace(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Prepare one stage inside an already-selected runtime namespace."""
    return _ensure_agent_stage_materialization_core(request)


def ensure_agent_stage_materialization(request: Mapping[str, Any]) -> dict[str, Any]:
    """Run trusted materialization under the configured rollout authority."""
    if os.getenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS") == "structured_smoke":
        return {"status": "SYNTHETIC_NON_PRODUCTION_BYPASS"}
    mode = os.getenv("MOSAIC_ENSURE_SNAPSHOT_MODE")
    if mode not in {"off", "shadow", "enforce"}:
        raise DataVendorUnavailable(
            "MOSAIC_ENSURE_SNAPSHOT_MODE must be one of off, shadow, enforce"
        )
    core_request = dict(request)
    core_request.pop(_DEFERRED_REQUEST_ONLY_MARKER, None)
    core_request.pop(_DEFERRED_TOOL_IDS, None)
    if mode == "off":
        return {"ensure_mode": "off", "status": "OFF"}
    if mode == "enforce":
        agent_id = _required_text(request, "agent_id")
        stage = _required_text(request, "stage")
        as_of = _required_text(request, "as_of")
        date.fromisoformat(as_of)
        deferred_tool_ids = _deferred_request_only_tool_ids(request)
        if deferred_tool_ids is not None:
            stage_tool_ids = {
                binding["tool_id"] for binding in _stage_bindings(agent_id, stage)
            }
            if not set(deferred_tool_ids) <= stage_tool_ids:
                raise ValueError("deferred request-only tools are outside the stage")
        required_route_ids = {
            route_id
            for binding in _stage_bindings(agent_id, stage)
            for route_id in binding["required_route_ids"]
        }
        evaluated_at = datetime.now(timezone.utc).isoformat()
        if "composite.cn_rates" in required_route_ids and (
            production_license_receipt_ref(
                route_id="composite.cn_rates",
                evaluated_at=evaluated_at,
            )
            is None
        ):
            raise DataVendorUnavailable(
                "MOF/ChinaBond production use requires a named license decision receipt",
                reason_code="LICENSE_REVIEW_REQUIRED",
            )
        return {
            **_ensure_agent_stage_materialization_core(core_request),
            "ensure_mode": "enforce",
        }

    configured_shadow_root = os.getenv("MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT")
    shadow_root = (
        Path(configured_shadow_root).expanduser()
        if configured_shadow_root
        else agent_cache_root() / "agent_materialization_shadow"
    )
    try:
        with agent_runtime_root_override(shadow_root):
            shadow_result = _ensure_agent_stage_materialization_core(core_request)
    except DataVendorUnavailable:
        return {
            "blocker_codes": ["SHADOW_ENSURE_BLOCKED"],
            "ensure_mode": "shadow",
            "status": "SHADOW_BLOCKED",
        }
    return {
        "ensure_mode": "shadow",
        "shadow_status": shadow_result.get("status"),
        "status": "SHADOW_READY",
    }


def finalize_agent_stage_materialization(
    context: Mapping[str, Any],
    *,
    adaptive_query_store: FrozenAdaptiveQueryStore | None = None,
    staged_receipt_store: StagedQueryReceiptStore | None = None,
) -> dict[str, Any]:
    """Close the trusted stage receipt after capability payload materialization."""
    if os.getenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS") == "structured_smoke":
        return {"status": "SYNTHETIC_NON_PRODUCTION_BYPASS"}
    return TrustedAgentStageFinalizer(
        ledger_factory=lambda: open_agent_data_materialization_ledger(create=True),
        adaptive_query_store=adaptive_query_store,
        staged_receipt_store=staged_receipt_store,
    )(context)


__all__ = [
    "ADAPTIVE_QUERY_COMPILER_VERSION",
    "ADAPTIVE_QUERY_OUTPUT_CONTRACT_VERSION",
    "BOUND_RUNTIME_COMPILER_VERSION",
    "MATERIALIZATION_CONTRACT_VERSION",
    "SOURCE_ADMISSION_FAMILY_STAGE_GROUPS",
    "TrustedAgentStageFinalizer",
    "TrustedAgentStagePreparer",
    "US_MACRO_OBSERVATION_WINDOW_POLICY",
    "compile_adaptive_query_builds",
    "compile_sector_role_event_builds",
    "ensure_agent_stage_materialization",
    "finalize_agent_stage_materialization",
    "prepare_china_agent_family",
    "prepare_bound_runtime_family",
    "prepare_europe_macro_family",
    "prepare_geopolitical_family",
    "prepare_market_breadth_family",
    "prepare_agent_stage_materialization_current_namespace",
    "prepare_sector_relationship_family",
    "prepare_us_macro_family",
    "publish_ready_stage_materialization",
    "us_macro_observation_start",
]
