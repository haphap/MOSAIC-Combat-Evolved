"""Server-enforced, bundle-bound capabilities for model-callable tools.

The model never receives the signed envelope. The TypeScript runtime keeps it
out of band. Snapshot payloads are materialised before the model call;
every tool payload remains bundle-bound.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Final, Literal, Mapping, Sequence, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.agent_stage_preparer import (
    SOURCE_ADMISSION_FAMILY_STAGE_GROUPS,
    ensure_agent_stage_materialization,
    finalize_agent_stage_materialization,
    prepare_agent_stage_materialization_current_namespace,
    trusted_deferred_request_only_request,
)
from mosaic.dataflows.agent_materialization import (
    load_agent_data_route_manifest,
    open_agent_data_materialization_ledger,
)
from mosaic.dataflows.bound_runtime_snapshots import (
    bound_runtime_snapshot_relative_path,
    runtime_snapshot_root,
)
from mosaic.dataflows.bound_runtime_production import (
    ActiveAdaptiveQueryPreparer,
    BoundRuntimeAdaptiveQueryPreparer,
)
from mosaic.dataflows.cninfo_supply_chain import (
    CninfoSupplyChainDisclosureCollector,
)
from mosaic.dataflows.frozen_adaptive_queries import (
    CALL_TIME_ARGUMENT_CONTRACT,
    FrozenAdaptiveQueryStore,
    PUBLIC_PROJECTION_VERSION,
    deferred_query_bundle_hash,
)
from mosaic.dataflows.frozen_research_digest import FrozenResearchDigestBuilder
from mosaic.dataflows.forward_archive_queries import (
    ForwardArchiveQueryReader,
    ForwardArchiveSourcePreparer,
)
from mosaic.dataflows.interface import route_to_vendor
from mosaic.dataflows.macro_snapshots import render_role_snapshot
from mosaic.dataflows.market_breadth import render_market_breadth_snapshot
from mosaic.dataflows.role_events import render_role_event_snapshot
from mosaic.dataflows.sector_relationship_production import (
    SectorRelationshipAdaptiveQueryPreparer,
)
from mosaic.dataflows.sector_relationship_queries import (
    DIRECT_VENDOR_TOOL_IDS,
    SectorRelationshipQueryMaterializer,
)
from mosaic.dataflows.sector_relationship_source_evidence import (
    SectorRelationshipSourceEvidenceAuthority,
)
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.dataflows.supply_chain_disclosures import (
    OfficialSupplyChainDisclosureArchive,
)
from mosaic.dataflows.sector_snapshots import render_sector_snapshot
from mosaic.dataflows.runtime_paths import isolated_agent_runtime_path
from mosaic.scorecard.canonical_json import canonical_hash, canonical_json
from mosaic.scorecard.accepted_output_contracts import _validate_knot_capture_v2
from mosaic.scorecard.capability_preservation import (
    build_binding_signal_projection_v1,
    build_claim_comparison_specs_v1,
    build_knot_capability_use_aggregate,
    compare_binding_projection_v1,
    load_capability_contract_bundle,
    validate_public_safe_projection,
    validate_trusted_counterevidence_evaluation_v2,
    validate_capability_contract_bundle,
)
from mosaic.scorecard.l3_l4_activation import l3_l4_overlay_stage_for_active
from mosaic.scorecard.l3_l4_preservation import (
    argument_schema_for_binding as l3_l4_argument_schema_for_binding,
)
from mosaic.scorecard.sector_relationship_preservation import argument_schema_for_tool

AgentToolId = Literal[
    "get_china_macro_snapshot",
    "get_us_macro_snapshot",
    "get_eu_macro_snapshot",
    "get_central_bank_snapshot",
    "get_us_financial_conditions_snapshot",
    "get_euro_area_financial_conditions_snapshot",
    "get_commodity_conditions_snapshot",
    "get_geopolitical_events_snapshot",
    "get_market_breadth_snapshot",
    "get_market_positioning_snapshot",
    "get_sector_research_snapshot",
    "get_role_event_snapshot",
    "get_superinvestor_candidate_snapshot",
    "get_cro_risk_snapshot",
    "get_alpha_candidate_snapshot",
    "get_execution_snapshot",
    "get_cio_decision_snapshot",
    "get_balance_sheet",
    "get_broker_research",
    "get_cashflow",
    "get_etf_holdings",
    "get_fundamentals",
    "get_income_statement",
    "get_indicators",
    "get_industry_moneyflow",
    "get_industry_policy_digest",
    "get_rke_research_context",
    "get_stock_data",
    "get_stock_research",
    "get_supply_chain_evidence",
    "get_yield_curve_cn",
]

INITIAL_SNAPSHOT_TOOL_IDS: Final[tuple[AgentToolId, ...]] = (
    "get_china_macro_snapshot",
    "get_us_macro_snapshot",
    "get_eu_macro_snapshot",
    "get_central_bank_snapshot",
    "get_us_financial_conditions_snapshot",
    "get_euro_area_financial_conditions_snapshot",
    "get_commodity_conditions_snapshot",
    "get_geopolitical_events_snapshot",
    "get_market_breadth_snapshot",
    "get_market_positioning_snapshot",
    "get_sector_research_snapshot",
    "get_role_event_snapshot",
    "get_superinvestor_candidate_snapshot",
    "get_cro_risk_snapshot",
    "get_alpha_candidate_snapshot",
    "get_execution_snapshot",
    "get_cio_decision_snapshot",
)
AGENT_TOOL_IDS: Final[tuple[AgentToolId, ...]] = (
    *INITIAL_SNAPSHOT_TOOL_IDS,
    "get_balance_sheet",
    "get_broker_research",
    "get_cashflow",
    "get_etf_holdings",
    "get_fundamentals",
    "get_income_statement",
    "get_indicators",
    "get_industry_moneyflow",
    "get_industry_policy_digest",
    "get_rke_research_context",
    "get_stock_data",
    "get_stock_research",
    "get_supply_chain_evidence",
    "get_yield_curve_cn",
)
ADAPTIVE_QUERY_TOOL_IDS: Final[frozenset[AgentToolId]] = frozenset(
    set(AGENT_TOOL_IDS) - set(INITIAL_SNAPSHOT_TOOL_IDS)
)
QUERY_SCOPED_SOURCE_ROUTE_IDS: Final[frozenset[str]] = frozenset(
    {
        "official.company_supply_chain_disclosures",
        "official.govcn_policy",
        "private.rke_report_intelligence",
        "private.tushare_research_reports",
        "tushare.etf_holdings",
    }
)
def _load_runtime_tool_contract() -> tuple[
    tuple[str, ...], dict[str, tuple[str, ...]], dict[str, tuple[AgentToolId, ...]]
]:
    """Load the TypeScript-generated roster and tool whitelist artifact."""
    path = (
        Path(__file__).resolve().parents[2]
        / "registry"
        / "prompt_checks"
        / "agent_tool_contract_manifest_v1.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load canonical Agent tool contract: {exc}") from exc
    if payload.get("schema_version") != "agent_tool_contract_manifest_v1":
        raise RuntimeError("canonical Agent tool contract version mismatch")
    rows = payload.get("agents")
    if not isinstance(rows, list) or len(rows) != 27:
        raise RuntimeError("canonical Agent tool contract must contain 27 agents")

    agent_ids: list[str] = []
    by_layer: dict[str, list[str]] = {
        "macro": [],
        "sector": [],
        "superinvestor": [],
        "decision": [],
    }
    matrix: dict[str, tuple[AgentToolId, ...]] = {}
    known_tools = set(AGENT_TOOL_IDS)
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Agent tool contract rows must be objects")
        agent = row.get("agent_id")
        layer = row.get("layer")
        tools = row.get("allowed_tools")
        if not isinstance(agent, str) or not agent or agent in matrix:
            raise RuntimeError("Agent tool contract has an invalid or duplicate agent")
        if layer not in by_layer:
            raise RuntimeError(f"Agent tool contract has unknown layer {layer!r}")
        if (
            not isinstance(tools, list)
            or not tools
            or any(not isinstance(tool, str) or tool not in known_tools for tool in tools)
            or len(tools) != len(set(tools))
        ):
            raise RuntimeError(f"Agent tool contract has invalid tools for {agent}")
        agent_ids.append(agent)
        by_layer[layer].append(agent)
        matrix[agent] = cast(tuple[AgentToolId, ...], tuple(tools))

    if len(agent_ids) != len(set(agent_ids)) or payload.get("agent_count") != 27:
        raise RuntimeError("Agent tool contract roster count mismatch")
    return (
        tuple(agent_ids),
        {layer: tuple(agents) for layer, agents in by_layer.items()},
        matrix,
    )


ALL_AGENT_IDS, AGENTS_BY_LAYER, AGENT_TOOL_MATRIX = _load_runtime_tool_contract()
STANDARD_SECTOR_AGENTS: Final[tuple[str, ...]] = AGENTS_BY_LAYER["sector"]
SUPERINVESTOR_AGENTS: Final[tuple[str, ...]] = AGENTS_BY_LAYER["superinvestor"]
DECISION_AGENTS: Final[tuple[str, ...]] = AGENTS_BY_LAYER["decision"]
MACRO_AGENT_TO_TOOL: Final[dict[str, AgentToolId]] = {
    agent: AGENT_TOOL_MATRIX[agent][0] for agent in AGENTS_BY_LAYER["macro"]
}
if any(len(AGENT_TOOL_MATRIX[agent]) != 1 for agent in MACRO_AGENT_TO_TOOL):
    raise RuntimeError("every Macro agent must have exactly one role snapshot tool")

TOOL_DESCRIPTIONS: Final[dict[AgentToolId, str]] = {
    "get_china_macro_snapshot": "Return the frozen China macro snapshot for this run.",
    "get_us_macro_snapshot": "Return the frozen US real-economy snapshot for this run.",
    "get_eu_macro_snapshot": "Return the frozen EU real-economy snapshot for this run.",
    "get_central_bank_snapshot": "Return the frozen PBOC and China rates snapshot.",
    "get_us_financial_conditions_snapshot": "Return the frozen US financial-conditions snapshot.",
    "get_euro_area_financial_conditions_snapshot": "Return the frozen euro-area financial-conditions snapshot.",
    "get_commodity_conditions_snapshot": "Return the frozen commodity-conditions snapshot.",
    "get_geopolitical_events_snapshot": "Return the frozen verified geopolitical-event snapshot.",
    "get_market_breadth_snapshot": "Return the frozen deterministic A-share breadth snapshot.",
    "get_market_positioning_snapshot": "Return the frozen A-share positioning snapshot.",
    "get_sector_research_snapshot": "Return the frozen role-scoped Sector research snapshot.",
    "get_role_event_snapshot": "Return the frozen event projection for the bound role.",
    "get_superinvestor_candidate_snapshot": "Return the frozen candidate view for this investment philosophy.",
    "get_cro_risk_snapshot": "Return the frozen CRO risk and constraint snapshot.",
    "get_alpha_candidate_snapshot": "Return the frozen novel-alpha candidate snapshot.",
    "get_execution_snapshot": "Return the frozen execution-feasibility snapshot.",
    "get_cio_decision_snapshot": "Return the frozen CIO proposal or final decision snapshot.",
    "get_balance_sheet": "Return one exact frozen balance-sheet query.",
    "get_broker_research": "Return one exact frozen broker-research query.",
    "get_cashflow": "Return one exact frozen cash-flow statement query.",
    "get_etf_holdings": "Return one exact frozen ETF-holdings query.",
    "get_fundamentals": "Return one exact frozen company-fundamentals query.",
    "get_income_statement": "Return one exact frozen income-statement query.",
    "get_indicators": "Return one exact frozen technical-indicator query.",
    "get_industry_moneyflow": "Return one exact frozen industry-moneyflow query.",
    "get_industry_policy_digest": "Return one exact frozen industry-policy query.",
    "get_rke_research_context": "Return one exact frozen RKE research-context query.",
    "get_stock_data": "Return one exact frozen stock-market-data query.",
    "get_stock_research": "Return one exact frozen stock-research query.",
    "get_supply_chain_evidence": "Return one exact frozen authoritative supply-chain query.",
    "get_yield_curve_cn": "Return one exact frozen China yield-curve query.",
}
if set(TOOL_DESCRIPTIONS) != set(AGENT_TOOL_IDS):
    raise RuntimeError("tool description registry must exactly cover AgentToolId")

SNAPSHOT_BUNDLE_CONTRACT_VERSION: Final = "agent_snapshot_bundle_v1"
CAPABILITY_CONTRACT_VERSION: Final = "agent_tool_capability_v1"
DEFAULT_CAPABILITY_TTL_SECONDS: Final = 900
SECTOR_USAGE_SUMMARY_RECEIPT_VERSION: Final = (
    "sector_model_usage_summary_receipt_v1"
)
SECTOR_USAGE_INSTRUMENTATION_CONTRACT: Final[dict[str, str]] = {
    "instrumentation_contract_id": "sector_inference_usage_instrumentation",
    "instrumentation_contract_version": "sector_inference_usage_instrumentation_v1",
    "source_contract_version": "server_owned_model_usage_ledger_v1",
    "measurement_rule": "sum_provider_reported_tokens_and_count_attempted_model_subcalls",
}


def _canonical_json(value: Any) -> str:
    return canonical_json(value)


def _sha256(value: Any) -> str:
    return canonical_hash(value)


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _prepared_initial_tool_ids(projection: Mapping[str, Any]) -> list[str]:
    projection_hash = projection.get("projection_hash")
    projection_body = {
        key: value for key, value in projection.items() if key != "projection_hash"
    }
    entries = projection.get("entries")
    if (
        not _is_sha256(projection_hash)
        or projection_hash != _sha256(projection_body)
        or not isinstance(entries, list)
    ):
        raise ValueError("adaptive query public projection is invalid")
    initial_tool_ids: set[str] = set()
    initial_count = 0
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("call_mode") not in {
            "INITIAL",
            "FOLLOW_UP",
        }:
            raise ValueError("adaptive query public projection entry is invalid")
        if entry["call_mode"] != "INITIAL":
            continue
        tool_id = entry.get("tool_id")
        if not isinstance(tool_id, str) or tool_id not in ADAPTIVE_QUERY_TOOL_IDS:
            raise ValueError("adaptive query initial tool is invalid")
        initial_count += 1
        initial_tool_ids.add(tool_id)
    if projection.get("initial_payload_count") != initial_count:
        raise ValueError("adaptive query initial payload count is invalid")
    return sorted(initial_tool_ids)


SECTOR_USAGE_INSTRUMENTATION_CONTRACT_HASH: Final = _sha256(
    SECTOR_USAGE_INSTRUMENTATION_CONTRACT
)

BOUND_RUNTIME_SNAPSHOT_CONTRACTS: Final[dict[AgentToolId, str]] = {
    "get_superinvestor_candidate_snapshot": "superinvestor_candidate_snapshot_v1",
    "get_cro_risk_snapshot": "cro_risk_snapshot_v1",
    "get_alpha_candidate_snapshot": "alpha_candidate_snapshot_v1",
    "get_execution_snapshot": "execution_snapshot_v1",
    "get_cio_decision_snapshot": "cio_decision_snapshot_v1",
}
_A_SHARE_CODE = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_FORBIDDEN_SOURCE_PROSE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "abstract",
        "article_body",
        "body",
        "claim_text",
        "content",
        "document_text",
        "raw_content",
        "raw_text",
        "source_excerpt",
        "source_prose",
        "source_span",
        "source_span_ids",
        "source_text",
        "title",
    }
)


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _aware_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def execution_stage_for_agent(agent_id: str, requested_stage: str | None = None) -> str:
    """Return one of the 28 closed execution-stage identifiers."""
    if agent_id not in ALL_AGENT_IDS:
        raise ValueError(f"unknown v3 agent_id {agent_id!r}")
    if agent_id != "cio":
        expected = agent_id
        if requested_stage not in (None, expected):
            raise ValueError(f"{agent_id} capability stage must be {expected!r}")
        return expected
    if requested_stage not in ("cio_proposal", "cio_final"):
        raise ValueError("cio capability stage must be 'cio_proposal' or 'cio_final'")
    return requested_stage


def allowed_tools_for_agent(agent_id: str) -> tuple[AgentToolId, ...]:
    try:
        return AGENT_TOOL_MATRIX[agent_id]
    except KeyError as exc:
        raise ValueError(f"unknown v3 agent_id {agent_id!r}") from exc


def _runtime_snapshot_root() -> Path:
    return runtime_snapshot_root()


def _bounded_identifier_schema() -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": 256}


def _sha256_schema() -> dict[str, Any]:
    return {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"}


def _structured_scalar_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            {"type": "number"},
            {"type": "boolean"},
            {"type": "null"},
            {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
                "pattern": r"^[A-Za-z0-9_.:+/-]+$",
            },
        ]
    }


def _evidence_ids_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": 32,
        "uniqueItems": True,
        "items": _bounded_identifier_schema(),
    }


def _unit_interval_schema() -> dict[str, Any]:
    return {"type": "number", "minimum": 0, "maximum": 1}


def _nullable_sha256_schema() -> dict[str, Any]:
    return {"oneOf": [_sha256_schema(), {"type": "null"}]}


def _nullable_identifier_schema() -> dict[str, Any]:
    return {"oneOf": [_bounded_identifier_schema(), {"type": "null"}]}


def _bounded_metrics_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "minProperties": 1,
        "maxProperties": 64,
        "propertyNames": {
            "type": "string",
            "pattern": r"^[A-Za-z0-9_.:-]{1,96}$",
        },
        "additionalProperties": _structured_scalar_schema(),
    }


def _accepted_output_ref_schema(accepted_output_kinds: Sequence[str]) -> dict[str, Any]:
    identifier = _bounded_identifier_schema()
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "accepted_output_id",
            "accepted_output_hash",
            "accepted_output_kind",
            "agent_id",
            "stage",
            "as_of",
            "evidence_ids",
        ],
        "properties": {
            "accepted_output_id": identifier,
            "accepted_output_hash": _sha256_schema(),
            "accepted_output_kind": {"enum": list(accepted_output_kinds)},
            "agent_id": identifier,
            "stage": identifier,
            "as_of": {"type": "string", "format": "date"},
            "evidence_ids": _evidence_ids_schema(),
        },
    }


def _candidate_schema(
    *, required: Sequence[str], properties: Mapping[str, Any]
) -> dict[str, Any]:
    base_properties: dict[str, Any] = {
        "candidate_ref": _bounded_identifier_schema(),
        "ts_code": {
            "type": "string",
            "pattern": r"^[0-9]{6}\.(?:SH|SZ|BJ)$",
        },
        "metrics": _bounded_metrics_schema(),
        "evidence_ids": _evidence_ids_schema(),
    }
    base_properties.update(properties)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "candidate_ref",
            "ts_code",
            *required,
            "metrics",
            "evidence_ids",
        ],
        "properties": base_properties,
    }


def _constraint_object_schema(
    *, required: Sequence[str], properties: Mapping[str, Any]
) -> dict[str, Any]:
    all_properties: dict[str, Any] = {
        **properties,
        "evidence_ids": _evidence_ids_schema(),
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [*required, "evidence_ids"],
        "properties": all_properties,
    }


def _runtime_control_source_schema(
    *, agent_id: str, accepted_output_kind: str
) -> dict[str, Any]:
    return {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_status",
                    "agent_id",
                    "accepted_output_kind",
                    "accepted_output_id",
                    "accepted_output_hash",
                    "stage_skip_id",
                    "stage_skip_hash",
                ],
                "properties": {
                    "source_status": {"const": "ACCEPTED_OUTPUT"},
                    "agent_id": {"const": agent_id},
                    "accepted_output_kind": {"const": accepted_output_kind},
                    "accepted_output_id": _bounded_identifier_schema(),
                    "accepted_output_hash": _sha256_schema(),
                    "stage_skip_id": {"type": "null"},
                    "stage_skip_hash": {"type": "null"},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_status",
                    "agent_id",
                    "accepted_output_kind",
                    "accepted_output_id",
                    "accepted_output_hash",
                    "stage_skip_id",
                    "stage_skip_hash",
                ],
                "properties": {
                    "source_status": {"const": "NO_EVALUATION_OBJECT"},
                    "agent_id": {"const": agent_id},
                    "accepted_output_kind": {"const": accepted_output_kind},
                    "accepted_output_id": {"type": "null"},
                    "accepted_output_hash": {"type": "null"},
                    "stage_skip_id": _bounded_identifier_schema(),
                    "stage_skip_hash": _sha256_schema(),
                },
            },
        ]
    }


def _bound_runtime_snapshot_envelope_schema(
    contract_version: str,
    *,
    agent_schema: Mapping[str, Any],
    stage_schema: Mapping[str, Any],
    candidate_schema: Mapping[str, Any],
    constraints_schema: Mapping[str, Any],
    role_context_schema: Mapping[str, Any],
    accepted_output_kinds: Sequence[str],
) -> dict[str, Any]:
    identifier = _bounded_identifier_schema()
    sha256 = _sha256_schema()
    scalar = _structured_scalar_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://mosaic.local/schemas/{contract_version}.schema.json",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "contract_version",
            "snapshot_id",
            "snapshot_hash",
            "graph_run_id",
            "agent_id",
            "stage",
            "as_of",
            "generated_at",
            "pit_status",
            "candidate_scope",
            "candidate_scope_hash",
            "candidate_universe_id",
            "candidate_universe_hash",
            "candidate_status",
            "candidate_universe",
            "constraint_set_id",
            "constraint_set_hash",
            "constraints",
            "role_context",
            "role_context_hash",
            "upstream_accepted_output_refs",
            "evidence_ledger",
        ],
        "properties": {
            "schema_version": {"const": contract_version},
            "contract_version": {"const": contract_version},
            "snapshot_id": identifier,
            "snapshot_hash": sha256,
            "graph_run_id": identifier,
            "agent_id": dict(agent_schema),
            "stage": dict(stage_schema),
            "as_of": {"type": "string", "format": "date"},
            "generated_at": {"type": "string", "format": "date-time"},
            "pit_status": {"const": "VERIFIED"},
            "candidate_scope": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_universe_id",
                    "candidate_universe_hash",
                    "constraint_set_id",
                    "constraint_set_hash",
                ],
                "properties": {
                    "candidate_universe_id": identifier,
                    "candidate_universe_hash": sha256,
                    "constraint_set_id": identifier,
                    "constraint_set_hash": sha256,
                },
            },
            "candidate_scope_hash": sha256,
            "candidate_universe_id": identifier,
            "candidate_universe_hash": sha256,
            "candidate_status": {"enum": ["AVAILABLE", "EMPTY_CONFIRMED"]},
            "candidate_universe": {
                "type": "array",
                "maxItems": 1000,
                "items": dict(candidate_schema),
            },
            "constraint_set_id": identifier,
            "constraint_set_hash": sha256,
            "constraints": dict(constraints_schema),
            "role_context": dict(role_context_schema),
            "role_context_hash": sha256,
            "upstream_accepted_output_refs": {
                "type": "array",
                "minItems": 1,
                "maxItems": 128,
                "items": _accepted_output_ref_schema(accepted_output_kinds),
            },
            "evidence_ledger": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2048,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "evidence_id",
                        "source_kind",
                        "source_id",
                        "metric",
                        "value",
                        "unit",
                        "as_of",
                        "available_at",
                        "source_fingerprint",
                    ],
                    "properties": {
                        "evidence_id": identifier,
                        "source_kind": {
                            "enum": [
                                "ACCEPTED_OUTPUT",
                                "ACCOUNT_SNAPSHOT",
                                "DERIVED_METRIC",
                                "MARKET_SNAPSHOT",
                                "POLICY_CONSTRAINT",
                                "POSITION_SNAPSHOT",
                            ]
                        },
                        "source_id": identifier,
                        "metric": {
                            "type": "string",
                            "pattern": r"^[A-Za-z0-9_.:-]{1,128}$",
                        },
                        "value": scalar,
                        "unit": {
                            "type": "string",
                            "pattern": r"^[A-Za-z0-9_.%:+/-]{1,64}$",
                        },
                        "as_of": {"type": "string", "format": "date"},
                        "available_at": {"type": "string", "format": "date-time"},
                        "source_fingerprint": sha256,
                    },
                },
            },
        },
    }


def _superinvestor_candidate_snapshot_schema() -> dict[str, Any]:
    contract = BOUND_RUNTIME_SNAPSHOT_CONTRACTS[
        "get_superinvestor_candidate_snapshot"
    ]
    candidate = _candidate_schema(
        required=(
            "source_output_id",
            "source_output_hash",
            "source_sector_agent_id",
            "source_direction_id",
            "source_direction",
        ),
        properties={
            "source_output_id": _bounded_identifier_schema(),
            "source_output_hash": _sha256_schema(),
            "source_sector_agent_id": {"enum": list(STANDARD_SECTOR_AGENTS)},
            "source_direction_id": _bounded_identifier_schema(),
            "source_direction": {"enum": ["PREFERRED", "LEAST_PREFERRED"]},
        },
    )
    constraints = _constraint_object_schema(
        required=(
            "cash_only",
            "allow_new_positions",
            "max_pick_count",
            "max_total_conviction",
            "prohibited_ts_codes",
        ),
        properties={
            "cash_only": {"type": "boolean"},
            "allow_new_positions": {"type": "boolean"},
            "max_pick_count": {"type": "integer", "minimum": 1, "maximum": 10},
            "max_total_conviction": _unit_interval_schema(),
            "prohibited_ts_codes": {
                "type": "array",
                "maxItems": 1000,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": _A_SHARE_CODE.pattern},
            },
        },
    )
    role_context = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "context_kind",
            "candidate_origin_set_id",
            "candidate_origin_set_hash",
            "evidence_ids",
        ],
        "properties": {
            "context_kind": {"const": "SUPERINVESTOR_CANDIDATE_SELECTION"},
            "candidate_origin_set_id": _bounded_identifier_schema(),
            "candidate_origin_set_hash": _sha256_schema(),
            "evidence_ids": _evidence_ids_schema(),
        },
    }
    return _bound_runtime_snapshot_envelope_schema(
        contract,
        agent_schema={"enum": list(SUPERINVESTOR_AGENTS)},
        stage_schema={"enum": list(SUPERINVESTOR_AGENTS)},
        candidate_schema=candidate,
        constraints_schema=constraints,
        role_context_schema=role_context,
        accepted_output_kinds=(
            "MACRO_TRANSMISSION",
            "STANDARD_SECTOR_SELECTION",
        ),
    )


def _alpha_candidate_snapshot_schema() -> dict[str, Any]:
    contract = BOUND_RUNTIME_SNAPSHOT_CONTRACTS["get_alpha_candidate_snapshot"]
    candidate = _candidate_schema(
        required=(
            "source_output_id",
            "source_output_hash",
            "source_agent_id",
            "source_candidate_ref",
            "omitted_by_superinvestor_agents",
        ),
        properties={
            "source_output_id": _bounded_identifier_schema(),
            "source_output_hash": _sha256_schema(),
            "source_agent_id": {"enum": list(AGENTS_BY_LAYER["sector"])},
            "source_candidate_ref": _bounded_identifier_schema(),
            "omitted_by_superinvestor_agents": {
                "type": "array",
                "minItems": len(SUPERINVESTOR_AGENTS),
                "maxItems": len(SUPERINVESTOR_AGENTS),
                "uniqueItems": True,
                "items": {"enum": list(SUPERINVESTOR_AGENTS)},
            },
        },
    )
    constraints = _constraint_object_schema(
        required=(
            "cash_only",
            "allow_new_positions",
            "max_novel_pick_count",
            "excluded_selected_ts_codes",
        ),
        properties={
            "cash_only": {"type": "boolean"},
            "allow_new_positions": {"type": "boolean"},
            "max_novel_pick_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
            },
            "excluded_selected_ts_codes": {
                "type": "array",
                "maxItems": 1000,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": _A_SHARE_CODE.pattern},
            },
        },
    )
    role_context = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "context_kind",
            "superinvestor_selection_set_id",
            "superinvestor_selection_set_hash",
            "excluded_security_set_id",
            "excluded_security_set_hash",
            "evidence_ids",
        ],
        "properties": {
            "context_kind": {"const": "ALPHA_NOVELTY_SEARCH"},
            "superinvestor_selection_set_id": _bounded_identifier_schema(),
            "superinvestor_selection_set_hash": _sha256_schema(),
            "excluded_security_set_id": _bounded_identifier_schema(),
            "excluded_security_set_hash": _sha256_schema(),
            "evidence_ids": _evidence_ids_schema(),
        },
    }
    return _bound_runtime_snapshot_envelope_schema(
        contract,
        agent_schema={"const": "alpha_discovery"},
        stage_schema={"const": "alpha_discovery"},
        candidate_schema=candidate,
        constraints_schema=constraints,
        role_context_schema=role_context,
        accepted_output_kinds=(
            "STANDARD_SECTOR_SELECTION",
            "SUPERINVESTOR_SELECTION",
        ),
    )


def _cro_risk_snapshot_schema() -> dict[str, Any]:
    contract = BOUND_RUNTIME_SNAPSHOT_CONTRACTS["get_cro_risk_snapshot"]
    candidate = _candidate_schema(
        required=(
            "proposal_position_ref",
            "current_weight",
            "proposed_target_weight",
            "proposed_delta_weight",
            "sector_id",
        ),
        properties={
            "proposal_position_ref": _bounded_identifier_schema(),
            "current_weight": _unit_interval_schema(),
            "proposed_target_weight": _unit_interval_schema(),
            "proposed_delta_weight": {
                "type": "number",
                "minimum": -1,
                "maximum": 1,
            },
            "sector_id": _bounded_identifier_schema(),
        },
    )
    constraints = _constraint_object_schema(
        required=(
            "max_total_target_weight",
            "max_single_name_weight",
            "max_sector_weight",
            "restricted_ts_codes",
        ),
        properties={
            "max_total_target_weight": _unit_interval_schema(),
            "max_single_name_weight": _unit_interval_schema(),
            "max_sector_weight": _unit_interval_schema(),
            "restricted_ts_codes": {
                "type": "array",
                "maxItems": 1000,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": _A_SHARE_CODE.pattern},
            },
        },
    )
    role_context = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "context_kind",
            "proposal_accepted_output_id",
            "proposal_accepted_output_hash",
            "position_snapshot_id",
            "position_snapshot_hash",
            "portfolio_exposure_snapshot_id",
            "portfolio_exposure_snapshot_hash",
            "evidence_ids",
        ],
        "properties": {
            "context_kind": {"const": "CRO_PROPOSAL_RISK_REVIEW"},
            "proposal_accepted_output_id": _bounded_identifier_schema(),
            "proposal_accepted_output_hash": _sha256_schema(),
            "position_snapshot_id": _bounded_identifier_schema(),
            "position_snapshot_hash": _sha256_schema(),
            "portfolio_exposure_snapshot_id": _bounded_identifier_schema(),
            "portfolio_exposure_snapshot_hash": _sha256_schema(),
            "evidence_ids": _evidence_ids_schema(),
        },
    }
    return _bound_runtime_snapshot_envelope_schema(
        contract,
        agent_schema={"const": "cro"},
        stage_schema={"const": "cro"},
        candidate_schema=candidate,
        constraints_schema=constraints,
        role_context_schema=role_context,
        accepted_output_kinds=("CIO_PROPOSAL",),
    )


def _execution_snapshot_schema() -> dict[str, Any]:
    contract = BOUND_RUNTIME_SNAPSHOT_CONTRACTS["get_execution_snapshot"]
    candidate = _candidate_schema(
        required=(
            "order_intent_ref",
            "current_weight",
            "target_weight",
            "requested_delta_weight",
            "side",
        ),
        properties={
            "order_intent_ref": _bounded_identifier_schema(),
            "current_weight": _unit_interval_schema(),
            "target_weight": _unit_interval_schema(),
            "requested_delta_weight": {
                "type": "number",
                "minimum": -1,
                "maximum": 1,
            },
            "side": {"enum": ["BUY", "SELL", "HOLD"]},
        },
    )
    constraints = _constraint_object_schema(
        required=(
            "execution_mode",
            "max_slippage_bps",
            "max_participation_rate",
            "min_trade_weight",
            "max_slice_count",
            "prohibited_ts_codes",
        ),
        properties={
            "execution_mode": {"enum": ["PAPER", "REAL"]},
            "max_slippage_bps": {"type": "number", "minimum": 0},
            "max_participation_rate": _unit_interval_schema(),
            "min_trade_weight": _unit_interval_schema(),
            "max_slice_count": {"type": "integer", "minimum": 1, "maximum": 100},
            "prohibited_ts_codes": {
                "type": "array",
                "maxItems": 1000,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": _A_SHARE_CODE.pattern},
            },
        },
    )
    role_context = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "context_kind",
            "proposal_accepted_output_id",
            "proposal_accepted_output_hash",
            "cro_control_source",
            "order_intent_set_id",
            "order_intent_set_hash",
            "liquidity_vintage_hash",
            "evidence_ids",
        ],
        "properties": {
            "context_kind": {"const": "EXECUTION_ORDER_FEASIBILITY"},
            "proposal_accepted_output_id": _bounded_identifier_schema(),
            "proposal_accepted_output_hash": _sha256_schema(),
            "cro_control_source": _runtime_control_source_schema(
                agent_id="cro", accepted_output_kind="CRO_RISK_REVIEW"
            ),
            "order_intent_set_id": _bounded_identifier_schema(),
            "order_intent_set_hash": _sha256_schema(),
            "liquidity_vintage_hash": _sha256_schema(),
            "evidence_ids": _evidence_ids_schema(),
        },
    }
    return _bound_runtime_snapshot_envelope_schema(
        contract,
        agent_schema={"const": "autonomous_execution"},
        stage_schema={"const": "autonomous_execution"},
        candidate_schema=candidate,
        constraints_schema=constraints,
        role_context_schema=role_context,
        accepted_output_kinds=("CIO_PROPOSAL", "CRO_RISK_REVIEW"),
    )


def _cio_decision_snapshot_schema() -> dict[str, Any]:
    contract = BOUND_RUNTIME_SNAPSHOT_CONTRACTS["get_cio_decision_snapshot"]
    nullable_weight = {"oneOf": [_unit_interval_schema(), {"type": "null"}]}
    proposal_candidate = _candidate_schema(
        required=(
            "source_kind",
            "current_weight",
            "reference_target_weight",
            "source_output_id",
            "source_output_hash",
        ),
        properties={
            "source_kind": {
                "enum": [
                    "CURRENT_POSITION",
                    "SECTOR_SELECTION",
                    "SUPERINVESTOR_SELECTION",
                    "ALPHA_DISCOVERY",
                ]
            },
            "current_weight": _unit_interval_schema(),
            "reference_target_weight": nullable_weight,
            "source_output_id": _nullable_identifier_schema(),
            "source_output_hash": _nullable_sha256_schema(),
        },
    )
    final_candidate = _candidate_schema(
        required=(
            "proposal_position_ref",
            "current_weight",
            "proposed_target_weight",
            "proposed_delta_weight",
        ),
        properties={
            "proposal_position_ref": _bounded_identifier_schema(),
            "current_weight": _unit_interval_schema(),
            "proposed_target_weight": _unit_interval_schema(),
            "proposed_delta_weight": {
                "type": "number",
                "minimum": -1,
                "maximum": 1,
            },
        },
    )
    constraints = _constraint_object_schema(
        required=(
            "max_total_target_weight",
            "min_cash_weight",
            "max_single_name_weight",
            "restricted_ts_codes",
        ),
        properties={
            "max_total_target_weight": _unit_interval_schema(),
            "min_cash_weight": _unit_interval_schema(),
            "max_single_name_weight": _unit_interval_schema(),
            "restricted_ts_codes": {
                "type": "array",
                "maxItems": 1000,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": _A_SHARE_CODE.pattern},
            },
        },
    )
    proposal_context = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "context_kind",
            "decision_stage",
            "position_snapshot_id",
            "position_snapshot_hash",
            "previous_target_id",
            "previous_target_hash",
            "evidence_ids",
        ],
        "properties": {
            "context_kind": {"const": "CIO_PORTFOLIO_DECISION"},
            "decision_stage": {"const": "PROPOSAL"},
            "position_snapshot_id": _bounded_identifier_schema(),
            "position_snapshot_hash": _sha256_schema(),
            "previous_target_id": _nullable_identifier_schema(),
            "previous_target_hash": _nullable_sha256_schema(),
            "evidence_ids": _evidence_ids_schema(),
        },
    }
    final_context = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "context_kind",
            "decision_stage",
            "proposal_accepted_output_id",
            "proposal_accepted_output_hash",
            "cro_control_source",
            "execution_control_source",
            "evidence_ids",
        ],
        "properties": {
            "context_kind": {"const": "CIO_PORTFOLIO_DECISION"},
            "decision_stage": {"const": "FINAL"},
            "proposal_accepted_output_id": _bounded_identifier_schema(),
            "proposal_accepted_output_hash": _sha256_schema(),
            "cro_control_source": _runtime_control_source_schema(
                agent_id="cro", accepted_output_kind="CRO_RISK_REVIEW"
            ),
            "execution_control_source": _runtime_control_source_schema(
                agent_id="autonomous_execution",
                accepted_output_kind="EXECUTION_ASSESSMENT",
            ),
            "evidence_ids": _evidence_ids_schema(),
        },
    }
    schema = _bound_runtime_snapshot_envelope_schema(
        contract,
        agent_schema={"const": "cio"},
        stage_schema={"enum": ["cio_proposal", "cio_final"]},
        candidate_schema={"oneOf": [proposal_candidate, final_candidate]},
        constraints_schema=constraints,
        role_context_schema={"oneOf": [proposal_context, final_context]},
        accepted_output_kinds=(
            "MACRO_TRANSMISSION",
            "STANDARD_SECTOR_SELECTION",
            "SUPERINVESTOR_SELECTION",
            "ALPHA_DISCOVERY",
            "CRO_RISK_REVIEW",
            "EXECUTION_ASSESSMENT",
            "CIO_PROPOSAL",
        ),
    )
    schema["allOf"] = [
        {
            "if": {
                "properties": {"stage": {"const": "cio_proposal"}},
                "required": ["stage"],
            },
            "then": {
                "properties": {
                    "candidate_universe": {
                        "type": "array",
                        "maxItems": 1000,
                        "items": proposal_candidate,
                    },
                    "role_context": proposal_context,
                }
            },
        },
        {
            "if": {
                "properties": {"stage": {"const": "cio_final"}},
                "required": ["stage"],
            },
            "then": {
                "properties": {
                    "candidate_universe": {
                        "type": "array",
                        "maxItems": 1000,
                        "items": final_candidate,
                    },
                    "role_context": final_context,
                }
            },
        },
    ]
    return schema


BOUND_RUNTIME_SNAPSHOT_SCHEMAS: Final[dict[AgentToolId, dict[str, Any]]] = {
    "get_superinvestor_candidate_snapshot": _superinvestor_candidate_snapshot_schema(),
    "get_cro_risk_snapshot": _cro_risk_snapshot_schema(),
    "get_alpha_candidate_snapshot": _alpha_candidate_snapshot_schema(),
    "get_execution_snapshot": _execution_snapshot_schema(),
    "get_cio_decision_snapshot": _cio_decision_snapshot_schema(),
}


def _reject_source_prose(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_SOURCE_PROSE_FIELDS:
                raise DataVendorUnavailable(
                    f"runtime snapshot contains forbidden source prose at {path}.{key}"
                )
            _reject_source_prose(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_source_prose(item, path=f"{path}[{index}]")


def _accepted_output_lineage(agent_id: str, stage: str, kind: str) -> bool:
    if agent_id in AGENTS_BY_LAYER["macro"]:
        return stage == agent_id and kind == "MACRO_TRANSMISSION"
    if agent_id in STANDARD_SECTOR_AGENTS:
        return stage == agent_id and kind == "STANDARD_SECTOR_SELECTION"
    if agent_id in SUPERINVESTOR_AGENTS:
        return stage == agent_id and kind == "SUPERINVESTOR_SELECTION"
    return (agent_id, stage, kind) in {
        ("alpha_discovery", "alpha_discovery", "ALPHA_DISCOVERY"),
        ("cro", "cro", "CRO_RISK_REVIEW"),
        (
            "autonomous_execution",
            "autonomous_execution",
            "EXECUTION_ASSESSMENT",
        ),
        ("cio", "cio_proposal", "CIO_PROPOSAL"),
        ("cio", "cio_final", "CIO_FINAL"),
    }


def _allowed_upstream_lineage(
    tool_id: AgentToolId, target_stage: str, ref: Mapping[str, Any]
) -> bool:
    agent = str(ref["agent_id"])
    stage = str(ref["stage"])
    kind = str(ref["accepted_output_kind"])
    if not _accepted_output_lineage(agent, stage, kind):
        return False
    macro = set(AGENTS_BY_LAYER["macro"])
    sector = set(AGENTS_BY_LAYER["sector"])
    superinvestor = set(SUPERINVESTOR_AGENTS)
    allowed_agents: set[str]
    if tool_id == "get_superinvestor_candidate_snapshot":
        allowed_agents = macro | sector
    elif tool_id == "get_alpha_candidate_snapshot":
        allowed_agents = macro | sector | superinvestor
    elif tool_id == "get_cro_risk_snapshot":
        allowed_agents = {"alpha_discovery", "cio"}
        if agent == "cio" and stage != "cio_proposal":
            return False
    elif tool_id == "get_execution_snapshot":
        allowed_agents = {"cro", "cio"}
        if agent == "cio" and stage != "cio_proposal":
            return False
    elif tool_id == "get_cio_decision_snapshot" and target_stage == "cio_proposal":
        allowed_agents = macro | sector | superinvestor | {"alpha_discovery"}
    elif tool_id == "get_cio_decision_snapshot" and target_stage == "cio_final":
        allowed_agents = {"cio", "cro", "autonomous_execution"}
        if agent == "cio" and stage != "cio_proposal":
            return False
    else:
        return False
    return agent in allowed_agents


def _accepted_ref_matches(
    ref: Mapping[str, Any],
    *,
    accepted_output_id: Any,
    accepted_output_hash: Any,
    accepted_output_kind: str,
    agent_id: str | None = None,
) -> bool:
    return (
        ref["accepted_output_id"] == accepted_output_id
        and ref["accepted_output_hash"] == accepted_output_hash
        and ref["accepted_output_kind"] == accepted_output_kind
        and (agent_id is None or ref["agent_id"] == agent_id)
    )


def _assert_control_source_closure(
    source: Mapping[str, Any],
    refs: Sequence[Mapping[str, Any]],
) -> None:
    if source["source_status"] == "NO_EVALUATION_OBJECT":
        if any(
            ref["accepted_output_kind"] == source["accepted_output_kind"]
            and ref["agent_id"] == source["agent_id"]
            for ref in refs
        ):
            raise DataVendorUnavailable(
                "runtime control stage skip masks an upstream accepted output"
            )
        return
    if not any(
        _accepted_ref_matches(
            ref,
            accepted_output_id=source["accepted_output_id"],
            accepted_output_hash=source["accepted_output_hash"],
            accepted_output_kind=str(source["accepted_output_kind"]),
            agent_id=str(source["agent_id"]),
        )
        for ref in refs
    ):
        raise DataVendorUnavailable(
            "runtime control source is not closed by an upstream accepted output"
        )


def _assert_proposal_ref_closure(
    role_context: Mapping[str, Any], refs: Sequence[Mapping[str, Any]]
) -> None:
    if not any(
        _accepted_ref_matches(
            ref,
            accepted_output_id=role_context["proposal_accepted_output_id"],
            accepted_output_hash=role_context["proposal_accepted_output_hash"],
            accepted_output_kind="CIO_PROPOSAL",
            agent_id="cio",
        )
        for ref in refs
    ):
        raise DataVendorUnavailable(
            "runtime proposal binding is not closed by the accepted CIO proposal"
        )


def _assert_weight_delta(
    candidate: Mapping[str, Any], *, target_field: str, delta_field: str
) -> None:
    expected = float(candidate[target_field]) - float(candidate["current_weight"])
    if abs(float(candidate[delta_field]) - expected) > 1e-9:
        raise DataVendorUnavailable("runtime candidate weight delta is inconsistent")


def _validate_role_snapshot_semantics(
    payload: Mapping[str, Any], *, tool_id: AgentToolId
) -> None:
    candidates = cast(list[Mapping[str, Any]], payload["candidate_universe"])
    constraints = cast(Mapping[str, Any], payload["constraints"])
    role_context = cast(Mapping[str, Any], payload["role_context"])
    refs = cast(list[Mapping[str, Any]], payload["upstream_accepted_output_refs"])

    if tool_id in {
        "get_superinvestor_candidate_snapshot",
        "get_alpha_candidate_snapshot",
    }:
        if constraints["cash_only"] and constraints["allow_new_positions"]:
            raise DataVendorUnavailable(
                "runtime candidate constraints cannot be cash-only and allow new positions"
            )
        if candidates and (
            constraints["cash_only"] or not constraints["allow_new_positions"]
        ):
            raise DataVendorUnavailable(
                "runtime candidate universe conflicts with no-new-position constraints"
            )

    if tool_id == "get_superinvestor_candidate_snapshot":
        for candidate in candidates:
            if candidate["ts_code"] in constraints["prohibited_ts_codes"]:
                raise DataVendorUnavailable(
                    "superinvestor candidate universe contains a prohibited security"
                )
            if not any(
                _accepted_ref_matches(
                    ref,
                    accepted_output_id=candidate["source_output_id"],
                    accepted_output_hash=candidate["source_output_hash"],
                    accepted_output_kind="STANDARD_SECTOR_SELECTION",
                    agent_id=str(candidate["source_sector_agent_id"]),
                )
                for ref in refs
            ):
                raise DataVendorUnavailable(
                    "superinvestor candidate source is not an accepted Sector output"
                )
        return

    if tool_id == "get_alpha_candidate_snapshot":
        observed_superinvestors = {
            str(ref["agent_id"])
            for ref in refs
            if ref["accepted_output_kind"] == "SUPERINVESTOR_SELECTION"
        }
        if observed_superinvestors != set(SUPERINVESTOR_AGENTS):
            raise DataVendorUnavailable(
                "alpha novelty snapshot requires all Superinvestor accepted outputs"
            )
        for candidate in candidates:
            if candidate["ts_code"] in constraints["excluded_selected_ts_codes"]:
                raise DataVendorUnavailable(
                    "alpha novelty universe contains an already selected security"
                )
            if not any(
                ref["accepted_output_id"] == candidate["source_output_id"]
                and ref["accepted_output_hash"] == candidate["source_output_hash"]
                and ref["agent_id"] == candidate["source_agent_id"]
                and ref["accepted_output_kind"]
                == "STANDARD_SECTOR_SELECTION"
                for ref in refs
            ):
                raise DataVendorUnavailable(
                    "alpha candidate source is not an accepted Sector output"
                )
        return

    if tool_id == "get_cro_risk_snapshot":
        _assert_proposal_ref_closure(role_context, refs)
        proposal_refs = [
            ref for ref in refs if ref["accepted_output_kind"] == "CIO_PROPOSAL"
        ]
        if len(proposal_refs) != 1:
            raise DataVendorUnavailable("CRO snapshot requires exactly one CIO proposal")
        position_refs: set[str] = set()
        target_weight = 0.0
        for candidate in candidates:
            _assert_weight_delta(
                candidate,
                target_field="proposed_target_weight",
                delta_field="proposed_delta_weight",
            )
            position_ref = str(candidate["proposal_position_ref"])
            if position_ref in position_refs:
                raise DataVendorUnavailable(
                    "CRO snapshot contains duplicate proposal position refs"
                )
            position_refs.add(position_ref)
            weight = float(candidate["proposed_target_weight"])
            if weight > float(constraints["max_single_name_weight"]) + 1e-9:
                raise DataVendorUnavailable(
                    "CRO candidate exceeds the frozen single-name weight limit"
                )
            target_weight += weight
        if target_weight > float(constraints["max_total_target_weight"]) + 1e-9:
            raise DataVendorUnavailable(
                "CRO candidate target exceeds the frozen total-weight limit"
            )
        return

    if tool_id == "get_execution_snapshot":
        _assert_proposal_ref_closure(role_context, refs)
        _assert_control_source_closure(role_context["cro_control_source"], refs)
        order_refs: set[str] = set()
        for candidate in candidates:
            _assert_weight_delta(
                candidate,
                target_field="target_weight",
                delta_field="requested_delta_weight",
            )
            order_ref = str(candidate["order_intent_ref"])
            if order_ref in order_refs:
                raise DataVendorUnavailable(
                    "execution snapshot contains duplicate order-intent refs"
                )
            order_refs.add(order_ref)
            delta = float(candidate["requested_delta_weight"])
            expected_side = "BUY" if delta > 1e-9 else "SELL" if delta < -1e-9 else "HOLD"
            if candidate["side"] != expected_side:
                raise DataVendorUnavailable(
                    "execution order side conflicts with requested weight delta"
                )
        return

    if tool_id != "get_cio_decision_snapshot":
        raise DataVendorUnavailable(f"no role-specific semantics for {tool_id}")

    if payload["stage"] == "cio_proposal":
        if role_context["decision_stage"] != "PROPOSAL":
            raise DataVendorUnavailable("CIO proposal context stage mismatch")
        if (role_context["previous_target_id"] is None) != (
            role_context["previous_target_hash"] is None
        ):
            raise DataVendorUnavailable("CIO previous-target binding is incomplete")
        for candidate in candidates:
            source_is_current = candidate["source_kind"] == "CURRENT_POSITION"
            source_is_null = (
                candidate["source_output_id"] is None
                and candidate["source_output_hash"] is None
            )
            if source_is_current != source_is_null:
                raise DataVendorUnavailable("CIO proposal candidate source binding mismatch")
            if not source_is_current and not any(
                ref["accepted_output_id"] == candidate["source_output_id"]
                and ref["accepted_output_hash"] == candidate["source_output_hash"]
                for ref in refs
            ):
                raise DataVendorUnavailable(
                    "CIO proposal candidate source is not an accepted upstream output"
                )
        return

    if role_context["decision_stage"] != "FINAL":
        raise DataVendorUnavailable("CIO final context stage mismatch")
    _assert_proposal_ref_closure(role_context, refs)
    _assert_control_source_closure(role_context["cro_control_source"], refs)
    _assert_control_source_closure(role_context["execution_control_source"], refs)
    proposal_position_refs: set[str] = set()
    target_weight = 0.0
    for candidate in candidates:
        _assert_weight_delta(
            candidate,
            target_field="proposed_target_weight",
            delta_field="proposed_delta_weight",
        )
        position_ref = str(candidate["proposal_position_ref"])
        if position_ref in proposal_position_refs:
            raise DataVendorUnavailable(
                "CIO final snapshot contains duplicate proposal position refs"
            )
        proposal_position_refs.add(position_ref)
        weight = float(candidate["proposed_target_weight"])
        if weight > float(constraints["max_single_name_weight"]) + 1e-9:
            raise DataVendorUnavailable(
                "CIO final candidate exceeds the frozen single-name weight limit"
            )
        target_weight += weight
    if target_weight > float(constraints["max_total_target_weight"]) + 1e-9:
        raise DataVendorUnavailable(
            "CIO final target exceeds the frozen total-weight limit"
        )


def _validate_bound_runtime_snapshot(
    payload: Mapping[str, Any],
    *,
    tool_id: AgentToolId,
    agent_id: str,
    stage: str,
    as_of: str,
    graph_run_id: str,
    expected_candidate_scope_hash: str | None,
) -> None:
    schema = BOUND_RUNTIME_SNAPSHOT_SCHEMAS.get(tool_id)
    if schema is None:
        raise DataVendorUnavailable(f"no strict runtime snapshot contract for {tool_id}")
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    except (SchemaError, ValidationError) as exc:
        raise DataVendorUnavailable(
            f"runtime snapshot {tool_id} failed its strict contract: {exc.message}"
        ) from exc
    _reject_source_prose(payload)
    if (
        payload["agent_id"] != agent_id
        or payload["stage"] != stage
        or payload["as_of"] != as_of
        or payload["graph_run_id"] != graph_run_id
    ):
        raise DataVendorUnavailable("runtime snapshot Agent/stage/run/as_of mismatch")
    expected_contract = BOUND_RUNTIME_SNAPSHOT_CONTRACTS[tool_id]
    if payload["contract_version"] != expected_contract:
        raise DataVendorUnavailable("runtime snapshot contract version mismatch")
    if payload["snapshot_hash"] != _sha256(
        {key: item for key, item in payload.items() if key != "snapshot_hash"}
    ):
        raise DataVendorUnavailable("runtime snapshot hash mismatch")
    candidates = payload["candidate_universe"]
    candidate_body = {
        "candidate_status": payload["candidate_status"],
        "candidate_universe": candidates,
    }
    if payload["candidate_universe_hash"] != _sha256(candidate_body):
        raise DataVendorUnavailable("runtime candidate universe hash mismatch")
    if (payload["candidate_status"] == "EMPTY_CONFIRMED") != (len(candidates) == 0):
        raise DataVendorUnavailable("runtime candidate status/universe mismatch")
    candidate_refs = [item["candidate_ref"] for item in candidates]
    ts_codes = [item["ts_code"] for item in candidates]
    if (
        len(set(candidate_refs)) != len(candidate_refs)
        or len(set(ts_codes)) != len(ts_codes)
        or any(_A_SHARE_CODE.fullmatch(code) is None for code in ts_codes)
    ):
        raise DataVendorUnavailable("runtime candidate universe is not unique A-share scope")
    constraints = payload["constraints"]
    if payload["constraint_set_hash"] != _sha256(constraints):
        raise DataVendorUnavailable("runtime constraint set hash mismatch")
    role_context = payload["role_context"]
    if payload["role_context_hash"] != _sha256(role_context):
        raise DataVendorUnavailable("runtime role context hash mismatch")
    expected_scope = {
        "candidate_universe_id": payload["candidate_universe_id"],
        "candidate_universe_hash": payload["candidate_universe_hash"],
        "constraint_set_id": payload["constraint_set_id"],
        "constraint_set_hash": payload["constraint_set_hash"],
    }
    if payload["candidate_scope"] != expected_scope or payload[
        "candidate_scope_hash"
    ] != _sha256(expected_scope):
        raise DataVendorUnavailable("runtime candidate scope binding mismatch")
    if (
        expected_candidate_scope_hash is not None
        and payload["candidate_scope_hash"] != expected_candidate_scope_hash
    ):
        raise DataVendorUnavailable("runtime snapshot differs from requested candidate scope")
    evidence_rows = payload["evidence_ledger"]
    evidence_by_id = {row["evidence_id"]: row for row in evidence_rows}
    if len(evidence_by_id) != len(evidence_rows):
        raise DataVendorUnavailable("runtime evidence IDs are duplicated")
    referenced_evidence: set[str] = set()
    for row in (
        *candidates,
        constraints,
        role_context,
        *payload["upstream_accepted_output_refs"],
    ):
        referenced_evidence.update(row["evidence_ids"])
    if referenced_evidence != set(evidence_by_id):
        raise DataVendorUnavailable("runtime snapshot evidence closure mismatch")
    as_of_close = _aware_timestamp(f"{as_of}T15:00:00+08:00", "snapshot.as_of")
    generated_at = _aware_timestamp(payload["generated_at"], "generated_at")
    for evidence in evidence_rows:
        available_at = _aware_timestamp(
            evidence["available_at"], "evidence.available_at"
        )
        if (
            date.fromisoformat(evidence["as_of"]) > date.fromisoformat(as_of)
            or available_at > generated_at
            or (
                evidence["source_kind"] != "ACCEPTED_OUTPUT"
                and available_at > as_of_close
            )
        ):
            raise DataVendorUnavailable("runtime snapshot evidence is not PIT")
    refs = payload["upstream_accepted_output_refs"]
    accepted_ids = [ref["accepted_output_id"] for ref in refs]
    if len(set(accepted_ids)) != len(accepted_ids):
        raise DataVendorUnavailable("runtime upstream accepted-output refs are duplicated")
    for ref in refs:
        if ref["as_of"] != as_of or not _allowed_upstream_lineage(
            tool_id, stage, ref
        ):
            raise DataVendorUnavailable("runtime upstream accepted-output lineage is invalid")
        supporting = [
            evidence_by_id[evidence_id]
            for evidence_id in ref["evidence_ids"]
            if evidence_id in evidence_by_id
        ]
        if not any(
            evidence["source_kind"] == "ACCEPTED_OUTPUT"
            and evidence["source_id"] == ref["accepted_output_id"]
            and evidence["source_fingerprint"] == ref["accepted_output_hash"]
            for evidence in supporting
        ):
            raise DataVendorUnavailable(
                "runtime accepted-output ref has no matching evidence record"
            )
    _validate_role_snapshot_semantics(payload, tool_id=tool_id)
    latest_evidence = max(
        _aware_timestamp(row["available_at"], "evidence.available_at")
        for row in evidence_rows
    )
    if generated_at < latest_evidence or generated_at > datetime.now(timezone.utc):
        raise DataVendorUnavailable("runtime snapshot generation timeline is invalid")


def _accepted_ref_projection(value: Any, *, field: str) -> list[dict[str, str]]:
    rows: list[Any]
    if isinstance(value, Mapping):
        rows = list(value.values())
    elif isinstance(value, list):
        rows = list(value)
    else:
        raise DataVendorUnavailable(f"{field} must contain accepted-output refs")
    projected: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise DataVendorUnavailable(f"{field}[{index}] must be an object")
        projection = {
            key: _required_string(row, key)
            for key in (
                "accepted_output_kind",
                "agent_id",
                "accepted_output_id",
                "accepted_output_hash",
            )
        }
        if not _is_sha256(projection["accepted_output_hash"]):
            raise DataVendorUnavailable(f"{field}[{index}] hash is invalid")
        projected.append(projection)
    identities = [
        (row["accepted_output_kind"], row["agent_id"], row["accepted_output_id"])
        for row in projected
    ]
    if len(set(identities)) != len(identities):
        raise DataVendorUnavailable(f"{field} contains duplicate accepted-output refs")
    return sorted(
        projected,
        key=lambda row: (
            row["accepted_output_kind"],
            row["agent_id"],
            row["accepted_output_id"],
        ),
    )


def _validate_bound_request_closure(
    *,
    payload: Mapping[str, Any],
    runtime_inputs: Mapping[str, Any],
    candidate_scope: Mapping[str, Any] | None,
) -> None:
    if candidate_scope is None or set(candidate_scope) != {"accepted_output_refs"}:
        raise DataVendorUnavailable(
            "bound runtime capability requires exact accepted-output candidate scope"
        )
    if set(runtime_inputs) not in (
        {"accepted_output_refs"},
        {
            "accepted_output_refs",
            "accepted_output_records",
            "bound_runtime_state",
        },
    ):
        raise DataVendorUnavailable(
            "bound runtime capability requires exact accepted-output runtime inputs"
        )
    scoped = _accepted_ref_projection(
        candidate_scope["accepted_output_refs"], field="candidate_scope"
    )
    runtime = _accepted_ref_projection(
        runtime_inputs["accepted_output_refs"], field="runtime_inputs"
    )
    authoritative = sorted(
        [
            {
                key: ref[key]
                for key in (
                    "accepted_output_kind",
                    "agent_id",
                    "accepted_output_id",
                    "accepted_output_hash",
                )
            }
            for ref in payload["upstream_accepted_output_refs"]
        ],
        key=lambda row: (
            row["accepted_output_kind"],
            row["agent_id"],
            row["accepted_output_id"],
        ),
    )
    if scoped != runtime or scoped != authoritative:
        raise DataVendorUnavailable(
            "bound runtime accepted-output closure differs from the frozen snapshot"
        )


def _validate_live_outcome_authority(
    *,
    agent_id: str,
    runtime_inputs: Mapping[str, Any],
    payloads: Mapping[AgentToolId, str],
) -> None:
    authority = runtime_inputs.get("outcome_opportunity_authority")
    if authority is None:
        return
    if not isinstance(authority, Mapping) or set(authority) != {
        "source_tool_id",
        "source_snapshot_hash",
        "domain_hash",
    }:
        raise DataVendorUnavailable("live outcome authority fields mismatch")
    if agent_id in MACRO_AGENT_TO_TOOL:
        expected_tool = MACRO_AGENT_TO_TOOL[agent_id]
    elif agent_id in STANDARD_SECTOR_AGENTS:
        expected_tool = "get_sector_research_snapshot"
    else:
        raise DataVendorUnavailable(
            "live outcome authority is restricted to L1/L2 Agents"
        )
    if authority.get("source_tool_id") != expected_tool:
        raise DataVendorUnavailable("live outcome authority tool mismatch")
    source_hash = authority.get("source_snapshot_hash")
    if not _is_sha256(source_hash) or not _is_sha256(authority.get("domain_hash")):
        raise DataVendorUnavailable("live outcome authority hash is invalid")
    try:
        source_payload = json.loads(payloads[expected_tool])
    except (KeyError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            "live outcome authority source payload is unavailable"
        ) from exc
    if (
        not isinstance(source_payload, Mapping)
        or source_payload.get("snapshot_hash") != source_hash
    ):
        raise DataVendorUnavailable(
            "live outcome source changed after opportunity freeze"
        )


def _load_bound_snapshot(
    *,
    tool_id: AgentToolId,
    agent_id: str,
    stage: str,
    as_of: str,
    graph_run_id: str,
    expected_candidate_scope_hash: str | None = None,
    accepted_output_refs: Any | None = None,
    synthetic_fixture_validated: bool = False,
) -> str:
    """Load a collector-produced, role-bound payload for non-Macro tools."""
    root = _runtime_snapshot_root()
    candidates = (
        root
        / bound_runtime_snapshot_relative_path(
            agent_id=agent_id,
            stage=stage,
            tool_id=tool_id,
            as_of=as_of,
            graph_run_id=graph_run_id,
        ),
        root / as_of / f"{agent_id}.{stage}.{tool_id}.json",
        root / as_of / f"{agent_id}.{tool_id}.json",
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise DataVendorUnavailable(
            f"no frozen runtime snapshot for {agent_id}/{stage}/{tool_id} on {as_of}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(f"cannot read runtime snapshot {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DataVendorUnavailable("runtime snapshot must be an object")
    payload = _rebind_synthetic_runtime_snapshot(
        payload,
        root=root,
        as_of=as_of,
        graph_run_id=graph_run_id,
        accepted_output_refs=accepted_output_refs,
        synthetic_fixture_validated=synthetic_fixture_validated,
    )
    _validate_bound_runtime_snapshot(
        payload,
        tool_id=tool_id,
        agent_id=agent_id,
        stage=stage,
        as_of=as_of,
        graph_run_id=graph_run_id,
        expected_candidate_scope_hash=expected_candidate_scope_hash,
    )
    return _canonical_json(payload)


def _rebind_synthetic_runtime_snapshot(
    payload: dict[str, Any],
    *,
    root: Path,
    as_of: str,
    graph_run_id: str,
    accepted_output_refs: Any | None,
    synthetic_fixture_validated: bool,
) -> dict[str, Any]:
    """Bind an explicitly authorised smoke fixture to one synthetic graph run.

    Production snapshots are immutable and never enter this path.  The marker,
    caller-provided marker hash, and non-production opt-in must all agree before
    any server-side rebinding is allowed.
    """
    if os.getenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS") != "structured_smoke":
        return payload
    if not synthetic_fixture_validated:
        _valid_synthetic_fixture_marker(root=root, as_of=as_of)
    if payload.get("graph_run_id") == graph_run_id and accepted_output_refs is None:
        return payload
    if accepted_output_refs is None:
        raise DataVendorUnavailable(
            "synthetic runtime rebinding requires exact accepted-output refs"
        )
    projected = _accepted_ref_projection(
        accepted_output_refs, field="synthetic accepted_output_refs"
    )
    runtime_by_identity = {
        (row["accepted_output_kind"], row["agent_id"]): row for row in projected
    }
    if len(runtime_by_identity) != len(projected):
        raise DataVendorUnavailable(
            "synthetic accepted-output refs contain duplicate kind/Agent identities"
        )
    frozen_refs = payload.get("upstream_accepted_output_refs")
    if not isinstance(frozen_refs, list):
        raise DataVendorUnavailable("synthetic runtime snapshot has no frozen upstream refs")
    rebound_refs: list[dict[str, Any]] = []
    replacements: dict[str, str] = {}
    for frozen in frozen_refs:
        if not isinstance(frozen, dict):
            raise DataVendorUnavailable("synthetic frozen upstream ref is invalid")
        identity = (frozen.get("accepted_output_kind"), frozen.get("agent_id"))
        runtime = runtime_by_identity.get(cast(tuple[str, str], identity))
        if runtime is None:
            raise DataVendorUnavailable(
                "synthetic accepted-output refs differ from the frozen role lineage"
            )
        replacements[str(frozen["accepted_output_id"])] = runtime[
            "accepted_output_id"
        ]
        replacements[str(frozen["accepted_output_hash"])] = runtime[
            "accepted_output_hash"
        ]
        rebound_refs.append(
            {
                **frozen,
                "accepted_output_id": runtime["accepted_output_id"],
                "accepted_output_hash": runtime["accepted_output_hash"],
            }
        )
    if len(rebound_refs) != len(projected):
        raise DataVendorUnavailable(
            "synthetic accepted-output refs do not close the frozen role lineage"
        )
    rebound = cast(dict[str, Any], _replace_exact_strings(payload, replacements))
    rebound["graph_run_id"] = graph_run_id
    rebound["snapshot_id"] = (
        f"{payload['snapshot_id']}:{_sha256_text(graph_run_id).removeprefix('sha256:')[:16]}"
    )
    rebound["upstream_accepted_output_refs"] = rebound_refs
    rebound["candidate_universe_hash"] = _sha256(
        {
            "candidate_status": rebound["candidate_status"],
            "candidate_universe": rebound["candidate_universe"],
        }
    )
    rebound["constraint_set_hash"] = _sha256(rebound["constraints"])
    rebound["role_context_hash"] = _sha256(rebound["role_context"])
    rebound["candidate_scope"] = {
        "candidate_universe_id": rebound["candidate_universe_id"],
        "candidate_universe_hash": rebound["candidate_universe_hash"],
        "constraint_set_id": rebound["constraint_set_id"],
        "constraint_set_hash": rebound["constraint_set_hash"],
    }
    rebound["candidate_scope_hash"] = _sha256(rebound["candidate_scope"])
    rebound["snapshot_hash"] = _sha256(
        {key: item for key, item in rebound.items() if key != "snapshot_hash"}
    )
    return rebound


def _valid_synthetic_fixture_marker(*, root: Path, as_of: str) -> bool:
    if os.getenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS") != "structured_smoke":
        return False
    expected_hash = os.getenv("MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH")
    if not _is_sha256(expected_hash):
        raise DataVendorUnavailable(
            "synthetic runtime rebinding requires a valid fixture bundle hash"
        )
    cache_root = root.expanduser().resolve().parent
    marker_path = cache_root / "structured_smoke_fixture_bundle.json"
    if marker_path.is_symlink():
        raise DataVendorUnavailable(
            "synthetic runtime fixture artifact inventory mismatch"
        )
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable("synthetic runtime fixture marker is unavailable") from exc
    if not isinstance(marker, dict):
        raise DataVendorUnavailable("synthetic runtime fixture marker must be an object")
    expected_marker_fields = {
        "schema_version",
        "as_of_date",
        "fixture_class",
        "contains_vendor_prose",
        "cache_root",
        "geopolitical_manifest",
        "geopolitical_manifest_hash",
        "artifact_inventory",
        "artifact_inventory_hash",
        "bundle_hash",
    }
    marker_hash = marker.get("bundle_hash")
    marker_body = {key: value for key, value in marker.items() if key != "bundle_hash"}
    if (
        set(marker) != expected_marker_fields
        or marker.get("schema_version") != "structured_smoke_fixture_bundle_v1"
        or marker.get("fixture_class") != "SYNTHETIC_NON_PRODUCTION"
        or marker.get("contains_vendor_prose") is not False
        or marker.get("as_of_date") != as_of
        or Path(str(marker.get("cache_root", ""))).expanduser().resolve()
        != cache_root
        or marker_hash != _sha256(marker_body)
        or marker_hash != expected_hash
    ):
        raise DataVendorUnavailable("synthetic runtime fixture marker binding is invalid")
    inventory = marker.get("artifact_inventory")
    if (
        not isinstance(inventory, list)
        or not inventory
        or marker.get("artifact_inventory_hash") != _sha256(inventory)
        or inventory != _synthetic_fixture_artifact_inventory(cache_root)
    ):
        raise DataVendorUnavailable(
            "synthetic runtime fixture artifact inventory mismatch"
        )
    geopolitical_manifest = Path(str(marker["geopolitical_manifest"])).expanduser()
    try:
        resolved_geopolitical_manifest = geopolitical_manifest.resolve(strict=True)
        manifest_relative = resolved_geopolitical_manifest.relative_to(
            cache_root
        ).as_posix()
    except (OSError, ValueError) as exc:
        raise DataVendorUnavailable(
            "synthetic runtime fixture artifact inventory mismatch"
        ) from exc
    inventory_paths = {row["relative_path"] for row in inventory}
    if (
        geopolitical_manifest.is_symlink()
        or manifest_relative not in inventory_paths
        or not _is_sha256(marker.get("geopolitical_manifest_hash"))
    ):
        raise DataVendorUnavailable(
            "synthetic runtime fixture artifact inventory mismatch"
        )
    try:
        geopolitical_payload = json.loads(
            resolved_geopolitical_manifest.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            "synthetic runtime fixture artifact inventory mismatch"
        ) from exc
    if (
        not isinstance(geopolitical_payload, dict)
        or geopolitical_payload.get("manifest_hash")
        != marker["geopolitical_manifest_hash"]
    ):
        raise DataVendorUnavailable(
            "synthetic runtime fixture artifact inventory mismatch"
        )
    return True


_SYNTHETIC_FIXTURE_ARTIFACT_ROOTS: Final = (
    "china_archive",
    "economic_calendar",
    "forward_archive",
    "geopolitical_events",
    "gov_policy",
    "macro_snapshots",
    "market_breadth",
    "outcome_runtime",
    "runtime_snapshots",
    "sector_archive",
    "sector_snapshots",
    "supply_chain_archive",
)


def _synthetic_fixture_artifact_inventory(
    cache_root: Path,
) -> list[dict[str, str]]:
    inventory: list[dict[str, str]] = []
    try:
        for directory_name in _SYNTHETIC_FIXTURE_ARTIFACT_ROOTS:
            directory = cache_root / directory_name
            if directory.is_symlink() or not directory.is_dir():
                raise DataVendorUnavailable(
                    "synthetic runtime fixture artifact inventory mismatch"
                )
            for current_root, directory_names, file_names in os.walk(
                directory, followlinks=False
            ):
                current = Path(current_root)
                for name in directory_names:
                    if (current / name).is_symlink():
                        raise DataVendorUnavailable(
                            "synthetic runtime fixture artifact inventory mismatch"
                        )
                for name in file_names:
                    path = current / name
                    if path.is_symlink() or not path.is_file():
                        raise DataVendorUnavailable(
                            "synthetic runtime fixture artifact inventory mismatch"
                        )
                    inventory.append(
                        {
                            "relative_path": path.relative_to(cache_root).as_posix(),
                            "content_sha256": (
                                "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                            ),
                        }
                    )
    except OSError as exc:
        raise DataVendorUnavailable(
            "synthetic runtime fixture artifact inventory mismatch"
        ) from exc
    inventory.sort(key=lambda row: row["relative_path"])
    return inventory


def _replace_exact_strings(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_exact_strings(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_exact_strings(item, replacements)
            for key, item in value.items()
        }
    return value


def materialize_tool_payload(
    tool_id: AgentToolId,
    *,
    agent_id: str,
    stage: str,
    as_of: str,
    graph_run_id: str = "standalone_tool_materialization",
    expected_candidate_scope_hash: str | None = None,
    accepted_output_refs: Any | None = None,
) -> str:
    """Materialise one payload before capability issuance."""
    synthetic_fixture_validated = False
    if os.getenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS") == "structured_smoke":
        # Validate the closed-set bundle immediately before every materialization,
        # including the render-based Macro/Sector paths.  Startup validation alone
        # would leave those paths open to fixture mutation between tool calls.
        _valid_synthetic_fixture_marker(root=_runtime_snapshot_root(), as_of=as_of)
        synthetic_fixture_validated = True
    role_by_tool = {tool: role for role, tool in MACRO_AGENT_TO_TOOL.items()}
    if tool_id in role_by_tool:
        role = role_by_tool[tool_id]
        if role != agent_id:
            raise ValueError(f"{tool_id} cannot be materialised for {agent_id}")
        if tool_id == "get_market_breadth_snapshot":
            return render_market_breadth_snapshot(as_of)
        return render_role_snapshot(role, as_of)
    if tool_id == "get_sector_research_snapshot":
        return render_sector_snapshot(agent_id, as_of)
    if tool_id == "get_role_event_snapshot":
        return render_role_event_snapshot(agent_id, as_of)
    return _load_bound_snapshot(
        tool_id=tool_id,
        agent_id=agent_id,
        stage=stage,
        as_of=as_of,
        graph_run_id=graph_run_id,
        expected_candidate_scope_hash=expected_candidate_scope_hash,
        accepted_output_refs=accepted_output_refs,
        synthetic_fixture_validated=synthetic_fixture_validated,
    )


@dataclass(frozen=True)
class SignedCapability:
    manifest: dict[str, Any]
    signing_key_id: str
    signature: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest,
            "signing_key_id": self.signing_key_id,
            "signature": self.signature,
        }


class AgentToolCapabilityStore:
    """SQLite-backed append-only bundle, capability-event and use ledger."""

    def __init__(
        self,
        db_path: Path,
        *,
        signing_key: bytes,
        signing_key_id: str,
        clock: Callable[[], datetime] | None = None,
        adaptive_query_store: FrozenAdaptiveQueryStore | None = None,
        adaptive_query_preparer: Callable[..., Mapping[str, Any]] | None = None,
        adaptive_query_materializer: (
            Callable[[str, dict[str, Any]], Mapping[str, Any]] | None
        ) = None,
        stage_materialization_preparer: Callable[[Mapping[str, Any]], Any] | None = None,
        stage_materialization_finalizer: Callable[[Mapping[str, Any]], Any] | None = None,
        require_knot_v2_audit_authority: bool = False,
    ) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.signing_key = signing_key
        self.signing_key_id = signing_key_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if (adaptive_query_store is None) != (adaptive_query_preparer is None):
            raise ValueError(
                "adaptive_query_store and adaptive_query_preparer must be configured together"
            )
        if (
            adaptive_query_store is not None
            and adaptive_query_store.db_path.resolve() == self.db_path.resolve()
        ):
            raise ValueError("adaptive query and capability ledgers must use distinct files")
        self.adaptive_query_store = adaptive_query_store
        self.adaptive_query_preparer = adaptive_query_preparer
        self.adaptive_query_materializer = adaptive_query_materializer
        self.stage_materialization_preparer = stage_materialization_preparer
        self.stage_materialization_finalizer = stage_materialization_finalizer
        self.require_knot_v2_audit_authority = require_knot_v2_audit_authority
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _initialise(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshot_bundles (
                    snapshot_bundle_id TEXT PRIMARY KEY,
                    snapshot_bundle_hash TEXT NOT NULL UNIQUE,
                    materialization_request_id TEXT NOT NULL UNIQUE,
                    bundle_json TEXT NOT NULL,
                    payloads_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS materialization_requests (
                    materialization_request_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    requested_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capabilities (
                    capability_id TEXT PRIMARY KEY,
                    snapshot_bundle_id TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    signing_key_id TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(snapshot_bundle_id)
                      REFERENCES snapshot_bundles(snapshot_bundle_id)
                );
                CREATE TABLE IF NOT EXISTS capability_events (
                    event_id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN ('ISSUED', 'TERMINATED')),
                    event_at TEXT NOT NULL,
                    reason TEXT,
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_termination_per_capability
                  ON capability_events(capability_id)
                  WHERE event_type = 'TERMINATED';
                CREATE TABLE IF NOT EXISTS capability_tool_uses (
                    capability_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    used_at TEXT NOT NULL,
                    PRIMARY KEY(capability_id, tool_id),
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id)
                );
                CREATE TABLE IF NOT EXISTS snapshot_bundle_audit_contexts (
                    snapshot_bundle_id TEXT PRIMARY KEY,
                    context_json TEXT NOT NULL,
                    context_hash TEXT NOT NULL UNIQUE,
                    signing_key_id TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(snapshot_bundle_id)
                      REFERENCES snapshot_bundles(snapshot_bundle_id)
                );
                CREATE TABLE IF NOT EXISTS capability_audit_contexts (
                    capability_id TEXT PRIMARY KEY,
                    snapshot_bundle_id TEXT NOT NULL,
                    snapshot_bundle_audit_context_hash TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    context_hash TEXT NOT NULL UNIQUE,
                    signing_key_id TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id),
                    FOREIGN KEY(snapshot_bundle_id)
                      REFERENCES snapshot_bundles(snapshot_bundle_id),
                    FOREIGN KEY(snapshot_bundle_audit_context_hash)
                      REFERENCES snapshot_bundle_audit_contexts(context_hash)
                );
                CREATE TABLE IF NOT EXISTS tool_result_events (
                    result_event_id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK(sequence > 0),
                    tool_id TEXT NOT NULL,
                    call_mode TEXT NOT NULL
                      CHECK(call_mode IN ('SNAPSHOT', 'INITIAL', 'FOLLOW_UP')),
                    status TEXT NOT NULL CHECK(status IN ('SUCCEEDED', 'FAILED')),
                    event_json TEXT NOT NULL,
                    result_event_hash TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id),
                    UNIQUE(capability_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS binding_signal_projections (
                    result_event_id TEXT NOT NULL,
                    binding_id TEXT NOT NULL,
                    projection_json TEXT NOT NULL,
                    projection_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(result_event_id, binding_id),
                    FOREIGN KEY(result_event_id)
                      REFERENCES tool_result_events(result_event_id)
                );
                CREATE TABLE IF NOT EXISTS accepted_knot_history_materializations_v2 (
                    accepted_output_id TEXT PRIMARY KEY,
                    accepted_output_hash TEXT NOT NULL UNIQUE,
                    capability_id TEXT,
                    capture_hash TEXT UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('MATERIALIZED', 'EXCLUDED')),
                    materialization_json TEXT NOT NULL,
                    materialization_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id)
                );
                CREATE TABLE IF NOT EXISTS trusted_counterevidence_evaluations_v2 (
                    accepted_output_id TEXT NOT NULL,
                    result_event_id TEXT NOT NULL,
                    binding_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL,
                    claim_spec_json TEXT NOT NULL,
                    claim_spec_hash TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    evaluation_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(accepted_output_id, result_event_id, binding_id, claim_id),
                    FOREIGN KEY(accepted_output_id)
                      REFERENCES accepted_knot_history_materializations_v2(accepted_output_id),
                    FOREIGN KEY(result_event_id, binding_id)
                      REFERENCES binding_signal_projections(result_event_id, binding_id)
                );
                CREATE TABLE IF NOT EXISTS knot_binding_observations_v2 (
                    accepted_output_id TEXT NOT NULL,
                    binding_id TEXT NOT NULL,
                    observation_json TEXT NOT NULL,
                    observation_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(accepted_output_id, binding_id),
                    FOREIGN KEY(accepted_output_id)
                      REFERENCES accepted_knot_history_materializations_v2(accepted_output_id)
                );
                CREATE TABLE IF NOT EXISTS tool_security_rejections (
                    security_rejection_id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    security_rejection_hash TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id)
                );
                CREATE TABLE IF NOT EXISTS snapshot_bundle_adaptive_queries (
                    snapshot_bundle_id TEXT PRIMARY KEY,
                    frozen_bundle_id TEXT NOT NULL,
                    frozen_bundle_hash TEXT NOT NULL,
                    public_projection_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(snapshot_bundle_id)
                      REFERENCES snapshot_bundles(snapshot_bundle_id)
                );
                CREATE TABLE IF NOT EXISTS capability_adaptive_sessions (
                    capability_id TEXT PRIMARY KEY,
                    frozen_bundle_id TEXT NOT NULL,
                    frozen_bundle_hash TEXT NOT NULL,
                    session_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id)
                );
                CREATE TABLE IF NOT EXISTS sector_model_usage_events (
                    usage_event_id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    model_subcall_id TEXT NOT NULL UNIQUE,
                    subcall_sequence INTEGER NOT NULL CHECK(subcall_sequence > 0),
                    attempted_stage TEXT NOT NULL,
                    attempt_index INTEGER NOT NULL CHECK(attempt_index > 0),
                    event_json TEXT NOT NULL,
                    usage_event_hash TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id),
                    UNIQUE(capability_id, subcall_sequence),
                    UNIQUE(capability_id, attempted_stage, attempt_index)
                );
                CREATE TABLE IF NOT EXISTS sector_model_usage_summaries (
                    usage_summary_receipt_id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL UNIQUE,
                    usage_ledger_record_json TEXT NOT NULL,
                    usage_ledger_record_hash TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL,
                    usage_summary_receipt_hash TEXT NOT NULL UNIQUE,
                    receipt_signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id)
                );
                CREATE TRIGGER IF NOT EXISTS snapshot_bundles_no_update
                  BEFORE UPDATE ON snapshot_bundles BEGIN
                    SELECT RAISE(ABORT, 'snapshot_bundles is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS snapshot_bundles_no_delete
                  BEFORE DELETE ON snapshot_bundles BEGIN
                    SELECT RAISE(ABORT, 'snapshot_bundles is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS materialization_requests_no_update
                  BEFORE UPDATE ON materialization_requests BEGIN
                    SELECT RAISE(ABORT, 'materialization_requests is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS materialization_requests_no_delete
                  BEFORE DELETE ON materialization_requests BEGIN
                    SELECT RAISE(ABORT, 'materialization_requests is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capabilities_no_update
                  BEFORE UPDATE ON capabilities BEGIN
                    SELECT RAISE(ABORT, 'capabilities is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capabilities_no_delete
                  BEFORE DELETE ON capabilities BEGIN
                    SELECT RAISE(ABORT, 'capabilities is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_events_no_update
                  BEFORE UPDATE ON capability_events BEGIN
                    SELECT RAISE(ABORT, 'capability_events is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_events_no_delete
                  BEFORE DELETE ON capability_events BEGIN
                    SELECT RAISE(ABORT, 'capability_events is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_tool_uses_no_update
                  BEFORE UPDATE ON capability_tool_uses BEGIN
                    SELECT RAISE(ABORT, 'capability_tool_uses is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_tool_uses_no_delete
                  BEFORE DELETE ON capability_tool_uses BEGIN
                    SELECT RAISE(ABORT, 'capability_tool_uses is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS snapshot_bundle_audit_contexts_no_update
                  BEFORE UPDATE ON snapshot_bundle_audit_contexts BEGIN
                    SELECT RAISE(ABORT, 'snapshot bundle audit contexts are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS snapshot_bundle_audit_contexts_no_delete
                  BEFORE DELETE ON snapshot_bundle_audit_contexts BEGIN
                    SELECT RAISE(ABORT, 'snapshot bundle audit contexts are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_audit_contexts_no_update
                  BEFORE UPDATE ON capability_audit_contexts BEGIN
                    SELECT RAISE(ABORT, 'capability audit contexts are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_audit_contexts_no_delete
                  BEFORE DELETE ON capability_audit_contexts BEGIN
                    SELECT RAISE(ABORT, 'capability audit contexts are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS tool_result_events_no_update
                  BEFORE UPDATE ON tool_result_events BEGIN
                    SELECT RAISE(ABORT, 'tool result events are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS tool_result_events_no_delete
                  BEFORE DELETE ON tool_result_events BEGIN
                    SELECT RAISE(ABORT, 'tool result events are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS binding_signal_projections_no_update
                  BEFORE UPDATE ON binding_signal_projections BEGIN
                    SELECT RAISE(ABORT, 'binding signal projections are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS binding_signal_projections_no_delete
                  BEFORE DELETE ON binding_signal_projections BEGIN
                    SELECT RAISE(ABORT, 'binding signal projections are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS accepted_knot_history_materializations_v2_no_update
                  BEFORE UPDATE ON accepted_knot_history_materializations_v2 BEGIN
                    SELECT RAISE(ABORT, 'accepted KNOT history materializations are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS accepted_knot_history_materializations_v2_no_delete
                  BEFORE DELETE ON accepted_knot_history_materializations_v2 BEGIN
                    SELECT RAISE(ABORT, 'accepted KNOT history materializations are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS trusted_counterevidence_evaluations_v2_no_update
                  BEFORE UPDATE ON trusted_counterevidence_evaluations_v2 BEGIN
                    SELECT RAISE(ABORT, 'trusted counterevidence evaluations are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS trusted_counterevidence_evaluations_v2_no_delete
                  BEFORE DELETE ON trusted_counterevidence_evaluations_v2 BEGIN
                    SELECT RAISE(ABORT, 'trusted counterevidence evaluations are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS knot_binding_observations_v2_no_update
                  BEFORE UPDATE ON knot_binding_observations_v2 BEGIN
                    SELECT RAISE(ABORT, 'KNOT binding observations are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS knot_binding_observations_v2_no_delete
                  BEFORE DELETE ON knot_binding_observations_v2 BEGIN
                    SELECT RAISE(ABORT, 'KNOT binding observations are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS tool_security_rejections_no_update
                  BEFORE UPDATE ON tool_security_rejections BEGIN
                    SELECT RAISE(ABORT, 'tool security rejections are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS tool_security_rejections_no_delete
                  BEFORE DELETE ON tool_security_rejections BEGIN
                    SELECT RAISE(ABORT, 'tool security rejections are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS snapshot_bundle_adaptive_queries_no_update
                  BEFORE UPDATE ON snapshot_bundle_adaptive_queries BEGIN
                    SELECT RAISE(ABORT, 'snapshot bundle adaptive queries are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS snapshot_bundle_adaptive_queries_no_delete
                  BEFORE DELETE ON snapshot_bundle_adaptive_queries BEGIN
                    SELECT RAISE(ABORT, 'snapshot bundle adaptive queries are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_adaptive_sessions_no_update
                  BEFORE UPDATE ON capability_adaptive_sessions BEGIN
                    SELECT RAISE(ABORT, 'capability adaptive sessions are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_adaptive_sessions_no_delete
                  BEFORE DELETE ON capability_adaptive_sessions BEGIN
                    SELECT RAISE(ABORT, 'capability adaptive sessions are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS sector_usage_events_no_update
                  BEFORE UPDATE ON sector_model_usage_events BEGIN
                    SELECT RAISE(ABORT, 'sector usage events are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS sector_usage_events_no_delete
                  BEFORE DELETE ON sector_model_usage_events BEGIN
                    SELECT RAISE(ABORT, 'sector usage events are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS sector_usage_summaries_no_update
                  BEFORE UPDATE ON sector_model_usage_summaries BEGIN
                    SELECT RAISE(ABORT, 'sector usage summaries are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS sector_usage_summaries_no_delete
                  BEFORE DELETE ON sector_model_usage_summaries BEGIN
                    SELECT RAISE(ABORT, 'sector usage summaries are append-only');
                  END;
                """
            )

    def _sign(self, manifest: Mapping[str, Any]) -> str:
        return "hmac-sha256:" + hmac.new(
            self.signing_key,
            _canonical_json(manifest).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _sign_domain(self, domain: str, payload: Mapping[str, Any]) -> str:
        message = domain.encode("utf-8") + _canonical_json(payload).encode("utf-8")
        return "hmac-sha256:" + hmac.new(
            self.signing_key,
            message,
            hashlib.sha256,
        ).hexdigest()

    def _active_knot_audit_authority(
        self,
        *,
        agent_id: str,
        stage: str,
        allowed_tools: Sequence[AgentToolId],
    ) -> dict[str, Any]:
        root = Path(__file__).resolve().parents[2]
        current_tool_manifest = json.loads(
            (
                root
                / "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
            ).read_text(encoding="utf-8")
        )
        bundle = load_capability_contract_bundle(root)
        validate_capability_contract_bundle(
            bundle, current_tool_manifest=current_tool_manifest
        )
        binding_manifest = bundle["binding_manifest"]
        staged_manifest = bundle["staged_tool_contract_manifest"]
        coverage_manifest = bundle["knot_coverage_manifest"]
        track = bundle["accepted_output_capability_track"]
        coverage_manifest_v2 = bundle["knot_coverage_manifest_v2"]
        audit_track_v2 = bundle["knot_audit_capability_track_v2"]
        binding_by_id = {
            row["binding_id"]: row for row in binding_manifest["bindings"]
        }
        coverage_by_id = {
            row["binding_id"]: row for row in coverage_manifest["coverage"]
        }
        coverage_v2_by_id = {
            row["binding_id"]: row
            for row in coverage_manifest_v2["coverage"]
        }
        staged_rows = [
            row
            for row in staged_manifest["tools"]
            if row["agent_id"] == agent_id and row["stage"] == stage
        ]
        if {row["tool_id"] for row in staged_rows} != set(allowed_tools):
            raise ValueError("KNOT staged tool authority does not match capability tools")
        tool_contexts: list[dict[str, Any]] = []
        for row in staged_rows:
            refs: list[dict[str, Any]] = []
            for binding_id in row["capability_binding_ids"]:
                binding = binding_by_id.get(binding_id)
                coverage = coverage_by_id.get(binding_id)
                coverage_v2 = coverage_v2_by_id.get(binding_id)
                if (
                    binding is None
                    or coverage is None
                    or coverage_v2 is None
                    or binding["agent_id"] != agent_id
                    or binding["stage"] != stage
                    or binding["tool_id"] != row["tool_id"]
                ):
                    raise ValueError("KNOT tool binding authority drift")
                refs.append(
                    {
                        "binding_id": binding_id,
                        "semantic_capability_id": binding[
                            "semantic_capability_id"
                        ],
                        "legacy_coverage_row_hash": coverage["coverage_row_hash"],
                        "coverage_row_hash": coverage_v2["coverage_row_hash"],
                        "coverage_row": coverage_v2,
                    }
                )
            refs.sort(key=lambda value: value["binding_id"])
            if not refs:
                raise ValueError("KNOT tool binding authority is empty")
            tool_contexts.append(
                {"tool_id": row["tool_id"], "binding_refs": refs}
            )
        tool_contexts.sort(key=lambda value: value["tool_id"])
        return {
            "capability_binding_manifest_hash": track[
                "capability_binding_manifest_hash"
            ],
            "tool_environment_hash": track["tool_environment_hash"],
            "knot_coverage_manifest_hash": track[
                "knot_coverage_manifest_hash"
            ],
            "capability_bundle_hash": track["capability_bundle_hash"],
            "knot_coverage_manifest_v2_hash": audit_track_v2[
                "knot_coverage_manifest_v2_hash"
            ],
            "knot_audit_capability_track_v2_hash": audit_track_v2["track_hash"],
            "execution_behavior_release_hash": audit_track_v2[
                "execution_behavior_release_hash"
            ],
            "tool_contexts": tool_contexts,
        }

    def _build_snapshot_audit_context(
        self,
        *,
        snapshot_bundle_id: str,
        snapshot_bundle_hash: str,
        agent_id: str,
        stage: str,
        as_of: str,
        allowed_tools: Sequence[AgentToolId],
        finalization: Any,
        deferred_query: Mapping[str, Any] | None,
        created_at: str,
    ) -> dict[str, Any]:
        eligibility = "INELIGIBLE"
        reasons: list[str] = []
        build_receipt_hashes: dict[str, str] = {}
        attempt_receipt_hash: str | None = None
        deferred_authority: dict[str, Any] | None = None
        expected_build_tools = set(allowed_tools)
        if deferred_query is not None:
            deferred_tool_ids = deferred_query.get("tool_ids")
            if (
                set(deferred_query)
                != {"call_contract", "frozen_bundle_hash", "tool_ids"}
                or deferred_query.get("call_contract")
                != CALL_TIME_ARGUMENT_CONTRACT
                or not _is_sha256(deferred_query.get("frozen_bundle_hash"))
                or not isinstance(deferred_tool_ids, list)
                or not deferred_tool_ids
                or deferred_tool_ids != sorted(set(deferred_tool_ids))
                or set(deferred_tool_ids)
                != set(allowed_tools).intersection(ADAPTIVE_QUERY_TOOL_IDS)
            ):
                raise ValueError("deferred query snapshot authority is invalid")
            deferred_authority = {
                "call_contract": CALL_TIME_ARGUMENT_CONTRACT,
                "frozen_bundle_hash": deferred_query["frozen_bundle_hash"],
                "tool_ids": list(deferred_tool_ids),
            }
            expected_build_tools -= set(deferred_tool_ids)
        try:
            authority = self._active_knot_audit_authority(
                agent_id=agent_id,
                stage=stage,
                allowed_tools=allowed_tools,
            )
        except ValueError:
            if self.require_knot_v2_audit_authority:
                raise
            reasons.append("ACTIVE_KNOT_AUTHORITY_MISMATCH")
            authority = {
                "capability_binding_manifest_hash": None,
                "tool_environment_hash": None,
                "knot_coverage_manifest_hash": None,
                "capability_bundle_hash": None,
                "knot_coverage_manifest_v2_hash": None,
                "knot_audit_capability_track_v2_hash": None,
                "execution_behavior_release_hash": None,
                "tool_contexts": [],
            }
        if finalization is None:
            reasons.append("MATERIALIZATION_FINALIZER_RESULT_MISSING")
        elif not isinstance(finalization, Mapping):
            reasons.append("MATERIALIZATION_FINALIZER_RESULT_INVALID")
        elif finalization.get("status") == "SYNTHETIC_NON_PRODUCTION_BYPASS":
            reasons.append("SYNTHETIC_NON_PRODUCTION_BYPASS")
        elif finalization.get("status") != "READY":
            reasons.append("MATERIALIZATION_FINALIZER_NOT_READY")
        else:
            tool_ids = finalization.get("tool_ids")
            receipts = finalization.get("build_receipt_hashes")
            attempt_hash = finalization.get("materialization_attempt_receipt_hash")
            identity_matches = (
                finalization.get("agent_id") == agent_id
                and finalization.get("stage") == stage
                and finalization.get("as_of") == as_of
            )
            tools_match = (
                isinstance(tool_ids, list)
                and tool_ids == sorted(expected_build_tools)
                and isinstance(receipts, Mapping)
                and set(receipts) == expected_build_tools
                and all(_is_sha256(value) for value in receipts.values())
            )
            deferred_matches = deferred_authority is None or (
                finalization.get("deferred_tool_ids")
                == deferred_authority["tool_ids"]
                and finalization.get("deferred_query_bundle_hash")
                == deferred_authority["frozen_bundle_hash"]
                and finalization.get("deferred_query_call_contract")
                == deferred_authority["call_contract"]
            )
            if not identity_matches:
                reasons.append("MATERIALIZATION_FINALIZER_IDENTITY_MISMATCH")
            if not tools_match:
                reasons.append("BUILD_RECEIPT_TOOL_CLOSURE_MISMATCH")
            if not deferred_matches:
                reasons.append("DEFERRED_QUERY_AUTHORITY_MISMATCH")
            attempt_matches = (
                attempt_hash is None
                if deferred_authority is not None
                else _is_sha256(attempt_hash)
            )
            if not attempt_matches:
                reasons.append("MATERIALIZATION_ATTEMPT_RECEIPT_INVALID")
            if identity_matches and tools_match and deferred_matches and attempt_matches:
                build_receipt_hashes = {
                    tool_id: str(receipts[tool_id])
                    for tool_id in sorted(expected_build_tools)
                }
                attempt_receipt_hash = (
                    str(attempt_hash) if attempt_hash is not None else None
                )
            if not reasons:
                eligibility = "ELIGIBLE"
        if (
            self.require_knot_v2_audit_authority
            and eligibility != "ELIGIBLE"
            and reasons != ["SYNTHETIC_NON_PRODUCTION_BYPASS"]
        ):
            raise ValueError(
                "production KNOT-v2 audit authority is incomplete: "
                + ",".join(sorted(reasons))
            )
        return {
            "schema_version": "snapshot_bundle_audit_context_v1",
            "snapshot_bundle_id": snapshot_bundle_id,
            "snapshot_bundle_hash": snapshot_bundle_hash,
            "agent_id": agent_id,
            "stage": stage,
            "as_of": as_of,
            "knot_v2_eligibility": eligibility,
            "ineligibility_reasons": sorted(reasons),
            "build_receipt_hashes": build_receipt_hashes,
            "materialization_attempt_receipt_hash": attempt_receipt_hash,
            **(
                {"deferred_query": deferred_authority}
                if deferred_authority is not None
                else {}
            ),
            **authority,
            "created_at": created_at,
        }

    def _build_capability_audit_context(
        self,
        *,
        manifest: Mapping[str, Any],
        snapshot_context: Mapping[str, Any],
        snapshot_context_hash: str,
        created_at: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "capability_audit_context_v1",
            "capability_id": manifest["capability_id"],
            "capability_manifest_hash": _sha256(manifest),
            "run_slot_id": manifest["run_slot_id"],
            "agent_id": manifest["agent_id"],
            "stage": manifest["stage"],
            "snapshot_bundle_id": manifest["snapshot_bundle_id"],
            "snapshot_bundle_hash": manifest["snapshot_bundle_hash"],
            "snapshot_bundle_audit_context_hash": snapshot_context_hash,
            "knot_v2_eligibility": snapshot_context["knot_v2_eligibility"],
            "created_at": created_at,
        }

    def _insert_snapshot_audit_context(
        self,
        conn: sqlite3.Connection,
        context: Mapping[str, Any],
    ) -> str:
        context_hash = _sha256(context)
        conn.execute(
            "INSERT INTO snapshot_bundle_audit_contexts VALUES (?, ?, ?, ?, ?, ?)",
            (
                context["snapshot_bundle_id"],
                _canonical_json(context),
                context_hash,
                self.signing_key_id,
                self._sign_domain(f"{context['schema_version']}:", context),
                context["created_at"],
            ),
        )
        return context_hash

    def _insert_capability_audit_context(
        self,
        conn: sqlite3.Connection,
        *,
        manifest: Mapping[str, Any],
        snapshot_context: Mapping[str, Any],
        snapshot_context_hash: str,
        created_at: str,
    ) -> str:
        context = self._build_capability_audit_context(
            manifest=manifest,
            snapshot_context=snapshot_context,
            snapshot_context_hash=snapshot_context_hash,
            created_at=created_at,
        )
        context_hash = _sha256(context)
        conn.execute(
            "INSERT INTO capability_audit_contexts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                manifest["capability_id"],
                manifest["snapshot_bundle_id"],
                snapshot_context_hash,
                _canonical_json(context),
                context_hash,
                self.signing_key_id,
                self._sign_domain("capability_audit_context_v1:", context),
                created_at,
            ),
        )
        return context_hash

    def _validated_snapshot_audit_context(
        self,
        row: sqlite3.Row,
        *,
        snapshot_bundle_id: str,
        snapshot_bundle_hash: str,
    ) -> tuple[dict[str, Any], str]:
        context = json.loads(row["context_json"])
        context_hash = _sha256(context)
        if (
            context.get("schema_version")
            not in {
                "snapshot_bundle_audit_context_v1",
                "snapshot_bundle_audit_context_v2",
            }
            or context.get("snapshot_bundle_id") != snapshot_bundle_id
            or context.get("snapshot_bundle_hash") != snapshot_bundle_hash
            or row["context_hash"] != context_hash
            or row["signing_key_id"] != self.signing_key_id
            or not hmac.compare_digest(
                row["signature"],
                self._sign_domain(
                    f"{context.get('schema_version')}:", context
                ),
            )
        ):
            raise ValueError("snapshot bundle audit context authority mismatch")
        return context, context_hash

    def _validated_capability_audit_context(
        self,
        row: sqlite3.Row,
        *,
        manifest: Mapping[str, Any],
        snapshot_context_hash: str,
    ) -> tuple[dict[str, Any], str]:
        context = json.loads(row["context_json"])
        context_hash = _sha256(context)
        if (
            context.get("schema_version") != "capability_audit_context_v1"
            or context.get("capability_id") != manifest["capability_id"]
            or context.get("capability_manifest_hash") != _sha256(manifest)
            or context.get("run_slot_id") != manifest["run_slot_id"]
            or context.get("snapshot_bundle_id") != manifest["snapshot_bundle_id"]
            or context.get("snapshot_bundle_hash") != manifest["snapshot_bundle_hash"]
            or context.get("snapshot_bundle_audit_context_hash")
            != snapshot_context_hash
            or row["context_hash"] != context_hash
            or row["snapshot_bundle_audit_context_hash"] != snapshot_context_hash
            or row["signing_key_id"] != self.signing_key_id
            or not hmac.compare_digest(
                row["signature"],
                self._sign_domain("capability_audit_context_v1:", context),
            )
        ):
            raise ValueError("capability audit context authority mismatch")
        return context, context_hash

    def _prepare_adaptive_query_descriptors(
        self,
        *,
        agent_id: str,
        stage: str,
        as_of: str,
        initial_payloads: Mapping[AgentToolId, str],
        runtime_inputs: Mapping[str, Any],
        candidate_scope: Mapping[str, Any] | None,
        adaptive_tools: Sequence[AgentToolId],
    ) -> tuple[dict[AgentToolId, str], dict[str, Any]]:
        if self.adaptive_query_store is None or self.adaptive_query_preparer is None:
            raise DataVendorUnavailable(
                "adaptive query compiler is unavailable for the active role whitelist"
            )
        prepared = self.adaptive_query_preparer(
            agent_id=agent_id,
            stage=stage,
            as_of=as_of,
            initial_payloads=dict(initial_payloads),
            runtime_inputs=dict(runtime_inputs),
            candidate_scope=(dict(candidate_scope) if candidate_scope is not None else None),
            allowed_tools=tuple(adaptive_tools),
        )
        if not isinstance(prepared, Mapping) or set(prepared) != {
            "bundle_id",
            "public_projection",
        }:
            raise ValueError("adaptive query compiler returned an invalid bundle reference")
        bundle_id = _required_string(prepared, "bundle_id")
        projection = prepared.get("public_projection")
        if not isinstance(projection, dict):
            raise ValueError("adaptive query public projection must be an object")
        projection_hash = projection.get("projection_hash")
        projection_body = {
            key: value for key, value in projection.items() if key != "projection_hash"
        }
        bundle_hash = projection.get("bundle_hash")
        entries = projection.get("entries")
        max_rounds = projection.get("adaptive_max_rounds")
        initial_payload_count = projection.get("initial_payload_count", 0)
        deferred = projection.get("call_contract") == CALL_TIME_ARGUMENT_CONTRACT
        if (
            projection.get("bundle_id") != bundle_id
            or projection.get("agent_id") != agent_id
            or projection.get("stage") != stage
            or projection.get("as_of") != as_of
            or not _is_sha256(bundle_hash)
            or not _is_sha256(projection_hash)
            or projection_hash != _sha256(projection_body)
            or not isinstance(entries, list)
            or projection.get("private_payload_count")
            != (0 if deferred else len(entries))
            or max_rounds not in {0, 3}
            or isinstance(initial_payload_count, bool)
            or not isinstance(initial_payload_count, int)
            or not 0 <= initial_payload_count <= len(entries)
        ):
            raise ValueError("adaptive query public projection binding is invalid")
        allowed = set(adaptive_tools)
        counts = dict.fromkeys(adaptive_tools, 0)
        initial_counts = dict.fromkeys(adaptive_tools, 0)
        follow_up_counts = dict.fromkeys(adaptive_tools, 0)
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or entry.get("tool_id") not in allowed
                or entry.get("call_mode") not in {"INITIAL", "FOLLOW_UP"}
                or not _is_sha256(entry.get("request_hash"))
            ):
                raise ValueError("adaptive query public projection entry is invalid")
            if deferred:
                if (
                    set(entry)
                    != {
                        "tool_id",
                        "request",
                        "request_hash",
                        "call_mode",
                        "binding_id",
                    }
                    or not isinstance(entry.get("request"), dict)
                    or _sha256(entry["request"]) != entry["request_hash"]
                    or not isinstance(entry.get("binding_id"), str)
                ):
                    raise ValueError("deferred query projection entry is invalid")
            elif "request" in entry or not _is_sha256(entry.get("payload_hash")):
                raise ValueError("eager query projection entry is invalid")
            tool_id = cast(AgentToolId, entry["tool_id"])
            counts[tool_id] += 1
            if entry["call_mode"] == "INITIAL":
                initial_counts[tool_id] += 1
            else:
                follow_up_counts[tool_id] += 1
        if (
            sum(initial_counts.values()) != initial_payload_count
            or (max_rounds == 0 and sum(follow_up_counts.values()) != 0)
            or (
                deferred
                and (
                    deferred_query_bundle_hash(projection) != bundle_hash
                    or bundle_id != "frozen_bundle_" + bundle_hash[7:]
                )
            )
        ):
            raise ValueError("adaptive query call modes do not match the public contract")
        if deferred:
            knot_authority = self._active_knot_audit_authority(
                agent_id=agent_id,
                stage=stage,
                allowed_tools=allowed_tools_for_agent(agent_id),
            )
            tool_contexts = knot_authority.get("tool_contexts")
            if not isinstance(tool_contexts, list):
                raise ValueError("deferred query KNOT tool authority is invalid")
            active_binding_ids: dict[str, str] = {}
            for tool_id in adaptive_tools:
                matching_contexts = [
                    context
                    for context in tool_contexts
                    if isinstance(context, Mapping)
                    and context.get("tool_id") == tool_id
                ]
                binding_refs = (
                    matching_contexts[0].get("binding_refs")
                    if len(matching_contexts) == 1
                    else None
                )
                if (
                    not isinstance(binding_refs, list)
                    or len(binding_refs) != 1
                    or not isinstance(binding_refs[0], Mapping)
                    or not isinstance(binding_refs[0].get("binding_id"), str)
                    or not binding_refs[0]["binding_id"]
                ):
                    raise ValueError(
                        f"deferred query active binding is not unique for {tool_id}"
                    )
                active_binding_ids[tool_id] = binding_refs[0]["binding_id"]
            rebound_body = {
                key: value
                for key, value in projection.items()
                if key not in {"bundle_id", "bundle_hash", "projection_hash"}
            }
            rebound_body["entries"] = [
                {
                    **entry,
                    "binding_id": active_binding_ids[cast(AgentToolId, entry["tool_id"])],
                }
                for entry in entries
            ]
            bundle_hash = deferred_query_bundle_hash(rebound_body)
            bundle_id = "frozen_bundle_" + bundle_hash[7:]
            projection_body = {
                **rebound_body,
                "bundle_id": bundle_id,
                "bundle_hash": bundle_hash,
            }
            projection = {
                **projection_body,
                "projection_hash": _sha256(projection_body),
            }
        descriptors = {
            tool_id: _canonical_json(
                {
                    "schema_version": "adaptive_tool_bundle_descriptor_v1",
                    "tool_id": tool_id,
                    "frozen_query_bundle_id": bundle_id,
                    "frozen_query_bundle_hash": bundle_hash,
                    "prepared_request_count": counts[tool_id],
                    "prepared_initial_count": initial_counts[tool_id],
                    "prepared_follow_up_count": follow_up_counts[tool_id],
                    "call_contract": (
                        CALL_TIME_ARGUMENT_CONTRACT
                        if deferred
                        else "EXACT_FROZEN_ARGS_ONLY"
                    ),
                    "adaptive_max_rounds": max_rounds,
                }
            )
            for tool_id in adaptive_tools
        }
        return descriptors, {
            "bundle_id": bundle_id,
            "bundle_hash": bundle_hash,
            "public_projection": projection,
            "max_rounds": max_rounds,
            "deferred": deferred,
        }

    def prepare_source_admission(
        self,
        *,
        as_of: str,
        route_id: str | None = None,
        historical_replay: bool = False,
        materializer: Callable[..., str] = materialize_tool_payload,
    ) -> dict[str, Any]:
        """Prepare the exact external-source union without signing capabilities."""
        date.fromisoformat(as_of)
        if not isinstance(historical_replay, bool):
            raise ValueError("historical_replay must be a boolean")
        if self.stage_materialization_preparer is None:
            raise DataVendorUnavailable("source family preparer is unavailable")

        manifest = load_agent_data_route_manifest()
        runtime_route_ids = {
            route["route_id"]
            for route in manifest["routes"]
            if route["pit_strategy"] == "LOCAL_RUNTIME_AUTHORITY"
        }
        external_route_ids = {
            route["route_id"]
            for route in manifest["routes"]
            if route["pit_strategy"] != "LOCAL_RUNTIME_AUTHORITY"
        }
        if route_id is not None and route_id not in external_route_ids:
            raise ValueError("source preparation route must be an external Agent route")
        bindings_by_stage: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for binding in manifest["bindings"]:
            key = (binding["agent_id"], binding["stage"])
            bindings_by_stage.setdefault(key, []).append(binding)
        source_stage_keys = sorted(
            key
            for key, bindings in bindings_by_stage.items()
            if not runtime_route_ids.intersection(
                route_id
                for binding in bindings
                for route_id in binding["required_route_ids"]
            )
        )
        family_stage_keys = {
            key
            for _representative, stage_keys in SOURCE_ADMISSION_FAMILY_STAGE_GROUPS
            for key in stage_keys
        }
        family_route_ids = {
            route_id
            for key in family_stage_keys
            for binding in bindings_by_stage.get(key, ())
            for route_id in binding["required_route_ids"]
        }
        if (
            len(external_route_ids) != 25
            or family_route_ids != external_route_ids
            or family_stage_keys != set(source_stage_keys)
        ):
            raise RuntimeError("source admission family closure drift")

        if route_id in QUERY_SCOPED_SOURCE_ROUTE_IDS:
            blocked_stage_ids = sorted(
                f"{agent_id}/{stage}"
                for agent_id, stage in source_stage_keys
                if any(
                    route_id in binding["required_route_ids"]
                    for binding in bindings_by_stage[(agent_id, stage)]
                )
            )
            return {
                "as_of": as_of,
                "adaptive_stage_count": 0,
                "blocked_stage_ids": blocked_stage_ids,
                "blocked_stage_reasons": {
                    stage_id: ["QUERY_SCOPE_REQUIRED"]
                    for stage_id in blocked_stage_ids
                },
                "family_stage_count": 0,
                "route_id": route_id,
                "status": "SOURCE_PREPARATION_BLOCKED",
            }

        selected_family_groups = SOURCE_ADMISSION_FAMILY_STAGE_GROUPS
        if route_id is not None:
            matching_groups = []
            for _representative, stage_keys in SOURCE_ADMISSION_FAMILY_STAGE_GROUPS:
                owning_stage_keys = tuple(
                    key
                    for key in stage_keys
                    if any(
                        route_id in binding["required_route_ids"]
                        for binding in bindings_by_stage[key]
                    )
                )
                if owning_stage_keys:
                    matching_groups.append((owning_stage_keys[0], stage_keys))
            selected_family_groups = tuple(matching_groups[:1])
            if not selected_family_groups:
                raise RuntimeError("source preparation route has no family authority")

        source_stage_preparer = (
            prepare_agent_stage_materialization_current_namespace
            if self.stage_materialization_preparer is ensure_agent_stage_materialization
            else self.stage_materialization_preparer
        )
        blocked_stages: set[str] = set()
        blocked_stage_reasons: dict[str, set[str]] = {}

        def record_blocker(stage_id: str, reason: str) -> None:
            blocked_stages.add(stage_id)
            blocked_stage_reasons.setdefault(stage_id, set()).add(reason)

        for (agent_id, stage), _stage_keys in selected_family_groups:
            stage_id = f"{agent_id}/{stage}"
            try:
                source_request = {
                    "agent_id": agent_id,
                    "stage": stage,
                    "as_of": as_of,
                }
                if route_id is not None:
                    source_request["route_id"] = route_id
                if historical_replay:
                    source_request["historical_replay"] = True
                result = source_stage_preparer(source_request)
            except DataVendorUnavailable as exc:
                record_blocker(stage_id, exc.reason_code)
                continue
            if isinstance(result, Mapping) and result.get("status") == "SHADOW_BLOCKED":
                record_blocker(stage_id, "SHADOW_ENSURE_BLOCKED")

        adaptive_stage_count = 0
        adaptive_stage_keys = source_stage_keys if route_id is None else ()
        for agent_id, stage in adaptive_stage_keys:
            stage_tools = tuple(
                cast(AgentToolId, binding["tool_id"])
                for binding in sorted(
                    bindings_by_stage[(agent_id, stage)],
                    key=lambda row: row["tool_id"],
                )
            )
            adaptive_tools = tuple(
                tool_id
                for tool_id in stage_tools
                if tool_id in ADAPTIVE_QUERY_TOOL_IDS
            )
            if not adaptive_tools:
                continue
            adaptive_stage_count += 1
            initial_payloads: dict[AgentToolId, str] = {}
            try:
                for tool_id in stage_tools:
                    if tool_id not in INITIAL_SNAPSHOT_TOOL_IDS:
                        continue
                    materializer_kwargs = {
                        "agent_id": agent_id,
                        "stage": stage,
                        "as_of": as_of,
                        "graph_run_id": f"source-preflight:{as_of}",
                    }
                    if materializer is materialize_tool_payload:
                        initial_payloads[tool_id] = materializer(
                            tool_id,
                            **materializer_kwargs,
                            expected_candidate_scope_hash=None,
                            accepted_output_refs=None,
                        )
                    else:
                        initial_payloads[tool_id] = materializer(
                            tool_id, **materializer_kwargs
                        )
                self._prepare_adaptive_query_descriptors(
                    agent_id=agent_id,
                    stage=stage,
                    as_of=as_of,
                    initial_payloads=initial_payloads,
                    runtime_inputs={},
                    candidate_scope=None,
                    adaptive_tools=adaptive_tools,
                )
            except DataVendorUnavailable as exc:
                record_blocker(
                    f"{agent_id}/{stage}",
                    exc.reason_code,
                )

        result = {
            "as_of": as_of,
            "adaptive_stage_count": adaptive_stage_count,
            "family_stage_count": len(selected_family_groups),
            "status": (
                "SOURCE_PREPARED" if not blocked_stages else "SOURCE_PREPARATION_BLOCKED"
            ),
        }
        if route_id is not None:
            result["route_id"] = route_id
        if blocked_stages:
            result["blocked_stage_ids"] = sorted(blocked_stages)
            result["blocked_stage_reasons"] = {
                stage_id: sorted(blocked_stage_reasons[stage_id])
                for stage_id in sorted(blocked_stage_reasons)
            }
        return result

    def prepare(
        self,
        request: Mapping[str, Any],
        *,
        materializer: Callable[..., str] = materialize_tool_payload,
    ) -> dict[str, Any]:
        graph_run_id = _required_string(request, "graph_run_id")
        run_slot_id = _required_string(request, "run_slot_id")
        run_id = _required_string(request, "run_id")
        node_id = _required_string(request, "node_id")
        agent_id = _required_string(request, "agent_id")
        stage = execution_stage_for_agent(agent_id, request.get("stage"))
        as_of = _required_string(request, "as_of")
        date.fromisoformat(as_of)
        materialization_request_id = _required_string(
            request, "materialization_request_id"
        )
        runtime_inputs = request.get("runtime_inputs", {})
        candidate_scope = request.get("candidate_scope")
        if not isinstance(runtime_inputs, dict):
            raise ValueError("runtime_inputs must be an object")
        if candidate_scope is not None and not isinstance(candidate_scope, dict):
            raise ValueError("candidate_scope must be an object or null")
        runtime_input_hash = _sha256(runtime_inputs)
        now = self.clock().astimezone(timezone.utc)
        ttl = request.get("ttl_seconds", DEFAULT_CAPABILITY_TTL_SECONDS)
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 3600:
            raise ValueError("ttl_seconds must be an integer in [1, 3600]")
        allowed_tools = allowed_tools_for_agent(agent_id)
        adaptive_tools = tuple(
            tool_id for tool_id in allowed_tools if tool_id in ADAPTIVE_QUERY_TOOL_IDS
        )
        adaptive_enabled = bool(adaptive_tools) and self.adaptive_query_store is not None
        deferred_request_only = adaptive_enabled and isinstance(
            self.adaptive_query_preparer, ActiveAdaptiveQueryPreparer
        )
        normalized_request = dict(request)
        normalized_request["stage"] = stage
        normalized_request["runtime_inputs"] = runtime_inputs
        normalized_request["candidate_scope"] = candidate_scope
        stage_request = (
            trusted_deferred_request_only_request(
                normalized_request,
                tool_ids=adaptive_tools,
            )
            if deferred_request_only
            else normalized_request
        )
        stage_preparation = (
            self.stage_materialization_preparer(stage_request)
            if self.stage_materialization_preparer is not None
            else None
        )
        ensure_mode = (
            stage_preparation.get("ensure_mode")
            if isinstance(stage_preparation, Mapping)
            else None
        )
        if ensure_mode not in {None, "off", "shadow", "enforce"}:
            raise ValueError("stage preparation returned an invalid ensure_mode")
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO materialization_requests VALUES (?, ?, ?, ?, ?)",
                    (materialization_request_id, agent_id, stage, as_of, now.isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("materialization_request_id has already been used") from exc

        if adaptive_tools and materializer is materialize_tool_payload and not adaptive_enabled:
            raise DataVendorUnavailable(
                "adaptive query compiler is unavailable for the active role whitelist"
            )
        materialized_tools = (
            tuple(
                tool_id
                for tool_id in allowed_tools
                if tool_id in INITIAL_SNAPSHOT_TOOL_IDS
            )
            if adaptive_enabled
            else allowed_tools
        )
        payloads: dict[AgentToolId, str] = {}
        for tool_id in materialized_tools:
            materializer_kwargs = {
                "agent_id": agent_id,
                "stage": stage,
                "as_of": as_of,
                "graph_run_id": graph_run_id,
            }
            if materializer is materialize_tool_payload:
                payloads[tool_id] = materializer(
                    tool_id,
                    **materializer_kwargs,
                    expected_candidate_scope_hash=None,
                    accepted_output_refs=(
                        candidate_scope.get("accepted_output_refs")
                        if isinstance(candidate_scope, dict)
                        else None
                    ),
                )
            else:
                payloads[tool_id] = materializer(tool_id, **materializer_kwargs)
        adaptive_ref: dict[str, Any] | None = None
        if adaptive_enabled:
            descriptors, adaptive_ref = self._prepare_adaptive_query_descriptors(
                agent_id=agent_id,
                stage=stage,
                as_of=as_of,
                initial_payloads=payloads,
                runtime_inputs=runtime_inputs,
                candidate_scope=candidate_scope,
                adaptive_tools=adaptive_tools,
            )
            payloads.update(descriptors)
        if deferred_request_only != bool(
            adaptive_ref is not None and adaptive_ref["deferred"]
        ):
            raise ValueError("adaptive query preparation mode changed after stage preparation")
        if set(payloads) != set(allowed_tools):
            raise ValueError("materialized payload keys do not match allowed tools")
        if any(not isinstance(payload, str) or not payload for payload in payloads.values()):
            raise ValueError("every materialized tool payload must be a non-empty string")
        _validate_live_outcome_authority(
            agent_id=agent_id,
            runtime_inputs=runtime_inputs,
            payloads=payloads,
        )

        authoritative_scope_hashes: set[str] = set()
        for tool_id, rendered in payloads.items():
            if (
                materializer is not materialize_tool_payload
                or tool_id not in BOUND_RUNTIME_SNAPSHOT_CONTRACTS
            ):
                continue
            try:
                bound_payload = json.loads(rendered)
            except json.JSONDecodeError as exc:  # pragma: no cover - validator owns this
                raise ValueError("bound runtime snapshot is not valid JSON") from exc
            scope_hash = bound_payload.get("candidate_scope_hash")
            if not _is_sha256(scope_hash):
                raise ValueError("bound runtime snapshot has no authoritative scope hash")
            _validate_bound_request_closure(
                payload=bound_payload,
                runtime_inputs=runtime_inputs,
                candidate_scope=candidate_scope,
            )
            authoritative_scope_hashes.add(scope_hash)
        if len(authoritative_scope_hashes) > 1:
            raise ValueError("bound runtime snapshots disagree on candidate scope")
        candidate_scope_hash = (
            next(iter(authoritative_scope_hashes))
            if authoritative_scope_hashes
            else (_sha256(candidate_scope) if candidate_scope is not None else None)
        )

        snapshot_bundle_id = f"bundle_{uuid.uuid4().hex}"
        payload_hashes = {
            tool_id: _sha256_text(payload) for tool_id, payload in payloads.items()
        }
        finalization: Any = None
        if (
            self.stage_materialization_finalizer is not None
            and ensure_mode not in {"off", "shadow"}
        ):
            finalization = self.stage_materialization_finalizer(
                {
                    **normalized_request,
                    "stage_preparation": stage_preparation,
                    "tool_payload_hashes": dict(payload_hashes),
                    "adaptive_query": (
                        dict(adaptive_ref) if adaptive_ref is not None else None
                    ),
                    **(
                        {
                            "deferred_tool_ids": sorted(adaptive_tools),
                            "initial_snapshot_tool_ids": sorted(materialized_tools),
                        }
                        if deferred_request_only
                        else {}
                    ),
                }
            )
        bundle_without_hash = {
            "snapshot_bundle_id": snapshot_bundle_id,
            "snapshot_bundle_contract_version": SNAPSHOT_BUNDLE_CONTRACT_VERSION,
            "materialization_request_id": materialization_request_id,
            "agent_id": agent_id,
            "stage": stage,
            "as_of": as_of,
            "candidate_scope_hash": candidate_scope_hash,
            "runtime_input_hash": runtime_input_hash,
            "tool_payload_hashes": payload_hashes,
            "materialized_at": now.isoformat(),
        }
        snapshot_bundle_hash = _sha256(bundle_without_hash)
        bundle = {
            **bundle_without_hash,
            "snapshot_bundle_hash": snapshot_bundle_hash,
        }
        snapshot_audit_context = self._build_snapshot_audit_context(
            snapshot_bundle_id=snapshot_bundle_id,
            snapshot_bundle_hash=snapshot_bundle_hash,
            agent_id=agent_id,
            stage=stage,
            as_of=as_of,
            allowed_tools=allowed_tools,
            finalization=finalization,
            deferred_query=(
                {
                    "call_contract": CALL_TIME_ARGUMENT_CONTRACT,
                    "frozen_bundle_hash": adaptive_ref["bundle_hash"],
                    "tool_ids": sorted(adaptive_tools),
                }
                if deferred_request_only and adaptive_ref is not None
                else None
            ),
            created_at=now.isoformat(),
        )
        capability_id = f"cap_{uuid.uuid4().hex}"
        manifest = {
            "capability_contract_version": CAPABILITY_CONTRACT_VERSION,
            "capability_id": capability_id,
            "graph_run_id": graph_run_id,
            "run_slot_id": run_slot_id,
            "run_id": run_id,
            "node_id": node_id,
            "agent_id": agent_id,
            "stage": stage,
            "allowed_tools": list(allowed_tools),
            "as_of": as_of,
            "candidate_scope_hash": bundle["candidate_scope_hash"],
            "snapshot_bundle_id": snapshot_bundle_id,
            "snapshot_bundle_hash": snapshot_bundle_hash,
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
            "nonce": secrets.token_hex(24),
        }
        signed = SignedCapability(
            manifest=manifest,
            signing_key_id=self.signing_key_id,
            signature=self._sign(manifest),
        )
        adaptive_session_id = (
            self.adaptive_query_store.start_session(
                bundle_id=adaptive_ref["bundle_id"],
                agent_id=agent_id,
                stage=stage,
            )
            if (
                adaptive_ref is not None
                and adaptive_ref["max_rounds"] > 0
                and not adaptive_ref["deferred"]
                and self.adaptive_query_store is not None
            )
            else None
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO snapshot_bundles VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        snapshot_bundle_id,
                        snapshot_bundle_hash,
                        materialization_request_id,
                        _canonical_json(bundle),
                        _canonical_json(payloads),
                        now.isoformat(),
                    ),
                )
                snapshot_audit_context_hash = self._insert_snapshot_audit_context(
                    conn, snapshot_audit_context
                )
                if adaptive_ref is not None:
                    conn.execute(
                        "INSERT INTO snapshot_bundle_adaptive_queries VALUES (?, ?, ?, ?, ?)",
                        (
                            snapshot_bundle_id,
                            adaptive_ref["bundle_id"],
                            adaptive_ref["bundle_hash"],
                            _canonical_json(adaptive_ref["public_projection"]),
                            now.isoformat(),
                        ),
                    )
                conn.execute(
                    "INSERT INTO capabilities VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        capability_id,
                        snapshot_bundle_id,
                        _canonical_json(manifest),
                        self.signing_key_id,
                        signed.signature,
                        now.isoformat(),
                    ),
                )
                self._insert_capability_audit_context(
                    conn,
                    manifest=manifest,
                    snapshot_context=snapshot_audit_context,
                    snapshot_context_hash=snapshot_audit_context_hash,
                    created_at=now.isoformat(),
                )
                if adaptive_ref is not None and adaptive_session_id is not None:
                    conn.execute(
                        "INSERT INTO capability_adaptive_sessions VALUES (?, ?, ?, ?, ?)",
                        (
                            capability_id,
                            adaptive_ref["bundle_id"],
                            adaptive_ref["bundle_hash"],
                            adaptive_session_id,
                            now.isoformat(),
                        ),
                    )
                conn.execute(
                    "INSERT INTO capability_events VALUES (?, ?, 'ISSUED', ?, NULL)",
                    (f"evt_{uuid.uuid4().hex}", capability_id, now.isoformat()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        result = {"bundle": bundle, "capability": signed.as_dict()}
        if adaptive_ref is not None:
            result["prepared_initial_tool_ids"] = _prepared_initial_tool_ids(
                adaptive_ref["public_projection"]
            )
        return result

    def issue_for_bundle(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Issue another node-bound capability without re-running collectors."""
        graph_run_id = _required_string(request, "graph_run_id")
        run_slot_id = _required_string(request, "run_slot_id")
        run_id = _required_string(request, "run_id")
        node_id = _required_string(request, "node_id")
        agent_id = _required_string(request, "agent_id")
        stage = execution_stage_for_agent(agent_id, request.get("stage"))
        as_of = _required_string(request, "as_of")
        date.fromisoformat(as_of)
        snapshot_bundle_id = _required_string(request, "snapshot_bundle_id")
        snapshot_bundle_hash = _required_string(request, "snapshot_bundle_hash")
        ttl = request.get("ttl_seconds", DEFAULT_CAPABILITY_TTL_SECONDS)
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 3600:
            raise ValueError("ttl_seconds must be an integer in [1, 3600]")

        with self._connect() as conn:
            row = conn.execute(
                "SELECT bundle_json, payloads_json FROM snapshot_bundles WHERE snapshot_bundle_id = ?",
                (snapshot_bundle_id,),
            ).fetchone()
            adaptive_row = conn.execute(
                "SELECT frozen_bundle_id, frozen_bundle_hash, public_projection_json "
                "FROM snapshot_bundle_adaptive_queries WHERE snapshot_bundle_id = ?",
                (snapshot_bundle_id,),
            ).fetchone()
            snapshot_audit_row = conn.execute(
                "SELECT * FROM snapshot_bundle_audit_contexts "
                "WHERE snapshot_bundle_id = ?",
                (snapshot_bundle_id,),
            ).fetchone()
        if row is None:
            raise ValueError("unknown snapshot_bundle_id")
        bundle = json.loads(row["bundle_json"])
        if (
            bundle.get("snapshot_bundle_hash") != snapshot_bundle_hash
            or bundle.get("agent_id") != agent_id
            or bundle.get("stage") != stage
            or bundle.get("as_of") != as_of
        ):
            raise ValueError("requested capability does not match the snapshot bundle")
        bundle_without_hash = {
            key: value for key, value in bundle.items() if key != "snapshot_bundle_hash"
        }
        if snapshot_bundle_hash != _sha256(bundle_without_hash):
            raise ValueError("snapshot bundle hash mismatch")
        allowed_tools = allowed_tools_for_agent(agent_id)
        payload_hashes = bundle.get("tool_payload_hashes")
        payloads = json.loads(row["payloads_json"])
        if (
            not isinstance(payload_hashes, dict)
            or not isinstance(payloads, dict)
            or set(payload_hashes) != set(allowed_tools)
            or set(payloads) != set(allowed_tools)
        ):
            raise ValueError("snapshot bundle tools do not match the canonical role whitelist")
        for tool_id in allowed_tools:
            payload = payloads.get(tool_id)
            if not isinstance(payload, str) or payload_hashes.get(tool_id) != _sha256_text(payload):
                raise ValueError("snapshot bundle payload hash mismatch")
        snapshot_audit_context: dict[str, Any] | None = None
        snapshot_audit_context_hash: str | None = None
        if snapshot_audit_row is not None:
            snapshot_audit_context, snapshot_audit_context_hash = (
                self._validated_snapshot_audit_context(
                    snapshot_audit_row,
                    snapshot_bundle_id=snapshot_bundle_id,
                    snapshot_bundle_hash=snapshot_bundle_hash,
                )
            )

        now = self.clock().astimezone(timezone.utc)
        capability_id = f"cap_{uuid.uuid4().hex}"
        manifest = {
            "capability_contract_version": CAPABILITY_CONTRACT_VERSION,
            "capability_id": capability_id,
            "graph_run_id": graph_run_id,
            "run_slot_id": run_slot_id,
            "run_id": run_id,
            "node_id": node_id,
            "agent_id": agent_id,
            "stage": stage,
            "allowed_tools": list(allowed_tools),
            "as_of": as_of,
            "candidate_scope_hash": bundle.get("candidate_scope_hash"),
            "snapshot_bundle_id": snapshot_bundle_id,
            "snapshot_bundle_hash": snapshot_bundle_hash,
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
            "nonce": secrets.token_hex(24),
        }
        signed = SignedCapability(
            manifest=manifest,
            signing_key_id=self.signing_key_id,
            signature=self._sign(manifest),
        )
        if adaptive_row is not None and self.adaptive_query_store is None:
            raise ValueError("adaptive query store is unavailable for this snapshot bundle")
        adaptive_projection = (
            json.loads(adaptive_row["public_projection_json"])
            if adaptive_row is not None
            else None
        )
        adaptive_max_rounds = (
            adaptive_projection.get("adaptive_max_rounds")
            if isinstance(adaptive_projection, dict)
            else None
        )
        adaptive_deferred = (
            isinstance(adaptive_projection, dict)
            and adaptive_projection.get("call_contract")
            == CALL_TIME_ARGUMENT_CONTRACT
        )
        if adaptive_row is not None and adaptive_max_rounds not in {0, 3}:
            raise ValueError("adaptive query projection has an invalid round limit")
        if adaptive_deferred and (
            adaptive_projection.get("projection_hash")
            != _sha256(
                {
                    key: value
                    for key, value in adaptive_projection.items()
                    if key != "projection_hash"
                }
            )
            or deferred_query_bundle_hash(adaptive_projection)
            != adaptive_row["frozen_bundle_hash"]
            or adaptive_projection.get("bundle_id")
            != adaptive_row["frozen_bundle_id"]
        ):
            raise ValueError("deferred query projection binding is invalid")
        if adaptive_deferred:
            for tool_id in allowed_tools:
                if tool_id not in ADAPTIVE_QUERY_TOOL_IDS:
                    continue
                descriptor = json.loads(payloads[tool_id])
                if (
                    descriptor.get("frozen_query_bundle_id")
                    != adaptive_row["frozen_bundle_id"]
                    or descriptor.get("frozen_query_bundle_hash")
                    != adaptive_row["frozen_bundle_hash"]
                    or descriptor.get("call_contract")
                    != CALL_TIME_ARGUMENT_CONTRACT
                ):
                    raise ValueError("deferred query descriptor binding is invalid")
        adaptive_session_id = (
            self.adaptive_query_store.start_session(
                bundle_id=adaptive_row["frozen_bundle_id"],
                agent_id=agent_id,
                stage=stage,
            )
            if (
                adaptive_row is not None
                and adaptive_max_rounds > 0
                and not adaptive_deferred
                and self.adaptive_query_store is not None
            )
            else None
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO capabilities VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        capability_id,
                        snapshot_bundle_id,
                        _canonical_json(manifest),
                        self.signing_key_id,
                        signed.signature,
                        now.isoformat(),
                    ),
                )
                if (
                    snapshot_audit_context is not None
                    and snapshot_audit_context_hash is not None
                ):
                    self._insert_capability_audit_context(
                        conn,
                        manifest=manifest,
                        snapshot_context=snapshot_audit_context,
                        snapshot_context_hash=snapshot_audit_context_hash,
                        created_at=now.isoformat(),
                    )
                if adaptive_row is not None and adaptive_session_id is not None:
                    conn.execute(
                        "INSERT INTO capability_adaptive_sessions VALUES (?, ?, ?, ?, ?)",
                        (
                            capability_id,
                            adaptive_row["frozen_bundle_id"],
                            adaptive_row["frozen_bundle_hash"],
                            adaptive_session_id,
                            now.isoformat(),
                        ),
                    )
                conn.execute(
                    "INSERT INTO capability_events VALUES (?, ?, 'ISSUED', ?, NULL)",
                    (f"evt_{uuid.uuid4().hex}", capability_id, now.isoformat()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        result = {"bundle": bundle, "capability": signed.as_dict()}
        if adaptive_projection is not None:
            result["prepared_initial_tool_ids"] = _prepared_initial_tool_ids(
                adaptive_projection
            )
        return result

    def _verify(
        self,
        envelope: Mapping[str, Any],
        *,
        conn: sqlite3.Connection | None = None,
        allow_terminated: bool = False,
        verified_at: datetime | None = None,
    ) -> tuple[dict[str, Any], sqlite3.Row]:
        manifest = envelope.get("manifest")
        key_id = envelope.get("signing_key_id")
        signature = envelope.get("signature")
        if not isinstance(manifest, dict):
            raise ValueError("capability manifest must be an object")
        if key_id != self.signing_key_id or not isinstance(signature, str):
            raise ValueError("unknown capability signing key")
        expected = self._sign(manifest)
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid capability signature")
        capability_id = _required_string(manifest, "capability_id")
        for field in ("graph_run_id", "run_slot_id", "run_id", "node_id", "nonce"):
            _required_string(manifest, field)
        agent_id = _required_string(manifest, "agent_id")
        stage = execution_stage_for_agent(agent_id, _required_string(manifest, "stage"))
        as_of = _required_string(manifest, "as_of")
        date.fromisoformat(as_of)
        if manifest.get("capability_contract_version") != CAPABILITY_CONTRACT_VERSION:
            raise ValueError("capability contract version mismatch")
        if not _is_sha256(manifest.get("snapshot_bundle_hash")):
            raise ValueError("capability snapshot_bundle_hash is invalid")
        candidate_scope_hash = manifest.get("candidate_scope_hash")
        if candidate_scope_hash is not None and not _is_sha256(candidate_scope_hash):
            raise ValueError("capability candidate_scope_hash is invalid")
        allowed = manifest.get("allowed_tools")
        if not isinstance(allowed, list) or tuple(allowed) != allowed_tools_for_agent(agent_id):
            raise ValueError("capability tools do not match the canonical role whitelist")
        issued_at = datetime.fromisoformat(_required_string(manifest, "issued_at"))
        expires_at = datetime.fromisoformat(_required_string(manifest, "expires_at"))
        if issued_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("capability timestamps must be timezone-aware")
        issued_at = issued_at.astimezone(timezone.utc)
        expires_at = expires_at.astimezone(timezone.utc)
        if expires_at <= issued_at or expires_at - issued_at > timedelta(seconds=3600):
            raise ValueError("capability lifetime is invalid")
        now = (verified_at or self.clock()).astimezone(timezone.utc)
        if now < issued_at:
            raise ValueError("capability is not yet valid")
        if now >= expires_at:
            raise ValueError("capability is expired")

        def verify_ledger(connection: sqlite3.Connection) -> sqlite3.Row:
            row = connection.execute(
                """
                SELECT c.*, b.bundle_json, b.payloads_json
                FROM capabilities c
                JOIN snapshot_bundles b USING(snapshot_bundle_id)
                WHERE c.capability_id = ?
                """,
                (capability_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown capability_id")
            if (
                row["manifest_json"] != _canonical_json(manifest)
                or row["signature"] != signature
                or row["signing_key_id"] != key_id
            ):
                raise ValueError("capability does not match the issued ledger record")
            terminated = connection.execute(
                "SELECT 1 FROM capability_events "
                "WHERE capability_id = ? AND event_type = 'TERMINATED'",
                (capability_id,),
            ).fetchone()
            if terminated is not None and not allow_terminated:
                raise ValueError("capability is terminated")
            return row

        if conn is None:
            with self._connect() as connection:
                row = verify_ledger(connection)
        else:
            row = verify_ledger(conn)
        bundle = json.loads(row["bundle_json"])
        if (
            manifest.get("snapshot_bundle_id") != bundle.get("snapshot_bundle_id")
            or manifest.get("snapshot_bundle_hash") != bundle.get("snapshot_bundle_hash")
            or agent_id != bundle.get("agent_id")
            or stage != bundle.get("stage")
            or as_of != bundle.get("as_of")
            or manifest.get("candidate_scope_hash") != bundle.get("candidate_scope_hash")
        ):
            raise ValueError("capability/bundle binding mismatch")
        if bundle.get("snapshot_bundle_contract_version") != SNAPSHOT_BUNDLE_CONTRACT_VERSION:
            raise ValueError("snapshot bundle contract version mismatch")
        declared_bundle_hash = bundle.get("snapshot_bundle_hash")
        bundle_without_hash = {
            key: value for key, value in bundle.items() if key != "snapshot_bundle_hash"
        }
        if declared_bundle_hash != _sha256(bundle_without_hash):
            raise ValueError("snapshot bundle hash mismatch")
        if not _is_sha256(bundle.get("runtime_input_hash")):
            raise ValueError("snapshot bundle runtime_input_hash is invalid")
        payload_hashes = bundle.get("tool_payload_hashes")
        if not isinstance(payload_hashes, dict) or set(payload_hashes) != set(allowed):
            raise ValueError("capability tools do not match bundle payloads")
        payloads = json.loads(row["payloads_json"])
        if not isinstance(payloads, dict) or set(payloads) != set(allowed):
            raise ValueError("snapshot bundle payload keys mismatch")
        for tool_id in allowed:
            payload = payloads.get(tool_id)
            if not isinstance(payload, str) or not payload:
                raise ValueError("snapshot bundle payload is missing")
            if payload_hashes.get(tool_id) != _sha256_text(payload):
                raise ValueError("snapshot bundle payload hash mismatch")
        return manifest, row







    def record_sector_model_usage(
        self,
        *,
        capability_envelope: Mapping[str, Any],
        usage_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append one provider-reported Sector model subcall at the call boundary."""
        expected_keys = {
            "model_subcall_id",
            "attempted_stage",
            "attempt_index",
            "attempt_status",
            "input_tokens",
            "output_tokens",
            "provider_usage_evidence_id",
            "provider_usage_evidence_hash",
            "direction_comparison_audit_id",
            "direction_comparison_audit_hash",
            "conflict_review_id",
            "conflict_review_hash",
        }
        if set(usage_report) != expected_keys:
            raise ValueError("Sector model usage report fields mismatch")
        normalized: dict[str, Any] = {
            "model_subcall_id": _required_string(usage_report, "model_subcall_id"),
            "attempted_stage": _required_string(usage_report, "attempted_stage"),
            "attempt_index": usage_report.get("attempt_index"),
            "attempt_status": _required_string(usage_report, "attempt_status"),
            "input_tokens": usage_report.get("input_tokens"),
            "output_tokens": usage_report.get("output_tokens"),
            "provider_usage_evidence_id": _required_string(
                usage_report, "provider_usage_evidence_id"
            ),
            "provider_usage_evidence_hash": usage_report.get(
                "provider_usage_evidence_hash"
            ),
            "direction_comparison_audit_id": usage_report.get(
                "direction_comparison_audit_id"
            ),
            "direction_comparison_audit_hash": usage_report.get(
                "direction_comparison_audit_hash"
            ),
            "conflict_review_id": usage_report.get("conflict_review_id"),
            "conflict_review_hash": usage_report.get("conflict_review_hash"),
        }
        if normalized["attempted_stage"] not in {
            "DIRECTION_RESEARCH",
            "CONFLICT_REVIEW",
            "FINAL_SELECTION",
        }:
            raise ValueError("Sector attempted stage is invalid")
        if normalized["attempt_status"] not in {
            "ACCEPTED",
            "REJECTED",
            "OPERATIONAL_FAILURE",
        }:
            raise ValueError("Sector attempt status is invalid")
        for field in ("attempt_index", "input_tokens", "output_tokens"):
            item = normalized[field]
            minimum = 1 if field == "attempt_index" else 0
            if isinstance(item, bool) or not isinstance(item, int) or item < minimum:
                raise ValueError(f"Sector {field} is invalid")
        if not _is_sha256(normalized["provider_usage_evidence_hash"]):
            raise ValueError("Sector provider usage evidence hash is invalid")
        for id_field, hash_field in (
            ("direction_comparison_audit_id", "direction_comparison_audit_hash"),
            ("conflict_review_id", "conflict_review_hash"),
        ):
            identifier = normalized[id_field]
            digest = normalized[hash_field]
            if (identifier is None) != (digest is None):
                raise ValueError(f"Sector {id_field}/{hash_field} must be paired")
            if identifier is not None:
                _required_string(normalized, id_field)
                if not _is_sha256(digest):
                    raise ValueError(f"Sector {hash_field} is invalid")
        model_subcall_id = normalized["model_subcall_id"]
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT event_json FROM sector_model_usage_events "
                    "WHERE model_subcall_id = ?",
                    (model_subcall_id,),
                ).fetchone()
                if existing is not None:
                    event = json.loads(existing["event_json"])
                    manifest, _ = self._verify(
                        capability_envelope,
                        conn=conn,
                        allow_terminated=True,
                        verified_at=_aware_timestamp(
                            event["recorded_at"], "usage_event.recorded_at"
                        ),
                    )
                    if (
                        event.get("capability_id") != manifest["capability_id"]
                        or event.get("usage_report") != normalized
                    ):
                        raise ValueError(
                            "Sector usage retry changed immutable inputs"
                        )
                    conn.execute("COMMIT")
                    return event
                recorded_at = self.clock().astimezone(timezone.utc)
                manifest, _ = self._verify(
                    capability_envelope,
                    conn=conn,
                    verified_at=recorded_at,
                )
                if manifest["agent_id"] not in STANDARD_SECTOR_AGENTS:
                    raise ValueError(
                        "model usage instrumentation is restricted to standard Sector"
                    )
                uses = conn.execute(
                    "SELECT tool_id FROM capability_tool_uses "
                    "WHERE capability_id = ? ORDER BY tool_id",
                    (manifest["capability_id"],),
                ).fetchall()
                required_initial_tools = sorted(
                    tool_id
                    for tool_id in manifest["allowed_tools"]
                    if tool_id in INITIAL_SNAPSHOT_TOOL_IDS
                )
                if [row["tool_id"] for row in uses] != required_initial_tools:
                    raise ValueError(
                        "Sector model usage requires the exact initial snapshot tool set"
                    )
                prior = conn.execute(
                    "SELECT event_json FROM sector_model_usage_events "
                    "WHERE capability_id = ? ORDER BY subcall_sequence",
                    (manifest["capability_id"],),
                ).fetchall()
                previous_events = [json.loads(row["event_json"]) for row in prior]
                sequence = len(previous_events) + 1
                stage_order = {
                    "DIRECTION_RESEARCH": 1,
                    "CONFLICT_REVIEW": 2,
                    "FINAL_SELECTION": 3,
                }
                same_stage = [
                    event
                    for event in previous_events
                    if event["usage_report"]["attempted_stage"]
                    == normalized["attempted_stage"]
                ]
                if normalized["attempt_index"] != len(same_stage) + 1:
                    raise ValueError("Sector attempt indexes are not contiguous")
                if previous_events:
                    previous_stage = previous_events[-1]["usage_report"][
                        "attempted_stage"
                    ]
                    previous_order = stage_order[previous_stage]
                    current_order = stage_order[normalized["attempted_stage"]]
                    if current_order < previous_order:
                        raise ValueError("Sector attempted stage order is invalid")
                    if (
                        current_order == previous_order
                        and previous_events[-1]["usage_report"]["attempt_status"]
                        == "ACCEPTED"
                    ):
                        raise ValueError(
                            "Sector cannot retry an accepted model stage"
                        )
                    if (
                        current_order > previous_order
                        and previous_events[-1]["usage_report"]["attempt_status"]
                        != "ACCEPTED"
                    ):
                        raise ValueError(
                            "Sector cannot advance after an unaccepted subcall"
                        )
                elif normalized["attempted_stage"] != "DIRECTION_RESEARCH":
                    raise ValueError(
                        "Sector usage must begin with direction research"
                    )
                direction_ref_present = (
                    normalized["direction_comparison_audit_id"] is not None
                )
                conflict_ref_present = normalized["conflict_review_id"] is not None
                if normalized["attempted_stage"] == "DIRECTION_RESEARCH" and (
                    direction_ref_present or conflict_ref_present
                ):
                    raise ValueError(
                        "Sector direction research cannot carry downstream audit refs"
                    )
                if (
                    normalized["attempted_stage"] == "CONFLICT_REVIEW"
                    and (direction_ref_present or conflict_ref_present)
                ):
                    raise ValueError(
                        "Sector conflict review cannot carry not-yet-finalized audit refs"
                    )
                if (
                    normalized["attempted_stage"] == "FINAL_SELECTION"
                    and not direction_ref_present
                ):
                    raise ValueError(
                        "Sector final selection usage requires direction comparison"
                    )
                previous_conflict = any(
                    event["usage_report"]["attempted_stage"] == "CONFLICT_REVIEW"
                    for event in previous_events
                )
                if normalized["attempted_stage"] == "FINAL_SELECTION" and (
                    conflict_ref_present != previous_conflict
                ):
                    raise ValueError(
                        "Sector final selection conflict ref differs from its stage path"
                    )
                for id_field, hash_field in (
                    (
                        "direction_comparison_audit_id",
                        "direction_comparison_audit_hash",
                    ),
                    ("conflict_review_id", "conflict_review_hash"),
                ):
                    prior_refs = {
                        (
                            event["usage_report"][id_field],
                            event["usage_report"][hash_field],
                        )
                        for event in previous_events
                        if event["usage_report"][id_field] is not None
                    }
                    current_ref = (normalized[id_field], normalized[hash_field])
                    if prior_refs and current_ref not in prior_refs:
                        raise ValueError(
                            f"Sector {id_field} changed across model stages"
                        )
                event_without_hash = {
                    "schema_version": "sector_model_usage_event_v1",
                    "usage_event_id": f"sector-usage-event:{uuid.uuid4().hex}",
                    "capability_id": manifest["capability_id"],
                    "capability_manifest_hash": _sha256(manifest),
                    "graph_run_id": manifest["graph_run_id"],
                    "run_slot_id": manifest["run_slot_id"],
                    "run_id": manifest["run_id"],
                    "node_id": manifest["node_id"],
                    "agent_id": manifest["agent_id"],
                    "stage": manifest["stage"],
                    "as_of": manifest["as_of"],
                    "subcall_sequence": sequence,
                    "usage_report": normalized,
                    "recorded_at": recorded_at.isoformat(),
                }
                event = {
                    **event_without_hash,
                    "usage_event_hash": _sha256(event_without_hash),
                }
                conn.execute(
                    "INSERT INTO sector_model_usage_events "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event["usage_event_id"],
                        manifest["capability_id"],
                        model_subcall_id,
                        sequence,
                        normalized["attempted_stage"],
                        normalized["attempt_index"],
                        _canonical_json(event),
                        event["usage_event_hash"],
                        event["recorded_at"],
                    ),
                )
                conn.execute("COMMIT")
                return event
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise ValueError("Sector usage event collision") from exc
            except Exception:
                conn.execute("ROLLBACK")
                raise

    # Compatibility for the private evaluator while it migrates to the generic
    # usage summary receipt. New runtime callers use ``record_sector_model_usage``.

    def finalize_sector_model_usage(
        self, *, capability_envelope: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Freeze and sign the raw usage path for one standard Sector capability.

        The caller supplies no aggregate, budget decision, or accepted-output
        reference. All totals and path facts are derived from the append-only
        event ledger, which avoids a receipt/accepted-output dependency cycle.
        """
        finalized_at = self.clock().astimezone(timezone.utc)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                manifest, _ = self._verify(
                    capability_envelope,
                    conn=conn,
                    verified_at=finalized_at,
                )
                capability_id = manifest["capability_id"]
                if manifest["agent_id"] not in STANDARD_SECTOR_AGENTS:
                    raise ValueError(
                        "model usage summaries are restricted to standard Sector"
                    )
                existing = conn.execute(
                    "SELECT receipt_json FROM sector_model_usage_summaries "
                    "WHERE capability_id = ?",
                    (capability_id,),
                ).fetchone()
                if existing is not None:
                    receipt = json.loads(existing["receipt_json"])
                    self._verify_sector_model_usage_summary_with_conn(conn, receipt)
                    conn.execute("COMMIT")
                    return receipt

                uses = conn.execute(
                    "SELECT tool_id FROM capability_tool_uses "
                    "WHERE capability_id = ? ORDER BY tool_id",
                    (capability_id,),
                ).fetchall()
                required_initial_tools = sorted(
                    tool_id
                    for tool_id in manifest["allowed_tools"]
                    if tool_id in INITIAL_SNAPSHOT_TOOL_IDS
                )
                if [row["tool_id"] for row in uses] != required_initial_tools:
                    raise ValueError(
                        "Sector model usage finalization requires the exact initial "
                        "snapshot tool set"
                    )
                event_rows = conn.execute(
                    "SELECT event_json FROM sector_model_usage_events "
                    "WHERE capability_id = ? ORDER BY subcall_sequence",
                    (capability_id,),
                ).fetchall()
                events = [json.loads(row["event_json"]) for row in event_rows]
                for sequence, event in enumerate(events, start=1):
                    event_body = {
                        key: item
                        for key, item in event.items()
                        if key != "usage_event_hash"
                    }
                    if (
                        event.get("schema_version") != "sector_model_usage_event_v1"
                        or event.get("usage_event_hash") != _sha256(event_body)
                        or event.get("subcall_sequence") != sequence
                        or event.get("capability_id") != capability_id
                        or event.get("capability_manifest_hash") != _sha256(manifest)
                    ):
                        raise ValueError("Sector model usage event ledger mismatch")

                reports = [event["usage_report"] for event in events]
                stages = [report["attempted_stage"] for report in reports]
                conflict_review_triggered = "CONFLICT_REVIEW" in stages
                completed = bool(reports) and (
                    reports[-1]["attempted_stage"] == "FINAL_SELECTION"
                    and reports[-1]["attempt_status"] == "ACCEPTED"
                )
                last_attempted_stage = (
                    "COMPLETED"
                    if completed
                    else (stages[-1] if stages else "PRE_MODEL")
                )
                final_report = reports[-1] if completed else {}
                direction_id = final_report.get("direction_comparison_audit_id")
                direction_hash = final_report.get("direction_comparison_audit_hash")
                conflict_id = final_report.get("conflict_review_id")
                conflict_hash = final_report.get("conflict_review_hash")
                if completed and (
                    direction_id is None
                    or direction_hash is None
                    or ((conflict_id is not None) != conflict_review_triggered)
                ):
                    raise ValueError(
                        "completed Sector usage path lacks finalized audit aliases"
                    )
                input_tokens = sum(report["input_tokens"] for report in reports)
                output_tokens = sum(report["output_tokens"] for report in reports)
                measured_at = (
                    events[-1]["recorded_at"] if events else manifest["issued_at"]
                )
                ledger_id = f"sector-usage-ledger:{uuid.uuid4().hex}"
                ledger_without_hash = {
                    "schema_version": "server_owned_model_usage_ledger_v1",
                    "usage_ledger_record_id": ledger_id,
                    "capability_id": capability_id,
                    "usage_event_refs": [
                        {
                            "usage_event_id": event["usage_event_id"],
                            "usage_event_hash": event["usage_event_hash"],
                        }
                        for event in events
                    ],
                    "model_subcall_count": len(events),
                    "last_attempted_stage": last_attempted_stage,
                    "conflict_review_triggered": conflict_review_triggered,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "model_path_disposition": (
                        "COMPLETED" if completed else "INCOMPLETE"
                    ),
                    "measured_at": measured_at,
                    "finalized_at": finalized_at.isoformat(),
                }
                ledger_hash = _sha256(ledger_without_hash)
                ledger = {
                    **ledger_without_hash,
                    "usage_ledger_record_hash": ledger_hash,
                }
                receipt_id = f"sector-usage-summary:{uuid.uuid4().hex}"
                unsigned_body = {
                    "schema_version": SECTOR_USAGE_SUMMARY_RECEIPT_VERSION,
                    "usage_summary_receipt_id": receipt_id,
                    "capability_id": capability_id,
                    "capability_manifest_hash": _sha256(manifest),
                    "graph_run_id": manifest["graph_run_id"],
                    "run_slot_id": manifest["run_slot_id"],
                    "run_id": manifest["run_id"],
                    "node_id": manifest["node_id"],
                    "agent_id": manifest["agent_id"],
                    "stage": manifest["stage"],
                    "as_of": manifest["as_of"],
                    "snapshot_bundle_id": manifest["snapshot_bundle_id"],
                    "snapshot_bundle_hash": manifest["snapshot_bundle_hash"],
                    "model_subcall_count": len(events),
                    "last_attempted_stage": last_attempted_stage,
                    "conflict_review_triggered": conflict_review_triggered,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "model_path_disposition": (
                        "COMPLETED" if completed else "INCOMPLETE"
                    ),
                    "direction_comparison_audit_id": direction_id,
                    "direction_comparison_audit_hash": direction_hash,
                    "conflict_review_id": conflict_id,
                    "conflict_review_hash": conflict_hash,
                    **SECTOR_USAGE_INSTRUMENTATION_CONTRACT,
                    "instrumentation_contract_hash": (
                        SECTOR_USAGE_INSTRUMENTATION_CONTRACT_HASH
                    ),
                    "usage_ledger_record_id": ledger_id,
                    "usage_ledger_record_hash": ledger_hash,
                    "measured_at": measured_at,
                    "finalized_at": finalized_at.isoformat(),
                    "receipt_signing_key_id": self.signing_key_id,
                }
                receipt_hash = _sha256(unsigned_body)
                signed_body = {
                    **unsigned_body,
                    "usage_summary_receipt_hash": receipt_hash,
                }
                receipt = {
                    **signed_body,
                    "receipt_signature": self._sign_domain(
                        "sector-model-usage-summary-receipt-v1\0", signed_body
                    ),
                }
                conn.execute(
                    "INSERT INTO sector_model_usage_summaries VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        receipt_id,
                        capability_id,
                        _canonical_json(ledger),
                        ledger_hash,
                        _canonical_json(receipt),
                        receipt_hash,
                        receipt["receipt_signature"],
                        finalized_at.isoformat(),
                    ),
                )
                conn.execute("COMMIT")
                return receipt
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise ValueError("Sector model usage summary collision") from exc
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def verify_sector_model_usage_summary(
        self, receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Dereference and revalidate a signed generic Sector usage summary."""
        with self._connect() as conn:
            return self._verify_sector_model_usage_summary_with_conn(conn, receipt)

    def _verify_sector_model_usage_summary_with_conn(
        self,
        conn: sqlite3.Connection,
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        receipt = dict(value)
        expected_keys = {
            "schema_version",
            "usage_summary_receipt_id",
            "capability_id",
            "capability_manifest_hash",
            "graph_run_id",
            "run_slot_id",
            "run_id",
            "node_id",
            "agent_id",
            "stage",
            "as_of",
            "snapshot_bundle_id",
            "snapshot_bundle_hash",
            "model_subcall_count",
            "last_attempted_stage",
            "conflict_review_triggered",
            "input_tokens",
            "output_tokens",
            "model_path_disposition",
            "direction_comparison_audit_id",
            "direction_comparison_audit_hash",
            "conflict_review_id",
            "conflict_review_hash",
            "instrumentation_contract_id",
            "instrumentation_contract_version",
            "source_contract_version",
            "measurement_rule",
            "instrumentation_contract_hash",
            "usage_ledger_record_id",
            "usage_ledger_record_hash",
            "measured_at",
            "finalized_at",
            "receipt_signing_key_id",
            "usage_summary_receipt_hash",
            "receipt_signature",
        }
        if set(receipt) != expected_keys:
            raise ValueError("Sector model usage summary fields mismatch")
        if (
            receipt.get("schema_version") != SECTOR_USAGE_SUMMARY_RECEIPT_VERSION
            or receipt.get("receipt_signing_key_id") != self.signing_key_id
            or any(
                receipt.get(field) != expected
                for field, expected in SECTOR_USAGE_INSTRUMENTATION_CONTRACT.items()
            )
            or receipt.get("instrumentation_contract_hash")
            != SECTOR_USAGE_INSTRUMENTATION_CONTRACT_HASH
        ):
            raise ValueError("Sector model usage summary contract mismatch")
        receipt_hash = receipt.get("usage_summary_receipt_hash")
        if not _is_sha256(receipt_hash):
            raise ValueError("Sector model usage summary hash is invalid")
        unsigned_body = {
            key: item
            for key, item in receipt.items()
            if key not in {"usage_summary_receipt_hash", "receipt_signature"}
        }
        if receipt_hash != _sha256(unsigned_body):
            raise ValueError("Sector model usage summary hash mismatch")
        signed_body = {**unsigned_body, "usage_summary_receipt_hash": receipt_hash}
        signature = _required_string(receipt, "receipt_signature")
        if not hmac.compare_digest(
            signature,
            self._sign_domain("sector-model-usage-summary-receipt-v1\0", signed_body),
        ):
            raise ValueError("Sector model usage summary signature mismatch")

        for field in (
            "capability_manifest_hash",
            "snapshot_bundle_hash",
            "instrumentation_contract_hash",
            "usage_ledger_record_hash",
        ):
            if not _is_sha256(receipt.get(field)):
                raise ValueError(f"Sector model usage summary {field} is invalid")
        for id_field, hash_field in (
            ("direction_comparison_audit_id", "direction_comparison_audit_hash"),
            ("conflict_review_id", "conflict_review_hash"),
        ):
            if (receipt[id_field] is None) != (receipt[hash_field] is None):
                raise ValueError(f"Sector model usage summary {id_field} is unpaired")
            if receipt[hash_field] is not None and not _is_sha256(receipt[hash_field]):
                raise ValueError(f"Sector model usage summary {hash_field} is invalid")

        receipt_id = _required_string(receipt, "usage_summary_receipt_id")
        row = conn.execute(
            "SELECT * FROM sector_model_usage_summaries "
            "WHERE usage_summary_receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown Sector model usage summary")
        if (
            row["receipt_json"] != _canonical_json(receipt)
            or row["usage_summary_receipt_hash"] != receipt_hash
            or row["receipt_signature"] != signature
        ):
            raise ValueError("Sector model usage summary differs from its ledger")

        finalized_at = _aware_timestamp(
            receipt["finalized_at"], "usage_summary.finalized_at"
        )
        measured_at = _aware_timestamp(
            receipt["measured_at"], "usage_summary.measured_at"
        )
        if measured_at > finalized_at:
            raise ValueError("Sector model usage summary timeline is invalid")

        capability_row = conn.execute(
            "SELECT manifest_json, signing_key_id, signature FROM capabilities "
            "WHERE capability_id = ?",
            (receipt["capability_id"],),
        ).fetchone()
        if capability_row is None:
            raise ValueError("Sector model usage summary capability is unavailable")
        manifest, _ = self._verify(
            {
                "manifest": json.loads(capability_row["manifest_json"]),
                "signing_key_id": capability_row["signing_key_id"],
                "signature": capability_row["signature"],
            },
            conn=conn,
            allow_terminated=True,
            verified_at=finalized_at,
        )
        expected_lineage = {
            "capability_manifest_hash": _sha256(manifest),
            "graph_run_id": manifest["graph_run_id"],
            "run_slot_id": manifest["run_slot_id"],
            "run_id": manifest["run_id"],
            "node_id": manifest["node_id"],
            "agent_id": manifest["agent_id"],
            "stage": manifest["stage"],
            "as_of": manifest["as_of"],
            "snapshot_bundle_id": manifest["snapshot_bundle_id"],
            "snapshot_bundle_hash": manifest["snapshot_bundle_hash"],
        }
        if manifest["agent_id"] not in STANDARD_SECTOR_AGENTS or any(
            receipt.get(field) != expected for field, expected in expected_lineage.items()
        ):
            raise ValueError("Sector model usage summary capability lineage mismatch")

        event_rows = conn.execute(
            "SELECT event_json FROM sector_model_usage_events "
            "WHERE capability_id = ? ORDER BY subcall_sequence",
            (receipt["capability_id"],),
        ).fetchall()
        events = [json.loads(event_row["event_json"]) for event_row in event_rows]
        for sequence, event in enumerate(events, start=1):
            event_body = {
                key: item for key, item in event.items() if key != "usage_event_hash"
            }
            if (
                event.get("schema_version") != "sector_model_usage_event_v1"
                or event.get("usage_event_hash") != _sha256(event_body)
                or event.get("subcall_sequence") != sequence
                or event.get("capability_id") != receipt["capability_id"]
                or event.get("capability_manifest_hash") != _sha256(manifest)
            ):
                raise ValueError("Sector model usage event ledger mismatch")
        reports = [event["usage_report"] for event in events]
        stages = [report["attempted_stage"] for report in reports]
        completed = bool(reports) and (
            reports[-1]["attempted_stage"] == "FINAL_SELECTION"
            and reports[-1]["attempt_status"] == "ACCEPTED"
        )
        conflict_review_triggered = "CONFLICT_REVIEW" in stages
        final_report = reports[-1] if completed else {}
        expected_summary = {
            "model_subcall_count": len(events),
            "last_attempted_stage": (
                "COMPLETED" if completed else (stages[-1] if stages else "PRE_MODEL")
            ),
            "conflict_review_triggered": conflict_review_triggered,
            "input_tokens": sum(report["input_tokens"] for report in reports),
            "output_tokens": sum(report["output_tokens"] for report in reports),
            "model_path_disposition": "COMPLETED" if completed else "INCOMPLETE",
            "direction_comparison_audit_id": final_report.get(
                "direction_comparison_audit_id"
            ),
            "direction_comparison_audit_hash": final_report.get(
                "direction_comparison_audit_hash"
            ),
            "conflict_review_id": final_report.get("conflict_review_id"),
            "conflict_review_hash": final_report.get("conflict_review_hash"),
            "measured_at": events[-1]["recorded_at"] if events else manifest["issued_at"],
        }
        if any(
            receipt.get(field) != expected for field, expected in expected_summary.items()
        ):
            raise ValueError("Sector model usage summary aggregate mismatch")
        if completed and (
            receipt["direction_comparison_audit_id"] is None
            or receipt["direction_comparison_audit_hash"] is None
            or ((receipt["conflict_review_id"] is not None) != conflict_review_triggered)
        ):
            raise ValueError("completed Sector usage summary lacks audit aliases")

        ledger = json.loads(row["usage_ledger_record_json"])
        ledger_hash = ledger.pop("usage_ledger_record_hash", None)
        expected_ledger = {
            "schema_version": "server_owned_model_usage_ledger_v1",
            "usage_ledger_record_id": receipt["usage_ledger_record_id"],
            "capability_id": receipt["capability_id"],
            "usage_event_refs": [
                {
                    "usage_event_id": event["usage_event_id"],
                    "usage_event_hash": event["usage_event_hash"],
                }
                for event in events
            ],
            "model_subcall_count": expected_summary["model_subcall_count"],
            "last_attempted_stage": expected_summary["last_attempted_stage"],
            "conflict_review_triggered": conflict_review_triggered,
            "input_tokens": expected_summary["input_tokens"],
            "output_tokens": expected_summary["output_tokens"],
            "model_path_disposition": expected_summary["model_path_disposition"],
            "measured_at": expected_summary["measured_at"],
            "finalized_at": receipt["finalized_at"],
        }
        if (
            ledger != expected_ledger
            or ledger_hash != _sha256(expected_ledger)
            or ledger_hash != receipt["usage_ledger_record_hash"]
            or row["usage_ledger_record_hash"] != ledger_hash
        ):
            raise ValueError("Sector model usage summary ledger mismatch")
        return receipt

    def list_tools(self, envelope: Mapping[str, Any]) -> list[dict[str, Any]]:
        with self._connect() as conn:
            manifest, bundle_row = self._verify(envelope, conn=conn)
            adaptive_row = conn.execute(
                "SELECT frozen_bundle_id, frozen_bundle_hash, public_projection_json "
                "FROM snapshot_bundle_adaptive_queries WHERE snapshot_bundle_id = ?",
                (manifest["snapshot_bundle_id"],),
            ).fetchone()
        agent_id = manifest["agent_id"]
        stage = manifest["stage"]
        adaptive_projection = (
            json.loads(adaptive_row["public_projection_json"])
            if adaptive_row is not None
            else None
        )
        deferred = (
            isinstance(adaptive_projection, dict)
            and adaptive_projection.get("call_contract")
            == CALL_TIME_ARGUMENT_CONTRACT
        )
        deferred_entries: list[dict[str, Any]] = []
        adaptive_descriptors = json.loads(bundle_row["payloads_json"])
        if deferred:
            projection_body = {
                key: value
                for key, value in adaptive_projection.items()
                if key != "projection_hash"
            }
            entries = adaptive_projection.get("entries")
            if (
                adaptive_projection.get("projection_hash") != _sha256(projection_body)
                or deferred_query_bundle_hash(adaptive_projection)
                != adaptive_row["frozen_bundle_hash"]
                or adaptive_projection.get("bundle_id")
                != adaptive_row["frozen_bundle_id"]
                or adaptive_projection.get("agent_id") != agent_id
                or adaptive_projection.get("stage") != stage
                or adaptive_projection.get("as_of") != manifest["as_of"]
                or adaptive_projection.get("private_payload_count") != 0
                or not isinstance(entries, list)
            ):
                raise ValueError("deferred query projection binding is invalid")
            for entry in entries:
                if (
                    not isinstance(entry, dict)
                    or set(entry)
                    != {
                        "tool_id",
                        "request",
                        "request_hash",
                        "call_mode",
                        "binding_id",
                    }
                    or entry.get("tool_id") not in manifest["allowed_tools"]
                    or entry.get("call_mode") not in {"INITIAL", "FOLLOW_UP"}
                    or not isinstance(entry.get("request"), dict)
                    or _sha256(entry["request"]) != entry.get("request_hash")
                    or not isinstance(entry.get("binding_id"), str)
                ):
                    raise ValueError("deferred query projection entry is invalid")
                deferred_entries.append(entry)
        tools: list[dict[str, Any]] = []
        for tool_id in manifest["allowed_tools"]:
            if tool_id in ADAPTIVE_QUERY_TOOL_IDS:
                args_schema = (
                    l3_l4_argument_schema_for_binding(
                        agent_id=agent_id,
                        stage=l3_l4_overlay_stage_for_active(agent_id, stage),
                        tool_id=tool_id,
                    )
                    if agent_id in {*SUPERINVESTOR_AGENTS, *DECISION_AGENTS}
                    else argument_schema_for_tool(tool_id)
                )
                if adaptive_row is not None:
                    if deferred:
                        descriptor = json.loads(adaptive_descriptors[tool_id])
                        if (
                            descriptor.get("frozen_query_bundle_id")
                            != adaptive_row["frozen_bundle_id"]
                            or descriptor.get("frozen_query_bundle_hash")
                            != adaptive_row["frozen_bundle_hash"]
                            or descriptor.get("call_contract")
                            != CALL_TIME_ARGUMENT_CONTRACT
                        ):
                            raise ValueError("deferred query descriptor binding is invalid")
                        exact_args = [
                            entry["request"]
                            for entry in deferred_entries
                            if entry["tool_id"] == tool_id
                        ]
                    else:
                        if self.adaptive_query_store is None:
                            raise ValueError("adaptive query store is unavailable")
                        exact_args = self.adaptive_query_store.argument_sets(
                            bundle_id=adaptive_row["frozen_bundle_id"],
                            tool_id=tool_id,
                            expected_bundle_hash=adaptive_row["frozen_bundle_hash"],
                        )
                    if exact_args:
                        try:
                            Draft202012Validator.check_schema(args_schema)
                            validator = Draft202012Validator(
                                args_schema, format_checker=FormatChecker()
                            )
                            variants: list[dict[str, Any]] = []
                            base_properties = args_schema.get("properties", {})
                            for args in exact_args:
                                validator.validate(args)
                                variants.append(
                                    {
                                        "type": "object",
                                        "properties": {
                                            name: {
                                                **base_properties[name],
                                                "const": args[name],
                                            }
                                            for name in base_properties
                                            if name in args
                                        },
                                        "required": [
                                            name for name in base_properties if name in args
                                        ],
                                        "additionalProperties": False,
                                    }
                                )
                            args_schema = {"type": "object", "oneOf": variants}
                            Draft202012Validator.check_schema(args_schema)
                        except (SchemaError, ValidationError) as exc:
                            raise ValueError(
                                f"frozen query arguments violate {tool_id} schema"
                            ) from exc
            else:
                args_schema = {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                }
            tools.append(
                {
                "name": tool_id,
                "description": TOOL_DESCRIPTIONS[tool_id],
                    "args_schema": args_schema,
                }
            )
        return tools

    def _append_result_event(
        self,
        conn: sqlite3.Connection,
        *,
        manifest: Mapping[str, Any],
        tool_id: str,
        call_mode: str,
        args: Mapping[str, Any],
        payload: str | None,
        result_authority_type: str | None,
        result_authority_hash: str | None,
        status: Literal["SUCCEEDED", "FAILED"],
        error_code: str | None = None,
    ) -> dict[str, Any] | None:
        allowed_errors = {
            "ARGUMENT_SCHEMA_REJECTED",
            "CAPABILITY_TOOL_ALREADY_USED",
            "FROZEN_QUERY_REJECTED",
            "PAYLOAD_VALIDATION_FAILED",
        }
        if status == "SUCCEEDED":
            if (
                payload is None
                or result_authority_type
                not in {"SNAPSHOT_BUILD", "FROZEN_QUERY"}
                or not _is_sha256(result_authority_hash)
                or error_code is not None
            ):
                raise ValueError("successful tool result event authority is incomplete")
        elif (
            payload is not None
            or result_authority_type is not None
            or result_authority_hash is not None
            or error_code not in allowed_errors
        ):
            raise ValueError("failed tool result event authority is invalid")
        snapshot_row = conn.execute(
            "SELECT * FROM snapshot_bundle_audit_contexts "
            "WHERE snapshot_bundle_id = ?",
            (manifest["snapshot_bundle_id"],),
        ).fetchone()
        capability_row = conn.execute(
            "SELECT * FROM capability_audit_contexts WHERE capability_id = ?",
            (manifest["capability_id"],),
        ).fetchone()
        if snapshot_row is None or capability_row is None:
            return None
        snapshot_context, snapshot_context_hash = (
            self._validated_snapshot_audit_context(
                snapshot_row,
                snapshot_bundle_id=manifest["snapshot_bundle_id"],
                snapshot_bundle_hash=manifest["snapshot_bundle_hash"],
            )
        )
        capability_context, capability_context_hash = (
            self._validated_capability_audit_context(
                capability_row,
                manifest=manifest,
                snapshot_context_hash=snapshot_context_hash,
            )
        )
        if (
            snapshot_context["knot_v2_eligibility"] != "ELIGIBLE"
            or capability_context["knot_v2_eligibility"] != "ELIGIBLE"
        ):
            return None
        tool_contexts = [
            row
            for row in snapshot_context["tool_contexts"]
            if row["tool_id"] == tool_id
        ]
        if len(tool_contexts) != 1:
            raise ValueError("tool result audit binding authority is unavailable")
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM tool_result_events "
            "WHERE capability_id = ?",
            (manifest["capability_id"],),
        ).fetchone()[0]
        result_event_id = f"tool_evt_{uuid.uuid4().hex}"
        canonical_args_hash = _sha256(dict(args))
        payload_hash = _sha256({"text": payload}) if payload is not None else None
        result_authority = (
            {
                "authority_type": result_authority_type,
                "authority_hash": result_authority_hash,
            }
            if status == "SUCCEEDED"
            else None
        )
        context_binding_refs = tool_contexts[0]["binding_refs"]
        binding_refs: list[dict[str, Any]] = []
        for ref in context_binding_refs:
            event_ref = {
                "binding_id": ref["binding_id"],
                "semantic_capability_id": ref["semantic_capability_id"],
                "coverage_row_hash": ref["coverage_row_hash"],
            }
            if status == "SUCCEEDED":
                fingerprint = _sha256(
                    {
                        "schema_version": "binding_tool_result_fingerprint_v1",
                        "result_event_id": result_event_id,
                        "sequence": sequence,
                        "capability_id": manifest["capability_id"],
                        "run_slot_id": manifest["run_slot_id"],
                        "agent_id": manifest["agent_id"],
                        "stage": manifest["stage"],
                        "binding_id": ref["binding_id"],
                        "tool_id": tool_id,
                        "call_mode": call_mode,
                        "canonical_args_hash": canonical_args_hash,
                        "payload_hash": payload_hash,
                        "result_authority": result_authority,
                        "tool_environment_hash": snapshot_context[
                            "tool_environment_hash"
                        ],
                        "capability_bundle_hash": snapshot_context[
                            "capability_bundle_hash"
                        ],
                        "knot_audit_capability_track_v2_hash": snapshot_context[
                            "knot_audit_capability_track_v2_hash"
                        ],
                    }
                )
                binding_refs.append(
                    {**event_ref, "binding_result_fingerprint": fingerprint}
                )
            else:
                binding_refs.append(event_ref)
        binding_refs.sort(key=lambda value: value["binding_id"])
        recorded_at = self.clock().astimezone(timezone.utc).isoformat()
        event = {
            "schema_version": "server_tool_result_event_v1",
            "result_event_id": result_event_id,
            "sequence": sequence,
            "capability_id": manifest["capability_id"],
            "capability_manifest_hash": _sha256(manifest),
            "graph_run_id": manifest["graph_run_id"],
            "run_slot_id": manifest["run_slot_id"],
            "agent_id": manifest["agent_id"],
            "stage": manifest["stage"],
            "snapshot_bundle_id": manifest["snapshot_bundle_id"],
            "snapshot_bundle_hash": manifest["snapshot_bundle_hash"],
            "snapshot_bundle_audit_context_hash": snapshot_context_hash,
            "capability_audit_context_hash": capability_context_hash,
            "tool_environment_hash": snapshot_context["tool_environment_hash"],
            "capability_bundle_hash": snapshot_context["capability_bundle_hash"],
            "knot_coverage_manifest_v2_hash": snapshot_context[
                "knot_coverage_manifest_v2_hash"
            ],
            "knot_audit_capability_track_v2_hash": snapshot_context[
                "knot_audit_capability_track_v2_hash"
            ],
            "execution_behavior_release_hash": snapshot_context[
                "execution_behavior_release_hash"
            ],
            "tool_id": tool_id,
            "call_mode": call_mode,
            "binding_refs": binding_refs,
            "canonical_args_hash": canonical_args_hash,
            "payload_hash": payload_hash,
            "result_authority": result_authority,
            "status": status,
            "error_code": error_code,
            "recorded_at": recorded_at,
        }
        result_event_hash = _sha256(event)
        conn.execute(
            "INSERT INTO tool_result_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result_event_id,
                manifest["capability_id"],
                sequence,
                tool_id,
                call_mode,
                status,
                _canonical_json(event),
                result_event_hash,
                recorded_at,
            ),
        )
        if status == "FAILED":
            return None
        if payload is None:
            raise ValueError("successful result projection payload is missing")
        event_refs_by_id = {ref["binding_id"]: ref for ref in binding_refs}
        for context_ref in context_binding_refs:
            event_ref = event_refs_by_id[context_ref["binding_id"]]
            projection = build_binding_signal_projection_v1(
                event=event,
                result_event_hash=result_event_hash,
                binding_ref=event_ref,
                payload_text=payload,
                coverage_row=context_ref["coverage_row"],
            )
            conn.execute(
                "INSERT INTO binding_signal_projections VALUES (?, ?, ?, ?, ?)",
                (
                    result_event_id,
                    context_ref["binding_id"],
                    _canonical_json(projection),
                    projection["projection_hash"],
                    recorded_at,
                ),
            )
        audit = {
            "schema_version": "tool_call_audit_v1",
            "result_event_id": result_event_id,
            "result_event_hash": result_event_hash,
            "status": "SUCCEEDED",
            "result_authority_type": str(result_authority_type),
            "result_authority_hash": str(result_authority_hash),
            "tool_environment_hash": snapshot_context["tool_environment_hash"],
            "execution_behavior_release_hash": snapshot_context[
                "execution_behavior_release_hash"
            ],
            "capability_bundle_hash": snapshot_context["capability_bundle_hash"],
            "knot_coverage_manifest_v2_hash": snapshot_context[
                "knot_coverage_manifest_v2_hash"
            ],
            "knot_audit_capability_track_v2_hash": snapshot_context[
                "knot_audit_capability_track_v2_hash"
            ],
            "binding_result_refs": [
                {
                    "binding_id": ref["binding_id"],
                    "binding_result_fingerprint": ref[
                        "binding_result_fingerprint"
                    ],
                }
                for ref in binding_refs
            ],
        }
        return audit

    def _record_failed_result_event(
        self,
        *,
        envelope: Mapping[str, Any],
        manifest: Mapping[str, Any],
        tool_id: str,
        call_mode: Literal["SNAPSHOT", "INITIAL", "FOLLOW_UP"],
        args: Mapping[str, Any],
        error_code: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._verify(envelope, conn=conn)
                self._append_result_event(
                    conn,
                    manifest=manifest,
                    tool_id=tool_id,
                    call_mode=call_mode,
                    args=args,
                    payload=None,
                    result_authority_type=None,
                    result_authority_hash=None,
                    status="FAILED",
                    error_code=error_code,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def _best_effort_failed_result_event(
        self,
        *,
        envelope: Mapping[str, Any],
        manifest: Mapping[str, Any],
        tool_id: str,
        call_mode: Literal["INITIAL", "FOLLOW_UP"],
        args: Mapping[str, Any],
        error_code: str,
    ) -> None:
        try:
            self._record_failed_result_event(
                envelope=envelope,
                manifest=manifest,
                tool_id=tool_id,
                call_mode=call_mode,
                args=args,
                error_code=error_code,
            )
        except Exception:
            pass

    def _validated_deferred_call(
        self,
        *,
        envelope: Mapping[str, Any],
        manifest: Mapping[str, Any],
        tool_id: str,
        args: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if not isinstance(args, Mapping):
            raise ValueError("deferred query args must be an object")
        client_args = dict(args)
        with self._connect() as conn:
            verified_manifest, bundle_row = self._verify(envelope, conn=conn)
            if verified_manifest != manifest:
                raise ValueError("deferred query capability identity mismatch")
            adaptive_row = conn.execute(
                "SELECT frozen_bundle_id, frozen_bundle_hash, public_projection_json "
                "FROM snapshot_bundle_adaptive_queries WHERE snapshot_bundle_id = ?",
                (manifest["snapshot_bundle_id"],),
            ).fetchone()
            if adaptive_row is None:
                return None
            payloads = json.loads(bundle_row["payloads_json"])
            descriptor = json.loads(payloads[tool_id])
            projection = json.loads(adaptive_row["public_projection_json"])
            if not isinstance(descriptor, dict) or not isinstance(projection, dict):
                raise ValueError("adaptive query authority is malformed")
            projection_deferred = (
                projection.get("call_contract") == CALL_TIME_ARGUMENT_CONTRACT
            )
            descriptor_deferred = (
                descriptor.get("call_contract") == CALL_TIME_ARGUMENT_CONTRACT
            )
            if not projection_deferred and not descriptor_deferred:
                return None
            if not projection_deferred or not descriptor_deferred:
                raise ValueError("deferred query call contract binding mismatch")

            required_projection_fields = {
                "schema_version",
                "call_contract",
                "agent_id",
                "stage",
                "as_of",
                "authorized_scope_hash",
                "preservation_overlay_hash",
                "query_bundle_contract_version",
                "private_payload_count",
                "initial_payload_count",
                "adaptive_max_rounds",
                "entries",
                "bundle_id",
                "bundle_hash",
                "projection_hash",
            }
            expected_projection_fields = set(required_projection_fields)
            if "preservation_stage" in projection:
                expected_projection_fields.add("preservation_stage")
            projection_body = {
                key: value
                for key, value in projection.items()
                if key != "projection_hash"
            }
            entries = projection.get("entries")
            max_rounds = projection.get("adaptive_max_rounds")
            initial_payload_count = projection.get("initial_payload_count")
            if (
                set(projection) != expected_projection_fields
                or projection.get("schema_version") != PUBLIC_PROJECTION_VERSION
                or projection.get("call_contract") != CALL_TIME_ARGUMENT_CONTRACT
                or projection.get("agent_id") != manifest["agent_id"]
                or projection.get("stage") != manifest["stage"]
                or projection.get("as_of") != manifest["as_of"]
                or (
                    "preservation_stage" in projection
                    and (
                        not isinstance(projection["preservation_stage"], str)
                        or not projection["preservation_stage"]
                    )
                )
                or not _is_sha256(projection.get("authorized_scope_hash"))
                or not _is_sha256(projection.get("preservation_overlay_hash"))
                or not isinstance(
                    projection.get("query_bundle_contract_version"), str
                )
                or not projection["query_bundle_contract_version"]
                or projection.get("private_payload_count") != 0
                or isinstance(initial_payload_count, bool)
                or not isinstance(initial_payload_count, int)
                or initial_payload_count < 0
                or isinstance(max_rounds, bool)
                or max_rounds not in {0, 3}
                or not isinstance(entries, list)
                or not _is_sha256(projection.get("bundle_hash"))
                or projection.get("projection_hash") != _sha256(projection_body)
                or deferred_query_bundle_hash(projection)
                != adaptive_row["frozen_bundle_hash"]
                or projection.get("bundle_hash")
                != adaptive_row["frozen_bundle_hash"]
                or projection.get("bundle_id") != adaptive_row["frozen_bundle_id"]
                or projection.get("bundle_id")
                != "frozen_bundle_" + projection["bundle_hash"][7:]
            ):
                raise ValueError("deferred query projection binding is invalid")

            validated_entries: list[dict[str, Any]] = []
            for entry in entries:
                if (
                    not isinstance(entry, dict)
                    or set(entry)
                    != {
                        "tool_id",
                        "request",
                        "request_hash",
                        "call_mode",
                        "binding_id",
                    }
                    or entry.get("tool_id") not in manifest["allowed_tools"]
                    or entry.get("tool_id") not in ADAPTIVE_QUERY_TOOL_IDS
                    or entry.get("call_mode") not in {"INITIAL", "FOLLOW_UP"}
                    or not isinstance(entry.get("request"), dict)
                    or not entry["request"]
                    or entry.get("request_hash") != _sha256(entry["request"])
                    or not isinstance(entry.get("binding_id"), str)
                    or not entry["binding_id"]
                ):
                    raise ValueError("deferred query projection entry is invalid")
                validated_entries.append(entry)
            if sum(
                entry["call_mode"] == "INITIAL" for entry in validated_entries
            ) != initial_payload_count:
                raise ValueError("deferred query initial count is invalid")

            tool_entries = [
                entry for entry in validated_entries if entry["tool_id"] == tool_id
            ]
            initial_count = sum(
                entry["call_mode"] == "INITIAL" for entry in tool_entries
            )
            follow_up_count = sum(
                entry["call_mode"] == "FOLLOW_UP" for entry in tool_entries
            )
            expected_descriptor = {
                "schema_version": "adaptive_tool_bundle_descriptor_v1",
                "tool_id": tool_id,
                "frozen_query_bundle_id": adaptive_row["frozen_bundle_id"],
                "frozen_query_bundle_hash": adaptive_row["frozen_bundle_hash"],
                "prepared_request_count": len(tool_entries),
                "prepared_initial_count": initial_count,
                "prepared_follow_up_count": follow_up_count,
                "call_contract": CALL_TIME_ARGUMENT_CONTRACT,
                "adaptive_max_rounds": max_rounds,
            }
            if descriptor != expected_descriptor:
                raise ValueError("deferred query descriptor binding is invalid")

            snapshot_row = conn.execute(
                "SELECT * FROM snapshot_bundle_audit_contexts "
                "WHERE snapshot_bundle_id = ?",
                (manifest["snapshot_bundle_id"],),
            ).fetchone()
            capability_row = conn.execute(
                "SELECT * FROM capability_audit_contexts WHERE capability_id = ?",
                (manifest["capability_id"],),
            ).fetchone()
            if snapshot_row is None or capability_row is None:
                raise ValueError("deferred query KNOT audit authority is unavailable")
            snapshot_context, snapshot_context_hash = (
                self._validated_snapshot_audit_context(
                    snapshot_row,
                    snapshot_bundle_id=manifest["snapshot_bundle_id"],
                    snapshot_bundle_hash=manifest["snapshot_bundle_hash"],
                )
            )
            capability_context, _ = self._validated_capability_audit_context(
                capability_row,
                manifest=manifest,
                snapshot_context_hash=snapshot_context_hash,
            )
            normal_eligible = (
                snapshot_context.get("knot_v2_eligibility") == "ELIGIBLE"
                and capability_context.get("knot_v2_eligibility") == "ELIGIBLE"
            )
            synthetic_non_production_bypass = (
                snapshot_context.get("knot_v2_eligibility") == "INELIGIBLE"
                and snapshot_context.get("ineligibility_reasons")
                == ["SYNTHETIC_NON_PRODUCTION_BYPASS"]
                and capability_context.get("knot_v2_eligibility") == "INELIGIBLE"
            )
            if (
                snapshot_context.get("agent_id") != manifest["agent_id"]
                or snapshot_context.get("stage") != manifest["stage"]
                or snapshot_context.get("as_of") != manifest["as_of"]
                or capability_context.get("agent_id") != manifest["agent_id"]
                or capability_context.get("stage") != manifest["stage"]
                or not (normal_eligible or synthetic_non_production_bypass)
            ):
                raise ValueError("deferred query KNOT audit authority is ineligible")
            deferred_context = snapshot_context.get("deferred_query")
            expected_deferred_tool_ids = sorted(
                candidate
                for candidate in manifest["allowed_tools"]
                if candidate in ADAPTIVE_QUERY_TOOL_IDS
            )
            if (
                not isinstance(deferred_context, Mapping)
                or set(deferred_context)
                != {"call_contract", "frozen_bundle_hash", "tool_ids"}
                or deferred_context.get("call_contract")
                != CALL_TIME_ARGUMENT_CONTRACT
                or deferred_context.get("frozen_bundle_hash")
                != adaptive_row["frozen_bundle_hash"]
                or deferred_context.get("tool_ids") != expected_deferred_tool_ids
            ):
                raise ValueError("deferred query signed snapshot closure mismatch")
            tool_contexts = [
                context
                for context in snapshot_context.get("tool_contexts", [])
                if context.get("tool_id") == tool_id
            ]
            if len(tool_contexts) != 1:
                raise ValueError("deferred query KNOT tool authority is unavailable")
            binding_refs = tool_contexts[0].get("binding_refs")
            if (
                not isinstance(binding_refs, list)
                or not binding_refs
                or any(
                    not isinstance(ref, Mapping)
                    or not isinstance(ref.get("binding_id"), str)
                    or not ref["binding_id"]
                    for ref in binding_refs
                )
            ):
                raise ValueError("deferred query KNOT binding authority is invalid")
            active_binding_ids = {ref["binding_id"] for ref in binding_refs}
            if len(active_binding_ids) != len(binding_refs) or any(
                entry["binding_id"] not in active_binding_ids
                for entry in tool_entries
            ):
                raise ValueError("deferred query projection binding is not active")

            if client_args:
                request_hash = _sha256(client_args)
                matches = [
                    entry
                    for entry in tool_entries
                    if entry["call_mode"] == "FOLLOW_UP"
                    and entry["request_hash"] == request_hash
                    and entry["request"] == client_args
                ]
                if len(matches) != 1 or max_rounds != 3:
                    raise ValueError("frozen follow-up request is not uniquely authorized")
                successful_follow_ups = conn.execute(
                    "SELECT COUNT(*) FROM tool_result_events "
                    "WHERE capability_id = ? AND status = 'SUCCEEDED' "
                    "AND call_mode = 'FOLLOW_UP'",
                    (manifest["capability_id"],),
                ).fetchone()[0]
                if successful_follow_ups >= 3:
                    raise ValueError("frozen follow-up round limit is exhausted")
                call_mode: Literal["INITIAL", "FOLLOW_UP"] = "FOLLOW_UP"
            else:
                matches = [
                    entry
                    for entry in tool_entries
                    if entry["call_mode"] == "INITIAL"
                ]
                if len(matches) != 1 or not matches[0]["request"]:
                    raise ValueError("frozen initial request is not uniquely authorized")
                call_mode = "INITIAL"
            match = matches[0]
            return {
                "bundle_hash": adaptive_row["frozen_bundle_hash"],
                "call_mode": call_mode,
                "request_hash": match["request_hash"],
                "resolved_args": dict(match["request"]),
                "synthetic_non_production_bypass": (
                    synthetic_non_production_bypass
                ),
            }

    def _call_deferred_tool_result(
        self,
        *,
        envelope: Mapping[str, Any],
        manifest: Mapping[str, Any],
        tool_id: str,
        call: Mapping[str, Any],
    ) -> dict[str, Any]:
        call_mode = cast(Literal["INITIAL", "FOLLOW_UP"], call["call_mode"])
        resolved_args = dict(call["resolved_args"])
        if self.adaptive_query_materializer is None:
            self._best_effort_failed_result_event(
                envelope=envelope,
                manifest=manifest,
                tool_id=tool_id,
                call_mode=call_mode,
                args=resolved_args,
                error_code="FROZEN_QUERY_REJECTED",
            )
            raise ValueError("deferred query materializer is unavailable")
        try:
            materialized = self.adaptive_query_materializer(
                tool_id, dict(resolved_args)
            )
        except Exception:
            self._best_effort_failed_result_event(
                envelope=envelope,
                manifest=manifest,
                tool_id=tool_id,
                call_mode=call_mode,
                args=resolved_args,
                error_code="PAYLOAD_VALIDATION_FAILED",
            )
            raise
        try:
            if not isinstance(materialized, Mapping) or not {
                "payload"
            } <= set(materialized) <= {
                "payload",
                "source_receipt_hashes",
                "derivation",
            }:
                raise ValueError("deferred query materializer returned an invalid object")
            payload = materialized.get("payload")
            if not isinstance(payload, str) or not payload:
                raise ValueError("deferred query materializer returned an empty payload")
            receipt_hashes = materialized.get("source_receipt_hashes", [])
            if (
                not isinstance(receipt_hashes, list)
                or not all(_is_sha256(value) for value in receipt_hashes)
                or receipt_hashes != sorted(set(receipt_hashes))
            ):
                raise ValueError("deferred query source receipt hashes are invalid")
            derivation = materialized.get("derivation")
            derivation_hash: str | None = None
            if derivation is not None:
                if (
                    not isinstance(derivation, Mapping)
                    or set(derivation)
                    != {
                        "derivation_contract_version",
                        "model_hash",
                        "prompt_hash",
                        "source_payload_hash",
                    }
                    or derivation.get("derivation_contract_version")
                    != "frozen_research_digest_lineage_v1"
                    or not all(
                        _is_sha256(derivation.get(field))
                        for field in (
                            "model_hash",
                            "prompt_hash",
                            "source_payload_hash",
                        )
                    )
                ):
                    raise ValueError("deferred query derivation is invalid")
                derivation_hash = _sha256(dict(derivation))
            payload_hash = _sha256({"text": payload})
            receipt_hashes = list(receipt_hashes)
            authority = {
                "schema_version": "frozen_query_result_authority_v1",
                "authority_type": "FROZEN_QUERY",
                "frozen_bundle_hash": call["bundle_hash"],
                "tool_id": tool_id,
                "resolved_args": resolved_args,
                "request_hash": call["request_hash"],
                "payload_hash": payload_hash,
                "source_receipt_hashes": receipt_hashes,
                "source_receipt_set_hash": _sha256(receipt_hashes),
                "derivation_hash": derivation_hash,
            }
            authority_hash = _sha256(authority)
        except ValueError:
            self._best_effort_failed_result_event(
                envelope=envelope,
                manifest=manifest,
                tool_id=tool_id,
                call_mode=call_mode,
                args=resolved_args,
                error_code="PAYLOAD_VALIDATION_FAILED",
            )
            raise

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._verify(envelope, conn=conn)
                audit = self._append_result_event(
                    conn,
                    manifest=manifest,
                    tool_id=tool_id,
                    call_mode=call_mode,
                    args=resolved_args,
                    payload=payload,
                    result_authority_type="FROZEN_QUERY",
                    result_authority_hash=authority_hash,
                    status="SUCCEEDED",
                )
                if audit is None and not call["synthetic_non_production_bypass"]:
                    raise ValueError("deferred query result audit authority is unavailable")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        result: dict[str, Any] = {"text": payload}
        if audit is not None:
            result["audit"] = audit
        return result

    def _record_security_rejection(
        self,
        *,
        manifest: Mapping[str, Any],
        attempted_tool_id: str,
        args: Mapping[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                capability = conn.execute(
                    "SELECT manifest_json FROM capabilities WHERE capability_id = ?",
                    (manifest["capability_id"],),
                ).fetchone()
                terminated = conn.execute(
                    "SELECT 1 FROM capability_events "
                    "WHERE capability_id = ? AND event_type = 'TERMINATED'",
                    (manifest["capability_id"],),
                ).fetchone()
                if (
                    capability is None
                    or capability["manifest_json"] != _canonical_json(manifest)
                    or terminated is not None
                ):
                    raise ValueError("capability security audit authority mismatch")
                event_id = f"security_rejection_{uuid.uuid4().hex}"
                recorded_at = self.clock().astimezone(timezone.utc).isoformat()
                event = {
                    "schema_version": "tool_security_rejection_event_v1",
                    "security_rejection_id": event_id,
                    "capability_id": manifest["capability_id"],
                    "capability_manifest_hash": _sha256(manifest),
                    "run_slot_id": manifest["run_slot_id"],
                    "agent_id": manifest["agent_id"],
                    "stage": manifest["stage"],
                    "attempted_tool_id_hash": _sha256(
                        {"tool_id": attempted_tool_id}
                    ),
                    "canonical_args_hash": _sha256(dict(args)),
                    "reason_code": "TOOL_NOT_ALLOWED",
                    "recorded_at": recorded_at,
                }
                event_hash = _sha256(event)
                conn.execute(
                    "INSERT INTO tool_security_rejections VALUES (?, ?, ?, ?, ?)",
                    (
                        event_id,
                        manifest["capability_id"],
                        _canonical_json(event),
                        event_hash,
                        recorded_at,
                    ),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def call_tool_result(
        self,
        envelope: Mapping[str, Any],
        tool_id: str,
        args: Mapping[str, Any],
    ) -> dict[str, Any]:
        manifest, row = self._verify(envelope)
        if tool_id not in manifest["allowed_tools"]:
            self._record_security_rejection(
                manifest=manifest,
                attempted_tool_id=tool_id,
                args=args,
            )
            raise ValueError(f"tool {tool_id!r} is not allowed by this capability")
        if tool_id in ADAPTIVE_QUERY_TOOL_IDS:
            if self.adaptive_query_store is None:
                raise ValueError("adaptive query store is unavailable")
            try:
                deferred_call = self._validated_deferred_call(
                    envelope=envelope,
                    manifest=manifest,
                    tool_id=tool_id,
                    args=args,
                )
            except ValueError:
                self._best_effort_failed_result_event(
                    envelope=envelope,
                    manifest=manifest,
                    tool_id=tool_id,
                    call_mode="FOLLOW_UP" if args else "INITIAL",
                    args=args,
                    error_code="FROZEN_QUERY_REJECTED",
                )
                raise
            if deferred_call is not None:
                return self._call_deferred_tool_result(
                    envelope=envelope,
                    manifest=manifest,
                    tool_id=tool_id,
                    call=deferred_call,
                )
            failure_code = "FROZEN_QUERY_REJECTED"
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    self._verify(envelope, conn=conn)
                    if args:
                        session = conn.execute(
                            "SELECT session_id FROM capability_adaptive_sessions "
                            "WHERE capability_id = ?",
                            (manifest["capability_id"],),
                        ).fetchone()
                        if session is None:
                            raise ValueError(
                                "adaptive model calls are unavailable for this capability"
                            )
                        adaptive_result = self.adaptive_query_store.call_next_result(
                            session_id=session["session_id"],
                            tool_id=tool_id,
                            args=args,
                        )
                    else:
                        adaptive = conn.execute(
                            "SELECT frozen_bundle_id "
                            "FROM snapshot_bundle_adaptive_queries "
                            "WHERE snapshot_bundle_id = ?",
                            (manifest["snapshot_bundle_id"],),
                        ).fetchone()
                        if adaptive is None:
                            raise ValueError(
                                "adaptive query bundle is unavailable for this capability"
                            )
                        initial = self.adaptive_query_store.read_initial_results(
                            bundle_id=adaptive["frozen_bundle_id"],
                            agent_id=manifest["agent_id"],
                            stage=manifest["stage"],
                        )
                        matches = [
                            entry for entry in initial if entry["tool_id"] == tool_id
                        ]
                        if len(matches) != 1:
                            raise ValueError(
                                "frozen initial payload is unavailable for this tool"
                            )
                        adaptive_result = matches[0]
                    failure_code = "PAYLOAD_VALIDATION_FAILED"
                    payload = str(adaptive_result["payload"])
                    result_authority = adaptive_result.get("result_authority")
                    if (
                        not isinstance(result_authority, Mapping)
                        or result_authority.get("authority_type") != "FROZEN_QUERY"
                        or not _is_sha256(result_authority.get("authority_hash"))
                    ):
                        raise ValueError("frozen query result authority is invalid")
                    audit = self._append_result_event(
                        conn,
                        manifest=manifest,
                        tool_id=tool_id,
                        call_mode=str(adaptive_result["call_mode"]),
                        args=args,
                        payload=payload,
                        result_authority_type="FROZEN_QUERY",
                        result_authority_hash=str(
                            result_authority["authority_hash"]
                        ),
                        status="SUCCEEDED",
                    )
                    conn.execute("COMMIT")
                except ValueError:
                    conn.execute("ROLLBACK")
                    self._record_failed_result_event(
                        envelope=envelope,
                        manifest=manifest,
                        tool_id=tool_id,
                        call_mode="FOLLOW_UP" if args else "INITIAL",
                        args=args,
                        error_code=failure_code,
                    )
                    raise
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            result: dict[str, Any] = {"text": payload}
            if audit is not None:
                result["audit"] = audit
            return result
        if args:
            self._record_failed_result_event(
                envelope=envelope,
                manifest=manifest,
                tool_id=tool_id,
                call_mode="SNAPSHOT",
                args=args,
                error_code="ARGUMENT_SCHEMA_REJECTED",
            )
            raise ValueError("role-scoped snapshot tools accept no arguments")
        payloads = json.loads(row["payloads_json"])
        payload = payloads.get(tool_id)
        if not isinstance(payload, str) or not payload:
            raise ValueError("bundle payload is missing")
        bundle = json.loads(row["bundle_json"])
        if bundle["tool_payload_hashes"].get(tool_id) != _sha256_text(payload):
            raise ValueError("bundle payload hash mismatch")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                terminated = conn.execute(
                    """
                    SELECT 1 FROM capability_events
                    WHERE capability_id = ? AND event_type = 'TERMINATED'
                    """,
                    (manifest["capability_id"],),
                ).fetchone()
                if terminated is not None:
                    raise ValueError("capability is terminated")
                conn.execute(
                    "INSERT INTO capability_tool_uses VALUES (?, ?, ?)",
                    (
                        manifest["capability_id"],
                        tool_id,
                        self.clock().astimezone(timezone.utc).isoformat(),
                    ),
                )
                snapshot_context = conn.execute(
                    "SELECT context_json FROM snapshot_bundle_audit_contexts "
                    "WHERE snapshot_bundle_id = ?",
                    (manifest["snapshot_bundle_id"],),
                ).fetchone()
                audit: dict[str, Any] | None = None
                if snapshot_context is not None:
                    context = json.loads(snapshot_context["context_json"])
                    build_receipt_hash = context.get(
                        "build_receipt_hashes", {}
                    ).get(tool_id)
                    if context.get("knot_v2_eligibility") == "ELIGIBLE":
                        if not _is_sha256(build_receipt_hash):
                            raise ValueError(
                                "snapshot build receipt authority is unavailable"
                            )
                        audit = self._append_result_event(
                            conn,
                            manifest=manifest,
                            tool_id=tool_id,
                            call_mode="SNAPSHOT",
                            args=args,
                            payload=payload,
                            result_authority_type="SNAPSHOT_BUILD",
                            result_authority_hash=build_receipt_hash,
                            status="SUCCEEDED",
                        )
                conn.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                self._record_failed_result_event(
                    envelope=envelope,
                    manifest=manifest,
                    tool_id=tool_id,
                    call_mode="SNAPSHOT",
                    args=args,
                    error_code="CAPABILITY_TOOL_ALREADY_USED",
                )
                raise ValueError("capability tool has already been used") from exc
            except Exception:
                conn.execute("ROLLBACK")
                raise
        result: dict[str, Any] = {"text": payload}
        if audit is not None:
            result["audit"] = audit
        return result

    def call_tool(
        self,
        envelope: Mapping[str, Any],
        tool_id: str,
        args: Mapping[str, Any],
    ) -> str:
        """Compatibility wrapper returning only the immutable tool text."""
        return str(self.call_tool_result(envelope, tool_id, args)["text"])

    def finalize_accepted_knot_history_v2(
        self,
        accepted_output: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Materialize one accepted output against capture-time server authority."""
        accepted_output_id = accepted_output.get("accepted_output_id")
        accepted_output_hash = accepted_output.get("accepted_output_hash")
        if not isinstance(accepted_output_id, str) or not accepted_output_id:
            raise ValueError("accepted output id is invalid")
        if not _is_sha256(accepted_output_hash):
            raise ValueError("accepted output hash is invalid")
        accepted_body = {
            key: value
            for key, value in accepted_output.items()
            if key != "accepted_output_hash"
        }
        if accepted_output_hash != _sha256(accepted_body):
            raise ValueError("accepted output hash mismatch")
        created_at = self.clock().astimezone(timezone.utc).isoformat()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT accepted_output_hash, materialization_json "
                    "FROM accepted_knot_history_materializations_v2 "
                    "WHERE accepted_output_id = ?",
                    (accepted_output_id,),
                ).fetchone()
                if existing is not None:
                    if existing["accepted_output_hash"] != accepted_output_hash:
                        raise ValueError("accepted KNOT history identity collision")
                    conn.execute("COMMIT")
                    return cast(dict[str, Any], json.loads(existing["materialization_json"]))

                capture = accepted_output.get("knot_capture_v2")
                if capture is None:
                    materialization = self._insert_knot_history_exclusion(
                        conn,
                        accepted_output_id=accepted_output_id,
                        accepted_output_hash=str(accepted_output_hash),
                        capture_hash=None,
                        reasons=["LEGACY_KNOT_CAPTURE_MISSING"],
                        created_at=created_at,
                    )
                    conn.execute("COMMIT")
                    return materialization
                _validate_knot_capture_v2(accepted_output)
                if not isinstance(capture, Mapping):
                    raise ValueError("accepted KNOT capture is invalid")
                if capture["eligibility"] != "ELIGIBLE":
                    materialization = self._insert_knot_history_exclusion(
                        conn,
                        accepted_output_id=accepted_output_id,
                        accepted_output_hash=str(accepted_output_hash),
                        capture_hash=str(capture["capture_hash"]),
                        reasons=[str(value) for value in capture["ineligibility_reasons"]],
                        created_at=created_at,
                    )
                    conn.execute("COMMIT")
                    return materialization

                captured_events = self._load_captured_knot_events(
                    conn,
                    accepted_output=accepted_output,
                    capture=capture,
                )
                capability_ids = {event["capability_id"] for event in captured_events.values()}
                if len(capability_ids) != 1:
                    raise ValueError("accepted KNOT capture crosses capabilities")
                capability_id = next(iter(capability_ids))
                authority = self._load_knot_history_authority(
                    conn,
                    capability_id=capability_id,
                )
                fixed_fields = (
                    "tool_environment_hash",
                    "execution_behavior_release_hash",
                    "capability_bundle_hash",
                    "knot_coverage_manifest_v2_hash",
                    "knot_audit_capability_track_v2_hash",
                )
                if any(
                    capture[field] != authority["snapshot_context"][field]
                    for field in fixed_fields
                ):
                    raise ValueError("accepted KNOT fixed point authority mismatch")

                events_by_binding = self._load_knot_events_by_binding(
                    conn,
                    capability_id=capability_id,
                )
                coverage_by_binding = authority["coverage_by_binding"]
                accepted_specs = {
                    str(spec["claim_id"]): spec for spec in capture["claim_specs"]
                }
                comparison_input = {
                    "claims": [
                        {
                            "claim_id": spec["claim_id"],
                            "structured_conclusion": spec["structured_conclusion"],
                        }
                        for spec in capture["claim_specs"]
                    ]
                }
                comparison_input_hash = _sha256(comparison_input)
                evaluations: list[dict[str, Any]] = []
                evaluation_refs_by_binding: dict[str, list[dict[str, str]]] = {
                    binding_id: [] for binding_id in coverage_by_binding
                }
                captured_refs = {
                    str(ref["result_event_id"]): ref
                    for ref in capture["result_event_refs"]
                }
                for result_event_id, capture_ref in captured_refs.items():
                    event = captured_events[result_event_id]
                    for binding_ref in capture_ref["binding_result_refs"]:
                        binding_id = str(binding_ref["binding_id"])
                        coverage_row = coverage_by_binding.get(binding_id)
                        if coverage_row is None:
                            raise ValueError("accepted KNOT binding is outside capability authority")
                        projection = self._load_knot_projection(
                            conn,
                            result_event_id=result_event_id,
                            binding_id=binding_id,
                            event=event,
                            binding_ref=binding_ref,
                        )
                        claim_specs = build_claim_comparison_specs_v1(
                            accepted_output=comparison_input,
                            accepted_output_hash=comparison_input_hash,
                            coverage_row=coverage_row,
                        )
                        for claim_spec in claim_specs:
                            accepted_spec = accepted_specs.get(str(claim_spec["claim_id"]))
                            if accepted_spec is None or not set(
                                accepted_spec["evidence_ids"]
                            ).intersection(capture_ref["evidence_ids"]):
                                continue
                            evaluation = compare_binding_projection_v1(
                                projection=projection,
                                claim_spec=claim_spec,
                            )
                            validate_trusted_counterevidence_evaluation_v2(
                                evaluation,
                                projection=projection,
                                claim_spec=claim_spec,
                            )
                            evaluations.append(
                                {
                                    "result_event_id": result_event_id,
                                    "binding_id": binding_id,
                                    "claim_id": str(claim_spec["claim_id"]),
                                    "claim_spec": claim_spec,
                                    "evaluation": evaluation,
                                }
                            )
                            evaluation_refs_by_binding[binding_id].append(
                                {
                                    "claim_id": str(claim_spec["claim_id"]),
                                    "evaluation_hash": str(evaluation["evaluation_hash"]),
                                }
                            )

                observations: list[dict[str, Any]] = []
                for binding_id in sorted(coverage_by_binding):
                    event_refs = events_by_binding.get(binding_id, [])
                    succeeded = any(ref["status"] == "SUCCEEDED" for ref in event_refs)
                    binding_evaluations = [
                        row["evaluation"]
                        for row in evaluations
                        if row["binding_id"] == binding_id
                    ]
                    evaluated = [
                        row
                        for row in binding_evaluations
                        if row["evaluation_status"] == "EVALUATED"
                    ]
                    counterevidence = [
                        row for row in evaluated if row["counterevidence_available"]
                    ]
                    observation_body = {
                        "schema_version": "knot_binding_observation_v2",
                        "accepted_output_id": accepted_output_id,
                        "accepted_output_hash": accepted_output_hash,
                        "capture_hash": capture["capture_hash"],
                        "graph_run_id": accepted_output["graph_run_id"],
                        "run_slot_id": accepted_output["run_slot_id"],
                        "agent_id": accepted_output["agent_id"],
                        "stage": authority["manifest"]["stage"],
                        "capability_id": capability_id,
                        "binding_id": binding_id,
                        **{field: capture[field] for field in fixed_fields},
                        "eligible": True,
                        "ready": True,
                        "called": bool(event_refs),
                        "succeeded": succeeded,
                        "used_in_accepted_evidence": bool(evaluated),
                        "counterevidence_available": bool(counterevidence),
                        "counterevidence_handled": bool(counterevidence)
                        and all(row["counterevidence_handled"] for row in counterevidence),
                        "result_event_refs": event_refs,
                        "evaluation_refs": sorted(
                            evaluation_refs_by_binding[binding_id],
                            key=lambda row: (row["claim_id"], row["evaluation_hash"]),
                        ),
                    }
                    observations.append(
                        {
                            **observation_body,
                            "observation_hash": _sha256(observation_body),
                        }
                    )

                materialization_body = {
                    "schema_version": "accepted_knot_history_materialization_v2",
                    "accepted_output_id": accepted_output_id,
                    "accepted_output_hash": accepted_output_hash,
                    "capture_hash": capture["capture_hash"],
                    "capability_id": capability_id,
                    "status": "MATERIALIZED",
                    "exclusion_reasons": [],
                    **{field: capture[field] for field in fixed_fields},
                    "observation_count": len(observations),
                    "evaluation_count": len(evaluations),
                    "observation_set_hash": _sha256(
                        [row["observation_hash"] for row in observations]
                    ),
                    "evaluation_set_hash": _sha256(
                        [row["evaluation"]["evaluation_hash"] for row in evaluations]
                    ),
                }
                materialization = {
                    **materialization_body,
                    "materialization_hash": _sha256(materialization_body),
                }
                conn.execute(
                    "INSERT INTO accepted_knot_history_materializations_v2 "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        accepted_output_id,
                        accepted_output_hash,
                        capability_id,
                        capture["capture_hash"],
                        "MATERIALIZED",
                        _canonical_json(materialization),
                        materialization["materialization_hash"],
                        created_at,
                    ),
                )
                for row in evaluations:
                    evaluation = row["evaluation"]
                    claim_spec = row["claim_spec"]
                    conn.execute(
                        "INSERT INTO trusted_counterevidence_evaluations_v2 "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            accepted_output_id,
                            row["result_event_id"],
                            row["binding_id"],
                            row["claim_id"],
                            _canonical_json(claim_spec),
                            claim_spec["spec_hash"],
                            _canonical_json(evaluation),
                            evaluation["evaluation_hash"],
                            created_at,
                        ),
                    )
                for observation in observations:
                    conn.execute(
                        "INSERT INTO knot_binding_observations_v2 VALUES (?, ?, ?, ?, ?)",
                        (
                            accepted_output_id,
                            observation["binding_id"],
                            _canonical_json(observation),
                            observation["observation_hash"],
                            created_at,
                        ),
                    )
                conn.execute("COMMIT")
                return materialization
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def _insert_knot_history_exclusion(
        self,
        conn: sqlite3.Connection,
        *,
        accepted_output_id: str,
        accepted_output_hash: str,
        capture_hash: str | None,
        reasons: Sequence[str],
        created_at: str,
    ) -> dict[str, Any]:
        body = {
            "schema_version": "accepted_knot_history_materialization_v2",
            "accepted_output_id": accepted_output_id,
            "accepted_output_hash": accepted_output_hash,
            "capture_hash": capture_hash,
            "capability_id": None,
            "status": "EXCLUDED",
            "exclusion_reasons": sorted(set(reasons)),
            "tool_environment_hash": None,
            "execution_behavior_release_hash": None,
            "capability_bundle_hash": None,
            "knot_coverage_manifest_v2_hash": None,
            "knot_audit_capability_track_v2_hash": None,
            "observation_count": 0,
            "evaluation_count": 0,
            "observation_set_hash": _sha256([]),
            "evaluation_set_hash": _sha256([]),
        }
        materialization = {**body, "materialization_hash": _sha256(body)}
        conn.execute(
            "INSERT INTO accepted_knot_history_materializations_v2 "
            "VALUES (?, ?, NULL, ?, 'EXCLUDED', ?, ?, ?)",
            (
                accepted_output_id,
                accepted_output_hash,
                capture_hash,
                _canonical_json(materialization),
                materialization["materialization_hash"],
                created_at,
            ),
        )
        return materialization

    def _load_captured_knot_events(
        self,
        conn: sqlite3.Connection,
        *,
        accepted_output: Mapping[str, Any],
        capture: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]]:
        events: dict[str, dict[str, Any]] = {}
        for capture_ref in capture["result_event_refs"]:
            result_event_id = str(capture_ref["result_event_id"])
            row = conn.execute(
                "SELECT * FROM tool_result_events WHERE result_event_id = ?",
                (result_event_id,),
            ).fetchone()
            if row is None:
                raise ValueError("accepted KNOT result event is unavailable")
            event = cast(dict[str, Any], json.loads(row["event_json"]))
            if (
                row["result_event_hash"] != _sha256(event)
                or capture_ref["result_event_hash"] != row["result_event_hash"]
                or event["result_event_id"] != result_event_id
            ):
                raise ValueError("accepted KNOT result event hash mismatch")
            if (
                event["status"] != "SUCCEEDED"
                or event["graph_run_id"] != accepted_output.get("graph_run_id")
                or event["run_slot_id"] != accepted_output.get("run_slot_id")
                or event["agent_id"] != accepted_output.get("agent_id")
            ):
                raise ValueError("accepted KNOT result event identity mismatch")
            authority = event["result_authority"]
            if (
                capture_ref["result_authority_type"] != authority["authority_type"]
                or capture_ref["result_authority_hash"] != authority["authority_hash"]
            ):
                raise ValueError("accepted KNOT result event authority mismatch")
            event_refs = [
                {
                    "binding_id": ref["binding_id"],
                    "binding_result_fingerprint": ref["binding_result_fingerprint"],
                }
                for ref in event["binding_refs"]
            ]
            if canonical_json(capture_ref["binding_result_refs"]) != canonical_json(
                event_refs
            ):
                raise ValueError("accepted KNOT result event binding mismatch")
            events[result_event_id] = event
        return events

    def _load_knot_history_authority(
        self,
        conn: sqlite3.Connection,
        *,
        capability_id: str,
    ) -> dict[str, Any]:
        capability = conn.execute(
            "SELECT manifest_json FROM capabilities WHERE capability_id = ?",
            (capability_id,),
        ).fetchone()
        capability_context = conn.execute(
            "SELECT * FROM capability_audit_contexts WHERE capability_id = ?",
            (capability_id,),
        ).fetchone()
        if capability is None or capability_context is None:
            raise ValueError("accepted KNOT capability authority is unavailable")
        manifest = cast(dict[str, Any], json.loads(capability["manifest_json"]))
        snapshot_context_row = conn.execute(
            "SELECT * FROM snapshot_bundle_audit_contexts "
            "WHERE snapshot_bundle_id = ?",
            (manifest["snapshot_bundle_id"],),
        ).fetchone()
        if snapshot_context_row is None:
            raise ValueError("accepted KNOT snapshot authority is unavailable")
        snapshot_bundle = conn.execute(
            "SELECT snapshot_bundle_hash FROM snapshot_bundles "
            "WHERE snapshot_bundle_id = ?",
            (manifest["snapshot_bundle_id"],),
        ).fetchone()
        if snapshot_bundle is None:
            raise ValueError("accepted KNOT snapshot bundle is unavailable")
        snapshot_context, snapshot_context_hash = self._validated_snapshot_audit_context(
            snapshot_context_row,
            snapshot_bundle_id=manifest["snapshot_bundle_id"],
            snapshot_bundle_hash=snapshot_bundle["snapshot_bundle_hash"],
        )
        self._validated_capability_audit_context(
            capability_context,
            manifest=manifest,
            snapshot_context_hash=snapshot_context_hash,
        )
        coverage_by_binding: dict[str, Mapping[str, Any]] = {}
        for tool_context in snapshot_context["tool_contexts"]:
            for binding_ref in tool_context["binding_refs"]:
                binding_id = str(binding_ref["binding_id"])
                if binding_id in coverage_by_binding:
                    raise ValueError("accepted KNOT capability binding is duplicated")
                coverage_by_binding[binding_id] = binding_ref["coverage_row"]
        return {
            "manifest": manifest,
            "snapshot_context": snapshot_context,
            "coverage_by_binding": coverage_by_binding,
        }

    def _load_knot_events_by_binding(
        self,
        conn: sqlite3.Connection,
        *,
        capability_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        by_binding: dict[str, list[dict[str, Any]]] = {}
        for row in conn.execute(
            "SELECT * FROM tool_result_events WHERE capability_id = ? ORDER BY sequence",
            (capability_id,),
        ).fetchall():
            event = cast(dict[str, Any], json.loads(row["event_json"]))
            if row["result_event_hash"] != _sha256(event):
                raise ValueError("KNOT history result event hash mismatch")
            if event.get("schema_version") != "server_tool_result_event_v1":
                raise ValueError("KNOT history result event version is unsupported")
            for binding_ref in event["binding_refs"]:
                by_binding.setdefault(str(binding_ref["binding_id"]), []).append(
                    {
                        "result_event_id": event["result_event_id"],
                        "result_event_hash": row["result_event_hash"],
                        "status": event["status"],
                    }
                )
        return by_binding

    def _load_knot_projection(
        self,
        conn: sqlite3.Connection,
        *,
        result_event_id: str,
        binding_id: str,
        event: Mapping[str, Any],
        binding_ref: Mapping[str, Any],
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT projection_json, projection_hash "
            "FROM binding_signal_projections "
            "WHERE result_event_id = ? AND binding_id = ?",
            (result_event_id, binding_id),
        ).fetchone()
        if row is None:
            raise ValueError("accepted KNOT binding projection is unavailable")
        projection = cast(dict[str, Any], json.loads(row["projection_json"]))
        projection_body = {
            key: value for key, value in projection.items() if key != "projection_hash"
        }
        if (
            row["projection_hash"] != _sha256(projection_body)
            or projection.get("projection_hash") != row["projection_hash"]
            or projection.get("result_event_id") != result_event_id
            or projection.get("result_event_hash") != _sha256(event)
            or projection.get("binding_id") != binding_id
            or projection.get("binding_result_fingerprint")
            != binding_ref.get("binding_result_fingerprint")
        ):
            raise ValueError("accepted KNOT binding projection authority mismatch")
        return projection

    def build_knot_history_partition_v2(
        self,
        *,
        cutoff_at: str,
        accepted_output_hashes: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Build the current-track public KNOT history without backfilling legacy rows."""
        try:
            cutoff = datetime.fromisoformat(cutoff_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ValueError("KNOT history cutoff is invalid") from exc
        if cutoff.tzinfo is None:
            raise ValueError("KNOT history cutoff must include an offset")
        cutoff_utc = cutoff.astimezone(timezone.utc)
        selected_hashes = (
            sorted(set(accepted_output_hashes))
            if accepted_output_hashes is not None
            else None
        )
        if accepted_output_hashes is not None and (
            len(selected_hashes) != len(accepted_output_hashes)
            or any(not _is_sha256(value) for value in selected_hashes)
        ):
            raise ValueError("KNOT history selected accepted-output hashes are invalid")

        root = Path(__file__).resolve().parents[2]
        current_tool_manifest = json.loads(
            (
                root / "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
            ).read_text(encoding="utf-8")
        )
        bundle = load_capability_contract_bundle(root)
        validate_capability_contract_bundle(
            bundle,
            current_tool_manifest=current_tool_manifest,
        )
        coverage = bundle["knot_coverage_manifest_v2"]
        audit_track = bundle["knot_audit_capability_track_v2"]
        accepted_track = bundle["accepted_output_capability_track"]
        binding_ids = [str(row["binding_id"]) for row in coverage["coverage"]]
        if len(binding_ids) != 187 or binding_ids != sorted(set(binding_ids)):
            raise ValueError("KNOT history active binding closure mismatch")
        fixed_point = {
            "tool_environment_hash": accepted_track["tool_environment_hash"],
            "execution_behavior_release_hash": audit_track[
                "execution_behavior_release_hash"
            ],
            "capability_bundle_hash": accepted_track["capability_bundle_hash"],
            "knot_coverage_manifest_v2_hash": coverage["manifest_hash"],
            "knot_audit_capability_track_v2_hash": audit_track["track_hash"],
        }
        observations_by_binding: dict[str, list[dict[str, Any]]] = {
            binding_id: [] for binding_id in binding_ids
        }
        materialization_refs: list[dict[str, str]] = []
        excluded_refs: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM accepted_knot_history_materializations_v2 "
                "ORDER BY accepted_output_hash"
            ).fetchall()
            for row in rows:
                if (
                    selected_hashes is not None
                    and row["accepted_output_hash"] not in selected_hashes
                ):
                    continue
                created = datetime.fromisoformat(
                    str(row["created_at"]).replace("Z", "+00:00")
                )
                if created.tzinfo is None:
                    raise ValueError("KNOT history materialization timestamp is invalid")
                if created.astimezone(timezone.utc) > cutoff_utc:
                    continue
                seen_hashes.add(str(row["accepted_output_hash"]))
                materialization = cast(
                    dict[str, Any], json.loads(row["materialization_json"])
                )
                materialization_body = {
                    key: value
                    for key, value in materialization.items()
                    if key != "materialization_hash"
                }
                if (
                    row["materialization_hash"] != _sha256(materialization_body)
                    or materialization.get("materialization_hash")
                    != row["materialization_hash"]
                    or materialization.get("accepted_output_hash")
                    != row["accepted_output_hash"]
                ):
                    raise ValueError("KNOT history materialization hash mismatch")
                validate_public_safe_projection(materialization)
                reasons: list[str] = []
                if row["status"] != "MATERIALIZED":
                    reasons.extend(str(value) for value in materialization["exclusion_reasons"])
                elif any(
                    materialization.get(field) != value
                    for field, value in fixed_point.items()
                ):
                    reasons.append("KNOT_FIXED_POINT_PARTITION_MISMATCH")
                if reasons:
                    excluded_body = {
                        "accepted_output_hash": row["accepted_output_hash"],
                        "materialization_hash": row["materialization_hash"],
                        "reasons": sorted(set(reasons)),
                    }
                    excluded_refs.append(
                        {
                            "accepted_output_hash": str(row["accepted_output_hash"]),
                            "sample_ref_hash": _sha256(excluded_body),
                            "reasons": excluded_body["reasons"],
                        }
                    )
                    continue

                observation_rows = conn.execute(
                    "SELECT * FROM knot_binding_observations_v2 "
                    "WHERE accepted_output_id = ? ORDER BY binding_id",
                    (row["accepted_output_id"],),
                ).fetchall()
                if len(observation_rows) != materialization["observation_count"]:
                    raise ValueError("KNOT history observation count mismatch")
                observation_hashes: list[str] = []
                seen_bindings: set[str] = set()
                for observation_row in observation_rows:
                    observation = cast(
                        dict[str, Any], json.loads(observation_row["observation_json"])
                    )
                    observation_body = {
                        key: value
                        for key, value in observation.items()
                        if key != "observation_hash"
                    }
                    binding_id = str(observation.get("binding_id"))
                    if (
                        observation_row["observation_hash"]
                        != _sha256(observation_body)
                        or observation.get("observation_hash")
                        != observation_row["observation_hash"]
                        or observation.get("accepted_output_id")
                        != row["accepted_output_id"]
                        or observation.get("accepted_output_hash")
                        != row["accepted_output_hash"]
                        or binding_id not in observations_by_binding
                        or binding_id in seen_bindings
                        or any(
                            observation.get(field) != value
                            for field, value in fixed_point.items()
                        )
                    ):
                        raise ValueError("KNOT history observation authority mismatch")
                    validate_public_safe_projection(observation)
                    seen_bindings.add(binding_id)
                    observation_hashes.append(str(observation["observation_hash"]))
                    observations_by_binding[binding_id].append(observation)
                if materialization["observation_set_hash"] != _sha256(
                    observation_hashes
                ):
                    raise ValueError("KNOT history observation set mismatch")
                materialization_refs.append(
                    {
                        "accepted_output_hash": str(row["accepted_output_hash"]),
                        "materialization_hash": str(row["materialization_hash"]),
                    }
                )

        if selected_hashes is not None and seen_hashes != set(selected_hashes):
            raise ValueError("KNOT history selected sample closure mismatch")

        aggregates = [
            build_knot_capability_use_aggregate(
                binding_id=binding_id,
                observations=observations_by_binding[binding_id],
            )
            for binding_id in binding_ids
        ]
        materialization_refs.sort(key=lambda value: value["accepted_output_hash"])
        excluded_refs.sort(key=lambda value: value["sample_ref_hash"])
        body = {
            "schema_version": "knot_training_history_partition_v2",
            "cutoff_at": cutoff_at,
            **fixed_point,
            "history_partition_hash": _sha256(fixed_point),
            "sample_count": len(materialization_refs),
            "excluded_sample_count": len(excluded_refs),
            "materialization_refs": materialization_refs,
            "excluded_sample_refs": excluded_refs,
            "binding_aggregates": aggregates,
            "materialization_set_hash": _sha256(materialization_refs),
            "excluded_sample_set_hash": _sha256(excluded_refs),
            "binding_aggregate_set_hash": _sha256(
                [row["aggregate_hash"] for row in aggregates]
            ),
        }
        partition = {**body, "partition_hash": _sha256(body)}
        validate_public_safe_projection(partition)
        return partition

    def terminate(self, envelope: Mapping[str, Any], reason: str) -> None:
        manifest, _ = self._verify(envelope)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("termination reason must be non-empty")
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO capability_events VALUES (?, ?, 'TERMINATED', ?, ?)",
                    (
                        f"evt_{uuid.uuid4().hex}",
                        manifest["capability_id"],
                        self.clock().astimezone(timezone.utc).isoformat(),
                        reason.strip(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("capability is already terminated") from exc


_STORE_LOCK = threading.Lock()
_STORE_BY_PATH: dict[Path, AgentToolCapabilityStore] = {}
_EPHEMERAL_SIGNING_KEY = secrets.token_bytes(32)


def capability_ledger_path() -> Path:
    isolated = isolated_agent_runtime_path(
        "runtime/agent_tool_capabilities.sqlite3"
    )
    if isolated is not None:
        return isolated.resolve()
    explicit = os.getenv("MOSAIC_AGENT_TOOL_LEDGER_PATH")
    if explicit:
        return Path(explicit).expanduser().resolve()
    cache = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return (cache / "runtime" / "agent_tool_capabilities.sqlite3").resolve()


def get_capability_store() -> AgentToolCapabilityStore:
    path = capability_ledger_path()
    with _STORE_LOCK:
        store = _STORE_BY_PATH.get(path)
        if store is None:
            raw_key = os.getenv("MOSAIC_AGENT_CAPABILITY_SIGNING_KEY")
            key = raw_key.encode("utf-8") if raw_key else _EPHEMERAL_SIGNING_KEY
            key_id = os.getenv(
                "MOSAIC_AGENT_CAPABILITY_SIGNING_KEY_ID", "runtime-ephemeral-v1"
            )
            runtime_dir = path.parent
            adaptive_store = FrozenAdaptiveQueryStore(
                runtime_dir / "agent_frozen_adaptive_queries.sqlite3"
            )
            receipt_store = StagedQueryReceiptStore(
                runtime_dir / "agent_staged_query_receipts.sqlite3"
            )
            agent_data_ledger = open_agent_data_materialization_ledger(create=True)
            forward_archive_root = Path(
                os.getenv(
                    "MOSAIC_FORWARD_ARCHIVE_ROOT",
                    str(Path(__file__).resolve().parents[2]),
                )
            ).expanduser()
            forward_query_reader = ForwardArchiveQueryReader(
                root=forward_archive_root,
                sector_archive_store=None,
                policy_cache_dir=os.getenv("MOSAIC_GOV_POLICY_CACHE_DIR"),
            )
            forward_source_preparer = ForwardArchiveSourcePreparer(
                reader=forward_query_reader
            )
            source_evidence_authority = SectorRelationshipSourceEvidenceAuthority(
                root=forward_archive_root,
                receipt_store=receipt_store,
                forward_archive_reader=forward_query_reader,
                agent_data_ledger=agent_data_ledger,
            )
            def original_query_owner(method: str, *args: Any) -> Any:
                if method == "get_industry_policy":
                    return forward_query_reader(method, *args)
                return route_to_vendor(method, *args)

            def source_evidence(
                tool_id: str,
                args: Mapping[str, Any],
                raw_payload: str,
                descriptor: Mapping[str, Any],
                source_ids: Sequence[str],
            ) -> Sequence[Mapping[str, Any]] | None:
                if tool_id in DIRECT_VENDOR_TOOL_IDS:
                    return []
                if tool_id not in {
                    "get_industry_policy_digest",
                    "get_rke_research_context",
                }:
                    raise ValueError(
                        f"no source evidence owner for deferred tool {tool_id}"
                    )
                return source_evidence_authority(
                    tool_id,
                    args,
                    raw_payload,
                    descriptor,
                    source_ids,
                )

            digest_builder_lock = threading.Lock()
            digest_builder: FrozenResearchDigestBuilder | None = None

            def frozen_research_digest(
                tool_id: str,
                raw_payload: str,
                args: dict[str, Any],
            ) -> Mapping[str, Any]:
                nonlocal digest_builder
                with digest_builder_lock:
                    if digest_builder is None:
                        digest_builder = FrozenResearchDigestBuilder()
                    builder = digest_builder
                return builder(tool_id, raw_payload, args)

            query_materializer = SectorRelationshipQueryMaterializer(
                receipt_authority=receipt_store,
                route_caller=original_query_owner,
                digest_builder=frozen_research_digest,
                supply_chain_archive=CninfoSupplyChainDisclosureCollector(
                    archive=OfficialSupplyChainDisclosureArchive(
                        Path(
                            os.getenv(
                                "MOSAIC_SUPPLY_CHAIN_ARCHIVE_PATH",
                                str(
                                    runtime_dir
                                    / "official_supply_chain_disclosures.sqlite3"
                                ),
                            )
                        ),
                        create=not (
                            os.getenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS")
                            == "structured_smoke"
                            and os.getenv("MOSAIC_SUPPLY_CHAIN_ARCHIVE_PATH")
                        ),
                    ),
                    receipt_store=receipt_store,
                    agent_data_ledger=agent_data_ledger,
                ),
                source_evidence_authority=source_evidence,
                source_preparer=forward_source_preparer,
            )
            sector_adaptive_preparer = SectorRelationshipAdaptiveQueryPreparer(
                root=Path(__file__).resolve().parents[2],
                frozen_store=adaptive_store,
                materializer=query_materializer,
            )
            bound_adaptive_preparer = BoundRuntimeAdaptiveQueryPreparer(
                root=Path(__file__).resolve().parents[2],
                frozen_store=adaptive_store,
                materializer=query_materializer,
            )
            adaptive_preparer = ActiveAdaptiveQueryPreparer(
                sector_relationship_preparer=sector_adaptive_preparer,
                bound_runtime_preparer=bound_adaptive_preparer,
            )
            store = AgentToolCapabilityStore(
                path,
                signing_key=key,
                signing_key_id=key_id,
                adaptive_query_store=adaptive_store,
                adaptive_query_preparer=adaptive_preparer,
                adaptive_query_materializer=query_materializer,
                stage_materialization_preparer=ensure_agent_stage_materialization,
                stage_materialization_finalizer=lambda context: (
                    finalize_agent_stage_materialization(
                        context,
                        adaptive_query_store=adaptive_store,
                        staged_receipt_store=receipt_store,
                    )
                ),
                require_knot_v2_audit_authority=True,
            )
            _STORE_BY_PATH[path] = store
        return store


__all__ = [
    "AGENT_TOOL_MATRIX",
    "ALL_AGENT_IDS",
    "AgentToolCapabilityStore",
    "AgentToolId",
    "CAPABILITY_CONTRACT_VERSION",
    "MACRO_AGENT_TO_TOOL",
    "SNAPSHOT_BUNDLE_CONTRACT_VERSION",
    "TOOL_DESCRIPTIONS",
    "allowed_tools_for_agent",
    "capability_ledger_path",
    "execution_stage_for_agent",
    "get_capability_store",
    "materialize_tool_payload",
]
