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
  has manual review, paper-trading, and audit-history readiness blockers. The
  checked-in public baseline still has gold-set, source-license, and lockbox
  promotion blockers; the synthetic pytest fixture can mark
  gold-set/source-license rows complete for contract tests, but that does not
  open the real promotion gate.

Current public aggregate evidence. Private report-intelligence JSONL files such
as `report_metadata.jsonl`, `forecast_claims.jsonl`, and
`report_outcome_labels.jsonl` may be absent on a clean or public-safe checkout;
the committed evidence below comes from public aggregate artifacts and schema
contracts.

| Artifact | Evidence |
| --- | --- |
| `registry/report_intelligence/extraction_report.json` | current public-safe artifact reports 184 outcome labels: 36 industry ETF proxy, 148 stock price proxy |
| `registry/report_intelligence/patch_v1_5_coverage_report.json` | public count-only fallback preserves aggregate evidence when private JSONL inputs are absent; Phase C now passes, while Phase B/D remain blocked by manual review and footprint quality gates |
| `registry/report_intelligence/industry_etf_proxy_map.jsonl` | 64 primary/governed mapping rows; `工业金属` maps to `SH560860` |
| `registry/report_intelligence/recipe_paper_trading_runs.jsonl` | 110 pre-registered shadow paper-trading runs |
| `registry/report_intelligence/recipe_paper_trading_summary.json` | 0 recipes passed paper-trading validation; direct PIT binding diagnostics show 110 recipes still lack direct recipe-outcome binding and 110 recipes remain blocked by requested-tool placeholders |
| `registry/report_intelligence/confidence_impact_monitor.json` | 0 paper-trading validated recipes; confidence impact remains blocked until recipe validation passes |
| `registry/report_intelligence/evolution_readiness_gate.json` | blocked; 16 blockers remain across manual review, outcome-count, paper-trading, schema/audit, and audit-history readiness; public count-only fallback preserves outcome coverage when private label JSONL is absent |
| `registry/review_batches/manual_review_progress_report.json` | public baseline: gold-set 0/500, source license 0/1216, lockbox 0/1; synthetic fixture: gold-set 500/500, source license 50/50, lockbox 0/1 |

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
| P8 acceptance matrix | Automated acceptance passes except manual review / coverage gates | ruff, report-intelligence tests, schema-artifact tests, prompt leak guard, diff check pass; `schema-status` intentionally exits 2 until analytical footprint review, Phase B gold-set review, and Phase D footprint quality gates pass |
| P9 PDF/Markdown coverage expansion | Implemented for current sample pool | public coverage summary exists and passes privacy rules; private PDF/Markdown/cache paths remain gitignored |
| P10 industry ETF mapping/PIT availability | Implemented | 64-row mapping registry, PIT availability artifact, mapping contract tests; `工业金属 -> SH560860` pinned |
| P11 recipe paper-trading | Implemented | pre-registration hash, OOS chronological split, required data contracts, cost/benchmark protocol, paper-trading runs and summary |
| P12 confidence impact monitor | Implemented | monitor rows gate confidence impact on paper-trading validation; alpha decay and calibration drift actions are tracked |

## Validation Commands

Last local validation set:

```bash
uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /tmp/pytest-rke-schema-artifacts
uv run python -m pytest tests/test_rke_report_intelligence.py -q --basetemp /tmp/pytest-rke-ri-current
uv run python -m pytest tests/test_rke_*.py -q --basetemp /tmp/pytest-rke-all-current
uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py mosaic/rke/schema_validation.py tests/conftest.py tests/test_rke_report_intelligence.py tests/test_rke_schema_artifacts.py
uv run python scripts/check_prompt_leaks.py
git diff --check
```

`uv run mosaic-rke schema-status --root .` currently exits with code 2 by
design. The failing semantic records are
`schemas/report_intelligence_analytical_footprint_review_rules` and
`schemas/report_intelligence_patch_v1_5_coverage_rules`, because the analytical
footprint review gate, Phase B human gold-set review, and Phase D footprint
quality gates have not passed. Phase C now passes from public aggregate counts
even when private report-intelligence JSONL files are absent.

## Remaining Gates

The objective is not complete until the evolution readiness gate passes. Current
blocker families include:

1. Manual/operator gates: lockbox review remains pending, and schema-status
   still reports analytical-footprint review and patch coverage semantic blockers.
2. P9 coverage watchlist: current public gate reports `coverage_gate_status=passed`
   with no P9 coverage blockers. Continue monitoring the watchlist, but it is
   not currently blocking evolution readiness.
3. Outcome evidence: `industry_proxy_claim_count_below_threshold` remains
   (`12/30`), and total unique PIT outcome labels are below the evolution
   threshold (`49/100`); stock proxy labels now clear the minimum stock
   threshold (`37/30`).
4. Paper-trading evidence: `paper_trading_run_count_below_threshold` and
   `paper_trading_validated_recipe_count_below_threshold` remain. The
   after-cost summary object is now present, but it is marked
   `insufficient_validated_runs` until enough pre-registered recipes pass.
   `direct_pit_binding_diagnostics.status=blocked_no_direct_pit_binding`
   records that profile weights are not being used as a substitute for direct
   PIT recipe validation.
5. Refresh-history stability: audit history must satisfy the trailing-vintage
   gate; monitor and gap-distribution trailing-vintage gates currently pass.
6. Re-run `mosaic-rke review-progress --root .`, promotion dry-run, and
   `mosaic-rke schema-status --root .`.

Until those gates pass, evolution outputs remain shadow candidates and must not
modify production prompts or production trading decisions.
