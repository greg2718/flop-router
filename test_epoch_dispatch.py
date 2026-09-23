"""Normal dispatch and worker integration, exclusively synthetic private roots."""
from datetime import datetime, timezone
import copy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import projection_routing
from scout_projection import ProjectionReader
from scout_snapshot import SnapshotError
from scout_epoch_store import WorkerEpochStore
from test_epoch_acceptance import setup_bundle, NOW, Crash
from epoch_evidence_test_support import publish
from epoch_v2_test_support import canonical


def setup_dispatch(tmp_path, enabled=True):
    args,t,m=setup_bundle(tmp_path/'fixture',cumulative=True)
    state=tmp_path/'normal'; worker=state/'worker'; worker.mkdir(parents=True,mode=0o700)
    cache=worker/'v2-copies';cache.mkdir(mode=0o700)
    before=json.loads((args[0]/'state.json').read_bytes())
    previous=before['last_accepted_projection_v2']
    target=cache/(previous['database_hash']+'.sqlite')
    shutil.copyfile(previous['cache_path'],target)
    previous['cache_path']=str(target)
    before['task_inbox_initialized']=True
    (worker/'worker_state.json').write_bytes(canonical(before))
    (worker/'tasks.jsonl').write_bytes(b'')
    reader=ProjectionReader(args[1],cache,timeout=60,enable_epoch_v2=enabled,
        epoch_v2_state_dir=worker,epoch_v2_bridge_root=args[2],epoch_v2_archive_root=args[3])
    return reader,state,args,t,m


def read(reader):
    return reader.read(lambda conn:projection_routing.build(conn,reader),now=NOW)


def checkpoint(reader):
    path=reader.epoch_v2_state_dir/'worker_state.json'
    raw=path.read_bytes();state=json.loads(raw);cache=Path(state['last_accepted_projection_v2']['cache_path'])
    return raw,cache.read_bytes()


def test_disabled_real_dispatch_no_candidate_mutations(tmp_path):
    reader,_,_,_,_=setup_dispatch(tmp_path,False)
    before=checkpoint(reader);files=set(reader.epoch_v2_state_dir.rglob('*'))
    with pytest.raises(SnapshotError,match='^EPOCH_V2_DISABLED$'):
        reader.read(lambda conn:pytest.fail('disabled profiles'),now=NOW)
    assert checkpoint(reader)==before
    assert set(reader.epoch_v2_state_dir.rglob('*'))==files
    reader.close()


def test_enabled_then_disabled_reads_only_accepted(tmp_path):
    reader,_,args,_,_=setup_dispatch(tmp_path)
    profiles,meta=read(reader)
    assert profiles and meta['database_content_id']=='2'
    assert meta['epoch_status']=='EPOCH_V2_ACCEPTED'
    before=checkpoint(reader)
    # No producer acquisition is needed in accepted-only mode.
    shutil.rmtree(args[1]);reader.close();reader.enable_epoch_v2=False
    profiles,meta=read(reader)
    assert profiles and meta['epoch_status']=='EPOCH_V2_ACCEPTED_ONLY'
    assert checkpoint(reader)==before
    reader.close()


@pytest.mark.parametrize('kind',['missing','symlink','inside-state','bridge-overlap'])
def test_bad_trust_root(tmp_path,kind):
    reader,_,args,_,_=setup_dispatch(tmp_path)
    if kind=='missing': reader.epoch_v2_archive_root=None
    elif kind=='symlink':
        path=tmp_path/'link';path.symlink_to(args[3],target_is_directory=True);reader.epoch_v2_archive_root=path
    elif kind=='inside-state': reader.epoch_v2_archive_root=reader.epoch_v2_state_dir
    else: reader.epoch_v2_archive_root=reader.epoch_v2_bridge_root
    before=checkpoint(reader)
    with pytest.raises(SnapshotError,match='EPOCH_TRUST_ROOT'):read(reader)
    assert checkpoint(reader)==before
    reader.close()


def test_disk_preflight_precedes_profiles(tmp_path,monkeypatch):
    import scout_epoch_dispatch as dispatch
    reader,_,_,_,_=setup_dispatch(tmp_path)
    before=checkpoint(reader)
    monkeypatch.setattr(dispatch.shutil,'disk_usage',lambda path:SimpleNamespace(free=1))
    with pytest.raises(SnapshotError,match='EPOCH_DISK_SPACE'):read(reader)
    assert checkpoint(reader)==before
    reader.close()


def test_single_writer_rejected(tmp_path):
    reader,_,_,_,_=setup_dispatch(tmp_path)
    before=checkpoint(reader)
    with WorkerEpochStore(reader.epoch_v2_state_dir).locked():
        with pytest.raises(SnapshotError,match='EPOCH_WRITER_BUSY'):read(reader)
    assert checkpoint(reader)==before
    reader.close()


@pytest.mark.parametrize('boundary,content',[('commit:before_rename','0'),('commit:after_rename','2')])
def test_startup_recovers_before_acquisition(tmp_path,monkeypatch,boundary,content):
    reader,_,args,_,_=setup_dispatch(tmp_path)
    original=WorkerEpochStore.rename
    def interrupt(self,source,target,label):
        if label+':before_rename'==boundary:raise Crash()
        original(self,source,target,label)
        if label+':after_rename'==boundary:raise Crash()
    monkeypatch.setattr(WorkerEpochStore,'rename',interrupt)
    before=checkpoint(reader)
    with pytest.raises(Crash):read(reader)
    monkeypatch.setattr(WorkerEpochStore,'rename',original)
    reader.close(); reader.enable_epoch_v2=False
    if content=='0':
        with pytest.raises(SnapshotError,match='EPOCH_V2_DISABLED'):read(reader)
        assert checkpoint(reader)==before
    else:
        profiles,meta=read(reader);assert profiles and meta['database_content_id']=='2'
    assert not (reader.epoch_v2_state_dir/'journal.json').exists()
    reader.close()


def test_profile_failure_and_heartbeat_preserve_state(tmp_path,monkeypatch):
    reader,_,args,_,m=setup_dispatch(tmp_path)
    before=checkpoint(reader)
    def fail(*a,**kw):raise ValueError('hostile profile text should not be reported')
    monkeypatch.setattr(projection_routing,'build',fail)
    with pytest.raises(SnapshotError,match='^EPOCH_INPUT_INVALID$'):read(reader)
    assert checkpoint(reader)==before
    m['publication_kind']='HEARTBEAT';publish(args[1],m,args[1]/'active.sqlite')
    with pytest.raises(SnapshotError,match='EPOCH_PUBLICATION_KIND'):read(reader)
    assert checkpoint(reader)==before
    reader.close()


def test_a1_dispatch_parity(tmp_path):
    reader,_,args,_,_=setup_dispatch(tmp_path,False)
    reader.root=args[2]
    previous=json.loads(checkpoint(reader)[0])['last_accepted_projection_v2']
    normal=ProjectionReader(args[2],reader.cache_dir,timeout=60)
    try:
        _,expected=normal.read(lambda conn:None,previous=previous,now=NOW,allow_stale=True)
        _,actual=reader.read(lambda conn:None,previous=previous,now=NOW,allow_stale=True)
        for key in ('manifest_hash','database_hash','routing_input_hash','qualification_history'):
            assert actual[key]==expected[key]
    finally:normal.close();reader.close()


def test_worker_configuration_is_explicit_and_no_environment_fallback(tmp_path,monkeypatch):
    import router
    monkeypatch.setenv('ENABLE_SCOUT_EPOCH_V2','1')
    sources=router.worker_sources(tmp_path)
    assert sources[0]['enable_scout_epoch_v2'] is False
    sources=router.worker_sources(tmp_path,enable_scout_epoch_v2=True,epoch_archive_root=tmp_path/'archive',epoch_bridge_root=tmp_path/'bridge')
    assert sources[0]['enable_scout_epoch_v2'] is True
    assert sources[0]['epoch_archive_root']==str(tmp_path/'archive')


def test_worker_persistence_does_not_rewrite_acceptance_record(tmp_path,monkeypatch):
    import router
    reader,state,args,_,_=setup_dispatch(tmp_path)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return NOW
    monkeypatch.setattr(router,'datetime',Clock)
    sources=router.worker_sources(state,scout_snapshot_root=args[1],enable_scout_epoch_v2=True,
        epoch_archive_root=args[3],epoch_bridge_root=args[2],snapshot_timeout=60)
    cycle=router.run_worker_cycle(state,sources=sources)
    assert cycle['status']=='READY_IDLE'
    store=WorkerEpochStore(reader.epoch_v2_state_dir)
    with store.locked(): _,accepted=store.recover()
    assert accepted['last_accepted_projection_v2']['database_content_id']=='2'
    sources[0]['enable_scout_epoch_v2']=False
    cycle=router.run_worker_cycle(state,sources=sources)
    assert cycle['status']=='READY_IDLE'
    with store.locked(): store.recover()
    reader.close()
