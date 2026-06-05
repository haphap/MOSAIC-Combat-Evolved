"""Mutation-planner pipeline component."""

from __future__ import annotations

from typing import Any

from ..governance import MutationProposal
from ..p0 import ParameterPrior, ValidationDecision


def plan_parameter_update(
    *,
    mutation_id: str,
    source_experiment_id: str,
    parameter_prior: ParameterPrior,
    validation_decision: ValidationDecision,
    selected_value: Any,
    risk: str,
) -> MutationProposal:
    if not validation_decision.paper_trading_allowed:
        raise ValueError("parameter mutation requires paper-trading-eligible validation")
    if selected_value not in parameter_prior.candidate_values:
        raise ValueError("selected_value must come from parameter prior candidate_values")
    if selected_value == parameter_prior.current_value:
        raise ValueError("selected_value must differ from current_value")
    return MutationProposal(
        mutation_id=mutation_id,
        proposal_type="parameter_update",
        agent_id=parameter_prior.agent_id,
        target_path=parameter_prior.target_path,
        operation="replace",
        old_value=parameter_prior.current_value,
        new_value=selected_value,
        source_experiment_id=source_experiment_id,
        expected_effect={
            "primary_metric": "net_alpha_after_cost_20d",
            "direction": "increase",
            "net_alpha_after_cost": validation_decision.report["net_alpha_after_cost"],
        },
        risk=risk,
        rollback_condition={
            "metric": "live_net_alpha_after_cost_20d",
            "delta_lt": -0.02,
            "window_trading_days": 60,
        },
    )
