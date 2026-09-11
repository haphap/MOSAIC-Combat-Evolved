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
