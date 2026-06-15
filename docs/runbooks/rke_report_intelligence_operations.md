# RKE Report Intelligence Operations Runbook

This file records local RKE report-intelligence operations so future agents can
resume from the latest known state instead of rediscovering or reinstalling the
same environment. Do not write API keys, licensed report prose, PDF contents, or
Markdown excerpts here.

## Current Local Runtime

- Repository: `/home/hap/Project/MOSAIC-RKE`
- Private runtime/cache root: `.mosaic/rke/report_intelligence/`
- Local temp root: `.mosaic/tmp/`
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
TMPDIR=.mosaic/tmp uv run mosaic-rke report-intelligence \
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
TMPDIR=.mosaic/tmp uv run mosaic-rke report-intelligence \
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

Last completed VLM batch:

```bash
TMPDIR=.mosaic/tmp uv run mosaic-rke report-intelligence \
  --root . \
  --env-file .env \
  --source-path registry/sources/local_macro_strategy_reports.jsonl \
  --cache-dir .mosaic/rke/report_intelligence \
  --registry-dir .mosaic/rke/report_intelligence/macro_vlm_batch_registry \
  --selection-order stratified \
  --limit 5 \
  --mineru-command .venv/bin/mineru \
  --mineru-backend vlm-auto-engine \
  --mineru-timeout-seconds 3600 \
  --mineru-batch-size 1 \
  --mineru-batch-max-bytes 8000000 \
  --skip-llm \
  --overwrite
```

Result:

- Run id: `RIR-20260615T003823+0000`
- Selected reports: `5`
- PDF ready: `5`
- Markdown ready: `5`
- Blockers: `0`
- MinerU backend counts: `vlm-auto-engine=5`
- Markdown status counts: `converted=5`
- Markdown quality gate counts: `passed=5`
- Markdown durations: `44.517s`, `38.151s`, `39.165s`, `35.995s`,
  `52.435s`
- Private outputs under `.mosaic/rke/report_intelligence/macro_vlm_batch_registry/`
  are gitignored and must not be committed.

Last completed vLLM/VLM smoke:

```bash
TMPDIR=.mosaic/tmp uv run mosaic-rke report-intelligence \
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
TMPDIR=.mosaic/tmp uv run mosaic-rke report-intelligence \
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
TMPDIR=.mosaic/tmp uv run mosaic-rke report-intelligence \
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
  HTTP client modes, then ran a 5-PDF local VLM batch; all five Markdown
  conversions passed quality gates with no blockers.
