"""Producer fixtures and consumer contract tests; no live Scout access."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import scout_snapshot as ss


def make_database(path):
    with sqlite3.connect(path) as conn:
        conn.executescript('CREATE TABLE messages (room TEXT, seq INTEGER, timestamp TEXT, sender TEXT, signed INTEGER, text TEXT, normalized_text TEXT, template_normalized_hash TEXT, generation TEXT); CREATE TABLE interactions (source_did TEXT,target_did TEXT,relationship_type TEXT,confidence REAL);')


def atomic_write(path, data):
    temporary = path.with_name('.' + path.name + '.tmp')
    with temporary.open('wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def publish_snapshot(root, database=None, snapshot_id='1', produced_at=None, manifest_changes=None, database_bytes=None):
    root.mkdir(parents=True, exist_ok=True)
    produced_at = produced_at or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    if database_bytes is None:
        source = database or root.parent / ('fixture-source-' + root.name + '.sqlite')
        if database is None and not source.exists():
            make_database(source)
        destination = root.parent / ('fixture-backup-' + root.name + '.sqlite')
        destination.unlink(missing_ok=True)
        src = sqlite3.connect(source)
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
            dst.execute('PRAGMA journal_mode=DELETE')
            dst.execute('PRAGMA user_version=1')
            dst.commit()
            columns = {r[1] for r in dst.execute('PRAGMA table_info(messages)')}
            generation = "COALESCE(CAST(generation AS TEXT), 'UNKNOWN_LEGACY')" if 'generation' in columns else "'UNKNOWN_LEGACY'"
            rows = dst.execute(f'SELECT room,{generation},MAX(seq) FROM messages GROUP BY room,{generation} ORDER BY room,{generation}').fetchall()
        finally:
            src.close(); dst.close()
        data = destination.read_bytes()
        destination.unlink()
    else:
        data = database_bytes
        rows = []
    digest = hashlib.sha256(data).hexdigest()
    manifest = dict(schema='flop-scout-router-snapshot/v1', snapshot_id=snapshot_id,
                    database=f'observer-{snapshot_id}-{digest}.sqlite', sha256=digest, size_bytes=len(data),
                    database_schema_version='scout-observer/v1', produced_at=produced_at,
                    watermarks=[dict(room=r, generation=g, max_seq=n) for r,g,n in rows])
    manifest.update(manifest_changes or {})
    atomic_write(root / f'observer-{snapshot_id}-{digest}.sqlite', data)
    raw = json.dumps(manifest, sort_keys=True).encode()
    manifest_hash = hashlib.sha256(raw).hexdigest()
    manifest_name = f'manifest-{snapshot_id}-{manifest_hash}.json'
    atomic_write(root / manifest_name, raw)
    pointer = dict(schema='flop-scout-router-current/v1', manifest=manifest_name,
                   manifest_sha256=manifest_hash, published_at=produced_at)
    atomic_write(root / 'current.json', json.dumps(pointer).encode())
    return manifest, pointer


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / 'publication'
        self.manifest, self.pointer = publish_snapshot(self.root)

    def read(self, **kwargs):
        with ss.SnapshotReader(self.root) as reader:
            return reader.read(lambda conn: conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0], **kwargs)

    def assert_invalid(self, **kwargs):
        with self.assertRaises(ss.SnapshotError) as caught:
            self.read(**kwargs)
        self.assertEqual(caught.exception.reason, 'DEGRADED_INPUT_INVALID')

    def test_valid_empty_private_snapshot_no_publication_changes(self):
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in self.root.iterdir()}
        def inspect(conn):
            filename = Path(conn.execute('PRAGMA database_list').fetchone()[2])
            self.assertNotEqual(filename.parent, self.root)
            self.assertEqual(filename.stat().st_mode & 0o777, 0o600)
            self.assertEqual(filename.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(conn.execute('PRAGMA query_only').fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute('CREATE TABLE forbidden (x)')
            return filename
        with ss.SnapshotReader(self.root) as reader:
            filename, metadata = reader.read(inspect)
        self.assertFalse(filename.exists())
        self.assertEqual(metadata['snapshot_id'], '1')
        self.assertEqual(metadata['watermarks'], [])
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in self.root.iterdir()})

    def test_active_wal_producer_backup_and_generation_zero(self):
        source = self.base / 'wal.sqlite'; make_database(source)
        conn = sqlite3.connect(source)
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)', ('room', 7, None, 'did:key:z6MkWorker', 1, 'text', 'text', '', 0))
            conn.commit()
            publish_snapshot(self.root, source, snapshot_id='2')
        finally:
            conn.close()
        count, metadata = self.read()
        self.assertEqual(count, 1)
        self.assertEqual(metadata['watermarks'], [dict(room='room', generation='0', max_seq=7)])
        self.assertFalse(any(p.name.endswith(('-wal', '-shm', '-journal')) for p in self.root.iterdir()))

    def test_symlinks_rejected_for_root_and_all_artifacts(self):
        link = self.base / 'linked'; link.symlink_to(self.root, target_is_directory=True)
        with ss.SnapshotReader(link) as reader, self.assertRaises(ss.SnapshotError):
            reader.read(lambda c: None)
        for name in ('current.json', self.pointer['manifest'], self.manifest['database']):
            with self.subTest(name=name):
                path = self.root / name; held = self.base / name
                path.rename(held); path.symlink_to(held)
                self.assert_invalid()
                path.unlink(); held.rename(path)

    def test_retained_root_prevents_parent_replacement(self):
        replacement = self.base / 'replacement'; publish_snapshot(replacement, snapshot_id='999')
        with ss.SnapshotReader(self.root) as reader:
            reader.read(lambda c: None)
            held = self.base / 'held'; self.root.rename(held)
            self.root.symlink_to(replacement, target_is_directory=True)
            _, metadata = reader.read(lambda c: None)
            self.assertEqual(metadata['snapshot_id'], '1')

    def test_descriptor_copy_does_not_reopen_replaced_database(self):
        original = ss.os.read
        fired = False
        def replace_after_open(fd, size):
            nonlocal fired
            info = os.fstat(fd)
            path = self.root / self.manifest['database']
            if not fired and info.st_ino == path.stat().st_ino:
                fired = True
                path.rename(self.base / 'original.sqlite')
                path.write_bytes(b'wrong artifact')
            return original(fd, size)
        with patch.object(ss.os, 'read', side_effect=replace_after_open):
            count, _ = self.read()
        self.assertTrue(fired)
        self.assertEqual(count, 0)
        self.assert_invalid()

    def test_pointer_strict_parsing_and_names(self):
        original = dict(self.pointer)
        for value in ('', '.', '..', '../x', '/tmp/x', 'x/y', 'x\\y', 'x\0y', 'manifest-1-' + 'A'*64 + '.json'):
            pointer = {**original, 'manifest': value}
            atomic_write(self.root / 'current.json', json.dumps(pointer).encode())
            self.assert_invalid()
        for payload in (b'[]', b'{}', b'{"schema":1,"schema":2}', b'x' * (ss.MAX_CURRENT_BYTES + 1)):
            atomic_write(self.root / 'current.json', payload); self.assert_invalid()

    def test_hash_and_size_mismatches(self):
        (self.root / self.pointer['manifest']).write_bytes(b'{}')
        self.assert_invalid()
        self.manifest, self.pointer = publish_snapshot(self.root, snapshot_id='2')
        (self.root / self.manifest['database']).write_bytes(b'corrupt')
        self.assert_invalid()
        publish_snapshot(self.root, snapshot_id='3', manifest_changes={'size_bytes': 1})
        self.assert_invalid()

    def test_schema_integrity_and_watermark_validation(self):
        for changes in ({'database_schema_version':'unsupported'}, {'schema':'unsupported'},
                        {'size_bytes':True}, {'snapshot_id':'01'}, {'produced_at':'2026-09-08T00:00:00'},
                        {'watermarks':[dict(room='x',generation='0',max_seq=0)]},
                        {'watermarks':[dict(room='x',generation='0',max_seq=0)]*2},
                        {'watermarks':[dict(room='x',generation='0',max_seq=-1)]}):
            with self.subTest(changes=changes):
                publish_snapshot(self.root, manifest_changes=changes); self.assert_invalid()
        publish_snapshot(self.root, database_bytes=b'not sqlite'); self.assert_invalid()

    def test_continuity_conflicts_regression_stale(self):
        _, accepted = self.read()
        for changes in ({'snapshot_id':'0'}, {'snapshot_id':'1', 'produced_at':'2026-01-01T00:00:00Z'}):
            publish_snapshot(self.root, **changes)
            self.assert_invalid(previous=accepted, max_age=10**9)
        publish_snapshot(self.root, snapshot_id='2', produced_at='2026-01-01T00:00:00Z')
        self.assert_invalid(previous=accepted, max_age=10**9)
        with self.assertRaises(ss.SnapshotError) as caught:
            self.read(max_age=1)
        self.assertEqual(caught.exception.reason, 'DEGRADED_INPUT_STALE')

    def test_cancellation_and_error_cleanup(self):
        captured = []
        def fail(conn):
            captured.append(Path(conn.execute('PRAGMA database_list').fetchone()[2]))
            raise ss.Cancelled()
        with ss.SnapshotReader(self.root) as reader, self.assertRaises(ss.Cancelled):
            reader.read(fail)
        self.assertTrue(captured)
        self.assertFalse(captured[0].exists())
        with ss.SnapshotReader(self.root, check_cancel=lambda: (_ for _ in ()).throw(ss.Cancelled())) as reader, self.assertRaises(ss.Cancelled):
            reader.read(lambda c: None)

    def test_nonregular_artifacts_and_oversized_manifest_rejected(self):
        path = self.root / 'current.json'
        path.unlink(); path.mkdir(); self.assert_invalid()
        path.rmdir()
        self.manifest,self.pointer=publish_snapshot(self.root)
        (self.root/self.pointer['manifest']).write_bytes(b' '*(ss.MAX_MANIFEST_BYTES+1))
        self.assert_invalid()

    def test_manifest_filename_traversal_and_timestamp_fields(self):
        for changes in ({'database':'../observer.sqlite'}, {'database':'/tmp/observer.sqlite'},
                        {'sha256':'A'*64}, {'size_bytes':-1}, {'size_bytes':ss.MAX_DATABASE_BYTES+1},
                        {'produced_at':'2026-09-08T00:00:00+01:00'}, {'snapshot_id':3},
                        {'watermarks':[dict(room='x',generation=0,max_seq=1)]}):
            publish_snapshot(self.root,manifest_changes=changes)
            self.assert_invalid()

    def test_actual_schema_version_and_integrity_failure(self):
        source=self.base/'bad.sqlite';make_database(source)
        with sqlite3.connect(source) as conn:conn.execute('PRAGMA user_version=1');conn.execute('DROP TABLE interactions')
        publish_snapshot(self.root,database_bytes=source.read_bytes());self.assert_invalid()
        with sqlite3.connect(source) as conn:conn.execute('CREATE TABLE interactions (source_did TEXT)')
        publish_snapshot(self.root,database_bytes=source.read_bytes());self.assert_invalid()
        self.manifest,self.pointer=publish_snapshot(self.root)
        data=bytearray((self.root/self.manifest['database']).read_bytes());data[100]=0
        publish_snapshot(self.root,database_bytes=bytes(data));self.assert_invalid()

    def test_watermark_regression_and_same_id_hash_conflict(self):
        source=self.base/'watermarks.sqlite';make_database(source)
        with sqlite3.connect(source) as conn:
            conn.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)',('room',5,None,'did:key:z6MkWorker',1,'text','text','',0))
        publish_snapshot(self.root,source,snapshot_id='2')
        _,accepted=self.read()
        with sqlite3.connect(source) as conn:conn.execute('UPDATE messages SET seq=4')
        publish_snapshot(self.root,source,snapshot_id='3')
        self.assert_invalid(previous=accepted)
        publish_snapshot(self.root,source,snapshot_id='2')
        with self.assertRaises(ss.SnapshotError) as caught:self.read(previous=accepted)
        self.assertEqual(caught.exception.code,'SNAPSHOT_ID_CONFLICT')

    def test_identical_pointer_reverified_and_legacy_generation_distinct(self):
        source=self.base/'generations.sqlite';make_database(source)
        with sqlite3.connect(source) as conn:
            conn.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)',[
                ('room',1,None,'did:key:z6MkWorker',1,'text','text','',None),
                ('room',2,None,'did:key:z6MkWorker',1,'text','text','',0)])
        manifest,_=publish_snapshot(self.root,source)
        count,accepted=self.read()
        self.assertEqual(count,2)
        self.assertEqual([w['generation'] for w in accepted['watermarks']],['0','UNKNOWN_LEGACY'])
        count,again=self.read(previous=accepted)
        self.assertEqual(again['database_hash'],accepted['database_hash'])
        (self.root/manifest['database']).write_bytes(b'changed')
        self.assert_invalid(previous=accepted)

    def test_copy_timeout_and_exception_cleanup(self):
        with ss.SnapshotReader(self.root,timeout=-1) as reader, self.assertRaises(ss.SnapshotError) as caught:
            reader.read(lambda conn:None)
        self.assertEqual(caught.exception.code,'SNAPSHOT_READ_TIMEOUT')
        captured=[]
        def fail(conn):
            captured.append(Path(conn.execute('PRAGMA database_list').fetchone()[2]));raise ValueError('fixture failure')
        with ss.SnapshotReader(self.root) as reader,self.assertRaises(ValueError):reader.read(fail)
        self.assertFalse(captured[0].exists())

    def test_sqlite_never_opens_publication_or_companions(self):
        original=sqlite3.connect;calls=[]
        def connect(filename,*args,**kwargs):
            calls.append(filename)
            return original(filename,*args,**kwargs)
        # Companions are deliberately hostile; a standalone consumer must ignore them.
        for suffix in ('-wal','-shm','-journal'):
            (self.root/(self.manifest['database']+suffix)).symlink_to('/nonexistent/never-read')
        with patch.object(ss.sqlite3,'connect',side_effect=connect):self.read()
        self.assertEqual(len(calls),1)
        self.assertNotIn(str(self.root),str(calls[0]))
        self.assertTrue(str(calls[0]).endswith('?mode=ro'))

    def test_temp_destination_cannot_be_inside_publication(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        with patch.object(ss.tempfile,'gettempdir',return_value=str(self.root)):
            self.assert_invalid()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})

    def test_concurrent_producer_backup_is_transactionally_consistent(self):
        import threading
        source=self.base/'concurrent.sqlite';make_database(source)
        started=threading.Event();errors=[]
        def writer():
            conn=sqlite3.connect(source)
            try:
                conn.execute('PRAGMA journal_mode=WAL')
                for batch in range(40):
                    with conn:
                        conn.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)',[
                            ('room',batch*2+i,None,'did:key:z6MkWorker',1,'text','text','',0) for i in (0,1)])
                    started.set()
                    threading.Event().wait(0.001)
            except BaseException as exc:errors.append(exc)
            finally:conn.close()
        thread=threading.Thread(target=writer);thread.start()
        try:
            self.assertTrue(started.wait(2))
            for number in range(2,5):
                publish_snapshot(self.root,source,snapshot_id=str(number))
                count,metadata=self.read()
                self.assertEqual(count%2,0)
                self.assertEqual(metadata['watermarks'][0]['max_seq'],count-1)
        finally:thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors,[])
