# V2/A1 consumer performance and closure review

Follow-up measurements and explicit preparation phases are recorded in
[the readiness envelope follow-up](ROUTER_V2_A1_READINESS_ENVELOPE.md).

Status: implementation candidate for coordinated review; **not deployment approval**.
Measured on 2026-09-08 using supplied synthetic Scout publications and newly
constructed temporary derivatives only. No live Scout database, live Router
state, signing identity, producer runtime, or settlement execution was accessed.
The default limits remain **4 GiB, 30 seconds, 512 MiB RSS**.

## Root performance bottlenecks

The pre-change 1,000-message candidate took approximately 17.05 seconds without
instrumentation. A separate cProfile/tracemalloc/SQL-trace run took 33.45 seconds,
33.02 in profile construction. It performed 54,000 evidence assessments and
384,600 text normalizations: the same observation was assessed across the whole
capability rule set, then assessed again for quality/risk. The instrumented run
made approximately 18.4 million Python calls. Repeated regex normalization and
capability scans explain the 1k-to-10k deadline failure without requiring a
pairwise duplicate algorithm.

SQL tracing also found 1,000 sender lookups, 550 proof-text lookups, 500 proof
source joins, 100 qualification lookups, and 50 existence checks in the small
run. The old profile builder retained full observation objects and rescanned
interactions across profiles. Those costs grew with evidence and candidate count.

An intermediate streaming query still selected a poor join plan over duplicate
groups. `EXPLAIN QUERY PLAN` exposed it; the corrected left join uses an automatic
covering index on sender/room/generation/template rather than repeated group
scans. Query plans are retained in the benchmark artifact.

The instrumented optimized 1k run took approximately 0.79 seconds overall, 0.46
in summary construction. Text normalization calls fell to 9,502. The SQL count
rose from 3,327 to 5,773 because compact index inserts and indexed per-capability
aggregates replace Python materialization; reducing SQL statement count itself
is not the optimization. Proof/sender lookups of the original full-text rows were
removed from the main per-row path. Some bounded, indexed qualification-reference
lookups remain.

Tracemalloc reports **live allocation blocks**, not cumulative Python objects
created: 7,390 before and 14,047 after, including profiler/trace metadata. Traced
profile-stage peak allocation fell from 6,684,017 to 3,763,136 bytes; live traced
bytes at that boundary fell from 3,664,498 to 1,646,370. The largest retained
application allocation in the optimized trace was approximately 306 KiB in
summary construction. Full stage/allocation/SQL evidence is in
`ROUTER_V2_BASELINE_PROFILE.json` and `ROUTER_V2_OPTIMIZED_PROFILE.json`.

## Scaling, SQL, text, and duplicate changes

`ProjectionReader._rows`, `_qualifications`, and `qualification_history` stream
ordered rows. Joins bind source provenance and qualification proof references;
the qualification history iterator joins events once, rather than replaying the
event log for each profile. Scratch SQLite tables validate audit uniqueness and
supersession without unbounded Python sets. `_extension` compares prior and new
verified private copies with SQL joins, including append-only audit, unchanged
first-observation times, pin preservation, and proven finite expiry transitions.

`projection_routing.build` creates a separate Router-private SQLite summary
index. It streams full text only for Router's required semantic derivation,
groups duplicate/template identities in SQL, and retains bounded representative
evidence plus counts. Producer classification/retention labels do not confer
capability support. `semantic_decisions` derives content semantics once and
rebinds provenance to each observation; small bounded caches avoid repeated
normalization/regex work. Large texts bypass the retained text cache.

Duplicate grouping is by stable template and sender/room/generation identity;
there is no pairwise duplicate comparison. Duplicate/current-support changes
remain separate from durable qualification history. Compact SQL aggregates
preserve support, contradiction, risk, peer and operator semantics. A manual
comparison of foundation rule functions against fixture text made 11,525 checks
with no differences; automated fixture/profile parity tests are also included.

`Profiles` lazily constructs one candidate at a time from its index. `Router.route`
retains only the requested top candidates. Peer counts use SQL counts, not large
Python sets. `current_support` in status is a deterministic sample of at most
1,000 DIDs with capabilities; `current_support_scope` gives total count,
completeness, limit, and full index path. A profile's explanatory direct-edge
list is limited to 100 descriptions, while all edge counts and semantic input
hashes remain complete. Neither sampling rule discards routing evidence.

Indexes and scratch tables are exclusively Router-owned; Scout artifacts and
the verified source copy remain read-only. The derived index also stores compact
per-observation metadata. At 100k messages it occupies about 236 MiB in addition
to the 368 MiB private source copy. Dropped staging tables leave reusable SQLite
free pages; acquisition does not incur a VACUUM. Changed-content acquisition
temporarily needs prior and new source/index files plus scratch space. Disk
capacity must be qualified separately from the source artifact ceiling.

## Cache and heartbeat design

`ProjectionReader.read` binds persistent validation results to immutable content
ID, database hash, manifest schema/policy/watermarks, and validator version.
`verify_private` checks exact private cache location, filename binding, owner,
permissions, regular-file type, size and SHA-256. Cache metadata is checksummed;
this detects corruption, not malicious replacement by the same trusted user.
The derived index is independently hash-bound and versioned, including optional
evidence/proof context. Old state without validation/index metadata is fully
validated and rebuilt.

Every heartbeat still validates pointer/manifest identity, freshness, selection
expiry, continuity and bindings. On first reuse or process restart, private
artifact hashes are verified. During one process only, unchanged descriptor
identity/size/mtime/ctime/mode tokens allow skipping repeat hashing. Modified or
missing private files fail closed. Changed content always undergoes full
validation; full `integrity_check` has **not** been replaced by `quick_check`.

Only an entirely READY cycle advances accepted snapshot/cache state. Cancelled
or degraded cycles preserve the last accepted checkpoint. Obsolete source/index
files are removed from Router's private cache only after acceptance. Publication
metadata, processing/import timestamps and paths are excluded from semantic
decision identity; authoritative evidence timestamps and all substantive inputs
remain included. Deduplication happens before candidate scoring. The hour-later
restart test asserts routing is not called for identical evidence.

## Capacity results

Scale labels below count **messages**, not all relational rows. The 100k model
also contains 100k provenance rows, 100k membership rows, 50k qualifications and
5k events (about 355k rows total). These are synthetic shapes, not estimates of
the live Router projection. Each capacity report records implementation hashes.

| Messages | Artifact MiB | Copy s | SHA s | Integrity s | Schema s | Watermarks s | Qualifications s | Derivation/index s | Total s | Peak RSS MiB |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10k | 36.53 | 0.008 | 0.011 | 0.026 | 0.440 | 0.001 | 0.380 | 1.486 | 2.355 | 63.47 |
| 100k | 367.76 | 0.199 | 0.116 | 0.291 | 4.498 | 0.013 | 4.229 | 15.393 | 24.747 | 82.39 |
| 350k, diagnostic 180s budget | 1,288.05 | 0.845 | 0.410 | 5.985 | 15.680 | 0.047 | 15.685 | 54.403 | 93.080 | 82.94 |
| 1M, default 30s budget | 3,679.77 | 2.476 | 1.181 | 26.341, interrupted | — | — | — | — | 30.132, timeout | 50.16 |

The 100k total includes final bounded routing-state construction (0.0235s).
Derivation/index timing contains capability derivation (13.674s) and compact
profile-index construction (1.599s); nested stage timings must not be added
together. The 10k and 350k runs predate the final state-assembly instrumentation
and report through index readiness, not final worker-state serialization.

A changed-content 100k publication, adding a retained interaction/provenance
record, completed in **25.936s** including **0.547s** prior/new continuity
comparison and **0.0232s** final state construction. This measures changed-content
validation, not a claim that the synthetic relationship is independent trust.

100k heartbeat acquisition including bounded state construction measured:

| Reuse case | Seconds |
|---|---:|
| First heartbeat, private hashes checked | 0.2533 |
| Steady heartbeat, unchanged in-process file tokens | 0.0230 |
| Restart heartbeat, private hashes checked again | 0.2475 |

An earlier 1M diagnostic with a 300s budget timed out during capability
derivation at 300.041s and 71.14 MiB RSS. It predates the final qualification-join
optimization and is retained as historical evidence, not a final 1M throughput
result. The final default-budget 1M run still fails during integrity validation.
Neither run establishes full 1M memory qualification.

Stage-specific RSS, row counts, query plans, timings and implementation hashes
are in `ROUTER_V2_A1_PERFORMANCE_BENCHMARK.json`. RSS is the process high-water
mark, not an isolated allocation delta; warm runs inherit the cold high-water
mark. Copy and SHA work use one bounded buffer/open source descriptor. Times are
single-machine observations subject to filesystem cache and workload variation.

**Practical envelope:** up to the measured 100k-message/368-MiB synthetic shape
fits the unchanged 30s deadline with roughly 4–5 seconds of margin. This misses
the preferred 10s/acceptable 20s targets and does not establish comfortable
production headroom. 350k is explicitly outside normal qualification despite
its successful memory result; 1M is unqualified. Do not truncate mandatory,
negative, pinned or durable evidence to fit this envelope. A different evidence
mix, cold storage, optional stores and many routing tasks require qualification.
Per-task scoring at these large scales was not separately benchmarked.

## Closure verifier

`projection_workflows.ClosureVerifier` reconstructs only structured,
authenticated records with exact source/room/generation/workflow linkage. Kibble
requires a unique authoritative JOB root, an explicit linked RESULT/DELIVER and
issuer ACCEPT, without conflicting/rejected proof. Closure expiry uses trusted
first-observed timestamps and the contract horizon, not prose or claimed clock
text. TCLK permits proven elapsed offer deadlines only when there is no linked
active transition. No accept/lock/reveal/refund or settlement operation is added.

Missing, conflicting, unauthenticated, cross-generation/source or ambiguous
root proofs cannot authorize finite retention. `UNKNOWN_LEGACY` is kept as a
distinct domain. Unknown generic workflow grammars remain unresolved: A1
provides no general authoritative terminal-message schema. This is an explicit
remaining interoperability limitation, not an inferred closure heuristic.

Bench proof linkage records CLOSED/REJECTED outcomes, but retains Bench evidence
permanently. Local proof originals do not export an authoritative first-observed
closure time, so `closed_at` is null and cannot justify expiry.

## Controlled Bench scoring

`projection_bench.proofs_from_records` validates the optional explicit
`--bench-proof-store` (`router-bench-proof/v1` JSONL). Each envelope contains an
exact LOCAL_ARTIFACT reference and its original request/result body, with
canonical SHA-256 binding. The worker never resolves artifact paths or URLs
found inside evidence. Configured missing/malformed proof files degrade
readiness; an unconfigured proof source is disabled.

`linked_outcomes`/`controlled_results` require linked original request/result,
matching request hash and target, routing/task linkage, recognized local
requester and Bench identity, explicit capability, consistent correctness,
deterministic reproducibility, and `same_operator=true` /
`independent_reputation=false`. Invalidated/superseded historical assertions do
not score. Duplicate originals collapse; FAIL prevents a positive result.
PASS enters existing controlled validation policy, never independent peer or
operator-group reputation. Historical qualification does not invent current
observational support. The downgrade test preserves SIGNAL_ONLY observations
while keeping a separately identified controlled validation.

The supplied controlled Bench fixture lacks explicit capability linkage and
therefore remains audit-only. An opaque qualification assertion alone is not
converted to confidence. Producer hashes establish consistency, not independent
attestation against a compromised same-user producer or proof-store writer.

## Cancellation, readiness and compatibility

Cancellation checks and SQLite progress handlers cover acquisition, copy/hash,
integrity/schema/qualification validation, workflow reconstruction, summary
construction and routing. Pending input/summary files and attached scratch
databases are cleaned. Prior accepted files/checkpoints survive interruption;
no post-cancellation decision is emitted. Source status is reset each cycle,
so failures do not inherit stale valid/cache-success fields. Final index/state
readiness and memory/deadline checks precede routing. READY_IDLE/READY_ACTIVE
remain distinct from degraded missing/unreadable/invalid inputs and ERROR.

State created by f5ca717 remains readable; cache fields are additive. The worker
policy version advances to `flop-router-shadow/v4-v2-a1-stream`, so reevaluation
across that policy change is intentional; existing history/decision IDs remain
intact. Signed routing-decision schema/hashes/signatures are unchanged.
Settlement remains SIMULATION_ONLY/DISABLED, with no network write path added.

## Tests and review boundary

Final full suite: **394 passed, 88 subtests passed in 43.77s**; no skips.
This is 63 added cases beyond the supplied 331-test candidate. `git diff --check`
passed. Read-only `launchctl print` reported that the worker service could not
be found in `gui:501`; no launchd mutation was performed. New coverage
in `test_projection_performance.py` includes fixture profile parity, semantic
prefilter parity, streaming qualification history, modified private source/index
rejection, corrupt validation-cache metadata, proof-store recovery, optional
evidence merge parity, cancellation cleanup, closure proof/restart cases,
controlled PASS/FAIL/duplicate/superseded/invalidated/downgrade cases,
hour-later restart deduplication, cache retention and bounded status state.
The existing suite continues to exercise all eight supplied Scout fixture
categories, descriptor/path attacks, continuity, old state, signals and worker
failure persistence.

Capacity tests are opt-in separate processes to avoid making every unit-test
invocation perform gigabytes of I/O:

```sh
.venv/bin/python tools/benchmark_projection_consumer.py 100k 30 profiles 10000
.venv/bin/python tools/benchmark_projection_consumer.py 100k 30 profiles --changed
.venv/bin/python tools/benchmark_projection_consumer.py 350k 180 profiles
.venv/bin/python tools/benchmark_projection_consumer.py 1m 30 profiles
```

The 180s value is a diagnostic argument only, not a worker default change.
The script requires the named supplied `/private/tmp/scout-v2-a1-capacity-*`
fixtures and never edits them. Temporary CLI `worker once`/`status` smoke tests
were run from `/`, both without configuration (degraded, zero decisions) and
with a temporary valid publication (READY_IDLE, zero decisions). Exact commands
and outputs are retained in `ROUTER_V2_SMOKE.json`.

Deployment remains blocked pending coordinated implementation/security review,
actual producer/proof linkage compatibility, disk and task-throughput
qualification, and an evidence volume/mix with adequate cold-acquisition
headroom. The 350k/1M time targets are not achieved. No service was loaded,
started or reloaded, and no commit or push was performed.
