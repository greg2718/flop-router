# FLOP Router

Evidence-driven execution router for autonomous agents.

FLOP Router selects agents and teams using observed evidence rather than self-reported capability. It separates each execution decision into:

```text
WORK_ROUTE
SETTLEMENT_PLAN
VERIFICATION_PLAN
SECURITY_POLICY
```

It is designed to answer:

- Who should do this work?
- What evidence supports that choice?
- How should the result be verified?
- What settlement route is compatible?
- What security policy applies?

Router is currently local-first and evidence-driven. It does not post to Technocore, execute settlement, hold funds, or autonomously contact agents.

## Router Identity

FLOP Router DID:

```text
did:key:z6MkpGs1L6fYEsaXsDfyDfrTxbKVeZ3evuPaBj2x38KzupPd
```

This is Router's persistent Ed25519 `did:key` identity. Private signing material is stored outside this repository under:

```text
~/.flop_agents/router/
```

The DID is intended to remain stable across Router versions. Public metadata may include:

- `operator_group`: `local-flop-agent-family`
- planned canonical Technocore room: `d-flop-router`
- planned signed mailbox: `mb-flop-router`

The planned room and mailbox are documented public intent only. They are not claimed or activated as part of this repository preparation.

## Current Features

Implemented features:

- evidence-grounded capability routing
- qualification-before-scoring
- capability support levels: `STRONG_SUPPORT`, `LIMITED_SUPPORT`, `SIGNAL_ONLY`, `NO_EVIDENCE`
- multi-agent team composition
- same-operator independence protection
- controlled capability validation
- Scout TCLK observation ingestion
- TCLK-aware execution planning
- settlement support levels: `VERIFIED_USAGE`, `OBSERVED_SIGNED_SUPPORT`, `ADVERTISED_HINT`, `NO_EVIDENCE`, `CONTRADICTED`
- exact integer settlement amount handling
- `OBJECTIVE_BENCH` verification planning
- Sentinel security-policy interface
- local Router -> Scout -> Bench verification workflow
- evidence consistency checking
- persistent encrypted Router Ed25519 identity provisioning
- deterministic signed routing-decision receipts

TCLK planning is non-value-bearing:

```text
mode: SIMULATION_ONLY
settlement_execution: DISABLED
```

Router consumes normalized TCLK observations as evidence for settlement compatibility. It does not implement the normative TCLK state machine, sign TCLK frames, accept offers, lock funds, reveal/refund/cancel, generate settlement secrets, or write to Technocore.

## Shadow Worker

**V2/A1 and A1-LG2 consumer development candidate; not deployed.** The worker accepts
[V2/A1 and A1-LG2 projections](docs/SCOUT_ROUTER_SNAPSHOT_V2.md). Scout's producer is implemented
but not deployed. The retained [V1 contract](docs/SCOUT_ROUTER_SNAPSHOT_V1.md) and
V1 reader are historical compatibility fixtures, not an automatic fallback.
See the [performance correction and measured limits](docs/ROUTER_V2_A1_PERFORMANCE_REVIEW.md).

The [A1-LG2 compact legacy-report contract](docs/SCOUT_ROUTER_SNAPSHOT_V2.md#lg2-compact-legacy-report-storage)
replaces LG1's oversized per-row JSON with normalized report/witness tables.
LG1 authority semantics remain unchanged: captured UNKNOWN_LEGACY, reported
zero/one as audit metadata only. Scout and Router now implement LG2; Router
explicitly rejects LG1 publications and mixed encodings. See the
[LG2 consumer results and limitations](docs/ROUTER_A1_LG2_CONSUMER_REVIEW.md).
A fresh temporary state may accept LG2 directly. Existing A1/LG1 checkpoints
require explicit `--activate-scout-lg2`, preserved historical artifacts and a new
CONTENT publication; validation and routing caches rebuild. This is development
qualification, not deployment approval. No production worker start is authorized.
The subsequent [production-shaped TCLK linkage review](docs/ROUTER_TCLK_LINKAGE_REVIEW.md)
keeps handoff blocked: the producer stopped before creating a valid projection.
`offer_id` is not an authoritative tclk/1 ACCEPT field; no alias or runtime fix
is authorized. The report also records a conservative-retention gap for review.
Keep production stopped. Neither passing schema validation nor fitting below
4 GiB establishes operational qualification.

The proposed [A1-LG2-TL1 legacy reconciliation design](docs/ROUTER_TCLK_LEGACY_RECONCILIATION_DESIGN.md)
has an approved structural schema pin (`tclk1-tl1-structural-schema/v1`) for
implementation: only the exact pinned JSON Schema determines structural cohort
nonconformance; reference-decoder results cannot change historical membership.
See the design for the immutable revision and SHA-256. It adds authenticated-but-nonconforming,
audit-only records, no `offer_id` alias, and conservative unresolved domain holds
with explicit capacity stops. Its schema and policy are not implemented in either
runtime here. The ClosureVerifier safety correction and production qualification
remain required before handoff; current A1-LG2 behavior is not repaired by this document.

A1 keeps durable qualification/history separately from current support. Duplicate
downgrades do not erase original evidence; append-only supersession/invalidation
records remain in verified Router-owned copies. Audit transport does not award
STRONG_SUPPORT or independent reputation. Explicitly configured, exactly linked
local Bench originals can contribute controlled validation confidence; an opaque
audit record alone cannot.

The worker produces local unsigned shadow recommendations. Polling never loads signing identity, posts to Technocore, invokes Bench, claims work, or executes settlement. `worker once` runs one cycle; `worker run` polls continuously; `worker status` prints persisted state as JSON and checks the PID lock. Process `running` is liveness, not input readiness.

Worker input arguments belong **after `worker run` or `worker once`**:

| Argument | Policy |
| --- | --- |
| `--scout-snapshot-root PATH` | Required Scout immutable publication directory. Omission/missing publication degrades readiness. |
| `--max-snapshot-age SECONDS` | Finite positive freshness limit; default 3600 seconds. |
| `--max-snapshot-bytes BYTES` | Positive integer, default/hard maximum 4294967296 (4 GiB); may tighten, never silently increase. No 8-GiB override is implemented. |
| `--snapshot-timeout SECONDS` | Positive finite acquisition and profile-construction deadline; default 30. |
| `--max-projection-memory BYTES` | Positive process peak-RSS guard; default 536870912 (512 MiB). Exceeding it requires a fresh process before recovery. |
| `--activate-scout-lg2` | Explicit migration of an accepted A1 or supplied LG1 candidate checkpoint to LG2. Archives the old checkpoint/private copy, validates continuity and rebuilds caches. No downgrade or automatic conversion. |
| `--activate-scout-v2` | Required only to migrate a retained V1 checkpoint. Preserve V1 provenance and enforce global ID/time continuity. New state uses V2 directly. |
| `--validation-store PATH` | Optional local validation-attempt JSONL. Omission explicitly means disabled/unconfigured. |
| `--ingest-store PATH` | Optional normalized Scout export-observation JSONL. Omission explicitly means disabled/unconfigured. |
| `--tclk-store PATH` | Optional normalized TCLK observation JSONL. Omission explicitly means disabled/unconfigured. |
| `--bench-proof-store PATH` | Optional explicit Router-local `router-bench-proof/v1` JSONL originals. Disabled when omitted; missing/malformed configured files degrade readiness. |
| `--task-inbox PATH` | Router-owned task JSONL; defaults to `<state-dir>/worker/tasks.jsonl`. Initialized exclusively as an empty file on first use if absent. Existing contents are preserved. |
| `--sentinel-executable PATH` | Explicit Sentinel venv Python executable; defaults to the reviewed local Sentinel venv and is never resolved through `PATH`/`PYTHONPATH`. |
| `--sentinel-timeout SECONDS` | Finite positive per-task screening deadline; default 5 seconds. Timeout or any invalid/missing Sentinel result fails closed. |

Every configured path is expanded and resolved absolutely at startup. No worker evidence source inherits a `devdata` default. Existing global `--db`, `--validation-store`, `--ingest-store`, `--tclk-store`, and `--verification-evidence-store` remain available to other commands with their development defaults, but are rejected for worker commands to prevent ambiguous configuration.

Before a task is routed, its extracted `{task_id, task}` pair is screened by
Sentinel v0.2 in an isolated child process. `R-110/WARN` is the documented
unsigned-task floor and can route; `QUARANTINE`, `REJECT`, unavailable/timeout,
malformed, unknown, or version-mismatched verdicts produce no qualified route.
See [the Sentinel integration pin and soak set](docs/SENTINEL_ROUTER_INTEGRATION.md).

`verification_evidence.jsonl` remains the normalized lifecycle audit store, not
an original-proof store or validation-attempt store. Its global CLI option is
still rejected for workers. The new `--bench-proof-store` is an explicit input
with [a separate proof envelope and scoring boundary](docs/ROUTER_V2_A1_PERFORMANCE_REVIEW.md#controlled-bench-originals).
Router never follows a path or URL embedded in a Scout proof reference. A Bench
PASS without an explicit tested capability remains unscored. Accepted, currently
valid linked originals may affect controlled confidence under the existing
validation policy; they never count as independent counterparties. Invalidated or
superseded results confer no current credit. Conflicting effective PASS/FAIL for
one request yields FAIL. `verification_evidence_count` counts accepted validation
attempts plus eligible controlled Bench validations. Optional JSONL parsing is
strict, rejects duplicate keys, and limits each record to 4 MiB; the proof store
also has a 16-MiB file limit.

The worker consumes the [Scout publication contract V2/A1 or A1-LG2](docs/SCOUT_ROUTER_SNAPSHOT_V2.md): atomic `current.json`, a hash-addressed immutable manifest, and a standalone SQLite online-backup artifact produced by Scout. It never opens live Scout SQLite or copies WAL/SHM/journal files. `--scout-db` is explicitly rejected as unsafe/deprecated.

Router retains the publication directory descriptor, rejects symlinks, and opens each artifact relative to that descriptor. Bounded pointer/manifest parsing, hash-embedded filenames, descriptor-bound database copying, size/SHA-256 verification, SQLite integrity/schema checks, and exact database watermarks precede routing. Only a verified mode-0600 temporary copy is opened through SQLite (`mode=ro`, `query_only=ON`); candidate directories are removed on failure/cancellation. Accepted immutable copies are retained under `<state-dir>/worker/v2-copies` for history and restart continuity. Publication files remain read-only. The contract is a trusted local-operator consistency boundary, not independent producer attestation or a signature claim.

Separate publication/content IDs, hashes, times, policy, selected-scope watermarks and cumulative historical witnesses are persisted in `last_accepted_projection_v2`. Heartbeats may advance publication identity while reusing the last verified database. Every restart rehashes the prior private copy. Missing/corrupt continuity state blocks acceptance. Rollback, same-ID hash conflict, unsupported schema, and watermark regression fail closed. A retained root descriptor prevents parent-path replacement from substituting another publication directory.

All enabled sources must pass validation before routing; the Scout source is a directory containing regular publication artifacts. A configured optional source is just as readiness-blocking as Scout. Each cycle and status contains a `sources` manifest with name, absolute path, enabled/required flags, existence/readability/validity, type, modification time where available, record count, and safe reason code. `scout_snapshot` also reports pointer status, snapshot ID, hashes, production time, age, schema version, and watermarks. Disabled sources have null paths and `DISABLED_UNCONFIGURED`. Scout freshness is enforced by `--max-snapshot-age`; other evidence has no new freshness policy.

- `READY_IDLE`: every enabled source is valid; no new decision is needed, including empty inputs or deduplicated tasks.
- `READY_ACTIVE`: every enabled source is valid and new shadow decisions were produced.
- `DEGRADED_INPUT_MISSING`, `DEGRADED_INPUT_UNREADABLE`, `DEGRADED_INPUT_INVALID`: at least one enabled source failed inspection; no routing decisions are produced.
- `DEGRADED_INPUT_STALE`: the Scout publication exceeds the configured age limit; no routing decisions are produced.
- `ERROR`: cycle processing failed or was cancelled; an error cycle and state update are persisted.

V2 source readiness additionally reports `READY`, `WARNING_LARGE`, `TOO_LARGE`,
`TOO_SLOW`, `MEMORY_LIMIT`, `STALE`, `INVALID`, `UNSUPPORTED_POLICY`, or
`CONTINUITY_FAILURE`. Warnings require operator qualification; failed readiness
never routes. Per-stage timings distinguish pointer/manifest reads, copy, SHA-256,
SQLite open/integrity, schema/rows, watermarks, qualifications, evidence and profiles.
The byte target remains preferred <512 MiB and normally qualified <1 GiB; a
1–4 GiB artifact is `WARNING_LARGE`, not a production recommendation.

Unresolved Kibble workflows require a uniquely scoped authenticated JOB, an
exact linked RESULT/DELIVER, and the issuer's unambiguous ACCEPT before finite
retention is accepted. TCLK expiry-only closure requires an authenticated offer,
a valid elapsed deadline and no linked transition. Unknown generic terminal
grammars and missing/conflicting proof fail closed. Bench originals validate
request/result closure but their permanent retention never becomes time-limited.

Raw message text is streamed into Router-derived private SQLite summaries.
Duplicate groups, capability aggregates and qualification history use indexed
queries; candidate profiles load on demand. Producer capability labels are not
scoring authority. The accepted database and compact routing store are separately
hash-bound. After restart Router rehashes both private files before reusing their
validation; unchanged in-process file identities/size/mtime/ctime permit cheap
heartbeat reuse. Changed content receives full integrity, schema, policy, history
and continuity validation. No `quick_check` substitution is implemented.
Obsolete source copies are removed only after a ready checkpoint is durable;
failed/cancelled acquisition preserves the previous checkpoint. Budget disk for
prior and candidate databases, private summary stores and temporary SQL indexes.
Status `current_support` samples at most 1,000 DIDs with capabilities;
`current_support_scope` reports completeness, total count and the full index
path. Explanatory direct-edge lists show at most 100 descriptions per profile;
complete counts and substantive input hashes still drive routing.
Source `readiness_phase` reports the last completed preparation step:
`CONTENT_VALIDATED`, `INDEX_READY`, then `ROUTING_READY`. Only the worker can
reach the last phase after all enabled inputs and final state/resource checks
pass. This progress field does not override the cycle's current readiness or
error status. Stage metrics include process high-water RSS and its increase
during the stage; nested stage deltas overlap.

The loop retries failures on exponential backoff capped by `--max-backoff` (default 300 seconds), then returns to `--poll-interval` (default 60 seconds) after recovery. An initialized inbox disappearing later is a failure, including after restart; it is not silently recreated. `last_success_at` remains the historical last success, while current `status`/`readiness`, failure count, and error timestamps identify failure. SIGTERM/SIGINT cancel both `once` and `run`, wake polling waits, clean temporary artifacts, and release the lock. Bounded reads, SQLite progress callbacks, and Python computation checks handle cancellation. Decisions are prepared in a private temporary history file with cancellable bounded copying; only the final atomic rename masks signals. Polling cancellation is persisted. Cooperative checks require filesystem/SQLite calls to return.

The worker appends cycle records and preserves existing history. State from `f5ca717` remains readable; status reports `UNKNOWN_LEGACY` until a new validated cycle. Foundation history remains readable. V1 publication checkpoints require explicit migration; their original fields are preserved. Shadow policy `flop-router-shadow/v4-v2-a1-stream` hashes loaded substantive routing evidence and profile fields, including interactions, trust/risk, validations, TCLK, and generation-aware identities. Clock-derived activity-recency labels/components are excluded. Publication IDs, publication times, and artifact hashes are provenance, not routing evidence, and do not independently trigger decisions. Worker work qualification has no time-based capability expiry; worker plans use default constraints without requesting settlement, so settlement expiry is not a worker reevaluation boundary. Existing decision IDs are retained; the new snapshot/policy causes one intentional reevaluation of existing tasks after upgrade. Subsequent unchanged tasks remain deduplicated across recovery/restart. Signed routing-decision schemas and hashes are unchanged. There are no ingestion cursors to reset.

Structured JSON stdout events cover startup, resolved configuration, readiness transitions, source failure/recovery, cycle summaries, and shutdown. Unchanged idle/failure summaries are limited to once per 15 minutes; every cycle is still persisted. Raw source contents and exception messages are not logged.

**Do not restart production or load launchd.** Scout is implemented but not deployed,
and current end-to-end capacity is substantially below the nominal byte targets.
After coordinated review, deployment authorization and producer qualification,
the proposed foreground command below checks a publication. A retained V1 checkpoint
also requires separately reviewed `--activate-scout-v2` migration. This is not
permission to use live state during development:

```sh
/Users/greg/Dev/flop-router/.venv/bin/python /Users/greg/Dev/flop-router/router.py worker once --state-dir /Users/greg/.flop_agents/router --scout-snapshot-root /Users/greg/.flop_scout/router-publication --max-snapshot-age 3600 --task-inbox /Users/greg/.flop_agents/router/worker/tasks.jsonl --shadow
```

Require exit code 0, a final `READY_IDLE` or `READY_ACTIVE` cycle, and valid Scout/inbox manifest entries. Omitted optional evidence sources in this command are deliberately disabled. If enabling one, add its explicit absolute path to both foreground and launchd arguments and repeat validation. `worker once` exits 1 on degraded/error readiness. Status can be inspected with:

```sh
/Users/greg/Dev/flop-router/.venv/bin/python /Users/greg/Dev/flop-router/router.py worker status --state-dir /Users/greg/.flop_agents/router
```

Proposed launchd configuration fragment (documentation only):

```xml
<key>ProgramArguments</key>
<array>
    <string>/Users/greg/Dev/flop-router/.venv/bin/python</string>
    <string>/Users/greg/Dev/flop-router/router.py</string>
    <string>worker</string>
    <string>run</string>
    <string>--state-dir</string>
    <string>/Users/greg/.flop_agents/router</string>
    <string>--scout-snapshot-root</string>
    <string>/Users/greg/.flop_scout/router-publication</string>
    <string>--max-snapshot-age</string>
    <string>3600</string>
    <string>--task-inbox</string>
    <string>/Users/greg/.flop_agents/router/worker/tasks.jsonl</string>
    <string>--poll-interval</string>
    <string>60</string>
    <string>--max-backoff</string>
    <string>300</string>
    <string>--shadow</string>
</array>
<key>WorkingDirectory</key>
<string>/Users/greg/Dev/flop-router</string>
```

`WorkingDirectory` is defense in depth: correctness comes from explicit absolute input arguments. **Do not load the launchd plist until source validation and the foreground shadow cycle above succeed.** This correction does not edit or load `~/Library/LaunchAgents/com.greg.flop-router.worker.plist`; keep the live worker stopped pending review.

### Selection scoring

Qualification precedes scoring. `work_score` is the authoritative routing score, using bounded weights `5/25/25/15/10/20` for claimed capability, observed behavior, Bench evidence, completion history, independent counterparties, and trust/risk. Claims are discovery signals only and cannot satisfy a required capability. Trust requires affirmative profile evidence; ordinary activity and absence of risk are not trust evidence. Soft risks produce explicit warnings and deterministic deductions. When settlement is explicitly required, compatibility and hard safety gates run first, then selection uses exactly `0.65 * work_score + 0.35 * settlement_score`; otherwise settlement inputs do not affect worker selection. Malformed settlement deadlines are rejected. A qualified worker with no compatible settlement retains its work route and receives `NO_COMPATIBLE_SETTLEMENT_ROUTE`. Settlement remains `SIMULATION_ONLY` with execution `DISABLED`.

## Related Agents

Operator group:

```text
local-flop-agent-family
```

Related agents:

```text
FLOP Scout
did:key:z6MkfJnczowbivU9SEDcZ77MEpKUfQTVbcD3i1gcwsfo4yL1

FLOP Bench
did:key:z6MkqqqEMxujBTEAvoanSx6pVBMMZzLP7gMUcmNVdYHS3BVk

FLOP Sentinel
DID not yet provisioned
```

Interactions among related agents are controlled same-operator evidence. They must not count as independent peer reputation, independent jurors, independent arbiters, or multiple independent operator groups.

## Quick Demo

Use the repository virtualenv:

```bash
.venv/bin/python router.py evaluate
.venv/bin/python router.py verify-evidence-consistency --fixture fixtures/evidence_consistency.jsonl
.venv/bin/python router.py route "Debug an HTTP 400 response"
.venv/bin/python router.py compose "Reproduce an Ed25519 signed POST failure against Technocore"
.venv/bin/python router.py plan-execution "Debug an HTTP 400 response" --asset FLOP --max-amount 1 --allowed-rails x402 --allowed-lock-types hash --verification-mode OBJECTIVE_BENCH
.venv/bin/python router.py decision create "Debug an HTTP 400 response" --fixture fixtures/evidence_consistency.jsonl --output /tmp/router-decision.json
.venv/bin/python router.py decision show /tmp/router-decision.json
.venv/bin/python router.py technocore status
.venv/bin/python router.py technocore profile-message
.venv/bin/python router.py identity show
```

These commands are local/read-only except for generated local reports or local ignored development artifacts. They do not sign, post, claim rooms, execute settlement, or access wallets.

## Identity Commands

Router identity state belongs under:

```text
~/.flop_agents/router/
```

Available commands:

```bash
.venv/bin/python router.py --state-dir ~/.flop_agents/router identity init
.venv/bin/python router.py --state-dir ~/.flop_agents/router identity verify
.venv/bin/python router.py --state-dir ~/.flop_agents/router identity show
```

`identity init` must only be run once per persistent Router identity. If a Router identity already exists, do not regenerate it. `identity init` refuses to overwrite `identity.pem` or `identity.json`.

`identity verify` decrypts the encrypted private key locally with the operator-supplied passphrase, derives the public DID, and verifies it matches `identity.json`.

`identity show` reads public metadata only and does not decrypt or access the private key.

Never commit `identity.pem`, `identity.json`, passphrases, private keys, or local state directories.

## Capability Model

Router infers capability from behavioral evidence, not claims alone. Messages such as "I can debug" are weak signals unless the observation also shows concrete behavior such as tracing, diagnosing, reproducing, fixing, testing, or reporting a specific failure.

Capability support levels:

- `STRONG_SUPPORT`: strong demonstrated/reproduced evidence or enough independent substantive behavioral evidence
- `LIMITED_SUPPORT`: relevant substantive evidence exists but does not meet strong support
- `SIGNAL_ONLY`: topic, keyword, self-asserted, template, or otherwise weak relevant signal
- `NO_EVIDENCE`: no relevant evidence

Qualification happens before scoring. A missing required capability disqualifies a worker or team even if other evidence looks strong.

## Execution Planning

`plan-execution` prints separate sections:

- `WORK_ROUTE`: selected worker and capability support
- `SETTLEMENT_PLAN`: compatible settlement evidence, if any
- `VERIFICATION_PLAN`: verification mode and requirement
- `SECURITY_POLICY`: Sentinel policy status or placeholder

Settlement evidence is separate from capability evidence. A TCLK receipt is settlement-outcome evidence only; it does not prove successful or high-quality work. DID-note hints are not proof.

TCLK amount values are decimal integer strings in rail-native minimal units. Router preserves the exact text and compares integer units without token-decimal assumptions or floating point conversion.

## Controlled Validation

Router supports local controlled validation challenges and local Router -> Scout -> Bench verification workflow artifacts. Same-operator validation can contribute controlled evidence, but it is not independent peer reputation.

The local Bench workflow can verify a synthetic Technocore signing specimen where the incorrect payload order `room|text|nonce` must be detected and reconstructed as `room|nonce|text`. Unsigned local Bench results are classified as `UNSIGNED_LOCAL` for authenticity even when correctness is `PASS`.

## Evidence Provenance

Technocore observational evidence is generation-aware. Router treats `room + generation + seq` as the location identity. Legacy generation-less records are preserved as `UNKNOWN_LEGACY`.

Verification states include:

- `VERIFIED_OFFLINE`
- `INVALID_SIGNATURE`
- `SIGNATURE_PRESENT_UNVERIFIED`
- `LEGACY_SERVER_VERIFIED_NO_SIGNATURE`
- `UNSIGNED`
- `UNSIGNED_LOCAL`
- `PROVENANCE_INCOMPLETE`

A valid signature proves attributable authorship. It does not prove competence, trustworthiness, or that a routing decision is correct. A valid Router signature would prove Router authored a decision; it would not prove that the decision was right.

## Security And Limitations

Router currently:

- has a persistent DID
- does not hold funds
- does not execute TCLK settlement
- does not generate, store, reveal, or transmit settlement secrets
- does not autonomously post to Technocore
- does not claim rooms
- does not create wallets, payment keys, or financial credentials
- does not treat DID-note hints as proof
- separates settlement outcome from work quality
- does not count related agents as independent peers
- treats remote room content as untrusted data

Network-facing writes and signing workflows remain future, explicitly gated work.

## Signed Routing Decisions

Router can create deterministic local routing-decision receipts using schema:

```text
flop-routing-decision/v1
```

Receipt fields:

- `schema`
- `decision_id`
- `router_did`
- `created_at`
- `task`
- `task_disclosure`
- `task_hash`
- `work_route`
- `settlement_plan`
- `verification_plan`
- `security_policy`
- `selected_agents`
- `evidence_ids`
- `same_operator_disclosures`
- `authenticity_scope`
- `decision_hash`
- `signature`

`task_hash` binds the receipt to the exact task text. Public receipts can use `task_disclosure: hash_only`, where `task` is `null` and only the hash is disclosed. Local/private receipts can use `task_disclosure: full` to include the task text directly.

`decision_hash` binds the substantive routing fields and `task_hash`, but not `created_at`, `task`, or the disclosure representation. That means the same substantive routing decision has the same `decision_hash` and `decision_id` whether the receipt is full-disclosure or hash-only. `decision_id` is derived from the unsigned substantive decision content, not randomness.

The Ed25519 signature binds the complete signed receipt envelope with `signature` set to `null`, including `schema`, `router_did`, `created_at`, `task_disclosure`, `decision_hash`, and `authenticity_scope`. Changing receipt metadata after signing, including `created_at` or disclosure mode, invalidates authenticity even when the semantic `decision_hash` is unchanged. Canonical JSON serialization is used for hashing and signing.

Local workflow:

```bash
.venv/bin/python router.py decision create "Debug an HTTP 400 response" \
  --fixture fixtures/evidence_consistency.jsonl \
  --task-disclosure hash_only \
  --output /tmp/router-decision.json

.venv/bin/python router.py decision show /tmp/router-decision.json

.venv/bin/python router.py --state-dir ~/.flop_agents/router decision sign \
  /tmp/router-decision.json \
  --output /tmp/router-decision.signed.json

.venv/bin/python router.py decision verify /tmp/router-decision.signed.json
```

`decision create` and `decision show` do not access the private key. `decision sign` is the only decision command that decrypts the local encrypted Router identity, and it does so only after explicit invocation and passphrase entry. Generated receipts are local artifacts; Router does not post them to Technocore.

Verification reports:

- `AUTHENTICITY: VERIFIED_OFFLINE`
- `TASK_BINDING: VERIFIED_FROM_CONTENT` or `HASH_ONLY`
- `ROUTING_CORRECTNESS: NOT_ESTABLISHED_BY_SIGNATURE`

A valid Router signature proves authorship and integrity only. It means Router authored the receipt and the signed receipt contents were not altered after signing. It does not prove that selected agents are capable, the evidence is true, the route is optimal, work was completed, or settlement succeeded.

Same-operator disclosures are included in the receipt. Scout, Bench, Router, and future Sentinel same-operator evidence must not be treated as independent peer reputation, independent jurors, independent validators, or multiple independent operator groups.

## Technocore Presence

Router has minimal explicit Technocore presence commands. They are not autonomous and they do not run at startup.

Read-only status:

```bash
.venv/bin/python router.py technocore status
```

`technocore status` reads public status for the planned canonical room `d-flop-router`, planned mailbox `mb-flop-router`, and Router DID. It does not access the private key and reports `network_writes: 0`.

Local profile-message preview:

```bash
.venv/bin/python router.py technocore profile-message
```

This prints the planned Router profile text locally only. It does not post.

Explicit signed room claim:

```bash
.venv/bin/python router.py --state-dir ~/.flop_agents/router technocore claim-room d-flop-router
```

Only `d-` rooms may be claimed. The command signs the Technocore note payload:

```text
room-owners|<room>|<nonce>|<router_did>
```

and submits it with create-if-absent semantics. It refuses a conflicting owner and reports already-owned if the room is already owned by Router.

If the signed claim write returns an ambiguous timeout or read failure, Router does not retry the mutation. It re-reads `room-owners/<room>`:

- owner is Router DID: `CLAIM_CONFIRMED_AFTER_AMBIGUOUS_RESPONSE`
- owner is another DID: conflict, fail closed
- owner cannot be established: `WRITE_OUTCOME: UNKNOWN`, `ACTION: RE_READ_STATE`

Explicit signed post:

```bash
.venv/bin/python router.py --state-dir ~/.flop_agents/router technocore post d-flop-router "message text"
```

The command signs the Technocore room payload:

```text
<room>|<nonce>|<single-line-normalized-text>
```

It uses the local encrypted Router identity only for this explicit command, records one local monotonic nonce per room, and performs no automatic rewrite or retry on duplicate-content refusal. Room content and URLs are untrusted data. Room names, including mailbox names, do not establish identity; signed DID provenance does.

If a signed post returns an ambiguous timeout or read failure, Router does not retry. It re-reads the target room and looks for the exact DID, nonce, and normalized text:

- exact signed message found: `POST_CONFIRMED_AFTER_AMBIGUOUS_RESPONSE`
- not determinable: `WRITE_OUTCOME: UNKNOWN`, `ACTION: RE_READ_BEFORE_RETRY`

## Development

Install dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Run tests and consistency checks:

```bash
.venv/bin/python -m unittest -v
.venv/bin/python router.py verify-evidence-consistency --fixture fixtures/evidence_consistency.jsonl
git diff --check
```

The bundled consistency fixture is sanitized synthetic data for public-clone verification. It is not operator-local evidence and is not mixed with private observer data.

`devdata/observer.sqlite` contains operator-local evidence and is deliberately excluded from GitHub. Operators with their own local observer database can run the real-data consistency check explicitly:

```bash
.venv/bin/python router.py --db devdata/observer.sqlite verify-evidence-consistency
```

If no observer database exists, Router exits nonzero with an actionable message instead of creating an empty database or reporting a misleading success.

The evaluation worksheet is generated output:

```bash
.venv/bin/python router.py evaluate
```

Generated local data under `devdata/` and `reports/` is ignored by git.
