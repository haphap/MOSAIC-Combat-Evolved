# Position-Aware Prompt Evolution Runbook

This runbook covers the operator path for the prompt-evolution work that adds
position review, target-current deltas, and MiroFish stress consumption to the
Layer 4 agents. It is public by design: do not paste private prompt prose,
private registry rows, account screenshots, or secret environment values here.

## Scope

The position-aware loop keeps RKE report signals shadow-only and MiroFish
simulation-only. Production portfolio actions still require current account and
current market evidence. MiroFish context can influence CRO, autonomous
execution, and CIO only through the governed runtime contract and current-data
validator.

## Preflight

Run from the repository root unless noted.

```bash
rtk pnpm --dir mosaic-ts typecheck
rtk pnpm --dir mosaic-ts lint
rtk pnpm --dir mosaic-ts test \
  mirofish_cli_options.test.ts mirofish_trainer.test.ts mirofish_context_inject.test.ts \
  research_knobs_checker.test.ts mutator.test.ts \
  dashboard.test.tsx decision_layer4_agents.test.ts daily_cycle.test.ts
rtk uvx ruff@0.15.15 check mosaic tests
rtk proxy env MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_scorecard_store.py tests/test_bridge_scorecard_handlers.py -q \
  --basetemp .mosaic/tmp/pytest-position-aware-scorecard
rtk proxy env MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_bridge_mirofish.py tests/test_mirofish.py -q \
  --basetemp .mosaic/tmp/pytest-position-aware-mirofish
rtk pnpm --dir mosaic-ts prompt:check
rtk uv run python scripts/check_prompt_leaks.py
```

For full RKE pytest, use `.mosaic/tmp` as `--basetemp`. CI isolates non-RKE
tests and each `test_rke_*.py` file; the monolithic local command is useful for
integration coverage but is not the shape used to identify one slow RKE file.

If `pytest tests/ -q` looks stuck locally, profile the slow tests before
changing code:

```bash
rtk proxy env MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/ -q --durations=20 --durations-min=0.1 \
  --basetemp .mosaic/tmp/pytest-rke-full-profile
```

Also check local private registry size:

```bash
rtk du -sh registry
rtk du -ah registry/report_intelligence
```

The root cause of the local slowdown was environmental, not pytest collection:
test helpers repeatedly copied the developer's ignored 151 MB
`registry/report_intelligence/` tree. Operator readiness repeated that copy 25
times, and two direct-root handoff tests scanned it again. Pytest registry copies
now exclude every path classified by `PRIVATE_LOCAL_REGISTRY_FILES` or
`PRIVATE_LOCAL_REGISTRY_PREFIXES`, then rebuild only the small synthetic private
fixture required by a test. Direct-root handoff/readiness cases use the same
isolated registry.

On the 2026-07-10 verification run, the monolithic suite fell from more than 78
minutes to about 3 minutes. `tests/test_rke_schema_artifacts.py` fell to about
1.9 seconds, and the former 22.75-second handoff scan fell to about 0.06 seconds.
Results and duration must not depend on ignored PDFs, report rows, review files,
or `.mosaic` caches.

Private/local schema fixtures are explicit diagnostics:

```bash
rtk proxy env MOSAIC_TEST_PRIVATE_REPORT_INTELLIGENCE_FIXTURES=1 \
  MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_rke_schema_artifacts.py -q --durations=20 \
  --basetemp .mosaic/tmp/pytest-private-schema-fixtures
```

This opt-in run never substitutes for the clean public fixture suite.

## Prompt IR And Domain Knob Catalog

Position-aware prompt evolution uses Prompt IR, the runtime source registry, and
the domain knob catalog as the machine-readable authority for learnable
parameters. Do not hand-maintain a second knob list in docs or prompts.

```bash
rtk pnpm --dir mosaic-ts dev prompts export-domain-knob-catalog \
  --out ../registry/prompt_checks/domain_knob_catalog_v1.json
rtk pnpm --dir mosaic-ts dev prompts export-domain-knob-evaluation-contract \
  --out ../registry/prompt_checks/domain_knob_evaluation_contract_v1.json
rtk pnpm --dir mosaic-ts dev prompts check-research-knobs \
  --cohort cohort_default \
  --enabled-agents '*'
rtk proxy env MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_rke_schema_artifacts.py -q \
  --basetemp .mosaic/tmp/pytest-position-aware-schema
```

Acceptance checks:

- exported catalog validates against `schemas/domain_knob_catalog_v1.schema.json`;
- `projection_bucket` is restricted to the v1 buckets `lookbacks`,
  `thresholds`, `tie_breaks`, `evidence_weights`, and `confidence_caps`; domain
  card projection, mutation old-value checks, and visible-contract filtering
  must use the catalog bucket instead of treating every non-lookback as a
  threshold;
- bucket assignment is explicit catalog behavior, not a suffix convention:
  quarter-count history windows such as `financial_statement_quarters`,
  `inventory_cycle_quarters`, and `capex_cycle_quarters` are `lookbacks`;
- every card declares `activation_state`: only `active` cards enter
  `mutation_targets` and active coverage counts; `read_only` cards keep their
  versioned defaults visible to runtime but cannot be mutated; `backlog` cards
  remain metadata-only and do not enter effective projection buckets;
- decision-layer domain cards are locked to the PR3 owner lists: CIO has the
  four position-review cards plus four MiroFish portfolio-stress cards, CRO has
  the four risk cards plus four MiroFish tail-risk cards, and autonomous
  execution has the four execution cards plus four MiroFish path-sizing cards;
  the broader CIO/CRO/execution defaults remain explicit `read_only` cards and
  are rejected if they appear in `mutation_targets`;
- source binding is coverage-level specific: `direct_tool` and `derived_proxy`
  cards must carry matching `evidence_dependencies`, while `runtime_state`
  cards must declare runtime input sources;
- card metric closure includes `evaluation_metric`, `rollback_condition.metric`,
  and `secondary_metrics`; every referenced metric must exist in the evaluation
  registry and use the card horizon, and rollback units must match the metric
  unit; `rollback_condition.worse_by` must be nonnegative; metric registry
  entries must carry rollback-usable `value_convention`, `direction`, `baseline`,
  PIT, and exclusion policies covering missing/stale inputs, source errors,
  lookahead risk, and incomplete fills;
  signed-return metrics must be higher-is-better, while loss/cost conventions
  must be lower-is-better;
- the generated language-neutral evaluation contract carries each binding's
  `activation_state`; downstream evaluators must reject proposals for a
  non-active binding instead of treating catalog presence as mutation
  eligibility;
- domain knob mutations may use only the card's metric closure: its primary
  evaluation metric, rollback metric, or a registered `secondary_metrics`
  entry; unrelated evaluation or rollback metrics must be rejected;
- CIO pre-decision cards must not declare `candidate_target_state`; that source
  is only available after the CIO proposal and is reserved for CRO/execution
  validation and downstream cards;
- catalog schema validation rejects incomplete executable cards: in-run
  tool-derived dependencies must declare their scope source fields, numeric
  targets must carry bounds/step, and `enforcement: code` cards must declare
  their runtime validator and audit field;
- Prompt IR contracts keep runtime tool, metric, current-data, and RKE-prior
  guardrails aligned with the TypeScript runtime registry;
- `conflicting_evidence` confidence caps require an explicit `conflict_rule`;
  until a direction-adapter registry is available, production prompt checks fail
  closed for that trigger instead of relying on LLM prose;
- runtime cap enforcement must revalidate capped structured or fallback output
  against the agent output schema before returning it; the validation view omits
  the runtime-owned top-level `verified_knob_audit`, but the returned envelope
  must preserve that audit;
- agent outputs must not declare influence from disabled domain cards. The
  postprocessor rejects disabled card ids instead of treating them as merely
  unsupported audit entries;
- `toolStatuses` must carry runtime fallback and `as_of` metadata. The tool loop
  derives these fields from JSON tool output and preserves them on cache hits so
  primary-tool fallback caps can fire after the run;
- Layer 4 runs the fixed sequence `alpha_discovery -> cio_proposal -> candidate
  freeze -> cro_review -> execution_feasibility -> cio_final -> shared
  validation`. Market and execution-liquidity statuses come from per-ticker
  adapters; a successful status for one scope never marks another scope loaded;
- `previous_target_state` is carried from the prior accepted final target in
  backtest and shadow replay. A first-cycle absence is explicit and disables
  drift/rebalance-card influence instead of fabricating an empty historical
  target;
- CIO proposal and final use the same cached static prompt pair and frozen
  source family. Rewriting a prompt file or refreshing account/market state
  during a run cannot change the final-stage contract;
- unsupported or disabled declared knob influence rejects the raw structured
  output and selects the deterministic conservative fallback. Audit-only
  retention of the original action is not allowed;
- claim/evidence schema validation is present, but rollout is not complete
  until tool/source result fingerprints, runtime-owned evidence ids, the
  structured-extractor evidence catalog, and required action claim references
  are wired into every enabled stage;
- private zh/en prompts have exactly one canonical `research-knobs` fence for
  enabled agents;
- historical runtime-source aliases are rejected in production catalog files.

To synchronize the private prompt repository after a catalog change, run from
`mosaic-ts/`:

```bash
rtk pnpm dev prompts sync-research-knobs \
  --private-prompts-root /home/hap/Project/MOSAIC-Prompts/prompts/mosaic \
  --cohort cohort_default --write
rtk pnpm dev prompts check-research-knobs \
  --private-prompts-root /home/hap/Project/MOSAIC-Prompts \
  --cohort cohort_default --enabled-stages '*'
rtk pnpm dev prompts prompt-token-budget \
  --private-prompts-root /home/hap/Project/MOSAIC-Prompts/prompts/mosaic \
  --baseline ../registry/prompt_checks/prompt_token_budget_manifest_v1.json \
  --out ../.mosaic/prompt_evolution_delivery/prompt-token-budget-candidate.json
```

The sync is idempotent. A second run must report zero updated files, and the
checker must report 26 ready stages with no legacy stage before the prompt
commit is published. Never stage local `mutation_patches/knob_mutations.jsonl`
as part of this synchronization.

## Daily-Cycle Smoke

Empty-position smoke must still run:

```bash
rtk pnpm --dir mosaic-ts dev daily-cycle \
  --cohort cohort_default \
  --fake-llm \
  --agent-timeout-seconds 0 \
  --out .mosaic/tmp/daily-cycle-empty-position-smoke.json
```

For a current-position smoke, pass the private prompt root and a local fixture:

```json
{
  "current_positions": [
    {
      "ticker": "600519.SH",
      "sector": "consumer",
      "current_weight": 0.08,
      "cost_basis": 1500,
      "market_price": 1700,
      "unrealized_pnl_pct": 0.12,
      "holding_days": 42,
      "entry_date": "2026-05-28",
      "source_agent": "cio",
      "entry_thesis_id": "fixture:600519.SH",
      "last_review_date": "2026-07-08"
    }
  ]
}
```

```bash
rtk pnpm --dir mosaic-ts dev daily-cycle \
  --cohort cohort_default \
  --fake-llm \
  --agent-timeout-seconds 0 \
  --prompts-root /home/hap/Project/MOSAIC-Prompts/prompts/mosaic \
  --current-positions-file .mosaic/tmp/current-positions.json \
  --out .mosaic/tmp/daily-cycle-current-position-smoke.json
```

The acceptance evidence is the final JSON:

- `current_positions.snapshot_status` is `loaded` or `empty_confirmed`.
- `position_audit.positions_loaded` matches the fixture.
- `position_audit.positions_reviewed` covers every loaded position.
- `position_audit.tool_status_summary` records the position source and market
  price evidence status.
- missing position snapshots surface as scoped runtime evidence misses:
  `current_position_snapshot` is `missing`, and unresolved market data is
  recorded as `current_market_data:ticker_scope:unknown`.
- `portfolio_actions[*]` include `current_weight`, `target_weight`,
  `delta_weight`, `position_decision`, `thesis_status`, and `risk_flags`.
- `position_decision` semantics are enforced: `ADD` maps to positive-delta
  `BUY`, `REDUCE` trims an existing holding, `EXIT` maps to zero-weight `SELL`,
  and `HOLD` maps to an existing held position.
- active `max_single_name_weight` overrides require both `override_reason` and
  the `cro_risk_override` risk flag.
- stop-loss-breached `HOLD` overrides require explicit counterevidence plus
  `override_reason` and the `cro_risk_override` risk flag.
- stop-loss-breached `HOLD` actions are normalized with a
  `stop_loss_breached` risk flag so audit/TUI warning counts do not depend on
  prompt prose.
- fixtures may include `sector`; it is required when testing an active
  `max_sector_weight` runtime card.

## MiroFish Portfolio Stress Fixture

`mirofish generate` and `mirofish train` accept current portfolio fixtures so
scenario stress can be computed for existing holdings. The fixture file may be a
JSON array of positions or an object with `current_positions`, `sector_exposure`,
and `theme_exposure`. Inline JSON flags override file values.
`--current-positions-json` accepts the same array or object shape as the file
fixture, so operators can pass a complete one-off portfolio stress fixture
without creating a local file.
Each MiroFish current position must include a positive `market_price` or
`current_price`; the bridge uses that value as the scenario path start price.

Example `.mosaic/tmp/mirofish-positions.json`:

```json
{
  "current_positions": [
    {
      "ticker": "600519.SH",
      "name": "Kweichow Moutai",
      "market_price": 1700,
      "current_weight": 0.08,
      "cost_basis": 1500,
      "holding_days": 42,
      "unrealized_pnl_pct": 0.12,
      "sector": "consumer",
      "entry_thesis": "premium consumption compounder"
    }
  ],
  "sector_exposure": { "consumer": 0.08 },
  "theme_exposure": { "premium_consumption": 0.08 }
}
```

Focused smoke:

```bash
rtk pnpm --dir mosaic-ts dev mirofish generate \
  --days 5 \
  --scenarios base \
  --current-positions-file .mosaic/tmp/mirofish-positions.json \
  --print
rtk pnpm --dir mosaic-ts dev mirofish train \
  --fake-llm \
  --dry-run \
  --days 5 \
  --scenarios base \
  --agents cio \
  --current-positions-file .mosaic/tmp/mirofish-positions.json
```

Acceptance checks:

- generated scenarios include per-position stress for loaded holdings;
- dry-run training computes scores but does not persist `mirofish_runs`;
- MiroFish remains simulation-only and cannot be the sole evidence for a
  production action.

## Autoresearch Knob-Patch Smoke

Use forced knob-patch mode to verify the prompt-evolution path can mutate
position and MiroFish domain knobs without rewriting prompt prose.

```bash
rtk pnpm --dir mosaic-ts dev autoresearch trigger \
  --cohort cohort_default \
  --agent cio \
  --dry-run \
  --fake-llm \
  --mutation-mode knob_patch \
  --eval-days 5
```

Acceptance checks:

- the mutation result is `dry_run`, not `error`;
- the patch summary names an allow-listed domain knob path such as
  `/learnable_parameters/stop_loss_pct/value` or
  `/learnable_parameters/mirofish_override_hurdle/value`;
- no branch, commit, prompt-version row, or prompt-file write is created in
  dry-run mode;
- baseline prompts without `research-knobs` fences are bootstrapped from the
  runtime spec and domain knob catalog, while mixed or duplicate fences still
  fail closed.

## Paper Execution

Paper execution submits target-current delta orders only. The operator should
inspect the daily-cycle console section `paper execution deltas` and the TUI
paper tab before considering a run reviewable.

Acceptance checks:

- `target_weight` is the post-trade portfolio target.
- `delta_weight` is the required trade delta.
- skipped rows explain no delta, no order, or validation failure.
- rejected or partial fills remain visible as residual drift in the next run.

## Backtest Carry-Over

Backtest stage 1 must rebuild position state from the prior day's targets before
invoking the next daily cycle.

Focused verifier:

```bash
rtk pnpm --dir mosaic-ts test daily_cycle.test.ts
```

Acceptance checks:

- the 10-day replay test carries day N target positions into day N+1.
- `holding_days` increments.
- active replay positions carry realized PnL and residual-drift fields, and
  exited positions are recorded under `closed_positions` with exit reason and
  realized PnL.
- exits remove positions from the replay snapshot.
- new target weights are not interpreted as repeated buys.

## TUI Review

Run:

```bash
rtk pnpm --dir mosaic-ts dev dashboard --cohort cohort_default
```

Operator review surfaces:

- Today tab: `positions loaded`, `reviewed`, stale thesis count, stop-loss
  override count, target-current drift count, and explicit warnings. The stale
  count reads the `stale_thesis` risk flag as well as expired thesis status.
- Today tab action rows: `current%`, `target%`, `delta%`, `position_decision`,
  `thesis_status`, risk flags, fired caps, declared knob influence ids, and
  dissent, override, or review notes.
- Today tab agent detail line: compact CRO, autonomous execution, and CIO fired
  caps, declared influence ids, and unsupported influence ids.
- Paper tab: current paper positions, required target-current delta, latest
  submitted/filled paper trade by ticker from `paper.get_trades`, and residual
  target-current drift.
- Paper tab: recent backtest carry-over runs with action/trade-day coverage,
  stage-1 turnover proxy, observed holding-day proxy, stale-thesis proxy, and
  action mix. Exit-after-hold alpha, reduce opportunity cost, and stop-loss
  avoided drawdown remain marked `requires_stage2_scored_positions` until the
  qlib/stage-2 replay has scored position outcomes.
- MiroFish tab: scenario count, horizon, `as_of`, context hash, generator
  version, simulation-only guard, and per-position stress.
- Runtime injection disables MiroFish context when `as_of_date` is missing or
  later than the daily-cycle `as_of_date`; the run log records the disable
  reason and no MiroFish section is appended.

Required warning labels must remain literal:

- `UNREVIEWED_POSITION`
- `MISSING_POSITION_SNAPSHOT`
- `POSITION_DATA_STALE`
- `STOP_LOSS_OVERRIDE`
- `STALE_THESIS`
- `TARGET_WEIGHT_OVER_LIMIT`
- `TARGET_CURRENT_DRIFT`

## Migration Checklist

1. Keep old prompt text and output schema names intact while adding
   position-aware optional fields to CIO portfolio actions.
2. Generate or validate `research-knobs` from Prompt IR and the domain knob
   catalog; do not hand-maintain a second authority.
3. Reject historical runtime-source aliases in production catalog files. Use a
   one-shot migration adapter only for old inputs.
4. Confirm private zh/en prompts have exactly one `research-knobs` fence each and
   canonical knob parity.
5. Confirm scorecard migration columns exist in the local SQLite DB:
   `current_weight_pct`, `delta_weight_pct`, `position_decision`,
   `position_decision_reason`, `thesis_status`, `risk_flags_json`, and
   `dissent_notes`.
6. Run the TUI and inspect the latest CIO plan before releasing a prompt
   mutation that touches position or MiroFish cards.

## Canary, Recovery, And Rollback

Canary assignment is deterministic for the run key. Every eligible invocation
writes one idempotent, fsynced runtime event to the operator-owned JSONL path:

```bash
export MOSAIC_PROMPT_CANARY_EVENT_LOG=.mosaic/prompt-releases/canary-events.jsonl
rtk pnpm --dir mosaic-ts dev prompt-release canary \
  --release-id RELEASE_ID --approved-by operator:NAME \
  --reason 'approved bounded canary' --traffic-percent 10
rtk pnpm --dir mosaic-ts dev daily-cycle --cohort cohort_default --fake-llm
rtk pnpm --dir mosaic-ts dev prompt-release summarize-slo \
  --release-id RELEASE_ID \
  --events .mosaic/prompt-releases/canary-events.jsonl \
  --observation-ended-at 2026-07-10T12:00:00Z \
  --out .mosaic/prompt-releases/RELEASE_ID-slo.json
```

`summarize-slo` recomputes fixed thresholds from event hashes. Fewer than 20
eligible samples, any schema/token/order/exposure breach, mixed release
identity, duplicate conflict, or stage-snapshot drift blocks activation.

After an interrupted cross-repository mutation, start a fresh process and use
only the durable descriptor:

```bash
rtk pnpm --dir mosaic-ts dev autoresearch recover-transactions \
  --transaction-dir .mosaic/prompt-mutations/transactions
```

Rollback drill:

```bash
rtk pnpm --dir mosaic-ts dev prompt-release rollback \
  --release-id RELEASE_ID --approved-by operator:NAME \
  --reason 'operator rollback rehearsal'
rtk pnpm --dir mosaic-ts dev prompt-release status --release-id RELEASE_ID
```

The rolled-back release must no longer receive traffic, the aggregate active
pointer must resolve to its previous release, and the rollback audit event must
bind the same release and component hashes.

## Delivery Status

The CI delivery job consumes the upstream Python and TypeScript job results and
runs the fixed G0-G7 command contract. It writes a privacy-safe artifact with
hashes, exit codes, reason codes, commits, and evidence refs; it never embeds
prompt bodies or command output.

```bash
rtk uv run python scripts/run_prompt_evolution_delivery.py \
  --allow-blocked \
  --output .mosaic/prompt_evolution_delivery/status.json
rtk uv run python scripts/run_prompt_evolution_delivery.py \
  --verify .mosaic/prompt_evolution_delivery/status.json --allow-blocked
```

A local run remains `blocked` at G7 because it has no GitHub upstream job
receipt. In GitHub Actions, `python_ci` and `typescript_ci` must both bind the
same head SHA and report success. Any input hash or code commit drift invalidates
the artifact.

## Release Boundary

Do not promote a mutation when any of these are true:

- a current position is missing from CIO output;
- a stop-loss-breached holding remains `HOLD` unless it carries explicit
  counterevidence, override rationale, and the `cro_risk_override` risk flag;
- an active `max_single_name_weight` runtime card is breached unless the action
  carries both override rationale and the `cro_risk_override` risk flag;
- a stale-thesis holding lacks a `stale_thesis` risk flag and explicit review
  reason;
- a `position_decision` contradicts its action or target/current weight
  semantics;
- an active `max_sector_weight` runtime card is breached, or an action lacks
  sector exposure while that card is active;
- RKE report prior is the only evidence for `BUY`, `ADD`, `HOLD`, `REDUCE`, or
  `EXIT`;
- MiroFish is the only evidence for `BUY`, `ADD`, `HOLD`, `REDUCE`, or `EXIT`;
- MiroFish context is missing `scenario_count`, `horizon_days`, `as_of_date`,
  `context_hash`, or `generator_version`, or has an `as_of_date` later than the
  run date;
- a MiroFish-influenced `ADD`, `REDUCE`, or `EXIT` on an existing position
  lacks non-empty `dissent_notes`;
- an autonomous execution output breaches an active `min_delta_trade_weight`,
  `slippage_cap`, or `liquidity_floor` runtime card, or omits the slippage or
  liquidity field required by an active execution card;
- the run lacks current account or current market evidence;
- the prompt-leak guard fails;
- private prompt, account, report, or local cache content appears in public
  artifacts.
