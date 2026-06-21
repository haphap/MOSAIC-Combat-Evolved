# RKE Stock Report Outcome and Evolution Status

Status date: 2026-06-21

This document tracks implementation evidence for
`docs/plans/rke_stock_report_outcome_and_evolution_plan.md`. It is public-safe:
it records aggregate counts, artifact paths, validation commands, and remaining
gates only. It must not include report prose, titles, abstracts, URLs, PDF or
Markdown paths, source spans, reviewer notes, or private Tushare rows.

## Current State

- Current public-safe extraction summary: 863 selected reports, 863 Markdown-ready
  reports, 963 forecast claims, and 2288 outcome labels.
- Outcome label split: 78 industry ETF proxy labels, 2188 stock price proxy
  labels, and 22 macro asset proxy labels.
- Manual gold-set review is imported: 125 reviewed claims across 71 documents;
  all gold quality gates pass.
- Manual analytical-footprint review is imported: 2446 reviewed footprints;
  all footprint quality gates pass.
- `schema-status --root . --failures-only` is accepted with zero failures.
- `operator-readiness --root .` is accepted with 18/18 checks passing.
- `evolution-readiness --root .` is accepted. RI-EVOL-01 through RI-EVOL-07
  pass, including RI-EVOL-04.
- RI-EVOL-04 has 3 distinct clean `data_vintage_hash` values. The current
  schema, PIT, provenance, and statistical checks all pass, and no additional
  audit refresh vintage is required for this plan gate.
- Prompt mutation output currently has 8 shadow-only candidates. All keep
  `promotion_state=shadow_candidate_only`,
  `production_prompt_change_allowed=false`, `manual_review_required=true`, and
  `private_text_included=false`.
- Direct production remains disabled until lockbox and promotion gates pass.

## Plan Coverage

| Plan Area | Status | Evidence |
| --- | --- | --- |
| P0-P3 stock outcome contract/builders/audits | Implemented | Stock proxy labels use PIT T+1 windows, `SH510300` benchmark, 20 bps cost, stock target resolution, and readiness gaps for missing/conflicting data. |
| P4 tests | Implemented | Focused stock/macro/schema tests are maintained; current final verification commands are listed below. |
| P5 evolution loop | Implemented for shadow evolution | Prompt mutation candidates, paper-trading, confidence monitor, gold review, footprint review, and audit refresh history feed the evolution gate. |
| P8 acceptance matrix | Complete for this plan | Schema, operator, and evolution gates all pass. RI-EVOL-04 has 3/3 distinct clean audit vintages. |
| P9-P12 coverage/mapping/paper-trading/monitor | Implemented for current sample pool | Public aggregate artifacts exist and pass schema; private PDFs, Markdown, source rows, claim text, and reviewed imports remain uncommitted. |

## Current Verification Commands

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp .venv/bin/mosaic-rke schema-status --root . --failures-only
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp .venv/bin/mosaic-rke operator-readiness --root .
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp .venv/bin/mosaic-rke evolution-readiness --root .
uvx ruff@0.15.15 check mosaic tests
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-artifacts
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python scripts/check_prompt_leaks.py
git diff --check
```

## Residual Operational Follow-Up

1. Keep prompt mutation candidates shadow-only until future lockbox and
   production promotion approvals explicitly allow production changes.
2. Re-run schema, operator, evolution, privacy, and test checks before each
   future public artifact update.
