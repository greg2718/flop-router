"""Read-only consumer of immutable, producer-published Scout snapshots.

No SQLite connection is ever opened on a publication artifact.
"""
from contextlib import closing
from datetime import datetime, timezone
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time

MAX_CURRENT_BYTES = 16 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_DATABASE_BYTES = 1024 * 1024 * 1024
MAX_WATERMARKS = 10000
DEFAULT_MAX_AGE = 3600.0
READ_TIMEOUT = 30.0
HASH = r'[0-9a-f]{64}'
SNAPSHOT_ID = r'(?:0|[1-9][0-9]{0,19})'


class Cancelled(Exception):
    pass


class SnapshotError(Exception):
    def __init__(self, code, reason='DEGRADED_INPUT_INVALID'):
        super().__init__(code)
        self.code = code
        self.reason = reason


def utc_timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', value):
        raise SnapshotError('INVALID_UTC_TIMESTAMP')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise SnapshotError('INVALID_UTC_TIMESTAMP') from None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _parse(raw, fields, schema):
    try:
        value = json.loads(raw, object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError):
        raise SnapshotError('INVALID_JSON') from None
    if not isinstance(value, dict) or set(value) != set(fields):
        raise SnapshotError('INVALID_FIELDS')
    if value['schema'] != schema:
        raise SnapshotError('UNSUPPORTED_CONTRACT')
    return value


def _basename(value, pattern):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise SnapshotError('INVALID_ARTIFACT_NAME')
    return value


def validate_watermarks(items):
    if not isinstance(items, list) or len(items) > MAX_WATERMARKS:
        raise SnapshotError('INVALID_WATERMARKS')
    keys = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {'room', 'generation', 'max_seq'}:
            raise SnapshotError('INVALID_WATERMARK')
        if any(not isinstance(item[k], str) or not item[k].strip() or len(item[k]) > 256 for k in ('room', 'generation')):
            raise SnapshotError('INVALID_WATERMARK')
        if type(item['max_seq']) is not int or item['max_seq'] < 0:
            raise SnapshotError('INVALID_WATERMARK')
        keys.append((item['room'], item['generation']))
    if keys != sorted(set(keys)):
        raise SnapshotError('UNORDERED_OR_DUPLICATE_WATERMARK')
    return items


def _continuity(manifest, digest, previous):
    if not previous:
        return
    if int(manifest['snapshot_id']) < int(previous['snapshot_id']):
        raise SnapshotError('SNAPSHOT_REGRESSION')
    if manifest['snapshot_id'] == previous['snapshot_id'] and (
            digest != previous['manifest_hash'] or manifest['sha256'] != previous['database_hash']):
        raise SnapshotError('SNAPSHOT_ID_CONFLICT')
    if utc_timestamp(manifest['produced_at']) < utc_timestamp(previous['produced_at']):
        raise SnapshotError('PRODUCED_AT_REGRESSION')
    current = {(w['room'], w['generation']): w['max_seq'] for w in manifest['watermarks']}
    for watermark in previous.get('watermark_high_water', previous['watermarks']):
        key = (watermark['room'], watermark['generation'])
        if key in current and current[key] < watermark['max_seq']:
            raise SnapshotError('WATERMARK_REGRESSION')


class SnapshotReader:
    def __init__(self, root, check_cancel=lambda: None, timeout=READ_TIMEOUT):
        # abspath normalizes '.'/'..' without dereferencing and hiding symlinks.
        self.root = Path(os.path.abspath(Path(root).expanduser()))
        self.check_cancel = check_cancel
        self.timeout = timeout
        self.root_fd = None
        self.metadata = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.root_fd is not None:
            os.close(self.root_fd)
            self.root_fd = None

    def check(self):
        self.check_cancel()
        if time.monotonic() > self.deadline:
            raise SnapshotError('SNAPSHOT_READ_TIMEOUT', 'DEGRADED_INPUT_UNREADABLE')

    def _open_root(self):
        if self.root_fd is not None:
            return
        if not all(hasattr(os, flag) for flag in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_CLOEXEC')) or os.open not in os.supports_dir_fd:
            raise SnapshotError('DESCRIPTOR_READING_UNSUPPORTED')
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        fd = os.open('/', flags)
        try:
            for component in self.root.parts[1:]:
                self.check()
                next_fd = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            if not os.fstat(fd).st_mode & 0o444:
                raise PermissionError()
            self.root_fd = fd
            fd = None
        finally:
            if fd is not None:
                os.close(fd)

    def _open_file(self, name):
        self.check()
        fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.root_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise SnapshotError('ARTIFACT_NOT_REGULAR')
            if not info.st_mode & 0o444:
                raise PermissionError()
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _read_json_file(self, name, limit):
        fd = self._open_file(name)
        try:
            info = os.fstat(fd)
            if name == 'current.json':
                self.metadata['last_modified'] = datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()
            if info.st_size > limit:
                raise SnapshotError('JSON_TOO_LARGE')
            chunks = []
            total = 0
            while True:
                self.check()
                chunk = os.read(fd, min(65536, limit + 1 - total))
                if not chunk:
                    return b''.join(chunks)
                total += len(chunk)
                if total > limit:
                    raise SnapshotError('JSON_TOO_LARGE')
                chunks.append(chunk)
        finally:
            os.close(fd)

    def _copy_database(self, manifest, destination):
        fd = self._open_file(manifest['database'])
        try:
            if os.fstat(fd).st_size != manifest['size_bytes']:
                raise SnapshotError('DATABASE_SIZE_MISMATCH')
            out = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC, 0o600)
            digest = hashlib.sha256()
            count = 0
            with os.fdopen(out, 'wb') as handle:
                while True:
                    self.check()
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > manifest['size_bytes']:
                        raise SnapshotError('DATABASE_SIZE_MISMATCH')
                    digest.update(chunk)
                    handle.write(chunk)
                if count != manifest['size_bytes'] or digest.hexdigest() != manifest['sha256']:
                    raise SnapshotError('DATABASE_HASH_OR_SIZE_MISMATCH')
                handle.flush()
                os.fsync(handle.fileno())
            self.check()
        finally:
            os.close(fd)

    def _query(self, path, manifest, consume):
        with path.open('rb') as handle:
            header = handle.read(100)
        if len(header) != 100 or header[:16] != b'SQLite format 3\x00' or header[18:20] != b'\x01\x01':
            raise SnapshotError('DATABASE_NOT_STANDALONE')
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.1)) as conn:
            conn.row_factory = sqlite3.Row
            interruption = []
            def progress():
                try:
                    self.check()
                except (Cancelled, SnapshotError) as exc:
                    interruption.append(exc)
                    return 1
                return 0
            conn.set_progress_handler(progress, 1000)
            try:
                conn.execute('PRAGMA query_only=ON')
                if [row[0] for row in conn.execute('PRAGMA integrity_check')] != ['ok']:
                    raise SnapshotError('DATABASE_INTEGRITY_FAILED')
                if conn.execute('PRAGMA user_version').fetchone()[0] != 1:
                    raise SnapshotError('UNSUPPORTED_DATABASE_SCHEMA')
                required = {
                    'messages': {'room','seq','timestamp','sender','signed','text','normalized_text','template_normalized_hash'},
                    'interactions': {'source_did','target_did','relationship_type','confidence'},
                }
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table, fields in required.items():
                    columns = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
                    if table not in tables or not fields <= columns:
                        raise SnapshotError('INVALID_DATABASE_SCHEMA')
                if conn.execute("SELECT 1 FROM messages WHERE typeof(room)!='text' OR trim(room)='' OR typeof(seq)!='integer' OR seq<0 LIMIT 1").fetchone():
                    raise SnapshotError('INVALID_DATABASE_WATERMARK')
                columns = {row[1] for row in conn.execute('PRAGMA table_info(messages)')}
                generation = "COALESCE(CAST(generation AS TEXT), 'UNKNOWN_LEGACY')" if 'generation' in columns else "'UNKNOWN_LEGACY'"
                rows = conn.execute(f'SELECT room,{generation},MAX(seq) FROM messages GROUP BY room,{generation} ORDER BY room,{generation}')
                watermarks = [dict(room=row[0], generation=row[1], max_seq=row[2]) for row in rows]
                validate_watermarks(watermarks)
                if watermarks != manifest['watermarks']:
                    raise SnapshotError('DATABASE_WATERMARK_MISMATCH')
                self.check()
                result = consume(conn)
                self.check()
                return result
            except sqlite3.Error:
                if interruption:
                    raise interruption[0]
                raise SnapshotError('DATABASE_INTEGRITY_OR_QUERY_FAILED') from None

    def read(self, consume, previous=None, max_age=DEFAULT_MAX_AGE, now=None):
        if not math.isfinite(max_age) or max_age <= 0:
            raise ValueError('max snapshot age must be finite and positive')
        self.deadline = time.monotonic() + self.timeout
        self.metadata = {'root_path': str(self.root), 'current_pointer_status': 'NOT_CHECKED'}
        try:
            self._open_root()
            pointer = _parse(self._read_json_file('current.json', MAX_CURRENT_BYTES),
                             ('schema','manifest','manifest_sha256','published_at'), 'flop-scout-router-current/v1')
            _basename(pointer['manifest_sha256'], HASH)
            _basename(pointer['manifest'], rf'manifest-{SNAPSHOT_ID}-{HASH}\.json')
            if not pointer['manifest'].endswith('-' + pointer['manifest_sha256'] + '.json'):
                raise SnapshotError('MANIFEST_FILENAME_HASH_MISMATCH')
            published_at = utc_timestamp(pointer['published_at'])
            self.metadata['current_pointer_status'] = 'VALID'
            raw = self._read_json_file(pointer['manifest'], MAX_MANIFEST_BYTES)
            digest = hashlib.sha256(raw).hexdigest()
            if digest != pointer['manifest_sha256']:
                raise SnapshotError('MANIFEST_HASH_MISMATCH')
            manifest = _parse(raw, ('schema','snapshot_id','database','sha256','size_bytes','database_schema_version','produced_at','watermarks'),
                              'flop-scout-router-snapshot/v1')
            _basename(manifest['snapshot_id'], SNAPSHOT_ID)
            _basename(manifest['sha256'], HASH)
            if pointer['manifest'] != f"manifest-{manifest['snapshot_id']}-{digest}.json":
                raise SnapshotError('MANIFEST_FILENAME_ID_MISMATCH')
            if manifest['database'] != f"observer-{manifest['snapshot_id']}-{manifest['sha256']}.sqlite":
                raise SnapshotError('DATABASE_FILENAME_MISMATCH')
            if type(manifest['size_bytes']) is not int or not 0 <= manifest['size_bytes'] <= MAX_DATABASE_BYTES:
                raise SnapshotError('INVALID_DATABASE_SIZE')
            if manifest['database_schema_version'] != 'scout-observer/v1':
                raise SnapshotError('UNSUPPORTED_DATABASE_SCHEMA')
            produced_at = utc_timestamp(manifest['produced_at'])
            now = now or datetime.now(timezone.utc)
            age = (now - produced_at).total_seconds()
            if produced_at > published_at or (published_at - now).total_seconds() > 60:
                raise SnapshotError('INVALID_PUBLICATION_TIME')
            validate_watermarks(manifest['watermarks'])
            self.metadata.update(snapshot_id=manifest['snapshot_id'], manifest_hash=digest, database_hash=manifest['sha256'],
                                 produced_at=manifest['produced_at'], age_seconds=max(0.0, age),
                                 database_schema_version=manifest['database_schema_version'], watermarks=manifest['watermarks'])
            _continuity(manifest, digest, previous)
            if age > max_age:
                raise SnapshotError('SNAPSHOT_STALE', 'DEGRADED_INPUT_STALE')
            if Path(tempfile.gettempdir()).resolve().is_relative_to(self.root):
                raise SnapshotError('TEMPORARY_DIRECTORY_INSIDE_PUBLICATION')
            with tempfile.TemporaryDirectory(prefix='flop-router-snapshot-') as temporary:
                destination = Path(temporary) / 'observer.sqlite'
                self._copy_database(manifest, destination)
                result = self._query(destination, manifest, consume)
            high = {(w['room'],w['generation']): w['max_seq'] for w in (previous or {}).get('watermark_high_water', (previous or {}).get('watermarks', []))}
            high.update({(w['room'],w['generation']):w['max_seq'] for w in manifest['watermarks']})
            self.metadata['watermark_high_water'] = [dict(room=k[0],generation=k[1],max_seq=n) for k,n in sorted(high.items())]
            return result, dict(self.metadata)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise SnapshotError('PUBLICATION_MISSING', 'DEGRADED_INPUT_MISSING') from None
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise SnapshotError('SYMLINK_OR_NON_DIRECTORY') from None
            raise SnapshotError('PUBLICATION_UNREADABLE', 'DEGRADED_INPUT_UNREADABLE') from None
