# Versioned legacy TCLK audit reconciliation design

**DECISION A: VERSIONED_LEGACY_AUDIT_REPRESENTATION.** Proposed contract revision
**A1-LG2-TL1**, ready for coordinated implementation review, not implemented.
This preserves authenticated nonconforming source evidence without accepting it
as official tclk/1. It does not solve production capacity or authorize deployment.

## Unchanged protocol and evidence boundary

Official ACCEPT still requires ref and contract; offer_id substitutes for neither.
The [official schema](https://github.com/flop-labs/tclk/blob/5cc4ab93efbc8999a3a7e1471b639deca25998ea/schema/tclk1-frames.schema.json)
and [preceding linkage review](ROUTER_TCLK_LINKAGE_REVIEW.md) remain authoritative
for that distinction. This design never rewrites signed text, derives a canonical
workflow from offer_id, or treats authentication as schema conformance.

Use only supplied production counts: 2,373 accept-like records and 132 receipt-like
records. These are structural populations, not 2,505 proven eligible admissions.
No live or frozen production data was accessed. No further aggregate is needed to
specify safe behavior; qualification must measure the resulting retained workload.

## Classification and bounded admission

The explicit class is **TCLK_LEGACY_NONCONFORMING**, dialect tag
`router-tclk-legacy-audit/v1`, authenticity interpretation
**AUTHENTICATED_BUT_NONCONFORMING**. This is an audit category, not another valid
TCLK_ACCEPT grammar or a new protocol commitment.

TL1 is a closed historical-cohort mechanism. First activation binds an exact
`legacy_tclk_cohort` manifest object with keys `source_id`, `epoch`, `through_event_id`,
`record_count`, `records_sha256`. Source/epoch must equal the manifest source
checkpoint; through_event_id is a canonical decimal not beyond that checkpoint.
The source owner explicitly selects the historical complete cut; it never advances
on heartbeats or normal ingestion. The supplied 4,289,850-event cut is a possible
reviewed production value, not a fabricated epoch or mandatory synthetic-test cut.

Cohort count is 0–4096; digest is SHA-256 of the raw 32-byte identities concatenated
in unsigned byte order, without separators. Duplicate identities reject. Every
cohort identity appears exactly once in legacy_tclk_records and remains there
throughout TL1. Count/digest/cut/source are immutable after activation and are
included in continuity/cache bindings. The exact cohort is registered explicitly
in local producer and consumer activation configuration; an artifact cannot
self-authorize a different cohort. This is public configuration, not a signing key.
New installations also require this explicit TL1 enrollment; no automatic opt-in.

Producer admission requires the original signed `tclk1 ` text, exact raw/source/cache
binding, VERIFIED_OFFLINE authorship with no contradictory transport/frame DID,
representable required projection provenance, and failure of the frozen normative
structural validator. A missing frame.from in otherwise authenticated raw data is
an explicit missing-field failure, not a fabricated match; a conflicting supplied
from is a provenance conflict and cannot enter this authenticated class. If JSON
is unparsable, transport authorship may be verified independently; claim extraction
is unavailable. Unsigned/invalid-signature/contradictorily bound records use existing
negative/audit handling, never this class. A normative-valid frame cannot enter TL1
merely because its target is missing or its transition guard fails.

### Approved TL1 structural schema pin

The coordinated candidate is Scout's recorded local
`tclk-tl1-validator-review/tclk1-frames.schema.candidate.json` from its
[preflight report](../../flop_scout_v02/docs/router-projection-v2-tl1-preflight.md).
No current GitHub branch was fetched or substituted for this decision.
The required manifest pin fields have exactly these values:

```json
{
  "tclk_frame_schema_repository": "flop-labs/tclk",
  "tclk_frame_schema_revision": "5cc4ab93efbc8999a3a7e1471b639deca25998ea",
  "tclk_frame_schema_path": "schema/tclk1-frames.schema.json",
  "tclk_frame_schema_sha256": "17071a2b3b21e8484cac9da7976088f3700e6fb6c1372268d4756b61ddd60c70",
  "tclk_frame_structural_boundary": "tclk1-tl1-structural-schema/v1",
  "tclk_frame_validator_version": "router-tclk1-structure/1"
}
```

Candidate identity is the complete repository/revision/path/SHA-256 tuple above;
its exact artifact length is 6,070 bytes. Its JSON Schema `$id` is
`https://github.com/flop-labs/tclk/schema/tclk1-frames.schema.json`, and its dialect
is JSON Schema Draft 2020-12. The `$id` is descriptive, not a fetch instruction or
an immutable content pin. Implementations must bundle and verify these exact bytes.

**Normative boundary:** historical cohort structural nonconformance is determined
ONLY by this pinned JSON Schema. Reference-decoder acceptance/rejection is not part
of permanent TL1 historical cohort membership.

| Pinned JSON Schema | Reference decoder | Structural cohort result |
| --- | --- | --- |
| FAIL | FAIL | Structurally nonconforming candidate. |
| FAIL | PASS | Structurally nonconforming candidate. |
| PASS | FAIL | Not admitted merely because the decoder rejects. |
| PASS | PASS | Not a structural-nonconformance candidate. |

“Candidate” still requires all existing authentication, provenance, historical-cut,
cohort enrollment and capacity checks; schema failure alone does not admit a row.
Strict unparseable/duplicate-key handling remains the specified fail-closed JSON
input rule (mask 128), not decoder fallback or coercion. A schema-valid object has
structural mask zero even when decoder point/identity/semantic checks reject it.
The decoder may serve diagnostics and current normative processing, including
separate cryptographic, role, transition and deadline guards. It cannot enlarge,
shrink or retroactively change the permanent historical cohort. Shared vectors must
cover both disagreement directions; do not copy receipt outcome coercion.

Require exact equality of every pin field, including repository revision, schema
path, SHA-256 and boundary version. Reject missing pins, mismatched bytes/hashes,
unsupported boundary versions, moving branches/tags such as `main`, and silently
substituted schemas. Persist the complete pin in continuity/cache/activation state;
changing it requires a separately approved versioned migration, never a heartbeat
or a decoder upgrade. No runtime schema fetch or manifest-selected arbitrary hash.

This pin does not make offer_id normative, alias it to ref or contract, establish
workflow linkage, closure, qualification, settlement or independent reputation, or
bridge generations. Official tclk/1 stays strict. Schema success is not proof of
normative workflow validity. This approves the structural pin for implementation;
shared fixtures, runtime work and production qualification remain outstanding.

`TL1_STRUCTURAL_SCHEMA_PIN_APPROVED = YES`

`SCOUT_TL1_IMPLEMENTATION_UNBLOCKED = YES`


All relevant nonconforming records at the chosen cut must be accounted for; the
producer cannot select only easy records. Records outside the enrolled set,
subsequently arriving nonconforming TCLK, unresolved enumeration, bad provenance
or cap overflow block publication when required evidence cannot be represented.
A new cohort requires another explicit policy migration; no rolling admission.

## Minimal normalized representation

Use [the additive SQL](router-tclk-legacy-tl1-schema.sql): **one new table**, yielding
12 application tables in total. Existing nine A1 tables and two LG2 tables remain
byte-for-byte unchanged. No per-message legacy JSON slot or hint table is added.

| Stored field | Meaning |
|---|---|
| raw_ref, 32-byte BLOB | Compact reference to existing immutable raw identity. |
| claimed_type_code | 0=unavailable/non-string; 1=exact lowercase accept; 2=exact lowercase receipt; 3=other string. |
| nonconformance_mask | Nonzero closed bit set below, independently recomputed. |
| message_id, virtual | Existing sm1 identity derived from raw_ref; not a new workflow identifier. |

Logical `legacy_tclk_record_id` is `lt1:` plus lower-hex(raw_ref). No new random ID.
A required bulk logical FK joins message_id to messages and its message provenance:
all must exist and p.raw_record_id must equal lower-hex(raw_ref). Use report-outer
indexed joins, not an unindexed physical child FK that scans on parent deletion.
Enforce the existing table schema, table_xinfo, row-count and value checks; SQLite
CHECK declarations alone are insufficient.

Exact raw text, supplied values/types, unknown keys and malformed bytes already
remain in messages.text. Raw envelope hash/event ID/source locator come from
source_provenance; sender/authenticity/room/captured generation from messages;
first observed time from selection_membership. No repeated text, sender, time,
policy strings or hashes are stored in the new table. Required original provenance
must still be preserved by Scout, and projected text hashes independently checked.

The eight A1 annotation keys remain unchanged. For TL1 members, classification is
exactly TCLK_LEGACY_NONCONFORMING and capability_support is empty; same-operator
flags remain accurate. Existing verification/task/evidence links may preserve
independent audit facts but cannot convert this record into successful work.

Read-only audit views expose the logical record ID, claimed frame type, dialect,
authentication, reasons, exact typed claimed offer_id/ref/contract values and source
references. Extraction distinguishes ABSENT, PRESENT_NULL, PRESENT_TYPED_VALUE,
AMBIGUOUS_DUPLICATE_KEY and UNAVAILABLE_PARSE; it never coerces or chooses among
duplicate keys. Raw text is not logged. Claimed values are not canonical references.

## Deterministic nonconformance codes

Set every applicable bit, not the first parser error. Unknown bits reject.

| Bit | Code | Deterministic condition |
|---:|---|---|
| 1 | MISSING_REQUIRED_REF | Exact accept object lacks ref key. |
| 2 | MISSING_REQUIRED_CONTRACT | A recognized contract-bearing frame lacks contract key. |
| 4 | UNSUPPORTED_OFFER_ID | Parsed top-level object contains offer_id; its type does not legalize it. |
| 8 | MISSING_LINKAGE | Accept has neither a usable ref nor contract; other contract-bearing types lack usable contract. Usable means correctly typed/nonempty normative identifier, not valid target proof. |
| 16 | MALFORMED_RECEIPT | Exact receipt object fails any normative structural requirement; accompanies specific reasons. |
| 32 | CONFLICTING_CLAIMED_OFFER_HINTS | Exact accept has nonempty string offer_id and ref with different bytes. An audit conflict only; never compare contract to offer ID as an alias. |
| 64 | OTHER_SCHEMA_FAILURE | A structural failure not covered by bits 1/2/4/128/256/512, such as an unsupported other key or missing other required field. |
| 128 | UNPARSEABLE_OR_AMBIGUOUS_JSON | Malformed JSON, non-object top level or duplicate keys. No trustworthy per-key extraction; mask is exactly 128, type code 0. |
| 256 | INVALID_FIELD_TYPE_OR_VALUE | Supplied field violates its normative type/value constraint, including null, blank or malformed identifier. |
| 512 | UNSUPPORTED_FRAME_TYPE | Object type is absent, non-string or not a supported exact type; use type code 0 or 3 as applicable. |

A recognized contract-bearing type means accept/lock/reveal/refund/cancel/receipt/
heartbeat in the frozen validator. For malformed objects where type is unavailable,
only independently knowable key/value violations are added; missing per-type fields
are not inferred. Unsupported offer_id's value is retained but is not given an
invented normative value constraint. The reason algorithm/version is fixed by TL1;
producer and consumer must share independent golden failure vectors. No raw error
messages are stored. Full schema validity implies mask zero and excludes TL1.

## AUDIT_HINT and ambiguity

AUDIT_HINT is a derived, non-authoritative diagnostic relationship, not an
interactions row, workflow membership or evidence of acceptance. Candidate offers
may be displayed when an unambiguous nonempty string claimed offer_id or accept.ref
matches an independently validated OFFER.id **within the exact same source/epoch,
room and captured generation**. Compare bytes exactly. A claimed contract requires
an independently proven contract-to-offer chain; absent that, it stays opaque.
Multiple candidates remain a set, never first/majority winner. Cross-domain matches
are not edges and cannot bridge UNKNOWN_LEGACY to reported 0/1.

No candidate-hint table is necessary: the immutable body and retained offers allow
bounded derivation in private indexes. Diagnostics may page candidates, reporting
complete counts and ambiguity; page truncation cannot mean unique. Claim extraction
and candidate computation are bounded/cancellable, and overflow degrades instead
of silently losing evidence. Displayed candidates have no scoring or reputation
weight and generate no si1 interaction identity.

Crucially, hints **never narrow the retention hold**. A misleading hint, malformed
value, zero candidates or multiple candidates must not let any potentially affected
offer expire more aggressively. An exact match is not proof of completeness.

## Closure safety and retention choice

Choose **A: retain while unresolved**, with explicit capacity limits. There is
**no automatic 30/90-day legacy-audit horizon**. TL1 has no automatic reconciliation,
so its enrolled records and required proof remain indefinitely unresolved until a
separately approved successor policy. Permanent negative/pinned/durable dependencies
continue to override any future release. This is not a rolling warehouse archive.

Each TL1 record imposes a **domain audit hold** on its exact source/epoch, room and
captured generation. The hold applies to every TCLK offer and related transcript
in that domain that cannot be authoritatively excluded as an unresolved obligation,
not only diagnostic candidates. Current projection lacks a general terminal-rail
adapter, so no new terminal exclusion is inferred. Receipt-like, malformed and
unmatched records impose the same hold. Thus deleting ref, changing it to offer_id,
or losing parseability cannot create an expiry proof.

At enrollment the producer must enumerate complete relevant historical roots and
transcripts from the declared cut **before horizon pruning**, restore required
already-expired source evidence where available, and retain it. Missing originals,
incomplete enumeration or unrepresentable dependencies block activation. Future
matching-domain source events join the hold before expiry evaluation. Source feed
gaps, late corrections and incomplete committed batches fail closed. A hold from
UNKNOWN_LEGACY does not assert a relation in concrete generation 0/1; any additional
cross-domain uncertainty unresolved by existing provenance rules blocks publication
rather than inventing a bridge or treating that uncertainty as proof of absence.

Use selection retention class `TCLK_LEGACY_AUDIT`, retain_until=NULL, for TL1 records
and rows retained solely by these holds. Keep actual first_observed_at and pin roots.
Existing permanent higher-priority classes remain; normal rows held by TL1 have NULL
expiry even if their previous finite deadline passed. Existing class/provenance
facts remain auditable. The hold is derived from immutable enrolled rows and domains;
no editable count or untrusted candidate list can switch it off. Held dependencies
cannot disappear between accepted cuts. Consumer recomputes holds from projected
facts; producer remains responsible for complete source enumeration, as in V2.

`ClosureVerifier` must consult the hold index before any TCLK offer expiry decision.
Under a hold, it returns unresolved-audit/no finite expiry; it does not set ACCEPTED,
CLOSED, EXPIRED or a canonical workflow link. Normative valid ACCEPT still follows
its existing active-obligation rules. A legacy record absent from the table, falsely
marked normative, or paired with finite membership invalidates readiness; it is
not skipped. Invalid representation never routes.

### Explicit capacity bounds and unavoidable tradeoff

Proposed TL1 policy fixes: max_cohort_records=4096,
max_hold_messages=100000, max_hold_serialized_bytes=268435456 (256 MiB).
Count the union of TL1 records and additional message dependencies retained by TL1,
once per sm1, plus all required interaction/provenance/membership/LG2/qualification
closure for the byte budget. Bytes are the sum of UTF-8 lengths of canonical JSON
`[table, row-object]` plus one newline per row, using V2 C; encode BLOB values as
lowercase hex for this accounting only. Include all columns and all dependencies,
without double counting rows across holds. These are declared design limits, not
measured production counts or SQLite allocation estimates.

At any limit+1, fail capacity/readiness and preserve the last valid checkpoint.
Do not trim rows, age out the hold, auto-increase limits, or mark the domain closed.
Normal 30-second/512-MiB/4-GiB consumer limits still apply independently; the smaller
normal projection-size targets remain. A permanent fact consumes capacity too.
Future arrivals can hit these bounds and require operator reconciliation. There is
no way to promise finite storage, indefinite unresolved preservation and guaranteed
forward progress simultaneously. This design bounds storage and sacrifices fresh
publication when necessary; it does not disguise that tradeoff as healthy expiry.

## Scoring, qualifications and reconciliation

“Hold-only” means evidence retained solely by TL1 after it would otherwise leave
the ordinary selection policy. Normally eligible independent evidence keeps its
ordinary eligibility; a domain hold does not turn genuine valid evidence into a
legacy frame. The producer and consumer must independently derive that distinction
from the bound ordinary policy/cutoff, not trust a claimed scoring flag. When an
ordinary row ages out, its hold persists but its ordinary positive eligibility does
not persist merely because of the hold.

TL1 records, their hints and hold-only dependencies supply no positive capability,
settlement, success, trust or independent-reputation credit. Retain applicable
negative evidence without attributing unauthenticated misconduct. Independent valid
normative evidence and preexisting genuine qualifications retain their existing
semantics. Consumer must exclude TL1 IDs from positive evidence paths, including
any duplicate optional normalized TCLK input referencing the same source identity;
no side-channel import can reintroduce acceptance or verified usage. Do not globally
erase independent valid support merely because its domain is held.

Previously recorded qualifications remain byte-identical historical audit; do not
fabricate a witness for a TL1 record or treat invalid structure as current support.
If a prior record incorrectly qualified, only the existing proof-backed invalidation
process may append a correction. Same-operator exclusions and LG2 authority remain.

Future reconciliation may append an independently authenticated normative event or
an explicitly approved derived resolution with exact originals, target/proof IDs,
rule version and complete provenance. It cannot turn the original signed text into
a valid tclk/1 message or reinterpret offer_id as ref. TL1 itself accepts **no**
resolution/unhold event and removes no cohort rows. A successor version must define
exact authority, new schema, append-only history, migration and release conditions;
ordinary terminal evidence, passage of time, deletion or a producer flag is not an
unhold instruction. Original legacy evidence/history remains preserved, including
all durable audit dependencies. No current automatic conversion is proposed.

## Receipt handling

The 132 receipt-like records use the same table with type code 2 and independent
reasons, including missing contract/linkage and MALFORMED_RECEIPT as applicable.
They do not invent an offer, agreement, payout, completion or valid receipt outcome.
A no-hint receipt still creates its exact-domain hold. The 49 unknown-generation and
83 concrete-generation records from the preceding report stay in their own domains.
No fixed positive admission count is claimed before original/provenance validation.

## Version and manifest contract

Exact new outer revision: **A1-LG2-TL1**. Pointer/manifest envelope remains /v2,
database schema identifier remains scout-router-projection/v2, user_version=2.
Require the original 11-table schema plus the TL1 table, its row_counts member,
unchanged legacy_generation_policy/encoding, and these new required fields:

- `tclk_legacy_policy`: exactly the policy object below.
- `tclk_legacy_policy_sha256`: V2 C hash of that complete object.
- `legacy_tclk_cohort`: exact closed enrollment object defined above.
- All six schema pin fields in **Approved TL1 structural schema pin**, with exactly
  the values shown there (including existing hash and validator-version fields).

```json
{
  "schema": "router-tclk-legacy-audit-policy/v1",
  "dialect": "router-tclk-legacy-audit/v1",
  "retention": "unresolved-domain-hold-no-auto-release/v1",
  "hint_authority": "AUDIT_ONLY_NO_WORKFLOW_ID",
  "max_cohort_records": 4096,
  "max_hold_messages": 100000,
  "max_hold_serialized_bytes": 268435456
}
```

Selection object shape/parameters remain; exact version becomes
`router-evidence-horizons/3`, classifier `router-evidence-classes/3`, with the new
TCLK_LEGACY_AUDIT membership semantics. All existing horizons/cutoff/pin rules stay.
Qualification policy stays router-durable-qualification/v1. Old /2 qualifications
retain their original policy/classifier hashes and versions as allowlisted historical
audit; new qualification records bind /3. Audit provenance is not rescored to replace
an old first witness. Future consumers must dispatch this exact combination; LG2
runtimes reject TL1, TL1 rejects mixed table/annotation/version/binding shapes.

Explicit activation requires CONTENT with greater content/publication IDs and
nonregressing clocks/cuts, preserves old accepted copies/history, and rebuilds both
validation and routing caches. Validate old rows/history and the allowed retention
extension to NULL; annotate the migration checkpoint without modifying old artifacts.
Previously finite rows may gain holds, never lose protection. Record TL1's exact
policy, schema pin and cohort in state. No downgrade or cohort reset. Same-content
heartbeats may reuse validated caches only under identical bindings and fresh
complete-cut checks. The changed evidence-filter semantics require a new Router
shadow policy version `flop-router-shadow/v5-v2-tl1-audit`; one deliberate reevaluation
is expected, preserving old decisions and signed receipt schemas.

## Storage estimate

Measured locally using the proposed DDL, SQLite's default 4,096-byte pages,
WITHOUT ROWID and no secondary indexes. Insert raw refs as SHA-256 of decimal
row ordinals in ordinal order; use type/reason values (1,15) for ACCEPT-shaped
rows and (2,26) for receipt-shaped rows. These are allocation fixtures, not
valid complete projections or assertions about every production reason bit.
Read table allocation from `dbstat`; close each temporary standalone database.

| Synthetic population | Rows | Table bytes | Table bytes/row | Standalone DB bytes |
| --- | ---: | ---: | ---: | ---: |
| Receipt-like | 132 | 12,288 | 93.09 | 16,384 |
| ACCEPT-like | 2,373 | 106,496 | 44.88 | 110,592 |
| Combined (ACCEPTs then receipts) | 2,505 | 118,784 | 47.42 | 122,880 |

The combined table is 116 KiB; its standalone file is 120 KiB including the
schema page. Primary-key storage is included in table bytes; secondary-index
bytes are zero. Existing projection schema-page growth and insertion order may
change actual allocation. No linear warehouse-size extrapolation is used.

This excludes already-existing source bodies and any additional hold dependencies.
Their production count/bytes are unknown and may dominate. No estimate assumes all
related rows pass admission. The new audit table does not duplicate full raw text;
restoring evidence needed by holds can still exceed capacity and block the dry run.

## Producer and consumer implementation tasks

Scout: freeze and independently validate cohort completeness; preserve signed/raw
originals; classify normative versus authenticated nonconforming versus provenance
failure; emit exact compact rows/reason bits; derive and enforce complete domain
holds before pruning, without offer_id aliasing; retain hints as non-authoritative
views; enforce capacities, replay/continuity, version binding and old qualification
history; publish only a complete valid cut. Do not edit live raw records or invoke
settlement. No Scout changes were made here.

Router: implement explicit TL1 dispatch/activation and complete schema/value/cohort
checks; independently revalidate published classifications and reason masks using
bundled structure vectors; bind raw hashes/provenance; construct a bounded hold index;
correct ClosureVerifier's expiry asymmetry; exclude TL1 positive scoring across
projection and optional imports; validate retention/dependency continuity; expose
counts by reason/type/domain, ambiguity, held bytes and readiness; rebuild caches
under new policy. Unknown/mixed/malformed metadata, missing required table/proof,
capacity overflow and cancellation must fail closed without decisions. No runtime
changes were made here.

## Planned tests and dry-run gate

1. Full normative ACCEPT ref+contract remains normative, with unchanged guards.
2. offer_id-only ACCEPT is not normative and never aliases either required field.
3. Eligible authenticated nonconforming ACCEPT is retained in the enrolled cohort.
4. No canonical workflow ID or si1 edge is derived from its claimed offer_id.
5. No accepted/closed/settled transition is created by the audit record.
6. Ref→offer_id substitution never permits earlier expiry.
7. No positive capability/settlement credit, including duplicate optional imports.
8. No added independence/reputation from hints or multiple candidates.
9. Multiple candidate offers remain ambiguous; insertion order cannot choose one.
10. Cross-generation hints do not bridge; UNKNOWN_LEGACY remains captured unknown.
11. Missing-linkage receipt remains retained and holds its own domain.
12. Malformed/duplicate-key JSON has immutable raw audit and no chosen field value.
13. Reparse/replay/restart preserves cohort, holds, originals and stable IDs.
14. TL1 rejects unhold/reconciliation mutations; future migration must be append-only.
15. Unknown revision/policy/schema hash/cohort changes and downgrade reject.
16. Mixed valid and legacy frames have deterministic separate classifications.
17. Same-operator exclusions and genuine historical qualifications stay unchanged.
18. Exact schema/types/reason bits/row counts, FK bindings and allocation sanity.
19. ClosureVerifier regression for ref, offer_id, no-link receipt and malformed body.
20. No first-field fallback; all applicable errors retained and recomputed.
21. Missing/ambiguous candidates cannot narrow the domain hold.
22. Enroll before expiry pruning; late same-domain arrivals inherit the hold.
23. Missing historical source originals or incomplete enumeration block activation.
24. Exact cohort/hold-byte/count limits pass; limit+1 fails without truncation.
25. Bounds/cancellation during scans leave no decisions or stale READY status.
26. Old /2 qualifications and copies survive explicit /3 migration and restart.
27. Genuine negative evidence remains negative; invalid signatures never enter the
    authenticated class; contradictory supplied frame DID still rejects.
28. Proposed resolution, elapsed 90 days or a valid receipt cannot release a TL1 hold.

These are planned tests, not implemented runtime coverage. The structural schema pin is now approved. Separately authorize implementations
and independent shared synthetic fixtures, including all four schema/decoder cases
and rejection of missing, moving, mismatched or substituted pins. Scout's next authorized production-shaped
run must report actual enrolled counts/reasons, complete held roots/dependencies,
held canonical bytes, restored historical evidence, ambiguities and capacity results.
Require valid pins/history and a complete immutable artifact before Router acquisition
qualification. No valid production projection or handoff exists yet.

TCLK_LEGACY_RECONCILIATION_READY = YES

SCOUT_TCLK_LEGACY_IMPLEMENTATION_READY = YES

ROUTER_TCLK_LEGACY_IMPLEMENTATION_READY = YES

These mean the design is ready for separately authorized implementation, not that
implementation, production capacity or deployment is approved. Official offer_id
aliasing remains blocked. STOP for coordinated review.
