"""Explicit, disposable-only Epoch V2 acceptance. Production dispatch is unchanged."""
from contextlib import closing
from datetime import datetime, timezone
import copy
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import time

import projection_contract as c
import scout_epoch_archive_validator as archive
import scout_epoch_evidence as evidence
import scout_epoch_v2_validator as v2
from scout_epoch_store import DisposableEpochStore
from scout_projection import ProjectionReader, coverage, require
from scout_snapshot import SnapshotError, utc_timestamp


def _initial(path, limit):
    """Bounded bootstrap read; subsequently retained by HeldInputs at this hash."""
    fd = evidence.open_held(path)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit, 'EPOCH_INPUT_BOUNDS')
        raw = bytearray()
        while len(raw) <= limit:
            chunk = os.read(fd, min(1024 * 1024, limit + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        require(len(raw) == info.st_size, 'EPOCH_INPUT_CHANGED')
        return bytes(raw)
    finally:
        os.close(fd)


def _path(root, locator):
    require(archive._safe_locator(locator), 'EPOCH_INPUT_LOCATOR')
    return root.joinpath(*locator.split('/'))


def _publication(held, root, stage, expected=None):
    try:
        pointer_raw = _initial(root / 'current.json', 65536)
    except FileNotFoundError:
        if expected is not None:
            raise SnapshotError('EPOCH_EXACT_BRIDGE_POINTER_UNAVAILABLE') from None
        raise
    pointer_raw = held.read(root / 'current.json', evidence.sha(pointer_raw), len(pointer_raw), 65536)
    pointer = c.loads(pointer_raw, 65536)
    c.keys(pointer, {'schema', 'manifest', 'manifest_sha256', 'published_at'})
    require(pointer['schema'] == 'flop-scout-router-current/v2', 'UNSUPPORTED_REVISION')
    c.sha(pointer['manifest_sha256'])
    if expected is not None:
        require(pointer['manifest_sha256'] == expected['manifest_sha256'], 'EPOCH_EXACT_BRIDGE_MANIFEST_UNAVAILABLE')
    manifest_path = _path(root, pointer['manifest'])
    try:
        raw = _initial(manifest_path, v2.MAX_INPUT_BYTES)
    except FileNotFoundError:
        if expected is not None:
            raise SnapshotError('EPOCH_EXACT_BRIDGE_MANIFEST_UNAVAILABLE') from None
        raise
    raw = held.read(manifest_path, pointer['manifest_sha256'], len(raw), v2.MAX_INPUT_BYTES)
    manifest = c.loads(raw, v2.MAX_INPUT_BYTES)
    require(pointer['manifest'] == f"manifest-v2-{manifest['snapshot_id']}-{evidence.sha(raw)}.json", 'MANIFEST_FILENAME_ID_MISMATCH')
    stage.mkdir(mode=0o700)
    (stage / 'current.json').write_bytes(pointer_raw)
    (stage / pointer['manifest']).write_bytes(raw)
    return pointer, manifest


def _metadata(reader, pointer, manifest, transition, previous, now):
    """Validate A1 metadata semantics without inventing any transport bytes."""
    m = copy.deepcopy(manifest)
    require(m['selection_policy'] == c.POLICY and m['selection_policy_sha256'] == c.POLICY_SHA, 'UNSUPPORTED_POLICY')
    require(m['snapshot_id'] > int(previous['snapshot_id']) and
            m['database_content_id'] > int(previous['database_content_id']), 'CONTINUITY_CONTENT_ROLLBACK')
    times = {k: utc_timestamp(m[k]) for k in ('content_created_at', 'selection_evaluated_at', 'produced_at')}
    published = utc_timestamp(pointer['published_at'])
    require(times['content_created_at'] <= times['selection_evaluated_at'] == times['produced_at'] <= published
            and (published - now).total_seconds() <= 60, 'INVALID_PUBLICATION_TIME')
    require((now - times['produced_at']).total_seconds() <= 3600, 'SNAPSHOT_STALE')
    require(m['content_created_at'] == transition['created_at'], 'EPOCH_CONTENT_TIME')
    for key in times:
        require(times[key] >= utc_timestamp(previous['manifest'][key]), 'CONTINUITY_TIME_ROLLBACK')
    require(published >= utc_timestamp(previous['published_at']), 'CONTINUITY_PUBLICATION_TIME_ROLLBACK')
    cut = transition['source_cut']
    checkpoint = m['source_checkpoint']
    require(type(checkpoint) is dict and type(checkpoint.get('committed_event_id')) is int
            and checkpoint == {key: cut[key] for key in ('source_id', 'epoch', 'committed_event_id')}, 'EPOCH_SOURCE_BINDING')
    # V2 wire cuts are normalized integers; A1 proof validation uses decimal TEXT.
    m['source_checkpoint'] = dict(checkpoint, committed_event_id=str(checkpoint['committed_event_id']))
    c.keys(m['row_counts'], set(c.TABLES))
    require(all(type(n) is int and n >= 0 for n in m['row_counts'].values()), 'INVALID_ROW_COUNTS')
    coverage(m['watermarks']); coverage(m['coverage_history'], True)
    if m['next_expiry_at'] is not None:
        require(utc_timestamp(m['next_expiry_at']) > times['selection_evaluated_at'], 'DUE_EXPIRY')
    # Database TEXT identifiers retain the A1 representation, independently of
    # normalized integer wire identifiers. This view is never a manifest receipt.
    m['database_content_id'] = str(m['database_content_id'])
    reader.metadata.update(database_hash=manifest['sha256'], selection_policy=c.POLICY,
                           content_binding=v2.transition_commitment(transition))
    return m


def _content(reader, artifact, bridge, manifest, previous, omitted, scratch):
    with reader.connection(artifact) as conn:
        require([r[0] for r in conn.execute('PRAGMA integrity_check')] == ['ok'], 'DATABASE_INTEGRITY_FAILED')
        reader._schema(conn, manifest)
        reader._rows(conn, manifest)
        reader._coverage(conn, manifest, previous)
        with closing(sqlite3.connect(scratch / 'audit.sqlite')) as audit:
            reader._qualifications(conn, manifest, audit)
            reader._workflows(conn, audit, manifest)
        # Omission exceptions are applied only to a private comparison copy,
        # after independent reconstruction proved exactly these archived rows.
        # Permanent/pinned/lifecycle rows may never be removed by this adapter.
        comparison = scratch / 'continuity.sqlite'
        shutil.copyfile(bridge, comparison)
        comparison.chmod(0o600)
        with closing(sqlite3.connect(comparison)) as old:
            for pid in omitted:
                reader.check()
                row = old.execute('SELECT retention_class,retain_until,pin_roots_json FROM selection_membership WHERE entity_type=? AND projection_row_id=?', ('message', pid)).fetchone()
                require(row and row[0] in ('CONTEXT', 'CAPABILITY_SIGNAL') and row[1] is not None and c.loads(row[2], 65536) == [], 'EPOCH_OMISSION_PROTECTED')
                require(conn.execute('SELECT 1 FROM messages WHERE projection_row_id=?', (pid,)).fetchone() is None, 'EPOCH_OMISSION_PRESENT')
                for table in ('messages', 'source_provenance', 'selection_membership'):
                    predicate = 'projection_row_id=?' if table == 'messages' else "entity_type='message' AND projection_row_id=?"
                    old.execute('DELETE FROM ' + table + ' WHERE ' + predicate, (pid,))
            old.commit()
        with reader.connection(comparison) as old:
            reader._extension(old, conn, manifest)
        import projection_routing
        indexed = projection_routing.build(conn, reader)
        profiles = {}
        for did, profile in indexed.items():
            reader.check()
            profiles[did] = profile
        return profiles


def accept_disposable(store_root, publication_root, bridge_root, archive_root, *, enable_epoch_v2=False,
                      now=None, timeout=180, fault=lambda boundary: None):
    """Accept only within an existing private disposable store.

    All roots are explicit operator configuration. No root or authority comes
    from a remote locator. No receipt argument is accepted from callers. The
    live bridge/archive session is created and consumed within this call.
    """
    if enable_epoch_v2 is not True:
        raise SnapshotError('EPOCH_V2_DISABLED')
    roots = [Path(x) for x in (publication_root, bridge_root, archive_root)]
    require(all(p.is_absolute() and p.resolve() == p for p in roots), 'EPOCH_TRUST_ROOT')
    store = DisposableEpochStore(store_root, fault)
    require(all(not store.root.is_relative_to(p) and not p.is_relative_to(store.root) for p in roots), 'EPOCH_TRUST_ROOT')
    with store.locked():
        before, state = store.recover()
        previous = state['last_accepted_projection_v2']
        require(previous['contract_revision'] == 'A1', 'EPOCH_FIRST_TRANSITION_REQUIRED')
        with tempfile.TemporaryDirectory(prefix='.stage-', dir=store.root) as temporary:
            scratch = Path(temporary)
            held = evidence.HeldInputs(scratch, lambda: None)
            reader = ProjectionReader(roots[0], Path(previous['cache_path']).parent, timeout=timeout, enable_epoch_v2=True)
            reader.deadline = time.monotonic() + timeout
            reader.metadata = {'stage_seconds': {}}
            held.check = reader.check
            try:
                anchor = reader._accepted_epoch_anchor(previous)
                reader._verify_cache(previous)
                pointer, manifest = _publication(held, roots[0], scratch / 'publication')
                require(manifest.get('contract_revision') == v2.REVISION, 'EPOCH_MANIFEST_SCHEMA')
                require('epoch_rollover' not in manifest, 'EPOCH_MANIFEST_FIELDS')
                sidecar = manifest['epoch_transition']
                v2.validate_transition_descriptor(sidecar)
                raw = held.read(_path(roots[0], sidecar['locator']), sidecar['sha256'], sidecar['size_bytes'], v2.MAX_INPUT_BYTES)
                transition = v2.validate_transition_bytes(raw, sidecar, anchor, 0, True)
                v2.validate_v2_manifest(manifest, transition)
                model = _metadata(reader, pointer, manifest, transition, previous, now or datetime.now(timezone.utc))
                desc = transition['bridge_predecessor']
                try:
                    bp, bm = _publication(held, roots[1], scratch / 'bridge', desc)
                    require(reader._epoch_descriptor(bm, bp['manifest_sha256']) == desc, 'EPOCH_BRIDGE_DESCRIPTOR')
                    bridge = held.read(_path(roots[1], bm['database']), desc['artifact_sha256'], desc['artifact_size'], reader.max_bytes, sqlite=True)
                except FileNotFoundError:
                    raise SnapshotError('EPOCH_EXACT_BRIDGE_ARTIFACT_UNAVAILABLE') from None
                shutil.copyfile(bridge, _path(scratch / 'bridge', bm['database']))
                with reader.epoch_validation_session() as session:
                    receipt = reader.validate_epoch_bridge(session, scratch / 'bridge', previous, sidecar['sha256'], accepted_anchor=anchor, now=now)
                    reader.require_verified_epoch_bridge(session, receipt, sidecar['sha256'], anchor, desc, transition['bridge_binding_sha256'])
                    active = transition['active_artifact']; plan = transition['active_set_plan']; arch = transition['archive']
                    artifact = held.read(_path(roots[0], active['locator']), active['artifact_sha256'], active['size_bytes'], reader.max_bytes, sqlite=True)
                    plan_raw = held.read(_path(roots[0], plan['locator']), plan['sha256'], plan['size_bytes'], v2.MAX_PLAN_BYTES)
                    plan_value = v2.validate_active_set_plan_bytes(plan_raw, transition)
                    omitted_ids = tuple(row['projection_row_id'] for row in plan_value['omitted'])
                    plan_path = scratch / 'plan.json'; plan_path.write_bytes(plan_raw)
                    # Reconstruction reopens these descriptor-bound bytes. Do not
                    # retain a second full 50,000-record plan during that pass.
                    del plan_value, plan_raw
                    # Archive root explicitly names the manifest's containing
                    # directory; locator never selects an unconfigured root.
                    archive_raw = held.read(roots[2] / 'manifest.json', arch['artifact_sha256'], arch['size_bytes'], v2.MAX_INPUT_BYTES)
                    am = v2.parse_json(archive_raw)
                    archive.validate_format(v2.without(arch, 'archive_commitment_sha256'), am)
                    local_archive = scratch / 'archive'; local_archive.mkdir()
                    (local_archive / 'manifest.json').write_bytes(archive_raw)
                    for member in am['members']:
                        target = _path(local_archive, member['locator']); target.parent.mkdir(parents=True, exist_ok=True)
                        source = held.read(_path(roots[2], member['locator']), member['sha256'], member['size_bytes'], archive.MAX_MEMBER, sqlite=True)
                        shutil.copyfile(source, target)
                    # This routine checks the complete archive/source recovery,
                    # all compact commitments and classifications independently.
                    summary = evidence.reconstruct(transition, accepted_anchor=anchor, plan_path=plan_path,
                        artifact_path=artifact, archive_root=local_archive, timeout=max(0.001, reader.deadline-time.monotonic()))
                    archive_receipt = archive.VerifiedEpochArchive(session, session.token, receipt,
                        copy.deepcopy(arch), am, plan['recovery_commitment_sha256'],
                        dict(summary.counts)['mandatory_proof_closure'])
                    require(archive_receipt._session is session and archive_receipt._token is session.token
                            and archive_receipt.bridge_receipt is receipt and archive_receipt.descriptor == transition['archive'], 'EPOCH_ARCHIVE_RECEIPT')
                    reader.require_verified_epoch_bridge(session, receipt, sidecar['sha256'], anchor, desc, transition['bridge_binding_sha256'])
                    bridge_previous = dict(previous, manifest=bm, snapshot_id=bm['snapshot_id'],
                        database_content_id=bm['database_content_id'], published_at=bp['published_at'])
                    model = _metadata(reader, pointer, manifest, transition, bridge_previous, now or datetime.now(timezone.utc))
                    # Routing's derived cache also remains session-private.
                    reader.cache_dir = scratch
                    profiles = _content(reader, artifact, bridge, model, previous,
                                        omitted_ids, scratch)
                    held.unchanged(); reader.check()
                    require(store.load()[0] == before, 'EPOCH_ACCEPTED_STATE_CHANGED')
                    accepted = { 'manifest': manifest, 'manifest_hash': pointer['manifest_sha256'],
                        'manifest_canonical_hash': c.digest(manifest), 'snapshot_id': str(manifest['snapshot_id']),
                        'database_content_id': str(manifest['database_content_id']), 'database_hash': manifest['sha256'],
                        'size_bytes': manifest['size_bytes'], 'contract_revision': v2.REVISION,
                        'produced_at': manifest['produced_at'], 'published_at': pointer['published_at'],
                        'watermarks': manifest['watermarks'], 'coverage_history': manifest['coverage_history']}
                    updated = copy.deepcopy(state); updated['last_accepted_projection_v2'] = accepted
                    facts = {'transition': v2.transition_commitment(transition), 'archive': arch['archive_commitment_sha256'],
                             'counts': dict(summary.counts), 'commitments': dict(summary.commitments),
                             'descriptors': dict(summary.descriptor_identities)}
                    store.commit(before, updated, artifact, facts)
                    return profiles, accepted, summary
            finally:
                held.close(); reader.close()
