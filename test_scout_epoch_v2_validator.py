import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scout_epoch_v2_validator as v
import scout_projection as projection
from scout_snapshot import SnapshotError

FIXTURE = Path(__file__).parent / 'docs/fixtures/scout-router-epoch-rollover-v2-conformance.json'
FIXTURE_SHA256 = '7d9a99af81370b2fcea69b85dc3b977d733a11cb8bdabc92e121473fce76f217'

def h(c): return c * 64

def model():
    pre={'publication_id':900,'content_id':800,'manifest_sha256':h('a'),'artifact_sha256':h('b'),'artifact_size_bytes':42,'epoch_id':'v1:predecessor','epoch_number':0,'source_cut':{'source_id':'scout-source','epoch':'source-epoch','committed_event_id':7,'cut_evidence_sha256':h('c')},'accepted_state_hash':h('d')}
    archive={'schema':'flop-scout-epoch-archive/v1','archive_id':'ea2:archive','artifact_sha256':h('e'),'size_bytes':42,'database_schema_version':'scout-observer/v1','locator':'archives/epoch-0.sqlite','previous_epoch_id':'v1:predecessor','previous_manifest_sha256':h('a'),'preservation':'IMMUTABLE_RETAINED'}
    archive['archive_commitment_sha256']=v.commitment('archive-descriptor',archive)
    floors={'entries':[{'room':'room-a','generation':'1','domain':'messages','retained_floor':4,'omitted_ranges':[[1,3]]}],'selection_policy_version':'epoch-v2-policy/1','mandatory_proof_closure':['proof-a'],'durable_qualification_history':['qualification-a'],'coverage_witnesses':['coverage-a'],'permanent_pinned_evidence':['pin-a'],'omitted_history':['row-a']}
    for body,field,domain in (('mandatory_proof_closure','mandatory_proof_closure_sha256','mandatory-closure'),('durable_qualification_history','durable_qualification_history_sha256','durable-qualification-history'),('coverage_witnesses','coverage_witnesses_sha256','coverage-witnesses'),('permanent_pinned_evidence','permanent_pinned_evidence_sha256','permanent-pinned-evidence'),('omitted_history','omitted_history_sha256','omitted-history')): floors[field]=v.commitment(domain,floors[body])
    floors['retained_floor_commitment_sha256']=v.commitment('retained-floor-declaration',floors)
    value={'schema':v.SCHEMA,'contract_revision':v.REVISION,'epoch_number':1,'epoch_id':'se2:epoch-one','created_at':'2026-01-01T00:00:00Z','source_binding':{'source_id':'scout-source','epoch':'source-epoch','descriptor_sha256':h('f')},'source_cut':{'source_id':'scout-source','epoch':'source-epoch','committed_event_id':8,'cut_evidence_sha256':h('0')},'predecessor':pre,'archive':archive,'retained_floor_commitment':floors,'active_epoch':{'target':40000,'headroom':9000,'reserve':1000,'hard_max':50000,'mandatory_closure_count':12000}}
    value['commitments']={'predecessor_sha256':v.commitment('predecessor',pre),'archive_descriptor_sha256':v.commitment('archive-descriptor',{k:x for k,x in archive.items() if k!='archive_commitment_sha256'}),'retained_floor_declaration_sha256':v.commitment('retained-floor-declaration',{k:x for k,x in floors.items() if k!='retained_floor_commitment_sha256'}),'mandatory_closure_sha256':floors['mandatory_proof_closure_sha256'],'durable_qualification_history_sha256':floors['durable_qualification_history_sha256'],'coverage_witnesses_sha256':floors['coverage_witnesses_sha256'],'permanent_pinned_evidence_sha256':floors['permanent_pinned_evidence_sha256']}
    value['commitments']['transition_sha256']=v.commitment('complete-transition',copy.deepcopy(value))
    return value

def error(call):
    with pytest.raises(v.EpochV2Error) as caught: call()
    return caught.value.code

def test_frozen_fixture_hash_and_shared_cases():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest()==FIXTURE_SHA256
    data=json.loads(FIXTURE.read_text())
    assert [x['expect'] for x in data['slice1_cases']] == ['PASS','EPOCH_NUMBER','EPOCH_FIRST_SOURCE_IDENTITY','EPOCH_PREDECESSOR','EPOCH_SOURCE_CUT','EPOCH_RETAINED_FLOOR','EPOCH_CAPACITY']

def test_valid_model_and_known_canonical_parity():
    value=model(); assert v.validate_transition(value,copy.deepcopy(value['predecessor']),True)['epoch_number']==1
    assert v.canonical_json({'b':1,'a':[True,None]}) == b'{"a":[true,null],"b":1}'
    assert v.commitment('predecessor',{'x':1}) == 'c09cb61457afcb028c5cd77cb0c13a3b761e52acf7cd60f2c1f1eae85fcaaa04'

def test_later_shared_transition_and_self_commitment_view():
    value=model(); prior=copy.deepcopy(value['predecessor'])
    prior.update(publication_id=901,content_id=801,manifest_sha256=h('7'),artifact_sha256=h('8'),epoch_id='se2:epoch-prior',epoch_number=1)
    prior['source_cut']['committed_event_id']=8
    value['epoch_number']=2; value['predecessor']=prior
    value['archive']['previous_epoch_id']=prior['epoch_id']; value['archive']['previous_manifest_sha256']=prior['manifest_sha256']
    value['archive']['archive_commitment_sha256']=v.commitment('archive-descriptor',{k:x for k,x in value['archive'].items() if k!='archive_commitment_sha256'})
    value['commitments']['predecessor_sha256']=v.commitment('predecessor',prior)
    value['commitments']['archive_descriptor_sha256']=v.commitment('archive-descriptor',{k:x for k,x in value['archive'].items() if k!='archive_commitment_sha256'})
    value['commitments']['transition_sha256']=v.commitment('complete-transition',{k:x for k,x in value.items() if k!='commitments'} | {'commitments':{k:x for k,x in value['commitments'].items() if k!='transition_sha256'}})
    assert v.validate_transition(value,prior,False)['epoch_number']==2
    assert value['archive']['archive_commitment_sha256'] != v.commitment('archive-descriptor',value['archive'])

@pytest.mark.parametrize('raw,code',[ (b'{"x":1,"x":2}','EPOCH_DUPLICATE_KEY'),(b'{"x":1.2}','EPOCH_NUMBER'),(b'{"x":"\xff"}','EPOCH_UTF8') ])
def test_bounded_parser(raw,code): assert error(lambda:v.parse_json(raw))==code

def test_parser_limits_domains_and_unknown_fields():
    assert error(lambda:v.parse_json(b'['*17+b'0'+b']'*17))=='EPOCH_NESTING'
    assert error(lambda:v.parse_json(b'{"x":"'+b'a'*4097+b'"}'))=='EPOCH_STRING_BOUNDS'
    assert error(lambda:v.commitment('wrong-domain',{}))=='EPOCH_DOMAIN'
    value=model(); value['unknown']=1
    assert error(lambda:v.validate_transition(value,model()['predecessor'],True))=='EPOCH_FIELDS'

@pytest.mark.parametrize('change,code',[('epoch','EPOCH_NUMBER'),('source','EPOCH_FIRST_SOURCE_IDENTITY'),('pre','EPOCH_PREDECESSOR'),('cut','EPOCH_SOURCE_CUT'),('floor','EPOCH_RETAINED_FLOOR'),('capacity','EPOCH_CAPACITY')])
def test_shared_invalid_semantics(change,code):
    value=model(); prior=copy.deepcopy(value['predecessor'])
    if change=='epoch': value['epoch_number']=0
    elif change=='source': value['source_binding']['source_id']=value['source_cut']['source_id']='other-source'
    elif change=='pre': value['predecessor']['content_id']=1
    elif change=='cut': value['source_cut']['committed_event_id']=6
    elif change=='floor': value['retained_floor_commitment']['entries'][0]['retained_floor']=5
    else: value['active_epoch'].update(target=45000,headroom=6000)
    assert error(lambda:v.validate_transition(value,prior,True))==code

def manifest(value):
    return json.dumps({'contract_revision':v.REVISION,'epoch_rollover':value}).encode('ascii')

def test_default_disabled_gate_never_falls_back_or_accepts():
    raw=manifest({}); pointer={'manifest_sha256':hashlib.sha256(raw).hexdigest()}
    disabled=SimpleNamespace(enable_epoch_v2=False)
    with pytest.raises(SnapshotError,match='EPOCH_V2_DISABLED'): projection.ProjectionReader._manifest(disabled,pointer,raw,None,1,None)
    value=model(); raw=manifest(value); pointer={'manifest_sha256':hashlib.sha256(raw).hexdigest()}
    enabled=SimpleNamespace(enable_epoch_v2=True,epoch_v2_predecessor=copy.deepcopy(value['predecessor']),epoch_v2_first_transition=True)
    with pytest.raises(SnapshotError,match='EPOCH_V2_NOT_ACCEPTING'): projection.ProjectionReader._manifest(enabled,pointer,raw,None,1,None)

def test_errors_do_not_echo_untrusted_value():
    raw=('{'+'"x":"'+'UNTRUSTED_REMOTE_TEXT'*300+'"}').encode('ascii')
    with pytest.raises(v.EpochV2Error) as caught: v.parse_json(raw)
    assert 'UNTRUSTED_REMOTE_TEXT' not in str(caught.value)
