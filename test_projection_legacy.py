"""LG2 compatibility, authority and migration checks; synthetic publications only."""
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from unittest.mock import patch

import pytest
import projection_contract as c
import projection_legacy as lg
import projection_routing as pr
import router
import scout_projection as v
import scout_snapshot as ss
from test_scout_projection import rewrite

ROOT=Path('/private/tmp/scout-lg2-router-fixtures-final-20260908')
NOW=datetime(2026,9,8,12,tzinfo=timezone.utc)
NAMES=['normal-concrete','legacy-reported-0','legacy-reported-1','multiple-same-generation-witnesses',
       'true-conflict','same-operator-bench','qualification-invalidation','heartbeat-reuse','unknown-without-lg2']


def fixture(name):
    if not (ROOT/'index.json').is_file():
        pytest.skip('Supplied temporary Scout LG2 fixtures unavailable')
    return ROOT/name


def clone(tmp_path,name='legacy-reported-0'):
    root=tmp_path/'publication';root.mkdir()
    source=fixture(name)
    pointer=json.loads((source/'current.json').read_text())
    manifest=json.loads((source/pointer['manifest']).read_text())
    for filename in ('current.json',pointer['manifest'],manifest['database']):
        shutil.copyfile(source/filename,root/filename)
    return root


def read(root,cache,previous=None,consume=None,**kwargs):
    with v.ProjectionReader(root,cache,**kwargs) as reader:
        return reader.read(consume or (lambda conn:pr.build(conn,reader)),previous=previous,now=NOW)


def mutate(root,sql=None,change=None):
    counts={}
    def edit(conn):
        if sql: sql(conn)
        counts.update({t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in set(c.TABLES)|lg.TABLES})
    def manifest(m):
        m['row_counts']=counts
        if change:change(m)
    return rewrite(root,manifest,edit)


def advance(root,sql=None):
    pointer=json.loads((root/'current.json').read_text());m=json.loads((root/pointer['manifest']).read_text())
    new=str(int(m['database_content_id'])+1)
    def edit(conn):
        conn.execute('UPDATE snapshot_meta SET database_content_id=?',(new,))
        if sql:sql(conn)
    def change(m):
        m.update(database_content_id=new,snapshot_id=str(int(m['snapshot_id'])+1),publication_kind='CONTENT')
        old=root/m['database'];m['database']=f"router-projection-v2-{new}-{m['sha256']}.sqlite";old.rename(root/m['database'])
    return mutate(root,edit,change)


@pytest.mark.parametrize('name',NAMES)
def test_nine_final_scout_lg2_fixtures(tmp_path,name):
    if name=='true-conflict':
        with pytest.raises(ss.SnapshotError,match='LG2_REPORT_PROVENANCE_CONFLICT'):
            read(fixture(name),tmp_path/'cache',consume=lambda conn:pytest.fail('degraded artifact consumed'))
        return
    def consume(conn):
        assert conn.execute('PRAGMA query_only').fetchone()[0]==1
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0]==1
        assert Path(conn.execute('PRAGMA database_list').fetchone()[2]).is_relative_to(tmp_path)
        with pytest.raises(sqlite3.OperationalError):conn.execute('DELETE FROM legacy_generation_reports')
        rows,edges=router._worker_snapshot_profiles(conn)
        audits=[lg.audit_view(conn,row[0]) for row in conn.execute('SELECT message_id FROM legacy_generation_reports')]
        history=list(v.qualification_history(conn))
        return rows,edges,audits,history
    (rows,edges,audits,history),meta=read(fixture(name),tmp_path/'cache',consume=consume)
    assert meta['contract_revision']==lg.REVISION and meta['content_binding']==lg.binding(meta['manifest'])
    stats=meta['legacy_generation_audit']
    assert stats['report_count']==len(audits) and stats['invalid_enum_count']==stats['conflict_count']==0
    if audits:
        assert len(audits)==1 and len(rows)==1
        value=audits[0]['legacy_generation']
        assert value['captured_generation']=='UNKNOWN_LEGACY'
        assert value['reported_generation']==('1' if name.endswith('-1') else '0')
        assert value['generation_authority']=='LEGACY_REPORTED_ONLY'
        assert value['generation_match_status']=='UNRESOLVED_LEGACY'
        assert len(value['linked_cache_records'])==2
        assert all(w['reported_generation']==value['reported_generation'] for w in value['linked_cache_records'])
        assert all(w['generation']=='UNKNOWN_LEGACY' for w in meta['watermarks'])
    if name=='unknown-without-lg2':
        assert not audits and rows[0].generation=='UNKNOWN_LEGACY'
    if name in ('same-operator-bench','qualification-invalidation'):
        q=next(q for q in history if q['record']['qualification_type']=='CONTROLLED_BENCH')
        assert q['record']['same_operator'] and not q['record']['independent_reputation']
        assert q['record']['operator_group']==c.FAMILY
        assert q['effective_status']=='VALID'
        if name=='qualification-invalidation':assert any(q['effective_status']=='INVALIDATED' for q in history)


@pytest.mark.parametrize('mutation',[
    lambda m:m.pop('legacy_generation_policy'),
    lambda m:m.pop('legacy_generation_encoding'),
    lambda m:m['legacy_generation_policy'].update(watermark_domain='REPORTED'),
    lambda m:m.update(legacy_generation_encoding='router-legacy-generation-storage/v3'),
    lambda m:m.update(contract_revision='A1-LG1'),
    lambda m:m.update(contract_revision='A1'),
    lambda m:m.update(contract_revision='FUTURE'),
])
def test_lg2_manifest_dispatch_rejects_mixed_or_unknown(tmp_path,mutation):
    root=clone(tmp_path);rewrite(root,mutation)
    with pytest.raises(ss.SnapshotError):read(root,tmp_path/'cache')


@pytest.mark.parametrize('statement',[
    'ALTER TABLE legacy_generation_reports ADD COLUMN extra TEXT',
    'CREATE INDEX lg_extra ON legacy_generation_witnesses(cache_kind)',
    'DROP TABLE legacy_generation_witnesses',
    'CREATE VIEW forbidden AS SELECT * FROM legacy_generation_reports',
])
def test_lg2_exact_schema_drift(tmp_path,statement):
    root=clone(tmp_path);rewrite(root,sql=lambda db:db.execute(statement))
    with pytest.raises(ss.SnapshotError,match='INVALID_DATABASE_SCHEMA'):read(root,tmp_path/'cache')


@pytest.mark.parametrize('statement',[
    'UPDATE legacy_generation_reports SET reported_code=2',
    'UPDATE legacy_generation_witnesses SET cache_kind=4',
    "UPDATE legacy_generation_witnesses SET record_hash=x'01'",
    "UPDATE legacy_generation_reports SET raw_ref=x'01'",
    'DELETE FROM legacy_generation_reports',
    'DELETE FROM legacy_generation_witnesses',
    'DELETE FROM legacy_generation_witnesses WHERE cache_kind=1',
    "UPDATE legacy_generation_witnesses SET locator=lower(hex(record_hash))",
    "UPDATE legacy_generation_witnesses SET locator='   '",
    "UPDATE legacy_generation_witnesses SET locator=printf('%0257d',0)",
    "UPDATE source_provenance SET raw_record_id='bad' WHERE entity_type='message'",
    "UPDATE messages SET message_hash=printf('%064d',0)",
    "UPDATE source_provenance SET annotations_json=json_set(annotations_json,'$.legacy_generation',NULL)",
    "UPDATE watermarks SET generation='0'",
    "INSERT INTO legacy_generation_witnesses SELECT raw_ref,cache_kind,randomblob(32),locator FROM legacy_generation_witnesses WHERE locator<>'' LIMIT 1",
])
def test_lg2_invalid_rows_fail_before_consumption(tmp_path,statement):
    root=clone(tmp_path)
    def edit(db):
        db.execute('PRAGMA ignore_check_constraints=ON');db.execute(statement)
    mutate(root,edit)
    with pytest.raises(ss.SnapshotError):read(root,tmp_path/'cache',consume=lambda db:pytest.fail('invalid source consumed'))


def test_provenance_annotation_cache_checks_each_row(tmp_path):
    root=clone(tmp_path)
    def edit(db):
        first,second=db.execute("SELECT projection_row_id,annotations_json FROM source_provenance WHERE entity_type='message' ORDER BY projection_row_id LIMIT 2").fetchall()
        # Force a cache hit for the later row, then corrupt a field outside the
        # cached annotation.  Per-row identity validation must still reject it.
        db.execute("UPDATE source_provenance SET annotations_json=?,raw_record_id='bad' WHERE projection_row_id=?",(first[1],second[0]))
    mutate(root,edit)
    with pytest.raises(ss.SnapshotError,match='INVALID_MESSAGE_ID'):
        read(root,tmp_path/'cache')


def test_lg2_duplicate_report_key_rejected():
    with sqlite3.connect(':memory:') as db:
        db.executescript(lg.SQL)
        db.execute('INSERT INTO legacy_generation_reports(raw_ref,reported_code) VALUES (?,0)',(bytes(32),))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO legacy_generation_reports(raw_ref,reported_code) VALUES (?,1)',(bytes(32),))


@pytest.mark.parametrize('change',[
    lambda db:db.execute('UPDATE legacy_generation_reports SET reported_code=1'),
    lambda db:db.execute('DELETE FROM legacy_generation_witnesses WHERE cache_kind<>1'),
    lambda db:db.execute("UPDATE legacy_generation_witnesses SET locator='different'"),
    lambda db:db.execute('UPDATE legacy_generation_witnesses SET record_hash=randomblob(32)'),
    lambda db:(db.execute('DELETE FROM legacy_generation_witnesses'),db.execute('DELETE FROM legacy_generation_reports')),
])
def test_lg2_continuity_report_witness_loss_or_conflict(tmp_path,change):
    root=clone(tmp_path);_,prior=read(root,tmp_path/'cache')
    advance(root,change)
    with pytest.raises(ss.SnapshotError,match='CONTINUITY_LG2'):
        read(root,tmp_path/'cache',prior)


def test_lg2_heartbeat_restart_cache_binding(tmp_path):
    _,prior=read(fixture('normal-concrete'),tmp_path/'cache')
    with patch.object(v.ProjectionReader,'_schema',side_effect=AssertionError('warm schema scan')),patch.object(lg,'validate',side_effect=AssertionError('warm audit scan')):
        _,warm=read(fixture('heartbeat-reuse'),tmp_path/'cache',prior)
    assert warm['validation_cache_reused'] and warm['routing_cache_reused']
    assert warm['snapshot_id']=='2' and warm['database_content_id']==prior['database_content_id']
    mismatch=copy.deepcopy(warm)
    mismatch['validated_content']['content_binding']['legacy_generation_encoding']='wrong'
    _,rebuilt=read(fixture('heartbeat-reuse'),tmp_path/'cache',mismatch)
    assert not rebuilt.get('validation_cache_reused') and not rebuilt.get('routing_cache_reused')
    assert rebuilt['content_binding']['legacy_generation_encoding']==lg.ENCODING


def historical(root,cache,revision):
    """Construct a candidate historical checkpoint from identical synthetic rows."""
    audits={}
    def edit(db):
        for row in db.execute('SELECT message_id FROM legacy_generation_reports'):
            audits[row[0]]=lg.audit_view(db,row[0])['legacy_generation']
        if revision=='A1-LG1':
            for row in db.execute('SELECT entity_type,projection_row_id,annotations_json FROM source_provenance').fetchall():
                a=c.loads(row[2]);a['legacy_generation']=audits.get(row[1]) if row[0]=='message' else None
                db.execute('UPDATE source_provenance SET annotations_json=? WHERE entity_type=? AND projection_row_id=?',(c.canonical(a).decode(),row[0],row[1]))
        db.execute('DROP TABLE legacy_generation_witnesses');db.execute('DROP TABLE legacy_generation_reports')
    def change(m):
        m.update(contract_revision=revision);m.pop('legacy_generation_encoding')
        if revision=='A1':m.pop('legacy_generation_policy')
        for t in lg.TABLES:m['row_counts'].pop(t)
    m=rewrite(root,change,edit)
    if revision=='A1':return read(root,cache)[1],audits
    # Current reader intentionally cannot activate LG1. A candidate checkpoint
    # needs an explicitly supplied, hash-bound historical copy, not LG1 fallback.
    cache.mkdir();path=cache/(m['sha256']+'.sqlite');shutil.copyfile(root/m['database'],path);path.chmod(0o600)
    pointer=json.loads((root/'current.json').read_text())
    return dict(manifest=m,manifest_hash=pointer['manifest_sha256'],manifest_canonical_hash=c.digest(m),
        snapshot_id=m['snapshot_id'],database_content_id=m['database_content_id'],database_hash=m['sha256'],
        produced_at=m['produced_at'],published_at=pointer['published_at'],watermarks=m['watermarks'],
        coverage_history=m['coverage_history'],contract_revision=revision,cache_path=str(path)),audits


def to_lg2(root,audits):
    def edit(db):
        db.executescript(lg.SQL)
        for mid,a in audits.items():
            raw=bytes.fromhex(mid[4:]);db.execute('INSERT INTO legacy_generation_reports(raw_ref,reported_code) VALUES (?,?)',(raw,int(a['reported_generation'])))
            for w in a['linked_cache_records']:
                h=bytes.fromhex(w['record_sha256']);locator=w['source_record_locator'];kind=next(k for k,v in lg.KINDS.items() if v==w['cache_table'])
                db.execute('INSERT INTO legacy_generation_witnesses VALUES (?,?,?,?)',(raw,kind,h,'' if locator==h.hex() else locator))
        for row in db.execute('SELECT entity_type,projection_row_id,annotations_json FROM source_provenance').fetchall():
            a=c.loads(row[2]);a.pop('legacy_generation',None)
            db.execute('UPDATE source_provenance SET annotations_json=? WHERE entity_type=? AND projection_row_id=?',(c.canonical(a).decode(),row[0],row[1]))
    advance(root,edit)
    rewrite(root,lambda m:m.update(contract_revision=lg.REVISION,legacy_generation_policy=lg.POLICY,legacy_generation_encoding=lg.ENCODING))


@pytest.mark.parametrize('revision',['A1','A1-LG1'])
def test_explicit_lg2_migration_preserves_archive_rebuilds_and_rejects_downgrade(tmp_path,revision):
    root=clone(tmp_path);cache=tmp_path/'cache';prior,audits=historical(root,cache,revision)
    saved=Path(prior['cache_path']).read_bytes();to_lg2(root,audits)
    with pytest.raises(ss.SnapshotError,match='CONTINUITY_LG2_ACTIVATION_REQUIRED'):read(root,cache,prior)
    _,meta=read(root,cache,prior,activate_lg2=True)
    assert meta['revision_migration']=='EXPLICIT_LG2_REBUILD'
    assert not meta.get('validation_cache_reused') and not meta.get('routing_cache_reused')
    assert meta['revision_history'][0]['manifest']==prior['manifest']
    with v.ProjectionReader(root,cache) as reader:
        _,restart=reader.read(lambda conn:pr.build(conn,reader),previous=meta,now=NOW)
        reader.cleanup(restart['cache_path'],restart['routing_cache']['path'])
    assert Path(prior['cache_path']).read_bytes()==saved
    assert restart['validation_cache_reused'] and restart['routing_cache_reused']
    def downgrade(m):
        m.update(contract_revision='A1');m.pop('legacy_generation_policy');m.pop('legacy_generation_encoding')
        for t in lg.TABLES:m['row_counts'].pop(t)
    rewrite(root,downgrade)
    with pytest.raises(ss.SnapshotError,match='CONTINUITY_REVISION_DOWNGRADE'):read(root,cache,restart,activate_lg2=True)


def test_lg1_migration_requires_exact_logical_audit(tmp_path):
    root=clone(tmp_path);cache=tmp_path/'cache';prior,audits=historical(root,cache,'A1-LG1')
    next(iter(audits.values()))['reported_generation']='1'
    to_lg2(root,audits)
    with pytest.raises(ss.SnapshotError,match='CONTINUITY_LG1_AUDIT_MISMATCH'):read(root,cache,prior,activate_lg2=True)


@pytest.mark.parametrize('name',[n for n in NAMES if n!='true-conflict'])
def test_lg2_routing_parity_and_no_audit_credit(tmp_path,name):
    def consume(db):
        obs,edges=router._worker_snapshot_profiles(db)
        expected=router.ProfileBuilder(obs,edges,canonical_order=True).build_all()
        with v.ProjectionReader(fixture(name),tmp_path/'inner') as inner:
            # Independent full evaluator parity, with identical captured evidence.
            actual,_=inner.read(lambda conn:pr.build(conn,inner),now=NOW)
        assert {k:asdict(p) for k,p in expected.items()}=={k:asdict(p) for k,p in actual.items()}
        for task in ('Write Python regression tests','Debug Technocore signed posts'):
            assert asdict(router.Router(expected).route(task))==asdict(router.Router(actual).route(task))
        return len(edges)
    read(fixture(name),tmp_path/'cache',consume=consume)


def test_report_only_addition_dedup_and_hour_restart(tmp_path):
    root=clone(tmp_path);cache=tmp_path/'cache';profiles,prior=read(root,cache)
    def extra(db):
        raw=db.execute('SELECT raw_ref FROM legacy_generation_reports').fetchone()[0]
        db.execute('INSERT INTO legacy_generation_witnesses VALUES (?,2,?,?)',(raw,bytes.fromhex('ab'*32),'additional-witness'))
    advance(root,extra);later,meta=read(root,cache,prior)
    assert prior['routing_input_hash']==meta['routing_input_hash']
    assert {k:asdict(p) for k,p in profiles.items()}=={k:asdict(p) for k,p in later.items()}
    with v.ProjectionReader(root,cache) as reader:
        _,restart=reader.read(lambda conn:pr.build(conn,reader),previous=meta,now=NOW+timedelta(hours=1),max_age=7200)
    assert restart['routing_input_hash']==prior['routing_input_hash']


@pytest.mark.parametrize('stage',['lg2_report_validation','lg2_witness_validation','lg2_audit_reconstruction'])
def test_lg2_cancellation_cleans_candidate(tmp_path,stage):
    root=clone(tmp_path)
    with v.ProjectionReader(root,tmp_path/'cache') as reader:
        real=reader.stage
        def stop(name):
            if name==stage:raise ss.Cancelled()
            return real(name)
        with patch.object(reader,'stage',stop),pytest.raises(ss.Cancelled):reader.read(lambda conn:pytest.fail('cancelled consumed'),now=NOW)
    assert not list((tmp_path/'cache').glob('.candidate-*'))
    assert not list((tmp_path/'cache').glob('*.sqlite'))


def test_lg2_worker_decisions_dedup_recovery_and_persisted_binding(tmp_path):
    root=clone(tmp_path);state=tmp_path/'state'
    paths=router.worker_paths(state);paths['dir'].mkdir(parents=True)
    paths['tasks'].write_text(json.dumps({'task_id':'task','task':'Write Python regression tests'})+'\n')
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return NOW
    with patch.object(router,'datetime',Clock):
        first=router.worker_once(state,scout_snapshot_root=root)
        assert first['status']=='READY_ACTIVE'
        history=paths['decisions'].read_bytes()
        def extra(db):
            raw=db.execute('SELECT raw_ref FROM legacy_generation_reports').fetchone()[0]
            db.execute('INSERT INTO legacy_generation_witnesses VALUES (?,2,?,?)',(raw,b'\xab'*32,'new-witness'))
        advance(root,extra)
        with patch.object(router.Router,'route',side_effect=AssertionError('audit-only re-route')):
            second=router.worker_once(state,scout_snapshot_root=root)
        assert second['status']=='READY_IDLE' and paths['decisions'].read_bytes()==history
        accepted=json.loads(paths['state'].read_text())['last_accepted_projection_v2']
        assert accepted['content_binding']==lg.binding(accepted['manifest'])
        assert accepted['legacy_generation_audit']['witness_count']==3
        current=(root/'current.json').read_bytes()
        mutate(root,lambda db:db.execute('UPDATE legacy_generation_reports SET reported_code=1'))
        failed=router.worker_once(state,scout_snapshot_root=root)
        assert failed['status']=='DEGRADED_INPUT_INVALID'
        assert paths['decisions'].read_bytes()==history
        assert json.loads(paths['state'].read_text())['last_accepted_projection_v2']==accepted
        (root/'current.json').write_bytes(current)
        recovered=router.worker_once(state,scout_snapshot_root=root)
        assert recovered['status']=='READY_IDLE'
        assert paths['decisions'].read_bytes()==history


@pytest.mark.parametrize('code',[0,1])
def test_report_cannot_bridge_workflow_generation(code):
    from test_projection_performance import workflow_database,kibble_events,verify_closure
    events=kibble_events()
    events=[(*e,{'generation':'UNKNOWN_LEGACY' if i<2 else str(code)}) for i,e in enumerate(events)]
    conn=workflow_database(events)
    try:
        conn.executescript(lg.SQL)
        # Audit tables are deliberately irrelevant to authoritative closure.
        conn.execute('INSERT INTO legacy_generation_reports(raw_ref,reported_code) VALUES (?,?)',(bytes(32),code))
        with pytest.raises(ss.SnapshotError):verify_closure(conn)
    finally:conn.close()


def test_lg2_qualification_cannot_add_generation_authority(tmp_path):
    root=clone(tmp_path,'same-operator-bench')
    def edit(db):
        row=db.execute('SELECT qualification_id,record_json FROM durable_qualifications LIMIT 1').fetchone()
        q=c.loads(row[1]);q['resolved_generation']='0'
        q['qualification_id']=c.identity('dq1',q)
        db.execute('UPDATE durable_qualifications SET record_json=? WHERE qualification_id=?',(c.canonical(q).decode(),row[0]))
    mutate(root,edit)
    with pytest.raises(ss.SnapshotError):read(root,tmp_path/'cache')


def test_lg2_witness_query_uses_bounded_indexed_join(tmp_path):
    import inspect
    source=inspect.getsource(lg.validate)
    query=source.split("query='''",1)[1].split("'''",1)[0]
    def consume(db):
        plan=[r[3] for r in db.execute('EXPLAIN QUERY PLAN '+query)]
        assert any('SCAN r' in p for p in plan)
        assert any('SEARCH p USING INDEX sqlite_autoindex_source_provenance' in p for p in plan)
        assert any('SEARCH w USING PRIMARY KEY' in p for p in plan)
        assert not any('SCAN p' in p or 'SCAN w' in p for p in plan)
    read(fixture('legacy-reported-0'),tmp_path/'cache',consume=consume)


def test_lg2_locator_token_decodes_exactly():
    assert lg.witness({'cache_kind':1,'record_hash':bytes(32),'locator':''},0)['source_record_locator']=='00'*32
    assert lg.witness({'cache_kind':3,'record_hash':bytes(32),'locator':'é/a:1'},1)['source_record_locator']=='é/a:1'


@pytest.mark.parametrize('count',[257,180])
def test_lg2_witness_and_logical_annotation_bounds(tmp_path,count):
    root=clone(tmp_path)
    def edit(db):
        raw=db.execute('SELECT raw_ref FROM legacy_generation_reports').fetchone()[0]
        db.execute('DELETE FROM legacy_generation_witnesses')
        for n in range(count):
            db.execute('INSERT INTO legacy_generation_witnesses VALUES (?,1,?,?)',(raw,n.to_bytes(32,'big'),str(n)+'x'*250))
    mutate(root,edit)
    with pytest.raises(ss.SnapshotError,match='LG2_WITNESS_BOUNDS|LG2_LOGICAL_ANNOTATION_TOO_LARGE'):
        read(root,tmp_path/'cache')


@pytest.mark.parametrize('old,new',[
    ('reported_code IN (0, 1)','reported_code IN (0, 1, 2)'),
    (' REFERENCES legacy_generation_reports(raw_ref)',' REFERENCES messages(projection_row_id)'),
    ('VIRTUAL','STORED'),
    ("'sm1:' || lower(hex(raw_ref))","'other:' || lower(hex(raw_ref))"),
])
def test_lg2_constraints_and_generated_definition_drift(tmp_path,old,new):
    root=clone(tmp_path)
    def edit(db):
        db.execute('PRAGMA writable_schema=ON')
        db.execute("UPDATE sqlite_master SET sql=replace(sql,?,?) WHERE name LIKE 'legacy_generation_%'",(old,new))
        db.execute('PRAGMA writable_schema=OFF')
    rewrite(root,sql=edit)
    with pytest.raises(ss.SnapshotError):read(root,tmp_path/'cache')


@pytest.mark.parametrize('damage',['revision','policy','history','archive'])
def test_lg2_restart_rejects_bad_continuity_binding(tmp_path,damage):
    root=clone(tmp_path);_,prior=read(root,tmp_path/'cache')
    if damage=='revision':prior['contract_revision']='A1-LG1'
    elif damage=='policy':prior['content_binding']['legacy_generation_policy']['watermark_domain']='REPORTED'
    elif damage=='history':prior['revision_history']=[dict(prior)]
    else:prior['revision_history']=[{'contract_revision':'A1','manifest':{}}]
    with pytest.raises(ss.SnapshotError,match='CONTINUITY_'):read(root,tmp_path/'cache',prior)


def test_lg2_worker_migration_flag_persists_history(tmp_path):
    root=clone(tmp_path);state=tmp_path/'state';paths=router.worker_paths(state)
    cache=paths['dir']/'v2-copies';cache.parent.mkdir(parents=True)
    prior,audits=historical(root,cache,'A1');to_lg2(root,audits)
    paths['state'].write_text(json.dumps({'scout_contract':'V2_A1','last_accepted_projection_v2':prior}))
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return NOW
    with patch.object(router,'datetime',Clock):
        assert router.worker_once(state,scout_snapshot_root=root)['status']=='DEGRADED_INPUT_INVALID'
        cycle=router.worker_once(state,scout_snapshot_root=root,activate_scout_lg2=True)
        assert cycle['status']=='READY_IDLE'
    persisted=json.loads(paths['state'].read_text())['last_accepted_projection_v2']
    assert persisted['revision_history'][0]['manifest']==prior['manifest']
    assert Path(prior['cache_path']).exists()


def test_lg2_interaction_identity_and_multiplicity_remain_captured(tmp_path):
    root=clone(tmp_path)
    def edge(db):
        # Immutable source endpoint identity contains captured UNKNOWN_LEGACY.
        identity=c.digest({'source':{'generation':'UNKNOWN_LEGACY','raw_id':'a'},
                           'target':{'generation':'UNKNOWN_LEGACY','raw_id':'b'},'relationship':'DIRECT_REPLY'})
        rid='si1:'+identity
        db.execute('INSERT INTO interactions VALUES (?,?,?,?,?)',(rid,router.SCOUT_DID,router.BENCH_DID,'DIRECT_REPLY',.5))
        a=dict(c.ANNOTATIONS,operator_group=c.FAMILY,same_operator=True,independent_reputation=False)
        db.execute('INSERT INTO source_provenance VALUES (?,?,?,?,?,?,?,?)',('interaction',rid,'scout-observer',rid,None,None,None,c.canonical(a).decode()))
        db.execute('INSERT INTO selection_membership VALUES (?,?,?,?,?,?)',('interaction',rid,'IDENTITY_OPERATOR','2026-09-08T12:00:00Z',None,'[]'))
    mutate(root,edge)
    def ids(db):return [tuple(r) for r in db.execute('SELECT * FROM interactions ORDER BY projection_row_id')]
    original,prior=read(root,tmp_path/'cache',consume=ids)
    def extra(db):
        raw=db.execute('SELECT raw_ref FROM legacy_generation_reports').fetchone()[0]
        db.execute('INSERT INTO legacy_generation_witnesses VALUES (?,3,?,?)',(raw,b'\x12'*32,'additional'))
    advance(root,extra);after,meta=read(root,tmp_path/'cache',prior,consume=ids)
    assert original==after and len(after)==1
    assert prior['watermarks']==meta['watermarks']
    assert prior['routing_input_hash']==meta['routing_input_hash']


@pytest.mark.parametrize('damage',['substantive-row','archive-loss'])
def test_lg2_migration_preserves_substantive_rows_and_archived_bytes(tmp_path,damage):
    root=clone(tmp_path);cache=tmp_path/'cache';prior,audits=historical(root,cache,'A1-LG1');to_lg2(root,audits)
    if damage=='substantive-row':
        mutate(root,lambda db:db.execute("UPDATE source_provenance SET raw_record_sha256=printf('%064d',0) WHERE entity_type='message'"))
        with pytest.raises(ss.SnapshotError,match='CONTINUITY_MIGRATION_ROW_CHANGED'):read(root,cache,prior,activate_lg2=True)
    else:
        _,accepted=read(root,cache,prior,activate_lg2=True)
        Path(prior['cache_path']).unlink()
        with pytest.raises(ss.SnapshotError,match='CONTINUITY_COPY_UNAVAILABLE'):read(root,cache,accepted)
