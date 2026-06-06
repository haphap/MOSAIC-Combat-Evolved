# RKE Operator Handoff

- Next state: paper_trading
- Paper trading allowed: true
- Staged production allowed: false
- Production allowed: false
- Direct production forbidden: true

- Manual review runbook: registry/review_batches/manual_review_runbook.md

## Run Order

- promotion-dry-run
- gold_set
- source_license
- promotion-status
- lockbox

Dry-run command: `mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && mosaic-rke promotion-dry-run --root . --gold-input registry/review_batches/gold_set_full_reviewed.jsonl --license-input registry/review_batches/source_license_policy_import.jsonl --lockbox-input registry/review_batches/lockbox_reviewed.json`

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
