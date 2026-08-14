"""Django 5.2 component tests for the independent v2 row-source ledger."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.state import ModelState, ProjectState

from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    PersistedSimulatedAccountRowSourceV2,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_codec import (
    SimulatedAccountRowSourceV2CodecError,
    decode_simulated_account_row_source_v2_record,
    encode_simulated_account_row_source_v2_record,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_models import (
    SimulatedAccountRowSourceV2Model,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Conflict,
    DjangoSimulatedAccountRowSourceV2Corruption,
    DjangoSimulatedAccountRowSourceV2Repository,
)

pytestmark = pytest.mark.django_db(transaction=True)
NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW + timedelta(days=120)


def _source(**changes: object) -> SimulatedAccountRowSourceV2:
    raw_values: dict[str, object] = {
        "observation_id": changes.get("source_id", "row-7"),
        "observation_version": changes.get("source_version", "mutation-1"),
        "row_pk": 7,
        "row_user_id": 19,
        "raw_account_type": "real",
        "is_active": changes.get("is_active", True),
        "row_created_at": NOW - timedelta(days=2),
        "row_updated_at": changes.get("row_updated_at", NOW - timedelta(hours=2)),
        "is_present": changes.get("is_present", True),
        "is_tombstone": changes.get("is_tombstone", False),
        "observed_at": changes.get("observed_at", NOW - timedelta(hours=1)),
        "valid_until": changes.get("source_valid_until", NOW + timedelta(days=60)),
        "supersedes_content_hash": changes.get("raw_observation_supersedes_content_hash"),
    }
    raw = SimulatedAccountRawObservation(**raw_values)  # type: ignore[arg-type]
    values: dict[str, object] = {
        "source_id": raw.observation_id,
        "source_version": raw.observation_version,
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": raw.row_pk,
        "row_user_id": raw.row_user_id,
        "raw_account_type": raw.raw_account_type,
        "is_active": raw.is_active,
        "row_created_at": raw.row_created_at,
        "row_updated_at": raw.row_updated_at,
        "is_present": raw.is_present,
        "is_tombstone": raw.is_tombstone,
        "observed_at": raw.observed_at,
        "recorded_at": changes.get("recorded_at", NOW),
        "source_valid_until": raw.valid_until,
        "ttl_valid_until": changes.get("ttl_valid_until", NOW + timedelta(days=30)),
        "valid_until": changes.get("valid_until", NOW + timedelta(days=30)),
        "raw_observation_id": raw.observation_id,
        "raw_observation_version": raw.observation_version,
        "raw_observation_identity_hash": raw.identity_hash,
        "raw_observation_content_hash": raw.content_hash,
        "raw_observation_observed_at": raw.observed_at,
        "raw_observation_valid_until": raw.valid_until,
        "raw_observation_supersedes_content_hash": raw.supersedes_content_hash,
        "supersedes_content_hash": changes.get("supersedes_content_hash"),
    }
    return SimulatedAccountRowSourceV2(**values)  # type: ignore[arg-type]


def _append(
    repository: DjangoSimulatedAccountRowSourceV2Repository,
    source: SimulatedAccountRowSourceV2,
) -> PersistedSimulatedAccountRowSourceV2:
    record = PersistedSimulatedAccountRowSourceV2(source=source)
    with repository.atomic():
        return repository.append(
            record,
            expected_predecessor_hash=source.supersedes_content_hash,
            recorded_at=source.recorded_at,
        )


def test_codec_append_exact_and_current_round_trip() -> None:
    source = _source()
    record = PersistedSimulatedAccountRowSourceV2(source=source)
    payload = encode_simulated_account_row_source_v2_record(record)
    assert decode_simulated_account_row_source_v2_record(payload) == record
    with pytest.raises(SimulatedAccountRowSourceV2CodecError):
        decode_simulated_account_row_source_v2_record({**payload, "extra": True})
    repository = DjangoSimulatedAccountRowSourceV2Repository(clock=_Clock())
    assert _append(repository, source) == record
    assert (
        repository.get_exact_by_hash(
            source_id=source.source_id,
            source_version=source.source_version,
            expected_content_hash=source.content_hash,
            as_of=NOW,
        )
        == record
    )
    assert (
        repository.get_current_head(
            source_id=source.source_id,
            account_namespace=source.account_namespace,
            account_id=source.account_id,
            underlying_unified_account_namespace=source.underlying_unified_account_namespace,
            underlying_unified_account_id=source.underlying_unified_account_id,
            as_of=NOW,
        )
        == record
    )


def test_successor_cas_and_final_head() -> None:
    repository = DjangoSimulatedAccountRowSourceV2Repository(clock=_Clock())
    root = _source()
    _append(repository, root)
    successor = _source(
        source_version="mutation-2",
        row_updated_at=NOW + timedelta(minutes=1),
        observed_at=NOW + timedelta(minutes=2),
        recorded_at=NOW + timedelta(minutes=3),
        source_valid_until=NOW + timedelta(days=60),
        ttl_valid_until=NOW + timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        raw_observation_supersedes_content_hash=root.raw_observation_content_hash,
        supersedes_content_hash=root.content_hash,
    )
    assert _append(repository, successor).source == successor
    with repository.atomic(), pytest.raises(DjangoSimulatedAccountRowSourceV2Conflict):
        repository.append(
            PersistedSimulatedAccountRowSourceV2(source=successor),
            expected_predecessor_hash="a" * 64,
            recorded_at=successor.recorded_at,
        )


def test_closed_world_tamper_and_mutation_guards() -> None:
    repository = DjangoSimulatedAccountRowSourceV2Repository(clock=_Clock())
    _append(repository, _source())
    model = SimulatedAccountRowSourceV2Model._default_manager.get()
    with pytest.raises(ValidationError):
        model.save()
    with pytest.raises(ValidationError):
        model.save_base(raw=True)
    with pytest.raises(ValidationError):
        model.delete()
    with pytest.raises(ValidationError):
        SimulatedAccountRowSourceV2Model._default_manager.update(status="active")
    with pytest.raises(ValidationError):
        SimulatedAccountRowSourceV2Model._default_manager.all().delete()
    with pytest.raises(ValidationError):
        SimulatedAccountRowSourceV2Model._default_manager.bulk_create([])
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE simulated_account_row_source_v2_ledger SET raw_binding_seal = %s WHERE id = %s",
            ["b" * 64, model.pk],
        )
    with pytest.raises(DjangoSimulatedAccountRowSourceV2Corruption):
        repository.get_winner(source_id="unrelated", source_version="x", as_of=NOW)


def test_append_requires_private_uow() -> None:
    source = _source()
    repository = DjangoSimulatedAccountRowSourceV2Repository(clock=_Clock())
    with pytest.raises(DjangoSimulatedAccountRowSourceV2Conflict):
        repository.append(
            PersistedSimulatedAccountRowSourceV2(source=source),
            expected_predecessor_hash=None,
            recorded_at=source.recorded_at,
        )


def test_0023_migration_is_zero_seed_and_matches_live_model() -> None:
    path = Path("apps/simulated_trading/migrations/0023_simulated_account_row_source_v2_ledger.py")
    text = path.read_text(encoding="utf-8")
    assert "CreateModel" in text
    assert "RunPython" not in text
    assert "RunSQL" not in text
    module = importlib.import_module(
        "apps.simulated_trading.migrations.0023_simulated_account_row_source_v2_ledger"
    )
    operation = module.Migration.operations[0]
    state = ProjectState()
    operation.state_forwards("simulated_trading", state)
    migrated = state.models[("simulated_trading", "simulatedaccountrowsourcev2model")]
    live = ModelState.from_model(SimulatedAccountRowSourceV2Model)
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
