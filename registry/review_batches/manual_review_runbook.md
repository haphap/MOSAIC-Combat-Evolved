# RKE Manual Review Runbook

This artifact is a read-only operator checklist for the remaining manual RKE gates.
It records paths, commands, row counts, acceptance criteria, and current blockers only.

## Current Progress

- Promotion dry-run ready: true
- Gold-set review: 125/125 complete; scratch exists: true; simulation accepted: true
- Analytical-footprint review: 10310/10310 complete; scratch exists: true; simulation accepted: true
- Source-license review: 17529/17529 complete; scratch exists: true; simulation accepted: true
- Lockbox review: 1/1 complete; scratch exists: true; simulation accepted: true
- Lockbox dependency status: ready

## Current Batch Scratch

This section reports aggregate completion counts for the current local batch or decision files only; it does not include source text, claim text, or reviewer notes.
- Gold-set batch: `registry/review_batches/gold_set_reviewed.jsonl`; exists: true; rows: 0; complete: 0; pending: 0; malformed: 0
  Evidence alignment: path=`registry/review_batches/gold_set_review_evidence.jsonl`; exists: true; rows: 50; covered: 0/0; same_order: false; aligned: false
  Evidence quality: snippet_ready: 50; missing_markdown: 0
  Evidence priority metadata: reason_ready: 50; missing_reason_rows: 0; refresh_recommended: false
  Quality-gap focus fields: `direction_correct`=8, `unsupported_field_false_grounded`=24, `variable_mapping_correct`=18
  Suggested evidence tags: `direction_text_needs_review`=8, `forecast_mapping_insufficient`=24, `unsupported_grounding_needs_review`=24, `variable_mapping_missing_expected_cause`=13, `variable_mapping_missing_target`=1, `variable_mapping_needs_review`=1, `variable_mapping_questionable_cause`=5
  Evidence priority scores: `2`=25, `3`=1, `5`=24
  Evidence priority reasons: `forecast_mapping_insufficient`=24, `low_extraction_confidence`=24, `manual_review_required`=50, `missing_target_variables`=1
  Suggested decision counts: `claim_correct`={true:50}; `direction_correct`={null:8,true:42}; `horizon_correct`={null:2,true:48}; `source_span_supports_claim`={true:50}; `target_correct`={null:5,true:45}; `unsupported_field_false_grounded`={false:26,null:24}; `variable_mapping_correct`={false:18,true:32}
  Review workload summary: missing_required_cells=0; draft_decision_available_cells=311; draft_text_available_cells=0; manual_review_required_cells=0; fields_with_manual_review_required=0
  Review next fields: manual_required: none; draft_available: `claim_correct`=50, `source_span_supports_claim`=50, `variable_mapping_correct`=50, `horizon_correct`=48, `target_correct`=45, `direction_correct`=42, `unsupported_field_false_grounded`=26; text_draft_available: none
  Review workflow groups: decision: none; metadata: none; text: none; draft_verify: `claim_correct`=50, `source_span_supports_claim`=50, `variable_mapping_correct`=50, `horizon_correct`=48, `target_correct`=45, `direction_correct`=42, `unsupported_field_false_grounded`=26; text_draft_verify: none
  Review field workload: `claim_correct`=missing:0,draft:50,text_draft:0,manual:0; `direction_correct`=missing:0,draft:42,text_draft:0,manual:0; `horizon_correct`=missing:0,draft:48,text_draft:0,manual:0; `source_span_supports_claim`=missing:0,draft:50,text_draft:0,manual:0; `target_correct`=missing:0,draft:45,text_draft:0,manual:0; `unsupported_field_false_grounded`=missing:0,draft:26,text_draft:0,manual:0; `variable_mapping_correct`=missing:0,draft:50,text_draft:0,manual:0
  Evidence alignment gaps: `extra_evidence_rows`=50
- Analytical-footprint batch: `registry/report_intelligence/analytical_footprint_review_batch.jsonl`; exists: true; rows: 498; complete: 498; pending: 0; malformed: 0
  Evidence alignment: path=`registry/report_intelligence/analytical_footprint_review_evidence.jsonl`; exists: true; rows: 498; covered: 498/498; same_order: true; aligned: true
  Evidence quality: snippet_ready: 498; missing_markdown: 0
  Evidence priority metadata: reason_ready: 498; missing_reason_rows: 0; refresh_recommended: false
  Quality-gap focus fields: `footprint_correct`=13, `inferred_steps_tagged_correctly`=13, `metric_mapping_correct`=21, `unknowns_used_when_uncertain`=8
  Suggested evidence tags: `boilerplate_risk_warning_footprint`=13, `metric_mapping_hidden_unknown`=1, `metric_mapping_unknown`=8
  Evidence priority scores: `1`=498
  Evidence priority reasons: `missing_target_agent_candidates`=498
  Suggested decision counts: `footprint_correct`={false:13,true:485}; `inferred_steps_tagged_correctly`={false:13,true:485}; `metric_mapping_correct`={false:21,true:477}; `no_proprietary_text_leakage`={true:498}; `source_span_supports_footprint`={true:498}; `unknowns_used_when_uncertain`={true:498}
  Review workload summary: missing_required_cells=0; draft_decision_available_cells=2988; draft_text_available_cells=0; manual_review_required_cells=0; fields_with_manual_review_required=0
  Review next fields: manual_required: none; draft_available: `footprint_correct`=498, `inferred_steps_tagged_correctly`=498, `metric_mapping_correct`=498, `no_proprietary_text_leakage`=498, `source_span_supports_footprint`=498, `unknowns_used_when_uncertain`=498; text_draft_available: none
  Review workflow groups: decision: none; metadata: none; text: none; draft_verify: `footprint_correct`=498, `inferred_steps_tagged_correctly`=498, `metric_mapping_correct`=498, `no_proprietary_text_leakage`=498, `source_span_supports_footprint`=498, `unknowns_used_when_uncertain`=498; text_draft_verify: none
  Review field workload: `footprint_correct`=missing:0,draft:498,text_draft:0,manual:0; `inferred_steps_tagged_correctly`=missing:0,draft:498,text_draft:0,manual:0; `metric_mapping_correct`=missing:0,draft:498,text_draft:0,manual:0; `no_proprietary_text_leakage`=missing:0,draft:498,text_draft:0,manual:0; `source_span_supports_footprint`=missing:0,draft:498,text_draft:0,manual:0; `unknowns_used_when_uncertain`=missing:0,draft:498,text_draft:0,manual:0
- Lockbox decision: `registry/review_batches/lockbox_reviewed.json`; exists: true; rows: 1; complete: 1; pending: 0; malformed: 0

## Prepare Commands

- Temp workspace: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke` keeps review-progress and promotion dry-run registry copies out of system `/tmp`; generated commands below include this prefix.
- Gold-set: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-gold-review --root . --full`
- Analytical-footprint: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-footprint-review --root . --output registry/report_intelligence/analytical_footprint_reviewed.jsonl --overwrite`
- Source-license: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-license-policy-review --root .`
- Lockbox: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-lockbox-review --root .`

## Reviewer Inputs

- Gold-set active batch scratch: `registry/review_batches/gold_set_reviewed.jsonl`
- Gold-set full promotion import: `registry/review_batches/gold_set_full_reviewed.jsonl`
- Analytical-footprint active batch scratch: `registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Analytical-footprint full promotion import: `registry/report_intelligence/analytical_footprint_reviewed.jsonl`
- Source-license reviewed policy: `registry/review_batches/source_license_policy_reviewed.json`
- Lockbox reviewed scratch: `registry/review_batches/lockbox_reviewed.json`

Active batch scratch files are the only files to edit for current-batch work. Full promotion imports are used after all batches are complete.
Reviewed scratch files are operator-local decision files. Do not commit them unless the operator explicitly chooses to publish signed review decisions.

## Read-Only Checklists

- Gold-set workbook: `registry/review_batches/gold_set_review_workbook.md`
- Gold-set evidence draft Markdown: `registry/review_batches/gold_set_review_evidence.md`
- Gold-set evidence draft JSONL: `registry/review_batches/gold_set_review_evidence.jsonl`
- Gold-set packet JSON: `registry/gold_sets/tushare_research_reports.review_packet.json`
- Gold-set packet Markdown: `registry/gold_sets/tushare_research_reports.review_packet.md`
- Source-license workbook: `registry/review_batches/source_license_review_workbook.md`
- Source-license packet JSON: `registry/compliance/tushare_license_review_packet.json`
- Source-license packet Markdown: `registry/compliance/tushare_license_review_packet.md`
- Source-license policy template: `registry/review_batches/source_license_policy_template.json`
- Analytical-footprint review template: `registry/report_intelligence/analytical_footprint_review_template.jsonl`
- Analytical-footprint review workbook: `registry/report_intelligence/analytical_footprint_review_workbook.md`
- Analytical-footprint review assist JSONL: `registry/report_intelligence/analytical_footprint_review_assist.jsonl`
- Analytical-footprint evidence draft Markdown: `registry/report_intelligence/analytical_footprint_review_evidence.md`
- Analytical-footprint evidence draft JSONL: `registry/report_intelligence/analytical_footprint_review_evidence.jsonl`
- Lockbox policy packet: `registry/evaluation/lockbox/lockbox_policy.json`

These checklist files are not import files. Use them to inspect IDs, hashes, counts, field meanings, review order, and quick-fill suggestions only.
Start current Gold-set batch review from `registry/review_batches/gold_set_review_evidence.md`; it contains `Field Meaning And Review Order` and `Quick Fill Checklist`.
Start current analytical-footprint batch review from `registry/report_intelligence/analytical_footprint_review_evidence.md`; it contains `Field Meaning And Review Order` and `Quick Fill Checklist`.

## Manual Field Contracts

These contracts are public-safe field rules for reviewer-edited input files. They do not include source text, claim text, evidence snippets, or reviewer notes.

### Gold-set review

- Policy: `human_decisions_only_preserve_ids_hashes_and_context_refs`
- Required fields: `manual_claim_text`, `claim_correct`, `source_span_supports_claim`, `direction_correct`, `target_correct`, `horizon_correct`, `variable_mapping_correct`, `unsupported_field_false_grounded`, `reviewer`, `review_date`
- Optional fields: `review_notes`
- Boolean fields: `claim_correct`, `source_span_supports_claim`, `direction_correct`, `target_correct`, `horizon_correct`, `variable_mapping_correct`, `unsupported_field_false_grounded`
- Boolean allowed values: `true`, `false`
- Date fields: `review_date`=`YYYY-MM-DD`
- Text fields: `manual_claim_text`, `reviewer`, `review_notes`
- Numeric fields: none
- Allowed results: none
- Preserve fields: `claim_id`, `target_row_hash`, `review_context_ref`, `target_review_path`

### Analytical-footprint review

- Policy: `human_decisions_only_preserve_ids_hashes_and_context_refs`
- Required fields: `footprint_correct`, `source_span_supports_footprint`, `metric_mapping_correct`, `inferred_steps_tagged_correctly`, `unknowns_used_when_uncertain`, `no_proprietary_text_leakage`, `reviewer`, `review_date`, `review_notes`
- Optional fields: none
- Boolean fields: `footprint_correct`, `source_span_supports_footprint`, `metric_mapping_correct`, `inferred_steps_tagged_correctly`, `unknowns_used_when_uncertain`, `no_proprietary_text_leakage`
- Boolean allowed values: `true`, `false`
- Date fields: `review_date`=`YYYY-MM-DD`
- Text fields: `reviewer`, `review_date`, `review_notes`
- Numeric fields: none
- Allowed results: none
- Preserve fields: `footprint_id`, `target_row_hash`, `review_context_ref`, `target_review_path`

### Source-license review

- Policy: `policy_decision_fields_only_preserve_source_ids`
- Required fields: `approved_for_derived_claim_storage`, `approved_for_production_runtime`, `reviewer`, `review_date`
- Optional fields: `notes`
- Boolean fields: `approved_for_derived_claim_storage`, `approved_for_production_runtime`
- Boolean allowed values: `true`, `false`
- Date fields: `review_date`=`YYYY-MM-DD`
- Text fields: `reviewer`, `review_date`, `notes`
- Numeric fields: none
- Allowed results: none
- Preserve fields: `source_id`, `target_row_hash`

### Lockbox review

- Policy: `only_fill_after_upstream_manual_gates_are_ready`
- Required fields: `experiment_family_id`, `experiment_id`, `opened_at`, `opened_by`, `open_count`, `result`, `parameter_search_after_open`, `rule_design_after_open`
- Optional fields: `notes`
- Boolean fields: `parameter_search_after_open`, `rule_design_after_open`
- Boolean allowed values: `true`, `false`
- Date fields: `opened_at`=`ISO-8601 datetime or date`
- Text fields: `opened_by`, `result`, `notes`
- Numeric fields: `open_count`
- Allowed results: `failed`, `passed`
- Preserve fields: none

## Gate Acceptance Criteria

Gold-set review is accepted only when all current claim rows are completed and the dry run accepts the import.
Each gold-set row must keep the template IDs and hashes intact and must fill `manual_claim_text`, `reviewer`, `review_date`, `claim_correct`, `source_span_supports_claim`, `direction_correct`, `target_correct`, `horizon_correct`, `variable_mapping_correct`, and `unsupported_field_false_grounded`.
Use `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-gold-review --root . --full --force --reviewer <name> --review-date <YYYY-MM-DD>` to prefill reviewer identity and date only; claim text and boolean review decisions remain human judgments.
For batch work, use `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-gold-review --root . --gold-batch-size 50 --offset 0 --force --reviewer <name> --review-date <YYYY-MM-DD>`; after applying that batch, rerun with `--offset 0` because completed rows leave the pending set.
Batch gold-set imports use `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl --dry-run`, then `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl` after the batch is accepted.
Use `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke write-gold-review-evidence --root . --limit 50 --offset 0 --review-input registry/review_batches/gold_set_reviewed.jsonl` after preparing the current gold scratch batch to regenerate a batch-aligned private source-evidence draft.
The resulting gold-set summary must satisfy the code-defined gate: at least 50 documents, at least 100 claims, claim precision >= 0.85, span-support precision >= 0.90, direction accuracy >= 0.85, target accuracy >= 0.85, horizon accuracy >= 0.85, variable mapping accuracy >= 0.80, and unsupported-field false grounding <= 0.05.

Analytical-footprint review is accepted only when every footprint row is completed, the import dry run accepts it, and the review summary quality gate passes.
Each analytical-footprint row must keep target IDs and hashes intact and must fill `reviewer`, `review_date`, `review_notes`, `footprint_correct`, `source_span_supports_footprint`, `metric_mapping_correct`, `inferred_steps_tagged_correctly`, `unknowns_used_when_uncertain`, and `no_proprietary_text_leakage`.
For batch work, use `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke prepare-footprint-review --root . --limit 50 --offset 0 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`; after applying that batch, rerun with `--offset 0` because completed rows leave the pending set.
Batch analytical-footprint imports use `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`, then `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl` after the batch is accepted.
Use `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl` and `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl` after preparing the current footprint scratch batch to regenerate a batch-aligned private evidence draft.

Source-license review is accepted only when the reviewed policy expands to all current source rows and both the build step and license import dry run accept it.
The reviewed policy must fill `reviewer`, `review_date`, `approved_for_derived_claim_storage`, and `approved_for_production_runtime`; production promotion requires `approved_for_production_runtime=true` for every matched current source.
The policy must keep `target_review_path`, `review_context_ref`, `matched_row_count`, `matched_rows_fingerprint`, publish-date bounds, and filter scope aligned with the current template; rerun prepare if the source scope changes.

Lockbox review is accepted only after the final holdout is opened once, the import dry run accepts the signed row, and the lockbox decision allows production.
The lockbox row must fill `opened_at`, `opened_by`, `open_count`, `result`, `parameter_search_after_open`, and `rule_design_after_open`; production requires `result=passed`, `open_count<=1`, no parameter search after open, no rule design after open, and matching target/context hashes.

A promotion dry run is ready only when all manual gates above report ready for promotion. Missing scratch files, incomplete rows, failed dry runs, or failed quality thresholds keep the system in paper trading.

## Import Templates

- Next gold-set batch template: `registry/review_batches/gold_set_next_import_template.jsonl`
- Full gold-set import template: `registry/review_batches/gold_set_full_import_template.jsonl`
- Next source-license batch template: `registry/review_batches/source_license_next_import_template.jsonl`
- Expanded source-license import output: `registry/review_batches/source_license_policy_import.jsonl`
- Lockbox import template: `registry/review_batches/lockbox_review_next_import_template.json`

## Dry-Run Commands

- Gold-set: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl --dry-run`
- Analytical-footprint: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl --dry-run`
- Source-license: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl --dry-run`
- Lockbox: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json --dry-run`

## Apply Commands

- Gold-set: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl`
- Analytical-footprint: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl`
- Source-license: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl`
- Lockbox: `MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json`

## Promotion Dry Run

`MOSAIC_RKE_TMPDIR=~/tmp/mosaic-rke TMPDIR=~/tmp/mosaic-rke mosaic-rke promotion-dry-run --root . --gold-input registry/review_batches/gold_set_full_reviewed.jsonl --footprint-input registry/report_intelligence/analytical_footprint_reviewed.jsonl --lockbox-input registry/review_batches/lockbox_reviewed.json`

## Full Pending Batch Plan

This plan slices the current pending set before any new batch is applied. If you apply one accepted batch, rerun `review-progress` and use the refreshed offsets.

- Gold-set review: no pending review batches.

- Analytical-footprint review: no pending review batches.

## Next Batch Commands

These commands operate on the current pending set. After applying an accepted batch, rerun review-progress and use the refreshed commands.

## Current Blockers

- none
