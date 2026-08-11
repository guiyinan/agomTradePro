"""Component coverage for the Signal realization-source definition registry."""

from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.signal.application.forecast_realization_source_definition import (
    ExactForecastRealizationSourceDefinitionCommand,
    ForecastRealizationSourceDefinitionUnavailable,
    RegisterForecastRealizationSourceDefinitionCommand,
)
from apps.signal.domain.forecast_realization_owner import ForecastRealizationManifestSource
from apps.signal.forecast_realization_source_definition_composition import (
    _build_django_forecast_realization_source_definition_test_runtime,
    _DjangoForecastRealizationSourceDefinitionTestRuntime,
    build_django_forecast_realization_source_definition_runtime,
)
from apps.signal.infrastructure.forecast_realization_models import (
    ForecastRealizationSourceDefinitionMemberModel,
    ForecastRealizationSourceDefinitionModel,
)
from apps.signal.infrastructure.forecast_realization_source_definition_repository import (
    ForecastRealizationSourceDefinitionCorruption,
)
from tests.unit.signal.test_forecast_realization_owner import RECORDED_AT, _source

SERVER_NOW = RECORDED_AT


class _SourceProvider:
    unit_of_work_key = "django:default"

    def __init__(self, source: ForecastRealizationManifestSource | None) -> None:
        self._source = source

    def get_exact(
        self,
        *,
        owner_record_id: str,
        owner_record_version: str,
        as_of: datetime,
    ) -> ForecastRealizationManifestSource | None:
        assert owner_record_id == "realization-manifest-1"
        assert owner_record_version == "manifest.v1"
        assert as_of == SERVER_NOW
        return self._source


class _SequenceSourceProvider:
    unit_of_work_key = "django:default"

    def __init__(self, values: tuple[ForecastRealizationManifestSource, ...]) -> None:
        self._values = list(values)

    def get_exact(
        self,
        *,
        owner_record_id: str,
        owner_record_version: str,
        as_of: datetime,
    ) -> ForecastRealizationManifestSource | None:
        assert owner_record_id == "realization-manifest-1"
        assert owner_record_version == "manifest.v1"
        assert as_of == SERVER_NOW
        return self._values.pop(0)


class _Clock:
    unit_of_work_key = "django:default"

    def now(self) -> datetime:
        return SERVER_NOW


def _changed_source() -> ForecastRealizationManifestSource:
    source = _source()
    return ForecastRealizationManifestSource.create(
        owner_record_id=source.owner_record_id,
        owner_record_version=source.owner_record_version,
        result_id=source.result_id,
        result_version=source.result_version,
        result_hash=source.result_hash,
        calendar_id=source.calendar_id,
        calendar_version=source.calendar_version,
        period_id=source.period_id,
        period_version=source.period_version,
        period_hash=source.period_hash,
        period_start=source.period_start,
        period_end=source.period_end,
        available_at=source.available_at,
        valid_until=source.valid_until,
        evidence_ref="forecast-realization-manifest:replacement",
        members=source.members,
    )


def _register_runtime() -> _DjangoForecastRealizationSourceDefinitionTestRuntime:
    return _build_django_forecast_realization_source_definition_test_runtime(
        source_provider=_SourceProvider(_source()),
        clock=_Clock(),
    )


@pytest.mark.django_db
def test_id_only_registration_round_trips_winner_and_pit_cutoffs() -> None:
    """One stable double-read source wins and remains hash-bound in PIT queries."""

    runtime = _register_runtime()
    command = RegisterForecastRealizationSourceDefinitionCommand(
        owner_record_id="realization-manifest-1",
        owner_record_version="manifest.v1",
    )
    persisted = runtime.register.execute(command)
    winner = runtime.register.execute(command)

    restored = runtime.query.execute(
        ExactForecastRealizationSourceDefinitionCommand(
            owner_record_id=command.owner_record_id,
            owner_record_version=command.owner_record_version,
            expected_content_hash=persisted.content_hash,
            as_of=SERVER_NOW,
        )
    )
    before_registration = runtime.query.execute(
        ExactForecastRealizationSourceDefinitionCommand(
            owner_record_id=command.owner_record_id,
            owner_record_version=command.owner_record_version,
            expected_content_hash=persisted.content_hash,
            as_of=SERVER_NOW - timedelta(microseconds=1),
        )
    )
    after_expiry = runtime.query.execute(
        ExactForecastRealizationSourceDefinitionCommand(
            owner_record_id=command.owner_record_id,
            owner_record_version=command.owner_record_version,
            expected_content_hash=persisted.content_hash,
            as_of=persisted.source.valid_until,
        )
    )

    assert restored == persisted
    assert winner == persisted
    assert before_registration is None
    assert after_expiry is None
    assert ForecastRealizationSourceDefinitionModel._default_manager.count() == 1
    assert ForecastRealizationSourceDefinitionMemberModel._default_manager.count() == 1


@pytest.mark.django_db
def test_missing_canonical_source_is_zero_write() -> None:
    """An empty production source cannot be promoted into a registry definition."""

    runtime = _build_django_forecast_realization_source_definition_test_runtime(
        source_provider=_SourceProvider(None),
        clock=_Clock(),
    )
    with pytest.raises(ForecastRealizationSourceDefinitionUnavailable, match="unavailable"):
        runtime.register.execute(
            RegisterForecastRealizationSourceDefinitionCommand(
                owner_record_id="realization-manifest-1",
                owner_record_version="manifest.v1",
            )
        )
    assert ForecastRealizationSourceDefinitionModel._default_manager.count() == 0
    assert ForecastRealizationSourceDefinitionMemberModel._default_manager.count() == 0


@pytest.mark.django_db
def test_public_registration_is_inert_for_valid_and_mutated_commands() -> None:
    """Production cannot inject a source, clock, token, or registry writer."""

    runtime = build_django_forecast_realization_source_definition_runtime()
    command = RegisterForecastRealizationSourceDefinitionCommand(
        owner_record_id="realization-manifest-1",
        owner_record_version="manifest.v1",
    )
    with pytest.raises(ForecastRealizationSourceDefinitionUnavailable, match="unavailable"):
        runtime.register.execute(command)
    object.__setattr__(command, "owner_record_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(ForecastRealizationSourceDefinitionUnavailable, match="malformed"):
        runtime.register.execute(command)
    assert ForecastRealizationSourceDefinitionModel._default_manager.count() == 0
    assert ForecastRealizationSourceDefinitionMemberModel._default_manager.count() == 0


@pytest.mark.django_db
def test_source_fork_between_double_reads_rolls_back_without_rows() -> None:
    """A changed canonical graph cannot create a partial or ambiguous definition."""

    runtime = _build_django_forecast_realization_source_definition_test_runtime(
        source_provider=_SequenceSourceProvider((_source(), _changed_source())),
        clock=_Clock(),
    )
    with pytest.raises(ForecastRealizationSourceDefinitionUnavailable, match="changed"):
        runtime.register.execute(
            RegisterForecastRealizationSourceDefinitionCommand(
                owner_record_id="realization-manifest-1",
                owner_record_version="manifest.v1",
            )
        )
    assert ForecastRealizationSourceDefinitionModel._default_manager.count() == 0
    assert ForecastRealizationSourceDefinitionMemberModel._default_manager.count() == 0


@pytest.mark.django_db
def test_member_insert_failure_rolls_back_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Header and complete membership share one atomic append."""

    runtime = _register_runtime()

    def fail_member_save(
        self: ForecastRealizationSourceDefinitionMemberModel,
        **kwargs: object,
    ) -> None:
        raise ValidationError("injected member failure")

    monkeypatch.setattr(
        ForecastRealizationSourceDefinitionMemberModel,
        "save",
        fail_member_save,
    )
    with pytest.raises(ForecastRealizationSourceDefinitionUnavailable, match="append failed"):
        runtime.register.execute(
            RegisterForecastRealizationSourceDefinitionCommand(
                owner_record_id="realization-manifest-1",
                owner_record_version="manifest.v1",
            )
        )
    assert ForecastRealizationSourceDefinitionModel._default_manager.count() == 0
    assert ForecastRealizationSourceDefinitionMemberModel._default_manager.count() == 0


@pytest.mark.django_db
def test_definition_rows_reject_orm_mutation_and_deletion() -> None:
    """Registry definitions and members remain append-only after registration."""

    runtime = _register_runtime()
    runtime.register.execute(
        RegisterForecastRealizationSourceDefinitionCommand(
            owner_record_id="realization-manifest-1",
            owner_record_version="manifest.v1",
        )
    )
    with pytest.raises(ValidationError, match="append-only|updated"):
        ForecastRealizationSourceDefinitionModel._default_manager.update(evidence_ref="forged")
    with pytest.raises(ValidationError, match="deleted|cannot be deleted"):
        ForecastRealizationSourceDefinitionMemberModel._default_manager.all().delete()
    with pytest.raises(ValidationError, match="exact insert claim"):
        ForecastRealizationSourceDefinitionModel().save()
    with pytest.raises(ValidationError, match="get_or_create"):
        ForecastRealizationSourceDefinitionModel._default_manager.get_or_create(
            owner_record_id="forged",
            owner_record_version="v1",
        )


@pytest.mark.django_db
def test_exact_query_detects_raw_header_and_member_tampering() -> None:
    """Relational mirrors must agree exactly with the strict sealed payload."""

    runtime = _register_runtime()
    persisted = runtime.register.execute(
        RegisterForecastRealizationSourceDefinitionCommand(
            owner_record_id="realization-manifest-1",
            owner_record_version="manifest.v1",
        )
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE signal_forecast_realization_source_definition_member "
            "SET forecast_group_id = %s WHERE entry_id = %s",
            ["forged", persisted.source.members[0].entry_id],
        )
    with pytest.raises(ForecastRealizationSourceDefinitionCorruption, match="member"):
        runtime.query.execute(
            ExactForecastRealizationSourceDefinitionCommand(
                owner_record_id=persisted.source.owner_record_id,
                owner_record_version=persisted.source.owner_record_version,
                expected_content_hash=persisted.content_hash,
                as_of=SERVER_NOW,
            )
        )
