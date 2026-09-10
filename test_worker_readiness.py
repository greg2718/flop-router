"""Worker integration tests against temporary producer publication fixtures."""
import copy
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
from io import StringIO
from unittest.mock import patch

import router
import scout_snapshot as ss
from projection_test_support import make_database, publish_snapshot
from test_router import obs, scout_tclk_offer_record


class WorkerReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.state = self.root / 'state'
        self.publication = self.root / 'publication'
        self.db = self.root / 'producer.sqlite'
        make_database(self.db)
        self.manifest, self.pointer = publish_snapshot(self.publication, self.db)
        self.out = StringIO()
        capture = redirect_stdout(self.out)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def once(self, **kwargs):
        return router.worker_once(self.state, **{'scout_snapshot_root': self.publication, **kwargs})

    def inbox(self, record=None):
        path = router.worker_paths(self.state)['tasks']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record or {'task_id':'task-1','task':'Debug an HTTP 400 response'}) + '\n')
        return path

    def source(self, cycle, name='scout_snapshot'):
        return next(item for item in cycle['sources'] if item['name'] == name)

    def cli(self, *options):
        return subprocess.run([sys.executable, str(Path(router.__file__).resolve()), 'worker','once',
                               '--state-dir',str(self.state),'--shadow',*options], cwd='/',
                              capture_output=True,text=True,timeout=10)

    def test_absolute_resolution_and_cwd_root_cli(self):
        result = self.cli('--scout-snapshot-root', str(self.publication))
        self.assertEqual(result.returncode, 0, result.stderr)
        cycle = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(cycle['status'], 'READY_IDLE')
        self.assertEqual(self.source(cycle)['path'], str(self.publication))
        self.assertFalse(any(s['path'] and s['path'].startswith('/devdata/') for s in cycle['sources']))

    def test_live_db_and_ambiguous_globals_rejected(self):
        result = self.cli('--scout-db',str(self.db))
        self.assertEqual(result.returncode, 2)
        self.assertIn('unsafe', result.stderr.lower())
        for option in ('--db','--validation-store','--ingest-store','--tclk-store','--verification-evidence-store'):
            result = subprocess.run([sys.executable,router.__file__,option,str(self.db),'worker','once','--shadow'],
                                    capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode, 2)
        self.assertFalse(self.state.exists())

    def test_required_missing_and_unconfigured(self):
        for value in (None, self.root/'missing'):
            cycle = self.once(scout_snapshot_root=value)
            self.assertEqual(cycle['status'],'DEGRADED_INPUT_MISSING')
            self.assertEqual(cycle['shadow_decisions_produced'],0)
        result = self.cli()
        self.assertEqual(result.returncode,1)

    def test_snapshot_symlink_unreadable_and_invalid(self):
        link=self.root/'link';link.symlink_to(self.publication,target_is_directory=True)
        self.assertEqual(self.once(scout_snapshot_root=link)['status'],'DEGRADED_INPUT_INVALID')
        pointer=self.publication/'current.json';pointer.chmod(0)
        try:self.assertEqual(self.once()['status'],'DEGRADED_INPUT_UNREADABLE')
        finally:pointer.chmod(0o600)
        pointer.write_text('malformed SECRET_SENTINEL')
        self.assertEqual(self.once()['status'],'DEGRADED_INPUT_INVALID')
        self.assertNotIn('SECRET_SENTINEL',self.out.getvalue())

    def test_optional_sources_configured_missing_invalid_unreadable(self):
        self.inbox()
        for option in ('validation_store','ingest_store','tclk_store'):
            path=self.root/(option+'.jsonl')
            self.assertEqual(self.once(**{option:path})['status'],'DEGRADED_INPUT_MISSING')
            for payload in ('bad SECRET_SENTINEL','[]','{}','{"task":NaN}'):
                path.write_text(payload)
                cycle=self.once(**{option:path})
                self.assertEqual(cycle['status'],'DEGRADED_INPUT_INVALID')
                self.assertEqual(cycle['shadow_decisions_produced'],0)
            path.chmod(0)
            try:self.assertEqual(self.once(**{option:path})['status'],'DEGRADED_INPUT_UNREADABLE')
            finally:path.chmod(0o600)
        self.assertNotIn('SECRET_SENTINEL',self.out.getvalue())

    def test_disabled_and_empty_sources_ready_idle(self):
        cycle=self.once()
        for name in ('validation_store','ingest_store','tclk_store','bench_proof_store'):
            self.assertEqual(self.source(cycle,name)['reason'],'DISABLED_UNCONFIGURED')
        path=self.root/'empty.jsonl';path.write_text('')
        cycle=self.once(validation_store=path,ingest_store=path,tclk_store=path,bench_proof_store=path)
        self.assertEqual(cycle['status'],'READY_IDLE')
        self.assertTrue(all(s['valid'] for s in cycle['sources']))

    def test_task_alias_validation_before_fallback(self):
        invalid=[{'task':[],'text':'valid'}, {'task':'valid','text':{}},
                 {'task':'one','text':'two'}, {'task':'valid','task_id':[],'job_id':'id'},
                 {'task':'valid','task_id':'a','job_id':'b'}]
        for field in ('task','text','task_id','job_id'):
            for value in ('',' ',None,True,1,[],{}):
                invalid.append({'task':'valid',field:value})
        for record in invalid:
            with self.subTest(record=record):
                self.inbox(record)
                cycle=self.once()
                self.assertEqual(cycle['status'],'DEGRADED_INPUT_INVALID')
                self.assertEqual(cycle['shadow_decisions_produced'],0)
        self.assertFalse(router.worker_paths(self.state)['decisions'].exists())
        for record in ({'task':'one','text':'one','task_id':'x','job_id':'x'},
                       {'text':'two','job_id':'y'}, {'task':'three'}):
            self.inbox(record)
            self.assertEqual(self.once()['status'],'READY_ACTIVE')

    def test_inbox_initialized_once_and_recovery(self):
        self.once();path=router.worker_paths(self.state)['tasks']
        self.assertEqual(path.read_text(),'')
        path.unlink()
        self.assertEqual(self.once()['status'],'DEGRADED_INPUT_MISSING')
        self.assertFalse(path.exists())
        path.write_text('')
        self.assertEqual(self.once()['status'],'READY_IDLE')

    def test_recovery_retains_history_dedup_and_continuity(self):
        self.inbox();first=self.once()
        pointer=self.publication/'current.json';saved=pointer.read_bytes();pointer.unlink()
        self.assertEqual(self.once()['status'],'DEGRADED_INPUT_MISSING')
        self.assertEqual(router.worker_status(self.state)['last_success_at'],first['ended_at'])
        pointer.write_bytes(saved)
        cycle=self.once()
        self.assertEqual(cycle['status'],'READY_IDLE')
        self.assertEqual(cycle['duplicate_decisions_suppressed'],1)
        state=router.worker_status(self.state)
        self.assertEqual(state['last_accepted_projection_v2']['snapshot_id'],'1')
        self.assertEqual(state['consecutive_failures'],0)

    def test_stale_snapshot_blocks_and_does_not_advance_continuity(self):
        old=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat().replace('+00:00','Z')
        publish_snapshot(self.publication,self.db,produced_at=old)
        self.assertEqual(self.once(max_snapshot_age=60)['status'],'DEGRADED_INPUT_STALE')
        self.assertNotIn('last_accepted_snapshot',router.worker_status(self.state))

    def test_continuity_regression_after_restart(self):
        publish_snapshot(self.publication,self.db,snapshot_id='2');self.once()
        publish_snapshot(self.publication,self.db,snapshot_id='1')
        cycle=self.once()
        self.assertEqual(cycle['status'],'DEGRADED_INPUT_INVALID')
        self.assertEqual(self.source(cycle)['detail'],'CONTINUITY_PUBLICATION_ROLLBACK')

    def test_degraded_never_routes_signs_or_uses_network(self):
        self.inbox()
        with patch.object(router.Router,'route',side_effect=AssertionError()) as route, \
             patch.object(router,'load_router_private_key_for_signing',side_effect=AssertionError()) as key, \
             patch.object(router.urllib.request,'urlopen',side_effect=AssertionError()) as network:
            self.assertEqual(self.once(scout_snapshot_root=None)['status'],'DEGRADED_INPUT_MISSING')
        route.assert_not_called();key.assert_not_called();network.assert_not_called()

    def test_legacy_state_and_safe_manifest_status(self):
        paths=router.worker_paths(self.state);paths['dir'].mkdir(parents=True)
        paths['state'].write_text(json.dumps({'last_success_at':'historical','consecutive_failures':0,'custom_old_field':'retained'}))
        history=''.join(json.dumps({'status':'HEALTHY','cycle_id':str(i)})+'\n' for i in range(3301))
        paths['cycles'].write_text(history)
        self.assertEqual(router.worker_status(self.state)['readiness'],'UNKNOWN_LEGACY')
        self.once()
        self.assertTrue(paths['cycles'].read_text().startswith(history))
        state=router.worker_status(self.state)
        self.assertEqual(state['custom_old_field'],'retained')
        before=paths['state'].read_bytes();out=StringIO()
        with redirect_stdout(out):router.print_worker_status(self.state)
        self.assertEqual(json.loads(out.getvalue())['sources'],state['sources'])
        self.assertEqual(paths['state'].read_bytes(),before)
        source=next(s for s in state['sources'] if s['name']=='scout_snapshot')
        self.assertTrue({'snapshot_id','manifest_hash','database_hash','produced_at','age_seconds','watermarks','record_count','current_pointer_status'}<=source.keys())

    def test_loop_exceptions_persist_and_backoff_is_bounded(self):
        self.once();before=router.worker_status(self.state);delays=[]
        def wait(delay):
            delays.append(delay)
            if len(delays)==3:signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
        with patch.object(router,'run_worker_cycle',side_effect=ValueError('SECRET_SENTINEL')), \
             patch.object(router.threading.Event,'wait',side_effect=wait):
            router.run_worker_loop(self.state,1,2,scout_snapshot_root=self.publication)
        state=router.worker_status(self.state)
        self.assertEqual(delays,[1,2,2]);self.assertEqual(state['status'],'ERROR')
        self.assertEqual(state['consecutive_failures'],4)
        self.assertEqual(state['last_success_at'],before['last_success_at'])
        self.assertNotIn('SECRET_SENTINEL',self.out.getvalue())
        self.assertFalse(router.worker_paths(self.state)['lock'].exists())

    def test_logs_transitions_recovery_and_idle_throttling(self):
        pointer=self.publication/'current.json';saved=pointer.read_bytes()
        def wait(_):
            count=len(router.worker_paths(self.state)['cycles'].read_text().splitlines())
            if count==1:pointer.unlink()
            elif count==2:pointer.write_bytes(saved)
            elif count==5:signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
        with patch.object(router.threading.Event,'wait',side_effect=wait):
            router.run_worker_loop(self.state,1,2,scout_snapshot_root=self.publication)
        events=[json.loads(line) for line in self.out.getvalue().splitlines()]
        names=[e['event'] for e in events]
        for name in ('worker_startup','source_configuration','readiness_transition','source_failure','source_recovery','cycle_summary','worker_shutdown'):
            self.assertIn(name,names)
        self.assertEqual(names.count('cycle_summary'),4)
        self.assertEqual(names.count('source_failure'),1)
        self.assertEqual(names.count('source_recovery'),1)

    def test_periodic_idle_summary(self):
        cycle=self.once();self.out.seek(0);self.out.truncate()
        logger=router.WorkerLog(self.state,cycle['sources'])
        with patch.object(router.time,'monotonic',side_effect=[0,1,901]):
            for _ in range(3):logger.cycle(cycle)
        self.assertEqual(sum(json.loads(line)['event']=='cycle_summary' for line in self.out.getvalue().splitlines()),2)

    def test_time_and_publication_identity_do_not_change_decision(self):
        self.inbox()
        export=self.root/'export.jsonl'
        stamp=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        export.write_text(json.dumps(router.observation_to_record(obs(router.SCOUT_DID,1,'Debug an HTTP 400 response',ts=stamp)))+'\n')
        self.assertEqual(self.once(ingest_store=export)['status'],'READY_ACTIVE')
        class Future(datetime):
            @classmethod
            def now(cls,tz=None):return datetime.now(timezone.utc)+timedelta(hours=1)
        with patch.object(router,'datetime',Future):
            self.assertEqual(self.once(ingest_store=export,max_snapshot_age=7200)['status'],'READY_IDLE')
        publish_snapshot(self.publication,self.db,snapshot_id='2')
        self.assertEqual(self.once(ingest_store=export)['status'],'READY_IDLE')
        record=json.loads(export.read_text());record['generation']='new-generation';record['evidence_id']='new-id'
        export.write_text(json.dumps(record)+'\n')
        self.assertEqual(self.once(ingest_store=export)['status'],'READY_ACTIVE')

    def test_full_substantive_profile_hash_and_presentation_exclusion(self):
        profiles=router.ProfileBuilder([obs(router.SCOUT_DID,1,'Debug an HTTP 400 response')]).build_all()
        baseline=router._worker_evidence_snapshot(profiles)
        for field,value in [('positive_trust_evidence',1),('soft_risk_flags',{'risk'}),('hard_trust_flags',{'risk'}),
                            ('independent_counterparty_groups',{'group'}),('completion_successes',3),
                            ('claimed_capabilities',{'debugging'}),('direct_interaction_evidence',['changed']),
                            ('validated_capability_evidence',{'debugging':[]}),('settlement_reliability',0.8)]:
            changed=copy.deepcopy(profiles);setattr(changed[router.SCOUT_DID],field,value)
            self.assertNotEqual(router._worker_evidence_snapshot(changed),baseline)
        changed=copy.deepcopy(profiles);profile=changed[router.SCOUT_DID]
        profile.activity_recency='later';profile.trust_evidence.activity_recency='LOW';profile.trust_evidence.components['activity_recency']=0.123
        self.assertEqual(router._worker_evidence_snapshot(changed),baseline)

    def test_interactions_validation_and_tclk_change_trigger_decisions(self):
        self.inbox();self.once()
        with sqlite3.connect(self.db) as conn:conn.execute('INSERT INTO interactions VALUES (?,?,?,?)',(router.SCOUT_DID,router.BENCH_DID,'reply',1))
        publish_snapshot(self.publication,self.db,snapshot_id='2')
        self.assertEqual(self.once()['status'],'READY_ACTIVE')
        tclk=self.root/'tclk.jsonl';record=scout_tclk_offer_record();tclk.write_text(json.dumps(record)+'\n')
        self.assertEqual(self.once(tclk_store=tclk)['status'],'READY_ACTIVE')
        record['operator_group']='changed';tclk.write_text(json.dumps(record)+'\n')
        self.assertEqual(self.once(tclk_store=tclk)['status'],'READY_ACTIVE')
        self.assertEqual(self.once(tclk_store=tclk)['status'],'READY_IDLE')

    def test_validation_material_change_is_not_suppressed(self):
        self.inbox();path=self.root/'validations.jsonl'
        attempt=router.ValidationAttempt(validation_id='VAL-001',target=router.ValidationTarget(router.SCOUT_DID,'software.debugging'),
            status='EVALUATED',created_at='2026-09-01T00:00:00Z',approved_at=None,capability_hypothesis='hypothesis',pre_validation_support_level='STRONG_SUPPORT',
            challenge=router.debugging_validation_challenge(),response=router.ValidationResponse(text='result',source_file='fixture',recorded_at='2026-09-01T00:00:00Z'),
            outcome=router.ValidationOutcome(result='PASS',score=90,criteria_passed=['diagnosis'],criteria_failed=[],safety_warnings=[],evaluated_at='2026-09-01T00:00:00Z'))
        record=router.validation_attempt_to_record(attempt);path.write_text(json.dumps(record)+'\n')
        self.assertEqual(self.once(validation_store=path)['verification_evidence_count'],1)
        self.assertEqual(self.once(validation_store=path)['status'],'READY_IDLE')
        record['target']['capability_id']='software.testing';path.write_text(json.dumps(record)+'\n')
        self.assertEqual(self.once(validation_store=path)['status'],'READY_ACTIVE')

    def test_cancellation_subprocess_acquisition_processing_sigterm_sigint(self):
        self.inbox()
        for stage in ('pointer','manifest','copy','database_read','query','routing'):
            for signum in (signal.SIGTERM,signal.SIGINT):
                with self.subTest(stage=stage,signum=signum):
                    code='''import os,sys,signal
from pathlib import Path
from unittest.mock import patch
import router,scout_projection as ss
root=Path(sys.argv[1]); stage=sys.argv[2]; signum=int(sys.argv[3])
if stage in ('pointer','manifest'): owner,name=ss.ProjectionReader,'_read_json_file'
elif stage=='database_read': owner,name=ss.os,'read'
elif stage=='copy': owner,name=ss.ProjectionReader,'_copy_database'
elif stage=='query': owner,name=ss.ProjectionReader,'_schema'
else: owner,name=router.Router,'route'
original=getattr(owner,name)
def cancel_then_call(*args,**kwargs):
 if stage=='manifest' and args[1]=='current.json':return original(*args,**kwargs)
 if stage=='database_read':
  result=original(*args,**kwargs)
  if result.startswith(b'SQLite format 3'):
   os.kill(os.getpid(),signum)
  return result
 os.kill(os.getpid(),signum)
 return original(*args,**kwargs)
with patch.object(owner,name,cancel_then_call):
 cycle=router.worker_once(root/'state',scout_snapshot_root=root/'publication')
raise SystemExit(1 if cycle['status']=='ERROR' else 0)
'''
                    result=subprocess.run([sys.executable,'-c',code,str(self.root),stage,str(int(signum))],
                                          capture_output=True,text=True,timeout=5,env={**os.environ,'TMPDIR':str(self.root)})
                    self.assertEqual(result.returncode,1,result.stderr)
                    self.assertFalse(router.worker_paths(self.state)['lock'].exists())
                    self.assertFalse(list(self.root.glob('flop-router-snapshot-*')))
                    self.assertFalse(router.worker_paths(self.state)['decisions'].exists())
                    self.assertEqual(router.worker_status(self.state)['last_error'],'WORKER_CANCELLED')
        self.assertEqual(self.once()['status'],'READY_ACTIVE')

    def test_signal_handlers_restored_and_nonfinite_intervals_rejected(self):
        before={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
        self.once()
        self.assertEqual(before,{sig:signal.getsignal(sig) for sig in before})
        for interval in (0,-1,float('inf'),float('nan')):
            with self.assertRaises(ValueError):router.run_worker_loop(self.state,interval,300,scout_snapshot_root=self.publication)

    def test_deduplication_across_actual_process_restart(self):
        self.inbox()
        self.assertEqual(self.once()['status'],'READY_ACTIVE')
        result=self.cli('--scout-snapshot-root',str(self.publication))
        self.assertEqual(result.returncode,0,result.stderr)
        cycle=json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(cycle['status'],'READY_IDLE')
        self.assertEqual(cycle['duplicate_decisions_suppressed'],1)
        self.assertEqual(len(router.worker_paths(self.state)['decisions'].read_text().splitlines()),1)

    def test_once_error_exit_and_stable_alias_reason(self):
        self.inbox({'task':[],'text':'SECRET_SENTINEL'})
        result=self.cli('--scout-snapshot-root',str(self.publication))
        self.assertEqual(result.returncode,1)
        cycle=json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(self.source(cycle,'task_inbox')['detail'],'INVALID_TASK_ALIAS')
        self.assertNotIn('SECRET_SENTINEL',result.stdout)
        self.inbox({'task':'one','text':'two'})
        self.assertEqual(self.source(self.once(),'task_inbox')['detail'],'CONFLICTING_TASK_ALIAS')

    def test_degraded_loop_retries_without_sleeping_full_interval_on_signal(self):
        self.publication.joinpath('current.json').unlink()
        observed=[]
        def wait(delay):
            observed.append(delay)
            signal.getsignal(signal.SIGINT)(signal.SIGINT,None)
        with patch.object(router.threading.Event,'wait',side_effect=wait):
            self.assertEqual(router.run_worker_loop(self.state,300,300,scout_snapshot_root=self.publication),0)
        self.assertEqual(observed,[300])
        self.assertFalse(router.worker_paths(self.state)['lock'].exists())

    def test_policy_v2_and_substantive_trust_preserved(self):
        self.assertEqual(router.WORKER_POLICY_VERSION,'flop-router-shadow/v4-v2-a1-stream')
        profiles=router.ProfileBuilder([obs(router.SCOUT_DID,1,'Debug an HTTP 400 response')]).build_all()
        base=router._worker_evidence_snapshot(profiles)
        changed=copy.deepcopy(profiles)
        changed[router.SCOUT_DID].trust_evidence.components['originality']=0.12345
        self.assertNotEqual(router._worker_evidence_snapshot(changed),base)

    def test_router_outputs_cannot_target_publication(self):
        before={p.name:p.read_bytes() for p in self.publication.iterdir()}
        with self.assertRaises(ValueError):self.once(task_inbox=self.publication/'tasks.jsonl')
        with self.assertRaises(ValueError):router.worker_once(self.publication,scout_snapshot_root=self.publication)
        alias=self.root/'publication-alias';alias.symlink_to(self.publication,target_is_directory=True)
        with self.assertRaises(ValueError):router.worker_once(self.publication,scout_snapshot_root=alias)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.publication.iterdir()})
