"""Schema validation gate for RKE Phase 1 artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .manual_review_bundle_manifest import MANUAL_REVIEW_BUNDLE_ARTIFACTS
from .manual_review_aids import manual_review_aid_paths, manual_review_field_contract
from .p0 import (
    CLAIM_GOLD_SET_METRIC_THRESHOLDS,
    MIN_CLAIM_GOLD_SET_CLAIMS,
    MIN_CLAIM_GOLD_SET_DOCUMENTS,
)
from .required_data import normalize_required_data_items
from .temp_paths import RKE_OPERATOR_TMP_ENV_PREFIX


SUPPORTED_JSON_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "if",
        "items",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "properties",
        "required",
        "then",
        "title",
        "type",
        "uniqueItems",
    }
)

REPORT_INTELLIGENCE_EVOLUTION_READINESS_GATE_SCHEMA_RULES = (
    "schemas/report_intelligence_evolution_readiness_gate_rules"
)


@dataclass(frozen=True)
class SchemaValidationRecord:
    schema_path: str
    artifact_path: str
    item_count: int
    accepted: bool
    failures: Sequence[str]


@dataclass(frozen=True)
class SchemaValidationReport:
    report_id: str
    records: Sequence[SchemaValidationRecord]

    @property
    def accepted(self) -> bool:
        return all(record.accepted for record in self.records)

    @property
    def failure_count(self) -> int:
        return sum(len(record.failures) for record in self.records)


def _has_operator_tmp_env_prefix(command: str) -> bool:
    return RKE_OPERATOR_TMP_ENV_PREFIX in command


JSON_SCHEMA_TARGETS = (
    ("schemas/source_metadata.schema.json", "registry/sources/central_bank_sources.jsonl", "jsonl"),
    ("schemas/source_grounded_claim.schema.json", "registry/claims/central_bank_claims.jsonl", "jsonl"),
    ("schemas/source_grounded_claim.schema.json", "registry/claims/semiconductor_claims.jsonl", "jsonl"),
    ("schemas/hypothesis.schema.json", "registry/hypotheses/central_bank_hypotheses.jsonl", "jsonl"),
    ("schemas/hypothesis.schema.json", "registry/hypotheses/semiconductor_hypotheses.jsonl", "jsonl"),
    (
        "schemas/data_availability_matrix.schema.json",
        "registry/data_availability/central_bank_data_availability.json",
        "json",
    ),
    (
        "schemas/data_availability_matrix.schema.json",
        "registry/data_availability/semiconductor_sandbox_data_availability.json",
        "json",
    ),
    (
        "schemas/data_availability_matrix.schema.json",
        "registry/data_availability/macro_expansion_data_availability.json",
        "json",
    ),
    (
        "schemas/parameter_prior.schema.json",
        "registry/parameter_priors/central_bank_parameter_priors.jsonl",
        "jsonl",
    ),
    (
        "schemas/validation_experiment_v2.schema.json",
        "registry/experiments/central_bank_validation_experiment_v2.json",
        "json",
    ),
    ("schemas/production_patch.schema.json", "registry/patches/central_bank_paper_trading_patch.json", "json"),
    (
        "schemas/domain_knob_catalog_v1.schema.json",
        "registry/prompt_checks/domain_knob_catalog_v1.json",
        "json",
    ),
    (
        "schemas/runtime_agent_manifest_v1.schema.json",
        "registry/prompt_checks/runtime_agent_manifest_v1.json",
        "json",
    ),
    (
        "schemas/domain_knob_evaluation_contract_v1.schema.json",
        "registry/prompt_checks/domain_knob_evaluation_contract_v1.json",
        "json",
    ),
)


RULE_PACK_TARGETS = (
    "registry/rule_packs/macro.central_bank.liquidity.v1.json",
    "registry/rule_packs/sector.semiconductor.policy_substitution.v1.json",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_mapping_json(path: Path, label: str) -> tuple[Mapping[str, Any] | None, tuple[str, ...]]:
    if not path.exists():
        return None, (f"{label} missing",)
    try:
        payload = _read_json(path)
    except json.JSONDecodeError as exc:
        return None, (f"{label} must contain valid JSON: {exc.msg}",)
    if not isinstance(payload, Mapping):
        return None, (f"{label} must be object",)
    return payload, ()


def _read_json_value(path: Path, label: str) -> tuple[Any | None, tuple[str, ...]]:
    if not path.exists():
        return None, (f"{label} missing",)
    try:
        return _read_json(path), ()
    except json.JSONDecodeError as exc:
        return None, (f"{label} must contain valid JSON: {exc.msg}",)


def _load_jsonl_values(path: Path, label: str) -> tuple[list[Any], tuple[str, ...]]:
    if not path.exists():
        return [], (f"{label} missing",)
    rows: list[Any] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                return rows, (f"{label} row {index} must contain valid JSON: {exc.msg}",)
    return rows, ()


def _schema_file(root_path: Path, schema_path: str) -> Path:
    rooted = root_path / schema_path
    if rooted.exists():
        return rooted
    return Path(schema_path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": 1}


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def iter_json_schema_keywords(schema: Mapping[str, Any]) -> tuple[str, ...]:
    keywords: list[str] = []

    def walk(node: Any) -> None:
        if not isinstance(node, Mapping):
            return
        for key, value in node.items():
            keywords.append(str(key))
            if key == "properties" and isinstance(value, Mapping):
                for property_schema in value.values():
                    walk(property_schema)
            elif key == "additionalProperties" and isinstance(value, Mapping):
                walk(value)
            elif key == "items":
                if isinstance(value, Mapping):
                    walk(value)
                elif isinstance(value, list):
                    for item_schema in value:
                        walk(item_schema)
            elif key in {"allOf"} and isinstance(value, list):
                for item_schema in value:
                    walk(item_schema)
            elif key in {"if", "then"} and isinstance(value, Mapping):
                walk(value)

    walk(schema)
    return tuple(keywords)


def _schema_expected_types(schema: Mapping[str, Any]) -> tuple[str, ...]:
    expected = schema.get("type")
    if isinstance(expected, str):
        return (expected,)
    if isinstance(expected, Sequence) and not isinstance(expected, str):
        return tuple(str(item) for item in expected)
    return ()


def _number_limit(schema: Mapping[str, Any], key: str) -> float | None:
    if key not in schema:
        return None
    try:
        return float(schema[key])
    except (TypeError, ValueError):
        return None


def _json_unique_items(value: Sequence[Any]) -> bool:
    seen: set[str] = set()
    for item in value:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if marker in seen:
            return False
        seen.add(marker)
    return True


def _validate_value(value: Any, schema: Mapping[str, Any], path: str) -> list[str]:
    failures: list[str] = []
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for item_schema in all_of:
            if isinstance(item_schema, Mapping):
                failures.extend(_validate_value(value, item_schema, path))
    if_schema = schema.get("if")
    then_schema = schema.get("then")
    if isinstance(if_schema, Mapping) and isinstance(then_schema, Mapping):
        if not _validate_value(value, if_schema, path):
            failures.extend(_validate_value(value, then_schema, path))
    expected_types = _schema_expected_types(schema)
    if expected_types and not any(
        _schema_type_matches(value, expected_type)
        for expected_type in expected_types
    ):
        return [f"{path}: expected {'/'.join(expected_types)}"]
    if "const" in schema and value != schema["const"]:
        failures.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and not any(value == enum_value for enum_value in schema["enum"]):
        failures.append(f"{path}: value {value!r} not in enum")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = _number_limit(schema, "minimum")
        maximum = _number_limit(schema, "maximum")
        exclusive_minimum = _number_limit(schema, "exclusiveMinimum")
        exclusive_maximum = _number_limit(schema, "exclusiveMaximum")
        if minimum is not None and value < minimum:
            failures.append(f"{path}: below minimum {schema['minimum']!r}")
        if maximum is not None and value > maximum:
            failures.append(f"{path}: above maximum {schema['maximum']!r}")
        if exclusive_minimum is not None and value <= exclusive_minimum:
            failures.append(f"{path}: below exclusiveMinimum {schema['exclusiveMinimum']!r}")
        if exclusive_maximum is not None and value >= exclusive_maximum:
            failures.append(f"{path}: above exclusiveMaximum {schema['exclusiveMaximum']!r}")
    if isinstance(value, str):
        if int(schema.get("minLength") or 0) and len(value) < int(schema["minLength"]):
            failures.append(f"{path}: below minLength")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            failures.append(f"{path}: above maxLength")
        if "pattern" in schema and not re.search(str(schema["pattern"]), value):
            failures.append(f"{path}: pattern mismatch")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems") or 0):
            failures.append(f"{path}: below minItems")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            failures.append(f"{path}: above maxItems")
        if schema.get("uniqueItems") is True and not _json_unique_items(value):
            failures.append(f"{path}: duplicate items")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for idx, item in enumerate(value):
                failures.extend(_validate_value(item, item_schema, f"{path}[{idx}]"))
    if isinstance(value, dict):
        required = tuple(schema.get("required") or ())
        for field in required:
            if field not in value:
                failures.append(f"{path}.{field}: required")
        properties = dict(schema.get("properties") or {})
        for field, field_schema in properties.items():
            if field in value and isinstance(field_schema, Mapping):
                failures.extend(_validate_value(value[field], field_schema, f"{path}.{field}"))
        additional = schema.get("additionalProperties", True)
        if additional is False:
            extra = set(value) - set(properties)
            failures.extend(f"{path}.{field}: additional property not allowed" for field in sorted(extra))
        elif isinstance(additional, Mapping):
            for field, item in value.items():
                if field not in properties:
                    failures.extend(_validate_value(item, additional, f"{path}.{field}"))
    return failures


def validate_json_schema_artifact(
    *,
    root: str | Path,
    schema_path: str,
    artifact_path: str,
    artifact_kind: str,
    allow_empty: bool = False,
) -> SchemaValidationRecord:
    root_path = Path(root)
    schema, schema_failures = _read_mapping_json(
        _schema_file(root_path, schema_path),
        schema_path,
    )
    failures: list[str] = list(schema_failures)
    artifact_file = root_path / artifact_path
    local_optional_report_intelligence = (
        artifact_path.startswith("registry/report_intelligence/")
        and not artifact_file.exists()
    )
    if (allow_empty or local_optional_report_intelligence) and not artifact_file.exists():
        items: list[Any] = []
        item_failures: tuple[str, ...] = ()
    elif artifact_kind == "jsonl":
        items, item_failures = _load_jsonl_values(artifact_file, artifact_path)
    elif artifact_kind == "json":
        item, item_failures = _read_json_value(artifact_file, artifact_path)
        items = [] if item is None else [item]
    else:
        raise ValueError(f"unsupported artifact_kind: {artifact_kind}")
    failures.extend(item_failures)
    if not items and not (allow_empty or local_optional_report_intelligence):
        failures.append("artifact has no validation items")
    if schema is not None:
        for idx, item in enumerate(items):
            failures.extend(_validate_value(item, schema, f"$[{idx}]"))
    return SchemaValidationRecord(
        schema_path=schema_path,
        artifact_path=artifact_path,
        item_count=len(items),
        accepted=not failures,
        failures=tuple(failures),
    )


REPORT_INTELLIGENCE_JSON_SCHEMA_TARGETS = (
    (
        "schemas/report_intelligence_feature_flags.schema.json",
        "registry/report_intelligence/feature_flags.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_report_metadata.schema.json",
        "registry/report_intelligence/report_metadata.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_forecast_claim.schema.json",
        "registry/report_intelligence/forecast_claims.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_analytical_footprint.schema.json",
        "registry/report_intelligence/analytical_footprints.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_report_forecast_ledger.schema.json",
        "registry/report_intelligence/report_forecast_ledger.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_markdown_coverage_summary.schema.json",
        "registry/report_intelligence/markdown_coverage_summary.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_industry_etf_proxy_map.schema.json",
        "registry/report_intelligence/industry_etf_proxy_map.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_industry_etf_proxy_pit_availability.schema.json",
        "registry/report_intelligence/industry_etf_proxy_pit_availability.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_macro_regime_calendar.schema.json",
        "registry/report_intelligence/macro_regime_calendar.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_report_outcome_label.schema.json",
        "registry/report_intelligence/report_outcome_labels.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_outcome_labeling_readiness.schema.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_source_performance_profile.schema.json",
        "registry/report_intelligence/source_performance_profiles.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_viewpoint_performance_profile.schema.json",
        "registry/report_intelligence/viewpoint_performance_profiles.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_macro_regime_snapshot.schema.json",
        "registry/report_intelligence/macro_regime_snapshots.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_macro_agent_research_prior.schema.json",
        "registry/report_intelligence/macro_agent_research_priors.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_macro_market_series_catalog.schema.json",
        "registry/report_intelligence/macro_market_series_catalog.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_stock_context_snapshot.schema.json",
        "registry/report_intelligence/stock_context_snapshots.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_industry_context_snapshot.schema.json",
        "registry/report_intelligence/industry_context_snapshots.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_method_performance_profile.schema.json",
        "registry/report_intelligence/method_performance_profiles.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_metric_candidate.schema.json",
        "registry/report_intelligence/metric_candidates.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_method_pattern.schema.json",
        "registry/report_intelligence/method_patterns.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_tool_coverage_match.schema.json",
        "registry/report_intelligence/tool_coverage_matches.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_tool_gap.schema.json",
        "registry/report_intelligence/tool_gaps.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_data_acquisition_proposal.schema.json",
        "registry/report_intelligence/data_acquisition_proposals.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_tool_design_proposal.schema.json",
        "registry/report_intelligence/tool_design_proposals.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_analysis_recipe.schema.json",
        "registry/report_intelligence/analysis_recipes.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_recipe_paper_trading_run.schema.json",
        "registry/report_intelligence/recipe_paper_trading_runs.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_recipe_paper_trading_summary.schema.json",
        "registry/report_intelligence/recipe_paper_trading_summary.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_confidence_impact_observation.schema.json",
        "registry/report_intelligence/confidence_impact_observations.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_confidence_impact_monitor.schema.json",
        "registry/report_intelligence/confidence_impact_monitor.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_evolution_refresh_history.schema.json",
        "registry/report_intelligence/monitor_refresh_history.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_evolution_refresh_history.schema.json",
        "registry/report_intelligence/audit_refresh_history.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_evolution_refresh_history.schema.json",
        "registry/report_intelligence/gap_distribution_history.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_evolution_readiness_gate.schema.json",
        "registry/report_intelligence/evolution_readiness_gate.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_prompt_mutation_candidate.schema.json",
        "registry/report_intelligence/prompt_mutation_candidates.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_weighted_research_context.schema.json",
        "registry/report_intelligence/weighted_research_contexts.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_runtime_tool_gap_observation.schema.json",
        "registry/report_intelligence/runtime_tool_gap_observations.jsonl",
        "jsonl",
        True,
    ),
    (
        "schemas/report_intelligence_monitoring_report.schema.json",
        "registry/report_intelligence/monitoring_report.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_runtime_safety_audit.schema.json",
        "registry/report_intelligence/runtime_safety_audit.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_pit_leakage_audit.schema.json",
        "registry/report_intelligence/pit_leakage_audit.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_extraction_provenance_audit.schema.json",
        "registry/report_intelligence/extraction_provenance_audit.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_statistical_robustness_audit.schema.json",
        "registry/report_intelligence/statistical_robustness_audit.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_tool_feasibility_audit.schema.json",
        "registry/report_intelligence/tool_feasibility_audit.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_recipe_validation_audit.schema.json",
        "registry/report_intelligence/recipe_validation_audit.json",
        "json",
        False,
    ),
    (
        "schemas/report_intelligence_patch_v1_5_coverage_report.schema.json",
        "registry/report_intelligence/patch_v1_5_coverage_report.json",
        "json",
        False,
    ),
)


def _extract_yaml_list(text: str, key: str) -> tuple[str, ...]:
    marker = f"{key}:"
    lines = text.splitlines()
    try:
        start = next(idx for idx, line in enumerate(lines) if line.strip() == marker)
    except StopIteration:
        return ()
    out: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        if not line.startswith(" ") and not stripped.startswith("-"):
            break
        if stripped.startswith("- "):
            out.append(stripped[2:].strip())
    return tuple(out)


def validate_rule_pack_schema_artifact(root: str | Path, artifact_path: str) -> SchemaValidationRecord:
    root_path = Path(root)
    schema_text = _schema_file(root_path, "schemas/rule_pack.schema.yaml").read_text(encoding="utf-8")
    required = _extract_yaml_list(schema_text, "required")
    rules_required = _extract_yaml_list(schema_text, "rules_required")
    rule_pack, artifact_failures = _read_json_value(root_path / artifact_path, artifact_path)
    failures: list[str] = list(artifact_failures)
    if artifact_failures:
        return SchemaValidationRecord(
            schema_path="schemas/rule_pack.schema.yaml",
            artifact_path=artifact_path,
            item_count=0,
            accepted=False,
            failures=tuple(failures),
        )
    if not isinstance(rule_pack, Mapping):
        return SchemaValidationRecord(
            schema_path="schemas/rule_pack.schema.yaml",
            artifact_path=artifact_path,
            item_count=1,
            accepted=False,
            failures=("$: expected object",),
        )
    for field in required:
        if field not in rule_pack:
            failures.append(f"$.{field}: required")
    raw_rules = rule_pack.get("rules") or {}
    if not isinstance(raw_rules, Mapping):
        rules: Mapping[str, Any] = {}
        failures.append("$.rules: expected object")
    else:
        rules = raw_rules
    if not raw_rules:
        failures.append("$.rules: required non-empty rule map")
    for rule_id, rule in rules.items():
        if not isinstance(rule, Mapping):
            failures.append(f"$.rules.{rule_id}: expected object")
            continue
        for field in rules_required:
            if field not in rule:
                failures.append(f"$.rules.{rule_id}.{field}: required")
    return SchemaValidationRecord(
        schema_path="schemas/rule_pack.schema.yaml",
        artifact_path=artifact_path,
        item_count=len(rules) or 1,
        accepted=not failures,
        failures=tuple(failures),
    )


def validate_policy_schema_files(root: str | Path) -> tuple[SchemaValidationRecord, ...]:
    root_path = Path(root)
    checks = (
        (
            "schemas/confidence_policy.schema.yaml",
            ("components:", "safe_default_function:", "research_only_without_current_data:", "thresholds:"),
        ),
        (
            "schemas/rule_aggregation_policy.schema.yaml",
            ("caps:", "conflict_handling:", "validation_required:"),
        ),
    )
    records: list[SchemaValidationRecord] = []
    for schema_path, required_markers in checks:
        text = _schema_file(root_path, schema_path).read_text(encoding="utf-8")
        failures = [f"{marker} missing" for marker in required_markers if marker not in text]
        records.append(
            SchemaValidationRecord(
                schema_path=schema_path,
                artifact_path=schema_path,
                item_count=1,
                accepted=not failures,
                failures=tuple(failures),
            )
        )
    return tuple(records)


def _load_mapping_jsonl(
    root_path: Path,
    artifact_path: str,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    values, load_failures = _load_jsonl_values(root_path / artifact_path, artifact_path)
    failures = list(load_failures)
    rows: list[Mapping[str, Any]] = []
    for index, value in enumerate(values, 1):
        if isinstance(value, Mapping):
            rows.append(value)
        else:
            failures.append(f"{artifact_path} row {index}: expected object")
    return rows, failures


def _load_optional_mapping_jsonl(
    root_path: Path,
    artifact_path: str,
) -> tuple[list[Mapping[str, Any]], list[str], bool]:
    if not (root_path / artifact_path).exists():
        return [], [], False
    rows, failures = _load_mapping_jsonl(root_path, artifact_path)
    return rows, failures, True


def _load_public_semantic_jsonl(
    root_path: Path,
    artifact_path: str,
) -> tuple[list[Mapping[str, Any]], list[str], bool]:
    return _load_optional_mapping_jsonl(root_path, artifact_path)


def _has_mapping_gap(row: Mapping[str, Any]) -> bool:
    target = row.get("target")
    benchmark = row.get("benchmark")
    horizon = row.get("horizon")
    direction = str(row.get("direction") or "unknown").strip().lower()
    macro_claim_legs = [
        leg for leg in row.get("macro_claim_legs") or () if isinstance(leg, Mapping)
    ]
    leg_targets = [
        str(
            leg.get("target_id")
            or (
                leg.get("target", {}).get("target_id")
                if isinstance(leg.get("target"), Mapping)
                else ""
            )
            or ""
        ).strip()
        for leg in macro_claim_legs
    ]
    leg_directions = [
        str(leg.get("direction") or "").strip().lower() for leg in macro_claim_legs
    ]
    leg_horizons = [
        leg.get("claim_horizon") or leg.get("horizon") for leg in macro_claim_legs
    ]
    target_missing = not isinstance(target, Mapping) or not str(
        target.get("target_id") or target.get("target_name") or ""
    ).strip()
    benchmark_missing = not isinstance(benchmark, Mapping) or not benchmark
    if target_missing and any(leg_targets):
        target_missing = False
    horizon_missing = not isinstance(horizon, Mapping) or not horizon
    if horizon_missing and any(isinstance(leg_horizon, Mapping) and leg_horizon for leg_horizon in leg_horizons):
        horizon_missing = False
    direction_missing = direction in {"", "unknown", "ambiguous"}
    if direction_missing and any(
        leg_direction in {"positive", "negative"} for leg_direction in leg_directions
    ):
        direction_missing = False
    return target_missing or benchmark_missing or horizon_missing or direction_missing


def _forecast_horizon_bucket(horizon: Mapping[str, Any]) -> str:
    preferred = horizon.get("preferred_days") or horizon.get("max_days") or horizon.get("min_days")
    try:
        days = int(preferred)
    except (TypeError, ValueError):
        return "unknown"
    if days <= 5:
        return "5d"
    if days <= 20:
        return "20d"
    if days <= 60:
        return "60d"
    return "long_horizon"


def _forecast_target_id(target: Mapping[str, Any]) -> str:
    return str(target.get("target_id") or target.get("target_name") or "unknown")


def _standard_outcome_labeling_ready(row: Mapping[str, Any]) -> bool:
    target = row.get("target")
    benchmark = row.get("benchmark")
    horizon = row.get("horizon")
    return (
        str(row.get("forecast_testability") or "") == "testable"
        and isinstance(target, Mapping)
        and _forecast_target_id(target) != "unknown"
        and isinstance(benchmark, Mapping)
        and bool(benchmark)
        and str(row.get("direction") or "unknown") not in {"", "unknown"}
        and isinstance(horizon, Mapping)
        and _forecast_horizon_bucket(horizon) != "unknown"
    )


STOCK_PROXY_REQUIRED_LABEL_FIELDS = (
    "proxy_symbol",
    "claim_window_set_id",
    "benchmark_symbol",
    "benchmark_source",
    "benchmark_family",
    "benchmark_alignment",
    "cost_model_id",
    "entry_lag_trading_days",
    "round_trip_cost",
    "stock_return",
    "benchmark_return",
    "relative_alpha",
    "after_cost_alpha",
    "directional_after_cost_return",
    "directional_hit",
    "relative_directional_hit",
    "outcome_label_source",
    "llm_outcome_labeling_allowed",
    "performance_value_basis",
    "direction_evaluated",
    "decision_basis",
    "window_role",
    "source_horizon_days",
    "source_horizon_bucket",
    "claim_window_alignment",
    "evaluation_policy",
    "target_resolution_source",
    "metadata_ts_code",
    "llm_target_id",
    "survivorship_check",
    "entry_tradable",
    "exit_tradable",
    "entry_limit_locked",
    "exit_limit_locked",
    "entry_liquidity_check",
    "exit_liquidity_check",
)

INDUSTRY_PROXY_REQUIRED_LABEL_FIELDS = (
    "proxy_symbol",
    "claim_window_set_id",
    "proxy_sector",
    "mapping_id",
    "mapping_version",
    "mapping_confidence",
    "pit_availability_status",
    "benchmark_symbol",
    "benchmark_source",
    "benchmark_family",
    "cost_model_id",
    "entry_lag_trading_days",
    "round_trip_cost",
    "proxy_return",
    "benchmark_return",
    "relative_alpha",
    "after_cost_alpha",
    "directional_after_cost_return",
    "directional_hit",
    "relative_directional_hit",
    "outcome_label_source",
    "llm_outcome_labeling_allowed",
    "performance_value_basis",
    "direction_evaluated",
    "decision_basis",
    "window_role",
    "source_horizon_days",
    "source_horizon_bucket",
    "claim_window_alignment",
    "evaluation_policy",
)

MACRO_PROXY_REQUIRED_LABEL_FIELDS = (
    "proxy_symbol",
    "claim_window_set_id",
    "macro_asset_target_id",
    "mapping_id",
    "mapping_version",
    "mapping_confidence",
    "benchmark_symbol",
    "benchmark_source",
    "benchmark_family",
    "cost_model_id",
    "entry_lag_trading_days",
    "round_trip_cost",
    "proxy_return",
    "benchmark_return",
    "relative_alpha",
    "after_cost_alpha",
    "directional_after_cost_return",
    "directional_hit",
    "relative_directional_hit",
    "outcome_label_source",
    "llm_outcome_labeling_allowed",
    "performance_value_basis",
    "direction_evaluated",
    "decision_basis",
    "window_role",
    "source_horizon_days",
    "source_horizon_bucket",
    "claim_window_alignment",
    "evaluation_policy",
)

MACRO_SERIES_REQUIRED_LABEL_FIELDS = (
    "target_series_id",
    "claim_window_set_id",
    "series_family",
    "quote_convention",
    "unit",
    "mapping_id",
    "mapping_version",
    "mapping_confidence",
    "benchmark_symbol",
    "benchmark_source",
    "benchmark_family",
    "cost_model_id",
    "entry_lag_trading_days",
    "round_trip_cost",
    "entry_value",
    "exit_value",
    "raw_change",
    "directional_change",
    "performance_value",
    "performance_value_basis",
    "directional_hit",
    "outcome_label_source",
    "llm_outcome_labeling_allowed",
    "direction_evaluated",
    "decision_basis",
    "window_role",
    "source_horizon_days",
    "source_horizon_bucket",
    "claim_window_alignment",
    "evaluation_policy",
    "target_resolution_source",
)

MACRO_CURVE_REQUIRED_LABEL_FIELDS = (
    "macro_curve_target_id",
    "claim_window_set_id",
    "curve_family",
    "long_leg_series_id",
    "short_leg_series_id",
    "entry_spread",
    "exit_spread",
    "spread_change",
    "spread_change_bps",
    "directional_change",
    "performance_value",
    "performance_value_basis",
    "quote_convention",
    "unit",
    "mapping_id",
    "mapping_version",
    "mapping_confidence",
    "benchmark_symbol",
    "benchmark_source",
    "benchmark_family",
    "cost_model_id",
    "entry_lag_trading_days",
    "round_trip_cost",
    "directional_hit",
    "outcome_label_source",
    "llm_outcome_labeling_allowed",
    "direction_evaluated",
    "decision_basis",
    "window_role",
    "source_horizon_days",
    "source_horizon_bucket",
    "claim_window_alignment",
    "evaluation_policy",
    "target_resolution_source",
)

INDUSTRY_ETF_DECISION_BASIS = "absolute_proxy_return_direction"
INDUSTRY_ETF_EVALUATION_POLICY = (
    "industry_etf_t_plus_1_multi_window_proxy_retains_long_horizon_evidence"
)
PROXY_BENCHMARK_SYMBOL = "SH510300"
PROXY_BENCHMARK_SOURCE = "cn_etf"
PROXY_BENCHMARK_FAMILY = "CSI300_ETF_PROXY"
INDUSTRY_ETF_COST_MODEL_ID = "industry_etf_round_trip_10bps_v1"
INDUSTRY_ETF_ROUND_TRIP_COST = 0.001
STOCK_PRICE_PROXY_DECISION_BASIS = "directional_stock_return_and_relative_alpha"
STOCK_PRICE_PROXY_EVALUATION_POLICY = (
    "stock_t_plus_1_multi_window_proxy_retains_long_horizon_evidence"
)
STOCK_PRICE_PROXY_COST_MODEL_ID = "single_stock_round_trip_20bps_v1"
STOCK_PRICE_PROXY_ROUND_TRIP_COST = 0.002
PROXY_OUTCOME_LABEL_TYPES = frozenset(
    {
        "stock_price_proxy",
        "industry_etf_proxy",
        "macro_asset_proxy",
        "macro_series_directional",
        "macro_curve_directional",
    }
)
MACRO_ASSET_PROXY_DECISION_BASIS = "directional_macro_asset_proxy_return"
MACRO_ASSET_PROXY_EVALUATION_POLICY = (
    "macro_asset_t_plus_1_multi_window_proxy_retains_long_horizon_evidence"
)
MACRO_ASSET_PROXY_COST_MODEL_ID = "macro_asset_etf_round_trip_10bps_v1"
MACRO_ASSET_PROXY_ROUND_TRIP_COST = 0.001
MACRO_ASSET_PROXY_BENCHMARK_SYMBOL = "CASH_0"
MACRO_ASSET_PROXY_BENCHMARK_SOURCE = "cash_zero_return"
MACRO_ASSET_PROXY_BENCHMARK_FAMILY = "ABSOLUTE_RETURN_PROXY"
MACRO_SERIES_DIRECTIONAL_DECISION_BASIS = "directional_macro_series_change"
MACRO_SERIES_DIRECTIONAL_EVALUATION_POLICY = (
    "macro_series_t_plus_1_multi_window_direct_pit_series"
)
MACRO_SERIES_DIRECTIONAL_COST_MODEL_ID = "macro_series_no_trade_cost_v1"
MACRO_SERIES_DIRECTIONAL_OUTCOME_LABEL_SOURCE = "pit_macro_series_window"
MACRO_SERIES_DIRECTIONAL_PERFORMANCE_BASES = {
    "directional_bps_change",
    "directional_fx_change",
    "directional_volatility_change",
    "directional_price_return",
    "directional_series_change",
}
MACRO_CURVE_DIRECTIONAL_DECISION_BASIS = "directional_macro_curve_spread_change"
MACRO_CURVE_DIRECTIONAL_EVALUATION_POLICY = (
    "macro_curve_t_plus_1_multi_window_direct_pit_spread"
)
MACRO_CURVE_DIRECTIONAL_COST_MODEL_ID = "macro_curve_no_trade_cost_v1"
MACRO_CURVE_DIRECTIONAL_OUTCOME_LABEL_SOURCE = "pit_macro_curve_window"
INDUSTRY_ETF_PROXY_WINDOW_EFFECTIVE_WEIGHTS: Mapping[str, float] = {
    "short": 0.25,
    "medium": 0.35,
    "long": 0.40,
}
MACRO_ASSET_PROXY_WINDOW_EFFECTIVE_WEIGHTS: Mapping[int, float] = {
    90: 0.333333,
    180: 0.333333,
    360: 0.333334,
}
MACRO_SERIES_DIRECTIONAL_WINDOW_EFFECTIVE_WEIGHTS: Mapping[int, float] = (
    MACRO_ASSET_PROXY_WINDOW_EFFECTIVE_WEIGHTS
)
MACRO_CURVE_DIRECTIONAL_WINDOW_EFFECTIVE_WEIGHTS: Mapping[int, float] = (
    MACRO_ASSET_PROXY_WINDOW_EFFECTIVE_WEIGHTS
)
STOCK_PRICE_PROXY_WINDOW_EFFECTIVE_WEIGHTS: Mapping[int, float] = {
    5: 0.20,
    20: 0.25,
    60: 0.25,
    120: 0.30,
}
PROXY_CLAIM_WINDOW_ALIGNMENTS = {
    "within_source_horizon",
    "shorter_than_source_horizon",
    "beyond_source_horizon",
    "fixed_window_no_source_horizon",
}

INDUSTRY_ETF_PIT_AVAILABILITY_RECORD_REQUIRED_FIELDS = (
    "mapping_id",
    "mapping_version",
    "sector_name",
    "status",
    "etf_symbol",
    "benchmark_symbol",
    "benchmark_source",
    "benchmark_family",
    "calendar_source",
    "earliest_price_date",
    "latest_price_date",
    "latest_calendar_date",
    "has_20d_window",
    "has_60d_window",
    "has_120d_window",
    "available_window_days",
    "missing_price_count",
    "stale_price_gap_count",
    "benchmark_available",
    "pit_available",
    "pit_gap_reasons",
)

INDUSTRY_ETF_PIT_LABELABILITY_REQUIRED_FIELDS = (
    "eligible_claim_count",
    "labelable_claim_count",
    "labelable_window_count",
    "pending_future_window_count",
    "sector_etf_mapping_missing_count",
    "proxy_series_missing_count",
    "benchmark_series_missing_count",
)

EVOLUTION_GATE_EXPECTED_CHECK_IDS = (
    "RI-EVOL-01",
    "RI-EVOL-02",
    "RI-EVOL-03",
    "RI-EVOL-04",
    "RI-EVOL-05",
    "RI-EVOL-06",
    "RI-EVOL-07",
    "RI-EVOL-08",
    "RI-EVOL-09",
)
EVOLUTION_GATE_OPTIONAL_CHECK_ID_GROUPS = (
    (
        "RI-MACRO-01",
        "RI-MACRO-02",
        "RI-MACRO-03",
        "RI-MACRO-04",
        "RI-MACRO-05",
        "RI-MACRO-06",
        "RI-MACRO-07",
    ),
    (
        "RI-STOCK-01",
        "RI-STOCK-02",
        "RI-STOCK-03",
        "RI-STOCK-04",
    ),
    (
        "RI-INDUSTRY-01",
        "RI-INDUSTRY-02",
        "RI-INDUSTRY-03",
        "RI-INDUSTRY-04",
    ),
)

EVOLUTION_GATE_EXPECTED_THRESHOLDS = {
    "min_unique_outcome_claims": 100,
    "min_stock_proxy_claims": 30,
    "min_industry_proxy_claims": 30,
    "min_paper_trading_recipes": 20,
    "min_consecutive_monitor_refreshes": 3,
    "min_consecutive_audit_refreshes": 3,
    "min_gap_distribution_refreshes": 3,
}
GAP_DISTRIBUTION_MAX_STABLE_SHARE = 0.80

GOLD_REVIEW_GATE_EXPECTED_REVIEW_PATH = (
    "registry/gold_sets/tushare_research_reports.review_template.jsonl"
)
GOLD_REVIEW_GATE_MIN_REVIEWED_CLAIMS = MIN_CLAIM_GOLD_SET_CLAIMS
GOLD_REVIEW_GATE_MIN_DOCUMENTS = MIN_CLAIM_GOLD_SET_DOCUMENTS
GOLD_REVIEW_GATE_METRIC_THRESHOLDS = CLAIM_GOLD_SET_METRIC_THRESHOLDS

OPERATOR_READINESS_EXPECTED_CHECK_IDS = {
    "required_registry_valid",
    "handoff_ready_for_operator",
    "handoff_command_sequence_complete",
    "manual_review_runbook_promotion_policy_consistent",
    "manual_batch_templates_match_status",
    "manual_batch_promotion_inputs_separated",
    "manual_import_templates_are_sparse",
    "manual_import_templates_have_provenance",
    "blank_full_gold_set_import_is_rejected",
    "lockbox_template_requires_human_decision",
    "blank_lockbox_import_is_rejected",
    "lockbox_upstream_cli_guard_enforced",
    "source_license_policy_template_requires_human_decision",
    "blank_source_license_policy_import_is_rejected",
    "blank_bundle_dry_run_does_not_promote",
    "manual_review_bundle_manifest_current",
    "promotion_gate_state_consistent",
    "source_text_redaction_clean",
}
PROMOTION_GATE_EXPECTED_CRITERION_IDS = {f"PG{index:02d}" for index in range(1, 11)}
PROMOTION_DRY_RUN_EXPECTED_REVIEW_KINDS = {
    "gold_set",
    "footprint_review",
    "source_license",
    "lockbox",
}
PROMOTION_NEXT_STATES = {
    "candidate",
    "paper_trading",
    "staged_production",
    "production",
}
OPERATOR_HANDOFF_EXPECTED_STEP_IDS = (
    "review-progress-preflight",
    "prepare-gold-review",
    "write-gold-review-evidence",
    "fill-gold-review",
    "dry-run-gold-review",
    "apply-gold-review",
    "prepare-footprint-review",
    "write-footprint-review-assist",
    "write-footprint-review-evidence",
    "fill-footprint-review",
    "dry-run-footprint-review",
    "apply-footprint-review",
    "promotion-status-before-lockbox",
    "prepare-lockbox-review",
    "fill-lockbox-review",
    "dry-run-lockbox-review",
    "promotion-dry-run",
    "apply-lockbox-review",
    "promotion-status-final",
)
MANUAL_REVIEW_PROGRESS_EXPECTED_GATES = {
    "gold_set": {
        "input_path": "registry/review_batches/gold_set_full_reviewed.jsonl",
    },
    "footprint_review": {
        "input_path": "registry/report_intelligence/analytical_footprint_reviewed.jsonl",
    },
    "source_license": {
        "input_path": "registry/review_batches/source_license_policy_reviewed.json",
    },
    "lockbox": {
        "input_path": "registry/review_batches/lockbox_reviewed.json",
    },
}

STOCK_PROXY_SURVIVORSHIP_UNVERIFIED_CHECK = "survivorship_unverified_qlib_cn_data"
STOCK_PROXY_SURVIVORSHIP_AUDITED_CHECK = "delisted_inclusive_universe_audit_passed"
STOCK_PROXY_SURVIVORSHIP_CHECKS = {
    STOCK_PROXY_SURVIVORSHIP_UNVERIFIED_CHECK,
    STOCK_PROXY_SURVIVORSHIP_AUDITED_CHECK,
}
STOCK_PROXY_TRADABILITY_CHECK = "positive_volume_and_limit_lock_screen"
STOCK_PROXY_READINESS_WINDOWS = (5, 20, 60, 120)
STOCK_PROXY_CODE_POLICY: Mapping[str, Any] = {
    "policy_id": "ordinary_a_share_stock_codes_v1",
    "allowed_prefixes": {
        "SH": ["60", "68"],
        "SZ": ["00", "30"],
        "BJ": ["92"],
    },
    "rejected_code_families": [
        "fund",
        "etf",
        "lof",
        "index",
        "legacy_bj_8_prefix",
    ],
    "fund_like_prefix_examples": {
        "SH": ["50", "51", "52"],
        "SZ": ["15", "16", "18"],
    },
    "fallback_action": "stock_target_mapping_missing",
}
PROMPT_MUTATION_REQUIRED_VALIDATION_REQUIREMENTS = (
    "gold_set_review_pass",
    "pit_outcome_replay_pass",
    "schema_validation_pass",
    "provenance_audit_pass",
    "statistical_robustness_audit_pass",
    "shadow_paper_trading_pass",
)
PRIOR_COMPILER_REFUSAL_CANDIDATE_TYPES = {
    "stock_prior_recipe_rule_refusal",
    "industry_prior_recipe_rule_refusal",
    "macro_prior_rule_parameter_refusal",
}
PRIOR_COMPILER_CANDIDATE_TYPES = {
    "stock_prior_recipe_rule_candidate",
    "industry_prior_recipe_rule_candidate",
    "macro_prior_rule_parameter_candidate",
}
PRIOR_COMPILER_ALLOWED_REFUSAL_REASONS = {
    "insufficient_effective_n",
    "missing_pit_outcome",
    "missing_validation_target",
    "source_dependent_cluster",
}
PROMPT_MUTATION_PUBLIC_EVIDENCE_PREFIXES = (
    "registry/report_intelligence/",
    "registry/gold_sets/",
    "registry/review_batches/",
)
PROMPT_MUTATION_PRIVATE_EVIDENCE_PATH_MARKERS = (
    "/pdfs/",
    "/markdown/",
    "/mineru/",
    "registry/report_intelligence/report_metadata.jsonl",
    "registry/report_intelligence/forecast_claims.jsonl",
    "registry/report_intelligence/analytical_footprints.jsonl",
    "registry/report_intelligence/report_outcome_labels.jsonl",
    "registry/report_intelligence/weighted_research_contexts.jsonl",
    "registry/report_intelligence/processing_status.jsonl",
    "registry/report_intelligence/analytical_footprint_review_template.jsonl",
    "registry/report_intelligence/analytical_footprint_reviewed.jsonl",
    "registry/sources/tushare_research_reports",
    "registry/gold_sets/tushare_research_reports.candidate",
    "registry/gold_sets/tushare_research_reports.review_template",
    "registry/compliance/tushare_license_review",
)
EXTRACTION_REPORT_PUBLIC_JSONL_COUNT_FIELDS = (
    ("forecast_ledger_rows", "registry/report_intelligence/report_forecast_ledger.jsonl"),
    ("source_performance_profile_rows", "registry/report_intelligence/source_performance_profiles.jsonl"),
    ("viewpoint_performance_profile_rows", "registry/report_intelligence/viewpoint_performance_profiles.jsonl"),
    ("method_performance_profile_rows", "registry/report_intelligence/method_performance_profiles.jsonl"),
    ("metric_candidate_rows", "registry/report_intelligence/metric_candidates.jsonl"),
    ("method_pattern_rows", "registry/report_intelligence/method_patterns.jsonl"),
    ("tool_coverage_match_rows", "registry/report_intelligence/tool_coverage_matches.jsonl"),
    ("tool_gap_rows", "registry/report_intelligence/tool_gaps.jsonl"),
    ("data_acquisition_proposal_rows", "registry/report_intelligence/data_acquisition_proposals.jsonl"),
    ("tool_design_proposal_rows", "registry/report_intelligence/tool_design_proposals.jsonl"),
    ("analysis_recipe_rows", "registry/report_intelligence/analysis_recipes.jsonl"),
    ("runtime_tool_gap_observation_rows", "registry/report_intelligence/runtime_tool_gap_observations.jsonl"),
)
REPORT_INTELLIGENCE_LOCAL_DETAIL_SEMANTIC_PATHS = frozenset(
    artifact_path
    for _count_field, artifact_path in EXTRACTION_REPORT_PUBLIC_JSONL_COUNT_FIELDS
) | frozenset(
    {
        "registry/report_intelligence/audit_refresh_history.jsonl",
        "registry/report_intelligence/confidence_impact_observations.jsonl",
        "registry/report_intelligence/gap_distribution_history.jsonl",
        "registry/report_intelligence/macro_agent_research_priors.jsonl",
        "registry/report_intelligence/macro_regime_snapshots.jsonl",
        "registry/report_intelligence/monitor_refresh_history.jsonl",
        "registry/report_intelligence/prompt_mutation_candidates.jsonl",
        "registry/report_intelligence/recipe_paper_trading_runs.jsonl",
        "registry/report_intelligence/tool_design_proposals.jsonl",
    }
)
REPORT_INTELLIGENCE_PUBLIC_FORBIDDEN_TEXT_KEYS = {
    "abstract",
    "claim_text",
    "manual_claim_text",
    "markdown_path",
    "original_markdown",
    "pdf_path",
    "pdf_url",
    "retrieval_locator",
    "source_span_ids",
    "source_span_text",
    "source_text",
    "title",
    "url",
}
REPORT_INTELLIGENCE_PUBLIC_FORBIDDEN_ID_QUEUE_SUFFIXES = (
    "_forecast_claim_ids",
    "_recipe_ids",
    "_tool_gap_ids",
    "_tool_proposal_ids",
)
REPORT_INTELLIGENCE_PUBLIC_FORBIDDEN_QUEUE_KEYS = {
    "requested_tools",
    "shadow_implemented_requested_tools",
    "tool_gap_ids",
    "tool_proposal_ids",
    "unlinked_requested_tools",
}
REPORT_INTELLIGENCE_PUBLIC_ID_QUEUE_ARTIFACTS = (
    "registry/report_intelligence/confidence_impact_monitor.json",
    "registry/report_intelligence/industry_etf_proxy_pit_availability.json",
    "registry/report_intelligence/outcome_labeling_readiness.json",
    "registry/report_intelligence/recipe_paper_trading_summary.json",
)


def _required_field_failures(
    row: Mapping[str, Any],
    *,
    row_label: str,
    required_fields: Sequence[str],
) -> list[str]:
    failures: list[str] = []
    for field in required_fields:
        if field not in row:
            failures.append(f"{row_label}.{field}: required")
    return failures


def _has_nonempty_source_spans(row: Mapping[str, Any]) -> bool:
    span_ids = row.get("source_span_ids")
    return isinstance(span_ids, list) and any(str(item).strip() for item in span_ids)


def _normalize_ts_code(value: Any) -> str:
    raw = str(value or "").strip().upper()
    match = re.fullmatch(r"([0-9]{6})[.](SH|SZ|BJ)", raw)
    if not match:
        return ""
    return f"{match.group(1)}.{match.group(2)}"


def _date_key(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) < 10:
        return ""
    candidate = text[:10]
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return ""
    return candidate


def _is_ordinary_stock_ts_code(value: Any) -> bool:
    ts_code = _normalize_ts_code(value)
    if not ts_code:
        return False
    code, exchange = ts_code.split(".", 1)
    allowed_prefixes = STOCK_PROXY_CODE_POLICY["allowed_prefixes"].get(exchange, [])
    return any(code.startswith(prefix) for prefix in allowed_prefixes)


def _numeric_contract_value(
    row: Mapping[str, Any],
    field: str,
    row_label: str,
    failures: list[str],
) -> float | None:
    try:
        return float(row.get(field))
    except (TypeError, ValueError):
        failures.append(f"{row_label}.{field}: expected number")
    return None


def _nearly_equal(left: float, right: float, *, tolerance: float = 1e-6) -> bool:
    return abs(left - right) <= tolerance


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


STOCK_TARGET_PRICE_CONTRACT_FIELDS = (
    "target_price",
    "target_price_hit",
    "target_price_entry_price",
    "target_price_eval_price",
    "target_price_source_grounded",
    "target_price_provenance",
    "target_price_hit_policy",
)


def _validate_stock_target_price_contract(
    row: Mapping[str, Any],
    *,
    row_label: str,
    direction: str,
) -> list[str]:
    if not any(field in row for field in STOCK_TARGET_PRICE_CONTRACT_FIELDS):
        return []
    failures = _required_field_failures(
        row,
        row_label=row_label,
        required_fields=STOCK_TARGET_PRICE_CONTRACT_FIELDS,
    )
    target_price = _float_or_none(row.get("target_price"))
    entry_price = _float_or_none(row.get("target_price_entry_price"))
    eval_price = _float_or_none(row.get("target_price_eval_price"))
    for field, value in (
        ("target_price", target_price),
        ("target_price_entry_price", entry_price),
        ("target_price_eval_price", eval_price),
    ):
        if value is None:
            failures.append(f"{row_label}.{field}: expected number")
        elif value <= 0:
            failures.append(f"{row_label}.{field}: must be > 0")
    if row.get("target_price_source_grounded") is not True:
        failures.append(f"{row_label}.target_price_source_grounded: must be true")
    if not str(row.get("target_price_provenance") or "").strip():
        failures.append(f"{row_label}.target_price_provenance: required")
    policy = str(row.get("target_price_hit_policy") or "")
    if not policy.startswith("auxiliary_source_grounded_target_price_hit_v1:"):
        failures.append(
            f"{row_label}.target_price_hit_policy: unsupported target price policy"
        )
    if target_price is not None and eval_price is not None and direction in {
        "positive",
        "negative",
    }:
        expected_hit = (
            eval_price >= target_price
            if direction == "positive"
            else eval_price <= target_price
        )
        if row.get("target_price_hit") is not expected_hit:
            failures.append(
                f"{row_label}.target_price_hit: must match direction_evaluated and target_price_eval_price"
            )
    return failures


def _validate_stock_target_resolution_contract(
    row: Mapping[str, Any],
    *,
    row_label: str,
) -> list[str]:
    failures: list[str] = []
    proxy_symbol = _normalize_ts_code(row.get("proxy_symbol"))
    if not proxy_symbol or not _is_ordinary_stock_ts_code(proxy_symbol):
        failures.append(
            f"{row_label}.proxy_symbol: must be ordinary stock ts_code per policy"
        )
        return failures

    source = str(row.get("target_resolution_source") or "").strip()
    metadata_ts_code = _normalize_ts_code(row.get("metadata_ts_code"))
    llm_target_id = _normalize_ts_code(row.get("llm_target_id"))
    raw_llm_target_id = str(row.get("llm_target_id") or "").strip()
    if source == "metadata_and_llm_target_id":
        if not metadata_ts_code:
            failures.append(
                f"{row_label}.metadata_ts_code: required for metadata_and_llm_target_id"
            )
        if not llm_target_id:
            failures.append(
                f"{row_label}.llm_target_id: valid ts_code required for metadata_and_llm_target_id"
            )
        if metadata_ts_code and metadata_ts_code != proxy_symbol:
            failures.append(
                f"{row_label}.metadata_ts_code: must equal proxy_symbol for metadata_and_llm_target_id"
            )
        if llm_target_id and llm_target_id != proxy_symbol:
            failures.append(
                f"{row_label}.llm_target_id: must equal proxy_symbol for metadata_and_llm_target_id"
            )
    elif source == "metadata_ts_code":
        if not metadata_ts_code:
            failures.append(f"{row_label}.metadata_ts_code: required")
        elif metadata_ts_code != proxy_symbol:
            failures.append(f"{row_label}.metadata_ts_code: must equal proxy_symbol")
        if llm_target_id and llm_target_id != proxy_symbol:
            failures.append(
                f"{row_label}.llm_target_id: conflicting ts_code cannot generate stock label"
            )
    elif source == "llm_target_id":
        if not llm_target_id:
            failures.append(f"{row_label}.llm_target_id: valid ts_code required")
        elif llm_target_id != proxy_symbol:
            failures.append(f"{row_label}.llm_target_id: must equal proxy_symbol")
        if metadata_ts_code and metadata_ts_code != proxy_symbol:
            failures.append(
                f"{row_label}.metadata_ts_code: conflicting ts_code cannot generate stock label"
            )
    else:
        failures.append(
            f"{row_label}.target_resolution_source: unsupported stock target resolution"
        )
    if raw_llm_target_id and llm_target_id and not _is_ordinary_stock_ts_code(llm_target_id):
        failures.append(
            f"{row_label}.llm_target_id: must use ordinary stock ts_code when present"
        )
    return failures


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _count_mapping(
    value: Any,
    *,
    row_label: str,
    failures: list[str],
) -> dict[str, int]:
    if not isinstance(value, Mapping):
        failures.append(f"{row_label}: expected object")
        return {}
    counts: dict[str, int] = {}
    for key, raw_count in value.items():
        try:
            counts[str(key)] = int(raw_count)
        except (TypeError, ValueError):
            failures.append(f"{row_label}.{key}: expected integer count")
    return counts


def _profile_effective_n(row: Mapping[str, Any], *, profile_kind: str) -> float:
    if profile_kind == "method":
        source_support = row.get("source_support")
        if isinstance(source_support, Mapping):
            return _float_or_none(source_support.get("n_effective_reports")) or 0.0
        return 0.0
    return _float_or_none(row.get("n_effective")) or 0.0


def _profile_weight_value(row: Mapping[str, Any], *, profile_kind: str) -> float:
    if profile_kind == "viewpoint":
        return _float_or_none(row.get("viewpoint_weight_multiplier")) or 1.0
    if profile_kind == "method":
        return 1.0
    return _float_or_none(row.get("weight_multiplier")) or 1.0


def _profile_effective_n_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    profile_kind: str,
) -> dict[str, int | float]:
    effective_values = [
        _profile_effective_n(row, profile_kind=profile_kind) for row in rows
    ]
    max_effective_n = max(effective_values, default=0.0)
    return {
        "profile_count": len(rows),
        "nonzero_effective_n_count": sum(1 for value in effective_values if value > 0),
        "max_effective_n": round(max_effective_n, 8),
    }


def _profile_non_neutral_count(
    rows: Sequence[Mapping[str, Any]],
    *,
    profile_kind: str,
) -> int:
    return sum(
        1
        for row in rows
        if abs(_profile_weight_value(row, profile_kind=profile_kind) - 1.0) > 1e-9
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _public_forbidden_text_failures(
    value: Any,
    *,
    path: str,
) -> list[str]:
    failures: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            child_path = f"{path}.{key}"
            if normalized_key in REPORT_INTELLIGENCE_PUBLIC_FORBIDDEN_TEXT_KEYS and bool(
                item
            ):
                failures.append(f"{child_path}: private/source text field forbidden")
                continue
            failures.extend(_public_forbidden_text_failures(item, path=child_path))
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for index, item in enumerate(value):
            failures.extend(
                _public_forbidden_text_failures(item, path=f"{path}[{index}]")
            )
    return failures


def _public_forbidden_id_queue_failures(
    value: Any,
    *,
    path: str,
) -> list[str]:
    failures: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            key_text = str(key)
            if key_text in REPORT_INTELLIGENCE_PUBLIC_FORBIDDEN_QUEUE_KEYS:
                failures.append(f"{child_path}: private queue field forbidden")
                continue
            if key_text.endswith(
                REPORT_INTELLIGENCE_PUBLIC_FORBIDDEN_ID_QUEUE_SUFFIXES
            ):
                failures.append(f"{child_path}: private id queue field forbidden")
                continue
            failures.extend(_public_forbidden_id_queue_failures(item, path=child_path))
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for index, item in enumerate(value):
            failures.extend(
                _public_forbidden_id_queue_failures(item, path=f"{path}[{index}]")
            )
    return failures


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_items(value: Any) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    items: list[int] = []
    for item in value:
        parsed = _int_or_none(item)
        if parsed is not None:
            items.append(parsed)
    return items


def _validate_proxy_outcome_label_contract(
    row: Mapping[str, Any],
    row_label: str,
) -> list[str]:
    label_type = str(row.get("label_type") or "")
    if label_type not in PROXY_OUTCOME_LABEL_TYPES:
        return [
            f"{row_label}.label_type: must be stock_price_proxy, industry_etf_proxy, macro_asset_proxy, macro_series_directional, or macro_curve_directional"
        ]
    required_fields = {
        "stock_price_proxy": STOCK_PROXY_REQUIRED_LABEL_FIELDS,
        "industry_etf_proxy": INDUSTRY_PROXY_REQUIRED_LABEL_FIELDS,
        "macro_asset_proxy": MACRO_PROXY_REQUIRED_LABEL_FIELDS,
        "macro_series_directional": MACRO_SERIES_REQUIRED_LABEL_FIELDS,
        "macro_curve_directional": MACRO_CURVE_REQUIRED_LABEL_FIELDS,
    }[label_type]
    failures = _required_field_failures(
        row,
        row_label=row_label,
        required_fields=required_fields,
    )
    if row.get("llm_outcome_labeling_allowed") is not False:
        failures.append(f"{row_label}.llm_outcome_labeling_allowed: must be false")
    if label_type == "macro_series_directional":
        if row.get("performance_value_basis") not in MACRO_SERIES_DIRECTIONAL_PERFORMANCE_BASES:
            failures.append(
                f"{row_label}.performance_value_basis: unsupported macro series basis"
            )
    elif label_type == "macro_curve_directional":
        if row.get("performance_value_basis") != "directional_curve_bps_change":
            failures.append(
                f"{row_label}.performance_value_basis: must be directional_curve_bps_change"
            )
    elif row.get("performance_value_basis") != "directional_after_cost_return":
        failures.append(
            f"{row_label}.performance_value_basis: must be directional_after_cost_return"
        )
    entry_date = _date_key(row.get("entry_datetime"))
    exit_date = _date_key(row.get("exit_datetime"))
    if not entry_date:
        failures.append(f"{row_label}.entry_datetime: missing or invalid ISO date")
    if not exit_date:
        failures.append(f"{row_label}.exit_datetime: missing or invalid ISO date")
    if entry_date and exit_date and exit_date <= entry_date:
        failures.append(
            f"{row_label}.exit_datetime: must be after entry_datetime date"
        )
    effective_n_weight = _float_or_none(row.get("effective_n_weight"))
    if effective_n_weight is None:
        failures.append(f"{row_label}.effective_n_weight: expected number")
    elif effective_n_weight <= 0.0 or effective_n_weight > 1.0:
        failures.append(f"{row_label}.effective_n_weight: must be in (0, 1]")
    horizon_days = _int_or_none(row.get("horizon_days"))
    if horizon_days is None:
        failures.append(f"{row_label}.horizon_days: expected integer")
    elif horizon_days <= 0:
        failures.append(f"{row_label}.horizon_days: must be > 0")
    else:
        if label_type in {
            "macro_asset_proxy",
            "macro_series_directional",
            "macro_curve_directional",
        }:
            expected_window_role = (
                "short"
                if horizon_days <= 90
                else "medium"
                if horizon_days <= 180
                else "long"
            )
        else:
            expected_window_role = (
                "short"
                if horizon_days <= 20
                else "medium"
                if horizon_days <= 60
                else "long"
            )
        if row.get("window_role") != expected_window_role:
            failures.append(
                f"{row_label}.window_role: must be {expected_window_role} for horizon_days={horizon_days}"
            )
    source_horizon_days = row.get("source_horizon_days")
    if source_horizon_days is not None:
        parsed_source_horizon_days = _int_or_none(source_horizon_days)
        if parsed_source_horizon_days is None:
            failures.append(f"{row_label}.source_horizon_days: expected integer or null")
        elif parsed_source_horizon_days < 0:
            failures.append(f"{row_label}.source_horizon_days: must be >= 0")
    if str(row.get("claim_window_alignment") or "") not in PROXY_CLAIM_WINDOW_ALIGNMENTS:
        failures.append(f"{row_label}.claim_window_alignment: unsupported alignment")
    try:
        entry_lag = int(row.get("entry_lag_trading_days"))
    except (TypeError, ValueError):
        failures.append(f"{row_label}.entry_lag_trading_days: expected integer")
    else:
        if entry_lag < 1:
            failures.append(f"{row_label}.entry_lag_trading_days: must be >= 1")
    round_trip_cost: float | None
    try:
        round_trip_cost = float(row.get("round_trip_cost"))
    except (TypeError, ValueError):
        round_trip_cost = None
        failures.append(f"{row_label}.round_trip_cost: expected number")
    else:
        if round_trip_cost < 0:
            failures.append(f"{row_label}.round_trip_cost: must be >= 0")
    if label_type == "macro_series_directional":
        for field, expected in (
            ("outcome_label_source", MACRO_SERIES_DIRECTIONAL_OUTCOME_LABEL_SOURCE),
            ("decision_basis", MACRO_SERIES_DIRECTIONAL_DECISION_BASIS),
            ("evaluation_policy", MACRO_SERIES_DIRECTIONAL_EVALUATION_POLICY),
            ("benchmark_source", "direct_macro_series"),
            ("cost_model_id", MACRO_SERIES_DIRECTIONAL_COST_MODEL_ID),
            ("target_resolution_source", "macro_series_mapping"),
        ):
            if row.get(field) != expected:
                failures.append(f"{row_label}.{field}: must be {expected}")
        if round_trip_cost is not None and not _nearly_equal(round_trip_cost, 0.0):
            failures.append(f"{row_label}.round_trip_cost: must be 0.0")
        if not str(row.get("target_series_id") or "").strip():
            failures.append(f"{row_label}.target_series_id: required")
        if not str(row.get("quote_convention") or "").strip():
            failures.append(f"{row_label}.quote_convention: required")
        if not str(row.get("series_family") or "").strip():
            failures.append(f"{row_label}.series_family: required")
        if not str(row.get("benchmark_family") or "").startswith(
            "DIRECT_MACRO_SERIES_"
        ):
            failures.append(
                f"{row_label}.benchmark_family: must start with DIRECT_MACRO_SERIES_"
            )
        entry_value = _numeric_contract_value(row, "entry_value", row_label, failures)
        exit_value = _numeric_contract_value(row, "exit_value", row_label, failures)
        raw_change = _numeric_contract_value(row, "raw_change", row_label, failures)
        performance_value = _numeric_contract_value(
            row,
            "performance_value",
            row_label,
            failures,
        )
        directional_change = _numeric_contract_value(
            row,
            "directional_change",
            row_label,
            failures,
        )
        direction = str(row.get("direction_evaluated") or "").strip().lower()
        if direction not in {"positive", "negative"}:
            failures.append(
                f"{row_label}.direction_evaluated: must be positive or negative"
            )
        if (
            entry_value is not None
            and exit_value is not None
            and raw_change is not None
            and not _nearly_equal(raw_change, exit_value - entry_value)
        ):
            failures.append(
                f"{row_label}.raw_change: must equal exit_value - entry_value"
            )
        if (
            performance_value is not None
            and directional_change is not None
            and not _nearly_equal(performance_value, directional_change)
        ):
            failures.append(
                f"{row_label}.performance_value: must equal directional_change"
            )
        if performance_value is not None:
            if row.get("directional_hit") is not (performance_value > 0):
                failures.append(
                    f"{row_label}.directional_hit: must match performance_value > 0"
                )
        expected_weight = (
            MACRO_SERIES_DIRECTIONAL_WINDOW_EFFECTIVE_WEIGHTS.get(horizon_days)
            if horizon_days is not None
            else None
        )
        if expected_weight is None:
            failures.append(
                f"{row_label}.horizon_days: unsupported macro series window"
            )
        elif effective_n_weight is not None and not _nearly_equal(
            effective_n_weight,
            expected_weight,
        ):
            failures.append(
                f"{row_label}.effective_n_weight: must be {expected_weight} for macro series horizon_days={horizon_days}"
            )
        return failures
    if label_type == "macro_curve_directional":
        for field, expected in (
            ("outcome_label_source", MACRO_CURVE_DIRECTIONAL_OUTCOME_LABEL_SOURCE),
            ("decision_basis", MACRO_CURVE_DIRECTIONAL_DECISION_BASIS),
            ("evaluation_policy", MACRO_CURVE_DIRECTIONAL_EVALUATION_POLICY),
            ("benchmark_source", "direct_macro_curve"),
            ("benchmark_family", "DIRECT_MACRO_CURVE"),
            ("cost_model_id", MACRO_CURVE_DIRECTIONAL_COST_MODEL_ID),
            ("target_resolution_source", "macro_curve_mapping"),
        ):
            if row.get(field) != expected:
                failures.append(f"{row_label}.{field}: must be {expected}")
        if round_trip_cost is not None and not _nearly_equal(round_trip_cost, 0.0):
            failures.append(f"{row_label}.round_trip_cost: must be 0.0")
        if not str(row.get("macro_curve_target_id") or "").strip():
            failures.append(f"{row_label}.macro_curve_target_id: required")
        if not str(row.get("long_leg_series_id") or "").strip():
            failures.append(f"{row_label}.long_leg_series_id: required")
        if not str(row.get("short_leg_series_id") or "").strip():
            failures.append(f"{row_label}.short_leg_series_id: required")
        if not str(row.get("quote_convention") or "").strip():
            failures.append(f"{row_label}.quote_convention: required")
        entry_spread = _numeric_contract_value(
            row,
            "entry_spread",
            row_label,
            failures,
        )
        exit_spread = _numeric_contract_value(row, "exit_spread", row_label, failures)
        spread_change = _numeric_contract_value(
            row,
            "spread_change",
            row_label,
            failures,
        )
        performance_value = _numeric_contract_value(
            row,
            "performance_value",
            row_label,
            failures,
        )
        directional_change = _numeric_contract_value(
            row,
            "directional_change",
            row_label,
            failures,
        )
        direction = str(row.get("direction_evaluated") or "").strip().lower()
        if direction not in {"positive", "negative"}:
            failures.append(
                f"{row_label}.direction_evaluated: must be positive or negative"
            )
        if (
            entry_spread is not None
            and exit_spread is not None
            and spread_change is not None
            and not _nearly_equal(spread_change, exit_spread - entry_spread)
        ):
            failures.append(
                f"{row_label}.spread_change: must equal exit_spread - entry_spread"
            )
        if (
            performance_value is not None
            and directional_change is not None
            and not _nearly_equal(performance_value, directional_change)
        ):
            failures.append(
                f"{row_label}.performance_value: must equal directional_change"
            )
        if performance_value is not None:
            if row.get("directional_hit") is not (performance_value > 0):
                failures.append(
                    f"{row_label}.directional_hit: must match performance_value > 0"
                )
        expected_weight = (
            MACRO_CURVE_DIRECTIONAL_WINDOW_EFFECTIVE_WEIGHTS.get(horizon_days)
            if horizon_days is not None
            else None
        )
        if expected_weight is None:
            failures.append(
                f"{row_label}.horizon_days: unsupported macro curve window"
            )
        elif effective_n_weight is not None and not _nearly_equal(
            effective_n_weight,
            expected_weight,
        ):
            failures.append(
                f"{row_label}.effective_n_weight: must be {expected_weight} for macro curve horizon_days={horizon_days}"
            )
        return failures
    benchmark_expected = (
        (
            ("benchmark_symbol", MACRO_ASSET_PROXY_BENCHMARK_SYMBOL),
            ("benchmark_source", MACRO_ASSET_PROXY_BENCHMARK_SOURCE),
            ("benchmark_family", MACRO_ASSET_PROXY_BENCHMARK_FAMILY),
        )
        if label_type == "macro_asset_proxy"
        else (
            ("benchmark_symbol", PROXY_BENCHMARK_SYMBOL),
            ("benchmark_source", PROXY_BENCHMARK_SOURCE),
            ("benchmark_family", PROXY_BENCHMARK_FAMILY),
        )
    )
    for field, expected in benchmark_expected:
        if row.get(field) != expected:
            failures.append(f"{row_label}.{field}: must be {expected}")
    proxy_return_field = "stock_return" if label_type == "stock_price_proxy" else "proxy_return"
    proxy_return = _numeric_contract_value(
        row,
        proxy_return_field,
        row_label,
        failures,
    )
    benchmark_return = _numeric_contract_value(
        row,
        "benchmark_return",
        row_label,
        failures,
    )
    relative_alpha = _numeric_contract_value(
        row,
        "relative_alpha",
        row_label,
        failures,
    )
    after_cost_alpha = _numeric_contract_value(
        row,
        "after_cost_alpha",
        row_label,
        failures,
    )
    directional_after_cost_return = _numeric_contract_value(
        row,
        "directional_after_cost_return",
        row_label,
        failures,
    )
    direction = str(row.get("direction_evaluated") or "").strip().lower()
    if direction not in {"positive", "negative"}:
        failures.append(f"{row_label}.direction_evaluated: must be positive or negative")
    if (
        proxy_return is not None
        and benchmark_return is not None
        and relative_alpha is not None
        and not _nearly_equal(relative_alpha, proxy_return - benchmark_return)
    ):
        failures.append(
            f"{row_label}.relative_alpha: must equal {proxy_return_field} - benchmark_return"
        )
    if (
        relative_alpha is not None
        and after_cost_alpha is not None
        and round_trip_cost is not None
        and round_trip_cost >= 0
        and not _nearly_equal(after_cost_alpha, relative_alpha - round_trip_cost)
    ):
        failures.append(
            f"{row_label}.after_cost_alpha: must equal relative_alpha - round_trip_cost"
        )
    if proxy_return is not None and direction in {"positive", "negative"}:
        expected_directional_hit = (
            proxy_return > 0 if direction == "positive" else proxy_return < 0
        )
        if row.get("directional_hit") is not expected_directional_hit:
            failures.append(
                f"{row_label}.directional_hit: must match direction_evaluated and {proxy_return_field}"
            )
        if (
            directional_after_cost_return is not None
            and round_trip_cost is not None
            and round_trip_cost >= 0
        ):
            directional_return = (
                proxy_return if direction == "positive" else -proxy_return
            )
            if not _nearly_equal(
                directional_after_cost_return,
                directional_return - round_trip_cost,
            ):
                failures.append(
                    f"{row_label}.directional_after_cost_return: must equal directional return - round_trip_cost"
                )
    if relative_alpha is not None and direction in {"positive", "negative"}:
        expected_relative_hit = (
            relative_alpha > 0 if direction == "positive" else relative_alpha < 0
        )
        if row.get("relative_directional_hit") is not expected_relative_hit:
            failures.append(
                f"{row_label}.relative_directional_hit: must match direction_evaluated and relative_alpha"
            )
    if label_type == "stock_price_proxy":
        if row.get("decision_basis") != STOCK_PRICE_PROXY_DECISION_BASIS:
            failures.append(
                f"{row_label}.decision_basis: must be {STOCK_PRICE_PROXY_DECISION_BASIS}"
            )
        if row.get("evaluation_policy") != STOCK_PRICE_PROXY_EVALUATION_POLICY:
            failures.append(
                f"{row_label}.evaluation_policy: must be {STOCK_PRICE_PROXY_EVALUATION_POLICY}"
            )
        if row.get("cost_model_id") != STOCK_PRICE_PROXY_COST_MODEL_ID:
            failures.append(
                f"{row_label}.cost_model_id: must be {STOCK_PRICE_PROXY_COST_MODEL_ID}"
            )
        if round_trip_cost is not None and not _nearly_equal(
            round_trip_cost,
            STOCK_PRICE_PROXY_ROUND_TRIP_COST,
        ):
            failures.append(
                f"{row_label}.round_trip_cost: must be {STOCK_PRICE_PROXY_ROUND_TRIP_COST}"
            )
        if row.get("outcome_label_source") != "pit_stock_price_window":
            failures.append(
                f"{row_label}.outcome_label_source: must be pit_stock_price_window"
            )
        expected_weight = (
            STOCK_PRICE_PROXY_WINDOW_EFFECTIVE_WEIGHTS.get(horizon_days)
            if horizon_days is not None
            else None
        )
        if expected_weight is None:
            failures.append(
                f"{row_label}.horizon_days: unsupported stock proxy window"
            )
        elif effective_n_weight is not None and not _nearly_equal(
            effective_n_weight,
            expected_weight,
        ):
            failures.append(
                f"{row_label}.effective_n_weight: must be {expected_weight} for stock horizon_days={horizon_days}"
            )
        if row.get("benchmark_alignment") != "date_key_cross_qlib_dir":
            failures.append(
                f"{row_label}.benchmark_alignment: must be date_key_cross_qlib_dir"
            )
        failures.extend(
            _validate_stock_target_resolution_contract(row, row_label=row_label)
        )
        survivorship_check = str(row.get("survivorship_check") or "").strip()
        if survivorship_check not in STOCK_PROXY_SURVIVORSHIP_CHECKS:
            failures.append(
                f"{row_label}.survivorship_check: unsupported stock survivorship check"
            )
        elif (
            row.get("survivorship_safe") is True
            and survivorship_check != STOCK_PROXY_SURVIVORSHIP_AUDITED_CHECK
        ):
            failures.append(
                f"{row_label}.survivorship_check: survivorship_safe=true requires "
                f"{STOCK_PROXY_SURVIVORSHIP_AUDITED_CHECK}"
            )
        if row.get("entry_tradable") is not True:
            failures.append(f"{row_label}.entry_tradable: must be true")
        if row.get("exit_tradable") is not True:
            failures.append(f"{row_label}.exit_tradable: must be true")
        if row.get("entry_limit_locked") is not False:
            failures.append(f"{row_label}.entry_limit_locked: must be false")
        if row.get("exit_limit_locked") is not False:
            failures.append(f"{row_label}.exit_limit_locked: must be false")
        if row.get("entry_liquidity_check") != STOCK_PROXY_TRADABILITY_CHECK:
            failures.append(
                f"{row_label}.entry_liquidity_check: must be {STOCK_PROXY_TRADABILITY_CHECK}"
            )
        if row.get("exit_liquidity_check") != STOCK_PROXY_TRADABILITY_CHECK:
            failures.append(
                f"{row_label}.exit_liquidity_check: must be {STOCK_PROXY_TRADABILITY_CHECK}"
            )
        failures.extend(
            _validate_stock_target_price_contract(
                row,
                row_label=row_label,
                direction=direction,
            )
        )
    elif label_type == "industry_etf_proxy":
        if row.get("decision_basis") != INDUSTRY_ETF_DECISION_BASIS:
            failures.append(
                f"{row_label}.decision_basis: must be {INDUSTRY_ETF_DECISION_BASIS}"
            )
        if row.get("evaluation_policy") != INDUSTRY_ETF_EVALUATION_POLICY:
            failures.append(
                f"{row_label}.evaluation_policy: must be {INDUSTRY_ETF_EVALUATION_POLICY}"
            )
        if row.get("cost_model_id") != INDUSTRY_ETF_COST_MODEL_ID:
            failures.append(
                f"{row_label}.cost_model_id: must be {INDUSTRY_ETF_COST_MODEL_ID}"
            )
        if round_trip_cost is not None and not _nearly_equal(
            round_trip_cost,
            INDUSTRY_ETF_ROUND_TRIP_COST,
        ):
            failures.append(
                f"{row_label}.round_trip_cost: must be {INDUSTRY_ETF_ROUND_TRIP_COST}"
            )
        if row.get("outcome_label_source") != "pit_industry_etf_price_window":
            failures.append(
                f"{row_label}.outcome_label_source: must be pit_industry_etf_price_window"
            )
        expected_weight = INDUSTRY_ETF_PROXY_WINDOW_EFFECTIVE_WEIGHTS.get(
            str(row.get("window_role") or "")
        )
        if expected_weight is None:
            failures.append(f"{row_label}.window_role: unsupported industry ETF role")
        elif effective_n_weight is not None and not _nearly_equal(
            effective_n_weight,
            expected_weight,
        ):
            failures.append(
                f"{row_label}.effective_n_weight: must be {expected_weight} for industry window_role={row.get('window_role')}"
            )
        if not str(row.get("mapping_id") or "").strip():
            failures.append(f"{row_label}.mapping_id: required")
        try:
            mapping_version = int(row.get("mapping_version"))
        except (TypeError, ValueError):
            failures.append(f"{row_label}.mapping_version: expected integer")
        else:
            if mapping_version < 1:
                failures.append(f"{row_label}.mapping_version: must be >= 1")
    elif label_type == "macro_asset_proxy":
        if row.get("decision_basis") != MACRO_ASSET_PROXY_DECISION_BASIS:
            failures.append(
                f"{row_label}.decision_basis: must be {MACRO_ASSET_PROXY_DECISION_BASIS}"
            )
        if row.get("evaluation_policy") != MACRO_ASSET_PROXY_EVALUATION_POLICY:
            failures.append(
                f"{row_label}.evaluation_policy: must be {MACRO_ASSET_PROXY_EVALUATION_POLICY}"
            )
        if row.get("cost_model_id") != MACRO_ASSET_PROXY_COST_MODEL_ID:
            failures.append(
                f"{row_label}.cost_model_id: must be {MACRO_ASSET_PROXY_COST_MODEL_ID}"
            )
        if round_trip_cost is not None and not _nearly_equal(
            round_trip_cost,
            MACRO_ASSET_PROXY_ROUND_TRIP_COST,
        ):
            failures.append(
                f"{row_label}.round_trip_cost: must be {MACRO_ASSET_PROXY_ROUND_TRIP_COST}"
            )
        if row.get("outcome_label_source") != "pit_macro_asset_etf_price_window":
            failures.append(
                f"{row_label}.outcome_label_source: must be pit_macro_asset_etf_price_window"
            )
        expected_weight = (
            MACRO_ASSET_PROXY_WINDOW_EFFECTIVE_WEIGHTS.get(horizon_days)
            if horizon_days is not None
            else None
        )
        if expected_weight is None:
            failures.append(
                f"{row_label}.horizon_days: unsupported macro asset proxy window"
            )
        elif effective_n_weight is not None and not _nearly_equal(
            effective_n_weight,
            expected_weight,
        ):
            failures.append(
                f"{row_label}.effective_n_weight: must be {expected_weight} for macro horizon_days={horizon_days}"
            )
        if row.get("benchmark_return") not in (0, 0.0):
            failures.append(f"{row_label}.benchmark_return: must be 0 for macro asset proxy")
        if not str(row.get("macro_asset_target_id") or "").strip():
            failures.append(f"{row_label}.macro_asset_target_id: required")
        if not str(row.get("mapping_id") or "").strip():
            failures.append(f"{row_label}.mapping_id: required")
        try:
            mapping_version = int(row.get("mapping_version"))
        except (TypeError, ValueError):
            failures.append(f"{row_label}.mapping_version: expected integer")
        else:
            if mapping_version < 1:
                failures.append(f"{row_label}.mapping_version: must be >= 1")
    return failures


def _validate_proxy_outcome_label_id_namespaces(
    outcome_label_rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    failures: list[str] = []
    id_fields = ("outcome_id", "claim_window_set_id", "overlap_group_id")
    namespace_index: dict[tuple[str, str], dict[str, list[int]]] = {}
    for index, row in enumerate(outcome_label_rows, 1):
        label_type = str(row.get("label_type") or "").strip()
        if label_type not in PROXY_OUTCOME_LABEL_TYPES:
            continue
        for field in id_fields:
            value = str(row.get(field) or "").strip()
            if not value:
                continue
            label_type_rows = namespace_index.setdefault((field, value), {})
            label_type_rows.setdefault(label_type, []).append(index)

    for (field, value), label_type_rows in sorted(namespace_index.items()):
        if len(label_type_rows) <= 1:
            continue
        namespace_detail = ", ".join(
            f"{label_type} rows {rows}"
            for label_type, rows in sorted(label_type_rows.items())
        )
        failures.append(
            "report_outcome_labels."
            f"{field}: {value} crosses label_type namespace ({namespace_detail})"
        )
    return failures


def _validate_proxy_outcome_label_effective_n_sets(
    outcome_label_rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    failures: list[str] = []
    grouped_weights: dict[str, list[tuple[int, float]]] = {}
    for index, row in enumerate(outcome_label_rows, 1):
        label_type = str(row.get("label_type") or "").strip()
        if label_type not in PROXY_OUTCOME_LABEL_TYPES:
            continue
        group_id = str(row.get("claim_window_set_id") or "").strip()
        if not group_id:
            continue
        weight = _float_or_none(row.get("effective_n_weight"))
        if weight is None:
            continue
        grouped_weights.setdefault(group_id, []).append((index, weight))

    for group_id, rows_and_weights in sorted(grouped_weights.items()):
        total_weight = sum(weight for _, weight in rows_and_weights)
        if total_weight > 1.000001:
            rows = [index for index, _ in rows_and_weights]
            failures.append(
                "report_outcome_labels.claim_window_set_id: "
                f"{group_id} effective_n_weight sum {total_weight:.6f} "
                f"exceeds 1 across rows {rows}"
            )
    return failures


def _validate_proxy_outcome_label_forecast_traceability(
    outcome_label_rows: Sequence[Mapping[str, Any]],
    forecast_rows: Sequence[Mapping[str, Any]],
    *,
    forecast_rows_present: bool,
) -> list[str]:
    if not forecast_rows_present:
        return []
    failures: list[str] = []
    forecast_by_id: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(forecast_rows, 1):
        claim_id = str(row.get("forecast_claim_id") or "").strip()
        if not claim_id:
            failures.append(f"forecast_claims row {index}.forecast_claim_id: required")
            continue
        if claim_id in forecast_by_id:
            failures.append(
                f"forecast_claims row {index}.forecast_claim_id: duplicate {claim_id}"
            )
            continue
        forecast_by_id[claim_id] = row

    for index, row in enumerate(outcome_label_rows, 1):
        label_type = str(row.get("label_type") or "").strip()
        if label_type not in PROXY_OUTCOME_LABEL_TYPES:
            continue
        row_label = f"report_outcome_labels row {index}"
        claim_id = str(row.get("forecast_claim_id") or "").strip()
        if not claim_id:
            failures.append(f"{row_label}.forecast_claim_id: required")
            continue
        claim = forecast_by_id.get(claim_id)
        if claim is None:
            failures.append(f"{row_label}.forecast_claim_id: not found in forecast_claims")
            continue
        signal_date = _date_key(claim.get("signal_datetime"))
        entry_date = _date_key(row.get("entry_datetime"))
        if not signal_date:
            failures.append(
                f"{row_label}.forecast_claim_id: referenced claim signal_datetime missing or invalid"
            )
        elif entry_date and entry_date <= signal_date:
            failures.append(
                f"{row_label}.entry_datetime: must be after forecast signal_datetime date"
            )
        if label_type == "stock_price_proxy" and not _has_nonempty_source_spans(claim):
            failures.append(
                f"{row_label}.forecast_claim_id: stock proxy forecast claim must cite source_span_ids"
            )
    return failures


def _validate_industry_etf_mapping_contract(
    root_path: Path,
    outcome_label_rows: Sequence[Mapping[str, Any]],
) -> tuple[int, list[str]]:
    mapping_rows, mapping_failures = _load_mapping_jsonl(
        root_path,
        "registry/report_intelligence/industry_etf_proxy_map.jsonl",
    )
    availability, availability_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/industry_etf_proxy_pit_availability.json",
        "registry/report_intelligence/industry_etf_proxy_pit_availability.json",
    )
    outcome_readiness, outcome_readiness_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/outcome_labeling_readiness.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
    )
    failures = [
        *mapping_failures,
        *availability_failures,
        *outcome_readiness_failures,
    ]

    mappings_by_id: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(mapping_rows, 1):
        row_label = f"industry_etf_proxy_map row {index}"
        mapping_id = str(row.get("mapping_id") or "").strip()
        if not mapping_id:
            failures.append(f"{row_label}.mapping_id: required")
            continue
        if mapping_id in mappings_by_id:
            failures.append(f"{row_label}.mapping_id: duplicate {mapping_id}")
        else:
            mappings_by_id[mapping_id] = row
        if str(row.get("status") or "") == "primary":
            if row.get("review_required") is not False:
                failures.append(f"{row_label}.review_required: primary mapping must be false")
            aliases = _string_items(row.get("sector_aliases"))
            sector_name = str(row.get("sector_name") or "").strip()
            if sector_name and sector_name not in aliases:
                failures.append(
                    f"{row_label}.sector_aliases: must include sector_name"
                )

    availability_records: list[Mapping[str, Any]] = []
    availability_by_id: dict[str, Mapping[str, Any]] = {}
    if availability:
        raw_records = availability.get("mapping_records")
        if not isinstance(raw_records, Sequence) or isinstance(raw_records, str):
            failures.append(
                "industry_etf_proxy_pit_availability.mapping_records: expected array"
            )
        else:
            for index, record in enumerate(raw_records, 1):
                row_label = (
                    f"industry_etf_proxy_pit_availability.mapping_records[{index}]"
                )
                if not isinstance(record, Mapping):
                    failures.append(f"{row_label}: expected object")
                    continue
                availability_records.append(record)
                for field in INDUSTRY_ETF_PIT_AVAILABILITY_RECORD_REQUIRED_FIELDS:
                    if field not in record:
                        failures.append(f"{row_label}.{field}: required")
                mapping_id = str(record.get("mapping_id") or "").strip()
                if not mapping_id:
                    failures.append(f"{row_label}.mapping_id: required")
                    continue
                if mapping_id in availability_by_id:
                    failures.append(f"{row_label}.mapping_id: duplicate {mapping_id}")
                else:
                    availability_by_id[mapping_id] = record
                mapping = mappings_by_id.get(mapping_id)
                if mapping is None:
                    failures.append(
                        f"{row_label}.mapping_id: no matching industry ETF mapping"
                    )
                    continue
                if not str(record.get("calendar_source") or "").startswith("qlib://"):
                    failures.append(
                        f"{row_label}.calendar_source: must use public qlib source label"
                    )
                for field in (
                    "mapping_version",
                    "sector_name",
                    "status",
                    "effective_from",
                    "effective_to",
                    "etf_symbol",
                    "benchmark_symbol",
                    "benchmark_source",
                    "benchmark_family",
                ):
                    if str(record.get(field) or "") != str(mapping.get(field) or ""):
                        failures.append(f"{row_label}.{field}: mapping mismatch")
                windows_days = set(_int_items(availability.get("windows_days")))
                available_windows = set(_int_items(record.get("available_window_days")))
                unexpected_windows = sorted(available_windows - windows_days)
                if unexpected_windows:
                    failures.append(
                        f"{row_label}.available_window_days: unexpected windows "
                        + ", ".join(str(item) for item in unexpected_windows)
                    )
                for window in windows_days:
                    flag_name = f"has_{window}d_window"
                    if flag_name in record and record.get(flag_name) is not (
                        window in available_windows
                    ):
                        failures.append(f"{row_label}.{flag_name}: window flag mismatch")
                pit_gap_reasons = _string_items(record.get("pit_gap_reasons"))
                if record.get("pit_available") is True and pit_gap_reasons:
                    failures.append(
                        f"{row_label}.pit_gap_reasons: pit_available record must have no blockers"
                    )
                if record.get("pit_available") is False and not pit_gap_reasons:
                    failures.append(
                        f"{row_label}.pit_gap_reasons: unavailable record requires blockers"
                    )
                if (
                    record.get("benchmark_available") is False
                    and "benchmark_series_missing" not in pit_gap_reasons
                ):
                    failures.append(
                        f"{row_label}.pit_gap_reasons: benchmark_series_missing required"
                    )
        labelability_summary = availability.get("labelability_summary")
        if not isinstance(labelability_summary, Mapping):
            failures.append(
                "industry_etf_proxy_pit_availability.labelability_summary: expected object"
            )
            labelability_summary = {}
        for field in INDUSTRY_ETF_PIT_LABELABILITY_REQUIRED_FIELDS:
            if field not in labelability_summary:
                failures.append(
                    f"industry_etf_proxy_pit_availability.labelability_summary.{field}: required"
                )
                continue
            parsed_count = _int_or_none(labelability_summary.get(field))
            if parsed_count is None:
                failures.append(
                    f"industry_etf_proxy_pit_availability.labelability_summary.{field}: expected integer"
                )
            elif parsed_count < 0:
                failures.append(
                    f"industry_etf_proxy_pit_availability.labelability_summary.{field}: must be >= 0"
                )
        industry_readiness = (
            outcome_readiness.get("industry_etf_proxy_readiness")
            if isinstance(outcome_readiness, Mapping)
            else None
        )
        if isinstance(industry_readiness, Mapping):
            if not str(
                industry_readiness.get("qlib_etf_dir_configured") or ""
            ).startswith("qlib://"):
                failures.append(
                    "outcome_labeling_readiness.industry_etf_proxy_readiness."
                    "qlib_etf_dir_configured: must use public qlib source label"
                )
            expected_labelability_fields = {
                "eligible_claim_count": "eligible_claim_count",
                "labelable_claim_count": "labelable_forecast_claim_count",
                "labelable_window_count": "labelable_window_count",
                "pending_future_window_count": "pending_future_window_count",
            }
            for summary_field, readiness_field in expected_labelability_fields.items():
                if _int_or_none(labelability_summary.get(summary_field)) != _int_or_none(
                    industry_readiness.get(readiness_field)
                ):
                    failures.append(
                        "industry_etf_proxy_pit_availability.labelability_summary."
                        f"{summary_field}: outcome_labeling_readiness mismatch"
                    )
            summary_gap_counts = labelability_summary.get("data_gap_counts")
            readiness_gap_counts = industry_readiness.get("data_gap_counts")
            if isinstance(summary_gap_counts, Mapping) and isinstance(
                readiness_gap_counts,
                Mapping,
            ):
                normalized_summary_gaps = {
                    str(key): _int_or_none(value)
                    for key, value in summary_gap_counts.items()
                }
                normalized_readiness_gaps = {
                    str(key): _int_or_none(value)
                    for key, value in readiness_gap_counts.items()
                }
                if normalized_summary_gaps != normalized_readiness_gaps:
                    failures.append(
                        "industry_etf_proxy_pit_availability.labelability_summary."
                        "data_gap_counts: outcome_labeling_readiness mismatch"
                    )
            for summary_field, gap_key in (
                ("sector_etf_mapping_missing_count", "sector_etf_mapping_missing"),
                ("proxy_series_missing_count", "proxy_series_missing"),
                ("benchmark_series_missing_count", "benchmark_series_missing"),
            ):
                expected_count = (
                    _int_or_none(readiness_gap_counts.get(gap_key))
                    if isinstance(readiness_gap_counts, Mapping)
                    else 0
                ) or 0
                if _int_or_none(labelability_summary.get(summary_field)) != expected_count:
                    failures.append(
                        "industry_etf_proxy_pit_availability.labelability_summary."
                        f"{summary_field}: outcome_labeling_readiness mismatch"
                    )
        else:
            failures.append(
                "outcome_labeling_readiness.industry_etf_proxy_readiness: expected object"
            )
        stock_readiness = (
            outcome_readiness.get("stock_price_proxy_readiness")
            if isinstance(outcome_readiness, Mapping)
            else None
        )
        if isinstance(stock_readiness, Mapping):
            for field in (
                "qlib_stock_dir_configured",
                "qlib_benchmark_dir_configured",
            ):
                if not str(stock_readiness.get(field) or "").startswith("qlib://"):
                    failures.append(
                        "outcome_labeling_readiness.stock_price_proxy_readiness."
                        f"{field}: must use public qlib source label"
                    )
        else:
            failures.append(
                "outcome_labeling_readiness.stock_price_proxy_readiness: expected object"
            )
        if availability.get("mapping_count") != len(mapping_rows):
            failures.append(
                "industry_etf_proxy_pit_availability.mapping_count mismatch"
            )
        if not str(availability.get("qlib_etf_dir_configured") or "").startswith(
            "qlib://"
        ):
            failures.append(
                "industry_etf_proxy_pit_availability.qlib_etf_dir_configured: "
                "must use public qlib source label"
            )
        pit_available_count = sum(
            1 for record in availability_records if record.get("pit_available") is True
        )
        if availability.get("pit_available_mapping_count") != pit_available_count:
            failures.append(
                "industry_etf_proxy_pit_availability.pit_available_mapping_count mismatch"
            )
        sector_missing_count = _int_or_none(
            labelability_summary.get("sector_etf_mapping_missing_count")
        ) or 0
        action_summary = availability.get("labelability_action_summary")
        if not isinstance(action_summary, Mapping):
            failures.append(
                "industry_etf_proxy_pit_availability.labelability_action_summary: "
                "expected object"
            )
        else:
            action_label = (
                "industry_etf_proxy_pit_availability.labelability_action_summary"
            )
            eligible_count = _int_or_none(
                labelability_summary.get("eligible_claim_count")
            ) or 0
            labelable_count = _int_or_none(
                labelability_summary.get("labelable_claim_count")
            ) or 0
            mapping_count = _int_or_none(availability.get("mapping_count")) or 0
            pit_unavailable_count = max(mapping_count - pit_available_count, 0)
            mapping_review_count = eligible_count + sector_missing_count
            remaining_action_count = sector_missing_count + pit_unavailable_count
            expected_labelability_rate = (
                round(labelable_count / eligible_count, 6)
                if eligible_count
                else 0.0
            )
            expected_mapping_coverage_rate = (
                round(eligible_count / mapping_review_count, 6)
                if mapping_review_count
                else 0.0
            )
            expected_status = (
                "actionable_gaps_present"
                if remaining_action_count
                else "passed"
            )
            for field, expected in (
                ("eligible_claim_count", eligible_count),
                ("labelable_claim_count", labelable_count),
                ("mapping_review_claim_count", mapping_review_count),
                ("sector_etf_mapping_missing_count", sector_missing_count),
                ("pit_unavailable_mapping_count", pit_unavailable_count),
                ("remaining_action_count", remaining_action_count),
            ):
                if _int_or_none(action_summary.get(field)) != expected:
                    failures.append(f"{action_label}.{field}: expected {expected}")
            for field, expected in (
                ("labelability_rate", expected_labelability_rate),
                ("primary_mapping_coverage_rate", expected_mapping_coverage_rate),
            ):
                value = _float_or_none(action_summary.get(field))
                if value is None or round(value, 6) != expected:
                    failures.append(f"{action_label}.{field}: expected {expected}")
            if action_summary.get("coverage_gate_status") != expected_status:
                failures.append(
                    f"{action_label}.coverage_gate_status: expected {expected_status}"
                )
            action_data_gaps = action_summary.get("data_gap_counts")
            if isinstance(action_data_gaps, Mapping) and isinstance(
                labelability_summary.get("data_gap_counts"),
                Mapping,
            ):
                normalized_action_gaps = {
                    str(key): _int_or_none(value)
                    for key, value in action_data_gaps.items()
                }
                normalized_labelability_gaps = {
                    str(key): _int_or_none(value)
                    for key, value in labelability_summary[
                        "data_gap_counts"
                    ].items()
                }
                if normalized_action_gaps != normalized_labelability_gaps:
                    failures.append(f"{action_label}.data_gap_counts mismatch")
            else:
                failures.append(f"{action_label}.data_gap_counts: expected object")
            action_pit_gaps = action_summary.get("pit_gap_counts")
            if isinstance(action_pit_gaps, Mapping) and isinstance(
                availability.get("pit_gap_counts"),
                Mapping,
            ):
                normalized_action_pit_gaps = {
                    str(key): _int_or_none(value)
                    for key, value in action_pit_gaps.items()
                }
                normalized_pit_gaps = {
                    str(key): _int_or_none(value)
                    for key, value in availability["pit_gap_counts"].items()
                }
                if normalized_action_pit_gaps != normalized_pit_gaps:
                    failures.append(f"{action_label}.pit_gap_counts mismatch")
            else:
                failures.append(f"{action_label}.pit_gap_counts: expected object")
            next_actions = _string_items(action_summary.get("next_actions"))
            if remaining_action_count and not next_actions:
                failures.append(f"{action_label}.next_actions: required")
            if sector_missing_count and (
                "add_primary_etf_mapping_for_unmapped_industry_sectors"
                not in next_actions
            ):
                failures.append(
                    f"{action_label}.next_actions: missing sector mapping action"
                )
            if pit_unavailable_count and (
                "refresh_or_replace_pit_unavailable_etf_mappings"
                not in next_actions
            ):
                failures.append(
                    f"{action_label}.next_actions: missing PIT availability action"
                )
        review_queue = availability.get("sector_etf_mapping_review_queue")
        review_queue_count_value = availability.get(
            "sector_etf_mapping_review_queue_count"
        )
        if review_queue is not None or review_queue_count_value is not None:
            queue_label = (
                "industry_etf_proxy_pit_availability."
                "sector_etf_mapping_review_queue"
            )
            if not isinstance(review_queue, Sequence) or isinstance(
                review_queue,
                str,
            ):
                failures.append(f"{queue_label}: expected array")
                review_queue_rows = []
            else:
                review_queue_rows = [
                    row for row in review_queue if isinstance(row, Mapping)
                ]
                if len(review_queue_rows) != len(review_queue):
                    failures.append(f"{queue_label}: all rows must be objects")
            if _int_or_none(review_queue_count_value) != len(review_queue_rows):
                failures.append(f"{queue_label}_count: count mismatch")
            queue_claim_count = 0
            queue_ids: set[str] = set()
            for index, row in enumerate(review_queue_rows, 1):
                row_label = f"{queue_label}[{index}]"
                queue_id = str(row.get("queue_id") or "").strip()
                if not queue_id:
                    failures.append(f"{row_label}.queue_id: required")
                elif queue_id in queue_ids:
                    failures.append(f"{row_label}.queue_id: duplicate {queue_id}")
                else:
                    queue_ids.add(queue_id)
                if not str(row.get("sector_name") or "").strip():
                    failures.append(f"{row_label}.sector_name: required")
                missing_claim_count = _int_or_none(row.get("missing_claim_count"))
                if missing_claim_count is None or missing_claim_count <= 0:
                    failures.append(
                        f"{row_label}.missing_claim_count: must be positive integer"
                    )
                else:
                    queue_claim_count += missing_claim_count
                if row.get("gap_type") != "sector_etf_mapping_missing":
                    failures.append(
                        f"{row_label}.gap_type: expected sector_etf_mapping_missing"
                    )
                if (
                    row.get("recommended_action")
                    != "add_primary_etf_mapping_for_unmapped_industry_sector"
                ):
                    failures.append(
                        f"{row_label}.recommended_action: unexpected action"
                    )
                if row.get("review_required") is not True:
                    failures.append(f"{row_label}.review_required: must be true")
                if row.get("source_text_included") is not False:
                    failures.append(
                        f"{row_label}.source_text_included: must be false"
                    )
                required_mapping_fields = _string_items(
                    row.get("required_mapping_fields")
                )
                for field in ("sector_name", "etf_symbol", "benchmark_symbol"):
                    if field not in required_mapping_fields:
                        failures.append(
                            f"{row_label}.required_mapping_fields: missing {field}"
                        )
            if queue_claim_count != sector_missing_count:
                failures.append(
                    f"{queue_label}.missing_claim_count: expected total "
                    f"{sector_missing_count}"
                )
        missing_availability_ids = sorted(
            set(mappings_by_id) - set(availability_by_id)
        )
        if missing_availability_ids:
            failures.append(
                "industry_etf_proxy_pit_availability missing mapping_ids: "
                + ", ".join(missing_availability_ids[:20])
            )

    industry_label_count = 0
    for index, row in enumerate(outcome_label_rows, 1):
        if row.get("label_type") != "industry_etf_proxy":
            continue
        industry_label_count += 1
        row_label = f"report_outcome_labels row {index}"
        mapping_id = str(row.get("mapping_id") or "").strip()
        mapping = mappings_by_id.get(mapping_id)
        if mapping is None:
            failures.append(f"{row_label}.mapping_id: no matching industry ETF mapping")
            continue
        if mapping.get("status") != "primary":
            failures.append(f"{row_label}.mapping_id: mapping must be primary")
        for label_field, mapping_field in (
            ("mapping_version", "mapping_version"),
            ("mapping_confidence", "mapping_confidence"),
            ("proxy_sector", "sector_name"),
            ("proxy_symbol", "etf_symbol"),
            ("benchmark_symbol", "benchmark_symbol"),
            ("benchmark_source", "benchmark_source"),
            ("benchmark_family", "benchmark_family"),
            ("cost_model_id", "cost_model_id"),
        ):
            if str(row.get(label_field) or "") != str(mapping.get(mapping_field) or ""):
                failures.append(f"{row_label}.{label_field}: mapping mismatch")
        availability_record = availability_by_id.get(mapping_id)
        if availability_record is None:
            failures.append(
                f"{row_label}.mapping_id: no PIT availability record for mapping"
            )
            continue
        if availability_record.get("pit_available") is not True:
            failures.append(
                f"{row_label}.mapping_id: cannot label PIT-unavailable mapping"
            )
        expected_status = (
            "available"
            if availability_record.get("pit_available") is True
            else "unavailable"
        )
        if row.get("pit_availability_status") != expected_status:
            failures.append(
                f"{row_label}.pit_availability_status: must match PIT availability"
            )

    item_count = (
        len(mapping_rows)
        + len(availability_records)
        + industry_label_count
        + (1 if availability else 0)
    )
    return item_count, failures


def _private_public_id_sets_same_vintage(
    private_ids: set[str],
    public_ids: set[str],
) -> bool:
    if not private_ids or not public_ids:
        return False
    overlap = private_ids & public_ids
    if not overlap:
        return False
    return len(overlap) / min(len(private_ids), len(public_ids)) >= 0.8


def _validate_stock_price_proxy_readiness_contract(
    root_path: Path,
    outcome_label_rows: Sequence[Mapping[str, Any]],
) -> tuple[int, list[str]]:
    readiness_report, readiness_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/outcome_labeling_readiness.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
    )
    failures = list(readiness_errors)
    if not readiness_report:
        return 0, failures

    stock_readiness = readiness_report.get("stock_price_proxy_readiness")
    if not isinstance(stock_readiness, Mapping):
        return 0, [
            *failures,
            "outcome_labeling_readiness.stock_price_proxy_readiness: expected object",
        ]

    for field in (
        "qlib_stock_dir_configured",
        "qlib_benchmark_dir_configured",
    ):
        if not str(stock_readiness.get(field) or "").startswith("qlib://"):
            failures.append(
                "outcome_labeling_readiness.stock_price_proxy_readiness."
                f"{field}: must use public qlib source label"
            )
    if stock_readiness.get("outcome_label_source") != "pit_stock_price_window":
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "outcome_label_source: must be pit_stock_price_window"
        )
    if stock_readiness.get("llm_outcome_labeling_allowed") is not False:
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "llm_outcome_labeling_allowed: must be false"
        )
    if _int_or_none(stock_readiness.get("entry_lag_trading_days")) != 1:
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "entry_lag_trading_days: must be 1"
        )
    if tuple(_int_items(stock_readiness.get("windows_days"))) != STOCK_PROXY_READINESS_WINDOWS:
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            f"windows_days: must be {list(STOCK_PROXY_READINESS_WINDOWS)}"
        )
    for field, expected in (
        ("benchmark_symbol", "SH510300"),
        ("benchmark_source", "cn_etf"),
        ("benchmark_family", "CSI300_ETF_PROXY"),
        ("cost_model_id", "single_stock_round_trip_20bps_v1"),
    ):
        if stock_readiness.get(field) != expected:
            failures.append(
                "outcome_labeling_readiness.stock_price_proxy_readiness."
                f"{field}: must be {expected}"
            )
    if stock_readiness.get("ordinary_stock_code_policy") != STOCK_PROXY_CODE_POLICY:
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "ordinary_stock_code_policy: must restrict labels to ordinary "
            "SH60/SH68, SZ00/SZ30, and BJ92 stock codes"
        )

    pit_policy = stock_readiness.get("pit_realism_policy")
    if not isinstance(pit_policy, Mapping):
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "pit_realism_policy: expected object"
        )
        pit_policy = {}
    for field in (
        "entry_suspension_blocks_label",
        "entry_limit_locked_blocks_label",
        "exit_liquidity_unverified_blocks_label",
        "exit_missing_or_delisted_blocks_label",
    ):
        if pit_policy.get(field) is not True:
            failures.append(
                "outcome_labeling_readiness.stock_price_proxy_readiness."
                f"pit_realism_policy.{field}: must be true"
            )
    if pit_policy.get("company_name_fuzzy_mapping_enabled") is not False:
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "pit_realism_policy.company_name_fuzzy_mapping_enabled: must be false"
        )
    if pit_policy.get("benchmark_alignment") != "date_key_cross_qlib_dir":
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "pit_realism_policy.benchmark_alignment: must be date_key_cross_qlib_dir"
        )
    survivorship_unverified = pit_policy.get("survivorship_unverified")
    survivorship_status = str(pit_policy.get("survivorship_status") or "")
    if survivorship_unverified is True:
        expected_survivorship_status = "survivorship_unverified"
    elif survivorship_unverified is False:
        expected_survivorship_status = STOCK_PROXY_SURVIVORSHIP_AUDITED_CHECK
    else:
        expected_survivorship_status = ""
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "pit_realism_policy.survivorship_unverified: must be boolean"
        )
    if survivorship_status != expected_survivorship_status:
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "pit_realism_policy.survivorship_status: expected "
            + expected_survivorship_status
        )
    survivorship_basis = str(pit_policy.get("survivorship_basis") or "")
    if survivorship_unverified is True and "delisted-inclusive universe audit" not in survivorship_basis:
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "pit_realism_policy.survivorship_basis: must document the delisted-inclusive audit blocker"
        )
    if survivorship_unverified is False and "delisted-inclusive universe audit passed" not in survivorship_basis:
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "pit_realism_policy.survivorship_basis: must document the delisted-inclusive audit pass"
        )

    gap_counts = stock_readiness.get("data_gap_counts")
    if not isinstance(gap_counts, Mapping):
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "data_gap_counts: expected object"
        )
        gap_counts = {}
    for gap_name, value in gap_counts.items():
        parsed = _int_or_none(value)
        if parsed is None or parsed < 0:
            failures.append(
                "outcome_labeling_readiness.stock_price_proxy_readiness."
                f"data_gap_counts.{gap_name}: must be nonnegative integer"
            )
    stock_labels = [
        row for row in outcome_label_rows if row.get("label_type") == "stock_price_proxy"
    ]
    eligible_count = _int_or_none(stock_readiness.get("eligible_claim_count"))
    labelable_count = _int_or_none(
        stock_readiness.get("labelable_forecast_claim_count")
    )
    pending_count = _int_or_none(
        stock_readiness.get("pending_future_forecast_claim_count")
    )
    for field, value in (
        ("eligible_claim_count", eligible_count),
        ("labelable_forecast_claim_count", labelable_count),
        ("pending_future_forecast_claim_count", pending_count),
    ):
        if value is None or value < 0:
            failures.append(
                "outcome_labeling_readiness.stock_price_proxy_readiness."
                f"{field}: expected nonnegative integer"
            )
    if (
        eligible_count is not None
        and labelable_count is not None
        and pending_count is not None
        and labelable_count + pending_count > eligible_count
    ):
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "labelable + pending future counts cannot exceed eligible_claim_count"
        )
    labelable_window_count = _int_or_none(stock_readiness.get("labelable_window_count"))
    if labelable_window_count is None or labelable_window_count < 0:
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "labelable_window_count: expected nonnegative integer"
        )
    elif stock_labels and labelable_window_count != len(stock_labels):
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            f"labelable_window_count: expected {len(stock_labels)}"
        )
    if (
        labelable_count is not None
        and _int_or_none(readiness_report.get("stock_proxy_label_ready_count"))
        != labelable_count
    ):
        failures.append(
            "outcome_labeling_readiness.stock_proxy_label_ready_count mismatch"
        )
    if (
        pending_count is not None
        and _int_or_none(readiness_report.get("stock_proxy_label_pending_count"))
        != pending_count
    ):
        failures.append(
            "outcome_labeling_readiness.stock_proxy_label_pending_count mismatch"
        )
    if _int_or_none(stock_readiness.get("pending_future_window_count")) is None:
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "pending_future_window_count: expected integer"
        )

    coverage_summary = stock_readiness.get("stock_series_coverage_summary")
    if not isinstance(coverage_summary, Mapping):
        failures.append(
            "outcome_labeling_readiness.stock_price_proxy_readiness."
            "stock_series_coverage_summary: expected object"
        )
    else:
        target_count = _int_or_none(coverage_summary.get("target_series_count"))
        missing_count = _int_or_none(
            coverage_summary.get("target_series_missing_count")
        )
        lifecycle_counts = coverage_summary.get("series_lifecycle_status_counts")
        if target_count is None or target_count < 0:
            failures.append(
                "outcome_labeling_readiness.stock_price_proxy_readiness."
                "stock_series_coverage_summary.target_series_count: must be nonnegative integer"
            )
        if missing_count is None or missing_count < 0:
            failures.append(
                "outcome_labeling_readiness.stock_price_proxy_readiness."
                "stock_series_coverage_summary.target_series_missing_count: must be nonnegative integer"
            )
        if target_count == 0 and (labelable_count or 0) > 0:
            failures.append(
                "outcome_labeling_readiness.stock_price_proxy_readiness."
                "stock_series_coverage_summary.target_series_count: cannot be zero when labels exist"
            )
        if isinstance(lifecycle_counts, Mapping):
            lifecycle_total = sum(
                (_int_or_none(value) or 0) for value in lifecycle_counts.values()
            )
            if (
                target_count is not None
                and missing_count is not None
                and lifecycle_total + missing_count != target_count
            ):
                failures.append(
                    "outcome_labeling_readiness.stock_price_proxy_readiness."
                    "stock_series_coverage_summary lifecycle counts must add to target_series_count"
                )

    return len(stock_labels) + (eligible_count or 0), failures


def _validate_macro_asset_proxy_readiness_contract(
    root_path: Path,
    outcome_label_rows: Sequence[Mapping[str, Any]],
) -> tuple[int, list[str]]:
    readiness_report, readiness_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/outcome_labeling_readiness.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
    )
    failures = list(readiness_errors)
    if not readiness_report:
        return 0, failures

    macro_readiness = readiness_report.get("macro_asset_proxy_readiness")
    if not isinstance(macro_readiness, Mapping):
        return 0, [
            *failures,
            "outcome_labeling_readiness.macro_asset_proxy_readiness: expected object",
        ]

    if not str(macro_readiness.get("qlib_etf_dir_configured") or "").startswith(
        "qlib://"
    ):
        failures.append(
            "outcome_labeling_readiness.macro_asset_proxy_readiness."
            "qlib_etf_dir_configured: must use public qlib source label"
        )
    for field, expected in (
        ("outcome_label_source", "pit_macro_asset_etf_price_window"),
        ("benchmark_symbol", MACRO_ASSET_PROXY_BENCHMARK_SYMBOL),
        ("benchmark_source", MACRO_ASSET_PROXY_BENCHMARK_SOURCE),
        ("benchmark_family", MACRO_ASSET_PROXY_BENCHMARK_FAMILY),
        ("cost_model_id", MACRO_ASSET_PROXY_COST_MODEL_ID),
    ):
        if macro_readiness.get(field) != expected:
            failures.append(
                "outcome_labeling_readiness.macro_asset_proxy_readiness."
                f"{field}: must be {expected}"
            )
    if macro_readiness.get("llm_outcome_labeling_allowed") is not False:
        failures.append(
            "outcome_labeling_readiness.macro_asset_proxy_readiness."
            "llm_outcome_labeling_allowed: must be false"
        )
    if _int_or_none(macro_readiness.get("entry_lag_trading_days")) != 1:
        failures.append(
            "outcome_labeling_readiness.macro_asset_proxy_readiness."
            "entry_lag_trading_days: must be 1"
        )
    if tuple(_int_items(macro_readiness.get("windows_days"))) != (90, 180, 360):
        failures.append(
            "outcome_labeling_readiness.macro_asset_proxy_readiness."
            "windows_days: must be [90, 180, 360]"
        )

    mapping_policy = macro_readiness.get("mapping_policy")
    if not isinstance(mapping_policy, Mapping):
        failures.append(
            "outcome_labeling_readiness.macro_asset_proxy_readiness."
            "mapping_policy: expected object"
        )
        mapping_policy = {}
    if mapping_policy.get("crude_oil_mapping_enabled") is not False:
        failures.append(
            "outcome_labeling_readiness.macro_asset_proxy_readiness."
            "mapping_policy.crude_oil_mapping_enabled: must be false"
        )
    if _int_or_none(mapping_policy.get("mapping_count")) != _int_or_none(
        macro_readiness.get("mapping_count")
    ):
        failures.append(
            "outcome_labeling_readiness.macro_asset_proxy_readiness."
            "mapping_policy.mapping_count mismatch"
        )

    gap_counts = macro_readiness.get("data_gap_counts")
    if not isinstance(gap_counts, Mapping):
        failures.append(
            "outcome_labeling_readiness.macro_asset_proxy_readiness."
            "data_gap_counts: expected object"
        )
        gap_counts = {}
    for gap_name, value in gap_counts.items():
        parsed = _int_or_none(value)
        if parsed is None or parsed < 0:
            failures.append(
                "outcome_labeling_readiness.macro_asset_proxy_readiness."
                f"data_gap_counts.{gap_name}: must be nonnegative integer"
            )

    macro_labels = [
        row for row in outcome_label_rows if row.get("label_type") == "macro_asset_proxy"
    ]
    eligible_count = _int_or_none(macro_readiness.get("eligible_claim_count"))
    labelable_count = _int_or_none(
        macro_readiness.get("labelable_forecast_claim_count")
    )
    pending_count = _int_or_none(
        macro_readiness.get("pending_future_forecast_claim_count")
    )
    for field, value in (
        ("eligible_claim_count", eligible_count),
        ("labelable_forecast_claim_count", labelable_count),
        ("pending_future_forecast_claim_count", pending_count),
    ):
        if value is None or value < 0:
            failures.append(
                "outcome_labeling_readiness.macro_asset_proxy_readiness."
                f"{field}: expected nonnegative integer"
            )
    if (
        eligible_count is not None
        and labelable_count is not None
        and pending_count is not None
        and labelable_count + pending_count > eligible_count
    ):
        failures.append(
            "outcome_labeling_readiness.macro_asset_proxy_readiness."
            "labelable + pending future counts cannot exceed eligible_claim_count"
        )
    labelable_window_count = _int_or_none(macro_readiness.get("labelable_window_count"))
    if labelable_window_count is None or labelable_window_count < 0:
        failures.append(
            "outcome_labeling_readiness.macro_asset_proxy_readiness."
            "labelable_window_count: expected nonnegative integer"
        )
    elif macro_labels and labelable_window_count != len(macro_labels):
        failures.append(
            "outcome_labeling_readiness.macro_asset_proxy_readiness."
            f"labelable_window_count: expected {len(macro_labels)}"
        )
    if (
        labelable_count is not None
        and _int_or_none(readiness_report.get("macro_proxy_label_ready_count"))
        != labelable_count
    ):
        failures.append(
            "outcome_labeling_readiness.macro_proxy_label_ready_count mismatch"
        )
    if (
        pending_count is not None
        and _int_or_none(readiness_report.get("macro_proxy_label_pending_count"))
        != pending_count
    ):
        failures.append(
            "outcome_labeling_readiness.macro_proxy_label_pending_count mismatch"
        )

    return len(macro_labels) + (eligible_count or 0), failures


def _validate_macro_series_directional_readiness_contract(
    root_path: Path,
    outcome_label_rows: Sequence[Mapping[str, Any]],
) -> tuple[int, list[str]]:
    readiness_report, readiness_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/outcome_labeling_readiness.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
    )
    failures = list(readiness_errors)
    if not readiness_report:
        return 0, failures
    series_readiness = readiness_report.get("macro_series_directional_readiness")
    if series_readiness is None:
        return 0, failures
    if not isinstance(series_readiness, Mapping):
        return 0, [
            *failures,
            "outcome_labeling_readiness.macro_series_directional_readiness: expected object",
        ]
    for field, expected in (
        ("outcome_label_source", MACRO_SERIES_DIRECTIONAL_OUTCOME_LABEL_SOURCE),
        ("cost_model_id", MACRO_SERIES_DIRECTIONAL_COST_MODEL_ID),
    ):
        if series_readiness.get(field) != expected:
            failures.append(
                "outcome_labeling_readiness.macro_series_directional_readiness."
                f"{field}: must be {expected}"
            )
    if series_readiness.get("llm_outcome_labeling_allowed") is not False:
        failures.append(
            "outcome_labeling_readiness.macro_series_directional_readiness."
            "llm_outcome_labeling_allowed: must be false"
        )
    if _int_or_none(series_readiness.get("entry_lag_observations")) != 1:
        failures.append(
            "outcome_labeling_readiness.macro_series_directional_readiness."
            "entry_lag_observations: must be 1"
        )
    if tuple(_int_items(series_readiness.get("windows_days"))) != (90, 180, 360):
        failures.append(
            "outcome_labeling_readiness.macro_series_directional_readiness."
            "windows_days: must be [90, 180, 360]"
        )
    mapping_policy = series_readiness.get("mapping_policy")
    if not isinstance(mapping_policy, Mapping):
        failures.append(
            "outcome_labeling_readiness.macro_series_directional_readiness."
            "mapping_policy: expected object"
        )
        mapping_policy = {}
    if mapping_policy.get("etf_proxy_inversion_allowed") is not False:
        failures.append(
            "outcome_labeling_readiness.macro_series_directional_readiness."
            "mapping_policy.etf_proxy_inversion_allowed: must be false"
        )
    gap_counts = series_readiness.get("data_gap_counts")
    if not isinstance(gap_counts, Mapping):
        failures.append(
            "outcome_labeling_readiness.macro_series_directional_readiness."
            "data_gap_counts: expected object"
        )
        gap_counts = {}
    for gap_name, value in gap_counts.items():
        parsed = _int_or_none(value)
        if parsed is None or parsed < 0:
            failures.append(
                "outcome_labeling_readiness.macro_series_directional_readiness."
                f"data_gap_counts.{gap_name}: must be nonnegative integer"
            )
    series_labels = [
        row
        for row in outcome_label_rows
        if row.get("label_type") == "macro_series_directional"
    ]
    eligible_count = _int_or_none(series_readiness.get("eligible_claim_count"))
    labelable_count = _int_or_none(
        series_readiness.get("labelable_forecast_claim_count")
    )
    pending_count = _int_or_none(
        series_readiness.get("pending_future_forecast_claim_count")
    )
    for field, value in (
        ("eligible_claim_count", eligible_count),
        ("labelable_forecast_claim_count", labelable_count),
        ("pending_future_forecast_claim_count", pending_count),
    ):
        if value is None or value < 0:
            failures.append(
                "outcome_labeling_readiness.macro_series_directional_readiness."
                f"{field}: expected nonnegative integer"
            )
    if (
        eligible_count is not None
        and labelable_count is not None
        and pending_count is not None
        and labelable_count + pending_count > eligible_count
    ):
        failures.append(
            "outcome_labeling_readiness.macro_series_directional_readiness."
            "labelable + pending future counts cannot exceed eligible_claim_count"
        )
    labelable_window_count = _int_or_none(
        series_readiness.get("labelable_window_count")
    )
    if labelable_window_count is None or labelable_window_count < 0:
        failures.append(
            "outcome_labeling_readiness.macro_series_directional_readiness."
            "labelable_window_count: expected nonnegative integer"
        )
    elif series_labels and labelable_window_count != len(series_labels):
        failures.append(
            "outcome_labeling_readiness.macro_series_directional_readiness."
            f"labelable_window_count: expected {len(series_labels)}"
        )
    if (
        labelable_count is not None
        and _int_or_none(readiness_report.get("macro_series_label_ready_count"))
        != labelable_count
    ):
        failures.append(
            "outcome_labeling_readiness.macro_series_label_ready_count mismatch"
        )
    if (
        pending_count is not None
        and _int_or_none(readiness_report.get("macro_series_label_pending_count"))
        != pending_count
    ):
        failures.append(
            "outcome_labeling_readiness.macro_series_label_pending_count mismatch"
        )
    return len(series_labels) + (eligible_count or 0), failures


def _validate_macro_curve_directional_readiness_contract(
    root_path: Path,
    outcome_label_rows: Sequence[Mapping[str, Any]],
) -> tuple[int, list[str]]:
    readiness_report, readiness_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/outcome_labeling_readiness.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
    )
    failures = list(readiness_errors)
    if not readiness_report:
        return 0, failures
    curve_readiness = readiness_report.get("macro_curve_directional_readiness")
    if curve_readiness is None:
        return 0, failures
    if not isinstance(curve_readiness, Mapping):
        return 0, [
            *failures,
            "outcome_labeling_readiness.macro_curve_directional_readiness: expected object",
        ]
    for field, expected in (
        ("outcome_label_source", MACRO_CURVE_DIRECTIONAL_OUTCOME_LABEL_SOURCE),
        ("cost_model_id", MACRO_CURVE_DIRECTIONAL_COST_MODEL_ID),
    ):
        if curve_readiness.get(field) != expected:
            failures.append(
                "outcome_labeling_readiness.macro_curve_directional_readiness."
                f"{field}: must be {expected}"
            )
    if curve_readiness.get("llm_outcome_labeling_allowed") is not False:
        failures.append(
            "outcome_labeling_readiness.macro_curve_directional_readiness."
            "llm_outcome_labeling_allowed: must be false"
        )
    if _int_or_none(curve_readiness.get("entry_lag_observations")) != 1:
        failures.append(
            "outcome_labeling_readiness.macro_curve_directional_readiness."
            "entry_lag_observations: must be 1"
        )
    if tuple(_int_items(curve_readiness.get("windows_days"))) != (90, 180, 360):
        failures.append(
            "outcome_labeling_readiness.macro_curve_directional_readiness."
            "windows_days: must be [90, 180, 360]"
        )
    mapping_policy = curve_readiness.get("mapping_policy")
    if not isinstance(mapping_policy, Mapping):
        failures.append(
            "outcome_labeling_readiness.macro_curve_directional_readiness."
            "mapping_policy: expected object"
        )
        mapping_policy = {}
    if mapping_policy.get("single_series_substitution_allowed") is not False:
        failures.append(
            "outcome_labeling_readiness.macro_curve_directional_readiness."
            "mapping_policy.single_series_substitution_allowed: must be false"
        )
    curve_labels = [
        row
        for row in outcome_label_rows
        if row.get("label_type") == "macro_curve_directional"
    ]
    eligible_count = _int_or_none(curve_readiness.get("eligible_claim_count"))
    labelable_count = _int_or_none(
        curve_readiness.get("labelable_forecast_claim_count")
    )
    pending_count = _int_or_none(
        curve_readiness.get("pending_future_forecast_claim_count")
    )
    for field, value in (
        ("eligible_claim_count", eligible_count),
        ("labelable_forecast_claim_count", labelable_count),
        ("pending_future_forecast_claim_count", pending_count),
    ):
        if value is None or value < 0:
            failures.append(
                "outcome_labeling_readiness.macro_curve_directional_readiness."
                f"{field}: expected nonnegative integer"
            )
    if (
        eligible_count is not None
        and labelable_count is not None
        and pending_count is not None
        and labelable_count + pending_count > eligible_count
    ):
        failures.append(
            "outcome_labeling_readiness.macro_curve_directional_readiness."
            "labelable + pending future counts cannot exceed eligible_claim_count"
        )
    labelable_window_count = _int_or_none(
        curve_readiness.get("labelable_window_count")
    )
    if labelable_window_count is None or labelable_window_count < 0:
        failures.append(
            "outcome_labeling_readiness.macro_curve_directional_readiness."
            "labelable_window_count: expected nonnegative integer"
        )
    elif curve_labels and labelable_window_count != len(curve_labels):
        failures.append(
            "outcome_labeling_readiness.macro_curve_directional_readiness."
            f"labelable_window_count: expected {len(curve_labels)}"
        )
    if (
        labelable_count is not None
        and _int_or_none(readiness_report.get("macro_curve_label_ready_count"))
        != labelable_count
    ):
        failures.append(
            "outcome_labeling_readiness.macro_curve_label_ready_count mismatch"
        )
    if (
        pending_count is not None
        and _int_or_none(readiness_report.get("macro_curve_label_pending_count"))
        != pending_count
    ):
        failures.append(
            "outcome_labeling_readiness.macro_curve_label_pending_count mismatch"
        )
    return len(curve_labels) + (eligible_count or 0), failures


def _validate_extraction_report_contract(root_path: Path) -> tuple[int, list[str]]:
    extraction_report, extraction_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/extraction_report.json",
        "registry/report_intelligence/extraction_report.json",
    )
    failures = list(extraction_errors)
    if not extraction_report:
        return 0, failures

    failures.extend(
        _public_forbidden_text_failures(
            extraction_report,
            path="report_intelligence.extraction_report",
        )
    )
    if extraction_report.get("root") != "<repo_root>":
        failures.append("extraction_report.root: must be <repo_root>")
    blockers = extraction_report.get("blockers")
    if blockers not in ([], ()):
        failures.append("extraction_report.blockers: must be empty for current baseline")
    if _int_or_none(extraction_report.get("blocker_count")) != 0:
        failures.append("extraction_report.blocker_count: must be zero")

    outputs = extraction_report.get("outputs")
    if not isinstance(outputs, Mapping):
        failures.append("extraction_report.outputs: expected object")
        outputs = {}
    for output_name, output_path in outputs.items():
        output_text = str(output_path or "")
        if not output_text.startswith("registry/report_intelligence/"):
            failures.append(
                f"extraction_report.outputs.{output_name}: must stay under registry/report_intelligence"
            )
        if output_text.startswith("/") or ".." in Path(output_text).parts:
            failures.append(
                f"extraction_report.outputs.{output_name}: must be repo-relative"
            )

    item_count = 1
    for count_field, artifact_path in EXTRACTION_REPORT_PUBLIC_JSONL_COUNT_FIELDS:
        rows, row_failures, rows_present = _load_public_semantic_jsonl(
            root_path,
            artifact_path,
        )
        failures.extend(row_failures)
        item_count += len(rows)
        if rows_present and _int_or_none(extraction_report.get(count_field)) != len(rows):
            failures.append(f"extraction_report.{count_field}: expected {len(rows)}")

    markdown_summary, markdown_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/markdown_coverage_summary.json",
        "registry/report_intelligence/markdown_coverage_summary.json",
    )
    failures.extend(markdown_errors)
    if markdown_summary:
        for report_field, summary_field in (
            ("selected_reports", "selected_report_count"),
            ("pdf_ready_count", "pdf_download_ready_count"),
            ("markdown_ready_count", "markdown_ready_count"),
        ):
            if _int_or_none(extraction_report.get(report_field)) != _int_or_none(
                markdown_summary.get(summary_field)
            ):
                failures.append(
                    f"extraction_report.{report_field}: markdown_coverage_summary mismatch"
                )

    readiness_report, readiness_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/outcome_labeling_readiness.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
    )
    failures.extend(readiness_errors)
    if readiness_report:
        industry_readiness = readiness_report.get("industry_etf_proxy_readiness")
        stock_readiness = readiness_report.get("stock_price_proxy_readiness")
        macro_readiness = readiness_report.get("macro_asset_proxy_readiness")
        macro_series_readiness = readiness_report.get(
            "macro_series_directional_readiness"
        )
        macro_curve_readiness = readiness_report.get(
            "macro_curve_directional_readiness"
        )
        if isinstance(industry_readiness, Mapping):
            for report_field, readiness_field in (
                ("industry_etf_proxy_eligible_claim_rows", "eligible_claim_count"),
                (
                    "industry_etf_proxy_labelable_window_rows",
                    "labelable_window_count",
                ),
                (
                    "industry_etf_proxy_pending_window_rows",
                    "pending_future_window_count",
                ),
            ):
                if _int_or_none(extraction_report.get(report_field)) != _int_or_none(
                    industry_readiness.get(readiness_field)
                ):
                    failures.append(
                        f"extraction_report.{report_field}: industry readiness mismatch"
                    )
        else:
            failures.append(
                "outcome_labeling_readiness.industry_etf_proxy_readiness: expected object"
            )
        if isinstance(stock_readiness, Mapping):
            for report_field, readiness_field in (
                ("stock_price_proxy_eligible_claim_rows", "eligible_claim_count"),
                (
                    "stock_price_proxy_labelable_window_rows",
                    "labelable_window_count",
                ),
                (
                    "stock_price_proxy_pending_window_rows",
                    "pending_future_window_count",
                ),
            ):
                if _int_or_none(extraction_report.get(report_field)) != _int_or_none(
                    stock_readiness.get(readiness_field)
                ):
                    failures.append(
                        f"extraction_report.{report_field}: stock readiness mismatch"
                    )
        else:
            failures.append(
                "outcome_labeling_readiness.stock_price_proxy_readiness: expected object"
            )
        if isinstance(macro_readiness, Mapping):
            for report_field, readiness_field in (
                ("macro_asset_proxy_eligible_claim_rows", "eligible_claim_count"),
                (
                    "macro_asset_proxy_labelable_window_rows",
                    "labelable_window_count",
                ),
                (
                    "macro_asset_proxy_pending_window_rows",
                    "pending_future_window_count",
                ),
            ):
                if _int_or_none(extraction_report.get(report_field)) != _int_or_none(
                    macro_readiness.get(readiness_field)
                ):
                    failures.append(
                        f"extraction_report.{report_field}: macro readiness mismatch"
                    )
        else:
            failures.append(
                "outcome_labeling_readiness.macro_asset_proxy_readiness: expected object"
            )
        if isinstance(macro_series_readiness, Mapping):
            for report_field, readiness_field in (
                ("macro_series_directional_eligible_claim_rows", "eligible_claim_count"),
                (
                    "macro_series_directional_labelable_window_rows",
                    "labelable_window_count",
                ),
                (
                    "macro_series_directional_pending_window_rows",
                    "pending_future_window_count",
                ),
            ):
                if _int_or_none(extraction_report.get(report_field)) != _int_or_none(
                    macro_series_readiness.get(readiness_field)
                ):
                    failures.append(
                        f"extraction_report.{report_field}: macro series readiness mismatch"
                    )
        else:
            failures.append(
                "outcome_labeling_readiness.macro_series_directional_readiness: expected object"
            )
        if isinstance(macro_curve_readiness, Mapping):
            for report_field, readiness_field in (
                ("macro_curve_directional_eligible_claim_rows", "eligible_claim_count"),
                (
                    "macro_curve_directional_labelable_window_rows",
                    "labelable_window_count",
                ),
                (
                    "macro_curve_directional_pending_window_rows",
                    "pending_future_window_count",
                ),
            ):
                if _int_or_none(extraction_report.get(report_field)) != _int_or_none(
                    macro_curve_readiness.get(readiness_field)
                ):
                    failures.append(
                        f"extraction_report.{report_field}: macro curve readiness mismatch"
                    )
        else:
            failures.append(
                "outcome_labeling_readiness.macro_curve_directional_readiness: expected object"
            )
    industry_labels = _int_or_none(
        extraction_report.get("industry_etf_proxy_outcome_label_rows")
    )
    stock_labels = _int_or_none(
        extraction_report.get("stock_price_proxy_outcome_label_rows")
    )
    macro_labels = _int_or_none(
        extraction_report.get("macro_asset_proxy_outcome_label_rows")
    )
    macro_series_labels = _int_or_none(
        extraction_report.get("macro_series_directional_outcome_label_rows")
    )
    macro_curve_labels = _int_or_none(
        extraction_report.get("macro_curve_directional_outcome_label_rows")
    )
    outcome_labels = _int_or_none(extraction_report.get("outcome_label_rows"))
    if (
        industry_labels is not None
        and stock_labels is not None
        and macro_labels is not None
        and macro_series_labels is not None
        and macro_curve_labels is not None
        and outcome_labels is not None
        and (
            industry_labels
            + stock_labels
            + macro_labels
            + macro_series_labels
            + macro_curve_labels
        )
        != outcome_labels
    ):
        failures.append(
            "extraction_report.outcome_label_rows: must equal industry + stock + macro proxy + macro direct labels"
        )

    paper_summary, paper_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/recipe_paper_trading_summary.json",
        "registry/report_intelligence/recipe_paper_trading_summary.json",
    )
    failures.extend(paper_errors)
    if paper_summary:
        blocked_count = _int_or_none(paper_summary.get("blocked_count"))
        if blocked_count is not None:
            analysis_rows = _int_or_none(extraction_report.get("analysis_recipe_rows"))
            if analysis_rows is not None and blocked_count > analysis_rows:
                failures.append(
                    "recipe_paper_trading_summary.blocked_count cannot exceed extraction_report.analysis_recipe_rows"
                )

    return item_count, failures


RECIPE_PAPER_TRADING_PROTOCOL_VERSION = "recipe_shadow_paper_trading_v1"
RECIPE_PAPER_TRADING_BENCHMARK_SOURCE = "cn_etf"
RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL = "SH510300"
RECIPE_PAPER_TRADING_COST_MODEL_ID = "single_stock_round_trip_20bps_v1"
RECIPE_PAPER_TRADING_MIN_EFFECTIVE_N = 3.0
RECIPE_PAPER_TRADING_MAX_DRAWDOWN = 0.20
RECIPE_PAPER_TRADING_ALPHA_DECAY_FAIL_STREAK = 2
RECIPE_PAPER_TRADING_MAX_HORIZON_CONCENTRATION = 0.70
RECIPE_PAPER_TRADING_MAX_REGIME_CONCENTRATION = 0.80
RECIPE_PAPER_TRADING_MIN_HORIZON_COUNT = 2
RECIPE_PAPER_TRADING_MIN_REGIME_COUNT = 2
RECIPE_PAPER_TRADING_COST_DECAY_TURNOVER_THRESHOLD = 6.0
RECIPE_PAPER_TRADING_OUT_OF_SAMPLE_FRACTION = 0.20
RECIPE_PAPER_TRADING_MIN_OUT_OF_SAMPLE_EFFECTIVE_N = 1.0
RECIPE_PAPER_TRADING_SLIPPAGE_MODEL_ID = "included_in_round_trip_cost_20bps_v1"
RECIPE_PAPER_TRADING_BACKTEST_WINDOW_POLICY = "chronological_pre_oos_exit_windows_v1"
RECIPE_PAPER_TRADING_OUT_OF_SAMPLE_WINDOW_POLICY = (
    "chronological_last_20pct_min_effective_n_exit_windows_v1"
)
RECIPE_PAPER_TRADING_PARAMETER_LOCK_POLICY = (
    "pre_registration_hash_locks_required_data_protocol_cost_benchmark_windows_v1"
)
CONFIDENCE_IMPACT_HIGH_DELTA_THRESHOLD = 0.02
CONFIDENCE_IMPACT_CALIBRATION_ERROR_THRESHOLD = 0.20
RECIPE_PAPER_TRADING_REQUIRED_METRICS = (
    "annualized_return",
    "benchmark_return",
    "alpha",
    "sharpe",
    "max_drawdown",
    "turnover",
    "hit_rate",
    "effective_n",
    "cost_adjusted_alpha",
    "alpha_decay_slope",
    "calibration_error",
    "drawdown_breach_count",
)
CONFIDENCE_IMPACT_REQUIRED_OBSERVATION_FIELDS = (
    "recipe_id",
    "agent_id",
    "confidence_delta",
    "confidence_delta_source",
    "expected_alpha",
    "realized_alpha",
    "after_cost_realized_alpha",
    "alpha_decay_slope",
    "calibration_error",
    "brier_score",
    "hit_rate_recent",
    "hit_rate_baseline",
    "drawdown_since_activation",
    "regime",
    "regime_status",
    "regime_contribution_shares",
    "max_regime_contribution_share",
    "observed_regime_count",
    "market_regime_missing_count",
    "market_regime_coverage_status",
    "drift_status",
    "recommended_action",
)
SHA256_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def _file_sha256(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _expected_recipe_paper_trading_protocol() -> dict[str, Any]:
    return {
        "entry_semantics": "T+1_or_more_conservative",
        "exit_semantics": "fixed_horizon_shadow_exit",
        "cost_model_id": RECIPE_PAPER_TRADING_COST_MODEL_ID,
        "benchmark_symbol": RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL,
        "benchmark_source": RECIPE_PAPER_TRADING_BENCHMARK_SOURCE,
        "slippage_model_id": RECIPE_PAPER_TRADING_SLIPPAGE_MODEL_ID,
        "round_trip_cost_includes_slippage": True,
        "backtest_window_policy": RECIPE_PAPER_TRADING_BACKTEST_WINDOW_POLICY,
        "out_of_sample_window_policy": (
            RECIPE_PAPER_TRADING_OUT_OF_SAMPLE_WINDOW_POLICY
        ),
        "out_of_sample_fraction": RECIPE_PAPER_TRADING_OUT_OF_SAMPLE_FRACTION,
        "minimum_out_of_sample_effective_n": (
            RECIPE_PAPER_TRADING_MIN_OUT_OF_SAMPLE_EFFECTIVE_N
        ),
        "parameter_lock_policy": RECIPE_PAPER_TRADING_PARAMETER_LOCK_POLICY,
        "minimum_effective_n": RECIPE_PAPER_TRADING_MIN_EFFECTIVE_N,
        "max_drawdown": RECIPE_PAPER_TRADING_MAX_DRAWDOWN,
        "alpha_decay_fail_streak": RECIPE_PAPER_TRADING_ALPHA_DECAY_FAIL_STREAK,
        "max_horizon_contribution_share": (
            RECIPE_PAPER_TRADING_MAX_HORIZON_CONCENTRATION
        ),
        "max_regime_contribution_share": (
            RECIPE_PAPER_TRADING_MAX_REGIME_CONCENTRATION
        ),
        "minimum_horizon_count": RECIPE_PAPER_TRADING_MIN_HORIZON_COUNT,
        "minimum_regime_count": RECIPE_PAPER_TRADING_MIN_REGIME_COUNT,
        "cost_decay_turnover_threshold": (
            RECIPE_PAPER_TRADING_COST_DECAY_TURNOVER_THRESHOLD
        ),
        "profile_weight_is_sufficient": False,
        "parameter_tuning_after_results_allowed": False,
        "production_decision_impact_allowed": False,
    }


def _normalize_required_data_items(value: Any) -> list[str]:
    return normalize_required_data_items(_string_items(value))


def _recipe_preregistration_payload_from_run(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "analysis_recipe_id": str(row.get("analysis_recipe_id") or ""),
        "promotion_state": str(row.get("promotion_state") or ""),
        "protocol_version": str(row.get("protocol_version") or ""),
        "source_method_pattern_ids": _string_items(row.get("source_method_pattern_ids")),
        "required_tools": _string_items(row.get("required_tools")),
        "required_data": _normalize_required_data_items(row.get("required_data")),
        "decision_scope": str(row.get("decision_scope") or ""),
        "entry_condition": str(row.get("entry_condition") or ""),
        "exit_condition": str(row.get("exit_condition") or ""),
        "risk_controls": _string_items(row.get("risk_controls")),
        "expected_horizon_days": _int_or_none(row.get("expected_horizon_days")),
        "benchmark_symbol": str(row.get("benchmark_symbol") or ""),
        "benchmark_source": str(row.get("benchmark_source") or ""),
        "cost_model_id": str(row.get("cost_model_id") or ""),
        "pre_registered_protocol": dict(
            row.get("pre_registered_protocol")
            if isinstance(row.get("pre_registered_protocol"), Mapping)
            else {}
        ),
        "production_decision_impact_allowed": False,
    }


def _recipe_preregistration_hash_from_run(row: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _jsonable(_recipe_preregistration_payload_from_run(row)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _recipe_contract_stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}-{sha256(encoded).hexdigest()[:16]}"


def _confidence_contract_pearson_correlation(
    pairs: Sequence[tuple[float, float]],
) -> float | None:
    if len(pairs) < 2:
        return None
    xs = [item[0] for item in pairs]
    ys = [item[1] for item in pairs]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    x_var = sum((value - x_mean) ** 2 for value in xs)
    y_var = sum((value - y_mean) ** 2 for value in ys)
    if x_var <= 0 or y_var <= 0:
        return None
    covariance = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    return covariance / ((x_var * y_var) ** 0.5)


def _confidence_contract_delta_bucket(delta: float | None) -> str:
    if delta is None or delta == 0:
        return "zero"
    if delta < 0:
        return "negative"
    if delta >= CONFIDENCE_IMPACT_HIGH_DELTA_THRESHOLD:
        return "high_positive"
    return "low_positive"


def _confidence_contract_bucket_outcome_summary(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        delta = _float_or_none(row.get("confidence_delta"))
        bucket = _confidence_contract_delta_bucket(delta)
        item = grouped.setdefault(
            bucket,
            {
                "count": 0,
                "realized_alpha_values": [],
                "hit_rate_values": [],
            },
        )
        item["count"] += 1
        realized_alpha = _float_or_none(
            row.get("after_cost_realized_alpha")
            if row.get("after_cost_realized_alpha") is not None
            else row.get("realized_alpha")
        )
        hit_rate = _float_or_none(row.get("hit_rate_recent"))
        if realized_alpha is not None:
            item["realized_alpha_values"].append(realized_alpha)
        if hit_rate is not None:
            item["hit_rate_values"].append(hit_rate)
    summary: dict[str, dict[str, Any]] = {}
    for bucket, item in grouped.items():
        alpha_values = item["realized_alpha_values"]
        hit_values = item["hit_rate_values"]
        summary[bucket] = {
            "count": int(item["count"]),
            "mean_realized_alpha": (
                round(sum(alpha_values) / len(alpha_values), 8)
                if alpha_values
                else None
            ),
            "mean_hit_rate": (
                round(sum(hit_values) / len(hit_values), 6) if hit_values else None
            ),
        }
    return dict(sorted(summary.items()))


def _confidence_contract_is_new_regime(row: Mapping[str, Any]) -> bool:
    if row.get("regime_is_new") is True:
        return True
    regime_status = str(row.get("regime_status") or "").strip().lower()
    return regime_status in {"new", "new_regime", "unseen_regime"}


def _validate_recipe_paper_trading_contract(
    root_path: Path,
) -> tuple[int, list[str]]:
    run_rows, run_failures, run_rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/recipe_paper_trading_runs.jsonl",
    )
    (
        confidence_rows,
        confidence_failures,
        _confidence_rows_present,
    ) = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/confidence_impact_observations.jsonl",
    )
    monitor, monitor_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/confidence_impact_monitor.json",
        "registry/report_intelligence/confidence_impact_monitor.json",
    )
    summary, summary_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/recipe_paper_trading_summary.json",
        "registry/report_intelligence/recipe_paper_trading_summary.json",
    )
    failures = [
        *run_failures,
        *confidence_failures,
        *monitor_failures,
        *summary_failures,
    ]
    item_count = (
        len(run_rows)
        + len(confidence_rows)
        + (1 if monitor else 0)
        + (1 if summary else 0)
    )

    runs_by_recipe_id: dict[str, Mapping[str, Any]] = {}
    paper_trading_run_ids: dict[str, str] = {}
    experiment_ids: dict[str, str] = {}
    recipe_instability_gap_blocker = "recipe_instability_gap"
    recipe_instability_source_blockers = {
        "window_horizon_missing",
        "single_window_concentration",
        "market_regime_missing",
        "single_regime_concentration",
    }
    passed_recipe_ids: list[str] = []
    blocked_recipe_ids: list[str] = []
    status_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    disagreement_count = 0
    instability_gap_count = 0
    cost_adjusted_values: list[float] = []

    for index, row in enumerate(run_rows, 1):
        row_label = f"recipe_paper_trading_runs row {index}"
        recipe_id = str(row.get("analysis_recipe_id") or "").strip()
        paper_trading_run_id = str(row.get("paper_trading_run_id") or "").strip()
        experiment_id = str(row.get("experiment_id") or "").strip()
        if not recipe_id:
            failures.append(f"{row_label}.analysis_recipe_id: required")
        elif recipe_id in runs_by_recipe_id:
            failures.append(f"{row_label}.analysis_recipe_id: duplicate {recipe_id}")
        else:
            runs_by_recipe_id[recipe_id] = row
        if not paper_trading_run_id:
            failures.append(f"{row_label}.paper_trading_run_id: required")
        elif paper_trading_run_id in paper_trading_run_ids:
            failures.append(
                f"{row_label}.paper_trading_run_id: duplicate {paper_trading_run_id}"
            )
        else:
            paper_trading_run_ids[paper_trading_run_id] = recipe_id
        if not experiment_id:
            failures.append(f"{row_label}.experiment_id: required")
        elif experiment_id in experiment_ids:
            failures.append(f"{row_label}.experiment_id: duplicate {experiment_id}")
        else:
            experiment_ids[experiment_id] = recipe_id

        status = str(row.get("paper_trading_status") or "")
        validation_status = str(row.get("validation_status") or "")
        if status not in {"passed", "blocked"}:
            failures.append(
                f"{row_label}.paper_trading_status: must be passed or blocked"
            )
        else:
            status_counts[status] = status_counts.get(status, 0) + 1
            if recipe_id:
                if status == "passed":
                    passed_recipe_ids.append(recipe_id)
                else:
                    blocked_recipe_ids.append(recipe_id)
        if validation_status != status:
            failures.append(
                f"{row_label}.validation_status: must match paper_trading_status"
            )
        if row.get("production_decision_impact_allowed") is not False:
            failures.append(
                f"{row_label}.production_decision_impact_allowed: must be false"
            )
        if row.get("promotion_state") != "shadow_candidate":
            failures.append(f"{row_label}.promotion_state: must be shadow_candidate")
        if row.get("protocol_version") != RECIPE_PAPER_TRADING_PROTOCOL_VERSION:
            failures.append(
                f"{row_label}.protocol_version: must be {RECIPE_PAPER_TRADING_PROTOCOL_VERSION}"
            )
        if recipe_id:
            expected_run_id = _recipe_contract_stable_id(
                "RIPT",
                {
                    "analysis_recipe_id": recipe_id,
                    "protocol_version": RECIPE_PAPER_TRADING_PROTOCOL_VERSION,
                },
            )
            if paper_trading_run_id and paper_trading_run_id != expected_run_id:
                failures.append(
                    f"{row_label}.paper_trading_run_id: must bind analysis_recipe_id and protocol_version"
                )
            expected_experiment_id = _recipe_contract_stable_id(
                "RIEXP",
                {
                    "analysis_recipe_id": recipe_id,
                    "protocol_version": RECIPE_PAPER_TRADING_PROTOCOL_VERSION,
                },
            )
            if experiment_id and experiment_id != expected_experiment_id:
                failures.append(
                    f"{row_label}.experiment_id: must bind analysis_recipe_id and protocol_version"
                )
        if row.get("benchmark_source") != RECIPE_PAPER_TRADING_BENCHMARK_SOURCE:
            failures.append(
                f"{row_label}.benchmark_source: must be {RECIPE_PAPER_TRADING_BENCHMARK_SOURCE}"
            )
        if row.get("benchmark_symbol") != RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL:
            failures.append(
                f"{row_label}.benchmark_symbol: must be {RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL}"
            )
        if row.get("cost_model_id") != RECIPE_PAPER_TRADING_COST_MODEL_ID:
            failures.append(
                f"{row_label}.cost_model_id: must be {RECIPE_PAPER_TRADING_COST_MODEL_ID}"
            )
        if row.get("entry_condition") != "T+1_or_more_conservative_shadow_entry":
            failures.append(
                f"{row_label}.entry_condition: must be T+1_or_more_conservative_shadow_entry"
            )
        if row.get("exit_condition") != "fixed_horizon_shadow_exit":
            failures.append(
                f"{row_label}.exit_condition: must be fixed_horizon_shadow_exit"
            )
        required_data = _string_items(row.get("required_data"))
        normalized_required_data = _normalize_required_data_items(required_data)
        if required_data != normalized_required_data:
            failures.append(
                f"{row_label}.required_data: must persist normalized metric:<canonical> items"
            )
        preregistration_hash = str(row.get("pre_registration_hash") or "")
        if not SHA256_DIGEST_PATTERN.fullmatch(preregistration_hash):
            failures.append(
                f"{row_label}.pre_registration_hash: expected sha256 digest"
            )

        protocol = row.get("pre_registered_protocol")
        if not isinstance(protocol, Mapping):
            failures.append(f"{row_label}.pre_registered_protocol: expected object")
            protocol = {}
        expected_protocol = _expected_recipe_paper_trading_protocol()
        for protocol_field, expected_value in expected_protocol.items():
            observed_value = protocol.get(protocol_field)
            if isinstance(expected_value, float):
                observed_float = _float_or_none(observed_value)
                if observed_float is None or not _nearly_equal(
                    observed_float,
                    expected_value,
                ):
                    failures.append(
                        f"{row_label}.pre_registered_protocol.{protocol_field}: "
                        f"must be {expected_value}"
                    )
            elif observed_value != expected_value:
                failures.append(
                    f"{row_label}.pre_registered_protocol.{protocol_field}: "
                    f"must be {expected_value}"
                )
        if protocol.get("cost_model_id") != row.get("cost_model_id"):
            failures.append(
                f"{row_label}.pre_registered_protocol.cost_model_id: must match row cost_model_id"
            )
        if protocol.get("benchmark_symbol") != row.get("benchmark_symbol"):
            failures.append(
                f"{row_label}.pre_registered_protocol.benchmark_symbol: must match row benchmark_symbol"
            )
        if protocol.get("benchmark_source") != row.get("benchmark_source"):
            failures.append(
                f"{row_label}.pre_registered_protocol.benchmark_source: must match row benchmark_source"
            )
        if SHA256_DIGEST_PATTERN.fullmatch(preregistration_hash):
            expected_hash = _recipe_preregistration_hash_from_run(row)
            if preregistration_hash != expected_hash:
                failures.append(
                    f"{row_label}.pre_registration_hash: mismatch with pre-registered protocol payload"
                )

        metrics = row.get("metrics")
        if not isinstance(metrics, Mapping):
            failures.append(f"{row_label}.metrics: expected object")
            metrics = {}
        for metric_field in RECIPE_PAPER_TRADING_REQUIRED_METRICS:
            if metric_field not in metrics:
                failures.append(f"{row_label}.metrics.{metric_field}: required")
        effective_n = _float_or_none(metrics.get("effective_n"))
        out_of_sample_effective_n = _float_or_none(
            metrics.get("out_of_sample_effective_n")
        )
        out_of_sample_alpha = _float_or_none(
            metrics.get("out_of_sample_cost_adjusted_alpha")
        )
        minimum_effective_n = _float_or_none(protocol.get("minimum_effective_n"))
        minimum_out_of_sample_n = _float_or_none(
            protocol.get("minimum_out_of_sample_effective_n")
        )
        cost_adjusted_alpha = _float_or_none(metrics.get("cost_adjusted_alpha"))
        if cost_adjusted_alpha is not None:
            cost_adjusted_values.append(cost_adjusted_alpha)
        blocked_reasons = _string_items(row.get("blocked_reasons"))
        for reason in blocked_reasons:
            blocker_counts[reason] = blocker_counts.get(reason, 0) + 1
        has_instability_source = bool(
            recipe_instability_source_blockers.intersection(blocked_reasons)
        )
        has_instability_gap = recipe_instability_gap_blocker in blocked_reasons
        if has_instability_gap:
            instability_gap_count += 1
        if has_instability_source and not has_instability_gap:
            failures.append(
                f"{row_label}.blocked_reasons: instability blockers require recipe_instability_gap"
            )
        if has_instability_gap and not has_instability_source:
            failures.append(
                f"{row_label}.blocked_reasons: recipe_instability_gap requires a named instability blocker"
            )

        if status == "passed":
            if blocked_reasons:
                failures.append(
                    f"{row_label}.blocked_reasons: passed run must have no blockers"
                )
            if cost_adjusted_alpha is None or cost_adjusted_alpha <= 0:
                failures.append(
                    f"{row_label}.metrics.cost_adjusted_alpha: passed run requires positive after-cost alpha"
                )
            if (
                minimum_effective_n is not None
                and (effective_n is None or effective_n < minimum_effective_n)
            ):
                failures.append(
                    f"{row_label}.metrics.effective_n: passed run must meet pre-registered minimum"
                )
            if (
                minimum_out_of_sample_n is not None
                and (
                    out_of_sample_effective_n is None
                    or out_of_sample_effective_n < minimum_out_of_sample_n
                )
            ):
                failures.append(
                    f"{row_label}.metrics.out_of_sample_effective_n: passed run must meet pre-registered OOS minimum"
                )
            if out_of_sample_alpha is None or out_of_sample_alpha <= 0:
                failures.append(
                    f"{row_label}.metrics.out_of_sample_cost_adjusted_alpha: passed run requires positive OOS after-cost alpha"
                )
        elif status == "blocked" and not blocked_reasons:
            failures.append(
                f"{row_label}.blocked_reasons: blocked run requires at least one blocker"
            )

        profile_support = row.get("profile_weight_support")
        if isinstance(profile_support, Mapping):
            if profile_support.get("profile_only_validation_allowed") is not False:
                failures.append(
                    f"{row_label}.profile_weight_support.profile_only_validation_allowed: must be false"
                )
            if profile_support.get("profile_paper_trade_disagreement") is True:
                disagreement_count += 1

    if summary and run_rows_present:
        expected_count_fields = {
            "recipe_count": len(run_rows),
            "paper_trading_run_count": len(run_rows),
            "validation_pass_count": len(passed_recipe_ids),
            "paper_trading_validated_recipe_count": len(passed_recipe_ids),
            "blocked_count": len(blocked_recipe_ids),
            "profile_paper_trade_disagreement_count": disagreement_count,
            "recipe_instability_gap_count": instability_gap_count,
        }
        for field, expected in expected_count_fields.items():
            if summary.get(field) != expected:
                failures.append(
                    f"recipe_paper_trading_summary.{field}: expected {expected}"
                )
        expected_status_counts = dict(sorted(status_counts.items()))
        observed_status_counts = _count_mapping(
            summary.get("status_counts"),
            row_label="recipe_paper_trading_summary.status_counts",
            failures=failures,
        )
        if observed_status_counts != expected_status_counts:
            failures.append("recipe_paper_trading_summary.status_counts mismatch")
        expected_blocker_counts = dict(sorted(blocker_counts.items()))
        observed_blocker_counts = _count_mapping(
            summary.get("blocker_counts"),
            row_label="recipe_paper_trading_summary.blocker_counts",
            failures=failures,
        )
        if observed_blocker_counts != expected_blocker_counts:
            failures.append("recipe_paper_trading_summary.blocker_counts mismatch")
        expected_mean = (
            round(sum(cost_adjusted_values) / len(cost_adjusted_values), 8)
            if cost_adjusted_values
            else None
        )
        observed_mean = _float_or_none(summary.get("mean_cost_adjusted_alpha"))
        if expected_mean is None:
            if summary.get("mean_cost_adjusted_alpha") is not None:
                failures.append(
                    "recipe_paper_trading_summary.mean_cost_adjusted_alpha: expected null"
                )
        elif observed_mean is None or not _nearly_equal(
            observed_mean,
            expected_mean,
            tolerance=1e-8,
        ):
            failures.append(
                "recipe_paper_trading_summary.mean_cost_adjusted_alpha mismatch"
            )
        validation_protocol = summary.get("validation_protocol")
        if not isinstance(validation_protocol, Mapping):
            failures.append(
                "recipe_paper_trading_summary.validation_protocol: expected object"
            )
            validation_protocol = {}
        expected_protocol = _expected_recipe_paper_trading_protocol()
        for protocol_field, expected_value in expected_protocol.items():
            observed_value = validation_protocol.get(protocol_field)
            if isinstance(expected_value, float):
                observed_float = _float_or_none(observed_value)
                if observed_float is None or not _nearly_equal(
                    observed_float,
                    expected_value,
                ):
                    failures.append(
                        "recipe_paper_trading_summary.validation_protocol."
                        f"{protocol_field}: must be {expected_value}"
                    )
            elif observed_value != expected_value:
                failures.append(
                    "recipe_paper_trading_summary.validation_protocol."
                    f"{protocol_field}: must be {expected_value}"
                )
        for field in ("profile_weight_is_sufficient", "production_decision_impact_allowed"):
            if validation_protocol.get(field) is not False:
                failures.append(
                    f"recipe_paper_trading_summary.validation_protocol.{field}: must be false"
                )

    confidence_by_recipe_id: dict[str, Mapping[str, Any]] = {}
    confidence_action_counts: dict[str, int] = {}
    confidence_drift_counts: dict[str, int] = {}
    confidence_blocker_counts: dict[str, int] = {}
    confidence_tracked_recipe_ids: list[str] = []
    reduce_confidence_recipe_ids: list[str] = []
    manual_review_recipe_ids: list[str] = []
    freeze_recipe_ids: list[str] = []
    retire_recipe_ids: list[str] = []
    alpha_decay_recipe_ids: list[str] = []
    cost_decay_recipe_ids: list[str] = []
    calibration_drift_recipe_ids: list[str] = []
    aggregate_calibration_recipe_ids: list[str] = []
    new_regime_miscalibration_recipe_ids: list[str] = []
    regime_fragile_recipe_ids: list[str] = []
    profile_paper_trade_disagreement_recipe_ids: list[str] = []
    calibration_rule_counts: dict[str, int] = {}
    confidence_alpha_pairs: list[tuple[float, float]] = []
    confidence_alpha_pair_recipe_ids: list[str] = []
    unvalidated_impact_count = 0
    confidence_observation_ids: dict[str, str] = {}
    for index, row in enumerate(confidence_rows, 1):
        row_label = f"confidence_impact_observations row {index}"
        for field in CONFIDENCE_IMPACT_REQUIRED_OBSERVATION_FIELDS:
            if field not in row:
                failures.append(f"{row_label}.{field}: required")
        recipe_id = str(row.get("recipe_id") or "").strip()
        observation_id = str(row.get("confidence_observation_id") or "").strip()
        if not recipe_id:
            failures.append(f"{row_label}.recipe_id: required")
            continue
        if not observation_id:
            failures.append(f"{row_label}.confidence_observation_id: required")
        elif observation_id in confidence_observation_ids:
            failures.append(
                f"{row_label}.confidence_observation_id: duplicate {observation_id}"
            )
        else:
            confidence_observation_ids[observation_id] = recipe_id
        expected_observation_id = _recipe_contract_stable_id(
            "CIMOBS",
            {
                "run_id": str(row.get("run_id") or ""),
                "analysis_recipe_id": recipe_id,
            },
        )
        if observation_id and observation_id != expected_observation_id:
            failures.append(
                f"{row_label}.confidence_observation_id: must bind run_id and recipe_id"
            )
        confidence_tracked_recipe_ids.append(recipe_id)
        if recipe_id in confidence_by_recipe_id:
            failures.append(f"{row_label}.recipe_id: duplicate {recipe_id}")
        else:
            confidence_by_recipe_id[recipe_id] = row
        run = runs_by_recipe_id.get(recipe_id)
        if run is None:
            failures.append(f"{row_label}.recipe_id: no matching paper-trading run")
            continue
        run_status = str(run.get("paper_trading_status") or "")
        observation_status = str(row.get("paper_trading_status") or "")
        if observation_status != run_status:
            failures.append(
                f"{row_label}.paper_trading_status: mismatch with paper-trading run"
            )
        if row.get("confidence_delta_source") != "recipe_paper_trading_validation":
            failures.append(
                f"{row_label}.confidence_delta_source: must be recipe_paper_trading_validation"
            )
        if row.get("production_decision_impact_allowed") is not False:
            failures.append(
                f"{row_label}.production_decision_impact_allowed: must be false"
            )
        confidence_delta = _float_or_none(row.get("confidence_delta"))
        if confidence_delta is None:
            failures.append(f"{row_label}.confidence_delta: expected number")
        elif run_status != "passed" and not _nearly_equal(confidence_delta, 0.0):
            failures.append(
                f"{row_label}.confidence_delta: blocked or unvalidated recipe must stay zero"
            )
        if run_status != "passed" and (confidence_delta or 0.0) != 0.0:
            unvalidated_impact_count += 1
        realized_alpha = _float_or_none(
            row.get("after_cost_realized_alpha")
            if row.get("after_cost_realized_alpha") is not None
            else row.get("realized_alpha")
        )
        hit_rate_recent = _float_or_none(row.get("hit_rate_recent"))
        hit_rate_baseline = _float_or_none(row.get("hit_rate_baseline"))
        calibration_error = _float_or_none(row.get("calibration_error"))
        if confidence_delta is not None and realized_alpha is not None:
            confidence_alpha_pairs.append((confidence_delta, realized_alpha))
            confidence_alpha_pair_recipe_ids.append(recipe_id)
        if (
            confidence_delta is not None
            and confidence_delta > 0
            and hit_rate_recent is not None
            and hit_rate_baseline is not None
            and hit_rate_recent < hit_rate_baseline
        ):
            calibration_rule_counts["positive_confidence_hit_nonimprovement"] = (
                calibration_rule_counts.get(
                    "positive_confidence_hit_nonimprovement",
                    0,
                )
                + 1
            )
            aggregate_calibration_recipe_ids.append(recipe_id)
        if (
            confidence_delta is not None
            and confidence_delta >= CONFIDENCE_IMPACT_HIGH_DELTA_THRESHOLD
            and (
                (realized_alpha is not None and realized_alpha <= 0)
                or (
                    hit_rate_recent is not None
                    and hit_rate_baseline is not None
                    and hit_rate_recent < hit_rate_baseline
                )
            )
        ):
            calibration_rule_counts["high_confidence_underperformance"] = (
                calibration_rule_counts.get("high_confidence_underperformance", 0)
                + 1
            )
            aggregate_calibration_recipe_ids.append(recipe_id)
        if _confidence_contract_is_new_regime(row) and (
            (
                calibration_error is not None
                and calibration_error > CONFIDENCE_IMPACT_CALIBRATION_ERROR_THRESHOLD
            )
            or (
                hit_rate_recent is not None
                and hit_rate_baseline is not None
                and hit_rate_recent < hit_rate_baseline
            )
            or (realized_alpha is not None and realized_alpha <= 0)
        ):
            calibration_rule_counts["new_regime_miscalibration"] = (
                calibration_rule_counts.get("new_regime_miscalibration", 0) + 1
            )
            aggregate_calibration_recipe_ids.append(recipe_id)
            new_regime_miscalibration_recipe_ids.append(recipe_id)
        drift_status = str(row.get("drift_status") or "")
        recommended_action = str(row.get("recommended_action") or "")
        if drift_status:
            confidence_drift_counts[drift_status] = (
                confidence_drift_counts.get(drift_status, 0) + 1
            )
        if recommended_action:
            confidence_action_counts[recommended_action] = (
                confidence_action_counts.get(recommended_action, 0) + 1
            )
        if (
            confidence_delta is not None
            and confidence_delta > 0
            and (
                run_status != "passed"
                or drift_status != "stable_shadow"
                or recommended_action != "keep_shadow"
            )
        ):
            failures.append(
                f"{row_label}.confidence_delta: positive impact requires passed stable_shadow keep_shadow"
            )
        if run_status != "passed" and recommended_action == "keep_shadow" and (
            drift_status != "paper_trading_blocked"
        ):
            failures.append(
                f"{row_label}.recommended_action: blocked keep_shadow requires paper_trading_blocked drift"
            )
        if (
            recommended_action
            in {
                "reduce_confidence_impact",
                "freeze_recipe",
                "send_to_manual_review",
                "retire_recipe",
            }
            and confidence_delta is not None
            and not _nearly_equal(confidence_delta, 0.0)
        ):
            failures.append(
                f"{row_label}.confidence_delta: mitigation actions must keep impact at zero"
            )
        if run_status != "passed" and row.get("drift_status") == "stable_shadow":
            failures.append(
                f"{row_label}.drift_status: blocked recipe cannot be stable_shadow"
            )
        if sorted(_string_items(row.get("blocker_reasons"))) != sorted(
            _string_items(run.get("blocked_reasons"))
        ):
            failures.append(
                f"{row_label}.blocker_reasons: mismatch with paper-trading run"
            )
        run_metrics_raw = run.get("metrics")
        run_metrics = run_metrics_raw if isinstance(run_metrics_raw, Mapping) else {}
        expected_regime_shares_raw = run_metrics.get("regime_contribution_shares")
        expected_regime_shares_mapping = (
            expected_regime_shares_raw
            if isinstance(expected_regime_shares_raw, Mapping)
            else {}
        )
        observed_regime_shares_raw = row.get("regime_contribution_shares")
        observed_regime_shares_mapping = (
            observed_regime_shares_raw
            if isinstance(observed_regime_shares_raw, Mapping)
            else {}
        )
        expected_regime_shares = {
            str(key): value
            for key, value in expected_regime_shares_mapping.items()
        }
        observed_regime_shares = {
            str(key): value
            for key, value in observed_regime_shares_mapping.items()
        }
        if observed_regime_shares != expected_regime_shares:
            failures.append(
                f"{row_label}.regime_contribution_shares: mismatch with paper-trading run"
            )
        expected_dominant_regime = "unknown"
        numeric_regime_shares = {
            key: float(value)
            for key, value in expected_regime_shares.items()
            if _float_or_none(value) is not None
        }
        if numeric_regime_shares:
            expected_dominant_regime = sorted(
                numeric_regime_shares.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]
        if str(row.get("regime") or "") != expected_dominant_regime:
            failures.append(f"{row_label}.regime: mismatch with paper-trading run")
        for field in (
            "max_regime_contribution_share",
            "observed_regime_count",
            "market_regime_missing_count",
        ):
            if row.get(field) != run_metrics.get(field):
                failures.append(f"{row_label}.{field}: mismatch with paper-trading run")
        expected_regime_coverage_status = (
            run_metrics.get("market_regime_coverage_status") or "unknown"
        )
        if row.get("market_regime_coverage_status") != expected_regime_coverage_status:
            failures.append(
                f"{row_label}.market_regime_coverage_status: mismatch with paper-trading run"
            )
        for reason in _string_items(row.get("blocker_reasons")):
            confidence_blocker_counts[reason] = (
                confidence_blocker_counts.get(reason, 0) + 1
            )
        if recommended_action == "reduce_confidence_impact":
            reduce_confidence_recipe_ids.append(recipe_id)
        if recommended_action == "send_to_manual_review":
            manual_review_recipe_ids.append(recipe_id)
        if recommended_action == "freeze_recipe":
            freeze_recipe_ids.append(recipe_id)
        if recommended_action == "retire_recipe":
            retire_recipe_ids.append(recipe_id)
        if drift_status in {"alpha_decay_watch", "alpha_decay_fail"}:
            alpha_decay_recipe_ids.append(recipe_id)
        if drift_status == "cost_decay_fail":
            cost_decay_recipe_ids.append(recipe_id)
        if drift_status == "calibration_drift_watch":
            calibration_drift_recipe_ids.append(recipe_id)
        if drift_status == "regime_fragile_alpha":
            regime_fragile_recipe_ids.append(recipe_id)
        if drift_status == "profile_paper_trade_disagreement":
            profile_paper_trade_disagreement_recipe_ids.append(recipe_id)

    missing_confidence_ids = sorted(
        set(runs_by_recipe_id) - set(confidence_by_recipe_id)
    )
    if missing_confidence_ids:
        failures.append(
            "confidence_impact_observations missing recipe_ids: "
            + ", ".join(missing_confidence_ids[:20])
        )
    confidence_alpha_correlation = _confidence_contract_pearson_correlation(
        confidence_alpha_pairs
    )
    if confidence_alpha_correlation is not None and confidence_alpha_correlation < 0:
        calibration_rule_counts["negative_confidence_alpha_correlation"] = (
            calibration_rule_counts.get("negative_confidence_alpha_correlation", 0)
            + 1
        )
        aggregate_calibration_recipe_ids.extend(confidence_alpha_pair_recipe_ids)
    aggregate_calibration_recipe_ids = sorted(set(aggregate_calibration_recipe_ids))
    calibration_drift_recipe_ids.extend(aggregate_calibration_recipe_ids)
    manual_review_recipe_ids.extend(aggregate_calibration_recipe_ids)
    if monitor and run_rows_present and _confidence_rows_present:
        expected_monitor_counts = {
            "recipe_count": len(run_rows),
            "observation_count": len(confidence_rows),
            "paper_trading_validated_recipe_count": len(passed_recipe_ids),
            "blocked_recipe_count": len(blocked_recipe_ids),
            "unvalidated_confidence_impact_count": unvalidated_impact_count,
            "alpha_decay_watch_count": confidence_drift_counts.get(
                "alpha_decay_watch",
                0,
            ),
            "alpha_decay_fail_count": confidence_drift_counts.get(
                "alpha_decay_fail",
                0,
            ),
            "cost_decay_fail_count": confidence_drift_counts.get(
                "cost_decay_fail",
                0,
            ),
            "calibration_drift_count": confidence_drift_counts.get(
                "calibration_drift_watch",
                0,
            ),
            "aggregate_calibration_drift_count": sum(
                calibration_rule_counts.values()
            ),
            "regime_fragile_alpha_count": confidence_drift_counts.get(
                "regime_fragile_alpha",
                0,
            ),
            "profile_paper_trade_disagreement_count": confidence_drift_counts.get(
                "profile_paper_trade_disagreement",
                0,
            ),
        }
        for field, expected in expected_monitor_counts.items():
            if field in monitor and monitor.get(field) != expected:
                failures.append(f"confidence_impact_monitor.{field}: expected {expected}")
        if monitor.get("production_decision_impact_allowed") is not False:
            failures.append(
                "confidence_impact_monitor.production_decision_impact_allowed: must be false"
            )
        if monitor.get("lockbox_required_before_production_impact") is not True:
            failures.append(
                "confidence_impact_monitor.lockbox_required_before_production_impact: must be true"
            )
        expected_action_counts = dict(sorted(confidence_action_counts.items()))
        observed_action_counts = _count_mapping(
            monitor.get("recommended_action_counts"),
            row_label="confidence_impact_monitor.recommended_action_counts",
            failures=failures,
        )
        if observed_action_counts != expected_action_counts:
            failures.append("confidence_impact_monitor.recommended_action_counts mismatch")
        expected_drift_counts = dict(sorted(confidence_drift_counts.items()))
        observed_drift_counts = _count_mapping(
            monitor.get("drift_status_counts"),
            row_label="confidence_impact_monitor.drift_status_counts",
            failures=failures,
        )
        if observed_drift_counts != expected_drift_counts:
            failures.append("confidence_impact_monitor.drift_status_counts mismatch")
        expected_blocker_counts = dict(sorted(confidence_blocker_counts.items()))
        observed_blocker_counts = _count_mapping(
            monitor.get("blocker_counts"),
            row_label="confidence_impact_monitor.blocker_counts",
            failures=failures,
        )
        if observed_blocker_counts != expected_blocker_counts:
            failures.append("confidence_impact_monitor.blocker_counts mismatch")
        expected_calibration_rule_counts = dict(sorted(calibration_rule_counts.items()))
        observed_calibration_rule_counts = _count_mapping(
            monitor.get("calibration_drift_rule_counts"),
            row_label="confidence_impact_monitor.calibration_drift_rule_counts",
            failures=failures,
        )
        if observed_calibration_rule_counts != expected_calibration_rule_counts:
            failures.append(
                "confidence_impact_monitor.calibration_drift_rule_counts mismatch"
            )
        observed_correlation = _float_or_none(
            monitor.get("confidence_alpha_correlation")
        )
        expected_correlation = (
            round(confidence_alpha_correlation, 8)
            if confidence_alpha_correlation is not None
            else None
        )
        if expected_correlation is None:
            if monitor.get("confidence_alpha_correlation") is not None:
                failures.append(
                    "confidence_impact_monitor.confidence_alpha_correlation: expected null"
                )
        elif observed_correlation is None or not _nearly_equal(
            observed_correlation,
            expected_correlation,
            tolerance=1e-8,
        ):
            failures.append(
                "confidence_impact_monitor.confidence_alpha_correlation mismatch"
            )
        expected_correlation_status = (
            "negative"
            if confidence_alpha_correlation is not None
            and confidence_alpha_correlation < 0
            else "non_negative"
            if confidence_alpha_correlation is not None
            else "insufficient_data"
        )
        if monitor.get("confidence_alpha_correlation_status") != expected_correlation_status:
            failures.append(
                "confidence_impact_monitor.confidence_alpha_correlation_status mismatch"
            )
        expected_bucket_outcomes = _confidence_contract_bucket_outcome_summary(
            confidence_rows
        )
        if monitor.get("confidence_delta_bucket_outcomes") != expected_bucket_outcomes:
            failures.append(
                "confidence_impact_monitor.confidence_delta_bucket_outcomes mismatch"
            )
    return item_count, failures


def _history_count(
    row: Mapping[str, Any],
    field: str,
    *,
    row_label: str,
    failures: list[str],
) -> int:
    parsed = _int_or_none(row.get(field))
    if parsed is None:
        failures.append(f"{row_label}.{field}: expected integer count")
        return -1
    if parsed < 0:
        failures.append(f"{row_label}.{field}: must be >= 0")
    return parsed


def _validate_history_data_vintage_hash(
    row: Mapping[str, Any],
    *,
    row_label: str,
    failures: list[str],
) -> None:
    data_vintage_hash = str(row.get("data_vintage_hash") or "")
    if not SHA256_DIGEST_PATTERN.fullmatch(data_vintage_hash):
        failures.append(
            f"{row_label}.data_vintage_hash: expected sha256 data vintage digest"
        )


def _validate_evolution_refresh_history_contract(
    root_path: Path,
) -> tuple[int, list[str]]:
    monitor_rows, monitor_failures, _monitor_rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/monitor_refresh_history.jsonl",
    )
    audit_rows, audit_failures, _audit_rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/audit_refresh_history.jsonl",
    )
    gap_rows, gap_failures, _gap_rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/gap_distribution_history.jsonl",
    )
    failures = [*monitor_failures, *audit_failures, *gap_failures]
    for index, row in enumerate(monitor_rows, 1):
        row_label = f"monitor_refresh_history row {index}"
        _validate_history_data_vintage_hash(
            row,
            row_label=row_label,
            failures=failures,
        )
        if str(row.get("history_type") or "") != "confidence_impact_monitor":
            failures.append(f"{row_label}.history_type: must be confidence_impact_monitor")
        for required_field in (
            "blocked_recipe_count",
            "unvalidated_confidence_impact_count",
            "alpha_decay_fail_count",
            "calibration_drift_count",
            "aggregate_calibration_drift_count",
            "blocker_counts",
            "calibration_drift_rule_counts",
        ):
            if required_field not in row:
                failures.append(f"{row_label}.{required_field}: required")
        _count_mapping(
            row.get("blocker_counts"),
            row_label=f"{row_label}.blocker_counts",
            failures=failures,
        )
        calibration_rule_counts = _count_mapping(
            row.get("calibration_drift_rule_counts"),
            row_label=f"{row_label}.calibration_drift_rule_counts",
            failures=failures,
        )
        expected_accepted = (
            _history_count(
                row,
                "unvalidated_confidence_impact_count",
                row_label=row_label,
                failures=failures,
            )
            == 0
            and _history_count(
                row,
                "aggregate_calibration_drift_count",
                row_label=row_label,
                failures=failures,
            )
            == 0
            and not calibration_rule_counts
        )
        if row.get("accepted") is not expected_accepted:
            failures.append(
                f"{row_label}.accepted: must match unvalidated confidence impact and aggregate calibration drift fields"
            )
    for index, row in enumerate(audit_rows, 1):
        row_label = f"audit_refresh_history row {index}"
        _validate_history_data_vintage_hash(
            row,
            row_label=row_label,
            failures=failures,
        )
        if (
            str(row.get("history_type") or "")
            != "schema_pit_provenance_statistical_audit"
        ):
            failures.append(
                f"{row_label}.history_type: must be schema_pit_provenance_statistical_audit"
            )
    for index, row in enumerate(gap_rows, 1):
        row_label = f"gap_distribution_history row {index}"
        _validate_history_data_vintage_hash(
            row,
            row_label=row_label,
            failures=failures,
        )
        if str(row.get("history_type") or "") != "mapping_gap_distribution":
            failures.append(
                f"{row_label}.history_type: must be mapping_gap_distribution"
            )
        gap_counts = _count_mapping(
            row.get("gap_counts"),
            row_label=f"{row_label}.gap_counts",
            failures=failures,
        )
        total_gap_count = sum(gap_counts.values())
        if _int_or_none(row.get("total_gap_count")) != total_gap_count:
            failures.append(f"{row_label}.total_gap_count: expected {total_gap_count}")
        expected_max_gap_name = ""
        expected_max_gap_share = 0.0
        if total_gap_count:
            expected_max_gap_name, max_gap_count = max(
                gap_counts.items(),
                key=lambda item: item[1],
            )
            expected_max_gap_share = round(max_gap_count / total_gap_count, 6)
        if str(row.get("max_gap_name") or "") != expected_max_gap_name:
            failures.append(
                f"{row_label}.max_gap_name: expected {expected_max_gap_name}"
            )
        max_gap_share = _float_or_none(row.get("max_gap_share"))
        if max_gap_share is None:
            failures.append(f"{row_label}.max_gap_share: expected number")
        elif not _nearly_equal(max_gap_share, expected_max_gap_share):
            failures.append(
                f"{row_label}.max_gap_share: expected {expected_max_gap_share}"
            )
        expected_stable = (
            total_gap_count == 0
            or expected_max_gap_share <= GAP_DISTRIBUTION_MAX_STABLE_SHARE
        )
        if row.get("stable") is not expected_stable:
            failures.append(f"{row_label}.stable: expected {expected_stable}")
        if row.get("accepted") is not expected_stable:
            failures.append(f"{row_label}.accepted: expected {expected_stable}")
        if row.get("private_text_included") is not False:
            failures.append(f"{row_label}.private_text_included: must be false")
    return len(monitor_rows) + len(audit_rows) + len(gap_rows), failures


def _validate_evolution_readiness_gate_contract(
    root_path: Path,
) -> tuple[int, list[str]]:
    gate, gate_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/evolution_readiness_gate.json",
        "registry/report_intelligence/evolution_readiness_gate.json",
    )
    failures = list(gate_failures)
    if not gate:
        return 0, failures

    thresholds = gate.get("thresholds")
    if not isinstance(thresholds, Mapping):
        failures.append("evolution_readiness_gate.thresholds: expected object")
        thresholds = {}
    for field, expected in EVOLUTION_GATE_EXPECTED_THRESHOLDS.items():
        if thresholds.get(field) != expected:
            failures.append(
                f"evolution_readiness_gate.thresholds.{field}: expected {expected}"
            )

    def evidence_mapping(check: Mapping[str, Any], row_label: str) -> Mapping[str, Any]:
        evidence = check.get("evidence")
        if not isinstance(evidence, Mapping):
            failures.append(f"{row_label}.evidence: expected object")
            return {}
        return evidence

    def require_int_at_least(
        evidence: Mapping[str, Any],
        field: str,
        minimum: int,
        row_label: str,
    ) -> None:
        value_label = (
            f"{row_label}.{field}"
            if ".evidence" in row_label
            else f"{row_label}.evidence.{field}"
        )
        value = _int_or_none(evidence.get(field))
        if value is None:
            failures.append(f"{value_label}: expected integer")
        elif value < minimum:
            failures.append(
                f"{value_label}: expected >= {minimum}"
            )

    def require_int_equal(
        evidence: Mapping[str, Any],
        field: str,
        expected: int,
        row_label: str,
    ) -> None:
        value_label = (
            f"{row_label}.{field}"
            if ".evidence" in row_label
            else f"{row_label}.evidence.{field}"
        )
        value = _int_or_none(evidence.get(field))
        if value is None:
            failures.append(f"{value_label}: expected integer")
        elif value != expected:
            failures.append(f"{value_label}: expected {expected}")

    def require_float_threshold(
        evidence: Mapping[str, Any],
        field: str,
        threshold: float,
        row_label: str,
        *,
        maximum: bool = False,
    ) -> None:
        value_label = (
            f"{row_label}.{field}"
            if ".evidence" in row_label
            else f"{row_label}.evidence.{field}"
        )
        value = _float_or_none(evidence.get(field))
        if value is None:
            failures.append(f"{value_label}: expected number")
        elif maximum and value > threshold:
            failures.append(f"{value_label}: expected <= {threshold}")
        elif not maximum and value < threshold:
            failures.append(f"{value_label}: expected >= {threshold}")

    checks = gate.get("checks")
    aggregate_blockers: list[str] = []
    observed_check_ids: list[str] = []
    checks_by_id: dict[str, Mapping[str, Any]] = {}
    if not isinstance(checks, Sequence) or isinstance(checks, str):
        failures.append("evolution_readiness_gate.checks: expected array")
        checks = []
    for index, check in enumerate(checks, 1):
        row_label = f"evolution_readiness_gate.checks[{index}]"
        if not isinstance(check, Mapping):
            failures.append(f"{row_label}: expected object")
            continue
        check_id = str(check.get("check_id") or "").strip()
        if not check_id:
            failures.append(f"{row_label}.check_id: required")
        else:
            observed_check_ids.append(check_id)
            checks_by_id[check_id] = check
        blockers = _string_items(check.get("blockers"))
        aggregate_blockers.extend(blockers)
        expected_passed = not blockers
        if check.get("passed") is not expected_passed:
            failures.append(
                f"{row_label}.passed: must be {expected_passed} based on blockers"
            )

    duplicate_check_ids = sorted(
        check_id
        for check_id in set(observed_check_ids)
        if observed_check_ids.count(check_id) > 1
    )
    if duplicate_check_ids:
        failures.append(
            "evolution_readiness_gate.checks duplicate check_ids: "
            + ", ".join(duplicate_check_ids)
        )
    expected_check_ids = set(EVOLUTION_GATE_EXPECTED_CHECK_IDS)
    optional_check_id_groups = [
        set(group) for group in EVOLUTION_GATE_OPTIONAL_CHECK_ID_GROUPS
    ]
    optional_check_ids = set().union(*optional_check_id_groups)
    observed_check_id_set = set(observed_check_ids)
    missing_check_ids = sorted(expected_check_ids - observed_check_id_set)
    extra_check_ids = sorted(
        observed_check_id_set - expected_check_ids - optional_check_ids
    )
    if missing_check_ids:
        failures.append(
            "evolution_readiness_gate.checks missing check_ids: "
            + ", ".join(missing_check_ids)
        )
    for optional_group in optional_check_id_groups:
        observed_optional_ids = observed_check_id_set & optional_group
        if observed_optional_ids and observed_optional_ids != optional_group:
            missing_optional_ids = sorted(optional_group - observed_optional_ids)
            failures.append(
                "evolution_readiness_gate.checks incomplete optional check group: "
                + ", ".join(missing_optional_ids)
            )
    if extra_check_ids:
        failures.append(
            "evolution_readiness_gate.checks unexpected check_ids: "
            + ", ".join(extra_check_ids)
        )

    expected_blockers = sorted(set(aggregate_blockers))
    observed_blockers = _string_items(gate.get("blockers"))
    if len(observed_blockers) != len(set(observed_blockers)):
        failures.append("evolution_readiness_gate.blockers: duplicate blockers")
    if set(observed_blockers) != set(expected_blockers):
        failures.append("evolution_readiness_gate.blockers mismatch with checks")
    expected_blocker_count = len(expected_blockers)
    observed_blocker_count = _int_or_none(gate.get("blocker_count"))
    if observed_blocker_count != expected_blocker_count:
        failures.append(
            f"evolution_readiness_gate.blocker_count: expected {expected_blocker_count}"
        )
    expected_gate_status = "passed" if expected_blocker_count == 0 else "blocked"
    if gate.get("gate_status") != expected_gate_status:
        failures.append(
            f"evolution_readiness_gate.gate_status: expected {expected_gate_status}"
        )
    expected_promotion_state = (
        "ready_for_shadow_evolution_candidate"
        if expected_gate_status == "passed"
        else "blocked_before_prompt_evolution"
    )
    if gate.get("promotion_state") != expected_promotion_state:
        failures.append(
            "evolution_readiness_gate.promotion_state: expected "
            + expected_promotion_state
        )
    if gate.get("production_prompt_change_allowed") is not False:
        failures.append(
            "evolution_readiness_gate.production_prompt_change_allowed: must be false"
        )
    if gate.get("private_text_included") is not False:
        failures.append("evolution_readiness_gate.private_text_included: must be false")

    check_01 = checks_by_id.get("RI-EVOL-01")
    if check_01:
        row_label = "evolution_readiness_gate.checks[RI-EVOL-01]"
        evidence = evidence_mapping(check_01, row_label)
        if check_01.get("passed") is True:
            require_int_at_least(
                evidence,
                "unique_outcome_claim_count",
                int(thresholds.get("min_unique_outcome_claims") or 0),
                row_label,
            )
            require_int_at_least(
                evidence,
                "stock_proxy_unique_claim_count",
                int(thresholds.get("min_stock_proxy_claims") or 0),
                row_label,
            )
            require_int_at_least(
                evidence,
                "industry_proxy_unique_claim_count",
                int(thresholds.get("min_industry_proxy_claims") or 0),
                row_label,
            )

    check_02 = checks_by_id.get("RI-EVOL-02")
    if check_02:
        row_label = "evolution_readiness_gate.checks[RI-EVOL-02]"
        evidence = evidence_mapping(check_02, row_label)
        min_recipes = int(thresholds.get("min_paper_trading_recipes") or 0)
        if check_02.get("passed") is True:
            require_int_at_least(
                evidence, "paper_trading_run_count", min_recipes, row_label
            )
            require_int_at_least(
                evidence, "validation_pass_count", min_recipes, row_label
            )
        after_cost = evidence.get("after_cost_paper_trading_summary")
        if not isinstance(after_cost, Mapping):
            failures.append(
                f"{row_label}.evidence.after_cost_paper_trading_summary: expected object"
            )
        elif check_02.get("passed") is True:
            if after_cost.get("status") != "computed":
                failures.append(
                    f"{row_label}.evidence.after_cost_paper_trading_summary.status: expected computed"
                )
            require_int_at_least(
                after_cost,
                "validated_recipe_count",
                min_recipes,
                row_label + ".evidence.after_cost_paper_trading_summary",
            )
            require_int_at_least(
                after_cost,
                "positive_after_cost_recipe_count",
                min_recipes,
                row_label + ".evidence.after_cost_paper_trading_summary",
            )

    check_03 = checks_by_id.get("RI-EVOL-03")
    if check_03:
        row_label = "evolution_readiness_gate.checks[RI-EVOL-03]"
        evidence = evidence_mapping(check_03, row_label)
        min_refreshes = int(thresholds.get("min_consecutive_monitor_refreshes") or 0)
        require_int_at_least(
            evidence,
            "trailing_monitor_distinct_vintage_count",
            min_refreshes,
            row_label,
        )
        require_int_at_least(
            evidence,
            "trailing_monitor_pass_count",
            min_refreshes,
            row_label,
        )
        require_int_equal(evidence, "unvalidated_confidence_impact_count", 0, row_label)
        require_int_equal(evidence, "aggregate_calibration_drift_count", 0, row_label)
        for field in (
            "alpha_decay_fail_count",
            "cost_decay_fail_count",
            "calibration_drift_count",
            "regime_fragile_alpha_count",
            "profile_paper_trade_disagreement_count",
        ):
            require_int_at_least(evidence, field, 0, row_label)
        recipe_level = evidence.get("recipe_level_monitor")
        recipe_level_label = f"{row_label}.evidence.recipe_level_monitor"
        if not isinstance(recipe_level, Mapping):
            failures.append(f"{recipe_level_label}: expected object")
        else:
            require_int_at_least(
                recipe_level,
                "recipe_level_risk_count",
                0,
                recipe_level_label,
            )
            require_int_at_least(
                recipe_level,
                "actionable_recipe_level_action_count",
                0,
                recipe_level_label,
            )
            risk_counts = recipe_level.get("recipe_level_risk_counts")
            if not isinstance(risk_counts, Mapping):
                failures.append(
                    f"{recipe_level_label}.recipe_level_risk_counts: expected object"
                )
                risk_counts = {}
            recommended_action_counts = recipe_level.get("recommended_action_counts")
            if not isinstance(recommended_action_counts, Mapping):
                failures.append(
                    f"{recipe_level_label}.recommended_action_counts: expected object"
                )
                recommended_action_counts = {}
            actionable_counts = recipe_level.get(
                "actionable_recipe_level_action_counts"
            )
            if not isinstance(actionable_counts, Mapping):
                failures.append(
                    f"{recipe_level_label}.actionable_recipe_level_action_counts: "
                    "expected object"
                )
                actionable_counts = {}
            risk_total = sum(
                value
                for value in (_int_or_none(item) for item in risk_counts.values())
                if value is not None
            )
            if _int_or_none(recipe_level.get("recipe_level_risk_count")) != risk_total:
                failures.append(
                    f"{recipe_level_label}.recipe_level_risk_count: mismatch with "
                    "recipe_level_risk_counts"
                )
            action_total = sum(
                value
                for value in (_int_or_none(item) for item in actionable_counts.values())
                if value is not None
            )
            if (
                _int_or_none(recipe_level.get("actionable_recipe_level_action_count"))
                != action_total
            ):
                failures.append(
                    f"{recipe_level_label}.actionable_recipe_level_action_count: "
                    "mismatch with actionable_recipe_level_action_counts"
                )
            if not str(recipe_level.get("global_blocker_policy") or "").strip():
                failures.append(f"{recipe_level_label}.global_blocker_policy: required")

    check_04 = checks_by_id.get("RI-EVOL-04")
    if check_04:
        row_label = "evolution_readiness_gate.checks[RI-EVOL-04]"
        evidence = evidence_mapping(check_04, row_label)
        blockers = set(_string_items(check_04.get("blockers")))
        audit_fields = (
            "schema_accepted",
            "pit_accepted",
            "provenance_accepted",
            "statistical_accepted",
        )
        current_audit_accepted = all(
            evidence.get(field) is True for field in audit_fields
        )
        if (
            current_audit_accepted
            and "current_schema_or_audit_gate_blocked" in blockers
        ):
            failures.append(
                f"{row_label}.blockers: current_schema_or_audit_gate_blocked "
                "not allowed when current schema/PIT/provenance/statistical "
                "evidence all pass"
            )
        if (
            not current_audit_accepted
            and "current_schema_or_audit_gate_blocked" not in blockers
        ):
            failures.append(
                f"{row_label}.blockers: must include "
                "current_schema_or_audit_gate_blocked when current "
                "schema/PIT/provenance/statistical evidence is not all true"
            )
        for field in audit_fields:
            if check_04.get("passed") is True and evidence.get(field) is not True:
                failures.append(f"{row_label}.evidence.{field}: must be true")
        min_refreshes = int(thresholds.get("min_consecutive_audit_refreshes") or 0)
        trailing_distinct = _int_or_none(
            evidence.get("trailing_audit_distinct_vintage_count")
        )
        trailing_pass = _int_or_none(evidence.get("trailing_audit_pass_count"))
        if trailing_distinct is None:
            failures.append(
                f"{row_label}.evidence.trailing_audit_distinct_vintage_count: "
                "expected integer"
            )
        if trailing_pass is None:
            failures.append(
                f"{row_label}.evidence.trailing_audit_pass_count: expected integer"
            )
        audit_history_ready = (
            trailing_distinct is not None
            and trailing_pass is not None
            and trailing_distinct >= min_refreshes
            and trailing_pass >= min_refreshes
        )
        dependency = evidence.get("audit_history_dependency")
        if not isinstance(dependency, Mapping):
            failures.append(
                f"{row_label}.evidence.audit_history_dependency: expected object"
            )
            dependency = {}
        blocking_components = sorted(
            field.removesuffix("_accepted")
            for field in audit_fields
            if evidence.get(field) is not True
        )
        expected_dependency_status = (
            "current_gate_blocked"
            if blocking_components
            else "history_below_threshold"
            if not audit_history_ready
            else "ready"
        )
        observed_components = sorted(_string_items(dependency.get("blocking_components")))
        if observed_components != blocking_components:
            failures.append(
                f"{row_label}.evidence.audit_history_dependency."
                "blocking_components mismatch"
            )
        if dependency.get("status") != expected_dependency_status:
            failures.append(
                f"{row_label}.evidence.audit_history_dependency.status: "
                f"expected {expected_dependency_status}"
            )
        expected_next_action = (
            "clear_current_schema_pit_provenance_statistical_blockers_before_"
            "counting_audit_refresh_history"
            if blocking_components
            else "run_distinct_derived_refreshes_after_current_audits_pass"
            if not audit_history_ready
            else "none"
        )
        if dependency.get("next_action") != expected_next_action:
            failures.append(
                f"{row_label}.evidence.audit_history_dependency.next_action: "
                f"expected {expected_next_action}"
            )
        if dependency.get("history_counts_only_passing_current_audits") is not True:
            failures.append(
                f"{row_label}.evidence.audit_history_dependency."
                "history_counts_only_passing_current_audits: must be true"
            )
        if (
            dependency.get("refresh_without_current_audit_pass_can_satisfy_history")
            is not False
        ):
            failures.append(
                f"{row_label}.evidence.audit_history_dependency."
                "refresh_without_current_audit_pass_can_satisfy_history: must be false"
            )
        if dependency.get("min_consecutive_audit_refreshes") != min_refreshes:
            failures.append(
                f"{row_label}.evidence.audit_history_dependency."
                f"min_consecutive_audit_refreshes: expected {min_refreshes}"
            )
        failure_counts = _count_mapping(
            dependency.get("current_failure_counts"),
            row_label=f"{row_label}.evidence.audit_history_dependency.current_failure_counts",
            failures=failures,
        )
        evidence_failure_counts = _count_mapping(
            evidence.get("current_failure_counts"),
            row_label=f"{row_label}.evidence.current_failure_counts",
            failures=failures,
        )
        if evidence_failure_counts and evidence_failure_counts != failure_counts:
            failures.append(
                f"{row_label}.evidence.current_failure_counts: must match "
                "audit_history_dependency.current_failure_counts"
            )
        failure_refs_raw = dependency.get("current_failure_refs")
        if not isinstance(failure_refs_raw, Mapping):
            failures.append(
                f"{row_label}.evidence.audit_history_dependency."
                "current_failure_refs: expected object"
            )
            failure_refs_raw = {}
        evidence_failure_refs_raw = evidence.get("current_failure_refs")
        if not isinstance(evidence_failure_refs_raw, Mapping):
            failures.append(f"{row_label}.evidence.current_failure_refs: expected object")
            evidence_failure_refs_raw = {}
        for component in ("schema", "pit", "provenance", "statistical"):
            accepted_field = f"{component}_accepted"
            if component == "provenance":
                accepted_field = "provenance_accepted"
            component_accepted = evidence.get(accepted_field) is True
            failure_count = failure_counts.get(component)
            if failure_count is None:
                failures.append(
                    f"{row_label}.evidence.audit_history_dependency."
                    f"current_failure_counts.{component}: expected integer count"
                )
            elif component_accepted and failure_count != 0:
                failures.append(
                    f"{row_label}.evidence.audit_history_dependency."
                    f"current_failure_counts.{component}: expected 0 when "
                    f"{accepted_field} is true"
                )
            elif not component_accepted and failure_count <= 0:
                failures.append(
                    f"{row_label}.evidence.audit_history_dependency."
                    f"current_failure_counts.{component}: expected positive "
                    f"count when {accepted_field} is false"
                )
            refs = failure_refs_raw.get(component)
            if refs is None:
                failures.append(
                    f"{row_label}.evidence.audit_history_dependency."
                    f"current_failure_refs.{component}: expected array"
                )
                continue
            if not isinstance(refs, Sequence) or isinstance(refs, str):
                failures.append(
                    f"{row_label}.evidence.audit_history_dependency."
                    f"current_failure_refs.{component}: expected array"
                )
                continue
            non_string_ref_count = sum(1 for item in refs if not isinstance(item, str))
            if non_string_ref_count:
                failures.append(
                    f"{row_label}.evidence.audit_history_dependency."
                    f"current_failure_refs.{component}: expected string refs"
                )
            elif component_accepted and _string_items(refs):
                failures.append(
                    f"{row_label}.evidence.audit_history_dependency."
                    f"current_failure_refs.{component}: expected empty refs when "
                    f"{accepted_field} is true"
                )
            evidence_refs = evidence_failure_refs_raw.get(component)
            if evidence_refs is None:
                failures.append(
                    f"{row_label}.evidence.current_failure_refs.{component}: "
                    "expected array"
                )
            elif not isinstance(evidence_refs, Sequence) or isinstance(
                evidence_refs, str
            ):
                failures.append(
                    f"{row_label}.evidence.current_failure_refs.{component}: "
                    "expected array"
                )
            elif _string_items(evidence_refs) != _string_items(refs):
                failures.append(
                    f"{row_label}.evidence.current_failure_refs.{component}: "
                    "must match audit_history_dependency.current_failure_refs"
                )
            if (
                component == "schema"
                and REPORT_INTELLIGENCE_EVOLUTION_READINESS_GATE_SCHEMA_RULES
                in _string_items(refs)
            ):
                failures.append(
                    f"{row_label}.evidence.audit_history_dependency."
                    "current_failure_refs.schema: must exclude "
                    "evolution-readiness self schema rule"
                )
            if (
                component == "schema"
                and isinstance(evidence_refs, Sequence)
                and not isinstance(evidence_refs, str)
                and REPORT_INTELLIGENCE_EVOLUTION_READINESS_GATE_SCHEMA_RULES
                in _string_items(evidence_refs)
            ):
                failures.append(
                    f"{row_label}.evidence.current_failure_refs.schema: must "
                    "exclude evolution-readiness self schema rule"
                )
        if audit_history_ready and "audit_refresh_history_below_threshold" in blockers:
            failures.append(
                f"{row_label}.blockers: audit_refresh_history_below_threshold "
                "not allowed when trailing audit distinct/pass counts meet threshold"
            )
        if (
            not audit_history_ready
            and "audit_refresh_history_below_threshold" not in blockers
        ):
            failures.append(
                f"{row_label}.blockers: must include "
                "audit_refresh_history_below_threshold when trailing audit "
                "distinct/pass counts are below threshold"
            )
        if check_04.get("passed") is True:
            require_int_at_least(
                evidence,
                "trailing_audit_distinct_vintage_count",
                min_refreshes,
                row_label,
            )
            require_int_at_least(
                evidence,
                "trailing_audit_pass_count",
                min_refreshes,
                row_label,
            )

    check_05 = checks_by_id.get("RI-EVOL-05")
    if check_05 and check_05.get("passed") is True:
        row_label = "evolution_readiness_gate.checks[RI-EVOL-05]"
        evidence = evidence_mapping(check_05, row_label)
        if evidence.get("gold_set_passed") is not True:
            failures.append(f"{row_label}.evidence.gold_set_passed: must be true")
        if evidence.get("review_complete") is not True:
            failures.append(f"{row_label}.evidence.review_complete: must be true")
        require_int_equal(evidence, "pending_claims", 0, row_label)
        gold_thresholds = evidence.get("thresholds")
        if not isinstance(gold_thresholds, Mapping):
            failures.append(f"{row_label}.evidence.thresholds: expected object")
            gold_thresholds = {}
        require_int_at_least(
            evidence,
            "reviewed_claims",
            int(gold_thresholds.get("min_reviewed_claims") or 0),
            row_label,
        )
        require_int_at_least(
            evidence,
            "total_documents",
            int(gold_thresholds.get("min_documents") or 0),
            row_label,
        )
        gold_metrics = evidence.get("metrics")
        if not isinstance(gold_metrics, Mapping):
            failures.append(f"{row_label}.evidence.metrics: expected object")
            gold_metrics = {}
        for metric in (
            "claim_precision",
            "direction_accuracy",
            "horizon_accuracy",
            "source_span_support_precision",
            "target_accuracy",
            "variable_mapping_accuracy",
        ):
            require_float_threshold(
                gold_metrics,
                metric,
                float(gold_thresholds.get(f"{metric}_min") or 0.0),
                row_label + ".evidence.metrics",
            )
        require_float_threshold(
            gold_metrics,
            "unsupported_field_false_grounding_rate",
            float(
                gold_thresholds.get(
                    "unsupported_field_false_grounding_rate_max",
                )
                or 0.0
            ),
            row_label + ".evidence.metrics",
            maximum=True,
        )
        stock_target_conflict_count = _int_or_none(
            evidence.get("stock_target_conflict_count")
        )
        if (
            stock_target_conflict_count is not None
            and stock_target_conflict_count > 0
            and evidence.get("stock_target_conflict_explained") is not True
        ):
            failures.append(
                f"{row_label}.evidence.stock_target_conflict_explained: must be true when conflicts exist"
            )
        stock_target_conflict_reviewed_count = _int_or_none(
            evidence.get("stock_target_conflict_reviewed_count")
        )
        if (
            stock_target_conflict_count is not None
            and stock_target_conflict_reviewed_count is not None
            and stock_target_conflict_reviewed_count < stock_target_conflict_count
        ):
            failures.append(
                f"{row_label}.evidence.stock_target_conflict_reviewed_count: expected >= stock_target_conflict_count"
            )

    check_06 = checks_by_id.get("RI-EVOL-06")
    if check_06:
        row_label = "evolution_readiness_gate.checks[RI-EVOL-06]"
        evidence = evidence_mapping(check_06, row_label)
        min_refreshes = int(thresholds.get("min_gap_distribution_refreshes") or 0)
        require_int_at_least(
            evidence,
            "trailing_gap_distribution_distinct_vintage_count",
            min_refreshes,
            row_label,
        )
        require_int_at_least(
            evidence,
            "trailing_gap_distribution_stable_count",
            min_refreshes,
            row_label,
        )

    check_07 = checks_by_id.get("RI-EVOL-07")
    if check_07:
        row_label = "evolution_readiness_gate.checks[RI-EVOL-07]"
        evidence = evidence_mapping(check_07, row_label)
        coverage_gate_status = str(evidence.get("coverage_gate_status") or "").strip()
        coverage_gate_blockers = _string_items(evidence.get("coverage_gate_blockers"))
        if not coverage_gate_status:
            failures.append(f"{row_label}.evidence.coverage_gate_status: required")
        if check_07.get("passed") is True:
            if coverage_gate_status != "passed":
                failures.append(
                    f"{row_label}.evidence.coverage_gate_status: expected passed"
                )
            if coverage_gate_blockers:
                failures.append(
                    f"{row_label}.evidence.coverage_gate_blockers: must be empty"
                )

    check_08 = checks_by_id.get("RI-EVOL-08")
    if check_08:
        row_label = "evolution_readiness_gate.checks[RI-EVOL-08]"
        evidence = evidence_mapping(check_08, row_label)
        if str(evidence.get("status") or "") != (
            "not_applicable_prompt_mutation_candidates_not_supplied"
        ):
            prior_count = _int_or_none(evidence.get("prior_compiler_candidate_count"))
            actionable_count = _int_or_none(
                evidence.get("prior_compiler_actionable_candidate_count")
            )
            if prior_count is None:
                failures.append(
                    f"{row_label}.evidence.prior_compiler_candidate_count: expected integer"
                )
            if actionable_count is None:
                failures.append(
                    f"{row_label}.evidence.prior_compiler_actionable_candidate_count: expected integer"
                )
            elif (
                prior_count
                and actionable_count == 0
                and "prior_compiler_refusal_only"
                not in _string_items(check_08.get("blockers"))
            ):
                failures.append(
                    f"{row_label}.blockers: prior_compiler_refusal_only required"
                )

    return len(checks), failures


def _validate_gold_review_gate_contract(root_path: Path) -> tuple[int, list[str]]:
    summary_path = (
        root_path / "registry/gold_sets/tushare_research_reports.review_summary.json"
    )
    if not summary_path.exists():
        return 0, []
    summary, summary_failures = _read_mapping_json(
        summary_path,
        "registry/gold_sets/tushare_research_reports.review_summary.json",
    )
    failures = list(summary_failures)
    if not summary:
        return 0, failures

    row_label = "gold_review_summary"
    required_fields = (
        "summary_id",
        "review_path",
        "total_claims",
        "reviewed_claims",
        "pending_claims",
        "total_documents",
        "review_complete",
        "passed",
        "blockers",
        "metrics",
    )
    failures.extend(
        _required_field_failures(
            summary,
            row_label=row_label,
            required_fields=required_fields,
        )
    )

    review_path = str(summary.get("review_path") or "").strip()
    review_parts = Path(review_path).parts
    if review_path != GOLD_REVIEW_GATE_EXPECTED_REVIEW_PATH:
        failures.append(
            f"{row_label}.review_path: expected "
            f"{GOLD_REVIEW_GATE_EXPECTED_REVIEW_PATH}"
        )
    if Path(review_path).is_absolute() or ".." in review_parts:
        failures.append(f"{row_label}.review_path: must be repo-relative")

    counts: dict[str, int | None] = {}
    for field in (
        "total_claims",
        "reviewed_claims",
        "pending_claims",
        "total_documents",
    ):
        value = _int_or_none(summary.get(field))
        counts[field] = value
        if value is None:
            failures.append(f"{row_label}.{field}: expected integer")
        elif value < 0:
            failures.append(f"{row_label}.{field}: must be non-negative")

    total_claims = counts["total_claims"]
    reviewed_claims = counts["reviewed_claims"]
    pending_claims = counts["pending_claims"]
    total_documents = counts["total_documents"]
    if None not in (total_claims, reviewed_claims, pending_claims) and (
        int(reviewed_claims or 0) + int(pending_claims or 0)
        != int(total_claims or 0)
    ):
        failures.append(
            f"{row_label}: reviewed_claims + pending_claims must equal total_claims"
        )

    expected_review_complete = (
        pending_claims == 0
        and reviewed_claims == total_claims
        and (total_claims or 0) > 0
    )
    review_complete = summary.get("review_complete")
    if not isinstance(review_complete, bool):
        failures.append(f"{row_label}.review_complete: must be boolean")
    elif review_complete is not expected_review_complete:
        failures.append(
            f"{row_label}.review_complete: expected {expected_review_complete}"
        )

    passed = summary.get("passed")
    if not isinstance(passed, bool):
        failures.append(f"{row_label}.passed: must be boolean")
        passed = False

    blockers = _string_items(summary.get("blockers"))
    if summary.get("blockers") is not None and (
        not isinstance(summary.get("blockers"), Sequence)
        or isinstance(summary.get("blockers"), str)
    ):
        failures.append(f"{row_label}.blockers: expected array")

    metrics_payload = summary.get("metrics")
    metric_failures: list[str] = []
    metric_threshold_failures: list[str] = []
    if metrics_payload is None:
        if review_complete is True or passed is True:
            metric_failures.append(f"{row_label}.metrics: expected object")
    elif not isinstance(metrics_payload, Mapping):
        metric_failures.append(f"{row_label}.metrics: expected object")
    else:
        for field, (operator, threshold) in GOLD_REVIEW_GATE_METRIC_THRESHOLDS.items():
            value = _float_or_none(metrics_payload.get(field))
            if value is None:
                metric_failures.append(f"{row_label}.metrics.{field}: expected number")
            elif operator == ">=" and value < threshold:
                metric_threshold_failures.append(
                    f"{row_label}.metrics.{field}: expected >= {threshold}"
                )
            elif operator == "<=" and value > threshold:
                metric_threshold_failures.append(
                    f"{row_label}.metrics.{field}: expected <= {threshold}"
                )
    failures.extend(metric_failures)
    if passed is True:
        failures.extend(metric_threshold_failures)

    review_is_complete = review_complete is True and expected_review_complete
    has_pending = pending_claims is None or pending_claims > 0
    below_minimum = (
        reviewed_claims is None
        or reviewed_claims < GOLD_REVIEW_GATE_MIN_REVIEWED_CLAIMS
        or total_documents is None
        or total_documents < GOLD_REVIEW_GATE_MIN_DOCUMENTS
    )
    blocked_state = has_pending or not review_is_complete or below_minimum or bool(
        metric_failures or metric_threshold_failures
    )
    if blocked_state and not blockers:
        failures.append(f"{row_label}.blockers: blocked review requires blockers")
    if passed is True:
        if blockers:
            failures.append(f"{row_label}.blockers: passed review must not block")
        if not review_is_complete:
            failures.append(f"{row_label}.passed: requires review_complete=true")
        if pending_claims != 0:
            failures.append(f"{row_label}.passed: requires pending_claims=0")
        if reviewed_claims is None or reviewed_claims < GOLD_REVIEW_GATE_MIN_REVIEWED_CLAIMS:
            failures.append(
                f"{row_label}.reviewed_claims: expected >= "
                f"{GOLD_REVIEW_GATE_MIN_REVIEWED_CLAIMS}"
            )
        if total_documents is None or total_documents < GOLD_REVIEW_GATE_MIN_DOCUMENTS:
            failures.append(
                f"{row_label}.total_documents: expected >= "
                f"{GOLD_REVIEW_GATE_MIN_DOCUMENTS}"
            )
        if metric_failures or metric_threshold_failures:
            failures.append(f"{row_label}.passed: requires threshold-clean metrics")
    elif passed is False and not blocked_state and blockers:
        failures.append(f"{row_label}.blockers: stale blockers for complete review")

    return 1, failures


def _validate_public_summary_id_queue_privacy(root_path: Path) -> tuple[int, list[str]]:
    failures: list[str] = []
    item_count = 0
    for artifact_path in REPORT_INTELLIGENCE_PUBLIC_ID_QUEUE_ARTIFACTS:
        payload, errors = _read_mapping_json(root_path / artifact_path, artifact_path)
        failures.extend(errors)
        if not payload:
            continue
        item_count += 1
        failures.extend(
            _public_forbidden_id_queue_failures(payload, path=artifact_path)
        )
    return item_count, failures


def _prompt_mutation_evidence_values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return _nearly_equal(float(left), float(right))
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            return False
        return all(
            _prompt_mutation_evidence_values_equal(left[key], right[key])
            for key in left
        )
    if (
        isinstance(left, Sequence)
        and not isinstance(left, str)
        and isinstance(right, Sequence)
        and not isinstance(right, str)
    ):
        return len(left) == len(right) and all(
            _prompt_mutation_evidence_values_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _positive_integer_mapping_values(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    counts: dict[str, int] = {}
    for key, raw_count in value.items():
        count = _int_or_none(raw_count)
        if count is not None and count > 0:
            counts[str(key)] = count
    return counts


def _integer_mapping_values(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    counts: dict[str, int] = {}
    for key, raw_count in value.items():
        count = _int_or_none(raw_count)
        if count is not None:
            counts[str(key)] = count
    return counts


def _evolution_gate_check(gate: Mapping[str, Any], check_id: str) -> Mapping[str, Any]:
    checks = gate.get("checks")
    if not isinstance(checks, Sequence) or isinstance(checks, str):
        return {}
    for check in checks:
        if isinstance(check, Mapping) and check.get("check_id") == check_id:
            return check
    return {}


def _gold_quality_prompt_candidate_expected_evidence(
    gate: Mapping[str, Any],
) -> Mapping[str, Any]:
    check = _evolution_gate_check(gate, "RI-EVOL-05")
    evidence = check.get("evidence")
    if not isinstance(evidence, Mapping):
        return {}
    blockers = set(_string_items(check.get("blockers")))
    metrics = evidence.get("metrics") if isinstance(evidence.get("metrics"), Mapping) else {}
    thresholds = (
        evidence.get("thresholds")
        if isinstance(evidence.get("thresholds"), Mapping)
        else {}
    )
    metric_failures: dict[str, dict[str, Any]] = {}
    for field, (operator, default_threshold) in GOLD_REVIEW_GATE_METRIC_THRESHOLDS.items():
        suffix = "min" if operator == ">=" else "max"
        threshold = _float_or_none(thresholds.get(f"{field}_{suffix}"))
        if threshold is None:
            threshold = default_threshold
        current_rate = _float_or_none(metrics.get(field))
        blocker = (
            f"{field}_below_threshold"
            if operator == ">="
            else f"{field}_above_threshold"
        )
        if (
            current_rate is None
            or (operator == ">=" and current_rate < threshold)
            or (operator == "<=" and current_rate > threshold)
            or blocker in blockers
        ):
            metric_failures[field] = {
                "operator": operator,
                "current_rate": current_rate,
                "threshold": threshold,
                "blocker": f"{field}_missing" if current_rate is None else blocker,
            }
    total_documents = _int_or_none(evidence.get("total_documents")) or 0
    min_documents = (
        _int_or_none(thresholds.get("min_documents"))
        or GOLD_REVIEW_GATE_MIN_DOCUMENTS
    )
    document_gap = max(0, min_documents - total_documents)
    return {
        "metric_failures": metric_failures,
        "metric_failure_count": len(metric_failures),
        "document_coverage_gap": {
            "current_count": total_documents,
            "threshold": min_documents,
            "minimum_additional_count": document_gap,
            "blocker": "gold_reviewed_documents_below_threshold" if document_gap else "",
        },
        "reviewed_claims": _int_or_none(evidence.get("reviewed_claims")) or 0,
        "pending_claims": _int_or_none(evidence.get("pending_claims")) or 0,
        "quality_blockers": sorted(blockers),
    }


def _footprint_quality_prompt_candidate_expected_evidence(
    summary: Mapping[str, Any],
) -> Mapping[str, Any]:
    metrics = (
        summary.get("precision_recall_report")
        if isinstance(summary.get("precision_recall_report"), Mapping)
        else {}
    )
    thresholds = (
        summary.get("quality_gate_thresholds")
        if isinstance(summary.get("quality_gate_thresholds"), Mapping)
        else {}
    )
    blockers = [
        str(item)
        for item in [
            *_string_items(summary.get("quality_gate_blockers")),
            *_string_items(summary.get("blockers")),
        ]
        if str(item).strip()
    ]
    metric_failures: dict[str, dict[str, Any]] = {}
    for field, threshold_value in thresholds.items():
        threshold = _float_or_none(threshold_value)
        if threshold is None:
            continue
        current_rate = _float_or_none(metrics.get(field))
        blocker = f"{field}_below_threshold"
        if current_rate is None or current_rate < threshold or any(
            str(item).startswith(str(field)) for item in blockers
        ):
            metric_failures[str(field)] = {
                "operator": ">=",
                "current_rate": current_rate,
                "threshold": threshold,
                "blocker": f"{field}_missing" if current_rate is None else blocker,
            }
    return {
        "footprint_review_accepted": summary.get("accepted") is True,
        "review_complete": summary.get("review_complete") is True,
        "quality_gate_passed": summary.get("quality_gate_passed") is True,
        "complete_rows": _int_or_none(summary.get("complete_rows")) or 0,
        "pending_rows": _int_or_none(summary.get("pending_rows")) or 0,
        "total_rows": _int_or_none(summary.get("total_rows")) or 0,
        "metric_failures": metric_failures,
        "metric_failure_count": len(metric_failures),
        "quality_gate_blockers": sorted(set(blockers)),
        "error_counts": _positive_integer_mapping_values(summary.get("error_counts")),
    }


def _stability_prompt_candidate_expected_evidence_refs(
    gate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    gate_thresholds = (
        gate.get("thresholds") if isinstance(gate.get("thresholds"), Mapping) else {}
    )
    expected_refs: list[dict[str, Any]] = []
    for check_id in ("RI-EVOL-03", "RI-EVOL-04", "RI-EVOL-06"):
        check = _evolution_gate_check(gate, check_id)
        if not check:
            continue
        check_blockers = _string_items(check.get("blockers"))
        if not check_blockers:
            continue
        expected_refs.append(
            {
                "artifact_path": (
                    "registry/report_intelligence/evolution_readiness_gate.json"
                ),
                "field": f"checks.{check_id}.evidence",
                "check_id": check_id,
                "blockers": check_blockers,
                "evidence": (
                    check.get("evidence")
                    if isinstance(check.get("evidence"), Mapping)
                    else {}
                ),
                "thresholds": {
                    key: gate_thresholds.get(key)
                    for key in (
                        "min_consecutive_monitor_refreshes",
                        "min_consecutive_audit_refreshes",
                        "min_gap_distribution_refreshes",
                    )
                    if key in gate_thresholds
                },
            }
        )
    return expected_refs


def _forecast_gold_review_prompt_candidate_expected_evidence_refs(
    gate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    check = _evolution_gate_check(gate, "RI-EVOL-05")
    evidence = check.get("evidence")
    if not isinstance(evidence, Mapping):
        return []
    return [
        {
            "artifact_path": "registry/report_intelligence/evolution_readiness_gate.json",
            "field": "checks.RI-EVOL-05.evidence",
            "gold_set_passed": check.get("passed") is True,
            "reviewed_claims": _int_or_none(evidence.get("reviewed_claims")) or 0,
            "total_documents": _int_or_none(evidence.get("total_documents")) or 0,
            "pending_claims": _int_or_none(evidence.get("pending_claims")) or 0,
            "metrics": (
                evidence.get("metrics")
                if isinstance(evidence.get("metrics"), Mapping)
                else {}
            ),
            "thresholds": (
                evidence.get("thresholds")
                if isinstance(evidence.get("thresholds"), Mapping)
                else {}
            ),
            "stock_target_conflict_count": _int_or_none(
                evidence.get("stock_target_conflict_count")
            )
            or 0,
            "stock_target_conflict_reviewed_count": _int_or_none(
                evidence.get("stock_target_conflict_reviewed_count")
            )
            or 0,
            "stock_target_conflict_explained": (
                evidence.get("stock_target_conflict_explained") is True
            ),
            "blockers": _string_items(check.get("blockers")),
        }
    ]


def _industry_mapping_prompt_candidate_expected_evidence_refs(
    *,
    root_path: Path,
    failures: list[str],
) -> list[dict[str, Any]]:
    availability, availability_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/industry_etf_proxy_pit_availability.json",
        "registry/report_intelligence/industry_etf_proxy_pit_availability.json",
    )
    readiness, readiness_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/outcome_labeling_readiness.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
    )
    failures.extend(availability_failures)
    failures.extend(readiness_failures)
    if not availability or not readiness:
        return []
    action_summary = (
        availability.get("labelability_action_summary")
        if isinstance(availability.get("labelability_action_summary"), Mapping)
        else {}
    )
    pit_gap_counts = _positive_integer_mapping_values(availability.get("pit_gap_counts"))
    industry_readiness = (
        readiness.get("industry_etf_proxy_readiness")
        if isinstance(readiness.get("industry_etf_proxy_readiness"), Mapping)
        else {}
    )
    readiness_gap_counts = (
        industry_readiness.get("data_gap_counts")
        if isinstance(industry_readiness.get("data_gap_counts"), Mapping)
        else {}
    )
    return [
        {
            "artifact_path": (
                "registry/report_intelligence/industry_etf_proxy_pit_availability.json"
            ),
            "field": "labelability_action_summary",
            "coverage_gate_status": str(
                action_summary.get("coverage_gate_status") or ""
            ),
            "remaining_action_count": _int_or_none(
                action_summary.get("remaining_action_count")
            )
            or 0,
            "sector_etf_mapping_missing_count": _int_or_none(
                action_summary.get("sector_etf_mapping_missing_count")
            )
            or 0,
            "pit_unavailable_mapping_count": _int_or_none(
                action_summary.get("pit_unavailable_mapping_count")
            )
            or 0,
            "labelability_rate": action_summary.get("labelability_rate"),
            "primary_mapping_coverage_rate": action_summary.get(
                "primary_mapping_coverage_rate"
            ),
            "next_actions": _string_items(action_summary.get("next_actions")),
        },
        {
            "artifact_path": (
                "registry/report_intelligence/industry_etf_proxy_pit_availability.json"
            ),
            "field": "pit_gap_counts",
            "gap_counts": pit_gap_counts,
        },
        {
            "artifact_path": "registry/report_intelligence/outcome_labeling_readiness.json",
            "field": "industry_etf_proxy_readiness.data_gap_counts",
            "sector_etf_mapping_missing_count": _int_or_none(
                readiness_gap_counts.get("sector_etf_mapping_missing")
            )
            or 0,
        },
    ]


def _regime_mechanism_prompt_candidate_expected_evidence_refs(
    *,
    root_path: Path,
    failures: list[str],
) -> list[dict[str, Any]]:
    readiness, readiness_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/outcome_labeling_readiness.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
    )
    failures.extend(readiness_failures)
    if not readiness:
        return []
    regime_gap_counts = _integer_mapping_values(readiness.get("regime_gap_counts"))
    mechanism_gap_counts = _integer_mapping_values(
        readiness.get("mechanism_gap_counts")
    )
    hard_regime_mechanism_gaps = {
        "regime_context_missing",
        "regime_context_unclassified",
        "economic_mechanism_missing",
        "mechanism_evaluable_impact_missing",
        "possible_operational_only_mechanism",
    }
    hard_gap_count = sum(
        count
        for key, count in {
            **regime_gap_counts,
            **mechanism_gap_counts,
        }.items()
        if key in hard_regime_mechanism_gaps
    )
    return [
        {
            "artifact_path": "registry/report_intelligence/outcome_labeling_readiness.json",
            "field": "regime_gap_counts.mechanism_gap_counts",
            "regime_gap_counts": regime_gap_counts,
            "mechanism_gap_counts": mechanism_gap_counts,
            "macro_regime_counts": _integer_mapping_values(
                readiness.get("macro_regime_counts")
            ),
            "source_text_macro_regime_counts": _integer_mapping_values(
                readiness.get("source_text_macro_regime_counts")
            ),
            "as_of_date_macro_regime_counts": _integer_mapping_values(
                readiness.get("as_of_date_macro_regime_counts")
            ),
            "macro_regime_source_counts": _integer_mapping_values(
                readiness.get("macro_regime_source_counts")
            ),
            "industry_cycle_regime_counts": _integer_mapping_values(
                readiness.get("industry_cycle_regime_counts")
            ),
            "regime_gap_forecast_claim_count": sum(regime_gap_counts.values()),
            "mechanism_gap_forecast_claim_count": sum(mechanism_gap_counts.values()),
            "hard_gap_count": hard_gap_count,
            "diagnostic_gap_policy": (
                "company_capability_only_no_regime_context is diagnostic; "
                "missing or unclassified regime and missing mechanism are "
                "prompt-evolution blockers"
            ),
        }
    ]


def _calibration_prompt_candidate_expected_evidence_refs(
    *,
    root_path: Path,
    failures: list[str],
) -> list[dict[str, Any]]:
    monitor, monitor_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/confidence_impact_monitor.json",
        "registry/report_intelligence/confidence_impact_monitor.json",
    )
    failures.extend(monitor_failures)
    if not monitor:
        return []
    drift_status_counts = _count_mapping(
        monitor.get("drift_status_counts"),
        row_label="confidence_impact_monitor.drift_status_counts",
        failures=failures,
    )
    calibration_rule_counts = _count_mapping(
        monitor.get("calibration_drift_rule_counts"),
        row_label="confidence_impact_monitor.calibration_drift_rule_counts",
        failures=failures,
    )
    action_counts = _count_mapping(
        monitor.get("recommended_action_counts"),
        row_label="confidence_impact_monitor.recommended_action_counts",
        failures=failures,
    )
    risk_counts = {
        key: _int_or_none(monitor.get(key)) or 0
        for key in (
            "alpha_decay_watch_count",
            "alpha_decay_fail_count",
            "cost_decay_fail_count",
            "calibration_drift_count",
            "regime_fragile_alpha_count",
            "profile_paper_trade_disagreement_count",
        )
    }
    actionable_counts = {
        key: int(action_counts.get(key, 0))
        for key in (
            "reduce_confidence_impact",
            "freeze_recipe",
            "send_to_manual_review",
            "retire_recipe",
        )
        if int(action_counts.get(key, 0)) > 0
    }
    return [
        {
            "artifact_path": "registry/report_intelligence/confidence_impact_monitor.json",
            "field": "drift_status_counts",
            "drift_status_counts": drift_status_counts,
            "calibration_drift_rule_counts": calibration_rule_counts,
            "confidence_alpha_correlation": monitor.get(
                "confidence_alpha_correlation"
            ),
            "confidence_alpha_correlation_status": str(
                monitor.get("confidence_alpha_correlation_status") or ""
            ),
            "recipe_level_monitor": {
                "recipe_level_risk_counts": {
                    key: value for key, value in risk_counts.items() if value > 0
                },
                "recipe_level_risk_count": sum(risk_counts.values()),
                "recommended_action_counts": action_counts,
                "actionable_recipe_level_action_counts": actionable_counts,
                "actionable_recipe_level_action_count": sum(
                    actionable_counts.values()
                ),
                "global_blocker_policy": (
                    "unvalidated positive confidence impact, aggregate calibration "
                    "drift, and aggregate calibration rule breaches block RI-EVOL-03; "
                    "per-recipe alpha decay, calibration watch, and regime fragility "
                    "remain shadow-only through freeze/manual/replay action queues"
                ),
            },
        }
    ]


def _confidence_gate_prompt_candidate_expected_evidence_refs(
    *,
    root_path: Path,
    failures: list[str],
) -> list[dict[str, Any]]:
    rows, row_failures, _rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/confidence_impact_observations.jsonl",
    )
    failures.extend(row_failures)
    blocked_observation_count = sum(
        1 for row in rows if str(row.get("paper_trading_status") or "") != "passed"
    )
    return [
        {
            "artifact_path": (
                "registry/report_intelligence/confidence_impact_observations.jsonl"
            ),
            "field": "paper_trading_status",
            "blocked_observation_count": blocked_observation_count,
        }
    ]


def _target_mapping_prompt_candidate_expected_evidence_refs(
    *,
    root_path: Path,
    failures: list[str],
) -> list[dict[str, Any]]:
    readiness, readiness_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/outcome_labeling_readiness.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
    )
    failures.extend(readiness_failures)
    if not readiness:
        return []
    stock_readiness = (
        readiness.get("stock_price_proxy_readiness")
        if isinstance(readiness.get("stock_price_proxy_readiness"), Mapping)
        else {}
    )
    stock_gap_counts = _positive_integer_mapping_values(
        stock_readiness.get("data_gap_counts")
    )
    target_gap_keys = (
        "stock_target_mapping_missing",
        "stock_target_missing",
        "stock_target_conflict",
    )
    target_gap_counts = {
        key: value
        for key, value in stock_gap_counts.items()
        if key in target_gap_keys
    }
    return [
        {
            "artifact_path": "registry/report_intelligence/outcome_labeling_readiness.json",
            "field": "stock_price_proxy_readiness.data_gap_counts",
            "gap_counts": target_gap_counts,
            "total_gap_count": sum(target_gap_counts.values()),
        }
    ]


def _horizon_direction_prompt_candidate_expected_evidence_refs(
    *,
    root_path: Path,
    failures: list[str],
) -> list[dict[str, Any]]:
    readiness, readiness_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/outcome_labeling_readiness.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
    )
    failures.extend(readiness_failures)
    if not readiness:
        return []
    gap_counts = _positive_integer_mapping_values(readiness.get("mapping_gap_counts"))
    stock_readiness = (
        readiness.get("stock_price_proxy_readiness")
        if isinstance(readiness.get("stock_price_proxy_readiness"), Mapping)
        else {}
    )
    industry_readiness = (
        readiness.get("industry_etf_proxy_readiness")
        if isinstance(readiness.get("industry_etf_proxy_readiness"), Mapping)
        else {}
    )
    stock_gap_counts = _positive_integer_mapping_values(
        stock_readiness.get("data_gap_counts")
    )
    industry_gap_counts = _positive_integer_mapping_values(
        industry_readiness.get("data_gap_counts")
    )
    total_gap_count = sum(
        gap_counts.get(key, 0)
        + stock_gap_counts.get(key, 0)
        + industry_gap_counts.get(key, 0)
        for key in (
            "direction_missing_or_unsupported",
            "horizon",
            "unknown_mapping_gap",
        )
    )
    return [
        {
            "artifact_path": "registry/report_intelligence/outcome_labeling_readiness.json",
            "field": "mapping_gap_counts",
            "gap_counts": gap_counts,
            "total_gap_count": total_gap_count,
        }
    ]


def _markdown_quality_prompt_candidate_expected_evidence_refs(
    *,
    root_path: Path,
    failures: list[str],
) -> list[dict[str, Any]]:
    summary, summary_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/markdown_coverage_summary.json",
        "registry/report_intelligence/markdown_coverage_summary.json",
    )
    failures.extend(summary_failures)
    if not summary:
        return []
    return [
        {
            "artifact_path": "registry/report_intelligence/markdown_coverage_summary.json",
            "field": "markdown_quality_gap_counts",
            "gap_counts": _positive_integer_mapping_values(
                summary.get("markdown_quality_gap_counts")
            ),
            "retry_queue_count": _int_or_none(summary.get("retry_queue_count")) or 0,
        }
    ]


def _tool_gap_prompt_candidate_expected_evidence_refs(
    *,
    root_path: Path,
    failures: list[str],
) -> list[dict[str, Any]]:
    rows, row_failures, _rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/tool_gaps.jsonl",
    )
    failures.extend(row_failures)
    priority_counts: dict[str, int] = {}
    for row in rows:
        bucket = str(row.get("priority_bucket") or "").strip() or "unknown"
        priority_counts[bucket] = priority_counts.get(bucket, 0) + 1
    priority_rank = {"urgent": 0, "blocked": 1, "high": 2, "medium": 3, "low": 4}
    ordered = sorted(
        rows,
        key=lambda row: (
            priority_rank.get(str(row.get("priority_bucket") or "low"), 9),
            str(row.get("tool_gap_id") or ""),
        ),
    )
    return [
        {
            "artifact_path": "registry/report_intelligence/tool_gaps.jsonl",
            "field": "priority_bucket",
            "priority_counts": dict(sorted(priority_counts.items())),
            "top_tool_gap_ids": [
                str(row.get("tool_gap_id") or "")
                for row in ordered[:10]
                if str(row.get("tool_gap_id") or "").strip()
            ],
        }
    ]


def _data_acquisition_prompt_candidate_expected_evidence_refs(
    *,
    root_path: Path,
    failures: list[str],
) -> list[dict[str, Any]]:
    rows, row_failures, _rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/data_acquisition_proposals.jsonl",
    )
    failures.extend(row_failures)
    active_rows = [
        row
        for row in rows
        if str(row.get("decision_status") or "pending_review") != "rejected"
    ]
    priority_counts: dict[str, int] = {}
    pit_counts: dict[str, int] = {}
    license_counts: dict[str, int] = {}
    for row in active_rows:
        priority = str(row.get("business_priority") or "").strip() or "unknown"
        pit_status = str(row.get("pit_feasibility_status") or "").strip() or "unknown"
        license_status = str(row.get("license_status") or "").strip() or "unknown"
        priority_counts[priority] = priority_counts.get(priority, 0) + 1
        pit_counts[pit_status] = pit_counts.get(pit_status, 0) + 1
        license_counts[license_status] = license_counts.get(license_status, 0) + 1
    return [
        {
            "artifact_path": "registry/report_intelligence/data_acquisition_proposals.jsonl",
            "field": "decision_status",
            "proposal_count": len(active_rows),
            "business_priority_counts": dict(sorted(priority_counts.items())),
            "pit_feasibility_status_counts": dict(sorted(pit_counts.items())),
            "license_status_counts": dict(sorted(license_counts.items())),
            "market_cap_metadata_gap_count": sum(
                1
                for row in active_rows
                if row.get("tool_gap_id")
                == "stock_context_market_cap_metadata_missing"
            ),
            "top_tool_gap_ids": [
                str(row.get("tool_gap_id") or "")
                for row in active_rows[:10]
                if str(row.get("tool_gap_id") or "").strip()
            ],
        }
    ]


def _paper_trading_diagnostic_evidence(
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    diagnostics = (
        summary.get("direct_pit_binding_diagnostics")
        if isinstance(summary.get("direct_pit_binding_diagnostics"), Mapping)
        else {}
    )
    if not diagnostics:
        return {}
    evidence: dict[str, Any] = {
        "artifact_path": "registry/report_intelligence/recipe_paper_trading_summary.json",
        "field": "direct_pit_binding_diagnostics",
        "status": str(diagnostics.get("status") or ""),
        "recipe_count": _int_or_none(diagnostics.get("recipe_count")) or 0,
        "direct_pit_bound_recipe_count": _int_or_none(
            diagnostics.get("direct_pit_bound_recipe_count")
        )
        or 0,
        "no_direct_recipe_outcome_binding_count": _int_or_none(
            diagnostics.get("no_direct_recipe_outcome_binding_count")
        )
        or 0,
        "insufficient_effective_n_count": _int_or_none(
            diagnostics.get("insufficient_effective_n_count")
        )
        or 0,
        "required_tools_not_shadow_implemented_count": _int_or_none(
            diagnostics.get("required_tools_not_shadow_implemented_count")
        )
        or 0,
        "next_actions": _string_items(diagnostics.get("next_actions")),
    }
    details = (
        diagnostics.get("binding_gap_details")
        if isinstance(diagnostics.get("binding_gap_details"), Mapping)
        else {}
    )
    if details:
        evidence["binding_gap_details"] = {
            "diagnostic_version": str(details.get("diagnostic_version") or ""),
            "artifact_counts": _integer_mapping_values(details.get("artifact_counts")),
            "method_source_linkage": _integer_mapping_values(
                details.get("method_source_linkage")
            ),
            "forecast_outcome_linkage": _integer_mapping_values(
                details.get("forecast_outcome_linkage")
            ),
            "footprint_source_linkage": _integer_mapping_values(
                details.get("footprint_source_linkage")
            ),
            "recipe_binding_linkage": _integer_mapping_values(
                details.get("recipe_binding_linkage")
            ),
            "missing_artifact_flags": _string_items(
                details.get("missing_artifact_flags")
            ),
            "next_actions": _string_items(details.get("next_actions")),
        }
    return evidence


def _recipe_paper_trading_prompt_candidate_expected_evidence_refs(
    *,
    root_path: Path,
    failures: list[str],
) -> list[dict[str, Any]]:
    runs, runs_failures, _runs_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/recipe_paper_trading_runs.jsonl",
    )
    summary, summary_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/recipe_paper_trading_summary.json",
        "registry/report_intelligence/recipe_paper_trading_summary.json",
    )
    failures.extend(runs_failures)
    failures.extend(summary_failures)
    blocker_counts: dict[str, int] = {}
    for run in runs:
        for reason in _string_items(run.get("blocked_reasons")):
            blocker_counts[reason] = blocker_counts.get(reason, 0) + 1
    expected_refs: list[dict[str, Any]] = [
        {
            "artifact_path": "registry/report_intelligence/recipe_paper_trading_runs.jsonl",
            "field": "blocked_reasons",
            "blocker_counts": dict(sorted(blocker_counts.items())),
        }
    ]
    if summary:
        diagnostic_evidence = _paper_trading_diagnostic_evidence(summary)
        if diagnostic_evidence:
            expected_refs.append(diagnostic_evidence)
    return expected_refs


def _prompt_mutation_matching_evidence_ref(
    row: Mapping[str, Any],
    *,
    artifact_path: str,
    field: str,
    row_label: str,
    failures: list[str],
) -> Mapping[str, Any] | None:
    evidence_refs = row.get("evidence_refs")
    if not isinstance(evidence_refs, Sequence) or isinstance(evidence_refs, str):
        return None
    matches = [
        evidence
        for evidence in evidence_refs
        if isinstance(evidence, Mapping)
        and evidence.get("artifact_path") == artifact_path
        and evidence.get("field") == field
    ]
    if not matches:
        failures.append(
            f"{row_label}.evidence_refs: missing {artifact_path} {field}"
        )
        return None
    if len(matches) > 1:
        failures.append(
            f"{row_label}.evidence_refs: duplicate {artifact_path} {field}"
        )
    return matches[0]


def _validate_prompt_mutation_expected_refs(
    row: Mapping[str, Any],
    *,
    row_label: str,
    candidate_type: str,
    expected_refs: Sequence[Mapping[str, Any]],
    evidence_source: str,
    failures: list[str],
) -> None:
    for expected in expected_refs:
        field = str(expected["field"])
        evidence = _prompt_mutation_matching_evidence_ref(
            row,
            artifact_path=str(expected["artifact_path"]),
            field=field,
            row_label=row_label,
            failures=failures,
        )
        if evidence is None:
            continue
        for key, expected_value in expected.items():
            if key in {"artifact_path", "field"}:
                continue
            if not _prompt_mutation_evidence_values_equal(
                evidence.get(key),
                expected_value,
            ):
                failures.append(
                    f"{row_label}.{candidate_type}.evidence_refs.{field}.{key}: "
                    f"must match {evidence_source} public evidence"
                )


def _validate_prompt_mutation_governed_evidence(
    row: Mapping[str, Any],
    *,
    row_label: str,
    gate: Mapping[str, Any],
    root_path: Path,
) -> list[str]:
    failures: list[str] = []
    candidate_type = str(row.get("candidate_type") or "")
    if candidate_type == "gold_quality_prompt_repair_rule":
        evidence = _prompt_mutation_matching_evidence_ref(
            row,
            artifact_path="registry/report_intelligence/evolution_readiness_gate.json",
            field="checks.RI-EVOL-05.evidence",
            row_label=row_label,
            failures=failures,
        )
        if evidence is None:
            return failures
        expected = _gold_quality_prompt_candidate_expected_evidence(gate)
        if not expected:
            failures.append(
                f"{row_label}.{candidate_type}: cannot locate RI-EVOL-05 evidence"
            )
            return failures
        for field, expected_value in expected.items():
            if not _prompt_mutation_evidence_values_equal(
                evidence.get(field), expected_value
            ):
                failures.append(
                    f"{row_label}.{candidate_type}.evidence_refs.{field}: "
                    "must match RI-EVOL-05 public evidence"
                )
    elif candidate_type == "footprint_quality_prompt_repair_rule":
        evidence = _prompt_mutation_matching_evidence_ref(
            row,
            artifact_path=(
                "registry/report_intelligence/"
                "analytical_footprint_review_summary.json"
            ),
            field="precision_recall_report",
            row_label=row_label,
            failures=failures,
        )
        if evidence is None:
            return failures
        summary, summary_failures = _read_mapping_json(
            root_path
            / "registry/report_intelligence/analytical_footprint_review_summary.json",
            "registry/report_intelligence/analytical_footprint_review_summary.json",
        )
        failures.extend(summary_failures)
        if not summary:
            return failures
        expected = _footprint_quality_prompt_candidate_expected_evidence(summary)
        for field, expected_value in expected.items():
            if not _prompt_mutation_evidence_values_equal(
                evidence.get(field), expected_value
            ):
                failures.append(
                    f"{row_label}.{candidate_type}.evidence_refs.{field}: "
                    "must match analytical footprint review summary"
                )
    elif candidate_type == "evolution_refresh_stability_rule":
        expected_refs = _stability_prompt_candidate_expected_evidence_refs(gate)
        if not expected_refs:
            failures.append(
                f"{row_label}.{candidate_type}: no current RI-EVOL-03/04/06 "
                "stability blockers require a mutation candidate"
            )
            return failures
        expected_fields = sorted(str(item["field"]) for item in expected_refs)
        actual_refs = row.get("evidence_refs")
        actual_ref_sequence = (
            actual_refs
            if isinstance(actual_refs, Sequence) and not isinstance(actual_refs, str)
            else []
        )
        actual_fields = sorted(
            str(evidence.get("field") or "")
            for evidence in actual_ref_sequence
            if isinstance(evidence, Mapping)
            and evidence.get("artifact_path")
            == "registry/report_intelligence/evolution_readiness_gate.json"
            and str(evidence.get("field") or "")
            in {
                "checks.RI-EVOL-03.evidence",
                "checks.RI-EVOL-04.evidence",
                "checks.RI-EVOL-06.evidence",
            }
        )
        if actual_fields != expected_fields:
            failures.append(
                f"{row_label}.{candidate_type}.evidence_refs: must match "
                "current blocked RI-EVOL-03/04/06 stability checks"
            )
        for expected in expected_refs:
            field = str(expected["field"])
            evidence = _prompt_mutation_matching_evidence_ref(
                row,
                artifact_path=str(expected["artifact_path"]),
                field=field,
                row_label=row_label,
                failures=failures,
            )
            if evidence is None:
                continue
            for key in ("check_id", "blockers", "evidence", "thresholds"):
                if not _prompt_mutation_evidence_values_equal(
                    evidence.get(key),
                    expected.get(key),
                ):
                    failures.append(
                        f"{row_label}.{candidate_type}.evidence_refs.{field}.{key}: "
                        "must match current evolution readiness gate"
                    )
    elif candidate_type == "forecast_gold_set_review_rule":
        _validate_prompt_mutation_expected_refs(
            row,
            row_label=row_label,
            candidate_type=candidate_type,
            expected_refs=_forecast_gold_review_prompt_candidate_expected_evidence_refs(
                gate
            ),
            evidence_source="RI-EVOL-05 gold review gate",
            failures=failures,
        )
    elif candidate_type == "regime_mechanism_extraction_rule":
        expected_refs = _regime_mechanism_prompt_candidate_expected_evidence_refs(
            root_path=root_path,
            failures=failures,
        )
        _validate_prompt_mutation_expected_refs(
            row,
            row_label=row_label,
            candidate_type=candidate_type,
            expected_refs=expected_refs,
            evidence_source="outcome readiness regime/mechanism",
            failures=failures,
        )
    elif candidate_type == "industry_proxy_mapping_rule":
        expected_refs = _industry_mapping_prompt_candidate_expected_evidence_refs(
            root_path=root_path,
            failures=failures,
        )
        for expected in expected_refs:
            field = str(expected["field"])
            evidence = _prompt_mutation_matching_evidence_ref(
                row,
                artifact_path=str(expected["artifact_path"]),
                field=field,
                row_label=row_label,
                failures=failures,
            )
            if evidence is None:
                continue
            for key, expected_value in expected.items():
                if key in {"artifact_path", "field"}:
                    continue
                if not _prompt_mutation_evidence_values_equal(
                    evidence.get(key),
                    expected_value,
                ):
                    failures.append(
                        f"{row_label}.{candidate_type}.evidence_refs.{field}.{key}: "
                        "must match industry ETF PIT/readiness public evidence"
                    )
    elif candidate_type == "calibration_fix_required":
        expected_refs = _calibration_prompt_candidate_expected_evidence_refs(
            root_path=root_path,
            failures=failures,
        )
        for expected in expected_refs:
            field = str(expected["field"])
            evidence = _prompt_mutation_matching_evidence_ref(
                row,
                artifact_path=str(expected["artifact_path"]),
                field=field,
                row_label=row_label,
                failures=failures,
            )
            if evidence is None:
                continue
            for key, expected_value in expected.items():
                if key in {"artifact_path", "field"}:
                    continue
                if not _prompt_mutation_evidence_values_equal(
                    evidence.get(key),
                    expected_value,
                ):
                    failures.append(
                        f"{row_label}.{candidate_type}.evidence_refs.{field}.{key}: "
                        "must match confidence impact monitor public evidence"
                    )
    elif candidate_type in {
        "confidence_gate_rule",
        "target_mapping_rule",
        "horizon_direction_rule",
        "markdown_quality_rule",
    }:
        if candidate_type == "confidence_gate_rule":
            expected_refs = _confidence_gate_prompt_candidate_expected_evidence_refs(
                root_path=root_path,
                failures=failures,
            )
            evidence_source = "confidence impact observations"
        elif candidate_type == "target_mapping_rule":
            expected_refs = _target_mapping_prompt_candidate_expected_evidence_refs(
                root_path=root_path,
                failures=failures,
            )
            evidence_source = "stock readiness"
        elif candidate_type == "horizon_direction_rule":
            expected_refs = _horizon_direction_prompt_candidate_expected_evidence_refs(
                root_path=root_path,
                failures=failures,
            )
            evidence_source = "outcome readiness mapping gaps"
        else:
            expected_refs = _markdown_quality_prompt_candidate_expected_evidence_refs(
                root_path=root_path,
                failures=failures,
            )
            evidence_source = "Markdown coverage summary"
        for expected in expected_refs:
            field = str(expected["field"])
            evidence = _prompt_mutation_matching_evidence_ref(
                row,
                artifact_path=str(expected["artifact_path"]),
                field=field,
                row_label=row_label,
                failures=failures,
            )
            if evidence is None:
                continue
            for key, expected_value in expected.items():
                if key in {"artifact_path", "field"}:
                    continue
                if not _prompt_mutation_evidence_values_equal(
                    evidence.get(key),
                    expected_value,
                ):
                    failures.append(
                        f"{row_label}.{candidate_type}.evidence_refs.{field}.{key}: "
                        f"must match {evidence_source} public evidence"
                    )
    elif candidate_type == "tool_gap_prioritization_rule":
        expected_refs = _tool_gap_prompt_candidate_expected_evidence_refs(
            root_path=root_path,
            failures=failures,
        )
        _validate_prompt_mutation_expected_refs(
            row,
            row_label=row_label,
            candidate_type=candidate_type,
            expected_refs=expected_refs,
            evidence_source="tool gap priority",
            failures=failures,
        )
    elif candidate_type == "data_acquisition_prioritization_rule":
        expected_refs = _data_acquisition_prompt_candidate_expected_evidence_refs(
            root_path=root_path,
            failures=failures,
        )
        _validate_prompt_mutation_expected_refs(
            row,
            row_label=row_label,
            candidate_type=candidate_type,
            expected_refs=expected_refs,
            evidence_source="data acquisition proposals",
            failures=failures,
        )
    elif candidate_type == "recipe_paper_trading_rule":
        expected_refs = _recipe_paper_trading_prompt_candidate_expected_evidence_refs(
            root_path=root_path,
            failures=failures,
        )
        _validate_prompt_mutation_expected_refs(
            row,
            row_label=row_label,
            candidate_type=candidate_type,
            expected_refs=expected_refs,
            evidence_source="recipe paper-trading",
            failures=failures,
        )
    return failures


def _validate_prior_compiler_candidate_contract(
    row: Mapping[str, Any],
    *,
    row_label: str,
) -> list[str]:
    candidate_type = str(row.get("candidate_type") or "")
    if candidate_type not in (
        PRIOR_COMPILER_REFUSAL_CANDIDATE_TYPES | PRIOR_COMPILER_CANDIDATE_TYPES
    ):
        return []
    failures: list[str] = []
    blocked_by = set(_string_items(row.get("blocked_by")))
    evidence_refs = row.get("evidence_refs")
    if not isinstance(evidence_refs, Sequence) or isinstance(evidence_refs, str):
        return failures
    refusal_reasons: set[str] = set()
    candidate_kinds: set[str] = set()
    for evidence in evidence_refs:
        if not isinstance(evidence, Mapping):
            continue
        candidate_kind = str(evidence.get("candidate_kind") or "").strip()
        if candidate_kind:
            candidate_kinds.add(candidate_kind)
        refusal_reasons.update(_string_items(evidence.get("refusal_reasons")))
    if candidate_type in PRIOR_COMPILER_REFUSAL_CANDIDATE_TYPES:
        if not refusal_reasons:
            failures.append(f"{row_label}.evidence_refs.refusal_reasons: required")
        unsupported = sorted(refusal_reasons - PRIOR_COMPILER_ALLOWED_REFUSAL_REASONS)
        if unsupported:
            failures.append(
                f"{row_label}.evidence_refs.refusal_reasons: unsupported "
                + ", ".join(unsupported)
            )
        missing_blockers = sorted(refusal_reasons - blocked_by)
        if missing_blockers:
            failures.append(
                f"{row_label}.blocked_by: must include refusal reasons "
                + ", ".join(missing_blockers)
            )
        if not any(kind.endswith("_refusal") for kind in candidate_kinds):
            failures.append(f"{row_label}.evidence_refs.candidate_kind: must be refusal")
    else:
        if refusal_reasons:
            failures.append(
                f"{row_label}.evidence_refs.refusal_reasons: must be empty for candidate"
            )
        if not any(kind.endswith("_candidate") for kind in candidate_kinds):
            failures.append(f"{row_label}.evidence_refs.candidate_kind: must be candidate")
    return failures


def _validate_prompt_mutation_candidate_contract(
    root_path: Path,
) -> tuple[int, list[str]]:
    (
        candidate_rows,
        candidate_failures,
        _candidate_rows_present,
    ) = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/prompt_mutation_candidates.jsonl",
    )
    gate, gate_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/evolution_readiness_gate.json",
        "registry/report_intelligence/evolution_readiness_gate.json",
    )
    failures = [*candidate_failures, *gate_failures]
    gate_status = str(gate.get("gate_status") or "") if gate else ""
    gate_blocked = gate_status != "passed"

    for index, row in enumerate(candidate_rows, 1):
        row_label = f"prompt_mutation_candidates row {index}"
        if row.get("promotion_state") != "shadow_candidate_only":
            failures.append(
                f"{row_label}.promotion_state: must remain shadow_candidate_only"
            )
        if row.get("production_prompt_change_allowed") is not False:
            failures.append(
                f"{row_label}.production_prompt_change_allowed: must be false"
            )
        if row.get("private_text_included") is not False:
            failures.append(f"{row_label}.private_text_included: must be false")
        if row.get("manual_review_required") is not True:
            failures.append(f"{row_label}.manual_review_required: must be true")
        if gate_blocked and not _string_items(row.get("blocked_by")):
            failures.append(
                f"{row_label}.blocked_by: required while evolution gate is blocked"
            )
        validation_requirements = tuple(_string_items(row.get("validation_requirements")))
        if validation_requirements != PROMPT_MUTATION_REQUIRED_VALIDATION_REQUIREMENTS:
            failures.append(
                f"{row_label}.validation_requirements: must be "
                + ", ".join(PROMPT_MUTATION_REQUIRED_VALIDATION_REQUIREMENTS)
            )
        evidence_refs = row.get("evidence_refs")
        if not isinstance(evidence_refs, Sequence) or isinstance(evidence_refs, str):
            failures.append(f"{row_label}.evidence_refs: expected array")
        elif not evidence_refs:
            failures.append(f"{row_label}.evidence_refs: at least one evidence ref required")
        else:
            for evidence_index, evidence in enumerate(evidence_refs, 1):
                evidence_label = f"{row_label}.evidence_refs[{evidence_index}]"
                if not isinstance(evidence, Mapping):
                    failures.append(f"{evidence_label}: expected object")
                    continue
                artifact_path = str(evidence.get("artifact_path") or "").strip()
                if not artifact_path:
                    failures.append(f"{evidence_label}.artifact_path: required")
                    continue
                artifact_parts = Path(artifact_path).parts
                if Path(artifact_path).is_absolute() or ".." in artifact_parts:
                    failures.append(
                        f"{evidence_label}.artifact_path: must be repo-relative"
                    )
                if not artifact_path.startswith(PROMPT_MUTATION_PUBLIC_EVIDENCE_PREFIXES):
                    failures.append(
                        f"{evidence_label}.artifact_path: must point to a public RKE aggregate artifact"
                    )
                elif not (root_path / artifact_path).exists():
                    failures.append(
                        f"{evidence_label}.artifact_path: referenced public evidence artifact must exist"
                    )
                if any(
                    marker in artifact_path
                    for marker in PROMPT_MUTATION_PRIVATE_EVIDENCE_PATH_MARKERS
                ):
                    failures.append(
                        f"{evidence_label}.artifact_path: private evidence path forbidden"
                    )
        failures.extend(
            _validate_prompt_mutation_governed_evidence(
                row,
                row_label=row_label,
                gate=gate or {},
                root_path=root_path,
            )
        )
        failures.extend(
            _validate_prior_compiler_candidate_contract(row, row_label=row_label)
        )
        failures.extend(_public_forbidden_text_failures(row, path=row_label))

    return len(candidate_rows), failures


PROFILE_OUTCOME_LAYER_REQUIRED_SUMMARY_FIELDS = (
    "label_type",
    "benchmark_family",
    "cost_model_id",
    "n_nominal",
    "n_effective",
    "mean_after_cost_alpha",
    "hit_rate",
    "shrunk_after_cost_alpha",
    "shrunk_hit_rate",
    "statistical_reliability_bucket",
)

PROFILE_OUTCOME_LAYER_BASE_KEY_FIELDS = (
    "label_type",
    "benchmark_family",
    "cost_model_id",
)

PROFILE_OUTCOME_LAYER_EXTENDED_KEY_FIELDS = (
    "target_family",
    "agent_layer",
    "regime_bucket",
)

DOMAIN_RATING_SUPPORT_REQUIRED_COUNT_FIELDS = (
    "rating_bucket_counts",
    "failure_mode_counts",
    "fundamental_metric_family_counts",
    "target_family_counts",
    "agent_layer_counts",
    "regime_bucket_counts",
    "mapping_confidence_counts",
)

DOMAIN_RATING_ALLOWED_BUCKETS = {
    "supportive_evidence",
    "mixed_evidence",
    "contradictory_evidence",
    "pending_or_unrated",
}


def _profile_layer_expected_effective_n(
    profile: Mapping[str, Any],
    profile_kind: str,
) -> float:
    if profile_kind == "method":
        source_support = profile.get("source_support")
        if not isinstance(source_support, Mapping):
            return 0.0
        return _float_or_none(source_support.get("n_effective_reports")) or 0.0
    return _float_or_none(profile.get("n_effective")) or 0.0


def _profile_layer_uses_extended_keys(
    *,
    policy: str,
    summaries: Sequence[Any],
    keys: Sequence[Any],
) -> bool:
    if any(field in policy for field in PROFILE_OUTCOME_LAYER_EXTENDED_KEY_FIELDS):
        return True
    for row in (*summaries, *keys):
        if isinstance(row, Mapping) and any(
            field in row for field in PROFILE_OUTCOME_LAYER_EXTENDED_KEY_FIELDS
        ):
            return True
    return False


def _profile_layer_key(
    row: Mapping[str, Any],
    fields: Sequence[str],
) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "") for field in fields)


def _validate_domain_rating_support(value: Any, *, row_label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, Mapping):
        return [f"{row_label}: expected object"]
    failures = _public_forbidden_text_failures(value, path=row_label)
    if value.get("privacy_policy") != "redacted_internal_rating_aggregate_only":
        failures.append(
            f"{row_label}.privacy_policy: must be redacted_internal_rating_aggregate_only"
        )
    for field in DOMAIN_RATING_SUPPORT_REQUIRED_COUNT_FIELDS:
        counts = value.get(field)
        if not isinstance(counts, Mapping):
            failures.append(f"{row_label}.{field}: expected object")
            continue
        for key, count in counts.items():
            if not str(key).strip():
                failures.append(f"{row_label}.{field}: blank key forbidden")
            int_count = _int_or_none(count)
            if int_count is None or int_count < 0:
                failures.append(f"{row_label}.{field}.{key}: count must be nonnegative")
            if field == "rating_bucket_counts" and key not in DOMAIN_RATING_ALLOWED_BUCKETS:
                failures.append(f"{row_label}.{field}.{key}: unsupported rating bucket")
    return failures


def _validate_profile_outcome_layer_support(
    root_path: Path,
) -> tuple[int, list[str]]:
    profile_specs = (
        (
            "source",
            "registry/report_intelligence/source_performance_profiles.jsonl",
            "profile_id",
        ),
        (
            "viewpoint",
            "registry/report_intelligence/viewpoint_performance_profiles.jsonl",
            "viewpoint_profile_id",
        ),
        (
            "method",
            "registry/report_intelligence/method_performance_profiles.jsonl",
            "method_profile_id",
        ),
    )
    failures: list[str] = []
    item_count = 0
    for profile_kind, artifact_path, id_field in profile_specs:
        rows, row_failures, _rows_present = _load_public_semantic_jsonl(
            root_path,
            artifact_path,
        )
        failures.extend(row_failures)
        item_count += len(rows)
        for index, profile in enumerate(rows, 1):
            profile_id = str(profile.get(id_field) or f"{profile_kind}-row-{index}")
            row_label = f"{artifact_path} {profile_id}"
            support = profile.get("outcome_layer_support")
            if not isinstance(support, Mapping):
                failures.append(f"{row_label}.outcome_layer_support: expected object")
                continue
            summaries = support.get("layer_summaries")
            if not isinstance(summaries, Sequence) or isinstance(summaries, str):
                failures.append(
                    f"{row_label}.outcome_layer_support.layer_summaries: expected array"
                )
                summaries = []
            keys = support.get("layer_keys")
            if not isinstance(keys, Sequence) or isinstance(keys, str):
                failures.append(
                    f"{row_label}.outcome_layer_support.layer_keys: expected array"
                )
                keys = []
            layer_count = _int_or_none(support.get("layer_count"))
            if layer_count != len(summaries) or layer_count != len(keys):
                failures.append(
                    f"{row_label}.outcome_layer_support.layer_count: must match layer_summaries and layer_keys"
                )
            mixed_layer = support.get("mixed_layer_profile")
            if mixed_layer is not (len(summaries) > 1):
                failures.append(
                    f"{row_label}.outcome_layer_support.mixed_layer_profile: must match layer_count > 1"
                )
            policy = str(support.get("layering_policy") or "")
            key_fields = PROFILE_OUTCOME_LAYER_BASE_KEY_FIELDS
            if _profile_layer_uses_extended_keys(
                policy=policy,
                summaries=summaries,
                keys=keys,
            ):
                key_fields = (
                    *PROFILE_OUTCOME_LAYER_BASE_KEY_FIELDS,
                    *PROFILE_OUTCOME_LAYER_EXTENDED_KEY_FIELDS,
                )
            for required_text in key_fields:
                if required_text not in policy:
                    failures.append(
                        f"{row_label}.outcome_layer_support.layering_policy: must mention {required_text}"
                    )
            failures.extend(
                _validate_domain_rating_support(
                    support.get("domain_rating_support"),
                    row_label=f"{row_label}.outcome_layer_support.domain_rating_support",
                )
            )
            summary_keys: list[tuple[str, ...]] = []
            n_effective_sum = 0.0
            for summary_index, summary in enumerate(summaries, 1):
                summary_label = (
                    f"{row_label}.outcome_layer_support.layer_summaries[{summary_index}]"
                )
                if not isinstance(summary, Mapping):
                    failures.append(f"{summary_label}: expected object")
                    continue
                for field in PROFILE_OUTCOME_LAYER_REQUIRED_SUMMARY_FIELDS:
                    if field not in summary:
                        failures.append(f"{summary_label}.{field}: required")
                failures.extend(
                    _validate_domain_rating_support(
                        summary.get("domain_rating_support"),
                        row_label=f"{summary_label}.domain_rating_support",
                    )
                )
                key = _profile_layer_key(summary, key_fields)
                if not all(key):
                    failures.append(
                        f"{summary_label}: {', '.join(key_fields)} required"
                    )
                summary_keys.append(key)
                n_effective = _float_or_none(summary.get("n_effective"))
                if n_effective is None or n_effective < 0:
                    failures.append(f"{summary_label}.n_effective: must be nonnegative")
                else:
                    n_effective_sum += n_effective
            observed_keys: list[tuple[str, ...]] = []
            for key_index, key_row in enumerate(keys, 1):
                key_label = (
                    f"{row_label}.outcome_layer_support.layer_keys[{key_index}]"
                )
                if not isinstance(key_row, Mapping):
                    failures.append(f"{key_label}: expected object")
                    continue
                key = _profile_layer_key(key_row, key_fields)
                if not all(key):
                    failures.append(
                        f"{key_label}: {', '.join(key_fields)} required"
                    )
                observed_keys.append(key)
            if sorted(observed_keys) != sorted(summary_keys):
                failures.append(
                    f"{row_label}.outcome_layer_support.layer_keys: must match layer_summaries"
                )
            expected_n = _profile_layer_expected_effective_n(profile, profile_kind)
            if not _nearly_equal(n_effective_sum, expected_n):
                failures.append(
                    f"{row_label}.outcome_layer_support.layer_summaries.n_effective: expected sum {expected_n}"
                )
    return item_count, failures


def _manual_progress_forbidden_text_failures(
    value: Any,
    *,
    path: str,
) -> list[str]:
    failures: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            child_path = f"{path}.{key}"
            if (
                normalized_key in REPORT_INTELLIGENCE_PUBLIC_FORBIDDEN_TEXT_KEYS
                and bool(item)
            ):
                if not _manual_progress_allows_private_key_as_count(
                    child_path,
                    item,
                ):
                    failures.append(
                        f"{child_path}: private/source text field forbidden"
                    )
                    continue
            failures.extend(
                _manual_progress_forbidden_text_failures(item, path=child_path)
            )
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for index, item in enumerate(value):
            failures.extend(
                _manual_progress_forbidden_text_failures(
                    item,
                    path=f"{path}[{index}]",
                )
            )
    return failures


def _manual_progress_allows_private_key_as_count(path: str, value: Any) -> bool:
    if (
        ".missing_required_fields." in path
        or ".invalid_required_fields." in path
    ):
        return type(value) is int
    if (
        ".review_field_workload." not in path
        and "_review_field_workload." not in path
    ):
        return False
    if not isinstance(value, Mapping):
        return False
    return all(type(item) is int for item in value.values())


def _validate_manual_review_batch_overview_contract(
    gate: Mapping[str, Any],
    *,
    review_kind: str,
    batch_plan: Sequence[Mapping[str, Any]],
    pending_rows: int | None,
    ready: Any,
    row_label: str,
    failures: list[str],
) -> None:
    overview = gate.get("batch_overview")
    overview_label = f"{row_label}.batch_overview"
    if overview is None:
        failures.append(f"{overview_label}: expected object")
        return
    if not isinstance(overview, Mapping):
        failures.append(f"{overview_label}: expected object")
        return
    if review_kind not in {"gold_set", "footprint_review"}:
        if overview:
            failures.append(f"{overview_label}: expected empty object")
        return

    def require_equal(field: str, expected: Any) -> None:
        if overview.get(field) != expected:
            failures.append(f"{overview_label}.{field}: expected {expected}")

    if ready is True:
        require_equal("batch_count", 0)
        require_equal("pending_rows", 0)
        require_equal("promotion_input_path", gate.get("input_path"))
        require_equal("rerun_review_progress_after_batch_apply", False)
        return

    expected_pending = int(pending_rows or 0)
    current = gate.get("current_batch_status")
    current = current if isinstance(current, Mapping) else {}
    evidence = current.get("evidence_status")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    target = current.get("target_status")
    target = target if isinstance(target, Mapping) else {}
    current_rows = int(_int_or_none(current.get("rows")) or 0)
    target_aligned = bool(target.get("aligned")) if target else None
    evidence_aligned = bool(evidence.get("aligned")) if evidence else None
    covered_rows = (
        current_rows
        if bool(current.get("exists"))
        and int(_int_or_none(current.get("malformed_rows")) or 0) == 0
        and target
        and target_aligned is True
        else 0
    )

    require_equal("batch_count", len(batch_plan))
    require_equal("pending_rows", expected_pending)
    require_equal("current_batch_path", current.get("path"))
    require_equal("current_batch_rows", current_rows)
    require_equal(
        "current_batch_pending_rows",
        int(_int_or_none(current.get("pending_rows")) or 0),
    )
    require_equal("current_batch_target_covered_rows", covered_rows)
    require_equal(
        "remaining_rows_after_current_batch",
        max(expected_pending - covered_rows, 0),
    )
    require_equal("current_batch_evidence_aligned", evidence_aligned)
    require_equal("current_batch_target_aligned", target_aligned)
    require_equal(
        "current_batch_target_hash_mismatch_count",
        int(_int_or_none(target.get("target_row_hash_mismatch_count")) or 0)
        if target
        else 0,
    )
    require_equal(
        "current_batch_evidence_path",
        str(evidence.get("path") or "") if evidence else "",
    )
    if batch_plan:
        first = batch_plan[0]
        last = batch_plan[-1]
        first_limit = int(_int_or_none(first.get("limit")) or 0)
        require_equal("next_batch_offset", int(_int_or_none(first.get("offset")) or 0))
        require_equal("next_batch_limit", first_limit)
        require_equal(
            "next_batch_pending_row_start",
            int(_int_or_none(first.get("pending_row_start")) or 0),
        )
        require_equal(
            "next_batch_pending_row_end",
            int(_int_or_none(first.get("pending_row_end")) or 0),
        )
        require_equal("final_batch_offset", int(_int_or_none(last.get("offset")) or 0))
        require_equal("final_batch_limit", int(_int_or_none(last.get("limit")) or 0))
        require_equal(
            "remaining_rows_after_next_batch",
            max(expected_pending - first_limit, 0),
        )
        require_equal(
            "current_batch_covers_next_batch",
            covered_rows >= first_limit if first_limit else False,
        )
    workload = overview.get("current_batch_review_field_workload")
    if isinstance(workload, Mapping) and workload:
        expected_summary = _expected_review_field_workload_summary(workload)
        if (
            overview.get("current_batch_review_field_workload_summary")
            != expected_summary
        ):
            failures.append(
                f"{overview_label}.current_batch_review_field_workload_summary: "
                "must match current_batch_review_field_workload"
            )
        expected_action_order = _expected_review_field_action_order(workload)
        if (
            overview.get("current_batch_review_field_action_order")
            != expected_action_order
        ):
            failures.append(
                f"{overview_label}.current_batch_review_field_action_order: "
                "must match current_batch_review_field_workload"
            )
        expected_workflow_groups = _expected_review_field_workflow_groups(
            workload,
            manual_review_field_contract(review_kind),
        )
        if (
            overview.get("current_batch_review_field_workflow_groups")
            != expected_workflow_groups
        ):
            failures.append(
                f"{overview_label}.current_batch_review_field_workflow_groups: "
                "must match current_batch_review_field_workload"
            )


def _expected_review_field_workload_summary(
    workload: Mapping[str, Any],
) -> Mapping[str, int]:
    summary = {
        "field_count": 0,
        "fields_with_draft_decisions": 0,
        "fields_with_draft_text": 0,
        "fields_with_manual_review_required": 0,
        "missing_required_cells": 0,
        "draft_decision_available_cells": 0,
        "draft_text_available_cells": 0,
        "manual_review_required_cells": 0,
        "suggested_true_cells": 0,
        "suggested_false_cells": 0,
        "suggested_null_cells": 0,
        "suggested_other_cells": 0,
    }
    for item in workload.values():
        if not isinstance(item, Mapping):
            continue
        summary["field_count"] += 1
        draft_rows = int(_int_or_none(item.get("draft_decision_available_rows")) or 0)
        draft_text_rows = int(_int_or_none(item.get("draft_text_available_rows")) or 0)
        manual_rows = int(_int_or_none(item.get("manual_decision_required_rows")) or 0)
        if draft_rows:
            summary["fields_with_draft_decisions"] += 1
        if draft_text_rows:
            summary["fields_with_draft_text"] += 1
        if manual_rows:
            summary["fields_with_manual_review_required"] += 1
        summary["missing_required_cells"] += int(
            _int_or_none(item.get("missing_required_rows")) or 0
        )
        summary["draft_decision_available_cells"] += draft_rows
        summary["draft_text_available_cells"] += draft_text_rows
        summary["manual_review_required_cells"] += manual_rows
        summary["suggested_true_cells"] += int(
            _int_or_none(item.get("suggested_true_rows")) or 0
        )
        summary["suggested_false_cells"] += int(
            _int_or_none(item.get("suggested_false_rows")) or 0
        )
        summary["suggested_null_cells"] += int(
            _int_or_none(item.get("suggested_null_rows")) or 0
        )
        summary["suggested_other_cells"] += int(
            _int_or_none(item.get("suggested_other_rows")) or 0
        )
    return summary


def _expected_review_field_action_order(
    workload: Mapping[str, Any],
) -> Mapping[str, Any]:
    manual_fields: list[dict[str, Any]] = []
    draft_fields: list[dict[str, Any]] = []
    draft_text_fields: list[dict[str, Any]] = []
    for field_name, item in sorted(workload.items()):
        if not isinstance(item, Mapping):
            continue
        missing_rows = int(_int_or_none(item.get("missing_required_rows")) or 0)
        draft_rows = int(_int_or_none(item.get("draft_decision_available_rows")) or 0)
        draft_text_rows = int(_int_or_none(item.get("draft_text_available_rows")) or 0)
        manual_rows = int(_int_or_none(item.get("manual_decision_required_rows")) or 0)
        field_summary = {
            "field": str(field_name),
            "missing_required_rows": missing_rows,
            "draft_decision_available_rows": draft_rows,
            "manual_decision_required_rows": manual_rows,
        }
        if manual_rows:
            manual_fields.append(dict(field_summary))
        if draft_rows:
            draft_fields.append(dict(field_summary))
        if draft_text_rows:
            draft_text_fields.append(
                {
                    **field_summary,
                    "draft_text_available_rows": draft_text_rows,
                }
            )
    manual_fields.sort(
        key=lambda item: (
            -int(item["manual_decision_required_rows"]),
            -int(item["missing_required_rows"]),
            str(item["field"]),
        )
    )
    draft_fields.sort(
        key=lambda item: (
            -int(item["draft_decision_available_rows"]),
            -int(item["missing_required_rows"]),
            str(item["field"]),
        )
    )
    draft_text_fields.sort(
        key=lambda item: (
            -int(item["draft_text_available_rows"]),
            -int(item["missing_required_rows"]),
            str(item["field"]),
        )
    )
    return {
        "manual_review_required_fields": manual_fields,
        "draft_decision_review_fields": draft_fields,
        "draft_text_review_fields": draft_text_fields,
    }


def _expected_review_field_workflow_groups(
    workload: Mapping[str, Any],
    field_contract: Mapping[str, Any],
) -> Mapping[str, Any]:
    boolean_fields = {str(field) for field in field_contract.get("boolean_fields") or ()}
    date_fields = {
        str(field)
        for field in (
            field_contract.get("date_fields").keys()
            if isinstance(field_contract.get("date_fields"), Mapping)
            else ()
        )
    }
    text_fields = {str(field) for field in field_contract.get("text_fields") or ()}
    metadata_fields = date_fields | {
        "opened_at",
        "opened_by",
        "open_count",
        "review_date",
        "reviewer",
    }
    groups: dict[str, list[dict[str, Any]]] = {
        "decision_fields_need_review": [],
        "metadata_fields_need_fill": [],
        "text_fields_need_fill": [],
        "other_fields_need_fill": [],
        "draft_decision_fields_to_verify": [],
        "draft_text_fields_to_verify": [],
    }
    for field_name, item in sorted(workload.items()):
        if not isinstance(item, Mapping):
            continue
        field = str(field_name)
        field_summary = {
            "field": field,
            "missing_required_rows": int(
                _int_or_none(item.get("missing_required_rows")) or 0
            ),
            "draft_decision_available_rows": int(
                _int_or_none(item.get("draft_decision_available_rows")) or 0
            ),
            "manual_decision_required_rows": int(
                _int_or_none(item.get("manual_decision_required_rows")) or 0
            ),
            "draft_text_available_rows": int(
                _int_or_none(item.get("draft_text_available_rows")) or 0
            ),
        }
        if field_summary["draft_decision_available_rows"] and field in boolean_fields:
            groups["draft_decision_fields_to_verify"].append(dict(field_summary))
        if field_summary["draft_text_available_rows"] and field in text_fields:
            groups["draft_text_fields_to_verify"].append(dict(field_summary))
        if not field_summary["manual_decision_required_rows"]:
            continue
        if field in boolean_fields:
            groups["decision_fields_need_review"].append(dict(field_summary))
        elif field in metadata_fields:
            groups["metadata_fields_need_fill"].append(dict(field_summary))
        elif field in text_fields:
            groups["text_fields_need_fill"].append(dict(field_summary))
        else:
            groups["other_fields_need_fill"].append(dict(field_summary))
    for group_items in groups.values():
        group_items.sort(
            key=lambda item: (
                -int(item["manual_decision_required_rows"]),
                -int(item["draft_decision_available_rows"]),
                -int(item["draft_text_available_rows"]),
                str(item["field"]),
            )
        )
    return groups


def _validate_manual_review_progress_privacy_contract(
    root_path: Path,
) -> tuple[int, list[str]]:
    report, report_failures = _read_mapping_json(
        root_path / "registry/review_batches/manual_review_progress_report.json",
        "registry/review_batches/manual_review_progress_report.json",
    )
    failures = list(report_failures)
    gates = []
    if report:
        failures.extend(
            _manual_progress_forbidden_text_failures(
                report,
                path="manual_review_progress_report",
            )
        )
        gates_payload = report.get("gates")
        if not isinstance(gates_payload, Sequence) or isinstance(gates_payload, str):
            failures.append("manual_review_progress_report.gates: expected array")
        else:
            gates = [gate for gate in gates_payload if isinstance(gate, Mapping)]
            gate_kinds = {str(gate.get("review_kind") or "") for gate in gates}
            expected_gate_kinds = {
                "gold_set",
                "footprint_review",
                "source_license",
                "lockbox",
            }
            missing_gate_kinds = sorted(expected_gate_kinds - gate_kinds)
            if missing_gate_kinds:
                failures.append(
                    "manual_review_progress_report.gates missing review_kind: "
                    + ", ".join(missing_gate_kinds)
                )
            for index, gate in enumerate(gates, 1):
                current_batch_status = gate.get("current_batch_status")
                if current_batch_status and not isinstance(
                    current_batch_status,
                    Mapping,
                ):
                    failures.append(
                        "manual_review_progress_report.gates"
                        f"[{index}].current_batch_status: expected object"
                    )

    return len(gates), failures


def _validate_manual_review_progress_contract(
    root_path: Path,
) -> tuple[int, list[str]]:
    report, report_failures = _read_mapping_json(
        root_path / "registry/review_batches/manual_review_progress_report.json",
        "registry/review_batches/manual_review_progress_report.json",
    )
    failures = list(report_failures)
    gates: list[Mapping[str, Any]] = []
    if not report:
        return 0, failures

    raw_gates = report.get("gates")
    if not isinstance(raw_gates, Sequence) or isinstance(raw_gates, str):
        failures.append("manual_review_progress_report.gates: expected array")
    else:
        gates = [gate for gate in raw_gates if isinstance(gate, Mapping)]
        malformed_count = len(raw_gates) - len(gates)
        if malformed_count:
            failures.append(
                f"manual_review_progress_report.gates: {malformed_count} non-object gates"
            )

    gate_kinds = [str(gate.get("review_kind") or "") for gate in gates]
    duplicate_gate_kinds = sorted(
        kind for kind in set(gate_kinds) if gate_kinds.count(kind) > 1
    )
    if duplicate_gate_kinds:
        failures.append(
            "manual_review_progress_report.gates duplicate review_kind: "
            + ", ".join(duplicate_gate_kinds)
        )
    observed_kinds = set(gate_kinds)
    expected_kinds = set(MANUAL_REVIEW_PROGRESS_EXPECTED_GATES)
    missing_kinds = sorted(expected_kinds - observed_kinds)
    unexpected_kinds = sorted(observed_kinds - expected_kinds)
    if missing_kinds:
        failures.append(
            "manual_review_progress_report.gates missing review_kind: "
            + ", ".join(missing_kinds)
        )
    if unexpected_kinds:
        failures.append(
            "manual_review_progress_report.gates unexpected review_kind: "
            + ", ".join(unexpected_kinds)
        )

    for gate in gates:
        review_kind = str(gate.get("review_kind") or "")
        row_label = f"manual_review_progress_report.gates[{review_kind}]"
        expected = MANUAL_REVIEW_PROGRESS_EXPECTED_GATES.get(review_kind)
        if expected is None:
            continue
        for field in ("input_rows", "target_rows", "complete_rows", "pending_rows"):
            value = _int_or_none(gate.get(field))
            if value is None:
                failures.append(f"{row_label}.{field}: expected integer")
            elif value < 0:
                failures.append(f"{row_label}.{field}: must be non-negative")
        complete_rows = _int_or_none(gate.get("complete_rows"))
        pending_rows = _int_or_none(gate.get("pending_rows"))
        target_rows = _int_or_none(gate.get("target_rows"))
        if (
            complete_rows is not None
            and pending_rows is not None
            and target_rows is not None
            and complete_rows + pending_rows != target_rows
        ):
            failures.append(
                f"{row_label}: complete_rows + pending_rows must equal target_rows"
            )
        for field, expected_value in expected.items():
            if gate.get(field) != expected_value:
                failures.append(f"{row_label}.{field}: expected {expected_value}")
        blockers = _string_items(gate.get("blockers"))
        ready = gate.get("ready_for_promotion")
        simulation_accepted = gate.get("simulation_accepted")
        if not isinstance(ready, bool):
            failures.append(f"{row_label}.ready_for_promotion: must be boolean")
        if not isinstance(simulation_accepted, bool):
            failures.append(f"{row_label}.simulation_accepted: must be boolean")
        if ready is True and blockers:
            failures.append(f"{row_label}.blockers: ready gate must not block")
        if ready is False and not blockers:
            failures.append(f"{row_label}.blockers: blocked gate requires blockers")
        if ready is True:
            if pending_rows not in (0, None):
                failures.append(f"{row_label}.pending_rows: ready gate must be zero")
            if (
                complete_rows is not None
                and target_rows is not None
                and complete_rows != target_rows
            ):
                failures.append(
                    f"{row_label}.complete_rows: ready gate must equal target_rows"
                )
        if simulation_accepted is not ready:
            failures.append(
                f"{row_label}.simulation_accepted: must match ready_for_promotion"
            )
        for command_field in ("prepare_command", "dry_run_command", "apply_command"):
            command = str(gate.get(command_field) or "")
            if not command:
                failures.append(f"{row_label}.{command_field}: must be non-empty")
                continue
            if "mosaic-rke " not in command:
                failures.append(f"{row_label}.{command_field}: must invoke mosaic-rke")
            if not _has_operator_tmp_env_prefix(command):
                failures.append(
                    f"{row_label}.{command_field}: missing MOSAIC_RKE_TMPDIR prefix"
                )
            if not _has_operator_tmp_env_prefix(command):
                failures.append(f"{row_label}.{command_field}: missing TMPDIR prefix")
        dry_run_command = str(gate.get("dry_run_command") or "")
        if "--dry-run" not in dry_run_command:
            failures.append(f"{row_label}.dry_run_command: must include --dry-run")
        if review_kind in {"gold_set", "footprint_review"}:
            expected_gate_input = (
                "registry/review_batches/gold_set_full_reviewed.jsonl"
                if review_kind == "gold_set"
                else "registry/report_intelligence/analytical_footprint_reviewed.jsonl"
            )
            for command_field in ("dry_run_command", "apply_command"):
                command = str(gate.get(command_field) or "")
                if f"--input {expected_gate_input}" not in command:
                    failures.append(
                        f"{row_label}.{command_field}: expected promotion input {expected_gate_input}"
                    )
        batch_status = gate.get("current_batch_status")
        if isinstance(batch_status, Mapping) and batch_status:
            rows = _int_or_none(batch_status.get("rows"))
            complete = _int_or_none(batch_status.get("complete_rows"))
            pending = _int_or_none(batch_status.get("pending_rows"))
            malformed = _int_or_none(batch_status.get("malformed_rows"))
            if None not in (rows, complete, pending, malformed) and (
                int(complete or 0) + int(pending or 0) + int(malformed or 0)
                != int(rows or 0)
            ):
                failures.append(
                    f"{row_label}.current_batch_status: complete + pending + malformed must equal rows"
                )
            evidence_status = batch_status.get("evidence_status")
            if review_kind in {"gold_set", "footprint_review"}:
                if not isinstance(evidence_status, Mapping):
                    failures.append(
                        f"{row_label}.current_batch_status.evidence_status: "
                        "expected object"
                    )
                else:
                    evidence_label = (
                        f"{row_label}.current_batch_status.evidence_status"
                    )
                    expected_evidence_path = (
                        "registry/review_batches/gold_set_review_evidence.jsonl"
                        if review_kind == "gold_set"
                        else "registry/report_intelligence/"
                        "analytical_footprint_review_evidence.jsonl"
                    )
                    expected_review_input_path = (
                        "registry/review_batches/gold_set_reviewed.jsonl"
                        if review_kind == "gold_set"
                        else "registry/report_intelligence/"
                        "analytical_footprint_review_batch.jsonl"
                    )
                    expected_id_field = (
                        "claim_id" if review_kind == "gold_set" else "footprint_id"
                    )
                    if evidence_status.get("path") != expected_evidence_path:
                        failures.append(
                            f"{evidence_label}.path: expected {expected_evidence_path}"
                        )
                    if (
                        evidence_status.get("review_input_path")
                        != expected_review_input_path
                    ):
                        failures.append(
                            f"{evidence_label}.review_input_path: "
                            f"expected {expected_review_input_path}"
                        )
                    if evidence_status.get("id_field") != expected_id_field:
                        failures.append(
                            f"{evidence_label}.id_field: expected {expected_id_field}"
                        )
                    evidence_int_fields = (
                        "rows",
                        "review_input_rows",
                        "covered_review_rows",
                        "missing_review_rows",
                        "extra_evidence_rows",
                        "malformed_rows",
                        "review_input_malformed_rows",
                        "duplicate_review_id_count",
                        "duplicate_evidence_id_count",
                        "target_row_hash_mismatch_count",
                    )
                    evidence_values: dict[str, int] = {}
                    for field in evidence_int_fields:
                        value = _int_or_none(evidence_status.get(field))
                        if value is None:
                            failures.append(f"{evidence_label}.{field}: expected integer")
                            continue
                        if value < 0:
                            failures.append(
                                f"{evidence_label}.{field}: must be non-negative"
                            )
                        evidence_values[field] = value
                    review_input_rows = evidence_values.get("review_input_rows")
                    covered_review_rows = evidence_values.get("covered_review_rows")
                    if (
                        rows is not None
                        and review_input_rows is not None
                        and review_input_rows != int(rows)
                    ):
                        failures.append(
                            f"{evidence_label}.review_input_rows: must match "
                            "current batch rows"
                        )
                    if (
                        review_input_rows is not None
                        and covered_review_rows is not None
                        and covered_review_rows > review_input_rows
                    ):
                        failures.append(
                            f"{evidence_label}.covered_review_rows: cannot exceed "
                            "review_input_rows"
                        )
                    for bool_field in (
                        "exists",
                        "review_input_exists",
                        "same_order",
                        "aligned",
                    ):
                        if not isinstance(evidence_status.get(bool_field), bool):
                            failures.append(
                                f"{evidence_label}.{bool_field}: expected boolean"
                            )
                    if evidence_status.get("aligned") is True:
                        if evidence_status.get("exists") is not True:
                            failures.append(
                                f"{evidence_label}.exists: aligned evidence must exist"
                            )
                        if evidence_status.get("review_input_exists") is not True:
                            failures.append(
                                f"{evidence_label}.review_input_exists: "
                                "aligned review input must exist"
                            )
                        if evidence_status.get("same_order") is not True:
                            failures.append(
                                f"{evidence_label}.same_order: aligned evidence "
                                "must be in review input order"
                            )
                        if (
                            evidence_values.get("rows") is not None
                            and review_input_rows is not None
                            and evidence_values["rows"] != review_input_rows
                        ):
                            failures.append(
                                f"{evidence_label}.rows: aligned evidence rows "
                                "must match review_input_rows"
                            )
                        if (
                            covered_review_rows is not None
                            and review_input_rows is not None
                            and covered_review_rows != review_input_rows
                        ):
                            failures.append(
                                f"{evidence_label}.covered_review_rows: aligned "
                                "evidence must cover every review row"
                            )
                        for gap_field in (
                            "missing_review_rows",
                            "extra_evidence_rows",
                            "malformed_rows",
                            "review_input_malformed_rows",
                            "duplicate_review_id_count",
                            "duplicate_evidence_id_count",
                            "target_row_hash_mismatch_count",
                        ):
                            if evidence_values.get(gap_field) not in (0, None):
                                failures.append(
                                    f"{evidence_label}.{gap_field}: aligned "
                                    "evidence must have zero gaps"
                                )
        raw_batch_plan = gate.get("batch_plan")
        batch_plan: list[Mapping[str, Any]] = []
        if raw_batch_plan is None:
            failures.append(f"{row_label}.batch_plan: expected array")
        elif not isinstance(raw_batch_plan, Sequence) or isinstance(raw_batch_plan, str):
            failures.append(f"{row_label}.batch_plan: expected array")
        else:
            batch_plan = [item for item in raw_batch_plan if isinstance(item, Mapping)]
            malformed_batch_count = len(raw_batch_plan) - len(batch_plan)
            if malformed_batch_count:
                failures.append(
                    f"{row_label}.batch_plan: {malformed_batch_count} non-object batches"
                )
            expected_batch_count = 0
            if review_kind in {"gold_set", "footprint_review"} and pending_rows:
                expected_batch_count = (int(pending_rows) + 49) // 50
            if len(batch_plan) != expected_batch_count:
                failures.append(
                    f"{row_label}.batch_plan: expected {expected_batch_count} batches"
                )
            for batch_index, batch in enumerate(batch_plan, 1):
                batch_label = f"{row_label}.batch_plan[{batch_index}]"
                offset = _int_or_none(batch.get("offset"))
                limit = _int_or_none(batch.get("limit"))
                pending_start = _int_or_none(batch.get("pending_row_start"))
                pending_end = _int_or_none(batch.get("pending_row_end"))
                if batch.get("batch_index") != batch_index:
                    failures.append(f"{batch_label}.batch_index: expected {batch_index}")
                expected_offset = (batch_index - 1) * 50
                if offset != expected_offset:
                    failures.append(f"{batch_label}.offset: expected {expected_offset}")
                if limit is None or limit <= 0 or limit > 50:
                    failures.append(f"{batch_label}.limit: must be 1..50")
                if None not in (offset, limit, pending_start, pending_end):
                    if pending_start != int(offset) + 1:
                        failures.append(
                            f"{batch_label}.pending_row_start: must equal offset + 1"
                        )
                    if pending_end != int(offset) + int(limit):
                        failures.append(
                            f"{batch_label}.pending_row_end: must equal offset + limit"
                        )
                    if pending_rows is not None and int(pending_end) > int(pending_rows):
                        failures.append(
                            f"{batch_label}.pending_row_end: exceeds pending_rows"
                        )
                expected_mode = (
                    "pending_offset_batch_before_applying_any_batch"
                    if review_kind == "gold_set"
                    else "priority_sorted_pending_batch_before_applying_any_batch"
                )
                if batch.get("mode") != expected_mode:
                    failures.append(
                        f"{batch_label}.mode: expected {expected_mode}"
                    )
                if batch.get("apply_effect") != "merge_batch_into_target_review_template":
                    failures.append(
                        f"{batch_label}.apply_effect: expected merge_batch_into_target_review_template"
                    )
                expected_target_template = (
                    "registry/gold_sets/tushare_research_reports.review_template.jsonl"
                    if review_kind == "gold_set"
                    else "registry/report_intelligence/analytical_footprint_review_template.jsonl"
                )
                expected_batch_input = (
                    "registry/review_batches/gold_set_reviewed.jsonl"
                    if review_kind == "gold_set"
                    else "registry/report_intelligence/analytical_footprint_review_batch.jsonl"
                )
                expected_promotion_input = (
                    "registry/review_batches/gold_set_full_reviewed.jsonl"
                    if review_kind == "gold_set"
                    else "registry/report_intelligence/analytical_footprint_reviewed.jsonl"
                )
                if batch.get("target_review_template_path") != expected_target_template:
                    failures.append(
                        f"{batch_label}.target_review_template_path: expected {expected_target_template}"
                    )
                if batch.get("batch_input_path") != expected_batch_input:
                    failures.append(
                        f"{batch_label}.batch_input_path: expected {expected_batch_input}"
                    )
                if batch.get("promotion_input_path") != expected_promotion_input:
                    failures.append(
                        f"{batch_label}.promotion_input_path: expected {expected_promotion_input}"
                    )
                commands = batch.get("commands")
                if not isinstance(commands, Mapping):
                    failures.append(f"{batch_label}.commands: expected object")
                    continue
                required_commands = (
                    ("evidence", "prepare", "dry_run", "apply")
                    if review_kind == "gold_set"
                    else ("assist", "evidence", "prepare", "dry_run", "apply")
                )
                for command_name in required_commands:
                    command = str(commands.get(command_name) or "")
                    if not command:
                        failures.append(
                            f"{batch_label}.commands.{command_name}: must be non-empty"
                        )
                        continue
                    if not _has_operator_tmp_env_prefix(command):
                        failures.append(
                            f"{batch_label}.commands.{command_name}: missing MOSAIC_RKE_TMPDIR prefix"
                        )
                    if not _has_operator_tmp_env_prefix(command):
                        failures.append(
                            f"{batch_label}.commands.{command_name}: missing TMPDIR prefix"
                        )
                    if "mosaic-rke " not in command:
                        failures.append(
                            f"{batch_label}.commands.{command_name}: must invoke mosaic-rke"
                        )
                for command_name in ("dry_run", "apply"):
                    command = str(commands.get(command_name) or "")
                    if f"--input {expected_batch_input}" not in command:
                        failures.append(
                            f"{batch_label}.commands.{command_name}: expected batch input {expected_batch_input}"
                        )
                    if f"--input {expected_promotion_input}" in command:
                        failures.append(
                            f"{batch_label}.commands.{command_name}: must not use promotion input {expected_promotion_input}"
                        )
                batch_dry_run_command = str(commands.get("dry_run") or "")
                if "--dry-run" not in batch_dry_run_command:
                    failures.append(f"{batch_label}.commands.dry_run: must include --dry-run")
                batch_apply_command = str(commands.get("apply") or "")
                if "--dry-run" in batch_apply_command:
                    failures.append(f"{batch_label}.commands.apply: must not include --dry-run")
                evidence_command = str(commands.get("evidence") or "")
                prepare_command_for_batch = str(commands.get("prepare") or "")
                if offset is not None and f"--offset {offset}" not in evidence_command:
                    failures.append(f"{batch_label}.commands.evidence: offset mismatch")
                if offset is not None and f"--offset {offset}" not in prepare_command_for_batch:
                    failures.append(f"{batch_label}.commands.prepare: offset mismatch")
                if limit is not None and f"--limit {limit}" not in evidence_command:
                    failures.append(f"{batch_label}.commands.evidence: limit mismatch")
                if f"--review-input {expected_batch_input}" not in evidence_command:
                    failures.append(
                        f"{batch_label}.commands.evidence: expected review input {expected_batch_input}"
                    )
                if review_kind == "gold_set":
                    if (
                        limit is not None
                        and f"--gold-batch-size {limit}" not in prepare_command_for_batch
                    ):
                        failures.append(
                            f"{batch_label}.commands.prepare: gold batch-size mismatch"
                        )
                elif limit is not None and f"--limit {limit}" not in prepare_command_for_batch:
                    failures.append(f"{batch_label}.commands.prepare: limit mismatch")
                if (
                    review_kind == "footprint_review"
                    and "--priority" not in prepare_command_for_batch
                ):
                    failures.append(
                        f"{batch_label}.commands.prepare: expected --priority"
                    )
        _validate_manual_review_batch_overview_contract(
            gate,
            review_kind=review_kind,
            batch_plan=batch_plan,
            pending_rows=pending_rows,
            ready=ready,
            row_label=row_label,
            failures=failures,
        )

    expected_ready_for_promotion = bool(gates) and all(
        gate.get("ready_for_promotion") is True for gate in gates
    )
    if report.get("ready_for_promotion_dry_run") is not expected_ready_for_promotion:
        failures.append(
            "manual_review_progress_report.ready_for_promotion_dry_run: "
            f"expected {expected_ready_for_promotion}"
        )
    report_blockers = _string_items(report.get("blockers"))
    if expected_ready_for_promotion and report_blockers:
        failures.append("manual_review_progress_report.blockers: ready report must be empty")
    if not expected_ready_for_promotion and not report_blockers:
        failures.append("manual_review_progress_report.blockers: must be non-empty")

    return len(gates), failures


def _validate_operator_readiness_contract(root_path: Path) -> tuple[int, list[str]]:
    report, report_failures = _read_mapping_json(
        root_path / "registry/handoffs/rke_operator_readiness_report.json",
        "registry/handoffs/rke_operator_readiness_report.json",
    )
    failures = list(report_failures)
    checks: list[Mapping[str, Any]] = []
    if not report:
        return 0, failures

    raw_checks = report.get("checks")
    if not isinstance(raw_checks, Sequence) or isinstance(raw_checks, str):
        failures.append("operator_readiness_report.checks: expected array")
    else:
        checks = [check for check in raw_checks if isinstance(check, Mapping)]
        malformed_count = len(raw_checks) - len(checks)
        if malformed_count:
            failures.append(
                f"operator_readiness_report.checks: {malformed_count} non-object checks"
            )

    check_ids = [str(check.get("check_id") or "") for check in checks]
    duplicate_check_ids = sorted(
        check_id for check_id in set(check_ids) if check_ids.count(check_id) > 1
    )
    if duplicate_check_ids:
        failures.append(
            "operator_readiness_report.checks duplicate check_ids: "
            + ", ".join(duplicate_check_ids)
        )
    observed_ids = set(check_ids)
    missing_ids = sorted(OPERATOR_READINESS_EXPECTED_CHECK_IDS - observed_ids)
    unexpected_ids = sorted(observed_ids - OPERATOR_READINESS_EXPECTED_CHECK_IDS)
    if missing_ids:
        failures.append(
            "operator_readiness_report.checks missing check_ids: "
            + ", ".join(missing_ids)
        )
    if unexpected_ids:
        failures.append(
            "operator_readiness_report.checks unexpected check_ids: "
            + ", ".join(unexpected_ids)
        )

    failed_checks = [
        str(check.get("check_id") or f"<check-{index}>")
        for index, check in enumerate(checks, 1)
        if check.get("passed") is not True
    ]
    if failed_checks:
        failures.append(
            "operator_readiness_report failed checks: "
            + ", ".join(sorted(failed_checks))
        )
    if report.get("accepted") is not True:
        failures.append("operator_readiness_report.accepted: must be true")
    check_count = len(checks)
    if report.get("check_count") != check_count:
        failures.append(f"operator_readiness_report.check_count: expected {check_count}")
    passed_count = sum(1 for check in checks if check.get("passed") is True)
    if report.get("passed_count") != passed_count:
        failures.append(
            f"operator_readiness_report.passed_count: expected {passed_count}"
        )
    failure_count = check_count - passed_count
    if report.get("failure_count") != failure_count:
        failures.append(
            f"operator_readiness_report.failure_count: expected {failure_count}"
        )
    if failure_count:
        failures.append("operator_readiness_report.failure_count must be zero")

    return check_count, failures


def _validate_operator_handoff_contract(root_path: Path) -> tuple[int, list[str]]:
    handoff, handoff_failures = _read_mapping_json(
        root_path / "registry/handoffs/rke_operator_handoff.json",
        "registry/handoffs/rke_operator_handoff.json",
    )
    failures = list(handoff_failures)
    progress_report, _ = _read_mapping_json(
        root_path / "registry/review_batches/manual_review_progress_report.json",
        "registry/review_batches/manual_review_progress_report.json",
    )
    progress_batch_overview_by_kind: dict[str, Mapping[str, Any]] = {}
    progress_gates = (
        progress_report.get("gates") if isinstance(progress_report, Mapping) else None
    )
    if isinstance(progress_gates, Sequence) and not isinstance(progress_gates, str):
        for progress_gate in progress_gates:
            if not isinstance(progress_gate, Mapping):
                continue
            overview = progress_gate.get("batch_overview")
            if isinstance(overview, Mapping):
                progress_batch_overview_by_kind[
                    str(progress_gate.get("review_kind") or "")
                ] = overview
    steps: list[Mapping[str, Any]] = []
    if not handoff:
        return 0, failures

    raw_steps = handoff.get("command_sequence")
    if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, str):
        failures.append("operator_handoff.command_sequence: expected array")
    else:
        steps = [step for step in raw_steps if isinstance(step, Mapping)]
        malformed_count = len(raw_steps) - len(steps)
        if malformed_count:
            failures.append(
                f"operator_handoff.command_sequence: {malformed_count} non-object steps"
            )

    step_ids = [str(step.get("step_id") or "") for step in steps]
    if tuple(step_ids) != OPERATOR_HANDOFF_EXPECTED_STEP_IDS:
        failures.append("operator_handoff.command_sequence step_id order mismatch")
    duplicate_step_ids = sorted(
        step_id for step_id in set(step_ids) if step_ids.count(step_id) > 1
    )
    if duplicate_step_ids:
        failures.append(
            "operator_handoff.command_sequence duplicate step_ids: "
            + ", ".join(duplicate_step_ids)
        )

    for index, step in enumerate(steps, 1):
        row_label = f"operator_handoff.command_sequence[{index}]"
        step_id = str(step.get("step_id") or "")
        command = str(step.get("command") or "")
        manual_input_path = str(step.get("manual_input_path") or "")
        for field in ("action", "expected_result", "phase", "step_id"):
            if not str(step.get(field) or "").strip():
                failures.append(f"{row_label}.{field}: must be non-empty")
        if command:
            if "mosaic-rke " not in command:
                failures.append(f"{row_label}.command: must invoke mosaic-rke")
            if not _has_operator_tmp_env_prefix(command):
                failures.append(f"{row_label}.command: missing MOSAIC_RKE_TMPDIR prefix")
            if not _has_operator_tmp_env_prefix(command):
                failures.append(f"{row_label}.command: missing TMPDIR prefix")
        elif not step_id.startswith("fill-"):
            failures.append(f"{row_label}.command: empty only allowed for fill steps")
        if step_id.startswith("fill-") and not manual_input_path:
            failures.append(f"{row_label}.manual_input_path: required for fill step")

    step_by_id = {str(step.get("step_id") or ""): step for step in steps}
    expected_manual_inputs = {
        "fill-gold-review": "registry/review_batches/gold_set_full_reviewed.jsonl",
        "dry-run-gold-review": "registry/review_batches/gold_set_full_reviewed.jsonl",
        "apply-gold-review": "registry/review_batches/gold_set_full_reviewed.jsonl",
        "fill-footprint-review": "registry/report_intelligence/analytical_footprint_reviewed.jsonl",
        "dry-run-footprint-review": "registry/report_intelligence/analytical_footprint_reviewed.jsonl",
        "apply-footprint-review": "registry/report_intelligence/analytical_footprint_reviewed.jsonl",
        "fill-lockbox-review": "registry/review_batches/lockbox_reviewed.json",
        "dry-run-lockbox-review": "registry/review_batches/lockbox_reviewed.json",
        "apply-lockbox-review": "registry/review_batches/lockbox_reviewed.json",
    }
    for step_id, expected_path in expected_manual_inputs.items():
        step = step_by_id.get(step_id)
        if not step:
            continue
        if step.get("manual_input_path") != expected_path:
            failures.append(
                f"operator_handoff.command_sequence[{step_id}].manual_input_path: expected {expected_path}"
            )
        command = str(step.get("command") or "")
        if command and expected_path not in command:
            failures.append(
                f"operator_handoff.command_sequence[{step_id}].command: expected {expected_path}"
            )

    preflight_step = step_by_id.get("review-progress-preflight")
    if preflight_step:
        preflight_command = str(preflight_step.get("command") or "")
        if (
            "review-progress --root . --actions-only --no-write"
            not in preflight_command
        ):
            failures.append(
                "operator_handoff.command_sequence[review-progress-preflight].command: "
                "must use actions-only no-write preflight"
            )

    for step_id in ("promotion-status-before-lockbox", "promotion-status-final"):
        promotion_status_step = step_by_id.get(step_id)
        if promotion_status_step:
            command = str(promotion_status_step.get("command") or "")
            if "promotion-status --root . --no-write" not in command:
                failures.append(
                    f"operator_handoff.command_sequence[{step_id}].command: "
                    "must use promotion-status no-write check"
                )

    promotion_step = step_by_id.get("promotion-dry-run")
    if promotion_step:
        command = str(promotion_step.get("command") or "")
        for expected_path in (
            "registry/review_batches/gold_set_full_reviewed.jsonl",
            "registry/report_intelligence/analytical_footprint_reviewed.jsonl",
            "registry/review_batches/lockbox_reviewed.json",
        ):
            if expected_path not in command:
                failures.append(
                    "operator_handoff.command_sequence[promotion-dry-run].command: "
                    f"expected {expected_path}"
                )
        for forbidden_path in (
            "gold_set_full_import_template.jsonl",
            "analytical_footprint_review_template.jsonl",
            "lockbox_review_next_import_template.json",
        ):
            if forbidden_path in command:
                failures.append(
                    "operator_handoff.command_sequence[promotion-dry-run].command: "
                    f"must not use {forbidden_path}"
                )
        if "--license-input" in command:
            failures.append(
                "operator_handoff.command_sequence[promotion-dry-run].command: "
                "must not pass source-license input while source-license gate is already applied"
            )

    raw_gates = handoff.get("gates")
    handoff_gates = (
        [gate for gate in raw_gates if isinstance(gate, Mapping)]
        if isinstance(raw_gates, Sequence) and not isinstance(raw_gates, str)
        else []
    )
    all_handoff_gates_passed = bool(handoff_gates) and all(
        gate.get("passed") is True for gate in handoff_gates
    )
    if handoff.get("production_allowed") is True:
        if handoff.get("direct_production_forbidden") is not False:
            failures.append(
                "operator_handoff.direct_production_forbidden: must be false when production is allowed"
            )
        if handoff.get("next_state") != "production":
            failures.append(
                "operator_handoff.next_state: expected production when production is allowed"
            )
        if not all_handoff_gates_passed:
            failures.append(
                "operator_handoff.production_allowed: requires all gates passed"
            )
    else:
        if handoff.get("production_allowed") is not False:
            failures.append("operator_handoff.production_allowed: must be false")
        if handoff.get("direct_production_forbidden") is not True:
            failures.append("operator_handoff.direct_production_forbidden: must be true")
    if handoff.get("ready_for_operator_review") is not True:
        failures.append("operator_handoff.ready_for_operator_review: must be true")
    run_order = tuple(str(item) for item in _string_items(handoff.get("run_order")))
    if run_order and run_order != tuple(step_ids):
        failures.append("operator_handoff.run_order mismatch with command_sequence")

    if not isinstance(raw_gates, Sequence) or isinstance(raw_gates, str):
        failures.append("operator_handoff.gates: expected array")
    else:
        gates = handoff_gates
        gate_by_kind = {str(gate.get("review_kind") or ""): gate for gate in gates}
        for review_kind in (
            "gold_set",
            "footprint_review",
            "source_license",
            "lockbox",
        ):
            gate = gate_by_kind.get(review_kind)
            if not gate:
                failures.append(f"operator_handoff.gates[{review_kind}]: missing")
                continue
            review_aids = gate.get("review_aids")
            expected_review_aids = dict(manual_review_aid_paths(review_kind))
            if review_aids != expected_review_aids:
                failures.append(
                    f"operator_handoff.gates[{review_kind}].review_aids: "
                    "must match shared manual review aid paths"
                )
            field_contract = gate.get("field_contract")
            expected_field_contract = dict(manual_review_field_contract(review_kind))
            if field_contract != expected_field_contract:
                failures.append(
                    f"operator_handoff.gates[{review_kind}].field_contract: "
                    "must match shared manual review field contract"
                )
            batch_overview = gate.get("batch_overview")
            if not isinstance(batch_overview, Mapping):
                failures.append(
                    f"operator_handoff.gates[{review_kind}].batch_overview: "
                    "expected object"
                )
                continue
            expected_batch_overview = progress_batch_overview_by_kind.get(review_kind)
            if expected_batch_overview is None:
                failures.append(
                    f"operator_handoff.gates[{review_kind}].batch_overview: "
                    "missing manual_review_progress_report source"
                )
            elif batch_overview != expected_batch_overview:
                failures.append(
                    f"operator_handoff.gates[{review_kind}].batch_overview: "
                    "must match manual_review_progress_report gate batch_overview"
                )

    return len(steps), failures


def _promotion_dry_run_summary_from_report(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    step_rows = [step for step in steps if isinstance(step, Mapping)]
    return {
        "accepted": (
            payload.get("accepted") if isinstance(payload.get("accepted"), bool) else None
        ),
        "after_next_state": str(payload.get("after_next_state") or ""),
        "production_allowed_after_simulation": (
            payload.get("production_allowed_after_simulation")
            if isinstance(payload.get("production_allowed_after_simulation"), bool)
            else None
        ),
        "staged_production_allowed_after_simulation": (
            payload.get("staged_production_allowed_after_simulation")
            if isinstance(payload.get("staged_production_allowed_after_simulation"), bool)
            else None
        ),
        "provided_steps": [
            str(step.get("review_kind") or "")
            for step in step_rows
            if step.get("provided") is True
        ],
        "accepted_steps": [
            str(step.get("review_kind") or "")
            for step in step_rows
            if step.get("accepted") is True
        ],
        "rejected_steps": [
            str(step.get("review_kind") or "")
            for step in step_rows
            if step.get("accepted") is False
        ],
        "already_applied_steps": [
            str(step.get("review_kind") or "")
            for step in step_rows
            if step.get("result") == "already_applied"
        ],
        "missing_steps": [
            str(step.get("review_kind") or "")
            for step in step_rows
            if step.get("result") == "not_provided"
        ],
    }


def _validate_manual_review_bundle_manifest_contract(
    root_path: Path,
) -> tuple[int, list[str]]:
    manifest, manifest_failures = _read_mapping_json(
        root_path / "registry/review_batches/manual_review_bundle_manifest.json",
        "registry/review_batches/manual_review_bundle_manifest.json",
    )
    failures = list(manifest_failures)
    artifacts: list[Mapping[str, Any]] = []
    if not manifest:
        return 0, failures

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, Sequence) or isinstance(raw_artifacts, str):
        failures.append("manual_review_bundle_manifest.artifacts: expected array")
    else:
        artifacts = [item for item in raw_artifacts if isinstance(item, Mapping)]
        malformed_count = len(raw_artifacts) - len(artifacts)
        if malformed_count:
            failures.append(
                f"manual_review_bundle_manifest.artifacts: {malformed_count} non-object artifacts"
            )

    expected_by_role = {
        role: {"path": path, "format": artifact_format}
        for role, path, artifact_format in MANUAL_REVIEW_BUNDLE_ARTIFACTS
    }
    artifacts_by_role = {str(item.get("role") or ""): item for item in artifacts}
    duplicate_roles = sorted(
        role
        for role in artifacts_by_role
        if [str(item.get("role") or "") for item in artifacts].count(role) > 1
    )
    if duplicate_roles:
        failures.append(
            "manual_review_bundle_manifest.artifacts duplicate roles: "
            + ", ".join(duplicate_roles)
        )
    missing_roles = sorted(set(expected_by_role) - set(artifacts_by_role))
    unexpected_roles = sorted(set(artifacts_by_role) - set(expected_by_role))
    if missing_roles:
        failures.append(
            "manual_review_bundle_manifest.artifacts missing roles: "
            + ", ".join(missing_roles)
        )
    if unexpected_roles:
        failures.append(
            "manual_review_bundle_manifest.artifacts unexpected roles: "
            + ", ".join(unexpected_roles)
        )

    for role, expected in expected_by_role.items():
        artifact = artifacts_by_role.get(role)
        if artifact is None:
            continue
        row_label = f"manual_review_bundle_manifest.artifacts[{role}]"
        if artifact.get("path") != expected["path"]:
            failures.append(f"{row_label}.path: expected {expected['path']}")
        if artifact.get("format") != expected["format"]:
            failures.append(f"{row_label}.format: expected {expected['format']}")
        if artifact.get("exists") is not True:
            failures.append(f"{row_label}.exists: must be true")
        reported_bytes = _int_or_none(artifact.get("bytes"))
        if reported_bytes is None or int(artifact.get("bytes") or 0) <= 0:
            failures.append(f"{row_label}.bytes: must be positive")
        sha_value = str(artifact.get("sha256") or "")
        if not SHA256_DIGEST_PATTERN.fullmatch(sha_value):
            failures.append(f"{row_label}.sha256: must be sha256:<64 hex>")
        artifact_path = root_path / expected["path"]
        if not artifact_path.exists():
            failures.append(f"{row_label}.path: referenced artifact missing")
            continue
        actual_bytes = artifact_path.stat().st_size
        if reported_bytes is not None and reported_bytes != actual_bytes:
            failures.append(
                f"{row_label}.bytes: expected current file size {actual_bytes}"
            )
        if SHA256_DIGEST_PATTERN.fullmatch(sha_value):
            actual_sha = _file_sha256(artifact_path)
            if sha_value != actual_sha:
                failures.append(
                    f"{row_label}.sha256: expected current file digest {actual_sha}"
                )

    if manifest.get("accepted") is not True:
        failures.append("manual_review_bundle_manifest.accepted: must be true")
    if manifest.get("artifact_count") != len(MANUAL_REVIEW_BUNDLE_ARTIFACTS):
        failures.append(
            "manual_review_bundle_manifest.artifact_count: expected "
            + str(len(MANUAL_REVIEW_BUNDLE_ARTIFACTS))
        )
    blockers = _string_items(manifest.get("blockers"))
    if blockers:
        failures.append(
            "manual_review_bundle_manifest.blockers: must be empty"
        )

    promotion = (
        manifest.get("promotion_dry_run")
        if isinstance(manifest.get("promotion_dry_run"), Mapping)
        else {}
    )
    if not promotion:
        failures.append("manual_review_bundle_manifest.promotion_dry_run: expected object")
    else:
        after_next_state = str(promotion.get("after_next_state") or "")
        if after_next_state not in PROMOTION_NEXT_STATES:
            failures.append(
                "manual_review_bundle_manifest.promotion_dry_run."
                "after_next_state: unexpected state " + after_next_state
            )
        expected_production = after_next_state == "production"
        expected_staged = after_next_state in {"staged_production", "production"}
        if promotion.get("production_allowed_after_simulation") is not expected_production:
            failures.append(
                "manual_review_bundle_manifest.promotion_dry_run."
                f"production_allowed_after_simulation: expected {expected_production}"
            )
        if promotion.get("staged_production_allowed_after_simulation") is not expected_staged:
            failures.append(
                "manual_review_bundle_manifest.promotion_dry_run."
                f"staged_production_allowed_after_simulation: expected {expected_staged}"
            )
        missing_steps = _string_items(promotion.get("missing_steps"))
        rejected_steps = _string_items(promotion.get("rejected_steps"))
        if promotion.get("accepted") is True and (missing_steps or rejected_steps):
            failures.append(
                "manual_review_bundle_manifest.promotion_dry_run: accepted summary "
                "must not have missing or rejected steps"
            )
        if expected_production and (missing_steps or rejected_steps):
            failures.append(
                "manual_review_bundle_manifest.promotion_dry_run: promoted summary "
                "must not have missing or rejected steps"
            )
        if promotion.get("accepted") is False and not (missing_steps or rejected_steps):
            failures.append(
                "manual_review_bundle_manifest.promotion_dry_run: rejected summary "
                "requires missing or rejected steps"
            )
        dry_run_payload, dry_run_errors = _read_mapping_json(
            root_path / "registry/promotion/rke_promotion_dry_run_report.json",
            "registry/promotion/rke_promotion_dry_run_report.json",
        )
        failures.extend(dry_run_errors)
        if dry_run_payload:
            expected_summary = _promotion_dry_run_summary_from_report(dry_run_payload)
            if dict(promotion) != expected_summary:
                failures.append(
                    "manual_review_bundle_manifest.promotion_dry_run: "
                    "must match current promotion dry-run report"
                )

    return len(artifacts), failures


def _validate_promotion_dry_run_contract(
    root_path: Path,
) -> tuple[int, list[str]]:
    report, report_failures = _read_mapping_json(
        root_path / "registry/promotion/rke_promotion_dry_run_report.json",
        "registry/promotion/rke_promotion_dry_run_report.json",
    )
    failures = list(report_failures)
    steps: list[Mapping[str, Any]] = []
    if not report:
        return 0, failures

    raw_steps = report.get("steps")
    if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, str):
        failures.append("promotion_dry_run_report.steps: expected array")
    else:
        steps = [step for step in raw_steps if isinstance(step, Mapping)]
        malformed_count = len(raw_steps) - len(steps)
        if malformed_count:
            failures.append(
                f"promotion_dry_run_report.steps: {malformed_count} non-object steps"
            )

    review_kinds = [str(step.get("review_kind") or "") for step in steps]
    duplicate_review_kinds = sorted(
        kind for kind in set(review_kinds) if review_kinds.count(kind) > 1
    )
    if duplicate_review_kinds:
        failures.append(
            "promotion_dry_run_report.steps duplicate review_kind: "
            + ", ".join(duplicate_review_kinds)
        )
    observed_kinds = set(review_kinds)
    missing_kinds = sorted(PROMOTION_DRY_RUN_EXPECTED_REVIEW_KINDS - observed_kinds)
    unexpected_kinds = sorted(observed_kinds - PROMOTION_DRY_RUN_EXPECTED_REVIEW_KINDS)
    if missing_kinds:
        failures.append(
            "promotion_dry_run_report.steps missing review_kind: "
            + ", ".join(missing_kinds)
        )
    if unexpected_kinds:
        failures.append(
            "promotion_dry_run_report.steps unexpected review_kind: "
            + ", ".join(unexpected_kinds)
        )

    for index, step in enumerate(steps, 1):
        row_label = f"promotion_dry_run_report.steps[{index}]"
        accepted = step.get("accepted")
        applied = step.get("applied")
        provided = step.get("provided")
        blockers = _string_items(step.get("blockers"))
        result = str(step.get("result") or "").strip()
        if not isinstance(accepted, bool):
            failures.append(f"{row_label}.accepted: must be boolean")
        elif accepted and blockers:
            failures.append(f"{row_label}.blockers: accepted step must not block")
        elif not accepted and not blockers:
            failures.append(f"{row_label}.blockers: rejected step requires blocker")
        if not isinstance(applied, bool):
            failures.append(f"{row_label}.applied: must be boolean")
        elif applied and accepted is not True:
            failures.append(f"{row_label}.applied: requires accepted step")
        if not isinstance(provided, bool):
            failures.append(f"{row_label}.provided: must be boolean")
        elif provided is False and str(step.get("input_path") or "").strip():
            failures.append(f"{row_label}.input_path: must be empty when not provided")
        if not result:
            failures.append(f"{row_label}.result: must be non-empty")
        if result == "already_applied":
            if accepted is not True:
                failures.append(f"{row_label}.accepted: already_applied must be true")
            if applied is not False:
                failures.append(f"{row_label}.applied: already_applied must be false")
            if _int_or_none(step.get("changed_rows")) != 0:
                failures.append(f"{row_label}.changed_rows: already_applied expected 0")
        if result == "not_provided" and provided is not False:
            failures.append(f"{row_label}.provided: not_provided must be false")

    accepted_steps = sum(1 for step in steps if step.get("accepted") is True)
    if report.get("accepted") is not (accepted_steps == len(steps) and bool(steps)):
        failures.append("promotion_dry_run_report.accepted mismatch with steps")
    if report.get("simulated") is not True:
        failures.append("promotion_dry_run_report.simulated: must be true")
    if report.get("mutated_original_registry") is not False:
        failures.append(
            "promotion_dry_run_report.mutated_original_registry: must be false"
        )
    before_next_state = str(report.get("before_next_state") or "")
    after_next_state = str(report.get("after_next_state") or "")
    production_after = report.get("production_allowed_after_simulation")
    staged_after = report.get("staged_production_allowed_after_simulation")
    if before_next_state not in PROMOTION_NEXT_STATES:
        failures.append(
            "promotion_dry_run_report.before_next_state: unexpected state "
            + before_next_state
        )
    if after_next_state not in PROMOTION_NEXT_STATES:
        failures.append(
            "promotion_dry_run_report.after_next_state: unexpected state "
            + after_next_state
        )
    expected_production_after = after_next_state == "production"
    expected_staged_after = after_next_state in {"staged_production", "production"}
    if production_after is not expected_production_after:
        failures.append(
            "promotion_dry_run_report.production_allowed_after_simulation: "
            f"expected {expected_production_after}"
        )
    if staged_after is not expected_staged_after:
        failures.append(
            "promotion_dry_run_report.staged_production_allowed_after_simulation: "
            f"expected {expected_staged_after}"
        )
    before_blockers = _string_items(report.get("before_blockers"))
    after_blockers = _string_items(report.get("after_blockers"))
    if before_next_state == "production" and before_blockers:
        failures.append(
            "promotion_dry_run_report.before_blockers: production state must be empty"
        )
    if after_next_state == "production" and after_blockers:
        failures.append(
            "promotion_dry_run_report.after_blockers: production state must be empty"
        )
    if after_next_state != "production" and report.get("accepted") is True and after_blockers:
        failures.append(
            "promotion_dry_run_report.after_blockers: accepted dry-run must not block"
        )
    if report.get("accepted") is False and not after_blockers:
        failures.append("promotion_dry_run_report.after_blockers: rejected dry-run must block")

    return len(steps), failures


def _validate_production_promotion_gate_contract(
    root_path: Path,
) -> tuple[int, list[str]]:
    gate, gate_failures = _read_mapping_json(
        root_path / "registry/promotion/rke_production_promotion_gate.json",
        "registry/promotion/rke_production_promotion_gate.json",
    )
    failures = list(gate_failures)
    criteria: list[Mapping[str, Any]] = []
    if not gate:
        return 0, failures

    raw_criteria = gate.get("criteria")
    if not isinstance(raw_criteria, Sequence) or isinstance(raw_criteria, str):
        failures.append("production_promotion_gate.criteria: expected array")
    else:
        criteria = [item for item in raw_criteria if isinstance(item, Mapping)]
        malformed_count = len(raw_criteria) - len(criteria)
        if malformed_count:
            failures.append(
                f"production_promotion_gate.criteria: {malformed_count} non-object criteria"
            )

    criterion_ids = [str(item.get("criterion_id") or "") for item in criteria]
    duplicate_ids = sorted(
        criterion_id
        for criterion_id in set(criterion_ids)
        if criterion_ids.count(criterion_id) > 1
    )
    if duplicate_ids:
        failures.append(
            "production_promotion_gate.criteria duplicate criterion_ids: "
            + ", ".join(duplicate_ids)
        )
    observed_ids = set(criterion_ids)
    missing_ids = sorted(PROMOTION_GATE_EXPECTED_CRITERION_IDS - observed_ids)
    unexpected_ids = sorted(observed_ids - PROMOTION_GATE_EXPECTED_CRITERION_IDS)
    if missing_ids:
        failures.append(
            "production_promotion_gate.criteria missing criterion_ids: "
            + ", ".join(missing_ids)
        )
    if unexpected_ids:
        failures.append(
            "production_promotion_gate.criteria unexpected criterion_ids: "
            + ", ".join(unexpected_ids)
        )

    criterion_blockers = [
        str(item.get("blocker") or "").strip()
        for item in criteria
        if str(item.get("blocker") or "").strip()
    ]
    for index, item in enumerate(criteria, 1):
        row_label = f"production_promotion_gate.criteria[{index}]"
        criterion_id = str(item.get("criterion_id") or "").strip()
        passed = item.get("passed")
        blocker = str(item.get("blocker") or "").strip()
        if not criterion_id:
            failures.append(f"{row_label}.criterion_id: must be non-empty")
        for string_key in ("description", "evidence", "evidence_path"):
            if not str(item.get(string_key) or "").strip():
                failures.append(f"{row_label}.{string_key}: must be non-empty")
        if not isinstance(passed, bool):
            failures.append(f"{row_label}.passed: must be boolean")
        elif passed and blocker:
            failures.append(f"{row_label}.blocker: passed criterion must not block")
        elif not passed and not blocker:
            failures.append(f"{row_label}.blocker: failed criterion requires blocker")

    blockers = _string_items(gate.get("blockers"))
    if set(blockers) != set(criterion_blockers):
        failures.append("production_promotion_gate.blockers mismatch with criteria")
    paper_allowed = gate.get("paper_trading_allowed") is True
    staged_allowed = gate.get("staged_production_allowed") is True
    production_allowed = gate.get("production_allowed") is True
    expected_next_state = (
        "production"
        if production_allowed
        else "staged_production"
        if staged_allowed
        else "paper_trading"
        if paper_allowed
        else "candidate"
    )
    if gate.get("next_state") != expected_next_state:
        failures.append(
            "production_promotion_gate.next_state: expected " + expected_next_state
        )
    if gate.get("direct_production_forbidden") is not (not production_allowed):
        failures.append(
            "production_promotion_gate.direct_production_forbidden mismatch"
        )
    if not paper_allowed:
        failures.append(
            "production_promotion_gate.paper_trading_allowed: must be true"
        )
    if staged_allowed and not all(
        item.get("passed") is True
        for item in criteria
        if str(item.get("criterion_id") or "") in {f"PG{idx:02d}" for idx in range(1, 9)}
    ):
        failures.append(
            "production_promotion_gate.staged_production_allowed: requires PG01-PG08"
        )
    if production_allowed and not all(item.get("passed") is True for item in criteria):
        failures.append(
            "production_promotion_gate.production_allowed: requires all criteria passed"
        )
    if production_allowed and blockers:
        failures.append(
            "production_promotion_gate.blockers: production state must be empty"
        )

    return len(criteria), failures


REPORT_INTELLIGENCE_PUBLIC_AGGREGATE_FORBIDDEN_KEYS = frozenset(
    {
        "abstract",
        "claim_id",
        "claim_text",
        "forecast_claim_id",
        "known_failure_modes",
        "manual_claim_text",
        "original_markdown",
        "pdf_path",
        "pdf_url",
        "report_id",
        "retrieval_locator",
        "source_span_id",
        "source_span_ids",
        "source_span_text",
        "source_text",
        "source_text_hash",
        "span_preview",
        "title",
        "url",
    }
)


def _public_aggregate_forbidden_key_path(value: Any, path: str = "$") -> str:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            item_path = f"{path}.{key}"
            if normalized_key in REPORT_INTELLIGENCE_PUBLIC_AGGREGATE_FORBIDDEN_KEYS:
                return item_path
            nested = _public_aggregate_forbidden_key_path(item, item_path)
            if nested:
                return nested
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for index, item in enumerate(value):
            nested = _public_aggregate_forbidden_key_path(item, f"{path}[{index}]")
            if nested:
                return nested
    return ""


def _validate_macro_public_research_artifact_contract(
    root_path: Path,
) -> tuple[int, list[str]]:
    snapshot_rows, snapshot_failures, _snapshot_present = _load_optional_mapping_jsonl(
        root_path,
        "registry/report_intelligence/macro_regime_snapshots.jsonl",
    )
    prior_rows, prior_failures, _prior_present = _load_optional_mapping_jsonl(
        root_path,
        "registry/report_intelligence/macro_agent_research_priors.jsonl",
    )
    catalog_rows, catalog_failures, _catalog_present = _load_optional_mapping_jsonl(
        root_path,
        "registry/report_intelligence/macro_market_series_catalog.jsonl",
    )
    failures = [*snapshot_failures, *prior_failures, *catalog_failures]
    for index, row in enumerate(snapshot_rows, 1):
        row_label = f"macro_regime_snapshots row {index}"
        forbidden_path = _public_aggregate_forbidden_key_path(row)
        if forbidden_path:
            failures.append(
                f"{row_label}: forbidden private/source field {forbidden_path}"
            )
        if row.get("private_text_included") is not False:
            failures.append(f"{row_label}.private_text_included: must be false")
        if row.get("background_only") is not True:
            failures.append(f"{row_label}.background_only: must be true")
        if row.get("claim_validation_allowed") is not False:
            failures.append(f"{row_label}.claim_validation_allowed: must be false")
        if str(row.get("use_policy") or "") != "background_only_not_claim_validation":
            failures.append(
                f"{row_label}.use_policy: must be background_only_not_claim_validation"
            )
        if not str(row.get("agent_id") or "").startswith("macro."):
            failures.append(f"{row_label}.agent_id: must be a macro agent id")
    for index, row in enumerate(prior_rows, 1):
        row_label = f"macro_agent_research_priors row {index}"
        forbidden_path = _public_aggregate_forbidden_key_path(row)
        if forbidden_path:
            failures.append(
                f"{row_label}: forbidden private/source field {forbidden_path}"
            )
        if row.get("private_text_included") is not False:
            failures.append(f"{row_label}.private_text_included: must be false")
        if row.get("research_only") is not True:
            failures.append(f"{row_label}.research_only: must be true")
        if row.get("current_data_required") is not True:
            failures.append(f"{row_label}.current_data_required: must be true")
        if row.get("production_signal_allowed") is not False:
            failures.append(f"{row_label}.production_signal_allowed: must be false")
        if (
            str(row.get("use_policy") or "")
            != "shadow_research_prior_only_not_current_signal"
        ):
            failures.append(
                f"{row_label}.use_policy: must be "
                "shadow_research_prior_only_not_current_signal"
            )
        if str(row.get("rating_source") or "") != "non_llm_viewpoint_performance_profile":
            failures.append(
                f"{row_label}.rating_source: must be "
                "non_llm_viewpoint_performance_profile"
            )
        if not str(row.get("agent_id") or "").startswith("macro."):
            failures.append(f"{row_label}.agent_id: must be a macro agent id")
    raw_catalog_keys = frozenset({"value", "close", "observations", "raw_observations"})
    for index, row in enumerate(catalog_rows, 1):
        row_label = f"macro_market_series_catalog row {index}"
        forbidden_path = _public_aggregate_forbidden_key_path(row)
        if forbidden_path:
            failures.append(
                f"{row_label}: forbidden private/source field {forbidden_path}"
            )
        if row.get("private_text_included") is not False:
            failures.append(f"{row_label}.private_text_included: must be false")
        if row.get("raw_observations_included") is not False:
            failures.append(f"{row_label}.raw_observations_included: must be false")
        raw_key = next((key for key in raw_catalog_keys if key in row), "")
        if raw_key:
            failures.append(f"{row_label}.{raw_key}: raw observations are not public")
        if not str(row.get("series_id") or "").strip():
            failures.append(f"{row_label}.series_id: required")
        target_agents = row.get("target_agent_candidates")
        if (
            not isinstance(target_agents, Sequence)
            or isinstance(target_agents, str)
            or not target_agents
        ):
            failures.append(f"{row_label}.target_agent_candidates: required")
    return len(snapshot_rows) + len(prior_rows) + len(catalog_rows), failures


def validate_report_intelligence_semantics(
    root: str | Path,
) -> tuple[SchemaValidationRecord, ...]:
    root_path = Path(root)
    report_intelligence_dir = root_path / "registry/report_intelligence"
    if not report_intelligence_dir.exists() or not any(
        path.is_file() for path in report_intelligence_dir.iterdir()
    ):
        return ()
    records: list[SchemaValidationRecord] = []

    (
        forecast_rows,
        forecast_failures,
        forecast_rows_present,
    ) = _load_optional_mapping_jsonl(
        root_path,
        "registry/report_intelligence/forecast_claims.jsonl",
    )
    (
        footprint_rows,
        footprint_failures,
        _footprint_rows_present,
    ) = _load_optional_mapping_jsonl(
        root_path,
        "registry/report_intelligence/analytical_footprints.jsonl",
    )
    provenance_failures = [*forecast_failures, *footprint_failures]
    for index, row in enumerate(forecast_rows, 1):
        row_label = f"forecast_claims row {index}"
        has_spans = _has_nonempty_source_spans(row)
        if (
            str(row.get("claim_provenance") or "") == "source_grounded"
            and not has_spans
        ):
            provenance_failures.append(
                f"{row_label}: source_grounded claim must cite source_span_ids"
            )
        for mode_index, mode in enumerate(row.get("failure_modes") or (), 1):
            if not isinstance(mode, Mapping):
                provenance_failures.append(
                    f"{row_label}.failure_modes[{mode_index}]: expected object with provenance"
                )
                continue
            if not str(mode.get("text") or "").strip():
                provenance_failures.append(
                    f"{row_label}.failure_modes[{mode_index}].text: required"
                )
            if not str(mode.get("provenance") or "").strip():
                provenance_failures.append(
                    f"{row_label}.failure_modes[{mode_index}].provenance: required"
                )
            if mode.get("provenance") == "source_grounded" and not has_spans:
                provenance_failures.append(
                    f"{row_label}.failure_modes[{mode_index}]: source_grounded requires claim spans"
                )
        if (
            _has_mapping_gap(row)
            and str(row.get("forecast_testability") or "") == "testable"
        ):
            provenance_failures.append(
                f"{row_label}: forecast with target/benchmark/direction/horizon gap cannot be testable"
            )
    for index, row in enumerate(footprint_rows, 1):
        row_label = f"analytical_footprints row {index}"
        extraction_type = str(row.get("extraction_type") or "")
        has_spans = _has_nonempty_source_spans(row)
        if extraction_type in {"source_grounded", "mixed"} and not has_spans:
            provenance_failures.append(
                f"{row_label}: source-grounded analytical footprint must cite source_span_ids"
            )
        for mention_index, mention in enumerate(
            row.get("indicator_mentions") or (),
            1,
        ):
            if not isinstance(mention, Mapping):
                provenance_failures.append(
                    f"{row_label}.indicator_mentions[{mention_index}]: expected object"
                )
                continue
            if mention.get("source_grounded") is True and not has_spans:
                provenance_failures.append(
                    f"{row_label}.indicator_mentions[{mention_index}]: source_grounded requires footprint spans"
                )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_provenance_rules",
            artifact_path="registry/report_intelligence",
            item_count=len(forecast_rows) + len(footprint_rows),
            accepted=not provenance_failures,
            failures=tuple(provenance_failures),
        )
    )

    (
        outcome_label_rows,
        outcome_label_failures,
        _outcome_label_rows_present,
    ) = _load_optional_mapping_jsonl(
        root_path,
        "registry/report_intelligence/report_outcome_labels.jsonl",
    )
    for index, row in enumerate(outcome_label_rows, 1):
        outcome_label_failures.extend(
            _validate_proxy_outcome_label_contract(
                row,
                f"report_outcome_labels row {index}",
            )
        )
    outcome_label_failures.extend(
        _validate_proxy_outcome_label_id_namespaces(outcome_label_rows)
    )
    outcome_label_failures.extend(
        _validate_proxy_outcome_label_effective_n_sets(outcome_label_rows)
    )
    outcome_label_failures.extend(
        _validate_proxy_outcome_label_forecast_traceability(
            outcome_label_rows,
            forecast_rows,
            forecast_rows_present=forecast_rows_present,
        )
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_proxy_outcome_label_contract_rules",
            artifact_path="registry/report_intelligence/report_outcome_labels.jsonl",
            item_count=len(outcome_label_rows),
            accepted=not outcome_label_failures,
            failures=tuple(outcome_label_failures),
        )
    )
    (
        macro_public_research_item_count,
        macro_public_research_failures,
    ) = _validate_macro_public_research_artifact_contract(root_path)
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_macro_public_research_rules",
            artifact_path="registry/report_intelligence",
            item_count=macro_public_research_item_count,
            accepted=not macro_public_research_failures,
            failures=tuple(macro_public_research_failures),
        )
    )

    (
        industry_etf_mapping_contract_item_count,
        industry_etf_mapping_contract_failures,
    ) = _validate_industry_etf_mapping_contract(root_path, outcome_label_rows)
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_industry_etf_mapping_contract_rules",
            artifact_path="registry/report_intelligence",
            item_count=industry_etf_mapping_contract_item_count,
            accepted=not industry_etf_mapping_contract_failures,
            failures=tuple(industry_etf_mapping_contract_failures),
        )
    )

    (
        stock_price_proxy_readiness_item_count,
        stock_price_proxy_readiness_failures,
    ) = _validate_stock_price_proxy_readiness_contract(root_path, outcome_label_rows)
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_stock_price_proxy_readiness_rules",
            artifact_path="registry/report_intelligence/outcome_labeling_readiness.json",
            item_count=stock_price_proxy_readiness_item_count,
            accepted=not stock_price_proxy_readiness_failures,
            failures=tuple(stock_price_proxy_readiness_failures),
        )
    )

    (
        macro_asset_proxy_readiness_item_count,
        macro_asset_proxy_readiness_failures,
    ) = _validate_macro_asset_proxy_readiness_contract(root_path, outcome_label_rows)
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_macro_asset_proxy_readiness_rules",
            artifact_path="registry/report_intelligence/outcome_labeling_readiness.json",
            item_count=macro_asset_proxy_readiness_item_count,
            accepted=not macro_asset_proxy_readiness_failures,
            failures=tuple(macro_asset_proxy_readiness_failures),
        )
    )

    (
        macro_series_directional_readiness_item_count,
        macro_series_directional_readiness_failures,
    ) = _validate_macro_series_directional_readiness_contract(
        root_path,
        outcome_label_rows,
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_macro_series_directional_readiness_rules",
            artifact_path="registry/report_intelligence/outcome_labeling_readiness.json",
            item_count=macro_series_directional_readiness_item_count,
            accepted=not macro_series_directional_readiness_failures,
            failures=tuple(macro_series_directional_readiness_failures),
        )
    )

    (
        macro_curve_directional_readiness_item_count,
        macro_curve_directional_readiness_failures,
    ) = _validate_macro_curve_directional_readiness_contract(
        root_path,
        outcome_label_rows,
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_macro_curve_directional_readiness_rules",
            artifact_path="registry/report_intelligence/outcome_labeling_readiness.json",
            item_count=macro_curve_directional_readiness_item_count,
            accepted=not macro_curve_directional_readiness_failures,
            failures=tuple(macro_curve_directional_readiness_failures),
        )
    )

    extraction_report_item_count, extraction_report_failures = (
        _validate_extraction_report_contract(root_path)
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_extraction_report_contract_rules",
            artifact_path="registry/report_intelligence/extraction_report.json",
            item_count=extraction_report_item_count,
            accepted=not extraction_report_failures,
            failures=tuple(extraction_report_failures),
        )
    )

    public_id_queue_item_count, public_id_queue_failures = (
        _validate_public_summary_id_queue_privacy(root_path)
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_public_id_queue_privacy_rules",
            artifact_path="registry/report_intelligence/*.json",
            item_count=public_id_queue_item_count,
            accepted=not public_id_queue_failures,
            failures=tuple(public_id_queue_failures),
        )
    )

    profile_layer_item_count, profile_layer_failures = (
        _validate_profile_outcome_layer_support(root_path)
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_profile_outcome_layer_rules",
            artifact_path="registry/report_intelligence/*_performance_profiles.jsonl",
            item_count=profile_layer_item_count,
            accepted=not profile_layer_failures,
            failures=tuple(profile_layer_failures),
        )
    )

    markdown_coverage_failures: list[str] = []
    markdown_coverage, markdown_coverage_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/markdown_coverage_summary.json",
        "registry/report_intelligence/markdown_coverage_summary.json",
    )
    markdown_coverage_failures.extend(markdown_coverage_errors)
    if markdown_coverage:
        markdown_coverage_failures.extend(
            _public_forbidden_text_failures(
                markdown_coverage,
                path="markdown_coverage_summary",
            )
        )
        if markdown_coverage.get("private_text_included") is not False:
            markdown_coverage_failures.append(
                "markdown_coverage_summary.private_text_included: must be false"
            )
        false_positive_counts = _count_mapping(
            markdown_coverage.get("markdown_false_positive_risk_gap_counts"),
            row_label="markdown_coverage_summary.markdown_false_positive_risk_gap_counts",
            failures=markdown_coverage_failures,
        )
        expected_false_positive_queue = sum(false_positive_counts.values())
        if (
            markdown_coverage.get("markdown_false_positive_review_queue_count")
            != expected_false_positive_queue
        ):
            markdown_coverage_failures.append(
                "markdown_coverage_summary.markdown_false_positive_review_queue_count mismatch"
            )
        quality_review_queue_count = _int_or_none(
            markdown_coverage.get("markdown_quality_review_queue_count")
        )
        if quality_review_queue_count is None:
            markdown_coverage_failures.append(
                "markdown_coverage_summary.markdown_quality_review_queue_count: expected integer"
            )
        else:
            if quality_review_queue_count < expected_false_positive_queue:
                markdown_coverage_failures.append(
                    "markdown_coverage_summary.markdown_quality_review_queue_count "
                    "must cover false-positive risk queue"
                )
            expected_spot_check = quality_review_queue_count > 0
            if (
                markdown_coverage.get("markdown_quality_spot_check_required")
                is not expected_spot_check
            ):
                markdown_coverage_failures.append(
                    "markdown_coverage_summary.markdown_quality_spot_check_required mismatch"
                )
        if (
            int(markdown_coverage.get("llm_extraction_without_quality_pass_count") or 0)
            > 0
            and "llm_extraction_without_quality_pass"
            not in _string_items(markdown_coverage.get("coverage_gate_blockers"))
        ):
            markdown_coverage_failures.append(
                "markdown_coverage_summary.coverage_gate_blockers must include "
                "llm_extraction_without_quality_pass"
            )
        coverage_targets = markdown_coverage.get("coverage_targets")
        coverage_blockers = set(
            _string_items(markdown_coverage.get("coverage_gate_blockers"))
        )
        coverage_shortfalls = markdown_coverage.get("coverage_shortfalls")
        if not isinstance(coverage_shortfalls, Mapping):
            markdown_coverage_failures.append(
                "markdown_coverage_summary.coverage_shortfalls: expected object"
            )
            coverage_shortfalls = {}

        def require_coverage_shortfall(
            key: str,
            *,
            current: int,
            target: int,
            blocker: str,
            next_action: str,
        ) -> None:
            row = coverage_shortfalls.get(key)
            row_label = f"markdown_coverage_summary.coverage_shortfalls.{key}"
            if not isinstance(row, Mapping):
                markdown_coverage_failures.append(f"{row_label}: expected object")
                return
            for field, expected in (
                ("current", current),
                ("target", target),
                ("remaining", max(target - current, 0)),
                ("blocker", blocker),
                ("next_action", next_action),
            ):
                if row.get(field) != expected:
                    markdown_coverage_failures.append(
                        f"{row_label}.{field}: expected {expected}"
                    )

        if not isinstance(coverage_targets, Mapping):
            markdown_coverage_failures.append(
                "markdown_coverage_summary.coverage_targets: expected object"
            )
        else:
            for count_field, target_field, blocker, next_action in (
                (
                    "selected_report_count",
                    "selected_report_count_min",
                    "selected_report_count_below_p9_target",
                    "add_stratified_real_reports_to_private_source_pool",
                ),
                (
                    "markdown_ready_count",
                    "markdown_ready_count_min",
                    "markdown_ready_count_below_p9_target",
                    "download_pdfs_and_convert_quality_gated_markdown",
                ),
                (
                    "markdown_quality_pass_count",
                    "markdown_quality_pass_count_min",
                    "markdown_quality_pass_count_below_p9_target",
                    "resolve_markdown_quality_gaps_before_llm_extraction",
                ),
                (
                    "llm_extraction_processed_count",
                    "llm_extraction_processed_count_min",
                    "llm_extraction_processed_count_below_p9_target",
                    "run_llm_extraction_on_quality_passed_markdown",
                ),
                (
                    "industry_report_count",
                    "industry_report_count_min",
                    "industry_report_count_below_p9_target",
                    "add_more_industry_research_reports_to_stratified_pool",
                ),
                (
                    "stock_report_count",
                    "stock_report_count_min",
                    "stock_report_count_below_p9_target",
                    "add_more_stock_research_reports_with_ts_code",
                ),
                (
                    "stock_outcome_120d_ready_report_count",
                    "stock_outcome_120d_ready_report_count_min",
                    "stock_outcome_120d_ready_count_below_p9_target",
                    "prefer_historical_stock_reports_with_120d_outcome_windows",
                ),
            ):
                count = _int_or_none(markdown_coverage.get(count_field))
                target = _int_or_none(coverage_targets.get(target_field))
                if count is None:
                    markdown_coverage_failures.append(
                        f"markdown_coverage_summary.{count_field}: expected integer"
                    )
                    continue
                if target is None:
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.coverage_targets."
                        f"{target_field}: expected integer"
                    )
                    continue
                require_coverage_shortfall(
                    count_field,
                    current=count,
                    target=target,
                    blocker=blocker,
                    next_action=next_action,
                )
                if count < target and blocker not in coverage_blockers:
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.coverage_gate_blockers must "
                        f"include {blocker}"
                    )
                if count >= target and blocker in coverage_blockers:
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.coverage_gate_blockers includes "
                        f"stale {blocker}"
                    )
            sector_bucket_counts = _count_mapping(
                markdown_coverage.get("sector_bucket_counts"),
                row_label="markdown_coverage_summary.sector_bucket_counts",
                failures=markdown_coverage_failures,
            )
            sector_bucket_min = _int_or_none(
                coverage_targets.get("sector_bucket_min_report_count")
            )
            if sector_bucket_min is None:
                markdown_coverage_failures.append(
                    "markdown_coverage_summary.coverage_targets."
                    "sector_bucket_min_report_count: expected integer"
                )
            else:
                expected_sector_gaps = {
                    f"sector_bucket:{bucket}"
                    for bucket, count in sector_bucket_counts.items()
                    if int(count or 0) < sector_bucket_min
                }
                actual_sector_gaps = set(
                    _string_items(markdown_coverage.get("sector_bucket_coverage_gaps"))
                )
                missing_sector_gaps = expected_sector_gaps - actual_sector_gaps
                if missing_sector_gaps:
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.sector_bucket_coverage_gaps "
                        "must include " + ", ".join(sorted(missing_sector_gaps))
                    )
                if (
                    expected_sector_gaps
                    and "sector_bucket_coverage_below_p9_target"
                    not in coverage_blockers
                ):
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.coverage_gate_blockers must "
                        "include sector_bucket_coverage_below_p9_target"
                    )
                if (
                    not expected_sector_gaps
                    and "sector_bucket_coverage_below_p9_target" in coverage_blockers
                ):
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.coverage_gate_blockers includes "
                        "stale sector_bucket_coverage_below_p9_target"
                    )
                sector_gap_count = _int_or_none(
                    markdown_coverage.get("sector_bucket_below_min_count")
                )
                if sector_gap_count != len(expected_sector_gaps):
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.sector_bucket_below_min_count mismatch"
                    )
                if sector_gap_count is not None:
                    require_coverage_shortfall(
                        "sector_bucket_below_min_count",
                        current=sector_gap_count,
                        target=0,
                        blocker="sector_bucket_coverage_below_p9_target",
                        next_action="fill_aggregate_sector_bucket_coverage_gaps",
                    )
        coverage_strata_targets = markdown_coverage.get("coverage_strata_targets")
        coverage_strata_missing = set(
            _string_items(markdown_coverage.get("coverage_strata_missing"))
        )
        if not isinstance(coverage_strata_targets, Mapping):
            markdown_coverage_failures.append(
                "markdown_coverage_summary.coverage_strata_targets: expected object"
            )
        else:
            strata_checks = (
                (
                    "time_bucket_counts",
                    "time_bucket_required",
                    "time_bucket",
                    "time_bucket_coverage_below_p9_target",
                ),
                (
                    "institution_bucket_counts",
                    "institution_bucket_required",
                    "institution_bucket",
                    "institution_bucket_coverage_below_p9_target",
                ),
                (
                    "report_horizon_bucket_counts",
                    "horizon_bucket_required",
                    "horizon_bucket",
                    "horizon_bucket_coverage_below_p9_target",
                ),
                (
                    "evaluability_bucket_counts",
                    "evaluability_bucket_required",
                    "evaluability_bucket",
                    "evaluability_bucket_coverage_below_p9_target",
                ),
                (
                    "stock_outcome_age_bucket_counts",
                    "stock_outcome_age_bucket_required",
                    "stock_outcome_age_bucket",
                    "stock_outcome_age_bucket_coverage_below_p9_target",
                ),
            )
            for counts_field, targets_field, dimension, blocker in strata_checks:
                counts = _count_mapping(
                    markdown_coverage.get(counts_field),
                    row_label=f"markdown_coverage_summary.{counts_field}",
                    failures=markdown_coverage_failures,
                )
                required = _string_items(coverage_strata_targets.get(targets_field))
                if not required:
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.coverage_strata_targets."
                        f"{targets_field}: must be non-empty"
                    )
                    continue
                expected_missing = {
                    f"{dimension}:{bucket}"
                    for bucket in required
                    if int(counts.get(bucket) or 0) <= 0
                }
                if expected_missing and blocker not in coverage_blockers:
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.coverage_gate_blockers must "
                        f"include {blocker}"
                    )
                if not expected_missing and blocker in coverage_blockers:
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.coverage_gate_blockers includes "
                        f"stale {blocker}"
                    )
                missing_delta = expected_missing - coverage_strata_missing
                if missing_delta:
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.coverage_strata_missing must "
                        "include " + ", ".join(sorted(missing_delta))
                    )
            require_coverage_shortfall(
                "coverage_strata_missing_count",
                current=len(coverage_strata_missing),
                target=0,
                blocker="stratified_coverage_below_p9_target",
                next_action=(
                    "fill_missing_time_institution_horizon_evaluability_strata"
                ),
            )
        expected_coverage_status = "blocked" if coverage_blockers else "passed"
        if markdown_coverage.get("coverage_gate_status") != expected_coverage_status:
            markdown_coverage_failures.append(
                "markdown_coverage_summary.coverage_gate_status: expected "
                f"{expected_coverage_status}"
            )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_markdown_coverage_privacy_rules",
            artifact_path="registry/report_intelligence/markdown_coverage_summary.json",
            item_count=1 if markdown_coverage else 0,
            accepted=not markdown_coverage_failures,
            failures=tuple(markdown_coverage_failures),
        )
    )

    footprint_review_failures: list[str] = []
    footprint_review_summary, footprint_review_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/analytical_footprint_review_summary.json",
        "registry/report_intelligence/analytical_footprint_review_summary.json",
    )
    footprint_review_failures.extend(footprint_review_errors)
    if footprint_review_summary:
        if footprint_review_summary.get("accepted") is not True:
            footprint_review_failures.append(
                "analytical_footprint_review_summary accepted must be true"
            )
        if footprint_review_summary.get("review_complete") is not True:
            footprint_review_failures.append(
                "analytical_footprint_review_summary review_complete must be true"
            )
        if footprint_review_summary.get("quality_gate_passed") is not True:
            footprint_review_failures.append(
                "analytical_footprint_review_summary quality_gate_passed must be true"
            )
        if int(footprint_review_summary.get("pending_rows") or 0) != 0:
            footprint_review_failures.append(
                "analytical_footprint_review_summary pending_rows must be zero"
            )
        quality_blockers = [
            str(item)
            for item in footprint_review_summary.get("quality_gate_blockers", [])
            if str(item).strip()
        ]
        if quality_blockers:
            footprint_review_failures.append(
                "analytical_footprint_review_summary quality blockers: "
                + "; ".join(quality_blockers)
            )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_analytical_footprint_review_rules",
            artifact_path="registry/report_intelligence/analytical_footprint_review_summary.json",
            item_count=1 if footprint_review_summary else 0,
            accepted=not footprint_review_failures,
            failures=tuple(footprint_review_failures),
        )
    )

    provenance_audit_failures: list[str] = []
    provenance_audit, provenance_audit_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/extraction_provenance_audit.json",
        "registry/report_intelligence/extraction_provenance_audit.json",
    )
    provenance_audit_failures.extend(provenance_audit_errors)
    provenance_checks = []
    if provenance_audit:
        provenance_checks = [
            item
            for item in provenance_audit.get("checks", [])
            if isinstance(item, Mapping)
        ]
        if provenance_audit.get("accepted") is not True:
            provenance_audit_failures.append(
                "extraction_provenance_audit accepted must be true"
            )
        if provenance_audit.get("blocker_count") not in {0, None}:
            provenance_audit_failures.append(
                "extraction_provenance_audit blocker_count must be zero"
            )
        expected_check_ids = {f"RI-PROV-{index:02d}" for index in range(6)}
        observed_check_ids = {
            str(item.get("check_id") or "") for item in provenance_checks
        }
        missing_check_ids = sorted(expected_check_ids - observed_check_ids)
        if missing_check_ids:
            provenance_audit_failures.append(
                "extraction_provenance_audit missing checks: "
                + ", ".join(missing_check_ids)
            )
        for item in provenance_checks:
            if item.get("accepted") is not True:
                provenance_audit_failures.append(
                    f"extraction_provenance_audit {item.get('check_id')}: check must be accepted"
                )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_extraction_provenance_audit_rules",
            artifact_path="registry/report_intelligence/extraction_provenance_audit.json",
            item_count=len(provenance_checks),
            accepted=not provenance_audit_failures,
            failures=tuple(provenance_audit_failures),
        )
    )

    statistical_audit_failures: list[str] = []
    statistical_audit, statistical_audit_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/statistical_robustness_audit.json",
        "registry/report_intelligence/statistical_robustness_audit.json",
    )
    statistical_audit_failures.extend(statistical_audit_errors)
    statistical_checks = []
    if statistical_audit:
        statistical_checks = [
            item
            for item in statistical_audit.get("checks", [])
            if isinstance(item, Mapping)
        ]
        if statistical_audit.get("accepted") is not True:
            statistical_audit_failures.append(
                "statistical_robustness_audit accepted must be true"
            )
        if statistical_audit.get("blocker_count") not in {0, None}:
            statistical_audit_failures.append(
                "statistical_robustness_audit blocker_count must be zero"
            )
        expected_check_ids = {f"RI-STAT-{index:02d}" for index in range(8)}
        observed_check_ids = {
            str(item.get("check_id") or "") for item in statistical_checks
        }
        missing_check_ids = sorted(expected_check_ids - observed_check_ids)
        if missing_check_ids:
            statistical_audit_failures.append(
                "statistical_robustness_audit missing checks: "
                + ", ".join(missing_check_ids)
            )
        for item in statistical_checks:
            if item.get("accepted") is not True:
                statistical_audit_failures.append(
                    f"statistical_robustness_audit {item.get('check_id')}: check must be accepted"
                )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_statistical_robustness_audit_rules",
            artifact_path="registry/report_intelligence/statistical_robustness_audit.json",
            item_count=len(statistical_checks),
            accepted=not statistical_audit_failures,
            failures=tuple(statistical_audit_failures),
        )
    )

    tool_feasibility_audit_failures: list[str] = []
    tool_feasibility_audit, tool_feasibility_audit_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/tool_feasibility_audit.json",
        "registry/report_intelligence/tool_feasibility_audit.json",
    )
    tool_feasibility_audit_failures.extend(tool_feasibility_audit_errors)
    tool_feasibility_checks = []
    if tool_feasibility_audit:
        tool_feasibility_checks = [
            item
            for item in tool_feasibility_audit.get("checks", [])
            if isinstance(item, Mapping)
        ]
        if tool_feasibility_audit.get("accepted") is not True:
            tool_feasibility_audit_failures.append(
                "tool_feasibility_audit accepted must be true"
            )
        if tool_feasibility_audit.get("blocker_count") not in {0, None}:
            tool_feasibility_audit_failures.append(
                "tool_feasibility_audit blocker_count must be zero"
            )
        expected_check_ids = {f"RI-TOOL-{index:02d}" for index in range(7)}
        observed_check_ids = {
            str(item.get("check_id") or "") for item in tool_feasibility_checks
        }
        missing_check_ids = sorted(expected_check_ids - observed_check_ids)
        if missing_check_ids:
            tool_feasibility_audit_failures.append(
                "tool_feasibility_audit missing checks: "
                + ", ".join(missing_check_ids)
            )
        for item in tool_feasibility_checks:
            if item.get("accepted") is not True:
                tool_feasibility_audit_failures.append(
                    f"tool_feasibility_audit {item.get('check_id')}: check must be accepted"
                )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_tool_feasibility_audit_rules",
            artifact_path="registry/report_intelligence/tool_feasibility_audit.json",
            item_count=len(tool_feasibility_checks),
            accepted=not tool_feasibility_audit_failures,
            failures=tuple(tool_feasibility_audit_failures),
        )
    )

    recipe_validation_audit_failures: list[str] = []
    recipe_validation_audit, recipe_validation_audit_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/recipe_validation_audit.json",
        "registry/report_intelligence/recipe_validation_audit.json",
    )
    recipe_validation_audit_failures.extend(recipe_validation_audit_errors)
    recipe_validation_checks = []
    if recipe_validation_audit:
        recipe_validation_checks = [
            item
            for item in recipe_validation_audit.get("checks", [])
            if isinstance(item, Mapping)
        ]
        if recipe_validation_audit.get("accepted") is not True:
            recipe_validation_audit_failures.append(
                "recipe_validation_audit accepted must be true"
            )
        if recipe_validation_audit.get("blocker_count") not in {0, None}:
            recipe_validation_audit_failures.append(
                "recipe_validation_audit blocker_count must be zero"
            )
        expected_check_ids = {f"RI-RECIPE-{index:02d}" for index in range(8)}
        observed_check_ids = {
            str(item.get("check_id") or "") for item in recipe_validation_checks
        }
        missing_check_ids = sorted(expected_check_ids - observed_check_ids)
        if missing_check_ids:
            recipe_validation_audit_failures.append(
                "recipe_validation_audit missing checks: "
                + ", ".join(missing_check_ids)
            )
        for item in recipe_validation_checks:
            if item.get("accepted") is not True:
                recipe_validation_audit_failures.append(
                    f"recipe_validation_audit {item.get('check_id')}: check must be accepted"
                )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_recipe_validation_audit_rules",
            artifact_path="registry/report_intelligence/recipe_validation_audit.json",
            item_count=len(recipe_validation_checks),
            accepted=not recipe_validation_audit_failures,
            failures=tuple(recipe_validation_audit_failures),
        )
    )

    (
        recipe_paper_trading_contract_item_count,
        recipe_paper_trading_contract_failures,
    ) = _validate_recipe_paper_trading_contract(root_path)
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_recipe_paper_trading_contract_rules",
            artifact_path="registry/report_intelligence",
            item_count=recipe_paper_trading_contract_item_count,
            accepted=not recipe_paper_trading_contract_failures,
            failures=tuple(recipe_paper_trading_contract_failures),
        )
    )

    (
        evolution_refresh_history_item_count,
        evolution_refresh_history_failures,
    ) = _validate_evolution_refresh_history_contract(root_path)
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_evolution_refresh_history_rules",
            artifact_path="registry/report_intelligence/*_refresh_history.jsonl",
            item_count=evolution_refresh_history_item_count,
            accepted=not evolution_refresh_history_failures,
            failures=tuple(evolution_refresh_history_failures),
        )
    )

    (
        evolution_readiness_gate_item_count,
        evolution_readiness_gate_failures,
    ) = _validate_evolution_readiness_gate_contract(root_path)
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_evolution_readiness_gate_rules",
            artifact_path="registry/report_intelligence/evolution_readiness_gate.json",
            item_count=evolution_readiness_gate_item_count,
            accepted=not evolution_readiness_gate_failures,
            failures=tuple(evolution_readiness_gate_failures),
        )
    )

    gold_review_gate_item_count, gold_review_gate_failures = (
        _validate_gold_review_gate_contract(root_path)
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_gold_review_gate_rules",
            artifact_path="registry/gold_sets/tushare_research_reports.review_summary.json",
            item_count=gold_review_gate_item_count,
            accepted=not gold_review_gate_failures,
            failures=tuple(gold_review_gate_failures),
        )
    )

    (
        prompt_mutation_candidate_item_count,
        prompt_mutation_candidate_failures,
    ) = _validate_prompt_mutation_candidate_contract(root_path)
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_prompt_mutation_candidate_contract_rules",
            artifact_path="registry/report_intelligence/prompt_mutation_candidates.jsonl",
            item_count=prompt_mutation_candidate_item_count,
            accepted=not prompt_mutation_candidate_failures,
            failures=tuple(prompt_mutation_candidate_failures),
        )
    )

    (
        manual_review_progress_item_count,
        manual_review_progress_failures,
    ) = _validate_manual_review_progress_privacy_contract(root_path)
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_manual_review_progress_privacy_rules",
            artifact_path="registry/review_batches/manual_review_progress_report.json",
            item_count=manual_review_progress_item_count,
            accepted=not manual_review_progress_failures,
            failures=tuple(manual_review_progress_failures),
        )
    )

    manual_review_progress_contract_item_count, manual_review_progress_contract_failures = (
        _validate_manual_review_progress_contract(root_path)
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_manual_review_progress_rules",
            artifact_path="registry/review_batches/manual_review_progress_report.json",
            item_count=manual_review_progress_contract_item_count,
            accepted=not manual_review_progress_contract_failures,
            failures=tuple(manual_review_progress_contract_failures),
        )
    )

    operator_handoff_item_count, operator_handoff_failures = (
        _validate_operator_handoff_contract(root_path)
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_operator_handoff_rules",
            artifact_path="registry/handoffs/rke_operator_handoff.json",
            item_count=operator_handoff_item_count,
            accepted=not operator_handoff_failures,
            failures=tuple(operator_handoff_failures),
        )
    )

    operator_readiness_item_count, operator_readiness_failures = (
        _validate_operator_readiness_contract(root_path)
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_operator_readiness_rules",
            artifact_path="registry/handoffs/rke_operator_readiness_report.json",
            item_count=operator_readiness_item_count,
            accepted=not operator_readiness_failures,
            failures=tuple(operator_readiness_failures),
        )
    )

    bundle_manifest_item_count, bundle_manifest_failures = (
        _validate_manual_review_bundle_manifest_contract(root_path)
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_manual_review_bundle_manifest_rules",
            artifact_path="registry/review_batches/manual_review_bundle_manifest.json",
            item_count=bundle_manifest_item_count,
            accepted=not bundle_manifest_failures,
            failures=tuple(bundle_manifest_failures),
        )
    )

    promotion_dry_run_item_count, promotion_dry_run_failures = (
        _validate_promotion_dry_run_contract(root_path)
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_promotion_dry_run_rules",
            artifact_path="registry/promotion/rke_promotion_dry_run_report.json",
            item_count=promotion_dry_run_item_count,
            accepted=not promotion_dry_run_failures,
            failures=tuple(promotion_dry_run_failures),
        )
    )

    promotion_gate_item_count, promotion_gate_failures = (
        _validate_production_promotion_gate_contract(root_path)
    )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_production_promotion_gate_rules",
            artifact_path="registry/promotion/rke_production_promotion_gate.json",
            item_count=promotion_gate_item_count,
            accepted=not promotion_gate_failures,
            failures=tuple(promotion_gate_failures),
        )
    )

    ledger_rows, ledger_failures, _ledger_rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/report_forecast_ledger.jsonl",
    )
    readiness_failures = list(ledger_failures)
    readiness_report, readiness_report_failures = _read_mapping_json(
        root_path / "registry/report_intelligence/outcome_labeling_readiness.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
    )
    readiness_failures.extend(readiness_report_failures)
    forecasts_by_id = {str(row.get("forecast_claim_id") or ""): row for row in forecast_rows}
    if forecast_rows_present and len(forecasts_by_id) != len(forecast_rows):
        readiness_failures.append("forecast_claim_id values must be unique")
    ledger_claim_ids = {
        str(row.get("forecast_claim_id") or "")
        for row in ledger_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    private_forecasts_same_vintage = (
        forecast_rows_present
        and _private_public_id_sets_same_vintage(
            {claim_id for claim_id in forecasts_by_id if claim_id},
            ledger_claim_ids,
        )
    )
    ledger_test_status_counts: dict[str, int] = {}
    for index, row in enumerate(ledger_rows, 1):
        row_label = f"report_forecast_ledger row {index}"
        if row.get("immutable") is not True:
            readiness_failures.append(f"{row_label}: immutable must be true")
        test_status = str(row.get("test_status") or "")
        ledger_test_status_counts[test_status] = ledger_test_status_counts.get(test_status, 0) + 1
        if not private_forecasts_same_vintage:
            continue
        claim_id = str(row.get("forecast_claim_id") or "")
        if claim_id not in forecasts_by_id:
            readiness_failures.append(f"{row_label}: forecast_claim_id not found")
    ready_count = ledger_test_status_counts.get("ready_for_outcome_labeling", 0)
    standard_blocked_count = len(ledger_rows) - ready_count
    if readiness_report:
        if readiness_report.get("forecast_ledger_count") != len(ledger_rows):
            readiness_failures.append(
                "outcome_labeling_readiness forecast_ledger_count mismatch"
            )
        if (
            private_forecasts_same_vintage
            and readiness_report.get("forecast_claim_count") != len(forecast_rows)
        ):
            readiness_failures.append(
                "outcome_labeling_readiness forecast_claim_count mismatch"
            )
        if readiness_report.get("test_status_counts") != dict(
            sorted(ledger_test_status_counts.items())
        ):
            readiness_failures.append(
                "outcome_labeling_readiness test_status_counts mismatch"
            )
        if readiness_report.get("ready_for_outcome_labeling_count") != ready_count:
            readiness_failures.append(
                "outcome_labeling_readiness ready_for_outcome_labeling_count mismatch"
            )
        if readiness_report.get("standard_blocked_count") != standard_blocked_count:
            readiness_failures.append(
                "outcome_labeling_readiness standard_blocked_count mismatch"
            )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_forecast_readiness_rules",
            artifact_path="registry/report_intelligence/report_forecast_ledger.jsonl",
            item_count=len(ledger_rows),
            accepted=not readiness_failures,
            failures=tuple(readiness_failures),
        )
    )

    runtime_failures: list[str] = []
    feature_flags, feature_flag_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/feature_flags.json",
        "registry/report_intelligence/feature_flags.json",
    )
    runtime_failures.extend(feature_flag_errors)
    if feature_flags:
        flags = feature_flags.get("flags") or {}
        rollout_mode = str(feature_flags.get("rollout_mode") or "")
        runtime_behavior = str(feature_flags.get("runtime_behavior") or "")
        if not isinstance(flags, Mapping):
            runtime_failures.append("feature_flags.flags: expected object")
        else:
            bool_flag_names = {
                str(key) for key, value in flags.items() if isinstance(value, bool)
            }
            expected_flag_names = {
                "report_weighting_enabled",
                "analytical_footprint_enabled",
                "weighted_research_retriever_enabled",
                "method_pattern_registry_enabled",
                "tool_design_loop_enabled",
                "shadow_tool_runtime_enabled",
                "production_use_of_weighted_reports",
            }
            missing_flag_names = sorted(expected_flag_names - bool_flag_names)
            if missing_flag_names:
                runtime_failures.append(
                    "feature_flags.flags missing expected booleans: "
                    + ", ".join(missing_flag_names)
                )
            if flags.get("production_use_of_weighted_reports") is True:
                runtime_failures.append(
                    "production_use_of_weighted_reports must remain false before paper-trading promotion"
                )
            if rollout_mode in {"off", "extraction_only"}:
                enabled = sorted(
                    str(key)
                    for key, value in flags.items()
                    if value is True and key != "production_use_of_weighted_reports"
                )
                if enabled:
                    runtime_failures.append(
                        f"{rollout_mode} mode cannot enable report-intelligence feature flags: "
                        + ", ".join(enabled)
                    )
            elif rollout_mode == "shadow_retrieval":
                if flags.get("weighted_research_retriever_enabled") is not True:
                    runtime_failures.append(
                        "shadow_retrieval requires weighted_research_retriever_enabled"
                    )
                if flags.get("shadow_tool_runtime_enabled") is True:
                    runtime_failures.append(
                        "shadow_retrieval cannot enable shadow_tool_runtime_enabled"
                    )
            elif rollout_mode == "shadow_tooling":
                required_shadow_flags = (
                    "weighted_research_retriever_enabled",
                    "method_pattern_registry_enabled",
                    "tool_design_loop_enabled",
                    "shadow_tool_runtime_enabled",
                )
                for name in required_shadow_flags:
                    if flags.get(name) is not True:
                        runtime_failures.append(f"shadow_tooling requires {name}")
            else:
                runtime_failures.append(
                    "rollout_mode must not exceed shadow_tooling before paper-trading validation"
                )
        if "no agent decision impact" not in runtime_behavior:
            runtime_failures.append(
                "feature_flags.runtime_behavior must state no agent decision impact"
            )

    method_rows, method_failures, _method_rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/method_patterns.jsonl",
    )
    recipe_rows, recipe_failures, _recipe_rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/analysis_recipes.jsonl",
    )
    (
        context_rows,
        context_failures,
        _context_rows_present,
    ) = _load_optional_mapping_jsonl(
        root_path,
        "registry/report_intelligence/weighted_research_contexts.jsonl",
    )
    (
        gap_observation_rows,
        gap_observation_failures,
        _gap_observation_rows_present,
    ) = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/runtime_tool_gap_observations.jsonl",
    )
    runtime_failures.extend(
        [
            *method_failures,
            *recipe_failures,
            *context_failures,
            *gap_observation_failures,
        ]
    )
    for index, row in enumerate(method_rows, 1):
        if row.get("allowed_runtime_mode") != "shadow_only":
            runtime_failures.append(f"method_patterns row {index}: allowed_runtime_mode must remain shadow_only")
    for index, row in enumerate(recipe_rows, 1):
        if row.get("runtime_mode") != "shadow_only":
            runtime_failures.append(f"analysis_recipes row {index}: runtime_mode must remain shadow_only")
    for index, row in enumerate(context_rows, 1):
        if row.get("research_only") is not True:
            runtime_failures.append(f"weighted_research_contexts row {index}: research_only must be true")
        if row.get("actionability") != "no_trade_without_current_data_confirmation":
            runtime_failures.append(
                f"weighted_research_contexts row {index}: actionability must block trading without current data"
            )
    for index, row in enumerate(gap_observation_rows, 1):
        if row.get("runtime_role") != "gap_observation_only":
            runtime_failures.append(
                f"runtime_tool_gap_observations row {index}: runtime_role must be gap_observation_only"
            )
        if row.get("research_only") is not True:
            runtime_failures.append(
                f"runtime_tool_gap_observations row {index}: research_only must be true"
            )
        if row.get("current_data_confirmation") != "missing":
            runtime_failures.append(
                f"runtime_tool_gap_observations row {index}: current data confirmation must remain missing"
            )
        if row.get("actionability") != "no_trade_without_current_data_confirmation":
            runtime_failures.append(
                f"runtime_tool_gap_observations row {index}: actionability must block trading without current data"
            )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_runtime_guard_rules",
            artifact_path="registry/report_intelligence",
            item_count=(
                len(method_rows)
                + len(recipe_rows)
                + len(context_rows)
                + len(gap_observation_rows)
            ),
            accepted=not runtime_failures,
            failures=tuple(runtime_failures),
        )
    )

    monitoring_failures: list[str] = []
    monitoring_report, monitoring_report_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/monitoring_report.json",
        "registry/report_intelligence/monitoring_report.json",
    )
    monitoring_failures.extend(monitoring_report_errors)
    confidence_impact_monitor, confidence_impact_monitor_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/confidence_impact_monitor.json",
        "registry/report_intelligence/confidence_impact_monitor.json",
    )
    monitoring_failures.extend(confidence_impact_monitor_errors)
    extraction_report, extraction_report_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/extraction_report.json",
        "registry/report_intelligence/extraction_report.json",
    )
    monitoring_failures.extend(extraction_report_errors)
    (
        source_profile_rows,
        source_profile_failures,
        _source_profile_rows_present,
    ) = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/source_performance_profiles.jsonl",
    )
    (
        viewpoint_profile_rows,
        viewpoint_profile_failures,
        _viewpoint_profile_rows_present,
    ) = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/viewpoint_performance_profiles.jsonl",
    )
    (
        method_profile_rows,
        method_profile_failures,
        _method_profile_rows_present,
    ) = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/method_performance_profiles.jsonl",
    )
    tool_gap_rows, tool_gap_failures, _tool_gap_rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/tool_gaps.jsonl",
    )
    (
        data_proposal_rows,
        data_proposal_failures,
        _data_proposal_rows_present,
    ) = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/data_acquisition_proposals.jsonl",
    )
    (
        metric_candidate_rows,
        metric_candidate_failures,
        _metric_candidate_rows_present,
    ) = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/metric_candidates.jsonl",
    )
    (
        tool_coverage_rows,
        tool_coverage_failures,
        _tool_coverage_rows_present,
    ) = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/tool_coverage_matches.jsonl",
    )
    monitoring_failures.extend(
        [
            *source_profile_failures,
            *viewpoint_profile_failures,
            *method_profile_failures,
            *tool_gap_failures,
            *data_proposal_failures,
            *metric_candidate_failures,
            *tool_coverage_failures,
        ]
    )
    expected_decay_metrics = {
        "rolling_after_cost_alpha",
        "rolling_hit_rate",
        "calibration_drift",
        "turnover_impact",
        "drawdown_after_signal",
        "half_life_estimate",
        "current_vs_backtest_performance_divergence",
    }
    expected_rollback_modes = {
        "soft_rollback",
        "hard_rollback",
        "compliance_rollback",
    }
    alpha_decay = {}
    if monitoring_report:
        alpha_decay = (
            monitoring_report.get("alpha_decay_monitoring")
            if isinstance(monitoring_report.get("alpha_decay_monitoring"), Mapping)
            else {}
        )
        confidence_impact_monitoring = (
            monitoring_report.get("confidence_impact_monitoring")
            if isinstance(
                monitoring_report.get("confidence_impact_monitoring"),
                Mapping,
            )
            else {}
        )
        if not confidence_impact_monitoring:
            monitoring_failures.append(
                "monitoring_report confidence_impact_monitoring must be object"
            )
        monitor_count_fields = (
            "observation_count",
            "paper_trading_validated_recipe_count",
            "unvalidated_confidence_impact_count",
            "alpha_decay_watch_count",
            "alpha_decay_fail_count",
            "cost_decay_fail_count",
            "calibration_drift_count",
            "aggregate_calibration_drift_count",
            "regime_fragile_alpha_count",
        )
        for field in monitor_count_fields:
            if confidence_impact_monitoring.get(field) != confidence_impact_monitor.get(
                field
            ):
                monitoring_failures.append(
                    f"confidence_impact_monitoring {field} mismatch"
                )
        for field in (
            "monitor_id",
            "confidence_alpha_correlation",
            "confidence_alpha_correlation_status",
            "production_decision_impact_allowed",
        ):
            if confidence_impact_monitoring.get(field) != confidence_impact_monitor.get(
                field
            ):
                monitoring_failures.append(
                    f"confidence_impact_monitoring {field} mismatch"
                )
        observed_action_counts = _count_mapping(
            confidence_impact_monitoring.get("recommended_action_counts"),
            row_label="confidence_impact_monitoring.recommended_action_counts",
            failures=monitoring_failures,
        )
        expected_action_counts = _count_mapping(
            confidence_impact_monitor.get("recommended_action_counts"),
            row_label="confidence_impact_monitor.recommended_action_counts",
            failures=monitoring_failures,
        )
        if observed_action_counts != expected_action_counts:
            monitoring_failures.append(
                "confidence_impact_monitoring recommended_action_counts mismatch"
            )
        if not alpha_decay:
            monitoring_failures.append(
                "monitoring_report alpha_decay_monitoring must be object"
            )
        report_corpus = (
            monitoring_report.get("report_corpus")
            if isinstance(monitoring_report.get("report_corpus"), Mapping)
            else {}
        )
        if not report_corpus:
            monitoring_failures.append("monitoring_report report_corpus must be object")
        if extraction_report:
            for report_field, extraction_field in (
                ("metadata_rows", "metadata_rows"),
                ("forecast_claim_rows", "forecast_claim_rows"),
                ("outcome_label_rows", "outcome_label_rows"),
            ):
                if _int_or_none(report_corpus.get(report_field)) != _int_or_none(
                    extraction_report.get(extraction_field)
                ):
                    monitoring_failures.append(
                        f"monitoring_report.report_corpus {report_field} mismatch"
                    )
        tooling_loop = (
            monitoring_report.get("tooling_loop_monitoring")
            if isinstance(monitoring_report.get("tooling_loop_monitoring"), Mapping)
            else {}
        )
        if not tooling_loop:
            monitoring_failures.append(
                "monitoring_report tooling_loop_monitoring must be object"
            )
        else:
            expected_tooling_counts = (
                (
                    "tool_gap_open_count",
                    len(tool_gap_rows),
                    _tool_gap_rows_present,
                ),
                (
                    "data_proposal_open_count",
                    len(data_proposal_rows),
                    _data_proposal_rows_present,
                ),
                (
                    "runtime_fallback_observation_count",
                    len(gap_observation_rows),
                    _gap_observation_rows_present,
                ),
                ("shadow_recipe_count", len(recipe_rows), _recipe_rows_present),
            )
            for field, expected, rows_present in expected_tooling_counts:
                if rows_present and _int_or_none(tooling_loop.get(field)) != expected:
                    monitoring_failures.append(
                        f"tooling_loop_monitoring {field}: expected {expected}"
                    )
            if _tool_gap_rows_present:
                expected_priority_counts: dict[str, int] = {}
                for row in tool_gap_rows:
                    bucket = str(row.get("priority_bucket") or "").strip()
                    if bucket:
                        expected_priority_counts[bucket] = (
                            expected_priority_counts.get(bucket, 0) + 1
                        )
                observed_priority_counts = _count_mapping(
                    tooling_loop.get("tool_gap_priority_counts"),
                    row_label="tooling_loop_monitoring.tool_gap_priority_counts",
                    failures=monitoring_failures,
                )
                if observed_priority_counts != dict(
                    sorted(expected_priority_counts.items())
                ):
                    monitoring_failures.append(
                        "tooling_loop_monitoring tool_gap_priority_counts mismatch"
                    )
            evidence_coverage = (
                tooling_loop.get("evidence_coverage")
                if isinstance(tooling_loop.get("evidence_coverage"), Mapping)
                else {}
            )
            if not evidence_coverage:
                monitoring_failures.append(
                    "tooling_loop_monitoring.evidence_coverage must be object"
                )
            else:
                if (
                    _metric_candidate_rows_present
                    and _int_or_none(evidence_coverage.get("metric_candidate_count"))
                    != len(metric_candidate_rows)
                ):
                    monitoring_failures.append(
                        "tooling_loop_monitoring.evidence_coverage metric_candidate_count mismatch"
                    )
                if _tool_coverage_rows_present:
                    expected_coverage_counts: dict[str, int] = {}
                    for row in tool_coverage_rows:
                        status = str(row.get("coverage_status") or "").strip()
                        if status:
                            expected_coverage_counts[status] = (
                                expected_coverage_counts.get(status, 0) + 1
                            )
                    observed_coverage_counts = _count_mapping(
                        evidence_coverage.get("tool_coverage_status_counts"),
                        row_label=(
                            "tooling_loop_monitoring.evidence_coverage."
                            "tool_coverage_status_counts"
                        ),
                        failures=monitoring_failures,
                    )
                    if observed_coverage_counts != dict(
                        sorted(expected_coverage_counts.items())
                    ):
                        monitoring_failures.append(
                            "tooling_loop_monitoring.evidence_coverage "
                            "tool_coverage_status_counts mismatch"
                        )
        weighting_monitoring = (
            monitoring_report.get("report_weighting_monitoring")
            if isinstance(monitoring_report.get("report_weighting_monitoring"), Mapping)
            else {}
        )
        if not weighting_monitoring:
            monitoring_failures.append(
                "monitoring_report report_weighting_monitoring must be object"
            )
        else:
            for field, rows, profile_kind, rows_present in (
                (
                    "effective_n_by_source",
                    source_profile_rows,
                    "source",
                    _source_profile_rows_present,
                ),
                (
                    "effective_n_by_viewpoint",
                    viewpoint_profile_rows,
                    "viewpoint",
                    _viewpoint_profile_rows_present,
                ),
                (
                    "effective_n_by_method",
                    method_profile_rows,
                    "method",
                    _method_profile_rows_present,
                ),
            ):
                if not rows_present:
                    continue
                summary = (
                    weighting_monitoring.get(field)
                    if isinstance(weighting_monitoring.get(field), Mapping)
                    else {}
                )
                expected_summary = _profile_effective_n_summary(
                    rows,
                    profile_kind=profile_kind,
                )
                for summary_field, expected in expected_summary.items():
                    observed = _float_or_none(summary.get(summary_field))
                    if observed is None or not _nearly_equal(float(observed), float(expected)):
                        monitoring_failures.append(
                            f"report_weighting_monitoring.{field}.{summary_field}: "
                            f"expected {expected}"
                        )
            source_weight_drift = (
                weighting_monitoring.get("source_weight_drift")
                if isinstance(weighting_monitoring.get("source_weight_drift"), Mapping)
                else {}
            )
            if not source_weight_drift:
                monitoring_failures.append(
                    "report_weighting_monitoring.source_weight_drift must be object"
                )
            elif _source_profile_rows_present:
                source_summary = _profile_effective_n_summary(
                    source_profile_rows,
                    profile_kind="source",
                )
                if not _nearly_equal(
                    float(_float_or_none(source_weight_drift.get("max_effective_n")) or 0.0),
                    float(source_summary["max_effective_n"]),
                ):
                    monitoring_failures.append(
                        "report_weighting_monitoring.source_weight_drift.max_effective_n mismatch"
                    )
                expected_non_neutral = _profile_non_neutral_count(
                    source_profile_rows,
                    profile_kind="source",
                )
                if (
                    _int_or_none(source_weight_drift.get("non_neutral_profile_count"))
                    != expected_non_neutral
                ):
                    monitoring_failures.append(
                        "report_weighting_monitoring.source_weight_drift."
                        "non_neutral_profile_count mismatch"
                    )
        observed_metrics = {
            str(item)
            for item in alpha_decay.get("required_decay_metrics", [])
            if str(item).strip()
        }
        missing_metrics = sorted(expected_decay_metrics - observed_metrics)
        if missing_metrics:
            monitoring_failures.append(
                "alpha_decay_monitoring missing required decay metrics: "
                + ", ".join(missing_metrics)
            )
        observed_modes = {
            str(item)
            for item in alpha_decay.get("required_rollback_modes", [])
            if str(item).strip()
        }
        missing_modes = sorted(expected_rollback_modes - observed_modes)
        if missing_modes:
            monitoring_failures.append(
                "alpha_decay_monitoring missing rollback modes: "
                + ", ".join(missing_modes)
            )
        if alpha_decay.get("monitoring_spec_ready") is not True:
            monitoring_failures.append(
                "alpha_decay_monitoring monitoring_spec_ready must be true"
            )
        paper_count = sum(
            1
            for row in recipe_rows
            if str(row.get("runtime_mode") or "") == "paper_trading"
        )
        limited_count = sum(
            1
            for row in recipe_rows
            if str(row.get("runtime_mode") or "") == "limited_production"
        )
        production_count = sum(
            1
            for row in recipe_rows
            if str(row.get("runtime_mode") or "") == "production"
        )
        if _recipe_rows_present and alpha_decay.get("paper_trading_recipe_count") != paper_count:
            monitoring_failures.append(
                "alpha_decay_monitoring paper_trading_recipe_count mismatch"
            )
        if (
            _recipe_rows_present
            and alpha_decay.get("limited_production_recipe_count") != limited_count
        ):
            monitoring_failures.append(
                "alpha_decay_monitoring limited_production_recipe_count mismatch"
            )
        if _recipe_rows_present and alpha_decay.get("production_recipe_count") != production_count:
            monitoring_failures.append(
                "alpha_decay_monitoring production_recipe_count mismatch"
            )
        if production_count and alpha_decay.get("live_alpha_decay_monitor_active") is not True:
            monitoring_failures.append(
                "alpha_decay_monitoring live monitor must be active for production recipes"
            )
        unmonitored = [
            *[
                str(item)
                for item in alpha_decay.get("unmonitored_paper_trading_recipe_ids", [])
                if str(item).strip()
            ],
            *[
                str(item)
                for item in alpha_decay.get("unmonitored_production_recipe_ids", [])
                if str(item).strip()
            ],
        ]
        if unmonitored:
            monitoring_failures.append(
                "alpha_decay_monitoring unmonitored recipes: "
                + ", ".join(sorted(unmonitored)[:20])
            )
        if alpha_decay.get("alpha_decay_monitor_ready") is not True:
            monitoring_failures.append(
                "alpha_decay_monitoring alpha_decay_monitor_ready must be true"
            )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_alpha_decay_monitoring_rules",
            artifact_path="registry/report_intelligence/monitoring_report.json",
            item_count=len(recipe_rows),
            accepted=not monitoring_failures,
            failures=tuple(monitoring_failures),
        )
    )

    safety_audit_failures: list[str] = []
    safety_audit, safety_audit_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/runtime_safety_audit.json",
        "registry/report_intelligence/runtime_safety_audit.json",
    )
    safety_audit_failures.extend(safety_audit_errors)
    safety_checks = []
    if safety_audit:
        safety_checks = [
            item
            for item in safety_audit.get("checks", [])
            if isinstance(item, Mapping)
        ]
        if safety_audit.get("accepted") is not True:
            safety_audit_failures.append(
                "runtime_safety_audit accepted must be true"
            )
        if safety_audit.get("blocker_count") not in {0, None}:
            safety_audit_failures.append(
                "runtime_safety_audit blocker_count must be zero"
            )
        expected_check_ids = {f"RI-SAFE-{index:02d}" for index in range(10)}
        observed_check_ids = {
            str(item.get("check_id") or "") for item in safety_checks
        }
        missing_check_ids = sorted(expected_check_ids - observed_check_ids)
        if missing_check_ids:
            safety_audit_failures.append(
                "runtime_safety_audit missing checks: "
                + ", ".join(missing_check_ids)
            )
        for item in safety_checks:
            if item.get("accepted") is not True:
                safety_audit_failures.append(
                    f"runtime_safety_audit {item.get('check_id')}: check must be accepted"
                )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_runtime_safety_audit_rules",
            artifact_path="registry/report_intelligence/runtime_safety_audit.json",
            item_count=len(safety_checks),
            accepted=not safety_audit_failures,
            failures=tuple(safety_audit_failures),
        )
    )

    pit_audit_failures: list[str] = []
    pit_audit, pit_audit_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/pit_leakage_audit.json",
        "registry/report_intelligence/pit_leakage_audit.json",
    )
    pit_audit_failures.extend(pit_audit_errors)
    pit_checks = []
    if pit_audit:
        pit_checks = [
            item
            for item in pit_audit.get("checks", [])
            if isinstance(item, Mapping)
        ]
        if pit_audit.get("accepted") is not True:
            pit_audit_failures.append("pit_leakage_audit accepted must be true")
        if pit_audit.get("blocker_count") not in {0, None}:
            pit_audit_failures.append("pit_leakage_audit blocker_count must be zero")
        expected_check_ids = {f"RI-PIT-{index:02d}" for index in range(8)}
        observed_check_ids = {str(item.get("check_id") or "") for item in pit_checks}
        missing_check_ids = sorted(expected_check_ids - observed_check_ids)
        if missing_check_ids:
            pit_audit_failures.append(
                "pit_leakage_audit missing checks: " + ", ".join(missing_check_ids)
            )
        for item in pit_checks:
            if item.get("accepted") is not True:
                pit_audit_failures.append(
                    f"pit_leakage_audit {item.get('check_id')}: check must be accepted"
                )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_pit_leakage_audit_rules",
            artifact_path="registry/report_intelligence/pit_leakage_audit.json",
            item_count=len(pit_checks),
            accepted=not pit_audit_failures,
            failures=tuple(pit_audit_failures),
        )
    )

    tooling_failures: list[str] = []
    tool_gap_rows, tool_gap_failures, _tool_gap_rows_present = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/tool_gaps.jsonl",
    )
    (
        data_proposal_rows,
        data_proposal_failures,
        _data_proposal_rows_present,
    ) = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/data_acquisition_proposals.jsonl",
    )
    (
        tool_proposal_rows,
        tool_proposal_failures,
        _tool_proposal_rows_present,
    ) = _load_public_semantic_jsonl(
        root_path,
        "registry/report_intelligence/tool_design_proposals.jsonl",
    )
    tooling_failures.extend(
        [*tool_gap_failures, *data_proposal_failures, *tool_proposal_failures]
    )
    data_by_gap = {
        str(row.get("tool_gap_id") or ""): row for row in data_proposal_rows
    }
    tool_by_gap = {
        str(row.get("tool_gap_id") or ""): row for row in tool_proposal_rows
    }
    required_proposal_fields = (
        "owner",
        "license_status",
        "pit_feasibility_status",
        "estimated_engineering_effort",
    )
    required_tool_fields = (
        "owner",
        "license_status",
        "pit_feasibility_status",
        "engineering_estimate",
    )
    for index, gap in enumerate(tool_gap_rows, 1):
        priority = str(gap.get("priority_bucket") or "")
        gap_id = str(gap.get("tool_gap_id") or "")
        if priority not in {"high", "medium"}:
            continue
        if not gap_id:
            tooling_failures.append(f"tool_gaps row {index}: tool_gap_id required")
            continue
        data_proposal = data_by_gap.get(gap_id)
        tool_proposal = tool_by_gap.get(gap_id)
        if data_proposal is None:
            tooling_failures.append(
                f"tool_gaps row {index}: {priority} gap missing data acquisition proposal"
            )
        else:
            for field in required_proposal_fields:
                if not str(data_proposal.get(field) or "").strip():
                    tooling_failures.append(
                        f"data_acquisition_proposals[{gap_id}].{field}: required for {priority} gap"
                    )
            if data_proposal.get("source_tool_gap_priority") != priority:
                tooling_failures.append(
                    f"data_acquisition_proposals[{gap_id}]: source_tool_gap_priority mismatch"
                )
            if data_proposal.get("owner") != gap.get("owner"):
                tooling_failures.append(
                    f"data_acquisition_proposals[{gap_id}]: owner must match tool gap"
                )
        if tool_proposal is None:
            tooling_failures.append(
                f"tool_gaps row {index}: {priority} gap missing tool design proposal"
            )
        else:
            for field in required_tool_fields:
                if not str(tool_proposal.get(field) or "").strip():
                    tooling_failures.append(
                        f"tool_design_proposals[{gap_id}].{field}: required for {priority} gap"
                    )
            if tool_proposal.get("source_tool_gap_priority") != priority:
                tooling_failures.append(
                    f"tool_design_proposals[{gap_id}]: source_tool_gap_priority mismatch"
                )
            if tool_proposal.get("owner") != gap.get("owner"):
                tooling_failures.append(
                    f"tool_design_proposals[{gap_id}]: owner must match tool gap"
                )
            if tool_proposal.get("status") not in {
                "shadow_build_requested",
                "blocked_pending_review",
            }:
                tooling_failures.append(
                    f"tool_design_proposals[{gap_id}]: status must stay shadow or blocked"
                )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_tooling_readiness_rules",
            artifact_path="registry/report_intelligence",
            item_count=(
                len(tool_gap_rows)
                + len(data_proposal_rows)
                + len(tool_proposal_rows)
            ),
            accepted=not tooling_failures,
            failures=tuple(tooling_failures),
        )
    )

    patch_coverage_failures: list[str] = []
    patch_coverage_report, patch_coverage_errors = _read_mapping_json(
        root_path / "registry/report_intelligence/patch_v1_5_coverage_report.json",
        "registry/report_intelligence/patch_v1_5_coverage_report.json",
    )
    patch_coverage_failures.extend(patch_coverage_errors)
    recipe_paper_trading_summary, recipe_paper_trading_summary_errors = (
        _read_mapping_json(
            root_path / "registry/report_intelligence/recipe_paper_trading_summary.json",
            "registry/report_intelligence/recipe_paper_trading_summary.json",
        )
    )
    patch_coverage_failures.extend(recipe_paper_trading_summary_errors)
    phase_records = []
    requirement_checklist = []
    if patch_coverage_report:
        corpus_counts = patch_coverage_report.get("corpus_counts")
        if not isinstance(corpus_counts, Mapping):
            patch_coverage_failures.append(
                "patch_v1_5_coverage_report corpus_counts: expected object"
            )
            corpus_counts = {}
        public_corpus_count_artifacts = {
            "method_pattern_rows": "registry/report_intelligence/method_patterns.jsonl",
            "metric_candidate_rows": "registry/report_intelligence/metric_candidates.jsonl",
            "runtime_tool_gap_observation_rows": (
                "registry/report_intelligence/runtime_tool_gap_observations.jsonl"
            ),
            "tool_gap_rows": "registry/report_intelligence/tool_gaps.jsonl",
        }
        for count_field, artifact_path in public_corpus_count_artifacts.items():
            rows, load_failures, rows_present = _load_public_semantic_jsonl(
                root_path,
                artifact_path,
            )
            patch_coverage_failures.extend(load_failures)
            if not rows_present:
                continue
            observed_count = _float_or_none(corpus_counts.get(count_field))
            expected_count = len(rows)
            if observed_count is None or int(observed_count) != expected_count:
                patch_coverage_failures.append(
                    "patch_v1_5_coverage_report corpus_counts."
                    f"{count_field}: expected {expected_count}"
                )
        phase_records = [
            item
            for item in patch_coverage_report.get("phase_records", [])
            if isinstance(item, Mapping)
        ]
        requirement_checklist = [
            item
            for item in patch_coverage_report.get("requirement_checklist", [])
            if isinstance(item, Mapping)
        ]
        if patch_coverage_report.get("accepted") is not True:
            patch_coverage_failures.append(
                "patch_v1_5_coverage_report accepted must be true"
            )
        if patch_coverage_report.get("blocker_count") not in {0, None}:
            patch_coverage_failures.append(
                "patch_v1_5_coverage_report blocker_count must be zero"
            )
        blocked_phase_ids_value = patch_coverage_report.get("blocked_phase_ids")
        if blocked_phase_ids_value not in (None, ()) and blocked_phase_ids_value != []:
            patch_coverage_failures.append(
                "patch_v1_5_coverage_report blocked_phase_ids must be empty"
            )
        observed_phase_ids = {
            str(item.get("phase_id") or "") for item in phase_records
        }
        expected_phase_ids = set("ABCDEFGH")
        missing_phase_ids = sorted(expected_phase_ids - observed_phase_ids)
        extra_phase_ids = sorted(observed_phase_ids - expected_phase_ids)
        if missing_phase_ids:
            patch_coverage_failures.append(
                "patch_v1_5_coverage_report missing phases: "
                + ", ".join(missing_phase_ids)
            )
        if extra_phase_ids:
            patch_coverage_failures.append(
                "patch_v1_5_coverage_report has unknown phases: "
                + ", ".join(extra_phase_ids)
            )
        if patch_coverage_report.get("phase_count") != len(phase_records):
            patch_coverage_failures.append(
                "patch_v1_5_coverage_report phase_count mismatch"
            )
        feature_rollout_mode = (
            str(feature_flags.get("rollout_mode") or "")
            if feature_flags
            else ""
        )
        if patch_coverage_report.get("current_rollout_mode") != feature_rollout_mode:
            patch_coverage_failures.append(
                "patch_v1_5_coverage_report current_rollout_mode must match feature_flags"
            )
        deferred_phase_ids = {
            str(item)
            for item in patch_coverage_report.get("deferred_phase_ids", [])
            if str(item).strip()
        }
        if feature_rollout_mode == "shadow_tooling" and not {"G", "H"} <= deferred_phase_ids:
            patch_coverage_failures.append(
                "shadow_tooling coverage must defer Phase G and Phase H by rollout"
            )
        after_cost_paper_trading_summary = (
            recipe_paper_trading_summary.get("after_cost_paper_trading_summary")
            if isinstance(
                recipe_paper_trading_summary.get("after_cost_paper_trading_summary"),
                Mapping,
            )
            else {}
        )
        expected_phase_g_counts = {
            "shadow_paper_trading_run_count": int(
                recipe_paper_trading_summary.get("paper_trading_run_count")
                or recipe_paper_trading_summary.get("recipe_count")
                or 0
            ),
            "paper_trading_validation_pass_count": int(
                recipe_paper_trading_summary.get("validation_pass_count") or 0
            ),
            "paper_trading_blocked_count": int(
                recipe_paper_trading_summary.get("blocked_count") or 0
            ),
            "after_cost_summary_status": str(
                after_cost_paper_trading_summary.get("status") or ""
            ),
        }
        expected_phase_g_positive_count = int(
            after_cost_paper_trading_summary.get(
                "positive_after_cost_recipe_count"
            )
            or 0
        )
        phase_g_records = [
            item for item in phase_records if str(item.get("phase_id") or "") == "G"
        ]
        checklist_g_records = [
            item
            for item in requirement_checklist
            if str(item.get("check_id") or "") == "RI15-G-G1"
        ]
        for row_label, rows in (
            ("Phase G", phase_g_records),
            ("RI15-G-G1", checklist_g_records),
        ):
            if not rows:
                continue
            evidence_counts = rows[0].get("evidence_counts")
            if not isinstance(evidence_counts, Mapping):
                patch_coverage_failures.append(
                    f"patch_v1_5_coverage_report {row_label}: evidence_counts must be object"
                )
                continue
            for field, expected in expected_phase_g_counts.items():
                observed = evidence_counts.get(field)
                if observed != expected:
                    patch_coverage_failures.append(
                        f"patch_v1_5_coverage_report {row_label}: "
                        f"evidence_counts.{field} expected {expected}"
                    )
            if (
                row_label == "Phase G"
                and evidence_counts.get("after_cost_positive_recipe_count")
                != expected_phase_g_positive_count
            ):
                patch_coverage_failures.append(
                    "patch_v1_5_coverage_report Phase G: "
                    "evidence_counts.after_cost_positive_recipe_count expected "
                    f"{expected_phase_g_positive_count}"
                )
        for item in phase_records:
            phase_id = str(item.get("phase_id") or "")
            status = str(item.get("status") or "")
            if item.get("accepted") is not True:
                patch_coverage_failures.append(
                    f"patch_v1_5_coverage_report Phase {phase_id}: accepted must be true"
                )
            if status not in {"passed", "deferred_by_rollout"}:
                patch_coverage_failures.append(
                    f"patch_v1_5_coverage_report Phase {phase_id}: status cannot be {status}"
                )
            if item.get("failure_count") not in {0, None}:
                patch_coverage_failures.append(
                    f"patch_v1_5_coverage_report Phase {phase_id}: failure_count must be zero"
                )
            if feature_rollout_mode == "shadow_tooling" and phase_id in {"G", "H"}:
                if status != "deferred_by_rollout":
                    patch_coverage_failures.append(
                        f"patch_v1_5_coverage_report Phase {phase_id}: must be deferred_by_rollout in shadow_tooling"
                    )
                if not str(item.get("deferred_reason") or "").strip():
                    patch_coverage_failures.append(
                        f"patch_v1_5_coverage_report Phase {phase_id}: deferred_reason required"
                    )
        expected_check_ids = {
            "RI15-A-D1",
            "RI15-A-D2",
            "RI15-B-D1",
            "RI15-B-D2",
            "RI15-C-D1",
            "RI15-D-D1",
            "RI15-E-D1",
            "RI15-F-D1",
            "RI15-G-G1",
            "RI15-H-G1",
        }
        observed_check_ids = {
            str(item.get("check_id") or "") for item in requirement_checklist
        }
        missing_check_ids = sorted(expected_check_ids - observed_check_ids)
        if missing_check_ids:
            patch_coverage_failures.append(
                "patch_v1_5_coverage_report requirement_checklist missing checks: "
                + ", ".join(missing_check_ids)
            )
        checklist_phase_ids = {
            str(item.get("phase_id") or "") for item in requirement_checklist
        }
        missing_checklist_phase_ids = sorted(expected_phase_ids - checklist_phase_ids)
        if missing_checklist_phase_ids:
            patch_coverage_failures.append(
                "patch_v1_5_coverage_report requirement_checklist missing phases: "
                + ", ".join(missing_checklist_phase_ids)
            )
        required_requirement_terms = {
            "runtime no-op",
            "human-labeled forecast claim gold set",
            "span-grounded verifier",
            "precision/recall report",
            "overlap adjustment",
            "bucketed weights",
            "alias/proxy mapping",
            "data availability/pit review",
            "weighted research retriever",
            "audit logs",
            "rollback hooks",
        }
        checklist_requirements_text = " ".join(
            str(item.get("requirement") or "").lower()
            for item in requirement_checklist
        )
        missing_terms = sorted(
            term for term in required_requirement_terms if term not in checklist_requirements_text
        )
        if missing_terms:
            patch_coverage_failures.append(
                "patch_v1_5_coverage_report requirement_checklist missing requirement terms: "
                + ", ".join(missing_terms)
            )
        for item in requirement_checklist:
            check_id = str(item.get("check_id") or "")
            status = str(item.get("status") or "")
            if item.get("accepted") is not True:
                patch_coverage_failures.append(
                    f"patch_v1_5_coverage_report {check_id}: accepted must be true"
                )
            if status not in {"passed", "deferred_by_rollout"}:
                patch_coverage_failures.append(
                    f"patch_v1_5_coverage_report {check_id}: status cannot be {status}"
                )
            if feature_rollout_mode == "shadow_tooling" and check_id in {
                "RI15-G-G1",
                "RI15-H-G1",
            } and status != "deferred_by_rollout":
                patch_coverage_failures.append(
                    f"patch_v1_5_coverage_report {check_id}: must be deferred_by_rollout in shadow_tooling"
                )
    records.append(
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_patch_v1_5_coverage_rules",
            artifact_path="registry/report_intelligence/patch_v1_5_coverage_report.json",
            item_count=len(phase_records) + len(requirement_checklist),
            accepted=not patch_coverage_failures,
            failures=tuple(patch_coverage_failures),
        )
    )
    return tuple(records)


def build_schema_validation_report(root: str | Path = ".") -> SchemaValidationReport:
    records: list[SchemaValidationRecord] = []
    for schema_path, artifact_path, artifact_kind in JSON_SCHEMA_TARGETS:
        records.append(
            validate_json_schema_artifact(
                root=root,
                schema_path=schema_path,
                artifact_path=artifact_path,
                artifact_kind=artifact_kind,
            )
        )
    for schema_path, artifact_path, artifact_kind, allow_empty in REPORT_INTELLIGENCE_JSON_SCHEMA_TARGETS:
        records.append(
            validate_json_schema_artifact(
                root=root,
                schema_path=schema_path,
                artifact_path=artifact_path,
                artifact_kind=artifact_kind,
                allow_empty=allow_empty,
            )
        )
    for artifact_path in RULE_PACK_TARGETS:
        records.append(validate_rule_pack_schema_artifact(root, artifact_path))
    records.extend(validate_policy_schema_files(root))
    records.extend(validate_report_intelligence_semantics(root))
    return SchemaValidationReport(
        report_id="RKE-SCHEMA-VALIDATION-REPORT-20260606",
        records=tuple(records),
    )


def write_schema_validation_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_schema_validation_report(root_path)
    output_path = root_path / "registry/schemas/rke_schema_validation_report.json"
    return _write_json(
        output_path,
        {
            **asdict(report),
            "accepted": report.accepted,
            "failure_count": report.failure_count,
        },
    )
