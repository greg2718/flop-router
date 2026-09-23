import copy
from dataclasses import FrozenInstanceError
import pickle
from pathlib import Path

import pytest

import scout_epoch_evidence as e
from epoch_evidence_test_support import bundle, refresh
from epoch_v2_test_support import seal, sha, canonical


def run(value):
    t, _, kwargs = value
    return e.reconstruct(t, **kwargs)


def test_valid_reconstruction_is_redacted_immutable_and_does_not_mutate(tmp_path):
    value=bundle(tmp_path)
    files={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}
    result=run(value)
    counts=dict(result.counts)
    assert counts == {'eligible':8,'selected':6,'omitted':2,'mandatory_proof_closure':4,
        'durable_qualification_history':1,'coverage_witnesses':1,'permanent_pinned_evidence':2,'omitted_history':2}
    for name in e.v2.SET_DOMAINS:
        assert dict(result.commitments)[name] == value[0]['retained_floor_commitment'][name+'_sha256']
    assert len(result.descriptor_identities)==7
    with pytest.raises(FrozenInstanceError): result.counts=()
    with pytest.raises(TypeError): pickle.dumps(result)
    assert 'synthetic' not in repr(result) and 'raw_text' not in repr(result)
    assert files=={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('name', list(e.v2.SET_DOMAINS))
@pytest.mark.parametrize('kind', ['count','sha256'])
def test_each_compact_count_and_hash_is_reconstructed(tmp_path,name,kind):
    t,p,kwargs=bundle(tmp_path)
    key=name+'_'+kind
    t['retained_floor_commitment'][key] = 99 if kind=='count' else '0'*64
    seal(t)
    p['retained_floor_commitment_sha256']=t['retained_floor_commitment']['retained_floor_commitment_sha256']
    p['omission_commitment_sha256']=t['retained_floor_commitment']['omitted_history_sha256']
    t,p,kwargs=refresh(tmp_path,t,p)
    with pytest.raises(e.EvidenceError) as exc:e.reconstruct(t,**kwargs)
    assert exc.value.code=='EVIDENCE_'+('COUNT_' if kind=='count' else 'HASH_')+name.upper()
    assert exc.value.summary is not None


@pytest.mark.parametrize('damage,expected', [
 ('selected-absent','EVIDENCE_SELECTED_SET'),('omitted-present','EVIDENCE_SELECTED_SET'),
 ('archive-provenance','EVIDENCE_ARCHIVE_PROVENANCE'),('recovered-hash','EVIDENCE_RECOVERED_HASH'),
 ('recovered-event','EVIDENCE_RECOVERED_EVENT'),('selected-hash','EVIDENCE_SELECTED_PROVENANCE'),
 ('selected-event','EVIDENCE_SELECTED_PROVENANCE'),('qualification','EVIDENCE_DURABLE_QUALIFICATIONS'),
 ('coverage','EVIDENCE_COVERAGE_HISTORY'),('pin','EVIDENCE_SELECTED_MEMBERSHIP'),
 ('permanent','EVIDENCE_SELECTED_MEMBERSHIP'),('lifecycle','EVIDENCE_SELECTED_MEMBERSHIP'),
 ('source-duplicate','EVIDENCE_DUPLICATE'),('lifecycle-dependency','EVIDENCE_INVALID'),('lifecycle-link','EVIDENCE_DEPENDENCY')])
def test_rehashed_evidence_mutations_fail_closed(tmp_path,damage,expected):
    value=bundle(tmp_path,damage)
    with pytest.raises(e.EvidenceError) as exc: run(value)
    assert exc.value.code==expected


@pytest.mark.parametrize('damage,expected', [
 ('overlap','EVIDENCE_PLAN_UNION'),('gap','EVIDENCE_PLAN_UNION'),('duplicate','EVIDENCE_PLAN_ORDER'),
 ('extra','EVIDENCE_PLAN_UNION'),('order','EVIDENCE_PLAN_ORDER'),('reason','EVIDENCE_CLASSIFICATION'),
 ('hash','EVIDENCE_PLAN_RECOVERED'),('event','EVIDENCE_PLAN_RECOVERED'),
 ('classification','EVIDENCE_CLASSIFICATION'),('uncommitted','EVIDENCE_PLAN_RECORD')])
def test_rehashed_plan_mutations_fail_closed(tmp_path,damage,expected):
    t,p,kwargs=bundle(tmp_path)
    if damage=='overlap':p['omitted'].append(copy.deepcopy(p['selected'][0]));p['omitted'].sort(key=lambda r:r['raw_record_id'])
    elif damage=='gap':p['omitted'].pop()
    elif damage=='duplicate':p['selected'].append(copy.deepcopy(p['selected'][-1]))
    elif damage=='extra':
        row=copy.deepcopy(p['selected'][0]);row.update(projection_row_id='sm1:'+'0'*64,raw_record_id='0'*64);p['selected'].insert(0,row)
    elif damage=='order':p['selected'].reverse()
    elif damage in ('reason','classification'):p['selected'][0]['reasons']=['producer_says_mandatory'] if damage=='reason' else ['deterministic_optional_omission']
    elif damage=='hash':p['omitted'][0]['raw_text_sha256']='0'*64
    elif damage=='event':p['omitted'][0]['scout_event_id']='99'
    else:p['selected'][0]['raw_text']='not allowed'
    value=refresh(tmp_path,t,p)
    with pytest.raises(e.EvidenceError) as exc:run(value)
    assert exc.value.code==expected


def test_wrong_descriptor_and_symlink_rejected(tmp_path):
    value=bundle(tmp_path/'data');t,p,kwargs=value
    path=kwargs['plan_path'];path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(e.EvidenceError,match='EVIDENCE_INPUT_SIZE'):run(value)
    path.write_bytes(canonical(p))
    alias=tmp_path/'alias';alias.symlink_to(path)
    with pytest.raises(e.EvidenceError,match='EVIDENCE_INVALID'):e.reconstruct(t,**dict(kwargs,plan_path=alias))


def test_plan_summary_bindings_are_not_ignored_after_evidence_matches(tmp_path):
    t,p,kwargs=bundle(tmp_path)
    p['retained_floor_commitment_sha256']='0'*64
    value=refresh(tmp_path,t,p)
    with pytest.raises(e.EvidenceError) as exc:run(value)
    assert exc.value.code=='EPOCH_PLAN_BINDING'
    assert dict(exc.value.summary.counts)['eligible']==8


def test_reader_paths_are_not_used(tmp_path,monkeypatch):
    value=bundle(tmp_path)
    def forbidden(*args,**kwargs):pytest.fail('acceptance/profile/cache path invoked')
    monkeypatch.setattr(e.ProjectionReader,'read',forbidden)
    monkeypatch.setattr(e.ProjectionReader,'_copy_database',forbidden)
    assert dict(run(value).counts)['eligible']==8


@pytest.mark.parametrize('damage,expected', [('counts','EPOCH_PLAN_COUNTS'),('floor','EVIDENCE_RETAINED_FLOOR'),
                                            ('capacity','EVIDENCE_CAPACITY'),('plan-logical','EPOCH_PLAN_COMMITMENT')])
def test_additional_plan_and_summary_invariants(tmp_path,damage,expected):
    t,p,kwargs=bundle(tmp_path)
    if damage=='counts':p['counts']['eligible']=99
    elif damage=='floor':
        t['retained_floor_commitment']['entries'][0]['retained_floor']=99
        seal(t);p['retained_floor_commitment_sha256']=t['retained_floor_commitment']['retained_floor_commitment_sha256']
    elif damage=='capacity':t['active_epoch']['mandatory_closure_count']=3
    t,p,kwargs=refresh(tmp_path,t,p)
    if damage=='plan-logical':
        p['plan_commitment_sha256']='0'*64
        raw=canonical(p);kwargs['plan_path'].write_bytes(raw)
        t['active_set_plan'].update(sha256=sha(raw),size_bytes=len(raw),plan_commitment_sha256='0'*64)
        seal(t)
    with pytest.raises(e.EvidenceError) as exc:e.reconstruct(t,**kwargs)
    assert exc.value.code==expected


def test_input_change_during_reconstruction_rejected(tmp_path,monkeypatch):
    value=bundle(tmp_path)
    original=e.HeldInputs.unchanged
    def mutate(held):
        path=value[2]['plan_path'];raw=path.read_bytes();path.write_bytes(raw[:-1]+b' ')
        original(held)
    monkeypatch.setattr(e.HeldInputs,'unchanged',mutate)
    with pytest.raises(e.EvidenceError,match='EVIDENCE_INPUT_CHANGED'):run(value)


def test_input_size_bound_before_read(tmp_path,monkeypatch):
    value=bundle(tmp_path)
    monkeypatch.setattr(e,'MAX_SQLITE_BYTES',1)
    with pytest.raises(e.EvidenceError,match='EVIDENCE_INPUT_BOUNDS'):run(value)


def test_same_size_descriptor_mismatch(tmp_path):
    value=bundle(tmp_path);path=value[2]['plan_path'];raw=path.read_bytes()
    path.write_bytes(b' '+raw[1:])
    with pytest.raises(e.EvidenceError,match='EVIDENCE_INPUT_HASH'):run(value)
