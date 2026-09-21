import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scout_epoch_v2_validator as epoch_v2
from scout_projection import (EpochValidationSession, ProjectionReader,
                              SnapshotError, VerifiedEpochBridge)


FIXTURE = Path(__file__).parent / 'docs/fixtures/scout-router-epoch-rollover-v2-conformance.json'


def vector(name):
    return next(copy.deepcopy(item) for item in json.loads(FIXTURE.read_text())['vectors'] if item['name'] == name)


def trusted_previous(anchor):
    return {'manifest': {'snapshot_id': str(anchor['publication_sequence']),
                         'database_content_id': str(anchor['content_id']),
                         'sha256': anchor['artifact_sha256'], 'size_bytes': anchor['artifact_size'],
                         'source_checkpoint': {'epoch': anchor['source_kind'], 'source_id': anchor['source_id'],
                                               'committed_event_id': str(anchor['source_cut'])}},
            'manifest_hash': anchor['manifest_sha256']}


def harness(tmp_path, item):
    reader = SimpleNamespace(cache_dir=tmp_path, enable_epoch_v2=True,
        epoch_v2_accepted_epoch_number=0,
        epoch_v2_first_transition=True, epoch_v2_bridge_root=None)
    reader._epoch_descriptor = ProjectionReader._epoch_descriptor
    reader._accepted_epoch_anchor = ProjectionReader._accepted_epoch_anchor.__get__(reader)
    reader.epoch_validation_session = lambda: EpochValidationSession(reader)
    reader.require_verified_epoch_bridge = ProjectionReader.require_verified_epoch_bridge
    reader._validate_epoch_v2_disabled = ProjectionReader._validate_epoch_v2_disabled.__get__(reader)
    return reader


def test_direct_flow_stops_without_profiles_or_cache_mutation(tmp_path):
    item = vector('valid-direct'); reader = harness(tmp_path, item)
    before = sorted(tmp_path.iterdir())
    with pytest.raises(SnapshotError, match='EPOCH_V2_NOT_ACCEPTING'):
        reader._validate_epoch_v2_disabled(item['transition'], trusted_previous(item['accepted_anchor']), None)
    assert sorted(tmp_path.iterdir()) == before
    assert not hasattr(reader, 'profiles')


def test_cumulative_flow_requires_live_verified_bridge_and_stops(tmp_path):
    item = vector('valid-cumulative'); reader = harness(tmp_path, item); calls = []
    def bridge(session, root, previous, candidate_sha256, *, accepted_anchor=None, now=None):
        calls.append(candidate_sha256)
        return VerifiedEpochBridge(session, session.token, candidate_sha256, accepted_anchor,
            item['transition']['bridge_predecessor'], item['transition']['bridge_binding_sha256'],
            'v' * 64, {}, 'w' * 64, 'h' * 64, 'a' * 64)
    reader.epoch_v2_bridge_root = tmp_path
    reader.validate_epoch_bridge = bridge
    before = sorted(tmp_path.iterdir())
    with pytest.raises(SnapshotError, match='EPOCH_V2_NOT_ACCEPTING'):
        reader._validate_epoch_v2_disabled(item['transition'], trusted_previous(item['accepted_anchor']), None)
    assert calls == [hashlib.sha256(epoch_v2.canonical_json(item['transition'])).hexdigest()]
    assert sorted(tmp_path.iterdir()) == before
    assert not hasattr(reader, 'profiles')


@pytest.mark.parametrize('name, expected', [
    ('forged-bridge-binding', 'EPOCH_BRIDGE_BINDING'),
    ('mutated-anchor', 'EPOCH_ACCEPTED_ANCHOR'),
    ('wrong-archive-bridge-binding', 'EPOCH_ARCHIVE_BINDING'),
    ('forbidden-verified_receipt', 'EPOCH_FIELDS'),
])
def test_disabled_flow_fails_closed_on_wire_errors(tmp_path, name, expected):
    item = vector(name); reader = harness(tmp_path, item)
    with pytest.raises(SnapshotError, match=expected):
        reader._validate_epoch_v2_disabled(item['transition'], trusted_previous(item['accepted_anchor']), None)


def test_cross_session_and_closed_receipts_cannot_satisfy_bridge_requirement(tmp_path):
    item = vector('valid-cumulative'); reader = harness(tmp_path, item)
    with reader.epoch_validation_session() as first:
        receipt = VerifiedEpochBridge(first, first.token, 'a' * 64, item['accepted_anchor'],
            item['transition']['bridge_predecessor'], item['transition']['bridge_binding_sha256'],
            'v' * 64, {}, 'w' * 64, 'h' * 64, 'a' * 64)
        with reader.epoch_validation_session() as other:
            with pytest.raises(SnapshotError, match='EPOCH_BRIDGE_RECEIPT_INVALID'):
                reader.require_verified_epoch_bridge(other, receipt, 'a' * 64, item['accepted_anchor'],
                    item['transition']['bridge_predecessor'], item['transition']['bridge_binding_sha256'])
    with pytest.raises(SnapshotError, match='EPOCH_BRIDGE_RECEIPT_INVALID'):
        reader.require_verified_epoch_bridge(first, receipt, 'a' * 64, item['accepted_anchor'],
            item['transition']['bridge_predecessor'], item['transition']['bridge_binding_sha256'])
