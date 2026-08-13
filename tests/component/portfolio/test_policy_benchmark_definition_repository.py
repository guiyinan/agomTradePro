"""Component coverage for policy-benchmark definition persistence."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models
from django.db.migrations import RunPython, RunSQL
from django.db.migrations.state import ProjectState

from apps.portfolio.domain.policy_benchmark_definition import (
    PolicyBenchmarkConstituentDefinition,
    PolicyBenchmarkMethodologyRef,
    PortfolioPolicyBenchmarkDefinition,
)
from apps.portfolio.infrastructure.policy_benchmark_definition_codec import (
    PolicyBenchmarkDefinitionCodecError,
    decode_policy_benchmark_definition,
    encode_policy_benchmark_definition,
)
from apps.portfolio.infrastructure.policy_benchmark_definition_models import (
    PortfolioPolicyBenchmarkDefinitionModel,
)
from apps.portfolio.infrastructure.policy_benchmark_definition_repository import (
    DjangoPolicyBenchmarkDefinitionRepository,
    PolicyBenchmarkDefinitionConflict,
    PolicyBenchmarkDefinitionCorruption,
    PolicyBenchmarkDefinitionUnavailable,
    _model_values,
)

NOW = datetime(2026, 8, 13, 10, tzinfo=UTC)
VALID_UNTIL = NOW + timedelta(days=30)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _ref(kind: str) -> PolicyBenchmarkMethodologyRef:
    return PolicyBenchmarkMethodologyRef(
        owner="portfolio",
        artifact_type=kind,
        artifact_id=f"{kind}-cn-v1",
        artifact_version="v1",
        content_hash="a" * 64,
        recorded_at=NOW - timedelta(hours=1),
        valid_until=VALID_UNTIL,
    )


def _definition(**changes: object) -> PortfolioPolicyBenchmarkDefinition:
    values: dict[str, object] = {
        "definition_id": "balanced-policy-benchmark",
        "definition_version": "v1",
        "base_currency": "CNY",
        "constituents": (
            PolicyBenchmarkConstituentDefinition("CSI300", "000300.SH", "CNY", Decimal("0.6"), 0),
            PolicyBenchmarkConstituentDefinition(
                "CGB_TOTAL_RETURN", "CBA00101.CS", "CNY", Decimal("0.4"), 1
            ),
        ),
        "trading_calendar_ref": _ref("trading_calendar_definition"),
        "price_fixing_ref": _ref("price_fixing_methodology"),
        "fx_fixing_ref": _ref("fx_fixing_methodology"),
        "corporate_action_ref": _ref("corporate_action_methodology"),
        "cost_tax_ref": _ref("cost_tax_methodology"),
        "valuation_timezone": "Asia/Shanghai",
        "valuation_cutoff": "15:00:00",
        "evaluation_window_days": 252,
        "max_price_age_seconds": 86400,
        "max_fx_age_seconds": 86400,
        "missing_price_policy": "fail_closed",
        "missing_fx_policy": "fail_closed",
        "recorded_at": NOW,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkDefinition(**values)  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
def test_append_codec_idempotency_and_exact_pit_roundtrip() -> None:
    clock = FixedClock(NOW)
    repository = DjangoPolicyBenchmarkDefinitionRepository(clock=clock)
    definition = _definition()
    with repository.atomic():
        assert repository.append(definition, recorded_at=NOW) == definition
        assert repository.append(definition, recorded_at=NOW) == definition

    assert PortfolioPolicyBenchmarkDefinitionModel._default_manager.count() == 1
    assert (
        decode_policy_benchmark_definition(encode_policy_benchmark_definition(definition))
        == definition
    )
    assert (
        repository.get_exact(
            definition_id=definition.definition_id,
            definition_version=definition.definition_version,
            expected_content_hash=definition.content_hash,
            as_of=NOW,
        )
        == definition
    )
    assert (
        repository.get_exact(
            definition_id=definition.definition_id,
            definition_version=definition.definition_version,
            expected_content_hash=definition.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )
    clock.value = VALID_UNTIL
    assert (
        repository.get_exact(
            definition_id=definition.definition_id,
            definition_version=definition.definition_version,
            expected_content_hash=definition.content_hash,
            as_of=VALID_UNTIL,
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_private_uow_clock_and_future_cutoff_fail_closed() -> None:
    repository = DjangoPolicyBenchmarkDefinitionRepository(clock=FixedClock(NOW))
    definition = _definition()
    with pytest.raises(PolicyBenchmarkDefinitionConflict, match="private unit"):
        repository.append(definition, recorded_at=NOW)
    with repository.atomic(), pytest.raises(PolicyBenchmarkDefinitionConflict, match="recorded_at"):
        repository.append(definition, recorded_at=NOW + timedelta(microseconds=1))
    with pytest.raises(PolicyBenchmarkDefinitionUnavailable, match="future"):
        repository.get_exact(
            definition_id=definition.definition_id,
            definition_version=definition.definition_version,
            expected_content_hash=definition.content_hash,
            as_of=NOW + timedelta(microseconds=1),
        )


@pytest.mark.django_db(transaction=True)
def test_first_winner_rejects_same_identity_with_other_exact_decimal_content() -> None:
    repository = DjangoPolicyBenchmarkDefinitionRepository(clock=FixedClock(NOW))
    first = _definition()
    with repository.atomic():
        repository.append(first, recorded_at=NOW)
    conflicting = _definition(evaluation_window_days=126)
    with (
        repository.atomic(),
        pytest.raises(PolicyBenchmarkDefinitionConflict, match="another first winner"),
    ):
        repository.append(conflicting, recorded_at=NOW)
    assert PortfolioPolicyBenchmarkDefinitionModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_direct_save_update_delete_bulk_and_raw_paths_are_blocked() -> None:
    repository = DjangoPolicyBenchmarkDefinitionRepository(clock=FixedClock(NOW))
    definition = _definition()
    with repository.atomic():
        repository.append(definition, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkDefinitionModel._default_manager.get()
    values = _model_values(definition, NOW)

    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(raw=True)
    with pytest.raises(ValidationError, match="cannot be updated"):
        PortfolioPolicyBenchmarkDefinitionModel._default_manager.update(content_hash="0" * 64)
    with pytest.raises(ValidationError, match="cannot be bulk updated"):
        PortfolioPolicyBenchmarkDefinitionModel._default_manager.bulk_update(
            [row], ["content_hash"]
        )
    with pytest.raises(ValidationError, match="cannot be deleted"):
        PortfolioPolicyBenchmarkDefinitionModel._default_manager.all()._raw_delete("default")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="exact insert claim"):
        PortfolioPolicyBenchmarkDefinitionModel._default_manager.create(**values)
    with pytest.raises(ValidationError, match="exact repository appends"):
        PortfolioPolicyBenchmarkDefinitionModel._default_manager.bulk_create(
            [PortfolioPolicyBenchmarkDefinitionModel(**values)]
        )


@pytest.mark.django_db(transaction=True)
def test_closed_world_restore_detects_hidden_double_selector_tamper() -> None:
    repository = DjangoPolicyBenchmarkDefinitionRepository(clock=FixedClock(NOW))
    definition = _definition()
    with repository.atomic():
        repository.append(definition, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkDefinitionModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_definition SET "
            "definition_id = %s, definition_version = %s, identity_hash = %s, "
            "content_hash = %s WHERE id = %s",
            ["hidden", "hidden-v", "0" * 64, "1" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkDefinitionCorruption):
        repository.get_exact(
            definition_id=definition.definition_id,
            definition_version=definition.definition_version,
            expected_content_hash=definition.content_hash,
            as_of=NOW,
        )
    with repository.atomic(), pytest.raises(PolicyBenchmarkDefinitionCorruption):
        repository.append(definition, recorded_at=NOW)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("constituents_hash", "0" * 64, "headers"),
        ("methodology_refs_hash", "1" * 64, "headers"),
        ("ledger_header_hash", "2" * 64, "seal"),
    ],
)
def test_decimal_constituent_ref_and_ledger_header_seals_are_verified(
    column: str, value: object, message: str
) -> None:
    repository = DjangoPolicyBenchmarkDefinitionRepository(clock=FixedClock(NOW))
    definition = _definition()
    with repository.atomic():
        repository.append(definition, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkDefinitionModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE portfolio_policy_benchmark_definition SET {column} = %s WHERE id = %s",
            [value, row.pk],
        )
    with pytest.raises(PolicyBenchmarkDefinitionCorruption, match=message):
        repository.get_exact(
            definition_id=definition.definition_id,
            definition_version=definition.definition_version,
            expected_content_hash=definition.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_database_constraints_reject_authority_and_persisted_clock_tamper() -> None:
    repository = DjangoPolicyBenchmarkDefinitionRepository(clock=FixedClock(NOW))
    with repository.atomic():
        repository.append(_definition(), recorded_at=NOW)
    row = PortfolioPolicyBenchmarkDefinitionModel._default_manager.get()
    for column, value in (
        ("permission", "active"),
        ("persisted_at", NOW - timedelta(microseconds=1)),
    ):
        with connection.cursor() as cursor, pytest.raises(IntegrityError):
            cursor.execute(
                f"UPDATE portfolio_policy_benchmark_definition SET {column} = %s WHERE id = %s",
                [value, row.pk],
            )


def test_codec_rejects_noncanonical_decimal_refs_and_unknown_fields() -> None:
    payload = encode_policy_benchmark_definition(_definition())
    constituents = list(payload["constituents"])  # type: ignore[arg-type]
    constituents[0] = {**constituents[0], "weight": "0.60"}  # type: ignore[arg-type]
    with pytest.raises(PolicyBenchmarkDefinitionCodecError, match="non-canonical"):
        decode_policy_benchmark_definition({**payload, "constituents": constituents})
    refs = list(payload["methodology_refs"])  # type: ignore[arg-type]
    with pytest.raises(PolicyBenchmarkDefinitionCodecError):
        decode_policy_benchmark_definition({**payload, "methodology_refs": refs[:-1]})
    with pytest.raises(PolicyBenchmarkDefinitionCodecError, match="shape"):
        decode_policy_benchmark_definition({**payload, "status": "active"})


def test_migration_is_schema_only_zero_seed_and_matches_runtime_model() -> None:
    migration = importlib.import_module(
        "apps.portfolio.migrations.0020_policy_benchmark_definition"
    ).Migration
    assert migration.dependencies == [("portfolio", "0019_planning_policy_activation")]
    assert len(migration.operations) == 1
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)

    state = ProjectState()
    migration.operations[0].state_forwards("portfolio", state)
    rendered = state.apps.get_model("portfolio", "PortfolioPolicyBenchmarkDefinitionModel")

    def field_state(
        model_type: type[models.Model],
    ) -> list[tuple[str, str, tuple[object, ...], dict[str, object]]]:
        result: list[tuple[str, str, tuple[object, ...], dict[str, object]]] = []
        for field in model_type._meta.local_fields:
            _, path, args, kwargs = field.deconstruct()
            result.append((field.name, path, args, kwargs))
        return result

    assert field_state(rendered) == field_state(PortfolioPolicyBenchmarkDefinitionModel)
    assert rendered._meta.db_table == PortfolioPolicyBenchmarkDefinitionModel._meta.db_table
    assert [item.deconstruct() for item in rendered._meta.indexes] == [
        item.deconstruct() for item in PortfolioPolicyBenchmarkDefinitionModel._meta.indexes
    ]
    assert [item.deconstruct() for item in rendered._meta.constraints] == [
        item.deconstruct() for item in PortfolioPolicyBenchmarkDefinitionModel._meta.constraints
    ]
