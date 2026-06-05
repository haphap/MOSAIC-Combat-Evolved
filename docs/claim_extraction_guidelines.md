# RKE Claim Extraction Guidelines

Claim extraction must preserve the boundary between source text and research
hypothesis.

## Source-Grounded Claim

A field may be marked source-grounded only when the cited span directly
supports it.

Required fields:

- `claim_id`
- `source_id`
- `source_span_id`
- `claim_type`
- `claim_text`
- `cause_variables`
- `target_variables`
- `direction`
- `verifier_status`

Before rule compilation:

- `claim_text` must appear in the cited source span.
- variables must be in the controlled vocabulary;
- `verifier_status` must be `passed`;
- unsupported fields must be empty.

## Hypothesis

Any inference that is not directly stated in the source must be stored as a
`Hypothesis`.

Examples:

- market transmission mechanisms inferred from a report;
- failure modes;
- parameter-window suggestions;
- regime conditions not stated in the span.

Hypotheses require validation and cannot be promoted as source-grounded facts.

## Gold Set Gate

Broad rollout requires a manual gold set to pass:

- at least 50 documents;
- at least 500 claims;
- claim precision at least 0.85;
- span-support precision at least 0.90;
- direction accuracy at least 0.85;
- variable mapping accuracy at least 0.80;
- false grounding of unsupported fields at most 0.05.
