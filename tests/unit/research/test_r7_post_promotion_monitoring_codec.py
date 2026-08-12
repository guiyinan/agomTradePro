"""Strict R7 monitoring codec reconstructs all derived Domain objects."""

from __future__ import annotations

from copy import deepcopy

import pytest

from apps.research.infrastructure.r7_post_promotion_monitoring_codec import (
    R7MonitoringCodecError,
    decode_r7_monitoring_evidence,
    encode_r7_monitoring_evidence,
)
from tests.unit.research.test_r7_post_promotion_monitoring_persistence import (
    _evidence,
)


def test_monitoring_codec_round_trips_complete_source_graph() -> None:
    _, evidence = _evidence()

    payload = encode_r7_monitoring_evidence(evidence)
    restored = decode_r7_monitoring_evidence(payload)

    assert restored == evidence
    assert restored.active == restored.active_owner_graph.active_result()
    assert restored.realization.owner_record == restored.realization_owner_record


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.pop("calendar"),
        lambda payload: payload.__setitem__("extra", True),
        lambda payload: payload.__setitem__("evidence_hash", "0" * 64),
        lambda payload: payload["assessment"].__setitem__("status", "healthy"),
        lambda payload: payload["lifecycle_stream"].clear(),
    ],
)
def test_monitoring_codec_rejects_missing_extra_or_tampered_content(mutator: object) -> None:
    _, evidence = _evidence()
    payload = deepcopy(encode_r7_monitoring_evidence(evidence))
    mutator(payload)

    with pytest.raises(R7MonitoringCodecError):
        decode_r7_monitoring_evidence(payload)
