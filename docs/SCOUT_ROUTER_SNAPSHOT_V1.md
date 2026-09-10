# Scout → Router immutable publication contract v1

Status: Router consumer implemented; Scout publisher implementation is a prerequisite, outside this change. Router must not be restarted against Scout until Scout publishes this contract and foreground qualification succeeds.

## Trust and ownership

This same-user Mac deployment is a trusted local-operator boundary, not protection against a malicious process running as Greg. SHA-256 verifies artifact consistency and accidental substitution; it is not independent producer attestation. No signature claim is made. Any future manifest signing requires a separately approved mechanism.

Scout exclusively owns publication, retention, and cleanup. Router opens publication directories/artifacts only for reading and never modifies, deletes, checkpoints, migrates, or connects SQLite to them. Router writes only private temporary copies and Router-owned state. Router output paths and its temporary destination must be outside the publication root; conflicting configuration is rejected. Filesystem permissions should grant the consumer read/traverse access only; same-user ownership does not itself provide privilege separation.

## Artifacts

All names are relative simple basenames under one configured publication root. No empty name, `.`, `..`, slash, backslash, NUL, absolute path, or traversal is permitted. Symlink roots, symlink ancestor components, symlink artifacts, and non-regular artifact files are rejected. Use the physical absolute root path, e.g. `/private/tmp/...` rather than the macOS `/var` alias in fixtures.

`current.json` is an atomic mutable pointer:

```json
{
  "schema": "flop-scout-router-current/v1",
  "manifest": "manifest-<snapshot-id>-<manifest-sha256>.json",
  "manifest_sha256": "<64 lowercase hex>",
  "published_at": "<UTC timestamp>"
}
```

The referenced manifest is immutable:

```json
{
  "schema": "flop-scout-router-snapshot/v1",
  "snapshot_id": "<unique monotonic identifier>",
  "database": "observer-<snapshot-id>-<database-sha256>.sqlite",
  "sha256": "<64 lowercase hex>",
  "size_bytes": 12345,
  "database_schema_version": "scout-observer/v1",
  "produced_at": "<UTC timestamp>",
  "watermarks": [
    {"room": "<room>", "generation": "<generation or UNKNOWN_LEGACY>", "max_seq": 123}
  ]
}
```

The angle-bracket values above are placeholders. Snapshot IDs are canonical unsigned decimal strings, 1–20 digits, with no leading zeros except `"0"`; comparisons are numeric. IDs increase for each new publication, including after producer restart. A repeated ID must refer to exactly the same manifest and database hashes. Filenames include that ID and the SHA-256 of the exact artifact bytes. Manifest whitespace therefore affects its hash. A filename is never reused for different bytes.

Both JSON documents must be objects with exactly the displayed fields. Duplicate or unknown keys are rejected. SHA-256 values are exactly 64 lowercase hexadecimal characters. Integers must be JSON integers, not booleans, floats, or coerced strings. Timestamps use RFC3339 UTC `YYYY-MM-DDTHH:MM:SS[.ffffff]Z`, with valid calendar dates and up to six fractional digits. `produced_at <= published_at`; the pointer may be at most 60 seconds ahead of the consumer clock. `size_bytes` is nonnegative and bounded.

Limits: pointer 16 KiB; manifest 4 MiB; database 1 GiB; at most 10,000 watermark entries. Room and generation are nonblank strings of at most 256 characters. Watermarks are strictly sorted lexicographically by `(room, generation)`, with no duplicates. `max_seq` is a nonnegative integer. Generation `"0"` is distinct from `"UNKNOWN_LEGACY"`; neither may be mapped to the other.

## Database schema `scout-observer/v1`

The artifact is a closed, standalone SQLite database with rollback-journal header read/write versions 1/1 and `PRAGMA user_version = 1`. It requires no WAL, SHM, or journal companion. Extra tables/columns may exist, but these actual tables and columns are required:

| Table | Required columns |
| --- | --- |
| `messages` | `room`, `seq`, `timestamp`, `sender`, `signed`, `text`, `normalized_text`, `template_normalized_hash` |
| `interactions` | `source_did`, `target_did`, `relationship_type`, `confidence` |

The existing Router adapter additionally uses optional message provenance columns when present: `generation`, `nonce`, `sig`, `message_hash`, `verification_status`, `source_export_hash`, `source_export_path`, `evidence_id`. Preserve these verbatim from the consistent backup. Missing or SQL NULL generation is `UNKNOWN_LEGACY`; non-NULL generation is represented as its text value, including `0` → `"0"`.

Manifest watermarks must exactly equal `MAX(seq)` grouped by room and normalized generation over **all** database message rows, including unsigned rows. Message room values must be nonblank text and sequence values nonnegative SQLite integers. An empty messages table has an empty watermark list. These watermarks are publication provenance, not an instruction to skip previously read rows. Router verifies equality and performs `PRAGMA integrity_check` before using observations/interactions.

## Scout publication sequence

1. Use SQLite online backup on Scout's writer-owned database to create a consistent destination in staging on the publication filesystem. Scout may coordinate its own WAL/locks; Router never participates. Producer backup must finish successfully before publication.
2. On the staging destination only, produce a standalone rollback-journal database, set/verify the declared schema version, validate integrity/schema, and derive watermarks. Close all destination connections. Do not publish an artifact that depends on companions.
3. Assign a fresh monotonic snapshot ID and UTC `produced_at`. Hash and count the closed database bytes. Write/fsync the database under a temporary name, then atomically rename to `observer-<id>-<hash>.sqlite`. Never overwrite an existing immutable name. Fsync the publication directory.
4. Serialize the immutable manifest, hash its exact bytes, write/fsync a temporary file, and atomically rename to `manifest-<id>-<hash>.json`. Fsync the directory again.
5. Only after both immutable artifacts are durable, write/fsync a temporary current pointer and atomically replace `current.json` by rename. Fsync the directory.
6. Published database and manifest contents never change. Publish a new ID for any changed contents. Changing the pointer does not invalidate an already opened immutable artifact.

No Scout implementation is included in this repository change.

## Router descriptor-bound verification

Router retains a publication-root directory descriptor during `worker run`. It opens each ancestor/root with `O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW`, and every artifact with descriptor-relative `os.open(..., dir_fd=root_fd)` plus `O_NOFOLLOW`, `O_CLOEXEC`, and `O_NONBLOCK`. Nonblocking open prevents a substituted FIFO from hanging before `fstat` can reject it. Platforms lacking the descriptor primitives fail closed.

`current.json` is read with a byte limit from its opened regular-file descriptor. Router then opens the named manifest under the same root descriptor, hashes those bounded bytes, verifies the pointer hash/name, and validates the manifest. It opens the database once, checks that descriptor with `fstat`, then hashes/counts and copies bytes from that same descriptor into a mode-0600 file in a unique mode-0700 temporary directory. It never reopens the source pathname for copying.

Size and hash must match before fsync/close and SQLite use. Only the verified temporary file is opened with `mode=ro` and `PRAGMA query_only=ON`. Integrity, schema, and database watermarks are checked before Router queries. Published companions are neither inspected nor copied. Database consistency comes from Scout's online backup and immutable publication contract; Router hash verification detects wrong or changed bytes. It does not infer consistency from file timestamps.

If a parent path is renamed/replaced after the root descriptor is retained, the consumer continues reading the original bound directory. It never silently switches to the replacement. If an artifact name is replaced after opening, the reader continues on the opened inode and must still verify its manifest hash. Missing retained artifacts degrade; adopting a different publication directory requires an explicit restart/configuration change.

There is one bounded acquisition attempt per cycle: 30-second cooperative deadline, bounded JSON/database sizes, 1-MiB copy chunks, and SQLite progress cancellation. SQLite's private-copy busy timeout is 0.1 seconds. Failures retry at the worker's bounded backoff, not an unbounded inner retry loop. Local filesystem calls must return for cooperative cancellation/deadlines to run; SIGKILL, host crashes, and permanently stalled kernel I/O cannot provide graceful cleanup guarantees.

## Continuity and freshness

Router persists the last accepted snapshot ID, manifest/database hashes, `produced_at`, watermarks, and cumulative room/generation high-water marks in its own worker state. Snapshot ID regression, timestamp regression, same-ID hash conflict, and lower sequence for a previously accepted room/generation fail closed. A new generation is a distinct sequence domain. Disappeared domains retain their high-water mark so later reappearance cannot rewind them; removal is not interpreted as sequence zero.

A valid Scout snapshot can advance acceptance even when another optional input blocks routing. An interrupted/error cycle does not advance acceptance. Legacy `f5ca717` state starts with no publication checkpoint and remains readable. No history migration or deletion occurs.

`--max-snapshot-age` sets the maximum age in seconds, default 3600, finite and positive. Age beyond the limit yields `DEGRADED_INPUT_STALE`. Operators must synchronize clocks and choose a limit compatible with Scout's publication interval. An unchanged pointer is reverified, including freshness, and reuses the same logical snapshot identity. A newer publication containing identical substantive evidence does not trigger another shadow decision.

## Retention and cancellation

Scout retains the current database/manifest and older versions for at least `max(600 seconds, configured Router max-snapshot-age)` after replacement; deployments must agree on that value. Scout cleans abandoned producer staging files and expires old publications. Router owns only its temporary copies and worker state. If cleanup races an unopened old artifact, Router degrades/retries; it never substitutes another filename.

SIGINT/SIGTERM request cancellation for both `once` and `run`. Checks cover bounded source reads/copying, SQLite validation, and Python parsing/routing. Cancellable computation completes before the short decision append; cancellation before that commit prevents appending decisions. Signal delivery is deferred during the append itself to avoid partially committing an interrupted batch. Temporary copies and retained descriptors close before lock release. Interrupted cycles record `ERROR` / `WORKER_CANCELLED` where state storage is writable. Prior signal handlers are restored. A later invocation can acquire the lock.
