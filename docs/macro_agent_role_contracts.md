# Macro Agent role contracts v2

Layer 1 contains ten independent Macro Agents:

`china`, `us_economy`, `eu_economy`, `central_bank`,
`us_financial_conditions`, `euro_area_financial_conditions`, `commodities`,
`geopolitical`, `market_breadth`, and `institutional_flow`.

`dollar`, `yield_curve`, `volatility`, `emerging_markets`, and
`news_sentiment` are tombstoned. Historical rows remain readable only as
`legacy_unverified`; no old prompt, sample, identity, or Darwinian weight is
inherited by a new Agent.

The graph is China-centric. `central_bank` owns only the PBOC reaction
function, Chinese money markets, the Chinese nominal curve, and domestic
credit conditions. Fed policy, the US nominal and real curves, credit spreads,
the broad dollar, USD/CNY, US financial stress, and VIX are one external
transmission owned by `us_financial_conditions`. ECB policy, euro-area rates,
credit, the euro, and CISS are owned by
`euro_area_financial_conditions`. `us_economy` and `eu_economy` are entity-cycle
roles and cannot repeat those financial-condition votes. Chinese realized
volatility is a CRO risk input, not a Macro Agent.

The code-owned source of truth is
`mosaic-ts/src/agents/macro/_contracts.ts`. Every model submission uses the
strict common transmission schema with non-empty claims, conclusion-level
`claim_refs`, key drivers, and confidence. `NEUTRAL` requires `strength=0`;
non-neutral directions require strength 1–5. Runtime acceptance adds immutable
lineage, contract versions, deterministic data quality, and reliability
metadata; the model cannot submit those fields.

Numeric source facts may appear only as one typed
`snapshot_echo_id`/`snapshot_metric`/`snapshot_value` triple per claim; Macro
prose cannot carry numeric literals. A series-observation locator is derived
from its frozen series, period, release, and vintage identity and is never an
`evidence_id`. Unknown, incomplete, duplicate, altered, or runtime-owned echoes
fail closed, while `evidence_ids` continue to bind each claim to the separate
runtime evidence catalog.

## Direct downstream consumption

There is no six-factor bundle, Macro stance, `layer1_consensus`, or ±0.3
aggregate. `macro_input_gate` accepts a cycle only when all ten named Macro
outputs pass their contracts. Sector, Superinvestor, and Decision consumers
receive the ten transmissions independently, with one authoritative
`usage_share` per eligible upstream Agent and deterministic causal-evidence
resolution. Consumers may not compare, sum, or maximize upstream confidence.

Darwinian usage weights are applied at the consumer boundary, not by collapsing
the ten views. The atomic production release has 28 evaluation tracks and 24
usage-weight tracks: 10 Macro, 10 Sector/relationship, and 4 Superinvestor
sources have usage weights; CRO, Alpha, Execution, and CIO are
`EVOLUTION_ONLY` and have no weight row. Outcome labels are owned by each
Agent's registered evaluation object; CIO portfolio PnL never updates upstream
Agents.

For the seven composed Macro contracts, the initial/current component weights
are a versioned runtime contract rather than permanent constants. An
independent semiannual calibration workflow may fit a candidate, evaluate it
in shadow, and publish an append-only release with a prospective effective
time (or roll it back). Darwinian usage weights and private KNOT prompt
evolution do not directly modify component weights, and component calibration
does not expose private KNOT values.

## Data and tool boundary

Each Macro role calls only its zero-argument, role-scoped snapshot:

- `get_china_macro_snapshot`
- `get_us_macro_snapshot`
- `get_eu_macro_snapshot`
- `get_central_bank_snapshot`
- `get_us_financial_conditions_snapshot`
- `get_euro_area_financial_conditions_snapshot`
- `get_commodity_conditions_snapshot`
- `get_geopolitical_events_snapshot`
- `get_market_breadth_snapshot`
- `get_market_positioning_snapshot`

The bridge binds Agent, stage, date, frozen candidate scope, and snapshot bundle
to a signed single-use capability. A model cannot pass an Agent ID, date,
ticker, or scope into these tools, and tool calls read pre-materialized bundles
rather than collecting live data.

Observations carry series ID, observation period, release and vintage times,
actual/previous/expected values, unit, source, PIT status, and evidence ID.
Historical runs accept only information visible by `as_of`. US revisions use
the preregistered ALFRED/official mapping; EU and euro-area sources use frozen
Eurostat/ECB keys; World Bank data is `CONTEXT_ONLY`. Missing required coverage
fails closed and is never converted to a neutral signal.

`mosaic/dataflows/official_macro_adapters.py` implements the closed, allowlisted
Eurostat, ECB, and World Bank transports. The committed
`registry/data_sources/official_macro_source_preflight_v1.json` contains only
request metadata, row counts, content hashes, and readiness status; provider
rows are not committed. A successful live request proves transport/schema
compatibility only. Until an append-only release/vintage ledger can prove
`released_at` and `vintage_at` at the requested `as_of`, EU/euro-area production
snapshots remain fail-closed.

The same operational gate applies to every required China, US, PBOC, US
financial-conditions, commodity, and institutional-flow branch. Public source
maps register identity and ownership only; they are not ingestion receipts.
In the current checkout all eight generic Macro snapshot roles have explicit
source gaps, so formal construction is rejected until a registered adapter and
archived PIT/release-vintage proof exist. Only explicitly marked synthetic
smoke fixtures behind a non-production switch may bypass this gate.

Tushare `major_news`, `news`, `npr`, and `monetary_policy` are permission-denied
and have no runtime client or fallback path. `eco_cal` supplies timestamped
calendar events to authorized roles but cannot replace an official release or
geopolitical event-state source. OpenCLI, Caixin/Google search, live Xueqiu
attention, and RKE report context are not production inputs. RKE remains an
isolated shadow-only subsystem.

The geopolitical registry contains 14 required direct sources and one optional
ReliefWeb context source. `geopolitical_source_adapters.py` performs bounded,
allowlisted root-transport checks and commits metadata/hashes only. Root access
does not prove route-complete no-event coverage: source-specific pagination,
publication-time parsing and 30 continuous days of health evidence must all
pass before the manifest can move from `PREFLIGHT_REQUIRED` to
`ACTIVE_VERIFIED`; until then the geopolitical snapshot is rejected.
The current checkout has no built-in source-specific page parser and no
verified continuous-preflight receipt reader. Its caller-supplied parser hook
is an explicitly non-production test harness; rows produced by that hook are
marked ineligible for formal coverage. Therefore all required geopolitical
sources remain fail-closed even if a root transport probe succeeds or a local
manifest is manually rehashed.
The private audit retains every route/query/source row. The model-visible role
snapshot contains only verified event records, source readiness, and exact
per-event-family coverage counts/hashes, keeping transport diagnostics outside
the 128K inference context without weakening the no-event proof.

`scripts/build_structured_smoke_fixtures.py` can build an explicitly marked
`SYNTHETIC_NON_PRODUCTION` PIT bundle for fake- or real-model 29-stage contract
smoke. The builder accepts only a fresh empty root; a closed inventory binds
every fixture-relative path and content hash to the caller-supplied bundle
hash. It contains no vendor prose and cannot be read by production as a source
release. Passing that smoke proves structured-output, graph, and scoped-tool
wiring only; the live Tushare permission/schema probe and every source-specific
readiness/coverage audit remain separate fail-closed gates.

Market breadth is calculated deterministically from PIT A-share membership and
prices. It rejects coverage below 90%, applies only adjustment factors known by
`as_of`, and reports participation, MA20/MA60 breadth, new-high/new-low balance,
turnover diffusion, dispersion, concentration, eligible/observed counts, and
coverage. The model interprets the frozen metrics; it does not calculate them.

## Prompt and release boundary

The public tree contains exactly 56 concise bilingual `cohort_default` prompts
for fake/offline use. Its seven non-default cohort directories contain only
skeleton markers; public renderers and generators reject requests for their
model-visible behavior. Production loads all eight cohorts from the pinned
private prompt repository. Private prompt files contain the cohort stress-test
lenses, while research knobs, Darwinian ranks, KNOT thresholds, endpoint
catalogs, and handwritten JSON schemas remain runtime-private.

`registry/prompt_checks/execution_behavior_release_manifest_v1.json` atomically
binds all 448 private variants (8 cohorts × 28 Agents × 2 languages), the 16
active cohort/language production rosters, prompt and immutable-block hashes,
ordered structured-output phase bindings, tool-policy hashes, and KNOT champion
baselines. `agent_prompt_role_contract_manifest_v2.json` pins the same private
commit and release ID/hash. Production fails closed on a missing file, commit,
content, language, provider/model, schema, tool, or release mismatch.
Release and token-budget builders resolve every recorded Git revision and reject
tracked or untracked changes inside the measured prompt subtree. Unrelated
working-tree changes outside that subtree do not invalidate the attribution;
model-visible bytes are read from the verified Git objects, not mutable files.
