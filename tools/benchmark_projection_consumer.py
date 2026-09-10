"""Opt-in synthetic consumer capacity probe; only named /private/tmp fixtures.

Usage: python tools/benchmark_projection_consumer.py 100k 30 profiles [subset_rows]
The optional subset is a newly constructed capacity model, never an edit to the
Scout-generated fixture. No producer runtime import or live state access.
"""
import sys,time,json,tempfile,hashlib,sqlite3,shutil
from pathlib import Path
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scout_projection as v, projection_contract as c, router
scale=sys.argv[1]; timeout=float(sys.argv[2]); profiles=len(sys.argv)>3
cut=next((int(arg) for arg in sys.argv[4:] if arg!='--changed'),None)
changed_probe='--changed' in sys.argv
implementation_hash=c.digest({name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in ('router.py','scout_projection.py','projection_contract.py','projection_routing.py','projection_bench.py','projection_workflows.py')})
src=Path('/private/tmp/scout-v2-a1-capacity-'+scale)/('projection-'+{'100k':'100000','350k':'350000','1m':'1000000'}[scale]+'.sqlite')
with tempfile.TemporaryDirectory(prefix='router-v2-bench-') as t:
 root=Path(t).resolve(); pub=root/'publication';pub.mkdir(); staging=root/'verified.sqlite'
 # Fixture acquisition: hash and copy from one open descriptor before SQLite.
 h=hashlib.sha256()
 with src.open('rb') as f, staging.open('wb') as out:
  while True:
   chunk=f.read(1024**2)
   if not chunk:break
   h.update(chunk);out.write(chunk)
 digest=h.hexdigest()
 results=json.loads(src.with_name('results.json').read_text())
 assert digest==results['sha256']
 if cut:
  # New synthetic capacity subset in our private copy; originals stay unchanged.
  with sqlite3.connect(staging) as edit:
   edit.row_factory=sqlite3.Row
   edit.execute('DELETE FROM messages WHERE seq>?',(cut,))
   edit.execute("DELETE FROM durable_qualifications WHERE json_extract(record_json,'$.source_ref.id') NOT IN (SELECT projection_row_id FROM messages)")
   edit.execute('DELETE FROM qualification_events WHERE qualification_id NOT IN (SELECT qualification_id FROM durable_qualifications)')
   for table in ('source_provenance','selection_membership'):
    edit.execute('DELETE FROM '+table+' WHERE projection_row_id NOT IN (SELECT projection_row_id FROM messages)')
   edit.execute('DELETE FROM watermarks');edit.execute('DELETE FROM coverage_history')
   for row in edit.execute('SELECT room,generation,count(*) AS record_count,min(seq) AS min_seq,max(seq) AS max_seq FROM messages GROUP BY room,generation').fetchall():
    edit.execute('INSERT INTO watermarks VALUES (?,?,?,?,?)',tuple(row))
    msg=dict(edit.execute('SELECT * FROM messages WHERE room=? AND generation=? AND seq=?',(row['room'],row['generation'],row['max_seq'])).fetchone())
    locator=edit.execute("SELECT source_record_locator FROM source_provenance WHERE entity_type='message' AND projection_row_id=?",(msg['projection_row_id'],)).fetchone()[0]
    edit.execute('INSERT INTO coverage_history VALUES (?,?,?,?,?)',(row['room'],row['generation'],row['max_seq'],locator,c.digest(msg)))
   edit.commit();edit.execute('VACUUM')
  h=hashlib.sha256()
  with staging.open('rb') as stream:
   while True:
    chunk=stream.read(1024**2)
    if not chunk:break
    h.update(chunk)
  digest=h.hexdigest()
 conn=sqlite3.connect(staging.as_uri()+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA query_only=ON')
 meta=dict(conn.execute('SELECT * FROM snapshot_meta').fetchone())
 m=json.loads(next(Path('/private/tmp/scout-v2-a1-review-fixtures/large-size-warning').glob('manifest*.json')).read_text())
 m.update(database_content_id=meta['database_content_id'],content_created_at=meta['content_created_at'],sha256=digest,size_bytes=staging.stat().st_size)
 m['database']=f"router-projection-v2-{m['database_content_id']}-{digest}.sqlite"
 for table in ('watermarks','coverage_history'):m[table]=[dict(r) for r in conn.execute('SELECT * FROM '+table+' ORDER BY room,generation')]
 m['row_counts']={tab:conn.execute('SELECT count(*) FROM '+tab).fetchone()[0] for tab in c.TABLES}
 # Model qualification cuts advance with synthetic message IDs.
 m['source_checkpoint']['committed_event_id']=str(int({'100k':100000,'350k':350000,'1m':1000000}[scale]))
 m['next_expiry_at']=conn.execute('SELECT min(retain_until) FROM selection_membership').fetchone()[0]
 conn.close();staging.rename(pub/m['database']);raw=c.canonical(m);mh=hashlib.sha256(raw).hexdigest();mn=f"manifest-v2-{m['snapshot_id']}-{mh}.json";(pub/mn).write_bytes(raw)
 (pub/'current.json').write_bytes(c.canonical(dict(schema='flop-scout-router-current/v2',manifest=mn,manifest_sha256=mh,published_at=m['produced_at'])))
 with v.ProjectionReader(pub,root/'cache',timeout=timeout,max_memory=512*1024**2) as reader:
  def consume_with(owner,conn):
   if profiles:
    import projection_routing
    result=projection_routing.build(conn,owner)
    with owner.stage('routing_state_construction'):
     router._worker_evidence_snapshot(result,{'scout_snapshot':{'routing_input_hash':owner.metadata['routing_input_hash'],'selection_policy':owner.metadata['selection_policy']}})
     result.support();result.support_scope();result.verification_count()
    owner.metadata['readiness_phase']='ROUTING_READY'
    return result
   return conn.execute('SELECT count(*) FROM messages').fetchone()[0]
  def consume(conn):return consume_with(reader,conn)
  status='PASS'; warm={}
  try:
   _,cold=reader.read(consume,now=c.instant(m['produced_at']))
  except Exception as exc:
   status=getattr(exc,'code',type(exc).__name__);cold=dict(reader.metadata)
  if status=='PASS':
   # Publish only in this temporary synthetic directory. Heartbeats reuse the
   # immutable artifact; all three probes run the full pointer/manifest path.
   heartbeat=dict(m,snapshot_id=str(int(m['snapshot_id'])+1),publication_kind='HEARTBEAT',
                  produced_at=c.utc(c.instant(m['produced_at'])+timedelta(seconds=1)),
                  selection_evaluated_at=c.utc(c.instant(m['produced_at'])+timedelta(seconds=1)))
   raw=c.canonical(heartbeat);mh=hashlib.sha256(raw).hexdigest();mn=f"manifest-v2-{heartbeat['snapshot_id']}-{mh}.json"
   (pub/mn).write_bytes(raw)
   (pub/'current.json').write_bytes(c.canonical(dict(schema='flop-scout-router-current/v2',manifest=mn,manifest_sha256=mh,published_at=heartbeat['produced_at'])))
   previous=cold
   for label in ('first_heartbeat','steady_heartbeat'):
    _,previous=reader.read(consume,previous=previous,now=c.instant(heartbeat['produced_at']))
    warm[label]={k:previous.get(k) for k in ('total_acquisition_seconds','stage_seconds','peak_rss_bytes','validation_cache_reused','routing_cache_reused','readiness')}
   with v.ProjectionReader(pub,root/'cache',timeout=timeout,max_memory=512*1024**2) as restarted:
    callback=lambda conn:consume_with(restarted,conn)
    _,last=restarted.read(callback,previous=previous,now=c.instant(heartbeat['produced_at']))
    warm['restart_heartbeat']={k:last.get(k) for k in ('total_acquisition_seconds','stage_seconds','peak_rss_bytes','validation_cache_reused','routing_cache_reused','readiness')}
  changed_report=None
  if status=='PASS' and changed_probe:
   # A changed-evidence publication: add one retained interaction row.
   # Construct only in this temporary producer model; never modify Scout fixtures.
   changed_path=root/'new-content.sqlite'
   old=sqlite3.connect(Path(cold['cache_path']).as_uri()+'?mode=ro',uri=True);old.execute('PRAGMA query_only=ON')
   edit=sqlite3.connect(changed_path);old.backup(edit);old.close()
   when=c.utc(c.instant(heartbeat['produced_at'])+timedelta(seconds=1))
   edit.execute('UPDATE snapshot_meta SET database_content_id=?,content_created_at=?',('2',when))
   rid='si1:capacity-added-interaction'
   edit.execute('INSERT INTO interactions VALUES (?,?,?,?,?)',(rid,'did:key:z6MkSynthetic2','did:key:z6MkSynthetic1','DIRECT_REPLY',.8))
   edit.execute('INSERT INTO source_provenance VALUES (?,?,?,?,?,?,?,?)',('interaction',rid,'scout-observer',rid,None,None,None,c.canonical(c.ANNOTATIONS).decode()))
   edit.execute('INSERT INTO selection_membership VALUES (?,?,?,?,?,?)',('interaction',rid,'IDENTITY_OPERATOR',when,None,'[]'))
   edit.commit();edit.close()
   h=hashlib.sha256()
   with changed_path.open('rb') as stream:
    while chunk:=stream.read(1024**2):h.update(chunk)
   changed=json.loads(json.dumps(m));changed.update(snapshot_id='3',database_content_id='2',publication_kind='CONTENT',content_created_at=when,selection_evaluated_at=when,produced_at=when,sha256=h.hexdigest(),size_bytes=changed_path.stat().st_size)
   changed['database']=f"router-projection-v2-2-{h.hexdigest()}.sqlite"
   for table in ('interactions','source_provenance','selection_membership'):changed['row_counts'][table]+=1
   changed['source_checkpoint']['committed_event_id']=str(int(changed['source_checkpoint']['committed_event_id'])+1)
   changed_path.rename(pub/changed['database']);raw=c.canonical(changed);mh=hashlib.sha256(raw).hexdigest();mn=f'manifest-v2-3-{mh}.json';(pub/mn).write_bytes(raw)
   (pub/'current.json').write_bytes(c.canonical(dict(schema='flop-scout-router-current/v2',manifest=mn,manifest_sha256=mh,published_at=when)))
   with v.ProjectionReader(pub,root/'cache',timeout=timeout,max_memory=512*1024**2) as updated:
    changed_status='PASS'
    try:updated.read(lambda conn:consume_with(updated,conn),previous=last,now=c.instant(when))
    except Exception as exc:changed_status=getattr(exc,'code',type(exc).__name__)
    changed_report=dict(status=changed_status,**updated.metadata)
  report=dict(scale=scale,subset_rows=cut,status=status,profiles=profiles,implementation_sha256=implementation_hash,**cold,warm=warm,changed_content=changed_report)
  print(json.dumps(report,sort_keys=True))
