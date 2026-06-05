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
