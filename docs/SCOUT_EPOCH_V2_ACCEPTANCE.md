# Disposable Epoch V2 acceptance (Checkpoint 4)

`scout_epoch_acceptance.accept_disposable` is an explicit offline acceptance
entry point. `enable_epoch_v2=True` is required; its default raises
`EPOCH_V2_DISABLED` before any IO. Production pointer dispatch and all V1 paths
are unchanged. This checkpoint supports the first A1-to-compact transition;
subsequent epochs require a separately reviewed continuation implementation.

## Inputs and authority

The caller configures absolute, symlink-free publication, bridge-publication,
archive, and private disposable-store roots. The store must already exist with
mode 0700 and a `disposable.json` marker containing
`{"schema":"router-disposable-epoch-store/v1"}`. Its `state.json` must be a copy
of Router's durable state, with `last_accepted_projection_v2.cache_path` pointing
to a private copied cache **inside this disposable store**. The API does not
create this authority from candidate data, import production state, or accept
an anchor/receipt supplied by its caller.

The bridge root must contain an actual pointer-v2 `current.json` naming the
exact descriptor-bound A1 manifest and artifact. Original manifest bytes are
hashed and copied, never synthesized. A different bridge pointer fails with
`EPOCH_EXACT_BRIDGE_MANIFEST_UNAVAILABLE`; missing bridge bytes fail with
`EPOCH_EXACT_BRIDGE_POINTER_UNAVAILABLE`,
`EPOCH_EXACT_BRIDGE_MANIFEST_UNAVAILABLE`, or
`EPOCH_EXACT_BRIDGE_ARTIFACT_UNAVAILABLE`, identifying the missing input. Filenames enforce transport syntax only;
hashes, normalized descriptors, durable state and ordinary A1 continuity
validation establish authority. No discovery, network fetching or filename
inference is performed.

The archive root is the explicitly configured directory containing
`manifest.json` and its members. Every member, active artifact and canonical
plan is bounded and read through held descriptors; private verified copies
isolate SQLite consumers. Original descriptors are rehashed before commit.
The complete independent reconstruction checks archive/source recovery and
all compact classifications, counts and commitments. Only after that success
is a live archive receipt created in the same session as the bridge receipt.
No externally supplied diagnostic summary can authorize acceptance.

Metadata, SQLite integrity/schema, provenance, memberships, qualifications,
coverage, workflows and continuity retain the existing Router checks. Exact
verified omissions are removed only from a private bridge comparison copy;
permanent, pinned and lifecycle records cannot receive this exception. All
other A1 extension checks run against that copy. Both accepted-state and
bridge publication chronology are checked. Profiles are fully materialized
using the existing Router adapter after validation, before durable staging;
its temporary routing index is never promoted.

## Commit and recovery

An exclusive store lock covers recovery, validation and commit. Immutable
candidate generations contain a hashed artifact, accepted-state record, and
redacted durable verification record (transition/archive/evidence commitments
and counts). Session tokens and ephemeral receipt objects are never serialized.

1. Write and fsync private candidate files and their directory.
2. Write/fsync the journal with exact before/after state hashes and file hashes;
   rename it into place and fsync the store directory.
3. Rename the candidate generation into place and fsync the store directory.
4. Write/fsync the replacement state, then rename `state.json` **last** and fsync
   the store directory. This single rename is the logical commit point.

The original accepted cache is never overwritten. Before the state rename,
all exceptions leave original state/cache bytes unchanged. A failure after the
rename may represent a completed commit: callers must recover instead of
assuming rejection or attempting rollback. As with ordinary filesystem
transactions, a power loss before the final directory fsync can retain either
durable state version; recovery recognizes only the exact journal hashes.

Under `DisposableEpochStore.locked()`, call `recover()` on restart. If the
original state hash remains, discard staging/new generation and retain the
original accepted state. If the new hash is present, verify accepted record,
cache bytes and durable commitments before loading it. Unknown state hashes,
corrupt committed files or missing inputs fail closed; recovery never infers
acceptance from a staged cache. Completed verification records remain checked
on subsequent loads after journal cleanup. No persisted ephemeral receipt is
trusted. Recovery is idempotent.

## Verification scope

Synthetic tests exercise a distinct accepted anchor, bridge and active content;
all write/fsync/rename boundaries; precommit byte preservation; deterministic
restart; profile materialization failure; bad descriptors/content; changed held
inputs; symlinks; session expiry; and corrupt/ambiguous recovery. Existing
archive, bridge-session, compact fixture, disabled-flow and V1 suites remain
applicable.

At the initial Checkpoint 4 implementation, the real 232→242→243 acceptance
rehearsal had not yet run. The prior read-only reconstruction report records an
`EPOCH_PLAN_BINDING` failure in the isolated frozen real bundle; this entry point
preserves that rejection. Exact bridge bytes and a fully consistent candidate
remain required contract inputs, without repairing or bypassing either check.

## Compact v2 fixture rehearsal (historical rejection)

The replacement `scout-epoch-v2-publication-bundle-compact-v2.json` is preserved
byte-for-byte with SHA-256
`9eb970366344756dcfdc63a148ef3535d470e45a79453dbefc1c9a372444c67b`.
The earlier fixture remains unchanged as negative evidence. The real stale
plan still raises `EPOCH_PLAN_BINDING`; the corrected plan and all five
independently reconstructed compact summaries now pass.

The exact ordinary 232→242 A1 bridge also passes from an isolated copy of
Router's durable accepted state/cache. The corrected content-243 acceptance
attempt nevertheless rejects with `UNSUPPORTED_POLICY`: its manifest contains
`selection_policy: "A1"` and the canonical string hash
`961ea6171fe18f8c510fc30a17ba90b2dc0cca62fd36a1b8749aad14fe357483`.
The retained A1 validation requires the full policy object and policy hash
`219730642f738fb6c94b21b4a722aa7e078a60ae7cf5c1e0e115dfe5e9c53c5f`.
No alias mapping, metadata substitution or validator relaxation was introduced.

No Profiles were materialized, no candidate generation was committed, and
restart loaded content 232 with identical accepted-state/cache bytes.
All protected bundle, archive, bridge and initial-state/cache inputs retained
their hashes and metadata. The rehearsal used the explicit historical clock
2026-09-22T00:00:00Z and no production access. Details, timings, counts and
before/after fingerprints are recorded in
`fixtures/router-epoch-v2-corrected-real-acceptance-audit.json`.

Successful 243 acceptance/restart and downstream real-input failure injections
remain blocked pending a coherent producer manifest. The existing synthetic
failure tests do not substitute for that real rehearsal. At that stage, Checkpoint 4 was not yet ready to commit.


## Compact v3 acceptance and restart

The v3 fixture is copied byte-for-byte with SHA-256
`c7cee620934589e1a41bb26bbb0cb1af80a49811d99290d048618c21186ba735`.
It retains the corrected plan/artifact/transition and supplies the complete A1
policy with hash `219730642f738fb6c94b21b4a722aa7e078a60ae7cf5c1e0e115dfe5e9c53c5f`.
Both older chains remain negative regression cases: the original plan fails
`EPOCH_PLAN_BINDING`, and the v2 string-policy manifest fails `UNSUPPORTED_POLICY`.

Router requires the exact normalized integer V2 checkpoint and converts it to
A1 decimal TEXT only in the internal database-validation view. Strings,
booleans, floats and different cuts reject. Proven message omissions use the
existing entity/message indexes in the private comparison copy. Transport
validation releases its duplicate parsed plan before independent reconstruction;
the descriptor-bound sidecar and omission IDs remain available. Neither policy
checks nor the existing memory limit are relaxed.

The real isolated 232→242→243 path validates the ordinary A1 bridge, archive
recovery, all five compact summaries, policy, plan, transition and active
artifact; then materializes 21,231 Profiles and atomically commits content 243.
A separate Python process recovers and verifies the accepted generation/cache.
Real input mutations cover plan tampering, archive/bridge mismatch, missing
bridge bytes and a re-committed but false coverage summary. Profile failure and
precommit interruption preserve accepted content-232 state/cache bytes; a
postcommit interruption recovers content 243. Every case compares protected
input hashes and metadata before and after. Candidate mutations affect only
new disposable copies, and all test stores are removed after recording results.

The updated path-redacted audit retains the earlier v2 rejection, exact v3
identities, counts, timings/RSS, generation identity, profile count, fresh-process
restart results and input non-mutation proofs. The rehearsal clock is explicitly
2026-09-22T00:00:00Z; no freshness bypass or production/service access is used.
The API remains disabled by default and production dispatch is unchanged.
