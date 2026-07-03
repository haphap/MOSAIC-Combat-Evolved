# Part 2: RKE All-Agent Evolution Plan

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

## Current Status

As of 2026-07-03:

- Stock, industry, and macro report feedback supports PIT outcome/readiness/profile
  paths; macro additionally supports parent macro claims, macro claim legs,
  direct series labels, macro agent priors, and RI-MACRO readiness gates.
- Layer-3 public runtime has been migrated to the canonical roster:
  `druckenmiller`, `munger`, `burry`, `ackman`.
- Public fallback prompts exist for `munger` and `burry`, but complete
  role-specific prompt upgrades are still pending in the private prompt repo.
- The Python prompt bridge has to stay in sync with the TS canonical roster;
  this is part of the roster preflight, not an optional cleanup.

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
  `prompts/mosaic` path is inside a git worktree and the runner records the
  discovered git top-level as `prompt_repo_id`, the HEAD commit as repo revision,
  the prompt file path relative to that worktree, and the prompt hash. If those
  fields cannot be recovered, the row is blocked with `private_prompt_unavailable`
  or `prompt_provenance_unavailable`.
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
  the gate preserves the preflight source summary so E7 blockers include
  repo-level dirty state, not only repeated row-level prompt blockers.
- This implements the public E0 preflight mechanism. E0 is not fully closed
  until the private prompt repo has ready rows for all benchmark/replay agents
  and leak/drift/release checks have passed.

## E1: Runtime Consumption Of Part 1 Ranked RKE Context

Ownership split:

- Part 1 owns the redacted ranked context/export contract, including ranking
  keys, rank fields, truncation audit, and stock/industry/macro prior inputs.
- Part 2 owns all-agent runtime consumption of that ranked context: prompt/tool
  plumbing, runtime preflight, benchmark wiring, and replay evidence.
- The Python bridge / agent tools should consume already-ranked RKE context.
  TS should not re-rank except for display-only sorting.

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
  RKE context hash to carry matching `ranking_policy_id`, `retrieval_rank`,
  `priority_bucket`, and truncation audit metadata before shadow replay can be
  marked ready.
- This closes the public runtime consumption audit for the Python tool path only.
  Formal benchmark/replay still requires E0 private prompt provenance and the E2
  fixed-episode benchmark evidence.

## E2: Fixed-Episode LLM Benchmark

Run this before full replay, autoresearch mutation, Darwinian weight updates, or
RKE profile/retrieval evolution.

Initial benchmark size:

- Start with 8 fixed episodes.
- Each episode has 1-3 as-of dates.
- Each selected as-of date runs all macro, sector, superinvestor, and decision
  agents.
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
- PIT tool data
- redacted RKE priors
- tool summaries
- output schema
- context hash
- model parameters

Compare at least:

- one current baseline model/config
- local Qwen 27B
- local Qwen3.6 35B
- one API model, if available

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

- First benchmark may be approved by one operator.
- Promotion beyond shadow/paper-trading requires a second explicit review or a
  separate promotion gate.
- A model/config cannot advance if it has severe safety violations, uses
  fallback prompts as formal inputs, ignores current-data confirmation, or has
  systematic schema failures.
- If investment outcomes are inconclusive, expand the episode set instead of
  advancing.

Status 2026-07-03:

- Public bridge now exposes `rke_benchmark.fixed_episode_manifest`, a no-run E2
  manifest/preflight that fixes the 8 regime episodes, 17 as-of dates, all 25
  agents, four model config slots, input requirements, deterministic scoring
  fields, and manual-review-required state. It reuses `prompts.preflight`; if
  private prompt provenance is missing or dirty, the benchmark remains
  `blocked_preflight`, keeps the prompt source blocker summary, and bundled
  prompts do not count.
- Public bridge now also exposes `rke_benchmark.fixed_episode_benchmark_evidence`,
  a no-body gate for formal benchmark evidence refs. It requires total paired
  output count and per-required-model output counts for the three required model
  configs, fixed episode/as-of-date/model-config manifest refs, schema validation
  report, deterministic score table, investment outcome table, benchmark quality
  gate summary, and approved manual review timestamp before marking evidence
  ready. Evidence refs, quality summary, and manual review must bind to the same
  `benchmark_run_id`. The quality summary blocks severe safety violations,
  fallback prompt runs, current-data confirmation violations, and failed
  schema-failure gate; it never enables promotion by itself.
- This implements the episode/model/input manifest and benchmark-evidence proof
  object preflight. E2 is not complete until real paired LLM outputs, schema
  validation, deterministic score tables, investment outcome tables, and manual
  review decisions exist from actual runs.

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
  only under `.mosaic/rke/all_agent_evolution/agent_claim_footprints.jsonl` and
  the RPC returns aggregate layer/type counts plus a no-source-prose privacy scan.
  `rke_benchmark.agent_footprint_summary` reads the private rows and returns only
  redacted aggregate counts for layer, claim type, RKE prior usage quality,
  current-data confirmation, stale-prior rejection, contradictory-prior handling,
  and context-hash coverage.
- Public bridge now exposes `rke_benchmark.agent_profile_evolution_readiness`,
  a no-write gate that requires redacted footprint summary, all four layer
  coverage, RKE context hashes, privacy/no-source-prose audit, profile update ref,
  and evolution input ref before footprint aggregates can feed profile/evolution.
  Profile evidence must bind to the same `benchmark_run_id` as the captured
  footprint summary.
- This implements the redacted capture contract, private row sink, and aggregate
  profile summary reader. E3 is not complete until benchmark/replay agents
  actually emit these rows from real runs.

## E4: Private Prompt Mutation Lifecycle

Prompt mutation output is not a direct runtime change.

Optimized prompts may directly overwrite the current agent prompt files in
`https://github.com/haphap/MOSAIC-Prompts`. The overwrite is the intended update
mode; rollback comes from private git history, not from keeping parallel prompt
copies in the public repo.

Lifecycle:

```text
candidate
  -> private prompt branch
  -> overwrite current private prompt file
  -> leak/drift check
  -> fixed-episode benchmark
  -> manual review
  -> shadow replay
  -> paper-trading
  -> promotion gate
  -> rollback monitor
```

Each mutation must record:

- prompt file path
- overwrite target path in `https://github.com/haphap/MOSAIC-Prompts`
- private prompt repo revision/hash
- affected agents
- RKE prior usage hypothesis
- expected improvement metric
- fallback/rollback rule
- benchmark evidence

Status 2026-07-03:

- Public bridge now exposes `rke_benchmark.prompt_mutation_lifecycle_manifest`,
  a no-write E4 preflight that converts safe Part 1 candidate/refusal summaries
  into private prompt mutation lifecycle records. Non-refusal candidates record
  the planned private prompt branch, overwrite target paths, prompt pins,
  rollback rule, benchmark/manual-review requirements, and shadow-only promotion
  guard. Refusal rows only preserve the blocker reason and create no prompt
  branch; refusal-only input remains `blocked_preflight`.
- Public bridge now exposes `rke_benchmark.prompt_mutation_release_readiness`,
  a no-write gate that requires prompt version id, prompt repo/commit/hash,
  lifecycle private branch, base prompt repo revision, overwrite target paths,
  audit-version ref, `prompts.verify_release` evidence, and leak/drift check
  evidence before a prompt mutation can feed formal benchmark/replay gates.
- This implements the lifecycle planning proof object. E4 is not complete until
  actual private prompt branches, leak/drift checks, fixed-episode benchmark
  evidence, manual review, shadow replay, paper-trading gate, promotion decision,
  and rollback monitor evidence exist.

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

Status 2026-07-03:

- Public bridge now exposes `rke_benchmark.darwinian_autoresearch_input_manifest`,
  which packages E3 aggregate footprint evidence into separate inputs for
  current-data skill, research-prior usage skill, stale/contradictory-prior
  handling, schema/privacy reliability, downstream risk-adjusted outcome,
  turnover/cost discipline, and prompt mutation provenance. The manifest sets
  `rke_prior_treated_as_current_data=false`, requires downstream outcome metrics
  and prompt mutation provenance to bind to the same `benchmark_run_id`, and
  remains `blocked_preflight` until real downstream outcome metrics and prompt
  provenance are supplied.
- Public bridge now exposes
  `rke_benchmark.darwinian_autoresearch_consumption_readiness`, a no-write gate
  that requires replay run id, input manifest ref, RKE prior usage metrics ref,
  downstream outcome metrics ref, Darwinian/autoresearch update refs, rollback
  readiness ref, and explicit consumed flags before E5 can count as consumed by
  replay. It keeps `rke_prior_treated_as_current_data=false`.
- This implements the E5 input and consumption proof-object contracts. E5 is not
  complete until actual autoresearch and Darwinian weight updates produce those
  replay/run refs.

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
  state block the manifest.
- This implements the E6 candidate/refusal consumption boundary. E6 is not
  complete until private prompt mutation, benchmark, replay, and rollback flows
  actually consume this manifest.

## E7: Delivery Conditions

This plan is complete only when:

- All agents have formal private prompt repo hashes for benchmark/replay.
  Proof objects: `prompts.audit_versions` rows, `prompts.verify_release` results,
  prompt file relative path, prompt repo id, prompt repo revision, prompt sha256,
  and `fallback_used=false`.
- All-agent runtime consumes Part 1 ranked RKE context without re-ranking it.
  Proof objects: context hash, `ranking_policy_id`, consumed `retrieval_rank`
  distribution, truncation audit, and current-data confirmation audit.
- Fixed-episode LLM benchmark has passed manual review.
  Proof objects: episode manifest, as-of date list, model/config manifest,
  output schema validation report, deterministic score table, investment
  outcome table, manual review decision, and reviewer timestamp.
- Agent claims and footprints enter RKE profile/evolution paths.
  Proof objects: private agent claim/footprint rows, redacted aggregate profile
  summary, privacy scan result, and no-source-prose audit.
- Autoresearch and Darwinian weights consume RKE usage quality and downstream
  outcome evidence.
  Proof objects: replay run id, Darwinian/autoresearch input manifest, RKE prior
  usage quality metrics, downstream outcome metrics, and rollback readiness
  report.
- Prompt mutations are applied only through private prompt repo branches and
  gated promotion.
  Proof objects: private prompt branch, prompt version id, leak/drift checks,
  benchmark evidence link, manual review decision, shadow/paper-trading gate,
  and promotion decision.
- Rollback evidence exists for any prompt/rule/parameter that leaves shadow
  mode.
  Proof objects: rollback trigger definition, previous prompt hash, rollback
  command or procedure, monitor output, and post-rollback verification.

Status 2026-07-03:

- Public bridge now exposes `rke_benchmark.prompt_mutation_rollback_readiness`,
  a no-write E7 rollback gate over prompt mutation lifecycle records. It blocks
  shadow exit unless each private prompt branch candidate has previous prompt
  hashes plus rollback trigger, rollback procedure, monitor output ref, and
  post-rollback verification ref, and now keeps candidate `blocked_by` reasons
  blocking rollback. The gate never enables promotion by itself.
- Public bridge now exposes `rke_benchmark.shadow_replay_readiness`, a no-write
  gate that requires all-agent prompt provenance, fixed-episode benchmark
  evidence, Darwinian/autoresearch input readiness, prompt mutation
  release/leak-drift readiness, runtime RKE context hash/current-data
  confirmation, and rollback readiness before marking shadow replay ready. It
  keeps `paper_trading_allowed=false` and `promotion_allowed=false`.
- Public bridge now exposes `rke_benchmark.paper_trading_readiness`, a no-write
  gate that requires shadow replay readiness plus operator-reviewed
  paper-trading plan, risk-limit ref, and stop-loss/rollback ref before allowing
  paper-trading entry. It still keeps `promotion_allowed=false`.
- Public bridge now exposes `rke_benchmark.promotion_decision_readiness`, a
  no-write gate that requires paper-trading readiness, paper-trading result ref,
  monitor summary ref, second review timestamp, and lockbox decision ref before
  marking a mutation ready for operator promotion decision. It still keeps
  `production_allowed=false` and `promotion_allowed=false`.
- Public bridge now exposes `rke_benchmark.delivery_readiness`, a no-write E7
  aggregate audit that maps each delivery condition to its underlying readiness
  gate and returns condition-level blockers plus no-body evidence summaries for
  prompt source blockers. It does not run benchmark/replay or enable
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
- Public bridge now exposes `rke_benchmark.patch_activation_readiness`, a
  no-write shadow activation gate that requires patch artifact, validation,
  shadow apply, runtime activation/proof, and rollback refs before a candidate
  patch can count as activated. It preserves candidate `blocked_by` reasons and
  keeps production activation forbidden.
- Delivery readiness now includes the Darwinian/autoresearch consumption gate,
  so input-manifest readiness alone cannot satisfy the E7 consumption condition.
- Agent footprint summary and profile/evolution readiness now carry redacted
  `report_claim_refs` aggregate counts, and every footprint row that consumed an
  RKE context hash must also carry a redacted report-claim link before
  profile/evolution or Darwinian/autoresearch inputs can be marked ready.
- Prompt mutation release and rollback readiness now retain candidate
  `blocked_by` as hard blockers, preventing shadow-exit proof from overriding
  unresolved PIT/validation/refusal blockers.
- This implements the rollback and patch-activation proof-object preflights. E7
  is not complete until real private branch mutations, benchmark/manual-review
  decisions, shadow or paper-trading gate evidence, monitor output, runtime
  patch proof, and post-rollback verification are produced by actual runs.
