# RKE research query contract v4

The CLI export, Bridge JSON API and Agent materialization read only
`forecast_claims.jsonl`, `report_metadata.jsonl` and
`analytical_footprints.jsonl`. Outcome labels,
source/viewpoint profiles, weighted contexts, recipes, gaps and stock/industry
snapshots are offline artifacts. Their absence, changes or malformed JSON do
not change the basic query. The row-based builder now has the same three-input
contract: it no longer accepts or constructs those derived fields. Offline
Report Intelligence builders remain responsible for their own artifacts.

## Selection and output

Contexts use `rke_agent_research_context_v4` and rank policy
`rke_agent_research_context_rank_v4`. Authorized, point-in-time research cases
are eligible across stock, industry and supported Agent roles. Lexical overlap
between the case's question, historical regime, reasoning and role/sector
preferences ranks cases before ticker matches, legacy metadata specificity and
recency. Role labels are preferences; an absent label is not a permission failure.
This is lexical retrieval, not an embedding model or a guarantee of relevance.
Independent sources are preferred among equally relevant cases. Existing forecast
records retain their stock, industry and role restrictions.

Availability uses the latest supplied claim signal, claim as-of, report publication
and accessibility date. A later accessibility date cannot be overridden by an
earlier publication date. Case source identity, internal-use permission and PIT
remain required; runtime formatting rejects invalid or future availability.

Sector and Superinvestor frozen plans provide a broad RKE request in addition to
stock/sector-preferred requests. Active Superinvestor schemas make those preferences
optional while leaving frozen historical overlays untouched. Empty trading candidate
sets permit RKE-only queries, not other private market queries. Identity, dates,
receipts, finite query requests and trade scopes remain enforced. Prepare a new
bundle to use the new request; old sealed bundles remain immutable. Current Macro
runtime tool rosters still contain only their snapshot tool, so Macro query API
support is distinct from runtime tool authorization. Gate D maps the four historical
Superinvestor RKE bindings to active argument contracts while retaining every other
contract field; both historical and active identities remain in the evidence.

Research cases include the source question, historical regime, reasoning, evidence,
conditions and conclusion. They remain private derived content, and must be
reassessed against current data before use. Other basic items contain redacted
identity, target, direction, horizon, regime,
availability and shadow/current-data requirements. They contain no historical
scores, weights, outcome summaries, recipe/gap IDs or snapshot features.
Markdown renders these facts without the old context hash, rank/priority audit
banner or derived ranking explanations. Rank and summary counts remain JSON
metadata; they are not runtime permission checks. Privacy validation still
inspects the entire input, including unused fields. Required identity, scope
and shadow-use constraints still reject invalid input.

The old post-run re-query attribution is removed with the PR #28 change.
Completed Agent outputs alone do not establish RKE use. Legacy benchmark
footprints with rank v1 remain readable; new research contexts use rank v4. No
historical hash or usage record is relabeled. This change does not establish
trading benefit or a measured live success-rate improvement.

## Source receipts and hashes

RKE source receipts use envelope `source_capture_receipt_v2` and explicit
`authority.parser_version=rke_source_evidence_v3`. The shared Schema file
`source_capture_receipt_v1.schema.json` validates both historical v1 and RKE v2
without duplicating the common structure. Its v1 branch still requires
`content.schema_hash`. The v2 branch is restricted to the private RKE route
and parser v3 and forbids that field: the retired digest only encoded parser
and route identifiers, not Schema content. Other source routes remain v1.

Nonempty results still require private source identities and source-registry /
metadata PIT evidence. The source authority now owns RKE reading, selection,
formatting and sealing in one call. It does not accept caller-supplied RKE text
or an empty-result assertion. Each basic file is read once; parsing and empty
coverage hashing use those same bytes. Metadata for nonempty source attestation
comes from the same read. File mtime/size caching is removed, so subsequent
queries observe same-size updates even when the timestamp is preserved.

Empty attestation requires all three basic files and a no-prior reason; missing
inputs are not true empty. It hashes the three consumed inputs, and builds the
context once instead of twice. These are the exact inputs consumed by this
query, not a transaction across concurrently edited files. Private input bytes
and metadata remain inside server-side materialization and are never rendered.
Persisted receipt registration still rejects conflicts for an existing query.
The source archive digest remains in the PIT vintage query and parent capture
reference because route eligibility independently requires the parent binding.

Trusted receipt construction validates the owned body and hashes it once.
Loading an external or persisted receipt still validates the body and hash.
Staged receipt construction and loading share PIT time checks, including
capture/knowledge ordering and the as-of cutoff, without revalidating a just
constructed receipt. Request/content hashes, upstream source identity and
cross-process authorization remain distinct boundaries.

## Query authorization preparation

Deferred query descriptors and their signed KNOT context now use the same
validated active authority within one capability preparation. This removes a
second contract-bundle read and prevents those two steps from observing
different revisions. No authority is cached across preparations. Missing and
duplicate tool contexts have distinct errors at preparation, call and audit
boundaries. Invalid preparation does not issue a capability. Execution-time
signature, expiry, revocation and binding checks remain in place.

The historical 18 authorization failures lack the corresponding L4 snapshots;
these changes establish current behavior, not a reconstructed historical cause.

## Runtime snapshot authorities

The five L3/L4 bound snapshot contracts now use v2. They omit
`role_context_hash`: its only consumers recomputed the same subset, while
`snapshot_hash` already binds all role-context content. Changing role context
without resealing the snapshot still fails. Candidate universe, constraints
and candidate scope hashes remain: they bind the query authorization scope,
capability manifest and account/position policy, independently of display.
The current Bridge rejects v1 snapshots rather than silently changing their
meaning. Historical files are left intact; new runs must materialize v2 inputs.

## Migration and rollback

New contexts and source receipts get new versions and identities. Historical
sealed results retain their original fields and hashes; no private history or
frozen result is rewritten in place. Materialize a new query using one code
revision throughout. Rollback restores Python, TypeScript and Schema changes
together and creates fresh materializations with the restored revision; never
relabel historical contexts or source receipts as a different version. No private
input files are migrated or deleted.
