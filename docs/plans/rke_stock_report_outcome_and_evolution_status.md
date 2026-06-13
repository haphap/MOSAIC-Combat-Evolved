# RKE Stock Report Outcome and Evolution Status

Status date: 2026-06-13

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
| `registry/report_intelligence/extraction_report.json` | current public-safe artifact reports 366 outcome labels: 87 industry ETF proxy, 279 stock price proxy. Semantic validation now passes as `schemas/report_intelligence_extraction_report_contract_rules`, which checks repo-relative output paths, public-text redaction, blocker-free aggregate status, public JSONL row counts, Markdown coverage counts, proxy readiness counts, and industry+stock outcome total consistency. |
| `registry/report_intelligence/report_outcome_labels.jsonl` | proxy outcome label semantic validation now requires `claim_window_set_id`, `window_role`, and `source_horizon_days` on both stock and industry proxy labels and rejects any `outcome_id`, `claim_window_set_id`, or `overlap_group_id` shared across `label_type` namespaces. It also checks `window_role` against `horizon_days`, validates `source_horizon_days`, and pins channel-specific `decision_basis` and `evaluation_policy` values. This keeps stock-price and industry-ETF proxy outcomes stratified even when forecast claims, horizons, or proxy symbols overlap. |
| `registry/report_intelligence/patch_v1_5_coverage_report.json` | public count-only fallback preserves aggregate evidence when private JSONL inputs are absent; Phase C now passes, while Phase B/D remain blocked by manual review and footprint quality gates; Phase G remains rollout-gated but now carries shadow paper-trading evidence counts from `recipe_paper_trading_summary.json` |
| `registry/report_intelligence/industry_etf_proxy_map.jsonl` | 64 primary/governed mapping rows; `工业金属` maps to `SH560860` |
| `registry/report_intelligence/industry_etf_proxy_pit_availability.json` | labelability summary is kept consistent with `outcome_labeling_readiness.industry_etf_proxy_readiness`: 146 eligible industry claims, 39 labelable claims, 87 labelable windows, 342 pending future windows |
| `registry/report_intelligence/outcome_labeling_readiness.json` | stock readiness reports 220 eligible stock claims, 124 labelable stock claims, 279 labelable stock windows, and 593 pending future windows; public qlib source fields are redacted to `qlib://...` labels. Semantic validation now passes as `schemas/report_intelligence_stock_price_proxy_readiness_rules`, which hard-checks stock PIT realism policy, ordinary-stock code policy, benchmark/cost defaults, T+1 windows, public qlib redaction, labelable/pending claim counts, and stock series lifecycle totals. Entry-side and exit-side liquidity-verification gaps are tracked separately as `entry_liquidity_unverified` and `exit_liquidity_unverified`; both are blocking readiness gaps and cannot leak into generated labels. The current public artifact remains `survivorship_unverified`, but the contract now also accepts a future `delisted_inclusive_universe_audit_passed` state when the basis documents a passed delisted-inclusive audit. |
| `registry/report_intelligence/source_performance_profiles.jsonl`, `viewpoint_performance_profiles.jsonl`, and `method_performance_profiles.jsonl` | 3114 performance profile rows carry `outcome_layer_support` so profile evidence remains stratified by `label_type`, `benchmark_family`, and `cost_model_id`; semantic validation now passes as `schemas/report_intelligence_profile_outcome_layer_rules`, which checks layer keys, layer summaries, mixed-layer flags, and effective-N sums against each profile. |
| `registry/report_intelligence/recipe_paper_trading_runs.jsonl` | 1858 pre-registered shadow paper-trading runs |
| `registry/report_intelligence/recipe_paper_trading_summary.json` | 20 recipes passed paper-trading validation; 561 recipes have direct or inferred PIT binding; after-cost paper-trading summary is computed from passed pre-registered runs only; 1838 recipes remain blocked by direct binding, effective-N, or shadow-tool readiness gaps |
| `registry/report_intelligence/confidence_impact_monitor.json` and `registry/report_intelligence/monitoring_report.json` | 20 paper-trading validated recipes are monitored; unvalidated confidence impact count is 0; alpha-decay and calibration-drift observations remain shadow-only. `schemas/report_intelligence_alpha_decay_monitoring_rules` now also checks monitoring report corpus counts, tooling-loop counts, tool-gap priority counts, evidence-coverage counts, and source/viewpoint/method effective-N summaries against the underlying public registry artifacts. |
| `registry/report_intelligence/evolution_readiness_gate.json` | blocked; 13 blockers remain, limited to schema/audit-history readiness and manual forecast gold-set quality metrics. The semantic contract now hard-checks P13 machine thresholds in the committed gate evidence, including outcome coverage, stock/industry proxy counts, paper-trading counts and after-cost summary, monitor stability, audit refresh evidence, gap-distribution stability, and P9 coverage status. RI-EVOL-04 now requires current schema/PIT/provenance/statistical evidence to match `current_schema_or_audit_gate_blocked`, and trailing audit distinct/pass counts to match `audit_refresh_history_below_threshold`, even while the gate is blocked. `gap_distribution_history.jsonl` is also semantically checked so `total_gap_count`, `max_gap_name`, `max_gap_share`, `stable`, and `accepted` must match the committed gap counts; a single-gap share above 0.80 cannot be marked stable. |
| `registry/report_intelligence/prompt_mutation_candidates.jsonl` | 11 shadow-only mutation candidates exist across forecast extraction, confidence gating, paper-trading recipe validation, industry mapping, refresh stability, calibration, tool-gap prioritization, and Markdown quality; all have `promotion_state=shadow_candidate_only`, `manual_review_required=true`, `production_prompt_change_allowed=false`, and `private_text_included=false`. The semantic contract also requires the full offline validation matrix (`gold_set_review_pass`, PIT replay, schema, provenance, statistical robustness, and shadow paper-trading), rejects private or non-repo evidence paths in `evidence_refs`, and requires every referenced public evidence artifact to exist. |
| `registry/review_batches/manual_review_progress_report.json` and `registry/gold_sets/tushare_research_reports.review_summary.json` | public baseline: gold-set 0/500, analytical-footprint review 0/1001, source license 17529/17529, lockbox 0/1. Semantic validation now passes as `schemas/report_intelligence_manual_review_progress_rules`, which checks input paths, ready/simulation consistency, blocker consistency, home-tmp command prefixes, dry-run mode, and source-text-free `current_batch_status` counts. It accepts both the current blocked state and a future completed state where all gates have zero pending rows and no blockers. The public gold-set review summary is also checked as `schemas/report_intelligence_gold_review_gate_rules`: current 0/500 pending state is accepted, but false pass states, count drift, missing metrics, and below-threshold human review metrics are rejected. Synthetic pytest fixtures can mark manual rows complete for contract tests, but current target hashes in the real scratch still require human review. The report now includes aggregate `current_batch_status` for the active local 50-row gold-set, analytical-footprint, and lockbox scratch files, plus a public-safe full pending `batch_plan`: 10 gold-set batches and 21 analytical-footprint batches at 50 rows per batch except the final 1-row footprint batch. Each batch explicitly records `apply_effect=merge_batch_into_target_review_template`, the transient `batch_input_path` for the 50-row import, the `target_review_template_path` it merges into, and the separate `promotion_input_path` used only after full human review; schema validation also rejects batch commands that use promotion inputs and promotion commands that use transient batch inputs. Current gold batch status is 50 rows, 0 complete, 50 pending, 0 malformed; missing required fields are aggregate counts only. Current analytical-footprint batch status is 50 rows, 0 complete, 50 pending, 0 malformed; missing required fields are aggregate counts only. Current lockbox decision status is 1 row, 0 complete, 1 pending, 0 malformed; missing required fields are aggregate counts only. Full gold-set and footprint review imports still require human decisions before promotion dry-run. |
| `registry/handoffs/rke_operator_handoff.json` | operator handoff semantic validation now passes as `schemas/report_intelligence_operator_handoff_rules`: command sequence order, home-tmp prefixes, reviewed input paths, promotion dry-run inputs, and production-disabled state are checked directly against the handoff artifact |
| `registry/handoffs/rke_operator_readiness_report.json` | operator readiness currently passes 16/16 checks: required registry valid, handoff command sequence complete, manual import templates sparse and provenance-tagged, batch inputs separated from promotion inputs, blank gold/lockbox/source-license templates rejected, blank bundle dry-run does not promote, manual review bundle manifest current, and promotion gate state matches PG01-PG10 criteria |
| `registry/review_batches/manual_review_bundle_manifest.json` | manual review bundle manifest semantic validation now re-computes artifact bytes and SHA-256 digests, validates the embedded promotion dry-run summary against `registry/promotion/rke_promotion_dry_run_report.json`, and accepts both the current blocked dry-run summary and a future completed summary when all dry-run steps are accepted and no missing/rejected steps remain. |
| `registry/promotion/rke_promotion_dry_run_report.json` | promotion dry-run semantic validation now passes as `schemas/report_intelligence_promotion_dry_run_rules`: the report is simulated, does not mutate the original registry, has all four manual review steps, and checks `accepted`, blockers, `after_next_state`, staged/production flags, and per-step states for consistency. It accepts the current blocked dry-run and future completed simulations, while rejected dry-runs must still carry blockers. |
| `registry/promotion/rke_production_promotion_gate.json` | production promotion gate semantic validation now passes as `schemas/report_intelligence_production_promotion_gate_rules`: PG01-PG10 are complete, failed criteria carry blockers, blocker summaries match criteria, staged production requires PG01-PG08, and production requires PG01-PG10 with an empty blocker list. The current public baseline remains `paper_trading`, but the contract also accepts a future production state only when all criteria pass. |

## Plan Coverage

| Plan Area | Status | Evidence |
| --- | --- | --- |
| P0 stock evaluation data contract | Implemented | `ReportIntelligenceConfig.qlib_stock_dir`, `--qlib-stock-dir`, stock target resolution, target conflict gaps, and ordinary-stock code policy requiring SH60/SH68, SZ00/SZ30, and BJ92 while rejecting fund/ETF/LOF/index code families |
| P1 stock proxy outcome labeler | Implemented | `build_stock_price_proxy_readiness()`, `build_stock_price_proxy_outcome_labels()` |
| P2 stock scoring logic | Implemented | stock/benchmark return, relative alpha, after-cost alpha, directional hit fields in stock labels |
| P3 artifacts, schemas, audits | Implemented | outcome-label/readiness schema updates; extraction report and stock proxy readiness semantic contracts; PIT, provenance, statistical, recipe, runtime audits pass |
| P4 core tests | Implemented | `tests/test_rke_report_intelligence.py` stock label/readiness/PIT tests pass |
| P5 evolution loop | Partially implemented | mutation candidates, tool-gap prioritization, paper-trading and monitor inputs exist; promotion remains blocked by manual review gates |
| P6 decisions | Implemented for default path | default benchmark `SH510300` from `cn_etf`; stock cost 20 bps; stock windows 5/20/60/120; no company-name fuzzy mapping |
| P7 implementation breakdown | Implemented | qlib helpers, readiness builder, label builder, derived refresh integration, audits, schemas, tests, proxy outcome ID namespace contracts, and profile layer contracts that prevent cross-label-type/benchmark/cost aggregation from replacing stratified evidence |
| P8 acceptance matrix | Automated acceptance passes except manual review / coverage gates | ruff, report-intelligence tests, schema-artifact tests, prompt leak guard, diff check pass; `schema-status` intentionally exits 2 until analytical footprint review, Phase B gold-set review, and Phase D footprint quality gates pass; `prepare-footprint-review` now creates a gitignored import scaffold for the footprint gate |
| P9 PDF/Markdown coverage expansion | Implemented for current sample pool | public coverage summary exists and passes privacy rules; private PDF/Markdown/cache paths remain gitignored |
| P10 industry ETF mapping/PIT availability | Implemented | 64-row mapping registry, PIT availability artifact, mapping contract tests; `工业金属 -> SH560860` pinned; semantic validation now rejects drift between PIT availability `labelability_summary` and `outcome_labeling_readiness` |
| P11 recipe paper-trading | Implemented and threshold-cleared for current aggregate evidence | pre-registration hash, OOS chronological split, required data contracts, cost/benchmark protocol, 1858 paper-trading runs, 20 validated recipes |
| P12 confidence impact monitor | Implemented and threshold-cleared for current aggregate evidence | monitor rows gate confidence impact on paper-trading validation; 20 validated recipes are monitored; alpha decay and calibration drift actions are tracked; monitoring report aggregate counts are semantically checked against public registry artifacts |

## Validation Commands

Last broad local validation set:

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

The repository pytest default is also configured to keep its `--basetemp` under
`/home/hap/tmp/mosaic-rke/pytest-mosaic-rke`; `tests/conftest.py` uses the same
home tmp root for the private Tushare fixture lock file. This prevents ordinary
test runs from placing large registry copies or fixture locks in system `/tmp`
or under the repository checkout.

Most recent focused validation after the proxy entry-lag hardening:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_report_intelligence.py::test_report_intelligence_entry_calendar_index_uses_explicit_lag tests/test_rke_report_intelligence.py::test_report_intelligence_labels_industry_claims_with_etf_proxy_windows tests/test_rke_report_intelligence.py::test_report_intelligence_labels_stock_claims_with_qlib_price_windows tests/test_rke_report_intelligence.py::test_report_intelligence_pit_audit_rejects_t0_stock_entry -q --basetemp /home/hap/tmp/mosaic-rke/pytest-entry-lag-explicit
uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py tests/test_rke_report_intelligence.py
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python scripts/check_prompt_leaks.py
git diff --check
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .
```

The helper that computes entry dates now requires an explicit
`entry_lag_trading_days` argument. Industry proxy builders pass
`INDUSTRY_ETF_ENTRY_LAG_TRADING_DAYS`; stock proxy builders pass
`STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS`. This keeps the T+1 entry invariant
auditable if either channel later changes its lag policy.

Most recent focused validation after proxy outcome ID namespace hardening:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_cross_label_type_id_collisions -q --basetemp /home/hap/tmp/mosaic-rke/pytest-id-contract
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-schema-id-contract
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py mosaic/rke/report_intelligence.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after RI-EVOL-04 audit blocker hardening:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py::test_evolution_readiness_gate_contract_accepts_current_public_artifact tests/test_rke_schema_artifacts.py::test_evolution_readiness_gate_contract_rejects_missing_current_audit_blocker tests/test_rke_schema_artifacts.py::test_evolution_readiness_gate_contract_rejects_stale_audit_history_blocker -q --basetemp /home/hap/tmp/mosaic-rke/pytest-evolution-audit-contract
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-schema-evolution-audit
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the evolution readiness gate semantic
record is accepted.

Most recent focused validation after proxy outcome window-policy hardening:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_bad_window_policy_fields -q --basetemp /home/hap/tmp/mosaic-rke/pytest-window-policy-contract
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-schema-window-policy
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

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
private evidence draft covers 1001 rows with 0 missing local markdown rows. It
now emits structured `suggested_review_rationales` for span support, metric
mapping, inferred step tagging, uncertainty handling, and leakage checks, plus
review-only inferred indicator candidates for missing metric mappings. These
also are not import files.

`MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .`
currently exits with code 2 by design. The current failing semantic records are
`schemas/report_intelligence_analytical_footprint_review_rules` and
`schemas/report_intelligence_patch_v1_5_coverage_rules`, because the analytical
footprint review gate, Phase B human gold-set review, and Phase D footprint
quality gates have not passed. All ordinary schema records, proxy outcome
contracts, mapping/PIT availability contracts, recipe paper-trading contracts,
runtime guards, PIT/provenance/statistical/tooling audits, refresh-history
contracts, operator handoff rules, promotion dry-run rules, and
production-promotion gate semantic rules pass in the current public artifact set.
Profile outcome-layer semantic rules now also pass for 3114 source, viewpoint,
and method performance profiles, ensuring mixed stock/industry proxy evidence
stays stratified by `label_type`, `benchmark_family`, and `cost_model_id`.
The stock readiness contract now also rejects drift in
`ordinary_stock_code_policy`, so ordinary stock labels remain limited to
`SH60/SH68`, `SZ00/SZ30`, and `BJ92` code families; fund, ETF, LOF, index, and
legacy BJ 8-prefix codes stay out of the stock proxy outcome channel.

## Remaining Gates

The objective is not complete until the evolution readiness gate passes. Current
blocker families include:

1. Manual/operator gates: gold-set review, analytical-footprint review, and
   lockbox review remain pending, and schema-status still reports
   analytical-footprint review and patch coverage semantic blockers.
   Source-license review is ready in the current public
   progress report. The gold-set scratch file was regenerated with
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke prepare-gold-review --root . --full --force`; the remaining
   gold-set blockers are the 500 required human review rows. The private
   gold review evidence draft now emits `suggested_review_rationales` and
   aggregate triage tags for context synthesis, variable-mapping review,
   mechanism-support review, and manual claim compaction; these remain
   non-import review aids and do not fill any human decision fields. The footprint
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
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke operator-readiness --root .`,
   promotion dry-run, and
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .`.

Until those gates pass, evolution outputs remain shadow candidates and must not
modify production prompts or production trading decisions.
