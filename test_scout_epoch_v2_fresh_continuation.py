"""Independent Router parity tests for Scout's frozen fresh-cut chain."""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest

import scout_epoch_v2_validator as v


FIXTURE = Path(__file__).parent / (
    'docs/fixtures/scout-epoch-v2-fresh-cut-continuation-v1.json')
FIXTURE_SHA256 = '09b6899f3e253ba12ade5d2eee4daf14ec839775866cd70dc684ab97b1777011'
TRANSITIONS = (
    '672557597329377ebf69626c18d034777ba8e03b3ae5f7acb49b78a3d698010f',
    'ed95784d5505076440aad7d7e87f3866155166cc072eaba10063c1971dac9cdd',
    '450aa193e849d9c50c5c6ad8cfb478937708e442c4e27d4339fba87f500fe8cc',
)
EPOCH = 'se2:63dcce4fa7e5c4d0de207068f3ef46f168cc157d4e4ce3bbf88816b6eedf0545'


def code(call):
    with pytest.raises(v.EpochV2Error) as caught:
        call()
    return caught.value.code


def fixture():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256
    return json.loads(raw.decode('ascii'))


def transport(vector, name):
    item = vector['transports'][name]
    return item['descriptor'], base64.b64decode(item['bytes_base64'], validate=True)


def accepted_predecessor(root, manifest):
    payload = root['payload']
    return {
        'schema': 'flop-scout-epoch-accepted-predecessor/v1',
        'publication_id': payload['publication_id'], 'content_id': payload['content_id'],
        'epoch_id': payload['epoch_id'],
        'manifest_sha256': hashlib.sha256(manifest).hexdigest(),
        'transition_sha256': root['transition_sha256'],
        'artifact_sha256': payload['active_artifact']['artifact_sha256'],
        'artifact_size': payload['active_artifact']['size_bytes'],
        'source_id': payload['source_id'], 'source_epoch': payload['source_epoch'],
        'source_cut': payload['source_cut'],
        'selection_policy_sha256': payload['selection_policy_sha256'],
        'archive_commitment_sha256': payload['archive']['archive_commitment_sha256'],
        'retained_floor_commitment_sha256': (
            payload['retained_floor']['retained_floor_commitment_sha256']),
    }


def validate_vector_chain(data):
    assert set(data) == {'schema', 'vectors'}
    assert data['schema'] == 'scout-epoch-v2-fresh-cut-continuation-v1'
    assert [item['id'] for item in data['vectors']] == [
        'fresh-first', 'successor-1', 'successor-2']
    prior = None
    for index, item in enumerate(data['vectors']):
        assert set(item) == {'id', 'root', 'transports'}
        root = item['root']
        archive, archive_bytes = transport(item, 'archive')
        active, active_bytes = transport(item, 'active_artifact')
        plan, plan_bytes = transport(item, 'active_set_plan')
        assert v.validate_archive_descriptor_bytes(archive, archive_bytes) == archive
        assert v.validate_active_artifact_bytes(active, active_bytes) == active
        logical_plan = v.validate_plan_descriptor_bytes(plan, plan_bytes)
        assert logical_plan['plan_commitment_sha256'] == plan['plan_commitment_sha256']
        assert root['payload']['archive'] == archive
        assert root['payload']['plan'] == plan
        assert root['payload']['active_artifact'] == active
        manifest = base64.b64decode(item['transports']['manifest_bytes_base64'], validate=True)
        if index == 0:
            snapshot, snapshot_bytes = transport(item, 'source_snapshot')
            assert len(snapshot_bytes) == snapshot['size_bytes']
            assert hashlib.sha256(snapshot_bytes).hexdigest() == snapshot['sha256']
            assert v.validate_fresh_first_transition(
                root, root['payload']['accepted_anchor']) == root['payload']
        else:
            assert root['payload']['predecessor'] == prior
            assert v.validate_content_successor(root, prior) == root['payload']
        prior = accepted_predecessor(root, manifest)
        assert v.validate_accepted_predecessor(prior) == prior


def test_frozen_fresh_cut_fixture_has_independent_router_parity():
    data = fixture()
    validate_vector_chain(data)
    roots = [item['root'] for item in data['vectors']]
    assert tuple(root['transition_sha256'] for root in roots) == TRANSITIONS
    assert tuple(root['payload']['epoch_id'] for root in roots) == (EPOCH, EPOCH, EPOCH)
    assert [root['payload']['publication_id'] for root in roots] == [12, 13, 14]
    assert [root['payload']['content_id'] for root in roots] == [22, 23, 24]
    assert [root['payload']['source_cut'] for root in roots] == [101, 102, 103]
    assert [root['payload']['created_at'] for root in roots] == [
        '2026-01-01T00:00:00Z', '2026-01-01T00:01:00Z', '2026-01-01T00:02:00Z']
    assert roots[0]['payload']['epoch_id'] == 'se2:' + v.fresh_first_payload_identity(
        roots[0]['payload'])
    assert roots[0]['transition_sha256'] == v.commitment(
        'fresh-first-transition', roots[0]['payload'])
    for root in roots[1:]:
        assert root['transition_sha256'] == v.commitment(
            'content-successor-transition', root['payload'])


@pytest.mark.parametrize('mutation, expected', [
    ('authority', 'EPOCH_FRESH_AUTHORITY'), ('snapshot', 'EPOCH_FRESH_AUTHORITY'),
    ('archive', 'EPOCH_ARCHIVE_HASH'), ('plan', 'EPOCH_FRESH_EPOCH'),
    ('artifact', 'EPOCH_FRESH_EPOCH'), ('epoch', 'EPOCH_FRESH_EPOCH'),
    ('unknown', 'EPOCH_FRESH_FIRST_FIELDS'), ('heartbeat', 'EPOCH_PUBLICATION_KIND'),
])
def test_fresh_root_mutations_fail_closed(mutation, expected):
    root = copy.deepcopy(fixture()['vectors'][0]['root'])
    if mutation == 'authority':
        root['payload']['fresh_cut_authority']['authority_sha256'] = '0' * 64
    elif mutation == 'snapshot':
        root['payload']['fresh_cut_authority']['snapshot']['size_bytes'] += 1
    elif mutation == 'archive':
        root['payload']['archive']['archive_commitment_sha256'] = '0' * 64
    elif mutation == 'plan':
        root['payload']['plan']['sha256'] = '0' * 64
    elif mutation == 'artifact':
        root['payload']['active_artifact']['artifact_sha256'] = '0' * 64
    elif mutation == 'epoch':
        root['payload']['epoch_id'] = 'se2:' + '0' * 64
    elif mutation == 'unknown':
        root['unexpected'] = True
    else:
        assert code(lambda: v.validate_fresh_first_transition(
            root, root['payload']['accepted_anchor'], 'HEARTBEAT')) == expected
        return
    assert code(lambda: v.validate_fresh_first_transition(
        root, fixture()['vectors'][0]['root']['payload']['accepted_anchor'])) == expected


@pytest.mark.parametrize('mutation, expected', [
    ('predecessor', 'EPOCH_SUCCESSOR_GAP'), ('policy', 'EPOCH_SUCCESSOR_CONTINUITY'),
    ('floor', 'EPOCH_RETAINED_FLOOR'), ('source', 'EPOCH_SUCCESSOR_CONTINUITY'),
    ('rollback', 'EPOCH_SUCCESSOR_ROLLBACK'), ('cross-root', 'EPOCH_SUCCESSOR_SCHEMA'),
    ('heartbeat', 'EPOCH_PUBLICATION_KIND'),
])
def test_successor_mutations_and_cross_root_reject(mutation, expected):
    data = fixture(); first, successor = data['vectors'][:2]
    root = copy.deepcopy(successor['root'])
    manifest = base64.b64decode(first['transports']['manifest_bytes_base64'], validate=True)
    prior = accepted_predecessor(first['root'], manifest)
    if mutation == 'predecessor':
        root['payload']['predecessor']['manifest_sha256'] = '0' * 64
    elif mutation == 'policy':
        root['payload']['selection_policy_sha256'] = '0' * 64
    elif mutation == 'floor':
        root['payload']['retained_floor']['retained_floor_commitment_sha256'] = '0' * 64
    elif mutation == 'source':
        root['payload']['source_id'] = 'other-source'
    elif mutation == 'rollback':
        root['payload']['source_cut'] = prior['source_cut']
    elif mutation == 'cross-root':
        root = first['root']
    else:
        assert code(lambda: v.validate_content_successor(root, prior, 'HEARTBEAT')) == expected
        return
    assert code(lambda: v.validate_content_successor(root, prior)) == expected


@pytest.mark.parametrize('name, expected', [
    ('archive', 'EPOCH_ARCHIVE_BYTES'), ('active_artifact', 'EPOCH_ARTIFACT_BYTES'),
    ('active_set_plan', 'EPOCH_PLAN_BYTES'),
])
def test_transport_byte_mutations_reject(name, expected):
    vector = fixture()['vectors'][0]
    descriptor, raw = transport(vector, name)
    damaged = raw[:-1] + bytes([raw[-1] ^ 1])
    validator = {'archive': v.validate_archive_descriptor_bytes,
                 'active_artifact': v.validate_active_artifact_bytes,
                 'active_set_plan': v.validate_plan_descriptor_bytes}[name]
    assert code(lambda: validator(descriptor, damaged)) == expected
