"""Corrected producer identity; the original frozen stale identity is retained as negative evidence."""
import hashlib
import json
from pathlib import Path

import pytest
import scout_epoch_v2_validator as v
from epoch_v2_test_support import BUNDLE_FIXTURE, BUNDLE_SHA, model, plan_for

FIXTURE=Path(__file__).parent/'docs/fixtures/scout-epoch-v2-publication-bundle-compact-v2.json'
FIXTURE_SHA='9eb970366344756dcfdc63a148ef3535d470e45a79453dbefc1c9a372444c67b'


def test_corrected_frozen_identity_and_unchanged_negative_fixture():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest()==FIXTURE_SHA
    assert hashlib.sha256(BUNDLE_FIXTURE.read_bytes()).hexdigest()==BUNDLE_SHA
    corrected=json.loads(FIXTURE.read_bytes())['candidate']
    stale=json.loads(BUNDLE_FIXTURE.read_bytes())['compact_candidate_279_243']
    assert corrected['content_id']==243
    assert corrected['artifact_sha256']==stale['artifact_sha256']
    for key in ('plan_sha256','epoch_id','transition_sha256','manifest_sha256','pointer_sha256'):
        assert corrected[key]!=stale[key]
    assert {k:r['count'] for k,r in corrected['summaries'].items()}=={
        'mandatory_proof_closure':10427,'durable_qualification_history':7330,
        'coverage_witnesses':6,'permanent_pinned_evidence':9922,'omitted_history':5968}


@pytest.mark.parametrize('field,stale',[
    ('retained_floor_commitment_sha256','a8fac3dc217435268f6b5ca92fc9382cf954c15e7907183d1d1022cd85fb973f'),
    ('omission_commitment_sha256','2d8d9e5ce315670fd312a252c62564751cc9be9c17bf3823ca26cd2e973db925')])
def test_obsolete_advisory_commitments_never_authorize_a_plan(field,stale):
    transition=model();plan=plan_for(transition)
    plan[field]=stale
    plan['plan_commitment_sha256']=v.active_set_plan_commitment(v.without(plan,'plan_commitment_sha256'))
    with pytest.raises(v.EpochV2Error) as error:
        v.validate_active_set_plan(plan,transition)
    assert error.value.code=='EPOCH_PLAN_BINDING'


def test_v3_frozen_policy_and_exact_dependent_identities():
    import projection_contract as c
    path=FIXTURE.with_name('scout-epoch-v2-publication-bundle-compact-v3.json')
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='c7cee620934589e1a41bb26bbb0cb1af80a49811d99290d048618c21186ba735'
    latest=json.loads(path.read_bytes())['candidate']
    prior=json.loads(FIXTURE.read_bytes())['candidate']
    for key in ('artifact_sha256','plan_sha256','plan_commitment_sha256','epoch_id','transition_sha256','summaries'):
        assert latest[key]==prior[key]
    assert latest['manifest_sha256']=='278df134e5d523c1456b80967882adbfd05daa77b6a5202c1b85d28192006d39'
    assert latest['manifest_sha256']!=prior['manifest_sha256']
    assert latest['pointer_sha256']!=prior['pointer_sha256']
    assert latest['selection_policy']==c.POLICY
    assert latest['selection_policy_sha256']==c.POLICY_SHA


def test_v2_string_policy_is_not_an_accepted_alias(tmp_path):
    from test_epoch_acceptance import setup_bundle,NOW
    from epoch_evidence_test_support import publish
    from scout_epoch_acceptance import accept_disposable
    from scout_snapshot import SnapshotError
    args,_,manifest=setup_bundle(tmp_path)
    manifest['selection_policy']='A1'
    manifest['selection_policy_sha256']=hashlib.sha256(b'"A1"').hexdigest()
    publish(args[1],manifest,args[1]/'active.sqlite')
    before=(args[0]/'state.json').read_bytes()
    with pytest.raises(SnapshotError,match='UNSUPPORTED_POLICY'):
        accept_disposable(*args,enable_epoch_v2=True,now=NOW)
    assert (args[0]/'state.json').read_bytes()==before
