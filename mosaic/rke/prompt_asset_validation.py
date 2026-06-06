"""Validation gate for rendered RKE prompt and mutation artifacts."""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .p0 import validate_target_path


@dataclass(frozen=True)
class PromptAssetValidationRecord:
    check_id: str
    artifact_paths: Sequence[str]
    accepted: bool
    failures: Sequence[str]
    details: Mapping[str, Any]


@dataclass(frozen=True)
class PromptAssetValidationReport:
    report_id: str
    records: Sequence[PromptAssetValidationRecord]

    @property
    def accepted(self) -> bool:
        return all(record.accepted for record in self.records)

    @property
    def failure_count(self) -> int:
        return sum(len(record.failures) for record in self.records)


PROMPT_METADATA_PATH = "registry/rendered_prompts/macro.central_bank.rke.json"
PROMPT_MARKDOWN_PATH = "registry/rendered_prompts/macro.central_bank.rke.md"
PROMPT_IR_PATH = "registry/prompt_ir/macro.central_bank.json"
RUNTIME_INPUT_PATH = "registry/runtime_inputs/macro.central_bank.20260605.json"
MUTATION_PATCH_PATH = "registry/mutation_patches/central_bank_parameter_update.json"
RULE_PACK_PATH = "registry/rule_packs/macro.central_bank.liquidity.v1.json"
VALIDATION_EXPERIMENT_PATH = (
    "registry/experiments/central_bank_validation_experiment_v2.json"
)
PROMPT_CHECK_REPORT_PATH = "registry/prompt_checks/prompt_asset_validation_report.json"

REQUIRED_GUARDRAILS = (
    "research_reports_are_prior_not_signal",
    "research_only_no_trade",
    "no_direct_production_promotion",
)
SECRET_OR_RAW_SOURCE_PATTERNS = (
    r"tp-[A-Za-z0-9]{12,}",
    r"sk-[A-Za-z0-9]{12,}",
    r"token" r"[-.]plan" r"[-.]cn",
    r"dashscope" r"\.aliyuncs" r"\.com",
    r"pdf\.dfcfw\.com",
    r"https?://",
    r"(?:api_key|apikey|token|access_token)\s*[:=]\s*[A-Za-z0-9_.-]{12,}",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _record(
    check_id: str,
    artifact_paths: Sequence[str],
    failures: Sequence[str],
    details: Mapping[str, Any] | None = None,
) -> PromptAssetValidationRecord:
    return PromptAssetValidationRecord(
        check_id=check_id,
        artifact_paths=tuple(artifact_paths),
        accepted=not failures,
        failures=tuple(failures),
        details=dict(details or {}),
    )


def _path_exists(root_path: Path, relative: str) -> bool:
    return (root_path / relative).is_file() and (
        root_path / relative
    ).stat().st_size > 0


def _references_existing_files(
    root_path: Path, metadata: Mapping[str, Any]
) -> list[str]:
    failures: list[str] = []
    for field in ("prompt_ir_ref", "runtime_input_ref", "rendered_prompt_path"):
        relative = str(metadata.get(field) or "")
        if not relative:
            failures.append(f"{field}: required")
        elif not _path_exists(root_path, relative):
            failures.append(f"{field}: missing or empty file {relative}")
    return failures


def _matches_allowed_path(target_path: str, allowed_paths: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(target_path, pattern) for pattern in allowed_paths)


def _matches_forbidden_path(target_path: str, forbidden_paths: Sequence[str]) -> bool:
    return any(
        target_path == forbidden or target_path.startswith(f"{forbidden}/")
        for forbidden in forbidden_paths
    )


def _leak_failures(payloads: Mapping[str, str]) -> list[str]:
    failures: list[str] = []
    for label, text in payloads.items():
        for pattern in SECRET_OR_RAW_SOURCE_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                failures.append(f"{label}: matched forbidden pattern {pattern}")
    return failures


def _parameter_value_failures(parameter: Mapping[str, Any], value: Any) -> list[str]:
    failures: list[str] = []
    parameter_type = str(parameter.get("type") or "")
    if parameter_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            failures.append("new_value: integer parameter requires int")
    elif parameter_type == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            failures.append("new_value: float parameter requires number")
    elif parameter_type == "string":
        if not isinstance(value, str):
            failures.append("new_value: string parameter requires str")
    elif parameter_type == "boolean":
        if not isinstance(value, bool):
            failures.append("new_value: boolean parameter requires bool")
    else:
        failures.append("parameter.type: unsupported or missing")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        min_value = parameter.get("min")
        max_value = parameter.get("max")
        if min_value is not None and value < min_value:
            failures.append("new_value: value below min")
        if max_value is not None and value > max_value:
            failures.append("new_value: value above max")
    return failures


def _target_parameter(
    rule_pack: Mapping[str, Any], target_path: str
) -> tuple[Mapping[str, Any], list[str]]:
    parsed = validate_target_path(target_path)
    failures = [f"target_path: {reason}" for reason in parsed.get("reasons", ())]
    if not parsed.get("valid"):
        return {}, failures
    if rule_pack.get("rule_pack_id") != parsed.get("rule_pack_id"):
        failures.append("target_path: rule_pack_id does not match rule pack")
        return {}, failures
    rules = rule_pack.get("rules")
    if not isinstance(rules, Mapping):
        return {}, failures + ["rule_pack.rules: required object"]
    rule = rules.get(str(parsed.get("rule_id")))
    if not isinstance(rule, Mapping):
        return {}, failures + ["target_path: rule not found in rule pack"]
    parameters = rule.get("learnable_parameters")
    if not isinstance(parameters, Mapping):
        return {}, failures + ["rule.learnable_parameters: required object"]
    parameter = parameters.get(str(parsed.get("parameter_name")))
    if not isinstance(parameter, Mapping):
        return {}, failures + ["target_path: parameter not found in rule pack"]
    return parameter, failures


def _rollback_condition_failures(rollback: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if rollback.get("metric") != "live_net_alpha_after_cost_20d":
        failures.append(
            "rollback_condition.metric: must be live_net_alpha_after_cost_20d"
        )
    try:
        float(rollback.get("delta_lt"))
    except (TypeError, ValueError):
        failures.append("rollback_condition.delta_lt: required numeric threshold")
    try:
        window = int(rollback.get("window_trading_days"))
    except (TypeError, ValueError):
        failures.append(
            "rollback_condition.window_trading_days: required positive integer"
        )
    else:
        if window <= 0:
            failures.append(
                "rollback_condition.window_trading_days: required positive integer"
            )
    return failures


def build_prompt_asset_validation_report(
    root: str | Path = ".",
) -> PromptAssetValidationReport:
    root_path = Path(root)
    required_paths = (
        PROMPT_METADATA_PATH,
        PROMPT_MARKDOWN_PATH,
        PROMPT_IR_PATH,
        RUNTIME_INPUT_PATH,
        MUTATION_PATCH_PATH,
        RULE_PACK_PATH,
        VALIDATION_EXPERIMENT_PATH,
    )
    missing = [
        relative for relative in required_paths if not _path_exists(root_path, relative)
    ]
    records: list[PromptAssetValidationRecord] = [
        _record(
            "PROMPT-ASSET-FILES",
            required_paths,
            tuple(f"{relative}: missing or empty" for relative in missing),
            {"required_count": len(required_paths)},
        )
    ]
    if missing:
        return PromptAssetValidationReport(
            report_id="RKE-PROMPT-ASSET-VALIDATION-REPORT-20260606",
            records=tuple(records),
        )

    metadata = _read_json(root_path / PROMPT_METADATA_PATH)
    prompt_ir = _read_json(root_path / PROMPT_IR_PATH)
    runtime_input = _read_json(root_path / RUNTIME_INPUT_PATH)
    mutation_patch = _read_json(root_path / MUTATION_PATCH_PATH)
    rule_pack = _read_json(root_path / RULE_PACK_PATH)
    experiment = _read_json(root_path / VALIDATION_EXPERIMENT_PATH)
    rendered_prompt = (root_path / PROMPT_MARKDOWN_PATH).read_text(encoding="utf-8")

    metadata_failures = _references_existing_files(root_path, metadata)
    for field in (
        "agent_id",
        "prompt_version",
        "output_schema_ref",
        "progress_event_schema_ref",
        "handoff_schema_ref",
    ):
        if metadata.get(field) != prompt_ir.get(field):
            metadata_failures.append(f"{field}: metadata does not match prompt IR")
    if metadata.get("agent_id") != runtime_input.get("agent_id"):
        metadata_failures.append("agent_id: metadata does not match runtime input")
    if tuple(metadata.get("guardrails") or ()) != tuple(
        prompt_ir.get("guardrails") or ()
    ):
        metadata_failures.append("guardrails: metadata does not match prompt IR")
    records.append(
        _record(
            "PROMPT-METADATA-REFS",
            (
                PROMPT_METADATA_PATH,
                PROMPT_IR_PATH,
                RUNTIME_INPUT_PATH,
                PROMPT_MARKDOWN_PATH,
            ),
            metadata_failures,
            {
                "agent_id": metadata.get("agent_id"),
                "prompt_version": metadata.get("prompt_version"),
            },
        )
    )

    markdown_failures: list[str] = []
    for marker in (
        "## Runtime Evidence",
        "## Active Research Rules",
        "## Output Schema",
        "## Guardrails",
    ):
        if marker not in rendered_prompt:
            markdown_failures.append(f"{marker}: missing")
    for schema_field in (
        "output_schema_ref",
        "progress_event_schema_ref",
        "handoff_schema_ref",
    ):
        expected = f"{schema_field}: {prompt_ir.get(schema_field)}"
        if expected not in rendered_prompt:
            markdown_failures.append(f"{schema_field}: missing rendered schema ref")
    for guardrail in REQUIRED_GUARDRAILS:
        if guardrail not in rendered_prompt:
            markdown_failures.append(f"guardrail {guardrail}: missing")
    records.append(
        _record(
            "PROMPT-MARKDOWN-CONTRACT",
            (PROMPT_MARKDOWN_PATH,),
            markdown_failures,
            {"required_guardrails": REQUIRED_GUARDRAILS},
        )
    )

    runtime_failures: list[str] = []
    active_rule_packs = tuple(runtime_input.get("active_rule_packs") or ())
    prompt_rule_packs = tuple(prompt_ir.get("research_rule_pack_refs") or ())
    if active_rule_packs != prompt_rule_packs:
        runtime_failures.append(
            "active_rule_packs: runtime input does not match prompt IR"
        )
    tool_outputs = tuple(runtime_input.get("tool_outputs_normalized") or ())
    if not tool_outputs:
        runtime_failures.append("tool_outputs_normalized: required non-empty evidence")
    for idx, tool_output in enumerate(tool_outputs):
        for field in ("tool_name", "metric", "as_of", "freshness_days"):
            if field not in tool_output:
                runtime_failures.append(
                    f"tool_outputs_normalized[{idx}].{field}: required"
                )
    records.append(
        _record(
            "PROMPT-RUNTIME-EVIDENCE",
            (RUNTIME_INPUT_PATH,),
            runtime_failures,
            {
                "tool_output_count": len(tool_outputs),
                "active_rule_packs": active_rule_packs,
            },
        )
    )

    mutation = dict(mutation_patch.get("mutation") or {})
    validation = dict(mutation_patch.get("validation") or {})
    evolution_targets = dict(prompt_ir.get("evolution_targets") or {})
    allowed_paths = tuple(evolution_targets.get("allowed_paths") or ())
    forbidden_paths = tuple(evolution_targets.get("forbidden_paths") or ())
    target_path = str(mutation.get("target_path") or "")
    mutation_failures: list[str] = []
    if not target_path.startswith("/"):
        mutation_failures.append("target_path: must be absolute")
    parameter, parameter_failures = _target_parameter(rule_pack, target_path)
    mutation_failures.extend(parameter_failures)
    if not _matches_allowed_path(target_path, allowed_paths):
        mutation_failures.append("target_path: not covered by allowed evolution paths")
    if _matches_forbidden_path(target_path, forbidden_paths):
        mutation_failures.append("target_path: matches forbidden evolution path")
    if parameter:
        if mutation.get("old_value") != parameter.get("value"):
            mutation_failures.append(
                "old_value: does not match current rule-pack parameter"
            )
        mutation_failures.extend(
            _parameter_value_failures(parameter, mutation.get("new_value"))
        )
    if mutation.get("source_experiment_id") != experiment.get("experiment_id"):
        mutation_failures.append(
            "source_experiment_id: must match validation experiment"
        )
    if target_path not in tuple(experiment.get("parameter_paths") or ()):
        mutation_failures.append(
            "target_path: must be registered in validation experiment parameter_paths"
        )
    expected_effect = dict(mutation.get("expected_effect") or {})
    acceptance_rule = dict(experiment.get("acceptance_rule") or {})
    if expected_effect.get("primary_metric") != acceptance_rule.get("primary_metric"):
        mutation_failures.append(
            "expected_effect.primary_metric: must match validation experiment"
        )
    if expected_effect.get("direction") not in {"increase", "decrease", "neutral"}:
        mutation_failures.append("expected_effect.direction: unsupported or missing")
    rollback_condition = mutation.get("rollback_condition")
    if not isinstance(rollback_condition, Mapping):
        mutation_failures.append("rollback_condition: required object")
    else:
        mutation_failures.extend(_rollback_condition_failures(rollback_condition))
    if not str(mutation.get("risk") or "").strip():
        mutation_failures.append("risk: required")
    if validation.get("accepted") is not True:
        mutation_failures.append(
            "validation.accepted: must be true before paper trading"
        )
    if mutation_patch.get("promotion_state") != "paper_trading":
        mutation_failures.append("promotion_state: must remain paper_trading")
    if mutation_patch.get("production_allowed") is not False:
        mutation_failures.append(
            "production_allowed: must be false without production gates"
        )
    records.append(
        _record(
            "PROMPT-MUTATION-GATE",
            (
                MUTATION_PATCH_PATH,
                PROMPT_IR_PATH,
                RULE_PACK_PATH,
                VALIDATION_EXPERIMENT_PATH,
            ),
            mutation_failures,
            {
                "mutation_id": mutation.get("mutation_id"),
                "target_path": target_path,
                "source_experiment_id": mutation.get("source_experiment_id"),
                "current_value": parameter.get("value") if parameter else None,
            },
        )
    )

    leak_payloads = {
        "rendered_prompt": rendered_prompt,
        "rendered_metadata": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        "runtime_input": json.dumps(runtime_input, ensure_ascii=False, sort_keys=True),
        "mutation_patch": json.dumps(
            mutation_patch, ensure_ascii=False, sort_keys=True
        ),
    }
    records.append(
        _record(
            "PROMPT-LEAK-GUARD",
            (
                PROMPT_MARKDOWN_PATH,
                PROMPT_METADATA_PATH,
                RUNTIME_INPUT_PATH,
                MUTATION_PATCH_PATH,
            ),
            _leak_failures(leak_payloads),
            {"payload_count": len(leak_payloads)},
        )
    )

    return PromptAssetValidationReport(
        report_id="RKE-PROMPT-ASSET-VALIDATION-REPORT-20260606",
        records=tuple(records),
    )


def write_prompt_asset_validation_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_prompt_asset_validation_report(root_path)
    return _write_json(
        root_path / PROMPT_CHECK_REPORT_PATH,
        {
            **asdict(report),
            "accepted": report.accepted,
            "failure_count": report.failure_count,
        },
    )
