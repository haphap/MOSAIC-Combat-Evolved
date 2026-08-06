# mosaic-ts

TypeScript front-end for MOSAIC. Drives the Python codebase as a black-box
JSON-RPC sidecar (`mosaic.bridge`). See plan §2 for architecture and §11 for
the bridge wire protocol (mirrored from ETFAgents).

This package is **internal-use only** (no npm publish). It contains the CLI,
Ink TUI, and the TypeScript orchestration for the 28-Agent / 29-stage graph.

## Layout

```
mosaic-ts/
├── src/
│   ├── bridge/           # JSON-RPC client, types, JSON-Schema → Zod, tool factories
│   ├── agents/           # Agent contracts, runtime nodes, prompts, and validation
│   ├── autoresearch/     # Prompt-behavior evaluation and release plumbing
│   ├── graph/            # Layered LangGraph orchestration
│   ├── llm/              # ChatOpenAI / ChatAnthropic factory built from bridge config
│   └── cli/              # Commander entry, operational commands, and Ink TUI
└── test/                 # Vitest tests, mostly black-box against the real sidecar
```

The same repo also owns `mosaic/bridge/` on the Python side. Cross-language
contract changes touch both halves in a single commit.

## Prerequisites

- Node 22+, pnpm 11+
- A working Python venv with project deps. From the repo root:
  ```bash
  uv venv
  source .venv/bin/activate
  uv pip install -e ".[data]"
  ```
  This produces `<repoRoot>/.venv/bin/python` which the bridge client picks up
  automatically.

## Dev commands

```bash
pnpm install                 # one-time
pnpm typecheck               # tsc --noEmit
pnpm lint                    # biome check
pnpm format                  # biome format --write
pnpm test                    # vitest run
pnpm build                   # emit dist/

# Bridge and snapshot diagnostics (run via tsx during development)
pnpm dev bridge-ping
pnpm dev tool-loop [--provider name] [--model name] [--base-url url] [--max-tokens count] \
  [--question text] [--as-of-date YYYY-MM-DD]

# Prompt autoresearch: private Candidate generation, public frozen experiment,
# then a separate Prompt Release canary/rollback decision.
pnpm dev autoresearch generate-candidate --request REQUEST.json \
  --private-cli /path/to/private/dist/cli.js \
  --private-repo "$MOSAIC_PROMPTS_REPO" \
  --mutation-adapter "$MOSAIC_PROMPTS_REPO/path/to/tracked-adapter.js"
pnpm dev autoresearch shadow-run --plan SHADOW_PLAN.json --adapter EVALUATION_ADAPTER.js
pnpm dev autoresearch log --cohort crisis_2008 --days 7
pnpm dev autoresearch branches --cohort crisis_2008

# The mutation adapter must be tracked inside the private repository at its exact
# HEAD; the private runtime derives mutator identity from that committed state.

# PRISM is retained as read-only historical audit views.
pnpm dev prism list
pnpm dev prism status --cohort crisis_2008
pnpm dev prism compare [--metric sharpe] [--since YYYY-MM-DD]

# JANUS (meta-weighting over the 7 regime cohorts)
pnpm dev janus run [--date YYYY-MM-DD] [--window 30]    # weights + regime + blended recs (persisted)
pnpm dev janus weights [--date YYYY-MM-DD] [--window 30]
pnpm dev janus regime [--date YYYY-MM-DD]
pnpm dev janus history [--days 30]

# MiroFish (synthetic-futures forward training; isolated from real P&L)
pnpm dev mirofish generate [--days 30] [--seed 42] [--print] [--swarm]   # real MOSAIC-Fish by default; generate + persist context
  # The default oasis engine drives deployed MOSAIC-Fish (set MOSAIC_MIROFISH_URL, e.g. http://localhost:5001);
  #   walks the real multi-step API (graph/build → simulation → report) and maps the prediction report's
  #   direction onto scenario regimes (lossy: MiroFish predicts narratives, not prices). Needs configured LLM + embedding APIs.
  # Use --engine montecarlo or --engine swarm for an explicit local/no-service run.
pnpm dev mirofish train --fake-llm [--seed 42] [--agents a,b] [--dry-run] [--swarm] [--path-aware]
  # --path-aware = score the direction-adjusted equity curve with a max-drawdown penalty (default: terminal cumulative return)
pnpm dev mirofish history [--days 30]
  # mirofish.inject_context defaults true and appends the latest persisted scenario context
  # to CRO / autonomous execution / CIO with anti-lookahead checks and a simulation-only disclaimer.
  # Real-service operations: ../docs/runbooks/mosaic_fish_feedback_loop.md

# Paper trading (simulated A-share ETF account; fake money, local SQLite)
pnpm dev paper register <user> <pw>                  # create account
pnpm dev paper login <user> <pw>                     # start a session (host-global)
pnpm dev paper account [--user u]                    # cash / market value / PnL
pnpm dev paper buy <ticker> <qty> [--user u]         # qty = multiple of 100; T+1 lock
pnpm dev paper sell <ticker> <qty> [--user u]
pnpm dev paper positions [--user u]
pnpm dev paper trades [--user u] [--limit 50]
pnpm dev paper suggest <ticker> '<state-json>' [--user u]   # signal→order from a decision state

# Read-only Ink TUI dashboard (aggregates existing read RPCs; manual refresh)
pnpm dev dashboard [--cohort cohort_default] [--user u]
  # tabs: [1] today (latest CIO plan: what to trade) · [2] winrate (per-ticker hit rate) ·
  #       [3] skill (agent alpha/sharpe) · [4] paper (account+positions) · [5] cohorts (PRISM)
  #       · [6] mirofish (latest scenario context + recent forward-training runs)
  #       · r refresh · q quit
```

## Python interpreter resolution

The bridge client looks for the Python interpreter in this order:

1. `MOSAIC_PYTHON` env var (explicit override)
2. `<repoRoot>/.venv/bin/python` (POSIX)
3. `<repoRoot>/.venv/Scripts/python.exe` (Windows)
4. **Fail loud** with an instruction to run `uv venv && uv pip install -e ".[data]"`

There is no silent fallback to a system Python — failures would surface inside
LangChain / Tushare imports far from the root cause.

## Signed China snapshot tool loop

The `tool-loop` command demonstrates one capability-bound LLM + bridge round-trip. It always
uses the China Macro role and exposes only `get_china_macro_snapshot`; arbitrary tool selection is
intentionally unavailable because every snapshot tool is bound to an exact Agent and stage.

```bash
# Requires:
#   * ANTHROPIC_API_KEY (or OPENAI_API_KEY — see src/llm/factory.ts)
#   * TUSHARE_TOKEN and the configured live snapshot sources
export ANTHROPIC_API_KEY=sk-ant-...
export TUSHARE_TOKEN=...

pnpm dev tool-loop --as-of-date 2026-07-17 \
  --question "请仅依据冻结快照概括中国宏观环境。"
```

For a custom OpenAI-compatible endpoint, export the Agent-specific variables before starting the
TypeScript process. `MOSAIC_LLM_BASE_URL` accepts either the API base or the full
`.../chat/completions` URL; the client normalizes the latter before invoking the SDK.

```bash
export MOSAIC_LLM_PROVIDER=api
export MOSAIC_LLM_BASE_URL=https://gateway.example/v1/chat/completions
export MOSAIC_LLM_MODEL=remote-model
export MOSAIC_LLM_API_KEY=replace-me
export MOSAIC_LLM_MAX_TOKENS=65536
pnpm dev tool-loop --as-of-date 2026-07-17
```

Flow:

1. Spawn the Python sidecar.
2. Read the active model config and prepare a signed capability for the China Agent, China stage,
   and exact as-of date.
3. List the capability-authorized surface and bind only `get_china_macro_snapshot`.
4. Loop: invoke LLM → if `tool_calls`, dispatch through the signed capability → feed
   results back as `ToolMessage` → repeat until the LLM produces a final
   answer (max 6 iterations).
5. Terminate the capability and close the bridge.

## Tests

```bash
pnpm test
```

The TypeScript suite covers the current graph, signed tool capabilities, structured-output
contracts, prompt/private boundaries, accepted-output lineage, and CLI behavior. Tests that spawn
the Python bridge require `<repoRoot>/.venv` to exist; initialize it once with
`uv venv && uv pip install -e ".[data]"`.
