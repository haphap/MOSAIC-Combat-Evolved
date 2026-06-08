# RKE Source-License Review Workbook

- Workbook ID: RKE-SOURCE-LICENSE-REVIEW-WORKBOOK-20260606
- Pending rows: 0
- Source rows in template: 17529
- Matched policy rows: 0
- Matched rows fingerprint: `sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`
- Publish date range: none to none
- Review template: `registry/compliance/tushare_license_review_template.jsonl`
- Review packet: `registry/compliance/tushare_license_review_packet.json`
- Policy template: `registry/review_batches/source_license_policy_template.json`
- Reviewed policy: `registry/review_batches/source_license_policy_reviewed.json`
- Policy import output: `registry/review_batches/source_license_policy_import.jsonl`
- Prepare reviewed policy: `mosaic-rke prepare-license-policy-review --root .`
- Build policy import: `mosaic-rke build-license-review-import --root . --policy registry/review_batches/source_license_policy_reviewed.json --output registry/review_batches/source_license_policy_import.jsonl`
- Dry run policy import: `mosaic-rke apply-license-review --root . --input registry/review_batches/source_license_policy_import.jsonl --dry-run`

This workbook is read-only. Fill reviewer decisions only in the reviewed policy JSON; do not edit this Markdown file or use it as an import file.
It intentionally lists only IDs, hashes, dates, statuses, and short title previews.

## Policy Scope

| Field | Value |
|---|---|
| source_type_counts | {"tushare_research_report": 17529} |
| license_status_counts | {"pending_review": 17529} |

## Sample Pending Source Rows

The table shows the first 0 pending rows. The full policy scope is bound by the matched rows fingerprint above.

| # | source_id | target_hash | publish_date | source_type | status | title_preview |
|---|---|---|---|---|---|---|
