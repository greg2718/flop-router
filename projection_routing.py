"""Router-derived, disk-backed summaries. Never writes to a Scout artifact.

Only Router's semantic rules confer current support. Producer retention labels
and durable historical claims are not substitutes for current observations.
"""
from collections.abc import Mapping
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import projection_contract as contract

VERSION = 'router-projection-summaries/1'


def _materialization_metric(reader, name, count=0):
    """Return a per-acquisition timer callback for aggregate diagnostics."""
    import time
    started = time.monotonic()
    def finish():
        metrics = reader.metadata.setdefault('routing_materialization_breakdown', {})
        metrics[name] = metrics.get(name, 0.0) + time.monotonic() - started
        if count:
            counts = reader.metadata.setdefault('routing_materialization_counts', {})
            counts[name] = counts.get(name, 0) + count
    return finish


class Profiles(Mapping):
    def __init__(self, path, check=lambda: None):
        self.path, self.check = Path(path), check

    def connect(self):
        conn = sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)
        conn.execute('PRAGMA query_only=ON')
        conn.execute('PRAGMA cache_size=-2048')
        return conn

    def __len__(self):
        with closing(self.connect()) as conn:
            return conn.execute('SELECT count(*) FROM agents').fetchone()[0]

    def __iter__(self):
        with closing(self.connect()) as conn:
            for row in conn.execute('SELECT did FROM agents ORDER BY did'):
                self.check(); yield row[0]

    def __getitem__(self, did):
        with closing(self.connect()) as db:
            return self._get(db,did)

    def values(self):
        with closing(self.connect()) as db:
            for (did,) in db.execute('SELECT did FROM agents ORDER BY did'):
                self.check(); yield self._get(db,did)

    def items(self):
        for profile in self.values():
            yield profile.identity.did, profile

    def _get(self, db, did):
        import router as r
        row = db.execute('SELECT n,original,noise,promo,first_time,last_time FROM agents WHERE did=?',(did,)).fetchone()
        if row is None: raise KeyError(did)
        caps = []
        for (payload,) in db.execute('SELECT payload FROM capabilities WHERE did=? ORDER BY capability',(did,)):
            value = json.loads(payload)
            value['evidence_items'] = [r.EvidenceItem(**item) for item in value['evidence_items']]
            caps.append(r.AgentCapability(**value))
        rank = {'STRONG_SUPPORT':0,'LIMITED_SUPPORT':1,'SIGNAL_ONLY':2,'NO_EVIDENCE':3}
        caps.sort(key=lambda c:(rank[c.support_level],-c.confidence,c.capability_id))
        peers = range(db.execute('SELECT count(DISTINCT target) FROM edges WHERE source=?',(did,)).fetchone()[0])
        responders = db.execute('SELECT count(*) FROM edges WHERE target=?',(did,)).fetchone()[0]
        reciprocal = db.execute('SELECT count(DISTINCT a.target) FROM edges a WHERE a.source=? AND EXISTS (SELECT 1 FROM edges b WHERE b.source=a.target AND b.target=a.source)',(did,)).fetchone()[0]
        supported = db.execute('SELECT value FROM meta WHERE key="direct_supported"').fetchone()[0]=='1'
        direct = [x[0] for x in db.execute('SELECT description FROM edges WHERE source=? ORDER BY ordinal LIMIT 100',(did,))]
        summary = dict(counts=row[:4],timestamps=row[4:],capabilities=caps,
        rooms=[x[0] for x in db.execute('SELECT DISTINCT room FROM observations WHERE did=? ORDER BY room',(did,))],
        sequences=[x[0] for x in db.execute('SELECT location FROM observations WHERE did=? AND original=1 ORDER BY ordinal LIMIT 10',(did,))])
        profile = r.ProfileBuilder([])._build_one(did,[],peers,responders,peers,reciprocal if supported else None,direct,summary)
        for cap,outcome,payload in db.execute('SELECT capability,outcome,payload FROM controlled WHERE did=? ORDER BY capability,key',(did,)):
            record=json.loads(payload)
            if outcome=='PASS':
                prior=next((x.support_level for x in caps if x.capability_id==cap),'NO_EVIDENCE')
                profile.validated_capability_evidence.setdefault(cap,[]).append(r.ValidatedCapabilityEvidence(
                    did,cap,record['request_id'],prior,'PASS',100,[],record['timestamp'],record['provenance']))
            else:
                profile.soft_risk_flags.add('CONTROLLED_BENCH_FAIL:'+cap)
        for (payload,) in db.execute('SELECT payload FROM validations WHERE did=? ORDER BY payload',(did,)):
            evidence=r.ValidatedCapabilityEvidence(**json.loads(payload))
            profile.validated_capability_evidence.setdefault(evidence.capability_id,[]).append(evidence)
        profile.settlement_evidence=[r.SettlementEvidence(**json.loads(x[0])) for x in db.execute('SELECT payload FROM settlements WHERE did=? ORDER BY payload',(did,))]
        return profile

    def support(self, limit=1000):
        with closing(self.connect()) as db:
            result = {}
            for did,cap,payload in db.execute('SELECT did,capability,payload FROM capabilities ORDER BY did,capability'):
                if did not in result and len(result)>=limit: break
                self.check(); result.setdefault(did,{})[cap]=json.loads(payload)['support_level']
            return result

    def support_scope(self):
        with closing(self.connect()) as db:
            count=db.execute('SELECT count(DISTINCT did) FROM capabilities').fetchone()[0]
            return dict(total_profiles_with_support=count,sample_limit=1000,complete=count<=1000,
                        full_index=str(self.path))

    def verification_count(self):
        with closing(self.connect()) as db:
            return db.execute("SELECT (SELECT count(*) FROM controlled WHERE outcome='PASS')+(SELECT count(*) FROM validations)").fetchone()[0]


def build(conn, reader, extra_observations=(), extra_interactions=(), validated=(), settlement=()):
    """Stream raw text once; aggregate duplicates and support in private SQLite."""
    import router as r
    reader.check()
    proof_hash=contract.digest(dict(proofs=getattr(reader,'local_proofs',{}),observations=[asdict(x) for x in extra_observations],interactions=list(extra_interactions),validated=[asdict(x) for x in validated],settlement=[asdict(x) for x in settlement]))
    cached = reader.metadata.get('routing_cache')
    if cached and cached.get('version') == VERSION and cached.get('proof_hash')==proof_hash and cached.get('content_binding')==reader.metadata['content_binding']:
        path = Path(cached['path'])
        from scout_projection import require
        require(path.name==reader.metadata['database_hash']+'.'+cached['sha256']+'.routing.sqlite','CONTINUITY_ROUTING_CACHE_PATH')
        reader.verify_private(path,cached['sha256'],cached['size'])
        reader.metadata['routing_cache_reused'] = True
        reader.metadata['readiness_phase'] = 'INDEX_READY'
        return Profiles(path,reader.check_cancel)
    fd, name = tempfile.mkstemp(prefix='.summaries-',suffix='.sqlite',dir=reader.cache_dir)
    os.close(fd); path=Path(name)
    inputs_path=path.with_suffix('.inputs.sqlite')
    attached=False
    cursor=None
    try:
        columns=[x[1] for x in conn.execute('PRAGMA table_info(messages)')]
        with closing(sqlite3.connect(inputs_path)) as extra:
            extra.execute('CREATE TABLE extras ('+','.join(columns)+',extra_payload TEXT,origin INTEGER)')
            for number,obs in enumerate(extra_observations):
                reader.check()
                data=dict(projection_row_id=f'router-extra-{number:020d}',room=obs.room,generation=obs.generation,seq=obs.sequence_id,timestamp=obs.timestamp,sender=obs.identity.did,signed=1,text=obs.text,normalized_text=obs.normalized_text,template_normalized_hash=obs.template_hash,nonce=obs.nonce,sig=obs.sig,message_hash=obs.message_hash,verification_status=obs.verification_status,source_export_hash=obs.source_export_hash,source_export_path=obs.source_export_path,evidence_id=obs.evidence_id)
                extra.execute('INSERT INTO extras VALUES ('+','.join('?' for _ in range(len(columns)+2))+')',[data[k] for k in columns]+[json.dumps(asdict(obs)),1])
            extra.commit()
        os.chmod(inputs_path,0o600)
        conn.execute('ATTACH DATABASE ? AS router_inputs',(inputs_path.as_uri()+'?mode=ro',)); attached=True
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA cache_size=-4096'); db.execute('PRAGMA temp_store=FILE')
            # These indexes serve actual WHERE did/source/target lookups below;
            # the producer schema and producer DB are never modified.
            db.executescript('''
              CREATE TABLE observations(did TEXT,ordinal INTEGER,room TEXT,location TEXT,time TEXT,original INTEGER,noise INTEGER,promo INTEGER,contradiction INTEGER);
              CREATE INDEX obs_did ON observations(did,ordinal);
              CREATE TABLE hits(did TEXT,capability TEXT,template TEXT,location TEXT,ordinal INTEGER,quality REAL,positive INTEGER,strong INTEGER,medium INTEGER,verified INTEGER,type TEXT,payload TEXT,PRIMARY KEY(did,capability,template));
              CREATE INDEX hit_location ON hits(did,capability,location,quality DESC,ordinal);
              CREATE TABLE edges(source TEXT,target TEXT,ordinal INTEGER,description TEXT);
              CREATE INDEX edge_source ON edges(source,target);
              CREATE INDEX edge_target ON edges(target);
              CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
              CREATE TABLE capabilities(did TEXT,capability TEXT,payload TEXT,PRIMARY KEY(did,capability));
              CREATE TABLE validations(did TEXT,payload TEXT);
              CREATE INDEX validation_did ON validations(did);
              CREATE TABLE settlements(did TEXT,payload TEXT);
              CREATE INDEX settlement_did ON settlements(did);
              CREATE TABLE controlled(did TEXT,capability TEXT,key TEXT,outcome TEXT,payload TEXT,PRIMARY KEY(did,capability,key));
              CREATE TABLE bench_workflows(key TEXT PRIMARY KEY,status TEXT,payload TEXT);
            ''')
            interrupted=[]
            def progress():
                try: reader.check()
                except BaseException as exc: interrupted.append(exc); return 1
                return 0
            db.set_progress_handler(progress,1000)
            query='''WITH all_messages AS (SELECT m.*,NULL AS extra_payload,0 AS origin FROM messages m UNION ALL SELECT * FROM router_inputs.extras), templates AS (SELECT template_normalized_hash,COUNT(DISTINCT sender) AS dids FROM messages GROUP BY template_normalized_hash), duplicates AS (SELECT sender,room,generation,COALESCE(template_normalized_hash,'') AS template,count(*) AS n FROM all_messages WHERE signed=1 GROUP BY sender,room,generation,COALESCE(template_normalized_hash,''))
              SELECT m.*,COALESCE(t.dids,1) AS template_dids,d.n AS duplicates FROM all_messages m
              LEFT JOIN templates t ON t.template_normalized_hash IS m.template_normalized_hash
              LEFT JOIN duplicates d ON d.sender=m.sender AND d.room=m.room AND d.generation=m.generation AND d.template=COALESCE(m.template_normalized_hash,'')
              WHERE m.signed=1 ORDER BY m.room,m.generation,m.seq,m.origin,substr(m.projection_row_id,5)'''
            if not extra_observations:
                query=query.replace("WITH all_messages AS (SELECT m.*,NULL AS extra_payload,0 AS origin FROM messages m UNION ALL SELECT * FROM router_inputs.extras), templates", "WITH templates")
                query=query.replace('FROM all_messages', 'FROM messages').replace('SELECT m.*,COALESCE', 'SELECT m.*,NULL AS extra_payload,COALESCE').replace('m.seq,m.origin,', 'm.seq,')
            reader.metadata['profile_query_plan']=[tuple(x) for x in conn.execute('EXPLAIN QUERY PLAN '+query)]
            try:
                with reader.stage('capability_support_derivation'):
                    with reader.stage('duplicate_processing'):
                        cursor=conn.execute(query)
                    observations_batch=[]; hits_batch=[]
                    def flush_batches():
                        if observations_batch:
                            done=_materialization_metric(reader,'observation_sql_insert',len(observations_batch))
                            db.executemany('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',observations_batch)
                            done(); observations_batch.clear()
                        if hits_batch:
                            done=_materialization_metric(reader,'hit_sql_insert',len(hits_batch))
                            db.executemany('INSERT OR IGNORE INTO hits VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',hits_batch)
                            done(); hits_batch.clear()
                    for ordinal,row in enumerate(cursor):
                        reader.check()
                        if not r.DID_RE.match(row['sender']): continue
                        done=_materialization_metric(reader,'observation_decode',1)
                        if row['extra_payload'] is None:
                            obs=r._projection_observation(row)
                        else:
                            data=json.loads(row['extra_payload']);data['identity']=r.AgentIdentity(**data['identity']);obs=r.AgentObservation(**data)
                        done()
                        done=_materialization_metric(reader,'support_classification',1)
                        noise=r.is_template_or_noise(obs.text,row['duplicates'],obs.template_dids)
                        original=not noise and r.is_substantive(obs.text)
                        contradiction=bool(r.re.search(r'\b(not|no|never)\s+(solidity|smart contract|python|testing|technocore)\b',r.normalize_text(obs.text)))
                        observations_batch.append((obs.identity.did,ordinal,obs.room,obs.location_id,obs.timestamp,int(original),int(noise),int(r.is_promotional(obs.text)),int(contradiction)))
                        for d in r.semantic_decisions(obs,row['duplicates']):
                            if d.support_contribution=='NONE': continue
                            e=d.evidence; positive=d.support_contribution in {'LIMITED','STRONG'}
                            template=f'{obs.room}:{obs.generation}:{obs.template_hash or d.observation_id}'
                            hits_batch.append((obs.identity.did,d.capability_id,template,e.sequence_id,ordinal,r.provenance_quality_score(e.verification_status),int(positive),int(e.strong),int(e.usable and e.specificity>=.65),int(e.verification_status=='VERIFIED_OFFLINE'),e.evidence_type,json.dumps(asdict(e),separators=(',',':'))))
                        done()
                        if len(observations_batch)>=256:
                            flush_batches()
                    flush_batches()
                with reader.stage('interaction_loading'):
                    supported=False
                    import itertools
                    for ordinal,row in enumerate(itertools.chain(conn.execute("SELECT i.*,p.annotations_json FROM interactions i JOIN source_provenance p ON p.entity_type='interaction' AND p.projection_row_id=i.projection_row_id ORDER BY i.projection_row_id"),extra_interactions)):
                        reader.check()
                        if not r.is_direct_interaction_row(row): continue
                        supported=True
                        if row['source_did']==row['target_did']: continue
                        annotations=json.loads(row['annotations_json']) if 'annotations_json' in row.keys() else {}
                        if (annotations.get('same_operator') is True or annotations.get('independent_reputation') is False or annotations.get('operator_group')==contract.FAMILY
                                or row['source_did'] in {r.SCOUT_DID,r.BENCH_DID,r.ROUTER_DID}
                                and row['target_did'] in {r.SCOUT_DID,r.BENCH_DID,r.ROUTER_DID}):
                            continue
                        db.execute('INSERT INTO edges VALUES (?,?,?,?)',(row['source_did'],row['target_did'],ordinal,f"{row['source_did']} -> {row['target_did']} ({row['relationship_type']})"))
                    db.execute('INSERT INTO meta VALUES (?,?)',('direct_supported',str(int(supported))))
                with reader.stage('profile_construction'):
                    db.executescript('''
                      CREATE TABLE agents(did TEXT PRIMARY KEY,n INTEGER,original INTEGER,noise INTEGER,promo INTEGER,first_time TEXT,last_time TEXT);
                      INSERT INTO agents SELECT did,count(*),sum(original),sum(noise),sum(promo),NULL,NULL FROM observations GROUP BY did;
                      UPDATE agents SET first_time=(SELECT time FROM observations o WHERE o.did=agents.did ORDER BY ordinal LIMIT 1),last_time=(SELECT time FROM observations o WHERE o.did=agents.did ORDER BY ordinal DESC LIMIT 1);
                      CREATE TABLE positives AS SELECT * FROM (SELECT *,row_number() OVER(PARTITION BY did,capability,location ORDER BY quality DESC,ordinal) AS rn FROM hits WHERE positive=1) WHERE rn=1;
                      CREATE INDEX positive_lookup ON positives(did,capability,quality DESC,ordinal);
                    ''')
                    for did,cap in db.execute('SELECT DISTINCT did,capability FROM hits ORDER BY did,capability'):
                        reader.check()
                        count,strong,medium,verified=db.execute('SELECT count(*),COALESCE(sum(strong),0),COALESCE(sum(medium),0),COALESCE(sum(verified),0) FROM positives WHERE did=? AND capability=?',(did,cap)).fetchone()
                        weak=db.execute('SELECT count(DISTINCT location) FROM hits WHERE did=? AND capability=? AND positive=0',(did,cap)).fetchone()[0]
                        level='STRONG_SUPPORT' if strong>=1 or medium>=2 else 'LIMITED_SUPPORT' if count else 'SIGNAL_ONLY'
                        positive=[json.loads(x[0]) for x in db.execute('SELECT payload FROM positives WHERE did=? AND capability=? ORDER BY quality DESC,ordinal LIMIT 8',(did,cap))]
                        signals=[json.loads(x[0]) for x in db.execute('SELECT payload FROM hits WHERE did=? AND capability=? AND positive=0 ORDER BY ordinal LIMIT 8',(did,cap))]
                        types=dict(db.execute('SELECT type,count(*) FROM positives WHERE did=? AND capability=? GROUP BY type',(did,cap)))
                        contradictions=[x[0] for x in db.execute('SELECT location FROM observations WHERE did=? AND contradiction=1 ORDER BY ordinal LIMIT 5',(did,))] if cap=='security.general' else []
                        warning='Relevant evidence does not reach STRONG_SUPPORT.' if level in {'LIMITED_SUPPORT','SIGNAL_ONLY'} else 'Most apparent capability evidence lacks concrete/reproducible detail.' if count>=5 and not strong else None
                        payload=dict(capability_id=cap,confidence=round(min(.95,.25+.12*count+.18*strong+.08*medium+.01*min(weak,3)+min(.09,.03*verified)),2),supporting_observation_count=count,supporting_sequence_ids=[x['sequence_id'] for x in positive],representative_evidence=[x['text'] for x in positive[:3]],contradictory_evidence=contradictions,evidence_type_counts=types,strong_supporting_observation_count=strong,medium_supporting_observation_count=medium,signal_observation_count=weak,support_level=level,evidence_items=positive+signals,quality_warning=warning)
                        db.execute('INSERT INTO capabilities VALUES (?,?,?)',(did,cap,json.dumps(payload,separators=(',',':'))))
                    for table,items,field in [('validations',validated,'target_did'),('settlements',settlement,'did')]:
                        for item in items:
                            reader.check();did=getattr(item,field)
                            db.execute('INSERT OR IGNORE INTO agents VALUES (?,0,0,0,0,NULL,NULL)',(did,))
                            db.execute('INSERT INTO '+table+' VALUES (?,?)',(did,json.dumps(asdict(item))))
                    db.execute('DROP TABLE positives'); db.execute('DROP TABLE hits'); db.commit()
                with reader.stage('controlled_bench_linkage'):
                    import projection_bench
                    import scout_projection
                    if getattr(reader,'local_proofs',{}):
                        for item in projection_bench.linked_outcomes(scout_projection.qualification_history(conn),reader.local_proofs):
                            reader.check()
                            db.execute("INSERT INTO bench_workflows VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET status=CASE WHEN bench_workflows.status!=excluded.status THEN 'CONFLICT' ELSE bench_workflows.status END",(item['key'],item['workflow_status'],json.dumps(item)))
                            if item['capability'] is None: continue
                            db.execute('INSERT OR IGNORE INTO agents VALUES (?,0,0,0,0,NULL,NULL)',(item['target'],))
                            # A conflicting effective FAIL cannot be hidden by a
                            # second PASS for the same immutable request.
                            db.execute("INSERT INTO controlled VALUES (?,?,?,?,?) ON CONFLICT(did,capability,key) DO UPDATE SET outcome=CASE WHEN controlled.outcome='FAIL' OR excluded.outcome='FAIL' THEN 'FAIL' ELSE 'PASS' END",(item['target'],item['capability'],item['key'],item['outcome'],json.dumps(item)))
                    db.commit()
                    reader.metadata['controlled_bench_workflows']=db.execute('SELECT count(*) FROM bench_workflows').fetchone()[0]
            except sqlite3.Error:
                if interrupted: raise interrupted[0]
                raise
        reader.check()
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            while chunk:=stream.read(1024**2): reader.check(); digest.update(chunk)
        final=reader.cache_dir/(reader.metadata['database_hash']+'.'+digest.hexdigest()+'.routing.sqlite')
        os.replace(path,final); reader.created.add(final)
        reader.metadata['routing_cache']={'version':VERSION,'path':str(final),'sha256':digest.hexdigest(),'size':final.stat().st_size,'proof_hash':proof_hash,'content_binding':reader.metadata['content_binding']}
        reader.metadata['readiness_phase'] = 'INDEX_READY'
        return Profiles(final,reader.check_cancel)
    finally:
        if cursor is not None: cursor.close()
        try:
            if attached: conn.execute('DETACH DATABASE router_inputs')
        finally:
            inputs_path.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
