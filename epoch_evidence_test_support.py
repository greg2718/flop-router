"""Synthetic descriptor-bound evidence bundles, generated without Scout code."""
import copy
import json
from pathlib import Path
import sqlite3

import projection_contract as c
from scout_projection import SCHEMA_SQL
from epoch_v2_test_support import canonical, commit, sha, seal, model
from scout_epoch_evidence import SOURCE_COLUMNS, source_ddl_commitment

WHEN = '2026-09-22T00:00:00Z'
FIRST = '2026-09-01T00:00:00Z'


def qualify(pid, digest):
    ref = {'kind': 'PROJECTED_MESSAGE', 'source_id': 'scout-source', 'source_epoch': 'source-epoch', 'id': pid, 'sha256': digest}
    q = {'schema': 'router-durable-qualification/v1', 'source_ref': ref, 'scout_event_id': '1',
         'evidence_id': None, 'subject_did': 'sender', 'claim': {'kind': 'CAPABILITY', 'id': 'software.debugging'},
         'qualification_type': 'CAPABILITY_USE', 'qualification_outcome': 'LIMITED', 'qualified_at': FIRST,
         'policy_version': c.POLICY['version'], 'policy_sha256': c.POLICY_SHA,
         'classifier_version': c.POLICY['classifier_version'], 'qualification_policy_version': c.POLICY['qualification_policy_version'],
         'bootstrap_id': 'pe1:test', 'evaluation_id': 'pe1:test', 'source_cut': {'source_id': 'scout-source', 'epoch': 'source-epoch', 'committed_event_id': '8'},
         'rule_id': 'test-rule', 'rule_input_sha256': 'a'*64, 'rule_group_sha256': 'b'*64,
         'provenance_refs': [ref], 'operator_group': None, 'same_operator': None, 'independent_reputation': None,
         'authenticity': 'VERIFIED_OFFLINE', 'correctness': None, 'reproducibility': None, 'initial_status': 'VALID'}
    q['qualification_id'] = c.identity('dq1', q)
    return q


def bundle(root, damage=None):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    archive = root/'archive'; (archive/'members').mkdir(parents=True)
    bridge_path = archive/'members/bridge-projection.sqlite'; active_path = root/'active.sqlite'
    b=sqlite3.connect(bridge_path); b.row_factory=sqlite3.Row; b.executescript(SCHEMA_SQL)
    b.execute('INSERT INTO snapshot_meta VALUES (1,?,?,?,?)', (c.SCHEMA,'1',FIRST,c.POLICY_SHA))
    record_list=[]; raw_list=[]; membership=[]
    reason_list=[['durable_qualification','permanent_or_pinned'], ['permanent_or_pinned'], ['tclk_or_work_lifecycle'], ['coverage_witness'], [], [], [], []]
    for n in range(8):
        text = 'synthetic evidence '+str(n)
        if n==2: text='tclk1 '+canonical({'type':'offer','id':'offer-test','expiresMs':1788220800000}).decode()
        seq=100 if n==3 else n+1
        envelope={'text':text,'from':'sender','seq':seq}
        rid=sha(canonical(['scout-source','room','1','1',envelope])); pid='sm1:'+rid; digest=sha(text.encode())
        raw={'raw_record_id':rid,'source':'scout-source','room':'room','generation':'1','reported_generation':'1','seq':seq,'sender_did':'sender','signature':None,'nonce':None,'raw_text':text,'raw_text_sha256':digest,'raw_record_json':canonical(envelope).decode()}
        raw_list.append(raw)
        rec={'projection_row_id':pid,'raw_record_id':rid,'raw_text_sha256':digest,'scout_event_id':str(n+1)}; record_list.append(rec)
        b.execute('INSERT INTO messages (projection_row_id,room,generation,seq,sender,signed,text,message_hash,verification_status) VALUES (?,?,?,?,?,1,?,?,?)', (pid,'room','1',seq,'sender',text,digest,'VERIFIED_OFFLINE'))
        b.execute('INSERT INTO source_provenance VALUES (?,?,?,?,?,?,?,?)', ('message',pid,'scout-source',rid,str(n+1),rid,None,c.canonical(c.ANNOTATIONS).decode()))
        cls=['CAPABILITY_SUPPORT','PINNED','TCLK_LIFECYCLE','CONTEXT'][n] if n<4 else 'CONTEXT'
        expiry=None if n<2 else '2026-11-30T00:00:00Z' if n==2 else '2026-10-01T00:00:00Z'
        pins=canonical([{'kind':'TASK','id':'task-a'}] if n==1 else []).decode()
        member=('message',pid,cls,FIRST,expiry,pins); membership.append(member)
        b.execute('INSERT INTO selection_membership VALUES (?,?,?,?,?,?)',member)
    q=qualify(record_list[0]['projection_row_id'],record_list[0]['raw_text_sha256'])
    b.execute('INSERT INTO durable_qualifications VALUES (?,?)',(q['qualification_id'],canonical(q).decode()))
    witness=dict(b.execute('SELECT * FROM messages WHERE projection_row_id=?',(record_list[3]['projection_row_id'],)).fetchone())
    cov={'room':'room','generation':'1','max_ever_projected_seq':100,'witness_source_locator':record_list[3]['raw_record_id'],'witness_record_sha256':c.digest(witness)}
    b.execute('INSERT INTO coverage_history VALUES (?,?,?,?,?)',tuple(cov.values()))
    b.execute('INSERT INTO watermarks VALUES (?,?,?,?,?)',('room','1',8,1,100)); b.commit()
    a=sqlite3.connect(active_path); a.row_factory=sqlite3.Row; a.executescript(SCHEMA_SQL)
    a.execute('INSERT INTO snapshot_meta VALUES (1,?,?,?,?)',(c.SCHEMA,'2',WHEN,c.POLICY_SHA))
    chosen={0,1,2,3,6,7}
    for n in chosen:
        pid=record_list[n]['projection_row_id']
        for table in ('messages','source_provenance','selection_membership'):
            row=dict(b.execute('SELECT * FROM '+table+' WHERE projection_row_id=?',(pid,)).fetchone())
            if table=='source_provenance': row['raw_record_sha256']=record_list[n]['raw_text_sha256']
            a.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
    for table in ('durable_qualifications','coverage_history'):
        for row in b.execute('SELECT * FROM '+table): a.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in row)+')',tuple(row))
    a.execute('INSERT INTO watermarks VALUES (?,?,?,?,?)',('room','1',6,1,100))
    if damage=='selected-absent': a.execute('DELETE FROM messages WHERE projection_row_id=?',(record_list[7]['projection_row_id'],))
    if damage=='omitted-present':
        row=b.execute('SELECT * FROM messages WHERE projection_row_id=?',(record_list[4]['projection_row_id'],)).fetchone()
        a.execute('INSERT INTO messages VALUES ('+','.join('?' for _ in row)+')',tuple(row))
    if damage=='archive-provenance': b.execute('DELETE FROM source_provenance WHERE projection_row_id=?',(record_list[4]['projection_row_id'],))
    if damage in ('qualification','coverage'):
        a.execute('DELETE FROM '+('durable_qualifications' if damage=='qualification' else 'coverage_history'))
    if damage in ('pin','permanent','lifecycle'):
        n={'pin':1,'permanent':0,'lifecycle':2}[damage]
        a.execute("UPDATE selection_membership SET pin_roots_json='[]',retention_class='CONTEXT',retain_until='2026-10-01T00:00:00Z' WHERE projection_row_id=?",(record_list[n]['projection_row_id'],))
    if damage=='lifecycle-dependency':
        a.execute("UPDATE selection_membership SET retain_until='2026-12-01T00:00:00Z' WHERE projection_row_id=?",(record_list[2]['projection_row_id'],))
        b.execute("UPDATE selection_membership SET retain_until='2026-12-01T00:00:00Z' WHERE projection_row_id=?",(record_list[2]['projection_row_id'],))
    if damage=='selected-hash': a.execute("UPDATE source_provenance SET raw_record_sha256=? WHERE projection_row_id=?",('0'*64,record_list[7]['projection_row_id']))
    if damage=='selected-event': a.execute("UPDATE source_provenance SET scout_event_id='99' WHERE projection_row_id=?",(record_list[7]['projection_row_id'],))
    if damage=='lifecycle-link':
        annotation=dict(c.ANNOTATIONS, evidence_links=[{'room':'room','generation':'1','seq':5,'evidence_id':None}])
        for db in (a,b): db.execute('UPDATE source_provenance SET annotations_json=? WHERE projection_row_id=?',(canonical(annotation).decode(),record_list[2]['projection_row_id']))
    a.commit(); a.close(); b.commit(); b.close()
    t=model(); t['created_at']=WHEN
    desc={'publication_sequence':1,'content_id':1,'manifest_sha256':'a'*64,'artifact_sha256':sha(bridge_path.read_bytes()),'artifact_size':bridge_path.stat().st_size,'source_kind':'source-epoch','source_id':'scout-source','source_cut':8}
    t['accepted_anchor']=dict(desc);t['bridge_predecessor']=dict(desc)
    binding=commit('a1-bridge-binding',{'accepted_anchor':desc,'bridge_predecessor':desc});t['bridge_binding_sha256']=binding
    t['source_binding']={'source_id':'scout-source','epoch':'source-epoch','descriptor_sha256':commit('source-binding-descriptor',{'schema':'flop-scout-epoch-source-binding/v1','source_id':'scout-source','epoch':'source-epoch','bridge_binding_sha256':binding})}
    t['source_cut']={'source_id':'scout-source','epoch':'source-epoch','committed_event_id':8,'cut_evidence_sha256':commit('source-cut-evidence',{'schema':'flop-scout-epoch-source-cut-evidence/v1','source_binding':t['source_binding'],'committed_event_id':8,'bridge_binding_sha256':binding})}
    closure=sorted([dict(record_list[n],reasons=reason_list[n]) for n in range(4)],key=lambda r:r['raw_record_id'])
    content={'content_id':'1','manifest_sha256':desc['manifest_sha256'],'artifact_sha256':desc['artifact_sha256'],'source_id':'scout-source','source_epoch':'source-epoch','committed_event_id':'8'}
    recovery_hash=c.digest({'domain':'scout/legacy-a1-provenance-recovery-closure/v1','content':content,'records':[{k:r[k] for k in ('raw_record_id','raw_text_sha256','scout_event_id')} for r in closure]})
    recovery={'schema':'scout-legacy-a1-provenance-recovery/v1','closure':closure,'closure_count':4,'commitment':recovery_hash,'descriptor':content,'reason_counts':{'durable_qualification':1,'permanent_or_pinned':2,'tclk_or_work_lifecycle':1,'coverage_witness':1},'validated_records':8}
    (archive/'members/legacy-recovery.json').write_bytes(canonical(recovery))
    source_path=archive/'members/source-evidence.sqlite'; s=sqlite3.connect(source_path)
    for table,columns in SOURCE_COLUMNS.items():
        definitions=[]
        for name in columns.split():
            typ='INTEGER' if name in ('singleton','raw_record_count','observed_event_count','cache_link_count','seq','event_id','cache_rowid') else 'TEXT'
            definitions.append(name+' '+typ)
        s.execute('CREATE TABLE '+table+'('+','.join(definitions)+')')
    s.execute('CREATE INDEX compatibility_links_by_raw ON compatibility_links(raw_record_id,cache_table)')
    for n,raw in enumerate(raw_list):
        row=dict(raw)
        if damage=='recovered-hash' and n==4: row['raw_text_sha256']='0'*64
        s.execute('INSERT INTO raw_records VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
        s.execute('INSERT INTO observed_event_witnesses VALUES (?,?,?)',(99 if damage=='recovered-event' and n==4 else n+1,raw['raw_record_id'],raw['raw_text_sha256']))
        s.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(n+1,raw['room'],raw['seq'],raw['raw_text'],'sender'))
        s.execute('INSERT INTO compatibility_links VALUES (?,?,?,?)',('messages',n+1,raw['raw_record_id'],raw['raw_text_sha256']))
    if damage=='source-duplicate':
        row=raw_list[0];s.execute('INSERT INTO raw_records VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
    checkpoint={'source_id':'scout-source','source_epoch':'source-epoch','source_cut':8}
    s.execute('INSERT INTO source_evidence_metadata VALUES ('+','.join('?' for _ in range(12))+')',(1,'flop-scout-epoch-source-evidence/v1','legacy-a1-recovery/1',source_ddl_commitment(s),canonical(desc).decode(),canonical(desc).decode(),canonical(checkpoint).decode(),binding,recovery_hash,8,8,8))
    s.commit();s.close()
    roles={'bridge_projection_sqlite':('bridge-projection.sqlite',c.SCHEMA),'legacy_recovery_json':('legacy-recovery.json',recovery['schema']),'source_evidence_sqlite':('source-evidence.sqlite','flop-scout-epoch-source-evidence/v1')}
    members=[]
    for role,(name,schema) in sorted(roles.items()):
        raw=(archive/'members'/name).read_bytes();members.append({'role':role,'locator':'members/'+name,'schema':schema,'sha256':sha(raw),'size_bytes':len(raw)})
    manifest={'schema':'flop-scout-epoch-archive/v1','archive_id':'ea2:test','accepted_anchor':desc,'bridge_predecessor':desc,'previous_bridge_binding_sha256':binding,'source_checkpoint':checkpoint,'legacy_recovery':{'schema':recovery['schema'],'commitment_sha256':recovery_hash,'validated_records':8,'closure_count':4},'retention':'IMMUTABLE_INDEFINITE_FIRST_TRANSITION','members':members}
    manifest['manifest_commitment_sha256']=sha(b'flop-scout/epoch-archive-manifest/v1\0'+canonical(manifest))
    raw=canonical(manifest);(archive/'manifest.json').write_bytes(raw)
    t['archive']={'schema':manifest['schema'],'archive_id':'ea2:test','artifact_sha256':sha(raw),'size_bytes':len(raw),'database_schema_version':'flop-scout-epoch-archive-manifest/v1','locator':'archive/manifest.json','previous_epoch_id':'source-epoch','previous_manifest_sha256':desc['manifest_sha256'],'previous_bridge_binding_sha256':binding,'preservation':'IMMUTABLE_RETAINED'}
    t['active_artifact']={'schema':c.SCHEMA,'content_id':2,'locator':'active.sqlite','artifact_sha256':sha(active_path.read_bytes()),'size_bytes':active_path.stat().st_size,'database_schema_version':c.SCHEMA}
    selected=sorted([dict(record_list[n],reasons=reason_list[n] or ['optional_selection']) for n in chosen],key=lambda r:r['raw_record_id'])
    omitted=sorted([dict(record_list[n],reasons=['deterministic_optional_omission']) for n in (4,5)],key=lambda r:r['raw_record_id'])
    sets={'mandatory_proof_closure':closure,'durable_qualification_history':[{'qualification_id':q['qualification_id'],'record_json':q}],'coverage_witnesses':[cov],'permanent_pinned_evidence':[dict(record_list[n],reasons=reason_list[n]) for n in (0,1)],'omitted_history':omitted}
    domains={'mandatory_proof_closure':'mandatory-closure','durable_qualification_history':'durable-qualification-history','coverage_witnesses':'coverage-witnesses','permanent_pinned_evidence':'permanent-pinned-evidence','omitted_history':'omitted-history'}
    floor={'entries':[{'room':'room','generation':'1','domain':'messages','retained_floor':100,'omitted_ranges':[]}],'selection_policy_version':'epoch-v2-policy/1'}
    for name,domain in domains.items(): floor.update({name+'_count':len(sets[name]),name+'_sha256':commit(domain,sorted(sets[name],key=canonical))})
    t['retained_floor_commitment']=floor; t['active_epoch']={'target':6,'headroom':1,'reserve':0,'hard_max':50000,'mandatory_closure_count':4}
    t['active_set_plan']['recovery_commitment_sha256']=recovery_hash
    seal(t)
    p={'schema':'flop-scout-epoch-active-set-plan/v1','selection_policy_version':'epoch-v2-policy/1','candidate_source':{key:t[key] for key in ('source_binding','source_cut')},'archive_descriptor_sha256':t['archive']['archive_commitment_sha256'],'recovery_commitment_sha256':recovery_hash,'retained_floor_commitment_sha256':floor['retained_floor_commitment_sha256'],'omission_commitment_sha256':floor['omitted_history_sha256'],'capacity':t['active_epoch'],'selected':selected,'omitted':omitted,'counts':{'selected':6,'omitted':2,'eligible':8}}
    return refresh(root,t,p)


def refresh(root,t,p):
    p['plan_commitment_sha256']=commit('active-set-plan',{k:x for k,x in p.items() if k!='plan_commitment_sha256'})
    raw=canonical(p);path=Path(root)/'plan.json';path.write_bytes(raw)
    t['active_set_plan'].update(locator='plan.json',sha256=sha(raw),size_bytes=len(raw),plan_commitment_sha256=p['plan_commitment_sha256'])
    seal(t)
    return t,p,{'accepted_anchor':copy.deepcopy(t['accepted_anchor']),'plan_path':path.resolve(),'artifact_path':(Path(root)/'active.sqlite').resolve(),'archive_root':(Path(root)/'archive').resolve()}
