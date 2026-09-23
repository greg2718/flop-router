"""Crash-safe, explicitly disposable Epoch V2 store. No production worker wiring.

The state file is the sole commit point. Generation files are immutable and
fully synced before it can name them. A journal records both possible state
hashes; recovery accepts exactly one, never inferring completion from a cache.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid

from scout_epoch_evidence import open_held
from scout_snapshot import SnapshotError

MAX_STATE = 4 * 1024 * 1024


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def check(ok, code='EPOCH_STORE_INVALID'):
    if not ok:
        raise SnapshotError(code)


def read_private(path, limit=MAX_STATE):
    fd = open_held(path)
    try:
        before = os.fstat(fd)
        check(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
              and not before.st_mode & 0o022 and before.st_size <= limit)
        chunks = []
        remaining = limit + 1
        while remaining:
            part = os.read(fd, min(1024 * 1024, remaining))
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        raw = b''.join(chunks)
        after = os.fstat(fd)
        check(len(raw) == before.st_size <= limit and
              (before.st_ino, before.st_mtime_ns, before.st_ctime_ns) ==
              (after.st_ino, after.st_mtime_ns, after.st_ctime_ns))
        return raw
    finally:
        os.close(fd)


class DisposableEpochStore:
    """Requires an operator-created private disposable store, never creates one.

    `disposable.json` must contain {"schema":"router-disposable-epoch-store/v1"}.
    Initial state.json is a copy of Router durable state, with its accepted
    cache_path pointing at a private copy under this directory. No session
    objects or tokens are persisted. The fault hook is for crash-boundary tests.
    """
    def __init__(self, root, fault=lambda boundary: None):
        self.root = Path(root)
        check(self.root.is_absolute() and self.root.resolve() == self.root)
        info = self.root.stat()
        check(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
              and not info.st_mode & 0o077)
        check(json.loads(read_private(self.root / 'disposable.json')) ==
              {'schema': 'router-disposable-epoch-store/v1'})
        self.fault = fault
        self.state_path = self.root / 'state.json'

    @contextmanager
    def locked(self):
        fd = os.open(self.root / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            check(stat.S_ISREG(os.fstat(fd).st_mode))
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def sync(self, path, label):
        self.fault(label + ':before_fsync')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        self.fault(label + ':after_fsync')

    def write(self, path, raw, label):
        self.fault(label + ':before_write')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as out:
                out.write(raw)
                out.flush()
                self.fault(label + ':after_write')
                self.fault(label + ':before_fsync')
                os.fsync(fd)
                self.fault(label + ':after_fsync')
        finally:
            os.close(fd)

    def rename(self, source, target, label):
        self.fault(label + ':before_rename')
        os.replace(source, target)
        self.fault(label + ':after_rename')

    def load(self):
        raw = read_private(self.state_path)
        state = json.loads(raw)
        previous = state.get('last_accepted_projection_v2')
        check(type(previous) is dict, 'EPOCH_ACCEPTED_STATE_REQUIRED')
        cache = Path(previous.get('cache_path', ''))
        check(cache.is_absolute() and cache.is_relative_to(self.root)
              and cache.name == previous.get('database_hash', '') + '.sqlite')
        # Stream the cache under a held descriptor; never trust persisted checks.
        fd = open_held(cache)
        try:
            info = os.fstat(fd)
            check(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                  and not info.st_mode & 0o022
                  and 0 < info.st_size <= 4 * 1024**3
                  and info.st_size == previous.get('size_bytes'))
            h = hashlib.sha256()
            for chunk in iter(lambda: os.read(fd, 1024 * 1024), b''):
                h.update(chunk)
            check(h.hexdigest() == previous['database_hash'], 'EPOCH_STORE_CACHE_HASH')
            after = os.fstat(fd)
            check((info.st_size, info.st_mtime_ns, info.st_ctime_ns) ==
                  (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'EPOCH_STORE_CACHE_CHANGED')
        finally:
            os.close(fd)
        if previous.get('contract_revision') == 'A1-EPOCH-V2':
            proof = read_private(cache.parent / 'commitments.json')
            check(digest(proof) == state.get('epoch_commitments_sha256'), 'EPOCH_STORE_RECOVERY_HASH')
            check(read_private(cache.parent / 'accepted.json') == raw, 'EPOCH_STORE_RECOVERY_HASH')
        return raw, state

    def recover(self):
        """Caller holds lock. A corrupt/ambiguous journal always fails closed."""
        journal = self.root / 'journal.json'
        if journal.exists():
            j = json.loads(read_private(journal))
            check(set(j) == {'schema', 'generation', 'before', 'after', 'files'}
                  and j['schema'] == 'router-epoch-journal/v1')
            name = j['generation']
            check(type(name) is str and len(name) == 36 and name.startswith('gen-')
                  and all(c in '0123456789abcdef' for c in name[4:]))
            generation = self.root / name
            current = digest(read_private(self.state_path))
            if current == j['before']:
                if generation.exists():
                    check(not generation.is_symlink())
                    shutil.rmtree(generation)
            elif current == j['after']:
                check(type(j['files']) is dict and set(j['files']) == {'accepted.json', 'commitments.json', 'cache.sqlite'})
                for filename, expected in j['files'].items():
                    path = generation / filename
                    if filename == 'cache.sqlite':
                        _, state = self.load()
                        path = Path(state['last_accepted_projection_v2']['cache_path'])
                        check(path.parent == generation)
                        actual = state['last_accepted_projection_v2']['database_hash']
                    else:
                        actual = digest(read_private(path))
                    check(actual == expected, 'EPOCH_STORE_RECOVERY_HASH')
                check(read_private(generation / 'accepted.json') == read_private(self.state_path))
                self.sync(self.root, 'recovery_commit')
            else:
                raise SnapshotError('EPOCH_STORE_AMBIGUOUS_COMMIT')
            journal.unlink()
            self.sync(self.root, 'recovery_cleanup')
        # A crash before journal publication can leave only private staging.
        for path in self.root.glob('.stage-*'):
            check(path.is_dir() and not path.is_symlink())
            shutil.rmtree(path)
        for name in ('.journal-next', '.state-next'):
            path = self.root / name
            if path.exists():
                check(not path.is_symlink())
                path.unlink()
        return self.load()

    def commit(self, before, state, artifact, commitments):
        """Caller holds lock; profiles and all evidence checks already succeeded."""
        check(read_private(self.state_path) == before, 'EPOCH_STORE_CONCURRENT_CHANGE')
        token = uuid.uuid4().hex
        stage = self.root / ('.stage-' + token)
        generation = self.root / ('gen-' + token)
        stage.mkdir(mode=0o700)
        prior = state['last_accepted_projection_v2']
        cache_name = prior['database_hash'] + '.sqlite'
        prior['cache_path'] = str(generation / cache_name)
        proof = encoded(commitments)
        state['epoch_commitments_sha256'] = digest(proof)
        raw = encoded(state)
        check(len(raw) <= MAX_STATE and len(proof) <= MAX_STATE, 'EPOCH_STORE_STATE_BOUNDS')
        self.fault('cache:before_write')
        hasher = hashlib.sha256()
        with open(artifact, 'rb') as source, open(stage / cache_name, 'xb') as target:
            os.chmod(stage / cache_name, 0o600)
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                hasher.update(chunk)
                target.write(chunk)
            target.flush()
            self.fault('cache:after_write')
            self.fault('cache:before_fsync')
            os.fsync(target.fileno())
            self.fault('cache:after_fsync')
        check(hasher.hexdigest() == prior['database_hash'], 'EPOCH_STAGED_CACHE_HASH')
        self.write(stage / 'accepted.json', raw, 'accepted')
        self.write(stage / 'commitments.json', proof, 'commitments')
        self.sync(stage, 'stage')
        j = {'schema': 'router-epoch-journal/v1', 'generation': generation.name,
             'before': digest(before), 'after': digest(raw),
             'files': {'accepted.json': digest(raw), 'commitments.json': digest(proof),
                       'cache.sqlite': prior['database_hash']}}
        self.write(self.root / '.journal-next', encoded(j), 'journal')
        self.rename(self.root / '.journal-next', self.root / 'journal.json', 'journal')
        self.sync(self.root, 'journal_directory')
        self.rename(stage, generation, 'generation')
        self.sync(self.root, 'generation_directory')
        self.write(self.root / '.state-next', raw, 'state')
        self.rename(self.root / '.state-next', self.state_path, 'commit')
        self.sync(self.root, 'commit_directory')
        # Keep the journal until restart/recovery verifies the completed commit.
        return state
