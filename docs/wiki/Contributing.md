# Contributing

## Branch naming

- `phase-x-<feature>` / `fix-<scope>` / `chore-<scope>` for human work.
- Autoresearch auto-branches: `cohort/{name}/auto/{agent}/{YYYY-MM-DD}`.

Don't push directly to `main`; open a PR.

## Verification matrix (all green before a PR)

```bash
# TypeScript (from mosaic-ts/)
pnpm typecheck && pnpm lint && pnpm test
# Python (from repo root)
ruff check mosaic tests && python -m pytest -q
```

CI runs the same in `.github/workflows/ci.yml` (a Python lane + a TS lane). The TS lane builds a repo-root `.venv` with bridge deps so the live-sidecar tests can spawn the bridge.

Notes:
- `ruff` excludes the vendored collectors (`mosaic/dataflows/collectors`) — they're third-party, kept verbatim.
- The monolithic `python -m pytest tests/ -q` runs more than 2,000 tests serially;
  profile it with `--durations=80 --durations-min=0.1` and compare the CI-style
  per-file RKE split. Registry fixtures exclude all private prefixes and use
  copy-on-write clones when supported; they must never copy the full operator
  registry or make live FRED calls by default.
- A July 2026 local profile showed `tests/test_rke_cli.py` was the main drag: one CLI refresh contract test took 274s and several master-plan/promotion/review-progress CLI cases took 22-89s. Those tests now stub unrelated deep refresh/review-progress builders; the file should finish in about 10s locally. Accepted-import tests also stub unrelated downstream report-bundle rewrites; the remaining known local hotspot is `tests/test_rke_operator_handoff.py`, where deep handoff cases still exercise the real manual review progress builder.
- `tests/test_rke_tushare_reports.py` previously copied a 166 MB private-augmented registry nine times and depended on ignored review files. It now uses public-only registry fixtures plus synthetic review rows; all 27 tests should finish in about 3s and behave identically on a clean checkout.
- Some tests are guarded by `_HAS_QLIB` / dep-presence and skip cleanly when an optional extra (e.g. `pyqlib`, `bcrypt`, `numpy`) is absent, so the suite runs hermetically.
- CI also runs the prompt leak guard. It blocks autoresearch/private prompt artifacts in the project repo, but it is provenance-based and does not classify ordinary prompt content.
- Domain control catalogs are runtime contracts only. Keep TypeScript, schema,
  calculators, and visibility filters aligned, but never expose catalog cards,
  thresholds, or mutation metadata in bundled/private model-visible prompts.
  They are not KNOT mutation targets; changing them requires an explicit
  contract release and new Darwinian/KNOT track identities.
- Decision-layer control changes need their own contract, metric policy, PIT
  tests, and release migration. They cannot enter a private prompt behavior
  delta.
- Domain source bindings are coverage-specific: `direct_tool` and
  `derived_proxy` cards need matching evidence dependencies; `runtime_state`
  cards need runtime input sources.
- Domain card metrics are closed over the evaluation metric registry:
  `evaluation_metric`, `rollback_condition.metric`, and `secondary_metrics`
  must all be registered, horizon-compatible, and rollback-unit compatible;
  `rollback_condition.worse_by` must be nonnegative.
  Registry entries also need rollback-usable direction, value convention,
  baseline, PIT, and exclusion policies covering missing/stale inputs, source
  errors, lookahead risk, and incomplete fills. Signed-return metrics must be
  higher-is-better, while loss/cost conventions must be lower-is-better.
- KNOT mutations may change only reasoning order, counter-evidence checks, or
  expression strategy inside the private cohort-behavior block.
- CIO pre-decision cards must not consume `candidate_target_state`; only
  CRO/execution or downstream validation can depend on CIO's same-run proposal.
- Layer 4 must preserve the canonical proposal/freeze/CRO/execution/final
  sequence, carry the prior final target explicitly, and reuse one frozen
  prompt/source family through CIO final.
- `conflicting_evidence` confidence caps are fail-closed in prompt checks until
  a direction-adapter registry exists. Do not add that trigger to production
  knobs as a prose-only conflict rule.
- Runtime confidence caps revalidate both structured and fallback outputs
  against the agent schema after clamping. The validation view drops only the
  runtime-owned top-level `verified_knob_audit`; the returned envelope keeps the
  audit for sample exclusion and UI reporting.
- Agent outputs must not list disabled domain-card ids in
  `declared_knob_influence_ids`; runtime rejects those ids after scoped source
  resolution.
- Tool outputs that return JSON fallback metadata must populate
  `toolStatuses.fallback` and `toolStatuses.as_of`, including repeated calls
  served from the per-agent cache.
- Full claim/evidence rollout also requires runtime-owned result fingerprints,
  evidence ids, an extractor-visible evidence catalog, and claim refs for every
  recommendation/action. A standalone graph schema or validator is not enough.
- When a PR changes `prompts/mosaic/**` and you operate a private prompt repo, run `pnpm prompt:drift -- --base-ref origin/main` from `mosaic-ts/` with `MOSAIC_PROMPTS_REPO` set (`MOSAIC_PRIVATE_PROMPT_REPO` remains a compatibility alias). The check is staleness-aware: it only reports overrides not yet reconciled with the changed baseline *content* (tracked per-path in `prompts/mosaic/.baseline-sync.json` inside the private repo). After merging the baseline tool/schema/contract changes into a flagged override, rerun with `-- --mark-synced` to record it reconciled — it then stops alerting until that baseline content changes again.
- For scheduled operator checks, initialize `data/prompt-drift-state.json` with a known-good `baseline_ref`, then run `pnpm prompt:drift:scheduled` from `mosaic-ts/` with `MOSAIC_PROMPTS_REPO` set. The state advances when the check passes; prefer `-- --mark-synced` to acknowledge specific overrides precisely, or `-- --accept` to blanket-advance the state past all current findings.

## Conventions

- Keep each PR focused on a single concern; describe what changed / how it was tested / known limitations.
- New capabilities should be **opt-in** (default-off) and keep default behavior backward-compatible — see the MiroFish toggles and the autoresearch git-push flag for the pattern.
- Write minimal code that directly addresses the requirement; match existing style and the libraries already in use.
- Tool boundaries are strings/JSON only (no cross-language DataFrame transfer).

## Where things live

See [Architecture](Architecture.md) for the repo map. The canonical design + phase log is [`mosaic-tsplan.md`](../plans/mosaic-tsplan.md) under `docs/plans/`.
