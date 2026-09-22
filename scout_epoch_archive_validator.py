"""Read-only, Router-side validator for a Scout legacy-A1 epoch archive.

This module deliberately has no Scout imports and has no write path.  Archive
capabilities are live objects bound to the bridge-validation session.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib, json, os, re, sqlite3, stat
from pathlib import Path

import scout_epoch_v2_validator as v2

ARCHIVE_SCHEMA='flop-scout-epoch-archive/v1'
RECOVERY_SCHEMA='scout-legacy-a1-provenance-recovery/v1'
SOURCE_SCHEMA='flop-scout-epoch-source-evidence/v1'
MAX_MEMBER=1024*1024*1024
HEX=re.compile(r'^[0-9a-f]{64}$')
ROLES={
 'bridge_projection_sqlite':('members/bridge-projection.sqlite','scout-router-projection/v2'),
 'legacy_recovery_json':('members/legacy-recovery.json',RECOVERY_SCHEMA),
 'source_evidence_sqlite':('members/source-evidence.sqlite',SOURCE_SCHEMA),
}

class ArchiveValidationError(ValueError):
    def __init__(self, code): self.code=code; super().__init__(code)
def fail(code): raise ArchiveValidationError(code)
def sha(raw): return hashlib.sha256(raw).hexdigest()
def canonical(value):
    try: return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    except (TypeError,ValueError,UnicodeError): fail('ARCHIVE_CANONICAL')
def digest(value, code='ARCHIVE_DESCRIPTOR'):
    if not isinstance(value,str) or not HEX.fullmatch(value): fail(code)
def exact(value, keys, code):
    if not isinstance(value,dict) or set(value)!=set(keys): fail(code)

def _a1_descriptor(value):
    """Canonicalize either the V2 bridge receipt form or retained A1 form."""
    if not isinstance(value,dict): fail('ARCHIVE_BRIDGE_MEMBER')
    if 'publication_sequence' in value:
        keys={'publication_sequence','content_id','manifest_sha256','artifact_sha256','artifact_size','source_kind','source_id','source_cut'}
        exact(value,keys,'ARCHIVE_BRIDGE_MEMBER')
        return {'publication_id':str(value['publication_sequence']),'content_id':str(value['content_id']),
                'manifest_sha256':value['manifest_sha256'],'artifact_sha256':value['artifact_sha256'],
                'artifact_size':value['artifact_size'],'source_checkpoint':{'source_id':value['source_id'],'epoch':value['source_kind'],'committed_event_id':str(value['source_cut'])}}
    keys={'publication_id','content_id','manifest_sha256','artifact_sha256','artifact_size','source_checkpoint'}
    exact(value,keys,'ARCHIVE_BRIDGE_MEMBER'); cp=value['source_checkpoint']
    exact(cp,{'source_id','epoch','committed_event_id'},'ARCHIVE_SOURCE_BINDING')
    for k in ('manifest_sha256','artifact_sha256'): digest(value[k],'ARCHIVE_BRIDGE_MEMBER')
    if type(value['artifact_size']) is not int or value['artifact_size']<1: fail('ARCHIVE_BRIDGE_MEMBER')
    return {'publication_id':str(value['publication_id']),'content_id':str(value['content_id']),
            'manifest_sha256':value['manifest_sha256'],'artifact_sha256':value['artifact_sha256'],
            'artifact_size':value['artifact_size'],'source_checkpoint':{'source_id':cp['source_id'],'epoch':cp['epoch'],'committed_event_id':str(cp['committed_event_id'])}}

def validate_format(descriptor, manifest, source_evidence=None):
    """Pure canonical descriptor/manifest validation, used for frozen vectors."""
    dkeys={'schema','archive_id','artifact_sha256','size_bytes','database_schema_version','locator','previous_epoch_id','previous_manifest_sha256','previous_bridge_binding_sha256','preservation'}
    exact(descriptor,dkeys,'ARCHIVE_DESCRIPTOR')
    if descriptor['schema']!=ARCHIVE_SCHEMA or descriptor['database_schema_version']!='flop-scout-epoch-archive-manifest/v1' or descriptor['preservation']!='IMMUTABLE_RETAINED': fail('ARCHIVE_DESCRIPTOR')
    for key in ('artifact_sha256','previous_manifest_sha256','previous_bridge_binding_sha256'): digest(descriptor[key])
    if not isinstance(descriptor['size_bytes'],int) or descriptor['size_bytes']<1: fail('ARCHIVE_DESCRIPTOR')
    if not _safe_locator(descriptor['locator']): fail('ARCHIVE_LOCATOR')
    mkeys={'schema','archive_id','accepted_anchor','bridge_predecessor','previous_bridge_binding_sha256','source_checkpoint','legacy_recovery','retention','members','manifest_commitment_sha256'}
    exact(manifest,mkeys,'ARCHIVE_DESCRIPTOR')
    if manifest['schema']!=ARCHIVE_SCHEMA or manifest['archive_id']!=descriptor['archive_id'] or manifest['retention']!='IMMUTABLE_INDEFINITE_FIRST_TRANSITION': fail('ARCHIVE_DESCRIPTOR')
    digest(manifest['previous_bridge_binding_sha256'],'ARCHIVE_SOURCE_BINDING')
    proof={k:x for k,x in manifest.items() if k!='manifest_commitment_sha256'}
    if manifest['manifest_commitment_sha256']!=sha(b'flop-scout/epoch-archive-manifest/v1\0'+canonical(proof)): fail('ARCHIVE_MANIFEST_HASH')
    members=manifest['members']
    if not isinstance(members,list) or len(members)!=3: fail('ARCHIVE_MEMBER_ROLE')
    pairs=[(x.get('role'),x.get('locator')) for x in members if isinstance(x,dict)]
    if pairs!=sorted(pairs): fail('ARCHIVE_MEMBER_ORDER')
    if {x.get('role') for x in members}!=set(ROLES): fail('ARCHIVE_MEMBER_ROLE')
    for x in members:
        role=x['role']; exact(x,{'role','locator','schema','sha256','size_bytes'},'ARCHIVE_MEMBER_ROLE')
        if x['schema']!=ROLES[role][1] or not _safe_locator(x['locator']): fail('ARCHIVE_MEMBER_ROLE' if x['schema']!=ROLES[role][1] else 'ARCHIVE_LOCATOR')
        digest(x['sha256'],'ARCHIVE_MEMBER_IO')
        if type(x['size_bytes']) is not int or x['size_bytes']<1: fail('ARCHIVE_MEMBER_IO')
    bridge=_a1_descriptor(manifest['bridge_predecessor'])
    if next(x for x in members if x['role']=='bridge_projection_sqlite')['sha256']!=bridge['artifact_sha256'] or next(x for x in members if x['role']=='bridge_projection_sqlite')['size_bytes']!=bridge['artifact_size']: fail('ARCHIVE_BRIDGE_MEMBER')
    if descriptor['artifact_sha256']!=sha(canonical(manifest)) or descriptor['size_bytes']!=len(canonical(manifest)): fail('ARCHIVE_MANIFEST_HASH')
    if descriptor['previous_manifest_sha256']!=bridge['manifest_sha256'] or descriptor['previous_bridge_binding_sha256']!=manifest['previous_bridge_binding_sha256']: fail('ARCHIVE_SOURCE_BINDING')
    # Archive checkpoints use one canonical wire schema; legacy/mixed aliases
    # are never interpreted by Router.
    exact(manifest['source_checkpoint'],{'source_id','source_epoch','source_cut'},'ARCHIVE_SOURCE_BINDING')
    rec=manifest['legacy_recovery']; exact(rec,{'schema','commitment_sha256','validated_records','closure_count'},'ARCHIVE_RECOVERY')
    if rec['schema']!=RECOVERY_SCHEMA: fail('ARCHIVE_RECOVERY')
    digest(rec['commitment_sha256'],'ARCHIVE_RECOVERY')
    if source_evidence is not None and (source_evidence.get('schema')!=SOURCE_SCHEMA or source_evidence.get('raw_record_count')!=rec['validated_records'] or source_evidence.get('observed_event_count')!=rec['validated_records']): fail('SOURCE_EVIDENCE_METADATA')
    return manifest

def _safe_locator(value):
    return isinstance(value,str) and value and not value.startswith('/') and '\\' not in value and ':' not in value and all(x not in ('','.', '..') for x in value.split('/'))

def _read_member(root, locator):
    if not _safe_locator(locator): fail('ARCHIVE_LOCATOR')
    root=Path(root)
    path=root.joinpath(*locator.split('/'))
    if path.parent.resolve()!=root.joinpath(*locator.split('/')[:-1]).resolve() or not path.resolve().is_relative_to(root.resolve()): fail('ARCHIVE_MEMBER_IO')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_MEMBER: fail('ARCHIVE_MEMBER_IO')
        data=b''.join(iter(lambda:os.read(fd,1024*1024),b'')); after=os.fstat(fd)
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) or len(data)!=before.st_size: fail('ARCHIVE_MEMBER_IO')
        return data
    finally: os.close(fd)

def _ro(path):
    c=sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True); c.row_factory=sqlite3.Row; c.execute('PRAGMA query_only=ON'); return c

def _raw_id(raw):
    envelope=json.loads(raw['raw_record_json'])
    return sha(json.dumps([raw['source'],raw['room'],raw['generation'],raw['reported_generation'],envelope],sort_keys=True,ensure_ascii=True,separators=(',',':')).encode())

def _recover(source_path, bridge_path, manifest):
    """Independent closure recomputation over held source-evidence rows."""
    s,p=_ro(source_path),_ro(bridge_path)
    try:
        if s.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or s.execute('PRAGMA foreign_key_check').fetchone() is not None: fail('SOURCE_EVIDENCE_INTEGRITY')
        names={r['name'] for r in s.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index') AND name NOT LIKE 'sqlite_%'")}
        required={'source_evidence_metadata','raw_records','observed_event_witnesses','compatibility_links','compatibility_links_by_raw','messages','evidence_records','tclk_frames','kibble_events'}
        if names!=required: fail('SOURCE_EVIDENCE_SCHEMA')
        meta=s.execute('SELECT * FROM source_evidence_metadata').fetchall()
        if len(meta)!=1 or meta[0]['schema']!=SOURCE_SCHEMA or meta[0]['revision']!='legacy-a1-recovery/1': fail('SOURCE_EVIDENCE_METADATA')
        m=dict(meta[0]);
        for key in ('accepted_anchor','bridge_predecessor','source_checkpoint'):
            if json.loads(m[key+'_json'])!=manifest[key]: fail('SOURCE_EVIDENCE_METADATA')
        if m['previous_bridge_binding_sha256']!=manifest['previous_bridge_binding_sha256']: fail('SOURCE_EVIDENCE_METADATA')
        prov={r['raw_record_id']:dict(r) for r in p.execute("SELECT * FROM source_provenance WHERE entity_type='message'")}
        rows=[dict(r) for r in s.execute('SELECT * FROM raw_records')]
        if len(rows)!=49808 or {r['raw_record_id'] for r in rows}!=set(prov): fail('SOURCE_EVIDENCE_RAW_SET')
        events={r['raw_record_id']:dict(r) for r in s.execute('SELECT * FROM observed_event_witnesses')}
        if len(events)!=len(rows): fail('SOURCE_EVIDENCE_REFERENCES')
        reasons={('sm1:'+rid):set() for rid in prov}
        record={}
        for raw in rows:
            rid=raw['raw_record_id']; pr=prov[rid]
            if _raw_id(raw)!=rid or sha(raw['raw_text'].encode())!=raw['raw_text_sha256'] or pr['projection_row_id']!='sm1:'+rid or pr['source_record_locator']!=rid or pr['raw_record_sha256'] is not None: fail('SOURCE_EVIDENCE_RAW_SET')
            ev=events.get(rid)
            if ev is None or ev['raw_text_sha256']!=raw['raw_text_sha256'] or str(ev['event_id'])!=str(pr['scout_event_id']): fail('SOURCE_EVIDENCE_REFERENCES')
            record[rid]={'raw_record_id':rid,'raw_text_sha256':raw['raw_text_sha256'],'scout_event_id':str(ev['event_id'])}
        links=s.execute('SELECT cache_table,cache_rowid,raw_record_id,raw_text_sha256 FROM compatibility_links').fetchall()
        if len(links)!=116201 or any(x['cache_table'] not in ('messages','evidence_records','tclk_frames','kibble_events') or x['raw_record_id'] not in record or x['raw_text_sha256']!=record[x['raw_record_id']]['raw_text_sha256'] for x in links): fail('SOURCE_EVIDENCE_REFERENCES')
        for row in p.execute("SELECT projection_row_id,retain_until,pin_roots_json,retention_class FROM selection_membership WHERE entity_type='message'"):
            if row['projection_row_id'] not in reasons: fail('RECOVERY_CLOSURE')
            if row['retain_until'] is None or json.loads(row['pin_roots_json']): reasons[row['projection_row_id']].add('permanent_or_pinned')
            if row['retention_class'] in ('TCLK_LIFECYCLE','WORK_LIFECYCLE'): reasons[row['projection_row_id']].add('tclk_or_work_lifecycle')
        for row in p.execute('SELECT record_json FROM durable_qualifications'):
            ref=json.loads(row[0]).get('source_ref',{}); pid=ref.get('id')
            if ref.get('kind')!='PROJECTED_MESSAGE' or pid not in reasons: fail('RECOVERY_CLOSURE')
            reasons[pid].add('durable_qualification')
        for row in p.execute('SELECT * FROM coverage_history'):
            rid=row['witness_source_locator']; pid='sm1:'+rid
            msg=p.execute('SELECT * FROM messages WHERE projection_row_id=?',(pid,)).fetchone()
            if rid not in record or msg is None or (msg['room'],msg['generation'],msg['seq'])!=(row['room'],row['generation'],row['max_ever_projected_seq']) or sha(canonical(dict(msg)))!=row['witness_record_sha256']: fail('RECOVERY_CLOSURE')
            reasons[pid].add('coverage_witness')
        closure=[{**record[rid],'reasons':sorted(reasons['sm1:'+rid])} for rid in record if reasons['sm1:'+rid]]
        bridge=_a1_descriptor(manifest['bridge_predecessor']); content={'content_id':bridge['content_id'],'manifest_sha256':bridge['manifest_sha256'],'artifact_sha256':bridge['artifact_sha256'],'source_id':bridge['source_checkpoint']['source_id'],'source_epoch':bridge['source_checkpoint']['epoch'],'committed_event_id':bridge['source_checkpoint']['committed_event_id']}
        proof=[{k:x[k] for k in ('raw_record_id','raw_text_sha256','scout_event_id')} for x in sorted(closure,key=lambda x:x['raw_record_id'])]
        commitment=sha(canonical({'domain':'scout/legacy-a1-provenance-recovery-closure/v1','content':content,'records':proof}))
        if len(closure)!=10427 or commitment!=m['recovery_commitment_sha256']: fail('ARCHIVE_RECOVERY')
        return len(rows),len(links),len(closure),commitment
    finally: s.close(); p.close()

@dataclass(frozen=True)
class VerifiedEpochArchive:
    _session: object; _token: object; bridge_receipt: object; descriptor: dict; manifest: dict; recovery_commitment: str; closure_count: int
    def __reduce__(self): raise TypeError('VerifiedEpochArchive is session-local and non-serializable')
    def __repr__(self): return '<VerifiedEpochArchive active=%s>' % self._session.active

def validate_archive(session, bridge_receipt, root):
    """Validate an archive without accepting, caching, or constructing profiles."""
    # Receipt identity and liveness remain mandatory; no particular publication
    # or real bridge hash is an authority for future validation sessions.
    from scout_projection import EpochValidationSession, VerifiedEpochBridge
    if (not isinstance(session, EpochValidationSession) or not isinstance(bridge_receipt, VerifiedEpochBridge)
            or not session.active or bridge_receipt._session is not session
            or bridge_receipt._token is not session.token):
        fail('ARCHIVE_BRIDGE_RECEIPT')
    try:
        binding = v2.bridge_binding(bridge_receipt.accepted_anchor, bridge_receipt.bridge_predecessor)
    except v2.EpochV2Error:
        fail('ARCHIVE_BRIDGE_RECEIPT')
    if bridge_receipt.bridge_binding != binding: fail('ARCHIVE_BRIDGE_RECEIPT')
    root=Path(root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir(): fail('ARCHIVE_MEMBER_IO')
    raw=_read_member(root,'manifest.json')
    try: manifest=json.loads(raw.decode())
    except Exception: fail('ARCHIVE_MANIFEST_HASH')
    # Descriptor is supplied by the V2 candidate normally; reconstruct it here from canonical manifest only for offline validation.
    descriptor={'schema':ARCHIVE_SCHEMA,'archive_id':manifest.get('archive_id'),'artifact_sha256':sha(raw),'size_bytes':len(raw),'database_schema_version':'flop-scout-epoch-archive-manifest/v1','locator':'archive/manifest.json','previous_epoch_id':'legacy-a1','previous_manifest_sha256':manifest.get('bridge_predecessor',{}).get('manifest_sha256'),'previous_bridge_binding_sha256':manifest.get('previous_bridge_binding_sha256'),'preservation':'IMMUTABLE_RETAINED'}
    validate_format(descriptor,manifest)
    if _a1_descriptor(manifest['accepted_anchor'])!=_a1_descriptor(bridge_receipt.accepted_anchor) or _a1_descriptor(manifest['bridge_predecessor'])!=_a1_descriptor(bridge_receipt.bridge_predecessor) or manifest['previous_bridge_binding_sha256']!=binding: fail('ARCHIVE_BRIDGE_RECEIPT')
    checkpoint=manifest['source_checkpoint']; bridge_checkpoint=_a1_descriptor(bridge_receipt.bridge_predecessor)['source_checkpoint']
    # A recovery archive may be attributed to a distinct source ID, but not a
    # distinct epoch or cut from the already verified bridge.
    if checkpoint['source_epoch']!=bridge_checkpoint['epoch'] or str(checkpoint['source_cut'])!=bridge_checkpoint['committed_event_id']: fail('ARCHIVE_SOURCE_BINDING')
    held={x['role']:_read_member(root,x['locator']) for x in manifest['members']}
    for x in manifest['members']:
        if sha(held[x['role']])!=x['sha256'] or len(held[x['role']])!=x['size_bytes']: fail('ARCHIVE_MEMBER_IO')
    records,links,closure,commitment=_recover(root/'members/source-evidence.sqlite',root/'members/bridge-projection.sqlite',manifest)
    recovery=json.loads(held['legacy_recovery_json'].decode())
    if recovery.get('validated_records')!=records or recovery.get('closure_count')!=closure or recovery.get('commitment')!=commitment or manifest['legacy_recovery']['commitment_sha256']!=commitment: fail('ARCHIVE_RECOVERY')
    return VerifiedEpochArchive(session,session.token,bridge_receipt,descriptor,manifest,commitment,closure)
