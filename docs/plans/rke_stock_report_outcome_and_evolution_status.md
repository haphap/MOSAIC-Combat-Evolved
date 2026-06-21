# RKE Stock Report Outcome and Evolution Status

Status date: 2026-06-21

This document tracks implementation evidence for
`docs/plans/rke_stock_report_outcome_and_evolution_plan.md`. It is public-safe:
it records aggregate counts, artifact paths, validation commands, and remaining
gates only. It must not include report prose, titles, abstracts, URLs, PDF or
Markdown paths, source spans, reviewer notes, or private Tushare rows.

## Current State

- Current public-safe extraction summary: 890 selected reports, 890 Markdown-ready
  reports, 999 forecast claims, and 2375 outcome labels.
- Outcome label split: 78 industry ETF proxy labels, 2188 stock price proxy
  labels, 75 macro asset proxy labels, 31 macro direct-series labels, and 3
  macro curve labels.
- Outcome readiness currently has 900 standard ready claims, 707 proxy-label
  ready claims, and 38 still blocked claims.
- Manual gold-set review is imported: 125 reviewed claims across 71 documents;
  all gold quality gates pass.
- Manual analytical-footprint review is partially imported: 2329 reviewed
  footprints pass all measured quality thresholds, but 259 footprint review rows
  are still pending. This keeps `analytical_footprint_review_summary` blocked.
- `schema-status --root . --failures-only --no-write` currently reports 17
  failures, all downstream of the incomplete footprint manual review and patch
  v1.5 coverage gate.
- `operator-readiness --root .` is accepted with 18/18 checks passing.
- `evolution-readiness --root . --no-write` is currently blocked by RI-EVOL-04:
  current PIT, provenance, and statistical audit evidence is clean, but schema
  still has 17 failures from the incomplete footprint review / patch coverage
  gates. Because current schema is blocked, the trailing clean audit refresh
  count is 0/3 distinct required vintages.
- Prompt mutation output currently has 10 shadow-only candidates. All keep
  `promotion_state=shadow_candidate_only`,
  `production_prompt_change_allowed=false`, `manual_review_required=true`, and
  `private_text_included=false`.
- Patch v1.5 coverage is blocked in phases B and D because the analytical
  footprint manual review is incomplete; phases A, C, E, and F pass, while G/H
  remain deferred by rollout policy.
- Direct production remains disabled until lockbox and promotion gates pass.

## Plan Coverage

| Plan Area | Status | Evidence |
| --- | --- | --- |
| P0-P3 stock outcome contract/builders/audits | Implemented | Stock proxy labels use PIT T+1 windows, `SH510300` benchmark, 20 bps cost, stock target resolution, and readiness gaps for missing/conflicting data. |
| P4 tests | Implemented | Focused stock/macro/schema tests are maintained; current final verification commands are listed below. |
| P5 evolution loop | Implemented for shadow evolution, schema/history gate still blocked | Prompt mutation candidates, paper-trading, confidence monitor, gold review, footprint review, and audit refresh history feed the evolution gate. RI-EVOL-04 needs current schema acceptance plus 3 distinct clean audit vintages; current clean count is 0 while schema remains blocked. |
| P8 acceptance matrix | Partially complete | Operator readiness passes, and PIT/provenance/statistical audits pass. Full schema and patch coverage remain blocked by incomplete footprint manual review. |
| P9-P12 coverage/mapping/paper-trading/monitor | Implemented for current sample pool, promotion blocked | Public aggregate artifacts exist; private PDFs, Markdown, source rows, claim text, and reviewed imports remain uncommitted. Patch coverage stays blocked until footprint review completion. |

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
2. Complete the remaining 259 analytical-footprint manual review rows before
   claiming full schema or patch v1.5 coverage acceptance.
3. After schema acceptance is restored, collect three distinct clean audit
   refresh vintages before claiming RI-EVOL-04 acceptance.
4. Re-run schema, operator, evolution, privacy, and test checks before each
   future public artifact update.
