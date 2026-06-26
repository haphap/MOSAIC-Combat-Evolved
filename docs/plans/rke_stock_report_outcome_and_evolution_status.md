# RKE Stock Report Outcome and Evolution Status

Status date: 2026-06-26

This document tracks implementation evidence for
`docs/plans/rke_stock_report_outcome_and_evolution_plan.md`. It is public-safe:
it records aggregate counts, artifact paths, validation commands, and remaining
gates only. It must not include report prose, titles, abstracts, URLs, PDF or
Markdown paths, source spans, reviewer notes, or private Tushare rows.

## Current State

- Current public-safe extraction summary: 5454 selected reports, 5454 Markdown-ready
  reports, 5100 forecast claims, and 12360 outcome labels.
- Outcome label split: 1964 industry ETF proxy labels, 9523 stock price proxy
  labels, 409 macro asset proxy labels, 460 macro direct-series labels, and 4
  macro curve labels.
- Outcome readiness currently has 4511 standard ready claims, 3685 proxy-label
  ready claims, and 242 still blocked claims.
- Manual gold-set review is imported: 125 reviewed claims across 71 documents;
  all gold quality gates pass.
- Manual analytical-footprint review is complete and imported: 14712 reviewed
  footprints, 0 pending rows, `quality_gate_passed=true`, and all measured
  quality thresholds pass.
- `schema-status --root . --failures-only --no-write` currently reports 0
  failures. `patch_v1_5_coverage_report.json` is accepted with 0 blockers.
- `operator-readiness --root .` is accepted with 18/18 checks passing.
- `evolution-readiness --root . --no-write` is accepted with RI-EVOL-01 through
  RI-EVOL-07 passing. RI-EVOL-04 has 13 trailing clean audit passes and 13
  distinct clean audit vintages.
- Prompt mutation output currently has 8 shadow-only candidates. All keep
  `promotion_state=shadow_candidate_only`,
  `production_prompt_change_allowed=false`, `manual_review_required=true`, and
  `private_text_included=false`.
- Patch v1.5 coverage is accepted after footprint review completion.
- Lockbox is opened and passed in the committed registry; promotion gate state is
  consistent with `next_state=production`. report-derived signals remain
  shadow-only unless a separate promotion task explicitly changes runtime
  behavior.

## Plan Coverage

| Plan Area | Status | Evidence |
| --- | --- | --- |
| P0-P3 stock outcome contract/builders/audits | Implemented | Stock proxy labels use PIT T+1 windows, `SH510300` benchmark, 20 bps cost, stock target resolution, and readiness gaps for missing/conflicting data. |
| P4 tests | Implemented | Focused stock/macro/schema tests are maintained; current final verification commands are listed below. |
| P5 evolution loop | Implemented for shadow evolution; current gate passed | Prompt mutation candidates, paper-trading, confidence monitor, gold review, footprint review, and audit refresh history feed the evolution gate. RI-EVOL-04 now has 13 trailing clean audit passes and 13 distinct clean audit vintages. |
| P8 acceptance matrix | Complete for current registry state | Operator readiness, schema, PIT, provenance, statistical audits, footprint review, gold review, lockbox review, and patch coverage pass. |
| P9-P12 coverage/mapping/paper-trading/monitor | Implemented for current sample pool, still shadow-only | Public aggregate artifacts exist; private PDFs, Markdown, source rows, claim text, and reviewed imports remain uncommitted. Production behavior is unchanged unless a separate promotion task explicitly changes runtime wiring. |

## Current Verification Commands

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp .venv/bin/mosaic-rke schema-status --root . --failures-only --no-write
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp .venv/bin/mosaic-rke operator-readiness --root .
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp .venv/bin/mosaic-rke evolution-readiness --root . --no-write
uvx ruff@0.15.15 check mosaic tests
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-artifacts
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python scripts/check_prompt_leaks.py
git diff --check
```

## Residual Operational Follow-Up

1. Keep prompt mutation candidates shadow-only until future lockbox and
   production promotion approvals explicitly allow production changes.
2. Continue requiring distinct `data_vintage_hash` values for future clean audit
   history updates; repeated refreshes with the same hash must not count.
3. Keep reviewed imports and private review aids out of commits; only commit
   public-safe aggregate artifacts and code/tests.
4. Re-run schema, operator, evolution, privacy, and test checks before each
   future public artifact update.
