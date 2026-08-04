# Prompt Evolution Public Boundary

KNOT is a private, training-only Prompt Mutator. It reads a frozen summary of
Agent-specific training outcomes and produces a bilingual Prompt Candidate,
mutation summary, hypothesis, and parent lineage. Private Prompt bodies and
mutation policy remain in the private prompt repository.

The public repository owns the rest of the lifecycle:

- `prompt_experiment_runner.ts` runs Champion and Candidate against the same
  frozen split, model, tool, and Evaluator configuration;
- `prompt_promotion_policy.ts` applies Agent-specific outcome, minimum-sample,
  significance, tail, and one-time holdout gates;
- Prompt Release alone stages, starts a `canary`, activates, and performs
  `rollback`;
- `prompt_release_contract_ref_v2.json` binds the public Agent roster,
  structured-output contracts, tools, and outcome contracts;
- Darwinian weights remain a separate consumer of matured Agent outcomes, and
  RKE remains shadow-only.

The runtime never loads a KNOT executable, research knob, capability, pair,
receipt, replay capsule, or coordinator ledger. Those v1/v2 protocols are
retained only under `registry/knot/legacy_read_only_v2.json` for audit.

Verify the public boundary from the public checkout:

```bash
rtk pnpm --dir mosaic-ts prompt:check
rtk uv run python scripts/check_prompt_leaks.py
rtk uv run python -m pytest tests/test_knot_legacy_read_only.py \
  tests/test_prompt_optimizer_store.py tests/test_bridge_prompt_optimizer.py -q
```

Bundled prompts remain fake/offline fallbacks. Production Prompt Candidates
must be committed to the private Prompt repository and pass the ordinary
Prompt Release canary before activation.
