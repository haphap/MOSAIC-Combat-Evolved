# RKE Report Intelligence Operations Runbook

This file records local RKE report-intelligence operations so future agents can
resume from the latest known state instead of rediscovering or reinstalling the
same environment. Do not write API keys, licensed report prose, PDF contents, or
Markdown excerpts here.

## Current Local Runtime

- Repository: `/home/hap/Project/MOSAIC-RKE`
- Private runtime/cache root: `.mosaic/rke/report_intelligence/`
- Local temp root: `~/tmp/mosaic-rke/`
- MinerU CLI: `.venv/bin/mineru`
- Required MinerU backend for report conversion: `vlm-auto-engine`
- Previous `hybrid-auto-engine` smoke is useful only as environment proof; do
  not use it for the macro/strategy report batches unless the user explicitly
  asks for hybrid mode.
- Existing Docker vLLM container to inspect/start first:
  `rke-vllm-qwen36-27b-160k-20260610`
- Docker vLLM port: `8020`
- RKE extraction LLM config source: `.env`
- RKE extraction LLM env vars: `MOSAIC_RKE_VLLM_BASE_URL`,
  `MOSAIC_RKE_VLLM_MODEL`, and API-key env vars

Do not reinstall MinerU or rebuild vLLM until these checks fail:

```bash
.venv/bin/mineru --help
docker inspect rke-vllm-qwen36-27b-160k-20260610
```

## Local Macro Strategy Source

The macro strategy source registry is built from actual PDFs under:

```text
/home/hap/Downloads/yanbaoke/宏观策略
```

Do not rely on `文件清单.txt`; it is incomplete. Scan the directory recursively
for `*.pdf`.

Current private source outputs:

```text
registry/sources/local_macro_strategy_reports.jsonl
registry/sources/local_macro_strategy_reports.manifest.json
```

Both paths are gitignored and must remain private.

Last source build:

- Command:

```bash
uv run mosaic-rke build-local-macro-report-sources \
  --root . \
  --input-dir /home/hap/Downloads/yanbaoke/宏观策略
```

- Scanned PDF count: `788`
- Written source rows: `788`
- Date range: `2023-08-30` to `2026-06-09`
- Report type counts:
  `宏观策略=329`, `A股=22`, `债券=7`, `商品=33`, `大类资产=20`,
  `海外=11`, `待分类=366`

## MinerU Usage

User requirement: run MinerU in vLLM/VLM mode. Use `vlm-auto-engine` for PDF to
Markdown conversion, not `pipeline`, and not `hybrid-auto-engine` for the normal
macro/strategy batch path.

Mode distinction:

- `vlm-auto-engine` is MinerU local VLM mode. It uses local computing power
  through MinerU's VLM engine and does not require the Docker vLLM OpenAI server
  to be running. This mode has been smoke-tested locally.
- `vlm-http-client` and `hybrid-http-client` are MinerU HTTP-client modes. These
  require a compatible server URL via `--mineru-server-url` / MinerU `-u`, for
  example `http://127.0.0.1:30000`. Start and health-check the Docker vLLM
  service before using either HTTP-client backend.
- The RKE extraction LLM endpoint on port `8020` is separate from MinerU local
  VLM conversion. Do not infer that Docker vLLM is running just because
  `vlm-auto-engine` succeeds.

Preferred smoke command:

```bash
TMPDIR=~/tmp/mosaic-rke uv run mosaic-rke report-intelligence \
  --root . \
  --env-file .env \
  --source-path registry/sources/local_macro_strategy_reports.jsonl \
  --cache-dir .mosaic/rke/report_intelligence \
  --registry-dir .mosaic/rke/report_intelligence/macro_vlm_smoke_registry \
  --selection-order oldest \
  --limit 1 \
  --mineru-command .venv/bin/mineru \
  --mineru-backend vlm-auto-engine \
  --mineru-timeout-seconds 3600 \
  --skip-llm \
  --overwrite
```

Preferred batch command:

```bash
TMPDIR=~/tmp/mosaic-rke uv run mosaic-rke report-intelligence \
  --root . \
  --env-file .env \
  --source-path registry/sources/local_macro_strategy_reports.jsonl \
  --cache-dir .mosaic/rke/report_intelligence \
  --registry-dir .mosaic/rke/report_intelligence/macro_vlm_batch_registry \
  --selection-order stratified \
  --limit 20 \
  --mineru-command .venv/bin/mineru \
  --mineru-backend vlm-auto-engine \
  --mineru-timeout-seconds 3600 \
  --mineru-batch-size 1 \
  --mineru-batch-max-bytes 8000000 \
  --skip-llm
```

Operational rules:

- Start with `--limit 1` after any config change.
- For cached-stable VLM conversion on this 5090 host, prefer large MinerU
  batches after the single-file smoke passes. The 2026-06-20 old-stock run
  converted the remaining `44/44` PDFs in one VLM batch in roughly 5 minutes,
  materially faster than the earlier batch-size-1 path.
- Stop the Docker OpenAI-compatible vLLM service before local MinerU VLM runs
  when GPU memory is needed:
  `docker stop rke-vllm-qwen36-27b-160k-20260610`.
- Prepend `.venv/bin` to `PATH` so MinerU's local VLM subprocess can find
  `ninja`: `PATH=/home/hap/Project/MOSAIC-RKE/.venv/bin:$PATH`.
- Current MinerU CLI does not expose a `--max_concurrency` flag. Use
  `MINERU_API_MAX_CONCURRENT_REQUESTS=200` for the local MinerU API request
  concurrency.
- Current installed MinerU source does not read
  `MINERU_MIN_BATCH_INFERENCE_SIZE`. The useful VLM window knob observed
  locally is `MINERU_PROCESSING_WINDOW_SIZE=256`; keep
  `MINERU_MIN_BATCH_INFERENCE_SIZE=256` only as a harmless compatibility env if
  future MinerU versions add it.
- Keep outputs under `.mosaic/` until quality is confirmed.
- Do not reinstall MinerU or recreate the vLLM service before checking
  `.venv/bin/mineru --help` and the existing Docker/container state.
- Do not commit PDF, Markdown, MinerU output, or source-row JSONL artifacts.
- If a previous `hybrid-auto-engine` run is still active, wait for it to return
  or terminate only that specific `report-intelligence`/MinerU process before
  launching the VLM batch.

Tuned local VLM batch pattern:

```bash
PATH=/home/hap/Project/MOSAIC-RKE/.venv/bin:$PATH \
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
MINERU_API_MAX_CONCURRENT_REQUESTS=200 \
MINERU_PROCESSING_WINDOW_SIZE=256 \
MINERU_MIN_BATCH_INFERENCE_SIZE=256 \
.venv/bin/mosaic-rke report-intelligence \
  --root . \
  --env-file .env \
  --source-path .mosaic/tmp/<frozen_source_batch>.jsonl \
  --cache-dir .mosaic/rke/report_intelligence \
  --registry-dir .mosaic/rke/report_intelligence_batches/<vlm_batch_registry> \
  --selection-order oldest \
  --limit <N> \
  --skip-download \
  --mineru-command .venv/bin/mineru \
  --mineru-backend vlm-auto-engine \
  --mineru-timeout-seconds 3600 \
  --mineru-batch-size 80 \
  --mineru-batch-max-bytes 200000000
```

## Forecast Claim Pre-Review Rule

Before manual gold-set review, keep the source-grounded `claim_text` unchanged
and add a separate `analyst_claim` for the financial-practitioner rewrite. The
rewrite may clarify the macro regime, industry regime, transmission mechanism,
company/sector capability, earnings or valuation logic, target, direction, and
horizon, but it must not add facts or causal links unsupported by the report
chunk.

Each forecast claim should also carry `pre_review` with
`perspective=financial_practitioner` and `decision` in
`include|exclude|rewrite_needed`. Deterministic guardrails must override model
suggestions and exclude claims that are not source-grounded, have no actionable
direction or target, lack a finance-relevant market/fundamental impact, or lack
an economic mechanism linked to the target impact. Mapping gaps or missing
regime context should normally be marked `rewrite_needed`, not silently accepted.

`claim_regime_trace` is PIT background only. It records Mosaic macro/industry/
company regime context by the report as-of date for later outcome and backtest
stratification; it must not be used to validate claim correctness during
extraction or manual review.

Report-level rating, target-price, or industry-rating definitions may supply a
missing horizon for source-grounded forward claims with an evaluable market
proxy. For example, if the full Markdown contains a broker rating definition
such as a future 6-month relative-performance window, the extractor may mark the
claim with `horizon.source=report_level_rating_definition` and
`extraction_quality.horizon_inferred_from_report_level=true`. Do not inherit
that report-level horizon into descriptive current-state claims, incomplete
fragments, unsupported investment suggestions, or claims without an evaluable
target/proxy.

## Macro Claim Backtest Rule

Macro research claim performance is evaluated with non-LLM PIT outcome labels,
not during extraction or manual review. Keep `claim_regime_trace` as background
regime context only.

Default macro-research evaluation windows are T+1 entry, then 90, 180, and 360
trading days after entry. Keep `claim_horizon` as the report's stated forecast
window; do not copy the fixed evaluation windows into claim horizon unless the
report itself states them.

Backtest mapping:

- Equity/asset-allocation claims: compare mapped ETF proxy price return after
  cost, for example broad A-share, Hong Kong equity, US equity, gold, or bond
  ETFs.
- Bond price or duration-positive claims: use bond ETF price return. Positive
  bond-price direction is correct when the ETF return is positive.
- Interest-rate/yield claims: use the yield series directly when PIT yield data
  is available. Falling-yield claims are correct when the 90/180/360-day yield
  change is negative; rising-yield claims are correct when the change is
  positive. Do not invert a bond ETF proxy silently for yield claims.
- FX claims: use the quoted FX series direction explicitly, for example
  USD/CNY up means RMB depreciation and USD strength. Store the quote convention
  in the outcome label.
- Commodity claims: use the commodity ETF, futures, or spot series named by the
  mapping. If only an ETF proxy exists, label it as a proxy, not the commodity
  spot itself.

Current first-pass local ETF proxies are available for broad A-shares, large
caps, mid/small caps, ChiNext growth, Hong Kong equity, Nasdaq, S&P 500, China
government bonds, credit bonds, 10-year government-bond ETF, and gold. Treat
direct interest-rate/yield, FX, and non-gold commodity claims as pending until
their PIT series are wired into the outcome labeler.

The outcome row must record `outcome_label_source`, `target_series_id`,
`comparison_type`, `quote_convention` when relevant, `entry_datetime`,
`exit_datetime`, `horizon_days`, raw change/return, directional hit, and
`performance_value_basis`. Missing PIT data should produce a pending or blocked
label reason, not a guessed result.

## Claim Horizon Extraction Rule

Extract claim horizon from the full report context before judging a single claim
as horizon-missing. Use this order:

1. Claim text explicit horizon.
2. Section heading or nearby section context.
3. Report title, abstract, or core-view temporal context.
4. Rating definition or report-level investment-horizon definition.
5. Report type default, with low confidence.

Store inherited context in `extraction_quality.report_temporal_context` and mark
`horizon_inferred_from_report_temporal_context=true`. This context can make a
source-grounded financial claim testable, but it is not outcome evidence and is
not the same as the fixed `90/180/360` evaluation windows.

Also preserve non-horizon report context under
`extraction_quality.report_context`:

- `subject_context`: covered company, sector, or asset universe from report
  metadata and title context.
- `section_context`: nearest chunk section title and any section-level horizon.
- `benchmark_context`: report-level benchmark wording such as market benchmark
  index, HS300, S&P 500, or Nasdaq.
- `rating_context`: rating terms and rating-horizon definitions.
- `frequency_context`: report cadence inferred from title or report type, such
  as weekly, monthly, quarterly, semiannual, or annual, with low confidence.

These contexts may disambiguate generic claim language during extraction and
manual review, but they must not validate claim correctness or override a
claim's source-grounded target, direction, or benchmark.

## Dual-Model Claim Expansion Rule

For gold-set sample expansion, run the same cached-Markdown source batch through
both the local qwen/vLLM extractor and Mimo, then compare public-safe aggregate
quality before merging anything into `registry/report_intelligence`.

Operational steps:

1. Freeze one source-id batch under `.mosaic/tmp/`, excluding already processed
   sources and requiring cached Markdown. Reuse the exact same source-id file for
   both models.
2. Copy `registry/report_intelligence/macro_regime_calendar.jsonl` into each
   temporary output registry before extraction, so new claims receive the same
   PIT `claim_regime_trace` background.
3. Run local qwen/vLLM into a private temp registry, for example
   `.mosaic/tmp/report_intelligence_qwen_<batch>/`, with `--skip-download`,
   `--skip-convert`, `--require-cached-markdown`, and the frozen source ids.
   Start the existing Docker container
   `rke-vllm-qwen36-27b-160k-20260610` only when needed, then stop it after the
   qwen run to release GPU memory.
4. Run Mimo into a separate private temp registry, for example
   `.mosaic/tmp/report_intelligence_mimo_<batch>/`, using `--env-file .env` and
   the same frozen source ids. Do not print or commit endpoint URLs, API keys,
   source prose, or claim text.
5. Compare only no-source-text metrics: processed reports, blockers, forecast
   claim count, `pre_review.decision` counts, testable claims, complete
   `claim_regime_trace` count, target/direction distributions, and
   gold-candidate reviewable count.
6. A claim is eligible for manual gold review only when
   `pre_review.decision == "include"` and `gold_candidate_reviewable(...)` is
   true. Model agreement is useful but not sufficient; disagreement must not be
   auto-labeled.
7. Merge into the main private registry only after the batch produces enough
   reviewable claims to justify human review. Otherwise keep the temp outputs as
   comparison evidence and run another frozen batch.

Current empirical guidance from the 2026-06-18 20-report Tushare comparison:
Mimo was more stable (`20/20` processed, `0` blockers) and produced more
footprints/method patterns, while local qwen produced one more forecast claim and
one more gold-reviewable claim. Use dual-model extraction for expansion; do not
switch gold-claim extraction to Mimo-only unless later batches improve
gold-reviewable yield.

## Mimo Parallel Extraction

`mimo-v2.5-pro` is suitable for sharded parallel extraction when Markdown is
already cached. The RKE extraction loop is serial inside one process, so parallel
throughput comes from running multiple independent `report-intelligence`
processes against non-overlapping frozen source shards.

2026-06-20 empirical result on an 80-report old-stock cached-Markdown batch:

- Parallel plan: `8` shards, `10` reports per shard, each writing to its own
  private batch registry under `.mosaic/rke/report_intelligence_batches/`.
- First pass: `80` selected, `75` LLM-processed, `5` blockers, `86` forecast
  claims, `223` analytical footprints, `316` stock proxy outcome labels.
- Failure mode: no `429` rate-limit errors observed; blockers were transient
  SSL EOF errors plus one malformed JSON response.
- Retry plan: one failed source per retry shard, run concurrently.
- Retry result: `5/5` processed, `0` blockers, `7` forecast claims, `19`
  analytical footprints, `24` stock proxy outcome labels.
- Clean merge rule: filter failed source rows out of the first-pass shard JSONL
  inputs before merging retries, because a blocked multi-chunk report may leave
  partial footprint rows. Merge retry directories after clean first-pass shard
  directories.
- Final merged registry after `current_212 + extra_120 + macro_cached_60_clean +
  clean old-stock shards + retries`: `458` metadata rows, `458` forecast claims,
  `456` LLM-processed reports, `680` outcome labels, and `593` stock proxy
  outcome labels.
- Gate effect: paper-trading validated recipes improved to `8`; the evolution
  gate still requires `20`, so more directly labelable stock/industry claims or
  stronger recipe-to-outcome binding is still needed.

Shard command pattern:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
.venv/bin/mosaic-rke report-intelligence \
  --root . \
  --env-file .env \
  --source-path .mosaic/tmp/<mimo_parallel_batch>/shard_00.jsonl \
  --cache-dir .mosaic/rke/report_intelligence \
  --registry-dir .mosaic/rke/report_intelligence_batches/<batch>/shard_00 \
  --selection-order oldest \
  --limit 10 \
  --skip-download \
  --skip-convert \
  --require-cached-markdown \
  --vllm-timeout-seconds 180 \
  --progress-jsonl
```

Recommended operating pattern:

1. Freeze the source rows once under `.mosaic/tmp/`; never resample between
   shards.
2. Split into `8` concurrent shards while the Mimo RPM quota is `100`. Use
   `10` reports per shard for small batches and up to `25` reports per shard
   for larger cached-Markdown batches. Do not use `20` concurrent shards; the
   2026-06-20 test triggered broad `429` rate-limit failures.
3. Launch all shard commands concurrently, each with a distinct `--registry-dir`.
4. Summarize `extraction_report.json` from every shard and collect blocker
   source ids.
5. Retry blockers as one-source shards, still concurrently, with the same
   cached Markdown and `--vllm-timeout-seconds 180`.
6. Build a clean first-pass shard set that removes blocked source ids from
   mergeable JSONL inputs, then merge clean shards and retry dirs with
   `--replace --refresh-derived`.
7. Recheck `schema-status --failures-only --no-write`,
   `evolution-readiness --no-write`, and `extraction_provenance_audit.json`.

Do not commit the frozen source shards, batch registries, extracted claims,
source spans, PDF/Markdown caches, or retry outputs.

Additional 2026-06-20 tuning:

- MinerU VLM converted a 200-report cached-PDF stock batch with
  `--mineru-batch-size 80` as three batches (`80 + 80 + 40`), producing
  `200/200` Markdown and `0` blockers.
- Mimo `20`-way extraction over `20 x 10` shards was too aggressive: many
  shards returned `429` and the run was discarded.
- Mimo `8`-way extraction over `8 x 25` shards was stable: first pass
  processed `199/200`, with `0` rate-limit errors and one transient SSL EOF.
  A one-source retry succeeded, so the batch was cleanly mergeable after
  filtering the failed source from the first-pass status/metadata rows.
- The 200-report batch added `255` first-pass forecast claims, `597`
  footprints, and `732` stock proxy outcome labels before retry; after merge
  with prior batches the main private registry had `658` metadata rows, `714`
  forecast claims, `656` LLM-processed reports, `1415` outcome labels, and
  `1328` stock proxy outcome labels.
- Quality implication: extraction throughput improved, but paper-trading
  validated recipes fell to `4` after adding the newer 2026 stock reports.
  Treat this as a signal that the current evolution blocker is recipe
  effective-N/direct-outcome robustness, not just extraction volume.
- Mature 2025 stock reports fixed the RI-EVOL-02 effective-N issue. The
  2026-06-20 run added two older stock batches from January 2025:
  one `100`-row frozen batch with `99/100` Markdown-ready rows after excluding
  one empty-PDF source, and one follow-up `100/100` Markdown-ready batch. Both
  used `8` concurrent Mimo shards, clean first-pass filtering, and one-source
  retries for transient failures.
- First mature 2025 Mimo batch: first pass processed `98/99`, then a one-source
  retry succeeded. After merging clean shards plus retry, the main private
  registry had `757` metadata rows, `838` forecast claims, `1772` stock proxy
  outcome labels, and `15` validated paper-trading recipes.
- Second mature 2025 Mimo batch: VLM conversion produced `100/100` Markdown,
  first-pass Mimo processed `99/100`, and the one transient SSL EOF retry
  succeeded. After merging clean shards plus retry, the main private registry
  had `857` metadata rows, `958` forecast claims, `2188` stock proxy outcome
  labels, and `27` validated paper-trading recipes.

2026-06-21 Mimo concurrency smoke:

- Purpose: validate `mimo-v2.5-pro` concurrent extraction under the documented
  `100 RPM` quota before using the concurrent form for more cached-Markdown
  batches.
- Setup: `8` concurrent `report-intelligence` processes, `1` cached Markdown
  report per shard, each shard writing to its own private registry under
  `.mosaic/rke/report_intelligence_batches/mimo_concurrency_smoke_20260621_02/`.
- Result: `8/8` reports LLM-processed, `0` blockers, `0` rate-limit shards,
  `11` forecast claims, `28` analytical footprints, and `44` outcome labels.
  Slowest shard finished in about `99s`; other shards finished in about
  `28-49s`.
- Post-smoke processing status: the main private registry already includes the
  successful 2026-06-20 `8`-way Mimo stock-report batches. The current merged
  derived refresh has `857` metadata rows, `855` LLM-processed reports, `958`
  forecast claims, `2435` analytical footprints, `2188` stock price proxy
  outcome labels, and `0` extraction blockers.
- Operational decision: because the smoke passed, keep Mimo extraction in
  sharded concurrent mode for cached-Markdown batches. Use `8` concurrent
  shards by default while quota is `100 RPM`; use up to `25` reports per shard
  for larger batches, and retry transient blockers as one-source shards. Serial
  Mimo extraction should be reserved for single-report debugging or endpoint
  isolation. Do not use `20` concurrent shards unless the provider quota or
  observed rate-limit behavior changes.
- Current gate implication: `RI-EVOL-02` passed once the mature 2025 samples
  were merged. Because the merged registry is extraction-clean, do not add more
  stock samples just to clear `RI-EVOL-04`. The active blocker is the
  footprint/manual-review schema gate plus the required clean audit vintages, so
  the next productive work is footprint review approval/import and derived audit
  refresh.
- Sandbox note: the same smoke fails inside the managed network sandbox with
  DNS resolution errors. That is an environment restriction, not a Mimo
  rate-limit signal. Use the approved non-sandbox network execution path for
  real Mimo extraction.

## MinerU Smoke Status

Last completed Mimo extraction smoke from cached VLM Markdown:

16-report cached VLM Markdown coverage batch:

The 16 quality-passed VLM Markdown reports from `macro_vlm_batch_registry` were
processed through Mimo in serial small batches, not one large job. Use this
combined result as the current coverage baseline. A failed no-network sandbox
trial may exist under `macro_mimo_vlm_extract_16_registry`; do not use that
directory for coverage statistics.

Successful private registry directories:

```text
.mosaic/rke/report_intelligence/macro_mimo_vlm_extract_batch_registry
.mosaic/rke/report_intelligence/macro_mimo_vlm_extract_smoke2_registry
.mosaic/rke/report_intelligence/macro_mimo_vlm_extract_batch_03a_registry
.mosaic/rke/report_intelligence/macro_mimo_vlm_extract_batch_03b_registry
.mosaic/rke/report_intelligence/macro_mimo_vlm_extract_batch_03c_registry
```

Aggregate result:

- Run ids:
  `RIR-20260615T005011+0000`, `RIR-20260615T012448+0000`,
  `RIR-20260615T024802+0000`, `RIR-20260615T025541+0000`,
  `RIR-20260615T030129+0000`
- Unique source ids: `16`
- Selected reports: `16`
- PDF ready: `16`
- Markdown ready: `16`
- Markdown backend counts: `vlm-auto-engine=16`
- Markdown status counts: `cached=16`
- Markdown quality gate counts: `passed=16`
- LLM processed reports: `16`
- LLM status counts: `processed=16`
- LLM model counts: `mimo-v2.5-pro=16`
- Forecast claim rows: `21`
- Analytical footprint rows: `50`
- Metric candidate rows: `241`
- Method pattern rows: `191`
- Analysis recipe rows: `191`
- Macro asset proxy eligible claim rows: `4`
- Macro asset proxy labelable window rows: `1`
- Macro asset proxy outcome label rows: `1`
- Macro asset proxy pending window rows: `15`
- Outcome label rows: `1`
- Tool coverage match rows: `241`
- Tool gap rows: `371`
- Data acquisition proposal rows: `366`
- Tool design proposal rows: `366`
- Runtime tool gap observation rows: `371`
- Prompt mutation candidate rows: `53`
- Blockers: `0`
- Private extraction outputs under all five registry directories are gitignored
  and must not be committed.

Operational note: in restricted Codex/sandbox runs, set
`UV_CACHE_DIR=~/tmp/mosaic-rke/uv-cache` along with `TMPDIR=~/tmp/mosaic-rke` so `uv` does
not try to write under the home-level cache directory. Keep Mimo extraction
batches small, typically 2-3 reports after the initial 5-report smoke, because
some reports split into two chunks and can wait on the model endpoint for
several minutes.

Batch smoke:

```bash
TMPDIR=~/tmp/mosaic-rke uv run mosaic-rke report-intelligence \
  --root . \
  --env-file .env \
  --source-path registry/sources/local_macro_strategy_reports.jsonl \
  --cache-dir .mosaic/rke/report_intelligence \
  --registry-dir .mosaic/rke/report_intelligence/macro_mimo_vlm_extract_batch_registry \
  --source-id SRC-LMSR-20260609-1f86ed80b00a4cf1 \
  --source-id SRC-LMSR-20250320-9f1ef5bbbe651e02 \
  --source-id SRC-LMSR-20260607-6f0accae6bdf3fc3 \
  --source-id SRC-LMSR-20260606-2f9bf1c00d3b5a58 \
  --source-id SRC-LMSR-20260527-f1b95cdfa63df9aa \
  --require-cached-markdown \
  --skip-download \
  --skip-convert \
  --limit 5 \
  --mineru-backend vlm-auto-engine \
  --vllm-timeout-seconds 300 \
  --max-chunks 2 \
  --chunk-chars 30000
```

Result:

- Run id: `RIR-20260615T005011+0000`
- Selected reports: `5`
- Markdown ready: `5`
- Markdown backend counts: `vlm-auto-engine=5`
- LLM processed reports: `5`
- LLM model counts: `mimo-v2.5-pro=5`
- Forecast claim rows: `4`
- Analytical footprint rows: `16`
- Metric candidate rows: `72`
- Method pattern rows: `61`
- Analysis recipe rows: `61`
- Macro asset proxy eligible claim rows: `1`
- Macro asset proxy pending window rows: `4`
- Tool coverage match rows: `72`
- Tool gap rows: `122`
- Data acquisition proposal rows: `121`
- Tool design proposal rows: `121`
- Blockers: `0`
- Private extraction outputs under
  `.mosaic/rke/report_intelligence/macro_mimo_vlm_extract_batch_registry/` are
  gitignored and must not be committed.

Single-report smoke:

```bash
TMPDIR=~/tmp/mosaic-rke uv run mosaic-rke report-intelligence \
  --root . \
  --env-file .env \
  --source-path registry/sources/local_macro_strategy_reports.jsonl \
  --cache-dir .mosaic/rke/report_intelligence \
  --registry-dir .mosaic/rke/report_intelligence/macro_mimo_vlm_extract_smoke_registry \
  --source-id SRC-LMSR-20260609-1f86ed80b00a4cf1 \
  --require-cached-markdown \
  --skip-download \
  --skip-convert \
  --limit 1 \
  --mineru-backend vlm-auto-engine \
  --vllm-timeout-seconds 300 \
  --max-chunks 2 \
  --chunk-chars 30000
```

Result:

- Run id: `RIR-20260615T004657+0000`
- Source id: `SRC-LMSR-20260609-1f86ed80b00a4cf1`
- Markdown status: `cached`
- Markdown backend recorded in status: `vlm-auto-engine`
- Markdown quality gate: `passed`
- LLM status: `processed`
- LLM model: `mimo-v2.5-pro`
- Selected reports: `1`
- LLM processed reports: `1`
- Forecast claim rows: `2`
- Analytical footprint rows: `2`
- Metric candidate rows: `14`
- Method pattern rows: `7`
- Analysis recipe rows: `7`
- Tool coverage match rows: `14`
- Tool gap rows: `17`
- Data acquisition proposal rows: `16`
- Tool design proposal rows: `16`
- Blockers: `0`
- Private extraction outputs under
  `.mosaic/rke/report_intelligence/macro_mimo_vlm_extract_smoke_registry/` are
  gitignored and must not be committed.

Last completed VLM batch:

```bash
TMPDIR=~/tmp/mosaic-rke uv run mosaic-rke report-intelligence \
  --root . \
  --env-file .env \
  --source-path registry/sources/local_macro_strategy_reports.jsonl \
  --cache-dir .mosaic/rke/report_intelligence \
  --registry-dir .mosaic/rke/report_intelligence/macro_vlm_batch_registry \
  --selection-order stratified \
  --limit 20 \
  --mineru-command .venv/bin/mineru \
  --mineru-backend vlm-auto-engine \
  --mineru-timeout-seconds 3600 \
  --mineru-batch-size 1 \
  --mineru-batch-max-bytes 8000000 \
  --skip-llm \
  --overwrite
```

Result:

- Run id: `RIR-20260615T003006+0000`
- Selected reports: `20`
- PDF ready: `20`
- Markdown ready: `17`
- Blockers: `3`
- MinerU backend counts: `vlm-auto-engine=20`
- Markdown status counts: `converted=17`, `blocked=3`
- Markdown quality gate counts: `passed=16`, `blocked=4`
- Markdown blocker counts: `mineru_failed=3`
- Markdown quality gap counts: `mineru_failed=3`, `markdown_repeated_line_noise=1`
- Failed source ids:
  `SRC-LMSR-20260601-040294df2a6c0516`,
  `SRC-LMSR-20260608-cff15a9da6922e9e`,
  `SRC-LMSR-20260527-cfa0ef514483ee80`
- Quality-gap source id:
  `SRC-LMSR-20260605-f265329a148fd695`
- Private outputs under `.mosaic/rke/report_intelligence/macro_vlm_batch_registry/`
  are gitignored and must not be committed.

Last completed vLLM/VLM smoke:

```bash
TMPDIR=~/tmp/mosaic-rke uv run mosaic-rke report-intelligence \
  --root . \
  --env-file .env \
  --source-path registry/sources/local_macro_strategy_reports.jsonl \
  --cache-dir .mosaic/rke/report_intelligence \
  --registry-dir .mosaic/rke/report_intelligence/macro_vlm_smoke_registry \
  --selection-order oldest \
  --limit 1 \
  --mineru-command .venv/bin/mineru \
  --mineru-backend vlm-auto-engine \
  --mineru-timeout-seconds 3600 \
  --skip-llm \
  --overwrite
```

Result:

- Run id: `RIR-20260615T002746+0000`
- Selected reports: `1`
- PDF ready: `1`
- Markdown ready: `1`
- Blockers: `0`
- Processing status: `markdown_status=converted`
- MinerU backend: `vlm-auto-engine`
- Markdown quality gate: `passed`
- Markdown duration: `35.921s`

Last completed smoke run used `hybrid-auto-engine` before the vLLM-only
requirement was clarified:

```bash
TMPDIR=~/tmp/mosaic-rke uv run mosaic-rke report-intelligence \
  --root . \
  --env-file .env \
  --source-path registry/sources/local_macro_strategy_reports.jsonl \
  --cache-dir .mosaic/rke/report_intelligence \
  --registry-dir .mosaic/rke/report_intelligence/macro_smoke_registry \
  --selection-order oldest \
  --limit 1 \
  --mineru-command .venv/bin/mineru \
  --mineru-backend hybrid-auto-engine \
  --mineru-timeout-seconds 3600 \
  --skip-llm \
  --overwrite
```

Result:

- Run id: `RIR-20260615T001026+0000`
- Selected reports: `1`
- PDF ready: `1`
- Markdown ready: `1`
- Blockers: `0`
- Processing status: `markdown_status=converted`
- MinerU backend: `hybrid-auto-engine`
- Markdown quality gate: `passed`
- Markdown duration: `38.468s`

This confirms that the existing MinerU environment can convert a local macro PDF
to Markdown. It does not replace the current requirement to use
`vlm-auto-engine` for the next macro/strategy batches. The output registry was
written under `.mosaic/` and is private.

## Resume Sequence

For the next macro run, use the existing source and runtime:

1. Inspect the local source count if needed:

```bash
wc -l registry/sources/local_macro_strategy_reports.jsonl
```

2. Run a small VLM Markdown conversion batch without LLM:

```bash
TMPDIR=~/tmp/mosaic-rke uv run mosaic-rke report-intelligence \
  --root . \
  --env-file .env \
  --source-path registry/sources/local_macro_strategy_reports.jsonl \
  --cache-dir .mosaic/rke/report_intelligence \
  --registry-dir .mosaic/rke/report_intelligence/macro_vlm_batch_registry \
  --selection-order stratified \
  --limit 20 \
  --mineru-command .venv/bin/mineru \
  --mineru-backend vlm-auto-engine \
  --mineru-timeout-seconds 3600 \
  --mineru-batch-size 1 \
  --skip-llm
```

3. Only after Markdown quality is acceptable, start or verify the vLLM service
   and run LLM extraction with the configured `.env` model.

4. Recompute derived public artifacts with `--refresh-derived-only` after
   private extraction outputs exist.

## Operation Log

- `2026-06-15`: Added local macro source support and built private source rows
  from `/home/hap/Downloads/yanbaoke/宏观策略`; 788 PDFs found.
- `2026-06-15`: Documented that MinerU/vLLM are already configured locally and
  should be reused before reinstalling.
- `2026-06-15`: Fixed MinerU command resolution so relative commands such as
  `.venv/bin/mineru` are resolved before subprocess working-directory changes.
- `2026-06-15`: Ran MinerU smoke on one macro PDF with
  `hybrid-auto-engine`; conversion passed with no blockers.
- `2026-06-15`: Updated the required MinerU mode to `vlm-auto-engine`, then ran
  one macro PDF VLM smoke; conversion passed with no blockers.
- `2026-06-15`: Clarified local MinerU `vlm-auto-engine` versus Docker-backed
  HTTP client modes, then ran a 20-PDF local VLM batch; 17 converted, 16 passed
  quality gates, 3 failed in MinerU, and 1 converted output was blocked by
  repeated-line noise.
- `2026-06-15`: Ran one cached-VLM-Markdown Mimo extraction smoke using
  `mimo-v2.5-pro`; extraction processed successfully with 2 forecast claims, 2
  analytical footprints, 7 method patterns, and no blockers.
- `2026-06-15`: Ran a 5-report cached-VLM-Markdown Mimo extraction batch using
  `mimo-v2.5-pro`; all 5 reports processed with no blockers, producing 4
  forecast claims, 16 analytical footprints, and 61 method patterns.
- `2026-06-15`: Extended cached-VLM-Markdown Mimo extraction to all 16
  quality-passed VLM Markdown reports by merging 5+2+3+3+3 serial small-batch
  runs; all 16 processed with no blockers, producing 21 forecast claims, 50
  analytical footprints, and 191 method patterns.
- `2026-06-16`: Filled the current gold-review evidence Markdown gap by running
  MinerU `vlm-auto-engine` on 14 cached Tushare PDFs in a private staging
  registry with `--skip-llm`; all 14 were Markdown-ready and the refreshed
  private gold evidence batch now has 0 missing Markdown rows.
