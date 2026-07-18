# Agents

MOSAIC runs 28 logical Agents across four layers and 29 accepted-or-skipped
execution stages. CIO has proposal and final stages; every other logical Agent
has one stage. The canonical roster is `AGENTS_BY_LAYER`, and the committed
runtime contract is
`registry/prompt_checks/runtime_agent_manifest_v3.json`.

## Layer 1 — Macro (10)

`china`, `us_economy`, `eu_economy`, `central_bank`,
`us_financial_conditions`, `euro_area_financial_conditions`, `commodities`,
`geopolitical`, `market_breadth`, `institutional_flow`.

All ten accepted transmissions are consumed independently. `macro_input_gate`
requires the complete named set; there is no Macro consensus, stance, or
factor-group aggregate. See [Macro Agent role contracts](../macro_agent_role_contracts.md).

## Layer 2 — Sector and relationships (10)

Nine standard Sector Agents are `semiconductor`, `technology`, `energy`,
`biotech`, `consumer`, `industrials`, `real_estate_construction`, `financials`,
and `agriculture`. `relationship_mapper` is the tenth Layer-2 Agent.

Each standard Sector compares only its registered sub-industry directions over
the frozen PIT universe. It runs direction research, one conflict-only review
when required, and a separate final selection. The accepted result contains one
preferred direction, an eligible least-preferred direction when the deterministic
audit requires it, constrained long/short-or-avoid picks, drivers, risks,
claims/evidence, and ten Macro attributions. It does not emit a multi-industry
score. Direction ETF price/share-flow evidence is supplemental confirmation;
missing optional ETF evidence does not become a negative vote.

## Layer 3 — Superinvestor (4)

`druckenmiller`, `munger`, `burry`, and `ackman` apply distinct philosophy
filters to the runtime-frozen candidate set. They call only
`get_superinvestor_candidate_snapshot`, cannot expand the security domain, and
return either evidence-backed candidates or an explicit active abstention. An
empty pre-run opportunity set skips the stage and creates no Darwinian sample.

## Layer 4 — Decision (4, 5 stages)

The fixed sequence is:

`alpha_discovery → cio proposal → cro → autonomous_execution → cio final`.

Each role has a private snapshot tool and a dedicated outcome contract. CIO
proposal freezes the candidate target and pre-CIO lineage. CRO may only review
that proposal; Execution may only assess the CRO-adjusted order intents; CIO
final may not add a new candidate or replace the proposal snapshot. Decision
Agents are evaluated for KNOT evolution but never expose a downstream Darwinian
usage weight.

MiroFish remains simulation-only. RKE report context remains `RKE_SHADOW` only
and cannot enter production graph state, candidates, accepted output, Decision
input, labels, or Darwinian updates.

## Prompts and evolution

Production prompts live in the private repository as 448 bilingual variants:
8 cohorts × 28 Agents × 2 languages. Chinese files contain Chinese prose;
English files contain English prose; cohort lenses differ without encoding a
directional prior. Public bundled prompts are fake/offline fallbacks only.

The execution-behavior release manifest atomically binds all prompt hashes,
structured-output phases, tool policy, provider/model behavior, 16 active
production rosters, and KNOT baselines. Prompt text does not expose research
knobs, Darwinian ranks, label formulas, or KNOT thresholds.
