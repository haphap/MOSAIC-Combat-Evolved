# Configuration

Runtime config is a single object (`MosaicConfig` in `mosaic-ts/src/bridge/types.ts`; `DEFAULT_CONFIG` in `mosaic/default_config.py`). It is read by the sidecar per process and pushed/persisted from the front-end.

## Key fields

| Field | Meaning |
| --- | --- |
| `llm_provider` | `anthropic` (default) / `openai` / `deepseek` / `lemonade` / … (see `src/llm/factory.ts`) |
| `deep_think_llm`, `quick_think_llm` | model ids for the two LLM tiers |
| `backend_url`, `anthropic_base_url`, `anthropic_effort` | optional provider overrides |
| `output_language` | `Chinese` (default) / `English` / `Bilingual` |
| `active_cohort` | active cohort key (default `euphoria_2021`) |
| `cohorts` | 7 cohorts × {start, end} (see [Self-Improvement](Self-Improvement.md)) |
| `autoresearch` | cooldown / lockout / keep-threshold / monthly cap / eval horizon + opt-in `git` push |
| `mirofish` | `engine` / `scorer` / `inject_context` (all opt-in; defaults montecarlo / terminal / off) |
| `data_vendors`, `tool_vendors` | per-category vendor selection |
| `agent_data_cache` | SQLite exact-call cache for routed agent tool data; entries are retained until TTL refresh, max-entry eviction, cleanup, or clear (`enabled` default true; `db_path` optional; `read_ttl_seconds` default 86400; `max_entries` default 50000; `skip_empty_results` default true) |

## Persistence model

- **`config.default`** — pristine `DEFAULT_CONFIG`.
- **`config.get`** — active config for the running sidecar process.
- **`config.set`** — replace active config **for this process only** (a `ContextVar`; dies with the process).
- **`config.save`** — write to `~/.mosaic/config.json` **and** apply. This survives restarts: every sidecar runs `initialize_config()` at startup, which merges the persisted file over `DEFAULT_CONFIG`.

Behavior is conservative: an **absent** config file ⇒ pure defaults (unchanged behavior); **invalid** JSON ⇒ fail-soft back to defaults. `MOSAIC_CONFIG` overrides the file path (used to keep tests hermetic).

Each CLI command spawns its own sidecar, so only **`config.save`** changes reach the next command — which is why the [TUI settings tab](TUI.md) uses `config.save`.

## Environment overrides

Beyond the keys in [Getting Started](Getting-Started.md): `MOSAIC_PYTHON` (interpreter), `MOSAIC_DATA_DIR` / `MOSAIC_RESULTS_DIR` / `MOSAIC_CACHE_DIR` (artefact roots), `MOSAIC_AGENT_DATA_CACHE_ENABLED` / `MOSAIC_AGENT_DATA_CACHE_DB` / `MOSAIC_AGENT_DATA_CACHE_READ_TTL_SECONDS` / `MOSAIC_AGENT_DATA_CACHE_MAX_ENTRIES` / `MOSAIC_AGENT_DATA_CACHE_SKIP_EMPTY_RESULTS` (routed tool cache retention/freshness controls), `MOSAIC_BENCHMARK_TICKER` (scorer benchmark), `QLIB_CN_DATA_PATH` / `QLIB_CN_ETF_PATH` (qlib datasets), `MOSAIC_QLIB_REPO` / `MOSAIC_QLIB_ETF_COLLECTOR` (collector discovery), `MOSAIC_MIROFISH_URL` (OASIS engine).
