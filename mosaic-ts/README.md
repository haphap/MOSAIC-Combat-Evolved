# mosaic-ts

TypeScript front-end for MOSAIC. Drives the Python codebase as a black-box
JSON-RPC sidecar (`mosaic.bridge`). See plan §2 for architecture and §11 for
the bridge wire protocol (mirrored from ETFAgents).

This package is **internal-use only** for now (no npm publish). The eventual
delivery is a CLI + Ink TUI; Phase 1 only delivers the bridge plumbing.

## Layout

```
mosaic-ts/
├── src/
│   ├── bridge/           # JSON-RPC client, types, JSON-Schema → Zod, tool factories
│   ├── llm/              # ChatOpenAI / ChatAnthropic factory built from bridge config
│   └── cli/              # commander entry + commands (Phase 1)
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

# Phase 1 CLI commands (run via tsx during development)
pnpm dev bridge-ping
pnpm dev tool-call <name> [argsJson]
pnpm dev tool-loop [--tool name] [--model name] [--question text]

# Phase 4 autoresearch (prompt mutation loop)
pnpm dev autoresearch trigger --cohort crisis_2008 --agent volatility --fake-llm  # one-shot generate+commit+eval+decide (zero-cost smoke)
pnpm dev autoresearch trigger --cohort crisis_2008 --dry-run --fake-llm           # select+generate only, no branch/DB side effects
pnpm dev autoresearch evaluate --cohort crisis_2008                               # evaluate pending mutations (resume)
pnpm dev autoresearch log --cohort crisis_2008 --days 7                           # audit log
pnpm dev autoresearch branches --cohort crisis_2008                               # active feature branches
pnpm dev autoresearch revert --version-id 12                                      # manual revert (respects 3-day keep-lockout)

# Phase 5 PRISM (7-cohort training orchestration)
pnpm dev prism list                                  # 7 cohorts + branch/run status
pnpm dev prism train --cohort crisis_2008 --fake-llm [--max-concurrent 5] [--max-mutations 1] [--dry-run]
pnpm dev prism train --all --fake-llm                # train all 7 cohorts sequentially (layers sequential, ≤5 agents/layer concurrent)
pnpm dev prism status --cohort crisis_2008
pnpm dev prism compare [--metric sharpe] [--since YYYY-MM-DD]

# Phase 6 JANUS (meta-weighting over the 7 regime cohorts)
pnpm dev janus run [--date YYYY-MM-DD] [--window 30]    # weights + regime + blended recs (persisted)
pnpm dev janus weights [--date YYYY-MM-DD] [--window 30]
pnpm dev janus regime [--date YYYY-MM-DD]
pnpm dev janus history [--days 30]

# Phase 7 MiroFish (synthetic-futures forward training; isolated from real P&L)
pnpm dev mirofish generate [--days 30] [--seed 42] [--print] [--swarm]   # scenario set (--swarm = Phase 7M.1 agent-to-agent engine; default Monte-Carlo)
  # --engine oasis = drive a deployed 666ghj/MiroFish service (set MOSAIC_MIROFISH_URL, e.g. http://localhost:5001);
  #   walks the real multi-step API (graph/build → simulation → report) and maps the prediction report's
  #   direction onto scenario regimes (lossy: MiroFish predicts narratives, not prices). Needs LLM+Zep keys; default off.
pnpm dev mirofish train --fake-llm [--seed 42] [--agents a,b] [--dry-run] [--swarm] [--path-aware]
  # --path-aware = score the direction-adjusted equity curve with a max-drawdown penalty (default: terminal cumulative return)
pnpm dev mirofish history [--days 30]
  # config mirofish.inject_context=true (default false) appends the latest MiroFish scenario
  # context (regime/最高信念方向/尾部风险 + "仅供参考" disclaimer) to the CIO prompt — 7M Step 2

# Phase 8 — paper trading (simulated A-share ETF account; fake money, local SQLite)
pnpm dev paper register <user> <pw>                  # create account
pnpm dev paper login <user> <pw>                     # start a session (host-global)
pnpm dev paper account [--user u]                    # cash / market value / PnL
pnpm dev paper buy <ticker> <qty> [--user u]         # qty = multiple of 100; T+1 lock
pnpm dev paper sell <ticker> <qty> [--user u]
pnpm dev paper positions [--user u]
pnpm dev paper trades [--user u] [--limit 50]
pnpm dev paper suggest <ticker> '<state-json>' [--user u]   # signal→order from a decision state

# Phase 9B/10 — read-only Ink TUI dashboard (aggregates existing read RPCs; manual refresh)
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

## Phase 1 Exit standard

The `tool-loop` command demonstrates a minimal LLM + bridge tool round-trip:

```bash
# Requires:
#   * ANTHROPIC_API_KEY (or OPENAI_API_KEY — see src/llm/factory.ts)
#   * FRED_API_KEY (for the default get_fred_series tool — free at
#     https://fredaccount.stlouisfed.org/apikey)
export ANTHROPIC_API_KEY=sk-ant-...
export FRED_API_KEY=...

pnpm dev tool-loop --question "What was the U.S. effective federal funds rate in early 2024?"
```

Flow:

1. Spawn the Python sidecar.
2. Pull `tools.list` and the active config from the bridge.
3. Build a chat model from the bridge config + env API key (Anthropic by default).
4. Wrap **one** bridge tool (default `get_fred_series`) as a LangChain
   `DynamicStructuredTool`.
5. Loop: invoke LLM → if `tool_calls`, dispatch through the bridge → feed
   results back as `ToolMessage` → repeat until the LLM produces a final
   answer (max 6 iterations).
6. Print the final assistant message.

This proves: subprocess management, JSON-RPC framing/correlation, Pydantic
JSON Schema → Zod conversion, LangChain.js tool calling, and error
propagation across the language boundary.

## What's NOT in Phase 1

- LangGraph orchestration of the 4-layer 25-agent graph (Phase 2)
- Agent prompts, schemas, debate, manager (Phase 2)
- Memory, validation, reflection (Phase 2)
- Scorecard / Darwinian weights (Phase 3)
- Autoresearch / PRISM / JANUS / MiroFish (Phase 4–7)
- Ink TUI, full CLI command coverage (Phase 9)

## Tests

```bash
pnpm test
```

The suite has tests across three files:

- `python.test.ts` — interpreter discovery fallback chain (uses tempdirs).
- `client.test.ts` — JSON-RPC client driving the real bridge subprocess:
  request correlation, error envelope mapping, timeout semantics.
- `tools.test.ts` — JSON-Schema → Zod conversion (unit) plus end-to-end:
  every Pydantic schema returned by `tools.list` becomes a usable LangChain
  tool.

Black-box tests start the real `python -m mosaic.bridge` subprocess. They
require `<repoRoot>/.venv` to exist (run `uv venv && uv pip install -e ".[data]"`
once).
