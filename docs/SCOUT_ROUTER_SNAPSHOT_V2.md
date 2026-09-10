# SCOUT_ROUTER_SNAPSHOT_V2: Router-facing evidence projection

Status: **approved V2/A1 contract; consumer development candidate under review**.
The [LG2 compact storage revision](#lg2-compact-legacy-report-storage) is implemented
in the separately authorized Router consumer candidate. It preserves LG1 authority
semantics while replacing its oversized JSON representation. Scout's LG2 producer
is independently implemented. See [LG2 consumer validation and limitations](ROUTER_A1_LG2_CONSUMER_REVIEW.md).
A1 and LG1 formats below remain frozen for compatibility/history. Router accepts
A1 and LG2 explicitly; LG1 is supported only as an archived migration checkpoint,
not an active publication. This document does not authorize deployment.
The Router V2/A1 consumer is now implemented with fail-closed limitations and
measured capacity failures described in [the consumer review](ROUTER_V2_A1_CONSUMER_REVIEW.md).
Scout's implementation is separate and not deployed. This document does not authorize deployment. V1 remains frozen in
`SCOUT_ROUTER_SNAPSHOT_V1.md`; a V2 artifact must not be labelled as V1.

**A1 coordinated decision: accepted.** Durable qualification history and current
support assessment are separate. This revision resolves A1 in Scout's
[coordinated source review](../../flop_scout_v02/docs/router-projection-v2-source-review.md),
reviewed SHA-256 `bce31fa7dce1f133c317a09539d3eaa8745f15f45316b3250b65bdc36a6297a0`.
Its proposed producer-private witness is retained, and this contract additionally
requires its public, immutable audit representation below so Router can read
history after restart. A producer-private ledger alone is insufficient for the
consumer requirements. The existing seven source-table mappings remain; A1 adds
two explicitly specified audit tables, not an audit-to-scoring conversion.

`A1_RESOLVED = YES`
`SCOUT_V2_PRODUCER_CONTRACT_READY = YES`

These mean the A1 producer contract is specified for implementation planning.
The A1 decision alone authorized neither runtime implementation nor service launch.
A subsequent task authorized this consumer implementation, not deployment.

## Why V1 is not production-viable

The operator supplied an earlier diagnostic reporting a production observer
database larger than 52 GiB; this is not a freshly verified measurement. The
current consumer permits at most 1 GiB and hashes/copies the entire artifact
before SQLite validation. A full observer backup cannot meet that contract.
Raising the limit above 50 GiB would also make per-cycle copying, integrity
checking, temporary storage, and cancellation latency unsuitable without a
different operational design.

V2 publishes a transactionally consistent **projection of Router inputs**.
Scout maintains a dedicated persistent projection database incrementally and
uses SQLite online backup of that database for changed publications. Publication
must not rescan or rebuild the full warehouse. A full observer backup is never
a prerequisite. Router never opens either live Scout database.

## Inputs actually required by current Router code

| Consumer | Required information | Projection decision |
| --- | --- | --- |
| `TechnocoreObservationAdapter.observations` | Signed message rows; room, generation, sequence, timestamps, sender, full text, normalized text, template hash, signature and evidence provenance | V2 reads the selected scope below, including retained negative/unverified evidence. This is an explicit selection change, not full-history equivalence. |
| Adapter template-count query | Distinct senders per template, before DID filtering | Recompute over the selected scope without removing its noise/invalid-DID rows. Label counts as projection-scoped, never lifetime reputation. |
| `CapabilityInferer`, `capability_evidence_decisions`, `assess_evidence`, `ProfileBuilder._build_one` | Text patterns/context, duplicate frequencies, positive and negative evidence, message counts, promotion/noise ratios, chronological evidence | Preserve full selected text. The 220-character preview is insufficient input. Horizon expiry must be explicit and must not remove durable negative evidence or pinned support. |
| `TechnocoreObservationAdapter.interactions`, `ProfileBuilder.build_all`, `is_direct_interaction_row` | Source DID, target DID, relationship type, confidence, edge multiplicity, reciprocity | Retain selected interaction multiplicity. Permanent identity/operator facts and pinned edges do not expire; ordinary edges use the context horizon. Never pre-award independent reputation. |
| `validated_evidence_from_attempt`, `ProfileBuilder` | Existing validation-attempt JSONL, accepted response, PASS outcome, score, capability, outbound/inbound room-generation-seq | Remains an explicitly configured Router-side input. Scout does not manufacture Router-owned validation attempts. |
| `TclkObservationAdapter`, `settlement_evidence_from_tclk` | Existing normalized TCLK JSONL including transport/frame identity, amount validity, rails, deadlines, parse/authenticity status, operator group, contract/offer/job IDs, receipts and Sentinel status | Remains an explicitly configured input. Text-only projection is not a replacement for TCLK JSONL. |
| `ingest_normalized_bench_result`, `normalize_scout_verification_result` | Bench request/result hashes, routing decision/task linkage, provenance, same-operator classification | Preserve available links in projection provenance; controlled verification audit remains separate; only explicitly supplied linked originals can confer controlled validation confidence. |
| `run_worker_cycle`, `Router.route`, `create_execution_plan` | Router-owned task inbox, derived profiles, default execution constraints | Tasks remain Router-owned. Capability support, scores, qualification and plans remain Router-derived. |

V2 removes unrelated warehouse tables, duplicated envelopes, unused indexes and
expired unpinned context. Selected rows remain lossless; the selection itself
changes history scope. Router must distinguish scoped activity/noise counts
from lifetime facts and must expose the policy in decisions/status. Selection
changes require qualification of their effect on rankings and risk. This is
not approval to discard all old text or to infer that a smaller history is
more trustworthy. Permanent/pinned evidence can still outgrow the byte budget;
that is a capacity failure, not permission to trim it.

No `agent_capability_support`, `verification_evidence`, or authoritative
`operator_relationships` scoring tables are introduced: current Router does not
consume such Scout tables. Existing `messages` and `interactions` names are
retained because they are the actual query interface. Additional tables serve
content identity, source linkage, retention membership and coverage history.

## Deterministic selection policy

Policy object (all keys required; the example contains the proposed defaults):

```json
{
  "schema": "flop-router-projection-selection/v1",
  "version": "router-evidence-horizons/2",
  "classifier_version": "router-evidence-classes/2",
  "qualification_policy_version": "router-durable-qualification/v1",
  "parameters": {
    "context_seconds": 2592000,
    "capability_signal_seconds": 7776000,
    "closed_work_seconds": 7776000,
    "closed_tclk_seconds": 7776000
  },
  "cutoff_semantics": "trusted-first-observed-strict-before-expiry/v1",
  "pinned_record_rules": "transitive-local-evidence-dependencies-no-implicit-unpin/v1"
}
```

Hash this complete object as UTF-8 JSON with sorted keys, compact separators,
`ensure_ascii=false`, no NaN/Infinity or duplicate keys. Bind the SHA-256 and
object in every manifest and the hash in `snapshot_meta`. Any parameter,
classification or pin-rule change changes the policy hash. The consumer accepts
only explicitly supported versions/parameter sets; an operator cannot silently
shorten a horizon. Policy changes require a reviewed migration and reevaluation.

Selection is the union of the following rules; permanent retention and pins
always override expiry. These are normalized classes, not arbitrary labels
accepted from room text. Scout's versioned classifier maps authenticated source
events and Router's deterministic evidence rules to them, retaining the rule
version and source provenance. Scout's linked source review supplies mapping,
precedence and complete-group ordering; A1 resolves its permanence blocker.
Implementation must follow those decisions and the new witness model, not choose
its own historical-retention behavior.
Unknown or ambiguous classes fall back to CONTEXT, not positive support. All
rows concerning a recognized durable negative condition use NEGATIVE_EVIDENCE
regardless of any competing positive or unknown label.

| Class | Retention rule |
| --- | --- |
| IDENTITY_OPERATOR | Always retain provenance-backed identity/operator bindings, same-operator disclosures, changes, revocations and conflicting binding evidence. A claimed independent group is not proof of independence. |
| BENCH_VERIFICATION | Always retain observed verification request/result classifications and linkage, including FAIL, invalid/unverified, rejected and same-operator outcomes; do not convert an audit into scoring evidence. |
| CAPABILITY_SUPPORT / CAPABILITY_CONTRADICTION | Permanent retention is established by the A1 durable qualification witness, not today's score. Preserve the original qualifying evidence, witness and required audit dependencies even after downgrade, supersession or invalidation. Self-advertising or mere keyword matches without a valid historical witness remain CAPABILITY_SIGNAL. |
| NEGATIVE_EVIDENCE | Always retain signature failure, DID mismatch, conflicting evidence identity, failed verification/work outcome, and concrete capability/security contradiction evidence. These facts do not age into a clean reputation. Preserve invalid/unverified classification; retention is not endorsement. |
| CONTEXT | Keep ordinary messages, unclassified parseable events, noise/promotion and ordinary interaction edges for 30 days from immutable Scout first-observed time, unless another rule retains them. Noise alone is not a durable misconduct finding; its scoped counts must be labelled. |
| CAPABILITY_SIGNAL | Keep unsubstantiated capability hints/claims for 90 days from first-observed time; retain longer when pinned. |
| WORK_LIFECYCLE | Keep unresolved requests/acceptances/results and their dependency closure while unresolved. Successful terminal workflows retain 90 days after the first valid observed terminal event; failed outcomes are permanent negative evidence. Missing/conflicting terminal status stays unresolved. |
| TCLK_LIFECYCLE | Keep all active/relevant offers and linked transcript events, including associated malformed/mismatched events needed to interpret the transcript. Retain terminal or deterministically expired, unreferenced transcripts for 90 days after observed closure/expiry. Unknown/conflicting deadlines or state remain relevant. Negative findings and pinned transcript links survive expiry. |
| PINNED | Keep every row and transitive local dependency supporting a retained Router decision, task, validation or verification record, regardless of age/class. Pins include both positive and adverse evidence used to reach the outcome. |

The classifier's CAPABILITY_SUPPORT rule uses the versioned equivalents of
`capability_evidence_decisions` and `assess_evidence` with full source context:
`support_contribution` in `LIMITED`/`STRONG` is concrete support; `SIGNAL` is
horizon-bounded. Contradiction and invalid-signature outcomes take precedence.
It cannot select only a task-specific top-K or discard evidence because its
score is low. A change to the underlying rules requires a new classifier/policy
version. A first qualifying complete-cut result establishes the A1 historical
witness; subsequent scores do not remove it. Router still computes its current
support/qualification; producer labels are not independent attestation or a
replacement score.

Set `selection_evaluated_at` to Scout's UTC clock after catching up the projection
to a committed source cut and processing due expiries. Time never moves backward.
For a fixed bootstrap, ordered complete-batch history, durable qualification
ledger, current source cut, policy, pin set and evaluation time, output is
deterministic. Current rows alone cannot reconstruct past qualification.
Use integer UTC microseconds for comparisons; a finite row is eligible exactly
while `selection_evaluated_at < retain_until`. First-observed time is the durable
local ingestion time assigned once, not sender time and not replay/publication
time. Store `retain_until` as first-observed plus the class horizon, or observed
terminal time plus its horizon. Future sender timestamps cannot extend retention.
For an expiry-only TCLK closure, effective expiry is the validated deadline;
missing/invalid/conflicting deadlines do not permit removal. New late-arriving
records receive their actual first-observed time; replay preserves it.

Pins are stable logical references (kind, root evidence/task/decision ID), never
publication IDs or temporary paths. Compute the transitive closure over known
local evidence links; cycles are handled as a visited set. Missing required
local dependencies fail projection qualification rather than yielding incomplete
support. External references stay opaque and do not authorize network fetching.
Required provenance accompanies every retained row and dependency. Pin roots
are monotonic in this initial policy: no automatic unpin when work completes,
and deleting an input file does not revoke pins. Unpinning needs a separate
reviewed policy. Router pin information must arrive through an explicitly
configured local artifact/import owned by Scout; no Technocore write or implicit
new IPC is introduced. Integration of this channel is a deployment prerequisite.
The Router-side pin export, if implemented, belongs in Router-owned state for
Scout to import. An initial empty pin set requires an explicit valid empty
artifact, not a missing file. Missing/malformed configured pin input or a
regressed/removal-bearing pin update blocks fresh publication; it never clears
previously accepted pins.

Exclude unreferenced attachments/full raw envelopes, duplicated fetch storage,
irrelevant warehouse indexes, expired unpinned context/signals and ordinary
unsigned chatter without a required linkage or negative fact. Never exclude
failure evidence merely because authenticity or parsing failed. A required fact
that cannot be represented with valid location/provenance causes degraded
qualification until its schema/mapping is resolved; it cannot disappear into
an allegedly healthy empty projection. No byte-budget-driven top-K trimming.

Identity changes, new/changed evidence, pins, class transitions, deadline changes
and expiry boundaries are all incremental projection updates. After unchanged
source ingestion, there may still be a due expiry; that is a content change,
not a heartbeat.

## A1: durable qualification versus current support

### Observed conflict and duplicate behavior

Current code has no durable qualification ledger. These existing functions have
different responsibilities and must not be conflated:

| Function | Current behavior relevant to A1 |
| --- | --- |
| `is_template_or_noise`, `evidence_type_for`, `assess_evidence` | A duplicate count or template-sender count above one makes evidence TEMPLATE; its usable/strong classification can fall. Invalid signatures are also unusable, but for a different reason. |
| `raw_capability_evidence_decision` | Contextual or strict-pattern evidence that is no longer usable becomes SIGNAL rather than LIMITED/STRONG. |
| `capability_evidence_decisions` | Recomputes group multiplicity, then counts only the first non-NONE contribution per room/generation/template; later entries become NONE with `passed_threshold=false`. Input order affects the representative. |
| `CapabilityInferer.infer` | Recomputes current support, prefers higher-provenance representatives, deduplicates evidence locations and derives STRONG_SUPPORT, LIMITED_SUPPORT or SIGNAL_ONLY; NO_EVIDENCE entries are omitted. This is not historical retention. |
| `ExportObservationStore.upsert_many` | Replaces the current entry with the same evidence_id or fallback location_id and rewrites the current export. It is not an immutable audit store and must not implement the qualification ledger. |
| `_worker_evidence_snapshot`, `run_worker_cycle` | Deduplicate shadow decisions by current task/evidence/policy hash; this is separate from raw evidence deduplication and historical qualification identity. |

A pure in-memory check using the existing endpoint-switch debugging fixture
returned STRONG/true with one row, then SIGNAL/false and NONE/false after a
second same-template row. Reversing input order changes which row gets SIGNAL.
Canonical order fixes that choice, not the downgrade. This check used current
Router functions without SQLite, workers, network or identity access.

### Qualification creation and deterministic replay

**Durable qualification evidence** means the historical fact that a named source
and claim met a defined retention rule at a particular complete committed cut.
It is not a guarantee of present competence, objective correctness or independent
reputation. **Current support assessment** is today's Router evaluation and may
decline due to duplicates, contradictions, superseding evidence, failures,
expired context, newer validation or changed policy.

For CAPABILITY_USE, qualify when the final result of
`capability_evidence_decisions` has `support_contribution` LIMITED or STRONG and
`passed_threshold=true`, with valid required source/identity binding. Evaluate
the whole affected sender group in canonical `(room,generation,seq,raw_record_id)`
order using actual duplicate multiplicity and selected-scope template-sender
counts before DID filtering. Never run isolated rows with fabricated counts.
Duplicate suppression must run before qualification, not after recording a
transient raw-rule success. Preserve legacy/incomplete authenticity labels; the
record only claims the exact rule outcome, never upgrades it to VERIFIED_OFFLINE.

Other closed qualification types are CONTROLLED_BENCH, OBJECTIVE_VALIDATION,
CAPABILITY_CONTRADICTION and NEGATIVE_FACT. CONTROLLED_BENCH and
OBJECTIVE_VALIDATION require validated request/target/result linkage and an
authoritative configured local result or verified authorized sender. Their
outcomes are PASS or FAIL, separately preserving authenticity, correctness and
reproducibility. CAPABILITY_CONTRADICTION requires a reproducible versioned rule
and proof linkage, outcome CONTRADICTED. NEGATIVE_FACT requires the source review's
scoped adverse-fact proof, outcome ESTABLISHED_NEGATIVE_FACT. An invalid signature
can establish a negative fact about that envelope, not misconduct by its claimed
sender. Merely recognized Bench attempts remain permanent audits under the
existing BENCH_VERIFICATION rule without inventing a positive qualification.

Use one first qualification per `(source_ref identity, subject_did, claim,
qualification_type, selection policy hash, classifier version, qualification
policy version)`. Later LIMITED→STRONG or STRONG→NONE changes under that same
rule version update the current assessment, not the immutable first witness.
A genuinely different source, claim or reviewed rule version may produce another
witness. Replay preserves the original record byte-for-byte.

Bootstrap evaluates its declared complete source cut once. It must not invent
one-record historical cuts to manufacture success before existing duplicates.
Subsequent complete outbox batches are applied atomically, with witnesses appended
only after full group evaluation. Record an immutable evaluation event for each
bootstrap, whole source batch, due-expiry cut or reviewed policy migration.
Its stable ID and trusted local UTC evaluation time are replay inputs; its time
cannot precede first availability of all required proof. `qualified_at` is that
first successful evaluation's recorded time, never sender, replay or publication
time. Bootstrap does not backdate qualification to an old message's timestamp.
Due-expiry events use the declared deterministic expiry boundary after the required
source cut is complete; a delayed evaluation records its actual first complete
evaluation instant and reuses it on replay. Define these event and batch boundaries in
the durable producer ledger; processing chunk size cannot change those boundaries.
Same bootstrap/history/policy yields the same witness set. A missing/corrupt
ledger must be restored or cause a fail-closed review, not reset permanence.

### Durable record model

Existing `CapabilityEvidenceDecision`, `EvidenceItem`, `ValidationAttempt` and
`ValidatedCapabilityEvidence` supply capability, evidence, outcome and validation
identifiers. None represents an immutable ever-qualified fact. A1 therefore adds
`durable_qualifications`, with records of this exact shape:

```json
{
  "schema": "router-durable-qualification/v1",
  "qualification_id": "dq1:<64 lowercase hex>",
  "source_ref": {"kind": "PROJECTED_MESSAGE", "source_id": "scout-observer", "source_epoch": "<epoch>", "id": "sm1:<raw_record_id>", "sha256": "<exact text SHA-256>"},
  "scout_event_id": null,
  "evidence_id": null,
  "subject_did": "<bound DID or scoped claimed-identity subject>",
  "claim": {"kind": "CAPABILITY", "id": "software.debugging"},
  "qualification_type": "CAPABILITY_USE",
  "qualification_outcome": "STRONG",
  "qualified_at": "<trusted UTC qualification instant>",
  "policy_version": "router-evidence-horizons/2",
  "policy_sha256": "<64 lowercase hex>",
  "classifier_version": "router-evidence-classes/2",
  "qualification_policy_version": "router-durable-qualification/v1",
  "bootstrap_id": "<stable bootstrap identity>",
  "evaluation_id": "<stable complete evaluation event ID>",
  "source_cut": {"source_id": "scout-observer", "epoch": "<epoch>", "committed_event_id": "<canonical decimal cursor>"},
  "rule_id": "capability_evidence_decisions:software.debugging",
  "rule_input_sha256": "<64 lowercase hex>",
  "rule_group_sha256": "<64 lowercase hex>",
  "provenance_refs": [],
  "operator_group": "local-flop-agent-family",
  "same_operator": true,
  "independent_reputation": false,
  "authenticity": "LEGACY_SERVER_VERIFIED_NO_SIGNATURE",
  "correctness": null,
  "reproducibility": null,
  "initial_status": "VALID"
}
```

Placeholders are illustrative, not valid published values. All displayed keys
are required. `source_ref.kind` is PROJECTED_MESSAGE or LOCAL_ARTIFACT.
PROJECTED_MESSAGE resolves a real selected sm1 identity; its hash is exact UTF-8
text SHA-256, not Router's composite message hash. LOCAL_ARTIFACT names an
explicitly configured immutable local audit/validation artifact and hashes its
exact bytes; never fabricate a network position. source ID/epoch/id are nonblank
strings. `scout_event_id` and `evidence_id` preserve available actual identifiers
or NULL; neither replaces the stable source reference. A supplied event alias
must resolve to the same raw source, not a new interpretation after reparse.

`claim.kind` is CAPABILITY, VERIFICATION or NEGATIVE_FACT. Its ID is the exact
capability_id, request/validation ID, or scoped adverse predicate. A scoped
negative claim must distinguish an unauthenticated envelope from an accusation
about the purported sender. `qualification_outcome` is LIMITED/STRONG for
CAPABILITY_USE, PASS/FAIL for the two validation types, and the exact contradiction/
negative enums above. `initial_status` is always VALID: it records validity of
the original historical qualification, not a positive score. Failures may be
validly qualified negative facts. Unsupported types/outcomes fail closed.

`provenance_refs` is a canonical-byte-sorted, duplicate-free array of the same
five-field source_ref shape. It contains required authority/request/result and
adverse/context proof references, including the qualifying source itself. Keep
the full qualifying source and locally required audit dependencies permanently.
Local originals remain in their owner's configured audit storage; Scout projects
their immutable qualification/provenance without inventing messages. Missing
required local proof blocks qualification/publication, not an implicit positive
result. No reference authorizes URL following or arbitrary filesystem access.

`rule_input_sha256` binds C of the exact per-rule inputs and initial rule output;
`rule_group_sha256` binds C of the canonical ordered source identities/content
hashes and actual duplicate/template counts used for the complete group. C is
the canonical encoder in the source review (strict UTF-8, sorted object keys,
compact separators, ensure_ascii=false, allow_nan=false). Scout retains these
input manifests in its private replay/audit ledger, alongside bootstrap and feed
history. Hashes identify the historical computation; they are not independent
attestation or permission for Router to query the warehouse. Router verifies
available source/linkage/version/operator facts and the immutable ledger chain;
it never treats an inaccessible historical group hash as independently proven
competence or reruns today's group to erase yesterday's fact.

The qualification ID is `dq1:` plus SHA-256(C(record excluding qualification_id)).
Keep all other fields immutable. Duplicate IDs require identical canonical bytes;
the first-qualification tuple also prevents replacing a witness with a new ID
and later timestamp under the same policy. Strings are at most 256 characters,
hashes lowercase 64-hex, reference arrays at most 256 entries and a record at most
64 KiB. Apply exact-key/type, UTC, nonfinite-number and duplicate-key rejection.
Bounds fail closed, never truncate audit proof. Unknown operator values are NULL,
not inferred independence; configured local-family qualifications require the
canonical group, same_operator=true and independent_reputation=false. Bench
retains CONTROLLED_SAME_OPERATOR_VALIDATION provenance, never independent credit.

### Downgrade, supersession and exceptional invalidation

| Change | Effect on history and retention |
| --- | --- |
| Current support decreases, including STRONG_SUPPORT→LIMITED_SUPPORT→NO_EVIDENCE | No change to qualification validity, ID, original outcome or permanent retention. |
| Newer evidence/validation supersedes the preferred interpretation | Append SUPERSEDED linkage to the new qualification where applicable; preserve both. Supersession is not invalidation. |
| Original signature/provenance fails, identity binding is wrong, task/result linkage is broken, or original evidence is corrupt | Append a proof-backed INVALIDATED event; do not rewrite or delete the original qualification. |
| A classifier bug invalidated the original rule result | Only an explicitly coordinated, versioned reclassification directive naming affected qualifications/rule versions permits INVALIDATED. Ordinary rule upgrades do not. |
| Authoritatively proven fraud/spoofing affecting the original qualification | Append INVALIDATED with exact scoped proof and authority binding; a room allegation or new low score is insufficient. |

`qualification_events` is append-only. Each exact event JSON object contains:
`schema="router-qualification-event/v1"`, `event_id`, `qualification_id`,
`sequence` (integer starting at 1), `previous_event_sha256` (NULL at 1),
`event_type` (SUPERSEDED or INVALIDATED), `recorded_at`, `reason_code`,
`proof_refs`, `authority_ref`, `superseded_by` (qualification ID or NULL), and
`qualification_policy_version`. References have the source_ref shape above;
proof_refs is nonempty, sorted/unique and ≤256. The authority is a configured
local audit/reclassification directive or a verified, correctly scoped authority
artifact, never an arbitrary sender assertion. It must bind the target
qualification, reason and proof. The verifier/version/directive must be auditable.

Allowed invalidation reasons are SIGNATURE_PROVENANCE_FAILURE,
WRONG_IDENTITY_BINDING, BROKEN_TASK_LINKAGE, CORRUPTED_EVIDENCE,
COORDINATED_CLASSIFIER_RECLASSIFICATION and PROVEN_FRAUD_SPOOFING.
SUPERSEDED uses NEW_QUALIFICATION and requires a resolvable, distinct superseded_by
qualification in the same claim/subject domain. INVALIDATED requires NULL
superseded_by. Corrections can later add a separately valid replacement record
under a corrected source or coordinated new rule version and a supersession link.

`event_id = "dqe1:" + SHA256(C(event excluding event_id))`; subsequent
previous_event_sha256 equals the preceding ID's hash suffix. Enforce consecutive
per-qualification sequence, nonregressing recorded_at, identical bytes for reused
IDs, no forks and no missing targets/proof. The same 64-KiB/type/field rules apply.
Events never edit initial_status. Effective status is VALID until a verified
INVALIDATED event, then INVALIDATED irreversibly under this policy; no automatic
reinstatement or reversal by a later score. A later supersession leaves INVALIDATED
unchanged. Effective superseded_by is the latest valid supersession event's target;
retain all earlier targets/events. Reject supersession cycles.

**Even invalidation does not authorize deletion or unpinning in A1.** Preserve
the old record, attempted/corrupt evidence as available, failing hashes, proof and
dependencies as negative audit history. If original bytes are actually lost or
corrupted, retain the ledger and expected hashes and degrade for missing required
proof; do not overwrite the old hash to make it pass. Physical removal would need
a separate coordinated audit-retention policy and is outside A1. Ordinary score
downgrades cannot invoke any invalidation reason.

### Producer/consumer history boundary and versioning

Scout keeps its transactional qualification/replay ledger outside the minimal
working projection as proposed in the source review, and atomically projects
the immutable records/events into the two A1 tables below with selected evidence.
An equivalent deterministic implementation may derive records from the fixed
bootstrap and complete feed history, but must publish exactly these records;
current classification alone or a private boolean ever_qualified is insufficient.
Qualification/event IDs never depend on database/publication IDs or current score.
Any append, validity event or supersession is a material content change, not a
heartbeat. Retention membership and audit references remain monotonic. When a
higher-priority negative/pin reason wins, preserve the durable witness anyway.

The current annotations.classification remains the primary event type;
annotations.capability_support contains current rule outputs, not historical
qualifications. Current assessment belongs in separate Router-owned state keyed
by subject/claim/task and current evidence/policy hash, with current contribution,
support level, qualification, reason codes, evidence references and assessed_at.
It may reference historical qualification IDs, but must not overwrite them or
award support solely because they are retained. Duplicates may replace the current
canonical interpretation, never the original source/witness or its dependencies.

A1 keeps outer pointer/manifest `/v2` and base SQLite schema/user_version=2.
It adds required manifest `contract_revision="A1"`, selection
`version="router-evidence-horizons/2"`, classifier
`router-evidence-classes/2`, and required
`qualification_policy_version="router-durable-qualification/v1"`. The complete
policy hash binds all three versions. The A1 revision requires both new tables
and their manifest row counts. Validation must check this revision/version/table
combination, not user_version alone. Pre-A1 consumers' exact-field/version checks
reject A1; A1 consumers reject an absent revision, unsupported policies or missing
audit tables. This is an explicit wire-contract amendment, not silently accepted
extra columns or annotations. The seven existing table definitions remain frozen.

Existing genuine qualification records retain the original versions and input
hashes. A coordinated migration may import verified historical witnesses without
rescoring them under /2, but historical versions must be explicitly allowlisted
as audit-only. Never assign /2 semantics to a /1 event or fabricate a witness for
an old CAPABILITY_SUPPORT membership without proof. Preserve such legacy
membership and mark migration blocked until the original witness is restored or
a coordinated resolution is recorded. New rule versions qualify prospectively
at declared cuts, not by invented pre-duplicate history. Invalidated old witnesses
stay invalidated. No resetting IDs, pins, source checkpoints or existing decisions.

## Projection selection and minimal database schema

Database schema identifier: `scout-router-projection/v2`.
Selection policy: the explicitly bound object above. The published tables hold
one committed selected view, not producer-private checkpoints or arbitrary SQL.

The following is the proposed DDL. Consumer validation must check values and
relationships explicitly; the producer's declared SQL constraints are not proof
that an artifact satisfies them. Required tables are real tables, not views or
virtual tables. No triggers or executable extensions are permitted. Only the
listed application tables, columns and indexes are allowed in this minimal
contract; SQLite internal tables are not evidence.

```sql
PRAGMA user_version = 2;
CREATE TABLE snapshot_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema TEXT NOT NULL CHECK (schema = 'scout-router-projection/v2'),
    database_content_id TEXT NOT NULL,
    content_created_at TEXT NOT NULL,
    selection_policy_sha256 TEXT NOT NULL
);
CREATE TABLE messages (
    projection_row_id TEXT PRIMARY KEY NOT NULL,
    room TEXT NOT NULL,
    generation TEXT NOT NULL,
    seq INTEGER NOT NULL CHECK (seq >= 0),
    timestamp TEXT,
    sender TEXT NOT NULL,
    signed INTEGER NOT NULL CHECK (signed IN (0, 1)),
    text TEXT NOT NULL,
    normalized_text TEXT,
    template_normalized_hash TEXT,
    nonce TEXT,
    sig TEXT,
    message_hash TEXT,
    verification_status TEXT,
    source_export_hash TEXT,
    source_export_path TEXT,
    evidence_id TEXT
);
CREATE TABLE interactions (
    projection_row_id TEXT PRIMARY KEY NOT NULL,
    source_did TEXT NOT NULL,
    target_did TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    confidence REAL NOT NULL
);
CREATE TABLE source_provenance (
    entity_type TEXT NOT NULL CHECK (entity_type IN ('message', 'interaction')),
    projection_row_id TEXT NOT NULL,
    source_namespace TEXT NOT NULL,
    source_record_locator TEXT NOT NULL,
    scout_event_id TEXT,
    raw_record_id TEXT,
    raw_record_sha256 TEXT,
    annotations_json TEXT NOT NULL,
    PRIMARY KEY (entity_type, projection_row_id)
);
CREATE TABLE watermarks (
    room TEXT NOT NULL,
    generation TEXT NOT NULL,
    record_count INTEGER NOT NULL CHECK (record_count > 0),
    min_seq INTEGER NOT NULL CHECK (min_seq >= 0),
    max_seq INTEGER NOT NULL CHECK (max_seq >= min_seq),
    PRIMARY KEY (room, generation)
);
CREATE INDEX messages_coverage ON messages(room, generation, seq);
CREATE TABLE selection_membership (
    entity_type TEXT NOT NULL CHECK (entity_type IN ('message', 'interaction')),
    projection_row_id TEXT NOT NULL,
    retention_class TEXT NOT NULL,
    first_observed_at TEXT NOT NULL,
    retain_until TEXT,
    pin_roots_json TEXT NOT NULL,
    PRIMARY KEY (entity_type, projection_row_id)
);
CREATE TABLE coverage_history (
    room TEXT NOT NULL,
    generation TEXT NOT NULL,
    max_ever_projected_seq INTEGER NOT NULL CHECK (max_ever_projected_seq >= 0),
    witness_source_locator TEXT NOT NULL,
    witness_record_sha256 TEXT NOT NULL,
    PRIMARY KEY (room, generation)
);
```

A1 additionally requires these two real tables. They are separate from the
one-to-one message/interaction provenance tables; each JSON record embeds its
source references and versions as defined above. No qualification is a fabricated
network message. An A1 database includes both SQL blocks, not just the base DDL.

```sql
CREATE TABLE durable_qualifications (
    qualification_id TEXT PRIMARY KEY NOT NULL,
    record_json TEXT NOT NULL
);
CREATE TABLE qualification_events (
    event_id TEXT PRIMARY KEY NOT NULL,
    qualification_id TEXT NOT NULL REFERENCES durable_qualifications(qualification_id),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_json TEXT NOT NULL,
    UNIQUE (qualification_id, sequence)
);
```

Validate stored IDs/sequence against their JSON fields, canonical hashes, first-
qualification uniqueness, all event targets and append-only continuity explicitly;
SQLite declarations alone are not proof. Enable/check foreign-key consistency
on the private copy. Record counts for both tables are mandatory in the manifest,
zero only when no such records exist. Records/events, original qualifying sources
and required audit dependencies cannot disappear between accepted snapshots,
even when effective validity becomes INVALIDATED. Compare their immutable bytes
with the previous accepted private copy; corruption or unexpected loss degrades
readiness. Qualification-only changes increment database content identity.

`snapshot_meta` has exactly one row, matching the manifest's database content
ID, content creation time, database schema and policy hash. It must not contain
publication ID, heartbeat time or source polling counters: those would prevent
database reuse. IDs retain V1's canonical unsigned decimal format, maximum 20
digits, and numeric monotonic comparison.

Every message/interaction also has exactly one `selection_membership` row.
`retention_class` names a class above; `first_observed_at` is immutable UTC;
`retain_until` is NULL for permanent/unresolved/pinned rows and the deterministic
expiry otherwise. `pin_roots_json` is a sorted, duplicate-free array of objects
with exactly `kind` and `id` (nonblank strings). Kind is one of
`ROUTING_DECISION`, `TASK`, `VALIDATION`, `VERIFICATION`; sort by `(kind, id)`.
Use at most 256 roots per row,
64 KiB of JSON, and the same strict JSON rules as annotations. An overflow fails
qualification without dropping a pin. Published pin roots are included in the
policy-bound membership data, not inferred from current wall clock.

Durable qualification references impose permanent retention independently of
these four external pin-root kinds. Do not invent a QUALIFICATION pin-root kind
or drop a qualification dependency because its external pin_roots_json is empty.
Resolve the audit references transitively and retain their required evidence and
provenance with retain_until=NULL; a current classification change cannot undo
this obligation.

`coverage_history` retains one compact highest-ever-projected witness per domain,
including retired domains. Its locator and SHA-256 identify the source record
that supplied that sequence. `witness_record_sha256` is SHA-256 of the canonical
JSON object containing all named columns of that projected message row (same
JSON encoding rules as policy hashing), not a substituted raw-message or Router
evidence hash. It does not retain or claim to cover an entire
expired body. When a higher sequence is selected, update the witness atomically.
Never reset it on horizon eviction. This is monotonic projection history, not
a raw warehouse ingestion cursor.

Each message/interaction has exactly one `source_provenance` row; orphaned,
missing or duplicated links invalidate publication. `projection_row_id` is a
stable, nonblank identifier scoped by entity type, at most 256 characters. Scout
must define its mapping from a durable source primary key or stable source
locator before implementation. A staging row number or publication ID is not a
stable identifier. Multiple real source rows remain multiple projected rows,
even when their text is identical. Conflicting message contents at the same
room/generation/seq must fail validation rather than selecting a winner.

`source_namespace` identifies the logical source, not a temporary filename.
`source_record_locator` is a durable opaque lookup reference, not a URL Router
follows. Retain Scout event IDs, raw record IDs and exact raw-record SHA-256
where Scout has them. Unknown optional identifiers/hashes are SQL NULL, never
invented. Raw-record hashes, Router message hashes, artifact hashes and evidence
IDs are different identities and must not be substituted for one another.
The source mapping is subject to Scout review: its actual schema was not
accessed during this design.

Room/generation are nonblank strings of at most 256 characters. Sequence is a
SQLite integer, not a coerced float/string. Missing or NULL source generation
becomes `UNKNOWN_LEGACY`; numeric zero becomes `"0"`. Preserve available message
fields verbatim, including NULL versus explicit verification status. Existing
Router message hashing and signature normalization are unchanged. A producer
must not upgrade server-reported signing or a present signature to independent
offline verification. Router retains its existing verification/classification
logic. Invalid signature and incomplete provenance are distinct states, not
healthy positive support. `signed=0` is permitted for selected unsigned negative
or linked evidence; it cannot become positive signed capability support merely
because it is retained. The V2 adapter must separate this negative/linkage path
from the existing signed-observation scoring path.

Malformed text content is retained as data. A selected source row with an
unrepresentable required field (e.g. NULL text, invalid sequence, nonfinite
confidence) causes producer qualification failure; silently dropping it is
forbidden. Consumer revalidates the same conditions. Unsigned raw messages are
outside the selection policy, not asserted to have been verified or covered.

`annotations_json` is a UTF-8 object with exactly these keys; nullable values
mean unknown, empty arrays mean no available links:

```json
{
  "classification": null,
  "same_operator": null,
  "independent_reputation": null,
  "operator_group": null,
  "capability_support": [],
  "verification_links": [],
  "task_routing_links": [],
  "evidence_links": []
}
```

Classification/operator group are nullable strings; disclosure values are
nullable booleans. `capability_support` entries contain exactly `capability_id`,
`classification`, `evidence_id` (strings). `verification_links` entries contain
exactly `request_id`, `result_hash`, `bench_did`, `validation_id`, `correctness`,
`reproducibility`, `authenticity`, `evidence_classification` (nullable strings;
at least one of the first four identity fields non-null). Preserve the last
four fields as separate assertions; network authenticity does not imply correct
or reproducible work. `task_routing_links` entries contain exactly
`job_proto`, `job_id`, `task_hash`, `routing_decision_id`, `routing_decision_hash`
(nullable strings; at least one non-null). `evidence_links` entries contain
exactly `room`, `generation`, `seq`, `evidence_id` (nullable, with seq an integer
when present); a location requires all of room/generation/seq. A link without a
location requires a nonblank evidence ID. Preserve available links, including
links from interactions; do not require that every external target be included
in this projection. External references never authorize reads or network calls.

These are producer provenance assertions, not new scoring authority. Router's
same-operator disclosures and operator-group exclusions prevail: Scout, Bench,
Sentinel and Router cannot become independent peers, jurors or arbiters through
projection metadata. A conflicting positive independence claim for known local
agents fails validation. Unknown independence does not become positive evidence.
Controlled Bench conversion requires an explicitly configured Router-local proof
store and exact request/result/capability linkage; opaque projection audit rows
alone remain unscored. See [the consumer implementation boundary](ROUTER_V2_A1_PERFORMANCE_REVIEW.md#controlled-bench-originals). Invalid or
unverified annotations cannot create capability support or TCLK verified usage.

Bound annotations at 64 KiB per row and at 256 entries per array. Reject duplicate
JSON keys, extra keys, wrong types, nonfinite numbers and malformed supplied
hashes. Optional hashes are lowercase 64-hex when present. Oversized required
provenance causes publication failure, not truncation. Keep metadata out of raw
logs. Text is not truncated to fit a row budget; the artifact byte ceiling is
the final bound.

## V2 manifest and pointer

Pointer fields are unchanged except for an explicit version and V2 filename:

```json
{
  "schema": "flop-scout-router-current/v2",
  "manifest": "manifest-v2-<id>-<manifest-sha256>.json",
  "manifest_sha256": "<64 lowercase hex>",
  "published_at": "<UTC timestamp>"
}
```

```json
{
  "schema": "flop-scout-router-snapshot/v2",
  "contract_revision": "A1",
  "snapshot_id": "<canonical decimal id>",
  "publication_kind": "CONTENT",
  "database_content_id": "<canonical decimal content id>",
  "database": "router-projection-v2-<database-content-id>-<database-sha256>.sqlite",
  "sha256": "<64 lowercase hex>",
  "size_bytes": 12345,
  "database_schema_version": "scout-router-projection/v2",
  "selection_policy": {
    "schema": "flop-router-projection-selection/v1",
    "version": "router-evidence-horizons/2",
    "classifier_version": "router-evidence-classes/2",
    "qualification_policy_version": "router-durable-qualification/v1",
    "parameters": {
      "context_seconds": 2592000,
      "capability_signal_seconds": 7776000,
      "closed_work_seconds": 7776000,
      "closed_tclk_seconds": 7776000
    },
    "cutoff_semantics": "trusted-first-observed-strict-before-expiry/v1",
    "pinned_record_rules": "transitive-local-evidence-dependencies-no-implicit-unpin/v1"
  },
  "selection_policy_sha256": "<64 lowercase hex>",
  "content_created_at": "<UTC timestamp of last material DB change>",
  "selection_evaluated_at": "<UTC timestamp of checked source cut and expiry evaluation>",
  "produced_at": "<UTC timestamp>",
  "source_checkpoint": {"source_id": "<stable source>", "epoch": "<stable epoch>", "committed_event_id": "<canonical decimal cursor>"},
  "next_expiry_at": null,
  "row_counts": {"messages": 0, "interactions": 0, "source_provenance": 0, "selection_membership": 0, "watermarks": 0, "coverage_history": 0, "durable_qualifications": 0, "qualification_events": 0},
  "watermarks": [],
  "coverage_history": []
}
```

Examples use placeholders, not publishable IDs/hashes. Exact field sets,
duplicate-key rejection, integer-not-boolean validation and lowercase SHA-256
are mandatory. Consumer verifies actual row counts, including the one-to-one
provenance relationship. The manifest cannot increase consumer size limits.
No artifact may mix V1 and V2 pointer, manifest or SQLite schemas. V1 consumers
reject V2; the proposed V2 worker accepts V2 only and rejects V1/unknown versions.

V1's pointer/manifest limits (16 KiB/4 MiB), at most 10,000 domains in each
coverage list, timestamp syntax, 60-second future skew and configured freshness
checks remain. Require `content_created_at <= selection_evaluated_at =
produced_at <= published_at`; freshness uses `selection_evaluated_at`, not file
mtime or the age of reusable database bytes. Heartbeats must not refresh a
stalled/unvalidated source merely by setting a new timestamp. `next_expiry_at`
equals the minimum non-NULL expiry in membership; it is NULL only when none
exist. It must be strictly later than evaluation time. A due expiry requires
content reevaluation and, when membership changes, a CONTENT publication.

`source_checkpoint` is the committed incremental-feed cut checked by Scout,
not a room sequence and not an assertion that all warehouse bodies are included.
Within one source/epoch its integer cursor cannot regress, even if none of the
new source events changed selected evidence. Source/epoch changes require an
explicit reviewed migration. Router can verify monotonicity, not independently
prove upstream completeness against a compromised same-user producer. Artifact
names must match the exact V2 patterns; no absolute names, separators or symlinks.

## Database identity and heartbeat reuse

`snapshot_id` is the **publication ID**: increase it for every new immutable
manifest, including a heartbeat. A repeated publication ID must identify the
same manifest bytes/hash. `database_content_id` increases only when projected
contents change and otherwise stays equal. Both counters are durable across
producer restarts, never reused for different contents, and never regress.
Database filename uses the content ID and database hash, not publication ID.

After incremental ingestion, pin processing and due-expiry evaluation, if no
selected logical row, membership, coverage, provenance, qualification, qualification
event or policy changed, Scout
MAY emit `publication_kind=HEARTBEAT`, with a fresh publication ID and evaluation
time, pointing to the **existing** content ID/filename/hash/size. Its database
row counts, content creation time, policy and coverage must remain identical.
Only source progress, evaluation/publication times and publication identity may
advance. Do not mutate `snapshot_meta` for a heartbeat. Do not run another
backup, create another identical multi-GB artifact, or hash the mutable warehouse
merely to refresh `produced_at`.

Use a transactional dirty/material-change indicator over all published logical
fields. Cursor-only advancement, SQL no-op replay and producer housekeeping do
not dirty content. Actual message/provenance/pin/class/expiry/coverage changes and
qualification/event appends do.
For changed content allocate a new content ID, back up normally and emit CONTENT.
Do not return to an older content ID when evidence later happens to match old
rows. Physical maintenance alone must not create a duplicate routing decision;
reuse the existing publication until a material change needs publication.

Persist the accepted publication ID/hash/time and content ID/hash separately.
Reject lower content IDs, same-content-ID/different-hash or policy bindings, and
same-publication-ID/different-manifest. Heartbeat reuse is allowed only for the
same latest content; it cannot roll back from B to previously valid A. On first
startup even a heartbeat requires full verified artifact acquisition. Later
heartbeats can use a retained Router-private verified content copy with matching
ID/hash/policy; a missing or invalid cache requires descriptor-bound reacquisition
or degraded readiness. On restart reverify that copy's hash before SQLite use.
Never trust producer filename existence alone or cache publication files directly.
Manifest freshness/continuity and expiry checks still run on every heartbeat.

## Coverage and continuity

V2 watermarks describe **included evidence**, not Scout's raw warehouse
cursor, last fetched message, or completeness through every sequence number.
The manifest list and `watermarks` table must exactly equal this query, sorted
lexicographically by room/generation:

```sql
SELECT room, generation, COUNT(*) AS record_count,
       MIN(seq) AS min_seq, MAX(seq) AS max_seq
FROM messages
GROUP BY room, generation
ORDER BY room, generation;
```

Each list entry has exactly `room`, `generation`, `record_count`, `min_seq`,
`max_seq`. Sequence gaps are allowed and are not claimed as covered. Duplicate
watermark keys, missing entries, unsupported domains or mismatched counts/ranges
fail closed. Empty messages require empty watermarks, not invented zero maxima.
Interactions have verified row counts and source links, not fabricated room
watermarks. The artifact hash binds all rows, including provenance and edges.
Hashing proves artifact consistency, not that a compromised same-user producer
included every eligible source row; producer-side parity qualification is needed.

The `coverage_history` list exactly matches its table, sorted by room/generation,
with exactly these five fields: `room`, `generation`,
`max_ever_projected_seq`, `witness_source_locator`, `witness_record_sha256`.
Its domain set is append-only and its maxima never decrease. For each current
domain, historical max is at least current max. New maxima require a matching
current message/provenance witness; unchanged historical witnesses stay bound
across retirement. This is a retained source assertion of highest projected
sequence, not proof of a contiguous or full historical body archive.

Persist accepted version/policy, both IDs/hashes, all relevant times, source
checkpoint, current coverage and historical witnesses. Reject ID/time/cursor
regression, stale/future publications, hash conflicts and historical watermark
regression. Corrupt/unreadable state is not a new installation.

Current counts/min/max may change when context legitimately expires; treating
them as monotonic would contradict the horizon policy. Keep the previous accepted
verified projection in Router-owned state and compare row/membership identities
before accepting a new content artifact. Every disappearing row must have been
finite-horizon, unpinned, and expired under the same supported policy at the new
evaluation time. Permanent, unresolved or pinned rows cannot disappear. Reject
early disappearance, silent pin loss, mutated first-observed time and shortened
expiry. A recognized terminal transition may set an unresolved row's expiry;
validate it from its retained terminal evidence. Retiring an entire current
domain is allowed only through these checks; its historical witness remains.
On restart reverify the prior private copy against persisted hashes. A missing
continuity copy after an accepted checkpoint degrades; it does not authorize
skipping comparison. Preserve previous state/copy until candidate acceptance is
durable; cleanup follows the committed reference, not a crash-interrupted rename.

V1 maxima include unsigned messages and cannot be compared directly to V2
maxima. Migration must retain V1 coverage as historical V1 provenance and
establish a distinct V2 coverage checkpoint; it must not claim that the V2
projection covers those unsigned rows. Global snapshot ID/hash/time continuity
still applies across migration. Do not silently reset IDs or discard checkpoints.

## Supplied production statistics and scope

These are operator-supplied historical observations, not measurements taken by
this revision. Their checkpoints must not be combined into a purported current
database census.

| Checkpoint | Exact supplied counts |
| --- | --- |
| Latest explicitly reported evidence integrity | 338,970 raw records; 338,970 parsed events; 1 signature failure; integrity PASS |
| Same integrity report | Zero orphaned events, hash mismatches, raw identity mismatches, missing events, seq conflicts, unlinked compatibility records, source gap errors, coverage integrity errors and foreign-key errors |
| Earlier 172,532-raw-record checkpoint | 164,706 signature verified; 1 signature failure; 4 DID mismatches; 5,924 malformed records; 3,650 live records ingested; 9 active watch collections |
| Earlier 175,086-raw-record checkpoint | 167,260 signature verified; 1 signature failure; 4 DID mismatches; 6,023 malformed records; 6,204 live records ingested |
| Reported TCLK checkpoint | 32,495 indexed; 27,751 parseable; 4,744 malformed; 32,428 signed matching; 66 DID mismatches; 20 signed unexpired offers for review |

The historical verified counts show that filtering solely on authenticity may
remove little data. They do not establish the latest selected message count.
TCLK remains observation-only: no accept, lock, reveal, refund, settlement or
autonomous assignment.

At a separate 168,882-raw-record migration checkpoint, the approximately 1.1-GiB
warehouse had these `dbstat` table sizes: raw_network_records 211.0 MiB;
evidence_records 186.7 MiB; opportunities 132.7 MiB; messages 126.0 MiB;
observed_events 97.1 MiB; compatibility_evidence_links 81.9 MiB; tclk_frames
27.1 MiB. Selected indexes were raw_network_records autoindex 25.9 MiB; raw_did
18.2 MiB; evidence_records autoindex 15.8 MiB; compatibility link autoindex
14.1 MiB; raw_hash, event_content_hash and messages hash index 13.5 MiB each;
messages template-hash index 13.4 MiB; messages sender index 11.9 MiB. These
figures motivate eliminating duplicated warehouse representations and irrelevant
indexes. They are not measurements of the V2 schema and must not be added to or
scaled from the later >52-GiB observation as a projection estimate.

The reported Bench request `FVR-83c180e9b05f85b0a72b` links VERIFIED_OFFLINE
network authenticity, PASS correctness, DETERMINISTIC reproducibility,
`same_operator=true`, `independent_reputation=false` and Router's
`CONTROLLED_SAME_OPERATOR_VALIDATION` classification. These are separate facts;
the projection preserves their linkage without treating them as independent
reputation or a new scoring conversion.

## Historical pre-A1 materialized multi-scale sizing validation

These retained measurements cover the original seven-table projection, before
the A1 qualification/event tables. The sizing utility still builds that baseline
only; its artifacts are not A1 publications and cannot qualify an A1 consumer.
Do not overwrite the historical JSON with a claim it measured qualification
history. Its DDL hash continues to identify the unchanged base SQL block. A1
implementation qualification must extend the benchmark to realistic accumulated
witnesses/events and retained dependencies; added audit storage is subject to the
same preferred/qualification/hard limits and is not assumed free. No new large
benchmark or runtime qualification is claimed by this amendment.

The historical command below is retained for provenance. Reruns should write a
new output file and remain labelled seven-table baseline, not A1 validation:

```sh
/Users/greg/Dev/flop-router/.venv/bin/python -B /Users/greg/Dev/flop-router/tools/model_scout_projection_v2.py --scales 100000 350000 1000000 2500000 --output /private/tmp/router-projection-seven-table-baseline.json
```

The checked-in [machine-readable measurements](SCOUT_ROUTER_SNAPSHOT_V2_BENCHMARK.json)
record the exact database/index bytes, artifact SHA-256, DDL/fixture hashes,
SQLite/Python versions and platform. These replace the earlier 5,000-row linear
extrapolation. All four scales below were **actually constructed, integrity
checked, backed up with SQLite online backup, closed/fsynced, hashed and deleted
from temporary storage**. No live Scout database or Router worker was used.

A projected evidence row means one message or interaction; each also has a
provenance row and a membership row. The total physical application rows are
therefore approximately three times the requested evidence count, not merely
100k/350k/1M/2.5M rows across all tables. The split is about two-thirds messages,
one-third interactions. The synthetic mix has 90% context with 188-byte plain
annotations and 10% durable Bench-shaped records with 1,022-byte link-rich
annotations. These ratios are declared assumptions, not production statistics.
Message text cycles through 103 literal `obs(...)` occurrences (48 unique texts)
from repository tests, averaging about 145 combined text/normalized-text bytes.
This is short-text capacity testing, not a production text-length sample or a
complete incremental-classifier implementation. Signatures are explicitly
unverified placeholders; raw hashes refer only to synthetic records.

Measured on macOS arm64, Python 3.11.14, SQLite 3.53.4:

| Projected evidence rows | Messages / edges | DB MiB | Index MiB | Bytes/evidence row | Build s | Backup s | SHA-256 s | Peak process RSS MiB |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100,000 | 66,666 / 33,334 | 114.12 | 13.63 | 1,196.69 | 1.32 | 0.27 | 0.05 | 74.83 |
| 350,000 | 233,333 / 116,667 | 399.73 | 48.09 | 1,197.57 | 5.32 | 0.71 | 0.17 | 60.55 |
| 1,000,000 | 666,666 / 333,334 | 1,142.34 | 137.69 | 1,197.83 | 16.22 | 2.30 | 0.81 | 63.36 |
| 2,500,000 | 1,666,666 / 833,334 | 2,856.08 | 344.45 | 1,197.93 | 42.33 | 8.44 | 1.86 | 58.97 |

Index size includes SQLite autoindexes and the explicit coverage index, measured
with `dbstat`; it is already included in DB size. Bytes/evidence row include all
provenance, membership, indexes and fixed schema overhead. Each scale runs in a
fresh child process, so peak RSS is a per-scale high-water measurement using
`getrusage`, not an accumulation across scales. It includes construction,
validation, backup and hashing, but excludes OS filesystem cache and is **not**
a measurement of Router's profile-building memory.

Build timing includes schema/data/index/membership construction, batched commits
and WAL checkpoint. It is a synthetic bootstrap cost, not a per-publication
warehouse scan. Backup timing includes destination conversion to standalone
rollback-journal format, closing, file fsync and directory fsync. Hash timing
streams the closed artifact in 1-MiB chunks. Source projection integrity-check
times were 0.18, 0.67, 11.64 and 52.89 seconds respectively; these are additional
to the displayed build/backup/hash timings. Destination/consumer full validation,
concurrent-writer load and incremental classifier/pin/expiry work remain separate
qualification tasks. Results are single warm-cache local runs, not cold-storage
or production latency guarantees.

## Normal size expectations and hard limits

- Preferred production projection: **strictly below 512 MiB**.
- Normal production qualification: **strictly below 1 GiB**, with growth and
  memory/latency checks; prefer enough headroom to remain below 512 MiB.
- Default hard consumer ceiling: **4 GiB = 4,294,967,296 bytes**.
- A limit above 4 GiB, up to **8 GiB = 8,589,934,592 bytes**, may only be an
  explicit operator override after separate capacity/latency justification.
  Eight GiB is not the default or a fallback. Never auto-escalate on oversize.

Proposed `--max-snapshot-bytes` remains one worker-subcommand integer option:
omission selects 4,294,967,296; a smaller value tightens it; an explicitly supplied
larger value is an override subject to the above review, never more than
8,589,934,592. Log the resolved limit and whether it is an override. No manifest,
heartbeat, source setting or environment-derived default may raise it. This is
the approved design. The development consumer implements the 4-GiB default and
lower overrides only; values above 4 GiB remain rejected pending separate review.

Check manifest length, opened descriptor length and streamed byte count against
the configured ceiling. Exact ceiling is permitted; ceiling+1 fails closed as
`DEGRADED_INPUT_INVALID` / `SNAPSHOT_TOO_LARGE` before SQLite/routing. Producer
oversize failure preserves the previous pointer; its eventual staleness degrades
readiness. A file below the emergency hard ceiling is not automatically qualified
for normal production. Never trim durable/pinned/negative rows to fit a budget.

The measured 100k and 350k evidence-row fixtures occupy about 114 and 400 MiB,
respectively, demonstrating the preferred range for this declared mix. The 1M
case is about 1.12 GiB and misses normal qualification; the 2.5M case is about
2.79 GiB and also misses qualification despite being below the 4-GiB hard limit.
Actual post-selection production counts, text lengths, edge ratios and durable/
pinned fractions remain unknown; neither the historical 338,970 raw-record count
nor the >52-GiB warehouse observation is an exact projection-size measurement.

Production expectation is the <512-MiB working-set target, not a claim of a
measured production result. Scout must report the actual selected class counts,
text/provenance bytes, retained pins, growth, closed artifact size and resource
costs before launch. Long text, a larger pinned/durable population or fragmentation
can exceed the measured shape. An incremental DB must reclaim freed pages with
bounded producer-side maintenance so expired rows do not leave a permanently
large backup; online backup does not promise to compact a freelist. Bootstrap
may configure incremental auto-vacuum; qualify its overhead separately from
these initially compact fixtures. Do not rebuild the full warehouse to compact
the projection or use compaction to discard evidence.

## Publication I/O estimate

For a changed S-byte projection, online backup entails approximately S bytes
read and S bytes written, and SHA-256 adds another S-byte read: **about 3S**
logical artifact I/O, plus validation/index reads, journal activity and fsync.
New Router acquisition adds approximately S read + S private-copy write; hashing
is combined with that same descriptor read. SQLite validation and comparisons
with the prior accepted private projection add their own reads. Actual physical
I/O depends on cache, page reuse, WAL and storage; do not call these logical
byte totals measured device-write counts.

At the measured 350k scale (about 400 MiB), producer backup+hash took about
0.88 seconds and the baseline 3S is about 1.17 GiB; a new Router acquisition adds
about 0.78 GiB before SQLite work. These are single-run estimates, not a promised
polling cadence. Avoid publishing unchanged content on each poll: fresh
heartbeats reuse the database and require only the small manifest/pointer writes
and directory fsyncs (within the unchanged 4-MiB/16-KiB JSON bounds). Incremental
source/pin/expiry checks still run; zero DB-artifact I/O does not mean zero work.
A healthy matching Router-private cache avoids another publication DB copy;
restart/cache loss requires verification or reacquisition as described above.

Full validation is significant: the 2.5M fixture's source integrity check alone
took about 53 seconds, exceeding the current consumer's 30-second acquisition
deadline. Thus the 4-GiB ceiling is an emergency bound, not evidence that maximum-
size cycles are operationally suitable. Keep the normal projection small and
measure Router parsing/profile memory and deadline behavior before deployment.
Do not silently extend deadlines or raise limits to make qualification pass.

## Dedicated incremental projection database

Scout exclusively owns a persistent configurable database, suggested location
`~/.flop_scout/router_projection.sqlite`. This is mutable producer state, never
a Router input or publication path. Scout may use WAL for it. The immutable
publication directory remains separate. Only Scout accesses either live DB.

After an explicitly scheduled one-time bootstrap, incrementally consume Scout's
durable committed change feed/outbox through its legitimate connection. Process
only new/changed records and affected dependency/classification groups, plus
indexed due expiries and pin updates. Source transactions must be applied as
whole committed batches, including source links and coverage. A source feed gap,
lost dependency, unknown source epoch or incomplete batch blocks fresh publication;
do not scan/rebuild the >50-GiB warehouse as a publication fallback. Recovery or
policy migration needing a new bootstrap is separate scheduled work, never part
of the normal publication cycle.

Before applying a projection transaction, durably journal the complete evaluation
identity/time, source cut and exact qualification/event records in the producer
ledger. Replay must reuse those records, including qualified_at, after any crash;
it must not rerun a first qualification with a new clock value. An incomplete
journal entry is not an applied cut and cannot authorize publication.

Projection transactions update selected rows, membership, durable history and
content identity atomically. Operations are idempotent by durable source identity;
do not duplicate edges or refresh first-observed time on replay. A producer-owned
checkpoint/journal records source cursor, pin import cursor, expiry queue and
publication state outside the published-schema database. Commit/fsync projection
changes before advancing that checkpoint. A crash in between leaves a lagging
checkpoint and safe replay; it must never leave a checkpoint ahead of committed
projection data. This does not assume cross-database WAL transactions are atomic.

Re-evaluate only affected classifier/dependency groups, and use indexed expiry
queues to make time-based changes. Mark publication content dirty only for actual
published logical changes. Source cursor advancement over excluded/no-op events
updates producer bookkeeping without changing projection database metadata.
The publisher may coalesce dirty updates into one publication while maintaining
the configured freshness budget. It cannot call an unchanged but lagging
projection healthy merely because the main Scout process is alive.

## Online-backup publication and consumer isolation

For changed content, use SQLite online backup **of the dedicated projection DB**
into private Scout staging. Coordinate the read snapshot with projection updates
so the backup, content ID, policy and recorded source cut describe one committed
view. Source cut may lag the writer's newest transaction, but cannot claim a cut
newer than the backed-up view. Never independently copy main/WAL/SHM files and
never first back up the full observer warehouse.

Validate types, selected-scope parity, links, membership, coverage and integrity.
Make the destination standalone rollback-journal SQLite (`user_version=2`,
header read/write versions 1/1), close all destination connections and confirm
no companion dependency. Close before byte counting/SHA-256. Fsync the database,
publish under its new immutable content-ID/hash name without overwrite, then
fsync the directory. Write/fsync/publish the immutable manifest and fsync the
directory. Write/fsync and atomically replace `current.json` last, then fsync the
directory. Counters survive restart; aborted IDs are not recycled. For a valid
heartbeat use only the manifest/pointer steps and reference the retained artifact.

## Retention with shared database artifacts

Retain current and previous manifests for at least
`max(600 seconds, Router max-snapshot-age)` after pointer replacement. Database
lifetime is determined by references, not by its creation age or a single old
manifest's expiry. A months-old database still referenced by a fresh heartbeat
must remain present.

Scout garbage collection takes a consistent reference set under publication/GC
coordination: current pointer's manifest, every retained manifest and any in-flight
publication lease. Remove eligible old manifests first; recompute references;
only then may unreferenced databases outside the staging/grace window be deleted.
Never unlink a database referenced by any retained/current manifest. Protect the
interval between selecting a reused artifact and publishing its new manifest
with the same lease/lock. Persist/recover leases or apply a conservative crash
grace period; uncertain GC state delays deletion, not publication verification.
Do not rely on an in-memory reference count surviving a crash. Scout cleans only
its own staging/publication state. Router cleans only its own private copies and
uses committed state references to preserve the prior continuity copy.

## Router descriptor isolation

Router retains one trusted publication-directory descriptor, rejecting symlinks
in every ancestor. Open pointer, manifest and database relative to it with
`O_NOFOLLOW`; regular-file checks and bounded reads remain mandatory. Verify
manifest filename/hash/ID, then hash/count/copy the database from the same open
descriptor into Router-private storage (0700 directory, 0600 file). Never reopen
a verified source by pathname. Never inspect/copy Scout WAL/SHM/journal files.
Only the verified private copy reaches SQLite (`mode=ro`, `query_only=ON`), then
integrity/schema/type/link/coverage validation. No queries against live Scout,
no changes or cleanup in its publication directory.

SIGINT/SIGTERM must cancel acquisition, hashing, SQLite work, routing and polling,
clean private copies/locks, restore handlers and persist shutdown when possible.
Retain V1's cooperative kernel-I/O limitation. Resolve the prior review's masked
unbounded append and missing polling cancellation state before claiming these
guarantees. Degraded input never produces a decision.

SHA-256 continues to prove consistency, not independent attestation against a
compromised same-user Scout producer. No new signing identity or signature
format, wallet, transaction execution or network posting is introduced. Existing
signed `flop-routing-decision/v1` hashes/signatures remain unchanged; settlement
stays `SIMULATION_ONLY`/`DISABLED`.

## V1 to V2 migration and required code changes

1. Coordinate the source-column mapping, deterministic classifier, selection
   scope changes, pin-import channel and production census with Scout's owner.
   Approve supported policy parameters and qualified size/latency limits.
2. Implement Scout's persistent incremental projector and online-backup publisher,
   distinct IDs, heartbeat reuse and reference-aware retention. Test these
   independently before any Router restart; no per-publication warehouse scan.
3. Implement a V2-only worker consumer in `scout_snapshot.py`: explicit version
   strings/names, byte setting, `user_version=2`, table/value/link validation,
   meta/count equality, membership and both kinds of coverage. Preserve the
   descriptor path; implement a Router-owned verified cache for heartbeat reuse
   and restart-safe membership/continuity comparisons.
4. Replace `_worker_snapshot_profiles`' adapter monkeypatch with an explicit
   projection reader returning the existing `AgentObservation`/interaction
   representations plus provenance and explicit selected-history scope. Reuse
   classification and `ProfileBuilder` where valid; qualify changes caused by
   horizons instead of claiming full-history parity. Do not move trust/scoring
   authority to Scout. Keep optional JSONL sources
   explicit, with no devdata fallback and no automatic live-DB fallback.
   Also load/validate durable qualifications and their event chains independently
   from current capability scoring. Persist current assessments separately;
   retain old witness versions, evidence and audit proof. Implement A1's complete-
   cut creation, non-destructive supersession/invalidation and permanent-history
   continuity checks. Do not use export-store upserts to replace immutable history.
5. Fix checkpoint loading, legacy `HEALTHY` readiness, unordered evidence hashing
   and cancellation defects identified in the pre-commit review. Canonicalize
   unordered collections by logical content/identity while preserving actual
   multiplicity and semantically ordered data. Separate source-audit metadata
   from substantive decision inputs. Exclude publication IDs/times, producer
   build paths and copy filenames from deduplication; retain evidence identities,
   authenticity, capability, verification, risk and operator facts.
6. Recognize foundation state without a publication checkpoint as
   `UNKNOWN_LEGACY`. Preserve histories/decision IDs. Existing V1 checkpoints
   require an explicit reviewed migration of coverage domains; preserve their
   original contents and global ID/time guard. Corrupt state never authorizes
   migration. Do not delete history, reuse IDs, or pretend V1 warehouse watermarks
   are V2 evidence coverage. Bind the accepted contract/selection policy in state
   so a subsequent V1 pointer fails closed.
7. Version the shadow policy if its substantive hash representation changes and
   document any intentional one-time reevaluation. Do not change signed decision
   schemas. Run parity, safety and restart tests below. Foreground qualification
   must succeed against the V2 producer before a separately approved deployment.

The list above is the original coordinated implementation plan. Current consumer
coverage and remaining blockers are recorded in the consumer review. V1 tests are
retained alongside V2 tests. README's proposed foreground/launchd arguments must
not be used to restart production before coordinated operational qualification.

## Compatibility and acceptance test plan

The following is the original producer/consumer acceptance plan. See the consumer
review for executed tests; listing a case here does not claim it passed.
Use temporary synthetic fixtures and a Scout-owner-operated aggregate benchmark;
Router tests must not access live Scout. Retain existing V1 tests as version-
rejection/migration fixtures and adapt consumer safety tests to V2.

| Planned test | Required assertion |
| --- | --- |
| `test_v2_large_warehouse_small_projection` | Build a Scout-style source with a large unrelated raw-envelope table and selected messages/edges; projector streams only selected columns. CI uses a bounded fixture; an opt-in producer benchmark uses >50-GiB materialized synthetic data. No full backup, source rewrite or Router live-DB access. Projection size follows selected payload, not warehouse bytes. |
| `test_v2_projection_capacity_no_silent_trimming` | Sweep selected record counts/text/provenance sizes; verify every eligible row and measure closed bytes. At exact byte limit accept; at limit+1 reject before SQLite/routing. Over-limit producer preserves old pointer. Manifest lies, growing descriptor and streamed overflow fail closed. |
| `test_v2_profile_and_decision_parity` | At a fixed clock and identical task/optional-source inputs compare a reference implementation of the approved selection policy to incremental V2 observations/profiles/plans. Explicitly review differences from unbounded V1; do not claim lifetime parity. Include noise, duplicate templates, invalid DIDs and selected interaction multiplicity. Reordered physical rows do not cause new decisions. |
| `test_v2_provenance_round_trip` | Scout event/raw IDs and hashes, source locators, nonce/signature, message/evidence hashes and room-generation-seq resolve unchanged; unknown remains NULL. Missing/orphan/conflicting links fail. No link is followed. |
| `test_v2_same_operator_and_bench_links` | Preserve Bench request/result/task/routing linkage and controlled same-operator classification. Reject falsely independent local-agent claims; no independent juror/peer credit and no automatic audit-only conversion. Explicit original-proof linkage is covered by the consumer performance correction below. Existing validation attempts produce identical accepted/rejected evidence. |
| `test_v2_tclk_semantic_parity` | Keep normalized JSONL enabled explicitly; compare hint, invalid amount/signature, DID mismatch, deadlines, receipt, rails, job/contract, Sentinel and operator semantics before/after projection. Message annotations never replace TCLK evidence or promote hints. |
| `test_v2_malformed_and_unverified` | Retain parseable negative/unverified evidence; never upgrade authenticity. Unrepresentable selected fields, unknown schema, malformed/oversize annotation JSON and false coverage fail closed. Selected unsigned negative/linked rows remain unsigned; irrelevant unsigned chatter is excluded without claiming its sequences. |
| `test_v2_watermarks_and_generations` | Recompute current counts/min/max and historical witnesses; distinguish legal horizon eviction from early loss. Test empty/retired domains, duplicate/missing history, sequence gaps, NULL/zero generations, early count loss, pin loss and regression across restart. Warehouse cursors are never substituted for coverage. |
| `test_v2_version_and_state_migration` | V1 consumer rejects V2; V2 rejects V1 and mixed/unknown versions, including SQLite version. Foundation state stays readable but not falsely healthy. Preserve existing decisions, global ID/time continuity and distinct V1 coverage archive. Corrupt/unreadable checkpoints fail closed. |
| `test_v2_publication_races_and_copy_isolation` | Replace pointer/manifest/database during acquisition, rename parents, truncate/disappear files and cancel copy; use old verified inode or fail closed. Hash and copy share a descriptor; SQLite opens only the private copy; no companions or publication writes. |
| `test_v2_continuity_freshness_and_dedup` | Same-ID content conflict, rollback, future skew, stale publication, and checkpoint corruption reject. Same evidence after one hour, pointer advancement, row reordering and process restart suppresses duplicates; substantive evidence changes reevaluate. |
| `test_v2_cancellation_once_and_run` | Real subprocess SIGINT/SIGTERM during pointer read, copy, hashing, long SQLite validation, routing, commit boundary and polling; bounded response, no post-cancellation new decisions, accurate committed counts, persisted shutdown, restored handlers and no leaked temp files/locks. |
| `test_v2_producer_consistent_cut` | Concurrent transactions change messages, provenance and interactions together; every publication is one committed cut. Crash at each fsync/rename step leaves old valid pointer or complete new publication, never a partially published projection. |
| `test_v2_incremental_selection_and_replay` | Bootstrap once, then ingest only committed deltas, pin updates and due expiries; instrument queries to prohibit full warehouse scans during publication. Crash before/after projection commit and checkpoint write; replay is idempotent and preserves first-observed time, edge multiplicity and source-cut consistency. |
| `test_v2_selection_policy_boundaries` | Test exact 30/90-day boundaries, late arrivals, forged future sender times, unknown classes, all permanent negative/Bench/operator/capability classes, unresolved work/TCLK, pinned transitive dependencies and cycles. Same cut/time/policy gives identical selected rows; changes to parameters or rules require supported policy migration. |
| `test_v2_heartbeat_shared_artifact` | Unchanged data advances publication ID/time/source checkpoint while content ID/hash/path remain fixed; backup and new DB creation are not called. Due expiry/material change requires new content. Reject refreshed timestamp with stale evaluation, regressed content ID, and same-ID hash changes. Cache loss/restart must reverify or degrade. |
| `test_v2_retention_shared_references` | Many retained heartbeats reference one old DB; never delete it until all references/leases expire. Race GC with heartbeat publication, crash and recover leases/reference scans; uncertain state conservatively retains DBs. |
| `test_v2_size_configuration` | Default 4 GiB; no silent promotion to 8 GiB. Explicit later-justified override is logged. Exact configured limit accepted, limit+1 rejected through manifest/descriptor/stream checks; normal qualification requires <1 GiB and prefers <512 MiB. |

### A1 contract acceptance cases

These are normative producer/consumer acceptance outcomes. During the original
A1 documentation revision only the pure duplicate-rule fixture was executed;
the subsequent consumer review records the new fixture and integration tests.

| Case / planned test | Required result |
| --- | --- |
| 1. `test_a1_concrete_support_qualifies_once` | A complete cut yielding final LIMITED/STRONG with passed_threshold creates one valid immutable witness, retains the full source/proof and makes membership permanent. SIGNAL/NONE and partial-batch successes do not qualify. |
| 2. `test_a1_later_duplicate_weakens_current_score` | Endpoint-fix source qualifies STRONG at cut A; a later complete cut B adds the same-template duplicate and current output becomes SIGNAL/NONE using actual multiplicity. |
| 3. `test_a1_duplicate_does_not_expire_original` | Advance past every normal horizon after case 2; the original sm1 row, qualification and required audit dependencies remain, with retain_until=NULL. |
| 4. `test_a1_current_support_is_independent` | Separate current assessment can show SIGNAL_ONLY, LIMITED_SUPPORT or NO_EVIDENCE while the initial STRONG qualification remains unchanged and historically VALID. Retention does not award current support. |
| 5. `test_a1_later_contradiction_downgrades_support` | Add valid contradictory/new failure evidence; change current support/risk without using invalidation merely because the score fell. |
| 6. `test_a1_history_auditable_after_supersession_restart` | Newer validation supersedes a current interpretation; both witnesses and event chain remain after process restart with original versions, source cuts, input hashes and operator facts. Export upserts cannot overwrite them. |
| 7. `test_a1_signature_invalidation_requires_proof` | An authoritative proof that the originally qualifying signature was invalid appends INVALIDATED and makes effective status INVALIDATED; initial outcome/record hash remain unchanged. A new low score or allegation is insufficient authority. |
| 8. `test_a1_invalidated_qualification_is_retained` | Invalidated record, original attempted evidence, expected hashes, proof/event and dependencies remain permanent audit history; deletion or implicit unpin fails continuity validation. Actual missing bytes degrade rather than being silently repaired. |
| 9. `test_a1_same_operator_never_independent` | Local-family qualification stays same_operator=true, independent_reputation=false; wrong group/positive independence conflicts fail. Qualification count is not independent peer count. |
| 10. `test_a1_controlled_bench_remains_same_operator` | Preserve request/result/task linkage, separate authenticity/correctness/reproducibility and CONTROLLED_SAME_OPERATOR_VALIDATION. A retained Bench PASS is not independent reputation and alone cannot score; the consumer correction below requires explicitly linked original proofs. |
| 11. `test_a1_policy_change_preserves_old_semantics` | A coordinated new policy may change current support, but old witness policy/hash/qualified_at stay byte-identical. Missing historical proof cannot be filled by rescoring under the new policy. Unsupported historical versions are audit-only or migration-blocking, not silently active. |
| 12. `test_a1_classifier_change_preserves_provenance` | Keep old classifier version and group/input hashes; only an explicit proof-backed coordinated bug directive may invalidate. A prospective classifier update alone cannot rewrite or revoke old qualification. |
| 13. `test_a1_bootstrap_batch_replay_determinism` | A bootstrap already containing both duplicates creates no invented one-row STRONG witness. Fixed bootstrap, committed batch/evaluation events and canonical order reproduce identical IDs/history across chunks/restarts. Loss of the witness ledger fails closed. |
| 14. `test_a1_schema_event_and_identity_rejection` | Reject missing A1 revision/tables, wrong policy/classifier/qualification versions, malformed/oversize records, reused-ID mutations, first-witness replacements, event-chain gaps/forks, missing authority/targets, supersession cycles and any disappearing audit row. |

Production sizing and parity remain review gates. The subsequent consumer
implementation has synthetic test results and measured capacity failures;
neither a 4-GiB ceiling nor fixture compatibility is deployment approval.
Consult the consumer review before coordinated implementation/deployment review.


## Consumer performance correction (implementation note)

The A1 producer wire schema and selection policy above are unchanged. The Router
consumer now derives a separate private summary database using streaming and SQL
aggregation. This is not a new Scout publication table, index or capability label.
Every changed artifact still receives full `integrity_check`. A hash-bound private
cache permits reusing validation for unchanged content, with full file rehashing
on restart. The source artifact, policy, scope, coverage and freshness bindings
remain mandatory. See [the measured implementation review](ROUTER_V2_A1_PERFORMANCE_REVIEW.md).

Kibble and deadline-only TCLK finite memberships are checked against the retained
source-scoped transcript. Bench evidence remains permanently retained even after
an exactly linked result establishes an outcome. No generic prose-based closure
rule has been added: an unsupported terminal grammar remains unresolved.
The optional Router-local proof envelope is a consumer configuration interface,
not permission to dereference opaque Scout `LOCAL_ARTIFACT` IDs or paths.

## LG1: legacy-reported generation metadata

Historical storage format: keep this exact revision readable/rejectable by name;
do not redefine it in place. LG2 below supersedes its storage representation only.

**DECISION A: LEGACY_REPORTED_METADATA_ALLOWED.**

`STRICT_GENERATION_AUTHORITY = YES`

`LEGACY_GENERATION_PROJECTION_READY = YES`

These flags mean that the compatibility model is specified, not that the
existing producer/consumer can accept it or production is ready. This is neither
generation enrichment nor resolution. There is no `resolved_generation`.

### Evidence and authority decision

Scout's [generation-authority report](../../flop_scout_v02/docs/router-projection-v2-generation-authority-evidence.md)
and [aggregate](../../flop_scout_v02/docs/router-projection-v2-generation-authority-evidence.json)
establish 161,073 distinct affected legacy raws: 127,146 have only reported
`"0"`, 33,927 only `"1"`. There are no competing concrete generation sets or
alternate exact raw candidates in that cut. The 32,890 raws with multiple
same-generation cache links are not additional independent observations.
**Zero affected raws have original authoritative transport-generation binding.**

The previous strict-authority conclusion remains correct. This extension
instead separates the meaning of captured metadata from a migrated report.
Agreement and uniqueness establish neither original server generation nor
independent corroboration. Other nonlegacy captures genuinely contain zero and
one; neither number is universally an unknown sentinel. No executing historical
code revision is inferred from the ingestion-version constant or timestamps.

Not every affected record passes all other checks: the supplied evidence reports
14 unsigned raws, one invalid signature and two additional DID-mismatch flags.
Missing sender fields and malformed protocol records also remain relevant.
LG1 does not certify all 161,073 rows as publishable or positive evidence.

### Wire compatibility and exact version binding

Keep outer pointer `flop-scout-router-current/v2`, manifest
`flop-scout-router-snapshot/v2`, SQLite schema `scout-router-projection/v2`,
user_version=2, and the nine existing table definitions unchanged. **Use
`contract_revision="A1-LG1"`**, not `"A1"`, for the extension. The closed A1
manifest/annotation field sets force an explicit compatibility revision.
Existing A1 artifacts retain their exact original shapes and meanings.

An A1-LG1 manifest has all A1 fields, the changed revision, and exactly one new
required field `legacy_generation_policy`, whose value is exactly:

```json
{
  "schema": "router-legacy-generation-authority/v1",
  "migration_class": "scout-legacy-evidence-v1-service-poll",
  "allowed_reported_generations": ["0", "1"],
  "authority": "LEGACY_REPORTED_ONLY",
  "match_status": "UNRESOLVED_LEGACY",
  "watermark_domain": "CAPTURED"
}
```

This complete exact object is bound by the existing canonical manifest hash;
the manifest also binds the database hash. No optional/default policy is allowed
for LG1. The revision fixes this policy version/value and annotation shape;
unsupported revisions/objects fail before SQLite/routing. Preserve existing
selection/classifier/qualification versions: this does not change retention or
the historical rules that created qualifications. Do not assign LG1 fields to
an old qualification record. A future change to these LG1 rules requires a new
explicitly supported revision/policy combination, not parameter substitution.

For LG1 only, every `annotations_json` object has the eight original keys plus
one required `legacy_generation` key. It is null for interactions and messages
outside the admitted class. For an admitted message it has exactly this shape
(placeholders below are illustrative, not valid identifiers/hashes):

```json
{
  "captured_generation": "UNKNOWN_LEGACY",
  "reported_generation": "0",
  "generation_authority": "LEGACY_REPORTED_ONLY",
  "generation_match_status": "UNRESOLVED_LEGACY",
  "migration_class": "scout-legacy-evidence-v1-service-poll",
  "raw_source": "legacy_evidence",
  "ingestion_schema": "flop-scout-evidence/v1",
  "ingestion_version": "1",
  "legacy_record": true,
  "raw_completeness": "PARTIAL",
  "cache_source": "service-poll",
  "transport_lineage": "UNAVAILABLE_IN_LEGACY_CAPTURE",
  "raw_record_id": "<original raw id>",
  "raw_text_sha256": "<exact UTF-8 text SHA-256>",
  "linked_cache_records": [
    {
      "cache_table": "evidence_records",
      "source_record_locator": "<stable cache record identity>",
      "record_sha256": "<canonical original cache record SHA-256>",
      "reported_generation": "0"
    }
  ]
}
```

Every displayed key is required; no extra keys or `resolved_generation` are
accepted. All fixed strings/booleans equal the shown literals, except reported
generation may be `"0"` or `"1"`. Ingestion version is the canonical string
`"1"` representing the recorded version-one value; it is not a Git revision.
`raw_record_id` is the actual 64-lowercase-hex identity, equal to provenance and
the suffix of `sm1:`. The raw text hash must equal the recomputed message text
hash; it is not substituted for the distinct raw-envelope hash.

Each cache reference has exactly the four displayed keys. Tables are restricted
to `evidence_records`, `tclk_frames`, `kibble_events`; include every linked
concrete-generation row in those tables, with at least one evidence_records
reference. Referenced record hashes bind C of the original table's named-column
object (all columns, no synthetic SQLite rowid); preserve those exact originals
in Scout's existing audit/replay storage. Use existing stable cache identity or
the full canonical record hash as the locator, never a temporary/publication ID
or migration-assigned row number. Identical repeated references collapse by
their complete canonical object. Distinct originals remain distinct audit refs.
Reject a reused table/locator with different hash or generation. Sort the array
by canonical bytes; require 1–256 entries and no duplicates. All reports equal
the top-level reported generation. Normal 256-character identifier, 64-hex hash,
64-KiB annotation, strict JSON and finite/type bounds apply without truncation.

These cache references are producer audit assertions, not permission for Router
to open arbitrary paths or independently attest historical cache originals.
Router validates the available projected bindings and structural consistency;
Scout must verify and retain the source originals. Artifact hashes establish
consistency, not immunity to a compromised same-user producer. The private
originals and public bounded annotations serve different purposes.

### Exact admitted class and remaining conflicts

The only exception is comparison of absent captured generation with a concrete
**reported** value in the reviewed legacy migration class. Scout must check each
row against all of the following; the aggregate total is not an allowlist:

1. Actual raw generation is NULL or UNKNOWN_LEGACY; preserve its original raw
   representation. Project `messages.generation="UNKNOWN_LEGACY"`. Source is
   legacy_evidence, legacy flag is one, completeness PARTIAL, ingestion schema
   flop-scout-evidence/v1 and version one. The original evidence cache source
   is service-poll, and raw reported_generation is exactly `"0"` or `"1"`.
2. At least one exact evidence-cache link binds the same immutable raw identity,
   room, sequence and exact text/raw hashes. Validate available sender, nonce,
   signature and network-time bindings using their original field meanings.
   Required unavailable identity/linkage remains a failure; never fabricate it.
   Distinguish absence of fields in a protocol cache schema from an assertion
   that those fields matched. Existing cache ambiguity rules remain: this
   extension does not select a winner among multiple rows in the same cache.
3. Independently inspect every applicable linked compatibility row and all exact
   raw candidates. All concrete reports, including raw reported_generation,
   form the same singleton set. No competing raw identity or incompatible
   lineage exists. Multiple same-generation links across cache types are allowed
   only with valid individual bindings; they convey no independent authority.
   A generationless message cache supplies no additional concrete report.
4. The original transport endpoint/body/header/epoch proof is unavailable in this
   class, not known contradictory. This *explicit* missing-authority condition
   is recorded as UNAVAILABLE_IN_LEGACY_CAPTURE. The mapping of service-poll
   cache to legacy_evidence container explains ingestion lineage only. It must
   not be described as a verified original transport lineage or header match.
   A supplied conflicting endpoint/transport assertion fails; other sources,
   ingestion versions or reported values remain outside this exception.

After these checks, only the captured-versus-reported generation comparison
ceases to be fatal. Concrete captured `"0"` versus reported `"1"` (and reverse),
UNKNOWN_LEGACY linked to both, mismatched room/sequence/text/hash, required sender
mismatch, alternate raw candidates, invalid/unverifiable linkage and incompatible
lineage remain fail-closed. Missing required evidence cannot be omitted to make
publication succeed. Malformed/unsigned/invalid-signature evidence that is
otherwise representable remains under existing negative/audit retention rules,
without positive authenticity or qualification promotion. Signature failure is
not itself a competing generation assertion; this exception does not repair it.

### Captured coverage, workflow, qualification and interaction identity

All projected identity and coverage operations continue to use
`messages.generation`, never `legacy_generation.reported_generation`.
Watermarks and coverage_history stay in UNKNOWN_LEGACY. Retain original domain
maxima/witnesses across restart; no count or witness moves to zero/one. Optional
diagnostic counts of reports must be labelled non-authoritative and separate
from watermark lists. No report satisfies concrete-generation continuity.

Reported generation may explain migrated linkage in audit/status output only.
It cannot establish a workflow domain, close a workflow across domains, repair
missing issuer/root/result proof or justify finite expiry. An UNKNOWN_LEGACY
workflow can use only independently sufficient existing exact-ID/authority
proof within its captured domain; absent or ambiguous closure remains unresolved.
Do not use the report as an additional filter to select one otherwise ambiguous
root or interaction endpoint.

Durable qualifications remain byte-identical with their original source refs,
outcomes, versions, input hashes and first qualification time. An otherwise valid
qualification based on UNKNOWN_LEGACY stays explicitly in that provenance
domain; a verified signature alone proves no concrete generation. New admitted
records qualify, if at all, only through the existing complete-cut rules and
actual authenticity/identity predicates. Preserve linked legacy audit metadata
and originals for every retained qualification dependency. No historical witness
is fabricated by treating the reported generation as prior observed evidence.

Duplicate/template grouping, observation/composite hashes and evidence locations
use captured generation. Extra same-generation cache reports neither duplicate
the raw message nor add independent support. The `si1:` interaction identity
specified in Scout's source review includes generation in both endpoint objects:
use captured UNKNOWN_LEGACY for affected endpoints and retain existing raw IDs,
roles, direction and relationship type. `resolve_interaction` must still find
one unambiguous captured-domain endpoint pair. Reported values must not choose,
merge or rename endpoints. Local-family same-operator exclusions are unchanged.

Audit-only changes to reported metadata cannot confer scoring authority or
independently trigger routing. Bind them to artifact/continuity/audit state, but
exclude this audit-only object from the routing-semantic fingerprint. Conflicting
updates degrade before deduplication. New source evidence, validity events and
actual current-support changes remain material routing inputs.

### Migration, replay and cache compatibility

No Scout warehouse/raw-record migration is required or authorized. Use explicit
derived audit fields during projection (option B in the migration question),
without changing captured/reported source values, raw IDs, original envelopes,
hashes, first-observed times or cache originals. Preserve the original migration
attributes; do not infer migration time from created_at == retrieved_at.

For the same complete cut and policy, reconstruct identical annotations/cache
reference order from immutable originals across batches/restart. Within a
revision, accepted legacy report/class/binding fields cannot mutate or disappear
while the source is retained. Cache-reference additions require valid new exact
source links; removals or changed existing references fail continuity. Conflicting
late reports block publication rather than relabelling captured identity.

The current A1 runtime must reject LG1. Future support must explicitly dispatch
both revisions and reject mixed field sets. An existing accepted A1 checkpoint
requires a separately explicit migration choice to A1-LG1: retain the old private
copy and histories, enforce all ID/time/source-cut guards, validate any new audit
annotation independently and preserve all existing substantive row/qualification
bytes. The original message row and coverage witness hashes need not change:
the extension is in annotations, not message generation. Retain historical A1
coverage. An accepted LG1 state rejects a later A1 downgrade.

Use a new content ID and CONTENT publication for the extension, never a
heartbeat. Store the accepted revision and exact legacy policy in worker state.
Bind source-validation and derived-index cache versions to that combination;
never reuse cached A1 validation as proof of LG1 annotation validation. Rebuild
private indexes for the explicit transition. No silent checkpoint deletion,
raw rekeying, qualification rewrite, ID reset or automatic migration flag.

### Implementation tasks and planned tests

**Scout:** implement exact class/source checks and annotations; change only the
reviewed captured-versus-reported comparison; preserve originals and complete
link multiplicity; retain strict conflicts; emit/bind A1-LG1 policy; maintain
captured coverage, workflows and interaction IDs; test deterministic replay.
Do not silently drop the known unsigned, signature-failure, DID-mismatch or
malformed populations. A later dry-run may expose other independent blockers.

**Router:** implement revision dispatch, exact policy/annotation validation,
projected raw/text bindings, audit visibility and continuity; preserve captured
generation throughout profiles, qualification, workflow and edges; exclude only
the new audit-only object from semantic deduplication; add explicit state/cache
migration support. Do not add live Scout access, network reads or signing changes.

The following tests are **planned, not implemented or executed by this contract
task**. Every positive case must also pass unchanged provenance/security checks.

| Case | Required result |
|---|---|
| 1. Legacy reported zero | Eligible UNKNOWN_LEGACY + `"0"` accepted as unresolved audit metadata under LG1 only. |
| 2. Legacy reported one | Same for `"1"`; nonzero grants no authority. |
| 3. Captured value | Raw provenance and projected UNKNOWN_LEGACY remain unchanged. |
| 4. Separate report | Preserve exact report, policy/class and all bounded cache refs separately. |
| 5. Watermarks | Counts/witnesses remain UNKNOWN_LEGACY; no concrete coverage inflation. |
| 6. Zero authority | Cannot use reported zero for a concrete-generation lookup/continuity proof. |
| 7. One authority | Same prohibition for reported one. |
| 8. Competing reports | A single raw linked to both zero/one rejects, including a late conflicting link. |
| 9. Concrete conflict | Captured zero/reported one and reverse reject. |
| 10. Hash mismatch | Room/seq match with different text/raw binding rejects. |
| 11. Sender | Required mismatch/missing binding rejects; no positive identity invented. |
| 12. Alternate raw | More than one plausible raw candidate rejects, regardless of row ordering. |
| 13. Closure | Report cannot bridge domains or resolve an ambiguous/missing workflow proof. |
| 14. Qualification | No concrete authority or new historical witness from a report; retain legacy dependencies. |
| 15. Interaction | Canonical si1 endpoints use captured generation; same-generation cache multiplicity does not duplicate edges. |
| 16. Replay | Same inputs yield identical audit/identity; preserve state/history and reject report/ref loss. |
| 17. Versions | Reject missing/unsupported policy, wrong revision/annotation shape and silent A1↔LG1 migration/cache reuse. |
| 18. Operator | Same-operator flags and independent-group exclusions remain unchanged. |
| 19. Negative evidence | Unsigned, invalid-signature, DID-mismatch and malformed facts remain distinct and never promoted. |
| 20. Audit dedup | Audit-only additions do not emit a routing decision; true conflicting updates degrade without routing. |
| 21. Class boundary | Reject nonlegacy sources, wrong schema/version, unsupported reports and contradictory transport metadata. |
| 22. Bounds | Reject extra/duplicate keys, malformed hashes, duplicate/conflicting refs and oversized annotations without trimming. |

After separately authorized implementation and synthetic qualification, Scout's
owner must repeat the frozen-copy production dry-run at a complete source cut.
Report accepted/rejected counts by authority and negative/linkage reason; verify
pins, required dependencies, history, captured watermarks and immutable IDs.
Publish nothing if any required source remains invalid. Only a valid immutable
artifact can qualify Router performance with unchanged 4-GiB/30-second/512-MiB
limits. Neither the prior empty staging projection nor this contract is readiness
or deployment approval. Do not start either service as part of this review.

## LG2: compact legacy report storage

`LG_STORAGE_CONTRACT_REVISED = YES`

`SCOUT_LG_COMPACT_IMPLEMENTATION_READY = YES`

`ROUTER_LG_COMPACT_IMPLEMENTATION_READY = YES`

These were contract implementation-readiness flags. Subsequent separately
authorized Router implementation and tests are recorded in the [LG2 review](ROUTER_A1_LG2_CONSUMER_REVIEW.md);
they do not establish production qualification. **All LG1 authority,
admission, true-conflict, retention and audit obligations remain unchanged.**
Captured generation stays UNKNOWN_LEGACY. There is no enrichment, resolved
generation, watermark promotion, workflow bridging, qualification promotion or
independent-evidence promotion. The reviewed migration class is not broadened.

### Contractual size problem and complete field classification

Scout's [implementation report](../../flop_scout_v02/docs/router-projection-v2-lg1-implementation.md)
records 491 passing tests and compatible synthetic fixtures, but substantial
overhead. The [optimization diagnostic](../../flop_scout_v02/docs/router-projection-v2-lg1-optimization-review.md)
locates 99.8% of public growth in source_provenance: 896 extra JSON payload bytes
per single-witness row, about 912 allocated bytes at scale. Public indexes add
zero bytes. The 2k payload-only floor exceeds the complete control DB by 53.6%.
Index removal or smaller batches cannot eliminate mandatory repeated strings.

Classification: A = row-variant; B = snapshot-constant; C = policy-constant;
D = derivable; E = audit-only. E describes purpose and may coexist with A/C/D.
Every key in the former per-message object is accounted for here:

| Former LG1 field | Class | LG2 source / reconstruction |
|---|---|---|
| captured_generation | D | Referenced messages.generation, required UNKNOWN_LEGACY. |
| reported_generation | A | reports.reported_code: 0→`"0"`, 1→`"1"`. |
| generation_authority | C | Membership in reports under the bound policy implies LEGACY_REPORTED_ONLY. |
| generation_match_status | C | Same membership implies UNRESOLVED_LEGACY. |
| migration_class | C | Exact manifest legacy_generation_policy.migration_class. |
| raw_source | C | Admitted class fixes legacy_evidence. |
| ingestion_schema | C | Admitted class fixes flop-scout-evidence/v1. |
| ingestion_version | C | Admitted class fixes canonical `"1"`; not an executing Git revision. |
| legacy_record | C | Admitted class fixes true. |
| raw_completeness | C | Admitted class fixes PARTIAL. |
| cache_source | C | Admitted evidence-cache class fixes service-poll. |
| transport_lineage | C | Admitted class fixes UNAVAILABLE_IN_LEGACY_CAPTURE; not verified lineage. |
| raw_record_id | D | Original identity suffix of referenced sm1 message/provenance, decoded from raw_ref. |
| raw_text_sha256 | D | SHA-256 of referenced exact message.text; use non-NULL message_hash only after verifying that equality. |
| linked_cache_records | A/E | Normalized witness rows; retain every distinct original reference. |
| linked_cache_records[].cache_table | A/E | cache_kind enum. |
| linked_cache_records[].source_record_locator | A/E, sometimes D | Exact locator; empty storage token decodes to lower-hex record_hash only when identical. |
| linked_cache_records[].record_sha256 | A/E | Required cache-original hash, compact 32-byte BLOB. |
| linked_cache_records[].reported_generation | D/E | Parent reported_code; all linked reports must pass the original singleton-generation check before admission. |

Contract revision and the whole LG policy object were already manifest-bound,
not additional per-row keys. They remain B/C, as do selection/classifier/
qualification versions. No field is silently dropped from the logical audit
view: the old object can be reconstructed exactly from the new representation,
with canonical reference ordering. The public format need not persist that view
as JSON. Audit-only does not mean disposable; per-witness provenance is retained.

### Revision and snapshot binding

Choose **contract_revision="A1-LG2"**. Outer pointer/manifest `/v2`, database
schema identifier `scout-router-projection/v2`, user_version=2 and the original
nine tables remain unchanged. LG2 adds exactly the two tables defined in
[router-legacy-generation-lg2-schema.sql](router-legacy-generation-lg2-schema.sql).
Exact revision/table/column/index/generated-column validation is mandatory;
user_version alone cannot identify the format. A1/LG1 runtimes reject LG2.

The LG2 manifest has all LG1 fields, the new revision, and one new required
field:

```json
{
  "legacy_generation_encoding": "router-legacy-generation-storage/v2"
}
```

This object shows the added member, not a complete manifest. Its exact value,
the unchanged full `router-legacy-generation-authority/v1` policy object and
the database hash are bound by the canonical manifest hash. The revision fixes
the DDL, enum dictionary and decoding rules below; no absent/default encoding
or alternative policy is accepted. Selection/classifier/qualification semantics
and versions remain unchanged. `row_counts` gains exactly
`legacy_generation_reports` and `legacy_generation_witnesses`, including zero
counts when empty; validate both against the database.

**LG2 annotations revert to the original eight A1 keys.** Neither a null
`legacy_generation` slot nor an expanded object is permitted. No report row
means the message is outside the LG1-admitted class; an unrelated unknown capture
does not become admitted by being unknown. Interaction annotations likewise
contain no LG field. Tables must exist even for zero admitted rows. Mixed JSON/
relational encoding rejects, rather than choosing whichever representation wins.

### Stored columns, references and compact enums

The SQL companion is normative and additive to the original nine-table DDL.
Both new tables use WITHOUT ROWID primary-key B-trees, with no duplicate
secondary uniqueness indexes. No extra indexes are part of this public revision.
Foreign keys must be enabled and checked; declarations alone do not prove data.

`legacy_generation_reports` stores one row per admitted message:

- `raw_ref`: 32-byte binary encoding of the original 64-hex raw-record identity.
  This is a compact foreign-key reference, not a new identity or another copy
  of a raw-text/raw-envelope hash. The virtual generated `message_id` is exactly
  `sm1:` + lowercase hex(raw_ref), with a required logical reference to messages
  checked by the bulk anti-join below. The generated
  value consumes no per-row stored text payload. Never use artifact-local rowids.
- `reported_code`: integer 0 means reported string `"0"`; integer 1 means
  reported string `"1"`. It is not captured generation. Unknown codes/types reject.

Row presence under LG2 means authority_code=1 (LEGACY_REPORTED_ONLY) and
status_code=1 (UNRESOLVED_LEGACY); neither constant requires a physical column.
Other authority/status meanings are unsupported, not fallback values. Do not
add undocumented numeric codes or trust producer strings to redefine them.

`legacy_generation_witnesses` stores distinct source-original witnesses:

- `raw_ref`: foreign key to the admitted report; repeats only the relationship
  reference, not source text, sender, room, sequence or interaction identity.
- `cache_kind`: 1=evidence_records; 2=tclk_frames; 3=kibble_events. Others reject.
- `record_hash`: exactly 32 bytes; decoding gives the existing lowercase 64-hex
  canonical original cache-record SHA-256. This hash cannot be removed or
  replaced with the message's raw-text hash.
- `locator`: exact original locator text, or empty **storage token** iff the
  original locator equals lowercase hex(record_hash). The token reconstructs
  that full nonblank locator; it never means unknown/missing. Any explicit
  locator equal to that hash must use the empty token, eliminating alternate
  encodings. Other locators are preserved byte-for-byte, never shortened,
  relabelled or replaced with hashes to improve size. Apply LG1's full string
  bounds/UTF-8 validation after decoding, beyond SQL's partial CHECK constraints.

The composite witness PK prevents identical stored duplicates. Additionally
reject a repeated `(raw_ref, cache_kind, decoded locator)` with different hashes.
Require 1–256 distinct decoded witnesses per report, at least one evidence_records
witness, and no orphan witnesses/reports. Retain the original 64-KiB bound on
the logically reconstructed annotation including the other eight fields; a
compact encoding does not expand admitted proof limits. Iterate per message
with a bounded witness set, never materialize all message text/originals.
The witness FK/PK indexes support raw_ref lookups; validate generated columns through
`table_xinfo`/exact schema checks, not table_info alone. SQLite must support the
specified virtual generated column and witness foreign-key checks or reject startup;
no silent ordinary-column/rowid fallback is permitted.

The producer still reads original source/report values, checks every concrete
report for agreement, validates each original and rules out competing raw
candidates. A differing report must fail **before** collapsing reports into one
code; selecting the first value or the majority would violate LG1. Shared labels
do not collapse distinct cache witnesses. Witness count is derived with COUNT,
not stored as a substitute for identities/hashes. Additional cache links do not
produce extra messages, edges, support, operator groups or independent evidence.

### Validation, auditability and unchanged semantics

For every report, join the generated message_id to messages and its one-to-one
source_provenance row. Verify the sm1/raw identity equality, captured
UNKNOWN_LEGACY and all existing message/provenance/hash conditions. Check the
exact LG policy and encoding, decoded references, enum values, class membership
and continuity. Producer-side class/original/source checks are **unchanged**.
Moving constants to policy is no permission to skip checking source attributes
or to label a nonlegacy row as admitted. Producer originals remain required for
stage/replay/publication validation exactly as in LG1. Router verifies available
projected bindings; it does not gain independent access to those originals.

The report→message reference is a required **logical foreign key**, checked
set-wise, like the existing A1 message/provenance relation. This query must return
no row before sealing/publishing any producer cut and during consumer validation:

```sql
SELECT r.message_id
FROM legacy_generation_reports AS r
LEFT JOIN messages AS m ON m.projection_row_id = r.message_id
LEFT JOIN source_provenance AS p
  ON p.entity_type = 'message' AND p.projection_row_id = r.message_id
WHERE m.projection_row_id IS NULL
   OR p.projection_row_id IS NULL
   OR m.generation <> 'UNKNOWN_LEGACY'
   OR p.raw_record_id IS NOT lower(hex(r.raw_ref))
LIMIT 1;
```

Retained-proof validation must also prohibit silently dropping a report to make
this query pass. No per-row message_id secondary index is introduced: a physical
FK on this unindexed generated child would cause repeated full report scans
when messages expire. The witness→report physical FK is efficient because its
child key is the leading primary-key column. Deletions must be coordinated at
the same complete producer cut; PRAGMA foreign_key_check alone is insufficient.

| Audit question | Deterministic answer |
|---|---|
| What was captured? | Referenced message and original source provenance: UNKNOWN_LEGACY. |
| What was reported? | Decode reported_code to the exact original string. |
| Why non-authoritative? | Manifest-bound policy/class implies missing original transport authority, not observed zero/one. |
| Which records supplied it? | Join witnesses; decode cache table, exact locator and immutable cache hash; bind to raw_ref/source_provenance. |
| Which interpretation? | Accepted revision, unchanged full authority policy, and explicit storage encoding in manifest/state. |
| Was it in the reviewed class? | Report-table membership is the producer's checked class assertion, backed by retained originals; consumer validates the available bindings. |

The compact representation is lossless for all logical LG1 annotation fields.
No full text, sender, room, sequence, raw-text hash, raw-envelope hash or
interaction ID is added to these tables. Raw_ref is necessarily repeated for
FK relationships, but is stored as 32 bytes rather than duplicating its 68-byte
sm1 representation and indexes. Cache-original hashes remain distinct audit
evidence. Hashes still provide consistency, not independent producer attestation.

Watermarks, historical witnesses, workflow identity/closure, qualifications,
duplicate groups, interaction si1 endpoints and substantive routing hashes
continue to use captured generation only. Do not use reported_code as an
observed-generation join/filter. Otherwise valid legacy qualifications retain
their actual provenance; bad/missing authority is not repaired. Unsigned,
invalid-signature, DID-mismatch, malformed and true-conflict behavior remains
unchanged. Same-operator exclusions remain unchanged. These two audit tables
are excluded from scoring/deduplication inputs except insofar as a conflict
invalidates readiness; audit additions alone never create a routing decision.

### Continuity, replay and migration

Compare logical decoded identities/fields, not physical B-tree order. Decode
each bounded witness set and sort by canonical LG1 reference bytes. The same
source/proof/policy yields the same report and witness set irrespective of
insertion order, SQLite page layout, batch size or restart. No newly assigned
surrogate IDs or row numbers enter source/interaction/qualification identities.

Retained report codes and class semantics cannot change/disappear; existing
witness references cannot change/disappear; legitimate validated additions are
allowed as before. Required qualification dependencies retain their full report/
witness closure. Any base evidence removal must still satisfy the existing
retention/continuity rules. Foreign-key cleanup does not authorize early deletion.

An explicit LG1→LG2 transition must archive/preserve the original immutable
publication, accepted state and producer replay history; decode old LG1 audit
objects and prove exact logical equality to normalized LG2 records before
acceptance. Preserve original locators, cache hashes and all private originals.
Existing history remains LG1 when replayed; a versioned migration operation
changes its storage view, not historical qualification or captured provenance.
Remove the public LG1 annotation slot only in the new artifact; do not edit the
old file or change raw Scout records. A separately approved A1→LG2 migration
uses the same guards and independent admission checks, not invented old reports.

Allocate new monotonic content/publication IDs and a CONTENT publication even
when only storage changes; never present this transition as a same-artifact
heartbeat. Persist the accepted revision/encoding/policy. Explicit migration
must rebuild/rebind consumer validation/index caches; incompatible cached LG1
validation is not LG2 validation. Reject downgrade, mixed shapes, unsupported
versions and silent reset. Once LG2 content is accepted, ordinary unchanged
heartbeats reuse it under the same freshness/continuity guarantees.

Private producer replay storage may normalize/interleave shared immutable
original objects to avoid repeated raw text, provided original canonical bytes,
hashes, history and replay results reconstruct exactly and a separately tested
private-ledger migration preserves old history. This does not authorize removing
original proof or treating a private hash alone as a replacement for its bytes.
Public LG2 tables do not prescribe a new private-ledger runtime here.

### Storage model and qualification targets

Targets, relative to the **same projected evidence population and base fields**
without the LG audit addition: preferred ≤10%, acceptable ≤15%, coordinated
review maximum ≤25%. Use a representable paired control; do not call an A1
control actual admission of formerly conflicting data. Fixed metadata overhead,
SQLite page allocation, witness multiplicity and locator lengths count. No
source/proof trimming is allowed to hit these percentages.

[SCOUT_ROUTER_LG2_STORAGE_ESTIMATE.json](SCOUT_ROUTER_LG2_STORAGE_ESTIMATE.json)
records a contract-level synthetic allocation model, with reproducible source
and SQL hash. It creates only temporary tables with hash-random synthetic IDs,
4096-byte pages, no VACUUM, and bounded 500-row insert batches. It uses witness
multiplicity `1 + 32890/161073`, rounded at each scale. Parent message data is
shared and excluded from *added* bytes. Added-table dbstat includes all their
primary-key B-tree pages; there are no added secondary indexes. A conservative
8-KiB allowance for fixed schema/file metadata is included in planning totals.

Two locator scenarios bracket useful shapes: H, every locator exactly equals
its cache hash (empty token); L64, every locator is a distinct 64-byte value.
Both preserve exact locator meaning. Actual production locator distribution is
not supplied; longer locators/higher witness fanout can exceed this model.
The synthetic DDL was executed and integrity/FK checks passed; these files are
not valid producer publications or consumer/production benchmarks.

The sizing table below is generated from that model. SQLite bytes are allocated
table pages, payload includes record headers, and residual overhead includes
page/cell/free-space effects. LG1 estimates use exact JSON lengths (896 bytes
for one evidence witness, 1126 for evidence+TCLK) at the same modeled multiplicity,
plus the observed single-witness allocation ratio 912.46592/896. That ratio is
an estimate, not a guarantee for multi-link JSON page packing. At 161,073 rows,
the baseline denominator is explicitly extrapolated from Scout's 100k control,
131,665,920 bytes / 100,000 rows; no production projection size is inferred.

| Admitted rows | LG1 JSON payload MiB / estimated total MiB | LG2 payload MiB H / L64 | LG2 SQLite + fixed overhead MiB H / L64 | LG2 total MiB H / L64 | LG2 bytes/row H / L64 | Estimated delta % LG1 / H / L64 |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 0.90 / 0.92 | 0.11 / 0.19 | 0.04 / 0.06 | 0.15 / 0.25 | 155.65 / 258.05 | 68.75 / 11.14 / 18.48 |
| 10,000 | 8.99 / 9.16 | 1.13 / 1.87 | 0.23 / 0.39 | 1.36 / 2.27 | 142.13 / 237.57 | 72.81 / 10.78 / 18.01 |
| 100,000 | 89.93 / 91.58 | 11.28 / 18.75 | 2.22 / 3.79 | 13.50 / 22.54 | 141.56 / 236.34 | 72.93 / 10.75 / 17.95 |
| 161,073 | 144.85 / 147.51 | 18.17 / 30.19 | 3.48 / 6.04 | 21.65 / 36.24 | 140.96 / 235.91 | 72.93 / 10.71 / 17.92 |

The H scenario is near 141 allocated bytes/row and meets the ≤15% target but
not consistently ≤10%; L64 is near 236 bytes/row and meets ≤25% but not ≤15%.
Neither establishes production acceptance. Physical private-ledger growth,
mapping/validation throughput, cache behavior, RSS and publication time require
separate implementation measurements. Removing this public format floor does
not claim that other producer/Router performance blockers are solved.

### Original implementation tasks and acceptance plan

**Scout:** emit report/witness tables rather than public per-row JSON; retain
exact class checks/original proof; perform singleton-generation checking before
normalization; add exact manifest/DDL/count/encoding validation, deterministic
replay and explicit archived migration; normalize private originals only with
lossless reconstruction tests. Rebenchmark 1k/10k/100k/161,073 paired controls
and actual locator distributions without dropping witnesses or adverse records.

**Router:** add explicit LG2 dispatch and exact schema/generated-column/FK/type/
enum/count/policy validation; join normalized evidence lazily for audit views;
preserve captured-domain rules and current support/history separation; validate
logical continuity and migration; rebind caches; reject old/new mixed forms.
Do not add live Scout access or follow audit locators as paths/URLs.

Original planned tests (the contract-only revision did not implement them; the subsequent LG2 consumer review maps current coverage and boundaries):

1. Eligible UNKNOWN_LEGACY with reported code 0 reconstructs exact LG1 semantics.
2. Same for code 1; neither becomes observed generation.
3. Decode report/cache-kind enums and implicit authority/status precisely.
4. Reject unknown enum values, wrong storage types, lengths and noncanonical locator tokens.
5. Reject missing/mismatched LG policy, revision or encoding.
6. Validate message/provenance FK lookup, orphan rejection and all raw/text bindings.
7. Same-generation multi-link reports have one semantic row and all distinct witnesses.
8. Conflicting reports, changed witness identity/hash and alternate raw candidates reject.
9. Watermarks/coverage_history remain UNKNOWN_LEGACY with original captured witnesses.
10. Workflow lookup/closure cannot use the reported code to bridge or resolve ambiguity.
11. Qualifications gain no concrete authority and retain exact historical provenance/proof.
12. Same-operator semantics and independent-evidence exclusions remain unchanged.
13. Replay/insertion-order variations produce identical logical audits and identities.
14. LG1 JSON/nine-table encoding under LG2 rejects; explicit lossless migration succeeds.
15. A1/LG1 consumers reject LG2; LG2 accepted state rejects unapproved downgrade.
16. Paired size regression at all four scales accounts for table/index/fixed bytes,
    including hash locators, explicit long locators, multi-links and worst allowed fanout.
17. Logical audit reconstruction equals every original LG1 field, including exact locators.
18. Source/class/negative-evidence checks are unchanged; malformed required proof is not trimmed.
19. Crash/restart/migration preserves prior state/history and cannot activate partial tables.
20. Audit-only additions do not route; conflict/readiness failures still suppress decisions.

No Router runtime, Scout code, live state or service is changed by this revision.
Only after separately authorized implementations and these qualifications may
the owners consider repeating the production dry-run. Storage estimates and the
implementation-ready flags do not authorize that dry-run or deployment.


## TCLK source-linkage clarification — 2026-09-09

**DECISION B: OFFER_ID_IS_NOT_AUTHORITATIVE.** In the reviewed official tclk/1
wire schema, ACCEPT requires `ref` (offer identity) and `contract` (derived
agreement identity). `offer_id` is not an allowed ACCEPT property. A similarly
named normalized cache column or workflow key does not authorize a wire alias.
No fallback, precedence rule or automatic source rewrite is approved.

The [complete linkage/source-mapping review](ROUTER_TCLK_LINKAGE_REVIEW.md)
defines field namespaces, frame effects, conflict handling, unchanged captured
identity/qualification rules, the planned tests and reconciliation prerequisites.
It records the supplied dry run's 2,373 accept-shaped raws and 132 receipts as
separate structural populations, not independently completed failures.

The producer was correct to stop the unsupported event; its generic ref/contract
lookup is not endorsed as a complete normative mapper. Router also reconstructs
closure from raw projected text and currently ignores offer_id when ruling out
active transitions. This is a separate conservative-retention gap, not grounds
to promote that field to authoritative acceptance. Do not infer closure, discard
required evidence or publish a partial healthy cut to bypass either issue.

This is a rejection/limitation clarification only. A1-LG2 DDL, manifest encoding,
selection/classifier versions, reported-generation authority and runtime are
unchanged. A future dialect or unresolved-audit representation needs separate
explicit versioning, migration and producer/consumer approval before coding.

`TCLK_OFFER_ID_LINKAGE_BLOCKED = YES`

`SCOUT_PRODUCTION_SHAPED_LG2_PROJECTION_VALID = NO`

`ROUTER_PRODUCTION_SHAPED_HANDOFF_READY = NO`

No valid producer artifact exists from the reported dry run. Keep services stopped;
no live-state access, alias implementation or deployment is authorized by this review.


## Proposed A1-LG2-TL1 legacy TCLK audit revision

Status: design ready for coordinated review; **not implemented or production qualified**.
A1-LG2 remains frozen. The normative proposed delta is
[ROUTER_TCLK_LEGACY_RECONCILIATION_DESIGN.md](ROUTER_TCLK_LEGACY_RECONCILIATION_DESIGN.md),
with additive [contract DDL](router-tclk-legacy-tl1-schema.sql). Existing eleven
application tables remain unchanged; `legacy_tclk_records` is the twelfth.

TL1 distinguishes `AUTHENTICATED_BUT_NONCONFORMING` / `TCLK_LEGACY_NONCONFORMING`
from valid tclk/1. `offer_id` never substitutes for `ref` or `contract` and supplies
no workflow identity. AUDIT_HINT is a non-authoritative derived view, not an edge
that can establish acceptance, closure, capability or reputation.

The exact revision is `A1-LG2-TL1`; the linked delta defines required manifest
bindings for policy, frozen validator/schema and an explicitly activated immutable
historical cohort. Selection/classifier advance to `/3`; outer v2 envelope and
SQLite user_version 2 remain unchanged. Unknown or mixed revisions fail closed.

Unresolved legacy records impose complete provenance-domain retention holds before
expiry pruning, without automatic horizon/release. Hints cannot narrow those holds.
Capacity limits are 4,096 enrolled records, 100,000 held messages and 256 MiB of
canonical held dependency data, alongside unchanged global limits. Overflow blocks
publication; it does not authorize evidence loss. The linked design defines exact
accounting, enrollment, migration and positive-scoring exclusions. Reconciliation
requires a separately approved append-only successor; TL1 cannot rewrite or resolve
originals. ClosureVerifier must implement the specified no-accelerated-expiry
invariant before TL1 is usable. This proposed audit route does not reverse the
previous linkage review's rejection of an `offer_id` alias or unblock production.

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
