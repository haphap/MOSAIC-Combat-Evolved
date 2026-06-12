# RKE Stock Report Outcome and Evolution Status

Status date: 2026-06-12

This document tracks implementation evidence for
`docs/plans/rke_stock_report_outcome_and_evolution_plan.md`. It is public-safe:
it records aggregate counts, artifact paths, validation commands, and remaining
gates only. It must not include report prose, titles, abstracts, URLs, PDF or
Markdown paths, source spans, reviewer notes, or private Tushare rows.

## Current State

- Stock proxy outcome labels are implemented and materialized as
  `label_type=stock_price_proxy` with `outcome_label_source=pit_stock_price_window`.
- Industry ETF proxy labels remain implemented as
  `label_type=industry_etf_proxy`.
- Outcome labels are shadow-only. `llm_outcome_labeling_allowed=false` remains
  required; LLM output extracts claims and methods only.
- Evolution is not promotable yet. The current public aggregate evidence still
  has manual review and audit-history readiness blockers. The checked-in public
  baseline still has gold-set, analytical-footprint, and lockbox manual blockers;
  source-license review is ready. Synthetic pytest fixtures can mark manual rows
  complete for contract tests, but that does not open the real promotion gate.

Current public aggregate evidence. Private report-intelligence JSONL files such
as `report_metadata.jsonl`, `forecast_claims.jsonl`, and
`report_outcome_labels.jsonl` may be absent on a clean or public-safe checkout;
the committed evidence below comes from public aggregate artifacts and schema
contracts.

| Artifact | Evidence |
| --- | --- |
| `registry/report_intelligence/extraction_report.json` | current public-safe artifact reports 366 outcome labels: 87 industry ETF proxy, 279 stock price proxy |
| `registry/report_intelligence/patch_v1_5_coverage_report.json` | public count-only fallback preserves aggregate evidence when private JSONL inputs are absent; Phase C now passes, while Phase B/D remain blocked by manual review and footprint quality gates |
| `registry/report_intelligence/industry_etf_proxy_map.jsonl` | 64 primary/governed mapping rows; `工业金属` maps to `SH560860` |
| `registry/report_intelligence/industry_etf_proxy_pit_availability.json` | labelability summary is kept consistent with `outcome_labeling_readiness.industry_etf_proxy_readiness`: 146 eligible industry claims, 39 labelable claims, 87 labelable windows, 342 pending future windows |
| `registry/report_intelligence/recipe_paper_trading_runs.jsonl` | 1858 pre-registered shadow paper-trading runs |
| `registry/report_intelligence/recipe_paper_trading_summary.json` | 20 recipes passed paper-trading validation; 561 recipes have direct or inferred PIT binding; after-cost paper-trading summary is computed from passed pre-registered runs only; 1838 recipes remain blocked by direct binding, effective-N, or shadow-tool readiness gaps |
| `registry/report_intelligence/confidence_impact_monitor.json` | 20 paper-trading validated recipes are monitored; unvalidated confidence impact count is 0; alpha-decay and calibration-drift observations remain shadow-only |
| `registry/report_intelligence/evolution_readiness_gate.json` | blocked; 13 blockers remain, limited to schema/audit-history readiness and manual forecast gold-set quality metrics |
| `registry/review_batches/manual_review_progress_report.json` | public baseline: gold-set 0/500, analytical-footprint review 0/1001, source license 17529/17529, lockbox 0/1; Synthetic pytest fixtures can mark manual rows complete for contract tests, but current target hashes in the real scratch still require human review. The report now includes source-text-free `current_batch_status` for the active local 50-row gold-set, analytical-footprint, and lockbox scratch files. Current gold batch status is 50 rows, 0 complete, 50 pending, 0 malformed; missing required fields are aggregate counts only. Current analytical-footprint batch status is 50 rows, 0 complete, 50 pending, 0 malformed; missing required fields are aggregate counts only. Current lockbox decision status is 1 row, 0 complete, 1 pending, 0 malformed; missing required fields are aggregate counts only. Full gold-set and footprint review imports still require human decisions before promotion dry-run. |

## Plan Coverage

| Plan Area | Status | Evidence |
| --- | --- | --- |
| P0 stock evaluation data contract | Implemented | `ReportIntelligenceConfig.qlib_stock_dir`, `--qlib-stock-dir`, stock target resolution, target conflict gaps |
| P1 stock proxy outcome labeler | Implemented | `build_stock_price_proxy_readiness()`, `build_stock_price_proxy_outcome_labels()` |
| P2 stock scoring logic | Implemented | stock/benchmark return, relative alpha, after-cost alpha, directional hit fields in stock labels |
| P3 artifacts, schemas, audits | Implemented | outcome-label/readiness schema updates; PIT, provenance, statistical, recipe, runtime audits pass |
| P4 core tests | Implemented | `tests/test_rke_report_intelligence.py` stock label/readiness/PIT tests pass |
| P5 evolution loop | Partially implemented | mutation candidates, tool-gap prioritization, paper-trading and monitor inputs exist; promotion remains blocked by manual review gates |
| P6 decisions | Implemented for default path | default benchmark `SH510300` from `cn_etf`; stock cost 20 bps; stock windows 5/20/60/120; no company-name fuzzy mapping |
| P7 implementation breakdown | Implemented | qlib helpers, readiness builder, label builder, derived refresh integration, audits, schemas, tests |
| P8 acceptance matrix | Automated acceptance passes except manual review / coverage gates | ruff, report-intelligence tests, schema-artifact tests, prompt leak guard, diff check pass; `schema-status` intentionally exits 2 until analytical footprint review, Phase B gold-set review, and Phase D footprint quality gates pass; `prepare-footprint-review` now creates a gitignored import scaffold for the footprint gate |
| P9 PDF/Markdown coverage expansion | Implemented for current sample pool | public coverage summary exists and passes privacy rules; private PDF/Markdown/cache paths remain gitignored |
| P10 industry ETF mapping/PIT availability | Implemented | 64-row mapping registry, PIT availability artifact, mapping contract tests; `工业金属 -> SH560860` pinned; semantic validation now rejects drift between PIT availability `labelability_summary` and `outcome_labeling_readiness` |
| P11 recipe paper-trading | Implemented and threshold-cleared for current aggregate evidence | pre-registration hash, OOS chronological split, required data contracts, cost/benchmark protocol, 1858 paper-trading runs, 20 validated recipes |
| P12 confidence impact monitor | Implemented and threshold-cleared for current aggregate evidence | monitor rows gate confidence impact on paper-trading validation; 20 validated recipes are monitored; alpha decay and calibration drift actions are tracked |

## Validation Commands

Last local validation set:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-schema-artifacts
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_report_intelligence.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-ri-current
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_*.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-all-current
uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py mosaic/rke/schema_validation.py tests/conftest.py tests/test_rke_report_intelligence.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python scripts/check_prompt_leaks.py
git diff --check
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke review-progress --root .
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke operator-readiness --root .
```

Current manual review evidence and scaffold commands:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke write-gold-review-evidence --root . --limit 50 --offset 0
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke prepare-gold-review --root . --gold-batch-size 50 --offset 0 --force --reviewer hap --review-date 2026-06-12
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl --dry-run
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke prepare-gold-review --root . --full --force --reviewer hap --review-date 2026-06-12
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke prepare-footprint-review --root . --limit 50 --offset 0 --reviewer hap --review-date 2026-06-12 --overwrite
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke prepare-footprint-review --root . --output registry/report_intelligence/analytical_footprint_reviewed.jsonl --reviewer hap --review-date 2026-06-12 --overwrite
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke write-footprint-review-assist --root .
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0
```

These commands write private, gitignored manual handoff files. The current
active gold-set batch has 50 pending rows and aggregate missing-field counts for
`manual_claim_text`, the seven boolean review fields, and reviewer decision
fields where applicable. The private gold-set evidence draft now covers 500 rows
with 0 missing local markdown rows after cache fallback; 500 rows still require manual claim text and boolean review decisions. The current active
analytical-footprint batch has 50 pending rows and aggregate missing-field counts
for `footprint_correct`,
`source_span_supports_footprint`, `metric_mapping_correct`,
`inferred_steps_tagged_correctly`, `unknowns_used_when_uncertain`,
`no_proprietary_text_leakage`, and `review_notes`. The assist command writes
private, gitignored helper files at
`registry/report_intelligence/analytical_footprint_review_assist.jsonl` and
`registry/report_intelligence/analytical_footprint_review_workbook.md`; private footprint review assist/workbook cover 1001 pending rows. These files are not import files and do not satisfy the review gate by themselves. The evidence command writes private, gitignored local-markdown snippets and draft review suggestions at
`registry/report_intelligence/analytical_footprint_review_evidence.jsonl` and
`registry/report_intelligence/analytical_footprint_review_evidence.md`; the
private evidence draft covers 1001 rows with 0 missing local markdown rows.
These also are not import files.

`MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .`
currently exits with code 2 by design. The current failing semantic records are
`schemas/report_intelligence_analytical_footprint_review_rules` and
`schemas/report_intelligence_patch_v1_5_coverage_rules`, because the analytical
footprint review gate, Phase B human gold-set review, and Phase D footprint
quality gates have not passed. All ordinary schema records, proxy outcome
contracts, mapping/PIT availability contracts, recipe paper-trading contracts,
runtime guards, PIT/provenance/statistical/tooling audits, and refresh-history
contracts pass in the current public artifact set.

## Remaining Gates

The objective is not complete until the evolution readiness gate passes. Current
blocker families include:

1. Manual/operator gates: gold-set review, analytical-footprint review, and
   lockbox review remain pending, and schema-status still reports
   analytical-footprint review and patch coverage semantic blockers.
   Source-license review is ready in the current public
   progress report. The gold-set scratch file was regenerated with
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke prepare-gold-review --root . --full --force`; the remaining
   gold-set blockers are the 500 required human review rows. The footprint
   reviewed scratch file was regenerated with
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke prepare-footprint-review --root . --output registry/report_intelligence/analytical_footprint_reviewed.jsonl --overwrite`;
   the remaining footprint blockers are the 1001 required human review rows.
   Validate with
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`,
   then apply through the same import path.
2. P9 coverage watchlist: current public gate reports `coverage_gate_status=passed`
   with no P9 coverage blockers. Continue monitoring the watchlist, but it is
   not currently blocking evolution readiness.
3. Outcome evidence: current gate thresholds are cleared: 159 unique PIT outcome
   claims, 39 industry proxy claims, and 124 stock proxy claims.
4. Paper-trading evidence: current gate thresholds are cleared: 1858
   pre-registered runs, 20 validated recipes, and an after-cost summary computed
   from passed pre-registered runs only. Remaining recipe rows stay blocked or
   shadow-only when direct PIT binding, effective N, or shadow-tool readiness is
   insufficient.
5. Confidence impact monitor: current gate thresholds are cleared with 20
   monitored validated recipes and no unvalidated confidence impact. Alpha decay
   and calibration drift observations are tracked but remain shadow-only.
6. Refresh-history stability: audit history must satisfy the trailing-vintage
   gate; monitor and gap-distribution trailing-vintage gates currently pass.
7. Re-run
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke review-progress --root .`,
   promotion dry-run, and
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .`.

Until those gates pass, evolution outputs remain shadow candidates and must not
modify production prompts or production trading decisions.
