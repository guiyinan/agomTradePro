"""R6 qualification payload, PIT identity, and lifecycle contract tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest

from apps.research.application.state_model_qualification import (
    AssessStateModelQualificationCommand,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationLifecycleAction,
    R6QualificationPromotionAuthorization,
    R6QualificationRef,
    create_r6_qualification_lifecycle_event,
    derive_r6_qualification_lifecycle_state,
)
from apps.research.infrastructure.state_model_qualification_codec import (
    R6QualificationCodecError,
    decode_r6_qualification_assessment,
    encode_r6_qualification_assessment,
)
from tests.unit.research.advanced_state_model_factories import NOW
from tests.unit.research.test_state_model_qualification_application import (
    _providers,
    _use_case,
)


def _assessment(assessed_at=NOW):
    providers = _providers()
    assert providers.study is not None
    return _use_case(providers).execute(
        AssessStateModelQualificationCommand(
            study_id=providers.study.study_id,
            assessed_at=assessed_at,
        )
    )


def _authorization(
    *,
    action: R6QualificationLifecycleAction,
    sequence: int,
    ref: R6QualificationRef,
    offset_minutes: int,
) -> R6QualificationPromotionAuthorization:
    recorded_at = NOW + timedelta(minutes=offset_minutes)
    return R6QualificationPromotionAuthorization(
        authorization_id=f"r6-auth-{sequence}",
        authorization_version="v1",
        qualification_ref=ref,
        event_id=f"r6-event-{sequence}",
        event_version="v1",
        action=action,
        expected_sequence=sequence,
        owner="research",
        issued_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(days=1),
        reason_codes=("manual-review",),
        evidence_ref=f"research://r6/lifecycle/{sequence}",
    )


def test_qualification_assessment_codec_round_trip_and_seal() -> None:
    assessment = _assessment()

    payload = encode_r6_qualification_assessment(assessment)
    assert decode_r6_qualification_assessment(payload) == assessment
    assert assessment.research_only is True
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_replace_regime is True


def test_qualification_assessment_codec_rejects_noncanonical_or_tampered_body() -> None:
    payload = encode_r6_qualification_assessment(_assessment())

    tampered = deepcopy(payload)
    body = tampered["body"]
    assert isinstance(body, dict)
    body["content_hash"] = "f" * 64
    with pytest.raises(R6QualificationCodecError):
        decode_r6_qualification_assessment(tampered)

    unknown = deepcopy(payload)
    body = unknown["body"]
    assert isinstance(body, dict)
    body["current"] = True
    with pytest.raises(R6QualificationCodecError, match="keys"):
        decode_r6_qualification_assessment(unknown)


def test_r6_lifecycle_replay_requires_promote_root_and_hash_chain() -> None:
    ref = R6QualificationRef("r6-assessment", "a" * 64)
    promote_auth = _authorization(
        action=R6QualificationLifecycleAction.PROMOTE,
        sequence=1,
        ref=ref,
        offset_minutes=1,
    )
    promote = create_r6_qualification_lifecycle_event(
        authorization=promote_auth,
        sequence=1,
        occurred_at=promote_auth.recorded_at,
        recorded_at=promote_auth.recorded_at,
        previous_event_hash=None,
    )
    retire_auth = _authorization(
        action=R6QualificationLifecycleAction.RETIRE,
        sequence=2,
        ref=ref,
        offset_minutes=2,
    )
    retire = create_r6_qualification_lifecycle_event(
        authorization=retire_auth,
        sequence=2,
        occurred_at=retire_auth.recorded_at,
        recorded_at=retire_auth.recorded_at,
        previous_event_hash=promote.content_hash,
    )

    active = derive_r6_qualification_lifecycle_state(
        (promote,),
        evaluated_at=NOW + timedelta(minutes=1),
    )
    retired = derive_r6_qualification_lifecycle_state(
        (promote, retire),
        evaluated_at=NOW + timedelta(minutes=2),
    )
    assert active.active is True
    assert retired.active is False
    assert retired.sequence == 2

    root_retire_auth = _authorization(
        action=R6QualificationLifecycleAction.RETIRE,
        sequence=1,
        ref=ref,
        offset_minutes=3,
    )
    root_retire = create_r6_qualification_lifecycle_event(
        authorization=root_retire_auth,
        sequence=1,
        occurred_at=root_retire_auth.recorded_at,
        recorded_at=root_retire_auth.recorded_at,
        previous_event_hash=None,
    )
    with pytest.raises(ValueError, match="root"):
        derive_r6_qualification_lifecycle_state(
            (root_retire,),
            evaluated_at=NOW + timedelta(minutes=3),
        )
    with pytest.raises(ValueError, match="hash chain"):
        derive_r6_qualification_lifecycle_state(
            (
                promote,
                retire.__class__(
                    event_id=retire.event_id,
                    event_version=retire.event_version,
                    qualification_ref=retire.qualification_ref,
                    authorization_id=retire.authorization_id,
                    authorization_version=retire.authorization_version,
                    authorization_hash=retire.authorization_hash,
                    action=retire.action,
                    sequence=retire.sequence,
                    occurred_at=retire.occurred_at,
                    recorded_at=retire.recorded_at,
                    previous_event_hash="b" * 64,
                    reason_codes=retire.reason_codes,
                ),
            ),
            evaluated_at=NOW + timedelta(minutes=2),
        )
