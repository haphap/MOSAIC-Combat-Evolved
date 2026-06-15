# RKE Stock Report Outcome and Evolution Status

Status date: 2026-06-16

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
  source-license review is already applied and no longer appears as a runnable
  action. Synthetic pytest fixtures can mark manual rows complete for contract
  tests, but that does not open the real promotion gate.
- Manual review action queues now expose a public-safe
  `current_batch_review_field_workload_summary` alongside per-field workload
  counts. In the current local scratch state, the active 26-row gold batch has
  208 missing required review cells, 97 evidence-draft cells available for
  human verification, and 111 cells that still require manual input. The active
  50-row analytical-footprint batch has 350 missing required review cells, 300
  evidence-draft cells available for human verification, and 50 cells that
  still require manual input. These summaries are review aids only; they do not
  auto-fill human decision fields. The same queue now includes
  `current_batch_review_field_action_order`, which sorts fields that still need
  manual input separately from fields with evidence-draft decisions available
  for human verification, and
  `current_batch_review_field_workflow_groups`, which separates boolean
  decision fields, reviewer/date metadata fields, free-text fields, and
  draft-decision verification fields.
- The current batch overview and runbook now also expose
  `current_batch_quality_gap_review_focus`, a public-safe metric-to-field focus
  list that maps failing quality gates to the exact review fields and aggregate
  evidence counts in the active scratch batch. The current gold focus is
  `variable_mapping_accuracy -> variable_mapping_correct`,
  `unsupported_field_false_grounding_rate -> unsupported_field_false_grounded`,
  and `direction_accuracy -> direction_correct`; the current footprint focus is
  `metric_mapping_accuracy -> metric_mapping_correct`.
  The same batch overview is now persisted in
  `manual_review_progress_report.json` and emitted by default `review-progress`
  output, so bundle consumers see the same focus fields as the action queue.
  The manual review progress semantic contract now rejects batch-overview drift
  from the persisted current-batch status and pending batch plan.
  `promotion-status --no-write` now also carries the same gold-set batch
  overview and nested manual review gate actions for lockbox dependency work.

Current public aggregate evidence. Private report-intelligence JSONL files such
as `report_metadata.jsonl`, `forecast_claims.jsonl`, and
`report_outcome_labels.jsonl` may be absent on a clean or public-safe checkout;
the committed evidence below comes from public aggregate artifacts and schema
contracts.

| Artifact | Evidence |
| --- | --- |
| `registry/report_intelligence/extraction_report.json` | current public-safe artifact reports 341 forecast claims and 336 outcome labels: 87 industry ETF proxy, 248 stock price proxy, 1 macro asset proxy. Semantic validation now passes as `schemas/report_intelligence_extraction_report_contract_rules`, which checks repo-relative output paths, public-text redaction, blocker-free aggregate status, public JSONL row counts, Markdown coverage counts, proxy readiness counts, and industry+stock+macro outcome total consistency. |
| `registry/report_intelligence/report_outcome_labels.jsonl` | proxy outcome label semantic validation now requires `claim_window_set_id`, `window_role`, and `source_horizon_days` on both stock and industry proxy labels and rejects any `outcome_id`, `claim_window_set_id`, or `overlap_group_id` shared across `label_type` namespaces. It also checks `window_role` against `horizon_days`, validates `source_horizon_days`, validates `entry_datetime`/`exit_datetime` date order, pins channel-specific `decision_basis` and `evaluation_policy` values, checks per-window `effective_n_weight` against the governed stock/industry window weight table, rejects any claim window set whose total effective-N weight exceeds 1, and, when private forecast claims are present, requires every proxy label to trace to an existing forecast claim whose `signal_datetime` date is before the proxy `entry_datetime` date; stock proxy claims must cite source spans. Stock proxy labels also require `metadata_ts_code` and `llm_target_id` fields and semantically validate `target_resolution_source`: metadata-only, LLM-only, and metadata+LLM resolutions must support the same ordinary-stock `proxy_symbol`; conflicting ts_codes cannot generate labels. Both stock and industry proxy labels must use the default `SH510300`/`cn_etf`/`CSI300_ETF_PROXY` benchmark family; stock labels must use `single_stock_round_trip_20bps_v1` and `round_trip_cost=0.002`, while industry ETF labels must use `industry_etf_round_trip_10bps_v1` and `round_trip_cost=0.001`. This keeps stock-price and industry-ETF proxy outcomes stratified and source-grounded even when forecast claims, horizons, or proxy symbols overlap. |
| `registry/report_intelligence/patch_v1_5_coverage_report.json` | public count-only fallback preserves aggregate evidence when private JSONL inputs are absent; Phase C now passes, while Phase B/D remain blocked by manual review and footprint quality gates; Phase G remains rollout-gated but now carries shadow paper-trading evidence counts from `recipe_paper_trading_summary.json` |
| `registry/report_intelligence/industry_etf_proxy_map.jsonl` | 64 primary/governed mapping rows; `工业金属` maps to `SH560860` |
| `registry/report_intelligence/industry_etf_proxy_pit_availability.json` | labelability summary is kept consistent with `outcome_labeling_readiness.industry_etf_proxy_readiness`: 105 eligible industry claims, 39 labelable claims, 87 labelable windows, 225 pending future windows. The P10 action summary is public-safe and aggregate-only: it records 38 `sector_etf_mapping_missing` claim gaps, 1 PIT-unavailable mapping, `labelability_rate=0.371429`, `primary_mapping_coverage_rate=0.734266`, and next actions to add primary ETF mappings for unmapped sectors and refresh or replace PIT-unavailable ETF mappings. |
| `registry/report_intelligence/outcome_labeling_readiness.json` | stock readiness reports 171 eligible stock claims, 115 labelable stock claims, 248 labelable stock windows, and 432 pending future windows; macro asset readiness reports 4 eligible macro asset claims, 1 labelable macro asset window, 1 macro asset proxy outcome label, and 15 pending future windows; public qlib source fields are redacted to `qlib://...` labels. Semantic validation now passes as `schemas/report_intelligence_stock_price_proxy_readiness_rules`, which hard-checks stock PIT realism policy, ordinary-stock code policy, benchmark/cost defaults, T+1 windows, public qlib redaction, labelable/pending claim counts, and stock series lifecycle totals. Entry-side and exit-side liquidity-verification gaps are tracked separately as `entry_liquidity_unverified` and `exit_liquidity_unverified`; suspension, limit-lock, delisting, and liquidity gaps are allowed as readiness `data_gap_counts`, but remain blocking gaps that cannot leak into generated labels. The current public artifact remains `survivorship_unverified`, but the contract now also accepts a future `delisted_inclusive_universe_audit_passed` state when the basis documents a passed delisted-inclusive audit. |
| `registry/report_intelligence/source_performance_profiles.jsonl`, `viewpoint_performance_profiles.jsonl`, and `method_performance_profiles.jsonl` | 3246 performance profile rows carry `outcome_layer_support` so profile evidence remains stratified by `label_type`, `benchmark_family`, and `cost_model_id`; semantic validation now passes as `schemas/report_intelligence_profile_outcome_layer_rules`, which checks layer keys, layer summaries, mixed-layer flags, and effective-N sums against each profile. |
| `registry/report_intelligence/recipe_paper_trading_runs.jsonl` | 2031 pre-registered shadow paper-trading runs. Semantic validation now requires every run to carry unique deterministic `paper_trading_run_id` and `experiment_id` values bound to `analysis_recipe_id` plus `recipe_shadow_paper_trading_v1`, so P11's experiment identity cannot be silently duplicated or post-hoc rewritten. |
| `registry/report_intelligence/recipe_paper_trading_summary.json` | 33 recipes passed paper-trading validation; 542 recipes have direct PIT binding; after-cost paper-trading summary is computed from passed pre-registered runs only; 1998 recipes remain blocked by direct binding, effective-N, or shadow-tool readiness gaps |
| `registry/report_intelligence/confidence_impact_monitor.json` and `registry/report_intelligence/monitoring_report.json` | 33 paper-trading validated recipes are monitored across 2031 confidence-impact observations; unvalidated confidence impact count is 0; alpha-decay and calibration-drift observations remain shadow-only. The recipe paper-trading semantic contract now recomputes confidence observation IDs, unvalidated impact counts, decay/calibration/regime risk counts, aggregate calibration drift rules, confidence-alpha correlation, confidence bucket outcomes, and monitor action/id lists from `confidence_impact_observations.jsonl`, so the P12 monitor cannot drift from its underlying observations. The alpha-decay blocker now uses the latest/tail non-positive after-cost streak while retaining the historical max streak as a diagnostic, so recovered short-window misses do not block long-window evidence. `schemas/report_intelligence_alpha_decay_monitoring_rules` now also checks monitoring report corpus counts, tooling-loop counts, tool-gap priority counts, evidence-coverage counts, and source/viewpoint/method effective-N summaries against the underlying public registry artifacts. |
| `registry/report_intelligence/evolution_readiness_gate.json` | blocked; 7 blockers remain across schema/audit-history readiness and manual forecast gold-set quality metrics. The semantic contract now hard-checks P13 machine thresholds in the committed gate evidence, including outcome coverage, stock/industry/macro proxy counts, paper-trading counts and after-cost summary, monitor stability, audit refresh evidence, gap-distribution stability, and P9 coverage status. RI-EVOL-02 now passes with 33/20 validated recipes, RI-EVOL-03 now exposes recipe-level P12 actions without turning them into global blockers: 23 `freeze_recipe` and 19 `send_to_manual_review` actions are tracked under `recipe_level_monitor`, while unvalidated positive confidence impact and aggregate calibration drift remain zero. RI-EVOL-04 requires current schema/PIT/provenance/statistical evidence to match `current_schema_or_audit_gate_blocked` and trailing audit distinct/pass counts to match `audit_refresh_history_below_threshold`, RI-EVOL-05 remains blocked by human gold-set quality metrics, and RI-EVOL-07 now passes after the macro asset proxy candidate stratum was filled. `gap_distribution_history.jsonl` is also semantically checked so `total_gap_count`, `max_gap_name`, `max_gap_share`, `stable`, and `accepted` must match the committed gap counts; a single-gap share above 0.80 cannot be marked stable. |
| `registry/report_intelligence/prompt_mutation_candidates.jsonl` | 13 shadow-only mutation candidates exist across forecast extraction, confidence gating, paper-trading recipe validation, industry mapping, refresh stability, calibration, tool-gap prioritization, Markdown quality, gold-set quality repair, and analytical-footprint quality repair; all have `promotion_state=shadow_candidate_only`, `manual_review_required=true`, `production_prompt_change_allowed=false`, and `private_text_included=false`. The industry mapping candidate directly cites `industry_etf_proxy_pit_availability.labelability_action_summary`, so the current 38 unmapped sector-claim gaps and 1 PIT-unavailable mapping are visible to the prompt-evolution action queue instead of remaining only in the PIT-availability artifact; semantic validation recomputes its action summary, PIT gap counts, and `industry_etf_proxy_readiness.data_gap_counts` refs from the public P10 artifacts so mapping evidence cannot drift. The calibration candidate cites `confidence_impact_monitor.recipe_level_monitor` aggregate counts, so the current 23 `freeze_recipe` actions and 19 `send_to_manual_review` actions are visible to the P12 review queue without exposing recipe text or private inputs; semantic validation recomputes its drift-status counts, calibration-rule counts, confidence-alpha correlation status, and recipe-level action/risk summary from `confidence_impact_monitor.json` so calibration evidence cannot drift. Confidence gating, stock target mapping, horizon/direction repair, Markdown quality, regime/mechanism extraction, tool-gap prioritization, recipe paper-trading, and forecast gold-set review candidates are also semantically recomputed from `confidence_impact_observations.jsonl`, `outcome_labeling_readiness.json`, `markdown_coverage_summary.json`, `tool_gaps.jsonl`, `recipe_paper_trading_runs.jsonl`, `recipe_paper_trading_summary.json`, and `evolution_readiness_gate.json`, so blocked observation counts, mapping/target/regime/mechanism gaps, retry/quality gaps, tool-priority counts, paper-trading blockers, recipe binding diagnostics, and gold gate evidence cannot go stale. The refresh-stability candidate cites the current RI-EVOL-04 evidence with the latest `data_vintage_hash`, 23 schema failures, and self-schema refs excluded; semantic validation recomputes its RI-EVOL-03/04/06 evidence refs from `evolution_readiness_gate.json` so stale audit-history evidence cannot remain in the prompt-evolution queue. The gold quality repair candidate cites RI-EVOL-05 aggregate metrics for `direction_accuracy`, `variable_mapping_accuracy`, and `unsupported_field_false_grounding_rate`, plus the 13-document coverage gap, so gold-set failures drive a specific prompt-repair queue rather than only a manual-review queue. The analytical-footprint quality repair candidate cites `analytical_footprint_review_summary.precision_recall_report`, including the `metric_mapping_accuracy` failure, 1017 pending footprint review rows, and aggregate error counts, so footprint mapping defects feed a specific prompt-repair queue without exposing source text. The semantic contract also requires the full offline validation matrix (`gold_set_review_pass`, PIT replay, schema, provenance, statistical robustness, and shadow paper-trading), rejects private or non-repo evidence paths in `evidence_refs`, requires every referenced public evidence artifact to exist, and recomputes all governed aggregate evidence refs above so candidate evidence cannot drift from public artifacts. |
| `registry/review_batches/manual_review_progress_report.json` and `registry/gold_sets/tushare_research_reports.review_summary.json` | public baseline: gold-set review summary is 158 reviewed but quality-blocked claims, while the local expanded gold review target is now 205 rows with 158 complete and 47 pending; analytical-footprint review is 34/1051 reviewed with 1017 pending, source license 17529/17529 already applied, and lockbox is 0/1. Semantic validation now passes as `schemas/report_intelligence_manual_review_progress_rules`, which checks input paths, ready/simulation consistency, blocker consistency, repo-local temp command prefixes, dry-run mode, and source-text-free `current_batch_status` counts. It accepts both the current blocked state and a future completed state where all gates have zero pending rows and no blockers. The public gold-set review summary is also checked as `schemas/report_intelligence_gold_review_gate_rules`: the current reviewed state is complete at row level but blocked by below-threshold human review metrics; false pass states, count drift, missing metrics, and below-threshold metrics are rejected. Synthetic pytest fixtures can mark manual rows complete for contract tests, but current target hashes in the real scratch still require human review. The action queue distinguishes already-applied gates from runnable apply work: source-license now reports `action_state=already_applied`, `can_run_now=false`, and an empty command set. The report includes aggregate `current_batch_status` for the active local 26-row gold-set expansion scratch, 50-row analytical-footprint scratch, and lockbox scratch files, plus a public-safe footprint `batch_plan`: 21 pending analytical-footprint batches at 50 rows per batch except the final 17-row batch. Each footprint batch explicitly records `apply_effect=merge_batch_into_target_review_template`, the transient `batch_input_path` for the 50-row import, the `target_review_template_path` it merges into, and the separate `promotion_input_path` used only after full human review; schema validation also rejects batch commands that use promotion inputs and promotion commands that use transient batch inputs. Current gold batch status is 26 rows, 0 complete, 26 pending, 0 malformed, with evidence and target hashes aligned; `review-progress --actions-only --review-kind gold_set` now reports `needs_human_review_fields`, 1 batch total, 47 target rows pending, `current_batch_target_covered_rows=26`, `remaining_rows_after_current_batch=21`, and `current_batch_covers_next_batch=false`. Gold remains blocked until the current expanded batch is manually filled and then the stale full reviewed import is regenerated, so the immediate action is filling `registry/review_batches/gold_set_reviewed.jsonl`, regenerating evidence/assist as needed, and dry-running `apply-gold-review`. Candidate expansion now runs `gold-candidate-claims --refresh-candidates-from-source --ensure-candidate-review-rows` to rebuild the local candidate list and append missing candidate starter rows without overwriting existing manual review fields. The gold candidate builder now strips trailing rating boilerplate from otherwise valid mechanism claims and continues to exclude disclaimer, risk-warning, rating-definition, and short rating-only text before writing reviewable candidate fields; current review aids and import scaffolds contain no candidate claim text matching those excluded classes. The current private source refresh selected 75 candidates, produced 152 current candidate diagnostics, and expanded the local review template to 205 rows / at least 50 documents, preserving the coverage target before human decisions. The stale analytical-footprint scratch was backed up under `.mosaic/tmp/review-backups/`, and the current analytical-footprint batch status is 50 rows, 0 complete, 50 pending, 0 malformed, with evidence and target hashes aligned. The next action is filling the current footprint batch fields, not re-preparing or applying. The target review summary still has 1017 pending rows. Current lockbox decision status is 1 row, 0 complete, 1 pending, 0 malformed; missing required fields are aggregate counts only. Full gold-set and footprint review imports still require quality-gate and human-review completion before promotion dry-run. |
| `registry/handoffs/rke_operator_handoff.json` | operator handoff semantic validation now passes as `schemas/report_intelligence_operator_handoff_rules`: command sequence order, repo-local temp prefixes, reviewed input paths, promotion dry-run inputs, and production-disabled state are checked directly against the handoff artifact |
| `registry/handoffs/rke_operator_readiness_report.json` | operator readiness currently passes 18/18 checks: required registry valid, handoff command sequence complete, manual review runbook promotion dry-run source-license policy consistent, manual import templates sparse and provenance-tagged, batch inputs separated from promotion inputs, blank gold/lockbox/source-license templates rejected, lockbox upstream CLI guard matches manual gate readiness, blank bundle dry-run does not promote, manual review bundle manifest current, and promotion gate state matches PG01-PG10 criteria. In `--no-write` mode, template/provenance/blank-import checks now use manual-batch support artifacts regenerated inside the temporary dry-run registry, while source-license progress, review progress, promotion state, and stale runbook detection remain anchored to the original registry. |
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
| P5 evolution loop | Partially implemented | mutation candidates, tool-gap prioritization, paper-trading and monitor inputs exist; gold-set, analytical-footprint quality, and refresh-stability failures now generate dedicated prompt-repair candidates with evidence refs that are semantically checked against public gate artifacts; promotion remains blocked by manual review gates |
| P6 decisions | Implemented for default path | default benchmark `SH510300` from `cn_etf`; stock cost 20 bps; stock windows 5/20/60/120; no company-name fuzzy mapping |
| P7 implementation breakdown | Implemented | qlib helpers, readiness builder, label builder, derived refresh integration, audits, schemas, tests, proxy outcome ID namespace contracts, and profile layer contracts that prevent cross-label-type/benchmark/cost aggregation from replacing stratified evidence |
| P8 acceptance matrix | Automated acceptance passes except manual review / coverage gates | ruff, report-intelligence tests, schema-artifact tests, prompt leak guard, diff check pass; `schema-status` intentionally exits 2 until analytical footprint review, gold-set quality/corpus review, and patch v1.5 Phase B/D coverage gates pass; `prepare-footprint-review` now creates a gitignored import scaffold for the footprint gate |
| P9 PDF/Markdown coverage expansion | Implemented for current sample pool | public coverage summary exists, includes `macro_asset_proxy_candidate` coverage, and passes privacy rules; private PDF/Markdown/cache paths remain gitignored; stratified source selection now consumes source-row `horizon_bucket` / horizon-day hints and `evaluability_bucket` hints when present, matching the P9 required sampling dimensions while retaining safe fallbacks for raw Tushare rows |
| P10 industry ETF mapping/PIT availability | Implemented with action watchlist | 64-row mapping registry, PIT availability artifact, mapping contract tests; `工业金属 -> SH560860` pinned; semantic validation now rejects drift between PIT availability `labelability_summary`, `labelability_action_summary`, PIT mapping counts, `outcome_labeling_readiness`, and the industry-mapping prompt mutation candidate evidence |
| P11 recipe paper-trading | Implemented; current aggregate threshold cleared | pre-registration hash, deterministic unique experiment/run IDs, OOS chronological split, required data contracts, cost/benchmark protocol, 2031 paper-trading runs, 33 validated recipes against the 20-recipe threshold |
| P12 confidence impact monitor | Implemented; current validated-recipe count is above the evolution threshold | monitor rows gate confidence impact on paper-trading validation; 33 validated recipes are monitored across 2031 observations; observation IDs and monitor-derived risk/action fields are semantically recomputed from the observation rows; alpha decay and calibration drift actions are tracked as shadow-only; RI-EVOL-03 now exposes recipe-level freeze/manual-review action counts while keeping production impact disabled; the calibration mutation candidate consumes the same recipe-level aggregate action counts so monitor actions feed the prompt-evolution queue, and its evidence is semantically recomputed from the P12 monitor artifact; monitoring report aggregate counts are semantically checked against public registry artifacts |

## Validation Commands

Last broad local validation set:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-artifacts
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_report_intelligence.py -q --basetemp .mosaic/tmp/pytest-rke-ri-current
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_*.py -q --basetemp .mosaic/tmp/pytest-rke-all-current
uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py mosaic/rke/schema_validation.py tests/conftest.py tests/test_rke_report_intelligence.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python scripts/check_prompt_leaks.py
git diff --check
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke review-progress --root .
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke operator-readiness --root . --no-write
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke master-plan-status --root . --no-write
```

The repository pytest default is also configured to keep its `--basetemp` under
`.mosaic/tmp/pytest-mosaic-rke`; this prevents ordinary test runs from placing
large registry copies in system `/tmp` or under tracked repository paths.
Pytest's synthetic private Tushare fixture is now overlaid only onto temporary
registry copies created under pytest basetemp; it no longer rewrites ignored
working-tree registry files such as gold review summaries during the test
session. A concurrent
`schema-status --root . --failures-only --no-write` run now stays on the real
local registry state and continues to report the current 23 manual-review
failures while CLI tests are running.
`operator-readiness --no-write` also builds its temporary dry-run registry under
`.mosaic/tmp` and now skips local-only Tushare source blobs and
report Markdown/PDF/cache directories when copying the dry-run root. It
regenerates the manual review batch support artifacts inside that temporary
root for template/provenance/blank-import safety checks, but keeps real
source-license progress, review progress, promotion state, and stale runbook
detection tied to the original registry. It does not depend on copying private
source JSONL/manifest files.

Most recent focused validation after the proxy entry-lag hardening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_report_intelligence.py::test_report_intelligence_entry_calendar_index_uses_explicit_lag tests/test_rke_report_intelligence.py::test_report_intelligence_labels_industry_claims_with_etf_proxy_windows tests/test_rke_report_intelligence.py::test_report_intelligence_labels_stock_claims_with_qlib_price_windows tests/test_rke_report_intelligence.py::test_report_intelligence_pit_audit_rejects_t0_stock_entry -q --basetemp .mosaic/tmp/pytest-entry-lag-explicit
uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py tests/test_rke_report_intelligence.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python scripts/check_prompt_leaks.py
git diff --check
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root .
```

The helper that computes entry dates now requires an explicit
`entry_lag_trading_days` argument. Industry proxy builders pass
`INDUSTRY_ETF_ENTRY_LAG_TRADING_DAYS`; stock proxy builders pass
`STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS`. This keeps the T+1 entry invariant
auditable if either channel later changes its lag policy.

Most recent focused validation after read-only status and action-queue
hardening:

```bash
uv run python -m pytest tests/test_rke_cli.py::test_rke_cli_master_plan_status_writes_coverage tests/test_rke_cli.py::test_rke_cli_master_plan_status_no_write_preserves_artifacts -q --basetemp .mosaic/tmp/pytest-master-plan-no-write-cli-20260614
uv run python -m pytest tests/test_rke_review_progress.py -q --basetemp .mosaic/tmp/pytest-review-progress-full-20260614
uvx ruff@0.15.15 check mosaic/rke/cli.py mosaic/rke/review_progress.py tests/test_rke_cli.py tests/test_rke_review_progress.py
uv run python scripts/check_prompt_leaks.py
git diff --check
uv run mosaic-rke review-progress --root . --actions-only --no-write
uv run mosaic-rke operator-readiness --root . --no-write
uv run mosaic-rke master-plan-status --root . --no-write
uv run mosaic-rke promotion-status --root . --no-write
uv run mosaic-rke evolution-readiness --root . --no-write
uv run mosaic-rke schema-status --root . --failures-only --no-write
```

`review-progress --actions-only --no-write` now reports source-license as
`already_applied` with `can_run_now=false` and no commands; runnable action
items remain the active gold-set and analytical-footprint review batches.
The same action-queue output now includes top-level public-safe
`action_state_counts`, so operators can see the current mix of runnable,
already-applied, and dependency-waiting gates before scanning individual
actions.
The gold assist/evidence commands and the footprint evidence command now carry
the same public-safe aggregate quality-gap targets as the action queue, so
reviewers can see the current document, direction, variable-mapping,
unsupported-grounding, and footprint metric-mapping gaps while working active
scratch batches.
`review-progress --summary --no-write` and
`review-progress --actions-only --no-write` now include a compact public-safe
`batch_overview` per review gate, so operators can see total batch count,
current batch size/path, evidence alignment, final-batch size, and the
requirement to rerun `review-progress` after each accepted batch without
expanding the full batch plan. If a gate is already ready for promotion while
an older scratch batch file still contains blank fields, the action queue uses
the promotion input path and marks that scratch as stale instead of showing its
missing fields as current work. For current manual-batch work, the action queue
also separates `after_dry_run_accepts` from the immediate `commands`, so apply,
rerun, and schema-check commands are visible without inviting operators to skip
the dry-run step.
`master-plan-status --no-write` and `schema-status --failures-only --no-write`
still exit 2 only because the same manual review-derived schema and patch
coverage gates remain open. The schema-status failure payload now includes
public-safe `next_actions` for the analytical-footprint review summary gate and
patch v1.5 manual coverage gate, so operators can jump from the failed schema
records back to the review-progress/evidence/dry-run commands without editing
coverage artifacts directly. The gold-set and analytical-footprint
`schema-status` actions also include the current public-safe `batch_overview`
from `review-progress`, so the failure entry point shows the active scratch
path, batch coverage, evidence alignment, and remaining target rows without an
extra discovery command. The same schema-status actions now carry the
`after_dry_run_accepts` command block for the active manual batch, preserving the
same dry-run-first sequencing from the lower-level action queue. They also carry
the current `review-progress` action-state context (`next_manual_action`,
`action_state`, `can_run_now`, batch input paths, and post-batch action), and the
patch v1.5 coverage action nests the current gold-set and analytical-footprint
gate states under `review_gate_actions`, so schema failures cannot point
operators at stale or ambiguous manual work.
`master-plan-status --no-write` now also includes
public-safe `next_actions` that point to `schema-status --failures-only`,
`review-progress --actions-only`, and `evolution-readiness --no-write`, then
reuses the same schema/manual-review actions and field contracts. MVP-D3 now
checks only the source-grounded claim schema records and the claim
variable/grounding verifier reports, so unrelated report-intelligence manual
review schema failures no longer make the claim-schema/verifier deliverable look
blocked. Those manual gates remain visible in MVP-D2, Phase-1B, and final
acceptance. Master-plan coverage now distinguishes missing evidence from blocked
evidence: existing but non-passing gold/schema/patch gates report as `blocked`,
while absent or malformed artifacts remain `missing`. `promotion-status
--no-write` now also includes public-safe
`next_actions` for PG02 manual gold-set review and PG09 lockbox review, with
lockbox commands explicitly marked as dependent on upstream manual gates. Its
promotion dry-run action and the manual review runbook now follow the same
source-license input policy as operator handoff: when PG03 source-license review
already passes, they omit `--license-input` and do not rebuild
`source_license_policy_import.jsonl`; only an unpassed PG03 path includes the
license-import build step.
`evolution-readiness --no-write` also exits 2 when
`gate_status=blocked` and includes `blocked_check_ids` / `blocked_checks` in
stdout so operators can see that RI-EVOL-04 and RI-EVOL-05 are the active
readiness blockers. The same read-only output now includes public-safe
`next_actions` with temp-prefixed commands for the current gold-set review
batch, the current analytical-footprint review batch, the schema/audit blocker
inspection path, and the distinct `data_vintage_hash` refresh-history
requirement. These manual-review actions now merge the same live
`review-progress` action-state context as `schema-status`: `next_manual_action`,
`action_state`, `can_run_now`, `batch_overview`, `after_dry_run_accepts`, active
manual/promotion input paths, and nested `review_gate_actions` for the schema
and audit blocker action. This keeps RI-EVOL-04/05 operator work aligned with
the current scratch batches instead of stale static commands. RI-EVOL-04 audit
blocker summaries now exclude the
`schemas/report_intelligence_evolution_readiness_gate_rules` self-check from
the current schema failure count and refs, so the current no-write output
reports the 23 true external schema failures across footprint review, gold
review, and patch coverage instead of recursively listing the evolution gate's
own semantic rule. The evolution gate semantic contract also rejects future
artifacts whose top-level `current_failure_counts` / `current_failure_refs`
drift from `audit_history_dependency`, or whose schema failure refs reintroduce
the evolution-readiness self schema rule.

Most recent focused validation after proxy outcome ID namespace hardening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_cross_label_type_id_collisions -q --basetemp .mosaic/tmp/pytest-id-contract
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-id-contract
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py mosaic/rke/report_intelligence.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root .
```

Most recent focused validation after stock readiness gap semantics hardening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_schema_artifacts.py::test_stock_price_proxy_readiness_contract_rejects_pit_policy_drift tests/test_rke_schema_artifacts.py::test_stock_price_proxy_readiness_contract_accepts_blocking_gap_counts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_untradable_stock_label -q --basetemp .mosaic/tmp/pytest-stock-gap-semantics
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
```

Most recent focused validation after stratified source-selection hardening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py::test_report_intelligence_stratified_source_selection_covers_p9_buckets tests/test_rke_report_intelligence.py::test_report_intelligence_stratified_source_selection_uses_horizon_and_evaluability_hints tests/test_rke_report_intelligence.py::test_report_intelligence_stratified_source_selection_covers_outcome_ready_stock -q --basetemp .mosaic/tmp/pytest-stratified-horizon-eval
uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py tests/test_rke_report_intelligence.py
```

Most recent focused validation after analytical-footprint indicator alias
hardening and non-research claim filter tightening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py::test_report_intelligence_structures_string_indicator_mentions tests/test_rke_report_intelligence.py::test_report_intelligence_structures_common_report_indicator_aliases -q --basetemp .mosaic/tmp/pytest-rke-indicator-aliases
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_suggests_missing_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_risk_warning_footprints -q --basetemp .mosaic/tmp/pytest-rke-footprint-evidence-rules
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_suggests_missing_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_unknown_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_risk_warning_footprints -q --basetemp .mosaic/tmp/pytest-rke-footprint-evidence-unknown-mapping
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_unknown_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_suggests_missing_metric_mapping -q --basetemp .mosaic/tmp/pytest-rke-footprint-repair-suggestions
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_suggests_missing_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_unknown_metric_mapping -q --basetemp .mosaic/tmp/pytest-rke-footprint-candidate-summary
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_unknown_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_suggests_missing_metric_mapping -q --basetemp .mosaic/tmp/pytest-rke-footprint-unknowns-decision
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py -q --basetemp .mosaic/tmp/pytest-rke-report-intelligence-indicator-rules
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py -q --basetemp .mosaic/tmp/pytest-rke-report-intelligence-evidence-unknown-mapping
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py -q --basetemp .mosaic/tmp/pytest-rke-report-intelligence-repair-suggestions
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py -q --basetemp .mosaic/tmp/pytest-rke-report-intelligence-candidate-summary
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py -q --basetemp .mosaic/tmp/pytest-rke-report-intelligence-unknowns-decision
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_gold_candidate_claims.py -q --basetemp .mosaic/tmp/pytest-rke-gold-candidate-claim-filters
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_manual_review_batches.py -q --basetemp .mosaic/tmp/pytest-rke-manual-review-batches-filters
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_review_progress.py -q --basetemp .mosaic/tmp/pytest-rke-review-progress-current
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-artifacts-current
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_gold_candidate_claims.py::test_gold_candidate_claims_skip_boilerplate_risk_warning_report_claims tests/test_rke_gold_candidate_claims.py::test_gold_candidate_claims_skip_generic_risk_enumeration_report_claims tests/test_rke_gold_candidate_claims.py::test_gold_candidate_claims_skip_unprefixed_generic_risk_list_report_claims tests/test_rke_gold_candidate_claims.py::test_gold_candidate_claims_skip_boilerplate_risk_warning_markdown_sentences -q --basetemp .mosaic/tmp/pytest-rke-risk-filters
uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py mosaic/rke/claim_text_filters.py tests/test_rke_report_intelligence.py tests/test_rke_schema_artifacts.py tests/test_rke_gold_candidate_claims.py tests/test_rke_manual_review_batches.py tests/test_rke_review_progress.py
uv run python scripts/check_prompt_leaks.py
git check-ignore registry/report_intelligence/analytical_footprint_review_evidence.jsonl registry/report_intelligence/analytical_footprint_review_evidence.md registry/report_intelligence/analytical_footprint_review_batch.jsonl registry/review_batches/gold_set_reviewed.jsonl
git diff --check
```

Most recent focused validation after tightening the gold candidate queue and
stripping trailing rating boilerplate from otherwise valid mechanism claims:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_gold_candidate_claims.py -q --basetemp .mosaic/tmp/pytest-rke-gold-candidate-rating-clean
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_manual_review_batches.py -q --basetemp .mosaic/tmp/pytest-rke-manual-batches-rating-clean
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_operator_handoff.py tests/test_rke_operator_readiness.py -q --basetemp .mosaic/tmp/pytest-rke-operator-rating-clean
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_review_progress.py -q --basetemp .mosaic/tmp/pytest-rke-review-progress-rating-clean
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_schema_artifacts.py::test_manual_review_bundle_manifest_contract_accepts_current_public_artifact tests/test_rke_schema_artifacts.py::test_manual_review_progress_contract_accepts_current_public_artifact -q --basetemp .mosaic/tmp/pytest-rke-schema-manual-rating-clean
uvx ruff@0.15.15 check mosaic/rke/claim_text_filters.py mosaic/rke/gold_candidate_claims.py tests/test_rke_gold_candidate_claims.py tests/test_rke_manual_review_batches.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python scripts/check_prompt_leaks.py
git diff --check
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke operator-readiness --root .
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root . --failures-only --no-write
```

`schema-status` still exits 2 with the expected 23 remaining failures from the
manual gold-set quality gate, analytical-footprint review gate, and patch v1.5
coverage gate. The manual-review bundle manifest drift check is clean after
regenerating operator readiness artifacts.

Most recent focused validation after report-level forecast-claim cap hardening:

```bash
uv run pytest tests/test_rke_report_intelligence.py::test_user_prompt_requires_context_synthesized_forecast_claims tests/test_rke_report_intelligence.py::test_select_report_forecast_claims_caps_and_preserves_source_order tests/test_rke_report_intelligence.py::test_report_intelligence_caps_forecast_claims_per_report tests/test_rke_report_intelligence.py::test_refresh_forecast_mapping_governance_caps_existing_rows_per_report -q --basetemp .mosaic/tmp/pytest-rke-forecast-cap4
uv run pytest tests/test_rke_report_intelligence.py -q --basetemp .mosaic/tmp/pytest-rke-ri-forecast-cap-full2
uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py tests/test_rke_report_intelligence.py
```

Most recent focused validation after P10 labelability action-summary hardening:

```bash
UV_CACHE_DIR=.mosaic/tmp/uv-cache uv run python -m pytest tests/test_rke_schema_artifacts.py::test_industry_etf_mapping_contract_accepts_current_public_artifacts tests/test_rke_schema_artifacts.py::test_industry_etf_mapping_contract_rejects_action_summary_drift tests/test_rke_schema_artifacts.py::test_industry_etf_pit_availability_schema_requires_plan_fields -q --basetemp .mosaic/tmp/pytest-p10-schema
UV_CACHE_DIR=.mosaic/tmp/uv-cache uv run python -m pytest tests/test_rke_report_intelligence.py::test_report_intelligence_labels_industry_claims_with_etf_proxy_windows tests/test_rke_report_intelligence.py::test_report_intelligence_industry_pit_availability_records_missing_benchmark tests/test_rke_report_intelligence.py::test_report_intelligence_industry_readiness_records_missing_proxy_series tests/test_rke_report_intelligence.py::test_report_intelligence_industry_mapping_effective_from_blocks_early_claim -q --basetemp .mosaic/tmp/pytest-p10-ri
UV_CACHE_DIR=.mosaic/tmp/uv-cache uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py tests/test_rke_report_intelligence.py
```

The industry ETF PIT availability artifact now has a public-safe
`labelability_action_summary`. It keeps P10 mapping/PIT coverage gaps visible
without exposing private source rows: current aggregate actions are 38 unmapped
sector-claim gaps and 1 PIT-unavailable mapping, while existing labels remain
limited to primary, PIT-available mapping rows. The prompt mutation candidate
for `industry_proxy_mapping_rule` now consumes the same action summary and adds
its next actions to `blocked_by`, keeping the P10 remediation queue connected to
the P5 evolution loop.

The current local expanded gold-set scratch has 26 rows, 0 complete rows, and
26 pending rows; its evidence and target hashes are aligned. The expanded target
review template now has 206 rows, with 158 complete and 48 still pending. The
stale full reviewed import must be regenerated after the expanded batch is
manually filled. The action queue now reports both planned-batch and
current-scratch coverage: the active 26-row scratch covers 26 of the 48 pending
target rows, so `remaining_rows_after_current_batch=22`,
`current_batch_covers_next_batch=false`, and
`post_current_batch_action=apply_current_batch_then_rerun_review_progress`.
The current review-progress, evolution-readiness, and promotion-status evidence
commands are scoped to the active 26-row scratch, not the full 48-row pending
target, so regenerating review evidence does not expand the private evidence
draft beyond the import rows being filled.
The current local analytical-footprint scratch has 50 rows, 0 complete rows,
and 50 pending rows; its evidence and target hashes are aligned. New
analytical-footprint batches should be prepared with `--priority`, which sorts
pending rows by the same high-risk/high-value heuristic used by the private
evidence draft before applying `--offset` and `--limit`. The committed
gold-set review summary still fails the quality gate:
`direction_accuracy=0.626582`, `variable_mapping_accuracy=0.189873`, and
`unsupported_field_false_grounding_rate=0.227848`. This means the next gold-set
work item is completing the expanded manual batch, then rerunning the gold
quality gate before deciding whether further extraction/mapping repair is still
needed. The footprint target summary is now `34/1051` complete with
1017 rows pending.

The gold candidate queue now keeps full diagnostics but narrows the default
review queue. Candidate rows with missing canonical variable mapping, ambiguous
or conflicting direction, or non-testable direction values are no longer exported
by default. `sentence_fallback_requires_context_synthesis` no longer blocks
queue entry by itself; it remains a review tag so humans can judge whether the
larger report context supports the candidate.
Gold-set source sampling now also prefers primary-domain matches when filling
each domain quota; secondary matches are only used as fallback. A read-only
diagnostic on the current private source pool still selected 75 candidates with
15 rows in each governed bucket, while reducing assigned-domain/primary-domain
mismatches to 0.
Report-claim rows with `forecast_mapping_insufficient` or `forecast_not_testable`
remain reviewable because they are useful for measuring mapping failure modes.
Direction reconciliation now refuses to let weak local keyword rules override a
conflicting LLM direction: explicit conflicts become `ambiguous` with
`direction_conflict_requires_review`. Fallback and report-derived candidates also
stop populating `unsupported_fields` unless a future extractor provides an
explicit source-grounded unsupported field. On the current local refresh, the
candidate source selection is oversampled to 75 documents before reviewability
filtering, producing 160 candidate diagnostics and expanding the local review
template to 206 rows / 63 documents before human decisions.

Forecast extraction now also has a report-level cap: each Markdown chunk prompt
asks for at most two high-value `forecast_claims`, and the deterministic
post-processor keeps at most five claims per report. The selector ranks already
normalized records by source grounding, testability, supported direction,
target/horizon availability, metric proxy mapping, economic mechanism, evaluable
impact, regime context, and source conviction, then preserves source order among
the selected records. Derived refresh applies the same cap to existing private
`forecast_claims.jsonl` rows grouped by `report_id`, so old local extraction
outputs can converge without another LLM pass. This prevents one report from
flooding the gold-set queue with repetitive low-value claims while keeping
detailed context available through analytical-footprint and metric artifacts.

The analytical-footprint indicator normalizer now covers common report aliases
for sector/index returns, valuation multiples, revenue/profitability/cash-flow
metrics, policy parameters, clinical endpoints, safety/tolerability, pipeline
milestones, AI infrastructure, and telecom spectrum/deployment milestones. This
does not auto-accept any manual review row; it only prevents future extraction
passes from defaulting reviewable indicators to `unknown` when a governed alias
rule exists. The analytical-footprint review evidence helper now also treats a
non-empty indicator list as incomplete when any mention still lacks a
non-`unknown` canonical metric or a source-grounded flag; it adds public-safe
diagnostic tags instead of suggesting `metric_mapping_correct=true` merely
because the list is non-empty. For incomplete indicator mentions, the same
review evidence helper emits source-unverified alias repair candidates so the
reviewer can see the likely canonical mapping without treating it as already
validated. The current 50-row footprint review evidence refresh completed with
50 rows, 0 missing Markdown rows, and no blockers. The private evidence
Markdown now includes batch-level suggested indicator candidate source and
canonical-metric counts, so reviewers can distinguish missing indicators from
unknown/ungrounded extracted indicators without reading every row first. When
an extracted indicator is `unknown` but an alias repair candidate exists,
`unknowns_used_when_uncertain` is now suggested as false instead of defaulting
to true; the current 50-row evidence refresh marks 16 rows false and 34 rows
true for that field. The shared non-research filter still removes boilerplate
risk warnings, disclaimers, rating-definition tables, and generic risk lists,
while preserving longer regime/mechanism claims that mention risk or competition
as context and then state a forward economic impact.

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after RI-EVOL-04 audit blocker hardening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py::test_evolution_readiness_gate_contract_accepts_current_public_artifact tests/test_rke_schema_artifacts.py::test_evolution_readiness_gate_contract_rejects_missing_current_audit_blocker tests/test_rke_schema_artifacts.py::test_evolution_readiness_gate_contract_rejects_stale_audit_history_blocker -q --basetemp .mosaic/tmp/pytest-evolution-audit-contract
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-evolution-audit
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root .
```

Most recent focused validation after excluding evolution-readiness self-schema
refs from RI-EVOL-04 current audit summaries:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_report_intelligence.py::test_report_intelligence_evolution_gate_explains_schema_blocked_audit_history tests/test_rke_report_intelligence.py::test_report_intelligence_evolution_gate_ignores_self_schema_rule_for_current_audit tests/test_rke_report_intelligence.py::test_report_intelligence_evolution_gate_filters_self_schema_from_failure_refs -q --basetemp .mosaic/tmp/pytest-evolution-self-schema
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run pytest tests/test_rke_schema_artifacts.py::test_evolution_readiness_gate_contract_tracks_current_public_artifact tests/test_rke_schema_artifacts.py::test_evolution_readiness_gate_contract_rejects_self_schema_audit_ref tests/test_rke_schema_artifacts.py::test_evolution_readiness_gate_contract_rejects_audit_ref_summary_drift tests/test_rke_schema_artifacts.py::test_evolution_readiness_gate_contract_rejects_stale_audit_failure_summary -q --basetemp .mosaic/tmp/pytest-evolution-contract-self-ref
uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py tests/test_rke_report_intelligence.py
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke evolution-readiness --root . --no-write
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root . --failures-only --no-write
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the evolution readiness gate semantic
record is accepted.

Most recent focused validation after proxy outcome window-policy hardening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_bad_window_policy_fields -q --basetemp .mosaic/tmp/pytest-window-policy-contract
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-window-policy
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after proxy outcome effective-N hardening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_bad_effective_n_weights tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_window_set_weight_sum_above_one -q --basetemp .mosaic/tmp/pytest-effective-n-contract
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-effective-n
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after proxy outcome forecast-traceability hardening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_trace_proxy_labels_to_forecast_claims tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_untraceable_stock_proxy_claim -q --basetemp .mosaic/tmp/pytest-forecast-trace-contract
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-forecast-trace
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after stock target-resolution hardening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_metadata_and_llm_stock_resolution tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_bad_stock_target_resolution -q --basetemp .mosaic/tmp/pytest-target-resolution-contract
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-target-resolution
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after proxy benchmark/cost hardening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_bad_benchmark_and_cost_policy -q --basetemp .mosaic/tmp/pytest-benchmark-cost-contract
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-benchmark-cost
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after proxy PIT timing hardening:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_bad_entry_exit_timing tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_same_day_signal_entry -q --basetemp .mosaic/tmp/pytest-pit-timing-contract
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp .mosaic/tmp/pytest-rke-schema-pit-timing
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after stock long-window evidence hardening:

```bash
uv run pytest tests/test_rke_report_intelligence.py::test_report_intelligence_keeps_long_window_stock_hits -q --basetemp .mosaic/tmp/pytest-rke-stock-long-window
uv run pytest tests/test_rke_report_intelligence.py::test_report_intelligence_labels_stock_claims_with_qlib_price_windows tests/test_rke_report_intelligence.py::test_report_intelligence_counts_stock_price_proxy_as_labelable_channel tests/test_rke_report_intelligence.py::test_report_intelligence_keeps_long_window_stock_hits -q --basetemp .mosaic/tmp/pytest-rke-stock-proxy-focused
uvx ruff@0.15.15 check tests/test_rke_report_intelligence.py
```

The stock long-window test now directly covers the P7.9 requirement that a
stock report can miss in the short window and still retain the later long-window
hit as governed evidence. The generated stock proxy rows keep `label_type`,
`horizon_days`, `window_role`, `directional_hit`, `temporal_validation_summary`,
and `window_evidence_policy=do_not_collapse_multi_window_outcome_to_single_label`
instead of collapsing the claim to one outcome.

Current manual review evidence and scaffold commands:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke prepare-gold-review --root . --gold-batch-size 50 --offset 0 --force --reviewer hap --review-date 2026-06-12
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke write-gold-review-assist --root . --review-input registry/review_batches/gold_set_reviewed.jsonl
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke write-gold-review-evidence --root . --limit 50 --offset 0 --review-input registry/review_batches/gold_set_reviewed.jsonl
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl --dry-run
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke prepare-gold-review --root . --full --force --reviewer hap --review-date 2026-06-12
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke prepare-footprint-review --root . --limit 50 --offset 0 --priority --reviewer hap --review-date 2026-06-12 --overwrite
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke prepare-footprint-review --root . --output registry/report_intelligence/analytical_footprint_reviewed.jsonl --reviewer hap --review-date 2026-06-12 --overwrite
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke write-footprint-review-assist --root . --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl
```

These commands write private, gitignored manual handoff files. The current local
expanded gold-set scratch batch has 26 rows, 0 complete rows, and 26 pending
rows; its private evidence draft is aligned with the same 26 scratch rows. The
gold action queue now includes a public-safe `backfill_status` for the active
scratch batch and hides `backfill_write` when the dry-run finds no writable
backfill. The current active batch matches 26 prior rows, but all 26 prior rows
still lack required manual fields, so backfill remains diagnostic-only and the
review fields must be filled manually. `review-progress --summary` and
`--actions-only` now both emit the current-scratch evidence command with
`--limit 26`, rather than the planned 47-row follow-up batch size. The promotion gold-set import remains not ready because the expanded current batch still
requires manual decisions before the full reviewed import can be
regenerated; after applying that current scratch, 21 target rows will still need
a refreshed batch, so the action queue explicitly tells the operator to rerun
`review-progress` after applying the current batch. The previous stale
analytical-footprint scratch was backed up under `.mosaic/tmp/review-backups/`
before overwrite. The current active analytical-footprint batch has 50 rows,
0 complete rows, 50 pending rows, and no target-row-hash mismatches against the
current footprint review template. `review-progress --actions-only
--review-kind footprint_review` therefore reports
`current_batch_target_aligned=true`, `current_batch_evidence_aligned=true`, and
the next action is filling the current batch fields before dry-run. When the
current batch is accepted and applied, rerun `prepare-footprint-review` with
`--priority --offset 0` so the next batch is selected from the remaining
priority-sorted pending rows. The target footprint review summary still has
1017 pending rows. The
assist command writes
private, gitignored helper files at
`registry/report_intelligence/analytical_footprint_review_assist.jsonl` and
`registry/report_intelligence/analytical_footprint_review_workbook.md`; the current private footprint review assist/workbook snapshot follows the active 50-row scratch batch via `--review-input`, rather than selecting a different full pending set. These files are not import files and do not satisfy the review gate by themselves. The evidence command writes private, gitignored local-markdown snippets and draft review suggestions at
`registry/report_intelligence/analytical_footprint_review_evidence.jsonl` and
`registry/report_intelligence/analytical_footprint_review_evidence.md`; the
private evidence draft is aligned with the current 50-row scratch batch. It
now emits structured `suggested_review_rationales` for span support, metric
mapping, inferred step tagging, uncertainty handling, and leakage checks, plus
review-only inferred indicator candidates for missing metric mappings. The
private Markdown now also renders a top-level Quick Fill Checklist with compact
machine-suggested boolean values and tags for the active 50-row scratch batch,
while still requiring human confirmation before copying anything into the
reviewed JSONL import. These also are not import files. Gold-set and analytical-footprint evidence commands
now support `--review-input`, so the private evidence draft can follow the exact
scratch batch order instead of priority sorting a different set of pending rows.
`review-progress --summary --no-write` and
`review-progress --actions-only --no-write` now include `review_aids` path maps
for each manual gate, so operators can see the current private evidence
Markdown/JSONL, assist workbook, fill import, and promotion import paths without
opening the full runbook. These are path-only pointers and remain non-import
review aids unless explicitly listed as `fill_import_path` or
`promotion_import_path`.
The higher-level `schema-status --failures-only --no-write`,
`evolution-readiness --no-write`, and `promotion-status --no-write`
`next_actions` also include the same `review_aids` and `field_contract` maps,
so an operator can move from a blocked gate to the exact private aid/import
paths and manual field rules without running an additional discovery command.
Lockbox actions also expose their reviewed JSON path as a path-only aid, but
the lockbox policy remains `wait_for_prior_manual_gates_before_opening` until
gold-set, analytical-footprint, and source-license gates are ready.
The same `field_contract` maps are also rendered into
`registry/review_batches/manual_review_runbook.md`, listing required fields,
optional fields, boolean fields with `true`/`false` values, date format
requirements, and fields that must be preserved. This makes the gold-set
`review_notes` optional but analytical-footprint `review_notes` required
distinction explicit in JSON action output and the Markdown runbook.
`registry/handoffs/rke_operator_handoff.json` and `.md` now expose the same
public-safe `review_aids` and `field_contract` maps per manual gate, so the
operator handoff entry point carries the same path and field rules as
`review-progress`, `schema-status`, `evolution-readiness`, and
`promotion-status`.
`tests/test_rke_review_progress.py` now asserts that these public-safe contracts
stay aligned with the gold-set, footprint, source-license, and lockbox import
validator constants. It also asserts that the public-safe `review_aids` path
maps stay aligned with the source import, evidence, assist, workbook, and
lockbox artifact constants, so operator-facing action output cannot silently
drift to stale manual-review paths.
`tests/test_rke_operator_handoff.py` asserts the same maps appear in the
operator handoff dataclasses, JSON output, and Markdown output.

`MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root .`
currently exits with code 2 by design. The refreshed failure-only run reports 23
semantic failures across three records:
`schemas/report_intelligence_analytical_footprint_review_rules`,
`schemas/report_intelligence_gold_review_gate_rules`, and
`schemas/report_intelligence_patch_v1_5_coverage_rules`. These failures are
downstream of the analytical-footprint review gate, gold-set quality/corpus
gate, and patch v1.5 Phase B/D coverage gates. Gold-set row-level review is
complete after the current 17-row quality re-review scratch was backfilled from
matching prior human-reviewed rows, but broader gold quality/corpus work remains
part of the schema and patch Phase B promotion path. The evolution readiness
semantic record now passes, including the paper-trading validated recipe
threshold. All ordinary schema records, proxy outcome
contracts, mapping/PIT availability contracts, recipe paper-trading contracts,
runtime guards, PIT/provenance/statistical/tooling audits, refresh-history
contracts, operator handoff rules, promotion dry-run rules, and
production-promotion gate semantic rules pass in the current public artifact set.
Profile outcome-layer semantic rules now also pass for 3246 source, viewpoint,
and method performance profiles, ensuring mixed stock/industry proxy evidence
stays stratified by `label_type`, `benchmark_family`, and `cost_model_id`.
The stock readiness contract now also rejects drift in
`ordinary_stock_code_policy`, so ordinary stock labels remain limited to
`SH60/SH68`, `SZ00/SZ30`, and `BJ92` code families; fund, ETF, LOF, index, and
legacy BJ 8-prefix codes stay out of the stock proxy outcome channel.

## Remaining Gates

The objective is not complete until the evolution readiness gate passes. Current
blocker families include:

1. Manual/operator gates: analytical-footprint review, expanded gold-set review,
   and lockbox review remain pending. The public gold-set baseline still has
   158 reviewed but quality-blocked claims, while the expanded local gold target
   is 206 rows with 48 pending rows; the current gold scratch covers 26 of those
   pending rows. `schema-status` still reports analytical-footprint review,
   gold-set quality, and patch coverage semantic blockers. Source-license review
   is applied in the manual progress report. The gold-set quality/corpus gap
   must be addressed through improved extraction/mapping rules and a refreshed
   gold corpus with at least 50 reviewed documents. The footprint review has 34
   accepted rows and 1017 rows still pending. `review-progress`,
   `schema-status`, `evolution-readiness`, and `master-plan-status` next-action
   payloads now all surface the same source-safe current-batch evidence quality
   aggregates: gold has 0 missing-Markdown rows and 26 snippet-ready rows, while
   footprint has 0 missing-Markdown rows and 50 snippet-ready rows. The
   `prepare-footprint-review --priority` report now also emits
   `selected_priority_reason_counts` and `selected_priority_score_counts`, so a
   reviewer can see whether the current batch is dominated by missing indicator
   mappings, complex multi-step patterns, missing target-agent/entity candidates,
   or many source spans before opening the private evidence workbook.
   `review-progress`, `schema-status`, `evolution-readiness`, and
   `master-plan-status` now also surface current-batch evidence priority score
   counts, priority reason counts, and a `priority_metadata_refresh_recommended`
   flag when older private evidence files have scores but lack reason metadata;
   the corresponding action hint points reviewers to regenerate evidence before
   filling the scratch. The same batch overview now exposes aggregate
   `suggested_review_decision_counts` by field and true/false/null bucket, so
   reviewers can see which required manual fields have machine draft decisions
   and which remain unresolved without opening source text. Prepare each
   footprint batch with
   `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke prepare-footprint-review --root . --limit 50 --offset 0 --priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite`,
   validate it with
   `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`,
   then apply through the same import path.
2. P9 coverage watchlist: current public gate reports `coverage_gate_status=passed`.
   The `macro_asset_proxy_candidate` stratum is now filled by 4 candidates from
   the cached-VLM-Markdown Mimo macro batch, and the count thresholds for
   selected reports, Markdown-ready samples, quality-passed Markdown,
   LLM-processed reports, stock reports, industry reports, sector buckets, and
   120-day stock outcome readiness are met.
3. Outcome evidence: current gate thresholds are cleared: 151 unique PIT outcome
   claims, 39 industry proxy claims, 115 stock proxy claims, and 1 macro asset
   proxy claim.
4. Paper-trading evidence: current gate thresholds are cleared: 2031
   pre-registered runs remain, 33 recipes are validated against the 20-recipe
   threshold, and the after-cost summary is computed from passed
   pre-registered runs only. Remaining recipe rows stay blocked or shadow-only
   when direct PIT binding, effective N, or shadow-tool readiness is
   insufficient.
5. Confidence impact monitor: current confidence-impact leakage gate is still
   clean with no unvalidated confidence impact, with 33 monitored validated
   recipes across 2031 observations after the forecast cap. Alpha decay and
   calibration drift observations are tracked but remain shadow-only.
6. Refresh-history stability: audit history must satisfy the trailing-vintage
   gate; monitor and gap-distribution trailing-vintage gates currently pass. The
   current audit trailing blocker is downstream of `schema_accepted=false`, and
   `evolution_readiness_gate.json` now records `audit_history_dependency` so
   operators can see that distinct refreshes only count after the current
   schema/PIT/provenance/statistical gates pass.
   `evolution-readiness --no-write` now also returns
   `active_requirement_shortfalls`, which filters the committed
   `requirement_shortfalls` down to the blockers that are live in the current
   gate, including nested Markdown/P9 coverage shortfalls. Use this field as the
   numeric work queue before running the matching `next_actions`.
7. Re-run
   `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke review-progress --root . --summary --no-write`,
   `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke review-progress --root . --actions-only --no-write`,
   `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke operator-readiness --root . --no-write`,
   `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke master-plan-status --root . --no-write`,
   `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke evolution-readiness --root . --refresh-prompt-mutations`,
   promotion dry-run, and
   `MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp uv run mosaic-rke schema-status --root . --failures-only --no-write`.
   For focused manual work, add `--review-kind gold_set`, `--review-kind footprint_review`, `--review-kind source_license`, or `--review-kind lockbox` to the summary or action-queue command; add `--action-state needs_human_review_fields`, `--action-state ready_to_apply`, `--action-state already_applied`, or `--action-state waiting_on_dependencies` to `--actions-only` when operators need one work class. The lockbox summary, runbook, operator handoff, and lockbox prepare/apply CLI paths are dependency-aware and should remain on `wait_for_prior_manual_gates` / `waiting_on ...` until the upstream manual review gates pass.
   The composite actions emitted by `schema-status`, `evolution-readiness`, and
   `master-plan-status` also include `review_gate_actions[*].batch_overview`, so
   operators can inspect current batch coverage and evidence quality without
   switching back to the raw `review-progress` action queue.

Until those gates pass, evolution outputs remain shadow candidates and must not
modify production prompts or production trading decisions.
