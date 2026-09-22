import copy
import json
from types import SimpleNamespace

import pytest

import scout_epoch_v2_validator as v
import scout_epoch_archive_validator as archive
from scout_projection import EpochValidationSession, ProjectionReader, VerifiedEpochBridge
from scout_snapshot import SnapshotError
from epoch_v2_test_support import (BUNDLE_FIXTURE, BUNDLE_SHA, canonical, commit, excluding,
                                   manifest_for, model, plan_for, seal, sha)


def code(call):
    with pytest.raises(v.EpochV2Error) as exc:
        call()
    return exc.value.code


def validate(value):
    return v.validate_transition(value, model()['accepted_anchor'], 0, True)


def test_frozen_fixture_sha():
    assert sha(BUNDLE_FIXTURE.read_bytes()) == BUNDLE_SHA


@pytest.mark.parametrize('case', json.loads(BUNDLE_FIXTURE.read_text())['transition_cases'], ids=lambda c: c['name'])
def test_all_frozen_transition_vectors(case):
    value = model(); kind = 'CONTENT'
    mutation = case['mutation']
    paths = {'artifact-hash': ('active_artifact', 'artifact_sha256'),
             'plan-descriptor': ('active_set_plan', 'sha256')}
    if mutation in paths:
        obj, key = paths[mutation]; value[obj][key] = '0' * 64
    elif mutation == 'epoch-id': value['epoch_id'] = 'se2:' + '0' * 64
    elif mutation == 'artifact-locator': value['active_artifact']['locator'] = 'other.sqlite'
    elif mutation == 'manifest-hash': value['manifest_sha256'] = '0' * 64
    elif mutation == 'heartbeat': kind = 'HEARTBEAT'
    else: assert mutation == 'none'
    call = lambda: v.validate_transition(value, model()['accepted_anchor'], 0, True, kind)
    if case['expect'] == 'PASS': assert call()['epoch_number'] == 1
    else: assert code(call) == case['expect']


@pytest.mark.parametrize('case', json.loads(BUNDLE_FIXTURE.read_text())['plan_cases'], ids=lambda c: c['name'])
def test_all_frozen_plan_vectors(case):
    value = model(); plan = plan_for(value); mutation = case['mutation']
    if mutation == 'artifact': plan['archive_descriptor_sha256'] = '0' * 64
    elif mutation == 'duplicate': plan['omitted'].append(copy.deepcopy(plan['selected'][0]))
    elif mutation == 'oversized':
        assert code(lambda: v.parse_active_set_plan(b'x' * (v.MAX_PLAN_BYTES + 1))) == case['expect']
        return
    else: assert mutation == 'none'
    call = lambda: v.validate_active_set_plan(plan, value)
    if case['expect'] == 'PASS': assert call()['counts']['eligible'] == 2
    else: assert code(call) == case['expect']


def test_complete_bundle_and_transport_bindings_are_pure():
    value = model(); plan = plan_for(value); raw_plan = canonical(plan)
    value['active_set_plan'].update(sha256=sha(raw_plan), size_bytes=len(raw_plan),
                                  plan_commitment_sha256=plan['plan_commitment_sha256'])
    seal(value); manifest = manifest_for(value); before = copy.deepcopy((value, plan, manifest))
    raw = canonical(value)
    assert validate(value)['epoch_number'] == 1
    assert v.validate_active_set_plan_bytes(raw_plan, value) == plan
    assert v.validate_transition_bytes(raw, manifest['epoch_transition'], value['accepted_anchor'], 0, True) == value
    assert v.validate_v2_manifest(manifest, value) == manifest
    assert (value, plan, manifest) == before
    assert v.canonical_json(value) == raw
    assert v.transition_commitment(value) == value['commitments']['transition_sha256']
    assert code(lambda: v.validate_active_set_plan_bytes(raw_plan + b' ', value)) == 'EPOCH_PLAN_BYTES'
    assert code(lambda: v.validate_transition_bytes(raw + b' ', manifest['epoch_transition'], value['accepted_anchor'])) == 'EPOCH_TRANSITION_BYTES'
    value['active_set_plan']['plan_commitment_sha256'] = '0' * 64
    assert code(lambda: v.validate_active_set_plan_bytes(raw_plan, value)) == 'EPOCH_PLAN_BINDING'
    manifest['epoch_transition']['transition_sha256'] = '0' * 64
    assert code(lambda: v.validate_transition_bytes(raw, manifest['epoch_transition'], value['accepted_anchor'], 0, True)) == 'EPOCH_MANIFEST_BINDING'


@pytest.mark.parametrize('field', v.DESCRIPTOR)
def test_every_normalized_descriptor_field_binds_bridge(field):
    value = model(); anchor = value['accepted_anchor']; bridge = copy.deepcopy(anchor)
    if type(bridge[field]) is int: bridge[field] += 1
    elif field.endswith('sha256'): bridge[field] = '0' * 64
    else: bridge[field] += '-other'
    assert v.bridge_binding(anchor, bridge) != value['bridge_binding_sha256']
    assert code(lambda: v.descriptor(excluding(anchor, field))) == 'EPOCH_DESCRIPTOR'


@pytest.mark.parametrize('field', ['publication_sequence', 'content_id', 'source_cut', 'artifact_size'])
@pytest.mark.parametrize('bad', [True, -1, '7', v.MAX_INT + 1])
def test_normalized_descriptor_numeric_bounds(field, bad):
    anchor = model()['accepted_anchor']; anchor[field] = bad
    assert code(lambda: v.descriptor(anchor)) == 'EPOCH_DESCRIPTOR'


@pytest.mark.parametrize('field,expected', [
    ('descriptor_sha256', 'EPOCH_SOURCE_DESCRIPTOR'), ('cut_evidence_sha256', 'EPOCH_SOURCE_CUT_EVIDENCE'),
    ('committed_event_id', 'EPOCH_FIRST_SOURCE_CUT')])
def test_first_source_derivation_mutations(field, expected):
    value = model()
    target = value['source_binding'] if field == 'descriptor_sha256' else value['source_cut']
    target[field] = target[field] + 1 if type(target[field]) is int else '0' * 64
    assert code(lambda: validate(value)) == expected


def test_derivation_parity_and_wrong_archive_domain():
    value = model(); bridge = value['bridge_predecessor']; binding = value['bridge_binding_sha256']
    assert v.bridge_binding(value['accepted_anchor'], bridge) == binding
    assert v.first_transition_source_binding(bridge, binding) == value['source_binding']
    assert v.first_transition_source_cut(value['source_binding'], bridge, binding) == value['source_cut']
    assert v.derive_epoch_id(value) == value['epoch_id']
    value['archive']['archive_commitment_sha256'] = sha(b'flop-scout/epoch-archive-descriptor/v1\0' + canonical(excluding(value['archive'], 'archive_commitment_sha256')))
    assert code(lambda: validate(value)) == 'EPOCH_ARCHIVE_HASH'


@pytest.mark.parametrize('section,field', [('active_artifact', 'locator'), ('active_set_plan', 'locator'),
                                          ('active_set_plan', 'sha256'), ('active_set_plan', 'size_bytes')])
def test_transport_changes_bind_complete_transition_not_epoch_id(section, field):
    value = model(); epoch = value['epoch_id']
    value[section][field] = 22 if field == 'size_bytes' else '0' * 64 if field == 'sha256' else 'other.json'
    assert v.derive_epoch_id(value) == epoch
    assert code(lambda: validate(value)) == 'EPOCH_COMMITMENT'
    domain = 'active-artifact-descriptor' if section == 'active_artifact' else 'active-set-plan-descriptor'
    value['commitments'][section + '_descriptor_sha256'] = commit(domain, value[section])
    assert code(lambda: validate(value)) == 'EPOCH_TRANSITION_HASH'
    value['commitments']['transition_sha256'] = v.transition_commitment(value)
    assert validate(value)['epoch_id'] == epoch


@pytest.mark.parametrize('raw, expected', [
    (b'{"a":0,"a":1}', 'EPOCH_DUPLICATE_KEY'), (b'[1.0]', 'EPOCH_NUMBER'),
    (b'[NaN]', 'EPOCH_NUMBER'), (b'"\xff"', 'EPOCH_PLAN_JSON'),
    (b'"\\u00e9"', 'EPOCH_UNICODE'), (b'"\\ud800"', 'EPOCH_UNICODE'),
    (b'[' * 18 + b'0' + b']' * 18, 'EPOCH_PLAN_NESTING'),
    (canonical([0] * 50001), 'EPOCH_PLAN_BOUNDS'), (b'', 'EPOCH_PLAN_BOUNDS'),
    (canonical({'a': v.MAX_INT + 1}), 'EPOCH_INTEGER_BOUNDS')])
def test_plan_parser_bounds(raw, expected):
    assert code(lambda: v.parse_active_set_plan(raw)) == expected


def test_plan_byte_bound_and_generic_bounds_stay_separate():
    raw = canonical(list(range(50000)))
    assert len(raw) > v.MAX_INPUT_BYTES
    assert len(v.parse_active_set_plan(raw)) == 50000
    assert code(lambda: v.parse_json(raw)) == 'EPOCH_INPUT_BOUNDS'
    assert code(lambda: v.canonical_json(list(range(257)))) == 'EPOCH_LIST_BOUNDS'
    assert v.parse_active_set_plan(b'0' + b' ' * (v.MAX_PLAN_BYTES - 1)) == 0
    assert code(lambda: v.parse_active_set_plan(b'0' + b' ' * v.MAX_PLAN_BYTES)) == 'EPOCH_PLAN_BOUNDS'


def test_large_redacted_plan_validates_and_enforces_total_count():
    value = model(); plan = plan_for(value)
    plan['selected'] = [dict(plan['selected'][0], raw_record_id=f'{n:064x}', projection_row_id=f'sm1:{n:064x}') for n in range(257)]
    plan['counts'] = {'selected': 257, 'omitted': 1, 'eligible': 258}
    plan['plan_commitment_sha256'] = commit('active-set-plan', excluding(plan, 'plan_commitment_sha256'))
    assert v.validate_active_set_plan(v.parse_active_set_plan(canonical(plan)), value) == plan
    plan['selected'] *= 195
    assert code(lambda: v.validate_active_set_plan(plan, value)) == 'EPOCH_PLAN_BOUNDS'


@pytest.mark.parametrize('mutation,expected', [
    ('raw_text', 'EPOCH_PLAN_RECORD'), ('bad_reasons', 'EPOCH_PLAN_RECORD'), ('duplicate_reason', 'EPOCH_PLAN_RECORD'),
    ('count', 'EPOCH_PLAN_COUNTS'), ('hash', 'EPOCH_PLAN_COMMITMENT'), ('source', 'EPOCH_PLAN_BINDING'),
    ('epoch_id', 'EPOCH_PLAN_FIELDS')])
def test_plan_mutations(mutation, expected):
    value = model(); plan = plan_for(value)
    if mutation == 'raw_text': plan['selected'][0]['raw_text'] = 'untrusted'
    elif mutation == 'bad_reasons': plan['selected'][0]['reasons'] = [{}]
    elif mutation == 'duplicate_reason': plan['selected'][0]['reasons'] *= 2
    elif mutation == 'count': plan['counts']['selected'] = 2
    elif mutation == 'hash': plan['plan_commitment_sha256'] = '0' * 64
    elif mutation == 'source': plan['candidate_source'] = {}
    else: plan['epoch_id'] = value['epoch_id']
    assert code(lambda: v.validate_active_set_plan(plan, value)) == expected


def test_compact_summary_sorted_sets_and_counts():
    sets = {name: ['a', 'b'] for name in v.SET_DOMAINS}
    summary = v.compact_retained_floor([], 'policy/1', sets)
    for name, domain in v.SET_DOMAINS.items():
        assert summary[name + '_count'] == 2
        assert summary[name + '_sha256'] == commit(domain, ['a', 'b'])
        assert name not in summary
    assert code(lambda: v.bounded_commitment('mandatory-closure', ['b', 'a'])) == 'EPOCH_FLOOR_ORDER'
    assert code(lambda: v.bounded_commitment('mandatory-closure', ['a', 'a'])) == 'EPOCH_FLOOR_ORDER'
    assert code(lambda: v.bounded_commitment('mandatory-closure', {})) == 'EPOCH_FLOOR_BOUNDS'
    value = model(); value['retained_floor_commitment']['mandatory_proof_closure_count'] = 50001
    assert code(lambda: validate(value)) == 'EPOCH_FLOOR_BOUNDS'
    value = model(); value['retained_floor_commitment']['mandatory_proof_closure'] = ['a']
    assert code(lambda: validate(value)) == 'EPOCH_FIELDS'


@pytest.mark.parametrize('field', v.MANIFEST)
def test_manifest_requires_exact_fields(field):
    value = model(); manifest = manifest_for(value); del manifest[field]
    assert code(lambda: v.validate_v2_manifest(manifest, value)) == 'EPOCH_MANIFEST_FIELDS'


@pytest.mark.parametrize('field,bad,expected', [
    ('publication_kind', 'HEARTBEAT', 'EPOCH_PUBLICATION_KIND'),
    ('database_content_id', 999, 'EPOCH_MANIFEST_BINDING'), ('snapshot_id', True, 'EPOCH_MANIFEST'),
    ('sha256', '0' * 64, 'EPOCH_MANIFEST_BINDING'), ('database', '../x', 'EPOCH_MANIFEST'),
    ('contract_revision', 'A1', 'EPOCH_MANIFEST_SCHEMA')])
def test_manifest_binding_mutations(field, bad, expected):
    value = model(); manifest = manifest_for(value); manifest[field] = bad
    assert code(lambda: v.validate_v2_manifest(manifest, value)) == expected


@pytest.mark.parametrize('field,bad', [('locator', '/tmp/a'), ('size_bytes', 65537), ('sha256', 'A' * 64),
                                      ('schema', 'old'), ('transition_sha256', None)])
def test_sidecar_descriptor_mutations(field, bad):
    desc = manifest_for(model())['epoch_transition']; desc[field] = bad
    assert code(lambda: v.validate_transition_descriptor(desc)) == 'EPOCH_MANIFEST_TRANSITION'


def test_pointer_dispatch_and_disabled_gate_do_not_construct_profiles(tmp_path):
    value = model(); manifest = manifest_for(value); raw = canonical(manifest)
    publication = tmp_path / 'publication'; publication.mkdir()
    reader = ProjectionReader(publication, tmp_path / 'cache')
    pointer = {'schema': 'flop-scout-router-current/v2', 'manifest': 'manifest-v2-901-' + sha(raw) + '.json',
               'manifest_sha256': sha(raw), 'published_at': value['created_at']}
    before = sorted(tmp_path.rglob('*'))
    with pytest.raises(SnapshotError, match='EPOCH_V2_DISABLED'):
        reader._manifest(pointer, raw, None, 3600, None)
    reader.enable_epoch_v2 = True
    with pytest.raises(SnapshotError, match='EPOCH_V2_NOT_ACCEPTING'):
        reader._manifest(pointer, raw, None, 3600, None)
    obsolete = canonical({'contract_revision': v.REVISION, 'epoch_rollover': value})
    with pytest.raises(SnapshotError, match='EPOCH_MANIFEST_FIELDS'):
        reader._manifest(dict(pointer, manifest_sha256=sha(obsolete)), obsolete, None, 3600, None)
    assert sorted(tmp_path.rglob('*')) == before


def receipt(session, value):
    return VerifiedEpochBridge(session, session.token, sha(canonical(value)), value['accepted_anchor'],
        value['bridge_predecessor'], value['bridge_binding_sha256'], 'a' * 64, {}, 'b' * 64, 'c' * 64, 'd' * 64)


@pytest.mark.parametrize('cumulative', [False, True])
def test_archive_binding_comes_from_live_receipt_not_fixed_real_hash(tmp_path, monkeypatch, cumulative):
    value = model(cumulative)
    class ReachedArchiveRead(Exception): pass
    def read(*args): raise ReachedArchiveRead
    monkeypatch.setattr(archive, '_read_member', read)
    with EpochValidationSession(SimpleNamespace(cache_dir=tmp_path)) as session:
        item = receipt(session, value)
        with pytest.raises(ReachedArchiveRead): archive.validate_archive(session, item, tmp_path)
        with EpochValidationSession(SimpleNamespace(cache_dir=tmp_path)) as other:
            with pytest.raises(archive.ArchiveValidationError, match='ARCHIVE_BRIDGE_RECEIPT'):
                archive.validate_archive(other, item, tmp_path)
        forged = receipt(session, value); forged.accepted_anchor['content_id'] += 1
        with pytest.raises(archive.ArchiveValidationError, match='ARCHIVE_BRIDGE_RECEIPT'):
            archive.validate_archive(session, forged, tmp_path)
    with pytest.raises(archive.ArchiveValidationError, match='ARCHIVE_BRIDGE_RECEIPT'):
        archive.validate_archive(session, item, tmp_path)


@pytest.mark.parametrize('damage', [None, 'binding', 'anchor', 'checkpoint-alias', 'epoch', 'member'])
def test_archive_receipt_and_manifest_bindings(tmp_path, monkeypatch, damage):
    """Exercise actual member reads and format checks, isolating legacy SQLite recovery."""
    value = model(); bridge_bytes = b'synthetic held bridge'
    for key in ('accepted_anchor', 'bridge_predecessor'):
        value[key].update(artifact_sha256=sha(bridge_bytes), artifact_size=len(bridge_bytes))
    value['bridge_binding_sha256'] = v.bridge_binding(value['accepted_anchor'], value['bridge_predecessor'])
    recovery = {'validated_records': 2, 'closure_count': 1, 'commitment': 'e' * 64}
    bodies = {'bridge_projection_sqlite': bridge_bytes, 'legacy_recovery_json': canonical(recovery),
              'source_evidence_sqlite': b'synthetic source'}
    members = []
    for role, (name, schema) in sorted(archive.ROLES.items()):
        path = tmp_path / name; path.parent.mkdir(exist_ok=True); path.write_bytes(bodies[role])
        members.append({'role': role, 'locator': name, 'schema': schema,
                        'sha256': sha(bodies[role]), 'size_bytes': len(bodies[role])})
    bridge = value['bridge_predecessor']
    manifest = {'schema': archive.ARCHIVE_SCHEMA, 'archive_id': 'ea2:synthetic',
        'accepted_anchor': copy.deepcopy(value['accepted_anchor']), 'bridge_predecessor': copy.deepcopy(bridge),
        'previous_bridge_binding_sha256': value['bridge_binding_sha256'],
        'source_checkpoint': {'source_id': 'archive-source', 'source_epoch': bridge['source_kind'], 'source_cut': bridge['source_cut']},
        'legacy_recovery': {'schema': archive.RECOVERY_SCHEMA, 'commitment_sha256': 'e' * 64, 'validated_records': 2, 'closure_count': 1},
        'retention': 'IMMUTABLE_INDEFINITE_FIRST_TRANSITION', 'members': members}
    if damage == 'binding': manifest['previous_bridge_binding_sha256'] = '0' * 64
    elif damage == 'anchor': manifest['accepted_anchor']['content_id'] += 1
    elif damage == 'checkpoint-alias': manifest['source_checkpoint']['epoch'] = manifest['source_checkpoint'].pop('source_epoch')
    elif damage == 'epoch': manifest['source_checkpoint']['source_epoch'] = 'other'
    elif damage == 'member': (tmp_path / 'members/source-evidence.sqlite').write_bytes(b'tampered')
    manifest['manifest_commitment_sha256'] = sha(b'flop-scout/epoch-archive-manifest/v1\0' + canonical(manifest))
    (tmp_path / 'manifest.json').write_bytes(canonical(manifest))
    monkeypatch.setattr(archive, '_recover', lambda *args: (2, 3, 1, 'e' * 64))
    with EpochValidationSession(SimpleNamespace(cache_dir=tmp_path)) as session:
        item = receipt(session, value)
        if damage:
            expected = {'binding': 'ARCHIVE_BRIDGE_RECEIPT', 'anchor': 'ARCHIVE_BRIDGE_RECEIPT',
                        'checkpoint-alias': 'ARCHIVE_SOURCE_BINDING', 'epoch': 'ARCHIVE_SOURCE_BINDING',
                        'member': 'ARCHIVE_MEMBER_IO'}[damage]
            with pytest.raises(archive.ArchiveValidationError, match=expected):
                archive.validate_archive(session, item, tmp_path)
        else:
            result = archive.validate_archive(session, item, tmp_path)
            assert result.bridge_receipt is item and result._session is session and result.closure_count == 1
            import pickle
            with pytest.raises(TypeError): pickle.dumps(result)
