"""Component coverage for Broker/Portfolio binding persistence."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.db.migrations import RunPython, RunSQL

from apps.broker_execution.application.portfolio_broker_account_binding import (
    BrokerPortfolioAccountBindingConflict,
    BrokerPortfolioAccountBindingCorruption,
    BrokerPortfolioAccountBindingRepository,
    BrokerPortfolioAccountBindingUnavailable,
)
from apps.broker_execution.domain.portfolio_broker_account_binding import (
    ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
    ACCOUNT_BINDING_SOURCE_OWNER,
    BROKER_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
    BROKER_ACCOUNT_BINDING_SOURCE_OWNER,
    BrokerPortfolioAccountBindingActor,
    BrokerPortfolioAccountNamespaceBinding,
)
from apps.broker_execution.infrastructure.broker_account_identity_snapshot_models import (
    _activate_broker_account_identity_uow,
)
from apps.broker_execution.infrastructure.portfolio_broker_account_binding_codec import (
    BrokerPortfolioAccountBindingCodecError,
    decode_broker_portfolio_account_binding,
    encode_broker_portfolio_account_binding,
)
from apps.broker_execution.infrastructure.portfolio_broker_account_binding_models import (
    BrokerPortfolioAccountBindingModel,
)
from apps.broker_execution.infrastructure.portfolio_broker_account_binding_repository import (
    DjangoBrokerPortfolioAccountBindingRepository,
    _model_values,
    _validate_closed_world,
)

NOW = datetime(2026, 8, 13, 10, tzinfo=UTC)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _actor() -> BrokerPortfolioAccountBindingActor:
    return BrokerPortfolioAccountBindingActor(
        actor_id="staff-user-9", user_id=9, role="broker-identity-operator"
    )


def _binding(**changes: object) -> BrokerPortfolioAccountNamespaceBinding:
    values: dict[str, object] = {
        "binding_id": "portfolio-broker-binding-1",
        "broker_account_namespace": "qmt-live",
        "broker_account_id": 42,
        "portfolio_account_namespace": "account-primary",
        "portfolio_account_id": "portfolio-account-alpha",
        "owner_user_id": 7,
        "broker_source_owner": BROKER_ACCOUNT_BINDING_SOURCE_OWNER,
        "broker_source_artifact_type": BROKER_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
        "broker_source_id": "broker-account-source-1",
        "broker_source_version": "v1",
        "broker_source_content_hash": "a" * 64,
        "portfolio_source_owner": ACCOUNT_BINDING_SOURCE_OWNER,
        "portfolio_source_artifact_type": ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
        "portfolio_source_id": "account-source-1",
        "portfolio_source_version": "v1",
        "portfolio_source_content_hash": "b" * 64,
        "asserted_by": _actor(),
        "issued_at": NOW,
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(hours=2),
    }
    values.update(changes)
    return BrokerPortfolioAccountNamespaceBinding(**values)  # type: ignore[arg-type]


def _successor(
    previous: BrokerPortfolioAccountNamespaceBinding, **changes: object
) -> BrokerPortfolioAccountNamespaceBinding:
    values: dict[str, object] = {
        "binding_id": "portfolio-broker-binding-2",
        "portfolio_source_content_hash": "c" * 64,
        "issued_at": NOW + timedelta(minutes=1),
        "recorded_at": NOW + timedelta(minutes=1),
        "supersedes_binding_hash": previous.content_hash,
    }
    values.update(changes)
    return _binding(**values)


def _repository(
    clock: FixedClock | None = None,
) -> DjangoBrokerPortfolioAccountBindingRepository:
    return DjangoBrokerPortfolioAccountBindingRepository(
        clock=clock or FixedClock(NOW + timedelta(minutes=10))
    )


def _accepts_protocol(
    repository: BrokerPortfolioAccountBindingRepository,
) -> BrokerPortfolioAccountBindingRepository:
    return repository


@pytest.mark.django_db
def test_append_round_trip_protocol_and_exact_pit() -> None:
    repository = _repository()
    assert _accepts_protocol(repository) is repository
    binding = _binding()
    with repository.atomic():
        persisted = repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)

    assert persisted == binding
    assert BrokerPortfolioAccountBindingModel._default_manager.count() == 1
    assert (
        decode_broker_portfolio_account_binding(encode_broker_portfolio_account_binding(binding))
        == binding
    )
    assert (
        repository.get_binding_winner(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            as_of=NOW,
        )
        == binding
    )
    assert (
        repository.get_exact_by_hash(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            expected_content_hash=binding.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )


@pytest.mark.django_db
def test_full_chain_current_head_and_expired_successor_no_fallback() -> None:
    repository = _repository()
    root = _binding()
    successor = _successor(root, valid_until=NOW + timedelta(minutes=2))
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
            broker_account_namespace="qmt-live", broker_account_id=42, as_of=NOW
        )
        == root
    )
    assert (
        repository.get_current_head(
            broker_account_namespace="qmt-live",
            broker_account_id=42,
            as_of=successor.valid_until,
        )
        is None
    )


@pytest.mark.django_db
def test_private_uow_and_foreign_token_are_rejected() -> None:
    repository = _repository()
    binding = _binding()
    with pytest.raises(BrokerPortfolioAccountBindingConflict, match="private unit"):
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)
    token = object()
    with (
        _activate_broker_account_identity_uow(token),
        pytest.raises(BrokerPortfolioAccountBindingConflict, match="private unit"),
    ):
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)


@pytest.mark.django_db
def test_identity_root_and_predecessor_claims_are_first_winner_only() -> None:
    repository = _repository()
    root = _binding()
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)

    identity_conflict = _binding(portfolio_source_content_hash="d" * 64)
    with (
        repository.atomic(),
        pytest.raises(BrokerPortfolioAccountBindingConflict, match="first winner"),
    ):
        repository.append(identity_conflict, expected_predecessor_hash=None, recorded_at=NOW)
    root_conflict = _binding(binding_id="other-root", portfolio_source_content_hash="e" * 64)
    with (
        repository.atomic(),
        pytest.raises(BrokerPortfolioAccountBindingConflict, match="claim"),
    ):
        repository.append(root_conflict, expected_predecessor_hash=None, recorded_at=NOW)

    successor = _successor(root)
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )
    fork = _successor(root, binding_id="fork", portfolio_source_content_hash="f" * 64)
    with (
        repository.atomic(),
        pytest.raises(BrokerPortfolioAccountBindingConflict, match="claim"),
    ):
        repository.append(
            fork,
            expected_predecessor_hash=root.content_hash,
            recorded_at=fork.recorded_at,
        )


@pytest.mark.django_db
def test_direct_mutation_delete_bulk_raw_and_unclaimed_create_are_blocked() -> None:
    repository = _repository()
    binding = _binding()
    with repository.atomic():
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPortfolioAccountBindingModel._default_manager.get()

    row.portfolio_account_id = "tampered"
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="cannot be updated"):
        BrokerPortfolioAccountBindingModel._default_manager.update(portfolio_account_id="tampered")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        BrokerPortfolioAccountBindingModel._default_manager.all().delete()
    values = _model_values(binding, recorded_at=NOW)
    with pytest.raises(ValidationError, match="exact insert claim"):
        BrokerPortfolioAccountBindingModel._default_manager.create(**values)
    with pytest.raises(ValidationError, match="exact repository appends"):
        BrokerPortfolioAccountBindingModel._default_manager.bulk_create(
            [BrokerPortfolioAccountBindingModel(**values)]
        )
    with pytest.raises(ValidationError, match="append-only"):
        BrokerPortfolioAccountBindingModel(**values).save_base(raw=True)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("actor_id", "substituted-actor"),
        ("broker_source_content_hash", "9" * 64),
        ("portfolio_source_content_hash", "8" * 64),
        ("portfolio_account_id", "substituted-account"),
        ("persisted_at", NOW + timedelta(seconds=1)),
    ],
)
def test_header_source_actor_and_persisted_clock_tamper_fail_closed(
    column: str, replacement: object
) -> None:
    repository = _repository()
    binding = _binding()
    with repository.atomic():
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPortfolioAccountBindingModel._default_manager.get()
    if column == "persisted_at":
        with pytest.raises(IntegrityError):
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE broker_execution_portfolio_account_binding SET {column} = %s WHERE id = %s",
                    [replacement, row.pk],
                )
        return
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE broker_execution_portfolio_account_binding SET {column} = %s WHERE id = %s",
            [replacement, row.pk],
        )
    with pytest.raises(BrokerPortfolioAccountBindingCorruption):
        repository.get_binding_winner(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            as_of=NOW,
        )


@pytest.mark.django_db
def test_double_selector_tamper_cannot_hide_binding() -> None:
    repository = _repository()
    binding = _binding()
    with repository.atomic():
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPortfolioAccountBindingModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_portfolio_account_binding "
            "SET broker_account_namespace = %s, broker_account_id = %s, "
            "binding_id = %s, content_hash = %s WHERE id = %s",
            ["hidden", 99, "hidden-id", "9" * 64, row.pk],
        )

    with pytest.raises(BrokerPortfolioAccountBindingCorruption, match="headers"):
        repository.get_current_head(
            broker_account_namespace="qmt-live", broker_account_id=42, as_of=NOW
        )
    with pytest.raises(BrokerPortfolioAccountBindingCorruption, match="headers"):
        repository.get_exact_by_hash(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            expected_content_hash=binding.content_hash,
            as_of=NOW,
        )


def test_closed_world_rejects_orphan_fork_and_cross_account_link() -> None:
    root = _binding()
    orphan = _successor(root, supersedes_binding_hash="9" * 64)
    with pytest.raises(BrokerPortfolioAccountBindingCorruption, match="missing"):
        _validate_closed_world((orphan,))
    first = _successor(root)
    second = _successor(root, binding_id="fork", portfolio_source_content_hash="8" * 64)
    with pytest.raises(BrokerPortfolioAccountBindingCorruption, match="multiple"):
        _validate_closed_world((root, first, second))
    cross = _successor(
        root,
        binding_id="cross-account",
        broker_account_namespace="other-broker",
        broker_account_id=43,
    )
    with pytest.raises(BrokerPortfolioAccountBindingCorruption, match="link"):
        _validate_closed_world((root, cross))


@pytest.mark.django_db
def test_noncanonical_payload_and_future_cutoff_fail_closed() -> None:
    repository = _repository(FixedClock(NOW))
    binding = _binding()
    with repository.atomic():
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPortfolioAccountBindingModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_portfolio_account_binding "
            "SET canonical_payload = %s WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(BrokerPortfolioAccountBindingCorruption, match="canonical"):
        repository.get_binding_winner(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            as_of=NOW,
        )
    with pytest.raises(BrokerPortfolioAccountBindingUnavailable, match="future"):
        repository.get_current_head(
            broker_account_namespace="qmt-live",
            broker_account_id=42,
            as_of=NOW + timedelta(microseconds=1),
        )


def test_codec_strict_and_0011_is_schema_only_zero_seed() -> None:
    payload = encode_broker_portfolio_account_binding(_binding())
    with pytest.raises(BrokerPortfolioAccountBindingCodecError, match="shape"):
        decode_broker_portfolio_account_binding({**payload, "unknown": True})
    migration = importlib.import_module(
        "apps.broker_execution.migrations.0011_portfolio_broker_account_binding"
    ).Migration
    assert migration.dependencies == [("broker_execution", "0010_broker_account_identity_snapshot")]
    assert migration.operations
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)
