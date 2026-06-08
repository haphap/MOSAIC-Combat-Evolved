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
from .monitoring import ProductionMonitorPolicy
from .p0 import LearnableParameter
from .phase_minus1 import evaluate_gold_set_reviews
from .review_integrity import (
    GOLD_REVIEW_FIELDS,
    gold_review_integrity_failures,
    license_review_integrity_failures,
)
from .runtime import (
    EvidenceLedgerItem,
    ProgressEvent,
    ResearchSupportItem,
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


def _numeric_field(
    payload: Mapping[str, Any], field: str, label: str
) -> tuple[float | None, str]:
    value = payload.get(field)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f"{label}.{field} must be numeric"
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
    "research_weight_confidence",
    "empirical_validation_confidence",
    "method_tool_confidence",
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
    if "research_confidence" in components:
        failures.append(
            "confidence_components.research_confidence is legacy; use research_weight_confidence"
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
        parsed_components["research_weight_confidence"],
        parsed_components["empirical_validation_confidence"],
        parsed_components["method_tool_confidence"],
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
    if "research_support_ledger" in runtime_output:
        research_support_rows, research_support_failures = _sequence_mapping_rows(
            runtime_output,
            "research_support_ledger",
            "research_support_ledger",
        )
    else:
        research_support_rows, research_support_failures = [], []
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
            *research_support_failures,
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
                evidence_type=str(row.get("evidence_type") or ""),
                metric_candidate_id=str(row.get("metric_candidate_id") or ""),
                analysis_recipe_id=str(row.get("analysis_recipe_id") or ""),
                report_footprint_ids=_string_sequence(row.get("report_footprint_ids")),
                tool_proposal_id=str(row.get("tool_proposal_id") or ""),
            )
            for row in evidence_rows
        )
        research_support = tuple(
            ResearchSupportItem(
                research_support_id=str(row.get("research_support_id") or ""),
                evidence_type=str(row.get("evidence_type") or ""),
                source_claim_ids=_string_sequence(row.get("source_claim_ids")),
                viewpoint_cluster_ids=_string_sequence(
                    row.get("viewpoint_cluster_ids")
                ),
                source_weight_bucket=str(row.get("source_weight_bucket") or ""),
                method_pattern_ids=_string_sequence(row.get("method_pattern_ids")),
                allowed_use=str(row.get("allowed_use") or ""),
                cannot_support_action_without_current_data=bool(
                    row.get("cannot_support_action_without_current_data")
                ),
            )
            for row in research_support_rows
        )
        inferences = tuple(
            RuntimeInference(
                inference_id=str(row.get("inference_id") or ""),
                statement=str(row.get("statement") or ""),
                evidence_ids=_string_sequence(row.get("evidence_ids")),
                rule_ids=_string_sequence(row.get("rule_ids")),
                source_claim_ids=_string_sequence(row.get("source_claim_ids")),
                research_support_ids=_string_sequence(
                    row.get("research_support_ids")
                ),
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
                research_support_ledger=research_support,
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


_PAPER_SNAPSHOT_REQUIRED_NUMERIC_FIELDS = (
    "live_shadow_signal",
    "baseline_signal",
    "live_net_alpha_after_cost",
    "turnover",
    "calibration_error",
)
_PAPER_SNAPSHOT_REQUIRED_RATE_FIELDS = (
    "conflict_rate",
    "fallback_rate",
    "missing_data_rate",
)
_PAPER_SUMMARY_RECOMPUTED_FIELDS = (
    "mean_live_vs_baseline_delta",
    "mean_live_net_alpha_after_cost",
    "mean_turnover",
    "mean_calibration_error",
)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 12) if values else 0.0


def _paper_trading_gate(
    paper_report: Mapping[str, Any] | None,
    *,
    paper_report_error: str = "",
) -> tuple[bool, str, str, bool, str, str]:
    common_failures: list[str] = []
    if paper_report_error:
        common_failures.append(paper_report_error)
    if paper_report is None:
        common_failures.append("paper trading report missing")
        blocker = "; ".join(common_failures)
        return (
            False,
            "paper-trading report missing",
            blocker,
            False,
            "paper-trading summary missing",
            blocker,
        )

    report_payload, report_error = _mapping_field(
        paper_report,
        "paper_trading_report",
        "paper_trading_report",
    )
    summary, summary_error = _mapping_field(
        paper_report,
        "paper_trading_summary",
        "paper_trading_summary",
    )
    production_monitor, monitor_error = _mapping_field(
        paper_report,
        "production_monitor",
        "production_monitor",
    )
    common_failures.extend(
        error for error in (report_error, summary_error, monitor_error) if error
    )

    snapshots, snapshot_failures = _sequence_mapping_rows(
        report_payload,
        "snapshots",
        "paper_trading_report.snapshots",
    )
    common_failures.extend(snapshot_failures)
    report_rule_id = str(report_payload.get("rule_id") or "").strip()
    if not report_rule_id:
        common_failures.append("paper_trading_report.rule_id required")
    elif not report_rule_id.startswith("macro."):
        common_failures.append("paper_trading_report.rule_id must be a macro rule")
    if not snapshots:
        common_failures.append("paper_trading_report.snapshots required")

    live_vs_baseline: list[float] = []
    net_alpha_after_cost: list[float] = []
    turnover_values: list[float] = []
    calibration_values: list[float] = []
    conflict_rates: list[float] = []
    fallback_rates: list[float] = []
    missing_data_rates: list[float] = []
    seen_dates: set[str] = set()
    for index, snapshot in enumerate(snapshots, 1):
        label = f"paper_trading_report.snapshots[{index}]"
        snapshot_rule_id = str(snapshot.get("rule_id") or "").strip()
        if snapshot_rule_id != report_rule_id:
            common_failures.append(
                f"{label}.rule_id must match paper_trading_report.rule_id"
            )
        date = str(snapshot.get("date") or "").strip()
        if not date:
            common_failures.append(f"{label}.date required")
        elif date in seen_dates:
            common_failures.append(f"{label}.date duplicated")
        seen_dates.add(date)

        parsed: dict[str, float] = {}
        for field in _PAPER_SNAPSHOT_REQUIRED_NUMERIC_FIELDS:
            number, error = _numeric_field(snapshot, field, label)
            if error:
                common_failures.append(error)
            elif number is not None:
                parsed[field] = number
        for field in _PAPER_SNAPSHOT_REQUIRED_RATE_FIELDS:
            number, error = _float_field(snapshot, field, label)
            if error:
                common_failures.append(error)
            elif number is not None:
                if field == "conflict_rate":
                    conflict_rates.append(number)
                elif field == "fallback_rate":
                    fallback_rates.append(number)
                elif field == "missing_data_rate":
                    missing_data_rates.append(number)
        if set(parsed) == set(_PAPER_SNAPSHOT_REQUIRED_NUMERIC_FIELDS):
            live_vs_baseline.append(
                parsed["live_shadow_signal"] - parsed["baseline_signal"]
            )
            net_alpha_after_cost.append(parsed["live_net_alpha_after_cost"])
            turnover_values.append(parsed["turnover"])
            calibration_values.append(parsed["calibration_error"])
            if parsed["turnover"] < 0:
                common_failures.append(f"{label}.turnover must be non-negative")
            if parsed["calibration_error"] < 0:
                common_failures.append(
                    f"{label}.calibration_error must be non-negative"
                )

    recomputed = {
        "mean_live_vs_baseline_delta": _mean(live_vs_baseline),
        "mean_live_net_alpha_after_cost": _mean(net_alpha_after_cost),
        "mean_turnover": _mean(turnover_values),
        "mean_calibration_error": _mean(calibration_values),
    }
    summary_failures = list(common_failures)
    if summary.get("rule_id") != report_rule_id:
        summary_failures.append(
            "paper_trading_summary.rule_id must match report rule_id"
        )
    if summary.get("n") != len(snapshots):
        summary_failures.append("paper_trading_summary.n must equal snapshot count")
    for field in _PAPER_SUMMARY_RECOMPUTED_FIELDS:
        value, error = _numeric_field(summary, field, "paper_trading_summary")
        if error:
            summary_failures.append(error)
            continue
        if value is not None and not _nearly_equal(value, recomputed[field]):
            summary_failures.append(
                f"paper_trading_summary.{field} must equal recomputed snapshot mean"
            )

    policy = ProductionMonitorPolicy()
    readiness_failures = list(summary_failures)
    if summary.get("ready") is not True:
        readiness_failures.append("paper_trading_summary.ready must be true")
    if len(snapshots) <= 0:
        readiness_failures.append("paper trading requires at least one snapshot")
    if recomputed["mean_live_net_alpha_after_cost"] <= 0:
        readiness_failures.append("mean_live_net_alpha_after_cost must be positive")
    if recomputed["mean_turnover"] > policy.turnover_increase_threshold:
        readiness_failures.append(
            "mean_turnover exceeds production monitor turnover threshold"
        )
    if recomputed["mean_calibration_error"] > policy.calibration_error_threshold:
        readiness_failures.append(
            "mean_calibration_error exceeds production monitor calibration threshold"
        )
    if max(conflict_rates or [0.0]) > 0.05:
        readiness_failures.append(
            "snapshot conflict_rate exceeds paper-trading tolerance"
        )
    if max(fallback_rates or [0.0]) > 0.05:
        readiness_failures.append(
            "snapshot fallback_rate exceeds paper-trading tolerance"
        )
    if max(missing_data_rates or [0.0]) > 0.05:
        readiness_failures.append(
            "snapshot missing_data_rate exceeds paper-trading tolerance"
        )

    monitor_metrics, monitor_metrics_error = _mapping_field(
        production_monitor,
        "metrics",
        "production_monitor.metrics",
    )
    if monitor_metrics_error:
        readiness_failures.append(monitor_metrics_error)
    monitor_state = str(production_monitor.get("state") or "").strip()
    monitor_action = str(production_monitor.get("action") or "").strip()
    if monitor_state != "production":
        readiness_failures.append("production_monitor.state must be production")
    if monitor_action != "none":
        readiness_failures.append("production_monitor.action must be none")
    effective_events, effective_events_error = _numeric_field(
        monitor_metrics,
        "effective_events",
        "production_monitor.metrics",
    )
    if effective_events_error:
        readiness_failures.append(effective_events_error)
    elif (
        effective_events is not None and effective_events < policy.min_effective_events
    ):
        readiness_failures.append(
            "production_monitor effective_events below policy minimum"
        )
    effect_ratio, effect_ratio_error = _numeric_field(
        monitor_metrics,
        "effect_ratio",
        "production_monitor.metrics",
    )
    if effect_ratio_error:
        readiness_failures.append(effect_ratio_error)
    elif effect_ratio is not None and effect_ratio < policy.effect_decay_threshold:
        readiness_failures.append(
            "production_monitor effect_ratio below decay threshold"
        )
    rolling_alpha, rolling_alpha_error = _numeric_field(
        monitor_metrics,
        "rolling_net_alpha_after_cost",
        "production_monitor.metrics",
    )
    if rolling_alpha_error:
        readiness_failures.append(rolling_alpha_error)
    elif rolling_alpha is not None and rolling_alpha <= 0:
        readiness_failures.append(
            "production_monitor rolling_net_alpha_after_cost must be positive"
        )
    monitor_calibration, monitor_calibration_error = _numeric_field(
        monitor_metrics,
        "calibration_error",
        "production_monitor.metrics",
    )
    if monitor_calibration_error:
        readiness_failures.append(monitor_calibration_error)
    elif (
        monitor_calibration is not None
        and abs(monitor_calibration) > policy.calibration_error_threshold
    ):
        readiness_failures.append(
            "production_monitor calibration_error exceeds threshold"
        )
    monitor_turnover, monitor_turnover_error = _numeric_field(
        monitor_metrics,
        "turnover_delta",
        "production_monitor.metrics",
    )
    if monitor_turnover_error:
        readiness_failures.append(monitor_turnover_error)
    elif (
        monitor_turnover is not None
        and monitor_turnover > policy.turnover_increase_threshold
    ):
        readiness_failures.append("production_monitor turnover_delta exceeds threshold")

    summary_evidence = (
        f"paper summary recomputed from {len(snapshots)} snapshot(s): "
        f"delta={recomputed['mean_live_vs_baseline_delta']:.3f}, "
        f"net_alpha_after_cost={recomputed['mean_live_net_alpha_after_cost']:.4f}, "
        f"turnover={recomputed['mean_turnover']:.3f}, "
        f"calibration={recomputed['mean_calibration_error']:.3f}"
    )
    readiness_evidence = (
        f"paper trading ready: rule={report_rule_id}, snapshots={len(snapshots)}, "
        f"mean_net_alpha_after_cost={recomputed['mean_live_net_alpha_after_cost']:.4f}, "
        f"monitor_state={monitor_state or 'missing'}"
    )
    return (
        not readiness_failures,
        readiness_evidence,
        "; ".join(readiness_failures),
        not summary_failures,
        summary_evidence,
        "; ".join(summary_failures),
    )


_EXPECTED_MONITOR_SCENARIOS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "healthy_production": ("production", "none", ()),
    "insufficient_live_events": (
        "insufficient_data",
        "keep_monitoring",
        ("not enough live effective events",),
    ),
    "alpha_decay": (
        "monitored_decay",
        "reduce_weight_and_revalidate",
        ("alpha effect decayed below threshold",),
    ),
    "calibration_drift": (
        "monitored_decay",
        "reduce_weight_and_revalidate",
        ("confidence calibration drift exceeds threshold",),
    ),
    "turnover_spike": (
        "monitored_decay",
        "reduce_weight_and_revalidate",
        ("turnover increased beyond threshold",),
    ),
    "negative_alpha_with_calibration_drift": (
        "rollback_required",
        "rollback",
        (
            "confidence calibration drift exceeds threshold",
            "live net alpha after cost is negative",
        ),
    ),
}

_EXPECTED_ROLLBACK_CHECKS: dict[str, tuple[str, str]] = {
    "soft_rollback_alpha_decay": ("soft", "reduce_weight_and_revalidate"),
    "hard_rollback_negative_alpha": ("hard", "rollback"),
    "patch_has_slow_decay_rollback_rule": ("patch", "apply patch rollback rule"),
    "compliance_rollback_blocks_runtime_retrieval": (
        "compliance",
        "block production runtime retrieval",
    ),
    "promotion_gate_respects_rollback_blocks": (
        "promotion",
        "keep rule in paper_trading",
    ),
}


def _monitor_diagnostics_gate(
    monitor_diagnostics: Mapping[str, Any] | None,
    rollback_readiness: Mapping[str, Any] | None,
    *,
    monitor_diagnostics_error: str = "",
    rollback_readiness_error: str = "",
) -> tuple[bool, str, str]:
    failures: list[str] = []
    if monitor_diagnostics_error:
        failures.append(monitor_diagnostics_error)
    if rollback_readiness_error:
        failures.append(rollback_readiness_error)
    if monitor_diagnostics is None:
        failures.append("production monitor diagnostics missing")
    if rollback_readiness is None:
        failures.append("rollback readiness report missing")
    if failures:
        return False, "production monitor diagnostics missing", "; ".join(failures)

    if monitor_diagnostics.get("accepted") is not True:
        failures.append("production monitor diagnostics accepted must be true")
    if monitor_diagnostics.get("scenario_count") != len(_EXPECTED_MONITOR_SCENARIOS):
        failures.append("production monitor diagnostics scenario_count mismatch")
    if monitor_diagnostics.get("passed_count") != len(_EXPECTED_MONITOR_SCENARIOS):
        failures.append("production monitor diagnostics passed_count mismatch")
    if monitor_diagnostics.get("failure_count") != 0:
        failures.append("production monitor diagnostics failure_count must be zero")

    scenario_rows, scenario_errors = _sequence_mapping_rows(
        monitor_diagnostics,
        "scenarios",
        "production monitor diagnostics scenarios",
    )
    failures.extend(scenario_errors)
    scenarios_by_id = {
        str(row.get("scenario_id") or ""): row
        for row in scenario_rows
        if str(row.get("scenario_id") or "").strip()
    }
    missing_scenarios = set(_EXPECTED_MONITOR_SCENARIOS) - set(scenarios_by_id)
    extra_scenarios = set(scenarios_by_id) - set(_EXPECTED_MONITOR_SCENARIOS)
    if missing_scenarios:
        failures.append(
            f"production monitor diagnostics missing scenarios: {sorted(missing_scenarios)}"
        )
    if extra_scenarios:
        failures.append(
            f"production monitor diagnostics unexpected scenarios: {sorted(extra_scenarios)}"
        )
    for scenario_id, (
        expected_state,
        expected_action,
        required_reasons,
    ) in _EXPECTED_MONITOR_SCENARIOS.items():
        scenario = scenarios_by_id.get(scenario_id)
        if not scenario:
            continue
        result, result_error = _mapping_field(
            scenario,
            "result",
            f"production monitor diagnostics {scenario_id}.result",
        )
        if result_error:
            failures.append(result_error)
        if scenario.get("expected_state") != expected_state:
            failures.append(f"{scenario_id}.expected_state must be {expected_state}")
        if scenario.get("expected_action") != expected_action:
            failures.append(f"{scenario_id}.expected_action must be {expected_action}")
        if scenario.get("passed") is not True:
            failures.append(f"{scenario_id}.passed must be true")
        if scenario.get("failure"):
            failures.append(f"{scenario_id}.failure must be empty")
        if result.get("state") != expected_state:
            failures.append(f"{scenario_id}.result.state must be {expected_state}")
        if result.get("action") != expected_action:
            failures.append(f"{scenario_id}.result.action must be {expected_action}")
        reasons = " ".join(str(item) for item in result.get("reasons") or ())
        for reason in required_reasons:
            if reason not in reasons:
                failures.append(f"{scenario_id}.result.reasons missing '{reason}'")
        metrics, metrics_error = _mapping_field(
            result,
            "metrics",
            f"production monitor diagnostics {scenario_id}.result.metrics",
        )
        if metrics_error:
            failures.append(metrics_error)
        if not metrics:
            failures.append(f"{scenario_id}.result.metrics required")

    if rollback_readiness.get("accepted") is not True:
        failures.append("rollback readiness accepted must be true")
    if rollback_readiness.get("check_count") != len(_EXPECTED_ROLLBACK_CHECKS):
        failures.append("rollback readiness check_count mismatch")
    if rollback_readiness.get("passed_count") != len(_EXPECTED_ROLLBACK_CHECKS):
        failures.append("rollback readiness passed_count mismatch")
    if rollback_readiness.get("failure_count") != 0:
        failures.append("rollback readiness failure_count must be zero")
    check_rows, check_errors = _sequence_mapping_rows(
        rollback_readiness,
        "checks",
        "rollback readiness checks",
    )
    failures.extend(check_errors)
    checks_by_id = {
        str(row.get("check_id") or ""): row
        for row in check_rows
        if str(row.get("check_id") or "").strip()
    }
    missing_checks = set(_EXPECTED_ROLLBACK_CHECKS) - set(checks_by_id)
    extra_checks = set(checks_by_id) - set(_EXPECTED_ROLLBACK_CHECKS)
    if missing_checks:
        failures.append(f"rollback readiness missing checks: {sorted(missing_checks)}")
    if extra_checks:
        failures.append(f"rollback readiness unexpected checks: {sorted(extra_checks)}")
    for check_id, (rollback_type, action) in _EXPECTED_ROLLBACK_CHECKS.items():
        check = checks_by_id.get(check_id)
        if not check:
            continue
        if check.get("passed") is not True:
            failures.append(f"{check_id}.passed must be true")
        if check.get("rollback_type") != rollback_type:
            failures.append(f"{check_id}.rollback_type must be {rollback_type}")
        if check.get("action") != action:
            failures.append(f"{check_id}.action must be {action}")
        if check.get("blocker"):
            failures.append(f"{check_id}.blocker must be empty")
        if not str(check.get("trigger") or "").strip():
            failures.append(f"{check_id}.trigger required")
        if not str(check.get("evidence_path") or "").strip():
            failures.append(f"{check_id}.evidence_path required")

    if failures:
        return False, "production monitor diagnostics checked", "; ".join(failures)
    return (
        True,
        (
            f"{len(_EXPECTED_MONITOR_SCENARIOS)} diagnostic scenarios + "
            f"{len(_EXPECTED_ROLLBACK_CHECKS)} rollback readiness checks accepted"
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
        patch_type=str(patch.get("patch_type") or ""),
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
    integrity_failures = gold_review_integrity_failures(rows)
    if integrity_failures:
        return (
            False,
            f"gold-set review records present: {len({str(row.get('document_id') or row.get('source_id') or '') for row in rows})} documents / {len(rows)} claims",
            "; ".join(integrity_failures),
        )
    if any(row.get(field) is None for row in rows for field in GOLD_REVIEW_FIELDS):
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
    integrity_failures = license_review_integrity_failures(sources, reviews)
    if integrity_failures:
        return (
            False,
            f"license review records present: {len(reviews)} reviews / {len(sources)} sources",
            "; ".join(integrity_failures),
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


_AUDIT_REQUIRED_NODE_TYPES = (
    "source",
    "claim",
    "hypothesis",
    "rule",
    "parameter_path",
    "experiment",
    "patch",
    "agent_output",
)
_AUDIT_REQUIRED_EDGE_CONTRACTS = (
    ("claim", "source", "source_ids", "source -> claim"),
    ("hypothesis", "claim", "claim_ids", "claim -> hypothesis"),
    ("rule", "claim", "claim_ids", "claim -> rule"),
    ("rule", "hypothesis", "hypothesis_ids", "hypothesis -> rule"),
    ("rule", "parameter_path", "parameter_paths", "rule -> parameter"),
    ("experiment", "rule", "rule_ids", "rule -> experiment"),
    ("experiment", "parameter_path", "parameter_paths", "parameter -> experiment"),
    ("patch", "experiment", "experiment_ids", "experiment -> patch"),
    ("patch", "parameter_path", "parameter_paths", "parameter -> patch"),
    ("agent_output", "claim", "claim_ids", "claim -> agent output"),
    ("agent_output", "hypothesis", "hypothesis_ids", "hypothesis -> agent output"),
    ("agent_output", "rule", "rule_ids", "rule -> agent output"),
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
    blockers = list(view.missing_references) + list(view.broken_edges)
    node_types = {node.ref_type for node in view.nodes}
    missing_node_types = set(_AUDIT_REQUIRED_NODE_TYPES) - node_types
    if missing_node_types:
        blockers.append(f"audit trace missing node types: {sorted(missing_node_types)}")
    edge_contracts = {
        (edge.source_type, edge.target_type, edge.relationship) for edge in view.edges
    }
    missing_edge_labels: list[str] = []
    for source_type, target_type, relationship, label in _AUDIT_REQUIRED_EDGE_CONTRACTS:
        if (source_type, target_type, relationship) not in edge_contracts:
            missing_edge_labels.append(label)
    if missing_edge_labels:
        blockers.append(f"audit trace missing chain edges: {missing_edge_labels}")
    if view.complete and not blockers:
        return (
            True,
            (
                f"{len(_AUDIT_REQUIRED_NODE_TYPES)} audit node types and "
                f"{len(_AUDIT_REQUIRED_EDGE_CONTRACTS)} source-to-output chain edges resolved"
            ),
            "",
        )
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
    rollback_readiness, rollback_readiness_error = _optional_mapping(
        root_path / "registry/monitoring/central_bank_rollback_readiness_report.json",
        "rollback readiness report",
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
    (
        paper_ready_passed,
        paper_ready_evidence,
        paper_ready_blocker,
        paper_summary_passed,
        paper_summary_evidence,
        paper_summary_blocker,
    ) = _paper_trading_gate(
        paper_report,
        paper_report_error=paper_report_error,
    )
    (
        monitor_diagnostics_passed,
        monitor_diagnostics_evidence,
        monitor_diagnostics_blocker,
    ) = _monitor_diagnostics_gate(
        monitor_diagnostics,
        rollback_readiness,
        monitor_diagnostics_error=monitor_diagnostics_error,
        rollback_readiness_error=rollback_readiness_error,
    )

    completion = CompletionAudit(
        criteria=(
            CompletionCriterion(
                "C01",
                "At least one macro rule family reaches the Phase 4 paper-trading gate.",
                paper_ready_passed,
                paper_ready_evidence,
                paper_ready_blocker,
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
                paper_summary_passed,
                paper_summary_evidence,
                paper_summary_blocker,
            ),
            CompletionCriterion(
                "C10",
                "Production monitor can detect alpha decay and calibration drift.",
                monitor_diagnostics_passed,
                monitor_diagnostics_evidence,
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
