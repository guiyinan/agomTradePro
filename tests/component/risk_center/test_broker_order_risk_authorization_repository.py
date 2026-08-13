"""Component coverage for Broker order risk authorization persistence."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations import RunPython

from apps.risk_center.application.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationConflict,
    BrokerOrderRiskAuthorizationCorruption,
    BrokerOrderRiskAuthorizationUnavailable,
)
from apps.risk_center.domain.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationActor,
    BrokerOrderRiskAuthorizationActorKind,
    BrokerOrderRiskAuthorizationRecord,
    BrokerOrderRiskAuthorizationSubject,
    BrokerOrderRiskScope,
)
from apps.risk_center.infrastructure.broker_order_risk_authorization_codec import (
    decode_broker_order_risk_authorization_record,
    encode_broker_order_risk_authorization_record,
)
from apps.risk_center.infrastructure.broker_order_risk_authorization_models import (
    BrokerOrderRiskAuthorizationRecordModel,
    BrokerOrderRiskAuthorizationSubjectModel,
)
from apps.risk_center.infrastructure.broker_order_risk_authorization_repository import (
    DjangoBrokerOrderRiskAuthorizationRepository,
    _record_values,
)

REQUESTED_AT = datetime(2026, 8, 13, 8, tzinfo=UTC)
VALID_UNTIL = datetime(2026, 8, 14, 8, tzinfo=UTC)
ORDER_ID = "12345678-1234-5678-1234-567812345678"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _actor(actor_id: str, user_id: int) -> BrokerOrderRiskAuthorizationActor:
    return BrokerOrderRiskAuthorizationActor(
        actor_id=actor_id,
        kind=BrokerOrderRiskAuthorizationActorKind.HUMAN,
        is_staff=True,
        user_id=user_id,
    )


def _scope() -> BrokerOrderRiskScope:
    return BrokerOrderRiskScope(
        account_id=41,
        execution_scope_id="broker-scope:41:order",
        execution_scope_hash=HASH_A,
        plan_id="transition-plan:41",
        plan_version="1",
        plan_content_hash=HASH_B,
        plan_approval_hash=HASH_C,
        plan_valid_until=VALID_UNTIL + timedelta(hours=3),
        order_id=ORDER_ID,
        order_version="1",
        order_content_hash=HASH_D,
        order_valid_until=VALID_UNTIL + timedelta(hours=2),
        policy_id="risk-policy:41",
        policy_version="1",
        policy_content_hash=HASH_E,
        policy_valid_until=VALID_UNTIL + timedelta(hours=1),
        execution_scope_valid_until=VALID_UNTIL,
    )


def _subject(
    *,
    subject_id: str = "broker-risk-subject:41:order:1",
    requested_at: datetime = REQUESTED_AT,
    supersedes: str | None = None,
) -> BrokerOrderRiskAuthorizationSubject:
    return BrokerOrderRiskAuthorizationSubject(
        subject_id=subject_id,
        scope=_scope(),
        requested_by=_actor("user:risk-requester", 41),
        requested_at=requested_at,
        valid_until=VALID_UNTIL,
        supersedes_authorization_hash=supersedes,
    )


def _record(
    subject: BrokerOrderRiskAuthorizationSubject,
    *,
    authorization_id: str = "broker-risk-authorization:41:order:1",
    issued_at: datetime = REQUESTED_AT,
) -> BrokerOrderRiskAuthorizationRecord:
    return BrokerOrderRiskAuthorizationRecord(
        authorization_id=authorization_id,
        subject=subject,
        approved_by=_actor("user:risk-approver", 42),
        issued_at=issued_at,
        valid_until=VALID_UNTIL,
    )


@pytest.mark.django_db
def test_append_exact_pit_and_codec_round_trip() -> None:
    clock = FixedClock(REQUESTED_AT)
    repository = DjangoBrokerOrderRiskAuthorizationRepository(clock=clock)
    subject = _subject()
    record = _record(subject)

    with repository.atomic():
        assert repository.append_subject(subject, recorded_at=REQUESTED_AT) == subject
        assert (
            repository.append(record, expected_predecessor_hash=None, recorded_at=REQUESTED_AT)
            == record
        )

    assert BrokerOrderRiskAuthorizationSubjectModel._default_manager.count() == 1
    assert BrokerOrderRiskAuthorizationRecordModel._default_manager.count() == 1
    assert (
        decode_broker_order_risk_authorization_record(
            encode_broker_order_risk_authorization_record(record)
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            authorization_id=record.authorization_id,
            authorization_version=record.authorization_version,
            expected_content_hash=record.content_hash,
            as_of=REQUESTED_AT,
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            authorization_id=record.authorization_id,
            authorization_version=record.authorization_version,
            expected_content_hash=record.content_hash,
            as_of=REQUESTED_AT - timedelta(microseconds=1),
        )
        is None
    )


@pytest.mark.django_db
def test_private_uow_and_append_only_guards_reject_shortcuts() -> None:
    subject = _subject()
    record = _record(subject)
    values = _record_values(record, recorded_at=REQUESTED_AT)

    with pytest.raises(BrokerOrderRiskAuthorizationConflict, match="private unit"):
        DjangoBrokerOrderRiskAuthorizationRepository(clock=FixedClock(REQUESTED_AT)).append_subject(
            subject, recorded_at=REQUESTED_AT
        )
    with pytest.raises(ValidationError, match="exact insert claim"):
        BrokerOrderRiskAuthorizationSubjectModel._default_manager.create(
            subject_id=subject.subject_id
        )
    with pytest.raises(ValidationError, match="exact repository appends"):
        BrokerOrderRiskAuthorizationRecordModel._default_manager.bulk_create(
            [BrokerOrderRiskAuthorizationRecordModel(**values)]
        )


@pytest.mark.django_db
def test_successor_advances_unique_current_head() -> None:
    first_time = REQUESTED_AT
    second_time = REQUESTED_AT + timedelta(hours=1)
    clock = FixedClock(first_time)
    repository = DjangoBrokerOrderRiskAuthorizationRepository(clock=clock)
    first_subject = _subject()
    first = _record(first_subject)
    with repository.atomic():
        repository.append_subject(first_subject, recorded_at=first_time)
        repository.append(first, expected_predecessor_hash=None, recorded_at=first_time)

    clock.value = second_time
    successor_subject = _subject(
        subject_id="broker-risk-subject:41:order:2",
        requested_at=second_time,
        supersedes=first.content_hash,
    )
    successor = _record(
        successor_subject,
        authorization_id="broker-risk-authorization:41:order:2",
        issued_at=second_time,
    )
    with repository.atomic():
        repository.append_subject(successor_subject, recorded_at=second_time)
        repository.append(
            successor,
            expected_predecessor_hash=first.content_hash,
            recorded_at=second_time,
        )

    assert repository.get_current_head(account_id=41, order_id=ORDER_ID, as_of=first_time) == first
    assert (
        repository.get_current_head(account_id=41, order_id=ORDER_ID, as_of=second_time)
        == successor
    )


@pytest.mark.django_db
def test_future_read_and_payload_tamper_fail_closed() -> None:
    clock = FixedClock(REQUESTED_AT)
    repository = DjangoBrokerOrderRiskAuthorizationRepository(clock=clock)
    subject = _subject()
    record = _record(subject)
    with repository.atomic():
        repository.append_subject(subject, recorded_at=REQUESTED_AT)
        repository.append(record, expected_predecessor_hash=None, recorded_at=REQUESTED_AT)

    with pytest.raises(BrokerOrderRiskAuthorizationUnavailable, match="future"):
        repository.get_exact_by_hash(
            authorization_id=record.authorization_id,
            authorization_version=record.authorization_version,
            expected_content_hash=record.content_hash,
            as_of=REQUESTED_AT + timedelta(microseconds=1),
        )
    row = BrokerOrderRiskAuthorizationRecordModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE risk_center_broker_order_risk_authorization "
            "SET canonical_payload = %s WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(BrokerOrderRiskAuthorizationCorruption, match="payload"):
        repository.get_authorization_winner(
            authorization_id=record.authorization_id, as_of=REQUESTED_AT
        )


def test_migration_is_schema_only_and_zero_seed() -> None:
    migration = importlib.import_module(
        "apps.risk_center.migrations.0008_broker_order_risk_authorizations"
    ).Migration

    assert migration.operations
    assert not any(isinstance(operation, RunPython) for operation in migration.operations)


@pytest.mark.django_db
def test_append_rejects_stale_predecessor_after_head_advances() -> None:
    first_time = REQUESTED_AT
    second_time = REQUESTED_AT + timedelta(hours=1)
    third_time = REQUESTED_AT + timedelta(hours=2)
    clock = FixedClock(first_time)
    repository = DjangoBrokerOrderRiskAuthorizationRepository(clock=clock)
    first_subject = _subject()
    first = _record(first_subject)
    with repository.atomic():
        repository.append_subject(first_subject, recorded_at=first_time)
        repository.append(first, expected_predecessor_hash=None, recorded_at=first_time)
    clock.value = second_time
    successor_subject = _subject(
        subject_id="broker-risk-subject:41:order:2",
        requested_at=second_time,
        supersedes=first.content_hash,
    )
    successor = _record(
        successor_subject,
        authorization_id="broker-risk-authorization:41:order:2",
        issued_at=second_time,
    )
    with repository.atomic():
        repository.append_subject(successor_subject, recorded_at=second_time)
        repository.append(
            successor,
            expected_predecessor_hash=first.content_hash,
            recorded_at=second_time,
        )

    clock.value = third_time
    stale_subject = _subject(
        subject_id="broker-risk-subject:41:order:stale",
        requested_at=third_time,
        supersedes=first.content_hash,
    )
    stale = _record(
        stale_subject,
        authorization_id="broker-risk-authorization:41:order:stale",
        issued_at=third_time,
    )
    with repository.atomic():
        repository.append_subject(stale_subject, recorded_at=third_time)
        with pytest.raises(BrokerOrderRiskAuthorizationConflict, match="current head changed"):
            repository.append(
                stale,
                expected_predecessor_hash=first.content_hash,
                recorded_at=third_time,
            )
