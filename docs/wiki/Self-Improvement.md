# Self-Improvement

MOSAIC separates two mechanisms that must not be conflated:

- Darwinian v2 evaluates all 28 logical Agents. It supplies downstream usage
  weights only for the 24 non-Decision Agents; CRO, Alpha, Execution, and CIO
  are evolution-only.
- KNOT is the only production prompt-behavior evolution and promotion path.

## Darwinian v2

Each Agent has a role-specific evaluation object, deterministic PIT label,
maturity horizon, and rank scope. A score updates only the owning Agent track;
CIO portfolio P&L is never copied backward to upstream Agents. New Agent IDs
start with zero mature evaluation samples, and the 24 usage-weight tracks start
from an isolated weight of 1.0.

Macro outputs remain ten independent transmissions. Downstream consumers receive
the accepted output, evidence lineage, operational reliability, and the owning
usage weight directly. There is no six-factor bundle or Macro stance. Decision
Agents receive explicit control DTOs without usage weights.

Component weights inside multi-component Agents are a separate, fixed runtime
contract. Offline component calibration can propose a shadow release, but
Darwinian and KNOT cannot mutate those weights.

## KNOT paired evolution

KNOT selects one mature track within its registered scope and proposes a minimal
change to the private prompt's cohort-behavior block. It cannot change roles,
tools, schemas, labels, component weights, immutable stage instructions, data
catalogs, or scoring thresholds.

Champion and candidate run against the same frozen snapshot bundle, tool
payloads, opportunity set, and realized market observation. They use distinct
capabilities and produce distinct outputs, labels, and scores. Agent failures
score `-2`; common exogenous exclusions do not score; asymmetric inputs fail the
pair contract.

CIO pairs run a special control-shadow subgraph. Alpha is sampled once and
reused by both sides; each side then runs its own proposal → CRO → Execution →
CIO-final chain. Alpha/CRO/Execution control calls are
`KNOT_CONTROL_SHADOW`, production-reliability-ineligible, and cannot create
their own outcome labels, Darwin maturity, usage weights, or KNOT scores.
Dependency failures block and consume the pair slot without assigning CIO a
`-2`; only CIO proposal/final failures are attributed to CIO.

Promotion requires at least 30 accountable non-overlapping pairs plus the
registered statistical, reliability, holdout-regime, and safety gates. A
multi-variant mutation publishes atomically: any failed target rejects the whole
batch. The promoted behavior starts a new future production roster revision and
an empty evaluation track. The first 20 mature post-promotion pairs can trigger
a prospective rollback.

Prompt-release traffic still enters through a bounded `canary` and uses
`rollback` on failure; neither operation changes KNOT pairing, attribution, or
promotion semantics.

## Prompt and release boundary

Production loads the pinned private release containing 8 cohorts × 28 Agents ×
2 languages = 448 prompts. Bundled prompts are minimal fake/offline fallbacks
and never serve as KNOT champions. Runtime contracts, research controls, KNOT
metadata, provider bindings, and tool payloads stay outside model-visible prompt
text.

The old Delta-Sharpe Autoresearch path is diagnostic/historical only. Evaluation
returns `legacy_unverified`; direct keep/merge is disabled, and manual domain
review can only record a rejection. Historical backtest evolution uses an
isolated sandbox branch and has no edge to the active production release.

See [Macro Agent Role Contracts](../macro_agent_role_contracts.md) and the
[position-aware evolution runbook](../runbooks/position_aware_prompt_evolution.md)
for contract and operating details.
