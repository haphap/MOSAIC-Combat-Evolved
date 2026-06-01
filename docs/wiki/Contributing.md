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
- Some tests are guarded by `_HAS_QLIB` / dep-presence and skip cleanly when an optional extra (e.g. `pyqlib`, `bcrypt`, `numpy`) is absent, so the suite runs hermetically.
- CI also runs the prompt leak guard. It blocks autoresearch/private prompt artifacts in the project repo, but it is provenance-based and does not classify ordinary prompt content.
- When a PR changes `prompts/mosaic/**` and you operate a private prompt repo, run `pnpm prompt:drift -- --base-ref origin/main` from `mosaic-ts/` with `MOSAIC_PRIVATE_PROMPT_REPO` set. Any reported override needs a private baseline-sync branch or an explicit waiver before release.
- For scheduled operator checks, initialize `data/prompt-drift-state.json` with a known-good `baseline_ref`, then run `pnpm prompt:drift:scheduled` from `mosaic-ts/` with `MOSAIC_PRIVATE_PROMPT_REPO` set. The state advances when the check passes; after a private baseline-sync review or explicit waiver, rerun the same command with `-- --accept` to acknowledge the findings and advance the state.

## Conventions

- Keep each PR focused on a single concern; describe what changed / how it was tested / known limitations.
- New capabilities should be **opt-in** (default-off) and keep default behavior backward-compatible — see the MiroFish toggles and the autoresearch git-push flag for the pattern.
- Write minimal code that directly addresses the requirement; match existing style and the libraries already in use.
- Tool boundaries are strings/JSON only (no cross-language DataFrame transfer).

## Where things live

See [Architecture](Architecture.md) for the repo map. The canonical design + phase log is [`mosaic-tsplan.md`](../../mosaic-tsplan.md) at the repo root.
