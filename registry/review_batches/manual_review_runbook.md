# RKE Manual Review Runbook

This artifact is a read-only operator checklist for the remaining manual RKE gates.
It records paths, commands, row counts, and current blockers only.

## Current Progress

- Promotion dry-run ready: false
- Gold-set review: 0/500 complete; scratch exists: false; simulation accepted: false
- Source-license review: 0/9812 complete; scratch exists: false; simulation accepted: false
- Lockbox review: 0/1 complete; scratch exists: false; simulation accepted: false

## Prepare Commands

- Gold-set: `mosaic-rke prepare-gold-review --root . --full`
- Source-license: `mosaic-rke prepare-license-policy-review --root .`
- Lockbox: `mosaic-rke prepare-lockbox-review --root .`

## Reviewer Inputs

- Gold-set reviewed scratch: `registry/review_batches/gold_set_full_reviewed.jsonl`
- Source-license reviewed policy: `registry/review_batches/source_license_policy_reviewed.json`
- Lockbox reviewed scratch: `registry/review_batches/lockbox_reviewed.json`

Reviewed scratch files are operator-local decision files. Do not commit them unless the operator explicitly chooses to publish signed review decisions.

## Read-Only Checklists

- Gold-set workbook: `registry/review_batches/gold_set_review_workbook.md`
- Gold-set packet JSON: `registry/gold_sets/tushare_research_reports.review_packet.json`
- Gold-set packet Markdown: `registry/gold_sets/tushare_research_reports.review_packet.md`
- Source-license workbook: `registry/review_batches/source_license_review_workbook.md`
- Source-license packet JSON: `registry/compliance/tushare_license_review_packet.json`
- Source-license packet Markdown: `registry/compliance/tushare_license_review_packet.md`
- Source-license policy template: `registry/review_batches/source_license_policy_template.json`
- Lockbox policy packet: `registry/evaluation/lockbox/lockbox_policy.json`

These checklist files are not import files. Use them to inspect IDs, hashes, counts, and short previews only.

## Import Templates

- Next gold-set batch template: `registry/review_batches/gold_set_next_import_template.jsonl`
- Full gold-set import template: `registry/review_batches/gold_set_full_import_template.jsonl`
- Next source-license batch template: `registry/review_batches/source_license_next_import_template.jsonl`
- Expanded source-license import output: `registry/review_batches/source_license_policy_import.jsonl`
- Lockbox import template: `registry/review_batches/lockbox_review_next_import_template.json`

## Dry-Run Commands

- Gold-set: `mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl --dry-run`
- Source-license: `mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl --dry-run`
- Lockbox: `mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json --dry-run`

## Apply Commands

- Gold-set: `mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl`
- Source-license: `mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl`
- Lockbox: `mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json`

## Promotion Dry Run

`mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl && mosaic-rke promotion-dry-run --root . --gold-input registry/review_batches/gold_set_full_reviewed.jsonl --license-input registry/review_batches/source_license_policy_import.jsonl --lockbox-input registry/review_batches/lockbox_reviewed.json`

## Current Blockers

- gold_set: 0/500 ready
- gold_set: registry/review_batches/gold_set_full_reviewed.jsonl missing; run mosaic-rke prepare-gold-review --root . --full
- source_license: 0/9812 ready
- source_license: registry/review_batches/source_license_policy_reviewed.json missing; run mosaic-rke prepare-license-policy-review --root .
- lockbox: 0/1 ready
- lockbox: registry/review_batches/lockbox_reviewed.json missing; run mosaic-rke prepare-lockbox-review --root .
