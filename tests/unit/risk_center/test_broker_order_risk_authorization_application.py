from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from apps.risk_center.application.broker_order_risk_authorization import (
    ApproveBrokerOrderRiskAuthorization,
    ApproveBrokerOrderRiskAuthorizationCommand,
    BrokerOrderExecutionScopeDefinition,
    BrokerOrderRiskAuthorizationConflict,
    BrokerOrderRiskAuthorizationCorruption,
    BrokerOrderRiskPolicyDefinition,
    GetCurrentBrokerOrderRiskAuthorizationForScope,
    GetCurrentBrokerOrderRiskAuthorizationForScopeCommand,
    GetExactBrokerOrderRiskAuthorization,
    GetExactBrokerOrderRiskAuthorizationCommand,
    RegisterBrokerOrderRiskAuthorizationSubject,
    RegisterBrokerOrderRiskAuthorizationSubjectCommand,
)
from apps.risk_center.domain.broker_order_risk_authorization import (
    BROKER_ORDER_RISK_AUTHORIZATION_VERSION,
    BROKER_ORDER_RISK_SCOPE_VERSION,
    BrokerOrderRiskAuthorizationActor,
    BrokerOrderRiskAuthorizationActorKind,
    BrokerOrderRiskAuthorizationRecord,
    BrokerOrderRiskAuthorizationSubject,
)

NOW = datetime(2026, 8, 13, 5, tzinfo=timezone.utc)
ORDER_ID = "56f9ae53-7606-46de-bf88-a6543f822d4a"


def _actor(actor_id: str, user_id: int) -> BrokerOrderRiskAuthorizationActor:
    return BrokerOrderRiskAuthorizationActor(
        actor_id=actor_id,
        kind=BrokerOrderRiskAuthorizationActorKind.HUMAN,
        is_staff=True,
        user_id=user_id,
    )


def _scope_definition(**changes: object) -> BrokerOrderExecutionScopeDefinition:
    values: dict[str, object] = {
        "execution_scope_id": "scope-1",
        "execution_scope_version": BROKER_ORDER_RISK_SCOPE_VERSION,
        "execution_scope_hash": "a" * 64,
        "account_id": 7,
        "plan_id": "plan-1",
        "plan_version": "v1",
        "plan_content_hash": "b" * 64,
        "plan_approval_hash": "c" * 64,
        "plan_valid_until": NOW + timedelta(hours=5),
        "order_id": ORDER_ID,
        "order_version": "v1",
        "order_content_hash": "d" * 64,
        "order_valid_until": NOW + timedelta(hours=4),
        "scope_valid_until": NOW + timedelta(hours=3),
        "recorded_at": NOW - timedelta(minutes=1),
    }
    values.update(changes)
    return BrokerOrderExecutionScopeDefinition(**values)  # type: ignore[arg-type]


def _policy_definition(**changes: object) -> BrokerOrderRiskPolicyDefinition:
    values: dict[str, object] = {
        "policy_id": "policy-1",
        "policy_version": "v1",
        "policy_content_hash": "e" * 64,
        "account_id": 7,
        "activated_at": NOW - timedelta(minutes=1),
        "valid_until": NOW + timedelta(hours=2),
        "recorded_at": NOW - timedelta(minutes=2),
    }
    values.update(changes)
    return BrokerOrderRiskPolicyDefinition(**values)  # type: ignore[arg-type]


class _SequenceProvider:
    def __init__(self, *values: object) -> None:
        self.values = list(values)

    def get_exact_active(self, **kwargs: object) -> object:
        del kwargs
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


class _SubjectProvider:
    def __init__(self, value: BrokerOrderRiskAuthorizationSubject) -> None:
        self.value = value

    def get_exact(self, **kwargs: object) -> BrokerOrderRiskAuthorizationSubject:
        del kwargs
        return self.value


class _Repository:
    def __init__(self) -> None:
        self.clock = NOW
        self.subject: BrokerOrderRiskAuthorizationSubject | None = None
        self.authorization: BrokerOrderRiskAuthorizationRecord | None = None
        self.head: BrokerOrderRiskAuthorizationRecord | None = None

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_subject_winner(self, **kwargs: object) -> BrokerOrderRiskAuthorizationSubject | None:
        del kwargs
        return self.subject

    def get_authorization_winner(
        self, **kwargs: object
    ) -> BrokerOrderRiskAuthorizationRecord | None:
        del kwargs
        return self.authorization

    def get_current_head(self, **kwargs: object) -> BrokerOrderRiskAuthorizationRecord | None:
        del kwargs
        return self.head

    def append_subject(
        self, subject: BrokerOrderRiskAuthorizationSubject, **kwargs: object
    ) -> BrokerOrderRiskAuthorizationSubject:
        del kwargs
        self.subject = subject
        return subject

    def append(
        self, record: BrokerOrderRiskAuthorizationRecord, **kwargs: object
    ) -> BrokerOrderRiskAuthorizationRecord:
        del kwargs
        self.authorization = record
        self.head = record
        return record

    def get_exact_by_hash(self, **kwargs: object) -> BrokerOrderRiskAuthorizationRecord | None:
        del kwargs
        return self.authorization


def _register(
    repository: _Repository,
    *,
    scope_provider: _SequenceProvider | None = None,
    policy_provider: _SequenceProvider | None = None,
) -> BrokerOrderRiskAuthorizationSubject:
    use_case = RegisterBrokerOrderRiskAuthorizationSubject(
        scope_provider=scope_provider or _SequenceProvider(_scope_definition()),  # type: ignore[arg-type]
        policy_provider=policy_provider or _SequenceProvider(_policy_definition()),  # type: ignore[arg-type]
        repository=repository,
        actor=_actor("user:11", 11),
    )
    return use_case.execute(
        RegisterBrokerOrderRiskAuthorizationSubjectCommand(
            subject_id="subject-1",
            execution_scope_id="scope-1",
            execution_scope_version=BROKER_ORDER_RISK_SCOPE_VERSION,
            policy_id="policy-1",
            policy_version="v1",
        )
    )


def test_register_uses_server_owned_sources_and_strict_validity_minimum() -> None:
    repository = _Repository()
    subject = _register(repository)
    assert subject.requested_at == NOW
    assert subject.valid_until == NOW + timedelta(hours=2)
    assert subject.scope.account_id == 7
    assert repository.subject == subject


def test_register_rejects_account_mismatch_and_provider_drift() -> None:
    with pytest.raises(BrokerOrderRiskAuthorizationCorruption, match="account"):
        _register(
            _Repository(),
            policy_provider=_SequenceProvider(_policy_definition(account_id=8)),
        )
    with pytest.raises(BrokerOrderRiskAuthorizationCorruption, match="changed"):
        _register(
            _Repository(),
            scope_provider=_SequenceProvider(
                _scope_definition(),
                _scope_definition(execution_scope_hash="f" * 64),
            ),
        )


def test_register_exact_replay_and_conflicting_first_winner() -> None:
    repository = _Repository()
    first = _register(repository)
    repository.clock += timedelta(minutes=1)
    assert _register(repository) == first
    repository.subject = replace(first, subject_id="other", content_hash="")
    with pytest.raises(BrokerOrderRiskAuthorizationConflict):
        _register(repository)


def test_approve_rereads_owner_sources_and_forbids_self_approval() -> None:
    repository = _Repository()
    subject = _register(repository)
    shared = {
        "subject_provider": _SubjectProvider(subject),
        "scope_provider": _SequenceProvider(_scope_definition()),
        "policy_provider": _SequenceProvider(_policy_definition()),
        "repository": repository,
    }
    with pytest.raises(ValueError, match="self approval"):
        ApproveBrokerOrderRiskAuthorization(
            **shared, actor=_actor("another-id", 11)  # type: ignore[arg-type]
        ).execute(
            ApproveBrokerOrderRiskAuthorizationCommand(
                subject_id="subject-1", authorization_id="authorization-1"
            )
        )

    record = ApproveBrokerOrderRiskAuthorization(
        **shared, actor=_actor("user:19", 19)  # type: ignore[arg-type]
    ).execute(
        ApproveBrokerOrderRiskAuthorizationCommand(
            subject_id="subject-1", authorization_id="authorization-1"
        )
    )
    assert record.subject == subject
    assert record.issued_at == NOW
    repository.clock += timedelta(minutes=1)
    assert (
        ApproveBrokerOrderRiskAuthorization(
            **shared, actor=_actor("user:19", 19)  # type: ignore[arg-type]
        ).execute(
            ApproveBrokerOrderRiskAuthorizationCommand(
                subject_id="subject-1", authorization_id="authorization-1"
            )
        )
        == record
    )


def test_approve_rejects_owner_source_drift_and_head_change() -> None:
    repository = _Repository()
    subject = _register(repository)
    use_case = ApproveBrokerOrderRiskAuthorization(
        subject_provider=_SubjectProvider(subject),
        scope_provider=_SequenceProvider(
            _scope_definition(execution_scope_hash="f" * 64)
        ),  # type: ignore[arg-type]
        policy_provider=_SequenceProvider(_policy_definition()),  # type: ignore[arg-type]
        repository=repository,
        actor=_actor("user:19", 19),
    )
    with pytest.raises(BrokerOrderRiskAuthorizationCorruption, match="no longer matches"):
        use_case.execute(
            ApproveBrokerOrderRiskAuthorizationCommand(
                subject_id="subject-1", authorization_id="authorization-1"
            )
        )


def test_exact_read_revalidates_identity_hash_and_pit() -> None:
    repository = _Repository()
    subject = _register(repository)
    record = ApproveBrokerOrderRiskAuthorization(
        subject_provider=_SubjectProvider(subject),
        scope_provider=_SequenceProvider(_scope_definition()),  # type: ignore[arg-type]
        policy_provider=_SequenceProvider(_policy_definition()),  # type: ignore[arg-type]
        repository=repository,
        actor=_actor("user:19", 19),
    ).execute(
        ApproveBrokerOrderRiskAuthorizationCommand(
            subject_id="subject-1", authorization_id="authorization-1"
        )
    )
    facade = GetExactBrokerOrderRiskAuthorization(repository)
    assert (
        facade.execute(
            GetExactBrokerOrderRiskAuthorizationCommand(
                authorization_id=record.authorization_id,
                authorization_version=BROKER_ORDER_RISK_AUTHORIZATION_VERSION,
                expected_content_hash=record.content_hash,
                as_of=NOW,
            )
        )
        == record
    )
    assert (
        facade.execute(
            GetExactBrokerOrderRiskAuthorizationCommand(
                authorization_id=record.authorization_id,
                authorization_version=BROKER_ORDER_RISK_AUTHORIZATION_VERSION,
                expected_content_hash=record.content_hash,
                as_of=record.valid_until,
            )
        )
        is None
    )


def test_approve_requires_persisted_subject_first_winner() -> None:
    repository = _Repository()
    subject = _register(repository)
    repository.subject = None
    with pytest.raises(Exception, match="persisted risk authorization subject"):
        ApproveBrokerOrderRiskAuthorization(
            subject_provider=_SubjectProvider(subject),
            scope_provider=_SequenceProvider(_scope_definition()),  # type: ignore[arg-type]
            policy_provider=_SequenceProvider(_policy_definition()),  # type: ignore[arg-type]
            repository=repository,
            actor=_actor("user:19", 19),
        ).execute(
            ApproveBrokerOrderRiskAuthorizationCommand(
                subject_id="subject-1", authorization_id="authorization-1"
            )
        )


def test_current_scope_read_rejects_superseded_old_record() -> None:
    repository = _Repository()
    subject = _register(repository)
    record = ApproveBrokerOrderRiskAuthorization(
        subject_provider=_SubjectProvider(subject),
        scope_provider=_SequenceProvider(_scope_definition()),  # type: ignore[arg-type]
        policy_provider=_SequenceProvider(_policy_definition()),  # type: ignore[arg-type]
        repository=repository,
        actor=_actor("user:19", 19),
    ).execute(
        ApproveBrokerOrderRiskAuthorizationCommand(
            subject_id="subject-1", authorization_id="authorization-1"
        )
    )
    command = GetCurrentBrokerOrderRiskAuthorizationForScopeCommand(
        authorization_id=record.authorization_id,
        authorization_version=record.authorization_version,
        expected_content_hash=record.content_hash,
        execution_scope_id=record.subject.scope.execution_scope_id,
        execution_scope_version=record.subject.scope.execution_scope_version,
        execution_scope_hash=record.subject.scope.execution_scope_hash,
        account_id=record.subject.scope.account_id,
        plan_id=record.subject.scope.plan_id,
        plan_version=record.subject.scope.plan_version,
        order_id=record.subject.scope.order_id,
        order_version=record.subject.scope.order_version,
        policy_id=record.subject.scope.policy_id,
        policy_version=record.subject.scope.policy_version,
        as_of=NOW,
    )
    facade = GetCurrentBrokerOrderRiskAuthorizationForScope(repository)
    assert facade.execute(command) == record
    repository.head = replace(record, authorization_id="authorization-2", content_hash="")
    assert facade.execute(command) is None
