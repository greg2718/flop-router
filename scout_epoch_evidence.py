"""Read-only, independent reconstruction of compact Epoch V2 evidence.

This module returns audit facts, never an acceptance capability. Every supplied
path is explicit. SQLite reads use disposable private snapshots streamed from
held, hash-verified descriptors; no input path is reopened by SQLite. There are
no Scout imports, network calls, profiles, or persistent Router state writes.
"""
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
import tempfile
import time
from types import SimpleNamespace

import projection_contract as c
import scout_epoch_archive_validator as archive
import scout_epoch_v2_validator as v2
from scout_projection import ProjectionReader, SCHEMA_SQL, PERMANENT
from scout_snapshot import SnapshotError
from projection_workflows import ClosureVerifier

MAX_RECORDS = 50000
MAX_SQLITE_BYTES = 1024 ** 3
MAX_JSON_BYTES = 16 * 1024 ** 2
MAX_CELL_BYTES = 65536
CACHE_TEXT = {'messages': 'text', 'evidence_records': 'text',
              'tclk_frames': 'raw_text', 'kibble_events': 'exact_text'}
SOURCE_COLUMNS = {
    'source_evidence_metadata': 'singleton schema revision canonical_ddl_sha256 accepted_anchor_json bridge_predecessor_json source_checkpoint_json previous_bridge_binding_sha256 recovery_commitment_sha256 raw_record_count observed_event_count cache_link_count',
    'raw_records': 'raw_record_id source room generation reported_generation seq sender_did signature nonce raw_text raw_text_sha256 raw_record_json',
    'observed_event_witnesses': 'event_id raw_record_id raw_text_sha256',
    'compatibility_links': 'cache_table cache_rowid raw_record_id raw_text_sha256',
    'messages': 'cache_rowid room seq text sender',
    'evidence_records': 'cache_rowid room generation seq text did sig nonce',
    'tclk_frames': 'cache_rowid room generation seq raw_text transport_did',
    'kibble_events': 'cache_rowid room generation seq exact_text sender_did',
}


@dataclass(frozen=True, slots=True, repr=False)
class EvidenceSummary:
    """Redacted immutable diagnostic facts, not a receipt or authority token."""
    counts: tuple
    commitments: tuple
    descriptor_identities: tuple

    def __repr__(self):
        return '<EvidenceSummary redacted; no acceptance authority>'

    def __reduce__(self):
        raise TypeError('EvidenceSummary is an in-process diagnostic, not a capability')


class EvidenceError(ValueError):
    def __init__(self, code, summary=None):
        self.code = code
        self.summary = summary
        super().__init__(code)


def require(ok, code):
    if not ok:
        raise EvidenceError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    # Raw archival envelopes may contain Unicode; compact commitment items may
    # not. The latter are checked separately by the frozen V2 primitives.
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def strict_json(raw, limit=MAX_CELL_BYTES):
    require(type(raw) in (str, bytes), 'EVIDENCE_JSON')
    try:
        return c.loads(raw, limit)
    except (c.ProjectionError, RecursionError, UnicodeError):
        raise EvidenceError('EVIDENCE_JSON') from None


def ordered(items):
    return sorted(items, key=canonical)


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode)


def open_held(path):
    """Walk an explicit absolute path without following any symlink component."""
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'EVIDENCE_PATH')
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)


class HeldInputs:
    def __init__(self, scratch, check):
        self.scratch, self.check = Path(scratch), check
        self.files = []

    def read(self, path, digest, size, limit, sqlite=False):
        require(type(size) is int and 0 < size <= limit, 'EVIDENCE_INPUT_BOUNDS')
        v2.digest(digest)
        fd = open_held(path)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_size == size, 'EVIDENCE_INPUT_SIZE')
            self.files.append((fd, stamp(info), digest))
        except BaseException:
            os.close(fd)
            raise
        target = self.scratch / ('held-%d.sqlite' % len(self.files)) if sqlite else None
        out = target.open('xb') if sqlite else None
        chunks = []
        hasher = hashlib.sha256()
        total = 0
        try:
            while True:
                self.check()
                block = os.read(fd, min(1024 * 1024, size - total + 1))
                if not block:
                    break
                total += len(block)
                require(total <= size, 'EVIDENCE_INPUT_CHANGED')
                hasher.update(block)
                if out: out.write(block)
                else: chunks.append(block)
        finally:
            if out: out.close()
        require(total == size and hasher.hexdigest() == digest, 'EVIDENCE_INPUT_HASH')
        require(stamp(os.fstat(fd)) == stamp(info), 'EVIDENCE_INPUT_CHANGED')
        if target:
            target.chmod(0o400)
            return target
        return b''.join(chunks)

    def unchanged(self):
        for fd, before, digest in self.files:
            self.check()
            require(stamp(os.fstat(fd)) == before, 'EVIDENCE_INPUT_CHANGED')
            os.lseek(fd, 0, os.SEEK_SET)
            hasher = hashlib.sha256()
            total = 0
            for block in iter(lambda: os.read(fd, min(1024 * 1024, before[2] - total + 1)), b''):
                self.check()
                total += len(block)
                require(total <= before[2], 'EVIDENCE_INPUT_CHANGED')
                hasher.update(block)
            require(hasher.hexdigest() == digest and stamp(os.fstat(fd)) == before, 'EVIDENCE_INPUT_CHANGED')

    def close(self):
        for fd, _, _ in self.files: os.close(fd)
        self.files.clear()


def database(path, check):
    db = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024 * 1024)
    db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 128)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA trusted_schema=OFF')
    db.execute('PRAGMA cache_size=-4096')
    db.set_progress_handler(lambda: (check(), 0)[1], 10000)
    return db


def rows(db, table, order, limit=MAX_RECORDS):
    # Table/order names are exclusively module constants, never wire values.
    cursor = db.execute('SELECT * FROM ' + table + ' ORDER BY ' + order + ' LIMIT ?', (limit + 1,))
    for number, row in enumerate(cursor):
        require(number < limit, 'EVIDENCE_ROW_BOUNDS')
        require(all(not isinstance(x, str) or len(x.encode('utf-8')) <= MAX_CELL_BYTES for x in row), 'EVIDENCE_CELL_BOUNDS')
        yield dict(row)


def index(db, table, key, limit=MAX_RECORDS):
    result = {}
    for row in rows(db, table, ','.join(key), limit):
        identity = tuple(row[k] for k in key)
        require(identity not in result, 'EVIDENCE_DUPLICATE')
        result[identity] = row
    return result


def projection_schema(db):
    with sqlite3.connect(':memory:') as expected:
        expected.executescript(SCHEMA_SQL)
        sql = "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        require([tuple(r) for r in db.execute(sql)] == list(expected.execute(sql)), 'EVIDENCE_PROJECTION_SCHEMA')
    require(db.execute('PRAGMA user_version').fetchone()[0] == 2, 'EVIDENCE_PROJECTION_SCHEMA')
    integrity(db)


def integrity(db):
    require(db.execute('PRAGMA integrity_check(1)').fetchone()[0] == 'ok', 'EVIDENCE_INTEGRITY')
    require(db.execute('PRAGMA foreign_key_check').fetchone() is None, 'EVIDENCE_INTEGRITY')


def source_schema(db):
    objects = list(db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
    expected = {(name, 'table') for name in SOURCE_COLUMNS} | {('compatibility_links_by_raw', 'index')}
    require(set(map(tuple, objects)) == expected, 'EVIDENCE_SOURCE_SCHEMA')
    for table, fields in SOURCE_COLUMNS.items():
        require([r['name'] for r in db.execute('PRAGMA table_info(' + table + ')')] == fields.split(), 'EVIDENCE_SOURCE_SCHEMA')
    integrity(db)


def check_membership(row, when):
    pins = strict_json(row['pin_roots_json'])
    c.roots(pins)
    require(row['retention_class'] in c.CLASSES, 'EVIDENCE_MEMBERSHIP')
    first = c.instant(row['first_observed_at'])
    require(first <= c.instant(when), 'EVIDENCE_MEMBERSHIP')
    if row['retain_until'] is not None:
        expiry = c.instant(row['retain_until'])
        require(expiry >= first and row['retention_class'] not in PERMANENT and not pins, 'EVIDENCE_MEMBERSHIP')
        if row['retention_class'] in ('CONTEXT', 'CAPABILITY_SIGNAL'):
            seconds = c.POLICY['parameters']['context_seconds' if row['retention_class'] == 'CONTEXT' else 'capability_signal_seconds']
            require((expiry - first).total_seconds() == seconds, 'EVIDENCE_MEMBERSHIP')
    return pins


def source_records(source, bridge, when, cut, check):
    """Recover raw hashes/events from the archive, not the plan or metadata."""
    provenance = index(bridge, 'source_provenance', ('entity_type', 'projection_row_id'))
    membership = index(bridge, 'selection_membership', ('entity_type', 'projection_row_id'))
    require(all(k[0] == 'message' for k in provenance) and set(provenance) == set(membership), 'EVIDENCE_ARCHIVE_PROVENANCE')
    events = index(source, 'observed_event_witnesses', ('raw_record_id',))
    records, reasons, facts = {}, {}, {}
    seen_events = set()
    for raw in rows(source, 'raw_records', 'raw_record_id'):
        check()
        rid = raw['raw_record_id']; pid = 'sm1:' + rid; key = ('message', pid)
        require(pid not in records, 'EVIDENCE_DUPLICATE')
        v2.digest(rid); v2.digest(raw['raw_text_sha256'])
        require(key in provenance and key in membership, 'EVIDENCE_ARCHIVE_PROVENANCE')
        p, member = provenance[key], membership[key]
        event = events.get((rid,))
        require(event is not None and type(event['event_id']) is int and 0 <= event['event_id'] <= cut
                and event['event_id'] not in seen_events, 'EVIDENCE_RECOVERED_EVENT')
        seen_events.add(event['event_id'])
        envelope = strict_json(raw['raw_record_json'])
        require(type(envelope) is dict and envelope.get('text') == raw['raw_text'], 'EVIDENCE_RAW_ENVELOPE')
        require(sha(canonical([raw['source'], raw['room'], raw['generation'], raw['reported_generation'], envelope])) == rid,
                'EVIDENCE_RAW_ID')
        digest = sha(raw['raw_text'].encode('utf-8'))
        require(digest == raw['raw_text_sha256'] == event['raw_text_sha256'], 'EVIDENCE_RECOVERED_HASH')
        require(p['raw_record_id'] == rid and p['source_record_locator'] == rid and p['raw_record_sha256'] is None
                and p['source_namespace'] == raw['source'], 'EVIDENCE_ARCHIVE_PROVENANCE')
        require(p['scout_event_id'] == str(event['event_id']), 'EVIDENCE_RECOVERED_EVENT')
        message = bridge.execute('SELECT * FROM messages WHERE projection_row_id=?', (pid,)).fetchone()
        require(message is not None, 'EVIDENCE_ARCHIVE_MESSAGE')
        require(message['text'] == raw['raw_text'] and message['room'] == raw['room'] and message['seq'] == raw['seq']
                and message['message_hash'] in (None, digest)
                and message['generation'] == generation(raw['generation']), 'EVIDENCE_ARCHIVE_MESSAGE')
        pins = check_membership(member, when)
        reasons[pid] = set()
        if member['retain_until'] is None or pins: reasons[pid].add('permanent_or_pinned')
        if member['retention_class'] in ('WORK_LIFECYCLE', 'TCLK_LIFECYCLE'): reasons[pid].add('tclk_or_work_lifecycle')
        records[pid] = {'projection_row_id': pid, 'raw_record_id': rid,
                        'raw_text_sha256': digest, 'scout_event_id': str(event['event_id'])}
        facts[pid] = (raw['room'], message['generation'], event['event_id'], member['retention_class'])
    require(0 < len(records) == len(provenance) == len(events), 'EVIDENCE_ARCHIVE_PROVENANCE')
    require(bridge.execute('SELECT count(*) FROM messages').fetchone()[0] == len(records), 'EVIDENCE_ARCHIVE_PROVENANCE')
    verify_cache_links(source, records)
    return records, reasons, facts, membership


def generation(value):
    if value is None: return 'UNKNOWN_LEGACY'
    require(type(value) is str and bool(value) or type(value) is int and value >= 0, 'EVIDENCE_GENERATION')
    return str(value)


def source_ddl_commitment(db):
    """Independently tokenize the closed source-evidence schema commitment."""
    keyword = set('CREATE TABLE INDEX ON PRIMARY KEY CHECK NOT NULL UNIQUE FOREIGN REFERENCES INTEGER TEXT AND IN'.split())
    pattern = re.compile(r"'(?:''|[^'])*'|[A-Za-z_][A-Za-z0-9_]*|[0-9]+|>=|<=|<>|!=|[(),=*<>;]")
    objects = {}
    for name, kind, sql in db.execute("SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"):
        tokens = []; pos = 0
        while pos < len(sql):
            if sql[pos].isspace(): pos += 1; continue
            match = pattern.match(sql, pos)
            require(match is not None, 'EVIDENCE_SOURCE_SCHEMA')
            token = match.group(); pos = match.end()
            tokens.append(['string', token[1:-1].replace("''", "'")] if token.startswith("'") else
                          ['word', token.upper() if token.upper() in keyword else token.lower()])
        while tokens and tokens[-1] == ['word', ';']: tokens.pop()
        objects[name] = {'type': kind, 'tokens': tokens}
    return sha(b'flop-scout/epoch-source-evidence-ddl/v1\0' + c.canonical(objects))


def verify_cache_links(source, records):
    count = 0
    sender_fields = {'messages': 'sender', 'evidence_records': 'did',
                     'tclk_frames': 'transport_did', 'kibble_events': 'sender_did'}
    for table, field in CACHE_TEXT.items():
        seen = set()
        query = ('SELECT l.raw_record_id,l.raw_text_sha256,c.* '
                 'FROM compatibility_links l LEFT JOIN ' + table + ' c ON c.cache_rowid=l.cache_rowid '
                 'WHERE l.cache_table=? ORDER BY l.cache_rowid LIMIT ?')
        for row in source.execute(query, (table, MAX_RECORDS + 1)):
            count += 1
            pid = 'sm1:' + row['raw_record_id']
            require(pid in records and pid not in seen and len(seen) < MAX_RECORDS, 'EVIDENCE_CACHE_LINK')
            seen.add(pid)
            body = row[field]
            require(type(body) is str and len(body.encode()) <= MAX_CELL_BYTES
                    and sha(body.encode()) == row['raw_text_sha256'] == records[pid]['raw_text_sha256'], 'EVIDENCE_CACHE_LINK')
            raw = source.execute('SELECT * FROM raw_records WHERE raw_record_id=?', (row['raw_record_id'],)).fetchone()
            require((row['room'], row['seq']) == (raw['room'], raw['seq']), 'EVIDENCE_CACHE_LINK')
            if 'generation' in row.keys(): require(generation(row['generation']) == generation(raw['generation']), 'EVIDENCE_CACHE_LINK')
            sender = row[sender_fields[table]]
            require(sender is None or sender == raw['sender_did'], 'EVIDENCE_CACHE_LINK')
            if table == 'evidence_records':
                require(row['sig'] == raw['signature'], 'EVIDENCE_CACHE_LINK')
                if row['nonce'] is not None and raw['nonce'] is not None:
                    require(type(row['nonce']) is int and type(raw['nonce']) is str and raw['nonce'].isdigit()
                            and row['nonce'] == int(raw['nonce']), 'EVIDENCE_CACHE_LINK')
        require(len(seen) == source.execute('SELECT count(*) FROM ' + table).fetchone()[0], 'EVIDENCE_CACHE_LINK')
    require(count == source.execute('SELECT count(*) FROM compatibility_links').fetchone()[0], 'EVIDENCE_CACHE_LINK')
    return count


def retained_tables(active, bridge, records, reasons):
    """All audit history survives; it cannot be trimmed to make counts agree."""
    qualifications = []
    for table, key in (('durable_qualifications', ('qualification_id',)),
                       ('qualification_events', ('qualification_id', 'sequence')),
                       ('coverage_history', ('room', 'generation'))):
        old = index(bridge, table, key)
        new = index(active, table, key)
        require(new == old, 'EVIDENCE_' + table.upper())
        if table == 'durable_qualifications':
            for row in new.values():
                record = c.validate_qualification(strict_json(row['record_json']))
                ref = record['source_ref']
                require(ref['kind'] == 'PROJECTED_MESSAGE' and ref['id'] in records, 'EVIDENCE_QUALIFICATION_PROOF')
                require(record['qualification_id'] == row['qualification_id'], 'EVIDENCE_QUALIFICATION_PROOF')
                reasons[ref['id']].add('durable_qualification')
                qualifications.append({'qualification_id': row['qualification_id'], 'record_json': record})
        if table == 'coverage_history':
            coverage = list(new.values())
            require(len(coverage) <= v2.MAX_LIST_ITEMS, 'EVIDENCE_ROW_BOUNDS')
            for row in coverage:
                pid = 'sm1:' + row['witness_source_locator']
                msg = active.execute('SELECT * FROM messages WHERE projection_row_id=?', (pid,)).fetchone()
                require(pid in records and msg is not None, 'EVIDENCE_COVERAGE_PROOF')
                require((msg['room'], msg['generation'], msg['seq']) ==
                        (row['room'], row['generation'], row['max_ever_projected_seq'])
                        and c.digest(dict(msg)) == row['witness_record_sha256'], 'EVIDENCE_COVERAGE_PROOF')
                reasons[pid].add('coverage_witness')
    return ordered(qualifications), ordered(coverage)


def select(records, reasons, facts, target):
    """Frozen policy/1: mandatory closure, domain representatives, then recency."""
    mandatory = {pid for pid in records if reasons[pid]}
    require(len(mandatory) <= target, 'EVIDENCE_MANDATORY_CAPACITY')
    optional = sorted(set(records) - mandatory,
                      key=lambda pid: (-facts[pid][2], facts[pid][3], facts[pid][0], facts[pid][1], 'messages', pid))
    selected = set(mandatory)
    domains = set()
    for pid in optional:
        domain = facts[pid][:2]
        if len(selected) < target and domain not in domains:
            selected.add(pid)
            domains.add(domain)
    for pid in optional:
        if len(selected) >= target: break
        selected.add(pid)
    return selected


def artifact_rows(active, bridge, selected, records, membership, check):
    expected = {('message', pid) for pid in selected}
    actual = index(active, 'source_provenance', ('entity_type', 'projection_row_id'))
    members = index(active, 'selection_membership', ('entity_type', 'projection_row_id'))
    require(set(actual) == set(members) == expected, 'EVIDENCE_SELECTED_SET')
    seen = set()
    for message in rows(active, 'messages', 'projection_row_id'):
        check()
        pid = message['projection_row_id']
        require(pid in selected and pid not in seen, 'EVIDENCE_SELECTED_SET')
        seen.add(pid)
        old_message = bridge.execute('SELECT * FROM messages WHERE projection_row_id=?', (pid,)).fetchone()
        require(old_message is not None and dict(old_message) == message, 'EVIDENCE_SELECTED_MESSAGE')
        require(sha(message['text'].encode()) == records[pid]['raw_text_sha256'], 'EVIDENCE_RECOVERED_HASH')
        p = dict(bridge.execute("SELECT * FROM source_provenance WHERE entity_type='message' AND projection_row_id=?", (pid,)).fetchone())
        p['raw_record_sha256'] = records[pid]['raw_text_sha256']
        require(actual[('message', pid)] == p, 'EVIDENCE_SELECTED_PROVENANCE')
        require(members[('message', pid)] == membership[('message', pid)], 'EVIDENCE_SELECTED_MEMBERSHIP')
    require(seen == selected, 'EVIDENCE_SELECTED_SET')
    # This frozen message-only adapter has no interaction provenance. Do not
    # silently grant unsupported extra entities entry into an evidence bundle.
    require(active.execute('SELECT count(*) FROM interactions').fetchone()[0] == 0
            and bridge.execute('SELECT count(*) FROM interactions').fetchone()[0] == 0, 'EVIDENCE_UNCOMMITTED_ENTITY')
    watermarks = [dict(r) for r in active.execute('SELECT room,generation,count(*) AS record_count,min(seq) AS min_seq,max(seq) AS max_seq FROM messages GROUP BY room,generation ORDER BY room,generation')]
    require(watermarks == list(rows(active, 'watermarks', 'room,generation', v2.MAX_LIST_ITEMS)), 'EVIDENCE_WATERMARKS')


def dependency_semantics(active, transition, check):
    """Reuse Router's proof and authoritative terminal rules, without a reader run."""
    # Resolve immutable annotation dependencies against selected evidence. Links
    # cannot be treated as producer assertions that their target was retained.
    positions, evidence = {}, {}
    for row in active.execute("SELECT m.projection_row_id,m.room,m.generation,m.seq,m.evidence_id,p.source_namespace FROM messages m JOIN source_provenance p ON p.entity_type='message' AND p.projection_row_id=m.projection_row_id"):
        key = (row['source_namespace'], row['room'], row['generation'], row['seq'])
        positions.setdefault(key, set()).add(row['evidence_id'])
        if row['evidence_id'] is not None: evidence.setdefault(row['source_namespace'], set()).add(row['evidence_id'])
    for row in active.execute('SELECT annotations_json,source_namespace FROM source_provenance'):
        check()
        annotations = c.annotations(strict_json(row['annotations_json']))
        for link in annotations['evidence_links']:
            namespace = row['source_namespace']
            if link['room'] is not None:
                key = (namespace, link['room'], link['generation'], link['seq'])
                require(key in positions and (link['evidence_id'] is None or link['evidence_id'] in positions[key]), 'EVIDENCE_DEPENDENCY')
            else:
                require(link['evidence_id'] in evidence.get(namespace, set()), 'EVIDENCE_DEPENDENCY')
    manifest = {'selection_evaluated_at': transition['created_at'],
                'source_checkpoint': {'source_id': transition['source_binding']['source_id'],
                                      'epoch': transition['source_binding']['epoch'],
                                      'committed_event_id': str(transition['source_cut']['committed_event_id'])},
                'row_counts': {table: active.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                               for table in ('durable_qualifications', 'qualification_events')}}
    helper = SimpleNamespace(check=check, metadata={'routing_input_hash': '0' * 64, 'stage_seconds': {}})
    helper._proof = ProjectionReader._proof.__get__(helper)
    with sqlite3.connect(':memory:') as scratch:
        ProjectionReader._qualifications(helper, active, manifest, scratch)
    # Frozen memberships preserve all lifecycle rows, including open and opaque
    # workflows. A finite expiry additionally needs Router's terminal evidence.
    with sqlite3.connect(':memory:') as scratch:
        verifier = ClosureVerifier(active, scratch, check)
        for row in active.execute("SELECT * FROM selection_membership WHERE retention_class IN ('WORK_LIFECYCLE','TCLK_LIFECYCLE') AND retain_until IS NOT NULL"):
            verifier.verify(row, transition['created_at'])


def recovery_check(recovery, manifest, metadata, records, reasons, bridge):
    closure = [dict(records[pid], reasons=sorted(reasons[pid])) for pid in sorted(records) if reasons[pid]]
    content = {'content_id': str(bridge['content_id']), 'manifest_sha256': bridge['manifest_sha256'],
               'artifact_sha256': bridge['artifact_sha256'], 'source_id': bridge['source_id'],
               'source_epoch': bridge['source_kind'], 'committed_event_id': str(bridge['source_cut'])}
    proof = [{k: row[k] for k in ('raw_record_id', 'raw_text_sha256', 'scout_event_id')} for row in closure]
    digest = c.digest({'domain': 'scout/legacy-a1-provenance-recovery-closure/v1', 'content': content, 'records': proof})
    reason_counts = {}
    for row in closure:
        for reason in row['reasons']: reason_counts[reason] = reason_counts.get(reason, 0) + 1
    expected = {'schema': archive.RECOVERY_SCHEMA, 'descriptor': content, 'validated_records': len(records),
                'closure_count': len(closure), 'closure': closure, 'reason_counts': reason_counts, 'commitment': digest}
    require(recovery == expected, 'EVIDENCE_RECOVERY')
    require(manifest['legacy_recovery'] == {'schema': archive.RECOVERY_SCHEMA,
            'commitment_sha256': digest, 'validated_records': len(records), 'closure_count': len(closure)}
            and metadata['recovery_commitment_sha256'] == digest, 'EVIDENCE_RECOVERY')
    return digest


def plan_records(plan, records):
    require(type(plan) is dict and set(plan) == set(v2.PLAN), 'EVIDENCE_PLAN_FIELDS')
    partitions = []
    for name in ('selected', 'omitted'):
        items = plan[name]
        require(type(items) is list and len(items) <= MAX_RECORDS, 'EVIDENCE_PLAN_BOUNDS')
        ids = []
        for row in items:
            require(type(row) is dict and set(row) == set(v2.PLAN_RECORD), 'EVIDENCE_PLAN_RECORD')
            pid = row['projection_row_id']
            require(type(pid) is str and pid in records, 'EVIDENCE_PLAN_UNION')
            require({k: row[k] for k in records[pid]} == records[pid], 'EVIDENCE_PLAN_RECOVERED')
            ids.append(pid)
        require(ids == sorted(set(ids)), 'EVIDENCE_PLAN_ORDER')
        partitions.append(set(ids))
    selected, omitted = partitions
    require(not selected & omitted and selected | omitted == set(records), 'EVIDENCE_PLAN_UNION')
    return selected, omitted


def summary_for(transition, sets, eligible, selected, recovery_digest, manifest):
    counts = {name: len(items) for name, items in sets.items()}
    counts.update(eligible=eligible, selected=selected, omitted=eligible-selected)
    commitments = {name: v2.bounded_commitment(v2.SET_DOMAINS[name], items) for name, items in sets.items()}
    commitments['recovery'] = recovery_digest
    identities = {'transition': v2.transition_commitment(transition),
                  'active_artifact': v2.commitment('active-artifact-descriptor', transition['active_artifact']),
                  'active_set_plan': v2.commitment('active-set-plan-descriptor', transition['active_set_plan']),
                  'archive': transition['archive']['archive_commitment_sha256']}
    for item in manifest['members']: identities[item['role']] = item['sha256']
    return EvidenceSummary(tuple(sorted(counts.items())), tuple(sorted(commitments.items())), tuple(sorted(identities.items())))


def reconstruct(transition, *, accepted_anchor, plan_path, artifact_path, archive_root,
                accepted_epoch_number=0, first_transition=True, timeout=180.0):
    """Reconstruct and check all five compact sets, returning redacted audit facts.

    Late summary/plan binding failures carry the recomputed diagnostic summary on
    EvidenceError.summary. It is never a successful validation result or receipt.
    All paths must be explicit absolute paths to isolated, immutable artifacts.
    """
    require(type(timeout) in (int, float) and 0 < timeout <= 3600, 'EVIDENCE_TIMEOUT')
    deadline = time.monotonic() + timeout
    def check(): require(time.monotonic() < deadline, 'EVIDENCE_TIMEOUT')
    # Snapshot caller-owned objects to avoid in-process descriptor mutations.
    transition = v2.parse_json(v2.canonical_json(transition))
    v2.validate_transition(transition, accepted_anchor, accepted_epoch_number, first_transition)
    try:
        with tempfile.TemporaryDirectory(prefix='router-epoch-evidence-') as scratch, ExitStack() as stack:
            held = HeldInputs(scratch, check)
            stack.callback(held.close)
            desc = transition['active_set_plan']
            plan_raw = held.read(plan_path, desc['sha256'], desc['size_bytes'], v2.MAX_PLAN_BYTES)
            plan = v2.parse_active_set_plan(plan_raw)
            require(canonical(plan) == plan_raw, 'EVIDENCE_PLAN_CANONICAL')
            desc = transition['active_artifact']
            active_path = held.read(artifact_path, desc['artifact_sha256'], desc['size_bytes'], MAX_SQLITE_BYTES, sqlite=True)
            desc = transition['archive']
            root = Path(archive_root)
            archive_raw = held.read(root / 'manifest.json', desc['artifact_sha256'], desc['size_bytes'], v2.MAX_INPUT_BYTES)
            manifest = v2.parse_json(archive_raw)
            require(archive.canonical(manifest) == archive_raw, 'EVIDENCE_ARCHIVE_CANONICAL')
            archive.validate_format(v2.without(desc, 'archive_commitment_sha256'), manifest)
            for key in ('accepted_anchor', 'bridge_predecessor'):
                require(manifest[key] == transition[key], 'EVIDENCE_ARCHIVE_BINDING')
            require(manifest['previous_bridge_binding_sha256'] == transition['bridge_binding_sha256'], 'EVIDENCE_ARCHIVE_BINDING')
            bridge_desc = transition['bridge_predecessor']
            require(manifest['source_checkpoint'] == {'source_id': bridge_desc['source_id'], 'source_epoch': bridge_desc['source_kind'],
                    'source_cut': bridge_desc['source_cut']}, 'EVIDENCE_ARCHIVE_BINDING')
            members = {}
            for item in manifest['members']:
                role = item['role']
                require(item['locator'] == archive.ROLES[role][0], 'EVIDENCE_ARCHIVE_LOCATOR')
                members[role] = held.read(root / item['locator'], item['sha256'], item['size_bytes'],
                    MAX_JSON_BYTES if role == 'legacy_recovery_json' else MAX_SQLITE_BYTES, sqlite=role != 'legacy_recovery_json')
            recovery = strict_json(members['legacy_recovery_json'], MAX_JSON_BYTES)
            databases = []
            for path in (active_path, members['bridge_projection_sqlite'], members['source_evidence_sqlite']):
                db = database(path, check)
                stack.callback(db.close)
                databases.append(db)
            active, bridge, source = databases
            projection_schema(active); projection_schema(bridge); source_schema(source)
            metas = list(rows(source, 'source_evidence_metadata', 'singleton', 1))
            require(len(metas) == 1, 'EVIDENCE_SOURCE_METADATA')
            metadata = metas[0]
            require(metadata['canonical_ddl_sha256'] == source_ddl_commitment(source), 'EVIDENCE_SOURCE_SCHEMA')
            require(metadata['schema'] == archive.SOURCE_SCHEMA and metadata['revision'] == 'legacy-a1-recovery/1', 'EVIDENCE_SOURCE_METADATA')
            for key in ('accepted_anchor', 'bridge_predecessor', 'source_checkpoint'):
                require(strict_json(metadata[key + '_json']) == manifest[key], 'EVIDENCE_SOURCE_METADATA')
            require(metadata['previous_bridge_binding_sha256'] == transition['bridge_binding_sha256'], 'EVIDENCE_SOURCE_METADATA')
            meta = list(rows(active, 'snapshot_meta', 'singleton', 1))
            require(len(meta) == 1 and meta[0] == {'singleton': 1, 'schema': c.SCHEMA,
                'database_content_id': str(transition['active_artifact']['content_id']),
                'content_created_at': transition['created_at'], 'selection_policy_sha256': c.POLICY_SHA}, 'EVIDENCE_ACTIVE_META')
            records, reasons, facts, membership = source_records(source, bridge, transition['created_at'], bridge_desc['source_cut'], check)
            require(metadata['raw_record_count'] == metadata['observed_event_count'] == len(records)
                    and metadata['cache_link_count'] == source.execute('SELECT count(*) FROM compatibility_links').fetchone()[0], 'EVIDENCE_SOURCE_METADATA')
            selected, omitted = plan_records(plan, records)
            artifact_rows(active, bridge, selected, records, membership, check)
            qualifications, coverage = retained_tables(active, bridge, records, reasons)
            dependency_semantics(active, transition, check)
            require(selected == select(records, reasons, facts, transition['active_epoch']['target']), 'EVIDENCE_SELECTION_POLICY')
            for name, ids in (('selected', selected), ('omitted', omitted)):
                expected_rows = [dict(records[pid], reasons=sorted(reasons[pid]) if reasons[pid] else
                                ['optional_selection'] if name == 'selected' else ['deterministic_optional_omission']) for pid in sorted(ids)]
                require(plan[name] == expected_rows, 'EVIDENCE_CLASSIFICATION')
            recovery_digest = recovery_check(recovery, manifest, metadata, records, reasons, bridge_desc)
            sets = {
                'mandatory_proof_closure': ordered([dict(records[pid], reasons=sorted(reasons[pid])) for pid in records if reasons[pid]]),
                'durable_qualification_history': qualifications, 'coverage_witnesses': coverage,
                'permanent_pinned_evidence': ordered([dict(records[pid], reasons=sorted(reasons[pid])) for pid in records if 'permanent_or_pinned' in reasons[pid]]),
                'omitted_history': ordered([dict(records[pid], reasons=['deterministic_optional_omission']) for pid in omitted]),
            }
            summary = summary_for(transition, sets, len(records), len(selected), recovery_digest, manifest)
            floor = transition['retained_floor_commitment']
            entries = [{'room': row['room'], 'generation': row['generation'], 'domain': 'messages',
                        'retained_floor': row['max_ever_projected_seq'], 'omitted_ranges': []}
                       for row in sorted(coverage, key=lambda r: (r['room'], r['generation']))]
            rebuilt = v2.compact_retained_floor(entries, 'epoch-v2-policy/1', sets)
            # Finish descriptor stability checks even when a late binding differs.
            held.unchanged()
            for name, items in sets.items():
                if floor[name + '_count'] != len(items): raise EvidenceError('EVIDENCE_COUNT_' + name.upper(), summary)
                if floor[name + '_sha256'] != dict(summary.commitments)[name]: raise EvidenceError('EVIDENCE_HASH_' + name.upper(), summary)
            if floor != rebuilt: raise EvidenceError('EVIDENCE_RETAINED_FLOOR', summary)
            if transition['active_epoch']['mandatory_closure_count'] != len(sets['mandatory_proof_closure']):
                raise EvidenceError('EVIDENCE_CAPACITY', summary)
            if plan['selection_policy_version'] != floor['selection_policy_version'] or plan['recovery_commitment_sha256'] != recovery_digest:
                raise EvidenceError('EVIDENCE_PLAN_BINDING', summary)
            try:
                v2.validate_active_set_plan_bytes(plan_raw, transition)
            except v2.EpochV2Error as exc:
                raise EvidenceError(exc.code, summary) from None
            return summary
    except EvidenceError:
        raise
    except (OSError, sqlite3.Error, c.ProjectionError, SnapshotError, archive.ArchiveValidationError,
            v2.EpochV2Error, TypeError, KeyError, ValueError):
        raise EvidenceError('EVIDENCE_INVALID') from None
