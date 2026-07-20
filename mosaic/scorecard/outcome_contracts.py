"""Generated 28-Agent outcome contracts consumed by Scorecard/Darwinian v2.

The editable source is ``mosaic-ts/src/autoresearch/outcome_registry.ts``.
Python deliberately loads the generated public artifact instead of maintaining
a second agent/label table.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from mosaic.scorecard.canonical_json import canonical_hash


_REPO_ROOT = Path(__file__).resolve().parents[2]
OUTCOME_CONTRACT_MANIFEST_PATH = (
    _REPO_ROOT
    / "registry"
    / "prompt_checks"
    / "agent_outcome_contract_manifest_v2.json"
)
OUTCOME_PROJECTION_SCHEMA_PATH = (
    _REPO_ROOT / "schemas" / "realized_outcome_projection_v2.schema.json"
)
TOOL_CONTRACT_MANIFEST_PATH = (
    _REPO_ROOT
    / "registry"
    / "prompt_checks"
    / "agent_tool_contract_manifest_v1.json"
)
OPPORTUNITY_GENERATOR_CONTRACT_VERSION = "evaluation_opportunity_generator_v2"
OPPORTUNITY_GENERATION_FAILURE_CODES = frozenset(
    {
        "CONTRACT_MISMATCH",
        "EMPTY_REQUIRED_OPPORTUNITY_SET",
        "PIT_UNVERIFIED",
        "REQUIRED_DATA_UNAVAILABLE",
        "SOURCE_COVERAGE_UNHEALTHY",
    }
)


def load_outcome_contracts(
    manifest_path: Path = OUTCOME_CONTRACT_MANIFEST_PATH,
    tool_manifest_path: Path = TOOL_CONTRACT_MANIFEST_PATH,
) -> Mapping[str, Mapping[str, Any]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("manifest_version") != "agent_outcome_contract_manifest_v2":
        raise RuntimeError("unsupported Agent outcome contract manifest")
    contracts = payload.get("contracts")
    if not isinstance(contracts, list) or len(contracts) != 28:
        raise RuntimeError("Agent outcome contract manifest must contain 28 rows")
    metric_schemas = payload.get("metric_schemas")
    if (
        payload.get("metric_schema_count") != 8
        or not isinstance(metric_schemas, dict)
        or len(metric_schemas) != 8
        or payload.get("metric_schemas_hash")
        != canonical_hash(metric_schemas)
    ):
        raise RuntimeError("Agent outcome metric schema registry is invalid")
    realized_metric_schemas = payload.get("realized_metric_schemas")
    if (
        payload.get("realized_metric_schema_count") != 8
        or not isinstance(realized_metric_schemas, dict)
        or len(realized_metric_schemas) != 8
        or payload.get("realized_metric_schemas_hash")
        != canonical_hash(realized_metric_schemas)
    ):
        raise RuntimeError("Agent realized outcome metric schema registry is invalid")

    by_agent: dict[str, Mapping[str, Any]] = {}
    labels: set[str] = set()
    component_calibration_contracts: list[Mapping[str, Any]] = []
    for row in contracts:
        if not isinstance(row, dict):
            raise RuntimeError("Agent outcome contract rows must be objects")
        agent_id = row.get("agent_id")
        label_id = row.get("primary_label_id")
        if not isinstance(agent_id, str) or not agent_id or agent_id in by_agent:
            raise RuntimeError("Agent outcome contract agent IDs must be unique")
        if not isinstance(label_id, str) or not label_id or label_id in labels:
            raise RuntimeError("Agent outcome contract label IDs must be unique")
        required_sources = row.get("required_source_ids")
        if (
            not isinstance(required_sources, list)
            or not required_sources
            or len(required_sources) != len(set(required_sources))
        ):
            raise RuntimeError(f"invalid required sources for Agent {agent_id}")
        if row.get("fallback_allowed") is not False:
            raise RuntimeError(f"fallback must be forbidden for Agent {agent_id}")
        if row.get("label_owner") != "DETERMINISTIC_RUNTIME":
            raise RuntimeError(f"label owner must be deterministic for Agent {agent_id}")
        dimensions = row.get("track_contract_dimensions")
        if not isinstance(dimensions, dict):
            raise RuntimeError(f"track dimensions are invalid for Agent {agent_id}")
        composition = row.get("component_composition_contract")
        requires_components = dimensions.get("component_weight_contract") == "REQUIRED"
        if requires_components != (composition is not None):
            raise RuntimeError(f"component composition presence mismatch for Agent {agent_id}")
        if composition is not None:
            if (
                not isinstance(composition, dict)
                or not isinstance(
                    composition.get("component_weight_contract_version"), str
                )
                or not composition["component_weight_contract_version"]
            ):
                raise RuntimeError(f"component composition version missing for Agent {agent_id}")
            components = composition.get("components")
            if (
                not isinstance(components, dict)
                or len(components) < 2
                or any(
                    not isinstance(component, str)
                    or not component
                    or isinstance(weight, bool)
                    or not isinstance(weight, (int, float))
                    or not math.isfinite(weight)
                    or weight <= 0
                    for component, weight in components.items()
                )
                or not math.isclose(sum(components.values()), 1.0, abs_tol=1e-12)
            ):
                raise RuntimeError(f"component weights are invalid for Agent {agent_id}")
            calibration = composition.get("calibration_contract")
            required_calibration_fields = {
                "calibration_contract_version",
                "calibration_solver_version",
                "reference_cohort_id",
                "reference_language",
                "maximum_lookback_trading_days",
                "semiannual_slot_months",
                "regularization_lambda",
                "component_weight_lower_bound",
                "component_weight_upper_bound",
                "maximum_component_delta",
                "solver_grid_step",
                "minimum_fit_samples",
                "minimum_production_samples",
                "minimum_rolling_folds",
                "minimum_validation_samples_per_fold",
                "purge_trading_days",
                "embargo_trading_days",
                "minimum_shadow_samples",
                "maximum_runs_per_half_year",
                "minimum_oos_mse_improvement_ratio",
                "maximum_regime_mse_degradation_ratio",
                "minimum_regime_validation_samples",
                "minimum_fold_adjustment_agreement_ratio",
                "maximum_bound_hit_fold_ratio",
                "minimum_diagnostic_paired_samples",
                "maximum_diagnostic_mse_degradation_ratio",
            }
            if not isinstance(calibration, dict) or set(calibration) != required_calibration_fields:
                raise RuntimeError(f"component calibration contract is invalid for Agent {agent_id}")
            if (
                calibration.get("reference_cohort_id") != "cohort_default"
                or calibration.get("reference_language") != "zh"
                or calibration.get("maximum_lookback_trading_days") != 1260
                or calibration.get("semiannual_slot_months") != [6, 12]
                or calibration.get("minimum_fit_samples") < 60
                or calibration.get("minimum_production_samples")
                < calibration.get("minimum_fit_samples")
                or calibration.get("minimum_rolling_folds") < 5
                or calibration.get("minimum_validation_samples_per_fold") < 12
                or calibration.get("purge_trading_days") != 5
                or calibration.get("embargo_trading_days") != 5
                or calibration.get("minimum_shadow_samples") < 20
                or calibration.get("maximum_runs_per_half_year") != 1
                or not 0
                < calibration.get("component_weight_lower_bound")
                < calibration.get("component_weight_upper_bound")
                < 1
                or not 0 < calibration.get("solver_grid_step") <= 0.01
                or not 0 < calibration.get("maximum_component_delta") <= 0.05
            ):
                raise RuntimeError(f"component calibration constraints are invalid for Agent {agent_id}")
            component_calibration_contracts.append(calibration)
        metric_schema_id = row.get("metric_schema_id")
        if not isinstance(metric_schema_id, str) or metric_schema_id not in metric_schemas:
            raise RuntimeError(f"unknown metric schema for Agent {agent_id}")
        realized_metric_schema_id = row.get("realized_metric_schema_id")
        if (
            not isinstance(realized_metric_schema_id, str)
            or realized_metric_schema_id not in realized_metric_schemas
        ):
            raise RuntimeError(f"unknown realized metric schema for Agent {agent_id}")
        by_agent[agent_id] = MappingProxyType(row)
        labels.add(label_id)

    canonical_registry = {
        agent_id: dict(by_agent[agent_id]) for agent_id in sorted(by_agent)
    }
    if payload.get("registry_hash") != canonical_hash(canonical_registry):
        raise RuntimeError("Agent outcome contract registry_hash mismatch")

    usage = {
        agent_id
        for agent_id, row in by_agent.items()
        if row.get("darwin_application_mode") == "DOWNSTREAM_USAGE_WEIGHT"
    }
    evolution_only = {
        agent_id
        for agent_id, row in by_agent.items()
        if row.get("darwin_application_mode") == "EVOLUTION_ONLY"
    }
    if (
        payload.get("contract_count") != 28
        or payload.get("usage_track_count") != 24
        or payload.get("evolution_only_track_count") != 4
        or len(usage) != 24
        or len(evolution_only) != 4
    ):
        raise RuntimeError("Agent outcome manifest 28/24/4 cardinality mismatch")
    if any(by_agent[agent_id].get("layer") == "DECISION" for agent_id in usage):
        raise RuntimeError("Decision Agent cannot own a downstream usage weight")
    if any(by_agent[agent_id].get("layer") != "DECISION" for agent_id in evolution_only):
        raise RuntimeError("EVOLUTION_ONLY is reserved for Decision Agents")
    component_agents = {
        agent_id
        for agent_id, row in by_agent.items()
        if row.get("component_composition_contract") is not None
    }
    if len(component_agents) != 7 or any(
        by_agent[agent_id].get("layer") != "MACRO" for agent_id in component_agents
    ):
        raise RuntimeError("component composition contracts must cover seven Macro Agents")
    if len({canonical_hash(contract) for contract in component_calibration_contracts}) != 1:
        raise RuntimeError("component calibration contract must be identical across Macro Agents")

    tool_payload = json.loads(tool_manifest_path.read_text(encoding="utf-8"))
    tool_agents = {
        row.get("agent_id")
        for row in tool_payload.get("agents", [])
        if isinstance(row, dict)
    }
    if tool_payload.get("agent_count") != 28 or tool_agents != set(by_agent):
        raise RuntimeError("outcome and tool contract Agent rosters differ")

    return MappingProxyType(by_agent)


def load_outcome_metric_schemas(
    manifest_path: Path = OUTCOME_CONTRACT_MANIFEST_PATH,
) -> Mapping[str, Mapping[str, Any]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    schemas = payload.get("metric_schemas")
    if (
        payload.get("metric_schema_count") != 8
        or not isinstance(schemas, dict)
        or len(schemas) != 8
        or payload.get("metric_schemas_hash") != canonical_hash(schemas)
    ):
        raise RuntimeError("Agent outcome metric schema registry is invalid")
    return MappingProxyType(
        {
            schema_id: MappingProxyType(schema)
            for schema_id, schema in schemas.items()
            if isinstance(schema_id, str) and isinstance(schema, dict)
        }
    )


def load_outcome_realized_metric_schemas(
    manifest_path: Path = OUTCOME_CONTRACT_MANIFEST_PATH,
) -> Mapping[str, Mapping[str, Any]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    schemas = payload.get("realized_metric_schemas")
    if (
        payload.get("realized_metric_schema_count") != 8
        or not isinstance(schemas, dict)
        or len(schemas) != 8
        or payload.get("realized_metric_schemas_hash")
        != canonical_hash(schemas)
    ):
        raise RuntimeError("Agent realized outcome metric schema registry is invalid")
    return MappingProxyType(
        {
            schema_id: MappingProxyType(schema)
            for schema_id, schema in schemas.items()
            if isinstance(schema_id, str) and isinstance(schema, dict)
        }
    )


OUTCOME_CONTRACTS = load_outcome_contracts()
OUTCOME_METRIC_SCHEMAS = load_outcome_metric_schemas()
OUTCOME_REALIZED_METRIC_SCHEMAS = load_outcome_realized_metric_schemas()
_OUTCOME_MANIFEST = json.loads(
    OUTCOME_CONTRACT_MANIFEST_PATH.read_text(encoding="utf-8")
)
OUTCOME_REGISTRY_HASH = str(_OUTCOME_MANIFEST["registry_hash"])
OUTCOME_METRIC_SCHEMAS_HASH = str(_OUTCOME_MANIFEST["metric_schemas_hash"])
OUTCOME_REALIZED_METRIC_SCHEMAS_HASH = str(
    _OUTCOME_MANIFEST["realized_metric_schemas_hash"]
)
OUTCOME_PROJECTION_SCHEMA_HASH = canonical_hash(
    json.loads(OUTCOME_PROJECTION_SCHEMA_PATH.read_text(encoding="utf-8"))
)
USAGE_WEIGHT_AGENT_IDS = tuple(
    agent_id
    for agent_id, row in OUTCOME_CONTRACTS.items()
    if row["darwin_application_mode"] == "DOWNSTREAM_USAGE_WEIGHT"
)
EVOLUTION_ONLY_AGENT_IDS = tuple(
    agent_id
    for agent_id, row in OUTCOME_CONTRACTS.items()
    if row["darwin_application_mode"] == "EVOLUTION_ONLY"
)


__all__ = [
    "EVOLUTION_ONLY_AGENT_IDS",
    "OPPORTUNITY_GENERATION_FAILURE_CODES",
    "OPPORTUNITY_GENERATOR_CONTRACT_VERSION",
    "OUTCOME_CONTRACTS",
    "OUTCOME_CONTRACT_MANIFEST_PATH",
    "OUTCOME_METRIC_SCHEMAS",
    "OUTCOME_METRIC_SCHEMAS_HASH",
    "OUTCOME_PROJECTION_SCHEMA_HASH",
    "OUTCOME_PROJECTION_SCHEMA_PATH",
    "OUTCOME_REALIZED_METRIC_SCHEMAS_HASH",
    "OUTCOME_REALIZED_METRIC_SCHEMAS",
    "OUTCOME_REGISTRY_HASH",
    "TOOL_CONTRACT_MANIFEST_PATH",
    "USAGE_WEIGHT_AGENT_IDS",
    "load_outcome_contracts",
    "load_outcome_metric_schemas",
    "load_outcome_realized_metric_schemas",
]
