# Architecture

MOSAIC is a **hybrid two-process system**. Heavy/stateful logic stays in Python; orchestration, LLM calls, and the user surface live in TypeScript. They communicate over **line-delimited JSON-RPC over stdio**.

```
TypeScript front-end (mosaic-ts/)      JSON-RPC / stdio       Python sidecar (mosaic/)
──────────────────────────────        ───────────────        ────────────────────────────
CLI (commander) + TUI (Ink)                                   bridge/    JSON-RPC server + handlers/
LangGraph.js 4-layer orchestration  ⇄  line-delimited JSON ⇄  dataflows/ Tushare/akshare/FRED/qlib
  L1 macro(10) · L2 sector(7)                                 scorecard/ · autoresearch/ · prism/
  L3 superinvestor(4) · L4 decision(4)                        janus/ · mirofish/ · backtest/ · paper_trading/
LLM clients · Scorecard views                                 persistence: SQLite + a git repo
```

## Why the split

- **Tooling boundaries are strings/JSON** — no cross-language DataFrame transfer. The TS side asks for data or an action; Python returns JSON.
- Heavy Python libs (pandas, numpy, pyqlib, tushare) never need a Node binding.
- The LLM/agent orchestration (LangGraph.js) and the user-facing CLI/TUI stay in one ergonomic TypeScript codebase.

## The bridge

- **Server**: `mosaic/bridge/server.py` reads JSON-RPC requests on stdin, dispatches by method name, writes responses on stdout. Importing `mosaic.bridge.handlers` registers every handler via an `@method("namespace.verb")` decorator (`mosaic/bridge/registry.py`).
- **Client**: `mosaic-ts/src/bridge/client.ts` (`BridgeClient`) spawns the Python process, frames requests, correlates responses by id, and maps `{error}` envelopes to `RpcError`. `mosaic-ts/src/bridge/types.ts` (`BridgeApi`) wraps each RPC as a typed method.
- **Interpreter discovery** (`mosaic-ts/src/bridge/python.ts`): `MOSAIC_PYTHON` env → `<repo>/.venv/bin/python` → fail-loud.
- See [Bridge RPC](Bridge-RPC.md) for the full method list.

## Repo layout

```
MOSAIC-Agents/
├── mosaic/                     # 🐍 Python sidecar
│   ├── bridge/                 #   JSON-RPC server + handlers/ (one module per namespace)
│   ├── dataflows/              #   Tushare / akshare / yfinance / FRED + qlib local reader + ingest
│   │   └── collectors/         #   vendored qlib + tushare/ETF collectors (see Data Layer)
│   ├── scorecard/              #   SQLite store · forward-return scoring · Darwinian weights
│   ├── autoresearch/           #   git_ops · constraints · evaluator · keep/revert decider
│   ├── prism/                  #   7-cohort training orchestration
│   ├── janus/                  #   cross-cohort meta-weighting
│   ├── mirofish/               #   reflexive scenario simulation (swarm engine · path-aware scorer)
│   ├── backtest/               #   qlib two-stage vectorized backtest
│   └── paper_trading/          #   bespoke paper-trading engine (T+1, commission, positions)
├── mosaic-ts/                  # 🟦 TypeScript front-end
│   └── src/
│       ├── bridge/             #   BridgeClient + typed RPC wrappers (BridgeApi)
│       ├── llm/                #   multi-provider LLM factory
│       ├── agents/             #   macro/sector/superinvestor/decision + helpers + prompts
│       ├── graph/              #   daily_cycle LangGraph.js assembly
│       ├── autoresearch/ · prism/ · mirofish/
│       ├── cli/commands/       #   CLI subcommands
│       └── tui/                #   Ink dashboard
├── prompts/mosaic/             # 📝 bilingual prompt repo (cohort_default + 7 cohorts)
├── tests/                      # ✅ Python tests (pytest / unittest)
├── pyproject.toml · mosaic-tsplan.md · .github/workflows/ci.yml
```

## Determinism & anti-lookahead

- The scorer snaps "today" backward to the last completed trading day and only scores rows whose forward horizon has matured (`mosaic/scorecard/scorer.py`).
- MiroFish context injection and context reads accept an `as_of_date` bound so a backtest never sees future scenario data.

## Persistence

- **SQLite** — scorecard recommendations + scoring, autoresearch metadata, backtest run cache, paper-trading DB (`~/.mosaic/paper_trading.db`).
- **git repo** — Autoresearch versions prompt mutations on feature branches; keep = merge to main, revert = delete branch (see [Self-Improvement](Self-Improvement.md)).
- **Config file** — `~/.mosaic/config.json` (optional; see [Configuration](Configuration.md)).
