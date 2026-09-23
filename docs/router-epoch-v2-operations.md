# Epoch V2 operator runbook (Checkpoint 5)

Release status: Checkpoint 5 disposable acceptance, restart, interruption recovery
and offline rollback passed. See
[the path-redacted audit](fixtures/router-epoch-v2-deployment-rehearsal.json).
Changes still require review and an approved release commit before deployment.
No production operations were performed while preparing this change.

## Prerequisites and verification

Use Python 3.11 and the reviewed Router revision. Freeze writers before backup or
rollback. Only one Router process may own a state directory. The existing worker
lock and the Epoch store advisory lock reject competing writers. Do not remove a
lock belonging to a running process.

Run in the reviewed checkout:

```sh
git status --short
git rev-parse HEAD
git ls-remote origin refs/heads/feature/scout-epoch-v2-validator
shasum -a 256 docs/fixtures/scout-epoch-v2-publication-bundle-compact-v3.json
python3.11 -m pytest -q
python3.11 -m compileall -q .
git diff --check
```

The frozen fixture SHA must be
`c7cee620934589e1a41bb26bbb0cb1af80a49811d99290d048618c21186ba735`.
Verify the approved release SHA independently. Historical fixtures do not waive
normal publication freshness checks. Never change the system clock to accept an
old publication.

## Backup and archive installation

An operator must stop the writer using the site's approved procedure. Back up the
**entire** private Router state directory, including worker_state.json, accepted
cache, generations and any journal. Keep a hash/size inventory of the backup.
Resolve any journal using the reviewed recovery implementation before proceeding;
do not edit checkpoints or journals. The accepted anchor must already be the
verified durable content-232 checkpoint with its original cache.

Install independently verified immutable archive files and the exact content-242
A1 bridge publication into separate operator-controlled absolute directories.
Retain exact manifest and artifact bytes. Do not synthesize bridge publications,
use producer-supplied absolute paths, or derive identity from filenames. Archive
and bridge roots must be disjoint from each other and the worker state directory,
with no symlink path components. Keep producer writers away from these roots.
The private worker directory must be owned by the Router user and mode 0700.
Use one local filesystem for worker staging, generations, journal and state.

## Disposable dry run

Create fresh copies of the backed-up state and approved publication, bridge and
archive inputs. Configure an empty disposable task inbox and no external worker
sources or service integration. Verify protected input hashes before and after.
Use explicit paths; never use a production state path for this rehearsal.

Example shell variables below must be assigned to the disposable copies:

```sh
python3.11 router.py worker once --state-dir "$REHEARSAL_STATE" \
  --scout-snapshot-root "$REHEARSAL_PUBLICATION" --shadow
```

A new V2 candidate must report exactly `EPOCH_V2_DISABLED`. Accepted checkpoint
and cache must remain byte-identical. Routine worker status can change.

Then exercise the explicit gate:

```sh
python3.11 router.py worker once --state-dir "$REHEARSAL_STATE" \
  --scout-snapshot-root "$REHEARSAL_PUBLICATION" --shadow \
  --enable-scout-epoch-v2 \
  --epoch-archive-root "$REHEARSAL_ARCHIVE" \
  --epoch-bridge-root "$REHEARSAL_BRIDGE" \
  --epoch-disk-budget 8589934592 --snapshot-timeout 300 \
  --max-projection-memory 536870912
python3.11 router.py worker status --state-dir "$REHEARSAL_STATE"
```

`--enable-scout-epoch-v2` is the sole enable gate (programmatic equivalent:
`enable_scout_epoch_v2=True`). It defaults to false. No environment variable
enables it. Existing `--activate-scout-v2` is a separate legacy migration option.
Missing or incompatible trust roots reject acceptance. V2 heartbeats reject.
The supported transition is the first A1-to-Epoch-V2 transition; another V2
transition is not enabled by this release.

Preflight estimates staging as 8 times active artifact bytes + 6 times bridge
artifact bytes + 4 times total archive member bytes + 512 MiB. This must fit the
configured budget (512 MiB through 64 GiB). Available disk must cover the entire
budget plus 256 MiB reserve. Staging usage, free disk, elapsed time, memory and
cancellation are checked during processing. Accepted-generation restart also
preflights temporary validation space. Increase limits only after measured review.

The recorded 232→242→243 replay materialized 21,231 Profiles in 50.33 seconds;
fresh-process accepted-generation restart took 18.06 seconds. Peak RSS across
cases was 496,091,136 bytes. Preflight required 3,587,329,496 staging bytes under
the explicit 8 GiB budget plus 256 MiB reserve. Use the explicit 300-second
timeout and 512 MiB memory ceiling above for this deployment shape; the default
30-second timeout is insufficient for the measured initial acceptance. All 22
source files retained identical SHA-256, size, inode, mtime and ctime. These are
historical replay measurements, not a guarantee for different data or hardware.

## Enable and verify health

Only after successful disposable acceptance, restart, failure injection and
rollback evidence has been reviewed may an operator schedule deployment. Restore
the approved explicit configuration with the gate and trust roots above. Do not
add environment fallbacks or service defaults. Acquire a fresh publication.

Verify content 243, the expected epoch and transition commitment, profile count,
archive commitments and healthy worker status. Restart the writer and verify the
same accepted generation loads. Recovery completes before acquisition: incomplete
precommit staging is discarded; a committed state is verified and loaded. A
corrupt or ambiguous journal must fail closed. No session capability is persisted.

Repeat with the gate omitted: already accepted content 243 remains readable,
without acquisition of a further V2 transition. Disabling does not roll back.

## Abort, rollback and retention

Abort on missing bridge bytes, wrong anchor, any binding/reconstruction/policy
error, disk/resource failure, unhealthy profiles or unexpected content/epoch.
`EPOCH_WRITER_BUSY`: locate the existing writer; do not override its lock.
`EPOCH_DISK_SPACE` or budget failure: free approved scratch space or review limits.
`EPOCH_IO_OR_COMMIT_RECOVERY_REQUIRED` / `EPOCH_RECOVERY_REQUIRED`: stop acquisition
and run recovery; do not manually promote a cache. Preserve diagnostic hashes,
not raw evidence or private absolute paths.

For rollback, stop all writers and restore the **entire** verified content-232
backup into a fresh private directory. Verify every inventory hash, then select
that directory with the gate disabled and verify ordinary A1 continuity. Do not
restore just worker_state.json over a newer generation. First rehearse this exact
procedure on copies and record the restored checkpoint/cache hashes.

Retain the backup, accepted generations, exact bridge publication and immutable
archive until documented retention/recovery requirements are independently
verified. This release authorizes no automatic archive or generation cleanup.
Only remove identified disposable staging after recovery and retention checks;
never delete an uncertain journal or evidence to make validation pass.
