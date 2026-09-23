"""Disposable acceptance and durable commit crash-boundary tests."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import pytest

from epoch_evidence_test_support import bundle, publication_manifest, publish, WHEN
from epoch_v2_test_support import canonical, sha
from scout_epoch_acceptance import accept_disposable
from scout_epoch_store import DisposableEpochStore
from scout_projection import ProjectionReader
from scout_snapshot import SnapshotError

NOW=datetime(2026,9,22,tzinfo=timezone.utc)


def setup_bundle(tmp_path, cumulative=False):
    root=tmp_path/'input'
    t,p,kw=bundle(root,publication=True,cumulative=cumulative)
    manifest=publication_manifest(root/'active.sqlite',2,WHEN)
    manifest.update(contract_revision='A1-EPOCH-V2',snapshot_id=2,database_content_id=2,database='active.sqlite')
    manifest['source_checkpoint']['committed_event_id']=8
    raw=canonical(t); (root/'transition.json').write_bytes(raw)
    manifest['epoch_transition']={'schema':t['schema'],'locator':'transition.json','sha256':sha(raw),
        'size_bytes':len(raw),'transition_sha256':t['commitments']['transition_sha256']}
    publish(root,manifest,root/'active.sqlite')
    store=tmp_path/'store'; store.mkdir(mode=0o700)
    cache=store/'initial'; cache.mkdir(mode=0o700)
    reader=ProjectionReader(root/('accepted-publication' if cumulative else 'bridge-publication'),cache)
    try:
        _,previous=reader.read(lambda conn:None,now=NOW,allow_stale=True)
    finally: reader.close()
    (store/'state.json').write_bytes(canonical({'last_accepted_projection_v2':previous}))
    (store/'disposable.json').write_bytes(canonical({'schema':'router-disposable-epoch-store/v1'}))
    args=(store,root,root/'bridge-publication',root/'archive')
    return args,t,manifest


def test_disabled_has_no_io():
    with pytest.raises(SnapshotError,match='EPOCH_V2_DISABLED'):
        accept_disposable('/missing','/missing','/missing','/missing')


def test_success(tmp_path):
    args,t,m=setup_bundle(tmp_path)
    before=(args[0]/'state.json').read_bytes()
    old=Path(json.loads(before)['last_accepted_projection_v2']['cache_path']); original=old.read_bytes()
    profiles,accepted,summary=accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert accepted['database_content_id']=='2'
    assert type(profiles) is dict and profiles
    assert profiles['did:key:z6MkSynthetic'].identity.did == 'did:key:z6MkSynthetic'
    assert old.read_bytes()==original
    store=DisposableEpochStore(args[0])
    with store.locked():
        _,state=store.recover()
        assert state['last_accepted_projection_v2']['database_content_id']=='2'
        assert store.recover()[1]==state
    assert not (args[0]/'journal.json').exists()
    assert 'token' not in (args[0]/'state.json').read_text()


def test_exact_bridge_required(tmp_path):
    args,t,m=setup_bundle(tmp_path)
    before=(args[0]/'state.json').read_bytes()
    (args[2]/'current.json').unlink()
    with pytest.raises(SnapshotError,match='EPOCH_EXACT_BRIDGE_POINTER_UNAVAILABLE'):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert (args[0]/'state.json').read_bytes()==before

WRITE_LABELS=('cache','accepted','commitments','journal','state')
BOUNDARIES=[f'{label}:{point}' for label in WRITE_LABELS for point in
            ('before_write','after_write','before_fsync','after_fsync')]
BOUNDARIES += [f'{label}:{point}' for label in ('journal','generation','commit')
               for point in ('before_rename','after_rename')]
BOUNDARIES += [f'{label}:{point}' for label in
               ('stage','journal_directory','generation_directory','commit_directory')
               for point in ('before_fsync','after_fsync')]


class Crash(BaseException):
    pass


@pytest.mark.parametrize('boundary',BOUNDARIES)
def test_restart_at_every_commit_boundary(tmp_path,boundary):
    args,t,m=setup_bundle(tmp_path)
    initial=(args[0]/'state.json').read_bytes()
    old=Path(json.loads(initial)['last_accepted_projection_v2']['cache_path'])
    original=old.read_bytes()
    visited=[]
    def fail(label):
        visited.append(label)
        if label==boundary: raise Crash(label)
    with pytest.raises(Crash):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW,fault=fail)
    assert boundary in visited
    committed=boundary in ('commit:after_rename','commit_directory:before_fsync','commit_directory:after_fsync')
    if not committed: assert (args[0]/'state.json').read_bytes()==initial
    assert old.read_bytes()==original
    store=DisposableEpochStore(args[0])
    with store.locked():
        _,state=store.recover()
        assert state['last_accepted_projection_v2']['database_content_id']==('2' if committed else '1')
        assert store.recover()[1]==state
    assert not list(args[0].glob('.stage-*'))
    assert not (args[0]/'journal.json').exists()
    if not committed:
        assert (args[0]/'state.json').read_bytes()==initial
        assert not list(args[0].glob('gen-*'))
    assert old.read_bytes()==original


@pytest.mark.parametrize('kind', ['policy','row-count','watermark','coverage','expiry','checkpoint',
                                  'time','old-publication','obsolete','plan','artifact','archive',
                                  'bridge-manifest','bridge-artifact','anchor','reconstruction'])
def test_invalid_input_preserves_accepted_bytes(tmp_path,kind):
    args,t,m=setup_bundle(tmp_path)
    initial=(args[0]/'state.json').read_bytes()
    old=Path(json.loads(initial)['last_accepted_projection_v2']['cache_path']); original=old.read_bytes()
    if kind=='policy': m['selection_policy_sha256']='0'*64
    elif kind=='row-count': m['row_counts']['messages']+=1
    elif kind=='watermark': m['watermarks'][0]['record_count']+=1
    elif kind=='coverage': m['coverage_history'][0]['max_ever_projected_seq']+=1
    elif kind=='expiry': m['next_expiry_at']='2026-09-01T00:00:00Z'
    elif kind=='checkpoint': m['source_checkpoint']['committed_event_id']='9'
    elif kind=='time': m['content_created_at']='2026-09-23T00:00:00Z'
    elif kind=='old-publication': m['snapshot_id']=1
    elif kind=='obsolete': m['epoch_rollover']={}
    elif kind in ('plan','artifact','archive'):
        path={'plan':args[1]/'plan.json','artifact':args[1]/'active.sqlite','archive':args[3]/'manifest.json'}[kind]
        raw=path.read_bytes(); path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
    elif kind=='bridge-manifest':
        p=json.loads((args[2]/'current.json').read_bytes());p['manifest_sha256']='0'*64
        (args[2]/'current.json').write_bytes(canonical(p))
    elif kind=='bridge-artifact':
        path=next(args[2].glob('*.sqlite'));raw=path.read_bytes();path.write_bytes(raw[:-1]+b'x')
    elif kind in ('anchor','reconstruction'):
        from epoch_v2_test_support import seal
        if kind=='anchor': t['accepted_anchor']['manifest_sha256']='0'*64
        else: t['retained_floor_commitment']['coverage_witnesses_count']+=1
        seal(t);raw=canonical(t);(args[1]/'transition.json').write_bytes(raw)
        m['epoch_transition'].update(sha256=sha(raw),size_bytes=len(raw),transition_sha256=t['commitments']['transition_sha256'])
    publish(args[1],m,args[1]/'active.sqlite')
    with pytest.raises((SnapshotError,ValueError)):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert (args[0]/'state.json').read_bytes()==initial
    assert old.read_bytes()==original
    assert not list(args[0].glob('gen-*'))


def test_profile_failure_before_staging(tmp_path,monkeypatch):
    import projection_routing
    args,_,_=setup_bundle(tmp_path)
    initial=(args[0]/'state.json').read_bytes()
    def reject(*a,**kw): raise ValueError('profile failure')
    monkeypatch.setattr(projection_routing,'build',reject)
    with pytest.raises(ValueError,match='profile failure'):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert (args[0]/'state.json').read_bytes()==initial
    assert not list(args[0].glob('gen-*'))


@pytest.mark.parametrize('file',['cache','commitments','accepted'])
def test_restart_rejects_corrupt_committed_generation(tmp_path,file):
    args,_,_=setup_bundle(tmp_path)
    accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    generation=next(args[0].glob('gen-*'))
    path=next(generation.glob('*.sqlite')) if file=='cache' else generation/(file+'.json')
    path.write_bytes(b'corrupt')
    store=DisposableEpochStore(args[0])
    with store.locked(),pytest.raises(SnapshotError): store.recover()
    assert (args[0]/'journal.json').exists()


def test_store_lock_and_marker_are_required(tmp_path):
    args,_,_=setup_bundle(tmp_path)
    store=DisposableEpochStore(args[0])
    with store.locked(),pytest.raises(BlockingIOError):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    (args[0]/'disposable.json').write_bytes(b'{}')
    with pytest.raises(SnapshotError):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)


def test_cumulative_anchor_bridge_active(tmp_path):
    args,t,m=setup_bundle(tmp_path,cumulative=True)
    assert t['accepted_anchor']['content_id']==0
    assert t['bridge_predecessor']['content_id']==1
    profiles,accepted,summary=accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert accepted['database_content_id']=='2'


def test_recovery_rejects_unknown_state_instead_of_guessing(tmp_path):
    args,_,_=setup_bundle(tmp_path)
    def crash(boundary):
        if boundary=='commit:before_rename': raise Crash()
    with pytest.raises(Crash): accept_disposable(*args,enable_epoch_v2=True,now=NOW,fault=crash)
    (args[0]/'state.json').write_bytes(b'{}')
    store=DisposableEpochStore(args[0])
    with store.locked(),pytest.raises(SnapshotError,match='EPOCH_STORE_AMBIGUOUS_COMMIT'):
        store.recover()


def test_committed_proof_is_checked_after_journal_cleanup(tmp_path):
    args,_,_=setup_bundle(tmp_path)
    accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    store=DisposableEpochStore(args[0])
    with store.locked(): store.recover()
    next(args[0].glob('gen-*/commitments.json')).write_bytes(b'{}')
    with store.locked(),pytest.raises(SnapshotError,match='EPOCH_STORE_RECOVERY_HASH'):
        store.recover()


def test_inputs_unchanged_and_no_serialized_session(tmp_path):
    args,_,_=setup_bundle(tmp_path,cumulative=True)
    def fingerprints():
        return {str(p): (sha(p.read_bytes()),p.stat().st_ino,p.stat().st_mtime_ns)
                for p in args[1].rglob('*') if p.is_file()}
    original=fingerprints()
    _,accepted,_=accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert fingerprints()==original
    generation=Path(accepted['cache_path']).parent
    for name in ('accepted.json','commitments.json'):
        raw=(generation/name).read_text()
        assert 'session' not in raw and 'token' not in raw and 'raw_text' not in raw


@pytest.mark.parametrize('boundary',['state:before_write','state:before_fsync','commit:before_rename'])
def test_os_errors_leave_prior_state_byte_identical(tmp_path,boundary):
    args,_,_=setup_bundle(tmp_path)
    original=(args[0]/'state.json').read_bytes()
    def fail(label):
        if label==boundary: raise OSError('injected disk failure')
    with pytest.raises(OSError): accept_disposable(*args,enable_epoch_v2=True,now=NOW,fault=fail)
    assert (args[0]/'state.json').read_bytes()==original
    store=DisposableEpochStore(args[0])
    with store.locked(): store.recover()
    assert (args[0]/'state.json').read_bytes()==original


def test_held_input_change_during_profiles_prevents_commit(tmp_path,monkeypatch):
    import projection_routing
    args,_,_=setup_bundle(tmp_path)
    original=(args[0]/'state.json').read_bytes()
    build=projection_routing.build
    def mutate(*a,**kw):
        result=build(*a,**kw)
        path=args[1]/'plan.json'; path.write_bytes(path.read_bytes()+b' ')
        return result
    monkeypatch.setattr(projection_routing,'build',mutate)
    with pytest.raises(ValueError,match='EVIDENCE_INPUT_CHANGED'):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert (args[0]/'state.json').read_bytes()==original


def test_archive_receipt_is_live_before_profiles(tmp_path,monkeypatch):
    import scout_epoch_archive_validator as archive
    args,_,_=setup_bundle(tmp_path)
    original=archive.VerifiedEpochArchive
    def expired(session,token,*a):
        session.active=False
        return original(session,token,*a)
    monkeypatch.setattr(archive,'VerifiedEpochArchive',expired)
    before=(args[0]/'state.json').read_bytes()
    with pytest.raises(SnapshotError,match='EPOCH_BRIDGE_RECEIPT_INVALID'):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert (args[0]/'state.json').read_bytes()==before


def test_profile_materialization_failure_is_precommit(tmp_path,monkeypatch):
    import projection_routing
    args,_,_=setup_bundle(tmp_path)
    before=(args[0]/'state.json').read_bytes()
    def fail(self):
        raise ValueError('lazy profile failure')
        yield
    monkeypatch.setattr(projection_routing.Profiles,'items',fail)
    with pytest.raises(ValueError,match='lazy profile failure'):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert (args[0]/'state.json').read_bytes()==before
    assert not list(args[0].glob('gen-*'))


@pytest.mark.parametrize('member',['plan.json','active.sqlite','archive/manifest.json'])
def test_trust_root_symlink_rejected(tmp_path,member):
    args,_,_=setup_bundle(tmp_path)
    path=args[1]/member; saved=tmp_path/'saved';path.rename(saved);path.symlink_to(saved)
    before=(args[0]/'state.json').read_bytes()
    with pytest.raises((OSError,SnapshotError,ValueError)):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert (args[0]/'state.json').read_bytes()==before


@pytest.mark.parametrize('kind',['manifest','artifact'])
def test_precise_missing_bridge_contract_input(tmp_path,kind):
    args,_,_=setup_bundle(tmp_path)
    pointer=json.loads((args[2]/'current.json').read_bytes())
    manifest=json.loads((args[2]/pointer['manifest']).read_bytes())
    path=args[2]/(pointer['manifest'] if kind=='manifest' else manifest['database'])
    path.unlink()
    before=(args[0]/'state.json').read_bytes()
    with pytest.raises(SnapshotError,match='EPOCH_EXACT_BRIDGE_'+kind.upper()+'_UNAVAILABLE'):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert (args[0]/'state.json').read_bytes()==before


def test_oversized_candidate_state_cannot_commit(tmp_path):
    from scout_epoch_store import MAX_STATE
    args,_,_=setup_bundle(tmp_path)
    store=DisposableEpochStore(args[0])
    with store.locked():
        before,state=store.recover()
        artifact=Path(state['last_accepted_projection_v2']['cache_path'])
        state['oversized']='x'*MAX_STATE
        with pytest.raises(SnapshotError,match='EPOCH_STORE_STATE_BOUNDS'):
            store.commit(before,state,artifact,{})
        assert (args[0]/'state.json').read_bytes()==before
        store.recover()


@pytest.mark.parametrize('bad',["8",True,8.0,None,9])
def test_v2_cut_is_exact_normalized_integer(tmp_path,bad):
    args,t,m=setup_bundle(tmp_path)
    before=(args[0]/'state.json').read_bytes()
    m['source_checkpoint']['committed_event_id']=bad
    publish(args[1],m,args[1]/'active.sqlite')
    with pytest.raises((SnapshotError,ValueError)):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert (args[0]/'state.json').read_bytes()==before
