"""Strict canonical codec coverage for Research R1 promotion evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest

from apps.research.application.r1_forecast_promotion import (
    R1PromotionLifecycleAction,
    R1PromotionLifecycleEventBundle,
    R1PromotionVersionRef,
)
from apps.research.domain.r1_forecast_promotion import (
    create_r1_promotion_lifecycle_root,
)
from apps.research.infrastructure.r1_forecast_promotion_codec import (
    R1PromotionCodecError,
    decode_r1_lifecycle_authorization_evidence,
    decode_r1_lifecycle_event_bundle,
    decode_r1_promotion_decision_bundle,
    decode_r1_promotion_policy,
    encode_r1_lifecycle_authorization_evidence,
    encode_r1_lifecycle_event_bundle,
    encode_r1_promotion_decision_bundle,
    encode_r1_promotion_policy,
)
from tests.unit.research.test_r1_forecast_promotion import _policy
from tests.unit.research.test_r1_forecast_promotion_lifecycle import _decision
from tests.unit.research.test_r1_forecast_promotion_lifecycle_application import (
    _bundle,
    _evidence,
)


def _lifecycle_bundle() -> R1PromotionLifecycleEventBundle:
    decision = _decision("codec-event", hour=1)
    event_ref = R1PromotionVersionRef("r1-event:codec", "event.v1")
    occurred_at = decision.recorded_at + timedelta(minutes=10)
    evidence = _evidence(
        event_ref=event_ref,
        decision=decision,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=occurred_at,
        reasons=("research_promotion_approved",),
    )
    event = create_r1_promotion_lifecycle_root(
        event_id=event_ref.stable_id,
        event_version=event_ref.version,
        decision=decision,
        authorization=evidence.authorization,
        reason_codes=evidence.reason_codes,
        occurred_at=evidence.occurred_at,
        recorded_at=evidence.event_recorded_at,
    )
    return R1PromotionLifecycleEventBundle.create(event=event, evidence=evidence)


def _record_fields(payload: dict[str, object], type_name: str) -> dict[str, object]:
    def visit(value: object) -> dict[str, object] | None:
        if isinstance(value, dict):
            if value.get("$type") == type_name and isinstance(value.get("$fields"), dict):
                return value["$fields"]  # type: ignore[return-value]
            for child in value.values():
                found = visit(child)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child)
                if found is not None:
                    return found
        return None

    result = visit(payload)
    if result is None:
        raise AssertionError(f"missing codec record: {type_name}")
    return result


def test_policy_round_trip_is_exact_and_typed() -> None:
    policy = _policy()

    payload = encode_r1_promotion_policy(policy)

    assert decode_r1_promotion_policy(payload) == policy


def test_decision_bundle_round_trip_revalidates_domain_and_application_hashes() -> None:
    bundle = _bundle(_decision("codec-decision", hour=1))

    payload = encode_r1_promotion_decision_bundle(bundle)

    assert decode_r1_promotion_decision_bundle(payload) == bundle


def test_authorization_evidence_round_trip_preserves_stable_server_clocks() -> None:
    bundle = _lifecycle_bundle()

    payload = encode_r1_lifecycle_authorization_evidence(bundle.evidence)

    restored = decode_r1_lifecycle_authorization_evidence(payload)
    assert restored == bundle.evidence
    assert restored.occurred_at == bundle.event.occurred_at
    assert restored.event_recorded_at == bundle.event.recorded_at


def test_event_bundle_round_trip_revalidates_embedded_receipt() -> None:
    bundle = _lifecycle_bundle()

    payload = encode_r1_lifecycle_event_bundle(bundle)

    assert decode_r1_lifecycle_event_bundle(payload) == bundle


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_missing_or_extra_nested_fields_are_rejected(mutation: str) -> None:
    payload = encode_r1_promotion_decision_bundle(_bundle(_decision("codec-fields", hour=1)))
    fields = _record_fields(payload, "R1ForecastPromotionDecision")
    if mutation == "missing":
        fields.pop("reason_codes")
    else:
        fields["caller_attestation"] = True

    with pytest.raises(R1PromotionCodecError, match="missing or extra"):
        decode_r1_promotion_decision_bundle(payload)


def test_noncanonical_decimal_and_timezone_are_rejected() -> None:
    decimal_payload = encode_r1_promotion_policy(_policy())
    policy_fields = _record_fields(decimal_payload, "R1ForecastPromotionPolicy")
    decimal_tag = policy_fields["minimum_metric_coverage"]
    assert isinstance(decimal_tag, dict)
    decimal_tag["$decimal"] = "1.0"
    with pytest.raises(R1PromotionCodecError, match="noncanonical.*Decimal"):
        decode_r1_promotion_policy(decimal_payload)

    time_payload = encode_r1_promotion_policy(_policy())
    time_fields = _record_fields(time_payload, "R1ForecastPromotionPolicy")
    datetime_tag = time_fields["approved_at"]
    assert isinstance(datetime_tag, dict)
    datetime_tag["$datetime"] = str(datetime_tag["$datetime"]).replace("Z", "+00:00")
    with pytest.raises(R1PromotionCodecError, match="noncanonical.*datetime"):
        decode_r1_promotion_policy(time_payload)


def test_rehashed_domain_content_and_bundle_hash_tamper_are_rejected() -> None:
    decision_payload = encode_r1_promotion_decision_bundle(_bundle(_decision("codec-hash", hour=1)))
    decision_fields = _record_fields(decision_payload, "R1ForecastPromotionDecision")
    decision_fields["content_hash"] = "0" * 64
    with pytest.raises(R1PromotionCodecError, match="validation failed"):
        decode_r1_promotion_decision_bundle(decision_payload)

    event_payload = encode_r1_lifecycle_event_bundle(_lifecycle_bundle())
    event_bundle_fields = _record_fields(event_payload, "R1PromotionLifecycleEventBundle")
    event_bundle_fields["content_hash"] = "0" * 64
    with pytest.raises(R1PromotionCodecError, match="validation failed"):
        decode_r1_lifecycle_event_bundle(event_payload)


def test_wrong_envelope_type_and_unknown_tags_are_rejected() -> None:
    policy_payload = encode_r1_promotion_policy(_policy())
    with pytest.raises(R1PromotionCodecError, match="schema mismatch"):
        decode_r1_promotion_decision_bundle(policy_payload)

    malformed = deepcopy(policy_payload)
    malformed["value"] = {"$caller": "self-signed"}
    with pytest.raises(R1PromotionCodecError, match="unknown or noncanonical"):
        decode_r1_promotion_policy(malformed)
