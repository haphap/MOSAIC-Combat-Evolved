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
- Use `--mineru-batch-size 1` for VLM mode unless a later runbook entry proves a
  larger batch is stable.
- Keep outputs under `.mosaic/` until quality is confirmed.
- Do not reinstall MinerU or recreate the vLLM service before checking
  `.venv/bin/mineru --help` and the existing Docker/container state.
- Do not commit PDF, Markdown, MinerU output, or source-row JSONL artifacts.
- If a previous `hybrid-auto-engine` run is still active, wait for it to return
  or terminate only that specific `report-intelligence`/MinerU process before
  launching the VLM batch.

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
