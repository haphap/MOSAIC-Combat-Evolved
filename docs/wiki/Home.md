# MOSAIC-CE Wiki

> 🌐 **语言 / Language:** **English** · [中文](zh/Home.md)

**MOSAIC-CE** (MOSAIC-Combat-Evolved) — an A-share self-improving multi-agent quantitative trading framework, inspired by ATLAS. It runs a hybrid architecture: heavy logic (numpy/pandas/git/SQLite/market data) lives in a **Python sidecar**; orchestration, LLM, CLI and TUI live in a **TypeScript front-end**. The two halves talk over **line-delimited JSON-RPC over stdio**.

> This wiki is generated from and cross-checked against the actual code. Where a fact comes from a specific file, the path is cited so you can verify it.

## Contents

- [Architecture](Architecture.md) — the hybrid sidecar/front-end split, the JSON-RPC bridge, repo layout.
- [Getting Started](Getting-Started.md) — install (uv + pnpm), optional extras, `.env`, first run.
- [CLI Reference](CLI-Reference.md) — every `pnpm dev <command>` and its subcommands.
- [Bridge RPC](Bridge-RPC.md) — the full `@method` surface by namespace.
- [Agents](Agents.md) — the 4-layer, 28-agent / 29-stage decision graph.
- [Data Layer](Data-Layer.md) — qlib local reader, ingest, vendored collectors, ETF routing.
- [Self-Improvement](Self-Improvement.md) — Autoresearch / PRISM / JANUS / MiroFish.
- [Scorecard & Paper Trading](Scorecard-and-Paper-Trading.md) — scoring, win-rate, Darwinian weights, the paper engine.
- [TUI](TUI.md) — the read/edit Ink dashboard and its tabs.
- [Configuration](Configuration.md) — `MosaicConfig`, persistence, env overrides.
- [Contributing](Contributing.md) — branch naming, the verification matrix, PR conventions.

## At a glance

| Aspect | Summary |
| --- | --- |
| Decision graph | 4 layers, 28 logical agents (10 macro → 10 sector → 4 superinvestor → 4 decision) across 29 execution stages, orchestrated by LangGraph.js as one daily cycle |
| Self-improvement | KNOT evolves private prompt behavior with paired shadow outcomes and atomic promotion; legacy ΔSharpe is audit-only |
| Multi-regime | PRISM covers 8 cohorts (default plus 7 market regimes); JANUS meta-weights across them |
| Reflexive sim | Real MOSAIC-Fish/OASIS by default, with explicit local Monte-Carlo and swarm engines |
| Backtest / paper | qlib two-stage vectorized backtest + a bespoke paper-trading engine (T+1, commission) |
| Languages | Python `≥3.10` sidecar · Node `≥22` + TypeScript front-end |
| License | Apache-2.0 (vendored qlib collector deps remain MIT — see [Data Layer](Data-Layer.md)) |

## Source of truth

The canonical design/phase document is [`mosaic-tsplan.md`](../plans/mosaic-tsplan.md) under `docs/plans/`. The READMEs ([root](../../README.md), [`mosaic-ts`](../../mosaic-ts/README.md)) cover quick usage. This wiki expands on both and keeps every claim tied to code.
