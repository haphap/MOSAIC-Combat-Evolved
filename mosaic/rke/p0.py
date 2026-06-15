"""P0 implementation for the MOSAIC Research Knowledge Engine.

This module implements the P0 gates from
``MOSAIC_RKE_PROMPT_EVOLUTION_MASTER_PLAN_V1_1.md``:

* data availability / PIT matrix;
* source-grounded claim extraction and gold-set gates;
* validation experiment v2 governance;
* effective-N / overlap / multiple-testing / cost-aware acceptance;
* pre-registration and lockbox rules;
* runtime rule aggregation with correlation de-duplication and conflicts;
* conservative confidence policy v1 and research-only actionability gates;
* central_bank / liquidity MVP seed objects.

The implementation is intentionally dependency-free so P0 governance can run
inside tests, bridge handlers, and offline validation jobs without the backtest
stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from json import dumps
from math import isfinite
from re import compile as re_compile
from statistics import median
from typing import Any, Literal, Mapping, Sequence

MIN_CLAIM_GOLD_SET_DOCUMENTS = 50
MIN_CLAIM_GOLD_SET_CLAIMS = 100
CLAIM_GOLD_SET_METRIC_THRESHOLDS: Mapping[str, tuple[str, float]] = {
    "claim_precision": (">=", 0.85),
    "source_span_support_precision": (">=", 0.90),
    "direction_accuracy": (">=", 0.85),
    "target_accuracy": (">=", 0.85),
    "horizon_accuracy": (">=", 0.85),
    "variable_mapping_accuracy": (">=", 0.80),
    "unsupported_field_false_grounding_rate": ("<=", 0.05),
}

RULE_ID_RE = re_compile(
    r"^(?:macro|sector|superinvestor|decision)\.[a-z0-9_]+\."
    r"(?:soft|hard|guard|prior|policy|risk)\.[0-9]{3}$"
)
RULE_PACK_ID_RE = re_compile(
    r"^(?:macro|sector|superinvestor|decision)\.[a-z0-9_]+\.[a-z0-9_]+\.v[1-9][0-9]*$"
)
TARGET_PATH_RE = re_compile(
    r"^/rule_packs/"
    r"(?P<rule_pack_id>(?:macro|sector|superinvestor|decision)\.[a-z0-9_]+\.[a-z0-9_]+\.v[1-9][0-9]*)/"
    r"rules/(?P<rule_id>(?:macro|sector|superinvestor|decision)\.[a-z0-9_]+\.(?:soft|hard|guard|prior|policy|risk)\.[0-9]{3})/"
    r"learnable_parameters/(?P<parameter_name>[a-z][a-z0-9_]*)/value$"
)

ALLOWED_OVERLAP_POLICIES = {
    "non_overlapping",
    "block_bootstrap",
    "stationary_bootstrap",
    "newey_west",
}
ALLOWED_MULTIPLE_TEST_METHODS = {
    "benjamini_hochberg_fdr",
    "bonferroni",
    "holm",
    "deflated_sharpe_ratio",
    "white_reality_check",
    "spa",
}
P0_FROZEN_FIELDS = {
    "hypothesis",
    "rule_ids",
    "parameter_paths",
    "candidate_values",
    "primary_metric",
    "secondary_metrics",
    "data_requirements",
    "sampling_design",
    "validation_design",
    "multiple_testing_control",
    "acceptance_rule",
}


def _as_tuple(values: Sequence[Any]) -> tuple[Any, ...]:
    return tuple(values)


def _ensure_unit_interval(value: float, name: str) -> None:
    if not isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be a finite value in [0, 1]")


def canonical_json_hash(payload: Mapping[str, Any]) -> str:
    """Return ``sha256:<digest>`` for a stable JSON representation."""
    encoded = dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + sha256(encoded).hexdigest()


def validate_rule_id(rule_id: str) -> bool:
    return bool(RULE_ID_RE.fullmatch(rule_id))


def validate_rule_pack_id(rule_pack_id: str) -> bool:
    return bool(RULE_PACK_ID_RE.fullmatch(rule_pack_id))


def validate_target_path(path: str) -> dict[str, Any]:
    match = TARGET_PATH_RE.fullmatch(path)
    if not match:
        return {"valid": False, "reasons": ["target_path is not canonical"]}
    groups = match.groupdict()
    pack_agent = ".".join(groups["rule_pack_id"].split(".")[:2])
    rule_agent = ".".join(groups["rule_id"].split(".")[:2])
    reasons: list[str] = []
    if pack_agent != rule_agent:
        reasons.append("rule_pack_id and rule_id must share agent")
    return {"valid": not reasons, "reasons": tuple(reasons), "agent_id": pack_agent, **groups}


@dataclass(frozen=True)
class MetricProxyAvailability:
    metric_proxy: str
    data_source: str
    point_in_time_available: bool
    history_start: str
    history_end: str
    vintage_handling: str
    restatement_risk: Literal["low", "medium", "high", "unknown"]
    survivorship_bias_risk: Literal["none", "low", "medium", "high", "unknown"]
    timestamp_granularity: Literal["intraday", "daily", "weekly", "monthly", "unknown"]
    known_biases: Sequence[str] = field(default_factory=tuple)
    allowed_for_validation: bool = False
    allowed_for_production: bool = False
    notes: str = ""
    publication_lag_days: int | None = None
    coverage_drift_risk: Literal["low", "medium", "high", "unknown"] = "unknown"

    def gate_failures(self, *, production: bool = False) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.point_in_time_available:
            failures.append(f"{self.metric_proxy}: PIT history unavailable")
        if not self.history_start or not self.history_end:
            failures.append(f"{self.metric_proxy}: history window missing")
        if self.vintage_handling not in {"as_reported", "as_published", "vintage"}:
            failures.append(f"{self.metric_proxy}: vintage handling is not PIT-safe")
        if self.allowed_for_validation is not True:
            failures.append(f"{self.metric_proxy}: not allowed for validation")
        if production and self.allowed_for_production is not True:
            failures.append(f"{self.metric_proxy}: not allowed for production")
        if self.survivorship_bias_risk in {"medium", "high", "unknown"}:
            failures.append(f"{self.metric_proxy}: survivorship bias risk {self.survivorship_bias_risk}")
        if self.coverage_drift_risk in {"medium", "high", "unknown"}:
            failures.append(f"{self.metric_proxy}: coverage drift risk {self.coverage_drift_risk}")
        return tuple(failures)


@dataclass(frozen=True)
class DataAvailabilityMatrix:
    matrix_id: str
    proxies: Mapping[str, MetricProxyAvailability]

    def require(self, metric_proxies: Sequence[str], *, production: bool = False) -> tuple[str, ...]:
        failures: list[str] = []
        for proxy_id in metric_proxies:
            proxy = self.proxies.get(proxy_id)
            if proxy is None:
                failures.append(f"{proxy_id}: missing from data availability matrix")
            else:
                failures.extend(proxy.gate_failures(production=production))
        return tuple(failures)


@dataclass(frozen=True)
class ResearchSourceMetadata:
    source_id: str
    source_type: str
    publish_date: str
    ingest_time: str
    license_status: Literal["approved", "pending_review", "restricted", "prohibited"]
    point_in_time_available: bool
    source_hash: str

    def gate_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        for field_name in (
            "source_id",
            "source_type",
            "publish_date",
            "ingest_time",
            "license_status",
            "source_hash",
        ):
            if not getattr(self, field_name):
                failures.append(f"{field_name} required")
        if self.license_status == "prohibited":
            failures.append("prohibited source cannot be ingested")
        if self.license_status in {"pending_review", "restricted"}:
            failures.append("source restricted to sandbox")
        if not self.point_in_time_available:
            failures.append("source lacks PIT availability")
        if not self.source_hash.startswith("sha256:"):
            failures.append("source_hash must be sha256:<digest>")
        return tuple(failures)


@dataclass(frozen=True)
class SourceGroundedClaim:
    claim_id: str
    source_id: str
    source_span_id: str
    claim_type: str
    claim_text: str
    cause_variables: Sequence[str]
    target_variables: Sequence[str]
    direction: Literal["positive", "negative", "neutral", "ambiguous"]
    expected_horizon_text: str | None = None
    unsupported_fields: Sequence[str] = field(default_factory=tuple)
    extraction_confidence_bin: Literal["high", "medium", "low", "unknown"] = "unknown"
    verifier_status: Literal["pending", "passed", "failed", "requires_review"] = "pending"
    human_review_required: bool = True


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    derived_from_claim_ids: Sequence[str]
    hypothesis_type: str
    statement: str
    not_source_grounded: bool
    requires_validation: bool
    proposed_metric_proxies: Sequence[str]
    status: Literal["draft", "candidate", "validated", "rejected"] = "draft"


@dataclass(frozen=True)
class ClaimCheckResult:
    accepted: bool
    eligible_for_rule_compiler: bool
    reasons: tuple[str, ...]


def verify_source_grounded_claim(
    claim: SourceGroundedClaim,
    *,
    source_spans: Mapping[str, str],
    controlled_variables: set[str],
) -> ClaimCheckResult:
    """Check span grounding and forbid fabricating hypothesis fields as source facts."""
    reasons: list[str] = []
    if not claim.source_span_id:
        reasons.append("source-grounded claim requires source_span_id")
    if claim.source_span_id not in source_spans:
        reasons.append("source_span_id not found")
    elif claim.claim_text.casefold() not in source_spans[claim.source_span_id].casefold():
        reasons.append("claim_text is not supported by source span")
    variables = set(claim.cause_variables) | set(claim.target_variables)
    unknown_variables = variables - controlled_variables
    if unknown_variables:
        reasons.append(f"unknown controlled variables: {sorted(unknown_variables)}")
    if claim.unsupported_fields:
        reasons.append("unsupported fields must be moved to hypothesis layer")
    if claim.verifier_status != "passed":
        reasons.append("verifier_status must pass before rule compilation")
    if claim.direction == "ambiguous":
        reasons.append("ambiguous direction cannot compile without hypothesis validation")
    return ClaimCheckResult(
        accepted=not reasons,
        eligible_for_rule_compiler=not reasons,
        reasons=tuple(reasons),
    )


@dataclass(frozen=True)
class ClaimExtractionGoldSet:
    gold_set_id: str
    sample_size_documents: int
    sample_size_claims: int
    claim_precision: float
    source_span_support_precision: float
    direction_accuracy: float
    variable_mapping_accuracy: float
    unsupported_field_false_grounding_rate: float
    target_accuracy: float = 0.0
    horizon_accuracy: float = 0.0

    def gate_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        if self.sample_size_documents < MIN_CLAIM_GOLD_SET_DOCUMENTS:
            failures.append(f"gold set requires >= {MIN_CLAIM_GOLD_SET_DOCUMENTS} documents")
        if self.sample_size_claims < MIN_CLAIM_GOLD_SET_CLAIMS:
            failures.append(f"gold set requires >= {MIN_CLAIM_GOLD_SET_CLAIMS} claims")
        for metric, (operator, threshold) in CLAIM_GOLD_SET_METRIC_THRESHOLDS.items():
            value = float(getattr(self, metric))
            if operator == ">=" and value < threshold:
                failures.append(f"{metric} below {threshold:.2f}")
            elif operator == "<=" and value > threshold:
                failures.append(f"{metric} above {threshold:.2f}")
        return tuple(failures)

    @property
    def passed(self) -> bool:
        return not self.gate_failures()


@dataclass(frozen=True)
class LearnableParameter:
    value: int | float | str | bool
    type: Literal["integer", "float", "string", "boolean"]
    unit: str | None = None
    min: float | None = None
    max: float | None = None

    def validate_value(self, value: Any | None = None) -> tuple[str, ...]:
        candidate = self.value if value is None else value
        failures: list[str] = []
        if self.type == "integer" and not isinstance(candidate, int):
            failures.append("integer parameter requires int")
        if self.type == "float" and not isinstance(candidate, (int, float)):
            failures.append("float parameter requires number")
        if self.type == "string" and not isinstance(candidate, str):
            failures.append("string parameter requires str")
        if self.type == "boolean" and not isinstance(candidate, bool):
            failures.append("boolean parameter requires bool")
        if isinstance(candidate, (int, float)):
            if self.min is not None and candidate < self.min:
                failures.append("value below min")
            if self.max is not None and candidate > self.max:
                failures.append("value above max")
        return tuple(failures)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    rule_type: Literal["soft", "hard", "guard", "prior", "policy", "risk"]
    status: Literal["candidate", "validated", "paper_trading", "production", "deprecated"]
    source_claim_ids: Sequence[str]
    hypothesis_ids: Sequence[str]
    metric_proxies: Sequence[str]
    mechanism_chain: Sequence[str]
    horizon_days: tuple[int, int]
    learnable_parameters: Mapping[str, LearnableParameter]
    validation_required: bool = True
    validation_status: str = "pending"


@dataclass(frozen=True)
class RulePack:
    rule_pack_id: str
    agent_id: str
    status: Literal["candidate", "validated", "paper_trading", "production"]
    rules: Mapping[str, Rule]

    def gate_failures(
        self,
        *,
        data_matrix: DataAvailabilityMatrix,
        known_claim_ids: set[str],
        known_hypothesis_ids: set[str],
        production: bool = False,
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if not validate_rule_pack_id(self.rule_pack_id):
            failures.append("rule_pack_id is not canonical")
        if not self.rule_pack_id.startswith(f"{self.agent_id}."):
            failures.append("rule_pack_id must start with agent_id")
        for key, rule in self.rules.items():
            if key != rule.rule_id:
                failures.append(f"{key}: rule map key mismatch")
            if not validate_rule_id(rule.rule_id):
                failures.append(f"{rule.rule_id}: rule_id is not canonical")
            if not rule.source_claim_ids:
                failures.append(f"{rule.rule_id}: source_claim_ids required")
            if set(rule.source_claim_ids) - known_claim_ids:
                failures.append(f"{rule.rule_id}: unknown source_claim_ids")
            if set(rule.hypothesis_ids) - known_hypothesis_ids:
                failures.append(f"{rule.rule_id}: unknown hypothesis_ids")
            if not rule.validation_required:
                failures.append(f"{rule.rule_id}: validation_required must be true")
            for name, parameter in rule.learnable_parameters.items():
                for failure in parameter.validate_value():
                    failures.append(f"{rule.rule_id}.{name}: {failure}")
            if rule.horizon_days[0] <= 0 or rule.horizon_days[1] < rule.horizon_days[0]:
                failures.append(f"{rule.rule_id}: invalid horizon")
            failures.extend(data_matrix.require(rule.metric_proxies, production=production))
            if production and rule.validation_status not in {"lockbox_reviewed", "production"}:
                failures.append(f"{rule.rule_id}: production requires lockbox-reviewed validation")
        return tuple(failures)


@dataclass(frozen=True)
class ParameterPrior:
    parameter_proposal_id: str
    agent_id: str
    target_path: str
    current_value: Any
    candidate_values: Sequence[Any]
    prior_source_claim_ids: Sequence[str]
    prior_hypothesis_ids: Sequence[str]
    rationale: str
    validation_required: bool = True
    status: Literal["candidate", "validated", "rejected"] = "candidate"

    def gate_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        target = validate_target_path(self.target_path)
        if not target["valid"]:
            failures.extend(target["reasons"])
        if not self.candidate_values:
            failures.append("candidate_values required")
        if not self.prior_source_claim_ids:
            failures.append("prior_source_claim_ids required")
        if not self.validation_required:
            failures.append("parameter prior must require validation")
        return tuple(failures)


@dataclass(frozen=True)
class ExperimentFamily:
    experiment_family_id: str
    agent_id: str
    rule_group: str
    planned_number_of_tests: int
    multiple_testing_method: str
    max_fdr: float = 0.10

    def gate_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.experiment_family_id:
            failures.append("experiment_family_id required")
        if self.planned_number_of_tests <= 0:
            failures.append("planned_number_of_tests must be positive")
        if self.multiple_testing_method not in ALLOWED_MULTIPLE_TEST_METHODS:
            failures.append("unsupported multiple-testing method")
        _ensure_unit_interval(self.max_fdr, "max_fdr")
        return tuple(failures)


@dataclass(frozen=True)
class PreRegistration:
    registered_at: str
    frozen_spec_hash: str
    frozen_fields: Sequence[str]
    validation_results_seen_before_freeze: bool = False

    @classmethod
    def freeze(cls, *, registered_at: str, spec: Mapping[str, Any]) -> "PreRegistration":
        return cls(
            registered_at=registered_at,
            frozen_spec_hash=canonical_json_hash(spec),
            frozen_fields=tuple(sorted(P0_FROZEN_FIELDS)),
            validation_results_seen_before_freeze=False,
        )

    def gate_failures(self, spec: Mapping[str, Any]) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.registered_at:
            failures.append("registered_at required")
        if set(self.frozen_fields) != P0_FROZEN_FIELDS:
            failures.append("pre-registration frozen fields incomplete")
        if self.validation_results_seen_before_freeze:
            failures.append("validation results were seen before freeze")
        if self.frozen_spec_hash != canonical_json_hash(spec):
            failures.append("frozen_spec_hash does not match current spec")
        return tuple(failures)


@dataclass(frozen=True)
class SamplingDesign:
    signal_unit: Literal["independent_event"]
    horizon_days: int
    overlap_policy: Literal["non_overlapping", "block_bootstrap", "stationary_bootstrap", "newey_west"]
    minimum_effective_n: int
    nominal_n: int
    block_length_days: int | None = None

    def effective_n(self) -> int:
        if self.overlap_policy == "non_overlapping":
            return max(0, self.nominal_n // max(self.horizon_days, 1))
        if self.overlap_policy == "block_bootstrap":
            block = self.block_length_days or self.horizon_days
            return max(0, self.nominal_n // max(block, 1))
        if self.overlap_policy == "stationary_bootstrap":
            block = self.block_length_days or self.horizon_days
            return max(0, int(self.nominal_n / max(block * 0.75, 1)))
        if self.overlap_policy == "newey_west":
            return max(0, int(self.nominal_n / max(self.horizon_days ** 0.5, 1)))
        raise ValueError(f"unsupported overlap_policy: {self.overlap_policy}")

    def gate_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        if self.signal_unit != "independent_event":
            failures.append("sampling must use independent_event")
        if self.overlap_policy not in ALLOWED_OVERLAP_POLICIES:
            failures.append("unsupported overlap policy")
        if self.effective_n() < self.minimum_effective_n:
            failures.append(
                f"effective_n below threshold: {self.effective_n()} < {self.minimum_effective_n}"
            )
        return tuple(failures)


def benjamini_hochberg_q_values(p_values: Sequence[float]) -> tuple[float, ...]:
    if not p_values:
        return tuple()
    indexed = sorted(enumerate(float(p) for p in p_values), key=lambda item: item[1])
    m = len(indexed)
    sorted_q = [0.0] * m
    running_min = 1.0
    for reverse_rank, (_idx, p_value) in enumerate(reversed(indexed), start=1):
        if not isfinite(p_value) or p_value < 0 or p_value > 1:
            raise ValueError("p-values must be in [0, 1]")
        rank = m - reverse_rank + 1
        running_min = min(running_min, p_value * m / rank)
        sorted_q[rank - 1] = min(running_min, 1.0)
    q_values = [0.0] * m
    for rank, (original_idx, _p) in enumerate(indexed):
        q_values[original_idx] = round(sorted_q[rank], 10)
    return tuple(q_values)


@dataclass(frozen=True)
class MultipleTestingControl:
    method: str
    max_fdr: float
    family_p_values: Sequence[float]
    selected_trial_index: int

    @property
    def adjusted_q_value(self) -> float:
        if self.method != "benjamini_hochberg_fdr":
            return 1.0
        return benjamini_hochberg_q_values(self.family_p_values)[self.selected_trial_index]

    def gate_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        if self.method not in ALLOWED_MULTIPLE_TEST_METHODS:
            failures.append("unsupported multiple-testing method")
        if not self.family_p_values:
            failures.append("family_p_values required")
        if self.method == "benjamini_hochberg_fdr" and self.adjusted_q_value > self.max_fdr:
            failures.append("multiple-testing adjusted q-value fails FDR gate")
        return tuple(failures)


@dataclass(frozen=True)
class CostAwareAcceptance:
    primary_metric: str
    gross_alpha: float
    estimated_transaction_cost: float
    slippage: float
    turnover_delta: float
    max_turnover_delta: float
    drawdown_worsening: float
    max_drawdown_worsening: float
    min_net_alpha: float
    calibration_degraded: bool = False

    @property
    def net_alpha_after_cost(self) -> float:
        return self.gross_alpha - self.estimated_transaction_cost - self.slippage

    def gate_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.primary_metric.startswith("net_alpha_after_cost"):
            failures.append("primary metric must be after-cost")
        if self.net_alpha_after_cost <= self.min_net_alpha:
            failures.append("net alpha after cost below threshold")
        if self.turnover_delta > self.max_turnover_delta:
            failures.append("turnover worsened beyond threshold")
        if self.drawdown_worsening > self.max_drawdown_worsening:
            failures.append("drawdown worsened beyond threshold")
        if self.calibration_degraded:
            failures.append("confidence calibration degraded")
        return tuple(failures)


@dataclass(frozen=True)
class ValidationExperimentV2:
    experiment_id: str
    family: ExperimentFamily
    agent_id: str
    rule_ids: Sequence[str]
    parameter_paths: Sequence[str]
    candidate_values: Sequence[Any]
    baseline_version: str
    candidate_version: str
    data_requirements: Sequence[str]
    sampling_design: SamplingDesign
    multiple_testing_control: MultipleTestingControl
    cost_acceptance: CostAwareAcceptance
    pre_registration: PreRegistration
    walk_forward_passed: bool
    lockbox_open_count: int
    lockbox_passed: bool = False
    direct_production_allowed: bool = False

    def frozen_spec(self) -> dict[str, Any]:
        return {
            "hypothesis": f"{self.agent_id} validation for {tuple(self.rule_ids)}",
            "rule_ids": tuple(self.rule_ids),
            "parameter_paths": tuple(self.parameter_paths),
            "candidate_values": tuple(self.candidate_values),
            "primary_metric": self.cost_acceptance.primary_metric,
            "secondary_metrics": ("hit_rate", "calibration_error", "turnover_delta"),
            "data_requirements": tuple(self.data_requirements),
            "sampling_design": {
                "signal_unit": self.sampling_design.signal_unit,
                "horizon_days": self.sampling_design.horizon_days,
                "overlap_policy": self.sampling_design.overlap_policy,
                "minimum_effective_n": self.sampling_design.minimum_effective_n,
            },
            "validation_design": {
                "walk_forward_required": True,
                "lockbox_required_for_final_promotion": True,
                "partial_pooling_required": True,
            },
            "multiple_testing_control": {
                "method": self.multiple_testing_control.method,
                "family_scope": self.family.experiment_family_id,
                "max_fdr": self.multiple_testing_control.max_fdr,
            },
            "acceptance_rule": {
                "primary_metric": self.cost_acceptance.primary_metric,
                "min_net_alpha": self.cost_acceptance.min_net_alpha,
                "cost_model_required": True,
            },
        }


@dataclass(frozen=True)
class ValidationDecision:
    status: Literal["failed", "insufficient_data", "validated", "paper_trading", "production_eligible"]
    paper_trading_allowed: bool
    production_allowed: bool
    failure_reasons: tuple[str, ...]
    report: Mapping[str, Any]


def evaluate_validation_experiment(
    experiment: ValidationExperimentV2,
    *,
    data_matrix: DataAvailabilityMatrix,
) -> ValidationDecision:
    failures: list[str] = []
    failures.extend(experiment.family.gate_failures())
    failures.extend(experiment.pre_registration.gate_failures(experiment.frozen_spec()))
    failures.extend(data_matrix.require(experiment.data_requirements, production=False))
    failures.extend(experiment.sampling_design.gate_failures())
    failures.extend(experiment.multiple_testing_control.gate_failures())
    failures.extend(experiment.cost_acceptance.gate_failures())
    for rule_id in experiment.rule_ids:
        if not validate_rule_id(rule_id):
            failures.append(f"{rule_id}: invalid rule_id")
    for path in experiment.parameter_paths:
        target = validate_target_path(path)
        if not target["valid"]:
            failures.extend(target["reasons"])
    if not experiment.walk_forward_passed:
        failures.append("walk-forward validation did not pass")
    if experiment.lockbox_open_count > 1:
        failures.append("lockbox reused more than once")
    if experiment.direct_production_allowed:
        failures.append("direct production is forbidden in P0")

    status: ValidationDecision.__annotations__["status"] = "failed"
    if any("effective_n below" in reason for reason in failures):
        status = "insufficient_data"
    elif not failures:
        status = "production_eligible" if experiment.lockbox_passed else "paper_trading"
    report = {
        "effective_n": experiment.sampling_design.effective_n(),
        "overlap_policy": experiment.sampling_design.overlap_policy,
        "adjusted_q_value": experiment.multiple_testing_control.adjusted_q_value,
        "net_alpha_after_cost": experiment.cost_acceptance.net_alpha_after_cost,
        "walk_forward_passed": experiment.walk_forward_passed,
        "lockbox_passed": experiment.lockbox_passed,
    }
    return ValidationDecision(
        status=status,
        paper_trading_allowed=not failures and experiment.walk_forward_passed,
        production_allowed=not failures and experiment.lockbox_passed,
        failure_reasons=tuple(failures),
        report=report,
    )


@dataclass(frozen=True)
class RuleFireOutput:
    rule_id: str
    rule_group_id: str
    target_signal: str
    direction: Literal["positive", "negative", "neutral"]
    raw_score_delta: float
    horizon_days: int
    validation_status: Literal["candidate", "validated", "paper_trading", "production"]
    empirical_confidence_bin: Literal["low", "medium", "high"]
    evidence_ids: Sequence[str]
    source_claim_ids: Sequence[str]
    correlated_rule_ids: Sequence[str] = field(default_factory=tuple)
    current_data_confirmed: bool = True
    research_only: bool = False

    @property
    def signed_delta(self) -> float:
        sign = 1.0 if self.direction == "positive" else -1.0 if self.direction == "negative" else 0.0
        return sign * abs(self.raw_score_delta)


@dataclass(frozen=True)
class RuleAggregationPolicy:
    single_rule_max_adjustment: float = 0.05
    rule_group_max_adjustment: float = 0.10
    global_research_adjustment_cap: float = 0.20
    research_only_adjustment_cap: float = 0.05
    conflict_confidence_cap_adjustment: float = -0.10


@dataclass(frozen=True)
class ConflictObject:
    conflict_id: str
    positive_rules: tuple[str, ...]
    negative_rules: tuple[str, ...]
    conflict_type: str
    resolution: str
    confidence_cap_adjustment: float
    actionability_adjustment: str


@dataclass(frozen=True)
class AggregationResult:
    target_signal: str
    horizon_days: int
    group_deltas: Mapping[str, float]
    final_research_delta: float
    conflict_objects: tuple[ConflictObject, ...]
    evidence_clusters: Mapping[str, tuple[str, ...]]


def _robust_group_delta(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    if len(values) <= 2:
        return sum(values) / len(values)
    med = median(values)
    kept = [value for _distance, value in sorted((abs(v - med), v) for v in values)[:-1]]
    return sum(kept) / len(kept)


def aggregate_rule_outputs(
    rules: Sequence[RuleFireOutput],
    *,
    target_signal: str,
    horizon_days: int,
    policy: RuleAggregationPolicy = RuleAggregationPolicy(),
) -> AggregationResult:
    selected = [
        rule for rule in rules if rule.target_signal == target_signal and rule.horizon_days == horizon_days
    ]
    group_values: dict[str, list[float]] = {}
    evidence_clusters: dict[str, set[str]] = {}
    positive: list[str] = []
    negative: list[str] = []
    for rule in selected:
        cap = policy.single_rule_max_adjustment
        if rule.research_only or not rule.current_data_confirmed:
            cap = min(cap, policy.research_only_adjustment_cap)
        delta = max(-cap, min(cap, rule.signed_delta))
        group_values.setdefault(rule.rule_group_id, []).append(delta)
        evidence_clusters.setdefault(rule.rule_group_id, set()).update(rule.evidence_ids)
        if delta > 0:
            positive.append(rule.rule_id)
        elif delta < 0:
            negative.append(rule.rule_id)
    group_deltas = {
        group: max(
            -policy.rule_group_max_adjustment,
            min(policy.rule_group_max_adjustment, _robust_group_delta(values)),
        )
        for group, values in group_values.items()
    }
    raw_total = sum(group_deltas.values())
    final = max(
        -policy.global_research_adjustment_cap,
        min(policy.global_research_adjustment_cap, raw_total),
    )
    conflicts: list[ConflictObject] = []
    if positive and negative:
        conflicts.append(
            ConflictObject(
                conflict_id=f"CONFLICT-{target_signal}-{horizon_days}",
                positive_rules=tuple(positive),
                negative_rules=tuple(negative),
                conflict_type="opposing_rules_same_signal_horizon",
                resolution="net_adjustment_and_reduce_confidence_cap",
                confidence_cap_adjustment=policy.conflict_confidence_cap_adjustment,
                actionability_adjustment="downgrade_to_watchlist",
            )
        )
    return AggregationResult(
        target_signal=target_signal,
        horizon_days=horizon_days,
        group_deltas=group_deltas,
        final_research_delta=final,
        conflict_objects=tuple(conflicts),
        evidence_clusters={k: tuple(sorted(v)) for k, v in evidence_clusters.items()},
    )


@dataclass(frozen=True)
class ConfidenceComponents:
    data_confidence: float
    research_weight_confidence: float
    empirical_validation_confidence: float
    method_tool_confidence: float
    regime_match_confidence: float

    def __post_init__(self) -> None:
        for name in (
            "data_confidence",
            "research_weight_confidence",
            "empirical_validation_confidence",
            "method_tool_confidence",
            "regime_match_confidence",
        ):
            _ensure_unit_interval(float(getattr(self, name)), name)


@dataclass(frozen=True)
class ConfidenceResult:
    pre_cap_confidence: float
    final_confidence: float
    confidence_bucket: Literal["very_low", "low", "medium_low", "medium", "high"]
    actionability: Literal["no_trade", "monitor_only", "watchlist_or_tiny_tilt", "modest_tilt", "risk_approval_required"]
    cap_reasons: tuple[str, ...]


def _confidence_bucket(value: float) -> str:
    if value < 0.45:
        return "very_low"
    if value < 0.55:
        return "low"
    if value < 0.65:
        return "medium_low"
    if value < 0.75:
        return "medium"
    return "high"


def compute_confidence_v1(
    components: ConfidenceComponents,
    *,
    confidence_cap: float = 1.0,
    current_data_confirmed: bool,
    risk_approval: bool = False,
) -> ConfidenceResult:
    _ensure_unit_interval(confidence_cap, "confidence_cap")
    cap = confidence_cap
    reasons: list[str] = []
    data_confidence = components.data_confidence
    if not current_data_confirmed:
        data_confidence = min(data_confidence, 0.50)
        cap = min(cap, 0.50)
        reasons.append("current data confirmation absent")
    pre_cap = min(
        data_confidence,
        components.research_weight_confidence,
        components.empirical_validation_confidence,
        components.method_tool_confidence,
        components.regime_match_confidence,
    )
    final = min(pre_cap, cap)
    if final < 0.55:
        actionability = "no_trade" if not current_data_confirmed else "monitor_only"
    elif final < 0.65:
        actionability = "watchlist_or_tiny_tilt" if current_data_confirmed else "monitor_only"
    elif final < 0.75:
        actionability = "modest_tilt" if current_data_confirmed else "watchlist_or_tiny_tilt"
    else:
        actionability = "risk_approval_required" if not risk_approval else "modest_tilt"
    return ConfidenceResult(
        pre_cap_confidence=round(pre_cap, 6),
        final_confidence=round(final, 6),
        confidence_bucket=_confidence_bucket(final),
        actionability=actionability,
        cap_reasons=tuple(reasons),
    )


def check_research_only_actionability(
    *,
    research_only: bool,
    current_data_confirmed: bool,
    actionability: str,
) -> tuple[str, ...]:
    if research_only and not current_data_confirmed and actionability not in {"no_trade", "monitor_only"}:
        return ("research-only rule without current data must not be actionable",)
    return tuple()


def build_central_bank_p0_mvp() -> dict[str, Any]:
    """Build deterministic P0 seed objects for the central_bank liquidity MVP."""
    matrix = DataAvailabilityMatrix(
        matrix_id="DAM-CB-P0-2026Q2",
        proxies={
            "pboc_net_injection_7d": MetricProxyAvailability(
                metric_proxy="pboc_net_injection_7d",
                data_source="official_pboc_omo",
                point_in_time_available=True,
                history_start="2015-01-01",
                history_end="2026-06-05",
                vintage_handling="as_published",
                restatement_risk="low",
                survivorship_bias_risk="none",
                timestamp_granularity="daily",
                allowed_for_validation=True,
                allowed_for_production=True,
                coverage_drift_risk="low",
            ),
            "risk_appetite_proxy": MetricProxyAvailability(
                metric_proxy="risk_appetite_proxy",
                data_source="qlib_pit_sector_style_returns",
                point_in_time_available=True,
                history_start="2005-01-01",
                history_end="2026-06-05",
                vintage_handling="as_reported",
                restatement_risk="low",
                survivorship_bias_risk="low",
                timestamp_granularity="daily",
                allowed_for_validation=True,
                allowed_for_production=True,
                coverage_drift_risk="low",
            ),
        },
    )
    claim = SourceGroundedClaim(
        claim_id="CLAIM-CB-20260605-0001",
        source_id="SRC-CB-20260605-0001",
        source_span_id="PAGE-1-PARA-1",
        claim_type="causal_mechanism",
        claim_text="PBOC liquidity injections can ease short-term liquidity pressure.",
        cause_variables=("pboc_net_injection",),
        target_variables=("short_term_liquidity_pressure",),
        direction="positive",
        verifier_status="passed",
        human_review_required=False,
        extraction_confidence_bin="medium",
    )
    hypothesis = Hypothesis(
        hypothesis_id="HYP-CB-20260605-0001",
        derived_from_claim_ids=(claim.claim_id,),
        hypothesis_type="market_transmission",
        statement="A confirmed liquidity impulse can support short-horizon risk appetite.",
        not_source_grounded=True,
        requires_validation=True,
        proposed_metric_proxies=("pboc_net_injection_7d", "risk_appetite_proxy"),
        status="candidate",
    )
    rule = Rule(
        rule_id="macro.central_bank.soft.001",
        rule_type="soft",
        status="candidate",
        source_claim_ids=(claim.claim_id,),
        hypothesis_ids=(hypothesis.hypothesis_id,),
        metric_proxies=("pboc_net_injection_7d", "risk_appetite_proxy"),
        mechanism_chain=(
            "pboc_net_injection",
            "short_term_liquidity_pressure",
            "risk_appetite_proxy",
        ),
        horizon_days=(20, 20),
        learnable_parameters={
            "net_injection_window_days": LearnableParameter(
                value=7,
                type="integer",
                unit="trading_day",
                min=3,
                max=20,
            )
        },
    )
    rule_pack = RulePack(
        rule_pack_id="macro.central_bank.liquidity.v1",
        agent_id="macro.central_bank",
        status="candidate",
        rules={rule.rule_id: rule},
    )
    target_path = (
        "/rule_packs/macro.central_bank.liquidity.v1/rules/"
        "macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value"
    )
    parameter_prior = ParameterPrior(
        parameter_proposal_id="PARAM-CB-20260605-0001",
        agent_id="macro.central_bank",
        target_path=target_path,
        current_value=7,
        candidate_values=(5, 7, 10, 20),
        prior_source_claim_ids=(claim.claim_id,),
        prior_hypothesis_ids=(hypothesis.hypothesis_id,),
        rationale="Liquidity effect should be confirmed over a short window before validation.",
    )
    family = ExperimentFamily(
        experiment_family_id="FAM-CB-LIQUIDITY-2026Q2",
        agent_id="macro.central_bank",
        rule_group="liquidity_impulse",
        planned_number_of_tests=4,
        multiple_testing_method="benjamini_hochberg_fdr",
    )
    sampling = SamplingDesign(
        signal_unit="independent_event",
        horizon_days=20,
        overlap_policy="block_bootstrap",
        minimum_effective_n=60,
        nominal_n=1600,
        block_length_days=20,
    )
    mtc = MultipleTestingControl(
        method="benjamini_hochberg_fdr",
        max_fdr=0.10,
        family_p_values=(0.003, 0.04, 0.08, 0.20),
        selected_trial_index=0,
    )
    cost = CostAwareAcceptance(
        primary_metric="net_alpha_after_cost_20d",
        gross_alpha=0.018,
        estimated_transaction_cost=0.003,
        slippage=0.002,
        turnover_delta=0.08,
        max_turnover_delta=0.20,
        drawdown_worsening=0.01,
        max_drawdown_worsening=0.02,
        min_net_alpha=0.005,
    )
    spec_seed = {
        "hypothesis": f"macro.central_bank validation for {tuple((rule.rule_id,))}",
        "rule_ids": (rule.rule_id,),
        "parameter_paths": (target_path,),
        "candidate_values": parameter_prior.candidate_values,
        "primary_metric": cost.primary_metric,
        "secondary_metrics": ("hit_rate", "calibration_error", "turnover_delta"),
        "data_requirements": rule.metric_proxies,
        "sampling_design": {
            "signal_unit": sampling.signal_unit,
            "horizon_days": sampling.horizon_days,
            "overlap_policy": sampling.overlap_policy,
            "minimum_effective_n": sampling.minimum_effective_n,
        },
        "validation_design": {
            "walk_forward_required": True,
            "lockbox_required_for_final_promotion": True,
            "partial_pooling_required": True,
        },
        "multiple_testing_control": {
            "method": mtc.method,
            "family_scope": family.experiment_family_id,
            "max_fdr": mtc.max_fdr,
        },
        "acceptance_rule": {
            "primary_metric": cost.primary_metric,
            "min_net_alpha": cost.min_net_alpha,
            "cost_model_required": True,
        },
    }
    prereg = PreRegistration.freeze(registered_at="2026-06-05T11:00:00+09:00", spec=spec_seed)
    experiment = ValidationExperimentV2(
        experiment_id="EXP-CB-20260605-0001",
        family=family,
        agent_id="macro.central_bank",
        rule_ids=(rule.rule_id,),
        parameter_paths=(target_path,),
        candidate_values=parameter_prior.candidate_values,
        baseline_version="prompt-ir-0.3.1",
        candidate_version="prompt-ir-0.3.2-exp",
        data_requirements=rule.metric_proxies,
        sampling_design=sampling,
        multiple_testing_control=mtc,
        cost_acceptance=cost,
        pre_registration=prereg,
        walk_forward_passed=True,
        lockbox_open_count=0,
        lockbox_passed=False,
        direct_production_allowed=False,
    )
    return {
        "data_matrix": matrix,
        "claim": claim,
        "hypothesis": hypothesis,
        "rule_pack": rule_pack,
        "parameter_prior": parameter_prior,
        "experiment": experiment,
    }
