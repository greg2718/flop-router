> Historical pre-optimization review. Current implementation, performance and
> limitations are documented in [the performance review](ROUTER_V2_A1_PERFORMANCE_REVIEW.md).

# Router V2/A1 consumer development review

Status: **implemented development candidate, not production qualified or deployed**.
Scout's producer is implemented but not deployed. The eight compatibility inputs
are temporary synthetic publications listed in
`/private/tmp/scout-v2-a1-review-fixtures/index.json`. No live Scout database,
production publication root, live Router state, signing identity, network write,
service start/reload, Scout edit, commit or push was used.

## Files and architecture

This implementation adds `scout_projection.py`, `projection_contract.py`, the exact
nine-table `docs/router-projection-v2-schema.sql`, `test_scout_projection.py`,
`projection_test_support.py`, `tools/benchmark_projection_consumer.py`, this review
and `ROUTER_V2_A1_CONSUMER_BENCHMARK.json`. It updates `router.py`, worker fixtures in
`test_router.py` / `test_worker_readiness.py`, README and V2 implementation-status
notes. The preexisting V1 reader, V1 tests/contract and pre-A1 benchmark remain.
The worktree already contained the uncommitted input-readiness foundation; this
report describes the V2 additions, not a claim that the entire diff started here.

`ProjectionReader` subclasses the V1 descriptor acquisition primitives without
changing V1 acceptance. Worker operation uses V2 only. Publication root/ancestors
are bound with directory descriptors and `O_NOFOLLOW`; pointer/manifest/database
opens remain relative to that root. Copy and SHA-256 consume one database descriptor.
Only verified Router-private bytes reach SQLite with `mode=ro`, query-only,
trusted-schema disabled and bounded SQLite cache/row allocations. No published
WAL/SHM/journal is read. SQLite progress callbacks and Python-loop checks enforce
cooperative cancellation/deadlines; stalled kernel I/O still must return.

Pure wire validators were adapted from Scout's reviewed contract/model into
`projection_contract.py`; Router does not import or execute Scout runtime modules.
These validators confer no scoring or independent attestation authority.

## Revision, schema, policy, heartbeat and continuity

The worker requires pointer/manifest `/v2`, revision `A1`, schema
`scout-router-projection/v2`, user_version 2, selection `router-evidence-horizons/2`,
classifier `router-evidence-classes/2`, qualification policy
`router-durable-qualification/v1`, and the exact approved policy parameters/hash.
Unknown/mixed versions fail closed. `_schema` compares all nine table/index/constraint
definitions, checks integrity/FKs, metadata and counts. `_rows`, `_coverage` and
`_qualifications` validate types, one-to-one provenance/membership, location
conflicts, selected-scope coverage, history witnesses and A1 records/events.

Publication ID and database content ID are distinct. A newer heartbeat can reuse
the latest content ID/hash, but must preserve content metadata, policy, counts,
coverage and expiry. `_manifest` rejects ID/time/source-cursor rollback, same-ID
conflicts, epoch changes and incompatible policy. Freshness follows evaluated
publication time, not database age. Repeated identical publications are idempotent.

`last_accepted_projection_v2` stores both IDs, hashes, policy/revision, publication
and content times, source cut, watermarks/history, a canonical manifest checksum,
and the Router-private copy reference. Restart rehashes that copy. Missing or
corrupt state/copies degrade; they do not authorize resetting continuity.
`_extension` compares immutable audit records, protected bodies, pins, observation
times and expiry before acceptance. Expired finite unpinned rows may disappear;
permanent/unresolved rows may not. Obsolete private content copies are removed
only after the replacement checkpoint is fsynced. The retained current copy
contains the complete durable audit history.

## Qualification history versus current support

`_qualifications` checks immutable qualification IDs, first-witness uniqueness,
policy/version/source bindings and permanently retained projected proof. Event
validation checks row/JSON identities, sequence/hash chains, time ordering,
qualified targets and supersession cycles. Disk-backed temporary indexes avoid
loading the entire qualification ledger/graph into Python. `qualification_history`
streams original records plus effective validity/supersession from an already
validated private connection. INVALIDATED records retain original outcomes and IDs.

`_worker_snapshot_profiles` explicitly reads canonical projection evidence rather
than monkeypatching a V1 adapter. Template counts cover the selected scope before
DID filtering. Unsigned selected evidence stays in the audit/hash path, not positive
signed capability observations. Raw-text hashes remain distinct from Router's
composite evidence hashes. Current support is independently calculated and stored
with assessment context; historical qualification does not award support.

Local family bindings require `local-flop-agent-family`, same_operator=true and
independent_reputation=false. Controlled Bench remains audit-only and non-independent.
SHA-256 provides consistency, not attestation against a compromised same-user
producer. Local original references remain opaque producer assertions; Router does
not follow paths/URLs embedded in them or claim to independently verify private
producer authorities.

Shadow policy `flop-router-shadow/v3-v2-a1` binds canonical material evidence,
interactions, provenance assertions, substantive audit changes and current profiles.
It excludes publication/content IDs, publication clocks, private copy paths and
clock-derived recency. Unordered external record sets are canonicalized with
multiplicity preserved; ordered event chains retain their order. Existing decision
IDs remain; policy activation intentionally causes one reevaluation. The signed
`flop-routing-decision/v1` schema/hashes/signatures are unchanged.

## Readiness, limits and measurements

Cycle readiness retains READY_IDLE/READY_ACTIVE and degraded/error states. Source
readiness adds READY, WARNING_LARGE, TOO_LARGE, TOO_SLOW, MEMORY_LIMIT, STALE, INVALID,
UNSUPPORTED_POLICY and CONTINUITY_FAILURE. A failed source never routes.
Warnings identify capacity requiring operator qualification; they are not deployment
approval. Optional JSONL sources still require explicit configuration.

Defaults: **4 GiB hard artifact ceiling, 30-second acquisition/profile deadline,
512 MiB process peak-RSS guard**. Preferred size is <512 MiB; normal byte qualification
is <1 GiB. 1–4 GiB is WARNING_LARGE. No automatic increase or 8-GiB override exists.
The process high-water memory guard is conservative: recovery after exceeding it
requires restart. Bounded checks may observe a small allocation overshoot before
failing; they are not OS-enforced hard memory isolation.

[Machine-readable measurements](ROUTER_V2_A1_CONSUMER_BENCHMARK.json) contain artifact
hashes, copy/hash, SQLite integrity, schema/rows, watermarks, qualification loading,
evidence/profile loading, total time and peak RSS. These are development probes,
not cold-storage, production or scheduler qualification. A timed-out stage is a
partial measurement; absent stages were not reached. Profile timing is nested in
evidence materialization in the standalone probe, not additive.

| Synthetic messages | Artifact MiB | Total s | Peak RSS MiB | Result |
| ---: | ---: | ---: | ---: | --- |
| 1,000 subset | 3.70 | 17.05 | 65.28 | Full evidence/profile PASS within default deadline |
| 10,000 subset | 36.53 | 30.00 | 95.86 | TOO_SLOW in profiles |
| 100,000 Scout capacity fixture | 367.76 | 30.01 | 340.00 | TOO_SLOW in profiles |
| 350,000 Scout capacity fixture | 1,288.05 | 30.09 | 50.09 | TOO_SLOW during qualification validation |
| 350,000, explicit 120-s diagnostic budget | 1,288.05 | 53.13 | 512.06 | MEMORY_LIMIT in evidence loading |
| 1,000,000, concurrent-I/O stress probe | 3,679.77 | 30.18 | 49.16 | TOO_SLOW during integrity validation |

For the final 100k probe, copy/hash were 0.081/0.119 s, integrity 0.296 s,
schema/rows 5.067 s, watermarks 0.013 s, qualifications 5.037 s, evidence loading
about 1.236 s, and profile construction exhausted its remaining 18.150 s.
For the sequential 350k default-budget probe, copy/hash were 0.839/0.476 s,
integrity 5.580 s, schema/rows 18.100 s, watermarks 0.048 s, and qualifications
used the remaining 4.956 s before cancellation. These do not extrapolate from
Scout's >52-GiB warehouse size.

**Practical qualification: only the measured 1k-message subset completed end to
end within defaults.** The 10k/100k/350k cases do not qualify. This brackets a
fixture-specific limit, not a universal 1k-row or byte ceiling. Actual text,
capability mix, DID distribution and operator-specified sources matter. Further
streaming/profile optimization and production-like qualification are required;
raising byte/deadline defaults would conceal this limitation.

Reproduce using only the existing temporary capacity fixtures, with new temporary
consumer state created by the utility:

```sh
.venv/bin/python -B tools/benchmark_projection_consumer.py 100k 30 profiles
.venv/bin/python -B tools/benchmark_projection_consumer.py 350k 30 profiles
.venv/bin/python -B tools/benchmark_projection_consumer.py 100k 30 profiles 1000
.venv/bin/python -B tools/benchmark_projection_consumer.py 1m 30
```

The 1k/10k cases are newly constructed subsets in private temporary storage; the
Scout originals were not modified. Reports include scenario and subset identity.
The benchmark helper does not invoke Scout's producer or read live state.

## Validation and remaining limitations

Final full suite: **331 passed, 88 subtests passed in 48.86 seconds** using
`.venv/bin/python -m pytest -q`. The V2 test module adds 72 parametrized cases;
existing worker tests were adapted to V2 fixtures and retain their subprocess
coverage. Tracked/new-file whitespace checks, compilation, contract policy/DDL
agreement and unchanged V1 file hashes passed.

The full suite exercises V1 compatibility fixtures alongside V2 rejection,
secure acquisition, fixed-clock Scout fixtures, heartbeat restart, schema/policy,
malformed history, downgrade/audit separation, effective invalidation, operator
semantics, canonical order, state corruption, migration, size/memory/deadline and
cancellation. `test_scout_projection.py` adds parametrized consumer cases;
`test_worker_readiness.py` retains real SIGINT/SIGTERM subprocess and worker-loop
coverage with V2 publications. Large fixture validation uses a diagnostic budget;
its wire-level WARNING_LARGE success does not imply profile readiness.

All eight supplied fixture categories are exercised: normal, heartbeat reuse,
controlled same-operator Bench, duplicate downgrade, invalidation audit,
UNKNOWN_LEGACY, large warning and oversize rejection. The oversize fixture is
rejected before SQLite. Worker integration additionally proves private copy →
observations → current support → persistent history/deduplication. No fixture is
represented as production attestations or complete warehouse evidence.

The CLI smoke commands ran with a fresh temporary state directory:

```sh
.venv/bin/python router.py worker once --state-dir <TEMP> --shadow
.venv/bin/python router.py worker status --state-dir <TEMP>
```

Once exited 1 with DEGRADED_INPUT_MISSING and zero decisions, as required without
Scout configuration. Status exited 0 and reported not running. Positive compatibility
runs inject the fixtures' fixed clock in tests rather than disabling freshness.

Outstanding limitations / missing qualification:

- Full default-budget consumption of 100k and larger fixtures fails. The current
  profile representation is guarded, but it is not a streaming million-row scorer.
- `_extension` deliberately rejects unresolved-to-finite membership transitions
  (`CONTINUITY_UNVERIFIED_TERMINAL_TRANSITION`). A consumer closure-proof verifier
  for the relevant workflow protocols remains required before claiming complete
  V2 lifecycle coverage. No test claims that legitimate transition is supported.
- Local audit authority contents and historical full-group rule manifests are
  producer-private. The consumer validates available projected proof and preserves
  opaque local assertions, not independent authority/correctness attestations.
- Independent production selection parity, lifetime-reputation equivalence,
  production steady-state throughput and actual operational qualification are not
  established by these synthetic tests. Controlled Bench audit-to-scoring remains
  unimplemented. Terminal-proof support and capacity are deployment blockers.

## Migration and deployment boundary

The development worker is V2-only. Foundation f5ca717 state stays readable and
legacy HEALTHY becomes UNKNOWN_LEGACY. Existing V1 checkpoints require explicit
`--activate-scout-v2`; preserve their original fields, enforce strictly newer global
publication identity/nonregressing time and establish separate V2 coverage.
A subsequent V1 publication never triggers fallback. Corrupt state is not migration.
Producer allocation must be coordinated if its initial ID would violate that guard.

Do not load launchd or start continuous Router operation. Resolve the limitations,
review producer/consumer compatibility and pin/proof channels, qualify the intended
size/cadence/memory/disk envelope, then separately authorize foreground validation
and deployment. Settlement remains SIMULATION_ONLY/DISABLED; no wallets, network
posting, signing changes or transaction execution were introduced.

The read-only launchd check returned service-not-found for
`gui/501/com.greg.flop-router.worker`. Its plist was neither edited nor loaded.
No commit/push was performed. Stop for coordinated review.
