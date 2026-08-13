"""Django 5.2 component tests for raw account observation ledger."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.state import ModelState, ProjectState

from apps.simulated_trading.application.simulated_account_raw_observation import (
    PersistedSimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_codec import (
    SimulatedAccountRawObservationCodecError,
    decode_simulated_account_raw_observation_record,
    encode_simulated_account_raw_observation_record,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_models import (
    SimulatedAccountRawObservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_repository import (
    DjangoSimulatedAccountRawObservationConflict,
    DjangoSimulatedAccountRawObservationCorruption,
    DjangoSimulatedAccountRawObservationRepository,
)

pytestmark = pytest.mark.django_db(transaction=True)
NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW + timedelta(days=120)


def _record(**changes: object) -> PersistedSimulatedAccountRawObservation:
    values: dict[str, object] = {
        "observation_id": "row-7",
        "observation_version": "mutation-1",
        "row_pk": 7,
        "row_user_id": 19,
        "raw_account_type": "real",
        "is_active": True,
        "row_created_at": NOW - timedelta(days=2),
        "row_updated_at": NOW - timedelta(hours=2),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": NOW - timedelta(hours=1),
        "valid_until": NOW + timedelta(days=60),
    }
    recorded_at = changes.pop("recorded_at", NOW)
    values.update(changes)
    return PersistedSimulatedAccountRawObservation(
        SimulatedAccountRawObservation(**values),  # type: ignore[arg-type]
        recorded_at,  # type: ignore[arg-type]
    )


def _append(
    repository: DjangoSimulatedAccountRawObservationRepository,
    record: PersistedSimulatedAccountRawObservation,
) -> None:
    with repository.atomic():
        assert (
            repository.append(
                record,
                expected_predecessor_hash=record.observation.supersedes_content_hash,
                recorded_at=record.recorded_at,
            )
            == record
        )


def test_codec_utc_round_trip_and_exact_pit_append() -> None:
    offset = timezone(timedelta(hours=8))
    record = _record(
        row_created_at=(NOW - timedelta(days=2)).astimezone(offset),
        row_updated_at=(NOW - timedelta(hours=2)).astimezone(offset),
        observed_at=(NOW - timedelta(hours=1)).astimezone(offset),
        valid_until=(NOW + timedelta(days=60)).astimezone(offset),
    )
    payload = encode_simulated_account_raw_observation_record(record)
    assert decode_simulated_account_raw_observation_record(payload) == record
    assert str(payload["recorded_at"]).endswith("Z")
    with pytest.raises(SimulatedAccountRawObservationCodecError):
        decode_simulated_account_raw_observation_record({**payload, "extra": True})

    repository = DjangoSimulatedAccountRawObservationRepository(clock=_Clock())
    assert repository.database_alias == "default"
    _append(repository, record)
    assert (
        repository.get_exact_by_hash(
            observation_id=record.observation.observation_id,
            observation_version=record.observation.observation_version,
            expected_content_hash=record.observation.content_hash,
            as_of=NOW,
        )
        == record
    )
    assert repository.get_physical_row_head(row_pk=7, as_of=NOW) == record


def test_successor_cas_and_final_tombstone_or_expiry_never_falls_back() -> None:
    repository = DjangoSimulatedAccountRawObservationRepository(clock=_Clock())
    root = _record(valid_until=NOW + timedelta(days=90))
    _append(repository, root)
    successor = _record(
        observation_version="mutation-2",
        row_updated_at=NOW + timedelta(minutes=1),
        observed_at=NOW + timedelta(minutes=2),
        recorded_at=NOW + timedelta(minutes=3),
        is_active=False,
        is_present=False,
        is_tombstone=True,
        supersedes_content_hash=root.observation.content_hash,
    )
    _append(repository, successor)
    assert (
        repository.get_current_head(
            observation_id="row-7",
            row_pk=7,
            as_of=NOW + timedelta(minutes=4),
        )
        == successor
    )
    assert (
        repository.get_physical_row_head(
            row_pk=7,
            as_of=NOW + timedelta(minutes=4),
        )
        == successor
    )
    assert (
        repository.get_current_head(
            observation_id="row-7",
            row_pk=7,
            as_of=successor.observation.valid_until + timedelta(seconds=1),
        )
        == successor
    )


def test_private_uow_mutation_guards_and_wrong_predecessor() -> None:
    repository = DjangoSimulatedAccountRawObservationRepository(clock=_Clock())
    record = _record()
    with pytest.raises(DjangoSimulatedAccountRawObservationConflict):
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=record.recorded_at,
        )
    _append(repository, record)
    model = SimulatedAccountRawObservationModel._default_manager.get()
    with pytest.raises(ValidationError):
        model.delete()
    with pytest.raises(ValidationError):
        SimulatedAccountRawObservationModel._default_manager.update(status="active")


def test_closed_world_tamper_blocks_unrelated_selector() -> None:
    repository = DjangoSimulatedAccountRawObservationRepository(clock=_Clock())
    _append(repository, _record())
    model = SimulatedAccountRawObservationModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE simulated_account_raw_observation_ledger " "SET row_seal = %s WHERE id = %s",
            ["b" * 64, model.pk],
        )
    with pytest.raises(DjangoSimulatedAccountRawObservationCorruption):
        repository.get_winner(
            observation_id="unrelated-row",
            observation_version="mutation-x",
            as_of=NOW,
        )


def test_0022_migration_is_zero_seed_and_matches_live_model() -> None:
    path = Path(
        "apps/simulated_trading/migrations/" "0022_simulated_account_raw_observation_ledger.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "CreateModel" in text
    assert "RunPython" not in text
    assert "RunSQL" not in text
    module = importlib.import_module(
        "apps.simulated_trading.migrations." "0022_simulated_account_raw_observation_ledger"
    )
    operation = module.Migration.operations[0]
    state = ProjectState()
    operation.state_forwards("simulated_trading", state)
    migrated = state.models[("simulated_trading", "simulatedaccountrawobservationmodel")]
    live = ModelState.from_model(SimulatedAccountRawObservationModel)
    assert set(migrated.fields) == set(live.fields)
    for field_name in migrated.fields:
        assert (
            migrated.fields[field_name].deconstruct()[1:]
            == live.fields[field_name].deconstruct()[1:]
        )
    assert migrated.options["db_table"] == live.options["db_table"]
    assert [value.deconstruct() for value in migrated.options["indexes"]] == [
        value.deconstruct() for value in live.options["indexes"]
    ]
    assert [value.deconstruct() for value in migrated.options["constraints"]] == [
        value.deconstruct() for value in live.options["constraints"]
    ]
