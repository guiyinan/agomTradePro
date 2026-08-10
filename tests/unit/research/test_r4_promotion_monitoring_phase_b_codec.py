"""Strict codec coverage for R4 post-promotion monitoring persistence."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest

from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import evaluate_r4_promotion_monitoring
from apps.research.infrastructure.r4_promotion_monitoring_codec import (
    R4MonitoringCodecError,
    decode_r4_monitoring_active_decision,
    decode_r4_monitoring_assessment,
    decode_r4_monitoring_observation,
    decode_r4_monitoring_period_calendar,
    decode_r4_monitoring_policy,
    decode_r4_monitoring_portfolio_result,
    decode_r4_monitoring_r3_attestation,
    encode_r4_monitoring_active_decision,
    encode_r4_monitoring_assessment,
    encode_r4_monitoring_observation,
    encode_r4_monitoring_period_calendar,
    encode_r4_monitoring_policy,
    encode_r4_monitoring_portfolio_result,
    encode_r4_monitoring_r3_attestation,
)
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_decision,
    monitoring_observation,
    monitoring_policy,
)


def _evidence() -> tuple[object, ...]:
    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    observations = tuple(
        monitoring_observation(
            period_index=index,
            decision=decision,
            calendar=calendar,
            policy=policy,
        )
        for index in range(2)
    )
    assessment = evaluate_r4_promotion_monitoring(
        requested_active_decision=R4PromotionDecisionIdentity.from_decision(decision),
        requested_policy_id=policy.policy_id,
        requested_policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        active_decision=decision,
        portfolio_result=decision.trial.portfolio_record,
        current_r3_attestation=decision.trial.current_r3_attestation,
        policy=policy,
        period_calendar=calendar,
        observations=observations,
        evaluated_at=calendar.valid_from + timedelta(hours=2, minutes=30),
    )
    return decision, calendar, policy, observations, assessment


def test_every_persisted_r4_monitoring_type_round_trips_strictly() -> None:
    decision, calendar, policy, observations, assessment = _evidence()

    pairs = (
        (encode_r4_monitoring_active_decision, decode_r4_monitoring_active_decision, decision),
        (
            encode_r4_monitoring_portfolio_result,
            decode_r4_monitoring_portfolio_result,
            decision.trial.portfolio_record,
        ),
        (
            encode_r4_monitoring_r3_attestation,
            decode_r4_monitoring_r3_attestation,
            decision.trial.current_r3_attestation,
        ),
        (encode_r4_monitoring_policy, decode_r4_monitoring_policy, policy),
        (
            encode_r4_monitoring_period_calendar,
            decode_r4_monitoring_period_calendar,
            calendar,
        ),
        (
            encode_r4_monitoring_observation,
            decode_r4_monitoring_observation,
            observations[0],
        ),
        (encode_r4_monitoring_assessment, decode_r4_monitoring_assessment, assessment),
    )
    for encoder, decoder, value in pairs:
        assert decoder(encoder(value)) == value


def test_codec_rejects_extra_keys_unknown_schema_and_computed_seal_tamper() -> None:
    decision, _calendar, policy, _observations, _assessment = _evidence()
    payload = encode_r4_monitoring_policy(policy)

    with_extra = deepcopy(payload)
    with_extra["caller_value"] = True
    with pytest.raises(R4MonitoringCodecError, match="missing or extra|envelope"):
        decode_r4_monitoring_policy(with_extra)

    wrong_schema = deepcopy(payload)
    wrong_schema["schema"] = "caller-selected.v999"
    with pytest.raises(R4MonitoringCodecError, match="schema"):
        decode_r4_monitoring_policy(wrong_schema)

    decision_payload = encode_r4_monitoring_active_decision(decision)
    value = decision_payload["value"]
    assert isinstance(value, dict)
    raw_fields = value["$fields"]
    assert isinstance(raw_fields, dict)
    raw_fields["content_hash"] = "f" * 64
    with pytest.raises(R4MonitoringCodecError, match="validation|seal|canonical"):
        decode_r4_monitoring_active_decision(decision_payload)
