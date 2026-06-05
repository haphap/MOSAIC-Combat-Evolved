"""Claim extraction pipeline component."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

from ..p0 import Hypothesis, SourceGroundedClaim
from .research_ingestor import IngestedDocument


@dataclass(frozen=True)
class ClaimAnnotation:
    claim_id: str
    source_span_id: str
    claim_type: str
    claim_text: str
    cause_variables: Sequence[str]
    target_variables: Sequence[str]
    direction: Literal["positive", "negative", "neutral", "ambiguous"]
    expected_horizon_text: str | None = None
    extraction_confidence_bin: Literal["high", "medium", "low", "unknown"] = "unknown"
    hypothesis_id: str | None = None
    hypothesis_type: str | None = None
    hypothesis_statement: str | None = None
    hypothesis_metric_proxies: Sequence[str] = field(default_factory=tuple)


def extract_claims_from_annotations(
    document: IngestedDocument,
    annotations: Sequence[ClaimAnnotation],
) -> tuple[tuple[SourceGroundedClaim, ...], tuple[Hypothesis, ...]]:
    """Build claim/hypothesis objects from explicit annotations.

    Unsupported explanatory additions are kept in ``Hypothesis`` objects and
    are never written into source-grounded claim fields.
    """
    claims: list[SourceGroundedClaim] = []
    hypotheses: list[Hypothesis] = []
    known_spans = document.source_spans
    for annotation in annotations:
        unsupported_fields: tuple[str, ...] = tuple()
        if annotation.source_span_id not in known_spans:
            unsupported_fields = ("source_span_id",)
        claim = SourceGroundedClaim(
            claim_id=annotation.claim_id,
            source_id=document.metadata.source_id,
            source_span_id=annotation.source_span_id,
            claim_type=annotation.claim_type,
            claim_text=annotation.claim_text,
            cause_variables=tuple(annotation.cause_variables),
            target_variables=tuple(annotation.target_variables),
            direction=annotation.direction,
            expected_horizon_text=annotation.expected_horizon_text,
            unsupported_fields=unsupported_fields,
            extraction_confidence_bin=annotation.extraction_confidence_bin,
            verifier_status="pending",
            human_review_required=True,
        )
        claims.append(claim)
        if annotation.hypothesis_statement:
            hypotheses.append(
                Hypothesis(
                    hypothesis_id=annotation.hypothesis_id or f"HYP-{annotation.claim_id}",
                    derived_from_claim_ids=(annotation.claim_id,),
                    hypothesis_type=annotation.hypothesis_type or "derived_mechanism",
                    statement=annotation.hypothesis_statement,
                    not_source_grounded=True,
                    requires_validation=True,
                    proposed_metric_proxies=tuple(annotation.hypothesis_metric_proxies),
                    status="draft",
                )
            )
    return tuple(claims), tuple(hypotheses)
