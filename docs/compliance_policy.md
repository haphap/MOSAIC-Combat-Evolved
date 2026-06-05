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

For large same-source review sets, compliance can sign one scoped policy and
expand it into the sparse JSONL expected by `apply-license-review`:

The operator handoff writes a reviewer-fillable starter policy at
`registry/review_batches/source_license_policy_template.json`. It is deliberately
incomplete: `reviewer`, `review_date`, and both approval booleans must be filled
before it can be expanded.

```json
{
  "approved_for_derived_claim_storage": true,
  "approved_for_production_runtime": false,
  "reviewer": "compliance",
  "review_date": "2026-06-06",
  "notes": "reviewed Tushare research-report source class for sandbox-derived claims only",
  "filters": {
    "source_type": ["tushare_research_report"],
    "current_license_status": ["pending_review"]
  }
}
```

Build the import rows:

```bash
mosaic-rke build-license-review-import \
  --root . \
  --policy registry/review_batches/source_license_policy_template.json \
  --output registry/review_batches/source_license_policy_import.jsonl
```

This command does not apply the decision. It only expands a reviewer/date-stamped
policy into per-source rows and writes an audit report at
`registry/review_batches/source_license_policy_import_report.json`. The generated
JSONL must still pass `mosaic-rke apply-license-review --dry-run` before being
applied.

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

Run the source-text redaction audit with:

```bash
mosaic-rke source-text-status --root .
```

The audit fingerprints long Tushare research-report abstracts and scans
runtime, prompt, dashboard, registry, docs, and agent-code artifacts for
long-passage exposure. The report stores only source IDs, source hashes, artifact
paths, and matched-chunk hashes; it must not echo the matched source text.

Allowed raw-text locations are limited to source-pool and manual-review sandbox
artifacts required for Phase -1 gold-set work. If a long passage appears outside
those sandbox paths, C11 remains failed even if license review later approves the
source for production retrieval.
