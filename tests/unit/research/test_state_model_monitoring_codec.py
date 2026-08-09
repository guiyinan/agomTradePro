"""Strict canonical codec contracts for persisted R6 monitoring evidence."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

import pytest

from apps.research.domain.state_model_monitoring import (
    R6MonitoringAssessment,
    evaluate_r6_monitoring,
)
from apps.research.infrastructure.state_model_monitoring_codec import (
    R6MonitoringCodecError,
    decode_r6_monitoring_assessment,
    decode_r6_monitoring_observation,
    decode_r6_monitoring_period_calendar,
    decode_r6_monitoring_policy,
    encode_r6_monitoring_assessment,
    encode_r6_monitoring_observation,
    encode_r6_monitoring_period_calendar,
    encode_r6_monitoring_policy,
)
from tests.unit.research.state_model_monitoring_factories import (
    NOW,
    active_qualification,
    observation,
    period_calendar,
    policy,
)


def _assessment() -> R6MonitoringAssessment:
    monitoring_policy = policy()
    qualification = active_qualification()
    observations = (
        observation(sequence=1, monitoring_policy=monitoring_policy),
        observation(sequence=2, monitoring_policy=monitoring_policy),
    )
    return evaluate_r6_monitoring(
        qualification_ref=monitoring_policy.qualification_ref,
        qualification_content_hash=monitoring_policy.qualification_ref.assessment_hash,
        qualification_assessed_at=qualification.assessed_at,
        qualification_known_at=qualification.known_at,
        requested_policy_id=monitoring_policy.policy_id,
        requested_policy_version=monitoring_policy.policy_version,
        expected_policy_hash=monitoring_policy.content_hash,
        policy=monitoring_policy,
        period_calendar=period_calendar(),
        observations=observations,
        evaluated_at=NOW,
    )


@pytest.mark.parametrize(
    ("value", "encoder", "decoder"),
    (
        (policy(), encode_r6_monitoring_policy, decode_r6_monitoring_policy),
        (
            period_calendar(),
            encode_r6_monitoring_period_calendar,
            decode_r6_monitoring_period_calendar,
        ),
        (
            observation(sequence=1, monitoring_policy=policy()),
            encode_r6_monitoring_observation,
            decode_r6_monitoring_observation,
        ),
        (
            _assessment(),
            encode_r6_monitoring_assessment,
            decode_r6_monitoring_assessment,
        ),
    ),
)
def test_monitoring_codec_round_trips_every_sealed_type(
    value: object,
    encoder: Callable[[object], dict[str, object]],
    decoder: Callable[[object], object],
) -> None:
    """Every persisted owner/result object is rebuilt and re-sealed."""

    assert decoder(encoder(value)) == value


@pytest.mark.parametrize(
    ("payload", "decoder"),
    (
        (encode_r6_monitoring_policy(policy()), decode_r6_monitoring_policy),
        (
            encode_r6_monitoring_period_calendar(period_calendar()),
            decode_r6_monitoring_period_calendar,
        ),
        (
            encode_r6_monitoring_observation(observation(sequence=1, monitoring_policy=policy())),
            decode_r6_monitoring_observation,
        ),
        (
            encode_r6_monitoring_assessment(_assessment()),
            decode_r6_monitoring_assessment,
        ),
    ),
)
def test_monitoring_codec_rejects_tampered_seals_and_unknown_fields(
    payload: dict[str, object],
    decoder: Callable[[object], object],
) -> None:
    """Neither hash tampering nor schema widening is accepted."""

    tampered = deepcopy(payload)
    body = tampered["body"]
    assert isinstance(body, dict)
    body["content_hash"] = "f" * 64
    with pytest.raises(R6MonitoringCodecError):
        decoder(tampered)

    widened = deepcopy(payload)
    body = widened["body"]
    assert isinstance(body, dict)
    body["current"] = True
    with pytest.raises(R6MonitoringCodecError, match="keys"):
        decoder(widened)


def test_observation_codec_preserves_owner_recorded_at_exactly() -> None:
    """The raw owner clock remains evidence, not a ledger insertion clock."""

    monitoring_policy = policy()
    raw_fact = observation(sequence=1, monitoring_policy=monitoring_policy)

    restored = decode_r6_monitoring_observation(encode_r6_monitoring_observation(raw_fact))

    assert restored.recorded_at == raw_fact.recorded_at
