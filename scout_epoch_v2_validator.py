"""Pure, deterministic Router-side validator for Scout epoch rollover V2."""
import hashlib
import json
import re

SCHEMA = 'flop-scout-router-epoch-rollover/v2'
REVISION = 'A1-EPOCH-V2'
MAX_INPUT_BYTES, MAX_DEPTH, MAX_STRING_BYTES = 65536, 16, 4096
MAX_LIST_ITEMS, MAX_MAP_ITEMS, MAX_EPOCH, MAX_INT = 256, 64, 9007199254740991, 9223372036854775807
DOMAINS = frozenset(('predecessor', 'archive-descriptor', 'retained-floor-declaration', 'mandatory-closure', 'durable-qualification-history', 'coverage-witnesses', 'permanent-pinned-evidence', 'omitted-history', 'complete-transition', 'a1-bridge-binding', 'bridge-watermarks', 'bridge-history', 'bridge-audit', 'verified-a1-bridge'))
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

def bounded(value, depth=0):
    if depth > MAX_DEPTH: fail('EPOCH_NESTING', 'JSON nesting exceeds the V2 limit')
    if value is None or type(value) is bool: return
    if type(value) is int:
        if not -MAX_INT <= value <= MAX_INT: fail('EPOCH_INTEGER_BOUNDS', 'integer exceeds the V2 limit')
    elif type(value) is str:
        try: size = len(value.encode('ascii'))
        except UnicodeEncodeError: fail('EPOCH_UNICODE', 'V2 strings must be ASCII')
        if size > MAX_STRING_BYTES: fail('EPOCH_STRING_BOUNDS', 'string exceeds the V2 limit')
    elif type(value) is list:
        if len(value) > MAX_LIST_ITEMS: fail('EPOCH_LIST_BOUNDS', 'array exceeds the V2 limit')
        for item in value: bounded(item, depth + 1)
    elif type(value) is dict:
        if len(value) > MAX_MAP_ITEMS: fail('EPOCH_MAP_BOUNDS', 'object exceeds the V2 limit')
        for key, item in value.items():
            if type(key) is not str: fail('EPOCH_TYPE', 'object key must be a string')
            bounded(key, depth + 1); bounded(item, depth + 1)
    else: fail('EPOCH_TYPE', 'unsupported JSON value')

def parse_json(data):
    if type(data) is not bytes or len(data) > MAX_INPUT_BYTES: fail('EPOCH_INPUT_BOUNDS', 'JSON input exceeds the V2 limit')
    try: text = data.decode('utf-8', 'strict')
    except UnicodeDecodeError: fail('EPOCH_UTF8', 'JSON input is not valid UTF-8')
    try: value = json.loads(text, object_pairs_hook=pairs, parse_float=bad_number, parse_constant=bad_number)
    except EpochV2Error: raise
    except (TypeError, ValueError, json.JSONDecodeError): fail('EPOCH_JSON', 'invalid JSON')
    bounded(value); return value

def canonical_json(value):
    bounded(value)
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')

def commitment(domain, value):
    if domain not in DOMAINS: fail('EPOCH_DOMAIN', 'commitment domain is not supported')
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

PRE = ('publication_id','content_id','manifest_sha256','artifact_sha256','artifact_size_bytes','epoch_id','epoch_number','source_cut','accepted_state_hash')
CUT = ('source_id','epoch','committed_event_id','cut_evidence_sha256')
ARCH = ('schema','archive_id','artifact_sha256','size_bytes','database_schema_version','locator','previous_epoch_id','previous_manifest_sha256','preservation','archive_commitment_sha256')
FLOOR = ('room','generation','domain','retained_floor','omitted_ranges')
FLOORS = ('entries','selection_policy_version','mandatory_proof_closure','mandatory_proof_closure_sha256','durable_qualification_history','durable_qualification_history_sha256','coverage_witnesses','coverage_witnesses_sha256','permanent_pinned_evidence','permanent_pinned_evidence_sha256','omitted_history','omitted_history_sha256','retained_floor_commitment_sha256')
ACTIVE = ('target','headroom','reserve','hard_max','mandatory_closure_count')
COMMITS = ('predecessor_sha256','archive_descriptor_sha256','retained_floor_declaration_sha256','mandatory_closure_sha256','durable_qualification_history_sha256','coverage_witnesses_sha256','permanent_pinned_evidence_sha256','transition_sha256')
ROOT = ('schema','contract_revision','epoch_number','epoch_id','created_at','source_binding','source_cut','predecessor','archive','retained_floor_commitment','active_epoch','commitments')

def validate_transition(value, accepted_predecessor, first_transition=False):
    bounded(value); obj(value, ROOT)
    if value['schema'] != SCHEMA or value['contract_revision'] != REVISION: fail('EPOCH_SCHEMA', 'unsupported epoch schema or revision')
    epoch = integer(value['epoch_number'], 'EPOCH_NUMBER', 1, MAX_EPOCH); ident(value['epoch_id'])
    if type(value['created_at']) is not str or not TIME.match(value['created_at']): fail('EPOCH_TIMESTAMP', 'timestamp is not canonical UTC RFC3339')
    source = value['source_binding']; obj(source, ('source_id','epoch','descriptor_sha256')); ident(source['source_id']); ident(source['epoch']); digest(source['descriptor_sha256'])
    cut = value['source_cut']; obj(cut, CUT); ident(cut['source_id']); ident(cut['epoch']); integer(cut['committed_event_id'], 'EPOCH_SOURCE_CUT'); digest(cut['cut_evidence_sha256'])
    if (cut['source_id'],cut['epoch']) != (source['source_id'],source['epoch']): fail('EPOCH_SOURCE_BINDING', 'source cut does not match source binding')
    pre = value['predecessor']; obj(pre, PRE)
    for key in ('publication_id','content_id','artifact_size_bytes'): integer(pre[key], 'EPOCH_PREDECESSOR')
    for key in ('manifest_sha256','artifact_sha256','accepted_state_hash'): digest(pre[key], 'EPOCH_PREDECESSOR')
    ident(pre['epoch_id'], 'EPOCH_PREDECESSOR'); integer(pre['epoch_number'], 'EPOCH_PREDECESSOR', 0, MAX_EPOCH); obj(pre['source_cut'], CUT)
    if pre != accepted_predecessor: fail('EPOCH_PREDECESSOR', 'candidate does not match accepted predecessor')
    if epoch != pre['epoch_number'] + 1: fail('EPOCH_REGRESSION', 'epoch number is not the next accepted epoch')
    if cut['committed_event_id'] < pre['source_cut']['committed_event_id']: fail('EPOCH_SOURCE_CUT', 'source cut regressed')
    if first_transition and (source['source_id'],source['epoch']) != (pre['source_cut']['source_id'],pre['source_cut']['epoch']): fail('EPOCH_FIRST_SOURCE_IDENTITY', 'first transition changed source identity')
    archive = value['archive']; obj(archive, ARCH)
    if archive['schema'] != 'flop-scout-epoch-archive/v1' or archive['preservation'] != 'IMMUTABLE_RETAINED': fail('EPOCH_ARCHIVE_SCHEMA', 'unsupported archive schema or preservation')
    ident(archive['archive_id']); digest(archive['artifact_sha256']); integer(archive['size_bytes'], 'EPOCH_ARCHIVE_BOUNDS', 1); text(archive['database_schema_version']); locator=text(archive['locator'])
    if len(locator)>256 or locator.startswith('/') or ':' in locator or '\\' in locator or '..' in locator.split('/'): fail('EPOCH_ARCHIVE_LOCATOR', 'archive locator is not safe')
    ident(archive['previous_epoch_id']); digest(archive['previous_manifest_sha256']); digest(archive['archive_commitment_sha256'])
    if archive['archive_commitment_sha256'] != commitment('archive-descriptor', without(archive, 'archive_commitment_sha256')): fail('EPOCH_ARCHIVE_HASH', 'archive descriptor commitment mismatch')
    if archive['previous_epoch_id'] != pre['epoch_id'] or archive['previous_manifest_sha256'] != pre['manifest_sha256']: fail('EPOCH_ARCHIVE_BINDING', 'archive is not bound to predecessor')
    floors=value['retained_floor_commitment']; obj(floors, FLOORS); last=None
    for item in floors['entries']:
        obj(item, FLOOR, 'EPOCH_FLOOR_FIELDS'); key=tuple(text(item[k], 'EPOCH_FLOOR_FIELDS') for k in ('room','generation','domain'))
        if last is not None and key <= last: fail('EPOCH_FLOOR_ORDER', 'floor domains must be sorted and unique')
        last=key
        if item['retained_floor'] is not None: integer(item['retained_floor'], 'EPOCH_RETAINED_FLOOR')
        prior=-1
        for pair in item['omitted_ranges']:
            if type(pair) is not list or len(pair)!=2: fail('EPOCH_OMISSION_RANGE', 'omission range is invalid')
            start=integer(pair[0], 'EPOCH_OMISSION_RANGE'); end=integer(pair[1], 'EPOCH_OMISSION_RANGE', start)
            if start<=prior: fail('EPOCH_OMISSION_ORDER', 'omission ranges must be sorted and disjoint')
            prior=end
    pairs=(('mandatory_proof_closure','mandatory_proof_closure_sha256','mandatory-closure'),('durable_qualification_history','durable_qualification_history_sha256','durable-qualification-history'),('coverage_witnesses','coverage_witnesses_sha256','coverage-witnesses'),('permanent_pinned_evidence','permanent_pinned_evidence_sha256','permanent-pinned-evidence'),('omitted_history','omitted_history_sha256','omitted-history'))
    for body, field, domain in pairs:
        digest(floors[field])
        if floors[field] != commitment(domain, floors[body]): fail('EPOCH_COMMITMENT', 'nested commitment mismatch')
    if floors['retained_floor_commitment_sha256'] != commitment('retained-floor-declaration', without(floors,'retained_floor_commitment_sha256')): fail('EPOCH_RETAINED_FLOOR', 'retained-floor commitment mismatch')
    active=value['active_epoch']; obj(active, ACTIVE); target=integer(active['target'],'EPOCH_CAPACITY',1,50000); headroom=integer(active['headroom'],'EPOCH_CAPACITY',1,50000); reserve=integer(active['reserve'],'EPOCH_CAPACITY',0,50000); hard=integer(active['hard_max'],'EPOCH_CAPACITY',1,50000); mandatory=integer(active['mandatory_closure_count'],'EPOCH_CAPACITY',0,50000)
    if hard != 50000 or target+headroom+reserve > hard or mandatory>target: fail('EPOCH_CAPACITY','invalid capacity arithmetic')
    commits=value['commitments']; obj(commits, COMMITS)
    expected={'predecessor_sha256':commitment('predecessor',pre),'archive_descriptor_sha256':commitment('archive-descriptor',without(archive,'archive_commitment_sha256')),'retained_floor_declaration_sha256':commitment('retained-floor-declaration',without(floors,'retained_floor_commitment_sha256')),'mandatory_closure_sha256':floors['mandatory_proof_closure_sha256'],'durable_qualification_history_sha256':floors['durable_qualification_history_sha256'],'coverage_witnesses_sha256':floors['coverage_witnesses_sha256'],'permanent_pinned_evidence_sha256':floors['permanent_pinned_evidence_sha256']}
    for key, expected_value in expected.items():
        if commits[key] != expected_value: fail('EPOCH_COMMITMENT','top-level commitment mismatch')
    complete=without(value,'commitments'); complete['commitments']=without(commits,'transition_sha256')
    if commits['transition_sha256'] != commitment('complete-transition',complete): fail('EPOCH_TRANSITION_HASH','transition commitment mismatch')
    return {'epoch_id':value['epoch_id'],'epoch_number':epoch,'source_cut':cut['committed_event_id'],'active_target':target}
