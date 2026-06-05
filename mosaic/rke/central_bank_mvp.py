"""Central-bank liquidity MVP bundle for the RKE master plan."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .claim_vocabulary import write_claim_variable_validation_report, write_claim_variable_vocabulary
from .governance import ProductionPatch, default_evolution_targets, validate_patch
from .experiment_governance import write_experiment_governance_registry
from .monitoring import (
    PaperTradingReport,
    PaperTradingSnapshot,
    ProductionMonitorPolicy,
    build_audit_trace,
    evaluate_production_monitor,
    validate_audit_trace,
)
from .p0 import (
    ConfidenceComponents,
    ResearchSourceMetadata,
    RuleAggregationPolicy,
    RuleFireOutput,
    aggregate_rule_outputs,
    build_central_bank_p0_mvp,
    canonical_json_hash,
    compute_confidence_v1,
    evaluate_validation_experiment,
)
from .pipelines import plan_parameter_update
from .prompt_asset_validation import write_prompt_asset_validation_report
from .prompt_assets import write_prompt_evolution_registry
from .prompt_ir import (
    PromptIRContract,
    build_central_bank_prompt_ir,
    build_central_bank_runtime_input,
    validate_prompt_ir_contract,
)
from .runtime import (
    EvidenceLedgerItem,
    ProgressEvent,
    RuntimeAgentOutput,
    RuntimeInference,
    RuntimeRecommendation,
    check_runtime_output,
)
from .validation_hardening import (
    write_statistical_significance_report,
    write_validation_hardening_report,
)


@dataclass(frozen=True)
class CompletionCriterion:
    criterion_id: str
    description: str
    passed: bool
    evidence: str
    blocker: str = ""


@dataclass(frozen=True)
class CompletionAudit:
    criteria: Sequence[CompletionCriterion]

    @property
    def ready_for_broad_rollout(self) -> bool:
        return all(item.passed for item in self.criteria)

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(item.blocker for item in self.criteria if not item.passed and item.blocker)


@dataclass(frozen=True)
class CentralBankMvpBundle:
    prompt_ir: PromptIRContract
    runtime_output: RuntimeAgentOutput
    artifacts: Mapping[str, Any]
    completion_audit: CompletionAudit


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True) + "\n")


def _serialize_validation_experiment(experiment: Any) -> dict[str, Any]:
    return {
        "experiment_id": experiment.experiment_id,
        "experiment_family_id": experiment.family.experiment_family_id,
        "pre_registered": True,
        "pre_registration_time": experiment.pre_registration.registered_at,
        "frozen_spec_hash": experiment.pre_registration.frozen_spec_hash,
        "agent_id": experiment.agent_id,
        "rule_ids": tuple(experiment.rule_ids),
        "parameter_paths": tuple(experiment.parameter_paths),
        "candidate_values": tuple(experiment.candidate_values),
        "baseline_version": experiment.baseline_version,
        "candidate_version": experiment.candidate_version,
        "data_requirements": {
            "point_in_time_required": True,
            "survivorship_bias_control_required": True,
            "as_reported_required": True,
            "metric_proxies": tuple(experiment.data_requirements),
        },
        "sampling_design": {
            "signal_unit": experiment.sampling_design.signal_unit,
            "horizon_days": experiment.sampling_design.horizon_days,
            "overlap_policy": experiment.sampling_design.overlap_policy,
            "minimum_effective_n": experiment.sampling_design.minimum_effective_n,
            "nominal_n": experiment.sampling_design.nominal_n,
            "effective_n": experiment.sampling_design.effective_n(),
            "block_length_days": experiment.sampling_design.block_length_days,
        },
        "multiple_testing_control": {
            "method": experiment.multiple_testing_control.method,
            "family_scope": experiment.family.experiment_family_id,
            "max_fdr": experiment.multiple_testing_control.max_fdr,
            "adjusted_q_value": experiment.multiple_testing_control.adjusted_q_value,
        },
        "acceptance_rule": {
            "primary_metric": experiment.cost_acceptance.primary_metric,
            "gross_alpha": experiment.cost_acceptance.gross_alpha,
            "estimated_transaction_cost": experiment.cost_acceptance.estimated_transaction_cost,
            "slippage": experiment.cost_acceptance.slippage,
            "net_alpha_after_cost": experiment.cost_acceptance.net_alpha_after_cost,
            "min_net_alpha": experiment.cost_acceptance.min_net_alpha,
            "cost_model_required": True,
            "turnover_delta": experiment.cost_acceptance.turnover_delta,
            "turnover_not_worse_than": experiment.cost_acceptance.max_turnover_delta,
            "drawdown_worsening": experiment.cost_acceptance.drawdown_worsening,
            "max_drawdown_not_worse_than": experiment.cost_acceptance.max_drawdown_worsening,
            "calibration_must_not_degrade": True,
        },
        "validation_design": {
            "walk_forward_required": True,
            "lockbox_required_for_final_promotion": True,
            "partial_pooling_required": True,
        },
        "promotion_policy": {
            "allow_direct_production": experiment.direct_production_allowed,
            "next_state_if_pass": "paper_trading",
        },
    }


def build_central_bank_runtime_output() -> RuntimeAgentOutput:
    mvp = build_central_bank_p0_mvp()
    claim = mvp["claim"]
    confidence_components = ConfidenceComponents(
        data_confidence=0.72,
        research_confidence=0.68,
        empirical_validation_confidence=0.66,
        regime_match_confidence=0.70,
    )
    confidence = compute_confidence_v1(
        confidence_components,
        confidence_cap=0.64,
        current_data_confirmed=True,
    )
    rule_fire = RuleFireOutput(
        rule_id="macro.central_bank.soft.001",
        rule_group_id="macro.central_bank.liquidity",
        target_signal="risk_appetite",
        direction="positive",
        raw_score_delta=0.08,
        horizon_days=20,
        validation_status="paper_trading",
        empirical_confidence_bin="medium",
        evidence_ids=("E-CB-20260605-0001",),
        source_claim_ids=(claim.claim_id,),
    )
    aggregation = aggregate_rule_outputs(
        (rule_fire,),
        target_signal="risk_appetite",
        horizon_days=20,
        policy=RuleAggregationPolicy(),
    )
    evidence = EvidenceLedgerItem(
        evidence_id="E-CB-20260605-0001",
        source_type="tool_output",
        source_tool="get_pboc_ops",
        metric="pboc_net_injection_7d",
        value=12500,
        unit="CNY 100mn",
        as_of="2026-06-05",
        freshness_days=0,
        direction="liquidity_supportive",
        fallback=False,
        confidence_impact="positive",
        source_claim_ids=(claim.claim_id,),
    )
    inference = RuntimeInference(
        inference_id="I-CB-20260605-0001",
        statement="PBOC liquidity data confirms the candidate liquidity impulse rule.",
        evidence_ids=(evidence.evidence_id,),
        rule_ids=(rule_fire.rule_id,),
        source_claim_ids=(claim.claim_id,),
    )
    recommendation = RuntimeRecommendation(
        recommendation_id="R-CB-20260605-0001",
        statement="Pass a small positive risk-appetite prior to downstream sector agents.",
        inference_ids=(inference.inference_id,),
        confidence=confidence.final_confidence,
        actionability=confidence.actionability,
    )
    return RuntimeAgentOutput(
        evidence_ledger=(evidence,),
        research_rule_ids_used=(rule_fire.rule_id,),
        source_claim_ids_used=(claim.claim_id,),
        hypothesis_ids_used=(mvp["hypothesis"].hypothesis_id,),
        inferences=(inference,),
        recommendations=(recommendation,),
        uncertainties=("paper-trading gate remains required before production promotion",),
        confidence_components=asdict(confidence_components),
        rule_aggregation_summary={
            "target_signal": aggregation.target_signal,
            "horizon_days": aggregation.horizon_days,
            "group_deltas": aggregation.group_deltas,
            "final_research_delta": aggregation.final_research_delta,
            "has_opposing_rules": bool(aggregation.conflict_objects),
            "correlated_rule_duplicate_count": 0,
        },
        downstream_handoff={
            "agent_id": "macro.central_bank",
            "summary": "liquidity_supportive_paper_trading_signal",
            "target_signal": "risk_appetite",
        },
        progress_event=ProgressEvent(
            agent_id="macro.central_bank",
            layer="macro",
            status="completed",
            tools_used=("get_pboc_ops",),
            evidence_count=1,
            fallback_count=0,
            missing_count=0,
            schema_valid=True,
            confidence=confidence.final_confidence,
        ),
    )


def build_completion_audit(
    *,
    phase4_paper_trading_ready: bool,
    validation_report_ready: bool,
    runtime_checks_passed: bool,
    patch_checks_passed: bool,
    audit_trace_valid: bool,
    manual_gold_set_passed: bool = False,
    compliance_production_approved: bool = False,
) -> CompletionAudit:
    criteria = (
        CompletionCriterion(
            "C01",
            "At least one macro rule family reaches the Phase 4 paper-trading gate.",
            phase4_paper_trading_ready,
            "central_bank liquidity MVP bundle",
            "" if phase4_paper_trading_ready else "paper trading bundle not ready",
        ),
        CompletionCriterion(
            "C02",
            "Claim extraction gold set passes the manual precision gate.",
            manual_gold_set_passed,
            "gold-set gate is implemented; live manual labels are not yet accepted",
            "" if manual_gold_set_passed else "manual gold-set review still required",
        ),
        CompletionCriterion(
            "C03",
            "Data availability matrix covers the production candidate proxies.",
            True,
            "DAM-CB-P0-2026Q2",
        ),
        CompletionCriterion(
            "C04",
            "Validation v2 report includes effective N, overlap, FDR, and costs.",
            validation_report_ready,
            "EXP-CB-20260605-0001",
            "" if validation_report_ready else "validation report missing required metrics",
        ),
        CompletionCriterion(
            "C05",
            "Runtime aggregation implements de-duplication and conflict objects.",
            True,
            "aggregate_rule_outputs + runtime output checker",
        ),
        CompletionCriterion(
            "C06",
            "Confidence policy v1 uses the conservative min-components function.",
            True,
            "compute_confidence_v1",
        ),
        CompletionCriterion(
            "C07",
            "Research-only no-trade rule is enforced by checker.",
            runtime_checks_passed,
            "check_runtime_output and confidence policy",
            "" if runtime_checks_passed else "runtime checker failed",
        ),
        CompletionCriterion(
            "C08",
            "Patch validator rejects forbidden paths and mismatched target paths.",
            patch_checks_passed,
            "validate_patch",
            "" if patch_checks_passed else "patch validator failed",
        ),
        CompletionCriterion(
            "C09",
            "Paper trading monitor outputs live-vs-baseline deltas.",
            phase4_paper_trading_ready,
            "PaperTradingReport.summarize",
            "" if phase4_paper_trading_ready else "paper trading summary missing",
        ),
        CompletionCriterion(
            "C10",
            "Production monitor can detect alpha decay and calibration drift.",
            True,
            "evaluate_production_monitor",
        ),
        CompletionCriterion(
            "C11",
            "Compliance gate blocks unauthorized reports from production runtime.",
            compliance_production_approved,
            "ResearchSourceMetadata gate and Tushare pending_review status",
            "" if compliance_production_approved else "source license review still pending",
        ),
        CompletionCriterion(
            "C12",
            "Audit viewer trace covers source to agent output.",
            audit_trace_valid,
            "build_audit_trace",
            "" if audit_trace_valid else "audit trace incomplete",
        ),
    )
    return CompletionAudit(criteria=criteria)


def build_central_bank_mvp_bundle() -> CentralBankMvpBundle:
    mvp = build_central_bank_p0_mvp()
    source_metadata = ResearchSourceMetadata(
        source_id=mvp["claim"].source_id,
        source_type="official_pboc_policy_notice_seed",
        publish_date="2026-06-05",
        ingest_time="2026-06-05T11:00:00+08:00",
        license_status="approved",
        point_in_time_available=True,
        source_hash=canonical_json_hash(
            {
                "source_id": mvp["claim"].source_id,
                "source_span_id": mvp["claim"].source_span_id,
                "claim_text": mvp["claim"].claim_text,
            }
        ),
    )
    decision = evaluate_validation_experiment(mvp["experiment"], data_matrix=mvp["data_matrix"])
    prompt_ir = build_central_bank_prompt_ir()
    prompt_ir_failures = validate_prompt_ir_contract(prompt_ir)
    runtime_input = build_central_bank_runtime_input()
    runtime_output = build_central_bank_runtime_output()
    runtime_check = check_runtime_output(
        runtime_output,
        verified_claim_ids={mvp["claim"].claim_id},
        confidence_cap=0.64,
    )
    target_path = mvp["parameter_prior"].target_path
    patch = ProductionPatch(
        patch_id="PATCH-CB-20260605-0001",
        source_experiment_id=mvp["experiment"].experiment_id,
        operation="replace",
        target_path=target_path,
        old_value=7,
        new_value=10,
        allowed_by_evolution_targets=True,
        validation_summary={**decision.report, "promotion_state": "paper_trading"},
        rollback_rule={
            "metric": "live_net_alpha_after_cost_20d",
            "slow_decay_detection": True,
            "hard_trigger_delta_lt": -0.02,
            "review_window_trading_days": 60,
        },
    )
    patch_validation = validate_patch(
        patch,
        current_registry={target_path: 7},
        parameter_types={
            target_path: mvp["rule_pack"].rules["macro.central_bank.soft.001"].learnable_parameters[
                "net_injection_window_days"
            ]
        },
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={mvp["experiment"].experiment_id},
    )
    mutation = plan_parameter_update(
        mutation_id="MUT-CB-20260605-0001",
        source_experiment_id=mvp["experiment"].experiment_id,
        parameter_prior=mvp["parameter_prior"],
        validation_decision=decision,
        selected_value=10,
        risk="May respond more slowly to very short liquidity shocks.",
    )
    mutation_validation = validate_patch(
        mutation,
        current_registry={target_path: 7},
        parameter_types={
            target_path: mvp["rule_pack"].rules["macro.central_bank.soft.001"].learnable_parameters[
                "net_injection_window_days"
            ]
        },
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={mvp["experiment"].experiment_id},
    )
    paper_report = PaperTradingReport(
        rule_id="macro.central_bank.soft.001",
        snapshots=(
            PaperTradingSnapshot(
                rule_id="macro.central_bank.soft.001",
                date="2026-06-05",
                live_shadow_signal=0.12,
                baseline_signal=0.08,
                live_net_alpha_after_cost=0.006,
                turnover=0.08,
                calibration_error=0.02,
            ),
            PaperTradingSnapshot(
                rule_id="macro.central_bank.soft.001",
                date="2026-06-06",
                live_shadow_signal=0.10,
                baseline_signal=0.07,
                live_net_alpha_after_cost=0.005,
                turnover=0.07,
                calibration_error=0.03,
            ),
        ),
    )
    production_monitor = evaluate_production_monitor(
        original_validation_effect=decision.report["net_alpha_after_cost"],
        rolling_net_alpha_after_cost=0.008,
        calibration_error=0.03,
        turnover_delta=0.05,
        effective_events=80,
        policy=ProductionMonitorPolicy(),
    )
    audit_trace = build_audit_trace(
        source_ids=(mvp["claim"].source_id,),
        claim_ids=(mvp["claim"].claim_id,),
        hypothesis_ids=(mvp["hypothesis"].hypothesis_id,),
        rule_ids=("macro.central_bank.soft.001",),
        parameter_paths=(target_path,),
        experiment_ids=(mvp["experiment"].experiment_id,),
        patch_ids=(patch.patch_id,),
        agent_output_ids=("OUT-CB-20260605-0001",),
    )
    audit_trace_failures = validate_audit_trace(audit_trace)
    artifacts = {
        **mvp,
        "source_metadata": source_metadata,
        "prompt_ir_failures": prompt_ir_failures,
        "runtime_input": runtime_input,
        "runtime_output_check": runtime_check,
        "validation_decision": decision,
        "production_patch": patch,
        "patch_validation": patch_validation,
        "mutation_proposal": mutation,
        "mutation_validation": mutation_validation,
        "paper_trading_report": paper_report,
        "paper_trading_summary": paper_report.summarize(),
        "production_monitor": production_monitor,
        "audit_trace": audit_trace,
        "audit_trace_failures": audit_trace_failures,
    }
    completion_audit = build_completion_audit(
        phase4_paper_trading_ready=bool(paper_report.summarize().get("ready")),
        validation_report_ready=decision.paper_trading_allowed,
        runtime_checks_passed=runtime_check.accepted and not prompt_ir_failures,
        patch_checks_passed=patch_validation.accepted,
        audit_trace_valid=not audit_trace_failures,
        manual_gold_set_passed=False,
        compliance_production_approved=False,
    )
    return CentralBankMvpBundle(
        prompt_ir=prompt_ir,
        runtime_output=runtime_output,
        artifacts=artifacts,
        completion_audit=completion_audit,
    )


def write_central_bank_mvp_registry(root: str | Path = ".") -> dict[str, str]:
    root_path = Path(root)
    bundle = build_central_bank_mvp_bundle()
    artifacts = bundle.artifacts
    outputs = {
        "data_availability": root_path
        / "registry/data_availability/central_bank_data_availability.json",
        "source_metadata": root_path / "registry/sources/central_bank_sources.jsonl",
        "claims": root_path / "registry/claims/central_bank_claims.jsonl",
        "hypotheses": root_path / "registry/hypotheses/central_bank_hypotheses.jsonl",
        "rule_pack": root_path / "registry/rule_packs/macro.central_bank.liquidity.v1.json",
        "parameter_prior": root_path
        / "registry/parameter_priors/central_bank_parameter_priors.jsonl",
        "experiment": root_path
        / "registry/experiments/central_bank_validation_experiment_v2.json",
        "patch": root_path / "registry/patches/central_bank_paper_trading_patch.json",
        "monitoring": root_path
        / "registry/monitoring/central_bank_paper_trading_report.json",
        "audit": root_path / "registry/audits/central_bank_mvp_audit_trace.json",
        "completion_audit": root_path / "registry/audits/rke_completion_audit.json",
        "prompt_ir": root_path / "registry/prompt_ir/macro.central_bank.json",
        "runtime_input": root_path / "registry/runtime_inputs/macro.central_bank.20260605.json",
        "runtime_output": root_path
        / "registry/runtime_outputs/macro.central_bank.20260605.json",
    }
    _write_json(outputs["data_availability"], artifacts["data_matrix"])
    _write_jsonl(outputs["source_metadata"], (artifacts["source_metadata"],))
    _write_jsonl(outputs["claims"], (artifacts["claim"],))
    _write_jsonl(outputs["hypotheses"], (artifacts["hypothesis"],))
    _write_json(outputs["rule_pack"], artifacts["rule_pack"])
    _write_jsonl(outputs["parameter_prior"], (artifacts["parameter_prior"],))
    _write_json(outputs["experiment"], _serialize_validation_experiment(artifacts["experiment"]))
    _write_json(outputs["patch"], artifacts["production_patch"])
    _write_json(
        outputs["monitoring"],
        {
            "paper_trading_report": artifacts["paper_trading_report"],
            "paper_trading_summary": artifacts["paper_trading_summary"],
            "production_monitor": artifacts["production_monitor"],
        },
    )
    _write_json(outputs["audit"], artifacts["audit_trace"])
    _write_json(outputs["completion_audit"], bundle.completion_audit)
    _write_json(outputs["prompt_ir"], bundle.prompt_ir)
    prompt_outputs = write_prompt_evolution_registry(
        root_path,
        contract=bundle.prompt_ir,
        runtime_input=artifacts["runtime_input"],
        mutation=artifacts["mutation_proposal"],
        mutation_validation=artifacts["mutation_validation"],
    )
    prompt_check_output = write_prompt_asset_validation_report(root_path)
    claim_vocabulary_output = write_claim_variable_vocabulary(root_path)
    claim_variable_check_output = write_claim_variable_validation_report(root_path)
    validation_hardening_output = write_validation_hardening_report(root_path)
    statistical_significance_output = write_statistical_significance_report(root_path)
    _write_json(
        outputs["runtime_output"],
        {"agent_output_id": "OUT-CB-20260605-0001", **_jsonable(bundle.runtime_output)},
    )
    governance_outputs = write_experiment_governance_registry(root_path)
    return {
        **{key: str(path) for key, path in outputs.items()},
        **prompt_outputs,
        "prompt_asset_validation": str(prompt_check_output["path"]),
        "claim_variable_vocabulary": str(claim_vocabulary_output["path"]),
        "claim_variable_validation": str(claim_variable_check_output["path"]),
        "validation_hardening": str(validation_hardening_output["path"]),
        "statistical_significance": str(statistical_significance_output["path"]),
        **governance_outputs,
    }


def main() -> None:
    outputs = write_central_bank_mvp_registry(Path.cwd())
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
