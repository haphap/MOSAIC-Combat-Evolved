# RKE Operator Handoff

- Next state: staged_production
- Paper trading allowed: true
- Staged production allowed: true
- Production allowed: false
- Direct production forbidden: true

- Manual review runbook: registry/review_batches/manual_review_runbook.md

## Run Order

- review-progress-preflight
- prepare-gold-review
- write-gold-review-evidence
- fill-gold-review
- dry-run-gold-review
- apply-gold-review
- prepare-footprint-review
- write-footprint-review-assist
- write-footprint-review-evidence
- fill-footprint-review
- dry-run-footprint-review
- apply-footprint-review
- promotion-status-before-lockbox
- prepare-lockbox-review
- fill-lockbox-review
- dry-run-lockbox-review
- promotion-dry-run
- apply-lockbox-review
- promotion-status-final

Dry-run command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke promotion-dry-run --root . --gold-input registry/review_batches/gold_set_full_reviewed.jsonl --footprint-input registry/report_intelligence/analytical_footprint_reviewed.jsonl --lockbox-input registry/review_batches/lockbox_reviewed.json`

## Command Sequence

### review-progress-preflight

- Phase: preflight
- Action: Inspect the next manual-gate action queue.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke review-progress --root . --actions-only --no-write`
- Manual input: none
- Expected result: Shows current next actions without writing artifacts or applying reviewer decisions.

### prepare-gold-review

- Phase: gold_set
- Action: Write the full gold-set import starter and workbook.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-gold-review --root . --full`
- Manual input: none
- Expected result: Reviewer scratch target is registry/review_batches/gold_set_full_reviewed.jsonl.

### write-gold-review-evidence

- Phase: gold_set
- Action: Write private gold-set evidence draft files.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke write-gold-review-evidence --root . --limit 50 --offset 0 --review-input registry/review_batches/gold_set_reviewed.jsonl`
- Manual input: none
- Expected result: Private evidence Markdown is registry/review_batches/gold_set_review_evidence.md and evidence JSONL is registry/review_batches/gold_set_review_evidence.jsonl.

### fill-gold-review

- Phase: gold_set
- Action: Fill the gold-set reviewed scratch file.
- Command: manual
- Manual input: registry/review_batches/gold_set_full_reviewed.jsonl
- Expected result: All current claim rows have required manual fields and preserved provenance hashes.

### dry-run-gold-review

- Phase: gold_set
- Action: Validate the reviewed gold-set scratch file.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl --dry-run`
- Manual input: registry/review_batches/gold_set_full_reviewed.jsonl
- Expected result: Import is accepted and gold-set quality thresholds pass.

### apply-gold-review

- Phase: gold_set
- Action: Apply accepted gold-set review decisions.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl`
- Manual input: registry/review_batches/gold_set_full_reviewed.jsonl
- Expected result: Gold-set summaries and downstream gates are recomputed.

### prepare-footprint-review

- Phase: footprint_review
- Action: Write the analytical-footprint review starter.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-footprint-review --root . --output registry/report_intelligence/analytical_footprint_reviewed.jsonl --overwrite`
- Manual input: none
- Expected result: Reviewer scratch target is registry/report_intelligence/analytical_footprint_reviewed.jsonl.

### write-footprint-review-assist

- Phase: footprint_review
- Action: Write private analytical-footprint review assist files.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Manual input: none
- Expected result: Private workbook is registry/report_intelligence/analytical_footprint_review_workbook.md and JSONL assist is registry/report_intelligence/analytical_footprint_review_assist.jsonl.

### write-footprint-review-evidence

- Phase: footprint_review
- Action: Write private analytical-footprint evidence draft files.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Manual input: none
- Expected result: Private evidence Markdown is registry/report_intelligence/analytical_footprint_review_evidence.md and evidence JSONL is registry/report_intelligence/analytical_footprint_review_evidence.jsonl.

### fill-footprint-review

- Phase: footprint_review
- Action: Fill the analytical-footprint reviewed scratch file.
- Command: manual
- Manual input: registry/report_intelligence/analytical_footprint_reviewed.jsonl
- Expected result: All footprint rows have required manual fields and preserved provenance hashes.

### dry-run-footprint-review

- Phase: footprint_review
- Action: Validate the reviewed analytical-footprint scratch file.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl --dry-run`
- Manual input: registry/report_intelligence/analytical_footprint_reviewed.jsonl
- Expected result: Import is accepted and footprint quality thresholds pass.

### apply-footprint-review

- Phase: footprint_review
- Action: Apply accepted analytical-footprint review decisions.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl`
- Manual input: registry/report_intelligence/analytical_footprint_reviewed.jsonl
- Expected result: Footprint summaries and downstream gates are recomputed.

### promotion-status-before-lockbox

- Phase: promotion
- Action: Confirm only the final lockbox gate remains before opening it.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke promotion-status --root . --no-write`
- Manual input: none
- Expected result: Gold-set, footprint, and source-license criteria pass; lockbox remains not opened.

### prepare-lockbox-review

- Phase: lockbox
- Action: Write the one-time lockbox review starter.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-lockbox-review --root .`
- Manual input: none
- Expected result: Reviewer scratch target is registry/review_batches/lockbox_reviewed.json.

### fill-lockbox-review

- Phase: lockbox
- Action: Fill the one-time lockbox review scratch file.
- Command: manual
- Manual input: registry/review_batches/lockbox_reviewed.json
- Expected result: Lockbox result, open count, post-open flags, and hashes are complete.

### dry-run-lockbox-review

- Phase: lockbox
- Action: Validate the signed lockbox review.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json --dry-run`
- Manual input: registry/review_batches/lockbox_reviewed.json
- Expected result: Lockbox import is accepted and production decision is eligible.

### promotion-dry-run

- Phase: promotion
- Action: Simulate the complete reviewed bundle before final apply.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke promotion-dry-run --root . --gold-input registry/review_batches/gold_set_full_reviewed.jsonl --footprint-input registry/report_intelligence/analytical_footprint_reviewed.jsonl --lockbox-input registry/review_batches/lockbox_reviewed.json`
- Manual input: none
- Expected result: Simulation accepts all required reviewed inputs without mutating the original registry.

### apply-lockbox-review

- Phase: lockbox
- Action: Apply the accepted one-time lockbox review.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json`
- Manual input: registry/review_batches/lockbox_reviewed.json
- Expected result: Lockbox review is recorded and downstream promotion gates are recomputed.

### promotion-status-final

- Phase: promotion
- Action: Inspect final staged-promotion state.
- Command: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke promotion-status --root . --no-write`
- Manual input: none
- Expected result: Promotion status reflects the applied manual reviews and lockbox decision.

## Gates

### PG02 gold_set

- Passed: true
- Blocker: none
- Evidence: 125 / 125 gold-set claims reviewed
- Review packet: registry/gold_sets/tushare_research_reports.review_packet.json
- Review workbook: registry/review_batches/gold_set_review_workbook.md
- Import template: registry/review_batches/gold_set_next_import_template.jsonl
- Full import template: registry/review_batches/gold_set_full_import_template.jsonl
- Policy template: none
- Reviewed policy/input: registry/review_batches/gold_set_full_reviewed.jsonl
- Prepare: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-gold-review --root . --full`
- Pending rows: 0
- Exported rows: 0
- Review aids: policy: private_review_aids_only_not_import_files; fill_import_path: registry/review_batches/gold_set_reviewed.jsonl; promotion_import_path: registry/review_batches/gold_set_full_reviewed.jsonl; assist_jsonl: registry/review_batches/gold_set_review_assist.jsonl; assist_markdown: registry/review_batches/gold_set_review_assist.md; evidence_jsonl: registry/review_batches/gold_set_review_evidence.jsonl; evidence_markdown: registry/review_batches/gold_set_review_evidence.md; batch_workbook_markdown: registry/review_batches/gold_set_review_workbook.md
- Field contract: policy: human_decisions_only_preserve_ids_hashes_and_context_refs; required_fields: manual_claim_text, claim_correct, source_span_supports_claim, direction_correct, target_correct, horizon_correct, variable_mapping_correct, unsupported_field_false_grounded, reviewer, review_date; optional_fields: review_notes; boolean_fields: claim_correct, source_span_supports_claim, direction_correct, target_correct, horizon_correct, variable_mapping_correct, unsupported_field_false_grounded; boolean_allowed_values: true, false; date_fields: review_date=YYYY-MM-DD; text_fields: manual_claim_text, reviewer, review_notes; preserve_fields: claim_id, target_row_hash, review_context_ref, target_review_path
- Batch overview: batch_count: 0; pending_rows: 0; rerun_review_progress_after_batch_apply: false
- Dry run: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl --dry-run`
- Apply: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl`
- Note: Run prepare-gold-review --full, fill the reviewed scratch JSONL, use registry/review_batches/gold_set_review_workbook.md as the read-only claim checklist, and use registry/review_batches/gold_set_review_assist.md as non-import machine assistance, use registry/review_batches/gold_set_review_evidence.md as private source evidence draft, then dry-run before applying the gold set. For batch work, prepare registry/review_batches/gold_set_reviewed.jsonl with --gold-batch-size/--offset, dry-run it, and apply accepted batches to accumulate progress.

### RI-FOOTPRINT-REVIEW footprint_review

- Passed: true
- Blocker: analytical-footprint review still required
- Evidence: 2768 / 2768 analytical footprints reviewed
- Review packet: registry/report_intelligence/analytical_footprint_review_template.jsonl
- Review workbook: registry/report_intelligence/analytical_footprint_review_workbook.md
- Import template: registry/report_intelligence/analytical_footprint_review_template.jsonl
- Full import template: registry/report_intelligence/analytical_footprint_review_template.jsonl
- Policy template: none
- Reviewed policy/input: registry/report_intelligence/analytical_footprint_reviewed.jsonl
- Prepare: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-footprint-review --root . --output registry/report_intelligence/analytical_footprint_reviewed.jsonl --overwrite`
- Pending rows: 0
- Exported rows: 2768
- Review aids: policy: private_review_aids_only_not_import_files; fill_import_path: registry/report_intelligence/analytical_footprint_review_batch.jsonl; promotion_import_path: registry/report_intelligence/analytical_footprint_reviewed.jsonl; assist_jsonl: registry/report_intelligence/analytical_footprint_review_assist.jsonl; assist_workbook_markdown: registry/report_intelligence/analytical_footprint_review_workbook.md; evidence_jsonl: registry/report_intelligence/analytical_footprint_review_evidence.jsonl; evidence_markdown: registry/report_intelligence/analytical_footprint_review_evidence.md
- Field contract: policy: human_decisions_only_preserve_ids_hashes_and_context_refs; required_fields: footprint_correct, source_span_supports_footprint, metric_mapping_correct, inferred_steps_tagged_correctly, unknowns_used_when_uncertain, no_proprietary_text_leakage, reviewer, review_date, review_notes; optional_fields: none; boolean_fields: footprint_correct, source_span_supports_footprint, metric_mapping_correct, inferred_steps_tagged_correctly, unknowns_used_when_uncertain, no_proprietary_text_leakage; boolean_allowed_values: true, false; date_fields: review_date=YYYY-MM-DD; text_fields: reviewer, review_date, review_notes; preserve_fields: footprint_id, target_row_hash, review_context_ref, target_review_path
- Batch overview: batch_count: 0; pending_rows: 0; rerun_review_progress_after_batch_apply: false
- Dry run: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl --dry-run`
- Apply: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl`
- Note: Generate the private footprint review assist/workbook and evidence draft, fill the reviewed scratch JSONL, keep hashes intact, and dry-run before applying. For batch work, prepare registry/report_intelligence/analytical_footprint_review_batch.jsonl with --limit/--offset, dry-run it, and apply accepted batches to accumulate progress.

### PG03 source_license

- Passed: true
- Blocker: none
- Evidence: 17529 / 17529 sources approved for production runtime
- Review packet: registry/compliance/tushare_license_review_packet.json
- Review workbook: registry/review_batches/source_license_review_workbook.md
- Import template: registry/review_batches/source_license_next_import_template.jsonl
- Full import template: registry/review_batches/source_license_policy_import.jsonl
- Policy template: registry/review_batches/source_license_policy_template.json
- Reviewed policy/input: registry/review_batches/source_license_policy_reviewed.json
- Prepare: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-license-policy-review --root .`
- Pending rows: 0
- Exported rows: 0
- Review aids: policy: private_review_aids_only_not_import_files; fill_policy_path: registry/review_batches/source_license_policy_reviewed.json; policy_template_path: registry/review_batches/source_license_policy_template.json; workbook_markdown: registry/review_batches/source_license_review_workbook.md
- Field contract: policy: policy_decision_fields_only_preserve_source_ids; required_fields: approved_for_derived_claim_storage, approved_for_production_runtime, reviewer, review_date; optional_fields: notes; boolean_fields: approved_for_derived_claim_storage, approved_for_production_runtime; boolean_allowed_values: true, false; date_fields: review_date=YYYY-MM-DD; text_fields: reviewer, review_date, notes; preserve_fields: source_id, target_row_hash
- Batch overview: none
- Dry run: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl --dry-run`
- Apply: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl`
- Note: Compliance approval is required before production runtime retrieval. Use registry/review_batches/source_license_review_workbook.md as the read-only source-class checklist. Copy registry/review_batches/source_license_policy_template.json to registry/review_batches/source_license_policy_reviewed.json, fill and sign the reviewed policy, then expand it instead of editing every source row manually.

### PG09 lockbox

- Passed: false
- Blocker: lockbox has not been opened
- Evidence: lockbox_state=not_ready, next_state=paper_trading, payload_errors=0
- Review packet: registry/evaluation/lockbox/lockbox_policy.json
- Review workbook: registry/review_batches/lockbox_review_checklist.md
- Import template: registry/review_batches/lockbox_review_next_import_template.json
- Full import template: none
- Policy template: none
- Reviewed policy/input: registry/review_batches/lockbox_reviewed.json
- Prepare: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-lockbox-review --root .`
- Pending rows: None
- Exported rows: 1
- Review aids: policy: wait_for_prior_manual_gates_before_opening; fill_import_path: registry/review_batches/lockbox_reviewed.json
- Field contract: policy: only_fill_after_upstream_manual_gates_are_ready; required_fields: experiment_family_id, experiment_id, opened_at, opened_by, open_count, result, parameter_search_after_open, rule_design_after_open; optional_fields: notes; boolean_fields: parameter_search_after_open, rule_design_after_open; boolean_allowed_values: true, false; allowed_results: failed, passed; date_fields: opened_at=ISO-8601 datetime or date; text_fields: opened_by, result, notes; numeric_fields: open_count; preserve_fields: none
- Batch overview: none
- Dry run: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json --dry-run`
- Apply: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json`
- Note: Run prepare-lockbox-review only after gold-set, analytical-footprint, and source-license gates pass; fill the reviewed scratch JSON, then dry-run before applying the one-time lockbox review.

## Remaining Blockers

- lockbox has not been opened
