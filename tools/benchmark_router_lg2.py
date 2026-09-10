"""Fresh-process LG2 compatibility benchmark; only fixed synthetic fixture roots.

Run: .venv/bin/python tools/benchmark_router_lg2.py > <new-report.json>
A1 controls remove audit-only LG2 storage from verified temporary copies. They
are semantic controls, not A1 producer admission claims or LG1 runtime results.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import projection_contract as c
import projection_legacy as lg
import projection_routing as pr
import router
import scout_projection as v

ROOT=Path('/private/tmp/scout-lg2-router-fixtures-final-20260908')


def publish(root,m):
    raw=c.canonical(m);h=hashlib.sha256(raw).hexdigest();name=f"manifest-v2-{m['snapshot_id']}-{h}.json"
    (root/name).write_bytes(raw)
    (root/'current.json').write_bytes(c.canonical(dict(schema='flop-scout-router-current/v2',manifest=name,manifest_sha256=h,published_at=m['produced_at'])))


def sample(name,mode):
    index=c.loads((ROOT/'index.json').read_bytes());entry=index['fixtures'][name]
    source=Path(entry['current']).parent
    pointer=c.loads((source/'current.json').read_bytes());m=c.loads((source/pointer['manifest']).read_bytes())
    now=c.instant(index['clock'])
    with tempfile.TemporaryDirectory(prefix='router-lg2-benchmark-') as temporary:
        root=Path(temporary).resolve();pub=root/'publication';pub.mkdir()
        if mode=='A1_CONTROL':
            # Bootstrap validates the original before any SQLite access. This
            # setup is excluded from timings and its RSS is reported as a limit.
            with v.ProjectionReader(source,root/'bootstrap') as seed:
                _,verified=seed.read(lambda conn:None,now=now)
            path=pub/'control.sqlite'
            with sqlite3.connect(Path(verified['cache_path']).as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(path) as dst:
                src.execute('PRAGMA query_only=ON');src.backup(dst)
                for table in ('legacy_generation_witnesses','legacy_generation_reports'):dst.execute('DROP TABLE '+table)
                dst.commit()
            m.update(contract_revision='A1');m.pop('legacy_generation_policy');m.pop('legacy_generation_encoding')
            for table in lg.TABLES:m['row_counts'].pop(table)
            m.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size)
            m['database']=f"router-projection-v2-{m['database_content_id']}-{m['sha256']}.sqlite";path.rename(pub/m['database'])
            publish(pub,m);source=pub
        results={}
        def consume(reader,conn):
            profiles=pr.build(conn,reader)
            with reader.stage('routing_state_construction'):
                profiles.support();profiles.support_scope();profiles.verification_count()
                router._worker_evidence_snapshot(profiles,{'scout_snapshot':{'routing_input_hash':reader.metadata['routing_input_hash'],'selection_policy':reader.metadata['selection_policy']}})
            return profiles
        with v.ProjectionReader(source,root/'cache') as reader:
            for label in ('cold','warm_first','warm_steady'):
                try:
                    _,meta=reader.read(lambda conn:consume(reader,conn),previous=results.get('previous'),now=now)
                    results['previous']=meta
                    results[label]={k:meta.get(k) for k in ('total_acquisition_seconds','stage_seconds','peak_rss_bytes','legacy_generation_audit','validation_cache_reused','routing_cache_reused','readiness')}
                except Exception as exc:
                    results[label]=dict(error=getattr(exc,'code',type(exc).__name__),stage_seconds=reader.metadata['stage_seconds'],peak_rss_bytes=v.rss_bytes())
                    break
        if 'previous' in results:
            with v.ProjectionReader(source,root/'cache') as reader:
                _,meta=reader.read(lambda conn:consume(reader,conn),previous=results['previous'],now=now)
                results['restart']={k:meta.get(k) for k in ('total_acquisition_seconds','stage_seconds','peak_rss_bytes','validation_cache_reused','routing_cache_reused')}
        results.pop('previous',None)
        return dict(name=name,mode=mode,artifact_bytes=m['size_bytes'],row_counts=m['row_counts'],measurements=results)


if __name__=='__main__':
    if len(sys.argv)>1:
        print(json.dumps(sample(sys.argv[1],sys.argv[2]),sort_keys=True))
    else:
        index=c.loads((ROOT/'index.json').read_bytes());rows=[]
        for trial in range(3):
            for name in index['fixtures']:
                modes=['LG2'] if name=='true-conflict' else (['LG2','A1_CONTROL'] if trial%2==0 else ['A1_CONTROL','LG2'])
                for mode in modes:
                    result=subprocess.run([sys.executable,__file__,name,mode],text=True,capture_output=True,check=True)
                    rows.append(dict(trial=trial,**json.loads(result.stdout)))
        report=dict(schema='router-lg2-consumer-benchmark/v1',fixture_index=str(ROOT/'index.json'),
                    fixture_index_sha256=hashlib.sha256((ROOT/'index.json').read_bytes()).hexdigest(),
                    scope='Nine synthetic fixtures; three fresh-process trials per mode. Warm samples repeat the same immutable publication; separate tests advance heartbeat publication IDs. Restart uses a new reader and rehashes private files. A1 control setup RSS is included. No cold OS cache or production qualification.',
                    limits=dict(timeout_seconds=30,max_memory_bytes=v.MAX_MEMORY,max_artifact_bytes=v.MAX_BYTES),
                    implementation_sha256={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ('router.py','scout_projection.py','projection_legacy.py','projection_routing.py')},trials=rows)
        print(json.dumps(report,indent=2,sort_keys=True))
