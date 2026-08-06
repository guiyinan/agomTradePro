"""Unit coverage for strict canonical R4 persistence codecs."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import cast

import pytest

from apps.research.application.r4_promotion_decision import R4PromotionVersionRef
from apps.research.application.r4_promotion_lifecycle_evidence import (
    ExactR4LifecycleAuthorizationEvidence,
    R4PromotionLifecycleEventBundle,
)
from apps.research.domain.r4_promotion_lifecycle import (
    R4PromotionLifecycleAuthorization,
    R4PromotionLifecycleEventType,
    create_r4_promotion_lifecycle_root,
)
from apps.research.infrastructure.r4_promotion_codec import (
    R4PromotionCodecError,
    decode_r4_lifecycle_event_bundle,
    decode_r4_promotion_decision_bundle,
    decode_r4_promotion_decision_receipt,
    decode_r4_promotion_policy,
    encode_r4_lifecycle_event_bundle,
    encode_r4_promotion_decision_bundle,
    encode_r4_promotion_decision_receipt,
    encode_r4_promotion_policy,
)
from tests.unit.research.r4_promotion_factories import (
    promotion_decision_bundle,
    promotion_policy,
)


def _lifecycle_bundle() -> R4PromotionLifecycleEventBundle:
    decision_bundle = promotion_decision_bundle()
    decision = decision_bundle.decision
    reasons = ("research_policy_approved",)
    issued_at = decision.recorded_at + timedelta(minutes=1)
    authorization = R4PromotionLifecycleAuthorization.create(
        authorization_id="r4-codec-authorization",
        authorization_version="authorization.v1",
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=decision,
        rollback_target=None,
        reason_codes=reasons,
        issued_at=issued_at,
        recorded_at=issued_at + timedelta(minutes=1),
        valid_until=issued_at + timedelta(hours=1),
    )
    evidence = ExactR4LifecycleAuthorizationEvidence.create(
        event_ref=R4PromotionVersionRef("r4-codec-event", "event.v1"),
        authorization=authorization,
        reason_codes=reasons,
        occurred_at=issued_at + timedelta(minutes=2),
        event_recorded_at=issued_at + timedelta(minutes=3),
    )
    event = create_r4_promotion_lifecycle_root(
        event_id=evidence.event_ref.stable_id,
        event_version=evidence.event_ref.version,
        decision=decision,
        authorization=authorization,
        reason_codes=reasons,
        occurred_at=evidence.occurred_at,
        recorded_at=evidence.event_recorded_at,
    )
    return R4PromotionLifecycleEventBundle.create(event=event, evidence=evidence)


def test_all_r4_persistence_payloads_round_trip_exactly() -> None:
    policy = promotion_policy()
    decision_bundle = promotion_decision_bundle()
    lifecycle_bundle = _lifecycle_bundle()

    assert decode_r4_promotion_policy(encode_r4_promotion_policy(policy)) == policy
    assert (
        decode_r4_promotion_decision_receipt(
            encode_r4_promotion_decision_receipt(decision_bundle.receipt)
        )
        == decision_bundle.receipt
    )
    assert (
        decode_r4_promotion_decision_bundle(encode_r4_promotion_decision_bundle(decision_bundle))
        == decision_bundle
    )
    assert (
        decode_r4_lifecycle_event_bundle(encode_r4_lifecycle_event_bundle(lifecycle_bundle))
        == lifecycle_bundle
    )


def test_codec_rejects_missing_extra_and_noncanonical_typed_fields() -> None:
    payload = encode_r4_promotion_decision_bundle(promotion_decision_bundle())
    missing = deepcopy(payload)
    tagged = cast(dict[str, object], missing["value"])
    values = cast(dict[str, object], tagged["$fields"])
    values.pop("content_hash")
    with pytest.raises(R4PromotionCodecError, match="missing or extra"):
        decode_r4_promotion_decision_bundle(missing)

    extra = deepcopy(payload)
    extra["unexpected"] = True
    with pytest.raises(R4PromotionCodecError, match="keys are missing or extra"):
        decode_r4_promotion_decision_bundle(extra)

    wrong_type = deepcopy(payload)
    tagged = cast(dict[str, object], wrong_type["value"])
    values = cast(dict[str, object], tagged["$fields"])
    values["content_hash"] = 7
    with pytest.raises(R4PromotionCodecError, match="field type mismatch"):
        decode_r4_promotion_decision_bundle(wrong_type)


@pytest.mark.parametrize("text", ("1.0", "NaN", "Infinity", "-Infinity"))
def test_codec_rejects_noncanonical_or_nonfinite_decimals(text: str) -> None:
    payload = encode_r4_promotion_policy(promotion_policy())
    tagged = cast(dict[str, object], payload["value"])
    values = cast(dict[str, object], tagged["$fields"])
    values["minimum_regime_coverage_ratio"] = {"$decimal": text}

    with pytest.raises(R4PromotionCodecError, match="Decimal"):
        decode_r4_promotion_policy(payload)


@pytest.mark.parametrize(
    "text",
    (
        "2025-12-15T00:00:00+00:00",
        "2025-12-15T08:00:00+08:00",
    ),
)
def test_codec_rejects_noncanonical_datetime_offsets(text: str) -> None:
    payload = encode_r4_promotion_policy(promotion_policy())
    tagged = cast(dict[str, object], payload["value"])
    values = cast(dict[str, object], tagged["$fields"])
    values["recorded_at"] = {"$datetime": text}

    with pytest.raises(R4PromotionCodecError, match="noncanonical.*datetime"):
        decode_r4_promotion_policy(payload)


def test_codec_rejects_nested_extra_scope_field() -> None:
    payload = encode_r4_promotion_policy(promotion_policy())
    tagged = cast(dict[str, object], payload["value"])
    values = cast(dict[str, object], tagged["$fields"])
    scope = cast(dict[str, object], values["scope"])
    scope_fields = cast(dict[str, object], scope["$fields"])
    scope_fields["unexpected"] = "forged"

    with pytest.raises(R4PromotionCodecError, match="missing or extra"):
        decode_r4_promotion_policy(payload)
