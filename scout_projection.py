"""V2/A1 consumer. SQLite sees only verified Router-private copies.

The producer is a trusted same-user source, not an independent attestor. Local
proof references stay opaque: they never authorize opening arbitrary paths.
"""
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import math
import os
from pathlib import Path
import resource
import sqlite3
import sys
import tempfile
import time

import projection_contract as c
import projection_legacy as lg
import scout_epoch_v2_validator as epoch_v2
from scout_snapshot import (SnapshotReader, SnapshotError, Cancelled, _parse,
                            _basename, HASH, SNAPSHOT_ID, MAX_CURRENT_BYTES,
                            MAX_MANIFEST_BYTES, utc_timestamp)

MAX_BYTES = 4 * 1024**3
MAX_MEMORY = 512 * 1024**2
VALIDATOR_VERSION = 'router-v2-a1-lg2-validator/3'
SCHEMA_SQL = Path(__file__).with_name('docs').joinpath('router-projection-v2-schema.sql').read_text()
MANIFEST_FIELDS = set('schema contract_revision snapshot_id publication_kind database_content_id database sha256 size_bytes database_schema_version selection_policy selection_policy_sha256 content_created_at selection_evaluated_at produced_at source_checkpoint next_expiry_at row_counts watermarks coverage_history'.split())
PERMANENT = {'NEGATIVE_EVIDENCE', 'PINNED', 'IDENTITY_OPERATOR', 'BENCH_VERIFICATION', 'CAPABILITY_SUPPORT', 'CAPABILITY_CONTRADICTION'}
LOCAL_DIDS = {'did:key:z6MkfJnczowbivU9SEDcZ77MEpKUfQTVbcD3i1gcwsfo4yL1', 'did:key:z6MkqqqEMxujBTEAvoanSx6pVBMMZzLP7gMUcmNVdYHS3BVk', 'did:key:z6MkpGs1L6fYEsaXsDfyDfrTxbKVeZ3evuPaBj2x38KzupPd'}


def rss_bytes():
    n = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return n if sys.platform == 'darwin' else n * 1024


def require(ok, code='INVALID_PROJECTION'):
    if not ok:
        raise SnapshotError(code)


@dataclass(frozen=True)
class VerifiedEpochBridge:
    """Router-local, live-only bridge capability; never wire-serializable."""
    _session: object
    _token: object
    candidate_transition_sha256: str
    accepted_anchor: dict
    bridge_predecessor: dict
    bridge_binding: str
    verified_bridge_commitment: str
    source_checkpoint: dict
    watermarks_commitment: str
    history_commitment: str
    audit_commitment: str

    def __repr__(self):
        return '<VerifiedEpochBridge active=%s>' % self._session.active

    def __reduce__(self):
        raise TypeError('VerifiedEpochBridge is session-local and non-serializable')


class EpochValidationSession:
    """Owns ephemeral bridge staging and invalidates all receipts on close."""
    def __init__(self, reader):
        self.reader = reader
        self.token = object()
        self.active = False
        self._temporary = None

    def __enter__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix='.epoch-v2-', dir=self.reader.cache_dir)
        os.chmod(self._temporary.name, 0o700)
        self.active = True
        return self

    def __exit__(self, *_):
        self.active = False
        self._temporary.cleanup()
        self._temporary = None


def family(value, did=None):
    if did in LOCAL_DIDS or value['operator_group'] == c.FAMILY or value['same_operator'] is True:
        require(value['operator_group'] == c.FAMILY and value['same_operator'] is True
                and value['independent_reputation'] is False, 'OPERATOR_CONFLICT')


def coverage(items, historical=False):
    require(type(items) is list and len(items) <= 10000, 'INVALID_COVERAGE')
    fields = {'room', 'generation', 'max_ever_projected_seq', 'witness_source_locator', 'witness_record_sha256'} if historical else {'room','generation','record_count','min_seq','max_seq'}
    keys = []
    for row in items:
        c.keys(row, fields); c.string(row['room']); c.string(row['generation'])
        keys.append((row['room'],row['generation']))
        if historical:
            require(type(row['max_ever_projected_seq']) is int and row['max_ever_projected_seq'] >= 0)
            c.string(row['witness_source_locator']); c.sha(row['witness_record_sha256'])
        else:
            require(all(type(row[k]) is int for k in ('record_count','min_seq','max_seq')))
            require(row['record_count'] > 0 and 0 <= row['min_seq'] <= row['max_seq'])
    require(keys == sorted(set(keys)), 'DUPLICATE_OR_UNORDERED_COVERAGE')


class ProjectionReader(SnapshotReader):
    def __init__(self, root, cache_dir, check_cancel=lambda: None, timeout=30.0,
                 max_bytes=MAX_BYTES, max_memory=MAX_MEMORY, activate_lg2=False,
                 enable_epoch_v2=False, epoch_v2_predecessor=None,
                 epoch_v2_first_transition=False):
        super().__init__(root, check_cancel, timeout)
        if not math.isfinite(timeout) or timeout <= 0 or type(max_bytes) is not int or not 0 < max_bytes <= MAX_BYTES:
            raise ValueError('positive timeout and byte ceiling <=4 GiB required')
        if type(max_memory) is not int or max_memory <= 0:
            raise ValueError('positive memory ceiling required')
        self.cache_dir = Path(cache_dir).expanduser().resolve()
        if self.cache_dir.is_relative_to(self.root.resolve()):
            raise ValueError('private cache must be outside publication')
        self.max_bytes, self.max_memory = max_bytes, max_memory
        self.created = set()
        self.activate_lg2 = activate_lg2
        self.enable_epoch_v2 = enable_epoch_v2
        self.epoch_v2_predecessor = epoch_v2_predecessor
        self.epoch_v2_first_transition = epoch_v2_first_transition
        self.archived_paths = set()
        self.verified_files = {}

    def check(self):
        super().check()
        if rss_bytes() > self.max_memory:
            raise SnapshotError('PROJECTION_MEMORY_LIMIT', 'DEGRADED_INPUT_UNREADABLE')

    @contextmanager
    def stage(self, name):
        self.check()
        before = time.monotonic()
        before_rss = rss_bytes()
        try:
            yield
            self.check()
        except BaseException:
            self.metadata.setdefault('failed_stage', name)
            raise
        finally:
            self.metadata.setdefault('stage_seconds', {})[name] = self.metadata.get('stage_seconds', {}).get(name, 0) + time.monotonic() - before
            self.metadata.setdefault('stage_peak_rss_bytes', {})[name] = rss_bytes()
            self.metadata.setdefault('stage_peak_rss_delta_bytes', {})[name] = max(0, rss_bytes()-before_rss)

    @contextmanager
    def schema_component(self, name, count_key=None):
        """Measure a required validation component without changing its scope.

        The values are deliberately aggregate-only: publication rows remain
        untrusted and are not copied into worker status diagnostics.
        """
        before = time.monotonic()
        counts = self.metadata.setdefault('schema_validation_object_counts', {})
        if count_key is not None:
            counts.setdefault(count_key, 0)
        try:
            yield
        finally:
            breakdown = self.metadata.setdefault('schema_validation_breakdown', {})
            breakdown[name] = breakdown.get(name, 0.0) + time.monotonic() - before

    def cleanup(self, accepted_path=None, accepted_routing=None):
        for path in self.created.copy():
            derived = str(path) == accepted_routing
            if str(path) != accepted_path and not derived:
                path.unlink(missing_ok=True)
            self.created.discard(path)
        # Called only after the durable worker checkpoint. Its current copy
        # contains all retained audit history; obsolete content copies are not
        # independent history records. Never scan a producer directory.
        if accepted_path and Path(accepted_path).parent == self.cache_dir:
            import re
            for path in self.cache_dir.glob("*.sqlite"):
                obsolete_source = str(path) != accepted_path and re.fullmatch(HASH + r"\.sqlite",path.name)
                obsolete_routing = str(path) != accepted_routing and re.fullmatch(HASH + r"\." + HASH + r"\.routing\.sqlite",path.name)
                if (obsolete_source or obsolete_routing) and str(path) not in self.archived_paths:
                    path.unlink(missing_ok=True)

    def _copy_database(self, manifest, destination):
        # Read, hash and copy the same open producer descriptor, never reopen it.
        fd = self._open_file(manifest['database'])
        before = time.monotonic(); hash_seconds = 0.0
        try:
            require(os.fstat(fd).st_size <= self.max_bytes, 'SNAPSHOT_TOO_LARGE')
            require(os.fstat(fd).st_size == manifest['size_bytes'], 'DATABASE_SIZE_MISMATCH')
            out = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC, 0o600)
            h = hashlib.sha256(); count = 0
            with os.fdopen(out,'wb') as target:
                while True:
                    self.check()
                    chunk = os.read(fd,1024**2)
                    if not chunk: break
                    count += len(chunk)
                    require(count <= min(manifest['size_bytes'],self.max_bytes), 'DATABASE_SIZE_MISMATCH')
                    start = time.monotonic(); h.update(chunk); hash_seconds += time.monotonic()-start
                    target.write(chunk)
                require(count == manifest['size_bytes'] and h.hexdigest() == manifest['sha256'], 'DATABASE_HASH_OR_SIZE_MISMATCH')
                target.flush(); os.fsync(target.fileno())
        finally:
            os.close(fd)
            self.metadata['stage_seconds']['sha256'] = hash_seconds
            self.metadata['stage_seconds']['database_copy'] = time.monotonic()-before-hash_seconds

    def _verify_cache(self, previous):
        path = self.cache_dir / (previous['database_hash'] + '.sqlite')
        require(previous.get('cache_path') == str(path), 'CONTINUITY_CACHE_PATH')
        self.verify_private(path, previous['database_hash'], previous['manifest']['size_bytes'])
        return path

    def verify_private(self, path, digest, size):
        require(path.parent == self.cache_dir, 'CONTINUITY_CACHE_PATH')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            import stat
            info=os.fstat(fd)
            require(stat.S_ISREG(info.st_mode), 'CONTINUITY_CACHE_NOT_REGULAR')
            require(info.st_uid==os.getuid() and not info.st_mode & 0o022, 'CONTINUITY_CACHE_OWNERSHIP')
            require(info.st_size == size, 'CONTINUITY_CACHE_SIZE')
            stamp=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_mode)
            if self.verified_files.get((str(path),digest)) == stamp:
                self.check(); return
            h = hashlib.sha256()
            while True:
                self.check(); chunk = os.read(fd,1024**2)
                if not chunk: break
                h.update(chunk)
            require(h.hexdigest() == digest, 'CONTINUITY_CACHE_HASH')
            after=os.fstat(fd)
            require(stamp==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns,after.st_mode),'CONTINUITY_CACHE_CHANGED')
            self.verified_files[(str(path),digest)] = stamp
        finally: os.close(fd)

    def _manifest(self, pointer, raw, previous, max_age, now, enforce_freshness=True):
        digest = hashlib.sha256(raw).hexdigest()
        require(digest == pointer['manifest_sha256'], 'MANIFEST_HASH_MISMATCH')
        m = c.loads(raw, MAX_MANIFEST_BYTES)
        revision = m.get('contract_revision') if type(m) is dict else None
        if revision == epoch_v2.REVISION:
            if not self.enable_epoch_v2:
                raise SnapshotError('EPOCH_V2_DISABLED')
            try:
                epoch_v2.validate_transition(m.get('epoch_rollover'), self.epoch_v2_predecessor,
                                             self.epoch_v2_first_transition)
            except epoch_v2.EpochV2Error as exc:
                raise SnapshotError(exc.code) from None
            # Slice 2 is deliberately validate-only: do not open an archive,
            # copy a database, or update accepted continuity state.
            raise SnapshotError('EPOCH_V2_NOT_ACCEPTING')
        require(revision in ('A1', lg.REVISION), 'UNSUPPORTED_REVISION')
        if revision == lg.REVISION:
            self.metadata['legacy_generation_audit']=dict(revision=revision,policy_status='NOT_VALIDATED',counts_scope='NOT_VALIDATED',
                report_count=None,witness_count=None,reported_0_count=None,reported_1_count=None,
                average_witnesses_per_report=None,max_witnesses_per_report=None,invalid_enum_count=None,conflict_count=None)
        fields = MANIFEST_FIELDS | ({'legacy_generation_policy','legacy_generation_encoding'} if revision == lg.REVISION else set())
        c.keys(m, fields)
        require(m['schema']=='flop-scout-router-snapshot/v2','UNSUPPORTED_REVISION')
        content_binding = lg.binding(m)
        if revision == lg.REVISION: self.metadata['legacy_generation_audit']['policy_status']='VALID'
        c.decimal(m['snapshot_id']); c.decimal(m['database_content_id']); c.sha(m['sha256'])
        require(pointer['manifest'] == f"manifest-v2-{m['snapshot_id']}-{digest}.json", 'MANIFEST_FILENAME_ID_MISMATCH')
        require(m['database'] == f"router-projection-v2-{m['database_content_id']}-{m['sha256']}.sqlite", 'DATABASE_FILENAME_MISMATCH')
        require(m['database_schema_version'] == c.SCHEMA, 'UNSUPPORTED_REVISION')
        require(c.canonical(m['selection_policy']) == c.canonical(c.POLICY) and m['selection_policy_sha256'] == c.POLICY_SHA, 'UNSUPPORTED_POLICY')
        require(type(m['size_bytes']) is int and m['size_bytes'] >= 100, 'INVALID_DATABASE_SIZE')
        require(m['size_bytes'] <= self.max_bytes, 'SNAPSHOT_TOO_LARGE')
        require(m['publication_kind'] in {'CONTENT','HEARTBEAT'}, 'INVALID_PUBLICATION_KIND')
        t = {k:utc_timestamp(m[k]) for k in ('content_created_at','selection_evaluated_at','produced_at')}
        pub = utc_timestamp(pointer['published_at'])
        require(t['content_created_at'] <= t['selection_evaluated_at'] == t['produced_at'] <= pub and (pub-now).total_seconds() <= 60, 'INVALID_PUBLICATION_TIME')
        age = (now-t['produced_at']).total_seconds()
        if enforce_freshness and age > max_age: raise SnapshotError('SNAPSHOT_STALE','DEGRADED_INPUT_STALE')
        if m['next_expiry_at'] is not None:
            require(utc_timestamp(m['next_expiry_at']) > t['selection_evaluated_at'], 'DUE_EXPIRY')
        c.keys(m['source_checkpoint'], {'source_id','epoch','committed_event_id'})
        c.string(m['source_checkpoint']['source_id']); c.string(m['source_checkpoint']['epoch']); c.decimal(m['source_checkpoint']['committed_event_id'])
        c.keys(m['row_counts'], set(c.TABLES) | (lg.TABLES if revision == lg.REVISION else set()))
        require(all(type(v) is int and v >= 0 for v in m['row_counts'].values()), 'INVALID_ROW_COUNTS')
        coverage(m['watermarks']); coverage(m['coverage_history'],True)
        self.metadata.update(snapshot_id=m['snapshot_id'], publication_id=m['snapshot_id'], manifest_hash=digest,
                             database_content_id=m['database_content_id'], database_hash=m['sha256'], produced_at=m['produced_at'],
                             published_at=pointer['published_at'], database_schema_version=c.SCHEMA, contract_revision=revision, content_binding=content_binding, selection_policy=m['selection_policy'],
                             watermarks=m['watermarks'], coverage_history=m['coverage_history'], age_seconds=max(0,age),
                             manifest_canonical_hash=c.digest(m), size_bytes=m['size_bytes'], preferred=m['size_bytes'] < 512*1024**2,
                             size_readiness='WARNING_LARGE' if m['size_bytes'] >= 1024**3 else 'QUALIFIED', manifest=m)
        if previous:
            p = previous.get('manifest')
            require(type(p) is dict, 'CONTINUITY_STATE_INVALID')
            for field in ('snapshot_id','database_content_id'): c.decimal(previous.get(field))
            require(previous['snapshot_id']==p.get('snapshot_id') and previous['database_content_id']==p.get('database_content_id')
                    and previous.get('database_hash')==p.get('sha256') and previous.get('produced_at')==p.get('produced_at')
                    and previous.get('watermarks')==p.get('watermarks') and previous.get('coverage_history')==p.get('coverage_history'), 'CONTINUITY_STATE_CONFLICT')
            require(previous.get('manifest_canonical_hash')==c.digest(p),'CONTINUITY_STATE_HASH')
            prior_revision=p.get('contract_revision')
            prior_fields=MANIFEST_FIELDS | ({'legacy_generation_policy'} if prior_revision=='A1-LG1' else {'legacy_generation_policy','legacy_generation_encoding'} if prior_revision==lg.REVISION else set())
            c.keys(p,prior_fields)
            require(prior_revision in ('A1','A1-LG1',lg.REVISION) and previous.get('contract_revision')==prior_revision, 'CONTINUITY_STATE_INVALID')
            prior_binding=lg.binding(p)
            if prior_revision == lg.REVISION:
                require(revision == lg.REVISION, 'CONTINUITY_REVISION_DOWNGRADE')
                require(previous.get('content_binding')==prior_binding,'CONTINUITY_LG2_BINDING')
            if prior_revision != revision:
                require(revision == lg.REVISION and self.activate_lg2,'CONTINUITY_LG2_ACTIVATION_REQUIRED')
                require(int(m['snapshot_id'])>int(p['snapshot_id']) and int(m['database_content_id'])>int(p['database_content_id']) and m['publication_kind']=='CONTENT','CONTINUITY_LG2_MIGRATION_IDS')
                self.metadata['revision_history'] = previous.get('revision_history',[]) + [{k:v for k,v in previous.items() if k!='revision_history'}]
                self.metadata['revision_migration']='EXPLICIT_LG2_REBUILD'
            else:
                self.metadata['revision_history'] = previous.get('revision_history',[])
            history=self.metadata['revision_history']
            require(type(history) is list and len(history)<=2,'CONTINUITY_REVISION_HISTORY')
            revisions=tuple(a.get('contract_revision') for a in history if type(a) is dict)
            require(len(revisions)==len(history) and revisions in ((),('A1',),('A1-LG1',),('A1','A1-LG1')),'CONTINUITY_REVISION_HISTORY')
            last_id=last_content=-1
            for archived in history:
                am=archived.get('manifest')
                require(type(am) is dict and archived.get('manifest_canonical_hash')==c.digest(am)
                        and am.get('contract_revision')==archived['contract_revision']
                        and archived.get('database_hash')==am.get('sha256')
                        and archived.get('snapshot_id')==am.get('snapshot_id')
                        and archived.get('database_content_id')==am.get('database_content_id'),'CONTINUITY_ARCHIVE_BINDING')
                lg.binding(am)
                c.decimal(am['snapshot_id']);c.decimal(am['database_content_id'])
                require(last_id<int(am['snapshot_id'])<int(m['snapshot_id']) and last_content<int(am['database_content_id'])<int(m['database_content_id']),'CONTINUITY_REVISION_HISTORY')
                last_id=int(am['snapshot_id']);last_content=int(am['database_content_id'])
                path=archived.get('cache_path')
                require(path==str(self.cache_dir/(archived['database_hash']+'.sqlite')),'CONTINUITY_ARCHIVE_PATH')
                self.archived_paths.add(path)
                if archived.get('routing_cache'): self.archived_paths.add(archived['routing_cache']['path'])
            require(pub >= utc_timestamp(previous.get('published_at',p['produced_at'])), 'CONTINUITY_PUBLICATION_TIME_ROLLBACK')
            require(int(m['snapshot_id']) >= int(p['snapshot_id']), 'CONTINUITY_PUBLICATION_ROLLBACK')
            if m['snapshot_id'] == p['snapshot_id']:
                require(digest == previous['manifest_hash'], 'CONTINUITY_PUBLICATION_CONFLICT')
            require(int(m['database_content_id']) >= int(p['database_content_id']), 'CONTINUITY_CONTENT_ROLLBACK')
            for k in ('content_created_at','selection_evaluated_at','produced_at'):
                require(utc_timestamp(m[k]) >= utc_timestamp(p[k]), 'CONTINUITY_TIME_ROLLBACK')
            require(m['selection_policy'] == p['selection_policy'], 'CONTINUITY_POLICY_CHANGE')
            cut, old = m['source_checkpoint'],p['source_checkpoint']
            require((cut['source_id'],cut['epoch']) == (old['source_id'],old['epoch']) and int(cut['committed_event_id']) >= int(old['committed_event_id']), 'CONTINUITY_SOURCE_ROLLBACK')
            if m['database_content_id'] == p['database_content_id']:
                fields = ('contract_revision','sha256','size_bytes','database','content_created_at','selection_policy_sha256','row_counts','watermarks','coverage_history','next_expiry_at')
                require(all(m[k] == p[k] for k in fields), 'CONTINUITY_CONTENT_CONFLICT')
                if m['snapshot_id'] != p['snapshot_id']: require(m['publication_kind'] == 'HEARTBEAT', 'CONTINUITY_CONTENT_KIND')
            else: require(m['publication_kind'] == 'CONTENT', 'CONTINUITY_HEARTBEAT_CHANGED_CONTENT')
        return m

    @contextmanager
    def connection(self, path):
        with path.open('rb') as stream:
            header = stream.read(100)
        require(len(header)==100 and header[:16]==b'SQLite format 3\x00' and header[18:20]==b'\x01\x01','DATABASE_NOT_STANDALONE')
        conn = None
        interrupted = []
        def progress():
            try: self.check()
            except (Cancelled,SnapshotError) as exc: interrupted.append(exc); return 1
            return 0
        try:
            with self.stage('sqlite_open'):
                conn = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1)
                conn.row_factory=sqlite3.Row
                conn.execute('PRAGMA query_only=ON'); conn.execute('PRAGMA trusted_schema=OFF'); conn.execute('PRAGMA foreign_keys=ON')
                conn.execute('PRAGMA cache_size=-8192'); conn.execute('PRAGMA temp_store=FILE')
                conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, min(self.max_memory//8,64*1024**2))
                conn.set_progress_handler(progress,1000)
            yield conn
        except sqlite3.Error:
            if interrupted: raise interrupted[0]
            raise SnapshotError('DATABASE_INTEGRITY_OR_QUERY_FAILED') from None
        finally:
            if conn is not None: conn.close()

    def _schema(self, conn, m):
        with self.schema_component('table_schema_metadata_validation'):
            with closing(sqlite3.connect(':memory:')) as expected:
                expected.executescript(SCHEMA_SQL + (lg.SQL if m['contract_revision']==lg.REVISION else ''))
                query="SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
                require([tuple(r) for r in conn.execute(query)] == [tuple(r) for r in expected.execute(query)], 'INVALID_DATABASE_SCHEMA')
                if m['contract_revision']==lg.REVISION:
                    for table in sorted(lg.TABLES):
                        for pragma in ('table_xinfo','foreign_key_list','index_list'):
                            require([tuple(r) for r in conn.execute(f'PRAGMA {pragma}({table})')]==[tuple(r) for r in expected.execute(f'PRAGMA {pragma}({table})')],'INVALID_LG2_SCHEMA')
            require(conn.execute('PRAGMA user_version').fetchone()[0] == 2, 'UNSUPPORTED_DATABASE_SCHEMA')
            require(conn.execute('PRAGMA foreign_key_check').fetchone() is None, 'INVALID_FOREIGN_KEY')
        with self.schema_component('snapshot_meta_validation', 'snapshot_meta'):
            rows=conn.execute('SELECT * FROM snapshot_meta').fetchall()
            self.metadata['schema_validation_object_counts']['snapshot_meta'] = len(rows)
            require(len(rows)==1 and dict(rows[0]) == dict(singleton=1,schema=c.SCHEMA,database_content_id=m['database_content_id'],content_created_at=m['content_created_at'],selection_policy_sha256=c.POLICY_SHA), 'INVALID_CONTENT_META')
        with self.schema_component('row_count_validation'):
            counts={t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in (set(c.TABLES) | (lg.TABLES if m['contract_revision']==lg.REVISION else set()))}
            self.metadata['schema_validation_object_counts'].update(counts)
            require(counts == m['row_counts'],'ROW_COUNT_MISMATCH')
        with self.schema_component('cross_reference_validation'):
            for table,entity in [('messages','message'),('interactions','interaction')]:
                require(not conn.execute(f'''SELECT 1 FROM {table} m LEFT JOIN source_provenance p ON p.entity_type=? AND p.projection_row_id=m.projection_row_id LEFT JOIN selection_membership s ON s.entity_type=? AND s.projection_row_id=m.projection_row_id WHERE p.projection_row_id IS NULL OR s.projection_row_id IS NULL LIMIT 1''',(entity,entity)).fetchone(),'MISSING_PROVENANCE_MEMBERSHIP')
            for table in ('source_provenance','selection_membership'):
                require(not conn.execute(f'''SELECT 1 FROM {table} p LEFT JOIN messages m ON p.entity_type='message' AND m.projection_row_id=p.projection_row_id LEFT JOIN interactions i ON p.entity_type='interaction' AND i.projection_row_id=p.projection_row_id WHERE m.projection_row_id IS NULL AND i.projection_row_id IS NULL LIMIT 1''').fetchone(),'ORPHAN_PROVENANCE')
            # json_array preserves NULL distinctions, unlike count(DISTINCT column).
            require(not conn.execute('''SELECT 1 FROM messages GROUP BY room,generation,seq HAVING count(DISTINCT json_array(sender,text,timestamp,nonce,sig))>1 LIMIT 1''').fetchone(),'CONFLICTING_SOURCE_POSITION')

    def _rows(self, conn, m):
        evidence_hash=hashlib.sha256()
        @lru_cache(maxsize=4096)
        def text_hash(text):
            before=time.monotonic()
            try: return c.text_hash(text)
            finally: self.metadata.setdefault('schema_validation_breakdown',{}).setdefault('json_parse_canonicalization',0.0); self.metadata['schema_validation_breakdown']['json_parse_canonicalization']+=time.monotonic()-before
        @lru_cache(maxsize=4096)
        def annotation(raw):
            metrics=self.metadata.setdefault('source_provenance_profile', {})
            before=time.monotonic()
            try:
                parsed=c.loads(raw,65536)
            finally:
                metrics['json_parse_seconds']=metrics.get('json_parse_seconds',0.0)+time.monotonic()-before
                metrics['json_parse_calls']=metrics.get('json_parse_calls',0)+1
            before=time.monotonic()
            try: return c.annotations(parsed)
            finally:
                elapsed=time.monotonic()-before
                metrics['annotation_contract_seconds']=metrics.get('annotation_contract_seconds',0.0)+elapsed
                metrics['annotation_contract_calls']=metrics.get('annotation_contract_calls',0)+1
                self.metadata.setdefault('schema_validation_breakdown',{}).setdefault('json_parse_canonicalization',0.0); self.metadata['schema_validation_breakdown']['json_parse_canonicalization']+=elapsed
        for table in ('messages','interactions'):
            began=time.monotonic(); visited=0
            component='message_row_validation' if table=='messages' else 'interaction_row_validation'
            with self.schema_component(component,table):
                for row in conn.execute('SELECT * FROM '+table+' ORDER BY projection_row_id'):
                    self.check(); visited+=1; obj=dict(row); c.string(row['projection_row_id'])
                    if table=='messages':
                        for k in ('room','generation','sender'): c.string(row[k])
                        require(type(row['seq']) is int and row['seq']>=0 and type(row['signed']) is int and row['signed'] in (0,1))
                        require(type(row['text']) is str)
                        for k in ('timestamp','normalized_text','nonce','sig','source_export_path','evidence_id','verification_status'):
                            require(row[k] is None or type(row[k]) is str)
                        for k in ('message_hash','template_normalized_hash','source_export_hash'): c.sha(row[k],True)
                        require(row['message_hash'] is None or row['message_hash']==text_hash(row['text']), 'MESSAGE_HASH_MISMATCH')
                        obj.pop('source_export_path'); obj.pop('source_export_hash')
                    else:
                        for k in ('source_did','target_did','relationship_type'): c.string(row[k])
                        require(type(row['confidence']) in (float,int) and math.isfinite(row['confidence']))
                    before=time.monotonic(); evidence_hash.update(c.canonical([table,obj])+b'\n'); self.metadata.setdefault('schema_validation_breakdown',{}).setdefault('json_parse_canonicalization',0.0); self.metadata['schema_validation_breakdown']['json_parse_canonicalization']+=time.monotonic()-before
            self.metadata['schema_validation_object_counts'][table]=visited
            self.metadata.setdefault('rows_read',{})[table]=visited
            self.metadata['stage_seconds'][table+'_loading']=time.monotonic()-began
            self.metadata.setdefault('stage_peak_rss_bytes',{})[table+'_loading']=rss_bytes()
        began=time.monotonic();visited=0
        provenance_profile=self.metadata.setdefault('source_provenance_profile', {})
        provenance_profile.update(sql_query_count=0, row_fetch_count=0, row_field_validation_calls=0,
                                 message_relationship_checks=0, provenance_canonicalization_calls=0,
                                 raw_hash_field_checks=0, source_locator_field_checks=0)
        with self.schema_component('source_provenance_validation','source_provenance'):
            before=time.monotonic()
            cursor=conn.execute("SELECT p.*,m.sender AS message_sender FROM source_provenance p LEFT JOIN messages m ON p.entity_type='message' AND m.projection_row_id=p.projection_row_id ORDER BY p.entity_type,p.projection_row_id")
            provenance_profile['sql_query_count']=1
            provenance_profile['sql_execute_seconds']=time.monotonic()-before
            iterator=iter(cursor)
            while True:
                before=time.monotonic()
                try: row=next(iterator)
                except StopIteration: break
                provenance_profile['row_fetch_seconds']=provenance_profile.get('row_fetch_seconds',0.0)+time.monotonic()-before
                provenance_profile['row_fetch_count']+=1
                self.check();visited+=1
                before=time.monotonic()
                for k in ('projection_row_id','source_namespace','source_record_locator'): c.string(row[k])
                c.string(row['raw_record_id'],True); c.sha(row['raw_record_sha256'],True)
                provenance_profile['source_locator_field_checks']+=3
                provenance_profile['raw_hash_field_checks']+=1
                if row['scout_event_id'] is not None: c.decimal(row['scout_event_id'])
                provenance_profile['row_field_validation_calls']+=1
                provenance_profile['row_field_validation_seconds']=provenance_profile.get('row_field_validation_seconds',0.0)+time.monotonic()-before
                provenance_profile['annotation_calls']=provenance_profile.get('annotation_calls',0)+1
                a=annotation(row['annotations_json'])
                before=time.monotonic()
                if row['entity_type']=='message':
                    require(row['raw_record_id'] is not None and row['projection_row_id']=='sm1:'+row['raw_record_id'],'INVALID_MESSAGE_ID')
                    family(a,row['message_sender'])
                else: family(a)
                provenance_profile['message_relationship_checks']+=1
                provenance_profile['message_relationship_seconds']=provenance_profile.get('message_relationship_seconds',0.0)+time.monotonic()-before
                obj=dict(row); obj.pop('message_sender'); obj['annotations_json']=a
                before=time.monotonic(); evidence_hash.update(c.canonical(['provenance',obj])+b'\n'); elapsed=time.monotonic()-before
                provenance_profile['provenance_canonicalization_calls']+=1
                provenance_profile['provenance_canonicalization_seconds']=provenance_profile.get('provenance_canonicalization_seconds',0.0)+elapsed
                self.metadata.setdefault('schema_validation_breakdown',{}).setdefault('json_parse_canonicalization',0.0); self.metadata['schema_validation_breakdown']['json_parse_canonicalization']+=elapsed
        info=annotation.cache_info()
        provenance_profile.update(annotation_cache_hits=info.hits,annotation_cache_misses=info.misses,
                                  annotation_cache_maxsize=info.maxsize, annotation_cache_size=info.currsize)
        self.metadata['schema_validation_object_counts']['source_provenance']=visited
        self.metadata.setdefault('rows_read',{})['source_provenance']=visited
        self.metadata['stage_seconds']['source_provenance_loading']=time.monotonic()-began
        self.metadata.setdefault('stage_peak_rss_bytes',{})['source_provenance_loading']=rss_bytes()
        began=time.monotonic();visited=0
        with self.schema_component('selection_membership_validation','selection_membership'):
         for row in conn.execute('SELECT * FROM selection_membership ORDER BY entity_type,projection_row_id'):
            self.check(); visited+=1; require(row['retention_class'] in c.CLASSES)
            first=c.instant(row['first_observed_at']); pins=c.loads(row['pin_roots_json'],65536); c.roots(pins)
            require(first <= c.instant(m['selection_evaluated_at']), 'FUTURE_MEMBERSHIP')
            if row['retain_until'] is not None:
                require(c.instant(row['retain_until']) >= first and c.instant(row['retain_until']) > c.instant(m['selection_evaluated_at']), 'INVALID_EXPIRY')
                require(row['retention_class'] not in PERMANENT and not pins, 'EXPIRABLE_PERMANENT')
                if row['retention_class'] in {'CONTEXT','CAPABILITY_SIGNAL'}:
                    seconds=c.POLICY['parameters']['context_seconds' if row['retention_class']=='CONTEXT' else 'capability_signal_seconds']
                    require(c.instant(row['retain_until'])-first == __import__('datetime').timedelta(seconds=seconds),'INVALID_HORIZON')
        self.metadata['schema_validation_object_counts']['selection_membership']=visited
        self.metadata.setdefault('rows_read',{})['selection_membership']=visited
        self.metadata['stage_seconds']['membership_loading']=time.monotonic()-began
        self.metadata.setdefault('stage_peak_rss_bytes',{})['membership_loading']=rss_bytes()
        self.metadata['routing_input_hash']=evidence_hash.hexdigest()

    def _coverage(self,conn,m,previous):
        with self.schema_component('watermarks_validation','watermarks'):
            for table,fields in [('watermarks','room,generation,count(*) AS record_count,min(seq) AS min_seq,max(seq) AS max_seq')]:
                actual=[dict(r) for r in conn.execute('SELECT * FROM '+table+' ORDER BY room,generation')]
                derived=[dict(r) for r in conn.execute('SELECT '+fields+' FROM messages GROUP BY room,generation ORDER BY room,generation')]
                self.metadata['schema_validation_object_counts']['watermarks']=len(actual)
                require(actual==derived==m['watermarks'],'DATABASE_WATERMARK_MISMATCH')
        with self.schema_component('coverage_history_validation','coverage_history'):
            history=[dict(r) for r in conn.execute('SELECT * FROM coverage_history ORDER BY room,generation')]
            self.metadata['schema_validation_object_counts']['coverage_history']=len(history)
            require(history==m['coverage_history'],'HISTORY_MISMATCH')
        with self.schema_component('coverage_cross_reference_validation'):
            by={(r['room'],r['generation']):r for r in history}
            old={(r['room'],r['generation']):r for r in (previous or {}).get('coverage_history',[])}
            for domain,p in old.items():
                require(domain in by and by[domain]['max_ever_projected_seq']>=p['max_ever_projected_seq'],'CONTINUITY_COVERAGE_REGRESSION')
                if by[domain]['max_ever_projected_seq']==p['max_ever_projected_seq']: require(by[domain]==p,'CONTINUITY_WITNESS_CONFLICT')
            for w in m['watermarks']:
                require((w['room'],w['generation']) in by and by[w['room'],w['generation']]['max_ever_projected_seq']>=w['max_seq'],'HISTORY_BELOW_CURRENT')
            for domain,w in by.items():
                self.check()
                if domain in old and old[domain]==w: continue
                rows=conn.execute('''SELECT m.* FROM messages m JOIN source_provenance p ON p.entity_type='message' AND m.projection_row_id=p.projection_row_id WHERE m.room=? AND m.generation=? AND m.seq=? AND p.source_record_locator=?''',(*domain,w['max_ever_projected_seq'],w['witness_source_locator']))
                require(any(c.digest(dict(r))==w['witness_record_sha256'] for r in rows),'INVALID_COVERAGE_WITNESS')
            require(conn.execute('SELECT min(retain_until) FROM selection_membership').fetchone()[0]==m['next_expiry_at'],'NEXT_EXPIRY_MISMATCH')

    def _proof(self,conn,ref,m):
        c.reference(ref,{'PROJECTED_MESSAGE','LOCAL_ARTIFACT'})
        if ref['kind']=='LOCAL_ARTIFACT': return  # Opaque producer audit assertion, never scoring credit.
        require((ref['source_id'],ref['source_epoch'])==(m['source_checkpoint']['source_id'],m['source_checkpoint']['epoch']),'PROOF_SOURCE_CONFLICT')
        row=conn.execute('''SELECT m.message_hash,CASE WHEN m.message_hash IS NULL THEN m.text END AS text,s.retain_until FROM messages m JOIN selection_membership s ON s.entity_type='message' AND s.projection_row_id=m.projection_row_id WHERE m.projection_row_id=?''',(ref['id'],)).fetchone()
        # _rows already independently checked every non-null raw-text hash.
        require(row and (row['message_hash'] or c.text_hash(row['text']))==ref['sha256'] and row['retain_until'] is None,'INVALID_DURABLE_PROOF')

    def _qualifications(self,conn,m,scratch):
        # Disk-backed uniqueness and graph indexes keep audit size out of Python RAM.
        scratch.executescript('CREATE TABLE firsts (key TEXT PRIMARY KEY); CREATE TABLE edges (source TEXT,target TEXT, PRIMARY KEY(source,target));')
        class Quals:
            def __contains__(_,key): return conn.execute('SELECT 1 FROM durable_qualifications WHERE qualification_id=?',(key,)).fetchone() is not None
            @lru_cache(maxsize=256)
            def __getitem__(_,key):
                row=conn.execute('SELECT record_json FROM durable_qualifications WHERE qualification_id=?',(key,)).fetchone()
                require(row,'MISSING_QUALIFICATION'); return c.loads(row[0],65536)
        quals=Quals()
        @lru_cache(maxsize=256)
        def proof(raw):
            self._proof(conn,c.loads(raw,65536),m)
        scratch.execute('CREATE TABLE semantic_audit (hash TEXT NOT NULL)')
        began=time.monotonic();visited=0
        for row in conn.execute("""SELECT q.*,m.sender AS source_sender,m.message_hash AS source_hash,
            CASE WHEN m.message_hash IS NULL THEN m.text END AS source_text,s.retain_until AS source_expiry,p.scout_event_id AS source_event
            FROM durable_qualifications q LEFT JOIN messages m ON json_extract(q.record_json,'$.source_ref.kind')='PROJECTED_MESSAGE' AND m.projection_row_id=json_extract(q.record_json,'$.source_ref.id')
            LEFT JOIN selection_membership s ON s.entity_type='message' AND s.projection_row_id=m.projection_row_id
            LEFT JOIN source_provenance p ON p.entity_type='message' AND p.projection_row_id=m.projection_row_id ORDER BY q.qualification_id"""):
            self.check();visited+=1; q=c.validate_qualification(c.loads(row['record_json'],65536))
            require(q['qualification_id']==row['qualification_id'],'QUALIFICATION_ID_CONFLICT'); family(q,q['subject_did'])
            require(c.instant(q['qualified_at'])<=c.instant(m['selection_evaluated_at']),'FUTURE_QUALIFICATION')
            cut=q['source_cut']; current=m['source_checkpoint']
            require((cut['source_id'],cut['epoch'])==(current['source_id'],current['epoch']) and int(cut['committed_event_id'])<=int(current['committed_event_id']),'QUALIFICATION_CUT_CONFLICT')
            # Source identity excludes mutable content hash for first-witness uniqueness.
            key={k:q[k] for k in ('source_ref','subject_did','claim','qualification_type','policy_sha256','classifier_version','qualification_policy_version')}
            key['source_ref']={k:v for k,v in key['source_ref'].items() if k!='sha256'}
            try: scratch.execute('INSERT INTO firsts VALUES (?)',(c.digest(key),))
            except sqlite3.IntegrityError: raise SnapshotError('DUPLICATE_FIRST_QUALIFICATION') from None
            semantic={k:q[k] for k in ('source_ref','subject_did','claim','qualification_type','qualification_outcome','policy_version','classifier_version','qualification_policy_version','operator_group','same_operator','independent_reputation','authenticity','correctness','reproducibility','provenance_refs')}
            scratch.execute('INSERT INTO semantic_audit VALUES (?)',(c.digest(semantic),))
            for ref in q['provenance_refs']:
                if ref['kind']=='PROJECTED_MESSAGE' and ref==q['source_ref']:
                    require((ref['source_id'],ref['source_epoch'])==(m['source_checkpoint']['source_id'],m['source_checkpoint']['epoch']),'PROOF_SOURCE_CONFLICT')
                    require(row['source_sender'] is not None and (row['source_hash'] or c.text_hash(row['source_text']))==ref['sha256'] and row['source_expiry'] is None,'INVALID_DURABLE_PROOF')
                else: proof(c.canonical(ref))
            if q['source_ref']['kind']=='PROJECTED_MESSAGE':
                require(q['subject_did']==row['source_sender'] or q['qualification_type']=='NEGATIVE_FACT','QUALIFICATION_SUBJECT_CONFLICT')
                require(q['scout_event_id'] is None or q['scout_event_id']==row['source_event'],'QUALIFICATION_EVENT_ALIAS')
        self.metadata.setdefault('rows_read',{})['durable_qualifications']=visited
        self.metadata['stage_seconds']['qualification_records_loading']=time.monotonic()-began
        self.metadata.setdefault('stage_peak_rss_bytes',{})['qualification_records_loading']=rss_bytes()
        prior_qid=None; last=None; count=0
        class Prior:
            def __len__(_): return count
            def __getitem__(_,index): return last
        began=time.monotonic();visited=0
        for row in conn.execute('SELECT * FROM qualification_events ORDER BY qualification_id,sequence'):
            self.check();visited+=1; e=c.loads(row['event_json'],65536)
            if row['qualification_id']!=prior_qid: prior_qid=row['qualification_id']; last=None; count=0
            c.validate_event(e,Prior(),quals)
            require((e['event_id'],e['qualification_id'],e['sequence'])==(row['event_id'],row['qualification_id'],row['sequence']),'EVENT_ROW_CONFLICT')
            require(c.instant(e['recorded_at'])<=c.instant(m['selection_evaluated_at']),'FUTURE_AUDIT_EVENT')
            for ref in e['proof_refs']+[e['authority_ref']]: proof(c.canonical(ref))
            if e['event_type']=='SUPERSEDED': scratch.execute('INSERT OR IGNORE INTO edges VALUES (?,?)',(e['qualification_id'],e['superseded_by']))
            target=quals[e['qualification_id']]
            semantic={k:e[k] for k in ('event_type','reason_code','proof_refs','authority_ref','qualification_policy_version')}
            semantic['claim']=target['claim']; semantic['source_ref']=target['source_ref']
            if e['superseded_by']:
                semantic['superseding_source']=quals[e['superseded_by']]['source_ref']
            scratch.execute('INSERT INTO semantic_audit VALUES (?)',(c.digest(semantic),))
            last=e; count+=1
        self.metadata.setdefault('rows_read',{})['qualification_events']=visited
        self.metadata['stage_seconds']['qualification_event_loading']=time.monotonic()-began
        self.metadata.setdefault('stage_peak_rss_bytes',{})['qualification_event_loading']=rss_bytes()
        require(not scratch.execute('''WITH RECURSIVE reach(source,target) AS (SELECT source,target FROM edges UNION SELECT r.source,e.target FROM reach r JOIN edges e ON e.source=r.target) SELECT 1 FROM reach WHERE source=target LIMIT 1''').fetchone(),'SUPERSESSION_CYCLE')
        h=hashlib.sha256(self.metadata['routing_input_hash'].encode())
        for row in scratch.execute('SELECT hash FROM semantic_audit ORDER BY hash'):
            self.check(); h.update(row[0].encode())
        self.metadata['routing_input_hash']=h.hexdigest()
        self.metadata['qualification_history']={'qualifications':m['row_counts']['durable_qualifications'],'events':m['row_counts']['qualification_events'],'invalidated':conn.execute("SELECT count(DISTINCT qualification_id) FROM qualification_events WHERE json_extract(event_json,'$.event_type')='INVALIDATED'").fetchone()[0],'audit_only':True,'local_proof_authority':'PRODUCER_ASSERTION_NOT_INDEPENDENTLY_ATTESTED'}

    def _extension(self,old,conn,m,prior_revision='A1'):
        # Both databases are verified Router-private artifacts. Indexed joins
        # compare history without N per-record queries or Python materialization.
        old_path=Path(old.execute('PRAGMA database_list').fetchone()[2])
        conn.execute('ATTACH DATABASE ? AS prior_projection',(old_path.as_uri()+'?mode=ro',))
        from datetime import timedelta
        epoch=datetime(1970,1,1,tzinfo=timezone.utc)
        conn.create_function('router_ticks',1,lambda value:(c.instant(value)-epoch)//timedelta(microseconds=1),deterministic=True)
        def absent(query,code,args=()):
            self.check(); require(conn.execute(query,args).fetchone() is None,code)
        try:
            for table,key,payload in [('durable_qualifications','qualification_id','record_json'),('qualification_events','event_id','event_json')]:
                absent(f'SELECT 1 FROM prior_projection.{table} a LEFT JOIN {table} b ON b.{key}=a.{key} WHERE b.{key} IS NULL OR b.{payload} IS NOT a.{payload} LIMIT 1','CONTINUITY_AUDIT_LOSS')
            join='FROM prior_projection.selection_membership a LEFT JOIN selection_membership b ON b.entity_type=a.entity_type AND b.projection_row_id=a.projection_row_id '
            permanent=','.join('?' for _ in PERMANENT)
            absent('SELECT 1 '+join+f"WHERE b.projection_row_id IS NULL AND (a.retention_class IN ({permanent}) OR json_array_length(a.pin_roots_json)>0 OR a.retain_until IS NULL OR router_ticks(a.retain_until)>router_ticks(?)) LIMIT 1",'CONTINUITY_EARLY_EVIDENCE_LOSS',(*sorted(PERMANENT),m['selection_evaluated_at']))
            present='b.projection_row_id IS NOT NULL AND '
            absent('SELECT 1 '+join+'WHERE '+present+'b.first_observed_at IS NOT a.first_observed_at LIMIT 1','CONTINUITY_FIRST_OBSERVED_CHANGED')
            absent('SELECT 1 '+join+"WHERE "+present+"EXISTS (SELECT 1 FROM json_each(a.pin_roots_json) x WHERE NOT EXISTS (SELECT 1 FROM json_each(b.pin_roots_json) y WHERE json_extract(x.value,'$.kind')=json_extract(y.value,'$.kind') AND json_extract(x.value,'$.id')=json_extract(y.value,'$.id'))) LIMIT 1",'CONTINUITY_PIN_LOSS')
            absent('SELECT 1 '+join+"WHERE "+present+"a.retain_until IS NULL AND b.retain_until IS NOT NULL AND (a.retention_class NOT IN ('WORK_LIFECYCLE','TCLK_LIFECYCLE') OR b.retention_class!=a.retention_class OR json_array_length(a.pin_roots_json)>0 OR ?=0) LIMIT 1",'CONTINUITY_UNVERIFIED_TERMINAL_TRANSITION',(int(bool(self.metadata.get('workflow_closures_validated'))),))
            absent('SELECT 1 '+join+'WHERE '+present+'a.retain_until IS NOT NULL AND b.retain_until IS NOT NULL AND a.retain_until!=b.retain_until AND router_ticks(b.retain_until)<router_ticks(a.retain_until) LIMIT 1','CONTINUITY_EXPIRY_SHORTENED')
            for table,entity,fields in [('messages','message','room generation seq timestamp sender text nonce sig'),('interactions','interaction','source_did target_did relationship_type')]:
                changed=' OR '.join('a.'+k+' IS NOT b.'+k for k in fields.split())
                absent(f"SELECT 1 FROM prior_projection.{table} a JOIN selection_membership s ON s.entity_type=? AND s.projection_row_id=a.projection_row_id LEFT JOIN {table} b ON b.projection_row_id=a.projection_row_id WHERE b.projection_row_id IS NULL OR {changed} LIMIT 1",'CONTINUITY_SOURCE_MUTATION',(entity,))
            changed=' OR '.join('a.'+k+' IS NOT b.'+k for k in ('source_namespace','source_record_locator','raw_record_id'))
            absent("SELECT 1 FROM prior_projection.source_provenance a JOIN selection_membership s ON s.entity_type=a.entity_type AND s.projection_row_id=a.projection_row_id LEFT JOIN source_provenance b ON b.entity_type=a.entity_type AND b.projection_row_id=a.projection_row_id WHERE b.projection_row_id IS NULL OR "+changed+' LIMIT 1','CONTINUITY_SOURCE_MUTATION')
            if m['contract_revision']==lg.REVISION:
                lg.continuity(self,conn,prior_revision)
        finally:
            conn.execute('DETACH DATABASE prior_projection')
            conn.create_function('router_ticks',1,None)

    def _workflows(self, conn, scratch, m):
        rows=conn.execute("SELECT * FROM selection_membership WHERE retain_until IS NOT NULL AND retention_class IN ('WORK_LIFECYCLE','TCLK_LIFECYCLE')")
        first=next(rows,None)
        if first is None:
            self.metadata['workflow_closures_validated']=True
            return
        from projection_workflows import ClosureVerifier
        import itertools
        verifier=ClosureVerifier(conn,scratch,self.check)
        for row in itertools.chain((first,),rows):
            verifier.verify(row,m['selection_evaluated_at'])
        self.metadata['workflow_closures_validated']=True

    def read(self,consume,previous=None,max_age=3600.,now=None,*,allow_stale=False,retain_candidate=True):
        if not math.isfinite(max_age) or max_age<=0: raise ValueError('positive max age required')
        start=time.monotonic(); self.deadline=start+self.timeout
        self.metadata={'root_path':str(self.root),'current_pointer_status':'NOT_CHECKED','stage_seconds':{},'readiness':'INVALID','readiness_phase':'ACQUIRING','max_snapshot_bytes':self.max_bytes,'max_memory_bytes':self.max_memory,'deadline_seconds':self.timeout}
        try:
            with self.stage('pointer_read'):
                self._open_root()
                pointer=_parse(self._read_json_file('current.json',MAX_CURRENT_BYTES),('schema','manifest','manifest_sha256','published_at'),'flop-scout-router-current/v2')
                _basename(pointer['manifest_sha256'],HASH); _basename(pointer['manifest'],rf'manifest-v2-{SNAPSHOT_ID}-{HASH}\.json')
                self.metadata['current_pointer_status']='VALID'
            with self.stage('manifest_read'):
                m=self._manifest(pointer,self._read_json_file(pointer['manifest'],MAX_MANIFEST_BYTES),previous,max_age,now or datetime.now(timezone.utc),not allow_stale)
            old_path=None
            if previous:
                with self.stage('prior_copy_verification'):
                    old_path=self._verify_cache(previous)
                    for archived in self.metadata.get('revision_history',[]):
                        self._verify_cache(archived)
            self.cache_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.candidate-',dir=self.cache_dir) as tmp:
                candidate=Path(tmp)/'projection.sqlite'
                reused=bool(previous and m['sha256']==previous['database_hash'] and m['database_content_id']==previous['database_content_id'])
                if reused: candidate=old_path
                else: self._copy_database(m,candidate)
                with self.connection(candidate) as conn:
                    cached = previous.get('validated_content') if reused else None
                    if cached and cached.get('version') == VALIDATOR_VERSION and cached.get('content_binding') == lg.binding(m):
                        require(cached.get('database_hash') == m['sha256'], 'CONTINUITY_VALIDATION_CACHE')
                        require(cached.get('checksum') == c.digest({k:v for k,v in cached.items() if k!='checksum'}), 'CONTINUITY_VALIDATION_CACHE_CHECKSUM')
                        c.sha(cached.get('routing_input_hash'))
                        require(cached['qualification_history']['qualifications']==m['row_counts']['durable_qualifications']
                                and cached['qualification_history']['events']==m['row_counts']['qualification_events'], 'CONTINUITY_VALIDATION_CACHE_COUNTS')
                        for key in ('routing_input_hash','qualification_history','legacy_generation_audit'):
                            if key in cached: self.metadata[key] = cached[key]
                        if m['contract_revision']==lg.REVISION:
                            audit=cached.get('legacy_generation_audit')
                            require(type(audit) is dict and audit.get('report_count')==m['row_counts']['legacy_generation_reports']
                                    and audit.get('witness_count')==m['row_counts']['legacy_generation_witnesses'],'CONTINUITY_LG2_CACHE_COUNTS')
                        if previous.get('routing_cache'):
                            self.metadata['routing_cache'] = previous['routing_cache']
                        self.metadata['validation_cache_reused'] = True
                    else:
                        with self.stage('integrity_validation'):
                            require([r[0] for r in conn.execute('PRAGMA integrity_check')]==['ok'],'DATABASE_INTEGRITY_FAILED')
                        with self.stage('schema_validation'): self._schema(conn,m); self._rows(conn,m)
                        if m['contract_revision']==lg.REVISION: lg.validate(self,conn,m)
                        with self.stage('watermark_validation'): self._coverage(conn,m,previous)
                        with closing(sqlite3.connect(str(Path(tmp)/'audit-index.sqlite'))) as scratch:
                            scratch.execute('PRAGMA cache_size=-2048'); scratch.execute('PRAGMA temp_store=FILE')
                            interrupted=[]
                            def progress():
                                try: self.check()
                                except (Cancelled,SnapshotError) as exc: interrupted.append(exc); return 1
                                return 0
                            scratch.set_progress_handler(progress,1000)
                            try:
                                with self.stage('qualification_loading'), self.schema_component('durable_qualifications_validation', 'durable_qualifications'):
                                    self._qualifications(conn,m,scratch)
                                with self.stage('workflow_reconstruction'): self._workflows(conn,scratch,m)
                            except sqlite3.Error:
                                if interrupted: raise interrupted[0]
                                raise
                    if old_path and not reused:
                        with self.stage('continuity_comparison'), self.connection(old_path) as old:
                            if self.metadata.get('revision_migration'):
                                require([r[0] for r in old.execute('PRAGMA integrity_check')]==['ok'],'CONTINUITY_ARCHIVE_INTEGRITY')
                                self._schema(old,previous['manifest'])
                            self._extension(old,conn,m,previous['contract_revision'])
                    self.metadata['readiness_phase']='CONTENT_VALIDATED'
                    with self.stage('evidence_materialization'): result=consume(conn)
                self.check()
                final=self.cache_dir/(m['sha256']+'.sqlite')
                if not reused and retain_candidate:
                    os.replace(candidate,final); self.created.add(final)
                    fd=os.open(self.cache_dir,os.O_RDONLY|os.O_DIRECTORY)
                    try: os.fsync(fd)
                    finally: os.close(fd)
                self.metadata['validated_content'] = dict(version=VALIDATOR_VERSION,content_binding=lg.binding(m),legacy_generation_audit=self.metadata.get('legacy_generation_audit'),database_hash=m['sha256'],routing_input_hash=self.metadata['routing_input_hash'],qualification_history=self.metadata['qualification_history'])
                self.metadata['validated_content']['checksum'] = c.digest(self.metadata['validated_content'])
                self.metadata.update(cache_path=str(final) if retain_candidate or reused else None,reused_database=reused,readiness='WARNING_LARGE' if m['size_bytes']>=1024**3 else 'READY')
                self.metadata.update(total_acquisition_seconds=time.monotonic()-start, peak_rss_bytes=rss_bytes())
                return result,dict(self.metadata)
        except (c.ProjectionError, ValueError, TypeError, KeyError, RecursionError):
            raise SnapshotError('INVALID_PROJECTION_CONTRACT') from None
        except SnapshotError as exc:
            self.metadata['readiness']=('TOO_LARGE' if exc.code=='SNAPSHOT_TOO_LARGE' else 'TOO_SLOW' if exc.code=='SNAPSHOT_READ_TIMEOUT' else 'MEMORY_LIMIT' if exc.code=='PROJECTION_MEMORY_LIMIT' else 'STALE' if exc.code=='SNAPSHOT_STALE' else 'UNSUPPORTED_POLICY' if 'UNSUPPORTED' in exc.code else 'CONTINUITY_FAILURE' if exc.code.startswith('CONTINUITY_') else 'INVALID')
            raise
        except OSError as exc:
            import errno
            reason=('DEGRADED_INPUT_MISSING' if exc.errno==errno.ENOENT else 'DEGRADED_INPUT_INVALID' if exc.errno in {errno.ELOOP,errno.ENOTDIR} else 'DEGRADED_INPUT_UNREADABLE')
            raise SnapshotError('CONTINUITY_COPY_UNAVAILABLE' if previous else 'PUBLICATION_UNREADABLE',reason) from None
        finally:
            self.metadata['total_acquisition_seconds']=time.monotonic()-start
            self.metadata['peak_rss_bytes']=rss_bytes()
            if self.metadata.get('readiness') not in {'READY','WARNING_LARGE'}:
                self.cleanup((previous or {}).get('cache_path'),(previous or {}).get('routing_cache',{}).get('path'))

    def epoch_validation_session(self):
        if not self.enable_epoch_v2:
            raise SnapshotError('EPOCH_V2_DISABLED')
        self.cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return EpochValidationSession(self)

    @staticmethod
    def _epoch_descriptor(manifest, manifest_hash):
        return {'publication_id':int(manifest['snapshot_id']),'content_id':int(manifest['database_content_id']),
                'manifest_sha256':manifest_hash,'artifact_sha256':manifest['sha256'],
                'artifact_size_bytes':manifest['size_bytes'],'source_checkpoint':dict(manifest['source_checkpoint']),
                'watermarks':[dict(x) for x in manifest['watermarks']],
                'coverage_history':[dict(x) for x in manifest['coverage_history']]}

    def validate_epoch_bridge(self, session, bridge_root, previous, candidate_transition_sha256, *, now=None):
        """Full A1 validation without profiles, accepted-state writes, or cache promotion."""
        if not isinstance(session, EpochValidationSession) or session.reader is not self or not session.active:
            raise SnapshotError('EPOCH_SESSION_INVALID')
        c.sha(candidate_transition_sha256)
        bridge = ProjectionReader(bridge_root, self.cache_dir, self.check_cancel, self.timeout,
                                  self.max_bytes, self.max_memory, self.activate_lg2)
        try:
            _none, metadata = bridge.read(lambda _conn: None, previous=previous, max_age=3600., now=now,
                                          allow_stale=True, retain_candidate=False)
        finally:
            bridge.close()
        anchor=self._epoch_descriptor(previous['manifest'],previous['manifest_hash'])
        candidate=self._epoch_descriptor(metadata['manifest'],metadata['manifest_hash'])
        binding=epoch_v2.commitment('a1-bridge-binding',{'accepted_anchor':anchor,'bridge_predecessor':candidate})
        watermarks=epoch_v2.commitment('bridge-watermarks',candidate['watermarks'])
        history=epoch_v2.commitment('bridge-history',candidate['coverage_history'])
        audit=epoch_v2.commitment('bridge-audit',{'qualifications':metadata['qualification_history'],'workflow_closures_validated':metadata.get('workflow_closures_validated')})
        verified=epoch_v2.commitment('verified-a1-bridge',{'candidate_transition_sha256':candidate_transition_sha256,'accepted_anchor':anchor,'bridge_predecessor':candidate,'bridge_binding':binding,'watermarks_commitment':watermarks,'history_commitment':history,'audit_commitment':audit})
        self.metadata['epoch_bridge_stage_seconds'] = dict(metadata.get('stage_seconds', {}))
        self.metadata['epoch_bridge_peak_rss_bytes'] = metadata.get('peak_rss_bytes')
        return VerifiedEpochBridge(session,session.token,candidate_transition_sha256,anchor,candidate,binding,verified,dict(candidate['source_checkpoint']),watermarks,history,audit)

    @staticmethod
    def require_verified_epoch_bridge(session, receipt, candidate_transition_sha256, accepted_anchor, bridge_predecessor, bridge_binding):
        if (not isinstance(receipt, VerifiedEpochBridge) or not session.active or receipt._session is not session
                or receipt._token is not session.token or receipt.candidate_transition_sha256 != candidate_transition_sha256
                or receipt.accepted_anchor != accepted_anchor or receipt.bridge_predecessor != bridge_predecessor
                or receipt.bridge_binding != bridge_binding):
            raise SnapshotError('EPOCH_BRIDGE_RECEIPT_INVALID')
        return receipt


def qualification_history(conn, subject_did=None):
    """Stream already validated history from a reader callback's private connection.

    Immutable original records and derived effective validity stay distinct from
    Router current support. No external proof reference is followed.
    """
    query = """SELECT q.qualification_id,q.record_json,e.event_json FROM durable_qualifications q
        LEFT JOIN qualification_events e ON e.qualification_id=q.qualification_id"""
    args=()
    if subject_did is not None:
        query += " WHERE json_extract(q.record_json,'$.subject_did')=?"
        args=(subject_did,)
    query += " ORDER BY q.qualification_id,e.sequence"
    current=None
    for qid,raw,event_raw in conn.execute(query,args):
        if current is None or current['record']['qualification_id'] != qid:
            if current is not None: yield current
            current=dict(record=c.loads(raw,65536),effective_status='VALID',superseded_by=None,event_count=0)
        if event_raw is not None:
            event=c.loads(event_raw,65536)
            if event['event_type']=='INVALIDATED': current['effective_status']='INVALIDATED'
            if event['event_type']=='SUPERSEDED': current['superseded_by']=event['superseded_by']
            current['event_count']+=1
    if current is not None: yield current
