# Scout epoch rollover V2 Router validation — Slice 2

Status: local validation only; **disabled by default**. It never accepts,
persists, publishes, routes, signs, settles, promotes a cache entry, or
materializes profiles from a V2 candidate.

- Scout Phase 0: `713b1a4`.
- Scout Slice 1: `f65894cafa881e934bbadf437fb92779366d7b47`.
- Frozen fixture SHA-256:
  `8b3727e5f0550218a2ed9f0475b4c914ab2314e46decead0b267acd01ad11c3c`.
- Supported pure schema/revision:
  `flop-scout-router-epoch-rollover/v2` / `A1-EPOCH-V2`.

The existing V1/A1/A1-LG2 reader path remains unchanged. A manifest declaring
`A1-EPOCH-V2` is rejected as `EPOCH_V2_DISABLED` unless the local constructor
argument enables the gate.

## A1 anchor and bridge wire contract

The V2 wire carries an `accepted_anchor` and `bridge_predecessor`, each with
exactly these fields: `publication_sequence`, `content_id`, `manifest_sha256`,
`artifact_sha256`, `artifact_size`, `source_kind`, `source_id`, and
`source_cut`. `bridge_binding_sha256` is the `a1-bridge-binding` commitment of
those two descriptors. The archive must name the bridge manifest and repeat
that binding in `archive.previous_bridge_binding_sha256`.

Router does not trust the candidate's `accepted_anchor` to establish its local
anchor. It derives the anchor only from Router's already accepted continuity
state: the accepted manifest, manifest hash, and private cache binding. A
candidate must exactly match that independently derived descriptor.

For a direct transition, the complete accepted anchor and bridge descriptor are
identical. For a cumulative transition, Router reads the bridge publication
through the normal A1 projection reader using the accepted private cache as its
continuity predecessor. Pointer, manifest, artifact hash, schema, provenance,
watermark, workflow, and continuity checks all run before the bridge descriptor
is formed.

That read produces an ephemeral `VerifiedEpochBridge` receipt bound to one
active `EpochValidationSession`, the candidate-transition hash, the trusted
anchor, bridge descriptor, and bridge binding. The receipt is neither wire data
nor persisted state. It cannot be reused across sessions or after its session
closes, and a candidate-provided proof field is forbidden.

## Disabled terminal behavior

After direct/cumulative checks and pure V2 validation succeed, Router always
raises `EPOCH_V2_NOT_ACCEPTING`. This is the terminal result for Slice 2. No
archive is opened, no accepted state or cache is changed, and no profile or
routing materialization is performed.
