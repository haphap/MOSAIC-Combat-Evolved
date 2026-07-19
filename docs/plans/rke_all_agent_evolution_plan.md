# Part 2: RKE All-Agent Evolution Plan

> **Scope note (2026-07):** This document remains historical design context for
> shadow-only RKE research. Its Agent roster, runtime prompt consumption, and
> production evolution/promotion sections are superseded by
> `docs/plans/macro-agent-role-contracts-v2-plan.md`. RKE has no production
> prompt or trading promotion edge in the v2 runtime.

## Purpose

This plan owns the follow-up work that starts after the stock, industry, and
macro report-feedback loops exist: all MOSAIC agents should consume redacted RKE priors, emit
auditable claims/footprints, and evolve through private prompt repo changes,
autoresearch, Darwinian weights, replay, and gated rollback.

It intentionally depends on Part 1,
`docs/plans/rke_macro_report_feedback_and_agent_evolution_plan.md`, for the
stock/industry/macro report-feedback, rating, PIT label, privacy, redacted ranked
context/export contract, and prior-to-candidate compiler/refusal contract. That
plan remains the source of truth for report-derived feedback semantics and
ranked RKE exports; this plan is the source of truth for all-agent runtime
consumption, private prompt repo evolution, benchmark, replay, and rollback.

## Non-Negotiable Boundaries

- RKE priors are research context only; they are not current data and cannot
  directly create trades.
- LLMs may generate agent reasoning, claims, methods, and structured outputs;
  they do not label correctness.
- Correctness comes from deterministic PIT outcome labels, gold sets, or
  operator-approved review.
- Report-intelligence derived artifacts are local/private by default. Public
  repo commits may include code, schemas, tests, docs, and minimal fallback
  prompts only.
- Complete prompt content, prompt mutation candidates, prompt hashes, prompt
  drift review, and prompt evolution live in the private prompt repo.

## Execution Wiring Required To Satisfy Purpose

Readiness gates are consumers, not producers. This plan satisfies its purpose
only when actual benchmark/replay/prompt-evolution runs produce the evidence
below and `rke_benchmark.delivery_readiness` returns `ready` for the same
`benchmark_run_id`.

Required producers:

- Prompt provenance producer: `prompts.preflight`, `prompts.audit_versions`,
  `prompts.verify_release`, and leak/drift checks produce private prompt pins,
  release refs, and no-body release evidence.
- Prompt content producer: rewrites the formal private prompt corpus for all
  canonical MOSAIC agents, validates the role/task contract, schema contract,
  RKE-prior contract, audit/footprint contract, and autoresearch evolution
  contract through the prompt contract checker, then emits no-body
  `prompt_contract_check_ref` evidence. Prompt bodies stay in the private prompt
  repo.
- Fixed-episode benchmark producer: runs the E2 episodes for every as-of date,
  all 25 agents, and required model configs using private prompt pins. It writes
  paired output refs, schema validation, deterministic score tables, investment
  outcome tables, quality-gate summary, and manual-review refs.
- Runtime RKE context producer: injects Part 1 ranked context into every agent
  path that can use report priors, preserving `retrieval_rank`,
  `priority_bucket`, `ranking_policy_id`, context hash, truncation audit, and
  current-data confirmation. Decision agents may consume direct RKE context or
  upstream redacted RKE context summaries, but their footprint rows must still
  identify which context hashes affected portfolio/risk/action claims.
- Agent footprint producer: converts each agent output into redacted
  claim/footprint rows and calls
  `rke_benchmark.capture_agent_claim_footprints`. Rows must contain no prompt
  body, report prose, source spans, URLs, or local paths.
- Prompt mutation producer: consumes Part 1 candidate/refusal rows through
  `rke_benchmark.candidate_consumption_manifest` and
  `rke_benchmark.prompt_mutation_lifecycle_manifest`, writes accepted prompt
  mutations only through `prompts.write(target=private_git)`, and records branch,
  prompt hash, release, leak/drift, benchmark, and review evidence.
- Autoresearch/Darwinian producer: consumes footprint summaries, RKE usage
  quality, downstream outcomes, prompt provenance, and rollback readiness, then
  writes update refs plus
  `rke_benchmark.darwinian_autoresearch_consumption_readiness` evidence. Input
  manifest readiness alone is not consumption.
- Replay, paper-trading, promotion, and rollback producer: runs shadow replay
  with pinned prompts/context/mutations, records paper-trading plan/result and
  monitor refs when allowed, and proves rollback trigger/procedure/monitor output
  before anything leaves shadow mode.

No E7 proof object may be hand-authored to bypass these producers. Staged runs
append their no-body refs through `rke_benchmark.record_delivery_evidence`; the
final audit is `rke_benchmark.delivery_evidence_audit` plus
`rke_benchmark.delivery_readiness`.

## Current Status

As of 2026-07-03:

- Stock, industry, and macro report feedback supports PIT outcome/readiness/profile
  paths; macro additionally supports parent macro claims, macro claim legs,
  direct series labels, macro agent priors, and RI-MACRO readiness gates.
- Layer-3 public runtime has been migrated to the canonical roster:
  `druckenmiller`, `munger`, `burry`, `ackman`.
- Public smoke/fallback prompts exist for all four superinvestors, but complete
  role-specific prompt upgrades for all 25 agents are still pending in the
  private prompt repo.
- The Python prompt bridge has to stay in sync with the TS canonical roster;
  this is part of the roster preflight, not an optional cleanup.

## Material Blockers To Actual Evolution

These are hard blockers, not documentation cleanup. Gates and manifests do not
close them; only producer runs and no-body evidence close them.

| Gap | Severity | Required closure |
| --- | --- | --- |
| Fixed-episode benchmark runner | Critical | A runnable E2 producer must execute the 8-episode / 17-date / 25-agent / required-model matrix, write paired output refs, capture footprints, record benchmark evidence, and pass `rke_benchmark.fixed_episode_benchmark_evidence` for the same `benchmark_run_id`. A manifest or evidence gate alone is not enough. Internal design is E2.1. |
| Replay execution engine | Critical | A shadow replay producer must replay pinned prompts, RKE context, mutations, Darwinian weights, and downstream outcome windows, then record replay refs consumed by `shadow_replay_readiness`, `paper_trading_readiness`, promotion, and rollback gates. Readiness gates alone are not runnable replay. Internal design is E7.1. |
| Darwinian/autoresearch compute | High | A compute producer must turn footprint summaries, RKE usage quality, current-data confirmation, downstream outcomes, schema/privacy reliability, and prompt provenance into weight/update refs consumed by `darwinian_autoresearch_consumption_readiness`. Uniform or stub weights do not close E5. Internal design is E5.1. |
| Prompt contract checker | High | A no-body checker must validate formal private prompt content and emit `prompt_contract_check_ref` rows before E0.5, E2, E4, or E7 can consume prompt contracts. Referencing `prompt_contract_check_ref` without this producer is invalid. |
| TS RKE context path | Medium | Tool-based consumption through `get_rke_research_context` is the canonical TS path. A direct TS bridge RPC is optional, but the plan must document that choice and the benchmark/replay producers must still record consumed context hashes, ranking metadata, truncation audit, and current-data confirmation. |
| Formal private prompt corpus | Medium | E0/E0.5 remain open until the private prompt repo contains rewritten, contract-checked, bilingual prompts for every formal canonical agent prompt file, with provenance, release, leak/drift, and `prompt_contract_check_ref` evidence. Fallback prompts do not count. |

## Critical Path And Execution Owner

All formal E1-E7 execution is gated on E0 prompt provenance. The public bridge
preflights can report blockers, but they cannot substitute for complete private
prompt content. As of this plan revision, complete private prompt repo rows are
still the critical path for all 25 benchmark/replay agents × 2 languages; the
pending Munger/Burry role-specific private prompt upgrades are part of that
blocker. Until E0 returns ready private prompt rows with release, audit-version,
and leak/drift evidence, E2-E7 can only produce blocked proof objects.

The E2 fixed-episode benchmark also requires a named execution engine. The
`rke_benchmark.*` bridge methods are no-write validators and evidence sinks;
they do not run LLMs. The formal executor must be a TS benchmark harness that
wraps `buildDailyCycleGraph` / the existing `daily-cycle` run primitive, applies
`prompts.preflight`, iterates the fixed E2 manifest across 17 as-of dates, all
25 agents, and the required model configs, and records no-body output/evidence
refs under `.mosaic/rke/all_agent_evolution/` for later validation by
`rke_benchmark.fixed_episode_benchmark_evidence` and `delivery_readiness`.
`mosaic-ts/src/cli/commands/backtest.ts` can support portfolio replay and
outcome measurement, but it is not sufficient by itself to close E2 because E2
needs per-agent/date/model paired LLM outputs, prompt pins, context hashes,
schema results, and deterministic score refs. If that dedicated fixed-episode
harness has not been implemented or configured for a run, E2 is blocked with
`benchmark_runner_missing`.

E2 runner implementation estimate:

- Effort: XL for a closeable runner because it must cover manifest iteration,
  model config switching, prompt-source preflight, per-agent/date/model retries,
  timeout isolation, schema validation capture, no-body output refs,
  deterministic score table generation, investment outcome table generation, and
  delivery evidence recording. A smaller L-sized script that only loops through
  `daily-cycle` dates is useful for smoke testing but cannot close E2.
- Required dependencies: `buildDailyCycleGraph`, the prompt-source override path
  used by `daily-cycle`, canonical `AGENTS_BY_LAYER`, the E2 episode/as-of-date
  manifest, model config resolution, agent output schema validators,
  `.mosaic/rke/all_agent_evolution/` evidence sinks, and a PIT outcome/replay
  source for investment outcome tables.
- Required failure reporting: each blocked or failed row must identify
  agent/language/as-of-date/model config, prompt provenance status, timeout or
  exception class, schema validation status, and whether an output ref was
  produced. Whole-run failure must not hide per-agent failures.

Canonical benchmark roster:

The authoritative runtime roster is `AGENTS_BY_LAYER` in
`mosaic-ts/src/agents/prompts/cohorts.ts`. E0/E2 gates should treat drift between
this list, prompt files, Python bridge routing, and private prompt provenance as
roster-preflight blockers.

| Layer | Agents | Count |
| --- | --- | --- |
| macro | `central_bank`, `geopolitical`, `china`, `dollar`, `yield_curve`, `commodities`, `volatility`, `emerging_markets`, `news_sentiment`, `institutional_flow` | 10 |
| sector | `semiconductor`, `energy`, `biotech`, `consumer`, `industrials`, `financials`, `relationship_mapper` | 7 |
| superinvestor | `druckenmiller`, `munger`, `burry`, `ackman` | 4 |
| decision | `cro`, `alpha_discovery`, `autonomous_execution`, `cio` | 4 |

## E0: Prompt Repo And Roster Preflight

Before any benchmark or replay:

- Canonical superinvestor roster must be
  `druckenmiller`, `munger`, `burry`, `ackman` in TS runtime, Python bridge
  prompt routing, RKE style-fit, tests, docs, and fallback prompts.
- Canonical private prompt repo identity is
  `https://github.com/haphap/MOSAIC-Prompts`.
- Formal benchmark/replay must have git-backed prompt provenance. Prefer
  `MOSAIC_PROMPTS_REPO` or `MOSAIC_PRIVATE_PROMPT_REPO` pointing at a local clone
  of `https://github.com/haphap/MOSAIC-Prompts`.
- `MOSAIC_PROMPTS_ROOT` is allowed for formal runs only if the direct
  `prompts/mosaic` path is inside a git worktree. The discovered git top-level
  is used only to prove worktree provenance and derive prompt-relative paths;
  formal rows still record the canonical/env private prompt repo identity as
  `prompt_repo_id`, the HEAD commit as repo revision, the prompt file path
  relative to that worktree, and the prompt hash. If those fields cannot be
  recovered, the row is blocked with `private_prompt_unavailable` or
  `prompt_provenance_unavailable`.
- Formal benchmark/replay must use private prompt repo prompts. Bundled prompts
  are smoke/fallback only.
- Each resolved prompt must record:
  `prompt_repo_id`, repo revision, file path, prompt hash, resolved source, and
  `fallback_used=false`.
- If a private prompt is missing, the agent/date/model row is blocked with
  `private_prompt_unavailable`; it cannot count as paired benchmark output.

Prompt freeze mechanics:

- Python bridge writes to private prompt repos through `prompts.write` with
  `target=private_git`, returning `prompt_commit_hash` and `prompt_sha256`.
- Release checks use `prompts.verify_release`.
- Leak/drift checks must pass before a prompt hash can be used in formal
  benchmark or replay.
- Replay records the prompt hash and repo revision, not the prompt body.

Status 2026-07-03:

- Public bridge now exposes `prompts.preflight`, a no-body formal-run preflight
  that resolves private prompt provenance for requested agents/languages. It
  requires `MOSAIC_PROMPTS_REPO` / `MOSAIC_PRIVATE_PROMPT_REPO`, or a git-backed
  `MOSAIC_PROMPTS_ROOT`, records `prompt_repo_id`, HEAD revision, relative prompt
  file path, prompt sha256, resolved source, and `fallback_used=false`. Dirty
  private prompt repos are blocked because a working-tree prompt hash paired
  with HEAD revision is not a reproducible formal prompt pin. The returned
  source summary includes blocked reason, resolved source, repo id/revision and
  dirty-file count, but never prompt body or dirty file paths.
- Missing private prompts or missing git provenance return blocked rows with
  `private_prompt_unavailable`, `prompt_provenance_unavailable`, or
  `private_prompt_repo_dirty`; bundled prompts are not used as fallback for
  formal rows.
- Public bridge now exposes `rke_benchmark.all_agent_prompt_provenance_readiness`,
  a no-write all-agent gate that requires all 25 agents × 2 languages to have
  private prompt pins plus per-prompt audit-version, release, and leak/drift
  evidence before formal benchmark/replay can treat prompt provenance as ready.
  Release evidence must match the private `prompt_repo_id`,
  `prompt_repo_revision`, and prompt file path returned by `prompts.preflight`;
  it must include a positive integer prompt version id. Shadow/delivery aggregate
  gates also require it to bind to the same `benchmark_run_id`. The gate
  preserves the preflight source summary so E7 blockers include repo-level dirty
  state, not only repeated row-level prompt blockers.
- This implements the public E0 preflight mechanism. E0 is not fully closed
  until the private prompt repo has ready rows for all benchmark/replay agents
  and leak/drift/release checks have passed.

## E0.5: Formal All-Agent Prompt Design Contract

This section owns the prompt content work. Public MOSAIC-RKE must not commit the
formal prompt bodies. The private prompt repo is the source of truth for the
rewritten prompt corpus; public proof is limited to prompt hashes and no-body
check refs.

Rewrite scope:

- Rewrite every formal Markdown prompt under
  `https://github.com/haphap/MOSAIC-Prompts` for the canonical 25-agent roster:
  all `cohort_default` prompts and every formal `cohort_*` prompt used by
  benchmark, replay, autoresearch, or paper trading.
- Each canonical agent must have synchronized `zh` and `en` prompts. The two
  language files must preserve the same role, workflow, schema, RKE-prior rule,
  audit rule, confidence policy, and evolution boundaries.
- Legacy/non-canonical prompt files, such as old superinvestor roster files, do
  not count as formal prompt coverage unless the TS/Python canonical roster is
  explicitly changed. They may remain historical, but formal benchmark/replay
  must ignore them.
- Shared private prompt contracts, overlays, rendered prompt outputs, and prompt
  IR may be regenerated as needed, but no prompt body or private prompt path is
  committed to MOSAIC-RKE.

Every formal agent prompt must contain these sections:

- Role boundary: exact agent id, layer, downstream consumer, and decisions the
  agent is not allowed to make.
- Required inputs and tools: required current-data tools, upstream state
  dependencies, fallback behavior when a required tool is unavailable, and the
  rule that missing current data caps confidence.
- RKE prior policy: `get_rke_research_context` or injected RKE context is a
  redacted research prior only. It may guide questions, ranking, and hypothesis
  formation; it cannot replace current PIT data or directly create a trade.
- Workflow: ordered steps for evidence collection, contradiction handling,
  current-data confirmation, role-specific reasoning, and final structured
  output.
- Output schema: exact JSON shape and field names expected by the runtime Zod
  schema. Autoresearch must not rename, remove, or add schema fields.
- Audit and footprint contract: fields such as `key_drivers`, `thesis`,
  `philosophy_note`, `reason`, or `dissent_notes` must carry enough redacted
  evidence to map the output to claim type, target, confidence, current-data
  confirmation, stale/contradictory prior handling, RKE context hash, ranking
  policy id, retrieval rank, priority bucket, and truncation audit.
- Privacy boundary: never quote report prose, source spans, prompt body, local
  paths, URLs, reviewer text, or licensed source metadata in agent output.
- Confidence policy: high confidence requires fresh current data plus at least
  two independent evidence families; stale priors, missing tools, fallback data,
  or conflicting evidence impose explicit caps.
- Refusal and no-action behavior: if required data is unavailable or RKE prior
  cannot be confirmed, emit conservative/no-action output inside the existing
  schema instead of inventing evidence.
- Autoresearch evolution contract: list mutable prompt parameters and immutable
  guardrails.

Layer-specific prompt obligations:

- Macro agents must emit macro regime, macro series, policy, flow, or asset
  claims only within their own domain. They must distinguish research priors
  from current macro data and expose missing-data/fallback caps in
  `key_drivers`.
- Sector agents must connect macro regime, policy, flow, sector ETF/holdings,
  broker/RKE priors, price, and indicator evidence before selecting longs,
  shorts, or relationship risks. A sector prior alone cannot create a pick.
- Superinvestor agents must apply their philosophy filters to the L2 candidate
  universe and current stock evidence. RKE priors may expand or annotate the
  candidate set, but every pick needs current confirmation and a style-fit
  reason.
- Decision agents must synthesize upstream outputs and any direct redacted RKE
  context into risk, alpha, execution, and CIO actions. They must cite upstream
  or direct RKE context hashes that materially affected risk/action/dissent
  notes, and no trade may be created from RKE prior alone.

Agent-specific prompt task targets:

- `central_bank`: PBOC/Fed stance, liquidity operation changes, rate-change
  direction, policy-window timing, and dual-bank divergence.
- `geopolitical`: escalation level, hot zones, sanctions/export-control/trade
  channels, and sector transmission.
- `china`: domestic policy direction, industrial-policy focus, property/credit
  stress, and policy-supported/risk sectors.
- `dollar`: DXY trend, USD/CNY pressure, CN-US yield-spread linkage, and FX
  pressure handoff to EM/sector agents.
- `yield_curve`: China curve shape, CN-US 10Y spread, recession/stress signal,
  and tenor-specific BPS evidence.
- `commodities`: oil, metals, agriculture, and China-demand signals with current
  commodity and curve evidence.
- `volatility`: VIX/iVX/realized-vol regime, risk-on/off filter, and volatility
  confidence caps when China vol data is fallback.
- `emerging_markets`: HK/A-share relative strength, EM capital-flow proxy,
  dollar/spread sensitivity, and cross-market ETF evidence.
- `news_sentiment`: retail/news topic heat, sentiment score, topic/ticker
  clusters, and contrarian flag versus institutional flow.
- `institutional_flow`: main-fund/LHB flow, top buyers, sector in/out map, and
  flow concentration risk.
- `semiconductor`: semiconductor policy, supply chain, ETF/holdings, equipment,
  design, foundry, and export-control evidence.
- `energy`: oil/coal/power/new-energy links, commodity regime, policy pressure,
  flow, and sector longs/shorts.
- `biotech`: healthcare policy, volume-procurement risk, pipeline/approval
  signals, flow, and valuation discipline.
- `consumer`: demand, brand pricing power, channel/retail heat, policy support,
  and discretionary/staple split.
- `industrials`: capex cycle, automation, export exposure, infrastructure
  policy, and order/flow evidence.
- `financials`: bank/broker/insurer sensitivity to curve, liquidity, credit
  risk, policy, and market activity.
- `relationship_mapper`: supply chains, ownership/common-shareholder clusters,
  contagion paths, and cross-sector risk handoff.
- `druckenmiller`: macro-asymmetry, liquidity/regime fit, momentum with risk
  control, and tactical holding period.
- `munger`: quality moat, predictable compounding, balance-sheet strength,
  fair-price discipline, and long holding period.
- `burry`: deep value, downside protection, balance-sheet stress, catalyst, and
  crowding/contrarian evidence.
- `ackman`: concentrated quality, simple business, catalyst/control angle,
  pricing power, and medium/long holding period.
- `cro`: reject/flag upstream picks with correlation, liquidity, regulatory,
  leverage, valuation, or tail-risk problems.
- `alpha_discovery`: find cross-layer candidates missed by the four
  superinvestor filters and explain why they were missed.
- `autonomous_execution`: convert accepted picks into BUY/SELL/HOLD/REDUCE and
  `size_pct`, applying CRO rejects, alpha additions, and Darwinian weights.
- `cio`: produce final portfolio actions, target weights, holding periods,
  dissent notes, cash decision, and final confidence.

Autoresearch mutation constraints:

- Mutable: thresholds, weights, lookback windows, evidence ordering, tie-breaks,
  sector/topic filters, confidence caps within stricter safety bounds, and
  wording that improves extraction reliability.
- Immutable: agent id, role boundary, required output schema, required tools,
  current-data gate, RKE-prior-as-prior rule, privacy boundary, audit/footprint
  contract, and shadow/promotion safety policy.
- A mutation must be bilingual and semantically synchronized. It may rewrite a
  prompt file, but it must preserve required section headers, schema field names,
  no-source-prose rules, and all immutable guardrails.
- The autoresearch loop invariant must protect all E0.5 required sections and
  immutable guardrails, not only output schema/workflow headings. Any TS
  `assertPromptInvariants`-style fast check must use the same required-section
  list as E0.5 and must reject mutation text that weakens the RKE-prior policy,
  removes the privacy boundary, removes refusal/no-action behavior, or merges
  mutable and immutable boundaries.
- Prompt mutation release evidence must include a no-body contract check ref in
  addition to `prompts.verify_release` and leak/drift refs.

Acceptance:

- A formal benchmark/replay row cannot count a prompt unless it has private git
  provenance, audit-version evidence, verify-release evidence, leak/drift
  evidence, and `prompt_contract_check_ref` for the same prompt hash.
- The prompt contract checker must validate section coverage, exact schema field
  names, required tool policy, RKE-prior/current-data separation,
  audit/footprint language, privacy/no-source-prose rules, and mutable/immutable
  autoresearch boundaries without returning the prompt body.
- `rke_benchmark.all_agent_prompt_provenance_readiness` is not sufficient to
  close prompt readiness by itself until it also consumes prompt contract check
  refs, or a separate prompt-content readiness gate is added and bound into E7.
- Until the rewritten private prompt corpus and its no-body contract evidence
  exist for all formal canonical prompt files, E0.5 remains open and E7 cannot
  be marked complete.

## E0.6: Prompt Contract Checker Producer

`prompt_contract_check_ref` must come from a real checker, not from hand-authored
release metadata. This component is currently unimplemented and blocks E0.5,
E2, E4, and E7 until built.

Required public bridge surface:

- Add `prompts.contract_check` as a no-body Python bridge RPC.
- Inputs:
  - `cohort`
  - optional `agents` and `langs`, defaulting to all canonical agents and
    `zh`/`en`
  - `prompt_repo_id`, `prompt_repo_revision`, `prompt_file_path`, and
    `prompt_sha256` from `prompts.preflight` or release evidence
  - optional `benchmark_run_id`
- The handler may read prompt files from the private prompt repo or private
  prompt root, but it must never return prompt body, prompt excerpts, dirty file
  paths, local paths, report prose, source spans, URLs, or reviewer text.

Required checks per prompt row:

- Section coverage: role boundary, required inputs/tools, RKE prior policy,
  workflow, output schema, audit/footprint contract, privacy boundary,
  confidence policy, refusal/no-action behavior, and autoresearch evolution
  contract.
- Exact runtime schema field names for that agent and language.
- Required tool policy: every runtime-required tool is named, and missing-tool
  fallback plus confidence cap are present.
- RKE separation: prompt states that RKE context is a redacted research prior,
  not current data, and cannot directly create trades.
- Audit/footprint language: existing output fields can carry claim type, target,
  confidence, current-data confirmation, stale/contradictory prior handling,
  RKE context hash, `ranking_policy_id`, `retrieval_rank`, `priority_bucket`,
  and truncation audit.
- Privacy/no-source-prose: prompt forbids report prose, source spans, prompt
  body, local paths, URLs, reviewer text, and licensed metadata in outputs.
- Autoresearch boundary: mutable and immutable prompt elements are explicitly
  separated, and immutable guardrails include role boundary, schema, required
  tools, current-data gate, RKE-prior policy, privacy boundary, audit/footprint
  contract, and shadow/promotion safety policy.
- Bilingual sync: for `zh`/`en` pairs, the checker reports whether both language
  rows have the same required contract categories for the same prompt hash set.

Output contract:

- Return one row per checked prompt with:
  `agent`, `layer`, `lang`, `prompt_repo_id`, `prompt_repo_revision`,
  `prompt_file_path`, `prompt_sha256`, `prompt_contract_check_ref`,
  `benchmark_run_id`, `ready`, and redacted blocker codes.
- Return aggregate counts by layer, language, blocker code, and ready status.
- `prompt_contract_check_ref` must be deterministic for the checked prompt hash
  and contract version, for example:
  `prompt-contract:<contract_version>:<prompt_sha256>`.
- The checker must fail closed: missing prompt provenance, dirty private prompt
  repo, missing prompt file, schema-field drift, privacy leak risk, or missing
  immutable guardrail blocks the row.

Required tests before closing E0.6:

- Accepts a minimal valid private prompt row for each layer without returning
  prompt body.
- Blocks missing required section.
- Blocks missing runtime schema field.
- Blocks missing required tool/fallback/confidence-cap language.
- Blocks RKE prior treated as current data or trade trigger.
- Blocks private/prose/path/url leakage in returned rows.
- Blocks cross-run `benchmark_run_id` mismatch when supplied.
- Blocks bilingual drift where `zh` and `en` rows for the same agent do not have
  the same required contract categories, schema fields, tool policy, RKE/current
  data separation, privacy rule, and autoresearch boundary.
- Verifies the TS autoresearch loop fast invariant and the Python
  `prompts.contract_check` contract share the same required section categories
  and immutable guardrail names, so mutation acceptance and release gating cannot
  drift silently.
- Verifies `all_agent_prompt_provenance_readiness`,
  `prompt_mutation_release_readiness`, E2 benchmark evidence, and E7 delivery
  readiness consume contract-check refs rather than trusting raw release rows.

Required gate and delivery wiring before closing E0.6:

- `rke_benchmark.all_agent_prompt_provenance_readiness` must require
  `prompt_contract_check_ref` on every all-agent prompt release row and bind it
  to the same prompt hash, prompt repo id, prompt repo revision, prompt file
  path, and `benchmark_run_id`.
- `rke_benchmark.prompt_mutation_release_readiness` must require
  `prompt_contract_check_ref` on every prompt mutation release row before it can
  feed benchmark/replay.
- `rke_benchmark.fixed_episode_benchmark_evidence`, shadow replay, paper
  trading, promotion, rollback, and `delivery_readiness` must treat missing
  contract-check evidence as a hard blocker.
- Delivery evidence storage must be updated so contract-check refs are not lost.
  Chosen design: add top-level `prompt_contract_checks` evidence rows to the
  private delivery evidence store, and require all prompt release rows to point
  to one of those refs. This means updating the delivery evidence key list,
  value type map, list item identity fields, TS bridge types, and record/audit
  tests.

Status:

- Not implemented: no `prompts.contract_check` RPC, no Python checker, no TS type
  binding, and no tests exist yet.
- Until this producer exists, any `prompt_contract_check_ref` requirement in
  E0.5/E2/E4/E7 is an explicit blocker, not satisfiable evidence.

## E1: Runtime Consumption Of Part 1 Ranked RKE Context

Ownership split:

- Part 1 owns the redacted ranked context/export contract, including ranking
  keys, rank fields, truncation audit, and stock/industry/macro prior inputs.
- Part 2 owns all-agent runtime consumption of that ranked context: prompt/tool
  plumbing, runtime preflight, benchmark wiring, and replay evidence.
- The Python bridge / agent tools should consume already-ranked RKE context.
  TS should not re-rank except for display-only sorting.
- TS runtime consumption is intentionally tool-based:
  `get_rke_research_context` is exposed through the bridge tool path used by
  agent loops. A separate direct TS RPC is not required for agent correctness,
  but benchmark/replay producers still must record the same context hashes and
  ranking metadata as proof of consumption.

Required Part 1 inputs consumed by Part 2:

- `retrieval_rank`
- `priority_bucket`
- `ranking_policy_id`
- `ranking_reason_codes`
- `downweighted_prior_sample` for contradictory or low-confidence priors that
  must remain auditable

The stable sort policy is defined in Part 1 P6.3/P12 condition 11. Part 2 must
record the `ranking_policy_id` and input context hash it consumed; it must not
quietly compute a different rank for execution.

Part 1 sort policy reference:

```text
agent_target_specificity_bucket
performance_context_match_rank
combined_research_prior_weight desc
statistical_reliability_bucket_rank
n_effective desc
freshness_bucket_rank
latest_completed_exit_date desc
original_input_index asc
```

Acceptance:

- Runtime context consumption preserves Part 1 `retrieval_rank` and
  `priority_bucket`.
- Any display-only sort records that it is display-only and keeps original rank.
- High-priority priors cannot be pushed out by low-value earlier rows during
  runtime truncation.
- Contradictory or stale priors are downweighted, not deleted.
- Non-neutral priors still require current-data confirmation before any
  recommendation field can use them.

Status 2026-07-03:

- Python runtime tool `get_rke_research_context` now emits a runtime preflight
  header with the consumed public-safe context hash, Part 1 `ranking_policy_id`,
  visible `retrieval_rank` sequence, `priority_bucket` sequence, truncation count,
  and current-data guard. The formatter preserves Part 1 order and flags
  `retrieval_rank_order_changed` instead of silently re-ranking.
- Agent footprint capture and shadow replay gates now require every consumed
  RKE context hash to carry canonical Part 1 `ranking_policy_id`, positive
  integer `retrieval_rank`, canonical `priority_bucket` (`high`/`medium`/`low`),
  non-negative truncation audit metadata, and current-data confirmation before
  shadow replay can be marked ready.
- This closes the public runtime consumption audit for the Python tool path only.
  Formal benchmark/replay still requires E0 private prompt provenance and the E2
  fixed-episode benchmark evidence.

## E2: Fixed-Episode LLM Benchmark

Run this before full replay, autoresearch mutation, Darwinian weight updates, or
RKE profile/retrieval evolution.

Execution engine:

- E2 is executed by a TS fixed-episode benchmark harness, not by the Python
  no-write bridge validators. The harness should reuse the same runtime graph as
  `mosaic-ts/src/cli/commands/daily-cycle.ts`, apply E0 prompt-source overrides,
  and emit one paired output record per agent/language/as-of-date/model config.
- The harness must iterate the canonical E2 manifest exactly: 8 episodes,
  17 as-of dates, all 25 agents, both `zh` and `en` prompt variants, and the
  required model config slots. It must preserve per-row prompt repo
  revision/hash, RKE context hash, model config id, timeout/error status, schema
  validation status, and no-body output refs.
- Existing `backtest` / `backtest-fill` infrastructure may be used downstream
  for portfolio replay and investment outcome calculation, but it cannot replace
  the fixed-episode runner because it does not produce the per-agent paired LLM
  output matrix required by E2. If the fixed-episode harness is absent, E2 is
  `blocked_preflight` with `benchmark_runner_missing`.

Initial benchmark size:

- Start with 8 fixed episodes.
- Each episode has 1-3 as-of dates.
- Each selected as-of date runs all macro, sector, superinvestor, and decision
  agents.
- Formal rows cover both `zh` and `en` prompt variants; single-language runs are
  smoke or diagnosis only and cannot close E2.
- Do not substitute representative agents for the full stack.

Initial regime coverage:

- 2009 post-crisis recovery / liquidity expansion.
- 2011 inflation and tightening pressure.
- 2015 China equity bubble/crash.
- 2018 deleveraging / trade friction.
- 2020 pandemic shock and policy response.
- 2021 commodity and inflation cycle.
- 2022 USD strength / rate shock / China stress.
- 2024-2026 AI/liquidity/sector-rotation regime.

Inputs are fixed:

- private prompt hash and repo revision
- prompt contract check ref
- PIT tool data
- redacted RKE priors
- tool summaries
- output schema
- context hash
- model parameters

RKE prior degraded mode:

- E2 may still run when the selected Part 1 corpus has PIT/outcome gate blockers,
  refusal-only compiler output, or overwhelmingly `pending_or_unrated` RKE
  prior buckets. In that mode the benchmark is valid only as an agent
  robustness test: it measures schema reliability, current-data discipline,
  stale/fallback handling, and behavior when RKE context is not informative.
- The runner must label the benchmark run and deterministic score table with
  `rke_priors_not_yet_informative` when the consumed RKE context has no
  actionable prior candidates, no effective PIT outcomes, or only refusal
  records for the relevant agent/domain slice. RKE prior usage quality scores in
  that run are diagnostic only and cannot be used as positive evidence that an
  agent learned from informative priors.
- While `rke_priors_not_yet_informative=true`, E4 prompt mutation candidates may
  be based on current-data skill, schema/contract reliability, safety, timeout
  behavior, or stale-prior rejection. They must not be justified by improved RKE
  prior usage quality until Part 1 gate blockers are cleared for the relevant
  corpus/domain and the E2 run consumes informative, non-refusal prior evidence.

Compare at least:

- one current baseline model/config
- local Qwen 27B
- local Qwen3.6 35B
- one API model slot, optional if unavailable

Deterministic scoring:

- schema validity
- JSON parse failure
- timeout/content-empty rate
- directional hit
- subsequent after-cost return
- benchmark-relative alpha
- drawdown
- turnover/cost
- confidence calibration
- RKE prior usage quality
- stale/contradictory prior rejection
- current-data confirmation
- safety violations

Manual review gate:

- First benchmark may be approved by one operator only while the result remains
  strictly shadow-only.
- Entry into paper-trading or any promotion gate requires a second explicit
  review by an independent reviewer who did not author the prompt mutation and
  did not provide the first benchmark approval. If a single-operator exception is
  used, paper-trading stays blocked with `reviewer_independence_unavailable`
  until an independent review is recorded.
- A model/config cannot advance if it has severe safety violations, uses
  fallback prompts as formal inputs, ignores current-data confirmation, or has
  systematic schema failures.
- If investment outcomes are inconclusive, expand the episode set instead of
  advancing.

## E2.1: Fixed-Episode Benchmark Runner Internal Design

This producer is the first critical execution engine. It turns E0/E0.5/E0.6
prompt proof and the E2 manifest into real paired outputs and benchmark evidence.

Runner command shape:

- Add a TS CLI command such as `rke-fixed-benchmark`.
- Inputs:
  - `benchmark_run_id`
  - `cohort`
  - optional `episode_id`, `as_of_date`, `model_config_id`, and `max_runs` for
    smoke/debug runs
  - private prompt repo/root configuration
  - required model config map
  - optional `paper_trading_allowed=false` hard default
- Formal runs must reject bundled/fallback prompts, missing prompt contract
  checks, dirty private prompt repo, fake LLM, and missing required model config.

Execution stages:

1. Load `rke_benchmark.fixed_episode_manifest` and expand it into run rows:
   episode × as-of date × agent × required model config.
2. Resolve prompt provenance with `prompts.preflight`.
3. Resolve prompt content contract proof with `prompts.contract_check`.
4. For each model config, construct the daily-cycle graph with the selected LLM
   provider, prompt source override, cohort, and as-of date.
5. Execute the full 25-agent graph for the date. Do not substitute
   representative agents or skip downstream agents after upstream failures; emit
   blocked paired-output rows when a required upstream artifact is unavailable.
6. Write no-body paired-output refs under private local storage. Each row records
   `benchmark_run_id`, episode, as-of date, model config id, agent, layer,
   prompt hash, prompt contract ref, RKE context hashes, output schema hash,
   output hash, status, and blocker codes. It must not store prompt bodies,
   report prose, raw source spans, URLs, or local paths in public artifacts.
7. Call `rke_benchmark.capture_agent_claim_footprints` for every completed
   agent output and same `benchmark_run_id`.
8. Produce schema validation, deterministic score table, investment outcome
   table, quality-gate summary, and manual-review payload refs.
9. Call `rke_benchmark.fixed_episode_benchmark_evidence`.
10. Persist no-body delivery refs with `rke_benchmark.record_delivery_evidence`.

Model config policy:

- Required configs are `baseline_current_config`, `local_qwen_27b`, and
  `local_qwen3_6_35b`.
- `api_model_if_available` is optional and cannot block readiness if absent.
- Every required model config must cover all 8 episodes, 17 as-of dates, and 25
  agents before formal E2 readiness can pass.

Failure model:

- A row can be `ready`, `blocked_preflight`, `tool_failed`, `timeout`,
  `schema_invalid`, `empty_output`, or `privacy_blocked`.
- Severe safety violation, fallback prompt use, current-data confirmation
  violation, missing prompt contract check, or schema failure over the allowed
  threshold blocks the benchmark quality gate.
- Smoke runs may use `max_runs`, but smoke evidence cannot close E2.

Acceptance:

- Formal run creates paired output refs for every required row.
- Footprints exist for every completed agent/date/model output.
- E2 evidence binds all refs to one `benchmark_run_id`.
- `rke_benchmark.fixed_episode_benchmark_evidence` returns ready.
- No public artifact contains prompt body, report prose, source spans, URLs, or
  local private paths.

Status 2026-07-03:

- Public bridge now exposes `rke_benchmark.fixed_episode_manifest`, a no-run E2
  manifest/preflight that fixes the 8 regime episodes, 17 as-of dates, all 25
  agents, four model config slots (three required plus optional API-if-available),
  input requirements, deterministic scoring fields, and manual-review-required
  state. It reuses `prompts.preflight`; if private prompt provenance is missing
  or dirty, the benchmark remains `blocked_preflight`, keeps the prompt source
  blocker summary, and bundled prompts do not count.
- Public bridge now also exposes `rke_benchmark.fixed_episode_benchmark_evidence`,
  a no-body gate for formal benchmark evidence refs. It requires total paired
  output count and per-required-model output counts for the three required model
  configs; the optional API slot is not required for readiness. It also requires
  fixed episode/as-of-date/model-config manifest refs, schema validation report,
  deterministic score table, investment outcome table, benchmark quality gate
  summary, and approved manual review timestamp before marking evidence ready.
  Evidence refs, quality summary, and manual review must bind to the same
  `benchmark_run_id`. The quality summary blocks severe safety violations,
  fallback prompt runs, current-data confirmation violations, and failed
  schema-failure gate; it never enables promotion by itself.
- This implements the episode/model/input manifest and benchmark-evidence proof
  object preflight. E2 is not complete until real paired LLM outputs, schema
  validation, deterministic score tables, investment outcome tables, and manual
  review decisions exist from actual runs produced by the named fixed-episode
  runner.

## E3: Agent Claim And Footprint Capture

All agents should emit redacted claim/footprint records:

- macro agents: macro regime/series/asset claims and failure modes
- sector agents: sector/ticker/metric family claims
- superinvestors: style-filtered candidate claims and rejection reasons
- decision agents: portfolio/action/risk claims and dissent notes

Public or committed artifacts must not include raw prompt text, report prose,
source spans, or private report metadata. Detailed claim/footprint rows remain
local/private unless explicitly promoted as aggregate reports.

Status 2026-07-03:

- Public bridge now exposes `rke_benchmark.capture_agent_claim_footprints`, a
  private-local capture path for redacted all-agent claim/footprint rows. It
  rejects prompt/report prose fields such as `claim_text`, `source_span_ids`,
  raw `text`, prompt body, URLs, and local paths; successful rows are written
  only under `.mosaic/rke/all_agent_evolution/agent_claim_footprints.jsonl`;
  runtime `rke_context_hash` values must be 64-hex SHA-256 digests; the RPC
  returns aggregate layer/type counts plus a no-source-prose privacy scan.
  `rke_benchmark.agent_footprint_summary` reads the private rows and returns only
  redacted aggregate counts for layer, claim type, RKE prior usage quality,
  current-data confirmation, stale-prior rejection, contradictory-prior handling,
  and context-hash coverage.
- Public bridge now exposes `rke_benchmark.agent_profile_evolution_readiness`,
  a no-write gate that requires redacted footprint summary, all four layer
  coverage, RKE context hashes, runtime ranking metadata, privacy/no-source-prose
  audit, current-data confirmation coverage, profile update ref, and evolution
  input ref before footprint aggregates can feed profile/evolution.
  Profile evidence must bind to the same `benchmark_run_id` as the captured
  footprint summary.
- This implements the redacted capture contract, private row sink, and aggregate
  profile summary reader. E3 is not complete until benchmark/replay agents
  actually emit these rows from real runs.

## E4: Private Prompt Mutation Lifecycle

Prompt mutation output is not a direct runtime change.

Optimized prompts may directly overwrite the current agent prompt files in
`https://github.com/haphap/MOSAIC-Prompts`, but only on a private feature or
release-candidate branch before approval. The overwrite is the intended update
mode for the prompt path within that branch; rollback comes from private git
history, not from keeping parallel prompt copies in the public repo. The default
branch of the private prompt repo must not receive an unreviewed prompt
mutation. Formal benchmark/replay rows pin the candidate branch commit/hash, and
default-branch promotion happens only after leak/drift checks, fixed-episode
benchmark, manual review, shadow/paper-trading gates, and the promotion decision
allow it.

Lifecycle:

```text
candidate
  -> private prompt feature/release branch
  -> overwrite current private prompt file on that branch
  -> prompt contract check
  -> leak/drift check
  -> fixed-episode benchmark
  -> manual review
  -> shadow replay
  -> paper-trading
  -> promotion gate
  -> merge/promote to private prompt default branch
  -> rollback monitor
```

Each mutation must record:

- prompt file path
- overwrite target path in `https://github.com/haphap/MOSAIC-Prompts`
- private prompt branch name and base revision
- private prompt repo revision/hash
- prompt contract check ref
- affected agents
- RKE prior usage hypothesis
- expected improvement metric
- fallback/rollback rule
- benchmark evidence

Mutation track policy:

- E4-E7 use a single-track mutation model by default: one active prompt file per
  agent path on a candidate branch, one pinned candidate commit per benchmark
  run, and rollback through private git history. This is intentional for the
  first shadow-only lifecycle because it keeps prompt provenance and rollback
  evidence simple.
- Competing mutations for the same agent must not be mixed in one branch or one
  benchmark run. If two candidate prompts need comparison, each candidate needs
  its own private branch, prompt hash, `benchmark_run_id`, evidence refs, and
  manual review record. The current E4 contract does not provide automatic A/B
  allocation, winner selection, or multi-arm mutation management.
- A future multi-track design may add one branch per mutation, cohort-specific
  prompt aliases, and explicit A/B assignment in the E2 runner. Until that
  exists, delivery gates should treat ambiguous same-agent competing mutations
  as `mutation_track_ambiguous`.

Status 2026-07-03:

- Public bridge now exposes `rke_benchmark.prompt_mutation_lifecycle_manifest`,
  a no-write E4 preflight that converts safe Part 1 candidate/refusal summaries
  into private prompt mutation lifecycle records. Non-refusal candidates record
  the planned private prompt branch, overwrite target paths, prompt pins,
  rollback rule, benchmark/manual-review requirements, and shadow-only promotion
  guard only when the candidate is prompt-branch actionable. Refusal rows and
  tooling/data-acquisition queue candidates only preserve blocker visibility and
  create no prompt branch; no-branch-only input remains `blocked_preflight`.
- Public bridge now exposes `rke_benchmark.prompt_mutation_release_readiness`,
  a no-write gate that requires positive integer prompt version id, prompt
  repo/commit/hash, lifecycle private branch, base prompt repo revision,
  overwrite target paths, audit-version ref, `prompts.verify_release` evidence,
  prompt contract check ref, and leak/drift check evidence before a prompt
  mutation can feed formal benchmark/replay gates.
  Shadow/delivery aggregate gates also require release evidence to bind to the
  same `benchmark_run_id`.
- This implements the lifecycle planning proof object. E4 is not complete until
  actual private prompt branches, prompt contract checks, leak/drift checks,
  fixed-episode benchmark evidence, manual review, shadow replay, paper-trading
  gate, promotion decision, and rollback monitor evidence exist.

## E5: Darwinian And Autoresearch Inputs

Autoresearch and Darwinian weights must distinguish:

- current-data skill
- research-prior usage skill
- stale-prior rejection skill
- schema/contract reliability
- risk-adjusted downstream outcome
- turnover/cost discipline
- prompt mutation provenance

Darwinian weights must not treat RKE prior as current data.

## E5.0: Autoresearch Loop Prompt Invariants

Autoresearch must reject unsafe prompt mutations inside the mutation loop before
they waste benchmark/replay cycles. E0.6 remains the authoritative release gate,
but it cannot be the first time immutable prompt-guardrail drift is detected.

Required loop-level invariant behavior:

- `mosaic-ts/src/autoresearch/mutator.ts::assertPromptInvariants` must enforce
  the E0.5 required section list:
  role boundary, required inputs/tools, RKE prior policy, workflow, output
  schema, audit/footprint contract, privacy boundary, confidence policy,
  refusal/no-action behavior, and autoresearch evolution contract.
- The mutator meta-prompt must instruct the mutation LLM to preserve all E0.5
  immutable guardrails, not just section headings and schema field names.
- The loop fast check must reject mutations that:
  - drop any E0.5 required section;
  - drop or rename any runtime schema field;
  - remove required tool/fallback/confidence-cap language;
  - weaken “RKE prior is not current data and cannot directly create trades”;
  - remove privacy/no-source-prose language;
  - remove refusal/no-action behavior;
  - remove or blur mutable versus immutable autoresearch boundaries;
  - desynchronize `zh` and `en` contract categories.
- The fast check may remain lexical/structural; it does not need to duplicate
  the full E0.6 private-repo provenance and no-body release check.
- A mutation that passes the TS loop invariant must still pass
  `prompts.contract_check`, leak/drift, benchmark, manual review, replay, and
  rollback gates before release.

Required tests:

- Mutation that drops any E0.5 section is rejected by `assertPromptInvariants`.
- Mutation that keeps schema/workflow headings but weakens RKE-prior policy is
  rejected.
- Mutation that removes privacy boundary or refusal/no-action behavior is
  rejected.
- Mutation that changes schema fields is rejected.
- Mutation that only changes allowed mutable thresholds/wording and preserves
  all immutable guardrails is accepted.
- TS invariant required-section names stay synchronized with E0.6 contract
  categories.

## E5.1: Darwinian And Autoresearch Compute Internal Design

This producer converts benchmark/replay evidence into agent weights and prompt
evolution update refs. Uniform `1/N` weights are allowed only as cold-start
fallback and never close E5.

Inputs:

- `benchmark_run_id`
- E2 paired-output refs and deterministic score table
- E3 footprint summary and profile/evolution readiness
- prompt provenance, prompt contract checks, mutation provenance, and rollback
  readiness
- downstream outcome metrics with risk-adjusted return, drawdown, turnover, and
  cost fields
- RKE prior usage quality, stale/contradictory-prior handling, and current-data
  confirmation metrics

Skill decomposition:

- `current_data_skill`: rewards fresh tool confirmation and penalizes fallback
  or missing current data.
- `rke_prior_usage_skill`: rewards useful ranked-prior use only when current
  data confirms it.
- `stale_prior_rejection_skill`: rewards rejecting stale or contradictory priors.
- `schema_contract_skill`: rewards valid schema, prompt contract preservation,
  and no privacy leak.
- `downstream_outcome_skill`: rewards risk-adjusted downstream outcome after
  costs.
- `turnover_cost_skill`: penalizes unnecessary churn and high implementation
  cost.
- `mutation_reliability_skill`: rewards prompt mutations that improve evidence
  quality without increasing safety, schema, or privacy failures.

Compute stages:

1. Load all inputs for one `benchmark_run_id`; fail closed if any required input
   is missing or cross-run.
2. Build an agent-level feature table with one row per canonical agent and
   optional model/config slices.
3. Normalize metrics within layer to avoid decision agents dominating macro or
   sector agents by output volume.
4. Apply safety caps before performance rewards:
   privacy leak, source-prose leak, current-data violation, schema invalidity,
   or RKE-as-current-data misuse caps the agent weight at the cold-start floor.
5. Compute layer-local weights and a global diagnostic table. Weights must sum
   to 1 within each layer and remain bounded by configured min/max caps.
6. Emit Darwinian weight refs, autoresearch update refs, rejected-update refs,
   and rollback-readiness refs.
7. Call `rke_benchmark.darwinian_autoresearch_consumption_readiness` with
   explicit consumed flags.

Outputs:

- `darwinian_weight_table_ref`
- `agent_skill_decomposition_ref`
- `rke_prior_usage_metrics_ref`
- `downstream_outcome_metrics_ref`
- `autoresearch_update_ref`
- `rejected_update_reasons_ref`
- `rollback_readiness_ref`
- `consumption_evidence` bound to `benchmark_run_id`

Acceptance:

- Non-stub weights exist for all 25 canonical agents.
- Every non-cold-start weight is traceable to footprint, RKE usage, current-data,
  schema/privacy, and downstream outcome evidence.
- RKE prior is never counted as current data.
- Agents with privacy leaks, source-prose leaks, schema failures, or current-data
  confirmation violations are capped or rejected.
- Autoresearch update refs are produced only for mutable prompt parameters or
  approved private prompt mutations.

Outcome source contract:

- The E2 fixed-episode runner owns the benchmark score bundle. It produces or
  references schema/contract metrics, timeout/error metrics, current-data
  confirmation metrics, RKE prior usage diagnostics, stale-prior rejection
  metrics, and manual-review refs from the paired output matrix.
- Investment outcome tables and downstream risk-adjusted outcome metrics must
  be generated from PIT replay inputs bound to the same `benchmark_run_id`.
  Acceptable sources are the existing TS `backtest` / `backtest-fill` plus qlib
  replay path for portfolio actions, or a scorecard-store replay/export that can
  bind each result to the E2 output refs, as-of dates, prompt hashes, and model
  config ids.
- Per-agent deterministic scores and portfolio-level replay metrics are distinct
  proof objects. If the E2 runner has paired LLM outputs but no replayable
  portfolio/action outcome table, E5 remains blocked with
  `downstream_outcome_replay_missing`; Darwinian/autoresearch updates may not
  consume only schema or current-data reliability as a substitute for
  risk-adjusted downstream outcome.

Status 2026-07-03:

- Public bridge now exposes `rke_benchmark.darwinian_autoresearch_input_manifest`,
  which packages E3 aggregate footprint evidence into separate inputs for
  current-data skill, research-prior usage skill, stale/contradictory-prior
  handling, schema/privacy reliability, downstream risk-adjusted outcome,
  turnover/cost discipline, and prompt mutation provenance. The manifest sets
  `rke_prior_treated_as_current_data=false`, requires downstream outcome metrics
  and prompt mutation provenance to bind to the same `benchmark_run_id`, requires
  current-data confirmation for every consumed RKE context hash, and remains
  `blocked_preflight` until real downstream outcome metrics and prompt provenance
  are supplied.
- Public bridge now exposes
  `rke_benchmark.darwinian_autoresearch_consumption_readiness`, a no-write gate
  that requires replay run id, input manifest ref, RKE prior usage metrics ref,
  downstream outcome metrics ref, Darwinian/autoresearch update refs, rollback
  readiness ref, same-`benchmark_run_id` consumption evidence, and explicit
  consumed flags before E5 can count as consumed by replay. It keeps
  `rke_prior_treated_as_current_data=false`.
- This implements the E5 input and consumption proof-object contracts. E5 is not
  complete until actual autoresearch and Darwinian weight compute producers
  produce non-stub update refs consumed by replay/run refs.

## E6: Candidate Consumption Boundary

Part 1 owns the stock/industry/macro prior-to-rule/recipe/parameter candidate
compiler and refusal contract. Part 2 consumes those candidate/refusal records in
private prompt mutation, benchmark, replay, and rollback flows.

- Macro priors may compile into macro rule packs or parameter priors in Part 1
  after validation.
- Stock/industry priors may compile into recipe/rule candidates or refusal
  reasons in Part 1.
- Sector/superinvestor/decision prompt changes go through the private prompt
  mutation lifecycle in Part 2, not directly through the report-prior compiler.
- Missing PIT proxy, missing validation target, source dependency, or unsafe
  actionability from Part 1 must remain visible to benchmark/replay and cannot be
  erased by prompt mutation.

Status 2026-07-03:

- Public bridge now exposes `rke_benchmark.candidate_consumption_manifest`, a
  no-body consumer view over Part 1 `prompt_mutation_candidates.jsonl`. It
  returns safe candidate summaries and aggregate counts while omitting
  `proposed_change` and evidence bodies; `blocked_by` reasons such as
  `missing_pit_outcome`, `missing_validation_target`, and
  `source_dependent_cluster` remain visible for benchmark/replay. Production
  prompt changes, missing manual review, private text, or non-shadow promotion
  state block the manifest. It also classifies tooling/data-acquisition,
  review, coverage, mapping-registry, and policy-gate queue candidates as
  no-prompt-branch records; prompt-like candidates without a resolvable affected
  agent are likewise recorded without creating an empty private prompt branch.
  These records are not mistaken for private prompt writes or patch activation
  candidates; no-prompt-only queues do not report
  `private_prompt_mutation_required=true`, and prompt release, rollback, and
  patch activation gates treat them as `not_applicable`.
- This implements the E6 candidate/refusal consumption boundary. E6 is not
  complete until private prompt mutation, benchmark, replay, and rollback flows
  actually consume this manifest.

## E7.1: Replay Execution Engine Internal Design

The replay engine is the second critical execution engine. It consumes E2/E3/E5
evidence and prompt mutation refs, then produces shadow replay, paper-trading,
promotion, monitor, and rollback refs. Readiness gates do not execute replay.

Replay command shape:

- Add a TS CLI command such as `rke-shadow-replay`.
- Inputs:
  - `benchmark_run_id`
  - `replay_run_id`
  - `cohort`
  - replay window or fixed episode list
  - pinned prompt repo revision/hash and prompt contract refs
  - pinned RKE context export refs
  - Darwinian weight refs
  - optional prompt mutation branch/revision refs
  - paper-trading flag, default false
- Formal replay must reject bundled prompts, missing prompt contract refs,
  missing benchmark evidence, missing Darwinian compute refs, missing rollback
  evidence for shadow-exit candidates, and any private/prose leak.

Execution stages:

1. Load delivery evidence for `benchmark_run_id` and fail if E0/E0.5/E0.6, E2,
   E3, or E5 is not ready.
2. Freeze prompt source, RKE context export, mutation refs, Darwinian weights,
   model config, and replay window.
3. Re-run the daily-cycle graph over each replay date using only point-in-time
   data and pinned RKE priors.
4. Record per-agent replay output hashes, consumed context hashes, ranking
   metadata, current-data confirmation, prompt hash, prompt contract ref, and
   Darwinian weight version.
5. Capture replay footprints with `capture_agent_claim_footprints` using the
   replay `benchmark_run_id`/`replay_run_id` binding.
6. Compute downstream outcome windows, after-cost returns, drawdown, turnover,
   calibration, stale-prior rejection, and safety/privacy metrics.
7. Write shadow replay refs and call `shadow_replay_readiness`.
8. If shadow replay is ready and operator explicitly supplies a paper-trading
   plan, write paper-trading plan/result refs and call
   `paper_trading_readiness`.
9. If paper-trading result is ready and a second review exists, write promotion
   decision refs. The gate may mark operator decision readiness but must keep
   `production_allowed=false`.
10. For any prompt/rule/parameter that leaves shadow mode, run rollback rehearsal
    and record rollback trigger, previous prompt hash, procedure, monitor output,
    and post-rollback verification.
11. Persist refs through `record_delivery_evidence`.

Replay outputs:

- `replay_run_ref`
- `replay_output_manifest_ref`
- `runtime_context_consumption_ref`
- `replay_footprint_ref`
- `downstream_outcome_metrics_ref`
- `paper_trading_plan_ref`
- `paper_trading_result_ref`
- `monitor_summary_ref`
- `promotion_decision_ref`
- `rollback_evidence_ref`

Failure model:

- Replay date failure, missing PIT data, missing pinned prompt, missing prompt
  contract ref, missing RKE context metadata, schema failure, privacy leak,
  current-data violation, and rollback rehearsal failure each produce blocker
  codes.
- A replay can be partially recorded for debugging, but partial replay cannot
  close E7.

Acceptance:

- Shadow replay refs bind to the same `benchmark_run_id` and one
  `replay_run_id`.
- Every replay output is traceable to prompt hash, prompt contract ref, RKE
  context hash, ranking metadata, Darwinian weight ref, and current-data
  confirmation.
- Paper trading and promotion gates only consume replay-produced refs.
- Rollback evidence exists before any candidate can leave shadow mode.
- No replay artifact returned through public bridge includes prompt body, report
  prose, source spans, URLs, or local private paths.

## E7: Delivery Conditions

This plan is complete only when the producers in
`Execution Wiring Required To Satisfy Purpose` have emitted their no-body refs,
and all of the following conditions are ready for one formal `benchmark_run_id`:

- All agents have formal private prompt repo hashes for benchmark/replay.
  Proof objects: `prompts.audit_versions` rows, `prompts.verify_release` results,
  leak/drift checks, `prompts.contract_check` refs, prompt file relative path,
  prompt repo id, prompt repo revision, prompt sha256, and `fallback_used=false`.
- All-agent runtime consumes Part 1 ranked RKE context without re-ranking it.
  Proof objects: context hash, `ranking_policy_id`, consumed `retrieval_rank`
  distribution, truncation audit, and current-data confirmation audit.
- Fixed-episode LLM benchmark has passed manual review.
  Proof objects: episode manifest, as-of date list, model/config manifest,
  named fixed-episode runner id/version, output schema validation report,
  deterministic score table, investment outcome table, manual review decision,
  reviewer timestamp, and independent second-review evidence before
  paper-trading or promotion.
- Agent claims and footprints enter RKE profile/evolution paths.
  Proof objects: private agent claim/footprint rows, redacted aggregate profile
  summary, privacy scan result, and no-source-prose audit.
- Autoresearch and Darwinian weights consume RKE usage quality and downstream
  outcome evidence.
  Proof objects: replay run id, Darwinian/autoresearch input manifest, RKE prior
  usage quality metrics, E2 score bundle ref, PIT replay or scorecard outcome
  source ref, downstream risk-adjusted outcome metrics, and rollback readiness
  report.
- Prompt mutations are applied only through private prompt repo branches and
  gated promotion.
  Proof objects: private prompt branch, prompt version id, leak/drift checks,
  benchmark evidence link, manual review decision, shadow/paper-trading gate,
  promotion decision, and proof that the private prompt default branch was not
  overwritten before approval.
- Rollback evidence exists for any prompt/rule/parameter that leaves shadow
  mode.
  Proof objects: rollback trigger definition, previous prompt hash, rollback
  command or procedure, monitor output, and post-rollback verification.

Status 2026-07-03:

- Public bridge now exposes `rke_benchmark.prompt_mutation_rollback_readiness`,
  a no-write E7 rollback gate over prompt mutation lifecycle records. It blocks
  shadow exit unless each private prompt branch candidate has previous prompt
  hashes matched by rollback evidence plus rollback trigger, rollback procedure,
  monitor output ref, post-rollback verification ref, and `benchmark_run_id`
  binding. Shadow/delivery aggregate gates reuse that binding, and candidate
  `blocked_by` reasons keep blocking rollback.
  The gate never enables promotion by itself.
- Public bridge now exposes `rke_benchmark.shadow_replay_readiness`, a no-write
  gate that requires all-agent prompt provenance, fixed-episode benchmark
  evidence, Darwinian/autoresearch input readiness, prompt mutation
  release/leak-drift readiness, runtime RKE context hash/current-data
  confirmation, and rollback readiness before marking shadow replay ready. It
  keeps `paper_trading_allowed=false` and `promotion_allowed=false`.
- TypeScript `rke-shadow-replay` now preflights the existing
  `delivery_readiness` conditions for prompt provenance, runtime context
  consumption, fixed benchmark, profile/evolution, Darwinian consumption,
  prompt release, patch activation, and rollback evidence before starting replay
  graph execution.
- TypeScript now exposes `rke-prompt-provenance-evidence`, a private-file
  recorder for all-agent prompt release checks. It validates no-body release
  rows through `all_agent_prompt_provenance_readiness` before recording
  `all_agent_prompt_release_checks` for later delivery audits.
- Public bridge now exposes `rke_benchmark.paper_trading_readiness`, a no-write
  gate that requires shadow replay readiness plus operator-approved reviewed
  paper-trading plan, risk-limit ref, and stop-loss/rollback ref before allowing
  paper-trading entry. The plan must bind to the same `benchmark_run_id`. It
  still keeps `promotion_allowed=false`.
- Public bridge now exposes `rke_benchmark.promotion_decision_readiness`, a
  no-write gate that requires paper-trading readiness, paper-trading result ref,
  monitor summary ref, approved second review timestamp, and lockbox decision ref
  before marking a mutation ready for operator promotion decision. The promotion
  evidence must bind to the same `benchmark_run_id`. It still keeps
  `production_allowed=false` and `promotion_allowed=false`.
- Public bridge now exposes `rke_benchmark.delivery_readiness`, a no-write E7
  aggregate audit that maps each delivery condition to its underlying readiness
  gate and returns condition-level blockers plus no-body evidence summaries for
  prompt source blockers. Patch activation evidence is checked against the same
  `benchmark_run_id` when aggregated through this gate. It does not run
  benchmark/replay or enable
  production.
- Public bridge now exposes `rke_benchmark.record_delivery_evidence`, a
  private-local no-body evidence sink under `.mosaic/rke/all_agent_evolution/`
  so actual benchmark/replay runs can persist refs and later rerun
  `delivery_readiness` without resupplying every field. Repeated records for a
  benchmark run merge by evidence key, so staged benchmark/replay/promotion runs
  can append proof refs incrementally. The stored run context includes `cohort`,
  so non-default benchmark cohorts can be re-audited by `benchmark_run_id`.
  Record responses count proof-object keys separately from run context keys.
- Public bridge now exposes `rke_benchmark.delivery_evidence_audit`, a no-body
  audit over that private store that reports recorded and missing proof-object
  keys per benchmark run, plus the aggregate delivery readiness status so
  key-complete evidence cannot be mistaken for E7 readiness. It also returns
  the condition-level readiness summaries from `delivery_readiness`, and keeps
  run context keys such as `cohort` and `prompt_source_status` separate from
  proof-object keys.
- TypeScript now exposes `rke-paper-promotion-evidence`, a thin E7 producer for
  operator-reviewed paper-trading and promotion refs. It only accepts refs bound
  to `rke-shadow:<benchmark_run_id>:<replay_run_id>:...`, checks the relevant
  `delivery_readiness` condition, and records no-body refs through
  `record_delivery_evidence`; it does not promote to production.
- TypeScript now exposes `rke-prompt-mutation-release-evidence`, a private-file
  recorder for prompt mutation release checks. It binds release refs to explicit
  candidate rows, validates them through `prompt_mutation_release_readiness`, and
  records `prompt_mutation_release_checks` only after release/leak/contract gates
  pass.
- TypeScript now exposes `rke-rollback-rehearsal-evidence`, a private-file
  evidence recorder for rollback rehearsal refs. It validates each row is bound
  to the same shadow replay, requires prompt hashes and rollback
  trigger/procedure/monitor/post-verification refs, checks the
  `rollback_evidence` delivery condition, and only then records no-body refs.
- Public bridge now exposes `rke_benchmark.patch_activation_readiness`, a
  no-write shadow activation gate that requires patch artifact, validation,
  shadow apply, runtime activation/proof, rollback refs, and `benchmark_run_id`
  binding before a candidate patch can count as activated. It preserves
  candidate `blocked_by` reasons and keeps production activation forbidden.
- TypeScript now exposes `rke-patch-activation-evidence`, a private-file
  recorder for shadow patch activation refs. It can bind explicit candidate rows
  with activation refs, checks `patch_activation_readiness`, and records
  `patch_activation_evidence` only after production activation remains forbidden.
- Delivery readiness now includes the Darwinian/autoresearch consumption gate,
  so input-manifest readiness alone cannot satisfy the E7 consumption condition.
- Full paper-trading/monitor execution remains producer-blocked until actual run
  artifacts emit replay refs, monitor refs, downstream outcome refs, and
  post-rollback verification. Readiness gates alone do not execute replay.
- Agent footprint summary and profile/evolution readiness now carry redacted
  `report_claim_refs` aggregate counts, and every footprint row that consumed an
  RKE context hash must also carry a redacted report-claim link before
  profile/evolution or Darwinian/autoresearch inputs can be marked ready.
- TypeScript now exposes `rke-profile-evidence`, a recorder for profile update,
  evolution input, and no-source-prose audit refs. It calls
  `agent_profile_evolution_readiness` before recording `profile_evidence`.
- Prompt mutation release and rollback readiness now retain candidate
  `blocked_by` as hard blockers, preventing shadow-exit proof from overriding
  unresolved PIT/validation/refusal blockers.
- This implements the rollback and patch-activation proof-object preflights. E7
  is not complete until real private branch mutations, benchmark/manual-review
  decisions, shadow or paper-trading gate evidence, monitor output, runtime
  patch proof, and post-rollback verification are produced by actual runs.
