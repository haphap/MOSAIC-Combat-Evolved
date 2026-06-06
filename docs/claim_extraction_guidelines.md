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

## Candidate Claims

Candidate claims are reviewer aids, not accepted labels.

The deterministic generator writes:

- `registry/gold_sets/tushare_research_reports.candidate_claims.jsonl`
- `registry/gold_sets/tushare_research_reports.candidate_claims.summary.json`

Each candidate claim must include:

- `claim_id` matching the gold-set review row;
- `source_id` and `source_span_id`;
- source span offsets and `source_text_hash`;
- proposed `claim_type`, `direction`, `cause_variables`, and `target_variables`;
- `verifier_status = requires_review`;
- review risk flags.

The generator may populate `proposed_*` fields in
`registry/gold_sets/tushare_research_reports.review_template.jsonl`, but it must
not fill any manual review field.

Manual fields are:

- `manual_claim_text`
- `claim_correct`
- `source_span_supports_claim`
- `direction_correct`
- `variable_mapping_correct`
- `unsupported_field_false_grounded`
- `reviewer`
- `review_date`
- `review_notes`

## Manual Import

Human labels are imported with:

```bash
mosaic-rke prepare-gold-review --root . --full
mosaic-rke apply-gold-review --root . \
  --input registry/review_batches/gold_set_full_reviewed.jsonl \
  --dry-run
```

Use `--dry-run` to validate without mutating the template.

For review triage, run `mosaic-rke review-batches --root .` and inspect
`registry/review_batches/gold_set_review_workbook.md`. The workbook is a
read-only checklist: it lists pending claim IDs, row hashes, source offsets,
variables, risk flags, and short claim previews, but it must not be edited or
used as an import file.

The import is accepted only when the whole batch passes:

- every `claim_id` exists in the target review template;
- no duplicate `claim_id`;
- all boolean review fields are booleans;
- `manual_claim_text`, `reviewer`, and `review_date` are present.

On success, downstream summaries and completion audit are recomputed. C02 passes
only after the manual metrics satisfy the gold-set gate.
