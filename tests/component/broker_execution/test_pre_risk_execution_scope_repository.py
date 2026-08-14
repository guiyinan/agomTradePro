"""Component coverage for Broker pre-Risk scope append-only persistence."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations import RunPython, RunSQL

from apps.broker_execution.application.pre_risk_execution_scope import (
    BrokerPreRiskExecutionScopeRepository,
)
from apps.broker_execution.domain.pre_risk_execution_scope import (
    BrokerPreRiskExecutionScope,
)
from apps.broker_execution.infrastructure.order_approval_artifact_models import (
    _activate_order_approval_artifact_uow,
)
from apps.broker_execution.infrastructure.pre_risk_execution_scope_codec import (
    BrokerPreRiskExecutionScopeCodecError,
    decode_broker_pre_risk_execution_scope,
    encode_broker_pre_risk_execution_scope,
)
from apps.broker_execution.infrastructure.pre_risk_execution_scope_models import (
    BrokerPreRiskExecutionScopeModel,
)
from apps.broker_execution.infrastructure.pre_risk_execution_scope_repository import (
    BrokerPreRiskExecutionScopeConflict,
    BrokerPreRiskExecutionScopeCorruption,
    BrokerPreRiskExecutionScopeUnavailable,
    DjangoBrokerPreRiskExecutionScopeRepository,
    _model_values,
)

NOW = datetime(2026, 8, 13, 4, tzinfo=UTC)
ORDER_ID = "56f9ae53-7606-46de-bf88-a6543f822d4a"


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _scope(**changes: object) -> BrokerPreRiskExecutionScope:
    values: dict[str, object] = {
        "scope_id": "pre-risk-scope-1",
        "broker_account_id": 7,
        "portfolio_account_id": "portfolio-account-7",
        "plan_id": "transition-plan-1",
        "plan_version": 2,
        "plan_content_hash": "a" * 64,
        "plan_valid_until": NOW + timedelta(hours=5),
        "portfolio_receipt_id": "portfolio-receipt-1",
        "portfolio_receipt_version": "portfolio-receipt.v1",
        "portfolio_receipt_content_hash": "b" * 64,
        "portfolio_subject_id": "portfolio-subject-1",
        "portfolio_subject_version": "portfolio-subject.v1",
        "portfolio_subject_content_hash": "c" * 64,
        "portfolio_receipt_valid_until": NOW + timedelta(hours=4),
        "order_artifact_id": ORDER_ID,
        "order_artifact_version": "broker-order-artifact.v1.3",
        "order_artifact_content_hash": "d" * 64,
        "order_artifact_identity_hash": "e" * 64,
        "order_version": 3,
        "order_approval_digest": "f" * 64,
        "order_valid_until": NOW + timedelta(hours=3),
        "order_risk_policy_version": "risk-policy-v4",
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(hours=3),
    }
    values.update(changes)
    return BrokerPreRiskExecutionScope(**values)  # type: ignore[arg-type]


def _successor(previous: BrokerPreRiskExecutionScope) -> BrokerPreRiskExecutionScope:
    return _scope(
        scope_id="pre-risk-scope-2",
        recorded_at=NOW + timedelta(minutes=1),
        supersedes_scope_hash=previous.content_hash,
    )


def _repository(clock: FixedClock | None = None) -> DjangoBrokerPreRiskExecutionScopeRepository:
    return DjangoBrokerPreRiskExecutionScopeRepository(
        clock=clock or FixedClock(NOW + timedelta(minutes=2))
    )


def _accepts_application_protocol(
    repository: BrokerPreRiskExecutionScopeRepository,
) -> BrokerPreRiskExecutionScopeRepository:
    return repository


@pytest.mark.django_db
def test_append_round_trip_protocol_and_exact_historical_pit_boundaries() -> None:
    repository = _repository()
    assert _accepts_application_protocol(repository) is repository
    scope = _scope()

    with repository.atomic():
        persisted = repository.append(scope, expected_predecessor_hash=None, recorded_at=NOW)

    assert persisted == scope
    assert BrokerPreRiskExecutionScopeModel._default_manager.count() == 1
    assert (
        decode_broker_pre_risk_execution_scope(encode_broker_pre_risk_execution_scope(scope))
        == scope
    )
    assert (
        repository.get_exact_by_hash(
            scope_id=scope.scope_id,
            scope_version=scope.scope_version,
            expected_content_hash=scope.content_hash,
            as_of=NOW,
        )
        == scope
    )
    assert (
        repository.get_exact_by_hash(
            scope_id=scope.scope_id,
            scope_version=scope.scope_version,
            expected_content_hash=scope.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )


@pytest.mark.django_db
def test_full_chain_current_head_restores_historical_and_latest_heads() -> None:
    repository = _repository()
    root = _scope()
    successor = _successor(root)
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )

    assert (
        repository.get_current_head(broker_account_id=7, order_artifact_id=ORDER_ID, as_of=NOW)
        == root
    )
    assert (
        repository.get_current_head(
            broker_account_id=7,
            order_artifact_id=ORDER_ID,
            as_of=successor.recorded_at,
        )
        == successor
    )
    assert (
        repository.get_scope_winner(
            scope_id=successor.scope_id,
            scope_version=successor.scope_version,
            as_of=successor.recorded_at,
        )
        == successor
    )


@pytest.mark.django_db
def test_expired_successor_never_reactivates_still_valid_root() -> None:
    repository = _repository()
    root = _scope()
    successor = _scope(
        scope_id="pre-risk-scope-2",
        recorded_at=NOW + timedelta(minutes=1),
        order_valid_until=NOW + timedelta(minutes=2),
        valid_until=NOW + timedelta(minutes=2),
        supersedes_scope_hash=root.content_hash,
    )
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )

    assert (
        repository.get_current_head(
            broker_account_id=7,
            order_artifact_id=ORDER_ID,
            as_of=successor.valid_until,
        )
        is None
    )


@pytest.mark.django_db
def test_private_uow_is_independent_from_order_artifact_ledger_token() -> None:
    repository = _repository()
    scope = _scope()

    with pytest.raises(BrokerPreRiskExecutionScopeConflict, match="private unit"):
        repository.append(scope, expected_predecessor_hash=None, recorded_at=NOW)
    foreign_token = object()
    with (
        _activate_order_approval_artifact_uow(foreign_token),
        pytest.raises(BrokerPreRiskExecutionScopeConflict, match="private unit"),
    ):
        repository.append(scope, expected_predecessor_hash=None, recorded_at=NOW)


@pytest.mark.django_db
def test_root_and_predecessor_claims_preserve_single_chain_first_winners() -> None:
    repository = _repository()
    root = _scope()
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)

    conflicting_root = _scope(scope_id="other-root", plan_content_hash="0" * 64)
    with (
        repository.atomic(),
        pytest.raises(BrokerPreRiskExecutionScopeConflict, match="claim"),
    ):
        repository.append(conflicting_root, expected_predecessor_hash=None, recorded_at=NOW)

    successor = _successor(root)
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )
    competing_successor = _scope(
        scope_id="other-successor",
        recorded_at=NOW + timedelta(minutes=1),
        supersedes_scope_hash=root.content_hash,
        plan_content_hash="1" * 64,
    )
    with (
        repository.atomic(),
        pytest.raises(BrokerPreRiskExecutionScopeConflict, match="claim"),
    ):
        repository.append(
            competing_successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=competing_successor.recorded_at,
        )
    assert BrokerPreRiskExecutionScopeModel._default_manager.count() == 2


@pytest.mark.django_db
def test_identity_first_winner_and_predecessor_cas_fail_closed() -> None:
    repository = _repository()
    root = _scope()
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)

    identity_conflict = _scope(plan_content_hash="2" * 64)
    with (
        repository.atomic(),
        pytest.raises(BrokerPreRiskExecutionScopeConflict, match="first winner"),
    ):
        repository.append(identity_conflict, expected_predecessor_hash=None, recorded_at=NOW)
    successor = _successor(root)
    with (
        repository.atomic(),
        pytest.raises(BrokerPreRiskExecutionScopeConflict, match="expected predecessor"),
    ):
        repository.append(
            successor, expected_predecessor_hash=None, recorded_at=successor.recorded_at
        )


@pytest.mark.django_db
def test_direct_update_delete_bulk_and_unclaimed_create_are_blocked() -> None:
    repository = _repository()
    scope = _scope()
    with repository.atomic():
        repository.append(scope, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPreRiskExecutionScopeModel._default_manager.get()

    row.plan_id = "tampered"
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="cannot be updated"):
        BrokerPreRiskExecutionScopeModel._default_manager.update(plan_id="tampered")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        BrokerPreRiskExecutionScopeModel._default_manager.all().delete()
    values = _model_values(scope, recorded_at=NOW)
    with pytest.raises(ValidationError, match="exact insert claim"):
        BrokerPreRiskExecutionScopeModel._default_manager.create(**values)
    with pytest.raises(ValidationError, match="exact repository appends"):
        BrokerPreRiskExecutionScopeModel._default_manager.bulk_create(
            [BrokerPreRiskExecutionScopeModel(**values)]
        )


@pytest.mark.django_db
def test_header_payload_ledger_and_persistence_clock_tamper_fail_closed() -> None:
    repository = _repository()
    scope = _scope()
    with repository.atomic():
        repository.append(scope, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPreRiskExecutionScopeModel._default_manager.get()

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_pre_risk_scope SET plan_id = %s WHERE id = %s",
            ["tampered", row.pk],
        )
    with pytest.raises(BrokerPreRiskExecutionScopeCorruption, match="headers"):
        repository.get_exact_by_hash(
            scope_id=scope.scope_id,
            scope_version=scope.scope_version,
            expected_content_hash=scope.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db
def test_double_chain_selector_tamper_cannot_hide_successor_and_revive_root() -> None:
    repository = _repository()
    root = _scope()
    successor = _successor(root)
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )
    row = BrokerPreRiskExecutionScopeModel._default_manager.get(scope_id=successor.scope_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_pre_risk_scope "
            "SET broker_account_id = %s, order_artifact_id = %s WHERE id = %s",
            [8, "75df9306-cb1d-47de-8588-3bfce22a7930", row.pk],
        )

    with pytest.raises(BrokerPreRiskExecutionScopeCorruption, match="headers"):
        repository.get_current_head(
            broker_account_id=7,
            order_artifact_id=ORDER_ID,
            as_of=successor.recorded_at,
        )


@pytest.mark.django_db
def test_double_exact_selector_tamper_cannot_hide_identity_winner() -> None:
    repository = _repository()
    scope = _scope()
    with repository.atomic():
        repository.append(scope, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPreRiskExecutionScopeModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_pre_risk_scope "
            "SET scope_id = %s, content_hash = %s WHERE id = %s",
            ["hidden-scope", "9" * 64, row.pk],
        )

    with pytest.raises(BrokerPreRiskExecutionScopeCorruption, match="headers"):
        repository.get_exact_by_hash(
            scope_id=scope.scope_id,
            scope_version=scope.scope_version,
            expected_content_hash=scope.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db
def test_noncanonical_payload_and_future_cutoff_fail_closed() -> None:
    clock = FixedClock(NOW)
    repository = _repository(clock)
    scope = _scope()
    with repository.atomic():
        repository.append(scope, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPreRiskExecutionScopeModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_pre_risk_scope SET canonical_payload = %s WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(BrokerPreRiskExecutionScopeCorruption, match="payload"):
        repository.get_scope_winner(
            scope_id=scope.scope_id,
            scope_version=scope.scope_version,
            as_of=NOW,
        )
    with pytest.raises(BrokerPreRiskExecutionScopeUnavailable, match="future"):
        repository.get_current_head(
            broker_account_id=7,
            order_artifact_id=ORDER_ID,
            as_of=NOW + timedelta(microseconds=1),
        )


def test_codec_is_strict_and_migration_is_schema_only_zero_seed() -> None:
    payload = encode_broker_pre_risk_execution_scope(_scope())
    with pytest.raises(BrokerPreRiskExecutionScopeCodecError, match="shape"):
        decode_broker_pre_risk_execution_scope({**payload, "unknown": True})

    migration = importlib.import_module(
        "apps.broker_execution.migrations.0009_pre_risk_execution_scope"
    ).Migration
    assert migration.dependencies == [("broker_execution", "0008_order_approval_artifact")]
    assert migration.operations
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)
