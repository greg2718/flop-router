# Router A1-LG2 consumer review

Development candidate, 2026-09-09. Implemented against the finalized Scout LG2
contract and nine supplied synthetic compatibility publications. No deployment
approval, live Scout/Router state access, signing-identity access, Scout edit,
service start/reload, commit or push occurred.

Preflight branch: `fix/worker-input-readiness`; HEAD: `f5ca717`. The existing
uncommitted candidate matched the preceding session's file list and baseline.
Existing work was preserved; the baseline commit was not amended.

## Files changed in this task

- `scout_projection.py`: explicit revision dispatch, schema, cache/continuity and archival guards.
- `projection_legacy.py`: new bounded normalized audit validator and read-only audit view.
- `projection_routing.py`: derived-cache binding to revision/policy/encoding.
- `router.py`: explicit LG2 migration option and persisted bindings/history/diagnostics.
- `test_projection_legacy.py`: LG2 compatibility, malformed, semantic and migration tests.
- `tools/benchmark_router_lg2.py`: isolated fresh-process compatibility measurements.
- `README.md` and `SCOUT_ROUTER_SNAPSHOT_V2.md`: current status and migration interface.
- This review, `ROUTER_A1_LG2_BENCHMARK.json`, and `ROUTER_A1_LG2_SMOKE.json`.

The normative LG2 SQL is unchanged. The other preexisting uncommitted modules,
tests and review artifacts remain part of the surrounding candidate.

## Dispatch and schema

`ProjectionReader._manifest` accepts exactly A1 and A1-LG2 as active publications.
LG2 requires the complete exact `router-legacy-generation-authority/v1` policy
and `router-legacy-generation-storage/v2` encoding. A1-LG1 is not an active reader
fallback: it can only be an explicitly supplied historical migration checkpoint.
Missing bindings, unknown revisions and mixed field sets reject before consumption.

`_schema` compares the complete normative sqlite_master definitions and LG2
`table_xinfo`, foreign-key and index metadata. CHECK constraints, WITHOUT ROWID
keys, virtual generated message_id and the witness FK cannot drift. All row counts,
full integrity checking and foreign-key consistency remain required. The original
eight-key provenance annotation validator rejects any LG1 JSON slot under LG2,
even null. SQLite is query-only with foreign keys enabled on the verified private
copy; acquisition/descriptor isolation and companion-file exclusions are unchanged.

## Reports, witnesses and audit visibility

`projection_legacy.validate` performs the required bulk logical report/message/
provenance anti-join, validates binary references and exact integer codes, then
streams reports and witnesses through indexed joins. Reports remain the outer
scan to avoid repeated full report scans through the generated message ID.
Python retains at most one report's 256 witnesses. No global report/witness graph
or persisted expanded LG JSON is built. Existing bounded A1 annotations are parsed;
a bounded logical reconstruction checks the unchanged 64-KiB audit limit.

Reported codes 0/1 decode to secondary strings "0"/"1". Cache kinds are exactly
1=evidence_records, 2=tclk_frames, 3=kibble_events. Unknown values fail closed.
Each affected message has one semantic report and all distinct witnesses, including
at least one evidence_records witness. Orphans, conflicting decoded locator/hash
identities, missing required witnesses, noncanonical tokens and bounds violations
reject. Empty locator storage reversibly means the exact lower-hex witness hash;
other locators remain exact opaque strings and are never followed.

`projection_legacy.audit_view(conn, message_id, check)` is a read-only internal API
for an already validated private connection. It reconstructs every LG1 audit field,
including captured/reported distinction, fixed authority/status/class, raw reference,
exact text hash, sorted witness source/hash/locator, policy, encoding and revision.
It returns no raw message body. It does not fetch Scout private originals.

Source/cycle/status diagnostics include `legacy_generation_audit`: report/witness
counts, reported-0/1 counts, average/max multiplicity, invalid-enum/conflict counts
and policy/revision status. `counts_scope` distinguishes NOT_VALIDATED (null counts),
VALIDATED_PREFIX on partial validation, and COMPLETE. These are per-acquisition
validation counts, not lifetime producer rejection counters. An integrity failure
before enum traversal does not invent a measured zero invalid-enum count.

## Preserved routing and authority semantics

Captured UNKNOWN_LEGACY remains the sole generation input for observations,
coverage/history, continuity, interaction endpoints, duplicates and workflows.
Neither reported value nor witness count enters profile construction, qualification,
settlement, independence or the semantic routing fingerprint. No resolved_generation
field or generation promotion was introduced.

The unchanged `ClosureVerifier` still requires authoritative captured-domain
request/result/acceptance or deadline proof. Reports cannot bridge domains or
resolve missing/ambiguous roots. Durable qualifications and invalidations remain
immutable historical records separate from current support. Same-operator Bench
stays `local-flop-agent-family`, same_operator=true, independent_reputation=false.
Multiple legacy witnesses do not add peers, interactions or reputation weight.

Fixture parity compares full streamed profiles and selected routes with the
independent existing full evaluator over identical captured evidence. Report-only
witness additions preserve the semantic fingerprint and interaction rows; a worker
integration test proves no new decision and no route call. Existing signed
`flop-routing-decision/v1` schema, hashes and signatures are unchanged. Settlement
remains SIMULATION_ONLY/DISABLED; no network write or transaction execution was added.

## Explicit cache and continuity migration

Fresh state can accept LG2 directly. Existing A1 or LG1 candidate state requires
`--activate-scout-lg2` after `worker once` or `worker run`. The Python reader's
corresponding explicit option is `activate_lg2=True`. Omission degrades readiness;
timeout, memory and size settings do not imply migration authorization.

Migration requires strictly greater publication and content IDs and CONTENT kind,
all existing time/source-cut/coverage/retention guards, and unchanged existing
message/interaction/provenance fields except removal of the LG1 annotation slot.
LG1 decoded audits must exactly equal the new normalized audits. Existing immutable
qualification/event records remain identical. A1 migration admits new reports only
after independent LG2 public-binding validation; it invents no historical reports.

The complete old checkpoint is retained in `revision_history`; its verified private
DB and any existing derived index are excluded from cleanup. Original producer
publication archives remain Scout's responsibility. Router preserves the private
bytes and checkpoint data already available to it. Restart validates archive
bindings and rehashes required historical copies; missing history cannot become a
fresh installation. Archive order/revisions/IDs are checked; downgrade and mixed
revision histories reject. Ordinary decisions/history are not rewritten.

The validator version changes to `router-v2-a1-lg2-validator/3`. Validation and
routing caches bind exact revision/policy/encoding. Migration rebuilds both; old
incompatible cache metadata cannot authorize LG2 validation. A mismatched derived
binding rebuilds from verified content. Corrupt accepted bytes or continuity state
fail closed rather than resetting history. Foundation f5ca717 state remains readable.

Same-content LG2 heartbeats reuse source validation, watermarks and the compact
routing index while still checking manifest freshness, expiry and continuity.
Restart rehashes private files; unchanged in-process file tokens avoid repeated
hashing. Accepted report codes and existing witness hashes/locators cannot change
or disappear while their source remains retained. Valid additions are audit-only.
Cancelled/degraded cycles do not advance the accepted checkpoint or emit decisions.

## Nine finalized fixture results

Fixed clock: `2026-09-08T12:00:00Z`. Fixture source:
`/private/tmp/scout-lg2-router-fixtures-final-20260908/index.json`.

| Fixture | Result | Checked meaning |
|---|---|---|
| normal-concrete | ACCEPT | Concrete captured evidence; zero LG reports. |
| legacy-reported-0 | ACCEPT | UNKNOWN_LEGACY, reported 0, two witnesses, one message/report. |
| legacy-reported-1 | ACCEPT | UNKNOWN_LEGACY, reported 1, unchanged authority. |
| multiple-same-generation-witnesses | ACCEPT | One semantic report, both exact witnesses. |
| true-conflict | REJECT | LG2_REPORT_PROVENANCE_CONFLICT despite valid artifact hashes. |
| same-operator-bench | ACCEPT | Controlled Bench history remains same-operator. |
| qualification-invalidation | ACCEPT | Invalidated historical qualification remains; Bench qualification itself remains VALID. |
| heartbeat-reuse | ACCEPT | New publication reuses verified content and index. |
| unknown-without-lg2 | ACCEPT | Unrelated unknown capture does not invent a report. |

## Performance

See [machine-readable trials](ROUTER_A1_LG2_BENCHMARK.json). Three fresh processes
per fixture/mode, with rotated A1-control/LG2 order. A1 controls remove only LG2 audit
storage from verified temporary copies and use the same optimized consumer. They
are semantic controls, not claims that the A1 producer admits this legacy class.
There is no previous LG1 Router runtime to benchmark. Control setup is outside
elapsed timings but remains in process high-water RSS. OS caches/host load are not
controlled; these are small-fixture observations, not production latency percentiles.

Cold acquisition includes pointer/manifest, descriptor copy/hash, SQLite integrity,
exact schema/base rows, watermarks, LG2 reports/witnesses/audit reconstruction,
qualification/workflow checks, compact profile indexing and bounded routing-state
construction. Nested timings overlap. This measures preparation through routing
state; production task-throughput is not measured. Steady/restart benchmarks repeat
the same publication; separate tests advance actual heartbeat publication IDs.

| Fixture | LG2 cold median ms | A1 control median ms | LG2 steady ms | LG2 restart ms | LG2 peak RSS MiB |
|---|---:|---:|---:|---:|---:|
| heartbeat-reuse | 15.240 | 14.312 | 0.697 | 0.819 | 31.98 |
| legacy-reported-0 | 14.928 | 13.960 | 0.720 | 0.814 | 31.92 |
| legacy-reported-1 | 14.767 | 14.409 | 0.814 | 0.934 | 31.97 |
| multiple-same-generation-witnesses | 15.344 | 13.852 | 0.727 | 0.820 | 31.91 |
| normal-concrete | 14.420 | 14.293 | 0.701 | 0.829 | 32.08 |
| qualification-invalidation | 15.294 | 14.040 | 0.708 | 0.821 | 32.05 |
| same-operator-bench | 14.687 | 14.478 | 0.710 | 0.824 | 31.98 |
| unknown-without-lg2 | 13.094 | 11.722 | 0.675 | 0.774 | 31.77 |

Example stage medians for `legacy-reported-0` (milliseconds):

| Stage | ms |
|---|---:|
| pointer_read | 0.223 |
| manifest_read | 0.190 |
| database_copy | 0.226 |
| sha256 | 0.035 |
| integrity_validation | 0.078 |
| schema_validation | 0.754 |
| watermark_validation | 0.099 |
| lg2_report_validation | 0.035 |
| lg2_witness_validation | 0.081 |
| lg2_audit_reconstruction | 0.036 |
| evidence_materialization | 11.002 |
| routing_state_construction | 0.319 |

LG2 adds roughly milliseconds at this scale, with no material absolute preparation regression. All successful trials remain well below 512 MiB; warm preparation is sub-second. Audit reconstruction is included within witness validation; index/state stages are included within evidence materialization.

The 30-second deadline, 512-MiB process guard and 4-GiB consumer ceiling remain
unchanged. No capacity limit was increased. The previous A1 100k-message envelope
remains historical A1 evidence; it is not relabelled as an LG2 scale result. Neither
Scout's 161,073-report benchmark nor these tiny consumer fixtures qualifies Router
at that volume. That is the next production-shaped dry-run measurement.

## Tests and temporary CLI validation

**Full suite: 475 tests and 88 subtests passed in 44.76 seconds; no skips.**
The new module adds 77 parametrized cases. `.venv/bin/python -m pytest -q`
was used. `git diff --check` passed; changed new files also passed whitespace
checks. No existing test was removed or weakened.

`test_projection_legacy.py` covers all nine fixtures, exact schema/generated-column/
CHECK/FK drift, policy/encoding dispatch, enums, provenance/hash/locator failures,
missing/orphan/oversized witnesses, duplicate reports, report/witness continuity,
A1 and LG1 explicit migration, exact old/new audit equality, archive preservation/
loss, restart/downgrade/cache mismatch, full profile/route parity, audit-only decision
suppression and recovery, workflow bridging rejection, qualification authority
rejection, captured interaction identity/multiplicity, query plans and cancellation.
The retained suite covers f5ca717 state, signed receipts, optional evidence,
responsive signals/lifecycle, descriptor isolation and read-only SQLite.

[CLI evidence](ROUTER_A1_LG2_SMOKE.json) records exact absolute commands from cwd=/,
using only newly created temporary state. Requested unconfigured `worker once
--state-dir <TEMP> --shadow` exits 1 with degraded missing input and zero decisions;
`worker status` exits 0 and reports stopped. An additional temporary synthetic LG2
heartbeat and state reach READY_IDLE/exit 0. Synthetic heartbeat time is updated
only in the new temporary publication; the supplied fixtures are not modified.
No continuous worker or launchd command was run.

## Trust boundary and remaining qualification

Public LG2 data cannot prove a hidden private source original. Scout must reject
competing raw generations/alternate candidates, validate original witness hashes
and locators, and retain its exact source proofs before normalization. Router
rejects malformed hashes, conflicting public bindings and later witness/code
mutations. It cannot detect a plausible but fabricated first-publication witness
hash/locator if a compromised producer recomputes all artifact hashes.

Likewise, deleting a report while leaving witnesses, or removing an accepted report,
fails. Omitting both the report and every witness on first publication is publicly
indistinguishable from the valid unrelated-unknown fixture. The approved contract
places that completeness check in Scout's retained-original validation. No test
pretends Router independently checked inaccessible originals or contradictory
values that were discarded before publication. SHA-256 establishes consistency,
not independent attestation against a compromised same-user producer.

The controlled Bench boundary remains accurate: opaque audits alone do not award
capability confidence. Explicitly configured, exactly linked originals with tested
capability may contribute controlled validation under existing rules. This task
adds no scoring conversion and does not infer competence from LG reports.

Large LG2 consumer volume/text/qualification mix, changed-content headroom, archive
disk growth, cold storage, many tasks and production cadence remain unqualified.
Cooperative cancellation still requires kernel/SQLite calls to return. The next
step is separately authorized production-shaped qualification with temporary state
and immutable producer artifacts, under unchanged limits; this report does not
authorize live-state access or deployment.

ROUTER_A1_LG2_IMPLEMENTED = YES

ROUTER_A1_LG2_FIXTURE_COMPATIBLE = YES

ROUTER_A1_LG2_READY_FOR_PRODUCTION_SHAPED_DRY_RUN = YES

The last flag means ready for that next qualification experiment after coordinated
review, not that a production-shaped consumer run has already passed. STOP for
review. No services, Scout edits, live state, deployment, commit or push.
