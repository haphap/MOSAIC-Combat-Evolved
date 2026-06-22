# RKE Stock Report Outcome and Evolution Status

Status date: 2026-06-22

This document tracks implementation evidence for
`docs/plans/rke_stock_report_outcome_and_evolution_plan.md`. It is public-safe:
it records aggregate counts, artifact paths, validation commands, and remaining
gates only. It must not include report prose, titles, abstracts, URLs, PDF or
Markdown paths, source spans, reviewer notes, or private Tushare rows.

## Current State

- Current public-safe extraction summary: 929 selected reports, 929 Markdown-ready
  reports, 1033 forecast claims, and 2375 outcome labels.
- Outcome label split: 78 industry ETF proxy labels, 2188 stock price proxy
  labels, 75 macro asset proxy labels, 31 macro direct-series labels, and 3
  macro curve labels.
- Outcome readiness currently has 921 standard ready claims, 707 proxy-label
  ready claims, and 50 still blocked claims.
- Manual gold-set review is imported: 125 reviewed claims across 71 documents;
  all gold quality gates pass.
- Manual analytical-footprint review is complete and imported: 2710 reviewed
  footprints, 0 pending rows, `quality_gate_passed=true`, and all measured
  quality thresholds pass.
- `schema-status --root . --failures-only --no-write` currently reports 0
  failures. `patch_v1_5_coverage_report.json` is accepted with 0 blockers.
- `operator-readiness --root .` is accepted with 18/18 checks passing.
- `evolution-readiness --root . --no-write` is currently blocked only by
  RI-EVOL-04 `audit_refresh_history_below_threshold`: current schema, PIT,
  provenance, and statistical evidence is clean, but the trailing clean audit
  refresh count is 1/3 distinct required vintages.
- Prompt mutation output currently has 9 shadow-only candidates. All keep
  `promotion_state=shadow_candidate_only`,
  `production_prompt_change_allowed=false`, `manual_review_required=true`, and
  `private_text_included=false`.
- Patch v1.5 coverage is accepted after footprint review completion.
- Lockbox remains unopened in the committed registry; promotion gate state is
  consistent with `next_state=staged_production`, and report-derived signals
  remain shadow-only unless a separate promotion task explicitly changes runtime
  behavior.

## Plan Coverage

| Plan Area | Status | Evidence |
| --- | --- | --- |
| P0-P3 stock outcome contract/builders/audits | Implemented | Stock proxy labels use PIT T+1 windows, `SH510300` benchmark, 20 bps cost, stock target resolution, and readiness gaps for missing/conflicting data. |
| P4 tests | Implemented | Focused stock/macro/schema tests are maintained; current final verification commands are listed below. |
| P5 evolution loop | Implemented for shadow evolution, clean-audit history gate still blocked | Prompt mutation candidates, paper-trading, confidence monitor, gold review, footprint review, and audit refresh history feed the evolution gate. RI-EVOL-04 now needs two additional distinct clean audit vintages; current clean count is 1/3. |
| P8 acceptance matrix | Complete for current registry state except distinct-vintage history | Operator readiness, schema, PIT, provenance, statistical audits, footprint review, gold review, lockbox review, and patch coverage pass. |
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
2. Collect two additional distinct clean audit refresh vintages before claiming
   RI-EVOL-04 acceptance; repeated refreshes with the same `data_vintage_hash`
   do not count.
3. Keep reviewed imports and private review aids out of commits; only commit
   public-safe aggregate artifacts and code/tests.
4. Re-run schema, operator, evolution, privacy, and test checks before each
   future public artifact update.
