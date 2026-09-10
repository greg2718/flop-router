# V2/A1 readiness envelope follow-up

This extends the existing uncommitted performance candidate; it does not change
the A1 producer contract, wire schema, qualification policy, activation rules or
resource limits. The preflight branch was `fix/worker-input-readiness`, HEAD
`f5ca717`. The worktree matched the preceding reviewed session's candidate.
No unexpected user changes were found. No Scout files or live data were used.

## Current profiling and changes

The historical 17.05-second 1k result belongs to the eager candidate, not the
starting point of this follow-up. Its measured repeated-assessment,
normalization, N+1 query and materialization costs are preserved in
[the first performance review](ROUTER_V2_A1_PERFORMANCE_REVIEW.md).

A fresh pre-edit 1k cProfile/tracemalloc/SQL-trace probe of the already optimized
candidate measured 0.879 seconds and 1,298,009 calls. Summary building took
0.510 seconds; semantic decisions 0.209; per-rule relevance filtering 0.128;
row validation 0.182; qualification validation 0.166. Nested timings overlap.
The trace recorded 181,400 generator calls inside the relevance filter.
The new necessary-first-word rule index removes that all-pattern scan per text.
Unrestricted regex rules are always tested; contextual rules and exact matching
still determine relevance. Rule order is restored before derivation. This is
bounded indexing of fixed Router rules, not trust in producer capability labels.

The index does not alter semantic outputs or require a policy-version change.
Every existing pattern is compared against the complete evaluator in plain,
behavioral and negative contexts. Fixture parity now compares routed results
as well as complete profiles, using two tasks across six compatible fixtures.
The separate controlled-proof tests cover intentional audit-to-controlled-score
behavior without independent reputation credit.

Source `readiness_phase` now records preparation progress:

1. `CONTENT_VALIDATED`: secure acquisition, schema/policy, qualifications,
   watermarks and continuity passed (or their bound immutable cache was reused).
2. `INDEX_READY`: the private compact routing index has been built or verified.
3. `ROUTING_READY`: all enabled sources and final bounded state/deadline/memory
   checks passed in the worker.

`ACQUIRING` is the initial phase. This is a last-completed-step field, not a
replacement for the cycle's READY_IDLE/READY_ACTIVE/degraded/ERROR status. An
error can retain an earlier completed phase without authorizing routing. Source
fields reset each cycle, so a prior ROUTING_READY phase cannot mask a new failure.
Final state timing now includes the semantic evidence fingerprint. Stage metrics
also report high-water RSS increases; these are not live heap deltas, and nested
stage deltas overlap.

## Retained architecture and safety boundaries

`ProjectionReader` validates a descriptor-bound publication, hashes/copies the
same database descriptor and opens SQLite only on Router-private bytes.
`integrity_check` remains mandatory for newly accepted content. Validation,
provenance and qualification rows are streamed; qualification events use one
ordered join. SQL groups duplicate identities and aggregates compact support.
`projection_routing.Profiles` loads candidate details on demand. Full text is
streamed for independent Router semantics, not kept in a global Python list.
The current implementation builds task-independent bounded evidence summaries;
it does not rely on producer retention labels as capability authority.

Same-content heartbeat reuse validates the new pointer/manifest and continuity.
In-process unchanged private-file identity/stat tokens skip repeat hashing;
restart rehashes the source and derived index before reusing bound validation.
Corrupt/mismatched cache files fail closed; they do not trigger a silent reset of
the accepted continuity checkpoint. Recovery from checkpoint/cache corruption
requires preserving history and restoring or explicitly rebuilding trusted
private state. No automatic checkpoint reset/recovery command was introduced.

Cancellation tests retain prior accepted files/state and clean incomplete
artifacts. The new phase tests reject ROUTING_READY on index cancellation or a
missing configured optional source. The existing tests cover signal handling,
copy/hash/SQLite interruption, cache corruption, restart, history and decision
deduplication. Neither cache reuse nor phase reporting weakens these guards.

Authoritative Kibble and TCLK closure, and explicitly linked original Bench
proofs, remain as implemented in the preceding pass. Missing/conflicting or
cross-source/generation proofs cannot authorize closure. Unknown generic
terminal grammars still remain unresolved; no prose inference was added.
Bench originals can supply controlled capability validation, with permanent
retention and no independent reputation. The supplied opaque Bench audit fixture
alone is not sufficient to invent capability linkage or score.

## Measurement interpretation and deployment boundary

`ROUTER_V2_A1_ENVELOPE_BENCHMARK.json` contains the follow-up measurements,
implementation fingerprints, individual stages, query plans, table row counts,
warm paths and memory results. Scale counts are **messages**; 100k includes about
355k relational rows. The full Scout warehouse size is not a projection estimate.

Cold means a fresh Router-private cache; it does not guarantee cold operating
system disk caches. These are single-host observations, not latency percentiles.
The 100k follow-up runs fit 30 seconds but do not establish a new end-to-end
speedup over the preceding pass. The 10/20-second targets are not met. The largest
tested passing shape remains approximately 100k messages / 368 MiB. This is a
measured ceiling for this fixture mix, not a production SLA or a license to trim
pinned, negative or durable evidence. Larger evidence mixes and per-task routing
throughput require qualification. The 4 GiB byte cap is not the operating ceiling.

Publication/policy parsing remains included in manifest timing; database row
validation includes its message, interaction, provenance and membership
subtimings. Index construction includes capability and aggregate-profile
subtimings. Row counts are logical scan counts, not SQLite page reads. The
retained tracemalloc probes report live allocation blocks, not total allocated
Python objects. No missing measurement is presented as a zero-cost operation.

No launchd start/reload, deployment, signing-key access, network write, settlement,
Scout edit, commit or push was performed. Deployment remains blocked pending
coordinated review, producer/proof compatibility, disk/task-throughput validation
and adequate changed-content readiness headroom.

## Follow-up results

| Messages | Artifact MiB | Copy s | SHA s | Integrity s | Schema / watermarks s | Qualifications s | Compact index + state s | Total s | Peak RSS MiB |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100k | 367.76 | 0.502 | 0.127 | 1.104 | 4.859 / 0.014 | 4.876 | 16.278 | 27.769 | 78.45 |
| 10k | 36.53 | 0.008 | 0.013 | 0.030 | 0.472 / 0.001 | 0.421 | 1.480 | 2.427 | 65.53 |
| 1k | 3.70 | 0.001 | 0.001 | 0.002 | 0.048 / 0.000 | 0.043 | 0.161 | 0.259 | 46.78 |
| 1m | 3679.77 | 5.828 | 1.286 | 22.898 | — / — | — | — | 30.157 | 32.05 |
| 350k | 1288.05 | 1.575 | 0.450 | 8.022 | 16.854 / 0.050 | 19.079 | 59.970 | 106.024 | 78.77 |

350k used a diagnostic 180-second budget and is outside normal qualification.
1M timed out during integrity validation; its integrity timing and memory are
partial measurements, not successful validation. All other rows completed.
100k changed-content acquisition also completed: **26.990 seconds**, including
continuity and final bounded state construction. Its source contains 100k
messages, 50k qualifications, 5k events, 100k provenance and membership rows.

100k warm heartbeat: **0.025 seconds** steady-state; **0.278 seconds** after
restart with private hashes checked again. These include bounded final state.
The benchmark identifies each implementation hash; the 100k run preceded the
final phase-label adjustment but includes state assembly.

The pre-edit follow-up profiler details are retained in
`ROUTER_V2_FOLLOWUP_PROFILE.json`. Full validation and temporary CLI smoke results
are reported below and in `ROUTER_V2_SMOKE.json`.

Final full suite: **398 tests and 88 subtests passed in 52.14 seconds**, no skips.
The four added tests cover all-pattern semantic parity, cold/cached preparation
phases, cancellation before index completion and all-source readiness gating.
The existing six profile-parity cases also compare selected routing results.
`git diff --check` passed. Temporary `worker once` and `worker status` from `/`
passed for missing configuration and a valid synthetic publication; neither
case emitted a decision or performed a network write/private-key access.
Read-only `launchctl print` confirmed no loaded worker service in `gui:501`.
The candidate is stopped for coordinated review, with no deployment approval.
