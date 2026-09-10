"""Authoritative, source-scoped closure checks for retained projected messages.

No prose inference, filesystem proof lookup, or network access. Unknown generic
protocols have no reviewed terminal grammar and cannot authorize expiry.
"""
from datetime import timedelta, datetime, timezone
import json
import sqlite3
import projection_contract as c
from scout_snapshot import SnapshotError


def require(value):
    if not value: raise SnapshotError('CONTINUITY_UNVERIFIED_TERMINAL_TRANSITION')


class ClosureVerifier:
    def __init__(self, conn, scratch, check):
        self.db, self.check = scratch, check
        scratch.executescript('''CREATE TABLE workflow_facts(id TEXT PRIMARY KEY,source TEXT,room TEXT,generation TEXT,sender TEXT,proto TEXT,workflow TEXT,role TEXT,result TEXT,reference TEXT,first_time TEXT,hash TEXT,deadline INTEGER,authenticated INTEGER,first_us INTEGER);
          CREATE INDEX workflow_scope ON workflow_facts(source,room,generation,proto,workflow);
          CREATE INDEX workflow_reference ON workflow_facts(source,room,generation,reference);''')
        for row in conn.execute("SELECT m.*,p.source_namespace,s.first_observed_at FROM messages m JOIN source_provenance p ON p.entity_type='message' AND p.projection_row_id=m.projection_row_id JOIN selection_membership s ON s.entity_type='message' AND s.projection_row_id=m.projection_row_id"):
            check(); text=row['text']
            if not (text.lstrip().startswith('{') or text.startswith('tclk1 ')): continue
            try: obj=c.loads(text[6:] if text.startswith('tclk1 ') else text)
            except c.ProjectionError: continue
            if not isinstance(obj,dict): continue
            kind=obj.get('type'); version=obj.get('version',obj.get('v')); schema=obj.get('schema_version',obj.get('schema'))
            if text.startswith('tclk1 '):
                proto='tclk/1'; workflow=obj.get('id') if kind=='offer' else None
                reference=obj.get('ref') or obj.get('contract'); deadline=obj.get('expiresMs') if kind=='offer' else None
            elif kind in {'JOB','CLAIM','RESULT','DELIVER','ACCEPT','REJECT'} and (type(version) in (str,int) and version in ('1','v1',1) or isinstance(schema,str) and schema.endswith('.v1')):
                proto='kibble/v1'; workflow=obj.get('job_id'); reference=None; deadline=None
            else: continue
            if workflow is not None and not isinstance(workflow,str): continue
            if reference is not None and not isinstance(reference,str): continue
            result=obj.get('result_raw_record_id')
            if result is not None and not isinstance(result,str): continue
            if type(deadline) is not int or not 0<=deadline<=253402300799999: deadline=None
            scratch.execute('INSERT INTO workflow_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(row['projection_row_id'],row['source_namespace'],row['room'],row['generation'],row['sender'],proto,workflow,kind,'sm1:'+result if result else None,reference,row['first_observed_at'],c.text_hash(text),deadline,int(row['signed']==1 and row['verification_status']=='VERIFIED_OFFLINE'),(c.instant(row['first_observed_at'])-datetime(1970,1,1,tzinfo=timezone.utc))//timedelta(microseconds=1)))

    def verify(self, row, evaluated_at):
        self.check()
        require(row['entity_type']=='message' and row['retention_class'] in {'WORK_LIFECYCLE','TCLK_LIFECYCLE'})
        fact=self.db.execute('SELECT * FROM workflow_facts WHERE id=?',(row['projection_row_id'],)).fetchone()
        require(fact is not None)
        # Our index is Router-private. Local producer namespace, room and exact
        # generation are all part of the domain; UNKNOWN_LEGACY is not a wildcard.
        columns=[x[1] for x in self.db.execute('PRAGMA table_info(workflow_facts)')]
        fact=dict(zip(columns,fact)); scope=(fact['source'],fact['room'],fact['generation'])
        if fact['proto']=='tclk/1':
            require(row['retention_class']=='TCLK_LIFECYCLE' and fact['role']=='offer' and fact['authenticated'] and fact['deadline'] is not None)
            roots=self.db.execute("SELECT count(DISTINCT json_array(sender,hash,deadline)) FROM workflow_facts WHERE source=? AND room=? AND generation=? AND proto='tclk/1' AND workflow=?",(*scope,fact['workflow'])).fetchone()[0]
            require(roots==1)
            # Any transition referencing this root keeps it active. No accept,
            # lock/reveal/refund/settlement inference is introduced here.
            require(self.db.execute('SELECT 1 FROM workflow_facts WHERE source=? AND room=? AND generation=? AND reference=? LIMIT 1',(*scope,fact['workflow'])).fetchone() is None)
            closed=datetime(1970,1,1,tzinfo=timezone.utc)+timedelta(milliseconds=fact['deadline'])
            require(closed<=c.instant(evaluated_at))
            horizon=c.POLICY['parameters']['closed_tclk_seconds']
        else:
            require(row['retention_class']=='WORK_LIFECYCLE' and fact['workflow'])
            domain=(*scope,fact['workflow'])
            root_count,identities,issuer,root_time=self.db.execute("SELECT count(*),count(DISTINCT json_array(sender,hash)),min(sender),max(first_us) FROM workflow_facts WHERE source=? AND room=? AND generation=? AND workflow=? AND proto='kibble/v1' AND role='JOB' AND authenticated=1",domain).fetchone()
            require(root_count==1 and identities==1)
            count,invalid,results,closed_us=self.db.execute("""SELECT count(*),COALESCE(sum(t.role!='ACCEPT' OR r.id IS NULL),0),count(DISTINCT t.result),min(max(t.first_us,r.first_us,?))
                FROM workflow_facts t LEFT JOIN workflow_facts r ON r.id=t.result AND r.authenticated=1 AND r.role IN ('RESULT','DELIVER') AND r.proto=t.proto AND r.source=t.source AND r.room=t.room AND r.generation=t.generation AND r.workflow=t.workflow
                WHERE t.source=? AND t.room=? AND t.generation=? AND t.workflow=? AND t.proto='kibble/v1' AND t.authenticated=1 AND t.sender=? AND t.role IN ('ACCEPT','REJECT')""",(root_time,*domain,issuer)).fetchone()
            require(count and not invalid and results==1 and closed_us is not None)
            closed=datetime(1970,1,1,tzinfo=timezone.utc)+timedelta(microseconds=closed_us)
            horizon=c.POLICY['parameters']['closed_work_seconds']
        require(c.instant(row['retain_until'])==closed+timedelta(seconds=horizon))
        return closed
