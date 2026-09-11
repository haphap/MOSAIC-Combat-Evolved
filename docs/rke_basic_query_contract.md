# RKE basic query contract v2

The default Agent query and `export-rke-agent-context` read only
`forecast_claims.jsonl` and `report_metadata.jsonl`. Report outcome labels,
source/viewpoint performance profiles, weighted contexts, recipes, tool gaps,
and stock/industry snapshots are offline research inputs. Their absence,
content changes or malformed JSON cannot prevent a basic query or change its
result. The explicit `build_rke_agent_research_context_from_rows` API still
accepts those inputs for offline analysis.

The context version is `rke_agent_research_context_v2`. Agent Markdown shows
the target, direction, horizon, regime, ranking and current-data/shadow-use
guards. Performance scores, outcome statistics, failure tags, recipes and
tool gaps are omitted; the formatter no longer validates those unused fields
or compares the declared forbidden-field count with a local constant. The
recursive privacy check still inspects the entire input, including unused
fields. Identity, as-of, role filtering, required target metadata and shadow
policy checks continue to reject invalid contexts.

The rank v1 algorithm and its rank/priority audit remain in place. With no
optional inputs loaded, default ranking uses target specificity and the
original input order to break ties; offline scores no longer affect default
selection. The JSON result still contains the existing neutral/empty derived
fields. Removing these fields and replacing the ranking algorithm are separate
migrations. This change makes no claim about trading benefit or measured live
Agent success rates.

## Source receipts and hashes

New source receipts use `rke_source_evidence_v2`; the shared receipt envelope
remains `source_capture_receipt_v1`. Nonempty results still require private
source identities and source-registry/metadata PIT evidence. These source
registries are additional authority inputs, not removed by the two-file query
contract. Empty results still require both basic files to exist, an exact
reconstructed result and a no-prior reason. Missing files cannot be sealed as
true empty. Only those two basic files are hashed for empty coverage, down
from ten. Source provenance, request/content binding and authorization remain
unchanged.

The displayed context hash and rank audit still have a consumer in the current
`rke_footprints.ts`; they are retained pending that consumer's migration.
The existing version-derived `schema_hash`, repeated empty materialization and
shared receipt validations are also outside this change.

## Migration and rollback

New contexts contain the v2 version, so their context/content hashes and new
receipt identities change. Historical stored receipts retain their original
versions and hashes; this change does not rewrite private history or upgrade
frozen results in place. Existing sealed historical results remain governed
by their recorded authority. A new query must be materialized with one code
revision throughout, using the corresponding context and source parser
versions.

Rollback restores this change's Python and TypeScript contracts together.
Create fresh materializations with the restored code; do not relabel a v2
context or reuse its receipts as v1. No private input file is migrated or
deleted by this change.
