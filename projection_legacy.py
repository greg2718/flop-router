"""Bounded LG2 audit validation. Reports never enter routing or generation joins.

Private Scout originals are outside this consumer's authority boundary. Public
hashes/locators are consistency assertions, not independently verified originals.
"""
from itertools import groupby
from pathlib import Path

import projection_contract as c
from scout_snapshot import SnapshotError

REVISION = 'A1-LG2'
ENCODING = 'router-legacy-generation-storage/v2'
POLICY = dict(schema='router-legacy-generation-authority/v1',
              migration_class='scout-legacy-evidence-v1-service-poll',
              allowed_reported_generations=['0', '1'], authority='LEGACY_REPORTED_ONLY',
              match_status='UNRESOLVED_LEGACY', watermark_domain='CAPTURED')
SQL = Path(__file__).with_name('docs').joinpath('router-legacy-generation-lg2-schema.sql').read_text()
TABLES = {'legacy_generation_reports', 'legacy_generation_witnesses'}
KINDS = {1: 'evidence_records', 2: 'tclk_frames', 3: 'kibble_events'}
FIXED = dict(captured_generation='UNKNOWN_LEGACY', generation_authority='LEGACY_REPORTED_ONLY',
             generation_match_status='UNRESOLVED_LEGACY', migration_class=POLICY['migration_class'],
             raw_source='legacy_evidence', ingestion_schema='flop-scout-evidence/v1',
             ingestion_version='1', legacy_record=True, raw_completeness='PARTIAL',
             cache_source='service-poll', transport_lineage='UNAVAILABLE_IN_LEGACY_CAPTURE')


def require(ok, code):
    if not ok:
        raise SnapshotError(code)


def binding(manifest):
    revision = manifest['contract_revision']
    if revision in ('A1-LG1', REVISION):
        require(c.canonical(manifest.get('legacy_generation_policy')) == c.canonical(POLICY), 'UNSUPPORTED_LG_POLICY')
    if revision == REVISION:
        require(manifest.get('legacy_generation_encoding') == ENCODING, 'UNSUPPORTED_LG_ENCODING')
    return {k: manifest.get(k) for k in ('contract_revision', 'legacy_generation_policy', 'legacy_generation_encoding')}


def witness(row, code):
    require(type(row['cache_kind']) is int and row['cache_kind'] in KINDS, 'LG2_INVALID_CACHE_KIND')
    h = row['record_hash']
    require(type(h) is bytes and len(h) == 32, 'LG2_INVALID_WITNESS_HASH')
    locator = row['locator']
    require(type(locator) is str and locator != h.hex(), 'LG2_NONCANONICAL_LOCATOR')
    locator = h.hex() if locator == '' else locator
    c.string(locator)
    return dict(cache_table=KINDS[row['cache_kind']], source_record_locator=locator,
                record_sha256=h.hex(), reported_generation=str(code))


def audit(raw, code, text_hash, refs):
    return dict(FIXED, reported_generation=str(code), raw_record_id=raw.hex(),
                raw_text_sha256=text_hash, linked_cache_records=sorted(refs, key=c.canonical))


def audit_view(conn, message_id, check=lambda: None):
    """Read one validated report (<=256 witnesses); no raw message body returned."""
    c.string(message_id)
    row = conn.execute('''SELECT r.raw_ref,r.reported_code,m.message_hash,
        CASE WHEN m.message_hash IS NULL THEN m.text END AS unhashed_text
        FROM legacy_generation_reports r CROSS JOIN messages m
        ON m.projection_row_id=r.message_id WHERE r.raw_ref=?''',
        (bytes.fromhex(message_id[4:]) if message_id.startswith('sm1:') and len(message_id)==68 else b'',)).fetchone()
    if row is None:
        return None
    refs=[]
    for w in conn.execute('SELECT * FROM legacy_generation_witnesses WHERE raw_ref=?', (row['raw_ref'],)):
        check(); require(len(refs)<256, 'LG2_WITNESS_BOUNDS'); refs.append(witness(w,row['reported_code']))
    result=audit(row['raw_ref'],row['reported_code'],row['message_hash'] or c.text_hash(row['unhashed_text']),refs)
    return dict(contract_revision=REVISION, legacy_generation_policy=POLICY,
                legacy_generation_encoding=ENCODING, legacy_generation=result)


def validate(reader, conn, manifest):
    stats=dict(report_count=0,witness_count=0,reported_0_count=0,reported_1_count=0,
               average_witnesses_per_report=0.0,max_witnesses_per_report=0,
               invalid_enum_count=0,conflict_count=0,policy_status='VALID',revision=REVISION,
               authority='SECONDARY_AUDIT_ONLY',counts_scope='VALIDATED_PREFIX')
    reader.metadata['legacy_generation_audit']=stats
    with reader.stage('lg2_report_validation'):
        bad=conn.execute('''SELECT r.message_id FROM legacy_generation_reports r
            LEFT JOIN messages m ON m.projection_row_id=r.message_id
            LEFT JOIN source_provenance p ON p.entity_type='message' AND p.projection_row_id=r.message_id
            WHERE m.projection_row_id IS NULL OR p.projection_row_id IS NULL
            OR m.generation <> 'UNKNOWN_LEGACY' OR p.raw_record_id IS NOT lower(hex(r.raw_ref)) LIMIT 1''').fetchone()
        if bad:
            stats['conflict_count']=1
            raise SnapshotError('LG2_REPORT_PROVENANCE_CONFLICT')
        for raw,code in conn.execute('SELECT raw_ref,reported_code FROM legacy_generation_reports'):
            reader.check()
            require(type(raw) is bytes and len(raw)==32,'LG2_INVALID_RAW_REFERENCE')
            if type(code) is not int or code not in (0,1):
                stats['invalid_enum_count']+=1
                raise SnapshotError('LG2_INVALID_REPORTED_CODE')
            stats['report_count']+=1; stats[f'reported_{code}_count']+=1
    # Keep reports outermost: generated message_id has no secondary index. A
    # planner-selected provenance-prefix scan can otherwise become quadratic.
    query='''SELECT r.raw_ref,r.reported_code,w.cache_kind,w.record_hash,w.locator,
        m.message_hash,CASE WHEN m.message_hash IS NULL THEN m.text END AS unhashed_text,
        p.annotations_json
        FROM legacy_generation_reports r
        CROSS JOIN messages m ON m.projection_row_id=r.message_id
        CROSS JOIN source_provenance p ON p.entity_type='message' AND p.projection_row_id=r.message_id
        LEFT JOIN legacy_generation_witnesses w ON w.raw_ref=r.raw_ref ORDER BY r.raw_ref'''
    with reader.stage('lg2_witness_validation'):
        for raw, rows in groupby(conn.execute(query),lambda row:row['raw_ref']):
            refs=[]; locators=set(); first=None
            for row in rows:
                reader.check(); first=first or row
                require(row['cache_kind'] is not None,'LG2_MISSING_WITNESS')
                require(len(refs)<256,'LG2_WITNESS_BOUNDS')
                if type(row['cache_kind']) is not int or row['cache_kind'] not in KINDS:
                    stats['invalid_enum_count']+=1
                    raise SnapshotError('LG2_INVALID_CACHE_KIND')
                ref=witness(row,row['reported_code'])
                key=(ref['cache_table'],ref['source_record_locator'])
                if key in locators:
                    stats['conflict_count']+=1
                    raise SnapshotError('LG2_WITNESS_LOCATOR_CONFLICT')
                locators.add(key); refs.append(ref)
            require(any(ref['cache_table']=='evidence_records' for ref in refs),'LG2_MISSING_EVIDENCE_WITNESS')
            # Only one bounded logical view exists at a time. No stored expanded
            # JSON or global report/witness object graph is created.
            with reader.stage('lg2_audit_reconstruction'):
                expanded=c.loads(first['annotations_json'],65536)
                expanded['legacy_generation']=audit(raw,first['reported_code'],first['message_hash'] or c.text_hash(first['unhashed_text']),refs)
                require(len(c.canonical(expanded))<=65536,'LG2_LOGICAL_ANNOTATION_TOO_LARGE')
            stats['witness_count']+=len(refs)
            stats['max_witnesses_per_report']=max(stats['max_witnesses_per_report'],len(refs))
    require(stats['witness_count']==manifest['row_counts']['legacy_generation_witnesses'],'LG2_ORPHAN_WITNESS')
    stats['counts_scope']='COMPLETE'
    stats['average_witnesses_per_report']=stats['witness_count']/stats['report_count'] if stats['report_count'] else 0.0


def continuity(reader, conn, prior_revision):
    """prior_projection is an attached, hash-verified Router-private database."""
    if prior_revision == REVISION:
        for query, code in [
            ('''SELECT 1 FROM prior_projection.legacy_generation_reports a
                JOIN messages m ON m.projection_row_id=a.message_id
                LEFT JOIN legacy_generation_reports b ON b.raw_ref=a.raw_ref
                WHERE b.raw_ref IS NULL OR b.reported_code IS NOT a.reported_code LIMIT 1''','CONTINUITY_LG2_REPORT_CHANGED'),
            ('''SELECT 1 FROM prior_projection.legacy_generation_witnesses a
                JOIN messages m ON m.projection_row_id='sm1:'||lower(hex(a.raw_ref))
                LEFT JOIN legacy_generation_witnesses b ON b.raw_ref=a.raw_ref
                AND b.cache_kind=a.cache_kind AND b.record_hash=a.record_hash AND b.locator=a.locator
                WHERE b.raw_ref IS NULL LIMIT 1''','CONTINUITY_LG2_WITNESS_LOSS')]:
            reader.check(); require(conn.execute(query).fetchone() is None,code)
    elif prior_revision in ('A1','A1-LG1'):
        # Explicit migration preserves all existing substantive provenance;
        # only the historical LG1 storage slot may disappear.
        for table, keys in (('messages',('projection_row_id',)),('interactions',('projection_row_id',)),
                            ('source_provenance',('entity_type','projection_row_id'))):
            columns=[row[1] for row in conn.execute(f'PRAGMA table_info({table})') if row[1]!='annotations_json']
            join=' AND '.join(f'a.{key}=b.{key}' for key in keys)
            changed=' OR '.join(f'a.{column} IS NOT b.{column}' for column in columns)
            reader.check()
            require(conn.execute(f'SELECT 1 FROM prior_projection.{table} a LEFT JOIN {table} b ON {join} WHERE {changed} LIMIT 1').fetchone() is None,
                    'CONTINUITY_MIGRATION_ROW_CHANGED')
        query='''SELECT a.*,b.annotations_json AS new_annotations FROM prior_projection.source_provenance a
            LEFT JOIN source_provenance b ON b.entity_type=a.entity_type AND b.projection_row_id=a.projection_row_id'''
        for row in conn.execute(query):
            reader.check(); old=c.loads(row['annotations_json'],65536)
            if prior_revision=='A1-LG1':
                require(set(old)==set(c.ANNOTATIONS)|{'legacy_generation'},'CONTINUITY_LG1_ANNOTATIONS')
                old_audit=old.pop('legacy_generation')
            else: old_audit=None
            c.annotations(old)
            require(row['new_annotations'] is not None and c.canonical(old)==c.canonical(c.loads(row['new_annotations'],65536)), 'CONTINUITY_MIGRATION_PROVENANCE')
            if prior_revision=='A1-LG1':
                view=audit_view(conn,row['projection_row_id'],reader.check) if row['entity_type']=='message' else None
                require(c.canonical(old_audit)==c.canonical(view['legacy_generation'] if view else None),'CONTINUITY_LG1_AUDIT_MISMATCH')
