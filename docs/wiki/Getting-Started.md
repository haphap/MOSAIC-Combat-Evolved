# Getting Started

## Prerequisites

- **Python ≥ 3.10** (`pyproject.toml` `requires-python`), managed with [`uv`](https://github.com/astral-sh/uv).
- **Node.js ≥ 22** (`mosaic-ts/package.json` `engines`) with **pnpm 11**.
- **API credentials** as needed, in `.env` (see `.env.example`).

## Install

```bash
git clone https://github.com/haphap/MOSAIC-Agents.git
cd MOSAIC-Agents

# 1. Python sidecar: create .venv + install (the TS side auto-discovers <repo>/.venv/bin/python)
uv venv
uv pip install -e '.[data,trading,llm]'      # add ,backtest for qlib; ,ingest for data updates

# 2. TypeScript front-end
cd mosaic-ts
pnpm install --frozen-lockfile

# 3. Configure env
cd ..
cp .env.example .env
```

## Optional extras (`pyproject.toml`)

Dependencies are grouped so per-cycle CLI users don't pull heavy data/backtest libs:

| Extra | Purpose | Notable deps |
| --- | --- | --- |
| `data` | market/macro data | pandas, numpy, tushare, akshare, yfinance, stockstats |
| `trading` | paper trading | bcrypt |
| `llm` | LLM providers | langchain-anthropic/openai/google, langgraph |
| `backtest` | qlib backtest engine | pyqlib, scipy, tqdm |
| `ingest` | data-collector subprocess deps | fire, loguru, joblib, yahooquery, beautifulsoup4 |
| `test` | tests | pytest, pytest-asyncio |
| `all` | everything above | — |

> `pyqlib` ships wheels for cp38–cp312; on newer Python the `backtest`/ingest path is skipped in tests (the suite guards qlib-dependent tests).

## Environment variables (`.env.example`)

LLM keys: `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`, `XAI_API_KEY`, `LEMONADE_BASE_URL`/`LEMONADE_API_KEY` (local dev).
Data: `TUSHARE_TOKEN` (A-share, required for live data), `FRED_API_KEY`, `BRAVE_SEARCH_API_KEY`, `ALPHA_VANTAGE_API_KEY`.
Runtime overrides: `MOSAIC_DATA_DIR`, `MOSAIC_RESULTS_DIR`, `MOSAIC_CACHE_DIR`, `MOSAIC_PYTHON`, `MOSAIC_BENCHMARK_TICKER`.

In development you can run the whole pipeline at zero cost with a mocked LLM (`--fake-llm`).

## First run

```bash
cd mosaic-ts

# Smoke-test the bridge (spawns the Python sidecar, lists tools + config)
pnpm dev bridge-ping

# Run one full daily cycle (25 agents) with a zero-cost mock LLM
pnpm dev daily-cycle --cohort cohort_default --fake-llm

# Look at the read-only dashboard
pnpm dev dashboard
```

See the [CLI Reference](CLI-Reference.md) for the full command surface and the
["daily use" flow](CLI-Reference.md#daily-operation) for the cron pipeline.

## Verify your setup

```bash
# TypeScript
cd mosaic-ts && pnpm typecheck && pnpm lint && pnpm test
# Python
cd .. && ruff check mosaic tests && python -m pytest -q
```
