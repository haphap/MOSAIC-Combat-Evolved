"""Rule-pack compiler pipeline component."""

from __future__ import annotations

from typing import Mapping, Sequence

from ..p0 import (
    DataAvailabilityMatrix,
    Hypothesis,
    LearnableParameter,
    Rule,
    RulePack,
    SourceGroundedClaim,
)


def compile_rule_pack(
    *,
    rule_pack_id: str,
    agent_id: str,
    rule_id: str,
    claims: Sequence[SourceGroundedClaim],
    hypotheses: Sequence[Hypothesis],
    metric_proxies: Sequence[str],
    mechanism_chain: Sequence[str],
    horizon_days: tuple[int, int],
    learnable_parameters: Mapping[str, LearnableParameter],
    data_matrix: DataAvailabilityMatrix,
) -> RulePack:
    if not claims:
        raise ValueError("at least one source-grounded claim is required")
    failed_claims = tuple(claim.claim_id for claim in claims if claim.verifier_status != "passed")
    if failed_claims:
        raise ValueError(f"claims must pass verifier before compilation: {failed_claims}")
    data_failures = data_matrix.require(metric_proxies, production=False)
    if data_failures:
        raise ValueError(f"metric proxies are not validation-ready: {data_failures}")
    rule = Rule(
        rule_id=rule_id,
        rule_type="soft",
        status="candidate",
        source_claim_ids=tuple(claim.claim_id for claim in claims),
        hypothesis_ids=tuple(hypothesis.hypothesis_id for hypothesis in hypotheses),
        metric_proxies=tuple(metric_proxies),
        mechanism_chain=tuple(mechanism_chain),
        horizon_days=horizon_days,
        learnable_parameters=dict(learnable_parameters),
        validation_required=True,
        validation_status="pending",
    )
    rule_pack = RulePack(
        rule_pack_id=rule_pack_id,
        agent_id=agent_id,
        status="candidate",
        rules={rule.rule_id: rule},
    )
    failures = rule_pack.gate_failures(
        data_matrix=data_matrix,
        known_claim_ids={claim.claim_id for claim in claims},
        known_hypothesis_ids={hypothesis.hypothesis_id for hypothesis in hypotheses},
    )
    if failures:
        raise ValueError(f"compiled rule pack failed gates: {failures}")
    return rule_pack
