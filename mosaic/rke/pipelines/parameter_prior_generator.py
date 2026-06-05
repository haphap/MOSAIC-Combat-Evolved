"""Parameter-prior generator pipeline component."""

from __future__ import annotations

from typing import Any, Sequence

from ..p0 import ParameterPrior, RulePack


def generate_parameter_prior(
    *,
    parameter_proposal_id: str,
    rule_pack: RulePack,
    rule_id: str,
    parameter_name: str,
    candidate_values: Sequence[Any],
    rationale: str,
) -> ParameterPrior:
    rule = rule_pack.rules[rule_id]
    parameter = rule.learnable_parameters[parameter_name]
    candidates = tuple(candidate_values)
    if parameter.value not in candidates:
        candidates = (parameter.value, *candidates)
    failures: list[str] = []
    for value in candidates:
        failures.extend(parameter.validate_value(value))
    if failures:
        raise ValueError(f"candidate values failed parameter type gates: {tuple(failures)}")
    target_path = (
        f"/rule_packs/{rule_pack.rule_pack_id}/rules/{rule.rule_id}/learnable_parameters/"
        f"{parameter_name}/value"
    )
    prior = ParameterPrior(
        parameter_proposal_id=parameter_proposal_id,
        agent_id=rule_pack.agent_id,
        target_path=target_path,
        current_value=parameter.value,
        candidate_values=candidates,
        prior_source_claim_ids=tuple(rule.source_claim_ids),
        prior_hypothesis_ids=tuple(rule.hypothesis_ids),
        rationale=rationale,
        validation_required=True,
        status="candidate",
    )
    prior_failures = prior.gate_failures()
    if prior_failures:
        raise ValueError(f"parameter prior failed gates: {prior_failures}")
    return prior
