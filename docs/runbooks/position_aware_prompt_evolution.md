# Prompt Evolution Public Boundary

Production prompt evolution is implemented in the private prompt/KNOT
repository. This public repository intentionally contains no KNOT scoring,
scheduling, mutation, promotion, rollback, or research-policy values.

The public runtime is responsible only for:

- loading a private runtime through a content-addressed reference;
- rejecting a missing, stale, or hash-mismatched private release;
- keeping research policy outside model-visible prompt text;
- preserving public Agent, tool, output-schema, PIT, privacy, and RKE
  shadow-only contracts;
- exposing release-level `canary` and `rollback` operations without defining
  private research decisions.

Configure the private repository root through the operator environment, then
verify the boundary from the public checkout:

```bash
rtk proxy env MOSAIC_KNOT_RUNTIME_ROOT=/path/to/private-repo \
  uv run python scripts/check_private_knot_boundary.py --require-private
rtk pnpm --dir mosaic-ts prompt:check
rtk uv run python scripts/check_prompt_leaks.py
```

Bundled prompts are fake/offline fallbacks. They are not production champions
and contain no private research controls. Detailed operating procedures and
acceptance thresholds live only in the private repository.
