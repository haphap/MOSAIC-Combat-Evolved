# MOSAIC

> A-share self-improving multi-agent quantitative research framework.
> A 股自我改进型多智能体量化研究框架。

[![CI](https://github.com/haphap/MOSAIC-Agents/actions/workflows/ci.yml/badge.svg)](https://github.com/haphap/MOSAIC-Agents/actions/workflows/ci.yml)
[![Wiki](https://img.shields.io/badge/docs-wiki-0969da)](https://github.com/haphap/MOSAIC-Agents/wiki)
![Python](https://img.shields.io/badge/Python-%E2%89%A53.10-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/Node-%E2%89%A522-339933?logo=node.js&logoColor=white)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

MOSAIC adapts the ATLAS-style four-layer multi-agent trading architecture to
the A-share market. It combines a Python data/backtest sidecar with a
TypeScript LangGraph front end, connected by line-delimited JSON-RPC over
stdio.

The project is designed for reproducible research loops: agents make daily
portfolio recommendations, results are scored, prompts evolve through git, and
changes are accepted or reverted by measured lift.

> Not financial advice. This repository is research infrastructure; use it with
> your own data-quality checks, risk controls, and compliance review.

## Highlights

- **25-agent decision graph**: 10 macro agents, 7 sector agents, 4
  superinvestor agents, and 4 decision agents (CRO / Alpha / Execution / CIO).
- **A-share data layer**: Tushare, akshare, FRED, yfinance, Xueqiu heat,
  financial statements, technical indicators, ETF data, and research reports.
- **Autoresearch loop**: mutate prompts, commit to a git branch, run two-stage
  backtests, and keep/revert by delta Sharpe under cooldown and lockout rules.
- **PRISM / JANUS / MiroFish**: regime-cohort training, cross-cohort
  meta-weighting, and synthetic forward scenarios.
- **Backtest and paper trading**: qlib replay, scorecard, Darwinian weights,
  T+1 paper-trading engine, and an Ink dashboard.
- **Prompt asset guardrails**: optimized/private prompts are designed to live
  outside the public repo; leak checks and release verification are wired into
  the toolchain.

## Documentation

- [Wiki home](https://github.com/haphap/MOSAIC-Agents/wiki)
- [Architecture](https://github.com/haphap/MOSAIC-Agents/wiki/Architecture)
- [Getting Started](https://github.com/haphap/MOSAIC-Agents/wiki/Getting-Started)
- [CLI Reference](https://github.com/haphap/MOSAIC-Agents/wiki/CLI-Reference)
- [Data Layer](https://github.com/haphap/MOSAIC-Agents/wiki/Data-Layer)
- [Self-Improvement](https://github.com/haphap/MOSAIC-Agents/wiki/Self-Improvement)
- [Chinese wiki / 中文文档](https://github.com/haphap/MOSAIC-Agents/wiki/zh-Home)

## Quick Start

Prerequisites:

- Python 3.10+
- Node.js 22+
- pnpm 11+
- uv
- `TUSHARE_TOKEN` for live A-share data
- LLM provider key for production runs, or `--fake-llm` for zero-cost smoke
  tests

```bash
git clone https://github.com/haphap/MOSAIC-Agents.git
cd MOSAIC-Agents

uv venv
uv pip install -e '.[data,trading,llm]'

cd mosaic-ts
pnpm install --frozen-lockfile

cd ..
cp .env.example .env
```

Run a full no-cost smoke cycle:

```bash
cd mosaic-ts
pnpm dev daily-cycle --cohort cohort_default --fake-llm
pnpm dev dashboard
```

## Common Commands

All development CLI commands run from `mosaic-ts/`:

```bash
# Daily 25-agent cycle
pnpm dev daily-cycle --cohort cohort_default --fake-llm

# Scorecard and Darwinian weights
pnpm dev scorecard --cohort cohort_default --since 2024-01-01
pnpm dev darwinian --cohort cohort_default

# Prompt self-improvement
pnpm dev autoresearch trigger --cohort crisis_2008 --fake-llm --eval-days 5
pnpm dev autoresearch log --cohort crisis_2008

# Regime training and meta-weighting
pnpm dev prism list
pnpm dev janus weights

# Synthetic forward scenarios
pnpm dev mirofish generate --swarm --seed 7
pnpm dev mirofish train --fake-llm --path-aware

# Paper trading and dashboard
pnpm dev paper account
pnpm dev dashboard
```

Build the packaged CLI:

```bash
cd mosaic-ts
pnpm build
pnpm start -- --help
```

## Architecture

```text
TypeScript front end (mosaic-ts/)     JSON-RPC over stdio     Python sidecar (mosaic/)
────────────────────────────────     ───────────────────     ───────────────────────
CLI + Ink TUI                                                 bridge handlers
LangGraph 4-layer graph                                      dataflows / tools
LLM providers                                                scorecard / autoresearch
agent schemas + prompts                                      prism / janus / mirofish
                                                               backtest / paper trading
```

Repository map:

```text
MOSAIC-Agents/
├── mosaic/                 Python sidecar, data, scoring, backtest, paper trading
├── mosaic-ts/              TypeScript CLI, TUI, LangGraph agents, bridge client
├── prompts/mosaic/         Public baseline prompts and cohort skeletons
├── docs/wiki/              Source docs for GitHub Wiki / Pages
├── scripts/                Prompt leak and drift checks
├── tests/                  Python tests
└── .github/workflows/      CI and Pages workflows
```

Key design rule: no DataFrames cross the language boundary. Bridge calls pass
JSON in and return JSON out.

## Prompt Assets

The public repository contains baseline prompts needed to understand and run the
system. Optimized production prompts should live in a separate private prompt
repo and be loaded through the private-repo path, not committed here.

Useful checks:

```bash
cd mosaic-ts
pnpm prompt:check
pnpm prompt:drift -- --base-ref origin/main
pnpm dev prompts verify-release --help
```

## Verification

```bash
# Python
uvx ruff@0.15.15 check mosaic tests
uv run python -m pytest tests/ -q

# TypeScript
cd mosaic-ts
pnpm typecheck
pnpm lint
pnpm test
pnpm prompt:check
```

## Contributing

Issues and PRs are welcome. Keep PRs focused, include verification output, and
prefer opt-in behavior for new capabilities. For larger changes, start from the
architecture and CLI reference pages in the wiki.

## License

Apache License 2.0. See [LICENSE](LICENSE).

Acknowledgments: [ATLAS](https://github.com/general-intelligence-capital/atlas),
[Qlib](https://github.com/microsoft/qlib),
[LangChain](https://github.com/langchain-ai/langchain),
[LangGraph](https://github.com/langchain-ai/langgraph),
[Tushare](https://tushare.pro/), [akshare](https://akshare.akfamily.xyz/),
and [FRED](https://fred.stlouisfed.org/).
