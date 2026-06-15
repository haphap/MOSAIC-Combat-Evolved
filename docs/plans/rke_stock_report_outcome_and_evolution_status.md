# RKE Stock Report Outcome and Evolution Status

Status date: 2026-06-14

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

Current public aggregate evidence. Private report-intelligence JSONL files such
as `report_metadata.jsonl`, `forecast_claims.jsonl`, and
`report_outcome_labels.jsonl` may be absent on a clean or public-safe checkout;
the committed evidence below comes from public aggregate artifacts and schema
contracts.

| Artifact | Evidence |
| --- | --- |
| `registry/report_intelligence/extraction_report.json` | current public-safe artifact reports 320 forecast claims and 335 outcome labels: 87 industry ETF proxy, 248 stock price proxy. Semantic validation now passes as `schemas/report_intelligence_extraction_report_contract_rules`, which checks repo-relative output paths, public-text redaction, blocker-free aggregate status, public JSONL row counts, Markdown coverage counts, proxy readiness counts, and industry+stock outcome total consistency. |
| `registry/report_intelligence/report_outcome_labels.jsonl` | proxy outcome label semantic validation now requires `claim_window_set_id`, `window_role`, and `source_horizon_days` on both stock and industry proxy labels and rejects any `outcome_id`, `claim_window_set_id`, or `overlap_group_id` shared across `label_type` namespaces. It also checks `window_role` against `horizon_days`, validates `source_horizon_days`, validates `entry_datetime`/`exit_datetime` date order, pins channel-specific `decision_basis` and `evaluation_policy` values, checks per-window `effective_n_weight` against the governed stock/industry window weight table, rejects any claim window set whose total effective-N weight exceeds 1, and, when private forecast claims are present, requires every proxy label to trace to an existing forecast claim whose `signal_datetime` date is before the proxy `entry_datetime` date; stock proxy claims must cite source spans. Stock proxy labels also require `metadata_ts_code` and `llm_target_id` fields and semantically validate `target_resolution_source`: metadata-only, LLM-only, and metadata+LLM resolutions must support the same ordinary-stock `proxy_symbol`; conflicting ts_codes cannot generate labels. Both stock and industry proxy labels must use the default `SH510300`/`cn_etf`/`CSI300_ETF_PROXY` benchmark family; stock labels must use `single_stock_round_trip_20bps_v1` and `round_trip_cost=0.002`, while industry ETF labels must use `industry_etf_round_trip_10bps_v1` and `round_trip_cost=0.001`. This keeps stock-price and industry-ETF proxy outcomes stratified and source-grounded even when forecast claims, horizons, or proxy symbols overlap. |
| `registry/report_intelligence/patch_v1_5_coverage_report.json` | public count-only fallback preserves aggregate evidence when private JSONL inputs are absent; Phase C now passes, while Phase B/D remain blocked by manual review and footprint quality gates; Phase G remains rollout-gated but now carries shadow paper-trading evidence counts from `recipe_paper_trading_summary.json` |
| `registry/report_intelligence/industry_etf_proxy_map.jsonl` | 64 primary/governed mapping rows; `工业金属` maps to `SH560860` |
| `registry/report_intelligence/industry_etf_proxy_pit_availability.json` | labelability summary is kept consistent with `outcome_labeling_readiness.industry_etf_proxy_readiness`: 105 eligible industry claims, 39 labelable claims, 87 labelable windows, 225 pending future windows |
| `registry/report_intelligence/outcome_labeling_readiness.json` | stock readiness reports 171 eligible stock claims, 115 labelable stock claims, 248 labelable stock windows, and 432 pending future windows; public qlib source fields are redacted to `qlib://...` labels. Semantic validation now passes as `schemas/report_intelligence_stock_price_proxy_readiness_rules`, which hard-checks stock PIT realism policy, ordinary-stock code policy, benchmark/cost defaults, T+1 windows, public qlib redaction, labelable/pending claim counts, and stock series lifecycle totals. Entry-side and exit-side liquidity-verification gaps are tracked separately as `entry_liquidity_unverified` and `exit_liquidity_unverified`; both are blocking readiness gaps and cannot leak into generated labels. The current public artifact remains `survivorship_unverified`, but the contract now also accepts a future `delisted_inclusive_universe_audit_passed` state when the basis documents a passed delisted-inclusive audit. |
| `registry/report_intelligence/source_performance_profiles.jsonl`, `viewpoint_performance_profiles.jsonl`, and `method_performance_profiles.jsonl` | 3045 performance profile rows carry `outcome_layer_support` so profile evidence remains stratified by `label_type`, `benchmark_family`, and `cost_model_id`; semantic validation now passes as `schemas/report_intelligence_profile_outcome_layer_rules`, which checks layer keys, layer summaries, mixed-layer flags, and effective-N sums against each profile. |
| `registry/report_intelligence/recipe_paper_trading_runs.jsonl` | 1858 pre-registered shadow paper-trading runs |
| `registry/report_intelligence/recipe_paper_trading_summary.json` | 13 recipes passed paper-trading validation; 536 recipes have direct PIT binding; after-cost paper-trading summary is computed from passed pre-registered runs only; 1845 recipes remain blocked by direct binding, effective-N, or shadow-tool readiness gaps |
| `registry/report_intelligence/confidence_impact_monitor.json` and `registry/report_intelligence/monitoring_report.json` | 13 paper-trading validated recipes are monitored; unvalidated confidence impact count is 0; alpha-decay and calibration-drift observations remain shadow-only. `schemas/report_intelligence_alpha_decay_monitoring_rules` now also checks monitoring report corpus counts, tooling-loop counts, tool-gap priority counts, evidence-coverage counts, and source/viewpoint/method effective-N summaries against the underlying public registry artifacts. |
| `registry/report_intelligence/evolution_readiness_gate.json` | blocked; 9 blockers remain across paper-trading validation count, P9 evaluability-bucket coverage, schema/audit-history readiness, and manual forecast gold-set quality metrics. The semantic contract now hard-checks P13 machine thresholds in the committed gate evidence, including outcome coverage, stock/industry proxy counts, paper-trading counts and after-cost summary, monitor stability, audit refresh evidence, gap-distribution stability, and P9 coverage status. RI-EVOL-02 remains blocked by the 13/20 validated-recipe count, RI-EVOL-04 requires current schema/PIT/provenance/statistical evidence to match `current_schema_or_audit_gate_blocked` and trailing audit distinct/pass counts to match `audit_refresh_history_below_threshold`, RI-EVOL-05 remains blocked by human gold-set quality metrics, and RI-EVOL-07 remains blocked by the missing `evaluability_bucket:macro_asset_proxy_candidate` coverage stratum. `gap_distribution_history.jsonl` is also semantically checked so `total_gap_count`, `max_gap_name`, `max_gap_share`, `stable`, and `accepted` must match the committed gap counts; a single-gap share above 0.80 cannot be marked stable. |
| `registry/report_intelligence/prompt_mutation_candidates.jsonl` | 13 shadow-only mutation candidates exist across forecast extraction, confidence gating, paper-trading recipe validation, industry mapping, refresh stability, calibration, tool-gap prioritization, and Markdown quality; all have `promotion_state=shadow_candidate_only`, `manual_review_required=true`, `production_prompt_change_allowed=false`, and `private_text_included=false`. The semantic contract also requires the full offline validation matrix (`gold_set_review_pass`, PIT replay, schema, provenance, statistical robustness, and shadow paper-trading), rejects private or non-repo evidence paths in `evidence_refs`, and requires every referenced public evidence artifact to exist. |
| `registry/review_batches/manual_review_progress_report.json` and `registry/gold_sets/tushare_research_reports.review_summary.json` | public baseline: gold-set 0/100, analytical-footprint review 0/1001, source license 17529/17529 already applied, lockbox 0/1. Semantic validation now passes as `schemas/report_intelligence_manual_review_progress_rules`, which checks input paths, ready/simulation consistency, blocker consistency, home-tmp command prefixes, dry-run mode, and source-text-free `current_batch_status` counts. It accepts both the current blocked state and a future completed state where all gates have zero pending rows and no blockers. The public gold-set review summary is also checked as `schemas/report_intelligence_gold_review_gate_rules`: current 0/100 pending state is accepted, but false pass states, count drift, missing metrics, and below-threshold human review metrics are rejected. Synthetic pytest fixtures can mark manual rows complete for contract tests, but current target hashes in the real scratch still require human review. The action queue distinguishes already-applied gates from runnable apply work: source-license now reports `action_state=already_applied`, `can_run_now=false`, and an empty command set. The report includes aggregate `current_batch_status` for the active local 50-row gold-set, analytical-footprint, and lockbox scratch files, plus a public-safe full pending `batch_plan`: 3 gold-set batches and 21 analytical-footprint batches at 50 rows per batch except the final 1-row gold-set and footprint batches. Each batch explicitly records `apply_effect=merge_batch_into_target_review_template`, the transient `batch_input_path` for the 50-row import, the `target_review_template_path` it merges into, and the separate `promotion_input_path` used only after full human review; schema validation also rejects batch commands that use promotion inputs and promotion commands that use transient batch inputs. Current gold batch status is 50 rows, 0 complete, 50 pending, 0 malformed; missing required fields are aggregate counts only. Current analytical-footprint batch status is 50 rows, 0 complete, 50 pending, 0 malformed; missing required fields are aggregate counts only. Current lockbox decision status is 1 row, 0 complete, 1 pending, 0 malformed; missing required fields are aggregate counts only. Full gold-set and footprint review imports still require human decisions before promotion dry-run. |
| `registry/handoffs/rke_operator_handoff.json` | operator handoff semantic validation now passes as `schemas/report_intelligence_operator_handoff_rules`: command sequence order, home-tmp prefixes, reviewed input paths, promotion dry-run inputs, and production-disabled state are checked directly against the handoff artifact |
| `registry/handoffs/rke_operator_readiness_report.json` | operator readiness currently passes 18/18 checks: required registry valid, handoff command sequence complete, manual review runbook promotion dry-run source-license policy consistent, manual import templates sparse and provenance-tagged, batch inputs separated from promotion inputs, blank gold/lockbox/source-license templates rejected, lockbox upstream CLI guard matches manual gate readiness, blank bundle dry-run does not promote, manual review bundle manifest current, and promotion gate state matches PG01-PG10 criteria |
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
| P11 recipe paper-trading | Implemented; current aggregate threshold not cleared after forecast cap | pre-registration hash, OOS chronological split, required data contracts, cost/benchmark protocol, 1858 paper-trading runs, 13 validated recipes against the 20-recipe threshold |
| P12 confidence impact monitor | Implemented; current validated-recipe count is below the evolution threshold | monitor rows gate confidence impact on paper-trading validation; 13 validated recipes are monitored; alpha decay and calibration drift actions are tracked; monitoring report aggregate counts are semantically checked against public registry artifacts |

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
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke operator-readiness --root . --no-write
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke master-plan-status --root . --no-write
```

The repository pytest default is also configured to keep its `--basetemp` under
`/home/hap/tmp/mosaic-rke/pytest-mosaic-rke`; `tests/conftest.py` uses the same
home tmp root for the private Tushare fixture lock file. This prevents ordinary
test runs from placing large registry copies or fixture locks in system `/tmp`
or under the repository checkout.
`operator-readiness --no-write` also builds its temporary dry-run registry under
`/home/hap/tmp/mosaic-rke` and now skips local-only Tushare source blobs and
report Markdown/PDF/cache directories when copying the dry-run root. It still
copies the manual review templates required for blank-import safety checks, but
does not depend on copying private source JSONL/manifest files.

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

Most recent focused validation after read-only status and action-queue
hardening:

```bash
uv run python -m pytest tests/test_rke_cli.py::test_rke_cli_master_plan_status_writes_coverage tests/test_rke_cli.py::test_rke_cli_master_plan_status_no_write_preserves_artifacts -q --basetemp /home/hap/tmp/mosaic-rke/pytest-master-plan-no-write-cli-20260614
uv run python -m pytest tests/test_rke_review_progress.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-review-progress-full-20260614
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
`review-progress --summary --no-write` and
`review-progress --actions-only --no-write` now include a compact public-safe
`batch_overview` per review gate, so operators can see total batch count,
current batch size/path, evidence alignment, final-batch size, and the
requirement to rerun `review-progress` after each accepted batch without
expanding the full batch plan. If a gate is already ready for promotion while
an older scratch batch file still contains blank fields, the action queue uses
the promotion input path and marks that scratch as stale instead of showing its
missing fields as current work.
`master-plan-status --no-write` and `schema-status --failures-only --no-write`
still exit 2 only because the same manual review-derived schema and patch
coverage gates remain open. The schema-status failure payload now includes
public-safe `next_actions` for the analytical-footprint review summary gate and
patch v1.5 manual coverage gate, so operators can jump from the failed schema
records back to the review-progress/evidence/dry-run commands without editing
coverage artifacts directly. `master-plan-status --no-write` now also includes
public-safe `next_actions` that point to `schema-status --failures-only`,
`review-progress --actions-only`, and `evolution-readiness --no-write`, then
reuses the same schema/manual-review actions and field contracts. This makes the
MVP-D3 `schema validation report accepted must be true` blocker traceable to the
underlying manual review gates without editing master-plan coverage artifacts
directly. `promotion-status --no-write` now also includes public-safe
`next_actions` for PG02 manual gold-set review and PG09 lockbox review, with
lockbox commands explicitly marked as dependent on upstream manual gates. Its
promotion dry-run action and the manual review runbook now follow the same
source-license input policy as operator handoff: when PG03 source-license review
already passes, they omit `--license-input` and do not rebuild
`source_license_policy_import.jsonl`; only an unpassed PG03 path includes the
license-import build step.
`evolution-readiness --no-write` also exits 2 when
`gate_status=blocked` and includes `blocked_check_ids` / `blocked_checks` in
stdout so operators can see that RI-EVOL-02, RI-EVOL-04, RI-EVOL-05, and
RI-EVOL-07 are the active readiness blockers. The same read-only output now
includes public-safe
`next_actions` with temp-prefixed commands for the current gold-set review
batch, the current analytical-footprint review batch, the schema/audit blocker
inspection path, and the distinct `data_vintage_hash` refresh-history
requirement.

Most recent focused validation after proxy outcome ID namespace hardening:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_cross_label_type_id_collisions -q --basetemp /home/hap/tmp/mosaic-rke/pytest-id-contract
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-schema-id-contract
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py mosaic/rke/report_intelligence.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .
```

Most recent focused validation after analytical-footprint indicator alias
hardening and non-research claim filter tightening:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_report_intelligence.py::test_report_intelligence_structures_string_indicator_mentions tests/test_rke_report_intelligence.py::test_report_intelligence_structures_common_report_indicator_aliases -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-indicator-aliases
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_suggests_missing_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_risk_warning_footprints -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-footprint-evidence-rules
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_suggests_missing_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_unknown_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_risk_warning_footprints -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-footprint-evidence-unknown-mapping
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_unknown_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_suggests_missing_metric_mapping -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-footprint-repair-suggestions
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_suggests_missing_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_unknown_metric_mapping -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-footprint-candidate-summary
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_flags_unknown_metric_mapping tests/test_rke_report_intelligence.py::test_analytical_footprint_review_evidence_suggests_missing_metric_mapping -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-footprint-unknowns-decision
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_report_intelligence.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-report-intelligence-indicator-rules
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_report_intelligence.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-report-intelligence-evidence-unknown-mapping
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_report_intelligence.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-report-intelligence-repair-suggestions
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_report_intelligence.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-report-intelligence-candidate-summary
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_report_intelligence.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-report-intelligence-unknowns-decision
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_gold_candidate_claims.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-gold-candidate-claim-filters
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_manual_review_batches.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-manual-review-batches-filters
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_review_progress.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-review-progress-current
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_schema_artifacts.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-schema-artifacts-current
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_gold_candidate_claims.py::test_gold_candidate_claims_skip_boilerplate_risk_warning_report_claims tests/test_rke_gold_candidate_claims.py::test_gold_candidate_claims_skip_generic_risk_enumeration_report_claims tests/test_rke_gold_candidate_claims.py::test_gold_candidate_claims_skip_unprefixed_generic_risk_list_report_claims tests/test_rke_gold_candidate_claims.py::test_gold_candidate_claims_skip_boilerplate_risk_warning_markdown_sentences -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-risk-filters
uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py mosaic/rke/claim_text_filters.py tests/test_rke_report_intelligence.py tests/test_rke_schema_artifacts.py tests/test_rke_gold_candidate_claims.py tests/test_rke_manual_review_batches.py tests/test_rke_review_progress.py
uv run python scripts/check_prompt_leaks.py
git check-ignore registry/report_intelligence/analytical_footprint_review_evidence.jsonl registry/report_intelligence/analytical_footprint_review_evidence.md registry/report_intelligence/analytical_footprint_review_batch.jsonl registry/review_batches/gold_set_reviewed.jsonl
git diff --check
```

Most recent focused validation after applying the current reviewed batches and
tightening the gold candidate queue:

```bash
uv run mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl --dry-run
uv run mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl
uv run mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run
uv run mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_gold_candidate_claims.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-gold-candidate-tightened3
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_manual_review_batches.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-manual-review-tightened2
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run pytest tests/test_rke_review_progress.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-review-progress-tightened
```

Most recent focused validation after report-level forecast-claim cap hardening:

```bash
uv run pytest tests/test_rke_report_intelligence.py::test_user_prompt_requires_context_synthesized_forecast_claims tests/test_rke_report_intelligence.py::test_select_report_forecast_claims_caps_and_preserves_source_order tests/test_rke_report_intelligence.py::test_report_intelligence_caps_forecast_claims_per_report tests/test_rke_report_intelligence.py::test_refresh_forecast_mapping_governance_caps_existing_rows_per_report -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-forecast-cap4
uv run pytest tests/test_rke_report_intelligence.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-ri-forecast-cap-full2
uvx ruff@0.15.15 check mosaic/rke/report_intelligence.py tests/test_rke_report_intelligence.py
```

The current approved scratch batches imported cleanly: 20 gold-set rows and 50
analytical-footprint rows were accepted with zero duplicate IDs, missing target
IDs, or invalid rows. After import, gold-set review has no pending rows
(`158/158` complete), but it still fails the quality gate: reviewed document
coverage is below the 50-document threshold, `direction_accuracy=0.626582`,
`variable_mapping_accuracy=0.189873`, and
`unsupported_field_false_grounding_rate=0.227848`. This means the next gold-set
work item is pipeline quality, not more approval of the old queue. The footprint
gate is now `34/1001` complete with 967 rows pending, and the current 50-row
batch has no missing required fields.

The gold candidate queue now keeps full diagnostics but narrows the default
review queue. Candidate rows with missing canonical variable mapping, ambiguous
or conflicting direction, non-testable direction values, or
single-sentence/context-synthesis fallback are no longer exported by default.
Report-claim rows with `forecast_mapping_insufficient` or `forecast_not_testable`
remain reviewable because they are useful for measuring mapping failure modes.
Direction reconciliation now refuses to let weak local keyword rules override a
conflicting LLM direction: explicit conflicts become `ambiguous` with
`direction_conflict_requires_review`. Fallback and report-derived candidates also
stop populating `unsupported_fields` unless a future extractor provides an
explicit source-grounded unsupported field. On the current local diagnostics this
leaves 84 candidate diagnostics across 37 sources and 31 default-reviewable
forecast-claim candidates across 19 sources; no default-reviewable row comes
from sentence fallback.

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

Most recent focused validation after proxy outcome effective-N hardening:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_bad_effective_n_weights tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_window_set_weight_sum_above_one -q --basetemp /home/hap/tmp/mosaic-rke/pytest-effective-n-contract
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-schema-effective-n
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after proxy outcome forecast-traceability hardening:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_trace_proxy_labels_to_forecast_claims tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_untraceable_stock_proxy_claim -q --basetemp /home/hap/tmp/mosaic-rke/pytest-forecast-trace-contract
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-schema-forecast-trace
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after stock target-resolution hardening:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_metadata_and_llm_stock_resolution tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_bad_stock_target_resolution -q --basetemp /home/hap/tmp/mosaic-rke/pytest-target-resolution-contract
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-schema-target-resolution
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after proxy benchmark/cost hardening:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_bad_benchmark_and_cost_policy -q --basetemp /home/hap/tmp/mosaic-rke/pytest-benchmark-cost-contract
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-schema-benchmark-cost
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after proxy PIT timing hardening:

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_accept_complete_proxy_contracts tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_bad_entry_exit_timing tests/test_rke_schema_artifacts.py::test_report_outcome_label_semantics_reject_same_day_signal_entry -q --basetemp /home/hap/tmp/mosaic-rke/pytest-pit-timing-contract
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-schema-pit-timing
uvx ruff@0.15.15 check mosaic/rke/schema_validation.py tests/test_rke_schema_artifacts.py
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .
```

`schema-status` still exits 2 only for the existing analytical-footprint review
and patch v1.5 manual coverage gates; the proxy outcome label contract record is
accepted.

Most recent focused validation after stock long-window evidence hardening:

```bash
uv run pytest tests/test_rke_report_intelligence.py::test_report_intelligence_keeps_long_window_stock_hits -q --basetemp /home/hap/tmp/pytest-rke-stock-long-window
uv run pytest tests/test_rke_report_intelligence.py::test_report_intelligence_labels_stock_claims_with_qlib_price_windows tests/test_rke_report_intelligence.py::test_report_intelligence_counts_stock_price_proxy_as_labelable_channel tests/test_rke_report_intelligence.py::test_report_intelligence_keeps_long_window_stock_hits -q --basetemp /home/hap/tmp/pytest-rke-stock-proxy-focused
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
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke prepare-gold-review --root . --gold-batch-size 50 --offset 0 --force --reviewer hap --review-date 2026-06-12
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke write-gold-review-evidence --root . --limit 50 --offset 0 --review-input registry/review_batches/gold_set_reviewed.jsonl
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl --dry-run
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke prepare-gold-review --root . --full --force --reviewer hap --review-date 2026-06-12
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke prepare-footprint-review --root . --limit 50 --offset 0 --reviewer hap --review-date 2026-06-12 --overwrite
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke prepare-footprint-review --root . --output registry/report_intelligence/analytical_footprint_reviewed.jsonl --reviewer hap --review-date 2026-06-12 --overwrite
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke write-footprint-review-assist --root .
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 --review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl
```

These commands write private, gitignored manual handoff files. The current local
gold-set scratch batch has 20 rows, of which 10 have complete human-review
fields and 10 still have aggregate missing-field counts for `manual_claim_text`
and the seven boolean review fields. Its private evidence draft is aligned with
the same 20 scratch rows and has no target-row-hash mismatches. The promotion
gold-set import remains not ready because the remaining scratch rows and
quality-metric blockers still require human decisions. The current active
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
also are not import files. Gold-set and analytical-footprint evidence commands
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

`MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root .`
currently exits with code 2 by design. The refreshed failure-only run reports 26
semantic failures across four records:
`schemas/report_intelligence_analytical_footprint_review_rules`,
`schemas/report_intelligence_evolution_readiness_gate_rules`,
`schemas/report_intelligence_gold_review_gate_rules`, and
`schemas/report_intelligence_patch_v1_5_coverage_rules`. These failures are
downstream of the analytical-footprint review gate, Phase B human gold-set
review quality metrics, the paper-trading validated recipe threshold, and Phase
D footprint quality gate. All ordinary schema records, proxy outcome
contracts, mapping/PIT availability contracts, recipe paper-trading contracts,
runtime guards, PIT/provenance/statistical/tooling audits, refresh-history
contracts, operator handoff rules, promotion dry-run rules, and
production-promotion gate semantic rules pass in the current public artifact set.
Profile outcome-layer semantic rules now also pass for 3045 source, viewpoint,
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
   Source-license review is applied in the manual progress report, but the
   broader promotion path is still blocked by source-text redaction and other
   promotion criteria. The gold-set row-level review is complete, but its quality
   metrics fail and must be addressed through improved extraction/mapping rules
   and a refreshed gold corpus with at least 50 reviewed documents. The footprint
   review has 34 accepted rows and 967 rows still pending. Validate each
   footprint batch with
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run`,
   then apply through the same import path.
2. P9 coverage watchlist: current public gate reports `coverage_gate_status=blocked`
   because `evaluability_bucket:macro_asset_proxy_candidate` is missing. The
   count thresholds for selected reports, Markdown-ready samples, quality-passed
   Markdown, LLM-processed reports, stock reports, industry reports, sector
   buckets, and 120-day stock outcome readiness are otherwise met.
3. Outcome evidence: current gate thresholds are cleared: 150 unique PIT outcome
   claims, 39 industry proxy claims, and 115 stock proxy claims.
4. Paper-trading evidence: current gate thresholds are not cleared after the
   report-level forecast-claim cap: 1858 pre-registered runs remain, but only 13
   recipes are currently validated against the 20-recipe threshold. The
   after-cost summary is computed from passed pre-registered runs only.
   Remaining recipe rows stay blocked or shadow-only when direct PIT binding,
   effective N, or shadow-tool readiness is insufficient.
5. Confidence impact monitor: current confidence-impact leakage gate is still
   clean with no unvalidated confidence impact, but only 13 monitored validated
   recipes remain after the forecast cap. Alpha decay and calibration drift
   observations are tracked but remain shadow-only.
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
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke review-progress --root . --summary --no-write`,
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke review-progress --root . --actions-only --no-write`,
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke operator-readiness --root . --no-write`,
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke master-plan-status --root . --no-write`,
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke evolution-readiness --root . --refresh-prompt-mutations`,
   promotion dry-run, and
   `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke uv run mosaic-rke schema-status --root . --failures-only --no-write`.
   For focused manual work, add `--review-kind gold_set`, `--review-kind footprint_review`, `--review-kind source_license`, or `--review-kind lockbox` to the summary or action-queue command; add `--action-state needs_human_review_fields`, `--action-state ready_to_apply`, `--action-state already_applied`, or `--action-state waiting_on_dependencies` to `--actions-only` when operators need one work class. The lockbox summary, runbook, operator handoff, and lockbox prepare/apply CLI paths are dependency-aware and should remain on `wait_for_prior_manual_gates` / `waiting_on ...` until the upstream manual review gates pass.

Until those gates pass, evolution outputs remain shadow candidates and must not
modify production prompts or production trading decisions.
