# Agent Data Rollout Runbook

This runbook operates the pre-capability data gate for the 26-stage Agent
cycle. It does not change trading promotion gates. Report-derived context
remains shadow-only.

## Modes and safety boundary

`MOSAIC_ENSURE_SNAPSHOT_MODE` must be explicit for every live run:

- `shadow` writes source receipts, snapshots, cycle events, and publications
  only below `MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT`;
- `enforce` uses the configured production stores and requires a production
  cycle authority;
- `off` preserves the legacy path and creates no cycle authority. After Gate F
  it is an emergency rollback mode, not a normal configuration.

The live CLI and Bridge fail closed with stable alert tokens:

- `P1_ENSURE_MODE_MISSING` — a live process has no configured mode;
- `P1_ENSURE_MODE_INVALID` — the configured value is not
  `off|shadow|enforce`;
- `P1_ENSURE_MODE_DRIFT` — the requested cycle kind can escape its configured
  namespace.

Alert on any of these tokens as P1 after Gate F. Never put provider keys in a
command, log, runbook, or Git. Load them through the deployment secret store.

## One-day structured-smoke acceptance and checkpoint resume

This is a non-production contract-acceptance route only. Set operator-owned
environment values; do not put API keys in commands or files. The empty
portfolio fixture must be exactly the two-byte JSON array `[]` (with no
positions object or extra fields).

```bash
set -euo pipefail
export MOSAIC_REPO_ROOT="${MOSAIC_REPO_ROOT:?set repository root}"
export SMOKE_DATE="${SMOKE_DATE:?set YYYY-MM-DD trading date}"
export MOSAIC_LLM_PROVIDER="${MOSAIC_LLM_PROVIDER:?set provider from operator configuration}"
export MOSAIC_LLM_BASE_URL="${MOSAIC_LLM_BASE_URL:?set provider endpoint from operator configuration}"
export MOSAIC_LLM_MODEL="${MOSAIC_LLM_MODEL:?set provider model from operator configuration}"
export MOSAIC_LLM_API_KEY="${MOSAIC_LLM_API_KEY:?load API key from env/secret store}"
export MAX_TOKENS="${MAX_TOKENS:?set an operator/provider-approved capability value}"
export AGENT_TIMEOUT_SECONDS="${AGENT_TIMEOUT_SECONDS:?set an operator-approved timeout}"
export CHECKPOINT_PATH="${CHECKPOINT_PATH:?set isolated checkpoint path}"
export POSITIONS_PATH="${POSITIONS_PATH:?set isolated positions path}"
export OUTPUT_PATH="${OUTPUT_PATH:?set isolated final-state output path}"
export MOSAIC_LLM_THINKING_MODE="${MOSAIC_LLM_THINKING_MODE:-enabled}"

cd "$MOSAIC_REPO_ROOT"
mkdir -p .mosaic/tmp
SMOKE_ROOT="$(mktemp -d '.mosaic/tmp/structured-smoke.XXXXXX')"
eval "$(uv run python scripts/build_structured_smoke_fixtures.py \
  --root \"$SMOKE_ROOT\" --date \"$SMOKE_DATE\" --shell-exports)"
test -f "$POSITIONS_PATH"
printf '[]' | cmp -s - "$POSITIONS_PATH"

daily_cycle_args=(
  --cohort cohort_default --date "$SMOKE_DATE" --structured-smoke
  --llm-provider "$MOSAIC_LLM_PROVIDER" --model "$MOSAIC_LLM_MODEL"
  --base-url "$MOSAIC_LLM_BASE_URL" --checkpoint "$CHECKPOINT_PATH"
  --current-positions-file "$POSITIONS_PATH" --out "$OUTPUT_PATH"
  --agent-timeout-seconds "$AGENT_TIMEOUT_SECONDS" --max-tokens "$MAX_TOKENS"
)
# Initial invocation: no --resume.
pnpm --dir mosaic-ts dev daily-cycle \
  "${daily_cycle_args[@]}"
```

After an interruption, invoke the same arguments with only `--resume` added:

```bash
pnpm --dir mosaic-ts dev daily-cycle "${daily_cycle_args[@]}" --resume
```

Resume must
open the same checkpoint identity, stage order, and hashes; it continues after
the accepted stage prefix and never replays that prefix. Any identity, order,
or hash drift fails closed. Thinking must not be defaulted off, and the token
limit remains an operator/provider capability setting rather than a machine-
specific constant. Do not use this route for live, paper, or production writes.

## Historical replay procedure

Choose a period for which the required historical data already exists. Use one
persistent, private shadow root for all 20 trading-date replay cycles; this gate
does not wait for current-date capture or a market-close window.
Do not reuse pytest roots or a root that contains a failed experiment with a
different manifest.

```bash
export RUN_DATE=YYYY-MM-DD
export MOSAIC_ENSURE_SNAPSHOT_MODE=shadow
export MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT=/private/path/agent-data-shadow
export MOSAIC_PYTHON=/path/to/repo/.venv/bin/python
export PYTHONPATH=/path/to/repo
export MOSAIC_BRIDGE_TIMEOUT_MS=1800000

rtk mkdir -p "${MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT}"
```

The 30-minute bridge budget covers the measured first A-share historical
capture while still failing a stuck route promptly. A route-only Relationship
capture must select at most one active security per registered
`(role, direction)` partition before it calls `top10_holders`; it must never
expand to every listed company. Increasing the timeout is not a remedy for a
scope expansion. Cached replays return without consuming the first-capture
budget.

Before collectors run, record SHA-256, size, and mtime for the configured
production materialization and scorecard databases. Repeat the same commands
after the shadow run; every value must be unchanged.

Run only the historical route that owns a failure while diagnosing:

```bash
rtk pnpm --dir mosaic-ts dev data source-backfill \
  --route tushare.eco_cal.cny --from "${RUN_DATE}" --to "${RUN_DATE}" \
  --historical-replay
rtk pnpm --dir mosaic-ts dev data source-backfill \
  --route tushare.eco_cal.usd --from "${RUN_DATE}" --to "${RUN_DATE}" \
  --historical-replay
rtk pnpm --dir mosaic-ts dev data source-backfill \
  --route tushare.eco_cal.eur --from "${RUN_DATE}" --to "${RUN_DATE}" \
  --historical-replay
rtk pnpm --dir mosaic-ts dev data source-backfill \
  --route tushare.relationship_graph --from "${RUN_DATE}" --to "${RUN_DATE}" \
  --historical-replay
```

For the Relationship probe, verify that the resolved `capture_scope` contains
no more securities than the registered `(role, direction)` partitions and that
the `top10_holders` query count equals the number of distinct selected
securities. Stop the run if either bound is exceeded; do not continue to an
all-agent preflight.

The replay receipt must retain the real retrieval time and the historical data
or vintage lineage. It must not claim that the replay was an original
production capture on `RUN_DATE`. Tushare remains the primary source; an
alternate provider is allowed only where its separate contract, fallback
trigger, license decision, and lineage receipt are active.

After every failing route has been resolved or has a documented external
blocker, evaluate the exact 26-route admission once:

```bash
rtk pnpm --dir mosaic-ts dev data source-preflight \
  --as-of "${RUN_DATE}" --all-agents
```

Do not start the Agent graph unless this returns `READY`. Then run the replay
cycle in the isolated shadow namespace without paper execution:

```bash
rtk pnpm --dir mosaic-ts dev daily-cycle \
  --cohort cohort_default \
  --date "${RUN_DATE}" \
  --cycle-kind replay
```

A successful day requires all of the following in the same target date and
shadow namespace:

- 26/26 external route eligibility receipts are `READY`;
- every runtime consumer seals the required runtime authority or a strict
  not-required receipt;
- all 26 stages have exactly one accepted-output or sealed-skip outcome;
- exactly one terminal `COMMITTED` event and one matching publication exist;
- no `OPEN` or `ABORTED` event is consumed by scorecard or KNOT;
- production database hashes, sizes, and mtimes are unchanged;
- no key, provider payload, research prose, or private cache appears in logs or
  Git.

Use the shadow ledger read-only for operational counts. Do not edit rows:

```bash
rtk sqlite3 \
  "file:${MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT}/agent_materialization/materialization.sqlite3?mode=ro" \
  "select target_date,state,count(*) from agent_cycle_events group by target_date,state order by target_date,state;"
rtk sqlite3 \
  "file:${MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT}/agent_materialization/materialization.sqlite3?mode=ro" \
  "select target_date,count(*) from agent_cycle_publications group by target_date order by target_date;"
```

## Twenty-trading-day gate

Select one already-existing historical interval and count distinct exchange
trading dates, not calendar days or retries. The 20 replay cycles can run now;
they do not require 20 future wall-clock days. A retry
does not add a day. A day with a blocked or aborted cycle remains in the audit
history but does not satisfy the gate. Retain per-day route status, freshness,
revision selection, materialization latency, terminal event hash, publication
hash, and production-isolation hashes.

Gate F requires 20 distinct successful historical trading dates and zero unresolved P1
mode alerts, implicit fallbacks, future evidence, partial capability, or
private-data leakage. Keep the real replay retrieval time; do not relabel a
replay as an original production capture or generate synthetic days.

The historical replay/source-route count is a separate metric from the Agent
roster and tool count: the `26` route admission above counts source routes and
their eligibility receipts. Do not mechanically translate it into Agent
stages or `29` tools without a code-backed route definition.

## Enforce canary and rollback drill

Promotion to `enforce` requires the 20-day evidence, current KNOT fixed point,
final full validation gate, and operator approval. Remove the shadow-root
override from the production service and set:

```bash
export MOSAIC_ENSURE_SNAPSHOT_MODE=enforce
```

Run source admission and the production daily cycle for the canary date. The
production cycle must create exactly one `COMMITTED` event/publication for its
date and cohort.

The mandatory rollback drill is a real configuration transition:

1. Stop new production-cycle starts and preserve the enforce publication and
   database hashes.
2. Change the service to `shadow` with a new isolated root, or to `off` for the
   shortest emergency window. Restart it; do not mutate an existing process
   environment in place.
3. In `shadow`, run a SHADOW cycle and prove production hashes are unchanged.
   In `off`, prove no cycle event or publication was created.
4. Inspect both ledgers read-only. A failed/aborted run may retain raw archives
   and snapshots, but it must have no consumable partial publication.
5. Before the next production cycle, restore an explicit `enforce`, restart,
   and run the next target date. Missing/invalid mode or namespace mismatch is
   a P1 and must stop the rollout.

Rollback is complete only when the restored enforce cycle commits normally,
the intervening shadow/off interval produced no production publication, and
all partial or aborted authority remains unreadable by production consumers.
