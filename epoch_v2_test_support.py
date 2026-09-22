"""Synthetic compact wire fixtures; no Scout imports or production artifacts."""
import copy
import hashlib
import json
from pathlib import Path

OLD_FIXTURE = Path(__file__).parent / 'docs/fixtures/scout-router-epoch-rollover-v2-conformance.json'
BUNDLE_FIXTURE = Path(__file__).parent / 'docs/fixtures/scout-epoch-v2-publication-bundle-v1.json'
BUNDLE_SHA = 'd3dca144bacaad1f47a1b0ad5a7ee4ec2c35eaa60c946bcc282d5b5b607bb8a4'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def commit(domain, value):
    return sha(b'flop-scout/epoch-v2/' + domain.encode('ascii') + b'\0' + canonical(value))


def excluding(value, key):
    return {k: v for k, v in value.items() if k != key}


def seal(value):
    """Independent test oracle for the frozen identity and commitment views."""
    floors = value['retained_floor_commitment']
    value['archive']['archive_commitment_sha256'] = commit('archive-descriptor', excluding(value['archive'], 'archive_commitment_sha256'))
    floors['retained_floor_commitment_sha256'] = commit('retained-floor-declaration', excluding(floors, 'retained_floor_commitment_sha256'))
    checks = {}
    for key, domain, body in (
        ('accepted_anchor_sha256', 'accepted-anchor', value['accepted_anchor']),
        ('bridge_predecessor_sha256', 'bridge-predecessor', value['bridge_predecessor']),
        ('archive_descriptor_sha256', 'archive-descriptor', excluding(value['archive'], 'archive_commitment_sha256')),
        ('active_artifact_descriptor_sha256', 'active-artifact-descriptor', value['active_artifact']),
        ('active_set_plan_descriptor_sha256', 'active-set-plan-descriptor', value['active_set_plan']),
    ):
        checks[key] = commit(domain, body)
    checks.update(bridge_binding_sha256=value['bridge_binding_sha256'],
                  retained_floor_declaration_sha256=floors['retained_floor_commitment_sha256'],
                  mandatory_closure_sha256=floors['mandatory_proof_closure_sha256'])
    for name in ('durable_qualification_history', 'coverage_witnesses', 'permanent_pinned_evidence'):
        checks[name + '_sha256'] = floors[name + '_sha256']
    identity = {key: value[key] for key in ('schema', 'contract_revision', 'epoch_number', 'accepted_anchor', 'bridge_predecessor', 'bridge_binding_sha256')}
    identity.update(candidate_source={'source_binding': value['source_binding'], 'source_cut': value['source_cut']},
        active_artifact=excluding(value['active_artifact'], 'locator'),
        active_set_plan={key: value['active_set_plan'][key] for key in ('schema', 'plan_commitment_sha256', 'recovery_commitment_sha256')},
        archive={key: item for key, item in value['archive'].items() if key not in ('schema', 'locator', 'preservation')},
        capacity_policy=dict(value['active_epoch'], selection_policy_version=floors['selection_policy_version']),
        retained_floor_commitment_sha256=floors['retained_floor_commitment_sha256'],
        omission_commitment_sha256=floors['omitted_history_sha256'])
    value['epoch_id'] = 'se2:' + commit('epoch-id', identity)
    value['commitments'] = checks
    checks['transition_sha256'] = commit('complete-transition', copy.deepcopy(value))
    return value


def model(cumulative=False):
    value = copy.deepcopy(json.loads(OLD_FIXTURE.read_text())['vectors'][int(cumulative)]['transition'])
    bridge = value['bridge_predecessor']
    binding = commit('a1-bridge-binding', {key: value[key] for key in ('accepted_anchor', 'bridge_predecessor')})
    value['bridge_binding_sha256'] = binding
    value['source_binding'] = {'source_id': bridge['source_id'], 'epoch': bridge['source_kind'],
        'descriptor_sha256': commit('source-binding-descriptor', {'schema': 'flop-scout-epoch-source-binding/v1',
            'source_id': bridge['source_id'], 'epoch': bridge['source_kind'], 'bridge_binding_sha256': binding})}
    value['source_cut'] = {'source_id': bridge['source_id'], 'epoch': bridge['source_kind'],
        'committed_event_id': bridge['source_cut'], 'cut_evidence_sha256': commit('source-cut-evidence', {
            'schema': 'flop-scout-epoch-source-cut-evidence/v1', 'source_binding': value['source_binding'],
            'committed_event_id': bridge['source_cut'], 'bridge_binding_sha256': binding})}
    value['archive'].update(previous_manifest_sha256=bridge['manifest_sha256'], previous_bridge_binding_sha256=binding)
    floors = value['retained_floor_commitment']
    for name in ('mandatory_proof_closure', 'durable_qualification_history', 'coverage_witnesses', 'permanent_pinned_evidence', 'omitted_history'):
        floors[name + '_count'] = len(floors.pop(name))
    value['active_artifact'] = {'schema': 'scout-router-projection/v2', 'content_id': 801,
        'locator': 'router-projection-v2-801.sqlite', 'artifact_sha256': '1' * 64, 'size_bytes': 43,
        'database_schema_version': 'scout-router-projection/v2'}
    value['active_set_plan'] = {'schema': 'flop-scout-epoch-active-set-plan/v1', 'locator': 'epoch-active-set-v2-801.json',
        'sha256': '2' * 64, 'size_bytes': 1024, 'plan_commitment_sha256': '3' * 64, 'recovery_commitment_sha256': '4' * 64}
    return seal(value)


def plan_for(value):
    def row(raw, text_hash, event, reason):
        return {'projection_row_id': 'sm1:' + raw * 64, 'raw_record_id': raw * 64,
                'raw_text_sha256': text_hash * 64, 'scout_event_id': event, 'reasons': [reason]}
    plan = {'schema': 'flop-scout-epoch-active-set-plan/v1', 'selection_policy_version': 'epoch-v2-policy/1',
        'candidate_source': {key: value[key] for key in ('source_binding', 'source_cut')},
        'archive_descriptor_sha256': value['archive']['archive_commitment_sha256'],
        'recovery_commitment_sha256': value['active_set_plan']['recovery_commitment_sha256'],
        'retained_floor_commitment_sha256': value['retained_floor_commitment']['retained_floor_commitment_sha256'],
        'omission_commitment_sha256': value['retained_floor_commitment']['omitted_history_sha256'],
        'capacity': value['active_epoch'], 'selected': [row('5', '6', '9', 'mandatory')],
        'omitted': [row('7', '8', '10', 'optional')], 'counts': {'selected': 1, 'omitted': 1, 'eligible': 2}}
    plan['plan_commitment_sha256'] = commit('active-set-plan', plan)
    return plan


def manifest_for(value):
    active = value['active_artifact']; raw = canonical(value)
    return {'schema': 'flop-scout-router-snapshot/v2', 'contract_revision': 'A1-EPOCH-V2',
        'snapshot_id': 901, 'publication_kind': 'CONTENT', 'database_content_id': active['content_id'],
        'database': active['locator'], 'sha256': active['artifact_sha256'], 'size_bytes': active['size_bytes'],
        'database_schema_version': active['database_schema_version'], 'selection_policy': 'epoch-v2-policy/1',
        'selection_policy_sha256': '9' * 64, 'content_created_at': value['created_at'],
        'selection_evaluated_at': value['created_at'], 'produced_at': value['created_at'],
        'source_checkpoint': {}, 'next_expiry_at': '2026-01-02T00:00:00Z', 'row_counts': {},
        'watermarks': {}, 'coverage_history': {}, 'epoch_transition': {'schema': value['schema'],
            'locator': 'epoch-transition-v2.json', 'sha256': sha(raw), 'size_bytes': len(raw),
            'transition_sha256': value['commitments']['transition_sha256']}}
