# Agent Data Rollout Runbook

This runbook operates the pre-capability data gate for the 26-stage Agent
cycle. It does not change trading promotion gates. Report-derived context
remains shadow-only.

## Modes and safety boundary

Normal `daily-cycle` does not set `MOSAIC_ENSURE_SNAPSHOT_MODE`. Its Agent data
path is always warm-first: use the existing cache when present; on a miss,
invoke the existing source tool and retain the result for later calls.

Set `MOSAIC_ENSURE_SNAPSHOT_MODE` only for an explicit snapshot rollout:

- `shadow` writes source receipts, snapshots, cycle events, and publications
  only below `MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT`;
- `enforce` uses the configured production stores and requires a production
  cycle authority.

The live CLI and Bridge fail closed with stable alert tokens:

- `P1_ENSURE_MODE_INVALID` — a configured snapshot rollout value is not
  `shadow|enforce`;
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

Resume must use the same checkpoint path, date, and cohort; it continues after
the accepted stage prefix and never replays that prefix. The checkpoint belongs
to that trading day only, so the next trading day starts with a new checkpoint
path. Thinking must not be defaulted off, and the token limit remains an
operator/provider capability setting rather than a machine-specific constant.
The commands above remain a non-production structured-smoke route; the same-day
checkpoint flags are also available to live and paper daily-cycle runs.

## One-day normal cycle without paper execution

For an operator-approved real-data diagnostic, use the normal warm-first path,
not structured smoke or paper execution. If the completion-token setting changes,
start with a new checkpoint; never resume an accepted prefix produced under a
different setting. Set an operator-approved per-request completion limit
explicitly; the current NInfer server defaults to 8192 tokens when no limit is
sent. The model server also has a finite context limit.

```bash
set -euo pipefail
export MOSAIC_ENV_FILE="${MOSAIC_ENV_FILE:?set private environment file}"
set -a
source "${MOSAIC_ENV_FILE}"
set +a
export MOSAIC_REPO_ROOT="${MOSAIC_REPO_ROOT:?set repository root}"
export MOSAIC_PYTHON="${MOSAIC_PYTHON:?set repository Python executable}"
export PYTHONPATH="${MOSAIC_REPO_ROOT}"
export MOSAIC_BRIDGE_TIMEOUT_MS="${MOSAIC_BRIDGE_TIMEOUT_MS:-1800000}"
export MOSAIC_LLM_PROVIDER="${MOSAIC_LLM_PROVIDER:?set provider}"
export MOSAIC_LLM_BASE_URL="${MOSAIC_LLM_BASE_URL:?set provider endpoint}"
export MOSAIC_LLM_MODEL="${MOSAIC_LLM_MODEL:?set provider model}"
: "${MOSAIC_LLM_API_KEY:?load API key from env/secret store}"
export MAX_TOKENS="${MAX_TOKENS:?set operator-approved completion limit}"
export MOSAIC_LLM_THINKING_MODE="${MOSAIC_LLM_THINKING_MODE:-enabled}"
export MOSAIC_RKE_ENABLED=0
export RUN_DATE="${RUN_DATE:?set YYYY-MM-DD trading date}"
export MOSAIC_PROMPTS_REPO="${MOSAIC_PROMPTS_REPO:?set private Prompt repository}"
unset MOSAIC_ENSURE_SNAPSHOT_MODE MOSAIC_LLM_MAX_TOKENS

cd "${MOSAIC_REPO_ROOT}"
rtk mkdir -p .mosaic/tmp
CYCLE_ARTIFACT_ROOT="$(mktemp -d "${MOSAIC_REPO_ROOT}/.mosaic/tmp/normal-cycle.XXXXXX")"
CHECKPOINT_PATH="${CYCLE_ARTIFACT_ROOT}/${RUN_DATE}.checkpoint.json"
OUTPUT_PATH="${CYCLE_ARTIFACT_ROOT}/${RUN_DATE}.state.json"
daily_cycle_args=(
  --cohort cohort_default --date "${RUN_DATE}"
  --checkpoint "${CHECKPOINT_PATH}" --out "${OUTPUT_PATH}"
  --llm-provider "${MOSAIC_LLM_PROVIDER}" --model "${MOSAIC_LLM_MODEL}"
  --base-url "${MOSAIC_LLM_BASE_URL}" --prompts-repo "${MOSAIC_PROMPTS_REPO}"
  --agent-timeout-seconds 1800 --max-tokens "${MAX_TOKENS}"
)
rtk pnpm --dir mosaic-ts dev daily-cycle "${daily_cycle_args[@]}"
```

No `--paper-positions`, `--paper-execute-deltas`, or `--resume` is used on the
initial call. After an interruption, resume only with the same arguments and
checkpoint plus `--resume`. Completion requires all 26 stages and a written
final state; this route makes no paper fills.

If pnpm stops before the CLI because its pre-run check reports only workspace
structure drift, do not approve a `node_modules` purge. First verify the
checked-out lockfile matches the installed lockfile byte-for-byte and that
typechecking passes. Only then run the same CLI with pnpm's check set to `warn`:

```bash
rtk proxy cmp -s mosaic-ts/pnpm-lock.yaml mosaic-ts/node_modules/.pnpm/lock.yaml
rtk pnpm --config.verify-deps-before-run=warn --dir mosaic-ts typecheck
rtk pnpm --config.verify-deps-before-run=warn --dir mosaic-ts dev daily-cycle "${daily_cycle_args[@]}"
```

## Twenty-trading-day normal paper cycle

Run 20 separate normal `daily-cycle` processes. This is not replay or backtest:
every cycle uses the normal Prompt, Darwinian, Agent/tool, accepted-output,
scorecard, and paper-order paths.
The active paper account is the only state carried between dates. A checkpoint
belongs only to one date and is used only to resume an interrupted cycle on
that date. Do not run snapshot rollout, pre-generation, or backfill commands on
this path. Agent tools use their normal cache-first behavior and call the
configured source on a cache miss.

For a requested start of 2025-06-15, the first exchange trading day is
2025-06-16. Run these dates in order, one invocation at a time:

```text
2025-06-16  2025-06-17  2025-06-18  2025-06-19  2025-06-20
2025-06-23  2025-06-24  2025-06-25  2025-06-26  2025-06-27
2025-06-30  2025-07-01  2025-07-02  2025-07-03  2025-07-04
2025-07-07  2025-07-08  2025-07-09  2025-07-10  2025-07-11
```

Configure the normal daily-cycle path and one private artifact directory. Do
not reuse a checkpoint from another date.

```bash
set -euo pipefail
export MOSAIC_ENV_FILE="${MOSAIC_ENV_FILE:?set private environment file}"
set -a
source "${MOSAIC_ENV_FILE}"
set +a
export MOSAIC_REPO_ROOT="${MOSAIC_REPO_ROOT:?set repository root}"
unset MOSAIC_ENSURE_SNAPSHOT_MODE
export MOSAIC_PYTHON="${MOSAIC_PYTHON:?set repository Python executable}"
export PYTHONPATH="${MOSAIC_REPO_ROOT}"
export MOSAIC_BRIDGE_TIMEOUT_MS="${MOSAIC_BRIDGE_TIMEOUT_MS:-1800000}"
export MOSAIC_LLM_PROVIDER=api
export MOSAIC_LLM_BASE_URL="${MOSAIC_LLM_BASE_URL:-http://127.0.0.1:18080/v1}"
export MOSAIC_LLM_MODEL="${MOSAIC_LLM_MODEL:-qwen3.8-27b}"
export MOSAIC_LLM_API_KEY="${MOSAIC_LLM_API_KEY:-ninfer-local}"
export MOSAIC_LLM_THINKING_MODE="${MOSAIC_LLM_THINKING_MODE:-enabled}"
export MAX_TOKENS="${MAX_TOKENS:?set an operator/provider-approved completion limit}"
export AGENT_TIMEOUT_SECONDS="${AGENT_TIMEOUT_SECONDS:?set an operator-approved timeout}"
export MOSAIC_PROMPTS_REPO="${MOSAIC_PROMPTS_REPO:?set private Prompt repository}"
export MOSAIC_REGISTRIES_REPO="${MOSAIC_REGISTRIES_REPO:?set private RKE registry repository}"
export CYCLE_ARTIFACT_ROOT="${CYCLE_ARTIFACT_ROOT:?set private cycle artifact root}"

cd "${MOSAIC_REPO_ROOT}"
rtk mkdir -p "${CYCLE_ARTIFACT_ROOT}"
```

Before day 1, verify that the intended paper account is active. Do not reset or
replace it during the 20 dates:

```bash
rtk pnpm --dir mosaic-ts dev paper account
rtk pnpm --dir mosaic-ts dev paper positions
```

For each listed date, set `RUN_DATE` and derive a new checkpoint and output
path.

```bash
export RUN_DATE=2025-06-16
export CHECKPOINT_PATH="${CYCLE_ARTIFACT_ROOT}/${RUN_DATE}.checkpoint.json"
export OUTPUT_PATH="${CYCLE_ARTIFACT_ROOT}/${RUN_DATE}.state.json"

daily_cycle_args=(
  --cohort cohort_default
  --date "${RUN_DATE}"
  --paper-positions
  --paper-execute-deltas
  --checkpoint "${CHECKPOINT_PATH}"
  --out "${OUTPUT_PATH}"
  --llm-provider "${MOSAIC_LLM_PROVIDER}"
  --model "${MOSAIC_LLM_MODEL}"
  --base-url "${MOSAIC_LLM_BASE_URL}"
  --prompts-repo "${MOSAIC_PROMPTS_REPO}"
  --agent-timeout-seconds "${AGENT_TIMEOUT_SECONDS}"
  --max-tokens "${MAX_TOKENS}"
)
rtk pnpm --dir mosaic-ts dev daily-cycle "${daily_cycle_args[@]}"
```

If that invocation is interrupted after at least one accepted Agent stage,
resume only that date with the same arguments:

```bash
rtk pnpm --dir mosaic-ts dev daily-cycle "${daily_cycle_args[@]}" --resume
```

A date is complete only when all 26 stages have an accepted-output or
sealed-skip outcome, the final state was written, and paper execution finished.
Then inspect the paper account and positions, select the next listed
`RUN_DATE`, and use its new checkpoint path. Do not copy positions between
files; `--paper-positions` reads the account updated by the preceding
successful date.

```bash
rtk pnpm --dir mosaic-ts dev paper account
rtk pnpm --dir mosaic-ts dev paper positions
```

A retry does not add a date. Diagnose and fix the failure, then retry the same
date before moving to the next one. Keep the paper account and any valid
same-day checkpoint. These paper fills are normal operational paper fills, not
historical-performance evidence.

## Enforce canary and rollback drill

Promotion to `enforce` requires the 20-day evidence, current KNOT fixed point,
final full validation gate, and operator approval. Remove the shadow-root
override from the production service and set:

```bash
export MOSAIC_ENSURE_SNAPSHOT_MODE=enforce
```

Run source admission and the production daily cycle with
`--cycle-kind production` for the canary date. The production cycle must create
exactly one `COMMITTED` event/publication for its date and cohort.

The mandatory rollback drill is a real configuration transition:

1. Stop new production-cycle starts and preserve the enforce publication and
   database hashes.
2. Change the service to `shadow` with a new isolated root, or remove the
   snapshot-rollout cycle kind and unset `MOSAIC_ENSURE_SNAPSHOT_MODE` for the
   shortest emergency window. Restart it; do not mutate an existing process
   environment in place.
3. In `shadow`, run a SHADOW cycle and prove production hashes are unchanged.
   On the normal path, prove no cycle event or publication was created.
4. Inspect both ledgers read-only. A failed/aborted run may retain raw archives
   and snapshots, but it must have no consumable partial publication.
5. Before the next production cycle, restore an explicit `enforce`, restart,
   and run the next target date. Invalid mode or namespace mismatch is a P1 and
   must stop the rollout.

Rollback is complete only when the restored enforce cycle commits normally,
the intervening shadow/normal interval produced no production publication, and
all partial or aborted authority remains unreadable by production consumers.
