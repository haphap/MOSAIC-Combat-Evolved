"""Span-grounded verifier pipeline component."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from ..p0 import ClaimCheckResult, SourceGroundedClaim, verify_source_grounded_claim


@dataclass(frozen=True)
class SpanVerificationBatch:
    claims: tuple[SourceGroundedClaim, ...]
    results: Mapping[str, ClaimCheckResult]

    @property
    def passed_claim_ids(self) -> set[str]:
        return {claim_id for claim_id, result in self.results.items() if result.accepted}


def verify_claim_batch(
    claims: Sequence[SourceGroundedClaim],
    *,
    source_spans: Mapping[str, str],
    controlled_variables: set[str],
) -> SpanVerificationBatch:
    verified_claims: list[SourceGroundedClaim] = []
    results: dict[str, ClaimCheckResult] = {}
    for claim in claims:
        provisional = replace(claim, verifier_status="passed")
        result = verify_source_grounded_claim(
            provisional,
            source_spans=source_spans,
            controlled_variables=controlled_variables,
        )
        status = "passed" if result.accepted else "failed"
        verified = replace(provisional, verifier_status=status, human_review_required=not result.accepted)
        verified_claims.append(verified)
        results[claim.claim_id] = result
    return SpanVerificationBatch(claims=tuple(verified_claims), results=results)
