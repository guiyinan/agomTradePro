from __future__ import annotations

import importlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.state import ModelState, ProjectState

from apps.simulated_trading.application.simulated_account_row_source import (
    PersistedSimulatedAccountRowSource,
    SimulatedAccountRowSourceActor,
)
from apps.simulated_trading.domain.simulated_account_row_source import (
    SimulatedAccountRowSource,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_codec import (
    SimulatedAccountRowSourceCodecError,
    decode_simulated_account_row_source_record,
    encode_simulated_account_row_source_record,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_models import (
    SimulatedAccountRowSourceModel,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_repository import (
    DjangoSimulatedAccountRowSourceCorruption,
    DjangoSimulatedAccountRowSourceRepository,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return _at(30)


def _record(**changes: object) -> PersistedSimulatedAccountRowSource:
    values: dict[str, object] = {
        "source_id": "row-7",
        "source_version": "v1",
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "row_user_id": None,
        "raw_account_type": "SIMULATED",
        "is_active": True,
        "row_created_at": _at(1),
        "row_updated_at": _at(2),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": _at(3),
        "recorded_at": _at(4),
        "source_valid_until": _at(20),
        "ttl_valid_until": _at(14),
        "valid_until": _at(14),
    }
    values.update(changes)
    return PersistedSimulatedAccountRowSource(
        source=SimulatedAccountRowSource(**values),  # type: ignore[arg-type]
        captured_by=SimulatedAccountRowSourceActor(actor_id="staff-1", user_id=1, role="recorder"),
    )


def test_codec_and_append_exact_pit_round_trip() -> None:
    record = _record()
    payload = encode_simulated_account_row_source_record(record)
    assert decode_simulated_account_row_source_record(payload) == record
    with pytest.raises(SimulatedAccountRowSourceCodecError):
        decode_simulated_account_row_source_record({**payload, "extra": True})

    repository = DjangoSimulatedAccountRowSourceRepository(clock=_Clock())
    with repository.atomic():
        assert (
            repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=record.source.recorded_at,
            )
            == record
        )
    assert (
        repository.get_exact_by_hash(
            source_id="row-7",
            source_version="v1",
            expected_content_hash=record.source.content_hash,
            as_of=_at(5),
        )
        == record
    )


def test_mutation_guards_and_closed_world_tamper() -> None:
    record = _record()
    repository = DjangoSimulatedAccountRowSourceRepository(clock=_Clock())
    with repository.atomic():
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=record.source.recorded_at,
        )
    model = SimulatedAccountRowSourceModel._default_manager.get()
    with pytest.raises(ValidationError):
        model.delete()
    with pytest.raises(ValidationError):
        SimulatedAccountRowSourceModel._default_manager.update(status="active")

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE simulated_account_row_source_ledger SET row_fact_hash = %s WHERE id = %s",
            ["b" * 64, model.pk],
        )
    with pytest.raises(DjangoSimulatedAccountRowSourceCorruption):
        repository.get_winner(source_id="row-7", source_version="v1", as_of=_at(5))


def test_0021_migration_is_zero_seed_and_matches_live_model() -> None:
    path = Path("apps/simulated_trading/migrations/0021_simulated_account_row_source_ledger.py")
    text = path.read_text(encoding="utf-8")
    assert "CreateModel" in text
    assert "RunPython" not in text
    assert "RunSQL" not in text
    module = importlib.import_module(
        "apps.simulated_trading.migrations.0021_simulated_account_row_source_ledger"
    )
    operation = module.Migration.operations[0]
    state = ProjectState()
    operation.state_forwards("simulated_trading", state)
    migrated = state.models[("simulated_trading", "simulatedaccountrowsourcemodel")]
    live = ModelState.from_model(SimulatedAccountRowSourceModel)
    assert set(migrated.fields) == set(live.fields)
    for field_name in migrated.fields:
        assert migrated.fields[field_name].deconstruct()[1:] == live.fields[
            field_name
        ].deconstruct()[1:]
    assert migrated.options["db_table"] == live.options["db_table"]
    assert [value.deconstruct() for value in migrated.options["indexes"]] == [
        value.deconstruct() for value in live.options["indexes"]
    ]
    assert [value.deconstruct() for value in migrated.options["constraints"]] == [
        value.deconstruct() for value in live.options["constraints"]
    ]
