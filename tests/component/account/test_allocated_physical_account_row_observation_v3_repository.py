"""Isolated component evidence for the allocated Physical-v3 ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, migrations

from apps.account.application.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3Recorder,
    PersistedAllocatedPhysicalAccountRowObservationV3,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_repository import (
    DjangoAllocatedPhysicalAccountRowObservationV3Corruption,
    DjangoAllocatedPhysicalAccountRowObservationV3Repository,
)
from tests.unit.account.test_allocated_physical_account_row_observation_v3 import _root


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return _at(30)


def _repository() -> DjangoAllocatedPhysicalAccountRowObservationV3Repository:
    return DjangoAllocatedPhysicalAccountRowObservationV3Repository(clock=_Clock())


def _record() -> PersistedAllocatedPhysicalAccountRowObservationV3:
    return PersistedAllocatedPhysicalAccountRowObservationV3(
        observation=_root(),
        recorded_by=AllocatedPhysicalAccountRowObservationV3Recorder(
            service_id="allocated-physical-v3-component"
        ),
    )


@pytest.mark.django_db(transaction=True)
def test_roundtrip_first_winner_exact_pit_and_full_anchor_head() -> None:
    repository = _repository()
    record = _record()
    observation = record.observation
    physical = observation.physical_observation

    with repository.atomic():
        assert (
            repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=observation.recorded_at,
            )
            == record
        )
        assert (
            repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=observation.recorded_at,
            )
            == record
        )

    assert (
        repository.get_winner(
            observation_id=observation.observation_id,
            observation_version=observation.observation_version,
            as_of=_at(8),
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            observation_id=observation.observation_id,
            observation_version=observation.observation_version,
            expected_content_hash=observation.content_hash,
            as_of=_at(8),
        )
        == record
    )
    assert (
        repository.get_current_head(
            allocation_content_hash=observation.allocation.content_hash,
            account_namespace=physical.account_namespace,
            account_id=physical.account_id,
            underlying_unified_account_namespace=(physical.underlying_unified_account_namespace),
            underlying_unified_account_id=physical.underlying_unified_account_id,
            physical_content_hash=physical.content_hash,
            as_of=_at(20),
        )
        == record
    )


@pytest.mark.django_db(transaction=True)
def test_private_uow_and_all_mutation_shortcuts_are_rejected() -> None:
    repository = _repository()
    record = _record()
    observation = record.observation
    with pytest.raises(Exception, match="private UOW|active private UOW"):
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=observation.recorded_at,
        )
    with pytest.raises(ValidationError):
        AllocatedPhysicalAccountRowObservationV3Model.objects.create()

    with repository.atomic():
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=observation.recorded_at,
        )
    row = AllocatedPhysicalAccountRowObservationV3Model._base_manager.get()
    with pytest.raises(ValidationError):
        row.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        AllocatedPhysicalAccountRowObservationV3Model._base_manager.update(status="tampered")
    with pytest.raises(ValidationError):
        AllocatedPhysicalAccountRowObservationV3Model._base_manager.all().delete()


@pytest.mark.django_db(transaction=True)
def test_closed_world_header_tamper_fails_before_selector_filtering() -> None:
    repository = _repository()
    record = _record()
    with repository.atomic():
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=record.observation.recorded_at,
        )
    table = AllocatedPhysicalAccountRowObservationV3Model._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "{table}" SET account_id = %s',  # noqa: S608
            ["hidden-account"],
        )
    with pytest.raises(
        DjangoAllocatedPhysicalAccountRowObservationV3Corruption,
        match="account_id",
    ):
        repository.get_winner(
            observation_id=record.observation.observation_id,
            observation_version=record.observation.observation_version,
            as_of=_at(8),
        )


def test_0046_is_schema_only_zero_seed_state() -> None:
    migration = import_module(
        "apps.account.migrations.0046_allocated_physical_account_row_observation_v3_ledger"
    ).Migration
    assert migration.dependencies == [("account", "0045_canonical_account_creation_ledger")]
    assert len(migration.operations) == 1
    operation = migration.operations[0]
    assert isinstance(operation, migrations.CreateModel)
    assert {name for name, _field in operation.fields} == {
        field.name for field in AllocatedPhysicalAccountRowObservationV3Model._meta.local_fields
    }
    assert {constraint.name for constraint in operation.options["constraints"]} == {
        constraint.name
        for constraint in AllocatedPhysicalAccountRowObservationV3Model._meta.constraints
    }
    assert {index.name for index in operation.options["indexes"]} == {
        index.name for index in AllocatedPhysicalAccountRowObservationV3Model._meta.indexes
    }
    assert not any(
        isinstance(operation, migrations.RunPython | migrations.RunSQL)
        for operation in migration.operations
    )
