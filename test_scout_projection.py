"""V2/A1 consumer safety and Scout-produced compatibility tests. Temporary data only."""
import copy
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import tempfile
import time
from unittest.mock import patch

import pytest
import router
import scout_projection as v
import scout_snapshot as ss
import projection_contract as c
from projection_test_support import publish_snapshot

FIXTURES=Path('/private/tmp/scout-v2-a1-review-fixtures')
NOW=datetime(2026,9,8,12,0,10,tzinfo=timezone.utc)


def fixture(name):
    if not (FIXTURES/'index.json').exists(): pytest.skip('Scout temporary compatibility fixtures unavailable')
    return FIXTURES/name


def read(root,cache,previous=None,consume=None,**kwargs):
    with v.ProjectionReader(root,cache,**kwargs) as reader:
        return reader.read(consume or (lambda conn: router._worker_snapshot_profiles(conn,reader.check)),previous=previous,now=NOW)


def clone(tmp_path,name='normal'):
    target=tmp_path/'publication';shutil.copytree(fixture(name),target)
    return target


def rewrite(root,change=None,sql=None):
    pointer=json.loads((root/'current.json').read_text());m=json.loads((root/pointer['manifest']).read_text())
    if sql:
        # Mutate only this test's copied fixture, never Scout's fixture.
        db=root/m['database'];conn=sqlite3.connect(db);conn.row_factory=sqlite3.Row
        sql(conn);conn.commit();conn.close()
        h=hashlib.sha256(db.read_bytes()).hexdigest();new=f"router-projection-v2-{m['database_content_id']}-{h}.sqlite";db.rename(root/new)
        m.update(database=new,sha256=h,size_bytes=(root/new).stat().st_size)
    if change:change(m)
    raw=c.canonical(m);digest=hashlib.sha256(raw).hexdigest();name=f"manifest-v2-{m['snapshot_id']}-{digest}.json";(root/name).write_bytes(raw)
    pointer.update(manifest=name,manifest_sha256=digest,published_at=m['produced_at']);(root/'current.json').write_bytes(c.canonical(pointer))
    return m


@pytest.mark.parametrize('name,count,quals,events',[
 ('normal',1,5,0),('heartbeat-reuse',1,5,0),('duplicate-downgrade',2,5,0),
 ('invalidation-audit',2,5,1),('same-operator-bench',2,6,1),('unknown-legacy',1,0,0)])
def test_scout_fixture_private_copy_ingestion(tmp_path,name,count,quals,events):
    def consume(conn):
        location=Path(conn.execute('PRAGMA database_list').fetchone()[2])
        assert location.is_relative_to(tmp_path)
        assert conn.execute('PRAGMA query_only').fetchone()[0]==1
        with pytest.raises(sqlite3.OperationalError):conn.execute('DELETE FROM messages')
        rows,edges=router._worker_snapshot_profiles(conn)
        q=[c.loads(r[0]) for r in conn.execute('SELECT record_json FROM durable_qualifications')]
        if name=='same-operator-bench':
            bench=next(x for x in q if x['qualification_type']=='CONTROLLED_BENCH')
            assert (bench['operator_group'],bench['same_operator'],bench['independent_reputation'])==(c.FAMILY,True,False)
        if name=='unknown-legacy':assert rows[0].generation=='UNKNOWN_LEGACY'
        return rows,q
    (rows,q),m=read(fixture(name),tmp_path/'cache',consume=consume)
    assert len(rows)==count and len(q)==quals
    assert m['qualification_history']['events']==events
    assert m['readiness']=='READY'
    assert all(k in m['stage_seconds'] for k in ('pointer_read','manifest_read','database_copy','sha256','sqlite_open','integrity_validation','schema_validation','watermark_validation','qualification_loading','evidence_materialization'))


def test_scout_heartbeat_restart_and_audit_downgrade(tmp_path):
    cache=tmp_path/'cache'
    (original,_),first=read(fixture('normal'),cache)
    with patch.object(v.ProjectionReader,'_copy_database',side_effect=AssertionError('heartbeat copied')):
        (_, _),heart=read(fixture('heartbeat-reuse'),cache,first)
    assert heart['snapshot_id']=='2' and heart['database_content_id']==first['database_content_id']
    (later,_),second=read(fixture('duplicate-downgrade'),cache,heart)
    before=router.capability_evidence_decisions(original,'software.debugging')
    after=router.capability_evidence_decisions(later,'software.debugging')
    assert any(x.support_contribution=='STRONG' for x in before)
    assert not any(x.support_contribution=='STRONG' for x in after)
    assert second['qualification_history']['qualifications']==5
    _,third=read(fixture('invalidation-audit'),cache,second)
    assert third['qualification_history']['events']==1
    _,fourth=read(fixture('same-operator-bench'),cache,third)
    assert fourth['qualification_history']['qualifications']==6


@pytest.mark.parametrize('field,value', [('contract_revision','A2'),('database_schema_version','scout-observer/v1'),('schema','flop-scout-router-snapshot/v1'),('publication_kind','NOOP')])
def test_unsupported_contract_fields(tmp_path,field,value):
    root=clone(tmp_path);rewrite(root,lambda m:m.update({field:value}))
    with pytest.raises(ss.SnapshotError):read(root,tmp_path/'cache')


@pytest.mark.parametrize('field', ['version','classifier_version','qualification_policy_version','parameters'])
def test_manifest_policy_versions_and_parameters(tmp_path,field):
    root=clone(tmp_path)
    def mutate(m):m['selection_policy'][field]='unsupported';m['selection_policy_sha256']=c.digest(m['selection_policy'])
    rewrite(root,mutate)
    with pytest.raises(ss.SnapshotError,match='UNSUPPORTED_POLICY'):read(root,tmp_path/'cache')


@pytest.mark.parametrize('mutation', ['missing-table','extra-column','trigger','foreign-key','watermark','coverage','expiry','operator','message-hash','provenance','duplicate-position'])
def test_schema_rows_and_provenance_fail_closed(tmp_path,mutation):
    root=clone(tmp_path)
    def mutate(conn):
        if mutation=='missing-table':conn.execute('DROP TABLE qualification_events')
        elif mutation=='extra-column':conn.execute('ALTER TABLE messages ADD COLUMN surprise TEXT')
        elif mutation=='trigger':conn.execute('CREATE TRIGGER surprise AFTER INSERT ON messages BEGIN SELECT 1; END')
        elif mutation=='foreign-key':conn.execute("INSERT INTO qualification_events VALUES ('x','missing',1,'{}')")
        elif mutation=='watermark':conn.execute('UPDATE watermarks SET record_count=99')
        elif mutation=='coverage':conn.execute("UPDATE coverage_history SET witness_record_sha256=?",('0'*64,))
        elif mutation=='expiry':conn.execute("UPDATE selection_membership SET retain_until='2026-09-08T12:00:00Z'")
        elif mutation=='operator':
            a=c.loads(conn.execute('SELECT annotations_json FROM source_provenance').fetchone()[0]);a.update(operator_group=c.FAMILY,same_operator=True,independent_reputation=True)
            conn.execute('UPDATE source_provenance SET annotations_json=?',(c.canonical(a).decode(),))
        elif mutation=='message-hash':conn.execute('UPDATE messages SET message_hash=?',('0'*64,))
        elif mutation=='provenance':conn.execute('DELETE FROM source_provenance')
        elif mutation=='duplicate-position':conn.execute("UPDATE messages SET seq=-1")
    if mutation=='duplicate-position':
        with pytest.raises(sqlite3.IntegrityError):rewrite(root,sql=mutate)
    else:
        rewrite(root,sql=mutate)
        with pytest.raises(ss.SnapshotError):read(root,tmp_path/'cache')


@pytest.mark.parametrize('mutation', ['id','version','proof','subject','family','event-gap','event-hash','event-target'])
def test_malformed_qualification_and_events(tmp_path,mutation):
    root=clone(tmp_path,'invalidation-audit')
    def mutate(conn):
        if mutation.startswith('event'):
            e=c.loads(conn.execute('SELECT event_json FROM qualification_events').fetchone()[0])
            if mutation=='event-gap':e['sequence']=2
            elif mutation=='event-hash':e['event_id']='dqe1:'+'0'*64
            else:e['qualification_id']='dq1:'+'0'*64
            conn.execute('UPDATE qualification_events SET event_json=?',(c.canonical(e).decode(),))
        else:
            key,raw=conn.execute('SELECT qualification_id,record_json FROM durable_qualifications LIMIT 1').fetchone();q=c.loads(raw)
            if mutation=='id':q['qualification_id']='dq1:'+'0'*64
            elif mutation=='version':q['classifier_version']='old'
            elif mutation=='proof':q['provenance_refs']=[]
            elif mutation=='subject':q['subject_did']='did:key:wrong'
            else:q.update(operator_group=c.FAMILY,same_operator=True,independent_reputation=True)
            conn.execute('UPDATE durable_qualifications SET record_json=? WHERE qualification_id=?',(c.canonical(q).decode(),key))
    rewrite(root,sql=mutate)
    with pytest.raises(ss.SnapshotError):read(root,tmp_path/'cache')


@pytest.mark.parametrize('name', ['normal','heartbeat-reuse'])
def test_publication_and_content_rollback(tmp_path,name):
    _,last=read(fixture('duplicate-downgrade'),tmp_path/'cache')
    with pytest.raises(ss.SnapshotError,match='CONTINUITY_'):read(fixture(name),tmp_path/'cache',last)


def test_heartbeat_metadata_lies(tmp_path):
    _,last=read(fixture('normal'),tmp_path/'cache')
    root=clone(tmp_path,'heartbeat-reuse');rewrite(root,lambda m:m['row_counts'].update(messages=2))
    with pytest.raises(ss.SnapshotError,match='CONTINUITY_CONTENT_CONFLICT'):read(root,tmp_path/'cache',last)


def test_restart_missing_or_corrupted_copy(tmp_path):
    _,last=read(fixture('normal'),tmp_path/'cache')
    Path(last['cache_path']).write_bytes(b'broken')
    with pytest.raises(ss.SnapshotError,match='CONTINUITY_CACHE'):read(fixture('heartbeat-reuse'),tmp_path/'cache',last)
    Path(last['cache_path']).unlink()
    with pytest.raises(ss.SnapshotError,match='CONTINUITY_COPY'):read(fixture('heartbeat-reuse'),tmp_path/'cache',last)


def test_v1_not_accepted(tmp_path):
    from test_scout_snapshot import publish_snapshot as v1
    root=tmp_path/'v1';v1(root)
    with pytest.raises(ss.SnapshotError,match='UNSUPPORTED_CONTRACT'):read(root,tmp_path/'cache')


@pytest.mark.parametrize('when',['2026-09-08T09:00:00Z','2026-09-08T13:00:00Z'])
def test_freshness_and_future(tmp_path,when):
    with v.ProjectionReader(fixture('normal'),tmp_path/'cache') as reader:
        with pytest.raises(ss.SnapshotError):reader.read(lambda c:None,now=c.instant(when),max_age=60)


@pytest.mark.parametrize('bad_name', ['../x','/tmp/x','a/b','a\\b','','..','manifest-v2-01-'+'0'*64+'.json'])
def test_pointer_names_fail_before_artifact_open(tmp_path,bad_name):
    root=clone(tmp_path);p=c.loads((root/'current.json').read_bytes());p['manifest']=bad_name;(root/'current.json').write_bytes(c.canonical(p))
    with pytest.raises(ss.SnapshotError):read(root,tmp_path/'cache')


def test_symlink_and_fifo_artifacts(tmp_path):
    root=clone(tmp_path);current=root/'current.json';raw=current.read_bytes();current.unlink();os.mkfifo(current)
    before=time.monotonic()
    with pytest.raises(ss.SnapshotError):read(root,tmp_path/'cache')
    assert time.monotonic()-before<1
    current.unlink();outside=tmp_path/'pointer';outside.write_bytes(raw);current.symlink_to(outside)
    with pytest.raises(ss.SnapshotError):read(root,tmp_path/'cache')


def test_pointer_replacement_keeps_verified_manifest(tmp_path):
    root=clone(tmp_path);old=v.ProjectionReader._read_json_file
    def raced(reader,name,limit):
        data=old(reader,name,limit)
        if name=='current.json':(root/'current.json').write_bytes(b'{}')
        return data
    with patch.object(v.ProjectionReader,'_read_json_file',raced):
        _,m=read(root,tmp_path/'cache')
    assert m['readiness']=='READY'


def test_bounded_json_timeout_memory_and_size(tmp_path):
    root=clone(tmp_path)
    with v.ProjectionReader(root,tmp_path/'cache',timeout=.000001) as r:
        with pytest.raises(ss.SnapshotError):r.read(lambda c:None,now=NOW)
        assert r.metadata['readiness']=='TOO_SLOW'
    with v.ProjectionReader(root,tmp_path/'cache',max_memory=1) as r:
        with pytest.raises(ss.SnapshotError):r.read(lambda c:None,now=NOW)
        assert r.metadata['readiness']=='MEMORY_LIMIT'
    with v.ProjectionReader(root,tmp_path/'cache',max_bytes=100) as r:
        with pytest.raises(ss.SnapshotError):r.read(lambda c:None,now=NOW)
        assert r.metadata['readiness']=='TOO_LARGE'
    (root/'current.json').write_bytes(b'x'*(ss.MAX_CURRENT_BYTES+1))
    with pytest.raises(ss.SnapshotError,match='JSON_TOO_LARGE'):read(root,tmp_path/'cache')


@pytest.mark.parametrize('stage',['_read_json_file','_copy_database','_schema','_rows','_coverage','_qualifications','_worker_snapshot_profiles'])
def test_cancel_every_stage_cleans_temporary_copies(tmp_path,stage):
    cancel=router.WorkerCancellation(); owner=router if stage=='_worker_snapshot_profiles' else v.ProjectionReader
    original=getattr(owner,stage)
    def cancelled(*a,**kw):cancel.request(None,None);return original(*a,**kw)
    with v.ProjectionReader(fixture('normal'),tmp_path/'cache',cancel.check) as r:
        with patch.object(owner,stage,cancelled),pytest.raises(ss.Cancelled):
            r.read(lambda conn:router._worker_snapshot_profiles(conn,r.check),now=NOW)
    assert not list((tmp_path/'cache').glob('*.sqlite'))
    assert not list((tmp_path/'cache').glob('.candidate-*'))


def test_history_loss_cannot_hide_behind_new_hash(tmp_path):
    cache=tmp_path/'cache';_,last=read(fixture('normal'),cache)
    root=clone(tmp_path,'duplicate-downgrade')
    rewrite(root,lambda m:m['row_counts'].update(durable_qualifications=0),lambda conn:conn.execute('DELETE FROM durable_qualifications'))
    with pytest.raises(ss.SnapshotError,match='CONTINUITY_AUDIT_LOSS'):read(root,cache,last)


def test_corrupt_state_preserved_and_legacy_health_unknown(tmp_path):
    state=tmp_path/'state';paths=router.worker_paths(state);paths['dir'].mkdir(parents=True)
    paths['state'].write_text('{broken');before=paths['state'].read_bytes()
    cycle=router.worker_once(state,scout_snapshot_root=fixture('normal'))
    assert cycle['status']=='ERROR' and paths['state'].read_bytes()==before
    paths['state'].write_text(json.dumps(dict(status='HEALTHY',last_success_at='old')))
    assert router.worker_status(state)['readiness']=='UNKNOWN_LEGACY'


def test_canonical_order_and_substantive_input_dedup(tmp_path):
    rows,_=read(fixture('duplicate-downgrade'),tmp_path/'cache')[0]
    profiles=router.ProfileBuilder(rows).build_all()
    records=[router.observation_to_record(r) for r in rows]
    assert router._worker_evidence_snapshot(profiles,{'ingest_store':records})==router._worker_evidence_snapshot(profiles,{'ingest_store':records[::-1]})
    for field in ('generation','verification_status','text'):
        changed=copy.deepcopy(records);changed[0][field]='changed'
        assert router._worker_evidence_snapshot(profiles,{'ingest_store':records})!=router._worker_evidence_snapshot(profiles,{'ingest_store':changed})


def test_scout_oversize_before_sqlite(tmp_path):
    with v.ProjectionReader(fixture('oversize-rejection'),tmp_path/'cache') as r:
        with patch.object(r,'connection',side_effect=AssertionError('SQLite opened')),pytest.raises(ss.SnapshotError,match='SNAPSHOT_TOO_LARGE'):
            r.read(lambda c:None,now=NOW)
        assert r.metadata['readiness']=='TOO_LARGE'


def test_scout_large_warning_fixture(tmp_path):
    # Full streamed validation; no multi-GiB Python materialization.
    with v.ProjectionReader(fixture('large-size-warning'),tmp_path/'cache',timeout=180) as r:
        result,m=r.read(lambda conn:conn.execute('SELECT count(*) FROM messages').fetchone()[0],now=NOW)
    assert result==350000 and m['readiness']=='WARNING_LARGE'
    assert m['peak_rss_bytes']<v.MAX_MEMORY


def test_worker_scout_pipeline_and_v1_activation(tmp_path):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return NOW
    state=tmp_path/'state';paths=router.worker_paths(state);paths['dir'].mkdir(parents=True)
    paths['tasks'].write_text('{"task_id":"one","task":"Debug an HTTP 400 response"}\n')
    with patch.object(router,'datetime',Clock):
        first=router.worker_once(state,scout_snapshot_root=fixture('normal'))
        assert first['status']=='READY_ACTIVE'
        checkpoint=router.worker_status(state)['last_accepted_projection_v2']
        second=router.worker_once(state,scout_snapshot_root=fixture('heartbeat-reuse'))
        assert second['status']=='READY_IDLE' and second['duplicate_decisions_suppressed']==1
        third=router.worker_once(state,scout_snapshot_root=fixture('duplicate-downgrade'))
        assert third['status']=='READY_ACTIVE'
        persisted=router.worker_status(state)
        assert persisted['current_support']!=first['current_support']
        assert Path(persisted['last_accepted_projection_v2']['cache_path']).exists()
        assert persisted['sources'][0]['qualification_history']['qualifications']==5
    from test_scout_snapshot import publish_snapshot as v1
    root=tmp_path/'v1';v1(root)
    with patch.object(router.Router,'route',side_effect=AssertionError('routed V1')):
        assert router.worker_once(state,scout_snapshot_root=root)['status']=='DEGRADED_INPUT_INVALID'
    assert router.worker_status(state)['last_accepted_projection_v2']['snapshot_id']=='3'
    migration=tmp_path/'migration';paths=router.worker_paths(migration);paths['dir'].mkdir(parents=True)
    legacy=dict(snapshot_id='0',produced_at='2020-01-01T00:00:00Z',watermarks=[],database_hash='0'*64,manifest_hash='0'*64)
    paths['state'].write_text(json.dumps(dict(last_accepted_snapshot=legacy)))
    with patch.object(router,'datetime',Clock):
        assert router.worker_once(migration,scout_snapshot_root=fixture('normal'))['status']=='DEGRADED_INPUT_INVALID'
        assert router.worker_once(migration,scout_snapshot_root=fixture('normal'),activate_scout_v2=True)['status']=='READY_IDLE'
    assert router.worker_status(migration)['last_accepted_snapshot']==legacy


def test_sqlite_order_does_not_change_profiles(tmp_path):
    root=clone(tmp_path,'duplicate-downgrade')
    (before,_),_=read(root,tmp_path/'a')
    def reorder(conn):
        records=list(conn.execute('SELECT * FROM messages'))
        conn.execute('DELETE FROM messages')
        for row in reversed(records):conn.execute('INSERT INTO messages VALUES ('+','.join('?' for _ in row)+')',tuple(row))
    rewrite(root,sql=reorder)
    (after,_),_=read(root,tmp_path/'b')
    assert before==after
    assert router._worker_evidence_snapshot(router.ProfileBuilder(before).build_all())==router._worker_evidence_snapshot(router.ProfileBuilder(after).build_all())


def test_sigterm_integrity_and_loading_are_persisted(tmp_path):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return NOW
    for name in ('_schema','_qualifications'):
        original=getattr(v.ProjectionReader,name)
        def stop(reader,*a,**kw):
            os.kill(os.getpid(),signal.SIGTERM)
            return original(reader,*a,**kw)
        state=tmp_path/name
        with patch.object(router,'datetime',Clock),patch.object(v.ProjectionReader,name,stop):
            cycle=router.worker_once(state,scout_snapshot_root=fixture('normal'))
        assert cycle['status']=='ERROR'
        assert router.worker_status(state)['last_error']=='WORKER_CANCELLED'
        assert not router.worker_paths(state)['lock'].exists()
        assert not list((router.worker_paths(state)['dir']/'v2-copies').glob('*.sqlite'))


def test_sqlite_progress_cancellation_and_deadline(tmp_path):
    import threading
    for mode in ('cancel','deadline'):
        cancellation=router.WorkerCancellation()
        with v.ProjectionReader(fixture('normal'),tmp_path/mode,cancellation.check,timeout=.1 if mode=='deadline' else 30) as reader:
            def consume(conn):
                timer=threading.Timer(.02,lambda:cancellation.request(None,None)) if mode=='cancel' else None
                if timer:timer.start()
                try:
                    return conn.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
                finally:
                    if timer:timer.cancel();timer.join()
            with pytest.raises(ss.Cancelled if mode=='cancel' else ss.SnapshotError):reader.read(consume,now=NOW)
            if mode=='deadline':assert reader.metadata['readiness']=='TOO_SLOW'
        assert not list((tmp_path/mode).glob('*.sqlite'))


def test_rehashed_qualification_proof_and_event_gap(tmp_path):
    root=clone(tmp_path,'normal')
    def mutate(conn):
        qid,raw=conn.execute('SELECT qualification_id,record_json FROM durable_qualifications LIMIT 1').fetchone();q=c.loads(raw)
        q['source_ref']['sha256']='0'*64
        q['provenance_refs']=[q['source_ref']]
        q['qualification_id']=c.identity('dq1',{k:val for k,val in q.items() if k!='qualification_id'})
        conn.execute('DELETE FROM durable_qualifications WHERE qualification_id=?',(qid,))
        conn.execute('INSERT INTO durable_qualifications VALUES (?,?)',(q['qualification_id'],c.canonical(q).decode()))
    rewrite(root,sql=mutate)
    with pytest.raises(ss.SnapshotError,match='INVALID_DURABLE_PROOF'):read(root,tmp_path/'cache')


def test_expired_membership_vs_permanent_loss(tmp_path):
    # Zero-message synthetic view first, then an early disappearance of a real
    # permanent witness. Counts alone cannot authorize the disappearance.
    cache=tmp_path/'cache';_,prior=read(fixture('normal'),cache)
    root=tmp_path/'empty';publish_snapshot(root,snapshot_id='2',produced_at='2026-09-08T12:00:09Z')
    with pytest.raises(ss.SnapshotError):read(root,cache,prior)


def test_profile_checks_preserve_results_and_cancel(tmp_path):
    observations=read(fixture('duplicate-downgrade'),tmp_path/'cache')[0][0]
    before=router.ProfileBuilder(observations).build_all()
    count=[]
    after=router.ProfileBuilder(observations,check=lambda:count.append(1)).build_all()
    assert count and before==after
    def cancel():raise ss.Cancelled()
    with pytest.raises(ss.Cancelled):router.ProfileBuilder(observations,check=cancel).build_all()


def test_invalidation_effective_status_keeps_original(tmp_path):
    rows,m=read(fixture('invalidation-audit'),tmp_path/'cache',consume=lambda conn:list(v.qualification_history(conn)))
    assert len(rows)==5 and m['qualification_history']['invalidated']==1
    invalid=next(r for r in rows if r['effective_status']=='INVALIDATED')
    assert invalid['record']['initial_status']=='VALID'
    assert invalid['record']['qualification_outcome'] in {'LIMITED','STRONG'}


def test_once_persists_cancellation_delivered_after_commit(tmp_path):
    root=tmp_path/'publication';publish_snapshot(root)
    state=tmp_path/'state';paths=router.worker_paths(state);paths['dir'].mkdir(parents=True)
    paths['tasks'].write_text('{"task":"debug failure"}\n')
    original=router._safe_worker_cycle
    def after_commit(*args,**kwargs):
        result=original(*args,**kwargs)
        if result['status']=='READY_ACTIVE':os.kill(os.getpid(),signal.SIGTERM)
        return result
    with patch.object(router,'_safe_worker_cycle',after_commit):cycle=router.worker_once(state,scout_snapshot_root=root)
    assert cycle['status']=='ERROR'
    assert router.worker_status(state)['last_error']=='WORKER_CANCELLED'
    assert len(paths['decisions'].read_text().splitlines())==1
    history=[json.loads(line) for line in paths['cycles'].read_text().splitlines()]
    assert [r['shadow_decisions_produced'] for r in history]==[1,0]
