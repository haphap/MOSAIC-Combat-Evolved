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
  - stocks: `600519.SH`, `300750.SZ`
  - industries: `银行`, `半导体`

Gold-set target from the master plan:

- 50 documents
- 500 claims
- source-grounded vs hypothesis labels
- claim precision >= 0.85
- source-span support precision >= 0.90
- direction accuracy >= 0.85
- variable mapping accuracy >= 0.80
- unsupported-field false grounding <= 0.05

Current seed corpus is not yet the gold set. It is the first source pool for sampling and annotation.

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
mosaic-rke apply-gold-review --root . --input reviewed_gold_set.jsonl
```

Import source license approvals:

```bash
mosaic-rke apply-license-review --root . --input reviewed_sources.jsonl
```

Both import commands support `--dry-run`. They reject duplicate IDs, unknown IDs,
missing reviewer/date fields, and non-boolean gate fields.

The generated batch templates are review aids. They contain IDs, hashes, source
refs, and empty manual fields, but not full abstracts or span previews. Reviewers
may fill a batch file and dry-run it before applying.

## Non-Goals

- Do not compile sell-side claims directly into production rules.
- Do not treat industry/stock reports as trading signals.
- Do not use semiconductor export-control style events as the first statistical validation proof.
- Do not promote any rule without P0 validation gates.
