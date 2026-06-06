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
- fill-gold-review
- dry-run-gold-review
- apply-gold-review
- prepare-source-license-review
- fill-source-license-policy
- dry-run-source-license-review
- apply-source-license-review
- promotion-status-before-lockbox
- prepare-lockbox-review
- fill-lockbox-review
- dry-run-lockbox-review
- promotion-dry-run
- apply-lockbox-review
- promotion-status-final

Dry-run command: `mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && mosaic-rke promotion-dry-run --root . --gold-input registry/review_batches/gold_set_full_reviewed.jsonl --license-input registry/review_batches/source_license_policy_import.jsonl --lockbox-input registry/review_batches/lockbox_reviewed.json`

## Command Sequence

### review-progress-preflight

- Phase: preflight
- Action: Inspect current manual-gate status.
- Command: `mosaic-rke review-progress --root .`
- Manual input: none
- Expected result: Shows current blockers without applying reviewer decisions.

### prepare-gold-review

- Phase: gold_set
- Action: Write the full gold-set import starter and workbook.
- Command: `mosaic-rke prepare-gold-review --root . --full`
- Manual input: none
- Expected result: Reviewer scratch target is registry/review_batches/gold_set_full_reviewed.jsonl.

### fill-gold-review

- Phase: gold_set
- Action: Fill the gold-set reviewed scratch file.
- Command: manual
- Manual input: registry/review_batches/gold_set_full_reviewed.jsonl
- Expected result: All 500 claim rows have required manual fields and preserved provenance hashes.

### dry-run-gold-review

- Phase: gold_set
- Action: Validate the reviewed gold-set scratch file.
- Command: `mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl --dry-run`
- Manual input: registry/review_batches/gold_set_full_reviewed.jsonl
- Expected result: Import is accepted and gold-set quality thresholds pass.

### apply-gold-review

- Phase: gold_set
- Action: Apply accepted gold-set review decisions.
- Command: `mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl`
- Manual input: registry/review_batches/gold_set_full_reviewed.jsonl
- Expected result: Gold-set summaries and downstream gates are recomputed.

### prepare-source-license-review

- Phase: source_license
- Action: Write the reviewed source-license policy starter and workbook.
- Command: `mosaic-rke prepare-license-policy-review --root .`
- Manual input: none
- Expected result: Reviewed policy target is registry/review_batches/source_license_policy_reviewed.json.

### fill-source-license-policy

- Phase: source_license
- Action: Fill and sign the reviewed source-license policy.
- Command: manual
- Manual input: registry/review_batches/source_license_policy_reviewed.json
- Expected result: Policy fields, matched-row fingerprint, and production approval scope are complete.

### dry-run-source-license-review

- Phase: source_license
- Action: Build and validate the source-license import rows.
- Command: `mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl --dry-run`
- Manual input: registry/review_batches/source_license_policy_reviewed.json
- Expected result: Policy expands to all current source rows and dry-run import is accepted.

### apply-source-license-review

- Phase: source_license
- Action: Build and apply accepted source-license decisions.
- Command: `mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl`
- Manual input: registry/review_batches/source_license_policy_reviewed.json
- Expected result: Source-license summaries and production blockers are recomputed.

### promotion-status-before-lockbox

- Phase: promotion
- Action: Confirm only the final lockbox gate remains before opening it.
- Command: `mosaic-rke promotion-status --root .`
- Manual input: none
- Expected result: Gold-set and source-license criteria pass; lockbox remains not opened.

### prepare-lockbox-review

- Phase: lockbox
- Action: Write the one-time lockbox review starter.
- Command: `mosaic-rke prepare-lockbox-review --root .`
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
- Command: `mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json --dry-run`
- Manual input: registry/review_batches/lockbox_reviewed.json
- Expected result: Lockbox import is accepted and production decision is eligible.

### promotion-dry-run

- Phase: promotion
- Action: Simulate the complete reviewed bundle before final apply.
- Command: `mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && mosaic-rke promotion-dry-run --root . --gold-input registry/review_batches/gold_set_full_reviewed.jsonl --license-input registry/review_batches/source_license_policy_import.jsonl --lockbox-input registry/review_batches/lockbox_reviewed.json`
- Manual input: none
- Expected result: Simulation accepts all three reviewed inputs without mutating the original registry.

### apply-lockbox-review

- Phase: lockbox
- Action: Apply the accepted one-time lockbox review.
- Command: `mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json`
- Manual input: registry/review_batches/lockbox_reviewed.json
- Expected result: Lockbox review is recorded and downstream promotion gates are recomputed.

### promotion-status-final

- Phase: promotion
- Action: Inspect final staged-promotion state.
- Command: `mosaic-rke promotion-status --root .`
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
- Prepare: `mosaic-rke prepare-gold-review --root . --full`
- Pending rows: 500
- Exported rows: 500
- Dry run: `mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl --dry-run`
- Apply: `mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl`
- Note: Run prepare-gold-review --full, fill the reviewed scratch JSONL, use registry/review_batches/gold_set_review_workbook.md as the read-only claim checklist, then dry-run before applying the 500-claim gold set.

### PG03 source_license

- Passed: false
- Blocker: source license review still pending or restricted
- Evidence: 0 / 9812 sources approved for production runtime
- Review packet: registry/compliance/tushare_license_review_packet.json
- Review workbook: registry/review_batches/source_license_review_workbook.md
- Import template: registry/review_batches/source_license_next_import_template.jsonl
- Full import template: registry/review_batches/source_license_policy_import.jsonl
- Policy template: registry/review_batches/source_license_policy_template.json
- Reviewed policy/input: registry/review_batches/source_license_policy_reviewed.json
- Prepare: `mosaic-rke prepare-license-policy-review --root .`
- Pending rows: 9812
- Exported rows: 50
- Dry run: `mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl --dry-run`
- Apply: `mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl`
- Note: Compliance approval is required before production runtime retrieval. Use registry/review_batches/source_license_review_workbook.md as the read-only source-class checklist. Copy registry/review_batches/source_license_policy_template.json to registry/review_batches/source_license_policy_reviewed.json, fill and sign the reviewed policy, then expand it instead of editing every source row manually.

### PG09 lockbox

- Passed: false
- Blocker: lockbox has not been opened
- Evidence: lockbox_state=not_ready, next_state=paper_trading, payload_errors=0
- Review packet: registry/evaluation/lockbox/lockbox_policy.json
- Review workbook: none
- Import template: registry/review_batches/lockbox_review_next_import_template.json
- Full import template: none
- Policy template: none
- Reviewed policy/input: registry/review_batches/lockbox_reviewed.json
- Prepare: `mosaic-rke prepare-lockbox-review --root .`
- Pending rows: None
- Exported rows: 1
- Dry run: `mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json --dry-run`
- Apply: `mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json`
- Note: Run prepare-lockbox-review only after manual gold and license gates pass, fill the reviewed scratch JSON, then dry-run before applying the one-time lockbox review.

## Remaining Blockers

- broad-rollout completion audit still has blockers
- manual gold-set review still required
- source license review still pending or restricted
- source registry has production blockers
- lockbox has not been opened
