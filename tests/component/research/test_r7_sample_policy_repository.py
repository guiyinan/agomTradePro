"""Component coverage for the approved R7 sample policy ledger."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection

from apps.research.application.r7_sample_policy import (
    GetExactR7SamplePolicyCommand,
    R7SamplePolicyConflict,
    R7SamplePolicyCorruption,
    R7SamplePolicyOwnerApproval,
    R7SamplePolicyRegistrationDraft,
    R7SamplePolicyUnavailable,
    RegisterR7SamplePolicyCommand,
)
from apps.research.domain.r7_sample_policy import R7SamplePolicyAuthorization
from apps.research.infrastructure.r7_sample_policy_codec import R7SamplePolicyCodecError
from apps.research.infrastructure.r7_sample_policy_models import (
    R7SamplePolicyApprovalReceiptModel,
    R7SamplePolicyModel,
)
from apps.research.infrastructure.r7_sample_policy_repository import (
    DjangoR7SamplePolicyAuthorizationProvider,
    _policy_values,
)
from apps.research.r7_sample_policy_composition import (
    DjangoR7SamplePolicyRuntime,
    _build_django_r7_sample_policy_test_runtime,
    build_django_r7_sample_policy_runtime,
)
from tests.unit.research.r7_sample_policy_factories import (
    ACTIVATED_AT,
    RECORDED_AT,
    make_authorization,
    make_draft,
)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class DefinitionProvider:
    def __init__(self, draft: R7SamplePolicyRegistrationDraft) -> None:
        self.draft = draft
        self.calls: list[datetime] = []

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        as_of: datetime,
    ) -> R7SamplePolicyRegistrationDraft | None:
        self.calls.append(as_of)
        if (policy_id, policy_version) != (
            self.draft.policy_id,
            self.draft.policy_version,
        ):
            return None
        return self.draft


class AuthorizationProvider:
    def __init__(self, authorization: R7SamplePolicyAuthorization) -> None:
        self.authorization = authorization
        self.substitute = False

    @property
    def unit_of_work_key(self) -> str:
        return "django:default"

    def get_exact(
        self,
        *,
        authorization_id: str,
        authorization_version: str,
        policy_id: str,
        policy_version: str,
        scope_content_hash: str,
        policy_definition_hash: str,
        as_of: datetime,
    ) -> R7SamplePolicyOwnerApproval | None:
        item = self.authorization
        if self.substitute:
            item = make_authorization(
                make_draft(policy_id="r7-policy:substituted"),
                authorization_id=authorization_id,
                authorization_version=authorization_version,
            )
            return R7SamplePolicyOwnerApproval(
                authorization_id=item.authorization_id,
                authorization_version=item.authorization_version,
                owner_record_id=item.owner_record_id,
                owner_record_version=item.owner_record_version,
                owner_record_hash=item.owner_record_hash,
                policy_id=item.policy_id,
                policy_version=item.policy_version,
                scope_content_hash=item.scope_content_hash,
                policy_definition_hash=item.policy_definition_hash,
                approved_by=item.approved_by,
                issued_at=item.issued_at,
                valid_until=item.valid_until,
            )
        if (
            (item.authorization_id, item.authorization_version)
            != (authorization_id, authorization_version)
            or (item.policy_id, item.policy_version) != (policy_id, policy_version)
            or item.scope_content_hash != scope_content_hash
            or item.policy_definition_hash != policy_definition_hash
            or not item.issued_at <= as_of < item.valid_until
        ):
            return None
        return R7SamplePolicyOwnerApproval(
            authorization_id=item.authorization_id,
            authorization_version=item.authorization_version,
            owner_record_id=item.owner_record_id,
            owner_record_version=item.owner_record_version,
            owner_record_hash=item.owner_record_hash,
            policy_id=item.policy_id,
            policy_version=item.policy_version,
            scope_content_hash=item.scope_content_hash,
            policy_definition_hash=item.policy_definition_hash,
            approved_by=item.approved_by,
            issued_at=item.issued_at,
            valid_until=item.valid_until,
        )


@dataclass
class RuntimeFixture:
    runtime: DjangoR7SamplePolicyRuntime
    clock: FixedClock
    draft: R7SamplePolicyRegistrationDraft
    authorization: AuthorizationProvider


def _runtime() -> RuntimeFixture:
    draft = make_draft()
    clock = FixedClock(RECORDED_AT)
    authorization = AuthorizationProvider(make_authorization(draft))
    runtime = _build_django_r7_sample_policy_test_runtime(
        definition_provider=DefinitionProvider(draft),
        authorization_provider=DjangoR7SamplePolicyAuthorizationProvider(authorization),
        clock=clock,
    )
    return RuntimeFixture(runtime, clock, draft, authorization)


def _command(fixture: RuntimeFixture) -> RegisterR7SamplePolicyCommand:
    item = fixture.authorization.authorization
    return RegisterR7SamplePolicyCommand(
        policy_id=fixture.draft.policy_id,
        policy_version=fixture.draft.policy_version,
        authorization_id=item.authorization_id,
        authorization_version=item.authorization_version,
        as_of=RECORDED_AT,
    )


@pytest.mark.django_db
def test_production_runtime_stays_fail_closed_without_risk_center_owner_evidence() -> None:
    draft = make_draft()
    runtime = build_django_r7_sample_policy_runtime(
        definition_provider=DefinitionProvider(draft),
        clock=FixedClock(RECORDED_AT),
    )
    authorization = make_authorization(draft)
    with pytest.raises(R7SamplePolicyUnavailable, match="Risk Center owner approval"):
        runtime.register.execute(
            RegisterR7SamplePolicyCommand(
                policy_id=draft.policy_id,
                policy_version=draft.policy_version,
                authorization_id=authorization.authorization_id,
                authorization_version=authorization.authorization_version,
                as_of=RECORDED_AT,
            )
        )
    assert R7SamplePolicyApprovalReceiptModel._default_manager.count() == 0
    assert R7SamplePolicyModel._default_manager.count() == 0


@pytest.mark.django_db
def test_id_only_registration_uses_server_clock_and_external_approver() -> None:
    fixture = _runtime()
    record = fixture.runtime.register.execute(_command(fixture))

    assert record.recorded_at == RECORDED_AT
    assert record.policy.approved_by == "research-governance-owner"
    assert record.policy.approved_by != fixture.draft.policy_definition.approved_by
    assert R7SamplePolicyApprovalReceiptModel._default_manager.count() == 1
    assert R7SamplePolicyModel._default_manager.count() == 1

    fixture.clock.value = ACTIVATED_AT
    assert (
        fixture.runtime.policy_provider.get_active(
            scope=fixture.draft.scope,
            evaluated_at=ACTIVATED_AT,
        )
        == record.policy
    )
    assert (
        fixture.runtime.get_exact.execute(
            GetExactR7SamplePolicyCommand(
                policy_id=record.policy_id,
                policy_version=record.policy_version,
                expected_content_hash=record.content_hash,
                as_of=ACTIVATED_AT,
            )
        )
        == record
    )


@pytest.mark.django_db
def test_same_identity_substitution_stale_and_future_queries_fail_closed() -> None:
    fixture = _runtime()
    fixture.runtime.register.execute(_command(fixture))

    with pytest.raises(R7SamplePolicyConflict, match="already sealed"):
        fixture.runtime.register.execute(_command(fixture))
    fixture.clock.value = ACTIVATED_AT
    with pytest.raises(R7SamplePolicyUnavailable, match="no persisted"):
        fixture.runtime.repository.get_active_record(
            scope=fixture.draft.scope,
            as_of=RECORDED_AT - timedelta(microseconds=1),
        )
    with pytest.raises(R7SamplePolicyUnavailable, match="future"):
        fixture.runtime.repository.get_active_record(
            scope=fixture.draft.scope,
            as_of=ACTIVATED_AT + timedelta(microseconds=1),
        )

    other = _runtime()
    other.authorization.substitute = True
    with pytest.raises(ValueError, match="substitution"):
        other.runtime.register.execute(_command(other))
    assert R7SamplePolicyModel._default_manager.count() == 1


@pytest.mark.django_db
def test_expired_owner_authorization_cannot_keep_policy_active() -> None:
    fixture = _runtime()
    fixture.runtime.register.execute(_command(fixture))
    expired_authorization_as_of = fixture.authorization.authorization.valid_until + timedelta(
        microseconds=1
    )
    fixture.clock.value = expired_authorization_as_of

    with pytest.raises(R7SamplePolicyUnavailable, match="no persisted"):
        fixture.runtime.repository.get_active_record(
            scope=fixture.draft.scope,
            as_of=expired_authorization_as_of,
        )


@pytest.mark.django_db
def test_direct_bulk_base_and_delete_mutations_are_rejected() -> None:
    fixture = _runtime()
    record = fixture.runtime.register.execute(_command(fixture))
    row = R7SamplePolicyModel._default_manager.get()

    row.minimum_historical_analogies = 99
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(force_update=True)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be updated"):
        R7SamplePolicyModel._default_manager.update(minimum_historical_analogies=99)
    with pytest.raises(ValidationError, match="exact repository appends"):
        R7SamplePolicyModel._default_manager.bulk_create(
            [R7SamplePolicyModel(approval=row.approval, **_policy_values(record))]
        )
    with pytest.raises(ValidationError, match="exact insert claim"):
        R7SamplePolicyModel._default_manager.create(
            approval=row.approval,
            **_policy_values(record),
        )


@pytest.mark.django_db
def test_raw_header_and_payload_tamper_are_detected_before_use() -> None:
    fixture = _runtime()
    fixture.runtime.register.execute(_command(fixture))
    fixture.clock.value = ACTIVATED_AT
    row = R7SamplePolicyModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r7_sample_policy "
            "SET minimum_historical_analogies = %s WHERE id = %s",
            [99, row.pk],
        )
    with pytest.raises(R7SamplePolicyCorruption, match="header mismatch"):
        fixture.runtime.repository.get_active_record(
            scope=fixture.draft.scope,
            as_of=ACTIVATED_AT,
        )

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r7_sample_policy SET canonical_payload = %s WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(R7SamplePolicyCodecError):
        fixture.runtime.repository.get_active_record(
            scope=fixture.draft.scope,
            as_of=ACTIVATED_AT,
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("column", "expression"),
    [
        ("recorded_at", "datetime(activated_at, '-30 minutes')"),
        ("activated_at", "datetime(activated_at, '+1 second')"),
        ("valid_until", "datetime(activated_at, '+1 day')"),
    ],
)
def test_raw_clock_header_tamper_is_not_hidden_by_pit_sql_filter(
    column: str,
    expression: str,
) -> None:
    fixture = _runtime()
    fixture.runtime.register.execute(_command(fixture))
    fixture.clock.value = ACTIVATED_AT
    row = R7SamplePolicyModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE research_r7_sample_policy SET {column} = {expression} WHERE id = %s",
            [row.pk],
        )
    with pytest.raises(R7SamplePolicyCorruption):
        fixture.runtime.repository.get_active_record(
            scope=fixture.draft.scope,
            as_of=ACTIVATED_AT,
        )


@pytest.mark.django_db
def test_identity_and_scope_header_tamper_is_not_hidden_by_redundant_anchors() -> None:
    fixture = _runtime()
    record = fixture.runtime.register.execute(_command(fixture))
    fixture.clock.value = ACTIVATED_AT
    row = R7SamplePolicyModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r7_sample_policy SET policy_id = %s WHERE id = %s",
            ["r7-policy:tampered", row.pk],
        )
    with pytest.raises(R7SamplePolicyCorruption):
        fixture.runtime.get_exact.execute(
            GetExactR7SamplePolicyCommand(
                policy_id=record.policy_id,
                policy_version=record.policy_version,
                expected_content_hash=record.content_hash,
                as_of=ACTIVATED_AT,
            )
        )


@pytest.mark.django_db
def test_scope_header_tamper_is_not_hidden_by_redundant_anchors() -> None:
    fixture = _runtime()
    fixture.runtime.register.execute(_command(fixture))
    fixture.clock.value = ACTIVATED_AT
    row = R7SamplePolicyModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r7_sample_policy SET scope_content_hash = %s WHERE id = %s",
            ["b" * 64, row.pk],
        )
    with pytest.raises(R7SamplePolicyCorruption):
        fixture.runtime.repository.get_active_record(
            scope=fixture.draft.scope,
            as_of=ACTIVATED_AT,
        )


@pytest.mark.django_db(transaction=True)
def test_policy_insert_failure_rolls_back_approval_receipt() -> None:
    fixture = _runtime()
    with (
        patch.object(R7SamplePolicyModel, "save", side_effect=IntegrityError("race")),
        pytest.raises(R7SamplePolicyConflict, match="race lost"),
    ):
        fixture.runtime.register.execute(_command(fixture))

    assert R7SamplePolicyApprovalReceiptModel._default_manager.count() == 0
    assert R7SamplePolicyModel._default_manager.count() == 0
