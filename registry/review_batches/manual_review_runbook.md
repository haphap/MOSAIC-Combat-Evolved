# RKE Manual Review Runbook

This artifact is a read-only operator checklist for the remaining manual RKE gates.
It records paths, commands, row counts, acceptance criteria, and current blockers only.

## Current Progress

- Promotion dry-run ready: false
- Gold-set review: 158/206 complete; scratch exists: true; simulation accepted: false
- Analytical-footprint review: 34/1051 complete; scratch exists: true; simulation accepted: false
- Source-license review: 17529/17529 complete; scratch exists: true; simulation accepted: true
- Lockbox review: 0/1 complete; scratch exists: true; simulation accepted: false
- Lockbox dependency status: waiting_on gold_set, footprint_review

## Current Batch Scratch

This section reports aggregate completion counts for the current local batch or decision files only; it does not include source text, claim text, or reviewer notes.
- Gold-set batch: `registry/review_batches/gold_set_reviewed.jsonl`; exists: true; rows: 26; complete: 0; pending: 26; malformed: 0
  Missing required fields: `claim_correct`=26, `direction_correct`=26, `horizon_correct`=26, `manual_claim_text`=26, `review_date`=26, `reviewer`=26, `source_span_supports_claim`=26, `target_correct`=26, `unsupported_field_false_grounded`=26, `variable_mapping_correct`=26
  Evidence alignment: path=`registry/review_batches/gold_set_review_evidence.jsonl`; exists: true; rows: 26; covered: 26/26; same_order: true; aligned: true
- Gold-set batch coverage: current scratch covers 26/48 pending target rows; remaining after current apply: 22; covers planned next batch: false
- Analytical-footprint batch: `registry/report_intelligence/analytical_footprint_review_batch.jsonl`; exists: true; rows: 50; complete: 0; pending: 50; malformed: 0
  Missing required fields: `footprint_correct`=50, `inferred_steps_tagged_correctly`=50, `metric_mapping_correct`=50, `no_proprietary_text_leakage`=50, `review_notes`=50, `source_span_supports_footprint`=50, `unknowns_used_when_uncertain`=50
  Evidence alignment: path=`registry/report_intelligence/analytical_footprint_review_evidence.jsonl`; exists: true; rows: 50; covered: 50/50; same_order: true; aligned: true
- Analytical-footprint batch coverage: current scratch covers 50/1017 pending target rows; remaining after current apply: 967; covers planned next batch: true
- Lockbox decision: `registry/review_batches/lockbox_reviewed.json`; exists: true; rows: 1; complete: 0; pending: 1; malformed: 0
  Missing required fields: `open_count`=1, `opened_at`=1, `opened_by`=1, `result`=1

## Prepare Commands

- Temp workspace: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp` keeps review-progress and promotion dry-run registry copies out of system `/tmp`; generated commands below include this prefix.
- Gold-set: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-gold-review --root . --full`
- Analytical-footprint: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --output registry/report_intelligence/analytical_footprint_reviewed.jsonl --overwrite`
- Source-license: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-license-policy-review --root .`
- Lockbox: wait for upstream gates before running `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-lockbox-review --root .`

## Reviewer Inputs

- Gold-set reviewed scratch: `registry/review_batches/gold_set_full_reviewed.jsonl`
- Analytical-footprint reviewed scratch: `registry/report_intelligence/analytical_footprint_reviewed.jsonl`
- Source-license reviewed policy: `registry/review_batches/source_license_policy_reviewed.json`
- Lockbox reviewed scratch: `registry/review_batches/lockbox_reviewed.json`

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

These checklist files are not import files. Use them to inspect IDs, hashes, counts, and short previews only.

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
Use `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-gold-review --root . --full --force --reviewer <name> --review-date <YYYY-MM-DD>` to prefill reviewer identity and date only; claim text and boolean review decisions remain human judgments.
For batch work, use `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-gold-review --root . --gold-batch-size 50 --offset 0 --force --reviewer <name> --review-date <YYYY-MM-DD>`; after applying that batch, rerun with `--offset 0` because completed rows leave the pending set.
Batch gold-set imports use `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl --dry-run`, then `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl` after the batch is accepted.
Use `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-gold-review-evidence --root . --limit 50 --offset 0 --review-input registry/review_batches/gold_set_reviewed.jsonl` after preparing the current gold scratch batch to regenerate a batch-aligned private source-evidence draft.
The resulting gold-set summary must satisfy the code-defined gate: at least 50 documents, at least 100 claims, claim precision >= 0.85, span-support precision >= 0.90, direction accuracy >= 0.85, target accuracy >= 0.85, horizon accuracy >= 0.85, variable mapping accuracy >= 0.80, and unsupported-field false grounding <= 0.05.

Analytical-footprint review is accepted only when every footprint row is completed, the import dry run accepts it, and the review summary quality gate passes.
Each analytical-footprint row must keep target IDs and hashes intact and must fill `reviewer`, `review_date`, `review_notes`, `footprint_correct`, `source_span_supports_footprint`, `metric_mapping_correct`, `inferred_steps_tagged_correctly`, `unknowns_used_when_uncertain`, and `no_proprietary_text_leakage`.
For batch work, use `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 0 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`; after applying that batch, rerun with `--offset 0` because completed rows leave the pending set.
Batch analytical-footprint imports use `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`, then `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl` after the batch is accepted.
Use `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl` and `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl` after preparing the current footprint scratch batch to regenerate a batch-aligned private evidence draft.

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

- Gold-set: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl --dry-run`
- Analytical-footprint: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl --dry-run`
- Source-license: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl --dry-run`
- Lockbox: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json --dry-run`

## Apply Commands

- Gold-set: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl`
- Analytical-footprint: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl`
- Source-license: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl`
- Lockbox: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json`

## Promotion Dry Run

`MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke promotion-dry-run --root . --gold-input registry/review_batches/gold_set_full_reviewed.jsonl --footprint-input registry/report_intelligence/analytical_footprint_reviewed.jsonl --lockbox-input registry/review_batches/lockbox_reviewed.json`

## Full Pending Batch Plan

This plan slices the current pending set before any new batch is applied. If you apply one accepted batch, rerun `review-progress` and use the refreshed offsets.

### Gold-set review

- Batch 1: pending rows 1-48; limit=48; offset=0; batch input=`registry/review_batches/gold_set_reviewed.jsonl`; promotion input=`registry/review_batches/gold_set_full_reviewed.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-gold-review-evidence --root . --limit 48 --offset 0 --review-input registry/review_batches/gold_set_reviewed.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-gold-review --root . --gold-batch-size 48 --offset 0 --force --reviewer <name> --review-date <YYYY-MM-DD>`
  - backfill_dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke backfill-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl`
  - backfill_write: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke backfill-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl --write`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl`

### Analytical-footprint review

- Batch 1: pending rows 1-50; limit=50; offset=0; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 0 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 2: pending rows 51-100; limit=50; offset=50; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 50 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 50 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 3: pending rows 101-150; limit=50; offset=100; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 100 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 100 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 4: pending rows 151-200; limit=50; offset=150; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 150 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 150 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 5: pending rows 201-250; limit=50; offset=200; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 200 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 200 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 6: pending rows 251-300; limit=50; offset=250; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 250 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 250 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 7: pending rows 301-350; limit=50; offset=300; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 300 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 300 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 8: pending rows 351-400; limit=50; offset=350; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 350 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 350 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 9: pending rows 401-450; limit=50; offset=400; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 400 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 400 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 10: pending rows 451-500; limit=50; offset=450; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 450 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 450 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 11: pending rows 501-550; limit=50; offset=500; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 500 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 500 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 12: pending rows 551-600; limit=50; offset=550; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 550 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 550 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 13: pending rows 601-650; limit=50; offset=600; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 600 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 600 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 14: pending rows 651-700; limit=50; offset=650; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 650 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 650 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 15: pending rows 701-750; limit=50; offset=700; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 700 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 700 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 16: pending rows 751-800; limit=50; offset=750; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 750 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 750 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 17: pending rows 801-850; limit=50; offset=800; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 800 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 800 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 18: pending rows 851-900; limit=50; offset=850; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 850 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 850 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 19: pending rows 901-950; limit=50; offset=900; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 900 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 900 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 20: pending rows 951-1000; limit=50; offset=950; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 950 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 950 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- Batch 21: pending rows 1001-1017; limit=17; offset=1000; batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`; promotion input=`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
  - assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 17 --offset 1000 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
  - prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 17 --offset 1000 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
  - dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
  - apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`

## Next Batch Commands

These commands operate on the current pending set. After applying an accepted batch, rerun review-progress and use the refreshed commands.

### gold_set

- assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-gold-review-assist --root . --review-input registry/review_batches/gold_set_reviewed.jsonl`
- evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-gold-review-evidence --root . --limit 48 --offset 0 --review-input registry/review_batches/gold_set_reviewed.jsonl`
- prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-gold-review --root . --gold-batch-size 48 --offset 0 --force --reviewer <name> --review-date <YYYY-MM-DD>`
- backfill_dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke backfill-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl`
- backfill_write: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke backfill-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl --write`
- dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl --dry-run`
- apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl`

### footprint_review

- assist: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- evidence: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
- prepare: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke prepare-footprint-review --root . --limit 50 --offset 0 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`
- dry_run: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`
- apply: `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl`

## Current Blockers

- gold_set: 158/206 ready
- gold_set: 332 review ids are missing from target
- gold_set: 500 review rows failed validation
- gold_set: 168 review rows have stale target_row_hash; rerun `mosaic-rke prepare-gold-review --root . --full --force` before filling reviewer decisions
- gold_set: 500 review rows: manual_claim_text required
- gold_set: 500 review rows: claim_correct must be boolean
- gold_set: 500 review rows: source_span_supports_claim must be boolean
- gold_set: 500 review rows: direction_correct must be boolean
- gold_set: 500 review rows: target_correct must be boolean
- gold_set: 500 review rows: horizon_correct must be boolean
- gold_set: 500 review rows: variable_mapping_correct must be boolean
- gold_set: 500 review rows: unsupported_field_false_grounded must be boolean
- gold_set: 2 additional validation reason(s) suppressed
- gold_set: 48 gold-set claim review rows still pending
- footprint_review: 34/1051 ready
- footprint_review: 1001 analytical footprint review rows failed validation
- footprint_review: 1017 analytical footprint review rows still pending
- footprint_review: metric_mapping_accuracy 0.558824 below threshold 0.80
- lockbox: 0/1 ready
- lockbox: opened_at required
- lockbox: opened_by required
- lockbox: open_count required
- lockbox: result required
- lockbox: result must be one of not_opened, passed, failed
- lockbox: open_count must be integer
- lockbox: lockbox has not been opened
