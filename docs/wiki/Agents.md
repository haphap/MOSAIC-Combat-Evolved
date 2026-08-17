# Agents

MOSAIC runs 25 logical Agents across four layers and 26 accepted-or-skipped
execution stages. CIO has proposal and final stages; every other logical Agent
has one stage. The canonical stage roster is `DAILY_CYCLE_STAGE_ROSTER`, and
the committed runtime contract is
`registry/prompt_checks/runtime_agent_manifest_v5.json`.

## Layer 1 — Macro (8)

`china`, `us_economy`, `eu_economy`, `central_bank`,
`us_financial_conditions`, `euro_area_financial_conditions`, `commodities`,
and `institutional_flow`. The historical `geopolitical` and `market_breadth`
Agents are retired and are not in the current roster.

All eight accepted transmissions are consumed independently. `macro_input_gate`
requires the complete current named set; there is no Macro consensus, stance,
or factor-group aggregate. See [Macro Agent role contracts](../macro_agent_role_contracts.md).

## Layer 2 — Sector (9)

Nine standard Sector Agents are `semiconductor`, `technology`, `energy`,
`biotech`, `consumer`, `industrials`, `real_estate_construction`, `financials`,
and `agriculture`. The historical `relationship_mapper` Agent is retired and
is not in the current roster.

Each standard Sector compares only its registered sub-industry directions over
the frozen PIT universe. It runs direction research, one conflict-only review
when required, and a separate final selection. The accepted result always
contains one preferred direction and one distinct least-preferred direction,
constrained long/short-or-avoid picks, drivers, risks, claims/evidence, all eight
required Macro submission summaries for the current eight Macro Agents, and any applicable target-level Macro
attributions. If one conflict review cannot produce a unique best/worst pair,
the stage rejects. It does not emit a multi-industry score. Direction ETF
price/share-flow evidence is supplemental confirmation; missing optional ETF
evidence does not become a negative vote.

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
Agents are evaluated for Prompt evolution but never expose a downstream Darwinian
usage weight.

MiroFish remains simulation-only. RKE report context remains `RKE_SHADOW` only
and cannot enter production graph state, candidates, accepted output, Decision
input, labels, or Darwinian updates.

## Structured-smoke lineage

Fixture-local `structured-smoke:accepted:*` references and runtime
`structured-smoke-accepted-output:*` references are different identity domains.
For a Sector candidate, the fixture payload first uses its own id/hash pair to
identify exactly one Sector Agent. The runtime state is then joined by
`STANDARD_SECTOR_SELECTION:<agent>`, followed by verification that the actual
accepted Layer-2 output contains exactly one `LONG` pick for the candidate
ticker. A ticker-only match is insufficient, and fixture-local id/hash values
must not be compared exactly with runtime id/hash values across those domains.

## Non-production acceptance record

The 2025-06-17 structured-smoke acceptance completed all 25 logical Agents and
all 26 stages from an exact empty portfolio (`[]`). Its non-production decision
was `512480.SH` `BUY`/`ADD` with target weight `0.04` and cash weight
`0.96`; CRO was `NO_OBJECTION`, execution was feasible, the final gate was
`PASS`, and `production_eligible=false`. This is an integration-contract
record, not a live or paper-trading recommendation.

## Prompts and evolution

Production prompts live in the private repository as 400 bilingual variants:
8 cohorts × 25 Agents × 2 languages. Chinese files contain Chinese prose;
English files contain English prose; cohort lenses differ without encoding a
directional prior. The public tree contains only 50 bilingual `cohort_default`
fake/offline prompts; public code cannot render the seven private cohort lenses.

The execution-behavior release manifest atomically binds all prompt hashes,
structured-output phases, tool policy, provider/model behavior, 16 active
production rosters, and Prompt execution baselines. Prompt text does not expose
mutator policy, Darwinian ranks, label formulas, or promotion thresholds.
