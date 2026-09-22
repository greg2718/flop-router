# Scout compact Epoch V2 pure Router validation

Status: **disabled by default**, with no V2 acceptance, profile construction,
cache promotion, or accepted-state mutation. V1/A1/A1-LG2 behavior is unchanged.

The independent Router implementation follows Scout's frozen model at
`2c786bf6d0b8cf5f4a6160c725da3c72afab7c74`. It imports no Scout code.
The publication fixture is `docs/fixtures/scout-epoch-v2-publication-bundle-v1.json`,
SHA-256 `d3dca144bacaad1f47a1b0ad5a7ee4ec2c35eaa60c946bcc282d5b5b607bb8a4`.
All seven transition vectors and four plan vectors execute their declared
outcomes against independently constructed synthetic compact bundles. The
fixture's compact-candidate hash/count summary is reference metadata, not a
bundled database or plan; these tests do not claim to validate production bytes.
The older embedded-array fixture remains only as a rejection regression.

## Pure wire validation

`scout_epoch_v2_validator.py` validates `flop-scout-router-epoch-rollover/v2`
with revision `A1-EPOCH-V2`. Ordinary JSON parsing remains bounded to 64 KiB,
16 levels, 256 array items, 64 object fields, 4096 ASCII bytes per string, and
signed 63-bit magnitude integers. Duplicate keys, floats and non-finite values
are rejected. Canonical commitments use sorted keys, compact separators and
`SHA256("flop-scout/epoch-v2/" + domain + NUL + canonical_json)`.

The exact normalized `accepted_anchor` and `bridge_predecessor` descriptors
contain `publication_sequence`, `content_id`, `manifest_sha256`,
`artifact_sha256`, `artifact_size`, `source_kind`, `source_id`, and `source_cut`.
The `a1-bridge-binding` domain commits both complete descriptors. First-transition
source descriptor and cut-evidence commitments derive from that bridge authority.
The archive descriptor uses the **V2 `archive-descriptor` domain**, omitting only
its own `archive_commitment_sha256` field; the archive manifest has its separate
existing `flop-scout/epoch-archive-manifest/v1` commitment domain.

Retained-floor declarations contain ordered floor entries plus count/hash pairs
for mandatory closure, qualification history, coverage witnesses, pinned evidence
and omitted history. Embedded sets are rejected. `bounded_commitment` and
`compact_retained_floor` support pure recomputation from sorted unique sets.
These summaries do not themselves prove the underlying database evidence.

The separately parsed redacted active-set plan permits up to 16 MiB of transport
bytes and 50,000 selected plus omitted records. It binds the candidate source,
archive, recovery, floor, omission and capacity fields. The transport hash and
logical `active-set-plan` commitment are checked independently. Unknown row
fields, duplicate raw record IDs and count mismatches are rejected.

Epoch IDs bind the frozen identity view, including active-artifact identity and
the logical plan/recovery commitments. Active-artifact locators and plan transport
fields are excluded from that view but included in the complete transition
commitment. Archive identity includes its descriptor commitment. The complete
transition omits only its own `transition_sha256` commitment, preventing a
self-hash cycle.

`validate_v2_manifest` checks the exact content-only manifest shape, active
artifact equality and transition-sidecar descriptor. `validate_transition_bytes`
and `validate_active_set_plan_bytes` validate already-held sidecar bytes; they
perform no acquisition or locator resolution. This is pure contract parity,
not full database or publication acceptance.

## Local bridge and archive capabilities

Router derives its trusted anchor from already accepted continuity state, never
from the candidate. The explicit local bridge-validation API retains the normal
A1 pointer, artifact, schema, provenance, watermark, workflow and continuity checks.
Its `VerifiedEpochBridge` remains bound to the active `EpochValidationSession`,
candidate transition hash, complete descriptors and binding. Receipts are neither
wire data nor serializable state and cannot cross sessions or survive closure.

Archive validation derives the expected binding from the live receipt's anchor
and bridge. There is no fixed real-publication bridge hash. The archive must match
both descriptors and the derived binding. Its canonical checkpoint has exactly
`source_id`, `source_epoch`, and `source_cut`; epoch and cut match the bridge,
while the archive source ID may differ.

Existing containment, regular-file, `O_NOFOLLOW`, hash/size, source-evidence,
provenance, recovery and session-bound `VerifiedEpochArchive` checks remain.
Legacy archive recovery remains scoped to the existing recovery evidence contract;
this change does not generalize its real-cohort record/closure checks.

## Disabled reader behavior

The pointer remains `flop-scout-router-current/v2` with exactly `schema`,
`manifest`, `manifest_sha256`, and `published_at`. Manifest revision dispatch
returns `EPOCH_V2_DISABLED` by default without A1 fallback. Even with the local
constructor flag enabled, acquisition stops at `EPOCH_V2_NOT_ACCEPTING`;
obsolete embedded `epoch_rollover` manifests are rejected. Pure validation is
invoked explicitly with held objects/bytes, not through an enabled acceptance path.
The existing explicit direct/cumulative local validation helper also terminates
at `EPOCH_V2_NOT_ACCEPTING` after successful checks.
