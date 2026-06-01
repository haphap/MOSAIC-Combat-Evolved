# Agents

MOSAIC runs **25 agents across 4 layers**, assembled into one daily cycle by LangGraph.js (`mosaic-ts/src/graph/daily_cycle.ts`). Each agent lives in `mosaic-ts/src/agents/<layer>/`; per-layer factories (`_factory.ts`) and schemas (`_schemas.ts`) are shared.

State flows layer by layer via per-layer maps in `mosaic-ts/src/agents/state.ts` (`layer1_outputs` … `layer4_outputs`, plus a top-level `portfolio_actions` mirror).

## Layer 1 — Macro (10)

`central_bank`, `china`, `commodities`, `dollar`, `emerging_markets`, `geopolitical`, `institutional_flow`, `news_sentiment`, `volatility`, `yield_curve`. (`_aggregator.ts` consolidates Layer-1 output.)

Layer-1 agents call sidecar tools (Tushare/akshare/FRED/Xueqiu/etc.) — e.g. `volatility` uses `get_ivx` + `get_etf_indicator(510050.SH)`; `emerging_markets` uses `get_etf_price_data`; `china` uses `get_property_data` (国房景气指数). The macro layer is 18 tools (see [Data Layer](Data-Layer.md) for the full list).

## Layer 2 — Sector (7)

`biotech`, `consumer`, `energy`, `financials`, `industrials`, `semiconductor`, `relationship_mapper`. They turn macro context into sector picks → the candidate universe.

The six industry agents share a common core of 8 tools — `get_industry_policy`, `get_xueqiu_heat`, `get_lhb_ranking`, `get_broker_research` (行业研报), `get_etf_holdings`, `get_stock_data`, `get_indicators`, `get_industry_moneyflow`. Sector-specific additions: `energy` also calls `get_fred_series`; `financials` also calls `get_yield_curve_cn`.

`relationship_mapper` works at the stock level and uses `get_lhb_ranking` + `get_stock_research` (个股研报).

## Layer 3 — Superinvestor (4)

`ackman`, `aschenbrenner`, `baker`, `druckenmiller`. Each applies an investing-philosophy lens to the Layer-2 candidate universe (they cite only tickers present in the upstream analysis — never invent codes). All four call `get_stock_research` (个股研报), `get_fundamentals`, `get_stock_data`, and `get_indicators`. `ackman` additionally calls `get_income_statement` / `get_cashflow` / `get_balance_sheet` (三张财报); `baker` calls `get_income_statement` / `get_cashflow`; `druckenmiller` calls `get_yield_curve_cn`.

## Layer 4 — Decision (4)

`cro`, `alpha_discovery`, `autonomous_execution`, `cio` (`mosaic-ts/src/agents/decision/`). Layer 4 is **synthesis-only** — no tool calls; each reads upstream state and reasons:

- **cro** — risk control / veto.
- **alpha_discovery** — alpha synthesis.
- **autonomous_execution** — turns decisions into trades (reads CRO + alpha + L3 + Darwinian weights).
- **cio** — final portfolio. Writes `layer4_outputs.cio` and mirrors `portfolio_actions` to the top level (single-writer). The CIO can recommend broad-based ETFs as well as stocks.

### MiroFish context injection (opt-in)

When `config.mirofish.inject_context` is true, the **CIO** prompt gets an appended MiroFish forward-looking section (latest scenario context, with a "simulation only" disclaimer and an `as_of_date` anti-lookahead bound). Off by default. See `maybeAppendMirofishContext` in `decision/_factory.ts`.

## Prompts

Prompts are bilingual and versioned per cohort under `prompts/mosaic/` — `cohort_default` plus the 7 regime cohorts (`cohort_bull_2007`, `cohort_crisis_2008`, `cohort_bull_2016`, `cohort_crisis_covid`, `cohort_recovery_2020`, `cohort_euphoria_2021`, `cohort_rate_tightening`). Autoresearch evolves these on git branches (see [Self-Improvement](Self-Improvement.md)).

Prompt language follows `config.output_language` (`pickPromptLanguage`: Chinese | English | Bilingual).
