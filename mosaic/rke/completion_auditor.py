"""Dynamic completion audit for the RKE master plan."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .audit_viewer import build_audit_trace_view
from .central_bank_mvp import CompletionAudit, CompletionCriterion
from .compliance import apply_source_license_reviews, evaluate_source_license
from .phase_minus1 import evaluate_gold_set_reviews, load_jsonl


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _optional_mapping(path: Path, label: str) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, ""
    payload = _read_json(path)
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


def _optional_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return load_jsonl(path)


def _split_mapping_rows(rows: list[Any]) -> tuple[list[Mapping[str, Any]], tuple[int, ...]]:
    valid: list[Mapping[str, Any]] = []
    invalid: list[int] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid.append(row)
        else:
            invalid.append(index)
    return valid, tuple(invalid)


def _runtime_output_passes(runtime_output: Mapping[str, Any]) -> bool:
    required = (
        "evidence_ledger",
        "research_rule_ids_used",
        "source_claim_ids_used",
        "hypothesis_ids_used",
        "inferences",
        "recommendations",
        "confidence_components",
        "rule_aggregation_summary",
        "downstream_handoff",
        "progress_event",
    )
    return all(runtime_output.get(field) for field in required)


def _gold_set_gate(root: Path) -> tuple[bool, str, str]:
    raw_rows = _optional_jsonl(root / "registry/gold_sets/tushare_research_reports.review_template.jsonl")
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
    raw_sources = _optional_jsonl(root / "registry/sources/tushare_research_reports.jsonl")
    raw_reviews = _optional_jsonl(root / "registry/compliance/tushare_license_review_template.jsonl")
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
    approved = [decision for decision in decisions if decision.allowed_for_production_runtime]
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
        return False, "source text redaction report missing", "source text redaction report missing"
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
    sampling, sampling_error = _mapping_field(experiment, "sampling_design", "sampling_design")
    mtc, mtc_error = _mapping_field(experiment, "multiple_testing_control", "multiple_testing_control")
    acceptance, acceptance_error = _mapping_field(experiment, "acceptance_rule", "acceptance_rule")
    failures: list[str] = []
    failures.extend(error for error in (sampling_error, mtc_error, acceptance_error) if error)
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
        ablation_checks, ablation_error = _mapping_field(hardening, "ablation_checks", "ablation_checks")
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
        ci, ci_error = _mapping_field(statistical, "confidence_interval", "confidence_interval")
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
        return False, "audit trace resolution failed", f"audit trace resolution failed: {exc}"
    if view.complete:
        return True, f"{view.node_count} audit nodes and {view.edge_count} provenance edges resolved", ""
    blockers = tuple(view.missing_references) + tuple(view.broken_edges)
    return False, f"{view.node_count} audit nodes and {view.edge_count} provenance edges resolved", "; ".join(blockers)


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
        root_path / "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json",
        "statistical significance report",
    )
    runtime_output, runtime_output_error = _optional_mapping(
        root_path / "registry/runtime_outputs/macro.central_bank.20260605.json",
        "runtime output",
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
    redaction_passed, redaction_evidence, redaction_blocker = _source_text_redaction_gate(root_path)
    validation_passed, validation_evidence, validation_blocker = _validation_gate(
        experiment,
        hardening,
        statistical,
        experiment_error=experiment_error,
        hardening_error=hardening_error,
        statistical_error=statistical_error,
    )
    audit_passed, audit_evidence, audit_blocker = _audit_trace_gate(root_path)

    aggregation, aggregation_error = _mapping_field(
        runtime_output,
        "rule_aggregation_summary",
        "rule_aggregation_summary",
    )
    runtime_passed = (
        not runtime_output_error
        and not aggregation_error
        and bool(runtime_output)
        and _runtime_output_passes(runtime_output)
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
    data_proxies, data_proxies_error = _mapping_field(
        data_matrix,
        "proxies",
        "data availability proxies",
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
                not paper_report_error and not paper_summary_error and paper_summary.get("ready") is True,
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
                (
                    not data_matrix_error
                    and not data_proxies_error
                    and bool(
                        data_matrix
                        and {"pboc_net_injection_7d", "risk_appetite_proxy"} <= set(data_proxies)
                    )
                ),
                "central_bank data availability matrix",
                data_matrix_error
                or data_proxies_error
                or ("" if data_matrix else "data availability matrix missing"),
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
                runtime_passed
                and "correlated_rule_duplicate_count" in aggregation
                and "has_opposing_rules" in aggregation,
                "runtime output aggregation summary",
                runtime_output_error
                or aggregation_error
                or ("" if runtime_passed else "runtime output missing required fields"),
            ),
            CompletionCriterion(
                "C06",
                "Confidence policy v1 uses the conservative min-components function.",
                Path(root_path / "schemas/confidence_policy.schema.yaml").exists(),
                "confidence_policy.schema.yaml + compute_confidence_v1 tests",
                "",
            ),
            CompletionCriterion(
                "C07",
                "Research-only no-trade rule is enforced by checker.",
                runtime_passed,
                "runtime output checker and focused tests",
                runtime_output_error
                or aggregation_error
                or ("" if runtime_passed else "runtime output checker evidence missing"),
            ),
            CompletionCriterion(
                "C08",
                "Patch validator rejects forbidden paths and mismatched target paths.",
                not patch_error and bool(patch and patch.get("allowed_by_evolution_targets") is True),
                "central_bank paper-trading patch + patch checker tests",
                patch_error or ("" if patch else "patch registry missing"),
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
                "; ".join(blocker for blocker in (license_blocker, redaction_blocker) if blocker),
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
    output_path = root_path / "registry/audits/rke_completion_audit.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(audit), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(output_path), "ready_for_broad_rollout": audit.ready_for_broad_rollout}


def main() -> None:
    print(json.dumps(write_completion_audit(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
