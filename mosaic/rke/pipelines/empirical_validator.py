"""Empirical-validation pipeline component."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..p0 import DataAvailabilityMatrix, ValidationDecision, ValidationExperimentV2, evaluate_validation_experiment


@dataclass(frozen=True)
class ValidationReport:
    experiment_id: str
    decision: ValidationDecision
    hardened_metrics: Mapping[str, Any]

    @property
    def paper_trading_ready(self) -> bool:
        return self.decision.paper_trading_allowed


def run_empirical_validation(
    experiment: ValidationExperimentV2,
    *,
    data_matrix: DataAvailabilityMatrix,
) -> ValidationReport:
    decision = evaluate_validation_experiment(experiment, data_matrix=data_matrix)
    metrics = {
        "effective_n": decision.report["effective_n"],
        "overlap_policy": decision.report["overlap_policy"],
        "multiple_testing_adjusted_q_value": decision.report["adjusted_q_value"],
        "net_alpha_after_cost": decision.report["net_alpha_after_cost"],
        "walk_forward_passed": decision.report["walk_forward_passed"],
        "lockbox_passed": decision.report["lockbox_passed"],
        "paper_trading_allowed": decision.paper_trading_allowed,
        "production_allowed": decision.production_allowed,
        "failure_reasons": decision.failure_reasons,
    }
    return ValidationReport(
        experiment_id=experiment.experiment_id,
        decision=decision,
        hardened_metrics=metrics,
    )
