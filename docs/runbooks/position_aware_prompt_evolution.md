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
rtk env MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_scorecard_store.py tests/test_bridge_scorecard_handlers.py -q \
  --basetemp .mosaic/tmp/pytest-position-aware-scorecard
rtk env MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_bridge_mirofish.py tests/test_mirofish.py -q \
  --basetemp .mosaic/tmp/pytest-position-aware-mirofish
rtk pnpm --dir mosaic-ts prompt:check
rtk uv run python scripts/check_prompt_leaks.py
```

For full RKE pytest, use `.mosaic/tmp` as `--basetemp`. Several RKE tests copy
the registry tree and can produce large temporary directories.

If `pytest tests/ -q` looks stuck locally, first check local private registry
size:

```bash
du -sh registry
du -ah registry/report_intelligence | sort -hr | head
```

On a checkout with ignored private `registry/report_intelligence/` artifacts,
`tests/test_rke_cli.py::test_rke_cli_master_plan_status_*` is usually the slow
section because those tests copy the full registry into `tmp_path`. In this
operator checkout, the largest local private file was
`registry/report_intelligence/analytical_footprint_reviewed.jsonl`, and the two
master-plan status tests measured about 46s and 92s. CI runs on the public
checkout and is much smaller; for local iteration prefer the targeted commands
above or the CI-style per-file RKE split instead of a monolithic
`pytest tests/ -q`.

## Prompt IR And Domain Knob Catalog

Position-aware prompt evolution uses Prompt IR, the runtime source registry, and
the domain knob catalog as the machine-readable authority for learnable
parameters. Do not hand-maintain a second knob list in docs or prompts.

```bash
rtk pnpm --dir mosaic-ts dev prompts export-domain-knob-catalog \
  --out registry/prompt_checks/domain_knob_catalog_v1.json
rtk pnpm --dir mosaic-ts dev prompts check-research-knobs \
  --cohort cohort_default \
  --enabled-agents '*'
rtk env MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_rke_schema_artifacts.py -q \
  --basetemp .mosaic/tmp/pytest-position-aware-schema
```

Acceptance checks:

- exported catalog validates against `schemas/domain_knob_catalog_v1.schema.json`;
- Prompt IR contracts keep runtime tool, metric, current-data, and RKE-prior
  guardrails aligned with the TypeScript runtime registry;
- private zh/en prompts have exactly one canonical `research-knobs` fence for
  enabled agents;
- historical runtime-source aliases are rejected in production catalog files.

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
- `portfolio_actions[*]` include `current_weight`, `target_weight`,
  `delta_weight`, `position_decision`, `thesis_status`, and `risk_flags`.
- `position_decision` semantics are enforced: `ADD` maps to positive-delta
  `BUY`, `REDUCE` trims an existing holding, `EXIT` maps to zero-weight `SELL`,
  and `HOLD` maps to an existing held position.
- fixtures may include `sector`; it is required when testing an active
  `max_sector_weight` runtime card.

## MiroFish Portfolio Stress Fixture

`mirofish generate` and `mirofish train` accept current portfolio fixtures so
scenario stress can be computed for existing holdings. The fixture file may be a
JSON array of positions or an object with `current_positions`, `sector_exposure`,
and `theme_exposure`. Inline JSON flags override file values.

Example `.mosaic/tmp/mirofish-positions.json`:

```json
{
  "current_positions": [
    {
      "ticker": "600519.SH",
      "name": "Kweichow Moutai",
      "current_weight": 0.08,
      "sector": "consumer",
      "thesis": "premium consumption compounder"
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
  override count, target-current drift count, and explicit warnings.
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

## Release Boundary

Do not promote a mutation when any of these are true:

- a current position is missing from CIO output;
- a stop-loss-breached holding remains `HOLD` without override rationale;
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
