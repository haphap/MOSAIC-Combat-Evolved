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
- Required MinerU API/deployment backend env for that VLM path:
  `MINERU_BACKEND=vlm-vllm-engine`
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

The macro strategy source registry is built from actual PDFs under the local
Yanbaoke root:

```text
/home/hap/Downloads/yanbaoke
```

Do not rely on `文件清单.txt`; it is incomplete. Scan the root recursively for
`*.pdf` so newly added macro-adjacent folders such as `其他债券研究`,
`汇率研究`/`外汇研究`, `全球策略`, and `国际宏观评论` are included in the same
private source registry. FX directory or filename signals (`汇率`, `外汇`, `人民币`,
`美元`, `USD/CNY`, `USDCNY`, `美元指数`) classify as `宏观策略-汇率`, not as the
commodity/futures bucket.

Current private source outputs:

```text
registry/sources/local_macro_strategy_reports.jsonl
registry/sources/local_macro_strategy_reports.manifest.json
```

Both paths are gitignored and must remain private.

## GitHub Registry Boundary

Do not commit the full Report Intelligence runtime database to GitHub. The
`registry/report_intelligence/` surface is local-only. Do not commit compact
catalogs, readiness gates, aggregate audit summaries, feature flags, or any other
Report Intelligence derived report. Treat redacted summaries as local generated
outputs too.

Keep these classes local/gitignored:

- compact catalogs, readiness gates, feature flags, and aggregate audit
  summaries;
- extracted claim, footprint, metadata, review-aid, and outcome-label files;
- recipe/method/tool-gap/metric-candidate detail JSONL files;
- macro, stock, and industry context snapshot detail exports, plus macro agent
  research-prior detail exports;
- audit, monitor, gap-distribution, prompt-mutation, and paper-trading history
  JSONL files.

If downstream macro or investment agents need one of these views, consume it
from the local registry. Do not re-add Report Intelligence artifacts to
`REQUIRED_REGISTRY_FILES`.

## Private Registry Repo

The private registry repo is the source of truth for report-intelligence
JSON/JSONL artifacts. Do not record its real remote URL, access token, licensed
source content, or operator-specific local paths in this public runbook.
MOSAIC-RKE does not auto-clone or auto-pull that repo at runtime. Operators
clone, pull, commit, and push it explicitly so a batch run cannot change its
de-duplication baseline in the middle of processing.

First setup on a machine:

```bash
git clone <private-registry-remote> <private-registry-checkout>
export MOSAIC_REGISTRIES_REPO=<private-registry-checkout>
```

Before formal extraction, batch merge, agent context export, or remote
processing:

```bash
cd <private-registry-checkout>
git pull --ff-only
cd <mosaic-rke-checkout>
mosaic-rke registries-preflight --root .
```

After generating or merging private registry outputs:

```bash
mosaic-rke export-private-registries --root . --output-dir <private-registry-checkout>
cd <private-registry-checkout>
git status
git add registry registry_manifest.json
git commit -m "sync report intelligence registries"
git push
```

Use `MOSAIC_REGISTRY_DIR=<private-registry-checkout>/registry/report_intelligence`
only when the registry directory is not under the standard repo layout. Explicit
CLI/RPC `--registry-dir` or `registry_dir` still wins over both environment
variables.

Last source build:

- Command:

```bash
uv run mosaic-rke build-local-macro-report-sources \
  --root . \
  --input-dir /home/hap/Downloads/yanbaoke
```

- Scanned PDF count: `1967`
- Written source rows: `1967`
- Date range: `2017-10-15` to `2026-06-21`
- Report type counts:
  `宏观策略=1014`, `宏观策略-A股=27`, `宏观策略-债券=274`,
  `宏观策略-商品=68`, `宏观策略-大类资产=94`, `宏观策略-汇率=218`,
  `宏观策略-海外=233`, `宏观策略-待分类=39`

## Macro Series Backfill

RKE report-intelligence reads macro time series from the local scorecard
`macro_series` table; it does not commit raw market observations. The local DB
path used in this checkout is:

```text
data/scorecard.db
```

This path is gitignored and must remain private/local. After adding or refreshing
macro observations, rebuild derived report-intelligence artifacts with:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m mosaic.rke.cli report-intelligence \
  --root . \
  --refresh-derived-only \
  --scorecard-db-path data/scorecard.db
```

Volatility/VIX status:

- `2026-06-22`: AKShare/Oxford Man VIX endpoint failed with an SSL EOF both
  inside and outside the sandbox, so it is not a sandbox permission issue.
- VIX backfill now uses the existing `mosaic.dataflows.macro_data.get_ivx`
  yfinance adapter with instrument `^VIX`.
- Successful command:

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m mosaic.rke.cli macro-series-backfill \
  --root . \
  --start-date 2025-01-01 \
  --end-date 2026-06-18 \
  --series-id VIX \
  --scorecard-db-path data/scorecard.db
```

Observed result: `accepted=true`, `fetched_rows=367`, `inserted_rows=367`.
After the derived refresh, `macro_market_series_catalog.jsonl` marks `VIX` as
`ready` with observations through `2026-06-18`. Current public macro outcome
labels still have no completed real volatility leg because the present claim
pool has no clear labelable volatility claim; this is a corpus/extraction gap,
not a VIX data gap.

## MinerU Usage

User requirement: run MinerU in vLLM/VLM mode. For the current installed MinerU
CLI, pass `vlm-auto-engine` as `-b/--backend` for PDF to Markdown conversion,
not `pipeline`, and not `hybrid-auto-engine` for the normal macro/strategy batch
path. Also set `MINERU_BACKEND=vlm-vllm-engine` in the MinerU subprocess
environment. Recent MinerU documentation names the API/deployment backend
`vlm-vllm-engine`; older/internal code paths may refer to the async engine as
`vllm-async-engine`.

Mode distinction:

- `vlm-auto-engine` is the CLI backend accepted by the installed MinerU command
  for local VLM conversion. RKE injects `MINERU_BACKEND=vlm-vllm-engine` when it
  launches this backend so MinerU's API/deployment layer uses the local vLLM
  engine. Do not pass `vlm-vllm-engine` directly to `mineru -b` unless
  `.venv/bin/mineru --help` shows it as a supported CLI choice.
- `vlm-http-client` and `hybrid-http-client` are MinerU HTTP-client modes. These
  require a compatible server URL via `--mineru-server-url` / MinerU `-u`, for
  example `http://127.0.0.1:30000`. Start and health-check the Docker vLLM
  service before using either HTTP-client backend.
- The RKE extraction LLM endpoint on port `8020` is separate from MinerU local
  VLM conversion. Do not infer that Docker vLLM is running just because
  `vlm-auto-engine` succeeds.

Preferred smoke command:

```bash
MINERU_BACKEND=vlm-vllm-engine TMPDIR=~/tmp/mosaic-rke \
  uv run mosaic-rke report-intelligence \
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
MINERU_BACKEND=vlm-vllm-engine TMPDIR=~/tmp/mosaic-rke \
  uv run mosaic-rke report-intelligence \
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
MINERU_BACKEND=vlm-vllm-engine \
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
  --mineru-command .venv/bin/mineru \
  --mineru-backend vlm-auto-engine \
  --mineru-timeout-seconds 3600 \
  --mineru-batch-size 80 \
  --mineru-batch-max-bytes 200000000
```

Use this no-`--skip-download` pattern for fresh local source batches so
`local_pdf_path` is materialized into the cache before MinerU conversion. Use
`--skip-download --skip-convert --require-cached-markdown` only for the
subsequent LLM-only shard pass after Markdown is already cached.

## Local Qwen LLM Extraction

Use the existing local Docker vLLM service for cached-Markdown extraction before
testing another local endpoint. Do not rerun a smoke test just to rediscover the
same parameters unless the container, model id, vLLM version, or RKE extraction
flags have changed.

Validated local service:

- Container: `rke-vllm-qwen36-27b-160k-20260610`
- Base URL: `http://127.0.0.1:8020/v1`
- Model id: `Qwen3.6-27B-heretic-int4-AutoRound`
- Health/model check: `curl -sS http://127.0.0.1:8020/v1/models`
- Managed-sandbox note: if localhost access fails inside the sandbox while
  `ss -ltnp` shows `0.0.0.0:8020` listening, rerun the curl/RKE command with
  host-network permission instead of changing model parameters.

NVIDIA Qwen3.6 27B NVFP4 sndr service:

- Use this service when the user explicitly requests the NVIDIA 27B NVFP4
  preset. The validated RKE extraction command above still points to the older
  `rke-vllm-qwen36-27b-160k-20260610` service on port `8020` unless that command
  is changed deliberately.
- Preset: `nvidia-qwen3.6-27b-nvfp4-5090`.
- Container: `vllm-qwen3.6-27b-nvfp4-5090-5090d`.
- Base URL: `http://127.0.0.1:8000`.
- Chat endpoint: `/v1/chat/completions`.
- Served model: `qwen3.6-27b-nvfp4`.
- Auth header: `Authorization: Bearer genesis-local`.
- HF snapshot:
  `/models/models--nvidia--Qwen3.6-27B-NVFP4/snapshots/0893e1606ff3d5f97a441f405d5fc541a6bdf404`.
- Current runtime envelope from `sndr launch --dry-run --skip-autodetect`
  after the 2026-07-08 benchmark update: `--tensor-parallel-size 1`,
  `--gpu-memory-utilization 0.85`, `--max-model-len 130000`,
  `--max-num-seqs 1`, `--max-num-batched-tokens 2048`, `--dtype bfloat16`,
  `--kv-cache-dtype turboquant_4bit_nc`,
  `--speculative-config '{"method": "mtp", "num_speculative_tokens": 3}'`,
  `--enable-chunked-prefill`, `--disable-custom-all-reduce`,
  `--language-model-only`, `--trust-remote-code`, and
  `--enable-auto-tool-choice`.
- This service shares port `8000` with the 35B NVFP4 sndr service. Run only one
  of them at a time.

Current 2026-07-08 sndr direct-launch presets:

- `nvidia-qwen3.6-35b-a3b-nvfp4-5090`: keep at `max_model_len=140000`,
  `--kv-cache-dtype turboquant_4bit_nc`, `--max-num-batched-tokens 2048`, and
  MTP K=3. The 140K fixed benchmark completed; 150K was not promoted because
  the observed headroom was thin.
- `nvidia-qwen3.6-27b-nvfp4-5090`: use `max_model_len=130000`,
  `--kv-cache-dtype turboquant_4bit_nc`, `--max-num-batched-tokens 2048`, and
  MTP K=3. The 140K run completed, but 130K was materially faster and left more
  VRAM headroom.
- `local-qwen3.6-27b-heretic-int4-5090`: use `max_model_len=140000`,
  `--kv-cache-dtype turboquant_4bit_nc`, `--max-num-batched-tokens 2048`, and
  MTP K=3. The 130K run did not materially improve speed over 140K, so the
  larger validated context is preferred.
- These are local sndr preset/profile updates under `/home/hap/.sndr`. Do not
  commit sndr files into this repository. Benchmark evidence files under
  `.mosaic/rke/all_agent_evolution/fixed_episode_benchmark/` are private
  generated evidence and must not be committed.

2026-07-06 27B fixed-benchmark k8v4/MTP probe:

- User constraint: keep MTP enabled, run only one vLLM at a time, and use local
  model snapshots only.
- Direct `sndr launch nvidia-qwen3.6-27b-nvfp4-5090` renders the normal 27B
  envelope with `--kv-cache-dtype auto`. For this probe the container was
  manually recreated from the same local snapshot/image so the only benchmark
  variable was the long-context KV path: `--kv-cache-dtype turboquant_k8v4`.
- Working 110K envelope on the 5090 host:
  `--max-model-len 110000`, `--max-num-seqs 1`,
  `--max-num-batched-tokens 2048`, `--gpu-memory-utilization 0.77`,
  `--kv-cache-dtype turboquant_k8v4`,
  `--speculative-config.method mtp`,
  `--speculative-config.num_speculative_tokens 3`,
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:256,garbage_collection_threshold:0.85`,
  `GENESIS_ENABLE_PN119=1`, `GENESIS_ENABLE_PN8_MTP_DRAFT_ONLINE_QUANT=1`,
  and `GENESIS_ENABLE_P40=1`.
- Failed envelopes:
  `120000` + k8v4 failed on the fixed-benchmark `china` long prompt with
  Genesis P38 TQ continuation workspace OOM; `110000` + k8v4 at
  `gpu-memory-utilization` `0.85` failed the same way; `0.80` avoided that
  P38 OOM but still killed EngineCore on a compiled `marlin_gemm` /
  `aten::empty` allocation during the same long prompt; `0.75` did not start
  because only about `3.1 GiB` KV cache was available versus `3.37 GiB`
  required for `110000`.
- Passing probe:
  `rke-fixed-benchmark --benchmark-run-id goal-probe-110k-real-20260618-512
  --model-config local_qwen_27b --as-of-date 2025-09-01 --max-tokens 1024`
  completed all 25 agents with the `0.77` k8v4/MTP envelope. The paired output
  count moved from `50` to `75`, adding `25` `local_qwen_27b` rows for
  `2025-09-01`.
- Evidence caveat: this was a stability/ctx probe, not a formal delivery gate
  pass. The full fixed-benchmark gate still requires the manifest's full
  episode/date/model matrix, independent review, and downstream evidence.

2026-07-06 27B AutoRound INT4 sndr preset smoke:

- Preset used exactly as configured: `local-qwen3.6-27b-heretic-int4-5090`.
  It renders `--kv-cache-dtype fp8_e5m2`, MTP K=3, `--max-model-len 120000`,
  `--max-num-seqs 1`, `--max-num-batched-tokens 4096`, and served model
  `qwen3.6-27b-heretic-int4`.
- Startup result: `sndr launch local-qwen3.6-27b-heretic-int4-5090
  --skip-autodetect` reached `/v1/models` on `http://127.0.0.1:8000/v1` with
  the local Heretic v2 AutoRound snapshot.
- Smoke result: `/v1/completions` returned a normal completion containing
  `OK`; `/v1/chat/completions` returned tokens in the `reasoning` field first,
  so short chat smokes can show `content: null` unless thinking is disabled or
  the token budget is large enough.
- Runtime note: loaded service used about `31.3 GiB` of the 5090 D's `32 GiB`
  VRAM. Keep only one vLLM service running on this host.

2026-07-06 27B AutoRound INT4 k8v4 130K agent-loop probe:

- Follow-up probe used the same local Heretic v2 AutoRound snapshot and kept
  MTP enabled at K=3. The tested runtime changed the KV/cache envelope to
  `--kv-cache-dtype turboquant_k8v4`, `--max-model-len 130000`,
  `--max-num-seqs 1`, `--max-num-batched-tokens 2048`, and
  `--gpu-memory-utilization 0.85`.
- Startup and smoke: `/v1/models` reported served model
  `qwen3.6-27b-heretic-int4` with `max_model_len=130000`, and
  `/v1/completions` returned `OK`.
- Agent-loop run:
  `rke-fixed-benchmark --benchmark-run-id goal-probe-27b-heretic-k8v4-130k-agent-loop-20260706
  --model-config local_qwen_27b --as-of-date 2025-09-01 --max-runs 1
  --max-tokens 512` completed all agent stages and then stopped at the fixed
  benchmark preflight gates: incomplete covered dates/episodes/model outputs,
  manual review not approved, and paired output count below the manifest
  requirement. This is not a vLLM, CUDA, or k8v4 failure.
- Observed runtime: the k8v4 service used about `27.6 GiB` for
  `VLLM::EngineCore` and about `29.1 GiB` total GPU memory during the agent
  loop, lower than the fp8 120K preset smoke. Logs showed successful
  `/v1/chat/completions` traffic; the notable warnings were PN59 short-sequence
  bypasses, grammar matcher warnings, external data-source disconnects, and
  expected structured-output fallback when `--max-tokens 512` truncated output.
- Preset update: `local-qwen3.6-27b-heretic-int4-5090` now points at a local
  profile that renders the validated k8v4 130K envelope above while preserving
  MTP K=3. The shared RTX 5090 D hardware defaults were left unchanged so
  sibling 35B/NVFP4 presets do not inherit this 27B-specific sizing.

2026-07-06 fixed-benchmark metrics retest:

- Benchmark runner metrics are written locally under
  `.mosaic/rke/all_agent_evolution/fixed_episode_benchmark/<run>.metrics.jsonl`.
  These files are private generated evidence and must not be committed. They
  record no prompt or response bodies.
- Metrics fields include actual LLM provider/model/base URL, expected and
  emitted agent-output counts, content-generation success rate, per-agent
  status, structured/fallback counts, tool call counts by name, tool failure
  count, full agent elapsed time, observed prompt/completion tokens, observed
  LLM wait time, and observed completion tokens/second. Success rate is
  `agent_done_count / expected_agent_count`; `output_agent_count` remains the
  separate output coverage counter. Token speed covers LLM calls that expose
  usage metadata; full content-generation wall time is tracked separately with
  `agent_elapsed_ms_total`.
- `bench-27b-heretic-k8v4-130k-metrics-20260706`: local Heretic AutoRound INT4
  27B, k8v4, MTP K=3, `max_model_len=130000`, `--max-tokens 1024`. Result:
  output coverage `25/25`, content success `25/25`, structured `25`, fallback
  `0`, timeouts `0`, tool calls `191`, tool failures `9`, prompt tokens
  `1472920`, completion tokens `35945`, observed LLM wait `744574 ms`, observed
  completion speed `48.28 tok/s`, full agent elapsed `1047900 ms`. Top tools were
  `get_rke_research_context=49`, `get_indicators=24`, `get_fred_series=20`,
  `get_stock_data=18`, and `get_fundamentals=15`.
- `bench-27b-nvfp4-k8v4-110k-metrics-20260706`: NVIDIA 27B NVFP4, k8v4, MTP
  K=3, `max_model_len=110000`, `--max-tokens 1024`. Minimal turboquant env
  failed startup with about `1.47 GiB` available KV cache versus `3.37 GiB`
  required; the fuller Genesis TQ env started and `/v1/models` confirmed
  `max_model_len=110000`. Result: output coverage `25/25`, content success
  `21/25`, structured `21`, fallback `0`, timeouts `4`
  (`L2:biotech`, `L2:industrials`, `L2:semiconductor`, `L3:burry`), tool calls
  `133`, tool failures `2`, prompt tokens `1092261`, completion tokens `25420`,
  observed LLM wait `701239 ms`, observed completion speed `36.25 tok/s`, full
  agent elapsed `2102500 ms`. Top tools were `get_rke_research_context=41`,
  `get_indicators=39`,
  `get_stock_data=26`, `get_fundamentals=19`, and `get_fred_series=9`.
- `bench-35b-nvfp4-120k-metrics-512-20260706`: NVIDIA 35B A3B NVFP4, auto KV,
  MTP K=3, `max_model_len=120000`, `--max-tokens 512`. The first `--max-tokens
  1024` attempt failed before generation on the long `geopolitical` prompt:
  the request needed at least `118977 + 1024 = 120001` tokens, above the
  declared `120000` context. The 512-token rerun completed. Result: output
  coverage `25/25`, content success `25/25`, structured `25`, fallback `0`,
  timeouts `0`, tool calls `228`, tool failures `5`, prompt tokens `2232353`,
  completion tokens `30957`, observed LLM wait `337074 ms`, observed completion
  speed `91.84 tok/s`, full agent elapsed `667500 ms`. Top tools were
  `get_rke_research_context=83`,
  `get_indicators=38`, `get_fred_series=22`, `get_fundamentals=21`, and
  `get_stock_data=17`.
- Current read: Heretic AutoRound INT4 27B + k8v4 is the only 27B variant that
  completed all 25 agents at a context above 120K in this benchmark. NVIDIA 27B
  NVFP4 + k8v4 can start and run at 110K with the fuller TQ env, but the
  observed agent-loop success rate and generation speed were worse. NVIDIA 35B
  A3B NVFP4 + auto KV remains the strongest of the three on this workload when
  the per-call output cap is kept below the 120K boundary.

2026-07-06 replay-pruned 130K fixed-benchmark retest:

- Code change under test: the agent loop no longer replays every prior
  `ToolMessage` on every subsequent LLM call. After a tool-call turn has been
  consumed by the next model call, the replay window drops the old assistant
  tool-call message and its tool replies. The full local transcript is still
  retained for debugging. This addresses the earlier prompt-token growth where
  each call replayed all prior tool outputs.
- Tool-output length cap: disabled by default. The default
  `MOSAIC_AGENT_TOOL_OUTPUT_MAX_CHARS` behavior is now unlimited; setting the
  env var to a positive integer explicitly enables truncation, and
  `off`/`none`/`false` also means unlimited. The previous 4K default cap is not
  used for benchmark comparison because it changes the content seen by the
  model.
- Timeout controls used for these runs:
  `MOSAIC_BRIDGE_TIMEOUT_MS=300000`,
  `MOSAIC_AGENT_TIMEOUT_SECONDS=600`, and benchmark `--max-tokens 2048`.
  The bridge default remains 60 seconds when the env var is unset.
- `bench-27b-nvfp4-k8v4-130k-mt1536-bt300-t600-replayprune-20260706`:
  NVIDIA 27B NVFP4, k8v4, MTP K=3, `max_model_len=130000`,
  `--max-num-batched-tokens 1536`. The same model at batched tokens `2048`
  hit a Genesis P38 TQ continuation workspace OOM on the first benchmark
  request. At `1536`, result was output coverage `25/25`, content success
  `25/25`, structured `25`, fallback `0`, timeouts `0`, tool calls `270`,
  tool failures `1`, prompt tokens `858593`, completion tokens `39461`,
  observed LLM wait `543444 ms`, observed completion speed `72.61 tok/s`, and
  full agent elapsed `789800 ms`. Top tools were
  `get_rke_research_context=47`, `get_fundamentals=37`,
  `get_stock_data=22`, `get_industry_policy=13`, and
  `get_industry_moneyflow=11`.
- `bench-35b-nvfp4-k8v4-130k-mt1536-bt300-t600-replayprune-agg-20260706`:
  NVIDIA 35B A3B NVFP4, k8v4, MTP K=3, `max_model_len=130000`,
  `--max-num-batched-tokens 1536`. Result was output coverage `25/25`,
  content success `25/25`, structured `24`, fallback `1`, timeouts `0`, tool
  calls `231`, tool failures `3`, prompt tokens `856571`, completion tokens
  `40003`, observed LLM wait `184435 ms`, observed completion speed
  `216.89 tok/s`, and full agent elapsed `527300 ms`. Top tools were
  `get_rke_research_context=77`, `get_fundamentals=39`,
  `get_fred_series=20`, `get_industry_moneyflow=16`, and
  `get_stock_data=13`.
- `bench-27b-heretic-k8v4-130k-mt2048-bt300-t600-replayprune-agg-20260706`:
  local Heretic AutoRound INT4 27B, k8v4, MTP K=3,
  `max_model_len=130000`, `--max-num-batched-tokens 2048`. Result was output
  coverage `25/25`, content success `25/25`, structured `25`, fallback `0`,
  timeouts `0`, tool calls `214`, tool failures `7`, prompt tokens `813810`,
  completion tokens `38881`, observed LLM wait `510002 ms`, observed
  completion speed `76.24 tok/s`, and full agent elapsed `698100 ms`. Top
  tools were `get_rke_research_context=63`, `get_fred_series=24`,
  `get_industry_moneyflow=17`, `get_broker_research=12`, and
  `get_stock_data=12`. Repeated graph executions were observed and are now
  accumulated in metrics: `L4:alpha_discovery`, `L4:autonomous_execution`, and
  `L4:cio` each ran twice.
- Current read after replay pruning: all three local models can complete this
  one-date, 25-agent fixed benchmark at 130K with k8v4 when batch sizing is
  adjusted. The 35B A3B NVFP4 model is still the fastest by a wide margin. The
  27B NVIDIA NVFP4 model no longer fails from replay-driven prompt growth, but
  needs a smaller batched-token envelope than the 27B Heretic INT4 model. The
  35B result is plausible despite larger weights because its MoE/GQA runtime
  KV profile is more favorable than the dense 27B NVFP4 path on this workload.
  Remaining failures are mostly external tool/data-source issues, especially
  AkShare/stdout pollution and realized-volatility fetch errors, not vLLM
  context failures.

2026-07-08 TurboQuant 4bit NC fixed-benchmark retest:

- Common test envelope: one vLLM at a time, local model snapshots only,
  MTP enabled at K=3, `--kv-cache-dtype turboquant_4bit_nc`,
  `--max-num-batched-tokens 2048`, benchmark `--max-tokens 2048`,
  `MOSAIC_AGENT_TIMEOUT_SECONDS=600`, `MOSAIC_BRIDGE_TIMEOUT_MS=300000`, and
  no tool-output truncation (`MOSAIC_AGENT_TOOL_OUTPUT_MAX_CHARS=off`).
- The benchmark used a temporary clean prompt repo snapshot derived from the
  current private prompt working tree so prompt provenance preflight could run
  without committing private prompt changes. Do not treat that temporary repo as
  a public artifact.
- `bench-35b-nvfp4-tq4nc-140k-bt2048-mt2048-mosaic-20260708-r1`: NVIDIA 35B
  A3B NVFP4, `max_model_len=140000`, MTP K=3. Result: output coverage `25/25`,
  content success `25/25`, structured `25`, fallback `0`, tool calls `192`,
  tool cache hits `22`, tool failures `3`, prompt tokens `1407160`,
  completion tokens `39096`, observed completion speed `156.8451 tok/s`, and
  full agent elapsed `344600 ms`.
- `bench-27b-nvfp4-tq4nc-140k-bt2048-mt2048-mosaic-20260708-r1`: NVIDIA 27B
  NVFP4, `max_model_len=140000`, MTP K=3. Result: output coverage `25/25`,
  content success `25/25`, structured `25`, fallback `0`, tool calls `193`,
  tool cache hits `14`, tool failures `2`, prompt tokens `1365993`,
  completion tokens `31700`, observed completion speed `32.1618 tok/s`, and
  full agent elapsed `1160700 ms`. The run completed but was tight: the service
  reached about `31.7 GiB` used on a `32 GiB` 5090 D, and `L2:biotech` took
  `308000 ms` with `215841` prompt tokens.
- `bench-27b-nvfp4-tq4nc-130k-bt2048-mt2048-mosaic-20260708-r1`: NVIDIA 27B
  NVFP4, `max_model_len=130000`, MTP K=3. Result: output coverage `25/25`,
  content success `25/25`, structured `25`, fallback `0`, tool calls `170`,
  tool cache hits `9`, tool failures `1`, prompt tokens `1263304`,
  completion tokens `31887`, observed completion speed `38.6253 tok/s`, and
  full agent elapsed `944400 ms`. This is the promoted direct-launch envelope
  for the NVIDIA 27B preset because it is faster and has more headroom than the
  140K run.
- `bench-27b-heretic-int4-tq4nc-140k-bt2048-mt2048-mosaic-20260708-r1`: local
  Heretic AutoRound INT4 27B, `max_model_len=140000`, MTP K=3. Result: output
  coverage `25/25`, content success `25/25`, structured `25`, fallback `0`,
  tool calls `160`, tool cache hits `23`, tool failures `2`, prompt tokens
  `998019`, completion tokens `44156`, observed completion speed
  `66.8837 tok/s`, and full agent elapsed `793500 ms`.
- `bench-27b-heretic-int4-tq4nc-130k-bt2048-mt2048-mosaic-20260708-r1`: local
  Heretic AutoRound INT4 27B, `max_model_len=130000`, MTP K=3. Result: output
  coverage `25/25`, content success `25/25`, structured `25`, fallback `0`,
  tool calls `159`, tool cache hits `27`, tool failures `2`, prompt tokens
  `1041317`, completion tokens `42981`, observed completion speed
  `65.2116 tok/s`, and full agent elapsed `773400 ms`. Since the 130K run did
  not materially improve throughput over 140K, keep Heretic at 140K.
- Current read after TurboQuant 4bit NC retest: 35B NVFP4 remains fastest and
  should stay at 140K; NVIDIA 27B NVFP4 should use the conservative 130K
  profile; Heretic INT4 should use the 140K profile. NVIDIA 27B is slower than
  Heretic on this workload because the NVFP4 path on the current 5090 D/vLLM
  pin uses a weight-only Marlin FP4 path and because the NVIDIA 27B run took
  heavier L2/L3 evidence paths. Heretic is faster but still has a quality risk:
  some `munger`, `burry`, and `ackman` superinvestor outputs were very short,
  so do not infer quality superiority from throughput alone.
- MTP was not disabled in these runs. Launches preserved
  `--speculative-config '{"method": "mtp", "num_speculative_tokens": 3}'`, and
  vLLM logs included the expected speculative-decoding warnings.
- Observed failures in these runs were external tool/data-source failures
  (`AkShare` SSL/remote disconnects and occasional `Tushare` remote disconnects)
  rather than vLLM CUDA/OOM failures.

Single-owner startup flow:

- If the same-parameter container is already healthy, reuse it and skip startup:

  ```bash
  curl -s http://127.0.0.1:8000/health
  rtk docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  ```

- If the same-parameter container exists but is stopped, prefer restarting it:

  ```bash
  rtk docker ps -a \
    --filter name=vllm-qwen3.6-27b-nvfp4-5090-5090d \
    --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  rtk docker start vllm-qwen3.6-27b-nvfp4-5090-5090d
  ```

  This preserves the container definition and mounted host caches, but not GPU
  memory. The model still reloads and warms up after every stopped start.

- Rebuild the container only when no reusable container exists, the preset or
  runtime flags changed, the container is in an abnormal state, or a clean
  deterministic launch is required:

  ```bash
  rtk sndr down nvidia-qwen3.6-27b-nvfp4-5090 || true
  rtk docker rm -f vllm-qwen3.6-27b-nvfp4-5090-5090d 2>/dev/null || true
  rtk docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  rtk nvidia-smi --query-gpu=memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits
  rtk sndr launch nvidia-qwen3.6-27b-nvfp4-5090 --skip-autodetect
  ```

  `sndr launch` renders a conservative Docker script that removes any same-name
  container before creating a fresh one. Use `rtk docker start` when the goal is
  to reuse an unchanged stopped container.

Wait for readiness:

```bash
for i in {1..120}; do
  code=$(curl -s -o /tmp/sndr-health-27b.out -w "%{http_code}" \
    http://127.0.0.1:8000/health || true)
  if [ "$code" = 200 ]; then
    echo READY
    break
  fi
  if ! rtk docker ps --format "{{.Names}}" | \
    grep -qx vllm-qwen3.6-27b-nvfp4-5090-5090d; then
    echo EXITED
    rtk docker ps -a \
      --filter name=vllm-qwen3.6-27b-nvfp4-5090-5090d \
      --format "{{.Status}}"
    rtk docker logs --tail 200 vllm-qwen3.6-27b-nvfp4-5090-5090d
    exit 1
  fi
  sleep 5
done
```

Confirm the served model:

```bash
curl -sS \
  -H 'Authorization: Bearer genesis-local' \
  http://127.0.0.1:8000/v1/models
```

Default stop keeps the container available for same-parameter reuse:

```bash
rtk sndr down nvidia-qwen3.6-27b-nvfp4-5090 || true
rtk docker stop vllm-qwen3.6-27b-nvfp4-5090-5090d 2>/dev/null || true
rtk docker ps -a \
  --filter name=vllm-qwen3.6-27b-nvfp4-5090-5090d \
  --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
rtk nvidia-smi --query-gpu=memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits
```

Full cleanup only when rebuilding or recovering from abnormal state:

```bash
rtk docker rm -f vllm-qwen3.6-27b-nvfp4-5090-5090d 2>/dev/null || true
```

Removing the container does not remove host caches mounted from Hugging Face,
Triton, or vLLM torch compile cache directories. It only discards the container
definition and forces the next `sndr launch` to recreate it.

LLM-only shard command pattern:

```bash
PATH=/home/hap/Project/MOSAIC-RKE/.venv/bin:$PATH \
HOME=/home/hap/Project/MOSAIC-RKE/.mosaic/tmp/home \
UV_CACHE_DIR=/home/hap/Project/MOSAIC-RKE/.mosaic/tmp/uv-cache \
MOSAIC_RKE_TMPDIR=/home/hap/Project/MOSAIC-RKE/.mosaic/tmp \
TMPDIR=/home/hap/Project/MOSAIC-RKE/.mosaic/tmp \
.venv/bin/mosaic-rke report-intelligence \
  --root . \
  --source-path .mosaic/rke/report_intelligence_batches/<batch>/<domain>_llm_shards/<shard>.jsonl \
  --registry-dir .mosaic/rke/report_intelligence_batches/<batch>/<domain>_llm_registry/<part> \
  --exclude-processed-registry-dir registry/report_intelligence \
  --skip-download \
  --skip-convert \
  --require-cached-markdown \
  --vllm-base-url http://127.0.0.1:8020/v1 \
  --vllm-model Qwen3.6-27B-heretic-int4-AutoRound \
  --vllm-timeout-seconds 600 \
  --max-llm-output-tokens 2048
```

Operational guidance:

- Feed only source shards whose Markdown status passed quality gates. Do not put
  PDF download, MinerU conversion, or blocked Markdown rows into the LLM pass.
- Use `250` reports per shard as the verified stable batch size on this host.
  Use smaller shards, such as `100`, only when frequent checkpoints matter more
  than launch overhead.
- Do not add `--progress-jsonl` for large LLM-only shards unless debugging; it
  can produce very large terminal buffers.
- Keep each shard in its own private registry directory, then merge only clean
  shard registries. Retry transient blockers as one-source shards before merge.
- Stop MinerU VLM workloads before starting this extraction service; both share
  the same GPU.

2026-06-29 local Qwen validation:

- Input shape: one cached-Markdown stock shard with `250` reports.
- Command parameters: the exact base URL, model id, timeout, and token cap shown
  above.
- Result: `250/250` LLM-processed, `0` blockers, `166` forecast claims, `432`
  analytical footprints, and `165` stock-price-proxy eligible claims.
- Wall time: about `69` minutes for the serial RKE extraction loop. This is a
  stability validation, not a reason to retest every future batch.

2026-06-29 NVIDIA Qwen3.6 35B NVFP4 validation:

- Model: `nvidia/Qwen3.6-35B-A3B-NVFP4`
- Local snapshot:
  `/home/hap/Project/qwen36-27b-single-5090/models/hf-cache/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/491c2f1ea524c639598bf8fa787a93fed5a6fbce`
- Docker image: `bbac761a6be4`
- Validated container: `rke-vllm-qwen36-35b-a3b-nvfp4-patched8-20260629`
- Base URL: `http://127.0.0.1:8020/v1`
- Health/model check:
  `curl -sS http://127.0.0.1:8020/v1/models`
- Required vLLM serving parameters on the 5090 host:
  `--quantization modelopt_mixed`, `--dtype auto`,
  `--max-model-len 65536`, `--gpu-memory-utilization 0.85`,
  `--max-num-seqs 1`, `--max-num-batched-tokens 4128`,
  `--kv-cache-dtype fp8_e4m3`, `--enable-prefix-caching`,
  `--enable-chunked-prefill`, `--reasoning-parser qwen3`,
  `--enable-auto-tool-choice`, `--tool-call-parser qwen3_coder`, and the local
  `qwen3.5-enhanced.jinja` chat template.
- RKE extraction already sends
  `chat_template_kwargs: {"enable_thinking": false}`. Keep this for JSON
  extraction; without it, short requests may return only `reasoning` and no
  `content`.
- Required temporary compatibility patch for this pinned vLLM image:
  `.mosaic/tmp/patch_modelopt_mixed_qwen36_nvfp4.py`, launched via
  `.mosaic/tmp/start_qwen35_nvfp4_vllm.sh`.
  The patch fixes three local compatibility gaps: ModelOpt mixed quant-layer
  prefix lookup for Qwen3.6, `ParallelLMHead` receiving `quant_config`, and
  scalar NVFP4 `lm_head` scale loading in `VocabParallelEmbedding`.
- Known bad parameters or shortcuts:
  `--kv-cache-dtype nvfp4` is not supported by the selected attention backend;
  `--disable-log-requests` is not accepted by this vLLM image; skipping or
  tying `lm_head` weights is not a valid quality comparison because the
  checkpoint has an untied quantized `lm_head`.
- MTP speculative decoding check on 2026-06-29:
  `--speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'`
  is accepted by vLLM argument parsing and initializes `Qwen3_5MoeMTP`, but the
  engine fails while loading the drafter with
  `ValueError: There is no module or parameter named 'lm_head.input_scale' in
  Qwen3_5MoeMTP`. Do not use this MTP config for RKE extraction until the local
  NVFP4 compatibility patch also covers the MTP drafter `lm_head` scale path, or
  a validated upstream image fixes that loader path.
- Startup metrics from the validated run: checkpoint size `21.82 GiB`, weight
  loading `12.01 s`, model memory `20.35 GiB`, initial profile/warmup `43.20 s`,
  torch compile `24.54 s`, KV cache memory `3.78 GiB`, GPU KV cache size
  `396144` tokens, and maximum concurrency for `65536` tokens per request
  `4.97x`.
- RKE cached-Markdown smoke:
  `50/50` selected stock reports processed, `0` blockers, `46` forecast claims,
  `131` analytical footprints, `271` metric candidates, `461` tool gaps, and
  `147` stock-price proxy outcome labels.
- Smoke wall time: about `8m29s` from run id `RIR-20260629T035251+0000` to
  output mtime, or about `354` reports/hour for the serial RKE extraction loop.
  This is faster than the local 27B validation baseline of about `214-218`
  reports/hour, but the samples differ, so treat quality comparison as
  directional until the same source shard is A/B tested.
- Quality gates on the 50-report smoke: extraction provenance accepted, runtime
  safety accepted, statistical robustness accepted, PIT leakage accepted, tool
  feasibility accepted, and `unvalidated_confidence_impact_count=0`.
  Manual analytical-footprint review remains pending for newly generated rows,
  as expected.
- Full 250-report stock shard validation:
  `historical_backfill_20260628/stock_llm_registry/part_04` processed
  `250/250` reports with `0` blockers. Run id
  `RIR-20260629T040509+0000`, output mtime `2026-06-29T12:54:10+08:00`,
  about `49m01s` wall time, or about `306` reports/hour. Provenance, runtime
  safety, statistical robustness, PIT leakage, and tool feasibility gates were
  accepted; `unvalidated_confidence_impact_count=0` and
  `aggregate_calibration_drift_count=0`.
- Same-source 50-report structural comparison against the 27B part_01 output:
  27B produced `30` forecast claims and `78` analytical footprints across the
  50 overlapping report ids, with footprints on `34/50` reports. The 35B NVFP4
  smoke produced `46` forecast claims and `131` analytical footprints across
  the same 50 report ids, with footprints on `50/50` reports. Treat this as
  higher structured-recall evidence, not as a completed manual semantic-quality
  review.
- 2026-07-02 sndr 35B NVFP4 article-extraction smoke:
  - Preset: `nvidia-qwen3.6-35b-a3b-nvfp4-5090`.
  - Do not use `sndr up` as the primary path for this preset. On this host it
    can fail a false model-path autodetect check even when the HF cache is
    present. Use `sndr launch ... --skip-autodetect`.
  - Runtime envelope:
    - Served model: `qwen3.6-35b-a3b-nvfp4`.
    - HF snapshot:
      `/models/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/491c2f1ea524c639598bf8fa787a93fed5a6fbce`.
    - API base URL: `http://127.0.0.1:8000`.
    - Chat endpoint: `/v1/chat/completions`.
    - Auth header: `Authorization: Bearer genesis-local`.
    - Preset engine flags: `--tensor-parallel-size 1`,
      `--gpu-memory-utilization 0.9`, `--max-model-len 120000`,
      `--max-num-seqs 1`, `--max-num-batched-tokens 4096`,
      `--dtype bfloat16`, `--kv-cache-dtype auto`,
      `--speculative-config '{"method":"mtp","num_speculative_tokens":3}'`,
      `--enable-chunked-prefill`, `--disable-custom-all-reduce`,
      `--language-model-only`, `--trust-remote-code`, and
      `--enable-auto-tool-choice`.
  - Single-owner service workflow, now the standard operating model:
    - Pick exactly one service owner for each service lifetime. The owner can
      be a human shell or one Codex session.
    - The same owner may perform the full lifecycle: cleanup, launch, health
      polling, extraction requests, log inspection, and final shutdown.
    - Current workstation note: on 2026-07-02 this service was successfully
      started by another owner shell before testing. When that is already true,
      skip startup and start at the health check and extraction request below.
  - Environment prerequisites:
    - RTX 5090 D visible from the host. `rtk nvidia-smi` should show the idle
      desktop baseline around `1.2-1.8 GiB` used before launch.
    - No other vLLM/MinerU GPU workload or vLLM Docker container should be
      running.
    - The HF cache must contain the NVIDIA Qwen3.6 35B NVFP4 snapshot above.
  - Service-owner startup flow, and only for the owner shell:
    - If the same-parameter container is already healthy, reuse it and skip
      startup:

      ```bash
      curl -s http://127.0.0.1:8000/health
      rtk docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
      ```

    - If the same-parameter container exists but is stopped, prefer restarting
      it instead of deleting it:

      ```bash
      rtk docker ps -a \
        --filter name=vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d \
        --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
      rtk docker start vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d
      ```

      This reuses the container definition and mounted host caches, but not GPU
      memory. The model still reloads and warms up after every stopped start.

    - Rebuild the container only when no reusable container exists, the preset
      or runtime flags changed, the container is in an abnormal state, or a
      clean deterministic launch is required:

      ```bash
      rtk sndr down nvidia-qwen3.6-35b-a3b-nvfp4-5090 || true
      rtk docker rm -f vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d 2>/dev/null || true
      rtk docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
      rtk nvidia-smi --query-gpu=memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits
      rtk sndr launch nvidia-qwen3.6-35b-a3b-nvfp4-5090 --skip-autodetect
      ```

    `sndr launch` renders a conservative Docker script that removes any
    same-name container before creating a fresh one. Use `rtk docker start`
    instead when the goal is to reuse an unchanged stopped container.

    If another vLLM container is already running, or GPU memory is close to
    full, do not launch. Either wait for the current owner to finish, or have
    that owner stop the service first.

  - Health wait, up to 10 minutes:

    ```bash
    for i in {1..120}; do
      code=$(curl -s -o /tmp/sndr-health-35b.out -w "%{http_code}" \
        http://127.0.0.1:8000/health || true)
      if [ "$code" = 200 ]; then
        echo READY
        break
      fi
      if ! rtk docker ps --format "{{.Names}}" | \
        grep -qx vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d; then
        echo EXITED
        rtk docker ps -a \
          --filter name=vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d \
          --format "{{.Status}}"
        rtk docker logs --tail 200 \
          vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d
        exit 1
      fi
      sleep 5
    done
    ```

    If the container exits before `/health` returns `200`, stop waiting and
    inspect logs instead of sending extraction requests.
  - Service ready confirmation by the owner:

    ```bash
    curl -s http://127.0.0.1:8000/health
    rtk docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    ```

    The owner should see container
    `vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d` with port
    `0.0.0.0:8000->8000/tcp`.
  - Extraction call flow:
    - Use `http://127.0.0.1:8000`, `/v1/chat/completions`, model
      `qwen3.6-35b-a3b-nvfp4`, `Authorization: Bearer genesis-local`, and
      `Content-Type: application/json`.
    - Start every extraction test with:

      ```bash
      curl -s http://127.0.0.1:8000/health
      ```

      Continue only when it returns a healthy response.
  - Model check after health is ready:

    ```bash
    curl -sS \
      -H 'Authorization: Bearer genesis-local' \
      http://127.0.0.1:8000/v1/models
    ```

  - Minimal reproducible article-extraction request:

    ```bash
    curl -s http://127.0.0.1:8000/v1/chat/completions \
      -H "Authorization: Bearer genesis-local" \
      -H "Content-Type: application/json" \
      -d @- <<'JSON' | tee /tmp/sndr-35b-extract-response.json | python3 -m json.tool
    {
      "model": "qwen3.6-35b-a3b-nvfp4",
      "messages": [
        {
          "role": "system",
          "content": "You extract article metadata. Return exactly one compact JSON object in the final answer content. No markdown."
        },
        {
          "role": "user",
          "content": "Title: Example Market Note\nAuthor: Jane Doe\nDate: 2026-07-02\nBody: Acme reported revenue growth of 12% and expanded operations in Shanghai. Extract title, author, date, organizations, locations, and numeric claims."
        }
      ],
      "temperature": 0,
      "max_tokens": 1024
    }
    JSON
    ```

    Read the final answer from `content` first:

    ```bash
    python3 - <<'PY'
    import json
    from pathlib import Path

    d = json.loads(Path("/tmp/sndr-35b-extract-response.json").read_text())
    msg = d["choices"][0]["message"]
    print(msg.get("content") or msg.get("reasoning") or "")
    PY
    ```

    Qwen reasoning parser output can include
    `choices[0].message.reasoning`. Prefer `choices[0].message.content`; if it
    is empty, increase `max_tokens` and make the system prompt explicit:
    `Return final JSON in content after reasoning.` For deterministic
    extraction where supported by the server,
    `chat_template_kwargs: {"enable_thinking": false}` also helps keep JSON in
    `content`.
  - RKE-like reproducible synthetic article input:

    ```text
    Title: Copper Grid Demand Lifts Orders
    Date: 2026-07-02

    Huaxin Cable said second-quarter orders rose 18% year over year to
    RMB 4.2 billion. Management attributed the increase to grid upgrades,
    data-center power projects, and higher copper-clad cable demand.
    The company expects gross margin to improve by 1.5 percentage points in
    the next two quarters if copper prices remain below RMB 82,000 per ton.
    It warned that a sudden copper-price spike and delayed utility tenders
    could pressure shipment timing. Capital expenditure for 2026 is planned
    at RMB 600 million, mainly for high-voltage production lines.
    ```

  - OpenAI-compatible extraction request to run only after `/health` is ready:

    ```bash
    curl -sS http://127.0.0.1:8000/v1/chat/completions \
      -H 'Authorization: Bearer genesis-local' \
      -H 'Content-Type: application/json' \
      -d '{
        "model": "qwen3.6-35b-a3b-nvfp4",
        "temperature": 0,
        "max_tokens": 600,
        "chat_template_kwargs": {"enable_thinking": false},
        "response_format": {"type": "json_object"},
        "messages": [
          {
            "role": "system",
            "content": "Extract structured facts from the article. Return only JSON with keys: title, publication_date, entities, metrics, forecasts, risks, capex, evidence_spans."
          },
          {
            "role": "user",
            "content": "Title: Copper Grid Demand Lifts Orders\nDate: 2026-07-02\n\nHuaxin Cable said second-quarter orders rose 18% year over year to RMB 4.2 billion. Management attributed the increase to grid upgrades, data-center power projects, and higher copper-clad cable demand. The company expects gross margin to improve by 1.5 percentage points in the next two quarters if copper prices remain below RMB 82,000 per ton. It warned that a sudden copper-price spike and delayed utility tenders could pressure shipment timing. Capital expenditure for 2026 is planned at RMB 600 million, mainly for high-voltage production lines."
          }
        ]
      }'
    ```

  - Result checks:
    - HTTP status is `200`.
    - `choices[0].message.content` is valid JSON.
    - The JSON includes article-level facts, metric values, forecast horizon,
      risks, capex, and evidence snippets grounded in the synthetic input.
    - Record elapsed wall time, HTTP status, and whether JSON parsing succeeds.
  - Observed benchmark reference:
    - File:
      `/home/hap/Project/sndr-bench-results/20260702-rtx5090d/nvidia-qwen3.6-35b-a3b-nvfp4-5090-ctx120k-k3-warm.json`.
    - Result: `16/16` success, output throughput `327.67 tok/s`, total token
      throughput `1665.09 tok/s`, mean TTFT `76.23 ms`, MTP acceptance rate
      `63.73%`, and MTP acceptance length `2.91`.
  - Service-owner stop, and only for the owner shell:
    - Default stop keeps the container available for same-parameter reuse:

      ```bash
      rtk sndr down nvidia-qwen3.6-35b-a3b-nvfp4-5090 || true
      rtk docker stop vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d 2>/dev/null || true
      rtk docker ps -a \
        --filter name=vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d \
        --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
      rtk docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
      rtk nvidia-smi --query-gpu=memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits
      ```

    `sndr down` may report no running engine if the container was launched
    outside the current sndr runtime state. In that case, use `rtk docker stop`
    on the known container name to preserve it for reuse.

    After stop, GPU memory should return to the desktop idle baseline.

  - Full cleanup only when rebuilding or recovering from abnormal state:

    ```bash
    rtk docker rm -f vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d 2>/dev/null || true
    ```

    Removing the container does not remove host caches mounted from Hugging
    Face, Triton, or vLLM torch compile cache directories. It only discards the
    container definition and forces the next `sndr launch` to recreate it.

  - Common failure notes:
    - If `sndr up` says the model is missing but the HF cache exists under
      `models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/`, use the rebuild
      `sndr launch --skip-autodetect` flow above.
    - If `/health` returns `000` while logs show safetensor loading, profile,
      warmup, or autotune, continue waiting until health is ready or the
      container exits.
    - If logs end with `Engine core initialization failed`, do not run RKE
      extraction against this endpoint. The service owner should capture
      `rtk docker logs --tail 200`, stop with `rtk sndr down` and
      `rtk docker stop`, and remove the stopped container only if a rebuild is
      required before retesting.
- 2026-07-01 macro backfill run:
  - Source pool: `979` previously unprocessed local macro reports from the
    private local source registry.
  - MinerU main conversion used `vlm-auto-engine` with
    `MINERU_BACKEND=vlm-vllm-engine`,
    `MINERU_API_MAX_CONCURRENT_REQUESTS=200`,
    `MINERU_PROCESSING_WINDOW_SIZE=256`, batch size `80`, and max batch bytes
    `200000000`. Result: `907/979` Markdown ready, `72` MinerU blockers.
  - LLM extraction used the 35B NVFP4 container above, model
    `nvidia/Qwen3.6-35B-A3B-NVFP4`, shard sizes `250/250/250/157`,
    `--vllm-timeout-seconds 600`, and `--max-llm-output-tokens 2048`. Result:
    `899/907` processed, with `8` Markdown repeated-line-noise blockers.
  - Retry conversion combined the `72` MinerU blockers and `8` Markdown-quality
    blockers, then used batch size `8`, max batch bytes `50000000`,
    `MINERU_API_MAX_CONCURRENT_REQUESTS=80`, and
    `MINERU_PROCESSING_WINDOW_SIZE=128` with `--overwrite`. Result: `69/80`
    Markdown ready and `11` remaining MinerU blockers.
  - Retry LLM extraction on the `69` ready rows processed `62/69`; `7` rows
    still failed the Markdown repeated-line-noise gate. Clean merge therefore
    added `961` processed macro reports. Remaining local macro source gap after
    this run is `18` reports: `11` MinerU conversion failures and `7` Markdown
    quality failures.
  - Practical 35B NVFP4 macro extraction throughput for the serial RKE loop was
    about `270` processed reports/hour over the four main macro shards. The
    retry shard was in the same order of magnitude. Do not re-test these
    settings before future macro shards unless the model/container, RKE
    extraction flags, or Markdown quality gates change.
- Ask the service owner to stop this container before MinerU VLM conversion or
  any other GPU-heavy local workload if memory pressure appears.

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
  stock samples just to clear `RI-EVOL-04`. The active blocker is now only the
  required distinct clean audit-vintage history.
- 2026-06-22 post-review local promotion check: after applying the completed
  gold-set and analytical-footprint review imports, then refreshing derived
  report-intelligence artifacts, `operator-readiness` passed `18/18` with
  `next_state=staged_production` and `schema-status --failures-only` returned
  `accepted=true, failure_count=0`. `evolution-readiness` then had only
  `audit_refresh_history_below_threshold`: current `1/3`, remaining `2`
  distinct clean data vintages. Do not keep rerunning `--refresh-derived-only`
  on unchanged inputs; same-`data_vintage_hash` refreshes are deduplicated and
  cannot satisfy `RI-EVOL-04`.
- Public-safe aggregate outputs from this check may be committed with the
  associated code/docs/tests. Private reviewed imports, review aids, source rows,
  PDFs, Markdown, MinerU caches, local scorecard DBs, and claim/source prose
  artifacts remain uncommitted.
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

4. Recompute local derived artifacts with `--refresh-derived-only` after private
   extraction outputs exist. Keep the generated `registry/report_intelligence/`
   files local.

## Operation Log

- `2026-06-15`: Added local macro source support and built private source rows
  from `/home/hap/Downloads/yanbaoke/宏观策略`; 788 PDFs found.
- `2026-06-22`: Rebuilt the private local macro source rows from the parent
  `/home/hap/Downloads/yanbaoke` root so macro-adjacent additions in
  `其他债券研究`, `汇率研究`, `全球策略`, and `国际宏观评论` are included; 1898 PDFs
  found, with no source-scan blockers.
- `2026-06-23`: Rebuilt the same parent Yanbaoke source registry after the
  latest local additions; 1967 PDFs/source rows were found, with no source-scan
  blockers. Final staged macro vintages were merged through clean batch
  directories only, then `--refresh-derived-only --scorecard-db-path
  data/scorecard.db` produced 947 selected/Markdown-ready reports, 1048
  forecast claims, 2768 analytical footprints, 2377 outcome labels, 811 macro
  regime snapshots, and 3661 macro agent research priors.
- `2026-06-23`: Rebuilt the local macro source registry after adding the FX
  classifier. The scan still found 1967 PDFs/source rows with no blockers; 218
  rows now classify as `宏观策略-汇率`, and FX futures reports no longer inflate
  the commodity bucket.
- `2026-06-23`: Completed the new analytical-footprint manual review rows
  introduced by the final macro batches. The footprint review summary is
  accepted with 2768/2768 complete rows, 0 pending rows, and all quality gates
  passing. `operator-readiness --root .` passed 18/18, `schema-status --root .
  --failures-only --no-write` returned 0 failures, and `evolution-readiness
  --root . --no-write` passed RI-EVOL-01 through RI-EVOL-07 and RI-MACRO-01
  through RI-MACRO-07.
- `2026-06-23`: Merged the next 80-report macro expansion tranche after
  VLM conversion and cached-Markdown LLM extraction, including a one-row retry
  for an FX report that hit a transient vLLM SSL EOF. The registry now has 1106
  selected reports, 1104 LLM-processed reports, 306 processed local macro
  reports, 1181 forecast claims, and 2621 outcome labels. This reopened the
  analytical-footprint manual-review gate: 369 footprint rows are pending human
  review, so `schema-status --root . --no-write` is expected to fail until those
  rows and the required human negative examples are completed.
- `2026-06-24`: Expanded report intelligence to 2492 selected/Markdown-ready
  reports, 2490 LLM-processed reports, 2611 forecast claims, and 6529 outcome
  labels. The analytical-footprint review is complete at 7312/7312 rows, and
  the private negative-example approval import produced 200 human-reviewed rows
  with 50 expected positives, `recall_status=computed_from_human_negative_examples`,
  `recall_estimate=0.22`, and zero source-text rows. After
  `--refresh-derived-only`, `schema-status --failures-only --no-write` returned
  0 failures, `evolution-readiness --no-write` passed, `promotion-status
  --no-write` allowed production, and `operator-readiness --root .` passed
  18/18 checks.
- `2026-07-03`: Built a clean private Part 1 validation corpus at
  `.mosaic/rke/report_intelligence/merged_private_replay_clean_macro_20260703`
  by copying `merged_private_replay_20260612`, merging clean macro batches
  excluding the one shard with a repeated-line Markdown QA queue, and reusing the
  public-safe aggregate gold review summary under the private `gold_sets/`
  sibling. `--refresh-derived-only --registry-dir
  .mosaic/rke/report_intelligence/merged_private_replay_clean_macro_20260703
  --scorecard-db-path data/scorecard.db` produced 531 selected reports, 529
  Markdown-ready reports, 385 LLM-processed reports, 442 forecast claims, 534
  outcome labels, 273 stock proxy labels, 109 industry ETF proxy labels, and
  macro asset/series/curve labels of 92/59/1. The private
  `evolution_readiness_gate.json` passed RI-EVOL-01 through RI-EVOL-09 and
  RI-MACRO-01 through RI-MACRO-07 with `blocker_count=0`.
- `2026-07-03`: The same clean corpus validates the first
  `cross_asset_consistency` implementation in `macro_agent_research_priors.jsonl`.
  Aggregate prior counts are `consistent=65`, `mixed=26`,
  `blocked_mapping=48`, and `not_applicable=1702`; prompt mutation output is no
  longer refusal-only, with 5 macro prior rule/parameter candidates plus stock
  and industry prior recipe/rule candidates. These artifacts remain local and
  shadow-only.
- `2026-07-03`: Re-ran the clean private corpus after adding stock/industry PIT
  context snapshots. `extraction_report.json` now records
  `stock_context_snapshot_rows=74` and `industry_context_snapshot_rows=58`;
  `evolution_readiness_gate.json` still has `gate_status=passed` and
  `blocker_count=0`. Snapshot rows are background-only, schema-validated local
  artifacts and must not be committed.
- `2026-07-03`: Re-ran the same clean corpus after adding stock/industry
  internal domain ratings to profile `outcome_layer_support`. Source/viewpoint
  profile summaries now expose redacted `domain_rating_support` bucket counts,
  tradeability blocker counts, target-price auxiliary counts, mapping confidence
  counts, and proxy limitation tags. Across source and viewpoint profiles the
  local diagnostic counted `supportive_evidence=749` and
  `contradictory_evidence=771`; `evolution_readiness_gate.json` still reports
  `blocker_count=0`.
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
- `2026-06-21`: Updated RKE's MinerU launcher so the normal local VLM path still
  passes CLI backend `vlm-auto-engine` but explicitly injects
  `MINERU_BACKEND=vlm-vllm-engine` for MinerU's vLLM API/deployment engine. This
  matches recent MinerU documentation without passing an unsupported backend
  name to the current installed CLI.
- `2026-06-21`: Ran a one-report forced-overwrite MinerU smoke under isolated
  cache `.mosaic/rke/report_intelligence_mineru_vllm_smoke` with
  `MINERU_BACKEND=vlm-vllm-engine`, CLI backend `vlm-auto-engine`, and
  `--skip-llm`; the PDF was downloaded, Markdown conversion completed, Markdown
  quality passed, and blocker count was `0`.
- `2026-06-21`: For macro curve extraction, title-level matches such as
  `期限利差` or `收益率曲线` were too broad and often produced sector/asset claims
  rather than curve claims. The useful selector is a Markdown window containing
  forecast language plus curve/spread terms plus a direction term, for example
  forecast/expected language near `期限利差`, `收益率曲线`, `中美利差`,
  `走陡`, `走平`, `扩大`, or `收窄`. After prompt and normalizer updates, the
  explicit-curve staging batch
  `.mosaic/rke/report_intelligence_batches/macro_curve_explicit_reextract_20260621_01`
  refreshed with 1 `macro_curve_directional` eligible claim and 3 curve outcome
  labels on `US_2S10S`, plus direct macro-series labels. The normalizer now
  preserves the parent `macro_curve` leg when the LLM also emits component
  `macro_series` legs.
