"""Parity, bounded derivation, verified cache and closure tests; synthetic only."""
from dataclasses import asdict
import copy
from datetime import timedelta
import json
import sqlite3
from unittest.mock import patch
import pytest
import router
import projection_routing as pr
import projection_contract as c
import scout_projection as v
import scout_snapshot as ss
from test_scout_projection import fixture, NOW

@pytest.mark.parametrize('name',['normal','heartbeat-reuse','duplicate-downgrade','invalidation-audit','same-operator-bench','unknown-legacy'])
def test_streamed_profile_parity(tmp_path,name):
    with v.ProjectionReader(fixture(name),tmp_path/'cache') as reader:
        def consume(conn):
            obs,edges=router._worker_snapshot_profiles(conn)
            expected=router.ProfileBuilder(obs,edges,canonical_order=True).build_all()
            actual=pr.build(conn,reader)
            assert {k:asdict(x) for k,x in actual.items()}=={k:asdict(x) for k,x in expected.items()}
            for task in ('Write Python regression tests', 'Debug Technocore signed posts'):
                assert asdict(router.Router(actual).route(task))==asdict(router.Router(expected).route(task))
            return actual
        profiles,meta=reader.read(consume,now=NOW)
        assert meta['routing_cache']['version']==pr.VERSION
        assert len(profiles)>0


def test_restart_cache_revalidates_hash_but_not_immutable_semantics(tmp_path):
    cache=tmp_path/'cache'
    with v.ProjectionReader(fixture('normal'),cache) as reader:
        _,first=reader.read(lambda conn:pr.build(conn,reader),now=NOW)
    with v.ProjectionReader(fixture('heartbeat-reuse'),cache) as reader:
        with patch.object(reader,'_rows',side_effect=AssertionError('replayed immutable validation')),patch.object(reader,'_qualifications',side_effect=AssertionError('replayed audit')):
            profiles,second=reader.read(lambda conn:pr.build(conn,reader),previous=first,now=NOW)
        assert second['validation_cache_reused'] and second['routing_cache_reused']
        assert len(reader.verified_files)==2
        assert len(profiles)>0

@pytest.mark.parametrize('artifact',['database','routing'])
def test_modified_private_cache_fails_closed(tmp_path,artifact):
    with v.ProjectionReader(fixture('normal'),tmp_path/'cache') as reader:
        _,first=reader.read(lambda conn:pr.build(conn,reader),now=NOW)
    path=first['cache_path'] if artifact=='database' else first['routing_cache']['path']
    with open(path,'r+b') as stream:stream.seek(100);stream.write(b'X')
    with v.ProjectionReader(fixture('heartbeat-reuse'),tmp_path/'cache') as reader:
        with pytest.raises(ss.SnapshotError,match='CONTINUITY_CACHE_HASH'):
            reader.read(lambda conn:pr.build(conn,reader),previous=first,now=NOW)


def test_cancel_summary_build_preserves_prior_files(tmp_path):
    with v.ProjectionReader(fixture('normal'),tmp_path/'cache') as reader:
        _,first=reader.read(lambda conn:pr.build(conn,reader),now=NOW)
    original=open(first['routing_cache']['path'],'rb').read()
    cancel=router.WorkerCancellation()
    with v.ProjectionReader(fixture('duplicate-downgrade'),tmp_path/'cache',cancel.check) as reader:
        real=router.semantic_decisions
        def interrupt(*args):cancel.request(None,None);return real(*args)
        with patch.object(router,'semantic_decisions',interrupt),pytest.raises(ss.Cancelled):
            reader.read(lambda conn:pr.build(conn,reader),previous=first,now=NOW)
        reader.cleanup(first['cache_path'],first['routing_cache']['path'])
    assert open(first['routing_cache']['path'],'rb').read()==original
    assert not list((tmp_path/'cache').glob('.summaries-*'))

@pytest.mark.parametrize('text',[
 'I can write Python software for a team.',
 'Reproduced the bug because the API failed with HTTP 403 after nonce reuse.',
 'A gardener walked through the garden and admired the flowers.',
 'I created unit tests against the API with regression fixtures because it failed.',
 'Not solidity or smart contract testing, never Python.',
 'The signer handles monotonic nonce increments and the signature verified with ed25519.',
 'A signed post workflow guide describes the testing setup.',
])
@pytest.mark.parametrize('duplicate',[1,2])
def test_semantic_prefilter_matches_complete_rules(text,duplicate):
    obs=router.AgentObservation(router.AgentIdentity('did:key:z6MkFixture'),'room',1,None,text,router.normalize_text(text),'hash',True)
    expected={d.capability_id:asdict(d) for rule in router.CAPABILITY_RULES if (d:=router.raw_capability_evidence_decision(obs,rule,duplicate)).relevant}
    actual={d.capability_id:asdict(d) for d in router.semantic_decisions(obs,duplicate)}
    assert actual==expected


def test_qualification_history_single_ordered_join(tmp_path):
    with v.ProjectionReader(fixture('invalidation-audit'),tmp_path/'cache') as reader:
        def consume(conn):
            queries=[];conn.set_trace_callback(queries.append)
            result=list(v.qualification_history(conn))
            assert len(queries)==1 and 'LEFT JOIN qualification_events' in queries[0]
            return result
        rows,_=reader.read(consume,now=NOW)
    assert any(x['effective_status']=='INVALIDATED' for x in rows)


def workflow_database(events, kind='WORK_LIFECYCLE'):
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row;conn.executescript(v.SCHEMA_SQL)
    for i,event in enumerate(events,1):
        sender,body,*options=event; options=options[0] if options else {}
        text=body if isinstance(body,str) else json.dumps(body)
        rid='sm1:r'+str(i)
        conn.execute('INSERT INTO messages(projection_row_id,room,generation,seq,sender,signed,text,message_hash,verification_status) VALUES (?,?,?,?,?,1,?,?,?)',(rid,'room',options.get('generation','1'),i,sender,text,c.text_hash(text),options.get('verification','VERIFIED_OFFLINE')))
        conn.execute('INSERT INTO source_provenance VALUES (?,?,?,?,?,?,?,?)',('message',rid,options.get('source','scout'),'r'+str(i),str(i),'r'+str(i),None,c.canonical(c.ANNOTATIONS).decode()))
        conn.execute('INSERT INTO selection_membership VALUES (?,?,?,?,?,?)',('message',rid,kind,'2026-09-08T12:00:00Z',None,'[]'))
    return conn


def verify_closure(conn,kind='WORK_LIFECYCLE',expiry='2026-12-07T12:00:00Z'):
    from projection_workflows import ClosureVerifier
    with sqlite3.connect(':memory:') as scratch:
        verifier=ClosureVerifier(conn,scratch,lambda:None)
        return verifier.verify(dict(entity_type='message',projection_row_id='sm1:r1',retention_class=kind,retain_until=expiry),'2026-09-08T12:00:10Z')


def kibble_events():
    return [('issuer',dict(type='JOB',version=1,job_id='job')),
            ('worker',dict(type='RESULT',version=1,job_id='job')),
            ('issuer',dict(type='ACCEPT',version=1,job_id='job',result_raw_record_id='r2'))]


def test_authoritative_kibble_closure():
    conn=workflow_database(kibble_events())
    try: assert verify_closure(conn)==c.instant('2026-09-08T12:00:00Z')
    finally:conn.close()

@pytest.mark.parametrize('failure',['missing','result-id','issuer','generation','source','conflict','unverified','wrong-expiry','duplicate-root'])
def test_kibble_closure_fails_closed(failure):
    events=kibble_events()
    if failure=='duplicate-root':events.append(copy.deepcopy(events[0]))
    elif failure=='missing':events.pop()
    elif failure=='result-id':events[-1][1]['result_raw_record_id']='unknown'
    elif failure=='issuer':events[-1]=('attacker',events[-1][1])
    elif failure in {'generation','source'}:events[-1]=(*events[-1],{failure:'different'})
    elif failure=='unverified':events[-1]=(*events[-1],{'verification':'UNSIGNED'})
    elif failure=='conflict':events.append(('issuer',dict(type='REJECT',version=1,job_id='job',result_raw_record_id='r2')))
    conn=workflow_database(events)
    try:
        with pytest.raises(ss.SnapshotError):verify_closure(conn,expiry='2026-12-08T12:00:00Z' if failure=='wrong-expiry' else '2026-12-07T12:00:00Z')
    finally:conn.close()

@pytest.mark.parametrize('active',[False,True])
def test_tclk_deadline_only_closure(active):
    body='tclk1 '+json.dumps(dict(type='offer',id='offer',expiresMs=1788868800000))
    events=[('maker',body)]
    if active:events.append(('taker','tclk1 '+json.dumps(dict(type='accept',ref='offer'))))
    conn=workflow_database(events,'TCLK_LIFECYCLE')
    try:
        if active:
            with pytest.raises(ss.SnapshotError):verify_closure(conn,'TCLK_LIFECYCLE')
        else:verify_closure(conn,'TCLK_LIFECYCLE')
    finally:conn.close()


def test_unknown_generic_closure_is_not_inferred():
    conn=workflow_database([('issuer',{'type':'WORK_REQUEST','job_id':'job'}),('worker',{'type':'WORK_RESULT','job_id':'job','status':'COMPLETE'})])
    try:
        with pytest.raises(ss.SnapshotError):verify_closure(conn)
    finally:conn.close()


def controlled_fixture():
    import projection_bench as b
    request=dict(schema_version='flop-verification-request/v1',request_id='request',requester_did=router.ROUTER_DID,target_agent_did='did:key:z6MkFixture',capability_id='software.testing',routing_decision_id='decision',routing_decision_hash='1'*64,task_hash='2'*64,independent_reputation=False)
    result=dict(schema_version='flop-verification-result/v1',request_id='request',artifact_hashes=dict(request_sha256=c.digest(request)),bench_did=router.BENCH_DID,status='PASS',reproducibility='DETERMINISTIC',independent_reputation=False)
    refs=[dict(kind='LOCAL_ARTIFACT',source_id='local',source_epoch='1',id=name,sha256=c.digest(body)) for name,body in [('request',request),('result',result)]]
    records=[dict(schema=b.SCHEMA,reference=ref,artifact=body) for ref,body in zip(refs,[request,result])]
    q=dict(qualification_type='CONTROLLED_BENCH',operator_group=c.FAMILY,same_operator=True,independent_reputation=False,provenance_refs=refs,source_ref=refs[1],claim=dict(kind='VERIFICATION',id='request'),subject_did=request['target_agent_did'],qualification_outcome='PASS',correctness='PASS',reproducibility='DETERMINISTIC',qualified_at='2026-09-08T12:00:00Z')
    item=dict(record=q,effective_status='VALID',superseded_by=None,event_count=0)
    return records,item

@pytest.mark.parametrize('variant',['pass','fail','missing','invalidated','superseded','independent','wrong-bench','missing-capability','broken-request-hash','wrong-source'])
def test_controlled_bench_linkage_boundary(variant):
    import projection_bench as b
    records,item=controlled_fixture()
    if variant=='fail':records[1]['artifact']['status']='FAIL';item['record']['qualification_outcome']=item['record']['correctness']='FAIL'
    elif variant=='invalidated':item['effective_status']='INVALIDATED'
    elif variant=='superseded':item['superseded_by']='new'
    elif variant=='independent':records[1]['artifact']['independent_reputation']=True
    elif variant=='wrong-bench':records[1]['artifact']['bench_did']='did:key:z6MkOther'
    elif variant=='missing-capability':records[0]['artifact'].pop('capability_id')
    elif variant=='broken-request-hash':records[1]['artifact']['artifact_hashes']['request_sha256']='f'*64
    for record in records:record['reference']['sha256']=c.digest(record['artifact'])
    if variant=='wrong-source':records[1]['reference']['source_epoch']='2';item['record']['source_ref']=dict(item['record']['source_ref'],source_epoch='1')
    proofs=b.proofs_from_records(records if variant!='missing' else records[:1])
    rows=list(b.controlled_results([item],proofs))
    if variant in {'pass','fail'}:
        assert rows[0]['outcome']==variant.upper()
        assert rows[0]['same_operator'] is True and rows[0]['independent_reputation'] is False
    else:assert rows==[]

@pytest.mark.parametrize('outcome',['PASS','FAIL','INVALIDATED','SUPERSEDED','DUPLICATE','DOWNGRADE'])
def test_bench_scoring_full_reader_and_restart(tmp_path,outcome):
    from test_scout_projection import clone,rewrite
    import projection_bench as b
    root=clone(tmp_path,'same-operator-bench')
    records,item=controlled_fixture()
    if outcome=='DOWNGRADE':
        records[0]['artifact']['target_agent_did']='did:key:z6MkSyntheticSource'
        item['record']['subject_did']='did:key:z6MkSyntheticSource'
        records[1]['artifact']['artifact_hashes']['request_sha256']=c.digest(records[0]['artifact'])
        for record in records:record['reference']['sha256']=c.digest(record['artifact'])
    if outcome=='FAIL':
        records[1]['artifact']['status']='FAIL'
        records[1]['reference']['sha256']=c.digest(records[1]['artifact'])
        item['record']['qualification_outcome']=item['record']['correctness']='FAIL'
    counts={}
    def mutate(conn):
        original=c.loads(conn.execute("SELECT record_json FROM durable_qualifications WHERE json_extract(record_json,'$.qualification_type')='CONTROLLED_BENCH'").fetchone()[0])
        conn.execute('DELETE FROM durable_qualifications WHERE qualification_id=?',(original['qualification_id'],))
        original.update(item['record']);original['provenance_refs']=sorted(original['provenance_refs'],key=c.canonical)
        original.pop('qualification_id');original['qualification_id']=c.identity('dq1',original)
        c.validate_qualification(original)
        conn.execute('INSERT INTO durable_qualifications VALUES (?,?)',(original['qualification_id'],c.canonical(original).decode()))
        if outcome in {'DUPLICATE','SUPERSEDED'}:
            second=copy.deepcopy(original);second.pop('qualification_id')
            second['source_ref']['id']='second-result'
            for ref in second['provenance_refs']:
                if ref['id']=='result':ref['id']='second-result'
            second['provenance_refs'].sort(key=c.canonical)
            second['qualification_id']=c.identity('dq1',second)
            conn.execute('INSERT INTO durable_qualifications VALUES (?,?)',(second['qualification_id'],c.canonical(second).decode()))
            records.append(dict(schema=b.SCHEMA,reference=second['source_ref'],artifact=records[1]['artifact']))
        if outcome in {'INVALIDATED','SUPERSEDED'}:
            event=c.loads(conn.execute('SELECT event_json FROM qualification_events LIMIT 1').fetchone()[0])
            event.pop('event_id');event.update(qualification_id=original['qualification_id'],sequence=1,previous_event_sha256=None,event_type=outcome,reason_code='CORRUPTED_EVIDENCE' if outcome=='INVALIDATED' else 'NEW_QUALIFICATION',proof_refs=original['provenance_refs'],authority_ref=original['source_ref'],superseded_by=second['qualification_id'] if outcome=='SUPERSEDED' else None)
            event['event_id']=c.identity('dqe1',event)
            conn.execute('INSERT INTO qualification_events VALUES (?,?,?,?)',(event['event_id'],event['qualification_id'],1,c.canonical(event).decode()))
        counts.update({table:conn.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in c.TABLES})
    rewrite(root,lambda m:m.update(row_counts=counts),mutate)
    cache=tmp_path/'cache'
    def acquire(previous=None):
        with v.ProjectionReader(root,cache) as reader:
            reader.local_proofs=b.proofs_from_records(records)
            return reader.read(lambda conn:pr.build(conn,reader),previous=previous,now=NOW)
    profiles,first=acquire();profiles,second=acquire(first)
    if outcome=='INVALIDATED':
        assert profiles.get('did:key:z6MkFixture') is None
        assert second['qualification_history']['qualifications']==6
        assert second['routing_cache_reused']
        return
    profile=profiles['did:key:z6MkSyntheticSource' if outcome=='DOWNGRADE' else 'did:key:z6MkFixture']
    assert not profile.independent_counterparty_groups
    assert profile.trust_evidence.components['independent_peer_breadth']==0
    evidence=profile.validated_capability_evidence.get('software.testing',[])
    if outcome in {'PASS','DUPLICATE','SUPERSEDED','DOWNGRADE'}:
        assert len(evidence)==1
        assert evidence[0].validation_provenance.startswith('CONTROLLED_SAME_OPERATOR_VALIDATION:')
        if outcome=='DOWNGRADE':
            assert next(cap for cap in profile.capabilities if cap.capability_id=='software.testing').support_level=='SIGNAL_ONLY'
            assert evidence[0].pre_validation_support=='SIGNAL_ONLY'
        else:
            assert not profile.capabilities  # Historical audit did not invent current observed support.
            assert router.Router(profiles).score_candidate(router.analyze_task('testing'),profile).capability_matches['software.testing']=='VALIDATED_PASS'
    else:
        assert evidence==[]
        if outcome=='FAIL':assert 'CONTROLLED_BENCH_FAIL:software.testing' in profile.soft_risk_flags
    assert second['routing_cache_reused']


def test_authoritative_closure_persists_across_restart(tmp_path):
    from test_scout_snapshot import make_database
    from projection_test_support import publish_snapshot
    from test_scout_projection import rewrite
    source=tmp_path/'synthetic.sqlite';make_database(source)
    with sqlite3.connect(source) as conn:
        conn.execute('ALTER TABLE messages ADD COLUMN verification_status TEXT')
        conn.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?)',('room',1,'2026-09-08T12:00:00Z','did:key:z6MkRoot',1,json.dumps(dict(type='JOB',version=1,job_id='job')),'',c.text_hash('root'),'1','VERIFIED_OFFLINE'))
    root=tmp_path/'publication'
    publish_snapshot(root,source,produced_at=c.utc(NOW))
    def membership(conn,closed=False):
        conn.execute("UPDATE selection_membership SET retention_class='WORK_LIFECYCLE',first_observed_at='2026-09-08T12:00:00Z',retain_until=?",('2026-12-07T12:00:00Z' if closed else None,))
    rewrite(root,sql=membership)
    with v.ProjectionReader(root,tmp_path/'cache') as reader:
        _,first=reader.read(lambda conn:pr.build(conn,reader),now=NOW)
    with sqlite3.connect(source) as conn:
        for seq,sender,body in [(2,'did:key:z6MkWorker',dict(type='RESULT',version=1,job_id='job')),(3,'did:key:z6MkRoot',dict(type='ACCEPT',version=1,job_id='job',result_raw_record_id='raw-2'))]:
            conn.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?)',('room',seq,'2026-09-08T12:00:00Z',sender,1,json.dumps(body),'',c.text_hash(str(seq)),'1','VERIFIED_OFFLINE'))
    publish_snapshot(root,source,snapshot_id='2',produced_at=c.utc(NOW+timedelta(seconds=1)))
    rewrite(root,lambda m:m.update(next_expiry_at='2026-12-07T12:00:00Z'),lambda conn:membership(conn,True))
    with v.ProjectionReader(root,tmp_path/'cache') as reader:
        _,second=reader.read(lambda conn:pr.build(conn,reader),previous=first,now=NOW+timedelta(seconds=1))
    assert second['workflow_closures_validated']
    with v.ProjectionReader(root,tmp_path/'cache') as reader:
        _,third=reader.read(lambda conn:pr.build(conn,reader),previous=second,now=NOW+timedelta(seconds=2))
    assert third['validation_cache_reused'] and third['routing_cache_reused']


def test_external_evidence_stream_merge_parity_and_cancellation(tmp_path):
    with v.ProjectionReader(fixture('normal'),tmp_path/'cache') as reader:
        def consume(conn):
            obs,edges=router._worker_snapshot_profiles(conn)
            from dataclasses import replace
            extra=replace(obs[0],sequence_id=0,evidence_id='external',message_hash='b'*64)
            expected=router.ProfileBuilder(obs+[extra],edges,canonical_order=True).build_all()
            actual=pr.build(conn,reader,[extra])
            assert {k:asdict(x) for k,x in actual.items()}=={k:asdict(x) for k,x in expected.items()}
        reader.read(consume,now=NOW)
    cancel=router.WorkerCancellation()
    with v.ProjectionReader(fixture('normal'),tmp_path/'cancel-cache',cancel.check) as reader:
        def consume(conn):
            obs,_=router._worker_snapshot_profiles(conn)
            real=router.semantic_decisions
            def interrupted(*args):cancel.request(None,None);return real(*args)
            with patch.object(router,'semantic_decisions',interrupted):pr.build(conn,reader,obs)
        with pytest.raises(ss.Cancelled):reader.read(consume,now=NOW)
    assert not list((tmp_path/'cancel-cache').iterdir())


def test_bench_linked_outcome_without_capability_is_permanent_unscored():
    import projection_bench as b
    records,item=controlled_fixture()
    records[0]['artifact'].pop('capability_id')
    records[0]['reference']['sha256']=c.digest(records[0]['artifact'])
    records[1]['artifact']['artifact_hashes']['request_sha256']=c.digest(records[0]['artifact'])
    records[1]['reference']['sha256']=c.digest(records[1]['artifact'])
    proofs=b.proofs_from_records(records)
    row=list(b.linked_outcomes([item],proofs))[0]
    assert row['workflow_status']=='CLOSED' and row['closed_at'] is None
    assert row['retention']=='PERMANENT_BENCH_VERIFICATION'
    assert list(b.controlled_results([item],proofs))==[]


def test_corrupted_validation_cache_metadata_fails_closed(tmp_path):
    with v.ProjectionReader(fixture('normal'),tmp_path/'cache') as reader:
        _,first=reader.read(lambda conn:pr.build(conn,reader),now=NOW)
    first['validated_content']['routing_input_hash']='f'*64
    with v.ProjectionReader(fixture('heartbeat-reuse'),tmp_path/'cache') as reader:
        with pytest.raises(ss.SnapshotError,match='CONTINUITY_VALIDATION_CACHE_CHECKSUM'):
            reader.read(lambda conn:pr.build(conn,reader),previous=first,now=NOW)


def test_proof_store_missing_malformed_and_recovery(tmp_path):
    state=tmp_path/'state';proof=tmp_path/'proofs.jsonl'
    with patch.object(router,'datetime',wraps=router.datetime) as clock:
        clock.now.return_value=NOW
        for content,expected in [(None,'DEGRADED_INPUT_MISSING'),('{"broken":1}\n','DEGRADED_INPUT_INVALID'),('', 'READY_IDLE')]:
            if content is not None:proof.write_text(content)
            cycle=router.worker_once(state,scout_snapshot_root=fixture('normal'),bench_proof_store=proof)
            assert cycle['status']==expected
            assert cycle['shadow_decisions_produced']==0
            if expected!='READY_IDLE':
                assert not router.worker_status(state).get('last_accepted_projection_v2')


def test_hour_later_restart_heartbeat_skips_routing(tmp_path):
    from test_scout_projection import clone,rewrite
    root=clone(tmp_path);state=tmp_path/'state'
    tasks=router.worker_paths(state)['tasks'];tasks.parent.mkdir(parents=True)
    tasks.write_text(json.dumps(dict(task_id='one',task='software testing'))+'\n')
    with patch.object(router,'datetime',wraps=router.datetime) as clock:
        clock.now.return_value=NOW
        first=router.worker_once(state,scout_snapshot_root=root)
    assert first['shadow_decisions_produced']==1
    future=NOW+timedelta(hours=1)
    rewrite(root,lambda m:m.update(snapshot_id='2',publication_kind='HEARTBEAT',produced_at=c.utc(future),selection_evaluated_at=c.utc(future)))
    with patch.object(router,'datetime',wraps=router.datetime) as clock,patch.object(router.Router,'route',side_effect=AssertionError('duplicate was routed')):
        clock.now.return_value=future
        second=router.worker_once(state,scout_snapshot_root=root)
    assert second['status']=='READY_IDLE' and second['duplicate_decisions_suppressed']==1
    assert second['shadow_decisions_produced']==0
    assert router.worker_status(state)['last_success_at']==c.utc(future).replace('.000000','')


def test_cache_retention_removes_obsolete_routing_indexes(tmp_path):
    cache=tmp_path/'cache'
    with v.ProjectionReader(fixture('normal'),cache) as reader:
        _,first=reader.read(lambda conn:pr.build(conn,reader),now=NOW)
    with v.ProjectionReader(fixture('duplicate-downgrade'),cache) as reader:
        _,second=reader.read(lambda conn:pr.build(conn,reader),previous=first,now=NOW)
        reader.cleanup(second['cache_path'],second['routing_cache']['path'])
    from pathlib import Path
    assert {p.name for p in cache.iterdir()}=={Path(second['cache_path']).name,Path(second['routing_cache']['path']).name}


def test_large_support_status_is_explicitly_bounded(tmp_path):
    path=tmp_path/'index.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE capabilities(did TEXT,capability TEXT,payload TEXT,PRIMARY KEY(did,capability))')
        db.executemany('INSERT INTO capabilities VALUES (?,?,?)',[(f'fixture-{i:04d}','software.testing',json.dumps(dict(support_level='SIGNAL_ONLY'))) for i in range(1001)])
    profiles=pr.Profiles(path)
    assert len(profiles.support())==1000
    assert profiles.support_scope()==dict(total_profiles_with_support=1001,sample_limit=1000,complete=False,full_index=str(path))


def test_import_bookkeeping_does_not_change_semantic_record_order():
    first=dict(did='did:key:z6MkFixture',room='room',generation='1',seq=1,text='evidence',timestamp='2026-09-08T12:00:00Z',source_export_path='/tmp/a',source_export_hash='a'*64,processed_at='one')
    second=dict(first,source_export_path='/tmp/b',source_export_hash='b'*64,processed_at='two')
    assert router._worker_semantic_record('ingest_store',first)==router._worker_semantic_record('ingest_store',second)
    changed=dict(second,generation='2')
    assert router._worker_semantic_record('ingest_store',first)!=router._worker_semantic_record('ingest_store',changed)
    # A timestamp inside an original-proof artifact remains hash-bound evidence.
    proof=dict(schema='router-bench-proof/v1',artifact=dict(processed_at='one'))
    assert router._worker_semantic_record('bench_proof_store',proof)==proof


def test_rule_index_exact_parity_for_every_pattern():
    # Exercise every pattern, including regex fallbacks and context-only rules,
    # with positive, negated and irrelevant surrounding text.
    texts = {p for rule in router.CAPABILITY_RULES
             for p in rule.strong_patterns + rule.weak_patterns}
    for text in sorted(texts):
        for template in ('{}', 'I tested {} against the fixture because it failed.', 'No {} supported here.'):
            raw = template.format(text)
            obs = router.AgentObservation(router.AgentIdentity('did:key:z6MkFixture'),'room',1,None,raw,router.normalize_text(raw),'hash',True)
            expected = {d.capability_id:asdict(d) for rule in router.CAPABILITY_RULES
                        if (d:=router.raw_capability_evidence_decision(obs,rule,1)).relevant}
            actual = {d.capability_id:asdict(d) for d in router.semantic_decisions(obs,1)}
            assert actual == expected, raw


def test_readiness_phases_and_cached_index(tmp_path):
    previous = None
    for name in ('normal','heartbeat-reuse'):
        with v.ProjectionReader(fixture(name),tmp_path/'cache') as reader:
            def consume(conn):
                assert reader.metadata['readiness_phase']=='CONTENT_VALIDATED'
                profiles=pr.build(conn,reader)
                assert reader.metadata['readiness_phase']=='INDEX_READY'
                return profiles
            _,previous=reader.read(consume,previous=previous,now=NOW)
            assert previous['readiness_phase']=='INDEX_READY'
            assert all(n>=0 for n in previous['stage_peak_rss_delta_bytes'].values())


def test_index_cancellation_never_claims_routing_ready(tmp_path):
    cancel=router.WorkerCancellation()
    with v.ProjectionReader(fixture('normal'),tmp_path/'cache',cancel.check) as reader:
        def consume(conn):
            assert reader.metadata['readiness_phase']=='CONTENT_VALIDATED'
            cancel.request(None,None)
            return pr.build(conn,reader)
        with pytest.raises(ss.Cancelled):reader.read(consume,now=NOW)
        assert reader.metadata['readiness_phase']=='CONTENT_VALIDATED'
        assert not list((tmp_path/'cache').iterdir())


def test_worker_routing_ready_requires_all_sources(tmp_path):
    from test_scout_projection import clone
    root=clone(tmp_path);state=tmp_path/'state'
    with patch.object(router,'datetime',wraps=router.datetime) as clock:
        clock.now.return_value=NOW
        ready=router.worker_once(state,scout_snapshot_root=root)
        assert ready['sources'][0]['readiness_phase']=='ROUTING_READY'
        degraded=router.worker_once(state,scout_snapshot_root=root,validation_store=tmp_path/'missing')
        assert degraded['status']=='DEGRADED_INPUT_MISSING'
        assert degraded['sources'][0].get('readiness_phase')!='ROUTING_READY'
        assert degraded['shadow_decisions_produced']==0
