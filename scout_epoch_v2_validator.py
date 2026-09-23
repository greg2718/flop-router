"""Independent, pure Router validation of the frozen compact Scout Epoch V2 wire.

No acquisition, acceptance, profile construction, or persistent state changes.
Large plans have a separate bound; generic wire objects remain limited to 64 KiB.
"""
import hashlib
import json
import re

SCHEMA = 'flop-scout-router-epoch-rollover/v2'
REVISION = 'A1-EPOCH-V2'
MANIFEST_SCHEMA = 'flop-scout-router-snapshot/v2'
MAX_PLAN_BYTES, MAX_PLAN_RECORDS = 16 * 1024 * 1024, 50000
MAX_INPUT_BYTES, MAX_DEPTH, MAX_STRING_BYTES = 65536, 16, 4096
MAX_LIST_ITEMS, MAX_MAP_ITEMS, MAX_EPOCH, MAX_INT = 256, 64, 9007199254740991, 9223372036854775807
DOMAIN = re.compile(r'^[a-z][a-z0-9-]{0,63}$')
HEX = re.compile(r'^[0-9a-f]{64}$'); IDENTIFIER = re.compile(r'^[a-z][a-z0-9:._-]{0,128}$')
TIME = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$')


class EpochV2Error(ValueError):
    def __init__(self, code, message): self.code = code; super().__init__(message)


def fail(code, message): raise EpochV2Error(code, message)

def pairs(items):
    result = {}
    for key, value in items:
        if key in result: fail('EPOCH_DUPLICATE_KEY', 'duplicate JSON object key')
        result[key] = value
    return result

def bad_number(_value): fail('EPOCH_NUMBER', 'floating-point or non-finite JSON number')

def bounded(value, depth=0, *, plan=False):
    if depth > MAX_DEPTH: fail('EPOCH_PLAN_NESTING' if plan else 'EPOCH_NESTING', 'JSON nesting exceeds the V2 limit')
    if value is None or type(value) is bool: return
    if type(value) is int:
        if not -MAX_INT <= value <= MAX_INT: fail('EPOCH_INTEGER_BOUNDS', 'integer exceeds the V2 limit')
    elif type(value) is str:
        try: size = len(value.encode('ascii'))
        except UnicodeEncodeError: fail('EPOCH_UNICODE', 'V2 strings must be ASCII')
        if size > MAX_STRING_BYTES: fail('EPOCH_STRING_BOUNDS', 'string exceeds the V2 limit')
    elif type(value) is list:
        if len(value) > (MAX_PLAN_RECORDS if plan else MAX_LIST_ITEMS): fail('EPOCH_PLAN_BOUNDS' if plan else 'EPOCH_LIST_BOUNDS', 'array exceeds the V2 limit')
        for item in value: bounded(item, depth + 1, plan=plan)
    elif type(value) is dict:
        if len(value) > MAX_MAP_ITEMS: fail('EPOCH_PLAN_BOUNDS' if plan else 'EPOCH_MAP_BOUNDS', 'object exceeds the V2 limit')
        for key, item in value.items():
            if type(key) is not str: fail('EPOCH_PLAN_TYPE' if plan else 'EPOCH_TYPE', 'object key must be a string')
            bounded(key, depth + 1, plan=plan); bounded(item, depth + 1, plan=plan)
    else: fail('EPOCH_PLAN_TYPE' if plan else 'EPOCH_TYPE', 'unsupported JSON value')

def parse_json(data):
    if type(data) is not bytes or len(data) > MAX_INPUT_BYTES: fail('EPOCH_INPUT_BOUNDS', 'JSON input exceeds the V2 limit')
    try: text = data.decode('utf-8', 'strict')
    except UnicodeDecodeError: fail('EPOCH_UTF8', 'JSON input is not valid UTF-8')
    try: value = json.loads(text, object_pairs_hook=pairs, parse_float=bad_number, parse_constant=bad_number)
    except EpochV2Error: raise
    except (TypeError, ValueError, RecursionError): fail('EPOCH_JSON', 'invalid JSON')
    bounded(value); return value

def canonical_json(value):
    bounded(value)
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')

def commitment(domain, value):
    if type(domain) is not str or not DOMAIN.match(domain): fail('EPOCH_DOMAIN', 'invalid commitment domain')
    return hashlib.sha256(('flop-scout/epoch-v2/' + domain).encode('ascii') + b'\0' + canonical_json(value)).hexdigest()

def obj(value, fields, code='EPOCH_FIELDS'):
    if type(value) is not dict or set(value) != set(fields): fail(code, 'unexpected or missing object fields')
def text(value, code='EPOCH_TYPE'):
    if type(value) is not str: fail(code, 'field must be a string')
    bounded(value); return value
def digest(value, code='EPOCH_HASH'):
    if type(value) is not str or not HEX.match(value): fail(code, 'field must be a lower-case SHA-256 digest')
    return value
def ident(value, code='EPOCH_IDENTIFIER'):
    if type(value) is not str or not IDENTIFIER.match(value): fail(code, 'field must be a bounded identifier')
    return value
def integer(value, code='EPOCH_TYPE', low=0, high=MAX_INT):
    if type(value) is not int or not low <= value <= high: fail(code, 'field is outside the permitted integer range')
    return value
def without(value, field):
    result = dict(value); del result[field]; return result

DESCRIPTOR = ('publication_sequence','content_id','manifest_sha256','artifact_sha256','artifact_size','source_kind','source_id','source_cut')
CUT = ('source_id','epoch','committed_event_id','cut_evidence_sha256')
ARCH = ('schema','archive_id','artifact_sha256','size_bytes','database_schema_version','locator','previous_epoch_id','previous_manifest_sha256','previous_bridge_binding_sha256','preservation','archive_commitment_sha256')
FLOOR = ('room','generation','domain','retained_floor','omitted_ranges')
SET_DOMAINS = {
    'mandatory_proof_closure': 'mandatory-closure',
    'durable_qualification_history': 'durable-qualification-history',
    'coverage_witnesses': 'coverage-witnesses',
    'permanent_pinned_evidence': 'permanent-pinned-evidence',
    'omitted_history': 'omitted-history',
}
FLOORS = ('entries', 'selection_policy_version', 'retained_floor_commitment_sha256') + tuple(
    name + suffix for name in SET_DOMAINS for suffix in ('_count', '_sha256'))
ACTIVE = ('target','headroom','reserve','hard_max','mandatory_closure_count')
COMMITS = ('accepted_anchor_sha256','bridge_predecessor_sha256','bridge_binding_sha256','archive_descriptor_sha256','active_artifact_descriptor_sha256','active_set_plan_descriptor_sha256','retained_floor_declaration_sha256','mandatory_closure_sha256','durable_qualification_history_sha256','coverage_witnesses_sha256','permanent_pinned_evidence_sha256','transition_sha256')
ROOT = ('schema','contract_revision','epoch_number','epoch_id','created_at','source_binding','source_cut','accepted_anchor','bridge_predecessor','bridge_binding_sha256','active_artifact','active_set_plan','archive','retained_floor_commitment','active_epoch','commitments')


def descriptor(value):
    obj(value, DESCRIPTOR, 'EPOCH_DESCRIPTOR')
    for key in ('publication_sequence','content_id','artifact_size','source_cut'):
        integer(value[key], 'EPOCH_DESCRIPTOR')
    for key in ('manifest_sha256','artifact_sha256'):
        digest(value[key], 'EPOCH_DESCRIPTOR')
    text(value['source_kind'], 'EPOCH_DESCRIPTOR'); ident(value['source_id'], 'EPOCH_DESCRIPTOR')

def validate_transition(value, accepted_anchor, accepted_epoch_number=0, first_transition=False, publication_kind='CONTENT'):
    if publication_kind != 'CONTENT': fail('EPOCH_PUBLICATION_KIND', 'only content transitions are supported')
    bounded(value); obj(value, ROOT)
    if value['schema'] != SCHEMA or value['contract_revision'] != REVISION: fail('EPOCH_SCHEMA', 'unsupported epoch schema or revision')
    epoch = integer(value['epoch_number'], 'EPOCH_NUMBER', 1, MAX_EPOCH); ident(value['epoch_id'])
    if type(value['created_at']) is not str or not TIME.match(value['created_at']): fail('EPOCH_TIMESTAMP', 'timestamp is not canonical UTC RFC3339')
    source = value['source_binding']; obj(source, ('source_id','epoch','descriptor_sha256')); ident(source['source_id']); ident(source['epoch']); digest(source['descriptor_sha256'])
    cut = value['source_cut']; obj(cut, CUT); ident(cut['source_id']); ident(cut['epoch']); integer(cut['committed_event_id'], 'EPOCH_SOURCE_CUT'); digest(cut['cut_evidence_sha256'])
    if (cut['source_id'],cut['epoch']) != (source['source_id'],source['epoch']): fail('EPOCH_SOURCE_BINDING', 'source cut does not match source binding')
    anchor=value['accepted_anchor']; bridge=value['bridge_predecessor']; descriptor(anchor); descriptor(bridge)
    if type(accepted_anchor) is not dict or anchor != accepted_anchor: fail('EPOCH_ACCEPTED_ANCHOR', 'candidate does not match Router accepted anchor')
    digest(value['bridge_binding_sha256'], 'EPOCH_BRIDGE_BINDING')
    binding=bridge_binding(anchor, bridge)
    if value['bridge_binding_sha256'] != binding: fail('EPOCH_BRIDGE_BINDING', 'bridge identity binding mismatch')
    if type(accepted_epoch_number) is not int or epoch != accepted_epoch_number + 1: fail('EPOCH_REGRESSION', 'epoch number is not next accepted epoch')
    if (anchor['source_kind'],anchor['source_id']) != (bridge['source_kind'],bridge['source_id']) or anchor['source_cut'] > bridge['source_cut']: fail('EPOCH_BRIDGE_SOURCE', 'bridge source regressed or changed')
    if (source['epoch'],source['source_id']) != (bridge['source_kind'],bridge['source_id']): fail('EPOCH_SOURCE_BINDING', 'candidate source identity differs from bridge')
    if cut['committed_event_id'] < bridge['source_cut']: fail('EPOCH_SOURCE_CUT', 'source cut regressed')
    if first_transition and epoch != 1: fail('EPOCH_FIRST_TRANSITION', 'first transition must begin epoch one')
    if first_transition:
        if source != first_transition_source_binding(bridge, binding):
            fail('EPOCH_SOURCE_DESCRIPTOR', 'source descriptor differs from bridge authority')
        if cut['committed_event_id'] != bridge['source_cut']:
            fail('EPOCH_FIRST_SOURCE_CUT', 'first transition must use bridge cut')
        if cut != first_transition_source_cut(source, bridge, binding):
            fail('EPOCH_SOURCE_CUT_EVIDENCE', 'cut evidence differs from bridge authority')
    validate_active_artifact(value['active_artifact'])
    validate_plan_descriptor(value['active_set_plan'])
    archive = value['archive']; obj(archive, ARCH)
    if archive['schema'] != 'flop-scout-epoch-archive/v1' or archive['preservation'] != 'IMMUTABLE_RETAINED': fail('EPOCH_ARCHIVE_SCHEMA', 'unsupported archive schema or preservation')
    ident(archive['archive_id']); digest(archive['artifact_sha256']); integer(archive['size_bytes'], 'EPOCH_ARCHIVE_BOUNDS', 1); text(archive['database_schema_version']); locator=text(archive['locator'])
    if len(locator)>256 or locator.startswith('/') or ':' in locator or '\\' in locator or '..' in locator.split('/'): fail('EPOCH_ARCHIVE_LOCATOR', 'archive locator is not safe')
    ident(archive['previous_epoch_id']); digest(archive['previous_manifest_sha256']); digest(archive['previous_bridge_binding_sha256']); digest(archive['archive_commitment_sha256'])
    if archive['archive_commitment_sha256'] != commitment('archive-descriptor', without(archive, 'archive_commitment_sha256')): fail('EPOCH_ARCHIVE_HASH', 'archive descriptor commitment mismatch')
    if archive['previous_manifest_sha256'] != bridge['manifest_sha256'] or archive['previous_bridge_binding_sha256'] != binding: fail('EPOCH_ARCHIVE_BINDING', 'archive is not bound to bridge predecessor')
    floors=value['retained_floor_commitment']; validate_retained_floor(floors)
    active=value['active_epoch']; obj(active, ACTIVE); target=integer(active['target'],'EPOCH_CAPACITY',1,50000); headroom=integer(active['headroom'],'EPOCH_CAPACITY',1,50000); reserve=integer(active['reserve'],'EPOCH_CAPACITY',0,50000); hard=integer(active['hard_max'],'EPOCH_CAPACITY',1,50000); mandatory=integer(active['mandatory_closure_count'],'EPOCH_CAPACITY',0,50000)
    if hard != 50000 or target+headroom+reserve > hard or mandatory>target: fail('EPOCH_CAPACITY','invalid capacity arithmetic')
    if value['epoch_id'] != derive_epoch_id(value): fail('EPOCH_ID', 'epoch identity mismatch')
    commits=value['commitments']; obj(commits, COMMITS)
    expected={'accepted_anchor_sha256':commitment('accepted-anchor',anchor),'bridge_predecessor_sha256':commitment('bridge-predecessor',bridge),'bridge_binding_sha256':binding,'archive_descriptor_sha256':commitment('archive-descriptor',without(archive,'archive_commitment_sha256')),'active_artifact_descriptor_sha256':commitment('active-artifact-descriptor',value['active_artifact']),'active_set_plan_descriptor_sha256':commitment('active-set-plan-descriptor',value['active_set_plan']),'retained_floor_declaration_sha256':commitment('retained-floor-declaration',without(floors,'retained_floor_commitment_sha256')),'mandatory_closure_sha256':floors['mandatory_proof_closure_sha256'],'durable_qualification_history_sha256':floors['durable_qualification_history_sha256'],'coverage_witnesses_sha256':floors['coverage_witnesses_sha256'],'permanent_pinned_evidence_sha256':floors['permanent_pinned_evidence_sha256']}
    for key, expected_value in expected.items():
        digest(commits[key])
        if commits[key] != expected_value: fail('EPOCH_COMMITMENT','top-level commitment mismatch')
    digest(commits['transition_sha256'])
    complete=without(value,'commitments'); complete['commitments']=without(commits,'transition_sha256')
    if commits['transition_sha256'] != commitment('complete-transition',complete): fail('EPOCH_TRANSITION_HASH','transition commitment mismatch')
    return {'epoch_id':value['epoch_id'],'epoch_number':epoch,'source_cut':cut['committed_event_id'],'active_target':target}


ACTIVE_ARTIFACT = ('schema', 'content_id', 'locator', 'artifact_sha256', 'size_bytes', 'database_schema_version')
PLAN_DESCRIPTOR = ('schema', 'locator', 'sha256', 'size_bytes', 'plan_commitment_sha256', 'recovery_commitment_sha256')
PLAN_SCHEMA = 'flop-scout-epoch-active-set-plan/v1'
PLAN = ('schema', 'selection_policy_version', 'candidate_source', 'archive_descriptor_sha256',
        'recovery_commitment_sha256', 'retained_floor_commitment_sha256', 'omission_commitment_sha256',
        'capacity', 'selected', 'omitted', 'counts', 'plan_commitment_sha256')
PLAN_RECORD = ('projection_row_id', 'raw_record_id', 'raw_text_sha256', 'scout_event_id', 'reasons')
MANIFEST = ('schema', 'contract_revision', 'snapshot_id', 'publication_kind', 'database_content_id',
            'database', 'sha256', 'size_bytes', 'database_schema_version', 'selection_policy',
            'selection_policy_sha256', 'content_created_at', 'selection_evaluated_at', 'produced_at',
            'source_checkpoint', 'next_expiry_at', 'row_counts', 'watermarks', 'coverage_history', 'epoch_transition')
SIDECAR = ('schema', 'locator', 'sha256', 'size_bytes', 'transition_sha256')


def bridge_binding(accepted_anchor, bridge_predecessor):
    descriptor(accepted_anchor)
    descriptor(bridge_predecessor)
    return commitment('a1-bridge-binding', {
        'accepted_anchor': accepted_anchor, 'bridge_predecessor': bridge_predecessor})


def source_binding_descriptor(bridge_predecessor, bridge_binding_sha256):
    descriptor(bridge_predecessor)
    digest(bridge_binding_sha256, 'EPOCH_BRIDGE_BINDING')
    return commitment('source-binding-descriptor', {
        'schema': 'flop-scout-epoch-source-binding/v1',
        'source_id': bridge_predecessor['source_id'], 'epoch': bridge_predecessor['source_kind'],
        'bridge_binding_sha256': bridge_binding_sha256})


def first_transition_source_binding(bridge_predecessor, bridge_binding_sha256):
    digest_value = source_binding_descriptor(bridge_predecessor, bridge_binding_sha256)
    return {'source_id': bridge_predecessor['source_id'], 'epoch': bridge_predecessor['source_kind'],
            'descriptor_sha256': digest_value}


def source_cut_evidence(source_binding, bridge_predecessor, bridge_binding_sha256):
    obj(source_binding, ('source_id', 'epoch', 'descriptor_sha256'), 'EPOCH_SOURCE_BINDING')
    descriptor(bridge_predecessor)
    digest(bridge_binding_sha256, 'EPOCH_BRIDGE_BINDING')
    return commitment('source-cut-evidence', {
        'schema': 'flop-scout-epoch-source-cut-evidence/v1', 'source_binding': source_binding,
        'committed_event_id': bridge_predecessor['source_cut'], 'bridge_binding_sha256': bridge_binding_sha256})


def first_transition_source_cut(source_binding, bridge_predecessor, bridge_binding_sha256):
    evidence = source_cut_evidence(source_binding, bridge_predecessor, bridge_binding_sha256)
    return {'source_id': source_binding['source_id'], 'epoch': source_binding['epoch'],
            'committed_event_id': bridge_predecessor['source_cut'], 'cut_evidence_sha256': evidence}


def locator(value, code):
    text(value, code)
    if (not value or len(value) > 256 or value.startswith('/') or ':' in value or '\\' in value
            or any(part in ('.', '..') for part in value.split('/'))):
        fail(code, 'unsafe relative locator')


def validate_active_artifact(value):
    code = 'EPOCH_ACTIVE_ARTIFACT'
    obj(value, ACTIVE_ARTIFACT, code)
    if value['schema'] != 'scout-router-projection/v2' or value['database_schema_version'] != 'scout-router-projection/v2':
        fail(code, 'unsupported active database schema')
    integer(value['content_id'], code, 1)
    locator(value['locator'], code)
    digest(value['artifact_sha256'], code)
    integer(value['size_bytes'], code, 1)


def validate_plan_descriptor(value):
    code = 'EPOCH_ACTIVE_SET_PLAN'
    obj(value, PLAN_DESCRIPTOR, code)
    if value['schema'] != PLAN_SCHEMA: fail(code, 'unsupported plan schema')
    locator(value['locator'], code)
    for key in ('sha256', 'plan_commitment_sha256', 'recovery_commitment_sha256'):
        digest(value[key], code)
    integer(value['size_bytes'], code, 1, MAX_PLAN_BYTES)


def validate_retained_floor(value):
    obj(value, FLOORS)
    entries = value['entries']
    if type(entries) is not list or len(entries) > MAX_LIST_ITEMS:
        fail('EPOCH_FLOOR_BOUNDS', 'invalid retained-floor entries')
    last = None
    for entry in entries:
        obj(entry, FLOOR, 'EPOCH_FLOOR_FIELDS')
        key = tuple(text(entry[k], 'EPOCH_FLOOR_FIELDS') for k in ('room', 'generation', 'domain'))
        if last is not None and key <= last: fail('EPOCH_FLOOR_ORDER', 'floor domains must be sorted and unique')
        last = key
        if entry['retained_floor'] is not None: integer(entry['retained_floor'], 'EPOCH_RETAINED_FLOOR')
        ranges = entry['omitted_ranges']
        if type(ranges) is not list: fail('EPOCH_OMISSION_BOUNDS', 'omission ranges must be an array')
        prior = -1
        for pair in ranges:
            if type(pair) is not list or len(pair) != 2: fail('EPOCH_OMISSION_RANGE', 'invalid omission range')
            start = integer(pair[0], 'EPOCH_OMISSION_RANGE')
            end = integer(pair[1], 'EPOCH_OMISSION_RANGE', start)
            if start <= prior: fail('EPOCH_OMISSION_ORDER', 'omission ranges must be sorted and disjoint')
            prior = end
    text(value['selection_policy_version'])
    for name in SET_DOMAINS:
        integer(value[name + '_count'], 'EPOCH_FLOOR_BOUNDS', 0, MAX_PLAN_RECORDS)
        digest(value[name + '_sha256'])
    digest(value['retained_floor_commitment_sha256'])
    if value['retained_floor_commitment_sha256'] != commitment('retained-floor-declaration', without(value, 'retained_floor_commitment_sha256')):
        fail('EPOCH_RETAINED_FLOOR', 'retained-floor commitment mismatch')


def _plan_canonical(value):
    bounded(value, plan=True)
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def parse_active_set_plan(data):
    if type(data) is not bytes or not 1 <= len(data) <= MAX_PLAN_BYTES:
        fail('EPOCH_PLAN_BOUNDS', 'plan input exceeds the limit')
    try:
        value = json.loads(data.decode('utf-8', 'strict'), object_pairs_hook=pairs,
                           parse_float=bad_number, parse_constant=bad_number)
    except EpochV2Error:
        raise
    except (ValueError, TypeError, RecursionError):
        fail('EPOCH_PLAN_JSON', 'invalid plan JSON')
    bounded(value, plan=True)
    return value


def active_set_plan_commitment(value):
    return hashlib.sha256(b'flop-scout/epoch-v2/active-set-plan\0' + _plan_canonical(value)).hexdigest()


def bounded_commitment(domain, value):
    if type(domain) is not str or not DOMAIN.match(domain): fail('EPOCH_DOMAIN', 'invalid commitment domain')
    encoded = _plan_canonical(value)
    if type(value) is not list: fail('EPOCH_FLOOR_BOUNDS', 'compact sets must be arrays')
    identities = [_plan_canonical(row) for row in value]
    if identities != sorted(identities) or len(set(identities)) != len(identities):
        fail('EPOCH_FLOOR_ORDER', 'compact sets must be sorted and unique')
    return hashlib.sha256(('flop-scout/epoch-v2/' + domain).encode('ascii') + b'\0' + encoded).hexdigest()


def compact_retained_floor(entries, selection_policy_version, sets):
    obj(sets, SET_DOMAINS, 'EPOCH_RETAINED_FLOOR')
    result = {'entries': entries, 'selection_policy_version': selection_policy_version}
    for name, domain in SET_DOMAINS.items():
        rows = sets[name]
        if type(rows) is not list or len(rows) > MAX_PLAN_RECORDS: fail('EPOCH_FLOOR_BOUNDS', 'compact set exceeds limit')
        result[name + '_count'] = len(rows)
        result[name + '_sha256'] = bounded_commitment(domain, rows)
    result['retained_floor_commitment_sha256'] = commitment('retained-floor-declaration', result)
    validate_retained_floor(result)
    return result


def validate_active_set_plan(value, transition):
    bounded(value, plan=True)
    obj(value, PLAN, 'EPOCH_PLAN_FIELDS')
    if value['schema'] != PLAN_SCHEMA: fail('EPOCH_PLAN_SCHEMA', 'unsupported plan schema')
    text(value['selection_policy_version'], 'EPOCH_PLAN_BINDING')
    expected = {
        'candidate_source': {key: transition[key] for key in ('source_binding', 'source_cut')},
        'archive_descriptor_sha256': commitment('archive-descriptor', without(transition['archive'], 'archive_commitment_sha256')),
        'recovery_commitment_sha256': transition['active_set_plan']['recovery_commitment_sha256'],
        'retained_floor_commitment_sha256': transition['retained_floor_commitment']['retained_floor_commitment_sha256'],
        'omission_commitment_sha256': transition['retained_floor_commitment']['omitted_history_sha256'],
        'capacity': transition['active_epoch'],
    }
    if any(value[key] != expected_value for key, expected_value in expected.items()):
        fail('EPOCH_PLAN_BINDING', 'plan differs from transition')
    selected, omitted = value['selected'], value['omitted']
    if type(selected) is not list or type(omitted) is not list or len(selected) + len(omitted) > MAX_PLAN_RECORDS:
        fail('EPOCH_PLAN_BOUNDS', 'plan exceeds total record limit')
    seen = set()
    for row in selected + omitted:
        obj(row, PLAN_RECORD, 'EPOCH_PLAN_RECORD')
        ident(row['projection_row_id'], 'EPOCH_PLAN_RECORD')
        digest(row['raw_record_id'], 'EPOCH_PLAN_RECORD')
        digest(row['raw_text_sha256'], 'EPOCH_PLAN_RECORD')
        if type(row['scout_event_id']) is not str or not re.match(r'^[0-9]+$', row['scout_event_id']):
            fail('EPOCH_PLAN_RECORD', 'event ID must be decimal digits')
        reasons = row['reasons']
        if type(reasons) is not list or not reasons: fail('EPOCH_PLAN_RECORD', 'reasons must be nonempty')
        for reason in reasons: ident(reason, 'EPOCH_PLAN_RECORD')
        if reasons != sorted(set(reasons)): fail('EPOCH_PLAN_RECORD', 'reasons must be sorted and unique')
        seen.add(row['raw_record_id'])
    counts = {'selected': len(selected), 'omitted': len(omitted), 'eligible': len(selected) + len(omitted)}
    if len(seen) != counts['eligible'] or value['counts'] != counts:
        fail('EPOCH_PLAN_COUNTS', 'duplicate records or incorrect counts')
    digest(value['plan_commitment_sha256'], 'EPOCH_PLAN_COMMITMENT')
    if value['plan_commitment_sha256'] != active_set_plan_commitment(without(value, 'plan_commitment_sha256')):
        fail('EPOCH_PLAN_COMMITMENT', 'plan logical commitment mismatch')
    return value


def validate_active_set_plan_bytes(data, transition):
    validate_plan_descriptor(transition['active_set_plan'])
    desc = transition['active_set_plan']
    if type(data) is not bytes or len(data) != desc['size_bytes'] or hashlib.sha256(data).hexdigest() != desc['sha256']:
        fail('EPOCH_PLAN_BYTES', 'plan transport bytes mismatch')
    value = validate_active_set_plan(parse_active_set_plan(data), transition)
    if value['plan_commitment_sha256'] != desc['plan_commitment_sha256']:
        fail('EPOCH_PLAN_BINDING', 'plan logical identity mismatch')
    return value


def epoch_identity(value):
    """Frozen identity view; plan transport bytes and active locators are excluded."""
    result = {key: value[key] for key in ('schema', 'contract_revision', 'epoch_number',
              'accepted_anchor', 'bridge_predecessor', 'bridge_binding_sha256')}
    result['candidate_source'] = {key: value[key] for key in ('source_binding', 'source_cut')}
    result['active_artifact'] = {key: value['active_artifact'][key] for key in
                                ('schema', 'content_id', 'artifact_sha256', 'size_bytes', 'database_schema_version')}
    result['active_set_plan'] = {key: value['active_set_plan'][key] for key in
                                ('schema', 'plan_commitment_sha256', 'recovery_commitment_sha256')}
    result['archive'] = {key: value['archive'][key] for key in
                         ('archive_id', 'artifact_sha256', 'size_bytes', 'database_schema_version',
                          'previous_epoch_id', 'previous_manifest_sha256', 'previous_bridge_binding_sha256', 'archive_commitment_sha256')}
    floors = value['retained_floor_commitment']
    result['capacity_policy'] = dict(value['active_epoch'], selection_policy_version=floors['selection_policy_version'])
    result['retained_floor_commitment_sha256'] = floors['retained_floor_commitment_sha256']
    result['omission_commitment_sha256'] = floors['omitted_history_sha256']
    return result


def derive_epoch_id(value):
    return 'se2:' + commitment('epoch-id', epoch_identity(value))


def transition_commitment(value):
    complete = without(value, 'commitments')
    complete['commitments'] = without(value['commitments'], 'transition_sha256')
    return commitment('complete-transition', complete)


def validate_transition_descriptor(value):
    code = 'EPOCH_MANIFEST_TRANSITION'
    obj(value, SIDECAR, code)
    if value['schema'] != SCHEMA: fail(code, 'unsupported transition schema')
    locator(value['locator'], code)
    digest(value['sha256'], code)
    integer(value['size_bytes'], code, 1, MAX_INPUT_BYTES)
    digest(value['transition_sha256'], code)


def validate_v2_manifest(value, transition):
    """Pure content binding only; ordinary database acceptance is still disabled."""
    bounded(value)
    obj(value, MANIFEST, 'EPOCH_MANIFEST_FIELDS')
    if value['schema'] != MANIFEST_SCHEMA or value['contract_revision'] != REVISION:
        fail('EPOCH_MANIFEST_SCHEMA', 'unsupported manifest schema or revision')
    if value['publication_kind'] != 'CONTENT': fail('EPOCH_PUBLICATION_KIND', 'only content manifests are supported')
    integer(value['snapshot_id'], 'EPOCH_MANIFEST')
    integer(value['database_content_id'], 'EPOCH_MANIFEST', 1)
    locator(value['database'], 'EPOCH_MANIFEST')
    digest(value['sha256'], 'EPOCH_MANIFEST')
    integer(value['size_bytes'], 'EPOCH_MANIFEST', 1)
    if value['database_schema_version'] != 'scout-router-projection/v2': fail('EPOCH_MANIFEST', 'unsupported database schema')
    validate_transition_descriptor(value['epoch_transition'])
    validate_active_artifact(transition['active_artifact'])
    mapping = {'database_content_id': 'content_id', 'database': 'locator', 'sha256': 'artifact_sha256',
               'size_bytes': 'size_bytes', 'database_schema_version': 'database_schema_version'}
    if any(value[key] != transition['active_artifact'][target] for key, target in mapping.items()):
        fail('EPOCH_MANIFEST_BINDING', 'manifest artifact differs from transition')
    if value['epoch_transition']['transition_sha256'] != transition['commitments']['transition_sha256']:
        fail('EPOCH_MANIFEST_BINDING', 'manifest transition commitment mismatch')
    return value


def validate_transition_bytes(data, sidecar, accepted_anchor, accepted_epoch_number=0, first_transition=False):
    """Validate a held sidecar without reading its locator or accepting its content."""
    validate_transition_descriptor(sidecar)
    if type(data) is not bytes or len(data) != sidecar['size_bytes'] or hashlib.sha256(data).hexdigest() != sidecar['sha256']:
        fail('EPOCH_TRANSITION_BYTES', 'transition transport bytes mismatch')
    value = parse_json(data)
    validate_transition(value, accepted_anchor, accepted_epoch_number, first_transition)
    if value['commitments']['transition_sha256'] != sidecar['transition_sha256']:
        fail('EPOCH_MANIFEST_BINDING', 'sidecar logical commitment mismatch')
    return value


# Fresh-cut and continuation roots.  These are intentionally separate from the
# historical A1 bridge schema above: Router accepts neither shape through the
# other validator, and this module imports no Scout implementation.
FRESH_SNAPSHOT = ('schema', 'locator', 'sha256', 'size_bytes',
                  'sqlite_schema_sha256', 'semantic_checkpoint_sha256')
FRESH_AUTHORITY = ('schema', 'source_id', 'epoch', 'committed_event_id',
                   'snapshot', 'snapshot_checkpoint_sha256',
                   'bridge_binding_sha256', 'authority_sha256')
FRESH_PAYLOAD = ('schema', 'publication_id', 'content_id', 'source_id',
                 'source_epoch', 'source_cut', 'created_at',
                 'selection_policy_sha256', 'archive', 'plan',
                 'active_artifact', 'retained_floor', 'accepted_anchor',
                 'bridge_predecessor', 'bridge_binding_sha256',
                 'fresh_cut_authority', 'epoch_id')
SUCCESSOR_PAYLOAD = ('schema', 'publication_id', 'content_id', 'source_id',
                     'source_epoch', 'source_cut', 'created_at',
                     'selection_policy_sha256', 'archive', 'plan',
                     'active_artifact', 'retained_floor', 'predecessor',
                     'epoch_id')
FRESH_ROOT = ('schema', 'payload', 'transition_sha256')
SUCCESSOR_ROOT = FRESH_ROOT
ACCEPTED_PREDECESSOR = ('schema', 'publication_id', 'content_id', 'epoch_id',
                        'manifest_sha256', 'transition_sha256',
                        'artifact_sha256', 'artifact_size', 'source_id',
                        'source_epoch', 'source_cut', 'selection_policy_sha256',
                        'archive_commitment_sha256',
                        'retained_floor_commitment_sha256')


def _time(value, code):
    if type(value) is not str or not TIME.match(value):
        fail(code, 'timestamp is not canonical UTC RFC3339')
    return value


def fresh_cut_authority_commitment(value):
    fields = tuple(key for key in FRESH_AUTHORITY if key != 'authority_sha256')
    obj(value, fields if 'authority_sha256' not in value else FRESH_AUTHORITY,
        'EPOCH_FRESH_AUTHORITY_FIELDS')
    body = dict(value); body.pop('authority_sha256', None)
    return commitment('fresh-cut-authority', body)


def fresh_first_payload_identity(value):
    obj(value, FRESH_PAYLOAD, 'EPOCH_FRESH_PAYLOAD_FIELDS')
    return commitment('fresh-first-payload',
                      {key: item for key, item in value.items() if key != 'epoch_id'})


def successor_payload_identity(value):
    obj(value, SUCCESSOR_PAYLOAD, 'EPOCH_SUCCESSOR_PAYLOAD_FIELDS')
    return commitment('content-successor-payload',
                      {key: item for key, item in value.items() if key != 'epoch_id'})


def validate_active_artifact_bytes(descriptor_value, data):
    validate_active_artifact(descriptor_value)
    if (type(data) is not bytes or len(data) != descriptor_value['size_bytes'] or
            hashlib.sha256(data).hexdigest() != descriptor_value['artifact_sha256']):
        fail('EPOCH_ARTIFACT_BYTES', 'active-artifact transport differs')
    return descriptor_value


def validate_plan_descriptor_bytes(descriptor_value, data):
    validate_plan_descriptor(descriptor_value)
    if (type(data) is not bytes or len(data) != descriptor_value['size_bytes'] or
            hashlib.sha256(data).hexdigest() != descriptor_value['sha256']):
        fail('EPOCH_PLAN_BYTES', 'plan transport differs')
    plan = parse_active_set_plan(data)
    obj(plan, PLAN, 'EPOCH_PLAN_FIELDS')
    if plan['schema'] != PLAN_SCHEMA:
        fail('EPOCH_PLAN_SCHEMA', 'unsupported plan schema')
    digest(plan['plan_commitment_sha256'], 'EPOCH_PLAN_COMMITMENT')
    if (plan['plan_commitment_sha256'] != descriptor_value['plan_commitment_sha256'] or
            active_set_plan_commitment(without(plan, 'plan_commitment_sha256')) !=
            descriptor_value['plan_commitment_sha256']):
        fail('EPOCH_PLAN_COMMITMENT', 'plan logical commitment differs')
    return plan


def validate_archive_descriptor(descriptor_value):
    obj(descriptor_value, ARCH, 'EPOCH_ARCHIVE_FIELDS')
    if (descriptor_value['schema'] != 'flop-scout-epoch-archive/v1' or
            descriptor_value['preservation'] != 'IMMUTABLE_RETAINED'):
        fail('EPOCH_ARCHIVE_SCHEMA', 'unsupported archive schema or retention')
    ident(descriptor_value['archive_id'], 'EPOCH_ARCHIVE'); digest(
        descriptor_value['artifact_sha256'], 'EPOCH_ARCHIVE')
    integer(descriptor_value['size_bytes'], 'EPOCH_ARCHIVE_BOUNDS', 1)
    text(descriptor_value['database_schema_version'], 'EPOCH_ARCHIVE')
    locator(descriptor_value['locator'], 'EPOCH_ARCHIVE_LOCATOR')
    ident(descriptor_value['previous_epoch_id'], 'EPOCH_ARCHIVE')
    for key in ('previous_manifest_sha256', 'previous_bridge_binding_sha256',
                'archive_commitment_sha256'):
        digest(descriptor_value[key], 'EPOCH_ARCHIVE')
    if descriptor_value['archive_commitment_sha256'] != commitment(
            'archive-descriptor', without(descriptor_value, 'archive_commitment_sha256')):
        fail('EPOCH_ARCHIVE_HASH', 'archive descriptor commitment differs')
    return descriptor_value


def validate_archive_descriptor_bytes(descriptor_value, data):
    validate_archive_descriptor(descriptor_value)
    if (type(data) is not bytes or len(data) != descriptor_value['size_bytes'] or
            hashlib.sha256(data).hexdigest() != descriptor_value['artifact_sha256']):
        fail('EPOCH_ARCHIVE_BYTES', 'archive transport differs')
    return descriptor_value


def validate_accepted_predecessor(value):
    obj(value, ACCEPTED_PREDECESSOR, 'EPOCH_SUCCESSOR_PREDECESSOR')
    if value['schema'] != 'flop-scout-epoch-accepted-predecessor/v1':
        fail('EPOCH_SUCCESSOR_PREDECESSOR', 'unsupported predecessor schema')
    for key in ('publication_id', 'content_id', 'artifact_size', 'source_cut'):
        integer(value[key], 'EPOCH_SUCCESSOR_PREDECESSOR', 1)
    for key in ('manifest_sha256', 'transition_sha256', 'artifact_sha256',
                'selection_policy_sha256', 'archive_commitment_sha256',
                'retained_floor_commitment_sha256'):
        digest(value[key], 'EPOCH_SUCCESSOR_PREDECESSOR')
    for key in ('epoch_id', 'source_id', 'source_epoch'):
        ident(value[key], 'EPOCH_SUCCESSOR_PREDECESSOR')
    return value


def validate_fresh_cut_authority(value, bridge_predecessor, bridge_binding_sha256):
    obj(value, FRESH_AUTHORITY, 'EPOCH_FRESH_AUTHORITY_FIELDS')
    if value['schema'] != 'flop-scout-epoch-fresh-cut-authority/v1':
        fail('EPOCH_FRESH_AUTHORITY_SCHEMA', 'unsupported fresh authority schema')
    ident(value['source_id'], 'EPOCH_FRESH_AUTHORITY'); ident(value['epoch'], 'EPOCH_FRESH_AUTHORITY')
    integer(value['committed_event_id'], 'EPOCH_FRESH_AUTHORITY', 1)
    obj(value['snapshot'], FRESH_SNAPSHOT, 'EPOCH_FRESH_SNAPSHOT_FIELDS')
    snapshot = value['snapshot']
    if snapshot['schema'] != 'flop-scout-epoch-source-snapshot/v1':
        fail('EPOCH_FRESH_SNAPSHOT_SCHEMA', 'unsupported snapshot schema')
    locator(snapshot['locator'], 'EPOCH_FRESH_SNAPSHOT')
    integer(snapshot['size_bytes'], 'EPOCH_FRESH_SNAPSHOT', 1, MAX_INPUT_BYTES)
    for key in ('sha256', 'sqlite_schema_sha256', 'semantic_checkpoint_sha256'):
        digest(snapshot[key], 'EPOCH_FRESH_SNAPSHOT')
    for key in ('snapshot_checkpoint_sha256', 'bridge_binding_sha256', 'authority_sha256'):
        digest(value[key], 'EPOCH_FRESH_AUTHORITY')
    if value['snapshot_checkpoint_sha256'] != snapshot['semantic_checkpoint_sha256']:
        fail('EPOCH_FRESH_CHECKPOINT', 'snapshot checkpoint differs')
    if value['bridge_binding_sha256'] != bridge_binding_sha256:
        fail('EPOCH_FRESH_BRIDGE', 'bridge binding differs')
    if (value['source_id'], value['epoch']) != (
            bridge_predecessor['source_id'], bridge_predecessor['source_kind']):
        fail('EPOCH_FRESH_SOURCE', 'fresh source identity differs')
    if value['committed_event_id'] <= bridge_predecessor['source_cut']:
        fail('EPOCH_FRESH_CUT', 'fresh source cut must advance bridge cut')
    if value['authority_sha256'] != fresh_cut_authority_commitment(value):
        fail('EPOCH_FRESH_AUTHORITY', 'fresh authority commitment differs')
    return value


def validate_fresh_first_payload(value):
    obj(value, FRESH_PAYLOAD, 'EPOCH_FRESH_PAYLOAD_FIELDS')
    if value['schema'] != 'flop-scout-epoch-fresh-first-payload/v1':
        fail('EPOCH_FRESH_PAYLOAD_SCHEMA', 'unsupported fresh payload schema')
    for key in ('publication_id', 'content_id', 'source_cut'):
        integer(value[key], 'EPOCH_FRESH_PAYLOAD', 1)
    ident(value['source_id'], 'EPOCH_FRESH_PAYLOAD'); ident(value['source_epoch'], 'EPOCH_FRESH_PAYLOAD')
    digest(value['selection_policy_sha256'], 'EPOCH_FRESH_PAYLOAD')
    _time(value['created_at'], 'EPOCH_FRESH_TIMESTAMP')
    descriptor(value['accepted_anchor']); descriptor(value['bridge_predecessor'])
    digest(value['bridge_binding_sha256'], 'EPOCH_BRIDGE_BINDING')
    binding = bridge_binding(value['accepted_anchor'], value['bridge_predecessor'])
    if value['bridge_binding_sha256'] != binding:
        fail('EPOCH_BRIDGE_BINDING', 'bridge identity binding differs')
    validate_active_artifact(value['active_artifact']); validate_plan_descriptor(value['plan'])
    archive = validate_archive_descriptor(value['archive'])
    if (archive['previous_manifest_sha256'] != value['bridge_predecessor']['manifest_sha256'] or
            archive['previous_bridge_binding_sha256'] != binding):
        fail('EPOCH_ARCHIVE_BINDING', 'archive is not bound to bridge')
    validate_retained_floor(value['retained_floor'])
    validate_fresh_cut_authority(value['fresh_cut_authority'], value['bridge_predecessor'], binding)
    if value['source_cut'] != value['fresh_cut_authority']['committed_event_id']:
        fail('EPOCH_FRESH_CUT', 'payload cut differs from authority')
    if (value['source_id'], value['source_epoch']) != (
            value['fresh_cut_authority']['source_id'], value['fresh_cut_authority']['epoch']):
        fail('EPOCH_FRESH_SOURCE', 'payload source differs from authority')
    if value['epoch_id'] != 'se2:' + fresh_first_payload_identity(value):
        fail('EPOCH_FRESH_EPOCH', 'fresh epoch identity differs')
    return value


def validate_fresh_first_transition(value, accepted_anchor, publication_kind='CONTENT'):
    if publication_kind != 'CONTENT':
        fail('EPOCH_PUBLICATION_KIND', 'heartbeats are not accepted')
    obj(value, FRESH_ROOT, 'EPOCH_FRESH_FIRST_FIELDS')
    if value['schema'] != 'flop-scout-epoch-fresh-first-transition/v1':
        fail('EPOCH_FRESH_FIRST_SCHEMA', 'unsupported fresh root schema')
    payload = validate_fresh_first_payload(value['payload'])
    if payload['accepted_anchor'] != accepted_anchor:
        fail('EPOCH_FRESH_PREDECESSOR', 'accepted anchor differs')
    if value['transition_sha256'] != commitment('fresh-first-transition', payload):
        fail('EPOCH_FRESH_TRANSITION', 'fresh root commitment differs')
    return payload


def validate_content_successor(value, accepted_predecessor, publication_kind='CONTENT'):
    if publication_kind != 'CONTENT':
        fail('EPOCH_PUBLICATION_KIND', 'heartbeats are not accepted')
    obj(value, SUCCESSOR_ROOT, 'EPOCH_SUCCESSOR_FIELDS')
    if value['schema'] != 'flop-scout-epoch-content-successor/v1':
        fail('EPOCH_SUCCESSOR_SCHEMA', 'unsupported successor root schema')
    predecessor = validate_accepted_predecessor(accepted_predecessor)
    payload = value['payload']
    obj(payload, SUCCESSOR_PAYLOAD, 'EPOCH_SUCCESSOR_PAYLOAD_FIELDS')
    if payload['schema'] != 'flop-scout-epoch-content-successor-payload/v1':
        fail('EPOCH_SUCCESSOR_PAYLOAD_SCHEMA', 'unsupported successor payload schema')
    if payload['predecessor'] != predecessor:
        fail('EPOCH_SUCCESSOR_GAP', 'accepted predecessor differs')
    for key in ('publication_id', 'content_id', 'source_cut'):
        integer(payload[key], 'EPOCH_SUCCESSOR_PAYLOAD', 1)
    _time(payload['created_at'], 'EPOCH_SUCCESSOR_TIMESTAMP')
    if (payload['publication_id'] <= predecessor['publication_id'] or
            payload['content_id'] <= predecessor['content_id'] or
            payload['source_cut'] <= predecessor['source_cut']):
        fail('EPOCH_SUCCESSOR_ROLLBACK', 'successor did not advance')
    if payload['epoch_id'] != predecessor['epoch_id']:
        fail('EPOCH_SUCCESSOR_EPOCH', 'successor epoch differs')
    for key in ('source_id', 'source_epoch', 'selection_policy_sha256'):
        if payload[key] != predecessor[key]:
            fail('EPOCH_SUCCESSOR_CONTINUITY', 'protected identity differs')
    digest(payload['selection_policy_sha256'], 'EPOCH_SUCCESSOR_PAYLOAD')
    validate_active_artifact(payload['active_artifact']); validate_plan_descriptor(payload['plan'])
    archive = validate_archive_descriptor(payload['archive'])
    if archive['archive_commitment_sha256'] != predecessor['archive_commitment_sha256']:
        fail('EPOCH_SUCCESSOR_CONTINUITY', 'archive identity differs')
    validate_retained_floor(payload['retained_floor'])
    if payload['retained_floor']['retained_floor_commitment_sha256'] != predecessor['retained_floor_commitment_sha256']:
        fail('EPOCH_SUCCESSOR_CONTINUITY', 'retained-floor identity differs')
    if value['transition_sha256'] != commitment('content-successor-transition', payload):
        fail('EPOCH_SUCCESSOR_TRANSITION', 'successor root commitment differs')
    return payload
