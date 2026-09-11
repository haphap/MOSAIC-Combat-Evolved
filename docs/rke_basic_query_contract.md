# RKE basic query contract v3

The CLI export, Bridge JSON API and Agent materialization read only
`forecast_claims.jsonl` and `report_metadata.jsonl`. Outcome labels,
source/viewpoint profiles, weighted contexts, recipes, gaps and stock/industry
snapshots are offline artifacts. Their absence, changes or malformed JSON do
not change the basic query. The row-based builder now has the same two-input
contract: it no longer accepts or constructs those derived fields. Offline
Report Intelligence builders remain responsible for their own artifacts.

## Selection and output

Contexts use `rke_agent_research_context_v3` and rank policy
`rke_agent_research_context_rank_v2`. Matching retains the existing Agent,
role/style, ticker and sector restrictions. Sort order is target specificity,
latest available date first, then redacted claim ID ascending; truncation
happens after sorting. Availability uses the latest supplied claim signal,
claim as-of, report publication and accessibility date. A later accessibility
date cannot be overridden by an earlier publication date. The runtime formatter
rejects unknown, invalid or future availability.

Basic items contain redacted identity, target, direction, horizon, regime,
availability and shadow/current-data requirements. They contain no historical
scores, weights, outcome summaries, recipe/gap IDs or snapshot features.
Markdown renders these facts without the old context hash, rank/priority audit
banner or derived ranking explanations. Rank and summary counts remain JSON
metadata; they are not runtime permission checks. Privacy validation still
inspects the entire input, including unused fields. Required identity, scope
and shadow-use constraints still reject invalid input.

The old post-run re-query attribution is removed with the PR #28 change.
Completed Agent outputs alone do not establish RKE use. Legacy benchmark
footprints with rank v1 remain readable; new basic contexts use rank v2. No
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
metadata PIT evidence. Empty attestation still requires both basic input files,
an exact reconstructed empty result and a no-prior reason; missing inputs are
not true empty. Empty coverage hashes the same two basic files, down from ten.
The source archive digest remains in the PIT vintage query and parent capture
reference because route eligibility independently requires the parent binding.

Trusted receipt construction validates the owned body and hashes it once.
Loading an external or persisted receipt still validates the body and hash.
Staged receipt construction and loading share PIT time checks, including
capture/knowledge ordering and the as-of cutoff, without revalidating a just
constructed receipt. Request/content hashes, upstream source identity and
cross-process authorization remain distinct boundaries.

## Migration and rollback

New contexts and source receipts get new versions and identities. Historical
sealed results retain their original fields and hashes; no private history or
frozen result is rewritten in place. Materialize a new query using one code
revision throughout. Rollback restores Python, TypeScript and Schema changes
together and creates fresh materializations with the restored revision; never
relabel v3 contexts or v2 source receipts as their predecessors. No private
input files are migrated or deleted.
