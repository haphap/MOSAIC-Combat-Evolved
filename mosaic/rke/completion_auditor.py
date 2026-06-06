"""Dynamic completion audit for the RKE master plan."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .audit_viewer import build_audit_trace_view
from .central_bank_mvp import CompletionAudit, CompletionCriterion
from .completion_acceptance import final_acceptance_metadata
from .compliance import apply_source_license_reviews, evaluate_source_license
from .governance import ProductionPatch, default_evolution_targets, validate_patch
from .p0 import LearnableParameter
from .phase_minus1 import evaluate_gold_set_reviews
from .runtime import (
    EvidenceLedgerItem,
    ProgressEvent,
    RuntimeAgentOutput,
    RuntimeInference,
    RuntimeRecommendation,
    check_runtime_output,
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _optional_mapping(path: Path, label: str) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, ""
    try:
        payload = _read_json(path)
    except json.JSONDecodeError as exc:
        return None, f"{label} must contain valid JSON: {exc.msg}"
    if isinstance(payload, Mapping):
        return dict(payload), ""
    return None, f"{label} must be object"


def _mapping_field(
    payload: Mapping[str, Any] | None,
    field: str,
    label: str,
) -> tuple[dict[str, Any], str]:
    if not payload:
        return {}, ""
    value = payload.get(field)
    if value is None:
        return {}, ""
    if isinstance(value, Mapping):
        return dict(value), ""
    return {}, f"{label} must be object"


def _sequence_field(
    payload: Mapping[str, Any] | None,
    field: str,
    label: str,
) -> tuple[list[Any], str]:
    if not payload:
        return [], ""
    value = payload.get(field)
    if value is None:
        return [], ""
    if isinstance(value, list | tuple):
        return list(value), ""
    return [], f"{label} must be list"


def _optional_jsonl(path: Path, label: str) -> tuple[list[Any], str]:
    if not path.exists():
        return [], ""
    rows: list[Any] = []
    with path.open("r", encoding="utf-8") as fh:
        for index, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                return [], f"{label} row {index} must contain valid JSON: {exc.msg}"
    return rows, ""


def _float_field(
    payload: Mapping[str, Any], field: str, label: str
) -> tuple[float | None, str]:
    value = payload.get(field)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f"{label}.{field} must be numeric"
    if number < 0.0 or number > 1.0:
        return None, f"{label}.{field} must be between 0 and 1"
    return number, ""


def _split_mapping_rows(
    rows: list[Any],
) -> tuple[list[Mapping[str, Any]], tuple[int, ...]]:
    valid: list[Mapping[str, Any]] = []
    invalid: list[int] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid.append(row)
        else:
            invalid.append(index)
    return valid, tuple(invalid)


_CONFIDENCE_COMPONENTS = (
    "data_confidence",
    "research_confidence",
    "empirical_validation_confidence",
    "regime_match_confidence",
)


def _nearly_equal(left: float, right: float, *, tolerance: float = 1e-9) -> bool:
    return abs(left - right) <= tolerance


def _confidence_policy_gate(
    root: Path,
    runtime_output: Mapping[str, Any] | None,
    runtime_output_error: str = "",
) -> tuple[bool, str, str]:
    failures: list[str] = []
    schema_path = root / "schemas/confidence_policy.schema.yaml"
    doc_path = root / "docs/confidence_policy.md"
    if not schema_path.exists():
        failures.append("confidence policy schema missing")
    else:
        schema_text = schema_path.read_text(encoding="utf-8")
        for marker in (
            "safe_default_function:",
            "research_only_without_current_data:",
            "final_confidence_max: 0.50",
        ):
            if marker not in schema_text:
                failures.append(f"confidence policy schema missing {marker}")
    if not doc_path.exists():
        failures.append("confidence policy doc missing")
    else:
        doc_text = doc_path.read_text(encoding="utf-8")
        for marker in (
            "final_confidence = min(pre_cap_confidence, confidence_cap)",
            "Research-Only Rule",
        ):
            if marker not in doc_text:
                failures.append(f"confidence policy doc missing {marker}")

    if runtime_output_error:
        failures.append(runtime_output_error)
    if not runtime_output:
        failures.append("runtime output missing")
        return False, "confidence policy runtime trace missing", "; ".join(failures)

    components, components_error = _mapping_field(
        runtime_output,
        "confidence_components",
        "confidence_components",
    )
    trace, trace_error = _mapping_field(
        runtime_output,
        "confidence_policy_trace",
        "confidence_policy_trace",
    )
    failures.extend(error for error in (components_error, trace_error) if error)
    if not trace:
        failures.append("confidence_policy_trace missing")
        return False, "confidence policy runtime trace missing", "; ".join(failures)
    if trace.get("policy_ref") != "confidence_policy.v1":
        failures.append(
            "confidence_policy_trace.policy_ref must be confidence_policy.v1"
        )
    if trace.get("safe_default_function") != "min_components_then_cap":
        failures.append(
            "confidence_policy_trace.safe_default_function must be min_components_then_cap"
        )
    if tuple(trace.get("component_order") or ()) != _CONFIDENCE_COMPONENTS:
        failures.append(
            "confidence_policy_trace.component_order must match confidence policy components"
        )

    parsed_components: dict[str, float] = {}
    for component in _CONFIDENCE_COMPONENTS:
        value, error = _float_field(components, component, "confidence_components")
        if error:
            failures.append(error)
        elif value is not None:
            parsed_components[component] = value
    if len(parsed_components) != len(_CONFIDENCE_COMPONENTS):
        return False, "confidence policy runtime trace incomplete", "; ".join(failures)

    current_data_confirmed = bool(trace.get("current_data_confirmed"))
    data_confidence = parsed_components["data_confidence"]
    if not current_data_confirmed:
        data_confidence = min(data_confidence, 0.50)
    expected_pre_cap = min(
        data_confidence,
        parsed_components["research_confidence"],
        parsed_components["empirical_validation_confidence"],
        parsed_components["regime_match_confidence"],
    )
    pre_cap, pre_cap_error = _float_field(
        trace, "pre_cap_confidence", "confidence_policy_trace"
    )
    cap, cap_error = _float_field(trace, "confidence_cap", "confidence_policy_trace")
    final, final_error = _float_field(
        trace, "final_confidence", "confidence_policy_trace"
    )
    failures.extend(error for error in (pre_cap_error, cap_error, final_error) if error)
    if pre_cap is not None and not _nearly_equal(pre_cap, expected_pre_cap):
        failures.append(
            "confidence_policy_trace.pre_cap_confidence must equal min confidence component"
        )
    if cap is not None and final is not None:
        expected_final = min(expected_pre_cap, cap)
        if not _nearly_equal(final, expected_final):
            failures.append(
                "confidence_policy_trace.final_confidence must equal min(pre_cap, confidence_cap)"
            )
        if not current_data_confirmed and final > 0.50:
            failures.append("research-only confidence must be capped at 0.50")

    recommendations, recommendations_error = _sequence_field(
        runtime_output,
        "recommendations",
        "recommendations",
    )
    progress_event, progress_error = _mapping_field(
        runtime_output, "progress_event", "progress_event"
    )
    failures.extend(error for error in (recommendations_error, progress_error) if error)
    for index, row in enumerate(recommendations, 1):
        if not isinstance(row, Mapping):
            failures.append(f"recommendations row {index} must be object")
            continue
        rec_confidence, rec_error = _float_field(
            row, "confidence", f"recommendations[{index}]"
        )
        if rec_error:
            failures.append(rec_error)
        elif (
            final is not None
            and rec_confidence is not None
            and not _nearly_equal(rec_confidence, final)
        ):
            failures.append(
                f"recommendations[{index}].confidence must equal final_confidence"
            )
        if not current_data_confirmed and row.get("actionability") not in {
            "no_trade",
            "monitor_only",
        }:
            failures.append(
                f"recommendations[{index}].actionability violates research-only rule"
            )
    progress_confidence, progress_confidence_error = _float_field(
        progress_event,
        "confidence",
        "progress_event",
    )
    if progress_confidence_error:
        failures.append(progress_confidence_error)
    elif (
        final is not None
        and progress_confidence is not None
        and not _nearly_equal(progress_confidence, final)
    ):
        failures.append("progress_event.confidence must equal final_confidence")

    if failures:
        return False, "confidence policy runtime trace checked", "; ".join(failures)
    return (
        True,
        f"policy_ref=confidence_policy.v1, pre_cap={expected_pre_cap:.2f}, cap={cap:.2f}, final={final:.2f}",
        "",
    )


def _sequence_mapping_rows(
    payload: Mapping[str, Any],
    field: str,
    label: str,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    rows, rows_error = _sequence_field(payload, field, label)
    failures = [rows_error] if rows_error else []
    valid_rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid_rows.append(row)
        else:
            failures.append(f"{label} row {index} must be object")
    return valid_rows, failures


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return tuple()
    return tuple(str(item) for item in value if str(item or "").strip())


def _runtime_agent_output_from_mapping(
    runtime_output: Mapping[str, Any],
) -> tuple[RuntimeAgentOutput | None, list[str]]:
    failures: list[str] = []
    evidence_rows, evidence_failures = _sequence_mapping_rows(
        runtime_output,
        "evidence_ledger",
        "evidence_ledger",
    )
    inference_rows, inference_failures = _sequence_mapping_rows(
        runtime_output,
        "inferences",
        "inferences",
    )
    recommendation_rows, recommendation_failures = _sequence_mapping_rows(
        runtime_output,
        "recommendations",
        "recommendations",
    )
    progress_event, progress_error = _mapping_field(
        runtime_output,
        "progress_event",
        "progress_event",
    )
    components, components_error = _mapping_field(
        runtime_output,
        "confidence_components",
        "confidence_components",
    )
    aggregation, aggregation_error = _mapping_field(
        runtime_output,
        "rule_aggregation_summary",
        "rule_aggregation_summary",
    )
    handoff, handoff_error = _mapping_field(
        runtime_output,
        "downstream_handoff",
        "downstream_handoff",
    )
    failures.extend(
        [
            *evidence_failures,
            *inference_failures,
            *recommendation_failures,
            *[
                error
                for error in (
                    progress_error,
                    components_error,
                    aggregation_error,
                    handoff_error,
                )
                if error
            ],
        ]
    )
    if failures:
        return None, failures

    try:
        evidence = tuple(
            EvidenceLedgerItem(
                evidence_id=str(row.get("evidence_id") or ""),
                source_type=str(row.get("source_type") or ""),
                source_tool=str(row.get("source_tool") or ""),
                metric=str(row.get("metric") or ""),
                value=row.get("value"),
                unit=str(row.get("unit") or ""),
                as_of=str(row.get("as_of") or ""),
                freshness_days=int(row.get("freshness_days")),
                direction=str(row.get("direction") or ""),
                fallback=bool(row.get("fallback")),
                confidence_impact=str(row.get("confidence_impact") or ""),
                source_claim_ids=_string_sequence(row.get("source_claim_ids")),
            )
            for row in evidence_rows
        )
        inferences = tuple(
            RuntimeInference(
                inference_id=str(row.get("inference_id") or ""),
                statement=str(row.get("statement") or ""),
                evidence_ids=_string_sequence(row.get("evidence_ids")),
                rule_ids=_string_sequence(row.get("rule_ids")),
                source_claim_ids=_string_sequence(row.get("source_claim_ids")),
            )
            for row in inference_rows
        )
        recommendations = tuple(
            RuntimeRecommendation(
                recommendation_id=str(row.get("recommendation_id") or ""),
                statement=str(row.get("statement") or ""),
                inference_ids=_string_sequence(row.get("inference_ids")),
                confidence=float(row.get("confidence")),
                actionability=str(row.get("actionability") or ""),
            )
            for row in recommendation_rows
        )
        progress = ProgressEvent(
            agent_id=str(progress_event.get("agent_id") or ""),
            layer=str(progress_event.get("layer") or ""),
            status=str(progress_event.get("status") or ""),
            tools_used=_string_sequence(progress_event.get("tools_used")),
            evidence_count=int(progress_event.get("evidence_count")),
            fallback_count=int(progress_event.get("fallback_count")),
            missing_count=int(progress_event.get("missing_count")),
            schema_valid=bool(progress_event.get("schema_valid")),
            confidence=float(progress_event.get("confidence")),
        )
        confidence_components = {
            str(key): float(value) for key, value in components.items()
        }
        return (
            RuntimeAgentOutput(
                evidence_ledger=evidence,
                research_rule_ids_used=_string_sequence(
                    runtime_output.get("research_rule_ids_used")
                ),
                source_claim_ids_used=_string_sequence(
                    runtime_output.get("source_claim_ids_used")
                ),
                hypothesis_ids_used=_string_sequence(
                    runtime_output.get("hypothesis_ids_used")
                ),
                inferences=inferences,
                recommendations=recommendations,
                uncertainties=_string_sequence(runtime_output.get("uncertainties")),
                confidence_components=confidence_components,
                rule_aggregation_summary=aggregation,
                downstream_handoff=handoff,
                progress_event=progress,
                confidence_policy_trace=dict(
                    runtime_output.get("confidence_policy_trace") or {}
                ),
            ),
            [],
        )
    except (TypeError, ValueError) as exc:
        return None, [f"runtime output cannot be restored: {exc}"]


def _runtime_aggregation_policy_markers(root: Path) -> list[str]:
    failures: list[str] = []
    schema_path = root / "schemas/rule_aggregation_policy.schema.yaml"
    if not schema_path.exists():
        return ["rule aggregation policy schema missing"]
    schema_text = schema_path.read_text(encoding="utf-8")
    for marker in (
        "single_rule_max_adjustment: 0.05",
        "rule_group_max_adjustment: 0.10",
        "global_research_adjustment_cap: 0.20",
        "research_only_adjustment_cap: 0.05",
        "conflict_object_required",
        "group_and_deduplicate",
        "correlated_rule_dedup_test",
        "aggregation_level_backtest",
    ):
        if marker not in schema_text:
            failures.append(f"rule aggregation policy schema missing {marker}")
    return failures


def _runtime_aggregation_gate(
    root: Path,
    runtime_output: Mapping[str, Any] | None,
    *,
    runtime_output_error: str = "",
) -> tuple[bool, str, str]:
    failures = _runtime_aggregation_policy_markers(root)
    if runtime_output_error:
        failures.append(runtime_output_error)
    if not runtime_output:
        failures.append("runtime output missing")
        return False, "runtime aggregation evidence missing", "; ".join(failures)

    restored, restore_failures = _runtime_agent_output_from_mapping(runtime_output)
    failures.extend(restore_failures)
    if restored is not None:
        trace, trace_error = _mapping_field(
            runtime_output,
            "confidence_policy_trace",
            "confidence_policy_trace",
        )
        failures.append(trace_error) if trace_error else None
        confidence_cap = trace.get("confidence_cap", 1.0)
        try:
            check_result = check_runtime_output(
                restored,
                verified_claim_ids=set(restored.source_claim_ids_used),
                confidence_cap=float(confidence_cap),
            )
        except (TypeError, ValueError) as exc:
            failures.append(f"runtime checker failed to run: {exc}")
        else:
            failures.extend(check_result.reasons)

    aggregation, aggregation_error = _mapping_field(
        runtime_output,
        "rule_aggregation_summary",
        "rule_aggregation_summary",
    )
    if aggregation_error:
        failures.append(aggregation_error)
    target_signal = str(aggregation.get("target_signal") or "").strip()
    if not target_signal:
        failures.append("rule_aggregation_summary.target_signal required")
    try:
        horizon_days = int(aggregation.get("horizon_days"))
    except (TypeError, ValueError):
        horizon_days = 0
        failures.append("rule_aggregation_summary.horizon_days must be integer")
    if horizon_days <= 0:
        failures.append("rule_aggregation_summary.horizon_days must be positive")
    group_deltas, group_deltas_error = _mapping_field(
        aggregation,
        "group_deltas",
        "rule_aggregation_summary.group_deltas",
    )
    if group_deltas_error:
        failures.append(group_deltas_error)
    if not group_deltas:
        failures.append("rule_aggregation_summary.group_deltas required")
    parsed_group_deltas: dict[str, float] = {}
    for group_id, raw_delta in group_deltas.items():
        try:
            delta = float(raw_delta)
        except (TypeError, ValueError):
            failures.append(
                f"rule_aggregation_summary.group_deltas.{group_id} must be numeric"
            )
            continue
        parsed_group_deltas[str(group_id)] = delta
        if abs(delta) > 0.10:
            failures.append(
                f"rule_aggregation_summary.group_deltas.{group_id} exceeds rule_group_max_adjustment"
            )
    try:
        final_delta = float(aggregation.get("final_research_delta"))
    except (TypeError, ValueError):
        final_delta = 0.0
        failures.append("rule_aggregation_summary.final_research_delta must be numeric")
    if abs(final_delta) > 0.20:
        failures.append(
            "rule_aggregation_summary.final_research_delta exceeds global_research_adjustment_cap"
        )
    if parsed_group_deltas:
        expected_final = max(-0.20, min(0.20, sum(parsed_group_deltas.values())))
        if not _nearly_equal(final_delta, expected_final):
            failures.append(
                "rule_aggregation_summary.final_research_delta must equal capped sum(group_deltas)"
            )
    if not isinstance(aggregation.get("has_opposing_rules"), bool):
        failures.append("rule_aggregation_summary.has_opposing_rules must be boolean")
    try:
        duplicate_count = int(aggregation.get("correlated_rule_duplicate_count"))
    except (TypeError, ValueError):
        duplicate_count = -1
        failures.append(
            "rule_aggregation_summary.correlated_rule_duplicate_count must be integer"
        )
    if duplicate_count < 0:
        failures.append(
            "rule_aggregation_summary.correlated_rule_duplicate_count must be non-negative"
        )

    if failures:
        return False, "runtime aggregation policy checked", "; ".join(failures)
    return (
        True,
        (
            "runtime checker accepted aggregation summary; "
            f"target={target_signal}, horizon={horizon_days}, groups={len(group_deltas)}, "
            f"delta={final_delta:.2f}"
        ),
        "",
    )


def _research_only_no_trade_gate(
    prompt_ir: Mapping[str, Any] | None,
    sector_runtime: Mapping[str, Any] | None,
    *,
    prompt_ir_error: str = "",
    sector_runtime_error: str = "",
) -> tuple[bool, str, str]:
    failures: list[str] = []
    if prompt_ir_error:
        failures.append(prompt_ir_error)
    if sector_runtime_error:
        failures.append(sector_runtime_error)
    if not prompt_ir:
        failures.append("prompt IR missing")
    else:
        guardrails = prompt_ir.get("guardrails") or ()
        if "research_only_no_trade" not in guardrails:
            failures.append("prompt IR guardrails must include research_only_no_trade")
    if not sector_runtime:
        failures.append("sector research-only runtime output missing")
        return (
            False,
            "research-only no-trade runtime evidence missing",
            "; ".join(failures),
        )

    aggregation, aggregation_error = _mapping_field(
        sector_runtime,
        "rule_aggregation_summary",
        "sector rule_aggregation_summary",
    )
    recommendations, recommendations_error = _sequence_field(
        sector_runtime,
        "recommendations",
        "sector recommendations",
    )
    progress_event, progress_error = _mapping_field(
        sector_runtime,
        "progress_event",
        "sector progress_event",
    )
    failures.extend(
        error
        for error in (aggregation_error, recommendations_error, progress_error)
        if error
    )
    if aggregation.get("research_only") is not True:
        failures.append(
            "sector runtime must mark rule_aggregation_summary.research_only=true"
        )
    if not recommendations:
        failures.append("sector runtime recommendations missing")
    allowed_actionability = {"no_trade", "monitor_only"}
    for index, row in enumerate(recommendations, 1):
        if not isinstance(row, Mapping):
            failures.append(f"sector recommendations row {index} must be object")
            continue
        actionability = row.get("actionability")
        if actionability not in allowed_actionability:
            failures.append(
                f"sector recommendations[{index}].actionability must be no_trade or monitor_only"
            )
        confidence, confidence_error = _float_field(
            row, "confidence", f"sector recommendations[{index}]"
        )
        if confidence_error:
            failures.append(confidence_error)
        elif confidence is not None and confidence > 0.50:
            failures.append(
                f"sector recommendations[{index}].confidence must be <= 0.50"
            )
    progress_confidence, progress_confidence_error = _float_field(
        progress_event,
        "confidence",
        "sector progress_event",
    )
    if progress_confidence_error:
        failures.append(progress_confidence_error)
    elif progress_confidence is not None and progress_confidence > 0.50:
        failures.append("sector progress_event.confidence must be <= 0.50")

    if failures:
        return (
            False,
            "research-only no-trade runtime evidence checked",
            "; ".join(failures),
        )
    return (
        True,
        f"guardrail=research_only_no_trade, research_only=true, recommendations={len(recommendations)} monitor-only/no-trade",
        "",
    )


def _patch_target_parameter(
    rule_pack: Mapping[str, Any] | None,
    target_path: str,
) -> tuple[LearnableParameter | None, Any, str]:
    if not rule_pack:
        return None, None, "central_bank rule pack missing"
    parts = target_path.strip("/").split("/")
    if len(parts) != 7 or parts[0] != "rule_packs" or parts[2] != "rules":
        return (
            None,
            None,
            "patch target_path is not a rule-pack learnable-parameter path",
        )
    if parts[4] != "learnable_parameters" or parts[6] != "value":
        return (
            None,
            None,
            "patch target_path must end in learnable_parameters/<name>/value",
        )
    rule_pack_id = parts[1]
    rule_id = parts[3]
    parameter_name = parts[5]
    if str(rule_pack.get("rule_pack_id") or "") != rule_pack_id:
        return None, None, "patch target_path rule_pack_id does not match rule pack"
    rules, rules_error = _mapping_field(rule_pack, "rules", "rule_pack.rules")
    if rules_error:
        return None, None, rules_error
    rule, rule_error = _mapping_field(rules, rule_id, f"rule_pack.rules.{rule_id}")
    if rule_error or not rule:
        return None, None, rule_error or "patch target rule missing"
    params, params_error = _mapping_field(
        rule,
        "learnable_parameters",
        f"rule_pack.rules.{rule_id}.learnable_parameters",
    )
    if params_error:
        return None, None, params_error
    param, param_error = _mapping_field(
        params,
        parameter_name,
        f"rule_pack.rules.{rule_id}.learnable_parameters.{parameter_name}",
    )
    if param_error or not param:
        return None, None, param_error or "patch target parameter missing"
    parameter_type = str(param.get("type") or "")
    if parameter_type not in {"integer", "float", "string", "boolean"}:
        return None, None, "patch target parameter type is invalid"
    return (
        LearnableParameter(
            value=param.get("value"),
            type=parameter_type,  # type: ignore[arg-type]
            unit=param.get("unit"),
            min=param.get("min"),
            max=param.get("max"),
        ),
        param.get("value"),
        "",
    )


def _patch_validator_gate(
    patch: Mapping[str, Any] | None,
    rule_pack: Mapping[str, Any] | None,
    experiment: Mapping[str, Any] | None,
    *,
    patch_error: str = "",
    rule_pack_error: str = "",
    experiment_error: str = "",
) -> tuple[bool, str, str]:
    failures: list[str] = []
    failures.extend(
        error for error in (patch_error, rule_pack_error, experiment_error) if error
    )
    if not patch:
        failures.append("paper-trading patch missing")
    if not experiment:
        failures.append("validation experiment missing")
    if failures:
        return False, "patch validator inputs missing", "; ".join(failures)

    required_fields = (
        "patch_id",
        "source_experiment_id",
        "operation",
        "target_path",
        "old_value",
        "new_value",
        "allowed_by_evolution_targets",
        "validation_summary",
        "rollback_rule",
    )
    for field in required_fields:
        if field not in patch:
            failures.append(f"patch.{field} required")
    validation_summary, validation_error = _mapping_field(
        patch,
        "validation_summary",
        "patch.validation_summary",
    )
    rollback_rule, rollback_error = _mapping_field(
        patch,
        "rollback_rule",
        "patch.rollback_rule",
    )
    failures.extend(error for error in (validation_error, rollback_error) if error)
    if failures:
        return False, "patch validator inputs malformed", "; ".join(failures)

    target_path = str(patch.get("target_path") or "")
    parameter, current_value, parameter_error = _patch_target_parameter(
        rule_pack, target_path
    )
    if parameter_error:
        failures.append(parameter_error)
    experiment_id = str(experiment.get("experiment_id") or "")
    if str(patch.get("source_experiment_id") or "") != experiment_id:
        failures.append("patch source_experiment_id must match validation experiment")
    if validation_summary.get("promotion_state") != "paper_trading":
        failures.append(
            "patch validation_summary.promotion_state must be paper_trading"
        )
    for field in (
        "net_alpha_after_cost",
        "effective_n",
        "adjusted_q_value",
        "walk_forward_passed",
        "overlap_policy",
    ):
        if field not in validation_summary:
            failures.append(f"patch.validation_summary.{field} required")
    if rollback_rule.get("metric") != "live_net_alpha_after_cost_20d":
        failures.append(
            "patch rollback_rule.metric must be live_net_alpha_after_cost_20d"
        )
    if not rollback_rule.get("review_window_trading_days"):
        failures.append("patch rollback_rule.review_window_trading_days required")
    if not rollback_rule.get("slow_decay_detection"):
        failures.append("patch rollback_rule.slow_decay_detection required")
    if parameter is None:
        return False, "patch validator inputs malformed", "; ".join(failures)

    patch_obj = ProductionPatch(
        patch_id=str(patch.get("patch_id") or ""),
        source_experiment_id=str(patch.get("source_experiment_id") or ""),
        operation=str(patch.get("operation") or ""),  # type: ignore[arg-type]
        target_path=target_path,
        old_value=patch.get("old_value"),
        new_value=patch.get("new_value"),
        allowed_by_evolution_targets=bool(patch.get("allowed_by_evolution_targets")),
        validation_summary=validation_summary,
        rollback_rule=rollback_rule,
    )
    patch_validation = validate_patch(
        patch_obj,
        current_registry={target_path: current_value},
        parameter_types={target_path: parameter},
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={experiment_id},
        allowed_promotion_states={"paper_trading"},
    )
    failures.extend(patch_validation.reasons)
    if failures:
        return False, "patch validator replay checked", "; ".join(failures)
    return (
        True,
        f"{patch_obj.patch_id} target_path replay accepted; old={patch_obj.old_value}, new={patch_obj.new_value}, promotion_state=paper_trading",
        "",
    )


def _gold_set_gate(root: Path) -> tuple[bool, str, str]:
    raw_rows, raw_error = _optional_jsonl(
        root / "registry/gold_sets/tushare_research_reports.review_template.jsonl",
        "gold-set review",
    )
    if raw_error:
        return False, "gold-set review records malformed", raw_error
    if not raw_rows:
        return False, "gold-set review records missing", "gold-set review file missing"
    rows, invalid_rows = _split_mapping_rows(raw_rows)
    if invalid_rows:
        return (
            False,
            f"gold-set review records malformed: {len(invalid_rows)} non-object row(s) / {len(raw_rows)} rows",
            f"gold-set review row must be object at row(s): {', '.join(str(row) for row in invalid_rows)}",
        )
    review_fields = (
        "claim_correct",
        "source_span_supports_claim",
        "direction_correct",
        "variable_mapping_correct",
        "unsupported_field_false_grounded",
    )
    if any(row.get(field) is None for row in rows for field in review_fields):
        return (
            False,
            f"gold-set review records present: {len({str(row.get('document_id') or row.get('source_id') or '') for row in rows})} documents / {len(rows)} claims",
            "manual gold-set review still required",
        )
    gold_set = evaluate_gold_set_reviews(rows, gold_set_id="GOLD-CLAIM-2026Q2")
    if gold_set.passed:
        return True, "manual gold-set review passed", ""
    failures = "; ".join(gold_set.gate_failures())
    return (
        False,
        f"gold-set review records present: {gold_set.sample_size_documents} documents / "
        f"{gold_set.sample_size_claims} claims",
        failures or "manual review fields are not yet accepted",
    )


def _license_gate(root: Path) -> tuple[bool, str, str]:
    raw_sources, raw_sources_error = _optional_jsonl(
        root / "registry/sources/tushare_research_reports.jsonl",
        "source registry",
    )
    raw_reviews, raw_reviews_error = _optional_jsonl(
        root / "registry/compliance/tushare_license_review_template.jsonl",
        "source license review",
    )
    if raw_sources_error:
        return False, "Tushare source rows malformed", raw_sources_error
    if raw_reviews_error:
        return False, "license review records malformed", raw_reviews_error
    if not raw_sources:
        return False, "Tushare source rows missing", "source registry missing"
    if not raw_reviews:
        return False, "license review records missing", "license review file missing"
    sources, invalid_source_rows = _split_mapping_rows(raw_sources)
    reviews, invalid_review_rows = _split_mapping_rows(raw_reviews)
    if invalid_source_rows:
        return (
            False,
            f"Tushare source rows malformed: {len(invalid_source_rows)} non-object row(s) / {len(raw_sources)} rows",
            f"source registry row must be object at row(s): {', '.join(str(row) for row in invalid_source_rows)}",
        )
    if invalid_review_rows:
        return (
            False,
            f"license review records malformed: {len(invalid_review_rows)} non-object row(s) / {len(raw_reviews)} rows",
            f"source license review row must be object at row(s): {', '.join(str(row) for row in invalid_review_rows)}",
        )
    reviewed_sources = apply_source_license_reviews(sources, reviews)
    decisions = [evaluate_source_license(source) for source in reviewed_sources]
    approved = [
        decision for decision in decisions if decision.allowed_for_production_runtime
    ]
    if len(approved) == len(sources):
        return True, f"{len(approved)} sources approved for production runtime", ""
    return (
        False,
        f"{len(approved)} / {len(sources)} sources approved for production runtime",
        "source license review still pending or restricted",
    )


def _source_text_redaction_gate(root: Path) -> tuple[bool, str, str]:
    report, report_error = _optional_mapping(
        root / "registry/compliance/source_text_redaction_report.json",
        "source text redaction report",
    )
    if report_error:
        return False, "source text redaction report malformed", report_error
    if report is None:
        return (
            False,
            "source text redaction report missing",
            "source text redaction report missing",
        )
    if report.get("accepted") is True:
        return (
            True,
            f"{report.get('source_text_count')} Tushare source texts checked for long-passage exposure",
            "",
        )
    return (
        False,
        f"{report.get('failure_count')} source text redaction failure(s)",
        "long source text appears outside approved sandbox artifacts",
    )


def _validation_gate(
    experiment: Mapping[str, Any] | None,
    hardening: Mapping[str, Any] | None,
    statistical: Mapping[str, Any] | None,
    *,
    experiment_error: str = "",
    hardening_error: str = "",
    statistical_error: str = "",
) -> tuple[bool, str, str]:
    if experiment_error:
        return False, "validation experiment malformed", experiment_error
    if experiment is None:
        return False, "validation experiment missing", "experiment registry missing"
    sampling, sampling_error = _mapping_field(
        experiment, "sampling_design", "sampling_design"
    )
    mtc, mtc_error = _mapping_field(
        experiment, "multiple_testing_control", "multiple_testing_control"
    )
    acceptance, acceptance_error = _mapping_field(
        experiment, "acceptance_rule", "acceptance_rule"
    )
    failures: list[str] = []
    failures.extend(
        error for error in (sampling_error, mtc_error, acceptance_error) if error
    )
    if sampling.get("effective_n", 0) < sampling.get("minimum_effective_n", 10**9):
        failures.append("effective_n below minimum")
    if not sampling.get("overlap_policy"):
        failures.append("overlap policy missing")
    if mtc.get("adjusted_q_value", 1.0) > mtc.get("max_fdr", 0.0):
        failures.append("multiple testing correction failed")
    if acceptance.get("cost_model_required") is not True:
        failures.append("cost model requirement missing")
    if acceptance.get("primary_metric") != "net_alpha_after_cost_20d":
        failures.append("primary after-cost metric missing")

    if hardening_error:
        failures.append(hardening_error)
    elif hardening is None:
        failures.append("validation hardening report missing")
    else:
        ablation_checks, ablation_error = _mapping_field(
            hardening, "ablation_checks", "ablation_checks"
        )
        if ablation_error:
            failures.append(ablation_error)
        if ablation_checks.get("accepted") is not True:
            failures.append("ablation checks failed")
        if hardening.get("horizon_metric_failures"):
            failures.append("horizon-metric alignment failed")
        if hardening.get("precision_failures"):
            failures.append("scoring precision check failed")

    if statistical_error:
        failures.append(statistical_error)
    elif statistical is None:
        failures.append("statistical significance report missing")
    else:
        ci, ci_error = _mapping_field(
            statistical, "confidence_interval", "confidence_interval"
        )
        if ci_error:
            failures.append(ci_error)
        if statistical.get("accepted") is not True:
            failures.append("statistical significance gate failed")
        if float(ci.get("low") or 0.0) <= 0:
            failures.append("after-cost confidence interval includes zero")
        if float(statistical.get("deflated_sharpe_ratio") or 0.0) < float(
            statistical.get("minimum_deflated_sharpe_ratio") or 10**9
        ):
            failures.append("deflated Sharpe ratio below threshold")

    evidence = (
        f"{experiment.get('experiment_id')} + hardening/statistical gates"
        if not failures
        else str(experiment.get("experiment_id") or "unknown experiment")
    )
    return not failures, evidence, "; ".join(failures)


_DATA_AVAILABILITY_REQUIRED_FIELDS = (
    "metric_proxy",
    "data_source",
    "point_in_time_available",
    "history_start",
    "history_end",
    "vintage_handling",
    "survivorship_bias_risk",
    "timestamp_granularity",
    "allowed_for_validation",
    "allowed_for_production",
)


def _data_availability_gate(
    data_matrix: Mapping[str, Any] | None,
    rule_pack: Mapping[str, Any] | None,
    *,
    data_matrix_error: str = "",
    rule_pack_error: str = "",
) -> tuple[bool, str, str]:
    failures: list[str] = []
    if data_matrix_error:
        failures.append(data_matrix_error)
    if rule_pack_error:
        failures.append(rule_pack_error)
    if data_matrix is None:
        failures.append("data availability matrix missing")
    if rule_pack is None:
        failures.append("central_bank rule pack missing")
    if failures:
        return False, "central_bank data availability matrix", "; ".join(failures)

    data_proxies, data_proxies_error = _mapping_field(
        data_matrix,
        "proxies",
        "data availability proxies",
    )
    rules, rules_error = _mapping_field(rule_pack, "rules", "rule_pack.rules")
    failures.extend(error for error in (data_proxies_error, rules_error) if error)
    if not data_proxies:
        failures.append("data availability proxies missing")
    if not rules:
        failures.append("rule_pack.rules missing")
    if failures:
        return False, "central_bank data availability matrix", "; ".join(failures)

    required_proxies: set[str] = set()
    rule_count = 0
    for rule_id, raw_rule in rules.items():
        if not isinstance(raw_rule, Mapping):
            failures.append(f"rule {rule_id} must be object")
            continue
        status = str(raw_rule.get("status") or "").strip().lower()
        if status not in {"candidate", "paper_trading", "production", "active"}:
            continue
        rule_count += 1
        metric_proxies = raw_rule.get("metric_proxies")
        if not isinstance(metric_proxies, list | tuple):
            failures.append(f"rule {rule_id}.metric_proxies must be list")
            continue
        for index, proxy in enumerate(metric_proxies, 1):
            proxy_name = str(proxy or "").strip()
            if not proxy_name:
                failures.append(
                    f"rule {rule_id}.metric_proxies[{index}] must be non-empty"
                )
                continue
            required_proxies.add(proxy_name)

    if not required_proxies:
        failures.append("no production candidate metric proxies found in rule pack")
    for proxy_name in sorted(required_proxies):
        raw_proxy = data_proxies.get(proxy_name)
        if not isinstance(raw_proxy, Mapping):
            failures.append(
                f"data availability proxy missing or malformed: {proxy_name}"
            )
            continue
        for field in _DATA_AVAILABILITY_REQUIRED_FIELDS:
            if field not in raw_proxy:
                failures.append(f"{proxy_name}.{field} missing")
        if raw_proxy.get("metric_proxy") != proxy_name:
            failures.append(f"{proxy_name}.metric_proxy must equal proxy key")
        for field in (
            "data_source",
            "history_start",
            "history_end",
            "vintage_handling",
            "survivorship_bias_risk",
            "timestamp_granularity",
        ):
            if not str(raw_proxy.get(field) or "").strip():
                failures.append(f"{proxy_name}.{field} must be non-empty")
        if raw_proxy.get("point_in_time_available") is not True:
            failures.append(f"{proxy_name}.point_in_time_available must be true")
        if raw_proxy.get("allowed_for_validation") is not True:
            failures.append(f"{proxy_name}.allowed_for_validation must be true")
        if raw_proxy.get("allowed_for_production") is not True:
            failures.append(f"{proxy_name}.allowed_for_production must be true")
        known_biases = raw_proxy.get("known_biases")
        if known_biases is not None and not isinstance(known_biases, list):
            failures.append(f"{proxy_name}.known_biases must be list when present")
        history_start = str(raw_proxy.get("history_start") or "").strip()
        history_end = str(raw_proxy.get("history_end") or "").strip()
        if history_start and history_end:
            try:
                if history_start > history_end:
                    failures.append(
                        f"{proxy_name}.history_start must be <= history_end"
                    )
            except TypeError:
                failures.append(
                    f"{proxy_name}.history dates must be comparable strings"
                )

    if failures:
        return (
            False,
            f"{len(required_proxies)} rule-pack proxy/proxies checked",
            "; ".join(failures),
        )
    return (
        True,
        (
            f"{len(required_proxies)} rule-pack proxies PIT/validation/production "
            f"eligible across {rule_count} candidate rule(s): "
            + ", ".join(sorted(required_proxies))
        ),
        "",
    )


def _audit_trace_gate(root: Path) -> tuple[bool, str, str]:
    trace, trace_error = _optional_mapping(
        root / "registry/audits/central_bank_mvp_audit_trace.json",
        "audit trace",
    )
    if trace_error:
        return False, "audit trace malformed", trace_error
    if trace is None:
        return False, "audit trace missing", "audit trace file missing"
    try:
        view = build_audit_trace_view(root, trace_id="central-bank-mvp")
    except Exception as exc:  # noqa: BLE001 - malformed registry artifacts should block, not crash, the audit
        return (
            False,
            "audit trace resolution failed",
            f"audit trace resolution failed: {exc}",
        )
    if view.complete:
        return (
            True,
            f"{view.node_count} audit nodes and {view.edge_count} provenance edges resolved",
            "",
        )
    blockers = tuple(view.missing_references) + tuple(view.broken_edges)
    return (
        False,
        f"{view.node_count} audit nodes and {view.edge_count} provenance edges resolved",
        "; ".join(blockers),
    )


def audit_master_plan_completion(root: str | Path = ".") -> CompletionAudit:
    root_path = Path(root)
    experiment, experiment_error = _optional_mapping(
        root_path / "registry/experiments/central_bank_validation_experiment_v2.json",
        "validation experiment",
    )
    hardening, hardening_error = _optional_mapping(
        root_path / "registry/validation_hardening/central_bank_hardening_report.json",
        "validation hardening report",
    )
    statistical, statistical_error = _optional_mapping(
        root_path
        / "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json",
        "statistical significance report",
    )
    runtime_output, runtime_output_error = _optional_mapping(
        root_path / "registry/runtime_outputs/macro.central_bank.20260605.json",
        "runtime output",
    )
    prompt_ir, prompt_ir_error = _optional_mapping(
        root_path / "registry/prompt_ir/macro.central_bank.json",
        "prompt IR",
    )
    sector_runtime, sector_runtime_error = _optional_mapping(
        root_path / "registry/runtime_outputs/sector.semiconductor.demo.20260605.json",
        "sector research-only runtime output",
    )
    paper_report, paper_report_error = _optional_mapping(
        root_path / "registry/monitoring/central_bank_paper_trading_report.json",
        "paper trading report",
    )
    monitor_diagnostics, monitor_diagnostics_error = _optional_mapping(
        root_path / "registry/monitoring/central_bank_monitoring_diagnostics.json",
        "production monitor diagnostics",
    )
    data_matrix, data_matrix_error = _optional_mapping(
        root_path / "registry/data_availability/central_bank_data_availability.json",
        "data availability matrix",
    )
    patch, patch_error = _optional_mapping(
        root_path / "registry/patches/central_bank_paper_trading_patch.json",
        "paper-trading patch",
    )
    rule_pack, rule_pack_error = _optional_mapping(
        root_path / "registry/rule_packs/macro.central_bank.liquidity.v1.json",
        "central_bank rule pack",
    )

    gold_passed, gold_evidence, gold_blocker = _gold_set_gate(root_path)
    license_passed, license_evidence, license_blocker = _license_gate(root_path)
    redaction_passed, redaction_evidence, redaction_blocker = (
        _source_text_redaction_gate(root_path)
    )
    validation_passed, validation_evidence, validation_blocker = _validation_gate(
        experiment,
        hardening,
        statistical,
        experiment_error=experiment_error,
        hardening_error=hardening_error,
        statistical_error=statistical_error,
    )
    audit_passed, audit_evidence, audit_blocker = _audit_trace_gate(root_path)
    confidence_passed, confidence_evidence, confidence_blocker = (
        _confidence_policy_gate(
            root_path,
            runtime_output,
            runtime_output_error=runtime_output_error,
        )
    )
    patch_passed, patch_evidence, patch_blocker = _patch_validator_gate(
        patch,
        rule_pack,
        experiment,
        patch_error=patch_error,
        rule_pack_error=rule_pack_error,
        experiment_error=experiment_error,
    )
    research_only_passed, research_only_evidence, research_only_blocker = (
        _research_only_no_trade_gate(
            prompt_ir,
            sector_runtime,
            prompt_ir_error=prompt_ir_error,
            sector_runtime_error=sector_runtime_error,
        )
    )
    data_availability_passed, data_availability_evidence, data_availability_blocker = (
        _data_availability_gate(
            data_matrix,
            rule_pack,
            data_matrix_error=data_matrix_error,
            rule_pack_error=rule_pack_error,
        )
    )
    (
        runtime_aggregation_passed,
        runtime_aggregation_evidence,
        runtime_aggregation_blocker,
    ) = _runtime_aggregation_gate(
        root_path,
        runtime_output,
        runtime_output_error=runtime_output_error,
    )

    paper_summary, paper_summary_error = _mapping_field(
        paper_report,
        "paper_trading_summary",
        "paper_trading_summary",
    )
    production_monitor, production_monitor_error = _mapping_field(
        paper_report,
        "production_monitor",
        "production_monitor",
    )
    monitor_diagnostics_passed = (
        not paper_report_error
        and not production_monitor_error
        and bool(production_monitor)
        and not monitor_diagnostics_error
        and bool(monitor_diagnostics)
        and monitor_diagnostics.get("accepted") is True
    )
    if paper_report_error:
        monitor_diagnostics_blocker = paper_report_error
    elif production_monitor_error:
        monitor_diagnostics_blocker = production_monitor_error
    elif not paper_report:
        monitor_diagnostics_blocker = "production monitor report missing"
    elif monitor_diagnostics_error:
        monitor_diagnostics_blocker = monitor_diagnostics_error
    elif not monitor_diagnostics:
        monitor_diagnostics_blocker = "production monitor diagnostics missing"
    elif monitor_diagnostics.get("accepted") is not True:
        monitor_diagnostics_blocker = "production monitor diagnostics failed"
    else:
        monitor_diagnostics_blocker = ""
    completion = CompletionAudit(
        criteria=(
            CompletionCriterion(
                "C01",
                "At least one macro rule family reaches the Phase 4 paper-trading gate.",
                not paper_report_error
                and not paper_summary_error
                and paper_summary.get("ready") is True,
                "central_bank paper-trading report",
                paper_report_error
                or paper_summary_error
                or ("" if paper_report else "paper trading report missing"),
            ),
            CompletionCriterion(
                "C02",
                "Claim extraction gold set passes the manual precision gate.",
                gold_passed,
                gold_evidence,
                gold_blocker,
            ),
            CompletionCriterion(
                "C03",
                "Data availability matrix covers the production candidate proxies.",
                data_availability_passed,
                data_availability_evidence,
                data_availability_blocker,
            ),
            CompletionCriterion(
                "C04",
                "Validation v2 report includes effective N, overlap, FDR, costs, CI, and DSR.",
                validation_passed,
                validation_evidence,
                validation_blocker,
            ),
            CompletionCriterion(
                "C05",
                "Runtime aggregation implements de-duplication and conflict objects.",
                runtime_aggregation_passed,
                runtime_aggregation_evidence,
                runtime_aggregation_blocker,
            ),
            CompletionCriterion(
                "C06",
                "Confidence policy v1 uses the conservative min-components function.",
                confidence_passed,
                confidence_evidence,
                confidence_blocker,
            ),
            CompletionCriterion(
                "C07",
                "Research-only no-trade rule is enforced by checker.",
                research_only_passed,
                research_only_evidence,
                research_only_blocker,
            ),
            CompletionCriterion(
                "C08",
                "Patch validator rejects forbidden paths and mismatched target paths.",
                patch_passed,
                patch_evidence,
                patch_blocker,
            ),
            CompletionCriterion(
                "C09",
                "Paper trading monitor outputs live-vs-baseline deltas.",
                bool(
                    not paper_report_error
                    and not paper_summary_error
                    and paper_report
                    and "mean_live_vs_baseline_delta" in paper_summary
                ),
                "central_bank paper-trading summary",
                paper_report_error
                or paper_summary_error
                or ("" if paper_report else "paper trading report missing"),
            ),
            CompletionCriterion(
                "C10",
                "Production monitor can detect alpha decay and calibration drift.",
                monitor_diagnostics_passed,
                (
                    "production monitor report + "
                    f"{(monitor_diagnostics or {}).get('scenario_count', 0)} diagnostic scenarios"
                ),
                monitor_diagnostics_blocker,
            ),
            CompletionCriterion(
                "C11",
                "Compliance gate blocks unauthorized reports from production runtime.",
                license_passed and redaction_passed,
                f"{license_evidence}; {redaction_evidence}",
                "; ".join(
                    blocker
                    for blocker in (license_blocker, redaction_blocker)
                    if blocker
                ),
            ),
            CompletionCriterion(
                "C12",
                "Audit viewer trace covers source to agent output.",
                audit_passed,
                audit_evidence,
                audit_blocker,
            ),
        )
    )
    if rule_pack is None or rule_pack_error:
        criteria = list(completion.criteria)
        criteria[0] = CompletionCriterion(
            criteria[0].criterion_id,
            criteria[0].description,
            False,
            criteria[0].evidence,
            rule_pack_error or "central_bank rule pack missing",
        )
        return CompletionAudit(criteria=tuple(criteria))
    return completion


def write_completion_audit(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    audit = audit_master_plan_completion(root_path)
    passed_count = sum(1 for item in audit.criteria if item.passed)
    payload = {
        "report_id": "RKE-COMPLETION-AUDIT-20260606",
        **final_acceptance_metadata(),
        **asdict(audit),
        "ready_for_broad_rollout": audit.ready_for_broad_rollout,
        "passed_count": passed_count,
        "blocked_count": len(audit.criteria) - passed_count,
        "blockers": list(audit.blockers),
    }
    output_path = root_path / "registry/audits/rke_completion_audit.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(output_path),
        "ready_for_broad_rollout": audit.ready_for_broad_rollout,
    }


def main() -> None:
    print(json.dumps(write_completion_audit(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
