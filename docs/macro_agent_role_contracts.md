# Macro Agent role contracts

Layer 1 still contains ten Macro Agents and the daily graph still contains 25
logical agents / 26 execution stages. The current roles are `china`,
`us_economy`, `central_bank`, `dollar`, `yield_curve`, `commodities`,
`geopolitical`, `volatility`, `market_breadth`, and `institutional_flow`.
`emerging_markets` and `news_sentiment` are audit-only legacy records marked
`legacy_unverified`; their historical scores and Darwinian weights are not
carried into current roles.

The public run contract pins the rebuilt private prompt tree in
`registry/prompt_checks/macro_prompt_role_contract_manifest_v1.json`, including
the private commit and a path-and-content SHA-256 over all 160 prompts. The
digest consumes files in sorted relative-path order as UTF-8 path, NUL, raw
file content, NUL.

The code-owned role matrix, tool whitelist, uniform Zod output schema, and
generated prompt contract live in
`mosaic-ts/src/agents/macro/_contracts.ts`. Every role emits `direction`,
`strength`, `horizon`, `channels`, non-empty evidence claims and conclusion
references, key drivers, and confidence. Neutral means exactly strength zero;
non-neutral strength is 1–5.

## Prompt generation and cohort boundary

The bundled repository contains concise Chinese and English prompts for the
default cohort. They deliberately omit the private `research-knobs` fence and
knob-card details. The private prompt repository contains all 160 combinations
of ten roles, eight cohorts, and two languages. Run
`pnpm dev prompts sync-macro-prompts` to regenerate either tree from the same
code-owned role and tool contract.

Role, tool, schema, PIT, and knob metadata stay identical across cohorts. Each
cohort instead has a distinct, bilingual stress-test lens that tells the role
which failure mode to challenge without supplying a market prior or overriding
current evidence. This preserves meaningful cohort variation without reviving
the old cohort-specific role drift or hidden output contracts. Chinese prompt
prose is Chinese; schema field names, tool names, and evidence identifiers stay
unchanged so runtime binding remains exact.

## Point-in-time data boundary

Each role can call exactly one snapshot tool. Private snapshots are read from
`$MOSAIC_MACRO_SNAPSHOT_DIR/<as_of>/<role>.json` (or
`<role>.<as_of>.json`); the default is outside the repository under
`$MOSAIC_CACHE_DIR/macro_snapshots`. Missing snapshots fail closed. The runtime
does not silently query a second vendor. Every observation includes its series,
period, release time, vintage time, actual/previous/expected values, unit,
source, PIT status, and evidence ID. US historical revisions are accepted only
from the fixed ALFRED/official series map.

Tushare `major_news` and official policy documents are deduplicated,
timestamp-filtered events available only to `china` and `geopolitical`. Raw
news and licensed content remain private. OpenCLI search, Google/Caixin search,
and live Xueqiu follower counts are not formal macro-factor inputs.

Market breadth reads fixed local PIT tables from
`$MOSAIC_MARKET_BREADTH_DATA_DIR` (default
`$MOSAIC_CACHE_DIR/market_breadth`): `stock_basic`, `daily`, `adj_factor`, and
optional `suspensions`, each as Parquet or CSV. The deterministic builder
reconstructs historical listing/delisting status, requires 60 observations,
excludes known suspensions, uses only adjustment factors dated on/before the
as-of date, and rejects core coverage below 90%. Its composite equally weights
advance/decline, MA20/MA60 trend breadth, 20-day new highs/lows, and turnover
diffusion. State thresholds use rolling 252-day percentiles and a 20-day
change. Limit-up/down data is not part of the cross-period core.

## Six-group aggregation

The deterministic aggregator first computes per-agent transmission
`s_i = direction_sign × strength / 5` and effective reliability
`a_i = confidence_i × darwin_weight_i`. It then computes group direction and
reliability:

```text
G_g = sum(a_i * s_i) / sum(a_i)
R_g = sum(a_i) / number_of_agents_in_group
W_g = R_g / sum(R_h)
S   = sum(W_g * G_g)
```

The six groups are China economy, US economy, policy/liquidity, financial
conditions, exogenous/real shocks, and market confirmation. Dividing group
reliability by group size prevents larger groups from receiving an automatic
vote bonus. `S` retains the ±0.3 stance thresholds. Formal aggregation is
rejected unless all ten current roles have accepted outputs.

Darwinian ranking requires 30 role-matched, non-overlapping five-day samples;
otherwise the role weight is exactly 1.0. Market-breadth scoring is 50% the
subsequent five-day composite change and 50% the PIT equal-weight A-share
return relative to the benchmark.
