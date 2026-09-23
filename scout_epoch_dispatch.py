"""Normal publication dispatch for explicitly enabled, atomic Epoch V2 acceptance.

No environment configuration and no production paths. The worker directory is
operator supplied. A1 dispatch remains in ProjectionReader._read_a1.
"""
from contextlib import closing
from datetime import datetime, timezone
import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

import projection_contract as c
import scout_epoch_v2_validator as v2
from scout_epoch_store import WorkerEpochStore, read_private
from scout_projection import require
from scout_snapshot import SnapshotError, _parse, _basename, HASH, SNAPSHOT_ID, MAX_CURRENT_BYTES, MAX_MANIFEST_BYTES

DISK_MARGIN = 256 * 1024**2
DEFAULT_DISK_BUDGET = 8 * 1024**3


class MaterializedProfiles(dict):
    """Bound worker status to the same 1,000-supported-profile sample as A1."""
    def support(self, limit=1000):
        supported = ((did, p) for did, p in sorted(self.items()) if p.capabilities)
        result = {}
        for did, profile in supported:
            if len(result) == limit: break
            result[did] = {cap.capability_id: cap.support_level for cap in profile.capabilities}
        return result

    def support_scope(self):
        count = sum(bool(p.capabilities) for p in self.values())
        return dict(total_profiles_with_support=count, sample_limit=1000, complete=count<=1000,
                    full_index=None)

    def verification_count(self):
        return sum(len(items) for p in self.values() for items in p.validated_capability_evidence.values())


def trust_roots(reader):
    require(type(reader.enable_epoch_v2) is bool, 'EPOCH_CONFIG_INVALID')
    roots = [reader.epoch_v2_bridge_root, reader.epoch_v2_archive_root]
    require(all(p is not None for p in roots), 'EPOCH_TRUST_ROOT_REQUIRED')
    for path in roots:
        require(path.is_absolute() and path.resolve()==path and path.is_dir(), 'EPOCH_TRUST_ROOT_INVALID')
        require(not path.is_relative_to(reader.epoch_v2_state_dir)
                and not reader.epoch_v2_state_dir.is_relative_to(path), 'EPOCH_TRUST_ROOT_OVERLAP')
    require(roots[0] != roots[1] and not roots[0].is_relative_to(roots[1])
            and not roots[1].is_relative_to(roots[0]), 'EPOCH_TRUST_ROOT_OVERLAP')
    require(type(reader.epoch_v2_disk_budget) is int
            and 512*1024**2 <= reader.epoch_v2_disk_budget <= 64*1024**3, 'EPOCH_DISK_BUDGET_INVALID')


def preflight(reader, held, scratch, manifest, transition, archive_root):
    import scout_epoch_archive_validator as archive
    require(manifest['size_bytes'] <= reader.max_bytes
            and transition['bridge_predecessor']['artifact_size'] <= reader.max_bytes, 'SNAPSHOT_TOO_LARGE')
    d = transition['archive']
    raw = held.read(archive_root/'manifest.json', d['artifact_sha256'], d['size_bytes'], v2.MAX_INPUT_BYTES)
    am = v2.parse_json(raw)
    archive.validate_format(v2.without(d, 'archive_commitment_sha256'), am)
    require(all(0 < m['size_bytes'] <= archive.MAX_MEMBER for m in am['members']), 'EPOCH_DISK_BOUNDS')
    # Copies retained by acquisition, reconstruction, continuity, the final
    # generation and routing scratch; no existing cache is counted as freeable.
    required = (8*manifest['size_bytes'] + 6*transition['bridge_predecessor']['artifact_size']
                + 4*sum(m['size_bytes'] for m in am['members']) + 512*1024**2)
    budget = reader.epoch_v2_disk_budget
    require(required <= budget, 'EPOCH_DISK_BUDGET_EXCEEDED')
    require(shutil.disk_usage(scratch).free >= budget + DISK_MARGIN, 'EPOCH_DISK_SPACE')
    reader.metadata['epoch_disk'] = dict(required_bytes=required, budget_bytes=budget, margin_bytes=DISK_MARGIN)
    guard_staging(reader, scratch, budget, held)


def guard_staging(reader, scratch, budget, held=None):
    original = reader.check
    last = [0.0]
    def bounded_check():
        original()
        now = time.monotonic()
        if now-last[0] < 0.5: return
        last[0] = now
        total = 0
        for root, dirs, files in os.walk(scratch, followlinks=False):
            for name in dirs + files:
                path = Path(root)/name
                require(not path.is_symlink(), 'EPOCH_STAGING_PATH')
            for name in files:
                total += (Path(root)/name).stat().st_size
                require(total <= budget, 'EPOCH_DISK_BUDGET_EXCEEDED')
        require(shutil.disk_usage(scratch).free >= DISK_MARGIN, 'EPOCH_DISK_SPACE')
    reader.check = bounded_check
    if held is not None: held.check = bounded_check


def _accepted(reader, consume, store, state):
    """Load only a previously committed generation, never a producer candidate."""
    previous = state['last_accepted_projection_v2']
    require(previous['size_bytes'] <= reader.max_bytes, 'SNAPSHOT_TOO_LARGE')
    required=2*previous['size_bytes']+512*1024**2
    require(required <= reader.epoch_v2_disk_budget, 'EPOCH_DISK_BUDGET_EXCEEDED')
    require(shutil.disk_usage(store.root).free >= required+DISK_MARGIN, 'EPOCH_DISK_SPACE')
    m = copy.deepcopy(previous['manifest'])
    m['database_content_id'] = str(m['database_content_id'])
    m['source_checkpoint']['committed_event_id'] = str(m['source_checkpoint']['committed_event_id'])
    reader.metadata.update(previous, content_binding=m['epoch_transition']['transition_sha256'],
                           selection_policy=m['selection_policy'], stage_seconds={},
                           current_pointer_status='ACCEPTED_STATE', epoch_status='EPOCH_V2_ACCEPTED_ONLY')
    original_cache = reader.cache_dir
    original_check = reader.check
    try:
        with tempfile.TemporaryDirectory(prefix='.stage-', dir=store.root) as temporary:
            reader.cache_dir = Path(temporary)
            guard_staging(reader, reader.cache_dir, reader.epoch_v2_disk_budget)
            with reader.connection(Path(previous['cache_path'])) as conn:
                require([r[0] for r in conn.execute('PRAGMA integrity_check')]==['ok'], 'DATABASE_INTEGRITY_FAILED')
                reader._schema(conn,m); reader._rows(conn,m); reader._coverage(conn,m,None)
                with closing(sqlite3.connect(reader.cache_dir/'audit.sqlite')) as audit:
                    reader._qualifications(conn,m,audit); reader._workflows(conn,audit,m)
                indexed=consume(conn)
                profiles=MaterializedProfiles()
                for did, profile in indexed.items(): reader.check(); profiles[did]=profile
            reader.metadata.pop('routing_cache',None)
            reader.metadata['cache_path']=previous['cache_path']
            return profiles, reader.metadata
    finally:
        reader.cache_dir=original_cache
        reader.check=original_check


def dispatch(reader, consume, previous, max_age, now, allow_stale, retain_candidate):
    from scout_epoch_acceptance import accept_with_store
    reader.deadline=time.monotonic()+reader.timeout
    reader.metadata={'stage_seconds':{},'current_pointer_status':'NOT_CHECKED','epoch_status':'NOT_CHECKED'}
    root=reader.epoch_v2_state_dir
    store=None
    acquisition=False
    try:
        # Recovery precedes all producer acquisition, even if the gate is off.
        state_path=root/'worker_state.json'
        if state_path.exists() or (root/'journal.json').exists():
            state=json.loads(read_private(state_path))
            accepted=state.get('last_accepted_projection_v2',{})
            if (root/'journal.json').exists() or accepted.get('contract_revision')==v2.REVISION:
                store=WorkerEpochStore(root, check_io=reader.check)
                with store.locked():
                    _,state=store.recover()
                    accepted=state['last_accepted_projection_v2']
                    if accepted['contract_revision']==v2.REVISION and not reader.enable_epoch_v2:
                        return _accepted(reader,consume,store,state)
        acquisition=True
        reader._open_root()
        pointer=_parse(reader._read_json_file('current.json',MAX_CURRENT_BYTES),
                       ('schema','manifest','manifest_sha256','published_at'),'flop-scout-router-current/v2')
        _basename(pointer['manifest_sha256'],HASH)
        _basename(pointer['manifest'],rf'manifest-v2-{SNAPSHOT_ID}-{HASH}\.json')
        raw=reader._read_json_file(pointer['manifest'],MAX_MANIFEST_BYTES)
        import hashlib
        require(hashlib.sha256(raw).hexdigest()==pointer['manifest_sha256'],'MANIFEST_HASH_MISMATCH')
        manifest=c.loads(raw,MAX_MANIFEST_BYTES)
        reader.metadata['current_pointer_status']='VALID'
        if type(manifest) is not dict or manifest.get('contract_revision')!=v2.REVISION:
            return reader._read_a1(consume,previous,max_age,now,allow_stale=allow_stale,retain_candidate=retain_candidate)
        acquisition=False
        if not reader.enable_epoch_v2: raise SnapshotError('EPOCH_V2_DISABLED')
        trust_roots(reader)
        require(not allow_stale and retain_candidate, 'EPOCH_DISPATCH_MODE')
        require(manifest.get('publication_kind')=='CONTENT','EPOCH_PUBLICATION_KIND')
        store=store or WorkerEpochStore(root, check_io=reader.check)
        with store.locked():
            _,state=store.recover()
            accepted=state['last_accepted_projection_v2']
            if accepted['contract_revision']==v2.REVISION:
                require(pointer['manifest_sha256']==accepted['manifest_hash'],'EPOCH_NEXT_TRANSITION_UNSUPPORTED')
                return _accepted(reader,consume,store,state)
        original_cache=reader.cache_dir
        def materialize(conn, internal):
            reader.metadata.update(internal.metadata)
            reader.cache_dir=internal.cache_dir
            return consume(conn)
        def check_space(internal,*args):
            internal.epoch_v2_disk_budget=reader.epoch_v2_disk_budget
            preflight(internal,*args)
        try:
            profiles, accepted, summary=accept_with_store(store,reader.root,reader.epoch_v2_bridge_root,
                reader.epoch_v2_archive_root,now=now or datetime.now(timezone.utc),
                timeout=max(0.001,reader.deadline-time.monotonic()),max_bytes=reader.max_bytes,
                max_memory=reader.max_memory,check_cancel=reader.check_cancel,
                materialize=materialize,preflight=check_space,max_age=max_age)
            # Seal recovery before ordinary worker status may update other fields.
            with store.locked(): store.recover()
            reader.metadata.update(accepted,epoch_status='EPOCH_V2_ACCEPTED',current_pointer_status='VALID',
                                   selection_policy=manifest['selection_policy'])
            reader.metadata.pop('routing_cache',None)
            return MaterializedProfiles(profiles),reader.metadata
        finally: reader.cache_dir=original_cache
    except BlockingIOError:
        raise SnapshotError('EPOCH_WRITER_BUSY') from None
    except (v2.EpochV2Error, ValueError) as exc:
        raise SnapshotError(getattr(exc,'code','EPOCH_INPUT_INVALID')) from None
    except OSError as exc:
        if acquisition:
            import errno
            reason=('DEGRADED_INPUT_MISSING' if exc.errno==errno.ENOENT else 'DEGRADED_INPUT_INVALID' if exc.errno in {errno.ELOOP,errno.ENOTDIR} else 'DEGRADED_INPUT_UNREADABLE')
            raise SnapshotError('CONTINUITY_COPY_UNAVAILABLE' if previous else 'PUBLICATION_UNREADABLE',reason) from None
        raise SnapshotError('EPOCH_IO_OR_COMMIT_RECOVERY_REQUIRED') from None
