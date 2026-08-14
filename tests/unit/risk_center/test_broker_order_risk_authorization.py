from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from apps.risk_center.domain.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationActor,
    BrokerOrderRiskAuthorizationActorKind,
    BrokerOrderRiskAuthorizationRecord,
    BrokerOrderRiskAuthorizationSubject,
    BrokerOrderRiskScope,
    broker_order_risk_authorization_identity_hash,
    broker_order_risk_subject_identity_hash,
    validate_risk_authorization_successor,
)

NOW = datetime(2026, 8, 13, 4, tzinfo=timezone.utc)
ORDER_ID = "56f9ae53-7606-46de-bf88-a6543f822d4a"


def _actor(actor_id: str, user_id: int) -> BrokerOrderRiskAuthorizationActor:
    return BrokerOrderRiskAuthorizationActor(
        actor_id=actor_id,
        kind=BrokerOrderRiskAuthorizationActorKind.HUMAN,
        is_staff=True,
        user_id=user_id,
    )


def _scope(**changes: object) -> BrokerOrderRiskScope:
    values: dict[str, object] = {
        "account_id": 7,
        "execution_scope_id": "execution-scope-1",
        "execution_scope_hash": "a" * 64,
        "plan_id": "plan-1",
        "plan_version": "v1",
        "plan_content_hash": "b" * 64,
        "plan_approval_hash": "c" * 64,
        "plan_valid_until": NOW + timedelta(hours=5),
        "order_id": ORDER_ID,
        "order_version": "v1",
        "order_content_hash": "d" * 64,
        "order_valid_until": NOW + timedelta(hours=4),
        "policy_id": "policy-1",
        "policy_version": "v1",
        "policy_content_hash": "e" * 64,
        "policy_activation_hash": "f" * 64,
        "policy_valid_until": NOW + timedelta(hours=3),
        "execution_scope_valid_until": NOW + timedelta(hours=2),
    }
    values.update(changes)
    return BrokerOrderRiskScope(**values)  # type: ignore[arg-type]


def _subject(**changes: object) -> BrokerOrderRiskAuthorizationSubject:
    scope = changes.pop("scope", _scope())
    assert isinstance(scope, BrokerOrderRiskScope)
    values: dict[str, object] = {
        "subject_id": "risk-subject:order-1:v1",
        "scope": scope,
        "requested_by": _actor("user:11", 11),
        "requested_at": NOW + timedelta(minutes=1),
        "valid_until": scope.effective_valid_until,
    }
    values.update(changes)
    return BrokerOrderRiskAuthorizationSubject(**values)  # type: ignore[arg-type]


def _record(**changes: object) -> BrokerOrderRiskAuthorizationRecord:
    subject = changes.pop("subject", _subject())
    assert isinstance(subject, BrokerOrderRiskAuthorizationSubject)
    values: dict[str, object] = {
        "authorization_id": "risk-authorization:order-1:v1",
        "subject": subject,
        "approved_by": _actor("user:19", 19),
        "issued_at": NOW + timedelta(minutes=2),
        "valid_until": subject.valid_until,
    }
    values.update(changes)
    return BrokerOrderRiskAuthorizationRecord(**values)  # type: ignore[arg-type]


def test_scope_subject_and_record_are_exact_content_addressed_contracts() -> None:
    scope = _scope()
    subject = _subject(scope=scope)
    record = _record(subject=subject)
    assert scope.effective_valid_until == NOW + timedelta(hours=2)
    assert all(len(value) == 64 for value in (scope.content_hash, subject.content_hash))
    assert len(record.content_hash) == 64
    assert record.permission_cap == "execution_eligible"
    assert record.is_valid_at(record.issued_at)
    assert not record.is_valid_at(record.valid_until)


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": True},
        {"execution_scope_hash": "A" * 64},
        {"order_id": "not-a-uuid"},
        {"policy_valid_until": datetime(2026, 8, 13, 7)},
        {"content_hash": "f" * 64},
    ],
)
def test_scope_fails_closed_on_invalid_identity_hash_or_clock(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _scope(**changes)


def test_each_upstream_change_changes_the_local_risk_scope_hash() -> None:
    original = _scope()
    assert _scope(plan_content_hash="f" * 64).content_hash != original.content_hash
    assert _scope(order_content_hash="f" * 64).content_hash != original.content_hash
    assert _scope(policy_content_hash="f" * 64).content_hash != original.content_hash
    assert _scope(execution_scope_hash="f" * 64).content_hash != original.content_hash


def test_request_and_approval_require_distinct_human_staff_actors() -> None:
    with pytest.raises(ValueError, match="non-human"):
        BrokerOrderRiskAuthorizationActor(
            actor_id="service:1",
            kind=BrokerOrderRiskAuthorizationActorKind.SERVICE,
            is_staff=True,
            user_id=1,
        )
    subject = _subject()
    with pytest.raises(ValueError, match="self approval"):
        _record(subject=subject, approved_by=_actor("other-id", 11))


def test_subject_and_record_validity_are_strict_intersections() -> None:
    scope = _scope()
    with pytest.raises(ValueError, match="strict scope minimum"):
        _subject(scope=scope, valid_until=scope.effective_valid_until - timedelta(seconds=1))
    subject = _subject(scope=scope)
    with pytest.raises(ValueError, match="match the subject"):
        _record(subject=subject, valid_until=subject.valid_until - timedelta(seconds=1))


def test_successor_binds_exact_head_subject_and_advanced_clock() -> None:
    previous = _record()
    scope = replace(
        previous.subject.scope,
        policy_content_hash="f" * 64,
        content_hash="",
    )
    subject = _subject(
        subject_id="risk-subject:order-1:v2",
        scope=scope,
        requested_at=previous.issued_at + timedelta(minutes=1),
        valid_until=scope.effective_valid_until,
        supersedes_authorization_hash=previous.content_hash,
    )
    successor = _record(
        authorization_id="risk-authorization:order-1:v2",
        subject=subject,
        issued_at=subject.requested_at + timedelta(minutes=1),
        valid_until=subject.valid_until,
    )
    validate_risk_authorization_successor(previous, successor)
    with pytest.raises(ValueError, match="exact previous"):
        validate_risk_authorization_successor(
            previous,
            replace(
                successor,
                subject=replace(
                    successor.subject,
                    supersedes_authorization_hash="0" * 64,
                    content_hash="",
                ),
                content_hash="",
            ),
        )


def test_identity_hashes_are_deterministic_and_separate() -> None:
    subject_hash = broker_order_risk_subject_identity_hash("subject-1")
    authorization_hash = broker_order_risk_authorization_identity_hash("authorization-1")
    assert len(subject_hash) == 64
    assert len(authorization_hash) == 64
    assert subject_hash != authorization_hash
