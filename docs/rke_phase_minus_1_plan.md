# RKE Phase -1 Plan: Feasibility Spikes

Phase -1 validates the two largest unknowns before schema freeze:

1. PIT data availability for candidate metric proxies.
2. Claim extraction reliability on source-grounded research text.

This phase is intentionally before P0 schema freeze. No rule can be promoted from this phase; outputs are feasibility evidence only.

## Spike A: PIT Data Availability

Goal: prove that the first macro rule family can be validated with point-in-time data.

Initial target:

- Agent: `macro.central_bank`
- Rule family: `macro.central_bank.liquidity.v1`
- Candidate proxies:
  - `pboc_net_injection_7d`
  - `pboc_net_injection_20d`
  - `short_rate_movement`
  - `risk_appetite_proxy`
  - `sector_style_relative_return_20d`

Exit criteria:

- At least one central-bank liquidity proxy has PIT-safe history.
- Required labels use independent signal events, not daily overlapping rows.
- Every proxy has source, history window, timestamp granularity, vintage handling, survivorship/coverage risk, and validation/production eligibility.
- Any non-PIT or coverage-drift proxy is explicitly marked paper-only.

## Spike B: Claim Extraction Reliability

Goal: prove that source-grounded claim extraction is reliable enough to support later rule compilation.

Seed corpus:

- File: `registry/sources/tushare_research_reports.jsonl`
- Source: Tushare `pro.research_report`
- Current seed query window: `2026-02-05` to `2026-06-05`
- Current seed query set:
  - full-market `report_type`: `个股研报`, `行业研报`
  - date chunking: 7 calendar days per Tushare query window
  - source rows: 9,812 total, with 4,756 `个股研报` rows and 5,056 `行业研报` rows

Gold-set target from the master plan:

- 50 documents
- 500 claims
- source-grounded vs hypothesis labels
- claim precision >= 0.85
- source-span support precision >= 0.90
- direction accuracy >= 0.85
- variable mapping accuracy >= 0.80
- unsupported-field false grounding <= 0.05

Current seed corpus is not yet the gold set. It is the source pool for
sampling, claim extraction, license review, and annotation. Targeted
stock-code / industry-keyword queries remain supported only as supplements when
reviewers need additional examples for a sparse domain.

## Immediate Work Order

1. Ingest Tushare research reports into structured source rows.
2. Generate source metadata and source span IDs.
3. Sample candidate documents for manual gold-set labeling.
4. Build source-grounded claim verifier tests.
5. Build central-bank PIT matrix and reject non-PIT proxies.
6. Only after both spikes pass, freeze hardened P0 schemas.

## Current Review Workflow

The current Phase -1 review queue is generated from Tushare research reports:

- 50 sampled documents;
- 500 review rows;
- deterministic candidate claims;
- source span offsets and hashes;
- controlled-vocabulary variable hints;
- manual review fields left empty.

Refresh candidate claims:

```bash
mosaic-rke gold-candidate-claims --root .
```

Inspect the reviewer packet:

```bash
mosaic-rke gold-review-packet --root .
```

Generate next-batch import templates without copying long source text:

```bash
mosaic-rke review-batches --root .
```

Import reviewed claim labels:

```bash
mosaic-rke prepare-gold-review --root . --full
mosaic-rke apply-gold-review --root . \
  --input registry/review_batches/gold_set_full_reviewed.jsonl \
  --dry-run
```

Import source license approvals:

```bash
mosaic-rke prepare-license-policy-review --root .
mosaic-rke build-license-review-import \
  --root . \
  --policy registry/review_batches/source_license_policy_reviewed.json \
  --output registry/review_batches/source_license_policy_import.jsonl
mosaic-rke apply-license-review \
  --root . \
  --input registry/review_batches/source_license_policy_import.jsonl \
  --dry-run
```

Both import commands support `--dry-run`. They reject duplicate IDs, unknown IDs,
missing reviewer/date fields, and non-boolean gate fields.

Before applying a reviewed gold/license/lockbox bundle, simulate the combined
promotion outcome without mutating the registry:

```bash
mosaic-rke promotion-dry-run --root . \
  --gold-input registry/review_batches/gold_set_full_reviewed.jsonl \
  --license-input registry/review_batches/source_license_policy_import.jsonl \
  --lockbox-input registry/review_batches/lockbox_reviewed.json
```

For large same-source license queues, build the `apply-license-review` input
from a signed policy file instead of hand-filling every row. The operator
handoff generates a fillable starter policy at
`registry/review_batches/source_license_policy_template.json`. Copy it to
`registry/review_batches/source_license_policy_reviewed.json`; reviewers must
fill the approval booleans, reviewer, review date, and notes in the reviewed
file before expanding it:

```bash
mosaic-rke prepare-license-policy-review --root .

mosaic-rke build-license-review-import \
  --root . \
  --policy registry/review_batches/source_license_policy_reviewed.json \
  --output registry/review_batches/source_license_policy_import.jsonl

mosaic-rke apply-license-review \
  --root . \
  --input registry/review_batches/source_license_policy_import.jsonl \
  --dry-run
```

The policy builder never applies approvals by itself; it only writes sparse
per-source import rows plus an audit report.

Prepare and import a one-time lockbox review only after the gold-set and
source-license gates pass:

```bash
mosaic-rke prepare-lockbox-review --root .
mosaic-rke apply-lockbox-review \
  --root . \
  --input registry/review_batches/lockbox_reviewed.json \
  --dry-run
```

Refresh the Tushare research-report source pool:

```bash
mosaic-rke fetch-tushare-reports \
  --root . \
  --start-date 2026-02-05 \
  --end-date 2026-06-06 \
  --report-type 个股研报 \
  --report-type 行业研报 \
  --date-chunk-days 7 \
  --max-reports-per-query 6000
```

If the Tushare corpus was already fetched into a local CSV/JSONL cache, import
that file directly and skip network calls:

```bash
mosaic-rke fetch-tushare-reports \
  --root . \
  --input-path ~/.mosaic/cache/research_reports/all_market_2017_20260606/tushare_research_reports_corrected_2017-01-01_2026-06-06_20260606_0853410000.csv
```

The import path accepts raw Tushare-style fields (`trade_date`, `abstr`,
`inst_csname`, `ind_name`) and RKE-style fields (`publish_date`, `abstract`,
`institution`, `industry`). The refresh still rewrites the same source registry,
manifest, review packets, redaction report, dashboard, promotion gate, and
operator handoff artifacts. Rows without a non-empty abstract are skipped before
writing the RKE source registry, and the skip count is recorded in the manifest.

The recommended corpus refresh queries full-market Tushare `research_report`
rows by `report_type` and date windows. This avoids hand-maintaining a large
stock or industry keyword list and makes the manifest reproducible via
`query_set.report_types` and `date_chunk_days`.

Targeted stock and industry queries are still supported for supplements:

```bash
mosaic-rke fetch-tushare-reports \
  --root . \
  --start-date 2026-02-05 \
  --end-date 2026-06-06 \
  --stock-code 600519.SH,300750.SZ \
  --industry-keyword 银行 \
  --industry-keyword 半导体 \
  --stock-query-batch-size 50
```

For stock-code queries, the refresh command first tries to batch codes by
joining them into Tushare's comma-separated `ts_code` parameter. If a whole
batch returns zero rows, it automatically falls back to single-code queries so
`research_report` batch quirks do not drop available reports. Industry keywords
still use separate `ind_name` queries. Every refresh updates the dependent
source, gold-set, license, redaction, dashboard, promotion-gate, coverage, and
manifest artifacts.

The generated batch templates are review aids. They contain IDs, hashes, source
refs, and empty manual fields, but not full abstracts or span previews. Reviewers
may fill a batch file and dry-run it before applying.
The manual review bundle manifest hashes these artifacts and records the latest
promotion dry-run summary separately; manifest `accepted=true` means bundle
integrity passed, not that the blank review bundle can promote.

## Non-Goals

- Do not compile sell-side claims directly into production rules.
- Do not treat industry/stock reports as trading signals.
- Do not use semiconductor export-control style events as the first statistical validation proof.
- Do not promote any rule without P0 validation gates.
