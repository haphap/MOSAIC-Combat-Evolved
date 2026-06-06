"""Schema validation gate for RKE Phase 1 artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

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
    return True


def _validate_value(value: Any, schema: Mapping[str, Any], path: str) -> list[str]:
    failures: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _schema_type_matches(value, expected_type):
        return [f"{path}: expected {expected_type}"]
    if "const" in schema and value != schema["const"]:
        failures.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in set(schema["enum"]):
        failures.append(f"{path}: value {value!r} not in enum")
    if isinstance(value, str):
        if int(schema.get("minLength") or 0) and len(value) < int(schema["minLength"]):
            failures.append(f"{path}: below minLength")
        if "pattern" in schema and not re.search(str(schema["pattern"]), value):
            failures.append(f"{path}: pattern mismatch")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems") or 0):
            failures.append(f"{path}: below minItems")
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
    if not items:
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
    for artifact_path in RULE_PACK_TARGETS:
        records.append(validate_rule_pack_schema_artifact(root, artifact_path))
    records.extend(validate_policy_schema_files(root))
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
