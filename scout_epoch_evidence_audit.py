"""Explicit offline audit of an isolated compact V2 publication. No state writes."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys
import tempfile
import time

from scout_epoch_evidence import (EvidenceError, HeldInputs, reconstruct, require,
                                  open_held, stamp)
import scout_epoch_v2_validator as v2


def fingerprint(path):
    import os
    fd = open_held(path)
    try:
        before = stamp(os.fstat(fd)); digest = hashlib.sha256()
        require(before[2] <= 1024**3, 'AUDIT_INPUT_BOUNDS')
        total = 0
        for block in iter(lambda: os.read(fd, min(1024*1024,before[2]-total+1)), b''):
            total += len(block)
            require(total <= before[2], 'AUDIT_INPUT_CHANGED')
            digest.update(block)
        require(stamp(os.fstat(fd)) == before, 'AUDIT_INPUT_CHANGED')
        return {'sha256': digest.hexdigest(), 'size_bytes': before[2], 'inode': before[1],
                'mtime_ns': before[3], 'ctime_ns': before[4]}
    finally:
        os.close(fd)


def audit_bundle(root, archive_root, accepted_anchor, pointer_sha256):
    root, archive_root = Path(root), Path(archive_root)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='router-epoch-audit-') as scratch:
        held = HeldInputs(scratch, lambda: None)
        try:
            inputs = {'pointer': root/'current.json'}
            info = fingerprint(inputs['pointer'])
            pointer = v2.parse_json(held.read(inputs['pointer'], pointer_sha256, info['size_bytes'], v2.MAX_INPUT_BYTES))
            v2.obj(pointer, ('schema','manifest','manifest_sha256','published_at'))
            require(pointer['schema'] == 'flop-scout-router-current/v2', 'AUDIT_POINTER_SCHEMA')
            v2.locator(pointer['manifest'], 'AUDIT_MANIFEST_LOCATOR')
            inputs['manifest'] = root/pointer['manifest']
            info = fingerprint(inputs['manifest'])
            manifest = v2.parse_json(held.read(inputs['manifest'], pointer['manifest_sha256'], info['size_bytes'], v2.MAX_INPUT_BYTES))
            sidecar = manifest['epoch_transition']; v2.validate_transition_descriptor(sidecar)
            inputs['transition'] = root/sidecar['locator']
            raw = held.read(inputs['transition'], sidecar['sha256'], sidecar['size_bytes'], v2.MAX_INPUT_BYTES)
            transition = v2.validate_transition_bytes(raw, sidecar, accepted_anchor, 0, True)
            v2.validate_v2_manifest(manifest, transition)
            inputs.update(plan=root/transition['active_set_plan']['locator'],
                          artifact=root/transition['active_artifact']['locator'], archive_manifest=archive_root/'manifest.json',
                          archive_bridge=archive_root/'members/bridge-projection.sqlite',
                          archive_source=archive_root/'members/source-evidence.sqlite',
                          archive_recovery=archive_root/'members/legacy-recovery.json')
            before = {role: fingerprint(path) for role,path in inputs.items()}
            stage = time.monotonic()
            try:
                result = reconstruct(transition, accepted_anchor=accepted_anchor, plan_path=inputs['plan'],
                                     artifact_path=inputs['artifact'], archive_root=archive_root)
                status, code = 'PASS', None
            except EvidenceError as exc:
                result, status, code = exc.summary, 'REJECTED', exc.code
            reconstruction_seconds = time.monotonic()-stage
            after = {role: fingerprint(path) for role,path in inputs.items()}
            held.unchanged()
            require(before == after, 'AUDIT_INPUT_CHANGED')
            # Re-read through a descriptor only to report the stale binding pair;
            # this diagnostic never substitutes corrected bytes into validation.
            desc=transition['active_set_plan']
            plan=v2.parse_active_set_plan(held.read(inputs['plan'],desc['sha256'],desc['size_bytes'],v2.MAX_PLAN_BYTES))
            mismatches={}
            for field, expected in (
                ('retained_floor_commitment_sha256', transition['retained_floor_commitment']['retained_floor_commitment_sha256']),
                ('omission_commitment_sha256', transition['retained_floor_commitment']['omitted_history_sha256'])):
                if plan[field] != expected: mismatches[field]={'plan':plan[field],'transition':expected}
            held.unchanged()
            return {'schema':'flop-router-epoch-evidence-audit/v1','status':status,'error':code,
                    'publication_sequence':manifest['snapshot_id'],'content_id':manifest['database_content_id'],
                    'epoch_id':transition['epoch_id'], 'counts':dict(result.counts) if result else None,
                    'commitments':dict(result.commitments) if result else None,
                    'descriptor_identities':dict(result.descriptor_identities) if result else None,
                    'all_five_summaries_match': bool(result) and all(dict(result.commitments)[name] == transition['retained_floor_commitment'][name+'_sha256']
                        and dict(result.counts)[name] == transition['retained_floor_commitment'][name+'_count'] for name in v2.SET_DOMAINS),
                    'plan_binding_mismatches':mismatches,'reconstruction_seconds':reconstruction_seconds,
                    'total_seconds':time.monotonic()-started,
                    'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),
                    'inputs_before':before,'inputs_after':after,'inputs_unchanged':True,
                    'acceptance_performed':False,'router_state_written':False}
        finally:
            held.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-root',required=True,type=Path)
    parser.add_argument('--archive-root',required=True,type=Path)
    parser.add_argument('--accepted-anchor',required=True,type=Path)
    parser.add_argument('--pointer-sha256',required=True)
    args=parser.parse_args()
    with args.accepted_anchor.open('rb') as stream: anchor=v2.parse_json(stream.read(v2.MAX_INPUT_BYTES+1))
    result=audit_bundle(args.bundle_root,args.archive_root,anchor,args.pointer_sha256)
    print(json.dumps(result,sort_keys=True,indent=2))
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
