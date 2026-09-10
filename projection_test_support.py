"""Small synthetic V2 publications; no Scout imports or live state."""
import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime,timezone
import projection_contract as c
from scout_projection import SCHEMA_SQL
from test_scout_snapshot import make_database, atomic_write


def publish_snapshot(root,database=None,snapshot_id='1',produced_at=None,manifest_changes=None,database_bytes=None):
    root.mkdir(parents=True,exist_ok=True)
    when=produced_at or datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    with sqlite3.connect(':memory:') as conn:
        conn.row_factory=sqlite3.Row;conn.executescript(SCHEMA_SQL)
        conn.execute('INSERT INTO snapshot_meta VALUES (1,?,?,?,?)',(c.SCHEMA,snapshot_id,when,c.POLICY_SHA))
        if database:
            src=sqlite3.connect(database);src.row_factory=sqlite3.Row
            try:
                for n,row in enumerate(src.execute('SELECT * FROM messages'),1):
                    d=dict(row);text=d['text'];rid='sm1:raw-'+str(n)
                    d.update(projection_row_id=rid,generation=str(d.get('generation') if d.get('generation') is not None else 'UNKNOWN_LEGACY'),message_hash=c.text_hash(text))
                    cols=[r[1] for r in conn.execute('PRAGMA table_info(messages)')]
                    conn.execute('INSERT INTO messages VALUES ('+','.join('?' for _ in cols)+')',[d.get(k) for k in cols])
                    annotation=dict(c.ANNOTATIONS)
                    from scout_projection import LOCAL_DIDS
                    if d['sender'] in LOCAL_DIDS:annotation.update(operator_group=c.FAMILY,same_operator=True,independent_reputation=False)
                    conn.execute('INSERT INTO source_provenance VALUES (?,?,?,?,?,?,?,?)',('message',rid,'scout-observer','raw-'+str(n),None,'raw-'+str(n),None,c.canonical(annotation).decode()))
                    conn.execute('INSERT INTO selection_membership VALUES (?,?,?,?,?,?)',('message',rid,'BENCH_VERIFICATION','2020-01-01T00:00:00Z',None,'[]'))
                for row in src.execute('SELECT * FROM interactions'):
                    rid='si1:'+c.digest(dict(row))
                    conn.execute('INSERT INTO interactions VALUES (?,?,?,?,?)',(rid,*tuple(row)))
                    conn.execute('INSERT INTO source_provenance VALUES (?,?,?,?,?,?,?,?)',('interaction',rid,'scout-observer',rid,None,None,None,c.canonical(c.ANNOTATIONS).decode()))
                    conn.execute('INSERT INTO selection_membership VALUES (?,?,?,?,?,?)',('interaction',rid,'IDENTITY_OPERATOR','2020-01-01T00:00:00Z',None,'[]'))
            finally:src.close()
        watermarks=[dict(r) for r in conn.execute('SELECT room,generation,count(*) AS record_count,min(seq) AS min_seq,max(seq) AS max_seq FROM messages GROUP BY room,generation ORDER BY room,generation')]
        for w in watermarks:
            conn.execute('INSERT INTO watermarks VALUES (?,?,?,?,?)',tuple(w.values()))
            row=conn.execute('SELECT * FROM messages WHERE room=? AND generation=? AND seq=?',(w['room'],w['generation'],w['max_seq'])).fetchone()
            conn.execute('INSERT INTO coverage_history VALUES (?,?,?,?,?)',(w['room'],w['generation'],w['max_seq'],row['projection_row_id'][4:],c.digest(dict(row))))
        history=[dict(r) for r in conn.execute('SELECT * FROM coverage_history ORDER BY room,generation')]
        counts={t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in c.TABLES}
        conn.commit();data=database_bytes if database_bytes is not None else conn.serialize()
    h=hashlib.sha256(data).hexdigest();name=f'router-projection-v2-{snapshot_id}-{h}.sqlite';(root/name).write_bytes(data)
    m=dict(schema='flop-scout-router-snapshot/v2',contract_revision='A1',snapshot_id=snapshot_id,publication_kind='CONTENT',database_content_id=snapshot_id,database=name,sha256=h,size_bytes=len(data),database_schema_version=c.SCHEMA,selection_policy=c.POLICY,selection_policy_sha256=c.POLICY_SHA,content_created_at=when,selection_evaluated_at=when,produced_at=when,source_checkpoint=dict(source_id='scout-observer',epoch='test',committed_event_id=snapshot_id),next_expiry_at=None,row_counts=counts,watermarks=watermarks,coverage_history=history)
    m.update(manifest_changes or {});raw=c.canonical(m);mh=hashlib.sha256(raw).hexdigest();mn=f'manifest-v2-{snapshot_id}-{mh}.json';(root/mn).write_bytes(raw)
    pointer=dict(schema='flop-scout-router-current/v2',manifest=mn,manifest_sha256=mh,published_at=when)
    atomic_write(root/'current.json',c.canonical(pointer))
    return m,pointer
