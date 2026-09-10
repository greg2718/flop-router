# Production generation provenance review

Historical review: the subsequent Scout authority aggregate resolves the evidence
request. Its values still cannot be promoted to observed generation. The
[LG1 contract decision](SCOUT_ROUTER_SNAPSHOT_V2.md#lg1-legacy-reported-generation-metadata)
now permits separately labelled, non-authoritative legacy reports under a new
compatibility revision. The old decision below is retained as review history;
it is not the current decision on secondary audit metadata.

**DECISION C: INSUFFICIENT_EVIDENCE.**

`GENERATION_RESOLUTION_BLOCKED = YES`

This is a semantics review, not a contract amendment or implementation approval.
Existing A1 still rejects incompatible linked generations. No Router runtime,
Scout file, live state, publication or service was modified. No deployment,
commit or push is authorized. The V2 contract was read in full; the two supplied
dry-run artifacts and relevant source/fixture code were inspected read-only.

## Evidence and production prevalence

Authoritative supplied reports:

- [Scout dry-run report](../../flop_scout_v02/docs/router-projection-v2-production-dry-run.md)
- [Scout aggregate JSON](../../flop_scout_v02/docs/router-projection-v2-production-dry-run.json)
- [V2/A1 contract](SCOUT_ROUTER_SNAPSHOT_V2.md)

The report describes a 48.450-GiB warehouse with 4,289,850 raw records. The
producer correctly stopped at event 9, after mapping eight records, on a
compatibility generation mismatch. No valid publication was created; the empty
partial staging projection is neither the selected production population nor a
healthy idle snapshot. Router performance on production-shaped evidence remains
unmeasured.

The aggregate contains **two**, not one, mismatching generation pairs:

| Raw generation | Cache generation | Linked pair count |
|---|---|---:|
| NULL / UNKNOWN_LEGACY | `"0"` | 127,146 |
| NULL / UNKNOWN_LEGACY | `"1"` | 33,927 |
| Total | | 161,073 |

These are linked-pair counts, not proven distinct raw-record counts. They do not
show whether any one raw record links to both concrete generations, or whether
the two populations are disjoint. Only the representative failure supplies
room/sequence/text-hash agreement; the aggregate does not prove those equalities,
sender agreement, transport lineage or valid verification for every pair.
The representative cache-link entries also omit sender and transport provenance.

## Meaning of generation zero and unknown

A1's exact mapping is NULL/missing actual generation → UNKNOWN_LEGACY and numeric
zero → the concrete string `"0"`. The sentinel means **actual generation was not
established in the captured provenance**. It does not mean that the server had
no generation, that the generation must have been zero, or that any concrete
generation is an interchangeable alias. NULL can also reflect conflicting or
unusable capture metadata; it is not by itself an enrichment authorization.

Read-only code evidence clarifies why a compatibility value is insufficient:

- Scout `scout_evidence.py` migration passes `generation=None` and stores the
  old verification cache value as `reported_generation` (`initialize` migration around
  lines 264–276). `ingest` and `raw_identity` preserve actual and reported
  generation separately; both contribute to immutable raw identity.
- `compatibility_links` around lines 695–719 can select the first match by
  room/sequence/text, ordered by legacy flag and creation time, without proving
  unique generation or sender in that historical selection. A missing match
  creates legacy raw evidence with the cache generation only *reported*.
- Scout's coordinated source review, lines 434–455, explicitly warns that a
  compatibility link is not proof of unambiguous generation and prohibits
  converting reported generation to actual after conflict.
- `flop_scout.py:network_result_generation` treats None, empty string and `"0"`
  as UNKNOWN_LEGACY in its Bench result path. This is evidence of contextual
  legacy/sentinel treatment, not proof that all production zero values were
  defaulted. Conversely, `fetch_room_view` reads body/header generation and can
  preserve a concrete value. Neither current code path proves the origin of
  every historical cache row.
- Synthetic fixtures deliberately assign `"0"` and UNKNOWN_LEGACY as separate
  domains. They validate the consumer distinction, not historical server truth.

**The supplied evidence does not prove whether these production `"0"` values
were observed server generations, defaults, imported labels or ambiguous links.**
It also does not establish the authority of the `"1"` population. Matching text
or a valid message signature is not proof of generation: Router's signing
payload binds room/nonce/text, not server generation/sequence. Source lineage
and unique capture linkage are separate obligations.

## Current acceptance and conflict rule

No enrichment is approved. Under current A1, UNKNOWN_LEGACY versus `"0"` or `"1"`
remains an incompatible source/cache assertion and blocks the projection.
Existing exact-generation linkage is still subject to all other checks; equal
generation alone does not establish authenticity or correct source binding.

The following remain rejecting conditions: competing concrete generations for
one raw identity; concrete `"1"` versus `"0"`; room/sequence/text/hash mismatch;
sender mismatch; conflicting endpoint/protocol lineage; ambiguous source
matching; invalid or unverifiable linkage. Do not drop the failed row, omit its
verification provenance, rewrite raw generation or emit a healthy empty cut.

Decision C leaves open two different future resolutions: correction of a
demonstrably erroneous cache/compatibility assertion under an audited migration,
or a separately approved generation-resolution policy backed by unique
authoritative capture evidence. A defaulted cache zero is **not** reconstructed
server generation. Lack of contradictory evidence is not affirmative proof.

## Minimal additional Scout-side evidence

Request one owner-produced aggregate from the same frozen diagnostic cut, with
the query definitions, source/code revision hashes and counting units. No raw
message bodies, DIDs, signatures, keys or production database access by Router
are needed. Required components:

1. For each actual-generation/cache-generation pair and cache table, report pair
   count and distinct raw-record count, grouped by raw source, legacy/provenance
   status, reported generation, migration/ingestion path/version and endpoint
   lineage availability. Keep absent and conflicting metadata distinct.
2. Per raw identity, aggregate the set of linked concrete generations across
   all compatibility sources. Report counts for `{0}`, `{1}`, `{0,1}`, other
   singleton/multiple sets and unknown-only. Include alternate raw candidates
   with the same room/sequence/text hash; first-match selection must not hide
   ambiguity. Return histograms/counts, not identity lists.
3. Independently count exact agreement, mismatch and unavailable values for
   room, sequence, exact raw/text hash, sender, nonce/signature binding and
   endpoint/protocol lineage, plus joint all-required-checks-pass counts. Supply
   linkage/authenticity validation statuses; raw foreign-key linkage alone is
   insufficient. Do not infer the joint passing count from separate marginals.
4. Identify the historical writer/default/migration behavior for zero and one
   using immutable code/schema revisions and sanitized synthetic reproductions.
   Count affected records backed by an original generation-bearing transport
   capture, mere cache/reported assertions, defaulted values, conflicting
   body/header metadata and no surviving authority. Explain what ties a transport
   generation to the exact raw record and source epoch. Current code alone does
   not establish historical execution.

This distinguishes a consistent proven legacy mapping from unresolved metadata
or true conflicting identities. If no authoritative historical binding survives,
the population remains unresolved; additional pair counts alone cannot approve
enrichment. No production raw-record request is necessary at this gate.

## Audit and watermark model

Current raw provenance, sm1/raw IDs, original hashes, qualifications and decision
history remain immutable. Preserve captured actual generation and separately
reported cache generation in their existing owner audits. A1 has no approved
resolved-generation field; do not insert extra columns/annotation keys under A1.

If future evidence supports enrichment, its design must preserve at least:
captured generation, resolved generation, observed/reported/enriched distinction,
resolution policy/version, exact proof references/hashes, source lineage and a
stable resolution identity. An enrichment may not claim `"0"` was originally
observed, change raw IDs or become an independent second observation. This is
a review requirement for a future design, not an approved wire schema.

For this decision, watermarks and coverage_history remain keyed by the **captured
generation**. UNKNOWN_LEGACY remains its own domain. No maxima/counts/witnesses
are moved to `"0"` or `"1"`; no historical domain is erased. Watermarks describe
selected evidence and do not prove contiguous or stronger observed coverage.
If a future resolution layer is approved, resolved linkage accounting should
remain separate from captured coverage; it must not retroactively strengthen
observational claims. Current `_coverage` recomputation and `_extension`
immutability checks intentionally prevent an unnoticed generation rewrite.

## Qualification, workflow and identity impact

- `observation_message_hash`, `evidence_id_for`, `template_count_key` and SQL
  duplicate grouping bind generation. No cross-generation coalescing or second
  independent support is authorized.
- `ClosureVerifier.verify` requires exact source/room/generation/protocol/key
  scope. Enrichment cannot currently bridge an UNKNOWN_LEGACY workflow to a
  concrete-generation terminal event or authorize expiry.
- `_proof`, `_qualifications` and append-only audit checks preserve source
  identities, raw hashes, original witnesses and event chains. A future approved
  resolution must be separately auditable; it cannot rewrite a historical
  qualification or fabricate an earlier successful evaluation.
- Explicit verification linkage remains distinct from cryptographic authenticity,
  correctness and reproducibility. Same-operator evidence never becomes
  independent reputation through resolution.
- Interaction identities must preserve their exact endpoint provenance. No
  generationless room/sequence join or merged edge is newly allowed.

Router's older non-V2 JSON adapters contain truthiness-based generation handling
(for example `normalize_export_record`); the V2 adapter preserves the validated
string directly. That older coercion is not evidence that zero equals unknown
and must not be used to define the producer contract. No adapter was changed.

## Versions and implementation impact

**Version changes now: none.** A1 and all validator/cache versions remain
unchanged. A future enrichment rule would require an explicit contract revision,
an exact schema and manifest-bound policy (a name such as
`router-generation-resolution/v1` is only a candidate), strict supported-version
checks and an approved continuity/cache migration. Do not label changed
generation semantics A1 or silently allow additional fields.

**Scout changes required now:** produce the aggregate and historical-path proof
above; keep the producer's strict stop. No runtime change is specified yet.
Any eventual reconciliation must be separately audited and preserve original
raw capture, required negative evidence, pins and qualification history.

**Router changes required now:** none to runtime. Review the additional evidence,
then jointly specify and test any supported resolution representation and its
use in verification, workflow, deduplication and continuity. Do not accept
partial source consistency to unblock a performance benchmark.

**Migration/replay:** preserve existing IDs, raw bytes, source epochs, captured
watermarks, first-observed times and immutable qualification/event history.
Reconcile derived links through an explicit reviewed mapping, not rewriting raw
generation in place. Replay must preserve resolution evidence and give identical
results regardless of link ordering, chunk size or restart. The dry-run created
no valid V2 ledger/publication; fresh bootstrap cannot reconstruct unavailable
historical qualifications or external pins.

## Planned acceptance tests (not implemented or executed here)

| Case | Required outcome |
|---|---|
| 1. UNKNOWN_LEGACY plus matching `"0"` | Reject under A1. Accept only under a future explicitly approved policy with every authority/linkage predicate satisfied; a cache label alone still rejects. |
| 2. Original generation | Captured UNKNOWN_LEGACY and original raw bytes/ID remain unchanged. |
| 3. Resolved generation | If approved, stored separately with resolution classification/version/proof; never substituted into captured provenance. |
| 4. Room/sequence/hash mismatch | Any mismatch rejects, including matching position with different text. |
| 5. Competing generations | One raw identity linked to both `"0"` and `"1"` rejects; disjoint populations are not falsely called per-record conflict. |
| 6. Concrete conflict | Captured `"1"` versus linked `"0"` rejects. |
| 7. Sender mismatch | Reject; missing sender authority cannot satisfy a required predicate. |
| 8. Invalid linkage | Reject default-only, unverifiable, ambiguous first-match and wrong-lineage proofs. |
| 9. Duplicates | Deterministic ordering/grouping; resolution cannot multiply observations or independent credit. |
| 10. Workflow | Exact authorized scope/linkage; ambiguous or cross-domain closure rejects and remains unresolved. |
| 11. Qualification | Historical bytes/IDs remain unchanged; any approved resolution provenance is retained and auditable. |
| 12. Watermarks | Captured UNKNOWN_LEGACY coverage remains distinct; no inflated concrete coverage or erased history. |
| 13. Restart/replay | Same input/proof/policy gives identical resolution/identity; preserve checkpoints and reject competing late proof. |
| 14. Policy mismatch | Reject absent/unsupported/mismatched version/hash and attempted new fields under A1. |

Existing generation fixture, source-mutation, workflow generation/source mismatch
and continuity tests remain untouched. Planned future-acceptance cases are
conditional; this review does not activate them.

## Production dry-run next step

Obtain the aggregate/historical provenance evidence first and repeat coordinated
semantics review. Only after an approved resolution and separately authorized
implementation/testing should Scout's owner repeat the frozen-copy dry-run:
verify the complete source cut, exact linkage, pins/dependencies, history and
watermarks; publish no artifact on any conflict; then measure a valid immutable
projection with Router's unchanged 4-GiB/30-second/512-MiB limits. Do not use the
failed staging DB, producer timings or warehouse size as Router performance.

`IMPLEMENTATION_READINESS = BLOCKED_PENDING_GENERATION_AUTHORITY`

`GENERATION_RESOLUTION_BLOCKED = YES`
