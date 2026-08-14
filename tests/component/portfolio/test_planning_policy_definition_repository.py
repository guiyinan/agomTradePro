"""Component coverage for Portfolio planning-policy definition persistence."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models
from django.db.migrations import RunPython, RunSQL
from django.db.migrations.state import ProjectState

from apps.portfolio.domain.planning_policy_definition import PlanningPolicyDefinition
from apps.portfolio.infrastructure.planning_policy_definition_codec import (
    PlanningPolicyDefinitionCodecError,
    decode_planning_policy_definition,
    encode_planning_policy_definition,
)
from apps.portfolio.infrastructure.planning_policy_definition_models import (
    PortfolioPlanningPolicyDefinitionModel,
)
from apps.portfolio.infrastructure.planning_policy_definition_repository import (
    DjangoPlanningPolicyDefinitionRepository,
    PlanningPolicyDefinitionConflict,
    PlanningPolicyDefinitionCorruption,
    PlanningPolicyDefinitionUnavailable,
    _model_values,
)

NOW = datetime(2026, 8, 13, 10, tzinfo=UTC)
VALID_UNTIL = NOW + timedelta(days=365)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _definition(**changes: object) -> PlanningPolicyDefinition:
    values: dict[str, object] = {
        "policy_id": "planning-policy-1",
        "policy_version": "policy-v1",
        "buy_lot_size": 100,
        "fee_rate": Decimal("0.0003"),
        "slippage_rate": Decimal("0.001"),
        "min_rebalance_value": Decimal("1000"),
        "max_asset_weight": Decimal("0.2"),
        "max_volume_participation": Decimal("0.1"),
        "recorded_at": NOW,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return PlanningPolicyDefinition(**values)  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
def test_append_codec_idempotency_and_exact_pit_boundaries() -> None:
    clock = FixedClock(NOW)
    repository = DjangoPlanningPolicyDefinitionRepository(clock=clock)
    definition = _definition()

    with repository.atomic():
        assert repository.append(definition, recorded_at=NOW) == definition
        assert repository.append(definition, recorded_at=NOW) == definition

    assert PortfolioPlanningPolicyDefinitionModel._default_manager.count() == 1
    assert (
        decode_planning_policy_definition(encode_planning_policy_definition(definition))
        == definition
    )
    assert (
        repository.get_exact(
            policy_id=definition.policy_id,
            policy_version=definition.policy_version,
            expected_content_hash=definition.content_hash,
            as_of=NOW,
        )
        == definition
    )
    assert (
        repository.get_exact(
            policy_id=definition.policy_id,
            policy_version=definition.policy_version,
            expected_content_hash=definition.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )
    clock.value = VALID_UNTIL
    assert (
        repository.get_exact(
            policy_id=definition.policy_id,
            policy_version=definition.policy_version,
            expected_content_hash=definition.content_hash,
            as_of=VALID_UNTIL,
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_private_uow_server_clock_and_future_cutoff_fail_closed() -> None:
    repository = DjangoPlanningPolicyDefinitionRepository(clock=FixedClock(NOW))
    definition = _definition()

    with pytest.raises(PlanningPolicyDefinitionConflict, match="private unit"):
        repository.append(definition, recorded_at=NOW)
    with (
        repository.atomic(),
        pytest.raises(PlanningPolicyDefinitionConflict, match="recorded_at"),
    ):
        repository.append(definition, recorded_at=NOW + timedelta(seconds=1))
    with pytest.raises(PlanningPolicyDefinitionUnavailable, match="future"):
        repository.get_exact(
            policy_id=definition.policy_id,
            policy_version=definition.policy_version,
            expected_content_hash=definition.content_hash,
            as_of=NOW + timedelta(microseconds=1),
        )


@pytest.mark.django_db(transaction=True)
def test_direct_save_update_delete_bulk_raw_and_unclaimed_create_are_blocked() -> None:
    repository = DjangoPlanningPolicyDefinitionRepository(clock=FixedClock(NOW))
    definition = _definition()
    with repository.atomic():
        repository.append(definition, recorded_at=NOW)
    row = PortfolioPlanningPolicyDefinitionModel._default_manager.get()
    values = _model_values(definition, recorded_at=NOW)

    row.policy_version = "tampered"
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(raw=True)
    with pytest.raises(ValidationError, match="cannot be updated"):
        PortfolioPlanningPolicyDefinitionModel._default_manager.update(content_hash="0" * 64)
    with pytest.raises(ValidationError, match="cannot be bulk updated"):
        PortfolioPlanningPolicyDefinitionModel._default_manager.bulk_update([row], ["content_hash"])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        PortfolioPlanningPolicyDefinitionModel._default_manager.all().delete()
    with pytest.raises(ValidationError, match="exact insert claim"):
        PortfolioPlanningPolicyDefinitionModel._default_manager.create(**values)
    with pytest.raises(ValidationError, match="exact repository appends"):
        PortfolioPlanningPolicyDefinitionModel._default_manager.bulk_create(
            [PortfolioPlanningPolicyDefinitionModel(**values)]
        )


@pytest.mark.django_db(transaction=True)
def test_identity_or_content_anchor_conflict_preserves_first_winner() -> None:
    repository = DjangoPlanningPolicyDefinitionRepository(clock=FixedClock(NOW))
    first = _definition()
    with repository.atomic():
        repository.append(first, recorded_at=NOW)

    conflicting = replace(first, fee_rate=Decimal("0.0004"), content_hash="")
    with (
        repository.atomic(),
        pytest.raises(PlanningPolicyDefinitionConflict, match="another first winner"),
    ):
        repository.append(conflicting, recorded_at=NOW)
    assert PortfolioPlanningPolicyDefinitionModel._default_manager.count() == 1


def _read(
    repository: DjangoPlanningPolicyDefinitionRepository, definition: PlanningPolicyDefinition
) -> object:
    return repository.get_exact(
        policy_id=definition.policy_id,
        policy_version=definition.policy_version,
        expected_content_hash=definition.content_hash,
        as_of=NOW,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("policy_version", "tampered", "headers"),
        ("identity_hash", "0" * 64, "headers"),
        ("ledger_header_hash", "1" * 64, "seal"),
    ],
)
def test_header_ledger_and_persisted_clock_tamper_are_detected(
    column: str, value: object, message: str
) -> None:
    repository = DjangoPlanningPolicyDefinitionRepository(clock=FixedClock(NOW))
    definition = _definition()
    with repository.atomic():
        repository.append(definition, recorded_at=NOW)
    row = PortfolioPlanningPolicyDefinitionModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE portfolio_planning_policy_definition SET {column} = %s WHERE id = %s",
            [value, row.pk],
        )
    with pytest.raises(PlanningPolicyDefinitionCorruption, match=message):
        _read(repository, definition)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("permission", "active"),
        ("persisted_at", NOW - timedelta(microseconds=1)),
    ],
)
def test_database_constraints_reject_fixed_authority_or_persisted_clock_tamper(
    column: str, value: object
) -> None:
    repository = DjangoPlanningPolicyDefinitionRepository(clock=FixedClock(NOW))
    definition = _definition()
    with repository.atomic():
        repository.append(definition, recorded_at=NOW)
    row = PortfolioPlanningPolicyDefinitionModel._default_manager.get()
    with connection.cursor() as cursor, pytest.raises(IntegrityError):
        cursor.execute(
            f"UPDATE portfolio_planning_policy_definition SET {column} = %s WHERE id = %s",
            [value, row.pk],
        )


@pytest.mark.django_db(transaction=True)
def test_canonical_payload_tamper_is_detected() -> None:
    repository = DjangoPlanningPolicyDefinitionRepository(clock=FixedClock(NOW))
    definition = _definition()
    with repository.atomic():
        repository.append(definition, recorded_at=NOW)
    row = PortfolioPlanningPolicyDefinitionModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_planning_policy_definition "
            "SET canonical_payload = %s WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(PlanningPolicyDefinitionCorruption, match="payload"):
        _read(repository, definition)


@pytest.mark.django_db(transaction=True)
def test_closed_world_scan_rejects_simultaneously_hidden_anchor_tamper() -> None:
    repository = DjangoPlanningPolicyDefinitionRepository(clock=FixedClock(NOW))
    definition = _definition()
    with repository.atomic():
        repository.append(definition, recorded_at=NOW)
    row = PortfolioPlanningPolicyDefinitionModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_planning_policy_definition SET "
            "policy_id = %s, policy_version = %s, identity_hash = %s, "
            "content_hash = %s WHERE id = %s",
            ["hidden-policy", "hidden-version", "0" * 64, "1" * 64, row.pk],
        )

    with pytest.raises(PlanningPolicyDefinitionCorruption):
        _read(repository, definition)
    with repository.atomic(), pytest.raises(PlanningPolicyDefinitionCorruption):
        repository.append(definition, recorded_at=NOW)
    assert PortfolioPlanningPolicyDefinitionModel._default_manager.count() == 1


def test_codec_is_strict_and_migration_is_schema_only_zero_seed() -> None:
    payload = encode_planning_policy_definition(_definition())
    with pytest.raises(PlanningPolicyDefinitionCodecError, match="shape"):
        decode_planning_policy_definition({**payload, "status": "active"})

    migration = importlib.import_module(
        "apps.portfolio.migrations.0018_planning_policy_definition"
    ).Migration
    assert migration.dependencies == [("portfolio", "0017_transition_plan_inactive_approvals")]
    assert migration.operations
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)


def test_migration_model_state_matches_runtime_model() -> None:
    migration = importlib.import_module(
        "apps.portfolio.migrations.0018_planning_policy_definition"
    ).Migration
    state = ProjectState()
    migration.operations[0].state_forwards("portfolio", state)
    rendered = state.apps.get_model("portfolio", "PortfolioPlanningPolicyDefinitionModel")

    def field_state(
        model_type: type[models.Model],
    ) -> list[tuple[str, str, tuple[object, ...], dict[str, object]]]:
        result: list[tuple[str, str, tuple[object, ...], dict[str, object]]] = []
        for field in model_type._meta.local_fields:
            _, path, args, kwargs = field.deconstruct()
            result.append((field.name, path, args, kwargs))
        return result

    assert field_state(rendered) == field_state(PortfolioPlanningPolicyDefinitionModel)
    assert rendered._meta.db_table == PortfolioPlanningPolicyDefinitionModel._meta.db_table
    assert [item.deconstruct() for item in rendered._meta.indexes] == [
        item.deconstruct() for item in PortfolioPlanningPolicyDefinitionModel._meta.indexes
    ]
    assert [item.deconstruct() for item in rendered._meta.constraints] == [
        item.deconstruct() for item in PortfolioPlanningPolicyDefinitionModel._meta.constraints
    ]
