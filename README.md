# MOSAIC-CE

> A-share self-improving multi-agent quantitative research framework.
> A 股自我改进型多智能体量化研究框架。

[![CI](https://github.com/haphap/MOSAIC-Combat-Evolved/actions/workflows/ci.yml/badge.svg)](https://github.com/haphap/MOSAIC-Combat-Evolved/actions/workflows/ci.yml)
[![Wiki](https://img.shields.io/badge/docs-wiki-0969da)](https://github.com/haphap/MOSAIC-Combat-Evolved/wiki)
![Python](https://img.shields.io/badge/Python-%E2%89%A53.10-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/Node-%E2%89%A522-339933?logo=node.js&logoColor=white)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

MOSAIC-CE (MOSAIC-Combat-Evolved) adapts the ATLAS-style four-layer
multi-agent trading architecture to the A-share market. It combines a Python
data/backtest sidecar with a TypeScript LangGraph front end, connected by
line-delimited JSON-RPC over stdio.

The project is designed for reproducible research loops: agents make daily
portfolio recommendations, results are scored, prompts evolve through git, and
changes are accepted or reverted by measured lift.

> Not financial advice. This repository is research infrastructure; use it with
> your own data-quality checks, risk controls, and compliance review.

## Highlights

- **28-agent decision graph**: 10 macro agents, 10 sector/relationship agents,
  4 superinvestor agents, and 4 decision agents (CRO / Alpha / Execution / CIO)
  run through 29 execution stages.
- **A-share data layer**: role-scoped PIT snapshots backed by registered
  Tushare and official macro sources, financial statements, market breadth,
  technical indicators, and ETF data. RKE research reports remain shadow-only.
- **Governed evolution loop**: KNOT paired research, Agent-owned deterministic
  outcome labels, and Darwinian usage weights with atomic promotion/rollback.
- **PRISM / JANUS / MiroFish**: regime-cohort training, cross-cohort
  meta-weighting, and synthetic forward scenarios.
- **Backtest and paper trading**: qlib replay, scorecard, Darwinian weights,
  T+1 paper-trading engine, and an Ink dashboard.
- **Prompt asset guardrails**: optimized/private prompts are designed to live
  outside the public repo; leak checks and release verification are wired into
  the toolchain.

## Documentation

- [Wiki home](https://github.com/haphap/MOSAIC-Combat-Evolved/wiki)
- [Architecture](https://github.com/haphap/MOSAIC-Combat-Evolved/wiki/Architecture)
- [Getting Started](https://github.com/haphap/MOSAIC-Combat-Evolved/wiki/Getting-Started)
- [CLI Reference](https://github.com/haphap/MOSAIC-Combat-Evolved/wiki/CLI-Reference)
- [Data Layer](https://github.com/haphap/MOSAIC-Combat-Evolved/wiki/Data-Layer)
- [Self-Improvement](https://github.com/haphap/MOSAIC-Combat-Evolved/wiki/Self-Improvement)
- [Chinese wiki / 中文文档](https://github.com/haphap/MOSAIC-Combat-Evolved/wiki/zh-Home)

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
git clone https://github.com/haphap/MOSAIC-Combat-Evolved.git
cd MOSAIC-Combat-Evolved

uv venv
uv pip install -e '.[data,trading,llm]'

cd mosaic-ts
pnpm install --frozen-lockfile

cd ..
cp .env.example .env
```

Optional parsed China policy database:

```bash
git clone https://github.com/haphap/china-policy-db.git ../china-policy-db
echo "MOSAIC_CHINA_POLICY_DB_DIR=$(pwd)/../china-policy-db" >> .env
```

If `MOSAIC_CHINA_POLICY_DB_DIR` is unset, the PBOC and gov.cn policy tools can
clone `haphap/china-policy-db` under `${MOSAIC_CACHE_DIR}/china-policy-db` on
first use. They read that local copy first, incrementally refresh stale local
data, and fall back to the existing official-site crawlers if clone/pull/refresh
is unavailable. Set `MOSAIC_CHINA_POLICY_DB_PUSH_UPDATES=1` only when this
machine should push refreshed data back to the policy-db remote.

Optional private prompt repo:

By default, agents load prompts from `MOSAIC-Combat-Evolved/prompts/mosaic`.
To make all agent runs prefer an external prompt repo, clone `MOSAIC-Prompts`
outside this checkout and configure it once in `.env`:

```bash
git clone https://github.com/haphap/MOSAIC-Prompts.git ../MOSAIC-Prompts
echo "MOSAIC_PROMPTS_REPO=$(pwd)/../MOSAIC-Prompts" >> .env
```

Optional private RKE registry repo:

Agents can consume a clean, committed snapshot of the gitignored Report
Intelligence JSON/JSONL registries from a separate private checkout. Clone the
private repo outside this checkout and configure its local path:

```bash
git clone <private-registry-remote> ../MOSAIC-Registries
echo "MOSAIC_REGISTRIES_REPO=$(pwd)/../MOSAIC-Registries" >> .env
uv run mosaic-rke registries-preflight --root .
uv run mosaic-rke hydrate-private-registries --root .
```

Keep generation in this checkout's ignored staging registry by passing
`--registry-dir registry/report_intelligence`, then export a stable snapshot.
The full pull, validate, export, commit, and push procedure is documented in
`docs/runbooks/rke_report_intelligence_operations.md`.

Run a full no-cost smoke cycle:

```bash
mkdir -p .mosaic/tmp
SMOKE_DATE="$(date +%F)"
SMOKE_ROOT="$(mktemp -d .mosaic/tmp/structured-smoke.XXXXXX)"
eval "$(uv run python scripts/build_structured_smoke_fixtures.py \
  --root "$SMOKE_ROOT" --date "$SMOKE_DATE" --shell-exports)"
pnpm --dir mosaic-ts dev daily-cycle \
  --cohort cohort_default --date "$SMOKE_DATE" --fake-llm
pnpm --dir mosaic-ts dev dashboard
```

## Common Commands

All development CLI commands run from `mosaic-ts/`:

```bash
# Daily 28-agent / 29-stage synthetic smoke: use the complete fresh-bundle
# sequence in "Run a full no-cost smoke cycle" above.

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
MOSAIC-Combat-Evolved/
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

The public repository contains only the 56 bilingual `cohort_default` baseline
prompts needed for fake/offline runs; non-default cohort directories are empty
skeletons. All seven non-default cohort behaviors and optimized production
prompts live in the private prompt repository and are loaded through the
private-repo path, never rendered or committed here.

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
