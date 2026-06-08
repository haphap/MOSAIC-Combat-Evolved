# RKE Gold Review Workbook

- Workbook ID: RKE-GOLD-REVIEW-WORKBOOK-20260606
- Pending rows: 0
- Review template: `registry/gold_sets/tushare_research_reports.review_template.jsonl`
- Full import template: `registry/review_batches/gold_set_full_import_template.jsonl`
- Review packet: `registry/gold_sets/tushare_research_reports.review_packet.json`
- Prepare reviewed scratch: `mosaic-rke prepare-gold-review --root . --full`
- Dry run reviewed scratch: `mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_full_reviewed.jsonl --dry-run`

This workbook is a read-only checklist. Fill reviewer decisions only in the reviewed JSONL scratch file.

## Pending Claims

| # | claim_id | target_hash | domain | source_id | offsets | type | direction | confidence | variables | risk_flags | claim_preview |
|---|---|---|---|---|---|---|---|---|---|---|---|
