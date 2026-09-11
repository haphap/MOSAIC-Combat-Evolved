# RKE JSON Schema validation

`validate_json_schema_artifact` retains its result shape and delegates generic
structure checks to the installed `jsonschema` validator for the declared draft.
All 127 repository JSON Schemas currently declare draft 2020-12. RKE-specific
cross-artifact, PIT, privacy and promotion checks remain separate.

The old handwritten recursive validator and keyword-support list are removed.
No package or service is added. An explicit empty `referencing.Registry` blocks
external retrieval, including HTTP and file references. Local fragment refs are
resolved within the supplied Schema. Unknown drafts, invalid Schemas, unresolved
refs and nonterminating self-refs return rejection records. Finite data under a
recursive local Schema is supported.

The migration intentionally adopts JSON Schema semantics:

- Integral JSON numbers such as `1.0` satisfy `integer`; booleans do not.
- `true` is distinct from `1` in `const`, `enum` and uniqueness checks.
- `1` and `1.0` are duplicates under `uniqueItems`.
- `date` and RFC 3339 `date-time` formats are checked. Impossible dates and
  space-separated timestamps previously accepted by the custom parser fail.
- `else` and boolean subschemas are enforced; composition and local refs use
  the library implementation.

Errors are sorted and deduplicated within each artifact item. Diagnostics
report paths and rule failures without echoing rejected values. Existing
required-field/type/pattern/minimum/oneOf diagnostic wording is retained where
consumers rely on it. Generic diagnostics may otherwise change wording.

Existing public artifacts validate without regeneration. Private-dependent
tests skip when their inputs are absent; those skips do not demonstrate private
corpus validity. No private imports or persisted histories are rewritten.
Rollback restores the validator and its tests together, not artifact hashes.

## Read-only operator readiness

`build_operator_readiness_report(root)` and `operator-readiness --no-write`
inspect existing artifacts without copying directories or writing files. The
former `write_supporting_artifacts` argument is removed. Call
`write_operator_readiness_report` or the CLI without `--no-write` to explicitly
prepare and persist the handoff and its supporting reports. The CLI returns the
written report directly instead of rebuilding it.

Missing, malformed, or stale templates remain visible as failures. A status
query no longer regenerates temporary templates and reports them as the state
of the original directory. `generated_paths` retains the existing artifact
inventory meaning; it does not assert that the read-only call generated files.

Blank gold, source-license, and lockbox decisions are checked in memory by the
same validation functions used by the actual import commands. The existing
`blank_bundle_dry_run_does_not_promote` check records rejection of those blank
inputs without applying decisions. It does not claim a new promotion simulation
occurred. The explicit `promotion-dry-run` operation still simulates imports in
an isolated copy, and the readiness writer still refreshes that simulation via
the bundle writer. Import provenance, forbidden fields, policy thresholds, and
promotion checks are unchanged.

For already prepared inputs, writing and then reading yields the same checks.
Regression tests prohibit writes, directory creation, and directory copying
during a no-write query, compare all file contents and modification times, and
exercise malformed and stale inputs alongside real isolated promotion tests.
