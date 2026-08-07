"""Strict codecs for R7 result promotion and retirement ledgers."""

from __future__ import annotations

from copy import deepcopy

import pytest

from apps.research.infrastructure.r7_research_result_lifecycle_codec import (
    R7ResultLifecycleCodecError,
    decode_r7_result_lifecycle_authorization,
    decode_r7_result_lifecycle_event,
    encode_r7_result_lifecycle_authorization,
    encode_r7_result_lifecycle_event,
)
from tests.unit.research.test_r7_research_result_lifecycle import (
    _authorization,
    _event,
)


def test_authorization_and_event_round_trip_exactly() -> None:
    authorization = _authorization()
    event = _event(authorization, previous_event_hash=None)

    assert (
        decode_r7_result_lifecycle_authorization(
            encode_r7_result_lifecycle_authorization(authorization)
        )
        == authorization
    )
    assert decode_r7_result_lifecycle_event(encode_r7_result_lifecycle_event(event)) == event


@pytest.mark.parametrize("target", ["authorization", "event"])
def test_codec_rejects_unknown_fields_and_safety_relaxation(target: str) -> None:
    authorization = _authorization()
    event = _event(authorization, previous_event_hash=None)
    payload = (
        encode_r7_result_lifecycle_authorization(authorization)
        if target == "authorization"
        else encode_r7_result_lifecycle_event(event)
    )
    unknown = deepcopy(payload)
    unknown["unknown"] = "field"
    relaxed = deepcopy(payload)
    relaxed["publishes_model_probability"] = True
    decoder = (
        decode_r7_result_lifecycle_authorization
        if target == "authorization"
        else decode_r7_result_lifecycle_event
    )

    with pytest.raises(R7ResultLifecycleCodecError):
        decoder(unknown)
    with pytest.raises(R7ResultLifecycleCodecError):
        decoder(relaxed)
