import pickle
from types import SimpleNamespace

import pytest

from scout_projection import (EpochValidationSession, ProjectionReader,
                              SnapshotError, VerifiedEpochBridge)


def receipt(session, candidate='a' * 64):
    anchor = {'anchor': 1}; bridge = {'bridge': 1}
    return VerifiedEpochBridge(session, session.token, candidate, anchor, bridge,
                              'b' * 64, 'c' * 64, {}, 'd' * 64, 'e' * 64, 'f' * 64)


def test_receipt_is_live_only_and_session_bound(tmp_path):
    reader = SimpleNamespace(cache_dir=tmp_path)
    session = EpochValidationSession(reader)
    with session:
        item = receipt(session)
        assert 'token' not in repr(item)
        with pytest.raises(TypeError):
            pickle.dumps(item)
        assert ProjectionReader.require_verified_epoch_bridge(session, item, 'a' * 64,
                                                              item.accepted_anchor,
                                                              item.bridge_predecessor,
                                                              item.bridge_binding) is item
        with EpochValidationSession(reader) as other:
            with pytest.raises(SnapshotError, match='EPOCH_BRIDGE_RECEIPT_INVALID'):
                ProjectionReader.require_verified_epoch_bridge(other, item, 'a' * 64,
                                                              item.accepted_anchor,
                                                              item.bridge_predecessor,
                                                              item.bridge_binding)
        with pytest.raises(SnapshotError, match='EPOCH_BRIDGE_RECEIPT_INVALID'):
            ProjectionReader.require_verified_epoch_bridge(session, item, '0' * 64,
                                                          item.accepted_anchor,
                                                          item.bridge_predecessor,
                                                          item.bridge_binding)
    with pytest.raises(SnapshotError, match='EPOCH_BRIDGE_RECEIPT_INVALID'):
        ProjectionReader.require_verified_epoch_bridge(session, item, 'a' * 64,
                                                      item.accepted_anchor,
                                                      item.bridge_predecessor,
                                                      item.bridge_binding)
