"""Component coverage for the Portfolio-owned R5 outcome ledger."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, models, transaction

from apps.fixed_income.application.relative_value_persistence import (
    R5PersistedRelativeValueBundle,
)
from apps.fixed_income.application.relative_value_projection import (
    GetExactR5RelativeValueOwnerRecord,
    project_r5_relative_value_owner_record,
)
from apps.portfolio import r5_relative_value_outcome_composition as composition_module
from apps.portfolio.application.r5_relative_value_outcome import (
    GetExactR5PortfolioOutcomeCommand,
    PersistR5PortfolioOutcomeCommand,
    R5PortfolioOutcomePersistenceConflict,
    R5PortfolioOutcomePersistenceCorruption,
    R5PortfolioOutcomeSourceRecord,
)
from apps.portfolio.infrastructure.r5_relative_value_outcome_models import (
    PortfolioR5RelativeValueOutcomeModel,
)
from apps.portfolio.r5_relative_value_outcome_composition import (
    DjangoR5PortfolioOutcomeRuntime,
    build_django_r5_portfolio_outcome_runtime,
)
from tests.unit.portfolio.test_r5_relative_value_outcome_persistence import _source
from tests.unit.research.r5_relative_value_promotion_factories import (
    make_persisted_bundles,
)

pytestmark = pytest.mark.django_db


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class _FixedIncomeRepository:
    def __init__(self, bundle: R5PersistedRelativeValueBundle | None) -> None:
        self.bundle = bundle
        self.unit_of_work_key = "django:default"
        self.atomic_states: list[bool] = []

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R5PersistedRelativeValueBundle | None:
        self.atomic_states.append(transaction.get_connection().in_atomic_block)
        bundle = self.bundle
        if bundle is None:
            return None
        result = bundle.result
        if (
            result.result_id != result_id
            or result.result_version != result_version
            or result.record_hash != expected_record_hash
            or result.recorded_at > as_of
        ):
            return None
        return bundle


class _SourceProvider:
    def __init__(
        self,
        source: R5PortfolioOutcomeSourceRecord | None,
        *,
        key: str = "django:default",
    ) -> None:
        self.source = source
        self.unit_of_work_key = key
        self.atomic_states: list[bool] = []

    def get_exact(
        self,
        *,
        owner_record_id: str,
        owner_record_version: str,
        as_of: datetime,
    ) -> R5PortfolioOutcomeSourceRecord | None:
        self.atomic_states.append(transaction.get_connection().in_atomic_block)
        source = self.source
        if source is None:
            return None
        if (
            source.owner_record_id != owner_record_id
            or source.owner_record_version != owner_record_version
            or not source.outcome_available_at <= as_of < source.valid_until
        ):
            return None
        return source


@dataclass(frozen=True)
class _Fixture:
    runtime: DjangoR5PortfolioOutcomeRuntime
    source_provider: _SourceProvider
    fixed_income_repository: _FixedIncomeRepository
    clock: _Clock
    source: R5PortfolioOutcomeSourceRecord


def _runtime(monkeypatch: pytest.MonkeyPatch) -> _Fixture:
    bundle, _ = make_persisted_bundles(monkeypatch)
    fixed_income = project_r5_relative_value_owner_record(bundle)
    source = _source(fixed_income)
    source_provider = _SourceProvider(source)
    fixed_income_repository = _FixedIncomeRepository(bundle)
    clock = _Clock(source.outcome_available_at + timedelta(seconds=1))
    runtime = build_django_r5_portfolio_outcome_runtime(
        source_provider=source_provider,
        fixed_income_query=GetExactR5RelativeValueOwnerRecord(fixed_income_repository),
        clock=clock,
    )
    return _Fixture(
        runtime=runtime,
        source_provider=source_provider,
        fixed_income_repository=fixed_income_repository,
        clock=clock,
        source=source,
    )


def _command(source: R5PortfolioOutcomeSourceRecord) -> PersistR5PortfolioOutcomeCommand:
    return PersistR5PortfolioOutcomeCommand(
        owner_record_id=source.owner_record_id,
        owner_record_version=source.owner_record_version,
    )


def test_id_only_append_replays_one_server_clocked_exact_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _runtime(monkeypatch)

    first = fixture.runtime.persist.execute(_command(fixture.source))
    replay = fixture.runtime.persist.execute(_command(fixture.source))

    assert replay == first
    assert first.recorded_at == fixture.clock.value
    assert fixture.clock.calls == 2
    assert PortfolioR5RelativeValueOutcomeModel._default_manager.count() == 1
    assert all(fixture.source_provider.atomic_states)
    assert all(fixture.fixed_income_repository.atomic_states)
    exact = fixture.runtime.query.execute(
        GetExactR5PortfolioOutcomeCommand(
            outcome_id=first.outcome_id,
            outcome_version=first.outcome_version,
            expected_content_hash=first.content_hash,
            as_of=first.recorded_at,
        )
    )
    assert exact == first
    assert (
        fixture.runtime.query.execute(
            GetExactR5PortfolioOutcomeCommand(
                outcome_id=first.outcome_id,
                outcome_version=first.outcome_version,
                expected_content_hash=first.content_hash,
                as_of=first.recorded_at - timedelta(microseconds=1),
            )
        )
        is None
    )


def test_model_has_no_cross_app_relation_and_public_query_has_no_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _runtime(monkeypatch)
    repository = fixture.runtime.query._repository

    assert not any(
        isinstance(field, models.ForeignKey)
        for field in PortfolioR5RelativeValueOutcomeModel._meta.fields
    )
    assert not hasattr(repository, "append")
    assert not hasattr(repository, "persist")
    with pytest.raises(AttributeError):
        repository.append = object()


def test_direct_bulk_base_and_conflict_mutations_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _runtime(monkeypatch)
    outcome = fixture.runtime.persist.execute(_command(fixture.source))
    row = PortfolioR5RelativeValueOutcomeModel._default_manager.get(outcome_id=outcome.outcome_id)

    row.owner = "research"
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.save_base(force_update=True)
    with pytest.raises(ValidationError):
        PortfolioR5RelativeValueOutcomeModel._default_manager.filter(pk=row.pk).update(
            owner="research"
        )
    with pytest.raises(ValidationError):
        PortfolioR5RelativeValueOutcomeModel._base_manager.filter(pk=row.pk).delete()
    with pytest.raises(ValidationError):
        PortfolioR5RelativeValueOutcomeModel._default_manager.bulk_update([row], ["owner"])
    with pytest.raises(ValidationError):
        PortfolioR5RelativeValueOutcomeModel._default_manager.bulk_create([row])
    with pytest.raises(ValidationError):
        PortfolioR5RelativeValueOutcomeModel._default_manager.update_or_create(
            outcome_id=outcome.outcome_id,
            outcome_version=outcome.outcome_version,
            defaults={"observation_id": "changed"},
        )


def test_raw_header_and_payload_tampering_fail_strict_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _runtime(monkeypatch)
    outcome = fixture.runtime.persist.execute(_command(fixture.source))
    row = PortfolioR5RelativeValueOutcomeModel._default_manager.get(outcome_id=outcome.outcome_id)
    payload = dict(row.canonical_payload)
    payload["observation_id"] = "tampered-observation"
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_r5_relative_value_outcome "
            "SET canonical_payload = %s WHERE id = %s",
            [json.dumps(payload), row.pk],
        )

    with pytest.raises(R5PortfolioOutcomePersistenceCorruption):
        fixture.runtime.query.execute(
            GetExactR5PortfolioOutcomeCommand(
                outcome_id=outcome.outcome_id,
                outcome_version=outcome.outcome_version,
                expected_content_hash=outcome.content_hash,
                as_of=outcome.recorded_at,
            )
        )


def test_owner_substitution_is_detected_on_every_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _runtime(monkeypatch)
    outcome = fixture.runtime.persist.execute(_command(fixture.source))
    fixture.source_provider.source = R5PortfolioOutcomeSourceRecord.create(
        **{
            **fixture.source.factory_values,
            "target_gross_return": Decimal("0.09"),
        }
    )

    with pytest.raises(R5PortfolioOutcomePersistenceCorruption):
        fixture.runtime.query.execute(
            GetExactR5PortfolioOutcomeCommand(
                outcome_id=outcome.outcome_id,
                outcome_version=outcome.outcome_version,
                expected_content_hash=outcome.content_hash,
                as_of=outcome.recorded_at,
            )
        )


def test_missing_fixed_income_owner_and_invalid_server_clock_roll_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = _runtime(monkeypatch)
    missing.fixed_income_repository.bundle = None
    with pytest.raises(R5PortfolioOutcomePersistenceConflict):
        missing.runtime.persist.execute(_command(missing.source))
    assert PortfolioR5RelativeValueOutcomeModel._default_manager.count() == 0

    invalid = _runtime(monkeypatch)
    invalid.clock.value = invalid.source.valid_until
    with pytest.raises(R5PortfolioOutcomePersistenceConflict):
        invalid.runtime.persist.execute(_command(invalid.source))
    assert PortfolioR5RelativeValueOutcomeModel._default_manager.count() == 0


def test_transaction_boundary_key_mismatch_fails_at_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _ = make_persisted_bundles(monkeypatch)
    fixed_income = project_r5_relative_value_owner_record(bundle)
    source = _source(fixed_income)

    with pytest.raises(R5PortfolioOutcomePersistenceConflict, match="transaction"):
        build_django_r5_portfolio_outcome_runtime(
            source_provider=_SourceProvider(source, key="django:other"),
            fixed_income_query=GetExactR5RelativeValueOwnerRecord(_FixedIncomeRepository(bundle)),
            clock=_Clock(source.outcome_available_at + timedelta(seconds=1)),
        )


def test_integrity_race_returns_the_exact_existing_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _runtime(monkeypatch)
    expected = fixture.runtime.persist.execute(_command(fixture.source))
    winner = PortfolioR5RelativeValueOutcomeModel._default_manager.get(
        outcome_id=expected.outcome_id
    )
    calls = 0

    def race_lookup(**kwargs: object) -> PortfolioR5RelativeValueOutcomeModel | None:
        nonlocal calls
        calls += 1
        return None if calls == 1 else winner

    monkeypatch.setattr(
        composition_module,
        "_get_r5_outcome_by_owner_identity",
        race_lookup,
    )

    replay = fixture.runtime.persist.execute(_command(fixture.source))

    assert replay == expected
    assert PortfolioR5RelativeValueOutcomeModel._default_manager.count() == 1


def test_observation_identity_cannot_be_reused_by_a_different_owner_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _runtime(monkeypatch)
    first = fixture.runtime.persist.execute(_command(fixture.source))
    replacement_source = R5PortfolioOutcomeSourceRecord.create(
        **{
            **fixture.source.factory_values,
            "owner_record_id": "portfolio-outcome-owner-2",
        }
    )
    replacement_provider = _SourceProvider(replacement_source)
    replacement_runtime = build_django_r5_portfolio_outcome_runtime(
        source_provider=replacement_provider,
        fixed_income_query=GetExactR5RelativeValueOwnerRecord(fixture.fixed_income_repository),
        clock=fixture.clock,
    )

    with pytest.raises(R5PortfolioOutcomePersistenceConflict):
        replacement_runtime.persist.execute(_command(replacement_source))
    assert PortfolioR5RelativeValueOutcomeModel._default_manager.count() == 1
    assert first.observation_id == replacement_source.observation_id
