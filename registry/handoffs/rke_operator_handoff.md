# RKE Operator Handoff

- Next state: paper_trading
- Paper trading allowed: true
- Staged production allowed: false
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

Dry-run command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke promotion-dry-run --root . --gold-input registry/review_batches/gold_set_full_reviewed.jsonl --footprint-input registry/report_intelligence/analytical_footprint_reviewed.jsonl --lockbox-input registry/review_batches/lockbox_reviewed.json`

## Command Sequence

### review-progress-preflight

- Phase: preflight
- Action: Inspect current manual-gate status.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke review-progress --root .`
- Manual input: none
- Expected result: Shows current blockers without applying reviewer decisions.

### prepare-gold-review

- Phase: gold_set
- Action: Write the full gold-set import starter and workbook.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke prepare-gold-review --root . --full`
- Manual input: none
- Expected result: Reviewer scratch target is registry/review_batches/gold_set_full_reviewed.jsonl.

### write-gold-review-evidence

- Phase: gold_set
- Action: Write private gold-set evidence draft files.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke write-gold-review-evidence --root . --limit 50 --offset 0 --review-input registry/review_batches/gold_set_reviewed.jsonl`
- Manual input: none
- Expected result: Private evidence Markdown is registry/review_batches/gold_set_review_evidence.md and evidence JSONL is registry/review_batches/gold_set_review_evidence.jsonl.

### fill-gold-review

- Phase: gold_set
- Action: Fill the gold-set reviewed scratch file.
- Command: manual
- Manual input: registry/review_batches/gold_set_full_reviewed.jsonl
- Expected result: All 500 claim rows have required manual fields and preserved provenance hashes.

### dry-run-gold-review

- Phase: gold_set
- Action: Validate the reviewed gold-set scratch file.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl --dry-run`
- Manual input: registry/review_batches/gold_set_full_reviewed.jsonl
- Expected result: Import is accepted and gold-set quality thresholds pass.

### apply-gold-review

- Phase: gold_set
- Action: Apply accepted gold-set review decisions.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl`
- Manual input: registry/review_batches/gold_set_full_reviewed.jsonl
- Expected result: Gold-set summaries and downstream gates are recomputed.

### prepare-footprint-review

- Phase: footprint_review
- Action: Write the analytical-footprint review starter.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke prepare-footprint-review --root . --output registry/report_intelligence/analytical_footprint_reviewed.jsonl --overwrite`
- Manual input: none
- Expected result: Reviewer scratch target is registry/report_intelligence/analytical_footprint_reviewed.jsonl.

### write-footprint-review-assist

- Phase: footprint_review
- Action: Write private analytical-footprint review assist files.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke write-footprint-review-assist --root .`
- Manual input: none
- Expected result: Private workbook is registry/report_intelligence/analytical_footprint_review_workbook.md and JSONL assist is registry/report_intelligence/analytical_footprint_review_assist.jsonl.

### write-footprint-review-evidence

- Phase: footprint_review
- Action: Write private analytical-footprint evidence draft files.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl`
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
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl --dry-run`
- Manual input: registry/report_intelligence/analytical_footprint_reviewed.jsonl
- Expected result: Import is accepted and footprint quality thresholds pass.

### apply-footprint-review

- Phase: footprint_review
- Action: Apply accepted analytical-footprint review decisions.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl`
- Manual input: registry/report_intelligence/analytical_footprint_reviewed.jsonl
- Expected result: Footprint summaries and downstream gates are recomputed.

### promotion-status-before-lockbox

- Phase: promotion
- Action: Confirm only the final lockbox gate remains before opening it.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke promotion-status --root .`
- Manual input: none
- Expected result: Gold-set, footprint, and source-license criteria pass; lockbox remains not opened.

### prepare-lockbox-review

- Phase: lockbox
- Action: Write the one-time lockbox review starter.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke prepare-lockbox-review --root .`
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
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json --dry-run`
- Manual input: registry/review_batches/lockbox_reviewed.json
- Expected result: Lockbox import is accepted and production decision is eligible.

### promotion-dry-run

- Phase: promotion
- Action: Simulate the complete reviewed bundle before final apply.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke promotion-dry-run --root . --gold-input registry/review_batches/gold_set_full_reviewed.jsonl --footprint-input registry/report_intelligence/analytical_footprint_reviewed.jsonl --lockbox-input registry/review_batches/lockbox_reviewed.json`
- Manual input: none
- Expected result: Simulation accepts all required reviewed inputs without mutating the original registry.

### apply-lockbox-review

- Phase: lockbox
- Action: Apply the accepted one-time lockbox review.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json`
- Manual input: registry/review_batches/lockbox_reviewed.json
- Expected result: Lockbox review is recorded and downstream promotion gates are recomputed.

### promotion-status-final

- Phase: promotion
- Action: Inspect final staged-promotion state.
- Command: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke promotion-status --root .`
- Manual input: none
- Expected result: Promotion status reflects the applied manual reviews and lockbox decision.

## Gates

### PG02 gold_set

- Passed: false
- Blocker: manual gold-set review still required
- Evidence: 0 / 500 gold-set claims reviewed
- Review packet: registry/gold_sets/tushare_research_reports.review_packet.json
- Review workbook: registry/review_batches/gold_set_review_workbook.md
- Import template: registry/review_batches/gold_set_next_import_template.jsonl
- Full import template: registry/review_batches/gold_set_full_import_template.jsonl
- Policy template: none
- Reviewed policy/input: registry/review_batches/gold_set_full_reviewed.jsonl
- Prepare: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke prepare-gold-review --root . --full`
- Pending rows: 500
- Exported rows: 500
- Dry run: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl --dry-run`
- Apply: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl`
- Note: Run prepare-gold-review --full, fill the reviewed scratch JSONL, use registry/review_batches/gold_set_review_workbook.md as the read-only claim checklist, and use registry/review_batches/gold_set_review_assist.md as non-import machine assistance, use registry/review_batches/gold_set_review_evidence.md as private source evidence draft, then dry-run before applying the 500-claim gold set. For batch work, prepare registry/review_batches/gold_set_reviewed.jsonl with --gold-batch-size/--offset, dry-run it, and apply accepted batches to accumulate progress.

### RI-FOOTPRINT-REVIEW footprint_review

- Passed: false
- Blocker: 1001 analytical footprint review rows still pending; footprint_precision unavailable; span_support_precision unavailable; metric_mapping_accuracy unavailable; inferred_step_tagging_accuracy unavailable; unknown_on_ambiguity_rate unavailable; proprietary_leakage_free_rate unavailable
- Evidence: 0 / 1001 analytical footprints reviewed
- Review packet: registry/report_intelligence/analytical_footprint_review_template.jsonl
- Review workbook: registry/report_intelligence/analytical_footprint_review_workbook.md
- Import template: registry/report_intelligence/analytical_footprint_review_template.jsonl
- Full import template: registry/report_intelligence/analytical_footprint_review_template.jsonl
- Policy template: none
- Reviewed policy/input: registry/report_intelligence/analytical_footprint_reviewed.jsonl
- Prepare: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke prepare-footprint-review --root . --output registry/report_intelligence/analytical_footprint_reviewed.jsonl --overwrite`
- Pending rows: 1001
- Exported rows: 1001
- Dry run: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl --dry-run`
- Apply: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_reviewed.jsonl`
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
- Prepare: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke prepare-license-policy-review --root .`
- Pending rows: 0
- Exported rows: 0
- Dry run: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl --dry-run`
- Apply: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl`
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
- Prepare: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke prepare-lockbox-review --root .`
- Pending rows: None
- Exported rows: 1
- Dry run: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json --dry-run`
- Apply: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json`
- Note: Run prepare-lockbox-review only after manual gold and license gates pass, fill the reviewed scratch JSON, then dry-run before applying the one-time lockbox review.

## Remaining Blockers

- manual gold-set review still required
- lockbox has not been opened
- 1001 analytical footprint review rows still pending; footprint_precision unavailable; span_support_precision unavailable; metric_mapping_accuracy unavailable; inferred_step_tagging_accuracy unavailable; unknown_on_ambiguity_rate unavailable; proprietary_leakage_free_rate unavailable
