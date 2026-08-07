"""Strict codec coverage for persisted R5 promotion graphs."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest

from apps.research.application.r5_relative_value_promotion_decision import (
    R5RelativeValueDecisionAuthorization,
    R5RelativeValuePromotionDecisionBundle,
    R5RelativeValuePromotionRef,
)
from apps.research.application.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueLifecycleAuthorizationEvidence,
    R5RelativeValueLifecycleEventBundle,
)
from apps.research.domain.r5_relative_value_promotion_decision import (
    create_r5_relative_value_promotion_decision,
    r5_relative_value_promotion_decision_valid_until,
)
from apps.research.domain.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueLifecycleAuthorization,
    R5RelativeValueLifecycleEventType,
    create_r5_relative_value_lifecycle_root,
)
from apps.research.infrastructure.r5_relative_value_promotion_codec import (
    R5PromotionCodecError,
    decode_r5_decision_authorization,
    decode_r5_decision_bundle,
    decode_r5_lifecycle_authorization_evidence,
    decode_r5_lifecycle_event_bundle,
    decode_r5_promotion_artifact,
    encode_r5_decision_authorization,
    encode_r5_decision_bundle,
    encode_r5_lifecycle_authorization_evidence,
    encode_r5_lifecycle_event_bundle,
    encode_r5_promotion_artifact,
)
from tests.unit.research.r5_relative_value_promotion_factories import (
    BASE_TIME,
    make_policy,
    make_trial,
)


def _decision_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> R5RelativeValuePromotionDecisionBundle:
    policy = make_policy()
    trial = make_trial(monkeypatch, policy=policy)
    decided_at = BASE_TIME + timedelta(hours=3, minutes=1)
    policy_ref = R5RelativeValuePromotionRef(policy.policy_id, policy.policy_version)
    trial_ref = R5RelativeValuePromotionRef(trial.trial_id, trial.trial_version)
    authorization = R5RelativeValueDecisionAuthorization.create(
        authorization_version="decision-auth-v1",
        scope_id=policy.scope.scope_id,
        scope_content_hash=policy.scope.content_hash,
        policy_ref=policy_ref,
        trial_ref=trial_ref,
        issued_at=decided_at - timedelta(minutes=1),
        recorded_at=decided_at,
        decided_at=decided_at,
        decision_recorded_at=decided_at + timedelta(seconds=30),
        decision_valid_until=r5_relative_value_promotion_decision_valid_until(
            policy=policy,
            trial=trial,
            decided_at=decided_at,
        ),
        valid_until=trial.valid_until,
    )
    decision = create_r5_relative_value_promotion_decision(
        policy=policy,
        trial=trial,
        decided_at=decided_at,
        recorded_at=authorization.decision_recorded_at,
    )
    return R5RelativeValuePromotionDecisionBundle.create(
        decision=decision,
        authorization=authorization,
    )


def _lifecycle_bundle(
    decision_bundle: R5RelativeValuePromotionDecisionBundle,
) -> R5RelativeValueLifecycleEventBundle:
    occurred_at = decision_bundle.decision.recorded_at + timedelta(minutes=1)
    reasons = ("research_owner_approved",)
    authorization = R5RelativeValueLifecycleAuthorization.create(
        authorization_version="lifecycle-auth-v1",
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        decision=decision_bundle.decision,
        rollback_target=None,
        reason_codes=reasons,
        issued_at=occurred_at - timedelta(seconds=20),
        recorded_at=occurred_at - timedelta(seconds=10),
        valid_until=occurred_at + timedelta(hours=1),
    )
    event = create_r5_relative_value_lifecycle_root(
        event_version="event-v1",
        decision=decision_bundle.decision,
        authorization=authorization,
        reason_codes=reasons,
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(seconds=5),
    )
    evidence = R5RelativeValueLifecycleAuthorizationEvidence.from_event(
        evidence_version="lifecycle-evidence-v1",
        event=event,
        receipt_recorded_at=occurred_at - timedelta(seconds=5),
    )
    return R5RelativeValueLifecycleEventBundle.create(
        event=event,
        authorization_evidence=evidence,
    )


def test_complete_policy_trial_decision_and_lifecycle_graph_round_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every nested FixedIncome and Portfolio value survives exact replay."""

    decision_bundle = _decision_bundle(monkeypatch)
    lifecycle_bundle = _lifecycle_bundle(decision_bundle)
    policy = decision_bundle.decision.policy
    trial = decision_bundle.decision.trial

    assert decode_r5_promotion_artifact(encode_r5_promotion_artifact(policy)) == policy
    assert decode_r5_promotion_artifact(encode_r5_promotion_artifact(trial)) == trial
    assert (
        decode_r5_decision_authorization(
            encode_r5_decision_authorization(decision_bundle.authorization)
        )
        == decision_bundle.authorization
    )
    assert decode_r5_decision_bundle(encode_r5_decision_bundle(decision_bundle)) == decision_bundle
    assert (
        decode_r5_lifecycle_authorization_evidence(
            encode_r5_lifecycle_authorization_evidence(lifecycle_bundle.authorization_evidence)
        )
        == lifecycle_bundle.authorization_evidence
    )
    assert (
        decode_r5_lifecycle_event_bundle(encode_r5_lifecycle_event_bundle(lifecycle_bundle))
        == lifecycle_bundle
    )


def test_codec_rejects_extra_fields_and_noncanonical_decimal_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw JSON cannot add fields or choose an equivalent Decimal spelling."""

    payload = encode_r5_promotion_artifact(make_trial(monkeypatch))
    extra = deepcopy(payload)
    extra["unexpected"] = True
    with pytest.raises(R5PromotionCodecError):
        decode_r5_promotion_artifact(extra)

    noncanonical = deepcopy(payload)
    stack: list[object] = [noncanonical]
    changed = False
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if set(value) == {"$decimal"}:
                value["$decimal"] = f"{value['$decimal']}0"
                changed = True
                break
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    assert changed
    with pytest.raises(R5PromotionCodecError):
        decode_r5_promotion_artifact(noncanonical)
