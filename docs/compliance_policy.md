# RKE Compliance Policy

Research sources are governed before they can affect production runtime.

## License Status

- `approved`: allowed for production runtime when PIT metadata and source hash are present.
- `pending_review`: allowed for sandbox and gold-set preparation only.
- `restricted`: allowed for sandbox only unless a narrower approval is recorded.
- `prohibited`: not allowed for ingest.

## Required Metadata

- `source_id`
- `source_type`
- `publish_date`
- `ingest_time` or `discovered_at`
- `license_status`
- `point_in_time_available`
- `source_hash`

## Production Runtime Gate

A source is rejected from production runtime if:

- license status is not approved;
- `point_in_time_available` is not true;
- `source_hash` is missing;
- `forbidden_uses` includes `production_runtime_retrieval`;
- compliance review forbids derived claim storage.

Current Tushare research-report rows are stored with `license_status =
pending_review`, so they can support sandbox inspection and gold-set candidate
selection but cannot enter production runtime.

## Manual License Review

Compliance decisions are imported with:

```bash
mosaic-rke apply-license-review --root . --input reviewed_sources.jsonl
```

Use `--dry-run` to validate without changing the review template.

The import is accepted only when:

- every `source_id` exists in
  `registry/compliance/tushare_license_review_template.jsonl`;
- no duplicate `source_id` is present;
- `approved_for_derived_claim_storage` is a boolean;
- `approved_for_production_runtime` is a boolean;
- `reviewer` and `review_date` are present.

After a successful import, the system recomputes:

- source license review summary;
- source registry validation;
- completion audit;
- dashboard;
- registry manifest.

If a source is not approved for production runtime, it remains blocked by C11.

## Allowed Uses

When a review row approves derived claim storage, the source may be used for
source-grounded claim ledgers and reviewer-facing packets.

When a review row approves production runtime retrieval, the source may be used
by production runtime context builders subject to PIT and source-hash checks.

If either approval is false, the corresponding use is written into
`forbidden_uses` by the compliance application layer.

## Original Text Handling

Do not put long sell-side report passages into prompts, runtime outputs, logs,
or public artifacts. Production prompts may cite source IDs, span IDs, hashes,
and short reviewer-approved claim text, not long original abstracts.
