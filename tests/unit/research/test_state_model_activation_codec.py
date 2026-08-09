"""Strict codec tests for R6 activation persistence payloads."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from apps.research.domain.state_model_activation import (
    R6ActivationAction,
    R6ActivationApprovalRef,
    R6ActivationAuthorization,
    R6ActivationScopeRef,
    create_r6_activation_event,
)
from apps.research.infrastructure.state_model_activation_codec import (
    R6ActivationCodecError,
    decode_r6_activation_authorization,
    decode_r6_activation_event,
    encode_r6_activation_authorization,
    encode_r6_activation_event,
)


def _authorization() -> R6ActivationAuthorization:
    start = datetime(2026, 8, 9, 1, tzinfo=UTC)
    return R6ActivationAuthorization(
        authorization_id="activation-auth-1",
        authorization_version="v1",
        event_id="activation-event-1",
        event_version="v1",
        scope_ref=R6ActivationScopeRef("scope-1", "v1", "a" * 64),
        action=R6ActivationAction.ACTIVATE,
        subject=R6ActivationApprovalRef("approval-1", "v1", "b" * 64),
        rollback_target=None,
        expected_sequence=1,
        expected_previous_event_hash=None,
        owner="research",
        issued_at=start,
        recorded_at=start + timedelta(seconds=1),
        valid_until=start + timedelta(hours=1),
        reason_codes=("manual-approval",),
        evidence_ref="research://activation/auth-1",
    )


def test_activation_codec_round_trips_every_sealed_field() -> None:
    authorization = _authorization()
    event = create_r6_activation_event(
        authorization=authorization,
        previous_events=(),
        applied_at=authorization.recorded_at + timedelta(seconds=1),
    )

    assert (
        decode_r6_activation_authorization(encode_r6_activation_authorization(authorization))
        == authorization
    )
    assert decode_r6_activation_event(encode_r6_activation_event(event)) == event


@pytest.mark.parametrize("kind", ["extra-key", "unknown-version", "tampered-seal"])
def test_activation_authorization_codec_rejects_noncanonical_payload(kind: str) -> None:
    payload = deepcopy(encode_r6_activation_authorization(_authorization()))
    body = payload["authorization"]
    assert isinstance(body, dict)
    if kind == "extra-key":
        body["caller_claim"] = "trusted"
    elif kind == "unknown-version":
        payload["schema"] = "r6-activation-authorization.v2"
    else:
        body["content_hash"] = "f" * 64

    with pytest.raises(R6ActivationCodecError):
        decode_r6_activation_authorization(payload)


def test_activation_codec_rejects_timezone_alias_and_event_tamper() -> None:
    authorization = _authorization()
    event = create_r6_activation_event(
        authorization=authorization,
        previous_events=(),
        applied_at=authorization.recorded_at + timedelta(seconds=1),
    )
    authorization_payload = deepcopy(encode_r6_activation_authorization(authorization))
    authorization_body = authorization_payload["authorization"]
    assert isinstance(authorization_body, dict)
    authorization_body["issued_at"] = "2026-08-09T09:00:00+08:00"
    with pytest.raises(R6ActivationCodecError):
        decode_r6_activation_authorization(authorization_payload)

    event_payload = deepcopy(encode_r6_activation_event(event))
    event_body = event_payload["event"]
    assert isinstance(event_body, dict)
    event_body["authorization_hash"] = "c" * 64
    with pytest.raises(R6ActivationCodecError):
        decode_r6_activation_event(event_payload)
