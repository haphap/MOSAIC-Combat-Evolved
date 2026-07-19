"""Server-enforced, bundle-bound capabilities for model-callable tools.

The model never receives the signed envelope.  The TypeScript runtime keeps it
out of band and only exposes zero-argument LangChain tools.  Every payload is
materialised before the model call, hashed into one immutable bundle, and read
back from the local ledger; ``tools.call`` never reaches a collector.
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
from mosaic.dataflows.macro_snapshots import render_role_snapshot
from mosaic.dataflows.market_breadth import render_market_breadth_snapshot
from mosaic.dataflows.role_events import render_role_event_snapshot
from mosaic.dataflows.sector_snapshots import (
    render_relationship_snapshot,
    render_sector_snapshot,
)

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
    "get_relationship_graph_snapshot",
    "get_superinvestor_candidate_snapshot",
    "get_cro_risk_snapshot",
    "get_alpha_candidate_snapshot",
    "get_execution_snapshot",
    "get_cio_decision_snapshot",
]

AGENT_TOOL_IDS: Final[tuple[AgentToolId, ...]] = (
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
    "get_relationship_graph_snapshot",
    "get_superinvestor_candidate_snapshot",
    "get_cro_risk_snapshot",
    "get_alpha_candidate_snapshot",
    "get_execution_snapshot",
    "get_cio_decision_snapshot",
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
    if not isinstance(rows, list) or len(rows) != 28:
        raise RuntimeError("canonical Agent tool contract must contain 28 agents")

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

    if len(agent_ids) != len(set(agent_ids)) or payload.get("agent_count") != 28:
        raise RuntimeError("Agent tool contract roster count mismatch")
    return (
        tuple(agent_ids),
        {layer: tuple(agents) for layer, agents in by_layer.items()},
        matrix,
    )


ALL_AGENT_IDS, AGENTS_BY_LAYER, AGENT_TOOL_MATRIX = _load_runtime_tool_contract()
STANDARD_SECTOR_AGENTS: Final[tuple[str, ...]] = tuple(
    agent for agent in AGENTS_BY_LAYER["sector"] if agent != "relationship_mapper"
)
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
    "get_relationship_graph_snapshot": "Return the frozen cross-sector relationship graph.",
    "get_superinvestor_candidate_snapshot": "Return the frozen candidate view for this investment philosophy.",
    "get_cro_risk_snapshot": "Return the frozen CRO risk and constraint snapshot.",
    "get_alpha_candidate_snapshot": "Return the frozen novel-alpha candidate snapshot.",
    "get_execution_snapshot": "Return the frozen execution-feasibility snapshot.",
    "get_cio_decision_snapshot": "Return the frozen CIO proposal or final decision snapshot.",
}
if set(TOOL_DESCRIPTIONS) != set(AGENT_TOOL_IDS):
    raise RuntimeError("tool description registry must exactly cover AgentToolId")

SNAPSHOT_BUNDLE_CONTRACT_VERSION: Final = "agent_snapshot_bundle_v1"
CAPABILITY_CONTRACT_VERSION: Final = "agent_tool_capability_v1"
DEFAULT_CAPABILITY_TTL_SECONDS: Final = 900
KNOT_PAIR_ROOT_RECEIPT_VERSION: Final = "knot_verified_pair_root_receipt_v2"
KNOT_REGIME_RECEIPT_VERSION: Final = "knot_regime_classification_receipt_v2"
KNOT_STRICT_OUTPUT_RECEIPT_VERSION: Final = (
    "knot_strict_output_validation_receipt_v2"
)
KNOT_SECTOR_USAGE_RECEIPT_VERSION: Final = (
    "knot_sector_inference_usage_receipt_v2"
)
SECTOR_USAGE_SUMMARY_RECEIPT_VERSION: Final = (
    "sector_model_usage_summary_receipt_v1"
)
KNOT_STRICT_VALIDATOR_CONTRACT: Final[dict[str, str]] = {
    "validator_contract_id": "public_json_schema_claim_graph_validator",
    "validator_contract_version": "public_json_schema_claim_graph_validator_v2",
}
KNOT_SECTOR_USAGE_INSTRUMENTATION_CONTRACT: Final[dict[str, str]] = {
    "instrumentation_contract_id": "sector_inference_usage_instrumentation",
    "instrumentation_contract_version": "sector_inference_usage_instrumentation_v1",
    "source_contract_version": "server_owned_model_usage_ledger_v1",
    "measurement_rule": "sum_provider_reported_tokens_and_count_attempted_model_subcalls",
}
SECTOR_INFERENCE_BUDGET_CONTRACT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "budget_contract_id",
        "budget_contract_version",
        "direction_research_output_token_cap",
        "conflict_review_output_token_reserve",
        "final_selection_output_token_cap",
        "total_stage_input_token_cap",
        "total_stage_output_token_cap",
        "maximum_model_subcalls",
        "review_reserve_transfer_policy",
        "budget_breach_policy",
        "budget_contract_hash",
    }
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_sector_inference_budget_contract(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an opaque private budget without embedding its parameter values."""
    contract = dict(value)
    if set(contract) != SECTOR_INFERENCE_BUDGET_CONTRACT_FIELDS:
        raise ValueError("Sector inference budget contract fields mismatch")
    if contract.get("budget_contract_id") != "sector-inference-budget":
        raise ValueError("Sector inference budget contract ID mismatch")
    if contract.get("budget_contract_version") != "sector_inference_budget_v3":
        raise ValueError("Sector inference budget contract version mismatch")
    for field in (
        "direction_research_output_token_cap",
        "conflict_review_output_token_reserve",
        "final_selection_output_token_cap",
        "total_stage_input_token_cap",
        "total_stage_output_token_cap",
        "maximum_model_subcalls",
    ):
        item = contract.get(field)
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ValueError(f"Sector inference budget {field} is invalid")
    if contract["maximum_model_subcalls"] > 3:
        raise ValueError("Sector inference budget exceeds the public subcall ceiling")
    if contract.get("review_reserve_transfer_policy") != "NON_TRANSFERABLE":
        raise ValueError("Sector inference review reserve must be non-transferable")
    if contract.get("budget_breach_policy") != "STAGE_REJECT":
        raise ValueError("Sector inference budget breach policy must reject the stage")
    supplied_hash = contract.get("budget_contract_hash")
    body = {
        key: item for key, item in contract.items() if key != "budget_contract_hash"
    }
    if not _is_sha256(supplied_hash) or supplied_hash != _sha256(body):
        raise ValueError("Sector inference budget contract hash mismatch")
    return contract


def _sector_inference_budget_ref(contract: Mapping[str, Any]) -> dict[str, str]:
    return {
        "budget_contract_id": _required_string(contract, "budget_contract_id"),
        "budget_contract_version": _required_string(
            contract, "budget_contract_version"
        ),
        "budget_contract_hash": cast(str, contract["budget_contract_hash"]),
    }


def _sector_inference_budget_violations(
    reports: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> tuple[str, ...]:
    """Return deterministic breach codes for a measured private-budget path."""
    violations: list[str] = []
    if len(reports) > contract["maximum_model_subcalls"]:
        violations.append("MODEL_SUBCALL_COUNT_EXCEEDED")
    stage_caps = {
        "DIRECTION_RESEARCH": contract["direction_research_output_token_cap"],
        "CONFLICT_REVIEW": contract["conflict_review_output_token_reserve"],
        "FINAL_SELECTION": contract["final_selection_output_token_cap"],
    }
    for stage, cap in stage_caps.items():
        stage_output_tokens = sum(
            cast(int, report["output_tokens"])
            for report in reports
            if report.get("attempted_stage") == stage
        )
        if stage_output_tokens > cap:
            violations.append(f"{stage}_OUTPUT_TOKENS_EXCEEDED")
    if sum(cast(int, report["input_tokens"]) for report in reports) > contract[
        "total_stage_input_token_cap"
    ]:
        violations.append("TOTAL_STAGE_INPUT_TOKENS_EXCEEDED")
    if sum(cast(int, report["output_tokens"]) for report in reports) > contract[
        "total_stage_output_token_cap"
    ]:
        violations.append("TOTAL_STAGE_OUTPUT_TOKENS_EXCEEDED")
    return tuple(violations)


def _classify_private_knot_regime(
    snapshot: Mapping[str, Any], *, as_of: str
) -> Mapping[str, Any]:
    from mosaic.scorecard import knot_v2 as private_knot

    result = private_knot.classify_knot_regime(snapshot, as_of=as_of)
    if not isinstance(result, Mapping):
        raise ValueError("private KNOT regime classification must be an object")
    return result


KNOT_STRICT_VALIDATOR_CONTRACT_HASH: Final = _sha256(
    KNOT_STRICT_VALIDATOR_CONTRACT
)
KNOT_SECTOR_USAGE_INSTRUMENTATION_CONTRACT_HASH: Final = _sha256(
    KNOT_SECTOR_USAGE_INSTRUMENTATION_CONTRACT
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


def _knot_payload_claim_container(
    payload: Mapping[str, Any], accepted_output_kind: str
) -> Mapping[str, Any]:
    field = {
        "STANDARD_SECTOR_SELECTION": "selection",
        "SUPERINVESTOR_SELECTION": "selection",
        "CRO_RISK_REVIEW": "review",
        "ALPHA_DISCOVERY": "selection",
        "EXECUTION_ASSESSMENT": "assessment",
        "CIO_PROPOSAL": "decision",
        "CIO_FINAL": "decision",
    }.get(accepted_output_kind)
    if field is None:
        return payload
    nested = payload.get(field)
    if not isinstance(nested, Mapping):
        raise ValueError(f"KNOT accepted output requires {field}")
    return nested


def _validate_knot_claim_graph(
    graph_value: Mapping[str, Any],
    *,
    accepted_output_record: Mapping[str, Any],
    accepted_output_kind: str,
    graph_run_id: str,
    snapshot_bundle_hash: str,
    allowed_tools: Sequence[str],
) -> None:
    graph = dict(graph_value)
    if set(graph) != {
        "schema_version",
        "run_id",
        "snapshot_hash",
        "evidence_ledger",
        "claims",
        "recommendation_claim_refs",
    }:
        raise ValueError("KNOT verified claim graph fields mismatch")
    if graph.get("schema_version") != "evidence_claim_graph_v1":
        raise ValueError("KNOT verified claim graph version mismatch")
    if (
        graph.get("run_id") != graph_run_id
        or graph.get("snapshot_hash") != snapshot_bundle_hash
    ):
        raise ValueError("KNOT verified claim graph run/snapshot mismatch")
    evidence_rows = graph.get("evidence_ledger")
    if not isinstance(evidence_rows, list) or not evidence_rows:
        raise ValueError("KNOT verified claim graph evidence is empty")
    evidence_by_id: dict[str, Mapping[str, Any]] = {}
    for index, evidence in enumerate(evidence_rows):
        if not isinstance(evidence, Mapping):
            raise ValueError(f"KNOT evidence_ledger[{index}] must be an object")
        evidence_id = _required_string(evidence, "evidence_id")
        if evidence_id in evidence_by_id:
            raise ValueError("KNOT verified claim graph has duplicate evidence IDs")
        if (
            evidence.get("run_id") != graph_run_id
            or evidence.get("snapshot_hash") != snapshot_bundle_hash
        ):
            raise ValueError("KNOT evidence lineage run/snapshot mismatch")
        source_kind = evidence.get("source_kind")
        source = _required_string(evidence, "tool_or_source")
        if source_kind not in {"tool", "runtime_source", "derived_metric"}:
            raise ValueError("KNOT evidence source kind is invalid")
        if source_kind == "tool" and source not in allowed_tools:
            raise ValueError("KNOT evidence used a tool outside the capability")
        if not _is_sha256(evidence.get("source_fingerprint")):
            raise ValueError("KNOT evidence source fingerprint is invalid")
        evidence_by_id[evidence_id] = evidence
    payload_container = _knot_payload_claim_container(
        accepted_output_record, accepted_output_kind
    )
    payload_claims = payload_container.get("claims")
    payload_claim_refs = payload_container.get("claim_refs")
    graph_claims = graph.get("claims")
    if (
        not isinstance(payload_claims, list)
        or not payload_claims
        or not isinstance(payload_claim_refs, list)
        or not payload_claim_refs
        or not isinstance(graph_claims, list)
        or not graph_claims
        or _canonical_json(payload_claims) != _canonical_json(graph_claims)
    ):
        raise ValueError("KNOT accepted output claims differ from the claim graph")
    claims_by_id: dict[str, Mapping[str, Any]] = {}
    for index, claim in enumerate(graph_claims):
        if not isinstance(claim, Mapping):
            raise ValueError(f"KNOT graph claim[{index}] must be an object")
        claim_id = _required_string(claim, "claim_id")
        if claim_id in claims_by_id:
            raise ValueError("KNOT verified claim graph has duplicate claim IDs")
        evidence_ids = claim.get("evidence_ids")
        if (
            not isinstance(evidence_ids, list)
            or not evidence_ids
            or any(
                not isinstance(evidence_id, str) or evidence_id not in evidence_by_id
                for evidence_id in evidence_ids
            )
        ):
            raise ValueError("KNOT claim references unknown evidence")
        if claim.get("claim_kind") != "RISK_FLAG" and any(
            evidence_by_id[evidence_id].get("freshness")
            in {"stale", "missing", "fallback", "tool_failed"}
            for evidence_id in evidence_ids
        ):
            raise ValueError("KNOT claim relies on unsupported evidence")
        claims_by_id[claim_id] = claim
    if (
        any(not isinstance(ref, str) or ref not in claims_by_id for ref in payload_claim_refs)
        or len(set(payload_claim_refs)) != len(payload_claim_refs)
    ):
        raise ValueError("KNOT accepted output claim_refs are invalid")
    recommendation_refs = graph.get("recommendation_claim_refs")
    if not isinstance(recommendation_refs, list):
        raise ValueError("KNOT recommendation claim refs must be an array")
    output_ids: set[str] = set()
    for index, reference in enumerate(recommendation_refs):
        if not isinstance(reference, Mapping):
            raise ValueError(
                f"KNOT recommendation_claim_refs[{index}] must be an object"
            )
        output_id = _required_string(reference, "output_id")
        claim_refs = reference.get("claim_refs")
        if (
            output_id in output_ids
            or not isinstance(claim_refs, list)
            or not claim_refs
            or any(ref not in claims_by_id for ref in claim_refs)
        ):
            raise ValueError("KNOT recommendation references unknown claims")
        output_ids.add(output_id)


def execution_stage_for_agent(agent_id: str, requested_stage: str | None = None) -> str:
    """Return one of the 29 closed execution-stage identifiers."""
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
    explicit = os.getenv("MOSAIC_RUNTIME_SNAPSHOT_DIR")
    if explicit:
        return Path(explicit).expanduser()
    cache = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache / "runtime_snapshots"


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
            "RELATIONSHIP_GRAPH",
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
            "RELATIONSHIP_GRAPH",
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
            "RELATIONSHIP_GRAPH",
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
    if agent_id == "relationship_mapper":
        return stage == agent_id and kind == "RELATIONSHIP_GRAPH"
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
                in {"STANDARD_SECTOR_SELECTION", "RELATIONSHIP_GRAPH"}
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
    for evidence in evidence_rows:
        if (
            date.fromisoformat(evidence["as_of"]) > date.fromisoformat(as_of)
            or _aware_timestamp(evidence["available_at"], "evidence.available_at")
            > as_of_close
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
    generated_at = _aware_timestamp(payload["generated_at"], "generated_at")
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
    if set(runtime_inputs) != {"accepted_output_refs"}:
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
    "economic_calendar",
    "geopolitical_events",
    "macro_snapshots",
    "market_breadth",
    "runtime_snapshots",
    "sector_snapshots",
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
    if tool_id == "get_relationship_graph_snapshot":
        if agent_id != "relationship_mapper":
            raise ValueError("relationship graph is restricted to relationship_mapper")
        return render_relationship_snapshot(as_of, graph_run_id)
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
        signing_key_is_durable: bool = True,
    ) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.signing_key = signing_key
        self.signing_key_id = signing_key_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.signing_key_is_durable = signing_key_is_durable
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
                CREATE TABLE IF NOT EXISTS verified_pair_root_receipts (
                    pair_root_reservation_id TEXT PRIMARY KEY,
                    pair_binding_hash TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL,
                    pair_root_receipt_hash TEXT NOT NULL UNIQUE,
                    receipt_signature TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS regime_classification_receipts (
                    regime_classification_receipt_id TEXT PRIMARY KEY,
                    assignment_binding_hash TEXT NOT NULL UNIQUE,
                    source_snapshot_hash TEXT NOT NULL,
                    classifier_ledger_record_json TEXT NOT NULL,
                    classifier_ledger_record_hash TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL,
                    regime_classification_receipt_hash TEXT NOT NULL UNIQUE,
                    receipt_signature TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capability_reservations (
                    capability_id TEXT PRIMARY KEY,
                    pair_root_reservation_id TEXT NOT NULL,
                    pair_side TEXT NOT NULL CHECK(pair_side IN ('CHAMPION', 'CANDIDATE')),
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id),
                    FOREIGN KEY(pair_root_reservation_id)
                      REFERENCES verified_pair_root_receipts(pair_root_reservation_id),
                    UNIQUE(pair_root_reservation_id, pair_side)
                );
                CREATE TABLE IF NOT EXISTS private_pair_bindings (
                    knot_pair_id TEXT PRIMARY KEY,
                    knot_pair_input_hash TEXT NOT NULL UNIQUE,
                    pair_root_reservation_id TEXT NOT NULL UNIQUE,
                    bound_at TEXT NOT NULL,
                    FOREIGN KEY(pair_root_reservation_id)
                      REFERENCES verified_pair_root_receipts(pair_root_reservation_id)
                );
                CREATE TABLE IF NOT EXISTS private_pair_sector_budget_bindings (
                    knot_pair_id TEXT PRIMARY KEY,
                    pair_root_reservation_id TEXT NOT NULL UNIQUE,
                    agent_id TEXT NOT NULL,
                    budget_contract_json TEXT NOT NULL,
                    budget_contract_hash TEXT NOT NULL,
                    bound_at TEXT NOT NULL,
                    FOREIGN KEY(knot_pair_id) REFERENCES private_pair_bindings(knot_pair_id),
                    FOREIGN KEY(pair_root_reservation_id)
                      REFERENCES verified_pair_root_receipts(pair_root_reservation_id)
                );
                CREATE TABLE IF NOT EXISTS strict_output_validation_receipts (
                    strict_validation_receipt_id TEXT PRIMARY KEY,
                    pair_root_reservation_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    accepted_output_kind TEXT NOT NULL,
                    accepted_output_record_hash TEXT NOT NULL,
                    verified_claim_graph_hash TEXT NOT NULL,
                    schema_hash TEXT NOT NULL,
                    validator_ledger_record_json TEXT NOT NULL,
                    validator_ledger_record_hash TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL,
                    strict_validation_receipt_hash TEXT NOT NULL UNIQUE,
                    receipt_signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(pair_root_reservation_id)
                      REFERENCES verified_pair_root_receipts(pair_root_reservation_id),
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id),
                    UNIQUE(pair_root_reservation_id, capability_id, accepted_output_kind)
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
                CREATE TABLE IF NOT EXISTS sector_inference_usage_receipts (
                    usage_receipt_id TEXT PRIMARY KEY,
                    pair_root_reservation_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL UNIQUE,
                    usage_ledger_record_json TEXT NOT NULL,
                    usage_ledger_record_hash TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL,
                    usage_receipt_hash TEXT NOT NULL UNIQUE,
                    receipt_signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(pair_root_reservation_id)
                      REFERENCES verified_pair_root_receipts(pair_root_reservation_id),
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
                CREATE TRIGGER IF NOT EXISTS verified_pair_root_receipts_no_update
                  BEFORE UPDATE ON verified_pair_root_receipts BEGIN
                    SELECT RAISE(ABORT, 'verified_pair_root_receipts is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS regime_receipts_no_update
                  BEFORE UPDATE ON regime_classification_receipts BEGIN
                    SELECT RAISE(ABORT, 'knot regime receipts are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS regime_receipts_no_delete
                  BEFORE DELETE ON regime_classification_receipts BEGIN
                    SELECT RAISE(ABORT, 'knot regime receipts are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS verified_pair_root_receipts_no_delete
                  BEFORE DELETE ON verified_pair_root_receipts BEGIN
                    SELECT RAISE(ABORT, 'verified_pair_root_receipts is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_reservations_no_update
                  BEFORE UPDATE ON capability_reservations BEGIN
                    SELECT RAISE(ABORT, 'capability_reservations is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_reservations_no_delete
                  BEFORE DELETE ON capability_reservations BEGIN
                    SELECT RAISE(ABORT, 'capability_reservations is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS private_pair_bindings_no_update
                  BEFORE UPDATE ON private_pair_bindings BEGIN
                    SELECT RAISE(ABORT, 'private_pair_bindings is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS private_pair_bindings_no_delete
                  BEFORE DELETE ON private_pair_bindings BEGIN
                    SELECT RAISE(ABORT, 'private_pair_bindings is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS private_pair_sector_budgets_no_update
                  BEFORE UPDATE ON private_pair_sector_budget_bindings BEGIN
                    SELECT RAISE(ABORT, 'private_pair_sector_budget_bindings is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS private_pair_sector_budgets_no_delete
                  BEFORE DELETE ON private_pair_sector_budget_bindings BEGIN
                    SELECT RAISE(ABORT, 'private_pair_sector_budget_bindings is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS strict_output_receipts_no_update
                  BEFORE UPDATE ON strict_output_validation_receipts BEGIN
                    SELECT RAISE(ABORT, 'knot strict output receipts are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS strict_output_receipts_no_delete
                  BEFORE DELETE ON strict_output_validation_receipts BEGIN
                    SELECT RAISE(ABORT, 'knot strict output receipts are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS sector_usage_events_no_update
                  BEFORE UPDATE ON sector_model_usage_events BEGIN
                    SELECT RAISE(ABORT, 'knot sector usage events are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS sector_usage_events_no_delete
                  BEFORE DELETE ON sector_model_usage_events BEGIN
                    SELECT RAISE(ABORT, 'knot sector usage events are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS sector_usage_summaries_no_update
                  BEFORE UPDATE ON sector_model_usage_summaries BEGIN
                    SELECT RAISE(ABORT, 'sector usage summaries are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS sector_usage_summaries_no_delete
                  BEFORE DELETE ON sector_model_usage_summaries BEGIN
                    SELECT RAISE(ABORT, 'sector usage summaries are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS sector_usage_receipts_no_update
                  BEFORE UPDATE ON sector_inference_usage_receipts BEGIN
                    SELECT RAISE(ABORT, 'knot sector usage receipts are append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS sector_usage_receipts_no_delete
                  BEFORE DELETE ON sector_inference_usage_receipts BEGIN
                    SELECT RAISE(ABORT, 'knot sector usage receipts are append-only');
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
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO materialization_requests VALUES (?, ?, ?, ?, ?)",
                    (materialization_request_id, agent_id, stage, as_of, now.isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("materialization_request_id has already been used") from exc

        allowed_tools = allowed_tools_for_agent(agent_id)
        payloads: dict[AgentToolId, str] = {}
        for tool_id in allowed_tools:
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
        if set(payloads) != set(allowed_tools):
            raise ValueError("materialized payload keys do not match allowed tools")
        if any(not isinstance(payload, str) or not payload for payload in payloads.values()):
            raise ValueError("every materialized tool payload must be a non-empty string")

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
                conn.execute(
                    "INSERT INTO capability_events VALUES (?, ?, 'ISSUED', ?, NULL)",
                    (f"evt_{uuid.uuid4().hex}", capability_id, now.isoformat()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {"bundle": bundle, "capability": signed.as_dict()}

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
                conn.execute(
                    "INSERT INTO capability_events VALUES (?, ?, 'ISSUED', ?, NULL)",
                    (f"evt_{uuid.uuid4().hex}", capability_id, now.isoformat()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {"bundle": bundle, "capability": signed.as_dict()}

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

    def verify_and_reserve_knot_pair_root(
        self,
        *,
        pair_binding: Mapping[str, Any],
        champion_envelope: Mapping[str, Any],
        candidate_envelope: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Verify two issued capabilities and reserve their shared KNOT root."""
        self._require_durable_knot_key()
        expected_binding_keys = {
            "knot_research_track_id",
            "knot_pair_assignment_id",
            "research_slot_id",
            "evaluation_opportunity_set_id",
        }
        if set(pair_binding) != expected_binding_keys:
            raise ValueError("KNOT pair binding fields mismatch")
        binding = {
            key: _required_string(pair_binding, key)
            for key in (
                "knot_research_track_id",
                "knot_pair_assignment_id",
                "research_slot_id",
                "evaluation_opportunity_set_id",
            )
        }
        binding_hash = _sha256(binding)
        verified_at = self.clock().astimezone(timezone.utc)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT receipt_json FROM verified_pair_root_receipts "
                    "WHERE pair_binding_hash = ?",
                    (binding_hash,),
                ).fetchone()
                if existing is not None:
                    receipt = json.loads(existing["receipt_json"])
                    receipt_verified_at = _aware_timestamp(
                        receipt.get("verified_at"), "pair_root.verified_at"
                    )
                    champion_manifest, _ = self._verify(
                        champion_envelope,
                        conn=conn,
                        allow_terminated=True,
                        verified_at=receipt_verified_at,
                    )
                    candidate_manifest, _ = self._verify(
                        candidate_envelope,
                        conn=conn,
                        allow_terminated=True,
                        verified_at=receipt_verified_at,
                    )
                    expected_ids = {
                        "CHAMPION": champion_manifest["capability_id"],
                        "CANDIDATE": candidate_manifest["capability_id"],
                    }
                    actual_ids = {
                        side: receipt.get("capabilities", {}).get(side, {}).get(
                            "capability_id"
                        )
                        for side in ("CHAMPION", "CANDIDATE")
                    }
                    if actual_ids != expected_ids or receipt.get("pair_binding") != binding:
                        raise ValueError("KNOT pair-root retry changed immutable inputs")
                    self._verify_knot_pair_root_receipt_with_conn(
                        conn,
                        receipt,
                        require_active_capabilities=False,
                    )
                    conn.execute("COMMIT")
                    return receipt

                champion_manifest, champion_row = self._verify(
                    champion_envelope,
                    conn=conn,
                    verified_at=verified_at,
                )
                candidate_manifest, candidate_row = self._verify(
                    candidate_envelope,
                    conn=conn,
                    verified_at=verified_at,
                )
                manifests = {
                    "CHAMPION": champion_manifest,
                    "CANDIDATE": candidate_manifest,
                }
                rows = {
                    "CHAMPION": champion_row,
                    "CANDIDATE": candidate_row,
                }
                self._validate_knot_pair_capabilities(conn, manifests, rows)
                bundle = json.loads(champion_row["bundle_json"])
                reservation_id = f"knot-pair-root:{uuid.uuid4().hex}"
                unsigned_body = {
                    "schema_version": KNOT_PAIR_ROOT_RECEIPT_VERSION,
                    "pair_root_reservation_id": reservation_id,
                    "pair_binding": binding,
                    "pair_binding_hash": binding_hash,
                    "agent_id": champion_manifest["agent_id"],
                    "stage": champion_manifest["stage"],
                    "as_of": champion_manifest["as_of"],
                    "snapshot_bundle_contract_version": bundle[
                        "snapshot_bundle_contract_version"
                    ],
                    "snapshot_bundle_id": bundle["snapshot_bundle_id"],
                    "snapshot_bundle_hash": bundle["snapshot_bundle_hash"],
                    "runtime_input_hash": bundle["runtime_input_hash"],
                    "candidate_scope_hash": bundle.get("candidate_scope_hash"),
                    "allowed_tools": list(champion_manifest["allowed_tools"]),
                    "tool_payload_hashes": dict(bundle["tool_payload_hashes"]),
                    "capabilities": {
                        side: self._knot_capability_projection(
                            manifests[side], rows[side]
                        )
                        for side in ("CHAMPION", "CANDIDATE")
                    },
                    "verified_at": verified_at.isoformat(),
                    "reservation_status": "ACTIVE",
                    "receipt_signing_key_id": self.signing_key_id,
                }
                receipt_hash = _sha256(unsigned_body)
                signed_body = {
                    **unsigned_body,
                    "pair_root_receipt_hash": receipt_hash,
                }
                receipt = {
                    **signed_body,
                    "receipt_signature": self._sign_domain(
                        "knot-pair-root-receipt-v2\0", signed_body
                    ),
                }
                conn.execute(
                    "INSERT INTO verified_pair_root_receipts VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        reservation_id,
                        binding_hash,
                        _canonical_json(receipt),
                        receipt_hash,
                        receipt["receipt_signature"],
                        verified_at.isoformat(),
                    ),
                )
                for side in ("CHAMPION", "CANDIDATE"):
                    conn.execute(
                        "INSERT INTO capability_reservations VALUES (?, ?, ?)",
                        (manifests[side]["capability_id"], reservation_id, side),
                    )
                conn.execute("COMMIT")
                return receipt
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise ValueError(
                    "KNOT capability or pair root has already been reserved"
                ) from exc
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def classify_and_reserve_knot_regime(
        self,
        *,
        knot_research_track_id: str,
        research_slot_id: str,
        scheduled_sample_id: str,
        expected_as_of: str,
        source_snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Reserve one opaque, pinned-private classification for a PIT snapshot."""
        self._require_durable_knot_key()
        date.fromisoformat(expected_as_of)
        binding = {
            "knot_research_track_id": _required_string(
                {"value": knot_research_track_id}, "value"
            ),
            "research_slot_id": _required_string(
                {"value": research_slot_id}, "value"
            ),
            "scheduled_sample_id": _required_string(
                {"value": scheduled_sample_id}, "value"
            ),
            "as_of": expected_as_of,
        }
        binding_hash = _sha256(binding)
        snapshot = dict(source_snapshot)
        supplied_snapshot_hash = snapshot.get("snapshot_hash")
        if not _is_sha256(supplied_snapshot_hash) or supplied_snapshot_hash != _sha256(
            {key: item for key, item in snapshot.items() if key != "snapshot_hash"}
        ):
            raise ValueError("KNOT regime source snapshot hash mismatch")
        classification = _classify_private_knot_regime(
            snapshot, as_of=expected_as_of
        )
        if not isinstance(classification, Mapping) or set(classification) != {
            "regime_label",
            "classifier_contract_id",
            "classifier_contract_version",
            "classifier_contract_hash",
            "pit_snapshot_hash",
        }:
            raise ValueError("private KNOT regime classification contract mismatch")
        evaluation_regime = classification.get("regime_label")
        if evaluation_regime not in {"normal", "stress"}:
            raise ValueError("private KNOT regime label is invalid")
        classifier_contract_id = _required_string(
            classification, "classifier_contract_id"
        )
        classifier_contract_version = _required_string(
            classification, "classifier_contract_version"
        )
        classifier_contract_hash = classification.get("classifier_contract_hash")
        if not _is_sha256(classifier_contract_hash):
            raise ValueError("private KNOT classifier contract hash is invalid")
        if classification.get("pit_snapshot_hash") != supplied_snapshot_hash:
            raise ValueError("private KNOT classification snapshot binding mismatch")
        as_of_timestamp = f"{expected_as_of}T15:00:00+08:00"
        classified_at = self.clock().astimezone(timezone.utc)
        source_snapshot_id = (
            "private-regime-source:"
            + supplied_snapshot_hash.removeprefix("sha256:")
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT * FROM regime_classification_receipts "
                    "WHERE assignment_binding_hash = ?",
                    (binding_hash,),
                ).fetchone()
                if existing is not None:
                    if existing["source_snapshot_hash"] != supplied_snapshot_hash:
                        raise ValueError(
                            "KNOT regime classification retry changed its source"
                        )
                    receipt = json.loads(existing["receipt_json"])
                    self._verify_knot_regime_receipt_with_conn(conn, receipt)
                    conn.execute("COMMIT")
                    return receipt
                receipt_id = f"knot-regime-receipt:{uuid.uuid4().hex}"
                ledger_id = f"knot-regime-ledger:{uuid.uuid4().hex}"
                ledger_without_hash = {
                    "classifier_ledger_record_id": ledger_id,
                    "classifier_contract_id": classifier_contract_id,
                    "classifier_contract_version": classifier_contract_version,
                    "classifier_contract_hash": classifier_contract_hash,
                    "assignment_binding": binding,
                    "assignment_binding_hash": binding_hash,
                    "source_snapshot_hash": supplied_snapshot_hash,
                    "evaluation_regime": evaluation_regime,
                    "classified_at": classified_at.isoformat(),
                }
                ledger_hash = _sha256(ledger_without_hash)
                ledger_record = {
                    **ledger_without_hash,
                    "classifier_ledger_record_hash": ledger_hash,
                }
                unsigned_body = {
                    "schema_version": KNOT_REGIME_RECEIPT_VERSION,
                    "regime_classification_receipt_id": receipt_id,
                    "knot_research_track_id": binding["knot_research_track_id"],
                    "research_slot_id": binding["research_slot_id"],
                    "scheduled_sample_id": binding["scheduled_sample_id"],
                    "evaluation_regime": evaluation_regime,
                    "source_snapshot_id": source_snapshot_id,
                    "source_snapshot_hash": supplied_snapshot_hash,
                    "classifier_contract_id": classifier_contract_id,
                    "classifier_contract_version": classifier_contract_version,
                    "classifier_contract_hash": classifier_contract_hash,
                    "as_of": as_of_timestamp,
                    "classified_at": classified_at.isoformat(),
                    "classifier_ledger_record_id": ledger_id,
                    "classifier_ledger_record_hash": ledger_hash,
                    "receipt_signing_key_id": self.signing_key_id,
                }
                receipt_hash = _sha256(unsigned_body)
                signed_body = {
                    **unsigned_body,
                    "regime_classification_receipt_hash": receipt_hash,
                }
                receipt = {
                    **signed_body,
                    "receipt_signature": self._sign_domain(
                        "knot-regime-classification-receipt-v2\0", signed_body
                    ),
                }
                conn.execute(
                    "INSERT INTO regime_classification_receipts "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        receipt_id,
                        binding_hash,
                        supplied_snapshot_hash,
                        _canonical_json(ledger_record),
                        ledger_hash,
                        _canonical_json(receipt),
                        receipt_hash,
                        receipt["receipt_signature"],
                        classified_at.isoformat(),
                    ),
                )
                conn.execute("COMMIT")
                return receipt
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise ValueError("KNOT regime receipt collision") from exc
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def verify_knot_regime_classification_receipt(
        self, receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        self._require_durable_knot_key()
        with self._connect() as conn:
            return self._verify_knot_regime_receipt_with_conn(conn, receipt)

    def verify_knot_pair_root_receipt(
        self, receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Dereference and revalidate one public KNOT pair-root receipt."""
        self._require_durable_knot_key()
        with self._connect() as conn:
            return self._verify_knot_pair_root_receipt_with_conn(conn, receipt)

    def bind_knot_private_pair(
        self,
        *,
        pair_root_reservation_id: str,
        knot_pair_id: str,
        knot_pair_input_hash: str,
        sector_inference_budget_contract: Mapping[str, Any] | None,
    ) -> None:
        """Bind a successful private freeze result to its public reservation."""
        reservation_id = _required_string(
            {"value": pair_root_reservation_id}, "value"
        )
        pair_id = _required_string({"value": knot_pair_id}, "value")
        if not _is_sha256(knot_pair_input_hash):
            raise ValueError("knot_pair_input_hash must be sha256")
        now = self.clock().astimezone(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT receipt_json FROM verified_pair_root_receipts "
                    "WHERE pair_root_reservation_id = ?",
                    (reservation_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("unknown KNOT pair-root reservation")
                pair_receipt = self._verify_knot_pair_root_receipt_with_conn(
                    conn,
                    json.loads(row["receipt_json"]),
                    require_active_capabilities=False,
                )
                agent_id = pair_receipt["agent_id"]
                budget_contract = (
                    _validate_sector_inference_budget_contract(
                        sector_inference_budget_contract
                    )
                    if sector_inference_budget_contract is not None
                    else None
                )
                if agent_id in STANDARD_SECTOR_AGENTS and budget_contract is None:
                    raise ValueError(
                        "standard Sector KNOT pair requires an inference budget contract"
                    )
                if agent_id not in STANDARD_SECTOR_AGENTS and budget_contract is not None:
                    raise ValueError(
                        "Sector inference budget contract is restricted to standard Sector"
                    )
                existing = conn.execute(
                    "SELECT * FROM private_pair_bindings "
                    "WHERE knot_pair_id = ? OR pair_root_reservation_id = ?",
                    (pair_id, reservation_id),
                ).fetchall()
                if existing:
                    if len(existing) != 1 or any(
                        item["knot_pair_id"] != pair_id
                        or item["knot_pair_input_hash"] != knot_pair_input_hash
                        or item["pair_root_reservation_id"] != reservation_id
                        for item in existing
                    ):
                        raise ValueError("KNOT private pair binding collision")
                else:
                    conn.execute(
                        "INSERT INTO private_pair_bindings VALUES (?, ?, ?, ?)",
                        (pair_id, knot_pair_input_hash, reservation_id, now),
                    )
                budget_row = conn.execute(
                    "SELECT * FROM private_pair_sector_budget_bindings "
                    "WHERE knot_pair_id = ? OR pair_root_reservation_id = ?",
                    (pair_id, reservation_id),
                ).fetchall()
                if budget_contract is None:
                    if budget_row:
                        raise ValueError("KNOT private Sector budget binding collision")
                elif budget_row:
                    if len(budget_row) != 1 or any(
                        item["knot_pair_id"] != pair_id
                        or item["pair_root_reservation_id"] != reservation_id
                        or item["agent_id"] != agent_id
                        or item["budget_contract_json"]
                        != _canonical_json(budget_contract)
                        or item["budget_contract_hash"]
                        != budget_contract["budget_contract_hash"]
                        for item in budget_row
                    ):
                        raise ValueError("KNOT private Sector budget binding collision")
                else:
                    conn.execute(
                        "INSERT INTO private_pair_sector_budget_bindings "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            pair_id,
                            reservation_id,
                            agent_id,
                            _canonical_json(budget_contract),
                            budget_contract["budget_contract_hash"],
                            now,
                        ),
                    )
                conn.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise ValueError("KNOT private pair binding collision") from exc
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def _sector_budget_for_reservation(
        self,
        conn: sqlite3.Connection,
        reservation_id: str,
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT budget_contract_json FROM private_pair_sector_budget_bindings "
            "WHERE pair_root_reservation_id = ?",
            (reservation_id,),
        ).fetchone()
        if row is None:
            raise ValueError("standard Sector KNOT budget is not pre-bound")
        try:
            value = json.loads(row["budget_contract_json"])
        except json.JSONDecodeError as exc:
            raise ValueError("stored Sector inference budget is unreadable") from exc
        if not isinstance(value, dict):
            raise ValueError("stored Sector inference budget is invalid")
        return _validate_sector_inference_budget_contract(value)

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
                reservation = conn.execute(
                    "SELECT pair_root_reservation_id, pair_side "
                    "FROM capability_reservations WHERE capability_id = ?",
                    (manifest["capability_id"],),
                ).fetchone()
                uses = conn.execute(
                    "SELECT tool_id FROM capability_tool_uses "
                    "WHERE capability_id = ? ORDER BY tool_id",
                    (manifest["capability_id"],),
                ).fetchall()
                if [row["tool_id"] for row in uses] != sorted(
                    manifest["allowed_tools"]
                ):
                    raise ValueError(
                        "Sector model usage requires the exact frozen tool set"
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
                    "pair_root_reservation_id": (
                        reservation["pair_root_reservation_id"]
                        if reservation is not None
                        else None
                    ),
                    "pair_side": reservation["pair_side"] if reservation is not None else None,
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
    def record_knot_sector_model_usage(
        self,
        *,
        capability_envelope: Mapping[str, Any],
        usage_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.record_sector_model_usage(
            capability_envelope=capability_envelope,
            usage_report=usage_report,
        )

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
                if [row["tool_id"] for row in uses] != sorted(
                    manifest["allowed_tools"]
                ):
                    raise ValueError(
                        "Sector model usage finalization requires the exact frozen tool set"
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
                reservation = conn.execute(
                    "SELECT pair_root_reservation_id, pair_side "
                    "FROM capability_reservations WHERE capability_id = ?",
                    (capability_id,),
                ).fetchone()
                budget_contract = (
                    self._sector_budget_for_reservation(
                        conn, reservation["pair_root_reservation_id"]
                    )
                    if reservation is not None
                    else None
                )
                budget_violations = (
                    _sector_inference_budget_violations(reports, budget_contract)
                    if budget_contract is not None
                    else ()
                )
                budget_contract_ref = (
                    _sector_inference_budget_ref(budget_contract)
                    if budget_contract is not None
                    else None
                )
                ordinary_completed = bool(reports) and (
                    reports[-1]["attempted_stage"] == "FINAL_SELECTION"
                    and reports[-1]["attempt_status"] == "ACCEPTED"
                )
                exact_knot_path = stages in (
                    ["DIRECTION_RESEARCH", "FINAL_SELECTION"],
                    ["DIRECTION_RESEARCH", "CONFLICT_REVIEW", "FINAL_SELECTION"],
                ) and all(report["attempt_status"] == "ACCEPTED" for report in reports)
                completed = (
                    ordinary_completed
                    if budget_contract is None
                    else exact_knot_path and not budget_violations
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
                    "budget_contract_ref": budget_contract_ref,
                    "budget_decision": (
                        {
                            "disposition": (
                                "STAGE_REJECT"
                                if budget_violations
                                else "WITHIN_BUDGET"
                            ),
                            "violation_codes": list(budget_violations),
                        }
                        if budget_contract is not None
                        else None
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
                    "pair_root_reservation_id": (
                        reservation["pair_root_reservation_id"]
                        if reservation is not None
                        else None
                    ),
                    "pair_side": reservation["pair_side"] if reservation is not None else None,
                    "budget_contract_ref": budget_contract_ref,
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
                    **KNOT_SECTOR_USAGE_INSTRUMENTATION_CONTRACT,
                    "instrumentation_contract_hash": (
                        KNOT_SECTOR_USAGE_INSTRUMENTATION_CONTRACT_HASH
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

    def mint_knot_sector_inference_usage_receipt(
        self, *, binding: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Aggregate the server-owned Sector usage ledger and sign its receipt."""
        self._require_durable_knot_key()
        expected_binding_keys = {
            "schema_version",
            "knot_pair_id",
            "knot_pair_input_hash",
            "pair_side",
            "production_variant_roster_id",
            "production_variant_roster_revision_id",
            "execution_behavior_release_id",
            "cohort_id",
            "language",
            "pair_root_reservation_id",
            "pair_root_receipt_hash",
            "capability_id",
            "capability_manifest_hash",
            "graph_run_id",
            "run_slot_id",
            "run_id",
            "node_id",
            "agent_id",
            "stage",
            "as_of",
            "snapshot_bundle_hash",
            "operational_opportunity_audit_id",
            "operational_opportunity_audit_hash",
            "accepted_output_id",
            "accepted_output_hash",
            "accepted_direction_comparison_audit_id",
            "accepted_direction_comparison_audit_hash",
            "accepted_runtime_inference_cost_audit_id",
            "accepted_runtime_inference_cost_audit_hash",
            "budget_contract_id",
            "budget_contract_version",
            "budget_contract_hash",
            "expected_result_disposition",
            "sector_usage_binding_hash",
        }
        normalized_binding = dict(binding)
        if set(normalized_binding) != expected_binding_keys:
            raise ValueError("KNOT Sector usage binding fields mismatch")
        if normalized_binding.get("schema_version") != "knot_sector_usage_binding_v2":
            raise ValueError("KNOT Sector usage binding version mismatch")
        supplied_binding_hash = normalized_binding.get("sector_usage_binding_hash")
        if not _is_sha256(supplied_binding_hash) or supplied_binding_hash != _sha256(
            {
                key: item
                for key, item in normalized_binding.items()
                if key != "sector_usage_binding_hash"
            }
        ):
            raise ValueError("KNOT Sector usage binding hash mismatch")
        for field in (
            "knot_pair_id",
            "production_variant_roster_id",
            "production_variant_roster_revision_id",
            "execution_behavior_release_id",
            "cohort_id",
            "language",
            "pair_root_reservation_id",
            "capability_id",
            "graph_run_id",
            "run_slot_id",
            "run_id",
            "node_id",
            "agent_id",
            "stage",
            "as_of",
            "operational_opportunity_audit_id",
            "budget_contract_id",
            "budget_contract_version",
        ):
            _required_string(normalized_binding, field)
        for field in (
            "knot_pair_input_hash",
            "pair_root_receipt_hash",
            "capability_manifest_hash",
            "snapshot_bundle_hash",
            "operational_opportunity_audit_hash",
            "budget_contract_hash",
        ):
            if not _is_sha256(normalized_binding.get(field)):
                raise ValueError(f"KNOT Sector {field} is invalid")
        if normalized_binding["pair_side"] not in {"CHAMPION", "CANDIDATE"}:
            raise ValueError("KNOT Sector usage binding pair side is invalid")
        disposition = normalized_binding["expected_result_disposition"]
        if disposition not in {"ACCEPTED", "AGENT_FAILURE"}:
            raise ValueError("KNOT Sector usage binding disposition is invalid")
        nullable_pairs = (
            ("accepted_output_id", "accepted_output_hash"),
            (
                "accepted_direction_comparison_audit_id",
                "accepted_direction_comparison_audit_hash",
            ),
            (
                "accepted_runtime_inference_cost_audit_id",
                "accepted_runtime_inference_cost_audit_hash",
            ),
        )
        for id_field, hash_field in nullable_pairs:
            identifier = normalized_binding[id_field]
            digest = normalized_binding[hash_field]
            if (identifier is None) != (digest is None):
                raise ValueError(f"KNOT Sector {id_field}/{hash_field} must be paired")
            if identifier is not None:
                _required_string(normalized_binding, id_field)
                if not _is_sha256(digest):
                    raise ValueError(f"KNOT Sector {hash_field} is invalid")
        if disposition == "ACCEPTED" and any(
            normalized_binding[id_field] is None for id_field, _ in nullable_pairs
        ):
            raise ValueError("accepted KNOT Sector usage binding is incomplete")
        if disposition == "AGENT_FAILURE" and normalized_binding["accepted_output_id"]:
            raise ValueError("failed KNOT Sector usage binding has accepted output")

        verified_at = self.clock().astimezone(timezone.utc)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                pair_row = conn.execute(
                    "SELECT receipt_json FROM verified_pair_root_receipts "
                    "WHERE pair_root_reservation_id = ?",
                    (normalized_binding["pair_root_reservation_id"],),
                ).fetchone()
                if pair_row is None:
                    raise ValueError("KNOT Sector pair-root receipt is unavailable")
                pair_receipt = self._verify_knot_pair_root_receipt_with_conn(
                    conn,
                    json.loads(pair_row["receipt_json"]),
                    require_active_capabilities=False,
                )
                capability = pair_receipt["capabilities"][
                    normalized_binding["pair_side"]
                ]
                budget_contract = self._sector_budget_for_reservation(
                    conn, normalized_binding["pair_root_reservation_id"]
                )
                budget_ref = _sector_inference_budget_ref(budget_contract)
                for binding_field, ref_field in (
                    ("budget_contract_id", "budget_contract_id"),
                    ("budget_contract_version", "budget_contract_version"),
                    ("budget_contract_hash", "budget_contract_hash"),
                ):
                    if normalized_binding[binding_field] != budget_ref[ref_field]:
                        raise ValueError(
                            "KNOT Sector usage binding budget differs from pre-bound contract"
                        )
                expected_lineage = {
                    "pair_root_receipt_hash": pair_receipt["pair_root_receipt_hash"],
                    "capability_id": capability["capability_id"],
                    "capability_manifest_hash": capability[
                        "capability_manifest_hash"
                    ],
                    "graph_run_id": capability["graph_run_id"],
                    "run_slot_id": capability["run_slot_id"],
                    "run_id": capability["run_id"],
                    "node_id": capability["node_id"],
                    "agent_id": capability["agent_id"],
                    "stage": capability["stage"],
                    "as_of": capability["as_of"],
                    "snapshot_bundle_hash": pair_receipt["snapshot_bundle_hash"],
                }
                for field, expected in expected_lineage.items():
                    if normalized_binding.get(field) != expected:
                        raise ValueError(
                            f"KNOT Sector usage binding {field} mismatch"
                        )
                if capability["agent_id"] not in STANDARD_SECTOR_AGENTS:
                    raise ValueError("KNOT usage receipt is restricted to standard Sector")
                self._validate_knot_capability_completion(
                    conn,
                    capability=capability,
                    allowed_tools=pair_receipt["allowed_tools"],
                    validated_at=verified_at,
                )
                existing = conn.execute(
                    "SELECT receipt_json, usage_ledger_record_json "
                    "FROM sector_inference_usage_receipts "
                    "WHERE capability_id = ?",
                    (capability["capability_id"],),
                ).fetchone()
                if existing is not None:
                    receipt = json.loads(existing["receipt_json"])
                    self._verify_knot_sector_usage_receipt_with_conn(conn, receipt)
                    existing_ledger = json.loads(
                        existing["usage_ledger_record_json"]
                    )
                    if (
                        existing_ledger.get("sector_usage_binding_hash")
                        != supplied_binding_hash
                    ):
                        raise ValueError(
                            "KNOT Sector usage retry changed immutable binding"
                        )
                    conn.execute("COMMIT")
                    return receipt

                event_rows = conn.execute(
                    "SELECT event_json FROM sector_model_usage_events "
                    "WHERE capability_id = ? ORDER BY subcall_sequence",
                    (capability["capability_id"],),
                ).fetchall()
                events = [json.loads(row["event_json"]) for row in event_rows]
                for sequence, event in enumerate(events, start=1):
                    body = {
                        key: item
                        for key, item in event.items()
                        if key != "usage_event_hash"
                    }
                    if (
                        event.get("usage_event_hash") != _sha256(body)
                        or event.get("subcall_sequence") != sequence
                        or event.get("capability_id") != capability["capability_id"]
                        or event.get("pair_root_reservation_id")
                        != normalized_binding["pair_root_reservation_id"]
                        or event.get("pair_side") != normalized_binding["pair_side"]
                    ):
                        raise ValueError("KNOT Sector usage event ledger mismatch")
                reports = [event["usage_report"] for event in events]
                budget_violations = _sector_inference_budget_violations(
                    reports, budget_contract
                )
                stages = [report["attempted_stage"] for report in reports]
                conflict_review_triggered = "CONFLICT_REVIEW" in stages
                if disposition == "ACCEPTED":
                    expected_stages = [
                        "DIRECTION_RESEARCH",
                        *(["CONFLICT_REVIEW"] if conflict_review_triggered else []),
                        "FINAL_SELECTION",
                    ]
                    if stages != expected_stages or any(
                        report["attempt_status"] != "ACCEPTED" for report in reports
                    ) or budget_violations:
                        raise ValueError(
                            "accepted KNOT Sector usage path is incomplete or over budget"
                        )
                    last_attempted_stage = "COMPLETED"
                else:
                    last_attempted_stage = stages[-1] if stages else "PRE_MODEL"
                model_subcall_count = len(events)
                if disposition == "ACCEPTED" and model_subcall_count not in {2, 3}:
                    raise ValueError("accepted KNOT Sector usage count is invalid")
                input_tokens = sum(report["input_tokens"] for report in reports)
                output_tokens = sum(report["output_tokens"] for report in reports)
                final_report = reports[-1] if reports else {}
                direction_id = final_report.get("direction_comparison_audit_id")
                direction_hash = final_report.get("direction_comparison_audit_hash")
                conflict_id = final_report.get("conflict_review_id")
                conflict_hash = final_report.get("conflict_review_hash")
                if disposition == "ACCEPTED" and (
                    direction_id
                    != normalized_binding["accepted_direction_comparison_audit_id"]
                    or direction_hash
                    != normalized_binding["accepted_direction_comparison_audit_hash"]
                ):
                    raise ValueError(
                        "accepted KNOT Sector direction audit differs from usage ledger"
                    )
                summary_row = conn.execute(
                    "SELECT receipt_json FROM sector_model_usage_summaries "
                    "WHERE capability_id = ?",
                    (capability["capability_id"],),
                ).fetchone()
                if summary_row is None:
                    raise ValueError("KNOT Sector signed model usage summary is unavailable")
                usage_summary = self._verify_sector_model_usage_summary_with_conn(
                    conn, json.loads(summary_row["receipt_json"])
                )
                if (
                    usage_summary["budget_contract_ref"] != budget_ref
                    or usage_summary["model_subcall_count"] != model_subcall_count
                    or usage_summary["input_tokens"] != input_tokens
                    or usage_summary["output_tokens"] != output_tokens
                    or usage_summary["conflict_review_triggered"]
                    != conflict_review_triggered
                ):
                    raise ValueError("KNOT Sector signed usage summary differs from ledger")
                if disposition == "ACCEPTED" and (
                    usage_summary["model_path_disposition"] != "COMPLETED"
                    or usage_summary["last_attempted_stage"] != "COMPLETED"
                ):
                    raise ValueError("accepted KNOT Sector usage summary is incomplete")
                if disposition == "AGENT_FAILURE":
                    last_attempted_stage = usage_summary["last_attempted_stage"]
                runtime_audit_body = {
                    "schema_version": "sector_runtime_inference_cost_audit_v3",
                    "evidence_source": "SIGNED_SERVER_MODEL_USAGE_SUMMARY",
                    "sector_agent_id": normalized_binding["agent_id"],
                    "snapshot_bundle_hash": normalized_binding[
                        "snapshot_bundle_hash"
                    ],
                    "usage_summary_receipt_id": usage_summary[
                        "usage_summary_receipt_id"
                    ],
                    "usage_summary_receipt_hash": usage_summary[
                        "usage_summary_receipt_hash"
                    ],
                    "usage_summary_receipt": usage_summary,
                    "model_subcall_count": model_subcall_count,
                    "last_attempted_stage": last_attempted_stage,
                    "conflict_review_triggered": conflict_review_triggered,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "disposition": (
                        "SUCCESS" if disposition == "ACCEPTED" else "AGENT_FAILURE"
                    ),
                }
                runtime_audit_hash = _sha256(runtime_audit_body)
                runtime_audit_id = (
                    "sector-inference-cost:"
                    + runtime_audit_hash.removeprefix("sha256:")
                )
                if disposition == "ACCEPTED" and (
                    runtime_audit_id
                    != normalized_binding["accepted_runtime_inference_cost_audit_id"]
                    or runtime_audit_hash
                    != normalized_binding["accepted_runtime_inference_cost_audit_hash"]
                ):
                    raise ValueError(
                        "accepted KNOT Sector cost audit differs from usage ledger"
                    )
                measured_at = (
                    events[-1]["recorded_at"]
                    if events
                    else pair_receipt["verified_at"]
                )
                ledger_id = f"sector-usage-ledger:{uuid.uuid4().hex}"
                ledger_without_hash = {
                    "schema_version": "server_owned_model_usage_ledger_v1",
                    "usage_ledger_record_id": ledger_id,
                    "sector_usage_binding_hash": supplied_binding_hash,
                    "pair_root_reservation_id": normalized_binding[
                        "pair_root_reservation_id"
                    ],
                    "capability_id": capability["capability_id"],
                    "usage_event_refs": [
                        {
                            "usage_event_id": event["usage_event_id"],
                            "usage_event_hash": event["usage_event_hash"],
                        }
                        for event in events
                    ],
                    "model_subcall_count": model_subcall_count,
                    "last_attempted_stage": last_attempted_stage,
                    "conflict_review_triggered": conflict_review_triggered,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "budget_decision": {
                        "disposition": (
                            "STAGE_REJECT"
                            if budget_violations
                            else "WITHIN_BUDGET"
                        ),
                        "violation_codes": list(budget_violations),
                    },
                    "runtime_inference_cost_audit_id": runtime_audit_id,
                    "runtime_inference_cost_audit_hash": runtime_audit_hash,
                    "runtime_inference_cost_audit": runtime_audit_body,
                    "measured_at": measured_at,
                    "verified_at": verified_at.isoformat(),
                }
                ledger_hash = _sha256(ledger_without_hash)
                ledger = {
                    **ledger_without_hash,
                    "usage_ledger_record_hash": ledger_hash,
                }
                receipt_id = f"sector-usage-receipt:{uuid.uuid4().hex}"
                unsigned_body = {
                    "schema_version": KNOT_SECTOR_USAGE_RECEIPT_VERSION,
                    "usage_receipt_id": receipt_id,
                    "pair_root_reservation_id": normalized_binding[
                        "pair_root_reservation_id"
                    ],
                    "pair_root_receipt_hash": pair_receipt[
                        "pair_root_receipt_hash"
                    ],
                    "knot_pair_id": normalized_binding["knot_pair_id"],
                    "pair_side": normalized_binding["pair_side"],
                    "capability_id": capability["capability_id"],
                    "capability_manifest_hash": capability[
                        "capability_manifest_hash"
                    ],
                    "graph_run_id": capability["graph_run_id"],
                    "run_slot_id": capability["run_slot_id"],
                    "run_id": capability["run_id"],
                    "node_id": capability["node_id"],
                    "agent_id": capability["agent_id"],
                    "stage": capability["stage"],
                    "as_of": capability["as_of"],
                    "budget_contract_id": normalized_binding[
                        "budget_contract_id"
                    ],
                    "budget_contract_version": normalized_binding[
                        "budget_contract_version"
                    ],
                    "budget_contract_hash": normalized_binding[
                        "budget_contract_hash"
                    ],
                    "budget_decision": {
                        "disposition": (
                            "STAGE_REJECT"
                            if budget_violations
                            else "WITHIN_BUDGET"
                        ),
                        "violation_codes": list(budget_violations),
                    },
                    "operational_opportunity_audit_id": normalized_binding[
                        "operational_opportunity_audit_id"
                    ],
                    "operational_opportunity_audit_hash": normalized_binding[
                        "operational_opportunity_audit_hash"
                    ],
                    "accepted_output_id": normalized_binding[
                        "accepted_output_id"
                    ],
                    "accepted_output_hash": normalized_binding[
                        "accepted_output_hash"
                    ],
                    "model_subcall_count": model_subcall_count,
                    "last_attempted_stage": last_attempted_stage,
                    "conflict_review_triggered": conflict_review_triggered,
                    "direction_comparison_audit_id": direction_id,
                    "direction_comparison_audit_hash": direction_hash,
                    "conflict_review_id": conflict_id,
                    "conflict_review_hash": conflict_hash,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "runtime_inference_cost_audit_id": runtime_audit_id,
                    "runtime_inference_cost_audit_hash": runtime_audit_hash,
                    **KNOT_SECTOR_USAGE_INSTRUMENTATION_CONTRACT,
                    "instrumentation_contract_hash": (
                        KNOT_SECTOR_USAGE_INSTRUMENTATION_CONTRACT_HASH
                    ),
                    "usage_ledger_record_id": ledger_id,
                    "usage_ledger_record_hash": ledger_hash,
                    "measured_at": measured_at,
                    "verified_at": verified_at.isoformat(),
                    "receipt_signing_key_id": self.signing_key_id,
                }
                receipt_hash = _sha256(unsigned_body)
                signed_body = {**unsigned_body, "usage_receipt_hash": receipt_hash}
                receipt = {
                    **signed_body,
                    "receipt_signature": self._sign_domain(
                        "knot-sector-inference-usage-receipt-v2\0",
                        signed_body,
                    ),
                }
                conn.execute(
                    "INSERT INTO sector_inference_usage_receipts "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        receipt_id,
                        normalized_binding["pair_root_reservation_id"],
                        capability["capability_id"],
                        _canonical_json(ledger),
                        ledger_hash,
                        _canonical_json(receipt),
                        receipt_hash,
                        receipt["receipt_signature"],
                        verified_at.isoformat(),
                    ),
                )
                conn.execute("COMMIT")
                return receipt
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise ValueError("KNOT Sector usage receipt collision") from exc
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def verify_knot_sector_inference_usage_receipt(
        self, receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Dereference and revalidate one server-owned Sector usage receipt."""
        self._require_durable_knot_key()
        with self._connect() as conn:
            return self._verify_knot_sector_usage_receipt_with_conn(conn, receipt)

    def mint_knot_strict_output_validation_receipt(
        self,
        *,
        knot_pair_id: str,
        pair_side: str,
        accepted_output_kind: str,
        accepted_output_record: Mapping[str, Any],
        verified_claim_graph: Mapping[str, Any],
        schema_binding: Mapping[str, Any],
        schema_json: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Strict-parse and sign one accepted KNOT side output."""
        self._require_durable_knot_key()
        if pair_side not in {"CHAMPION", "CANDIDATE"}:
            raise ValueError("KNOT pair_side must be CHAMPION or CANDIDATE")
        if set(schema_binding) != {
            "accepted_output_kind",
            "schema_phase",
            "schema_id",
            "schema_hash",
            "immutable_phase_instruction_hash",
            "structured_output_schema_binding_set_hash",
        }:
            raise ValueError("KNOT schema binding fields mismatch")
        if schema_binding.get("accepted_output_kind") != accepted_output_kind:
            raise ValueError("KNOT accepted output kind/schema binding mismatch")
        for field in ("schema_id", "schema_phase"):
            _required_string(schema_binding, field)
        for field in (
            "schema_hash",
            "immutable_phase_instruction_hash",
            "structured_output_schema_binding_set_hash",
        ):
            if not _is_sha256(schema_binding.get(field)):
                raise ValueError(f"KNOT {field} must be sha256")
        if _sha256(schema_json) != schema_binding["schema_hash"]:
            raise ValueError("KNOT supplied schema does not match the immutable binding")
        try:
            Draft202012Validator.check_schema(dict(schema_json))
            Draft202012Validator(dict(schema_json)).validate(
                dict(accepted_output_record)
            )
        except (SchemaError, ValidationError) as exc:
            raise ValueError(f"KNOT strict output schema validation failed: {exc.message}") from exc

        validated_at = self.clock().astimezone(timezone.utc)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                binding_row = conn.execute(
                    "SELECT pair_root_reservation_id FROM private_pair_bindings "
                    "WHERE knot_pair_id = ?",
                    (knot_pair_id,),
                ).fetchone()
                if binding_row is None:
                    raise ValueError("unknown public binding for KNOT pair")
                reservation_id = binding_row["pair_root_reservation_id"]
                pair_row = conn.execute(
                    "SELECT receipt_json FROM verified_pair_root_receipts "
                    "WHERE pair_root_reservation_id = ?",
                    (reservation_id,),
                ).fetchone()
                if pair_row is None:
                    raise ValueError("unknown KNOT pair-root reservation")
                pair_receipt = self._verify_knot_pair_root_receipt_with_conn(
                    conn,
                    json.loads(pair_row["receipt_json"]),
                    require_active_capabilities=False,
                )
                capability = pair_receipt["capabilities"][pair_side]
                capability_id = capability["capability_id"]
                self._validate_knot_capability_completion(
                    conn,
                    capability=capability,
                    allowed_tools=pair_receipt["allowed_tools"],
                    validated_at=validated_at,
                )
                _validate_knot_claim_graph(
                    verified_claim_graph,
                    accepted_output_record=accepted_output_record,
                    accepted_output_kind=accepted_output_kind,
                    graph_run_id=capability["graph_run_id"],
                    snapshot_bundle_hash=pair_receipt["snapshot_bundle_hash"],
                    allowed_tools=pair_receipt["allowed_tools"],
                )
                output_hash = _sha256(accepted_output_record)
                graph_hash = _sha256(verified_claim_graph)
                existing = conn.execute(
                    "SELECT * FROM strict_output_validation_receipts "
                    "WHERE pair_root_reservation_id = ? AND capability_id = ? "
                    "AND accepted_output_kind = ?",
                    (reservation_id, capability_id, accepted_output_kind),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["accepted_output_record_hash"] != output_hash
                        or existing["verified_claim_graph_hash"] != graph_hash
                        or existing["schema_hash"] != schema_binding["schema_hash"]
                    ):
                        raise ValueError(
                            "KNOT strict validation retry changed immutable inputs"
                        )
                    receipt = json.loads(existing["receipt_json"])
                    self._verify_knot_strict_output_receipt_with_conn(conn, receipt)
                    conn.execute("COMMIT")
                    return receipt

                validation_id = f"knot-strict-validation:{uuid.uuid4().hex}"
                ledger_id = f"knot-validator-ledger:{uuid.uuid4().hex}"
                validator_record_without_hash = {
                    "validator_ledger_record_id": ledger_id,
                    **KNOT_STRICT_VALIDATOR_CONTRACT,
                    "validator_contract_hash": KNOT_STRICT_VALIDATOR_CONTRACT_HASH,
                    "pair_root_reservation_id": reservation_id,
                    "capability_id": capability_id,
                    "accepted_output_kind": accepted_output_kind,
                    "schema_binding": dict(schema_binding),
                    "accepted_output_record_hash": output_hash,
                    "verified_claim_graph_hash": graph_hash,
                    "validation_status": "ACCEPTED",
                    "validated_at": validated_at.isoformat(),
                }
                ledger_hash = _sha256(validator_record_without_hash)
                validator_record = {
                    **validator_record_without_hash,
                    "validator_ledger_record_hash": ledger_hash,
                }
                unsigned_body = {
                    "schema_version": KNOT_STRICT_OUTPUT_RECEIPT_VERSION,
                    "strict_validation_receipt_id": validation_id,
                    **KNOT_STRICT_VALIDATOR_CONTRACT,
                    "validator_contract_hash": KNOT_STRICT_VALIDATOR_CONTRACT_HASH,
                    "validator_ledger_record_id": ledger_id,
                    "validator_ledger_record_hash": ledger_hash,
                    "pair_root_reservation_id": reservation_id,
                    "pair_root_receipt_hash": pair_receipt[
                        "pair_root_receipt_hash"
                    ],
                    "capability_id": capability_id,
                    "capability_manifest_hash": capability[
                        "capability_manifest_hash"
                    ],
                    "graph_run_id": capability["graph_run_id"],
                    "run_slot_id": capability["run_slot_id"],
                    "run_id": capability["run_id"],
                    "node_id": capability["node_id"],
                    "agent_id": capability["agent_id"],
                    "stage": capability["stage"],
                    "as_of": capability["as_of"],
                    "accepted_output_kind": accepted_output_kind,
                    "schema_phase": schema_binding["schema_phase"],
                    "schema_id": schema_binding["schema_id"],
                    "schema_hash": schema_binding["schema_hash"],
                    "immutable_phase_instruction_hash": schema_binding[
                        "immutable_phase_instruction_hash"
                    ],
                    "structured_output_schema_binding_set_hash": schema_binding[
                        "structured_output_schema_binding_set_hash"
                    ],
                    "accepted_output_record_hash": output_hash,
                    "verified_claim_graph_hash": graph_hash,
                    "validation_status": "ACCEPTED",
                    "validated_at": validated_at.isoformat(),
                    "receipt_signing_key_id": self.signing_key_id,
                }
                receipt_hash = _sha256(unsigned_body)
                signed_body = {
                    **unsigned_body,
                    "strict_validation_receipt_hash": receipt_hash,
                }
                receipt = {
                    **signed_body,
                    "receipt_signature": self._sign_domain(
                        "knot-strict-output-receipt-v2\0", signed_body
                    ),
                }
                conn.execute(
                    "INSERT INTO strict_output_validation_receipts "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        validation_id,
                        reservation_id,
                        capability_id,
                        accepted_output_kind,
                        output_hash,
                        graph_hash,
                        schema_binding["schema_hash"],
                        _canonical_json(validator_record),
                        ledger_hash,
                        _canonical_json(receipt),
                        receipt_hash,
                        receipt["receipt_signature"],
                        validated_at.isoformat(),
                    ),
                )
                conn.execute("COMMIT")
                return receipt
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise ValueError("KNOT strict validation receipt collision") from exc
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def resolve_knot_pair_side_capability(
        self, *, knot_pair_id: str, pair_side: str
    ) -> dict[str, Any]:
        if pair_side not in {"CHAMPION", "CANDIDATE"}:
            raise ValueError("KNOT pair_side must be CHAMPION or CANDIDATE")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT r.receipt_json FROM private_pair_bindings b "
                "JOIN verified_pair_root_receipts r USING(pair_root_reservation_id) "
                "WHERE b.knot_pair_id = ?",
                (knot_pair_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown public binding for KNOT pair")
            receipt = self._verify_knot_pair_root_receipt_with_conn(
                conn,
                json.loads(row["receipt_json"]),
                require_active_capabilities=False,
            )
            return dict(receipt["capabilities"][pair_side])

    def verify_knot_strict_output_validation_receipt(
        self, receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        self._require_durable_knot_key()
        with self._connect() as conn:
            return self._verify_knot_strict_output_receipt_with_conn(conn, receipt)

    def _require_durable_knot_key(self) -> None:
        if not self.signing_key_is_durable:
            raise ValueError(
                "KNOT receipts require MOSAIC_AGENT_CAPABILITY_SIGNING_KEY"
            )

    def _validate_knot_pair_capabilities(
        self,
        conn: sqlite3.Connection,
        manifests: Mapping[str, Mapping[str, Any]],
        rows: Mapping[str, sqlite3.Row],
        *,
        require_unused: bool = True,
    ) -> None:
        champion = manifests["CHAMPION"]
        candidate = manifests["CANDIDATE"]
        shared_fields = (
            "graph_run_id",
            "agent_id",
            "stage",
            "as_of",
            "candidate_scope_hash",
            "snapshot_bundle_id",
            "snapshot_bundle_hash",
            "allowed_tools",
        )
        for field in shared_fields:
            if champion.get(field) != candidate.get(field):
                raise ValueError(f"KNOT pair capabilities have different {field}")
        distinct_fields = (
            "capability_id",
            "run_slot_id",
            "run_id",
            "node_id",
            "nonce",
        )
        for field in distinct_fields:
            if champion.get(field) == candidate.get(field):
                raise ValueError(f"KNOT pair capabilities reused {field}")
        if rows["CHAMPION"]["signature"] == rows["CANDIDATE"]["signature"]:
            raise ValueError("KNOT pair capabilities reused a signature")
        for side, manifest in manifests.items():
            used = conn.execute(
                "SELECT 1 FROM capability_tool_uses WHERE capability_id = ? LIMIT 1",
                (manifest["capability_id"],),
            ).fetchone()
            if require_unused and used is not None:
                raise ValueError(f"{side} KNOT capability was used before pair freeze")

    def _knot_capability_projection(
        self, manifest: Mapping[str, Any], row: sqlite3.Row
    ) -> dict[str, Any]:
        ledger_record = {
            "capability_id": row["capability_id"],
            "snapshot_bundle_id": row["snapshot_bundle_id"],
            "manifest_json": row["manifest_json"],
            "signing_key_id": row["signing_key_id"],
            "signature": row["signature"],
            "created_at": row["created_at"],
        }
        return {
            "capability_contract_version": manifest["capability_contract_version"],
            "capability_id": manifest["capability_id"],
            "capability_manifest_hash": _sha256(manifest),
            "graph_run_id": manifest["graph_run_id"],
            "run_slot_id": manifest["run_slot_id"],
            "run_id": manifest["run_id"],
            "node_id": manifest["node_id"],
            "agent_id": manifest["agent_id"],
            "stage": manifest["stage"],
            "as_of": manifest["as_of"],
            "candidate_scope_hash": manifest.get("candidate_scope_hash"),
            "snapshot_bundle_id": manifest["snapshot_bundle_id"],
            "snapshot_bundle_hash": manifest["snapshot_bundle_hash"],
            "allowed_tools": list(manifest["allowed_tools"]),
            "issued_at": manifest["issued_at"],
            "expires_at": manifest["expires_at"],
            "nonce": manifest["nonce"],
            "capability_signing_key_id": row["signing_key_id"],
            "capability_signature_hash": _sha256(
                {
                    "signing_key_id": row["signing_key_id"],
                    "signature": row["signature"],
                }
            ),
            "ledger_record_hash": _sha256(ledger_record),
        }

    def _verify_knot_pair_root_receipt_with_conn(
        self,
        conn: sqlite3.Connection,
        value: Mapping[str, Any],
        *,
        require_active_capabilities: bool = True,
    ) -> dict[str, Any]:
        receipt = dict(value)
        expected_keys = {
            "schema_version",
            "pair_root_reservation_id",
            "pair_binding",
            "pair_binding_hash",
            "agent_id",
            "stage",
            "as_of",
            "snapshot_bundle_contract_version",
            "snapshot_bundle_id",
            "snapshot_bundle_hash",
            "runtime_input_hash",
            "candidate_scope_hash",
            "allowed_tools",
            "tool_payload_hashes",
            "capabilities",
            "verified_at",
            "reservation_status",
            "receipt_signing_key_id",
            "pair_root_receipt_hash",
            "receipt_signature",
        }
        if set(receipt) != expected_keys:
            raise ValueError("KNOT pair-root receipt fields mismatch")
        if receipt.get("schema_version") != KNOT_PAIR_ROOT_RECEIPT_VERSION:
            raise ValueError("KNOT pair-root receipt version mismatch")
        if (
            receipt.get("reservation_status") != "ACTIVE"
            or receipt.get("receipt_signing_key_id") != self.signing_key_id
        ):
            raise ValueError("KNOT pair-root receipt is not active")
        signature = _required_string(receipt, "receipt_signature")
        supplied_hash = receipt.get("pair_root_receipt_hash")
        if not _is_sha256(supplied_hash):
            raise ValueError("KNOT pair-root receipt hash is invalid")
        unsigned_body = {
            key: item
            for key, item in receipt.items()
            if key not in {"pair_root_receipt_hash", "receipt_signature"}
        }
        if supplied_hash != _sha256(unsigned_body):
            raise ValueError("KNOT pair-root receipt hash mismatch")
        expected_signature = self._sign_domain(
            "knot-pair-root-receipt-v2\0",
            {**unsigned_body, "pair_root_receipt_hash": supplied_hash},
        )
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("KNOT pair-root receipt signature mismatch")
        reservation_id = _required_string(receipt, "pair_root_reservation_id")
        stored = conn.execute(
            "SELECT * FROM verified_pair_root_receipts "
            "WHERE pair_root_reservation_id = ?",
            (reservation_id,),
        ).fetchone()
        if stored is None:
            raise ValueError("unknown KNOT pair-root receipt")
        if (
            stored["receipt_json"] != _canonical_json(receipt)
            or stored["pair_root_receipt_hash"] != supplied_hash
            or stored["receipt_signature"] != signature
        ):
            raise ValueError("KNOT pair-root receipt differs from its ledger record")
        binding = receipt.get("pair_binding")
        if not isinstance(binding, dict) or set(binding) != {
            "knot_research_track_id",
            "knot_pair_assignment_id",
            "research_slot_id",
            "evaluation_opportunity_set_id",
        }:
            raise ValueError("KNOT pair-root binding fields mismatch")
        for field in binding:
            _required_string(binding, field)
        if receipt.get("pair_binding_hash") != _sha256(binding):
            raise ValueError("KNOT pair-root binding hash mismatch")
        verified_at = _aware_timestamp(receipt.get("verified_at"), "verified_at")
        capabilities = receipt.get("capabilities")
        if not isinstance(capabilities, dict) or set(capabilities) != {
            "CHAMPION",
            "CANDIDATE",
        }:
            raise ValueError("KNOT pair-root capabilities are incomplete")
        manifests: dict[str, dict[str, Any]] = {}
        rows: dict[str, sqlite3.Row] = {}
        reservation_rows = conn.execute(
            "SELECT capability_id, pair_side FROM capability_reservations "
            "WHERE pair_root_reservation_id = ? ORDER BY pair_side",
            (reservation_id,),
        ).fetchall()
        if len(reservation_rows) != 2:
            raise ValueError("KNOT pair-root capability reservations are incomplete")
        reserved = {row["pair_side"]: row["capability_id"] for row in reservation_rows}
        for side in ("CHAMPION", "CANDIDATE"):
            projection = capabilities.get(side)
            if not isinstance(projection, dict):
                raise ValueError(f"KNOT {side} capability receipt is invalid")
            capability_id = _required_string(projection, "capability_id")
            if reserved.get(side) != capability_id:
                raise ValueError("KNOT capability reservation side mismatch")
            capability_row = conn.execute(
                "SELECT c.*, b.bundle_json, b.payloads_json FROM capabilities c "
                "JOIN snapshot_bundles b USING(snapshot_bundle_id) "
                "WHERE c.capability_id = ?",
                (capability_id,),
            ).fetchone()
            if capability_row is None:
                raise ValueError("KNOT reserved capability is unavailable")
            manifest = json.loads(capability_row["manifest_json"])
            envelope = {
                "manifest": manifest,
                "signing_key_id": capability_row["signing_key_id"],
                "signature": capability_row["signature"],
            }
            verified_manifest, verified_row = self._verify(
                envelope,
                conn=conn,
                allow_terminated=not require_active_capabilities,
                verified_at=verified_at,
            )
            expected_projection = self._knot_capability_projection(
                verified_manifest, verified_row
            )
            if projection != expected_projection:
                raise ValueError("KNOT capability projection differs from the ledger")
            manifests[side] = verified_manifest
            rows[side] = verified_row
        self._validate_knot_pair_capabilities(
            conn,
            manifests,
            rows,
            require_unused=require_active_capabilities,
        )
        bundle = json.loads(rows["CHAMPION"]["bundle_json"])
        root_expected = {
            "agent_id": manifests["CHAMPION"]["agent_id"],
            "stage": manifests["CHAMPION"]["stage"],
            "as_of": manifests["CHAMPION"]["as_of"],
            "snapshot_bundle_contract_version": bundle[
                "snapshot_bundle_contract_version"
            ],
            "snapshot_bundle_id": bundle["snapshot_bundle_id"],
            "snapshot_bundle_hash": bundle["snapshot_bundle_hash"],
            "runtime_input_hash": bundle["runtime_input_hash"],
            "candidate_scope_hash": bundle.get("candidate_scope_hash"),
            "allowed_tools": list(manifests["CHAMPION"]["allowed_tools"]),
            "tool_payload_hashes": dict(bundle["tool_payload_hashes"]),
        }
        for field, expected in root_expected.items():
            if receipt.get(field) != expected:
                raise ValueError(f"KNOT pair-root receipt {field} mismatch")
        return receipt

    def _verify_knot_regime_receipt_with_conn(
        self, conn: sqlite3.Connection, value: Mapping[str, Any]
    ) -> dict[str, Any]:
        receipt = dict(value)
        expected_keys = {
            "schema_version",
            "regime_classification_receipt_id",
            "knot_research_track_id",
            "research_slot_id",
            "scheduled_sample_id",
            "evaluation_regime",
            "source_snapshot_id",
            "source_snapshot_hash",
            "classifier_contract_id",
            "classifier_contract_version",
            "classifier_contract_hash",
            "as_of",
            "classified_at",
            "classifier_ledger_record_id",
            "classifier_ledger_record_hash",
            "receipt_signing_key_id",
            "regime_classification_receipt_hash",
            "receipt_signature",
        }
        if set(receipt) != expected_keys:
            raise ValueError("KNOT regime receipt fields mismatch")
        if (
            receipt.get("schema_version") != KNOT_REGIME_RECEIPT_VERSION
            or receipt.get("evaluation_regime") not in {"normal", "stress"}
            or receipt.get("receipt_signing_key_id") != self.signing_key_id
        ):
            raise ValueError("KNOT regime receipt contract mismatch")
        _required_string(receipt, "classifier_contract_id")
        _required_string(receipt, "classifier_contract_version")
        if not _is_sha256(receipt.get("classifier_contract_hash")):
            raise ValueError("KNOT regime receipt classifier hash is invalid")
        supplied_hash = receipt.get("regime_classification_receipt_hash")
        if not _is_sha256(supplied_hash):
            raise ValueError("KNOT regime receipt hash is invalid")
        unsigned_body = {
            key: item
            for key, item in receipt.items()
            if key
            not in {"regime_classification_receipt_hash", "receipt_signature"}
        }
        if supplied_hash != _sha256(unsigned_body):
            raise ValueError("KNOT regime receipt hash mismatch")
        expected_signature = self._sign_domain(
            "knot-regime-classification-receipt-v2\0",
            {
                **unsigned_body,
                "regime_classification_receipt_hash": supplied_hash,
            },
        )
        signature = _required_string(receipt, "receipt_signature")
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("KNOT regime receipt signature mismatch")
        receipt_id = _required_string(
            receipt, "regime_classification_receipt_id"
        )
        row = conn.execute(
            "SELECT * FROM regime_classification_receipts "
            "WHERE regime_classification_receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown KNOT regime receipt")
        if (
            row["receipt_json"] != _canonical_json(receipt)
            or row["regime_classification_receipt_hash"] != supplied_hash
            or row["receipt_signature"] != signature
            or row["source_snapshot_hash"] != receipt["source_snapshot_hash"]
        ):
            raise ValueError("KNOT regime receipt differs from its ledger record")
        ledger_record = json.loads(row["classifier_ledger_record_json"])
        ledger_hash = ledger_record.pop("classifier_ledger_record_hash", None)
        if (
            ledger_hash != _sha256(ledger_record)
            or ledger_hash != receipt.get("classifier_ledger_record_hash")
            or row["classifier_ledger_record_hash"] != ledger_hash
            or ledger_record.get("classifier_ledger_record_id")
            != receipt.get("classifier_ledger_record_id")
            or ledger_record.get("evaluation_regime")
            != receipt.get("evaluation_regime")
            or ledger_record.get("source_snapshot_hash")
            != receipt.get("source_snapshot_hash")
            or ledger_record.get("classifier_contract_id")
            != receipt.get("classifier_contract_id")
            or ledger_record.get("classifier_contract_version")
            != receipt.get("classifier_contract_version")
            or ledger_record.get("classifier_contract_hash")
            != receipt.get("classifier_contract_hash")
        ):
            raise ValueError("KNOT regime classifier ledger record mismatch")
        binding = ledger_record.get("assignment_binding")
        if not isinstance(binding, dict):
            raise ValueError("KNOT regime assignment binding is invalid")
        expected_binding = {
            "knot_research_track_id": receipt["knot_research_track_id"],
            "research_slot_id": receipt["research_slot_id"],
            "scheduled_sample_id": receipt["scheduled_sample_id"],
            "as_of": receipt["as_of"][:10],
        }
        if (
            binding != expected_binding
            or ledger_record.get("assignment_binding_hash") != _sha256(binding)
            or row["assignment_binding_hash"] != _sha256(binding)
        ):
            raise ValueError("KNOT regime assignment binding mismatch")
        if _aware_timestamp(receipt["as_of"], "regime.as_of") > _aware_timestamp(
            receipt["classified_at"], "regime.classified_at"
        ):
            raise ValueError("KNOT regime receipt predates its source")
        return receipt

    def _validate_knot_capability_completion(
        self,
        conn: sqlite3.Connection,
        *,
        capability: Mapping[str, Any],
        allowed_tools: Sequence[str],
        validated_at: datetime,
    ) -> None:
        capability_id = _required_string(capability, "capability_id")
        issued_at = _aware_timestamp(capability.get("issued_at"), "issued_at")
        expires_at = _aware_timestamp(capability.get("expires_at"), "expires_at")
        if not issued_at <= validated_at < expires_at:
            raise ValueError("KNOT strict validation is outside capability lifetime")
        termination = conn.execute(
            "SELECT event_at FROM capability_events "
            "WHERE capability_id = ? AND event_type = 'TERMINATED'",
            (capability_id,),
        ).fetchone()
        if termination is None:
            raise ValueError("KNOT strict validation requires a terminated capability")
        terminated_at = _aware_timestamp(termination["event_at"], "terminated_at")
        uses = conn.execute(
            "SELECT tool_id, used_at FROM capability_tool_uses "
            "WHERE capability_id = ? ORDER BY tool_id",
            (capability_id,),
        ).fetchall()
        if [row["tool_id"] for row in uses] != sorted(allowed_tools):
            raise ValueError("KNOT accepted output did not use the exact tool whitelist")
        pair_verified = conn.execute(
            "SELECT r.receipt_json FROM verified_pair_root_receipts r "
            "JOIN capability_reservations c USING(pair_root_reservation_id) "
            "WHERE c.capability_id = ?",
            (capability_id,),
        ).fetchone()
        if pair_verified is None:
            raise ValueError("KNOT capability has no pair-root reservation")
        root_verified_at = _aware_timestamp(
            json.loads(pair_verified["receipt_json"])["verified_at"],
            "pair_root.verified_at",
        )
        use_times = [
            _aware_timestamp(row["used_at"], f"tool_use.{row['tool_id']}")
            for row in uses
        ]
        if (
            terminated_at > validated_at
            or any(not root_verified_at <= used_at <= terminated_at for used_at in use_times)
        ):
            raise ValueError("KNOT capability use/termination timeline is invalid")

    def _verify_knot_strict_output_receipt_with_conn(
        self, conn: sqlite3.Connection, value: Mapping[str, Any]
    ) -> dict[str, Any]:
        receipt = dict(value)
        expected_keys = {
            "schema_version",
            "strict_validation_receipt_id",
            "validator_contract_id",
            "validator_contract_version",
            "validator_contract_hash",
            "validator_ledger_record_id",
            "validator_ledger_record_hash",
            "pair_root_reservation_id",
            "pair_root_receipt_hash",
            "capability_id",
            "capability_manifest_hash",
            "graph_run_id",
            "run_slot_id",
            "run_id",
            "node_id",
            "agent_id",
            "stage",
            "as_of",
            "accepted_output_kind",
            "schema_phase",
            "schema_id",
            "schema_hash",
            "immutable_phase_instruction_hash",
            "structured_output_schema_binding_set_hash",
            "accepted_output_record_hash",
            "verified_claim_graph_hash",
            "validation_status",
            "validated_at",
            "receipt_signing_key_id",
            "strict_validation_receipt_hash",
            "receipt_signature",
        }
        if set(receipt) != expected_keys:
            raise ValueError("KNOT strict output receipt fields mismatch")
        if receipt.get("schema_version") != KNOT_STRICT_OUTPUT_RECEIPT_VERSION:
            raise ValueError("KNOT strict output receipt version mismatch")
        if (
            receipt.get("validation_status") != "ACCEPTED"
            or receipt.get("receipt_signing_key_id") != self.signing_key_id
            or receipt.get("validator_contract_id")
            != KNOT_STRICT_VALIDATOR_CONTRACT["validator_contract_id"]
            or receipt.get("validator_contract_version")
            != KNOT_STRICT_VALIDATOR_CONTRACT["validator_contract_version"]
            or receipt.get("validator_contract_hash")
            != KNOT_STRICT_VALIDATOR_CONTRACT_HASH
        ):
            raise ValueError("KNOT strict output receipt contract mismatch")
        supplied_hash = receipt.get("strict_validation_receipt_hash")
        if not _is_sha256(supplied_hash):
            raise ValueError("KNOT strict output receipt hash is invalid")
        unsigned_body = {
            key: item
            for key, item in receipt.items()
            if key not in {"strict_validation_receipt_hash", "receipt_signature"}
        }
        if supplied_hash != _sha256(unsigned_body):
            raise ValueError("KNOT strict output receipt hash mismatch")
        expected_signature = self._sign_domain(
            "knot-strict-output-receipt-v2\0",
            {**unsigned_body, "strict_validation_receipt_hash": supplied_hash},
        )
        signature = _required_string(receipt, "receipt_signature")
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("KNOT strict output receipt signature mismatch")
        receipt_id = _required_string(receipt, "strict_validation_receipt_id")
        row = conn.execute(
            "SELECT * FROM strict_output_validation_receipts "
            "WHERE strict_validation_receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown KNOT strict output receipt")
        if (
            row["receipt_json"] != _canonical_json(receipt)
            or row["strict_validation_receipt_hash"] != supplied_hash
            or row["receipt_signature"] != signature
        ):
            raise ValueError("KNOT strict output receipt differs from its ledger record")
        validator_record = json.loads(row["validator_ledger_record_json"])
        ledger_hash = validator_record.pop("validator_ledger_record_hash", None)
        if (
            ledger_hash != _sha256(validator_record)
            or ledger_hash != receipt.get("validator_ledger_record_hash")
            or row["validator_ledger_record_hash"] != ledger_hash
            or validator_record.get("validator_ledger_record_id")
            != receipt.get("validator_ledger_record_id")
        ):
            raise ValueError("KNOT strict validator ledger record mismatch")
        pair_row = conn.execute(
            "SELECT receipt_json FROM verified_pair_root_receipts "
            "WHERE pair_root_reservation_id = ?",
            (receipt["pair_root_reservation_id"],),
        ).fetchone()
        if pair_row is None:
            raise ValueError("KNOT strict receipt pair root is unavailable")
        pair_receipt = self._verify_knot_pair_root_receipt_with_conn(
            conn,
            json.loads(pair_row["receipt_json"]),
            require_active_capabilities=False,
        )
        capabilities = pair_receipt["capabilities"]
        matching = [
            capability
            for capability in capabilities.values()
            if capability["capability_id"] == receipt["capability_id"]
        ]
        if len(matching) != 1:
            raise ValueError("KNOT strict receipt capability is not pair-bound")
        capability = matching[0]
        expected_lineage = {
            "pair_root_receipt_hash": pair_receipt["pair_root_receipt_hash"],
            "capability_manifest_hash": capability["capability_manifest_hash"],
            "graph_run_id": capability["graph_run_id"],
            "run_slot_id": capability["run_slot_id"],
            "run_id": capability["run_id"],
            "node_id": capability["node_id"],
            "agent_id": capability["agent_id"],
            "stage": capability["stage"],
            "as_of": capability["as_of"],
            "accepted_output_record_hash": row["accepted_output_record_hash"],
            "verified_claim_graph_hash": row["verified_claim_graph_hash"],
            "schema_hash": row["schema_hash"],
        }
        for field, expected in expected_lineage.items():
            if receipt.get(field) != expected:
                raise ValueError(f"KNOT strict output receipt {field} mismatch")
        return receipt

    def _verify_sector_model_usage_summary_with_conn(
        self, conn: sqlite3.Connection, value: Mapping[str, Any]
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
            "pair_root_reservation_id",
            "pair_side",
            "budget_contract_ref",
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
            "instrumentation_contract_hash",
            "source_contract_version",
            "measurement_rule",
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
                for field, expected in KNOT_SECTOR_USAGE_INSTRUMENTATION_CONTRACT.items()
            )
            or receipt.get("instrumentation_contract_hash")
            != KNOT_SECTOR_USAGE_INSTRUMENTATION_CONTRACT_HASH
        ):
            raise ValueError("Sector model usage summary contract mismatch")
        budget_ref = receipt.get("budget_contract_ref")
        if budget_ref is not None and (
            not isinstance(budget_ref, dict)
            or set(budget_ref)
            != {
                "budget_contract_id",
                "budget_contract_version",
                "budget_contract_hash",
            }
            or not _is_sha256(budget_ref.get("budget_contract_hash"))
        ):
            raise ValueError("Sector model usage summary budget ref is invalid")
        if isinstance(budget_ref, dict):
            _required_string(budget_ref, "budget_contract_id")
            _required_string(budget_ref, "budget_contract_version")
        supplied_hash = receipt.get("usage_summary_receipt_hash")
        if not _is_sha256(supplied_hash):
            raise ValueError("Sector model usage summary hash is invalid")
        unsigned_body = {
            key: item
            for key, item in receipt.items()
            if key not in {"usage_summary_receipt_hash", "receipt_signature"}
        }
        if supplied_hash != _sha256(unsigned_body):
            raise ValueError("Sector model usage summary hash mismatch")
        signature = _required_string(receipt, "receipt_signature")
        if not hmac.compare_digest(
            signature,
            self._sign_domain(
                "sector-model-usage-summary-receipt-v1\0",
                {**unsigned_body, "usage_summary_receipt_hash": supplied_hash},
            ),
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
        if (receipt["pair_root_reservation_id"] is None) != (
            receipt["pair_side"] is None
        ):
            raise ValueError("Sector model usage summary pair reservation is unpaired")
        if receipt["pair_side"] not in {None, "CHAMPION", "CANDIDATE"}:
            raise ValueError("Sector model usage summary pair side is invalid")

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
            or row["usage_summary_receipt_hash"] != supplied_hash
            or row["receipt_signature"] != signature
        ):
            raise ValueError("Sector model usage summary differs from its ledger")
        ledger = json.loads(row["usage_ledger_record_json"])
        ledger_hash = ledger.pop("usage_ledger_record_hash", None)
        if (
            ledger_hash != _sha256(ledger)
            or ledger_hash != receipt["usage_ledger_record_hash"]
            or row["usage_ledger_record_hash"] != ledger_hash
            or ledger.get("usage_ledger_record_id")
            != receipt["usage_ledger_record_id"]
        ):
            raise ValueError("Sector model usage summary ledger mismatch")

        capability_row = conn.execute(
            "SELECT manifest_json, signing_key_id, signature FROM capabilities "
            "WHERE capability_id = ?",
            (receipt["capability_id"],),
        ).fetchone()
        if capability_row is None:
            raise ValueError("Sector model usage summary capability is unavailable")
        manifest = json.loads(capability_row["manifest_json"])
        finalized_at = _aware_timestamp(
            receipt["finalized_at"], "usage_summary.finalized_at"
        )
        self._verify(
            {
                "manifest": manifest,
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
        for field, expected in expected_lineage.items():
            if receipt.get(field) != expected:
                raise ValueError(f"Sector model usage summary {field} mismatch")
        if manifest["agent_id"] not in STANDARD_SECTOR_AGENTS:
            raise ValueError("model usage summary is not for standard Sector")
        uses = conn.execute(
            "SELECT tool_id FROM capability_tool_uses "
            "WHERE capability_id = ? ORDER BY tool_id",
            (receipt["capability_id"],),
        ).fetchall()
        if [item["tool_id"] for item in uses] != sorted(manifest["allowed_tools"]):
            raise ValueError("Sector model usage summary tool closure mismatch")
        reservation = conn.execute(
            "SELECT pair_root_reservation_id, pair_side FROM capability_reservations "
            "WHERE capability_id = ?",
            (receipt["capability_id"],),
        ).fetchone()
        expected_reservation_id = (
            reservation["pair_root_reservation_id"] if reservation is not None else None
        )
        expected_pair_side = reservation["pair_side"] if reservation is not None else None
        if (
            receipt["pair_root_reservation_id"] != expected_reservation_id
            or receipt["pair_side"] != expected_pair_side
        ):
            raise ValueError("Sector model usage summary pair reservation mismatch")
        expected_budget = (
            self._sector_budget_for_reservation(conn, expected_reservation_id)
            if expected_reservation_id is not None
            else None
        )
        expected_budget_ref = (
            _sector_inference_budget_ref(expected_budget)
            if expected_budget is not None
            else None
        )
        if budget_ref != expected_budget_ref:
            raise ValueError("Sector model usage summary budget binding mismatch")

        event_rows = conn.execute(
            "SELECT event_json FROM sector_model_usage_events "
            "WHERE capability_id = ? ORDER BY subcall_sequence",
            (receipt["capability_id"],),
        ).fetchall()
        events = [json.loads(item["event_json"]) for item in event_rows]
        expected_refs = [
            {
                "usage_event_id": event["usage_event_id"],
                "usage_event_hash": event["usage_event_hash"],
            }
            for event in events
        ]
        reports = [event["usage_report"] for event in events]
        stages = [report["attempted_stage"] for report in reports]
        budget_violations = (
            _sector_inference_budget_violations(reports, expected_budget)
            if expected_budget is not None
            else ()
        )
        ordinary_completed = bool(reports) and (
            reports[-1]["attempted_stage"] == "FINAL_SELECTION"
            and reports[-1]["attempt_status"] == "ACCEPTED"
        )
        exact_knot_path = stages in (
            ["DIRECTION_RESEARCH", "FINAL_SELECTION"],
            ["DIRECTION_RESEARCH", "CONFLICT_REVIEW", "FINAL_SELECTION"],
        ) and all(report["attempt_status"] == "ACCEPTED" for report in reports)
        completed = (
            ordinary_completed
            if expected_budget is None
            else exact_knot_path and not budget_violations
        )
        expected_last = "COMPLETED" if completed else (stages[-1] if stages else "PRE_MODEL")
        expected_conflict = "CONFLICT_REVIEW" in stages
        input_tokens = sum(report["input_tokens"] for report in reports)
        output_tokens = sum(report["output_tokens"] for report in reports)
        final_report = reports[-1] if completed else {}
        aggregate = {
            "model_subcall_count": len(events),
            "last_attempted_stage": expected_last,
            "conflict_review_triggered": expected_conflict,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model_path_disposition": "COMPLETED" if completed else "INCOMPLETE",
            "direction_comparison_audit_id": final_report.get(
                "direction_comparison_audit_id"
            ),
            "direction_comparison_audit_hash": final_report.get(
                "direction_comparison_audit_hash"
            ),
            "conflict_review_id": final_report.get("conflict_review_id"),
            "conflict_review_hash": final_report.get("conflict_review_hash"),
        }
        if ledger.get("usage_event_refs") != expected_refs:
            raise ValueError("Sector model usage summary event refs mismatch")
        if ledger.get("budget_contract_ref") != expected_budget_ref:
            raise ValueError("Sector model usage summary ledger budget mismatch")
        expected_budget_decision = (
            {
                "disposition": (
                    "STAGE_REJECT" if budget_violations else "WITHIN_BUDGET"
                ),
                "violation_codes": list(budget_violations),
            }
            if expected_budget is not None
            else None
        )
        if ledger.get("budget_decision") != expected_budget_decision:
            raise ValueError("Sector model usage summary ledger budget decision mismatch")
        for field, expected in aggregate.items():
            if receipt.get(field) != expected or ledger.get(field) != expected:
                # Finalized audit aliases are intentionally receipt-only.
                if field in {
                    "direction_comparison_audit_id",
                    "direction_comparison_audit_hash",
                    "conflict_review_id",
                    "conflict_review_hash",
                } and receipt.get(field) == expected:
                    continue
                raise ValueError(f"Sector model usage summary {field} mismatch")
        measured_at = _aware_timestamp(
            receipt["measured_at"], "usage_summary.measured_at"
        )
        if measured_at > finalized_at or ledger.get("measured_at") != receipt["measured_at"]:
            raise ValueError("Sector model usage summary timeline mismatch")
        if ledger.get("finalized_at") != receipt["finalized_at"]:
            raise ValueError("Sector model usage summary finalization mismatch")
        return receipt

    def _verify_knot_sector_usage_receipt_with_conn(
        self, conn: sqlite3.Connection, value: Mapping[str, Any]
    ) -> dict[str, Any]:
        receipt = dict(value)
        expected_keys = {
            "schema_version",
            "usage_receipt_id",
            "pair_root_reservation_id",
            "pair_root_receipt_hash",
            "knot_pair_id",
            "pair_side",
            "capability_id",
            "capability_manifest_hash",
            "graph_run_id",
            "run_slot_id",
            "run_id",
            "node_id",
            "agent_id",
            "stage",
            "as_of",
            "budget_contract_id",
            "budget_contract_version",
            "budget_contract_hash",
            "budget_decision",
            "operational_opportunity_audit_id",
            "operational_opportunity_audit_hash",
            "accepted_output_id",
            "accepted_output_hash",
            "model_subcall_count",
            "last_attempted_stage",
            "conflict_review_triggered",
            "direction_comparison_audit_id",
            "direction_comparison_audit_hash",
            "conflict_review_id",
            "conflict_review_hash",
            "input_tokens",
            "output_tokens",
            "runtime_inference_cost_audit_id",
            "runtime_inference_cost_audit_hash",
            "instrumentation_contract_id",
            "instrumentation_contract_version",
            "instrumentation_contract_hash",
            "source_contract_version",
            "measurement_rule",
            "usage_ledger_record_id",
            "usage_ledger_record_hash",
            "measured_at",
            "verified_at",
            "receipt_signing_key_id",
            "usage_receipt_hash",
            "receipt_signature",
        }
        if set(receipt) != expected_keys:
            raise ValueError("KNOT Sector usage receipt fields mismatch")
        if (
            receipt.get("schema_version") != KNOT_SECTOR_USAGE_RECEIPT_VERSION
            or receipt.get("receipt_signing_key_id") != self.signing_key_id
            or any(
                receipt.get(field) != expected
                for field, expected in KNOT_SECTOR_USAGE_INSTRUMENTATION_CONTRACT.items()
            )
            or receipt.get("instrumentation_contract_hash")
            != KNOT_SECTOR_USAGE_INSTRUMENTATION_CONTRACT_HASH
        ):
            raise ValueError("KNOT Sector usage receipt contract mismatch")
        supplied_hash = receipt.get("usage_receipt_hash")
        if not _is_sha256(supplied_hash):
            raise ValueError("KNOT Sector usage receipt hash is invalid")
        unsigned_body = {
            key: item
            for key, item in receipt.items()
            if key not in {"usage_receipt_hash", "receipt_signature"}
        }
        if supplied_hash != _sha256(unsigned_body):
            raise ValueError("KNOT Sector usage receipt hash mismatch")
        signature = _required_string(receipt, "receipt_signature")
        if not hmac.compare_digest(
            signature,
            self._sign_domain(
                "knot-sector-inference-usage-receipt-v2\0",
                {**unsigned_body, "usage_receipt_hash": supplied_hash},
            ),
        ):
            raise ValueError("KNOT Sector usage receipt signature mismatch")
        for field in (
            "budget_contract_hash",
            "operational_opportunity_audit_hash",
            "runtime_inference_cost_audit_hash",
            "usage_ledger_record_hash",
        ):
            if not _is_sha256(receipt.get(field)):
                raise ValueError(f"KNOT Sector usage receipt {field} is invalid")
        budget_decision = receipt.get("budget_decision")
        if (
            not isinstance(budget_decision, dict)
            or set(budget_decision) != {"disposition", "violation_codes"}
            or budget_decision.get("disposition")
            not in {"WITHIN_BUDGET", "STAGE_REJECT"}
            or not isinstance(budget_decision.get("violation_codes"), list)
            or any(
                not isinstance(code, str) or not code
                for code in budget_decision["violation_codes"]
            )
        ):
            raise ValueError("KNOT Sector usage receipt budget decision is invalid")
        for id_field, hash_field in (
            ("accepted_output_id", "accepted_output_hash"),
            ("direction_comparison_audit_id", "direction_comparison_audit_hash"),
            ("conflict_review_id", "conflict_review_hash"),
        ):
            if (receipt[id_field] is None) != (receipt[hash_field] is None):
                raise ValueError(f"KNOT Sector usage receipt {id_field} is unpaired")
            if receipt[hash_field] is not None and not _is_sha256(receipt[hash_field]):
                raise ValueError(f"KNOT Sector usage receipt {hash_field} is invalid")
        receipt_id = _required_string(receipt, "usage_receipt_id")
        row = conn.execute(
            "SELECT * FROM sector_inference_usage_receipts "
            "WHERE usage_receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown KNOT Sector usage receipt")
        if (
            row["receipt_json"] != _canonical_json(receipt)
            or row["usage_receipt_hash"] != supplied_hash
            or row["receipt_signature"] != signature
        ):
            raise ValueError("KNOT Sector usage receipt differs from its ledger")
        ledger = json.loads(row["usage_ledger_record_json"])
        ledger_hash = ledger.pop("usage_ledger_record_hash", None)
        if (
            ledger_hash != _sha256(ledger)
            or ledger_hash != receipt["usage_ledger_record_hash"]
            or row["usage_ledger_record_hash"] != ledger_hash
            or ledger.get("usage_ledger_record_id")
            != receipt["usage_ledger_record_id"]
        ):
            raise ValueError("KNOT Sector usage ledger record mismatch")
        runtime_audit = ledger.get("runtime_inference_cost_audit")
        if not isinstance(runtime_audit, dict):
            raise ValueError("KNOT Sector runtime cost audit is unavailable")
        budget_contract = self._sector_budget_for_reservation(
            conn, receipt["pair_root_reservation_id"]
        )
        budget_ref = _sector_inference_budget_ref(budget_contract)
        if any(
            receipt[field] != budget_ref[field]
            for field in (
                "budget_contract_id",
                "budget_contract_version",
                "budget_contract_hash",
            )
        ):
            raise ValueError("KNOT Sector usage receipt budget binding mismatch")
        runtime_hash = _sha256(runtime_audit)
        runtime_id = "sector-inference-cost:" + runtime_hash.removeprefix("sha256:")
        if (
            runtime_hash != receipt["runtime_inference_cost_audit_hash"]
            or runtime_id != receipt["runtime_inference_cost_audit_id"]
            or ledger.get("runtime_inference_cost_audit_hash") != runtime_hash
            or ledger.get("runtime_inference_cost_audit_id") != runtime_id
        ):
            raise ValueError("KNOT Sector runtime cost audit mismatch")
        event_refs = ledger.get("usage_event_refs")
        if not isinstance(event_refs, list):
            raise ValueError("KNOT Sector usage event refs are invalid")
        event_rows = conn.execute(
            "SELECT event_json FROM sector_model_usage_events "
            "WHERE capability_id = ? ORDER BY subcall_sequence",
            (receipt["capability_id"],),
        ).fetchall()
        events = [json.loads(item["event_json"]) for item in event_rows]
        expected_refs = [
            {
                "usage_event_id": event["usage_event_id"],
                "usage_event_hash": event["usage_event_hash"],
            }
            for event in events
        ]
        reports = [event["usage_report"] for event in events]
        budget_violations = _sector_inference_budget_violations(
            reports, budget_contract
        )
        expected_budget_decision = {
            "disposition": (
                "STAGE_REJECT" if budget_violations else "WITHIN_BUDGET"
            ),
            "violation_codes": list(budget_violations),
        }
        if ledger.get("budget_decision") != expected_budget_decision:
            raise ValueError("KNOT Sector usage budget decision mismatch")
        if budget_decision != expected_budget_decision:
            raise ValueError("KNOT Sector usage receipt budget decision mismatch")
        if receipt["accepted_output_id"] is not None and budget_violations:
            raise ValueError("accepted KNOT Sector usage receipt is over budget")
        input_tokens = sum(report["input_tokens"] for report in reports)
        output_tokens = sum(report["output_tokens"] for report in reports)
        if (
            event_refs != expected_refs
            or len(events) != receipt["model_subcall_count"]
            or ledger.get("model_subcall_count") != len(events)
            or input_tokens != receipt["input_tokens"]
            or output_tokens != receipt["output_tokens"]
            or ledger.get("input_tokens") != input_tokens
            or ledger.get("output_tokens") != output_tokens
        ):
            raise ValueError("KNOT Sector usage aggregate mismatch")
        summary_row = conn.execute(
            "SELECT receipt_json FROM sector_model_usage_summaries "
            "WHERE capability_id = ?",
            (receipt["capability_id"],),
        ).fetchone()
        if summary_row is None:
            raise ValueError("KNOT Sector signed model usage summary is unavailable")
        usage_summary = self._verify_sector_model_usage_summary_with_conn(
            conn, json.loads(summary_row["receipt_json"])
        )
        if (
            usage_summary["budget_contract_ref"] != budget_ref
            or usage_summary["model_subcall_count"] != receipt["model_subcall_count"]
            or usage_summary["last_attempted_stage"]
            != receipt["last_attempted_stage"]
            or usage_summary["input_tokens"] != receipt["input_tokens"]
            or usage_summary["output_tokens"] != receipt["output_tokens"]
            or usage_summary["conflict_review_triggered"]
            != receipt["conflict_review_triggered"]
            or (
                receipt["accepted_output_id"] is not None
                and usage_summary["model_path_disposition"] != "COMPLETED"
            )
        ):
            raise ValueError("KNOT Sector usage receipt summary mismatch")
        expected_runtime_audit = {
            "schema_version": "sector_runtime_inference_cost_audit_v3",
            "evidence_source": "SIGNED_SERVER_MODEL_USAGE_SUMMARY",
            "sector_agent_id": receipt["agent_id"],
            "snapshot_bundle_hash": usage_summary["snapshot_bundle_hash"],
            "usage_summary_receipt_id": usage_summary["usage_summary_receipt_id"],
            "usage_summary_receipt_hash": usage_summary[
                "usage_summary_receipt_hash"
            ],
            "usage_summary_receipt": usage_summary,
            "model_subcall_count": receipt["model_subcall_count"],
            "last_attempted_stage": receipt["last_attempted_stage"],
            "conflict_review_triggered": receipt["conflict_review_triggered"],
            "input_tokens": receipt["input_tokens"],
            "output_tokens": receipt["output_tokens"],
            "disposition": (
                "SUCCESS"
                if receipt["accepted_output_id"] is not None
                else "AGENT_FAILURE"
            ),
        }
        if runtime_audit != expected_runtime_audit:
            raise ValueError("KNOT Sector runtime cost audit body mismatch")
        pair_row = conn.execute(
            "SELECT receipt_json FROM verified_pair_root_receipts "
            "WHERE pair_root_reservation_id = ?",
            (receipt["pair_root_reservation_id"],),
        ).fetchone()
        if pair_row is None:
            raise ValueError("KNOT Sector usage pair root is unavailable")
        pair_receipt = self._verify_knot_pair_root_receipt_with_conn(
            conn,
            json.loads(pair_row["receipt_json"]),
            require_active_capabilities=False,
        )
        capability = pair_receipt["capabilities"].get(receipt["pair_side"])
        if not isinstance(capability, dict):
            raise ValueError("KNOT Sector usage receipt pair side is invalid")
        expected_lineage = {
            "pair_root_receipt_hash": pair_receipt["pair_root_receipt_hash"],
            "capability_id": capability["capability_id"],
            "capability_manifest_hash": capability["capability_manifest_hash"],
            "graph_run_id": capability["graph_run_id"],
            "run_slot_id": capability["run_slot_id"],
            "run_id": capability["run_id"],
            "node_id": capability["node_id"],
            "agent_id": capability["agent_id"],
            "stage": capability["stage"],
            "as_of": capability["as_of"],
        }
        for field, expected in expected_lineage.items():
            if receipt.get(field) != expected:
                raise ValueError(f"KNOT Sector usage receipt {field} mismatch")
        measured_at = _aware_timestamp(receipt["measured_at"], "usage.measured_at")
        verified_at = _aware_timestamp(receipt["verified_at"], "usage.verified_at")
        if measured_at > verified_at:
            raise ValueError("KNOT Sector usage receipt timeline is invalid")
        self._validate_knot_capability_completion(
            conn,
            capability=capability,
            allowed_tools=pair_receipt["allowed_tools"],
            validated_at=verified_at,
        )
        return receipt

    def list_tools(self, envelope: Mapping[str, Any]) -> list[dict[str, Any]]:
        manifest, _ = self._verify(envelope)
        return [
            {
                "name": tool_id,
                "description": TOOL_DESCRIPTIONS[tool_id],
                "args_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            }
            for tool_id in manifest["allowed_tools"]
        ]

    def call_tool(
        self,
        envelope: Mapping[str, Any],
        tool_id: str,
        args: Mapping[str, Any],
    ) -> str:
        manifest, row = self._verify(envelope)
        if args:
            raise ValueError("role-scoped model tools accept no arguments")
        if tool_id not in manifest["allowed_tools"]:
            raise ValueError(f"tool {tool_id!r} is not allowed by this capability")
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
                conn.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise ValueError("capability tool has already been used") from exc
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return payload

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
            store = AgentToolCapabilityStore(
                path,
                signing_key=key,
                signing_key_id=key_id,
                signing_key_is_durable=raw_key is not None,
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
