# Checkpoint 3: independent compact Epoch V2 evidence reconstruction

`scout_epoch_evidence.reconstruct` reconstructs all five compact evidence sets
without importing Scout. It consumes explicit paths and a transition bound to a
caller-supplied anchor. It does not accept a publication, construct profiles,
promote a cache, mutate accepted state, or enable V2. Existing V1 behavior and
the default `EPOCH_V2_DISABLED` gate are unchanged.

## Evidence and canonical forms

The frozen reference is Scout commit
`2c786bf6d0b8cf5f4a6160c725da3c72afab7c74`, including the redacted plan adapter,
legacy source recovery, active artifact builder, and compact Epoch V2 model.
The isolated 279/243 transition uses these canonical item shapes:

| Set | Item | V2 commitment domain |
| --- | --- | --- |
| Mandatory proof closure | `projection_row_id`, `raw_record_id`, `raw_text_sha256`, decimal `scout_event_id`, sorted `reasons` | `mandatory-closure` |
| Durable qualification history | `qualification_id`, parsed `record_json` | `durable-qualification-history` |
| Coverage witnesses | Exact five-column `coverage_history` row | `coverage-witnesses` |
| Permanent/pinned evidence | Same record shape as mandatory closure, with all its verified reasons | `permanent-pinned-evidence` |
| Omitted history | Same record shape, with `reasons: ["deterministic_optional_omission"]` | `omitted-history` |

Each set is sorted by canonical ASCII JSON bytes, with duplicates forbidden.
Hashes use `SHA256("flop-scout/epoch-v2/" + domain + NUL + canonical_array)`.
The plan's selected and omitted arrays independently use raw-record-ID order;
reordering either array is rejected even if its transport and logical hashes
are recomputed. The compact summary's five counts and hashes are all recomputed.
Floor entries are reconstructed from archived coverage, including exact domain,
generation, floor and empty omission ranges for the frozen first transition.

Router requires the plan union to equal every eligible archived provenance row.
Source envelopes, text hashes, observed event IDs, source cut, metadata and
compatibility links are checked independently. The legacy recovery closure,
reason counts and commitment must also agree with reconstructed evidence.

The selected message/provenance/membership sets must match the active artifact
exactly; omitted records must exist only in the verified archive/source set.
Messages and memberships equal their archived rows. Active provenance differs
only by filling the recovered legacy raw-text hash. Qualifications, qualification
events and coverage history must survive exactly. Extra entities are rejected;
this checkpoint implements the frozen message-only adapter, not an unreviewed
interaction migration or a later-epoch planner.

Mandatory reasons come from verified archive memberships, durable qualification
sources and hash-verified coverage witnesses. Producer plan reasons are compared
against these derived reasons. Optional selection is recomputed from the frozen
policy's domain-representative and recency ordering. Membership class/expiry/pin
semantics are checked, and active memberships cannot reclassify archived records.
Router's existing qualification proof validator and `ClosureVerifier` check
proof dependencies and finite lifecycle expiry. Annotation evidence links resolve
to selected evidence in the same source namespace. Open/opaque lifecycle evidence
remains retained; this checkpoint does not infer new terminal semantics.

## Read boundary and result

Every input is streamed from a held regular-file descriptor opened with a
no-symlink component walk. Hashes, exact sizes, inode and modification metadata
are checked. SQLite never reopens producer paths: it reads disposable private
snapshots of the verified bytes using `mode=ro`, `immutable=1`, `query_only`,
`trusted_schema=OFF`, integrity checks and a deadline progress handler. Scratch
snapshots are deleted on return or error and are never promoted to a Router cache.
Inputs are rehashed and checked for changes before returning evidence facts.

Limits include 1 GiB per SQLite member, 16 MiB per plan/recovery JSON, 50,000
records per evidence table, 200,000 cache links, 64 KiB cells, and a default
180-second reconstruction deadline. The closed projection schema and source
object/column set, source DDL commitment and source metadata are checked.

The result is a frozen `EvidenceSummary` containing immutable tuples of counts,
commitments and descriptor identities. Its repr contains no data; it cannot be
pickled. It contains neither paths nor text and is explicitly an audit result,
**not a receipt or acceptance capability**. There is no API that consumes it as
authority, so no cross-session receipt is introduced. A late failed compact-summary
or plan binding check may attach the same redacted diagnostic facts to the error;
they do not turn a rejected bundle into a validated one.

## Isolated 279/243 audit

The reproducible read-only CLI is `scout_epoch_evidence_audit.py`. All roots,
the comparison anchor, and the expected pointer SHA must be provided explicitly.
It checks pointer, manifest and transition bindings, runs reconstruction, and
prints a redacted JSON report. It exits nonzero on rejection and writes no
report file or Router state itself. The supplied comparison anchor is an offline
reference descriptor; this audit does not establish production accepted state
or issue a cumulative bridge capability.

The recorded audit is
[`fixtures/router-epoch-v2-279-243-reconstruction.json`](fixtures/router-epoch-v2-279-243-reconstruction.json).
It reconstructs **49,808 eligible / 43,840 selected / 5,968 omitted** records.
All five compact count/hash summaries match exactly:

- mandatory closure: **10,427**;
- durable qualifications: **7,330**;
- coverage witnesses: **6**;
- permanent/pinned evidence: **9,922**;
- omitted history: **5,968**.

The unchanged frozen publication is nevertheless **rejected with
`EPOCH_PLAN_BINDING`**. Its descriptor-bound canonical plan carries the older
retained-floor hash `a8fac3dc217435268f6b5ca92fc9382cf954c15e7907183d1d1022cd85fb973f`
and omission hash `2d8d9e5ce315670fd312a252c62564751cc9be9c17bf3823ca26cd2e973db925`.
The compact transition instead requires
`b8ebd4d0819ea6ef1d6ee56b9fd97752483e8d8aea318573847cd02e97f8494e` and
`9ddae34ecf2fbe403f4be4cd0ea6d48b5c915a30442e8b6f73138d09b0855b6a` respectively.
The audit records exact timing, peak RSS and before/after fingerprints for all
nine bundle/archive inputs. No fixture was repaired or acceptance check bypassed.

## Tests

Synthetic tests construct independent SQLite/source/archive evidence and then
mutate/rebind descriptors so malformed content cannot pass merely because its
outer hashes were updated. Coverage includes every compact count/hash, plan
union/order/classification, missing or extra artifact/provenance records, raw
hash/event mismatches, qualification/coverage/pin/permanence/lifecycle removal,
lifecycle dependencies, duplicate source records, bounds, wrong descriptors,
symlinks, input changes, immutable redaction, and prohibition of reader/cache
paths. Existing frozen compact and obsolete-V2 rejection tests remain in place.
