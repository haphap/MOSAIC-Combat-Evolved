"""Schema validation gate for RKE Phase 1 artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


SUPPORTED_JSON_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "additionalProperties",
        "const",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
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
    schema, schema_failures = _read_mapping_json(_schema_file(root_path, schema_path), schema_path)
    failures: list[str] = list(schema_failures)
    if artifact_kind == "jsonl":
        items, item_failures = _load_jsonl_values(root_path / artifact_path, artifact_path)
    elif artifact_kind == "json":
        item, item_failures = _read_json_value(root_path / artifact_path, artifact_path)
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
        False,
    ),
    (
        "schemas/report_intelligence_forecast_claim.schema.json",
        "registry/report_intelligence/forecast_claims.jsonl",
        "jsonl",
        False,
    ),
    (
        "schemas/report_intelligence_analytical_footprint.schema.json",
        "registry/report_intelligence/analytical_footprints.jsonl",
        "jsonl",
        False,
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
        "schemas/report_intelligence_weighted_research_context.schema.json",
        "registry/report_intelligence/weighted_research_contexts.jsonl",
        "jsonl",
        False,
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


def validate_report_intelligence_semantics(
    root: str | Path,
) -> tuple[SchemaValidationRecord, ...]:
    root_path = Path(root)
    records: list[SchemaValidationRecord] = []

    forecast_rows, forecast_failures = _load_mapping_jsonl(
        root_path,
        "registry/report_intelligence/forecast_claims.jsonl",
    )
    footprint_rows, footprint_failures = _load_mapping_jsonl(
        root_path,
        "registry/report_intelligence/analytical_footprints.jsonl",
    )
    provenance_failures = [*forecast_failures, *footprint_failures]
    for index, row in enumerate(forecast_rows, 1):
        row_label = f"forecast_claims row {index}"
        span_ids = row.get("source_span_ids")
        has_spans = isinstance(span_ids, list) and any(str(item).strip() for item in span_ids)
        if str(row.get("claim_provenance") or "") == "source_grounded" and not has_spans:
            provenance_failures.append(f"{row_label}: source_grounded claim must cite source_span_ids")
        for mode_index, mode in enumerate(row.get("failure_modes") or (), 1):
            if not isinstance(mode, Mapping):
                provenance_failures.append(
                    f"{row_label}.failure_modes[{mode_index}]: expected object with provenance"
                )
                continue
            if not str(mode.get("text") or "").strip():
                provenance_failures.append(f"{row_label}.failure_modes[{mode_index}].text: required")
            if not str(mode.get("provenance") or "").strip():
                provenance_failures.append(
                    f"{row_label}.failure_modes[{mode_index}].provenance: required"
                )
            if mode.get("provenance") == "source_grounded" and not has_spans:
                provenance_failures.append(
                    f"{row_label}.failure_modes[{mode_index}]: source_grounded requires claim spans"
                )
        if _has_mapping_gap(row) and str(row.get("forecast_testability") or "") == "testable":
            provenance_failures.append(
                f"{row_label}: forecast with target/benchmark/direction/horizon gap cannot be testable"
            )
    for index, row in enumerate(footprint_rows, 1):
        row_label = f"analytical_footprints row {index}"
        extraction_type = str(row.get("extraction_type") or "")
        span_ids = row.get("source_span_ids")
        has_spans = isinstance(span_ids, list) and any(str(item).strip() for item in span_ids)
        if extraction_type in {"source_grounded", "mixed"} and not has_spans:
            provenance_failures.append(
                f"{row_label}: source-grounded analytical footprint must cite source_span_ids"
            )
        for mention_index, mention in enumerate(row.get("indicator_mentions") or (), 1):
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
    if len(forecasts_by_id) != len(forecast_rows):
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
    for index, row in enumerate(ledger_rows, 1):
        row_label = f"report_forecast_ledger row {index}"
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
            if claim_id not in proxy_label_ready_ids:
                unlabelable_count += 1
        if ready and test_status != "ready_for_outcome_labeling":
            readiness_failures.append(f"{row_label}: testable claim must be ready_for_outcome_labeling")
        if not ready and test_status == "ready_for_outcome_labeling":
            readiness_failures.append(f"{row_label}: unmapped or non-testable claim cannot be outcome-ready")
        if row.get("immutable") is not True:
            readiness_failures.append(f"{row_label}: immutable must be true")
    if readiness_report:
        if readiness_report.get("forecast_claim_count") != len(forecast_rows):
            readiness_failures.append("outcome_labeling_readiness forecast_claim_count mismatch")
        if readiness_report.get("forecast_ledger_count") != len(ledger_rows):
            readiness_failures.append("outcome_labeling_readiness forecast_ledger_count mismatch")
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
    context_rows, context_failures = _load_mapping_jsonl(
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
    phase_records = []
    requirement_checklist = []
    if patch_coverage_report:
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
