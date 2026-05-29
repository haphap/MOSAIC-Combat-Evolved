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
pnpm dev prism train --cohort crisis_2008 [--dry-run]
pnpm dev prism status --cohort crisis_2008
pnpm dev prism compare [--metric sharpe] [--since YYYY-MM-DD]
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
