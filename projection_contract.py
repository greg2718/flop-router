# Pure V2/A1 wire validators adapted from Scout development contract/model.
# No Scout runtime imports, database access or scoring authority.
"""Strict, local-only Scout Router V2/A1 wire contract primitives."""
from __future__ import annotations
import hashlib
import json
import math
import re
from datetime import datetime, timezone, timedelta

POLICY = {
    'schema': 'flop-router-projection-selection/v1',
    'version': 'router-evidence-horizons/2',
    'classifier_version': 'router-evidence-classes/2',
    'qualification_policy_version': 'router-durable-qualification/v1',
    'parameters': {'context_seconds': 2592000, 'capability_signal_seconds': 7776000,
                   'closed_work_seconds': 7776000, 'closed_tclk_seconds': 7776000},
    'cutoff_semantics': 'trusted-first-observed-strict-before-expiry/v1',
    'pinned_record_rules': 'transitive-local-evidence-dependencies-no-implicit-unpin/v1',
}
SCHEMA = 'scout-router-projection/v2'
FAMILY = 'local-flop-agent-family'
TABLES = ('messages', 'interactions', 'source_provenance', 'selection_membership',
          'watermarks', 'coverage_history', 'durable_qualifications', 'qualification_events')
CLASSES = {'IDENTITY_OPERATOR', 'BENCH_VERIFICATION', 'CAPABILITY_SUPPORT',
           'CAPABILITY_CONTRADICTION', 'NEGATIVE_EVIDENCE', 'CONTEXT',
           'CAPABILITY_SIGNAL', 'WORK_LIFECYCLE', 'TCLK_LIFECYCLE', 'PINNED'}
REF_KEYS = {'kind', 'source_id', 'source_epoch', 'id', 'sha256'}
ANNOTATIONS = {'classification': None, 'same_operator': None, 'independent_reputation': None,
               'operator_group': None, 'capability_support': [], 'verification_links': [],
               'task_routing_links': [], 'evidence_links': []}



class ProjectionError(ValueError):
    """Fail-closed producer error; never authorizes discarding evidence."""


def require(ok, message):
    if not ok:
        raise ProjectionError(message)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ProjectionError('Non-canonical JSON value') from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def text_hash(value):
    require(type(value) is str, 'Text must be a string')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def loads(raw, limit=4*1024*1024):
    require(not (isinstance(raw,bytes) and raw.startswith(b'\xef\xbb\xbf') or isinstance(raw,str) and raw.startswith('\ufeff')), 'JSON BOM rejected')
    require(len(raw.encode('utf-8') if isinstance(raw, str) else raw) <= limit, 'JSON exceeds limit')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda v: require(False, 'Nonfinite JSON'))
        canonical(value)
        return value
    except (ValueError, UnicodeError) as exc:
        raise ProjectionError('Invalid strict JSON: ' + str(exc)) from exc


def keys(value, expected):
    require(type(value) is dict and set(value) == set(expected), 'Unexpected object fields')


def string(value, nullable=False):
    if nullable and value is None:
        return value
    require(type(value) is str and bool(value.strip()) and len(value) <= 256, 'Invalid bounded string')
    # For an already type-checked bounded string, UTF-8 encoding is exactly
    # the remaining failure condition of canonical JSON (lone surrogates).
    # Avoid constructing millions of discarded quoted JSON strings.
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise ProjectionError('Non-canonical JSON value') from exc
    return value


def sha(value, nullable=False):
    require(nullable and value is None or type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'Invalid SHA-256')
    return value


def decimal(value):
    require(type(value) is str and re.fullmatch('0|[1-9][0-9]{0,19}', value), 'Invalid decimal ID')
    return value


def instant(value):
    require(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z', value), 'Invalid UTC timestamp')
    try:
        return datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError as exc:
        raise ProjectionError('Invalid UTC date') from exc


def utc(value=None):
    return (value or datetime.now(timezone.utc)).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def plus(value, seconds):
    return utc(instant(value) + timedelta(seconds=seconds))


def reference(value, kinds=None, nullable_hash=False):
    keys(value, REF_KEYS)
    for key in REF_KEYS - {'sha256'}:
        string(value[key])
    if kinds is not None:
        require(value['kind'] in kinds, 'Unsupported reference kind')
    sha(value['sha256'], nullable_hash)
    return value


def ordered_refs(values, nonempty=False):
    require(type(values) is list and len(values) <= 256 and (values or not nonempty), 'Invalid reference list')
    for value in values:
        reference(value)
    require([canonical(v) for v in values] == sorted(set(canonical(v) for v in values)), 'References must be sorted and unique')


def annotations(value):
    keys(value, ANNOTATIONS)
    require(len(canonical(value)) <= 65536, 'Annotations exceed limit')
    string(value['classification'], True); string(value['operator_group'], True)
    for key in ('same_operator', 'independent_reputation'):
        require(value[key] is None or type(value[key]) is bool, 'Invalid operator boolean')
    if value['operator_group'] == FAMILY or value['same_operator'] is True:
        require(value['independent_reputation'] is not True, 'Same operator cannot be independent')
    shapes = {
        'capability_support': {'capability_id', 'classification', 'evidence_id'},
        'verification_links': {'request_id', 'result_hash', 'bench_did', 'validation_id', 'correctness', 'reproducibility', 'authenticity', 'evidence_classification'},
        'task_routing_links': {'job_proto', 'job_id', 'task_hash', 'routing_decision_id', 'routing_decision_hash'},
        'evidence_links': {'room', 'generation', 'seq', 'evidence_id'},
    }
    for name, shape in shapes.items():
        rows = value[name]
        require(type(rows) is list and len(rows) <= 256, 'Invalid annotations array')
        require([canonical(r) for r in rows] == sorted(set(canonical(r) for r in rows)), 'Unsorted annotations')
        for row in rows:
            keys(row, shape)
            for key, item in row.items():
                if key == 'seq':
                    require(item is None or type(item) is int and item >= 0, 'Invalid link sequence')
                else:
                    string(item, name != 'capability_support')
                    if key in {'task_hash', 'result_hash', 'routing_decision_hash'}:
                        sha(item, True)
            if name == 'verification_links':
                require(any(row[k] is not None for k in ('request_id', 'result_hash', 'bench_did', 'validation_id')), 'Unidentified verification')
            if name == 'task_routing_links':
                require(any(v is not None for v in row.values()), 'Unidentified task')
            if name == 'evidence_links':
                location = [row[k] is not None for k in ('room', 'generation', 'seq')]
                require(all(location) or not any(location) and row['evidence_id'] is not None, 'Incomplete evidence location')
    return value


def roots(value):
    require(type(value) is list and len(value) <= 256 and len(canonical(value)) <= 65536, 'Invalid pin roots')
    for root in value:
        keys(root, {'kind', 'id'}); string(root['id'])
        require(root['kind'] in {'ROUTING_DECISION', 'TASK', 'VALIDATION', 'VERIFICATION'}, 'Invalid pin root kind')
    require(value == sorted(value, key=lambda r: (r['kind'], r['id'])) and len({canonical(v) for v in value}) == len(value), 'Unsorted pin roots')


def identity(prefix, value):
    return prefix + ':' + digest(value)



POLICY_SHA = digest(POLICY)

QUAL_KEYS = set('schema qualification_id source_ref scout_event_id evidence_id subject_did claim qualification_type qualification_outcome qualified_at policy_version policy_sha256 classifier_version qualification_policy_version bootstrap_id evaluation_id source_cut rule_id rule_input_sha256 rule_group_sha256 provenance_refs operator_group same_operator independent_reputation authenticity correctness reproducibility initial_status'.split())
EVENT_KEYS = set('schema event_id qualification_id sequence previous_event_sha256 event_type recorded_at reason_code proof_refs authority_ref superseded_by qualification_policy_version'.split())
OUTCOMES = {'CAPABILITY_USE': {'LIMITED', 'STRONG'}, 'CONTROLLED_BENCH': {'PASS', 'FAIL'},
            'OBJECTIVE_VALIDATION': {'PASS', 'FAIL'}, 'CAPABILITY_CONTRADICTION': {'CONTRADICTED'},
            'NEGATIVE_FACT': {'ESTABLISHED_NEGATIVE_FACT'}}
REASONS = {'SIGNATURE_PROVENANCE_FAILURE', 'WRONG_IDENTITY_BINDING', 'BROKEN_TASK_LINKAGE',
           'CORRUPTED_EVIDENCE', 'COORDINATED_CLASSIFIER_RECLASSIFICATION', 'PROVEN_FRAUD_SPOOFING'}


def validate_qualification(record, historical_policies=None):
    keys(record, QUAL_KEYS)
    require(len(canonical(record)) <= 65536, 'Qualification too large')
    require(record['schema'] == 'router-durable-qualification/v1', 'Unsupported qualification schema')
    require(record['qualification_id'] == identity('dq1', {k:v for k,v in record.items() if k != 'qualification_id'}), 'Qualification ID hash mismatch')
    reference(record['source_ref'], {'PROJECTED_MESSAGE', 'LOCAL_ARTIFACT'})
    ordered_refs(record['provenance_refs'], True)
    require(record['source_ref'] in record['provenance_refs'], 'Qualification missing source proof')
    keys(record['claim'], {'kind', 'id'}); string(record['claim']['id'])
    require(record['claim']['kind'] in {'CAPABILITY', 'VERIFICATION', 'NEGATIVE_FACT'}, 'Invalid claim kind')
    require(record['qualification_type'] in OUTCOMES and record['qualification_outcome'] in OUTCOMES[record['qualification_type']], 'Invalid qualification outcome')
    require(record['initial_status'] == 'VALID', 'Initial qualification must be VALID')
    instant(record['qualified_at'])
    versions = (record['policy_version'], record['policy_sha256'], record['classifier_version'], record['qualification_policy_version'])
    allowed = {(POLICY['version'], POLICY_SHA, POLICY['classifier_version'], POLICY['qualification_policy_version'])}
    allowed.update(historical_policies or ())
    require(versions in allowed, 'Unreviewed qualification policy versions')
    for k in ('policy_sha256', 'rule_input_sha256', 'rule_group_sha256'): sha(record[k])
    for k in ('subject_did', 'bootstrap_id', 'evaluation_id', 'rule_id'): string(record[k])
    for k in ('evidence_id', 'operator_group', 'authenticity', 'correctness', 'reproducibility'): string(record[k], True)
    if record['scout_event_id'] is not None: decimal(record['scout_event_id'])
    keys(record['source_cut'], {'source_id', 'epoch', 'committed_event_id'})
    string(record['source_cut']['source_id']); string(record['source_cut']['epoch']); decimal(record['source_cut']['committed_event_id'])
    for k in ('same_operator', 'independent_reputation'):
        require(record[k] is None or type(record[k]) is bool, 'Invalid operator boolean')
    if record['operator_group'] == FAMILY or record['same_operator'] is True:
        require(record['operator_group'] == FAMILY and record['same_operator'] is True and record['independent_reputation'] is False, 'Invalid family qualification')
    return record


def first_key(record):
    return digest([record[k] for k in ('source_ref', 'subject_did', 'claim', 'qualification_type', 'policy_sha256', 'classifier_version', 'qualification_policy_version')])


def validate_event(event, prior, qualifications):
    keys(event, EVENT_KEYS)
    require(len(canonical(event)) <= 65536, 'Audit event too large')
    require(event['schema'] == 'router-qualification-event/v1' and event['qualification_policy_version'] == POLICY['qualification_policy_version'], 'Unsupported audit policy')
    require(event['event_id'] == identity('dqe1', {k:v for k,v in event.items() if k != 'event_id'}), 'Event ID hash mismatch')
    qid = event['qualification_id']
    require(qid in qualifications, 'Missing qualification target')
    require(type(event['sequence']) is int and event['sequence'] == len(prior)+1, 'Audit sequence fork or gap')
    require(event['previous_event_sha256'] == (prior[-1]['event_id'][5:] if prior else None), 'Audit chain mismatch')
    when = instant(event['recorded_at'])
    require(when >= instant(prior[-1]['recorded_at'] if prior else qualifications[qid]['qualified_at']), 'Regressed audit time')
    ordered_refs(event['proof_refs'], True); reference(event['authority_ref'], {'LOCAL_ARTIFACT', 'PROJECTED_MESSAGE'})
    if event['event_type'] == 'INVALIDATED':
        require(event['reason_code'] in REASONS and event['superseded_by'] is None, 'Invalid invalidation reason')
    elif event['event_type'] == 'SUPERSEDED':
        target = event['superseded_by']
        require(event['reason_code'] == 'NEW_QUALIFICATION' and target in qualifications and target != qid, 'Invalid supersession target')
        require(all(qualifications[qid][k] == qualifications[target][k] for k in ('subject_did', 'claim')), 'Supersession domain mismatch')
    else: raise ProjectionError('Unsupported audit transition (downgrade is not an event)')
    return event


def effective_status(events):
    return 'INVALIDATED' if any(e['event_type'] == 'INVALIDATED' for e in events) else 'VALID'
