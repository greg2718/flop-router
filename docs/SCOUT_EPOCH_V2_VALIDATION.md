# Scout epoch rollover V2 Router validation — Slice 2

Status: pure parser/validator only; **disabled by default**.  It neither opens
an archive nor accepts, persists, publishes, routes, signs, or settles a V2
candidate.

- Scout Phase 0: `713b1a4`.
- Scout Slice 1: `f65894cafa881e934bbadf437fb92779366d7b47`.
- Frozen fixture SHA-256:
  `7d9a99af81370b2fcea69b85dc3b977d733a11cb8bdabc92e121473fce76f217`.
- Supported pure schema/revision:
  `flop-scout-router-epoch-rollover/v2` / `A1-EPOCH-V2`.

The existing V1/A1/A1-LG2 reader path remains unchanged.  A manifest declaring
`A1-EPOCH-V2` is rejected as `EPOCH_V2_DISABLED` unless the local constructor
argument enables the pure gate.  Even enabled, Slice 2 validates only supplied
in-memory transition data and raises `EPOCH_V2_NOT_ACCEPTING` before archive
acquisition or accepted-state mutation.
