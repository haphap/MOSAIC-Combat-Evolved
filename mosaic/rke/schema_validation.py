"""Schema validation gate for RKE Phase 1 artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .required_data import normalize_required_data_items


SUPPORTED_JSON_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "additionalProperties",
        "allOf",
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
    if allow_empty and not artifact_file.exists():
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
    if not items and not allow_empty:
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
        False,
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
        False,
    ),
    (
        "schemas/report_intelligence_viewpoint_performance_profile.schema.json",
        "registry/report_intelligence/viewpoint_performance_profiles.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_method_performance_profile.schema.json",
        "registry/report_intelligence/method_performance_profiles.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_metric_candidate.schema.json",
        "registry/report_intelligence/metric_candidates.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_method_pattern.schema.json",
        "registry/report_intelligence/method_patterns.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_tool_coverage_match.schema.json",
        "registry/report_intelligence/tool_coverage_matches.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_tool_gap.schema.json",
        "registry/report_intelligence/tool_gaps.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_data_acquisition_proposal.schema.json",
        "registry/report_intelligence/data_acquisition_proposals.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_tool_design_proposal.schema.json",
        "registry/report_intelligence/tool_design_proposals.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_analysis_recipe.schema.json",
        "registry/report_intelligence/analysis_recipes.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_recipe_paper_trading_run.schema.json",
        "registry/report_intelligence/recipe_paper_trading_runs.jsonl",
        "jsonl",
        False,
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
        False,
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
        False,
    ),
    (
        "schemas/report_intelligence_evolution_refresh_history.schema.json",
        "registry/report_intelligence/audit_refresh_history.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_evolution_refresh_history.schema.json",
        "registry/report_intelligence/gap_distribution_history.jsonl",
        "jsonl",
        False,
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
        False,
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
        False,
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


def _has_mapping_gap(row: Mapping[str, Any]) -> bool:
    target = row.get("target")
    benchmark = row.get("benchmark")
    horizon = row.get("horizon")
    direction = str(row.get("direction") or "unknown")
    target_missing = not isinstance(target, Mapping) or not str(
        target.get("target_id") or target.get("target_name") or ""
    ).strip()
    benchmark_missing = not isinstance(benchmark, Mapping) or not benchmark
    horizon_missing = not isinstance(horizon, Mapping) or not horizon
    direction_missing = direction in {"", "unknown", "ambiguous"}
    return target_missing or benchmark_missing or horizon_missing or direction_missing


STOCK_PROXY_REQUIRED_LABEL_FIELDS = (
    "proxy_symbol",
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
    "source_horizon_bucket",
    "claim_window_alignment",
    "evaluation_policy",
    "target_resolution_source",
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
    "source_horizon_bucket",
    "claim_window_alignment",
    "evaluation_policy",
)

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

STOCK_PROXY_SURVIVORSHIP_UNVERIFIED_CHECK = "survivorship_unverified_qlib_cn_data"
STOCK_PROXY_SURVIVORSHIP_AUDITED_CHECK = "delisted_inclusive_universe_audit_passed"
STOCK_PROXY_SURVIVORSHIP_CHECKS = {
    STOCK_PROXY_SURVIVORSHIP_UNVERIFIED_CHECK,
    STOCK_PROXY_SURVIVORSHIP_AUDITED_CHECK,
}
STOCK_PROXY_TRADABILITY_CHECK = "positive_volume_and_limit_lock_screen"
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


def _validate_proxy_outcome_label_contract(row: Mapping[str, Any], row_label: str) -> list[str]:
    label_type = str(row.get("label_type") or "")
    if label_type not in {"stock_price_proxy", "industry_etf_proxy"}:
        return [
            f"{row_label}.label_type: must be stock_price_proxy or industry_etf_proxy"
        ]
    failures = _required_field_failures(
        row,
        row_label=row_label,
        required_fields=(
            STOCK_PROXY_REQUIRED_LABEL_FIELDS
            if label_type == "stock_price_proxy"
            else INDUSTRY_PROXY_REQUIRED_LABEL_FIELDS
        ),
    )
    if row.get("llm_outcome_labeling_allowed") is not False:
        failures.append(f"{row_label}.llm_outcome_labeling_allowed: must be false")
    if row.get("performance_value_basis") != "directional_after_cost_return":
        failures.append(
            f"{row_label}.performance_value_basis: must be directional_after_cost_return"
        )
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
        if row.get("outcome_label_source") != "pit_stock_price_window":
            failures.append(
                f"{row_label}.outcome_label_source: must be pit_stock_price_window"
            )
        if row.get("benchmark_alignment") != "date_key_cross_qlib_dir":
            failures.append(
                f"{row_label}.benchmark_alignment: must be date_key_cross_qlib_dir"
            )
        if str(row.get("target_resolution_source") or "") not in {
            "metadata_and_llm_target_id",
            "metadata_ts_code",
            "llm_target_id",
        }:
            failures.append(
                f"{row_label}.target_resolution_source: unsupported stock target resolution"
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
        if row.get("outcome_label_source") != "pit_industry_etf_price_window":
            failures.append(
                f"{row_label}.outcome_label_source: must be pit_industry_etf_price_window"
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
        if availability.get("mapping_count") != len(mapping_rows):
            failures.append(
                "industry_etf_proxy_pit_availability.mapping_count mismatch"
            )
        pit_available_count = sum(
            1 for record in availability_records if record.get("pit_available") is True
        )
        if availability.get("pit_available_mapping_count") != pit_available_count:
            failures.append(
                "industry_etf_proxy_pit_availability.pit_available_mapping_count mismatch"
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


def _validate_recipe_paper_trading_contract(
    root_path: Path,
) -> tuple[int, list[str]]:
    run_rows, run_failures = _load_mapping_jsonl(
        root_path,
        "registry/report_intelligence/recipe_paper_trading_runs.jsonl",
    )
    confidence_rows, confidence_failures = _load_mapping_jsonl(
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
        if not recipe_id:
            failures.append(f"{row_label}.analysis_recipe_id: required")
        elif recipe_id in runs_by_recipe_id:
            failures.append(f"{row_label}.analysis_recipe_id: duplicate {recipe_id}")
        else:
            runs_by_recipe_id[recipe_id] = row

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

    if summary:
        expected_count_fields = {
            "recipe_count": len(run_rows),
            "paper_trading_run_count": len(run_rows),
            "validation_pass_count": len(passed_recipe_ids),
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
        if _string_items(summary.get("passed_recipe_ids")) != sorted(
            passed_recipe_ids
        ):
            failures.append("recipe_paper_trading_summary.passed_recipe_ids mismatch")
        if _string_items(summary.get("blocked_recipe_ids")) != sorted(
            blocked_recipe_ids
        ):
            failures.append("recipe_paper_trading_summary.blocked_recipe_ids mismatch")
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
    regime_fragile_recipe_ids: list[str] = []
    for index, row in enumerate(confidence_rows, 1):
        row_label = f"confidence_impact_observations row {index}"
        for field in CONFIDENCE_IMPACT_REQUIRED_OBSERVATION_FIELDS:
            if field not in row:
                failures.append(f"{row_label}.{field}: required")
        recipe_id = str(row.get("recipe_id") or "").strip()
        if not recipe_id:
            failures.append(f"{row_label}.recipe_id: required")
            continue
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

    missing_confidence_ids = sorted(
        set(runs_by_recipe_id) - set(confidence_by_recipe_id)
    )
    if missing_confidence_ids:
        failures.append(
            "confidence_impact_observations missing recipe_ids: "
            + ", ".join(missing_confidence_ids[:20])
        )
    if monitor:
        expected_monitor_counts = {
            "recipe_count": len(run_rows),
            "observation_count": len(confidence_rows),
            "paper_trading_validated_recipe_count": len(passed_recipe_ids),
            "blocked_recipe_count": len(blocked_recipe_ids),
        }
        for field, expected in expected_monitor_counts.items():
            if monitor.get(field) != expected:
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
        expected_monitor_ids = {
            "tracked_recipe_ids": sorted(set(confidence_tracked_recipe_ids)),
            "reduce_confidence_impact_recipe_ids": sorted(
                set(reduce_confidence_recipe_ids)
            ),
            "freeze_recipe_ids": sorted(set(freeze_recipe_ids)),
            "retire_recipe_ids": sorted(set(retire_recipe_ids)),
            "alpha_decay_recipe_ids": sorted(set(alpha_decay_recipe_ids)),
            "cost_decay_recipe_ids": sorted(set(cost_decay_recipe_ids)),
            "regime_fragile_recipe_ids": sorted(set(regime_fragile_recipe_ids)),
        }
        for field, expected_ids in expected_monitor_ids.items():
            if _string_items(monitor.get(field)) != expected_ids:
                failures.append(f"confidence_impact_monitor.{field} mismatch")
        observed_manual_review_ids = set(_string_items(monitor.get("manual_review_recipe_ids")))
        if not set(manual_review_recipe_ids).issubset(observed_manual_review_ids):
            failures.append(
                "confidence_impact_monitor.manual_review_recipe_ids missing action recipes"
            )
        observed_calibration_ids = set(
            _string_items(monitor.get("calibration_drift_recipe_ids"))
        )
        if not set(calibration_drift_recipe_ids).issubset(observed_calibration_ids):
            failures.append(
                "confidence_impact_monitor.calibration_drift_recipe_ids missing drift recipes"
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
    monitor_rows, monitor_failures = _load_mapping_jsonl(
        root_path,
        "registry/report_intelligence/monitor_refresh_history.jsonl",
    )
    audit_rows, audit_failures = _load_mapping_jsonl(
        root_path,
        "registry/report_intelligence/audit_refresh_history.jsonl",
    )
    gap_rows, gap_failures = _load_mapping_jsonl(
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

    checks = gate.get("checks")
    aggregate_blockers: list[str] = []
    observed_check_ids: list[str] = []
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
    observed_check_id_set = set(observed_check_ids)
    missing_check_ids = sorted(expected_check_ids - observed_check_id_set)
    extra_check_ids = sorted(observed_check_id_set - expected_check_ids)
    if missing_check_ids:
        failures.append(
            "evolution_readiness_gate.checks missing check_ids: "
            + ", ".join(missing_check_ids)
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

    return len(checks), failures


def validate_report_intelligence_semantics(
    root: str | Path,
) -> tuple[SchemaValidationRecord, ...]:
    root_path = Path(root)
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
        span_ids = row.get("source_span_ids")
        has_spans = isinstance(span_ids, list) and any(
            str(item).strip() for item in span_ids
        )
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
        span_ids = row.get("source_span_ids")
        has_spans = isinstance(span_ids, list) and any(
            str(item).strip() for item in span_ids
        )
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
        if not isinstance(coverage_targets, Mapping):
            markdown_coverage_failures.append(
                "markdown_coverage_summary.coverage_targets: expected object"
            )
        else:
            for count_field, target_field, blocker in (
                (
                    "selected_report_count",
                    "selected_report_count_min",
                    "selected_report_count_below_p9_target",
                ),
                (
                    "markdown_ready_count",
                    "markdown_ready_count_min",
                    "markdown_ready_count_below_p9_target",
                ),
                (
                    "markdown_quality_pass_count",
                    "markdown_quality_pass_count_min",
                    "markdown_quality_pass_count_below_p9_target",
                ),
                (
                    "llm_extraction_processed_count",
                    "llm_extraction_processed_count_min",
                    "llm_extraction_processed_count_below_p9_target",
                ),
                (
                    "industry_report_count",
                    "industry_report_count_min",
                    "industry_report_count_below_p9_target",
                ),
                (
                    "stock_report_count",
                    "stock_report_count_min",
                    "stock_report_count_below_p9_target",
                ),
                (
                    "stock_outcome_120d_ready_report_count",
                    "stock_outcome_120d_ready_report_count_min",
                    "stock_outcome_120d_ready_count_below_p9_target",
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
                if count < target and blocker not in coverage_blockers:
                    markdown_coverage_failures.append(
                        "markdown_coverage_summary.coverage_gate_blockers must "
                        f"include {blocker}"
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
        if (
            markdown_coverage.get("coverage_gate_status") == "passed"
            and coverage_blockers
        ):
            markdown_coverage_failures.append(
                "markdown_coverage_summary.coverage_gate_status passed with blockers"
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

    ledger_rows, ledger_failures = _load_mapping_jsonl(
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
    ready_count = 0
    standard_blocked_count = 0
    unlabelable_count = 0
    proxy_label_ready_ids = {
        str(claim_id)
        for claim_id in (
            readiness_report.get("proxy_label_ready_forecast_claim_ids", [])
            if readiness_report
            else []
        )
        if str(claim_id).strip()
    }
    proxy_label_pending_ids = {
        str(claim_id)
        for claim_id in (
            readiness_report.get("proxy_label_pending_forecast_claim_ids", [])
            if readiness_report
            else []
        )
        if str(claim_id).strip()
    }
    for index, row in enumerate(ledger_rows, 1):
        row_label = f"report_forecast_ledger row {index}"
        if row.get("immutable") is not True:
            readiness_failures.append(f"{row_label}: immutable must be true")
        if not forecast_rows_present:
            continue
        claim_id = str(row.get("forecast_claim_id") or "")
        claim = forecasts_by_id.get(claim_id)
        if claim is None:
            readiness_failures.append(f"{row_label}: forecast_claim_id not found")
            continue
        test_status = str(row.get("test_status") or "")
        ready = (
            str(claim.get("forecast_testability") or "") == "testable"
            and not _has_mapping_gap(claim)
        )
        if ready:
            ready_count += 1
        else:
            standard_blocked_count += 1
            if (
                claim_id not in proxy_label_ready_ids
                and claim_id not in proxy_label_pending_ids
            ):
                unlabelable_count += 1
        if ready and test_status != "ready_for_outcome_labeling":
            readiness_failures.append(
                f"{row_label}: testable claim must be ready_for_outcome_labeling"
            )
        if not ready and test_status == "ready_for_outcome_labeling":
            readiness_failures.append(
                f"{row_label}: unmapped or non-testable claim cannot be outcome-ready"
            )
    if readiness_report and forecast_rows_present:
        if readiness_report.get("forecast_ledger_count") != len(ledger_rows):
            readiness_failures.append(
                "outcome_labeling_readiness forecast_ledger_count mismatch"
            )
        if readiness_report.get("forecast_claim_count") != len(forecast_rows):
            readiness_failures.append(
                "outcome_labeling_readiness forecast_claim_count mismatch"
            )
        if readiness_report.get("ready_for_outcome_labeling_count") != ready_count:
            readiness_failures.append(
                "outcome_labeling_readiness ready_for_outcome_labeling_count mismatch"
            )
        if readiness_report.get("standard_blocked_count") != standard_blocked_count:
            readiness_failures.append(
                "outcome_labeling_readiness standard_blocked_count mismatch"
            )
        if readiness_report.get("blocked_count") != unlabelable_count:
            readiness_failures.append("outcome_labeling_readiness blocked_count mismatch")
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

    method_rows, method_failures = _load_mapping_jsonl(
        root_path,
        "registry/report_intelligence/method_patterns.jsonl",
    )
    recipe_rows, recipe_failures = _load_mapping_jsonl(
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
    gap_observation_rows, gap_observation_failures = _load_mapping_jsonl(
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
        if alpha_decay.get("paper_trading_recipe_count") != paper_count:
            monitoring_failures.append(
                "alpha_decay_monitoring paper_trading_recipe_count mismatch"
            )
        if alpha_decay.get("limited_production_recipe_count") != limited_count:
            monitoring_failures.append(
                "alpha_decay_monitoring limited_production_recipe_count mismatch"
            )
        if alpha_decay.get("production_recipe_count") != production_count:
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
    tool_gap_rows, tool_gap_failures = _load_mapping_jsonl(
        root_path,
        "registry/report_intelligence/tool_gaps.jsonl",
    )
    data_proposal_rows, data_proposal_failures = _load_mapping_jsonl(
        root_path,
        "registry/report_intelligence/data_acquisition_proposals.jsonl",
    )
    tool_proposal_rows, tool_proposal_failures = _load_mapping_jsonl(
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
            rows, load_failures = _load_mapping_jsonl(root_path, artifact_path)
            patch_coverage_failures.extend(load_failures)
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
