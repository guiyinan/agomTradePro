"""Default manual caller wiring: lazy construction and one calendar cutoff."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from apps.data_center.application.calendar_capture_configuration import (
    CalendarCaptureConfigurationError,
    resolve_calendar_capture_configuration,
)
from apps.simulated_trading import execution_current_reference_composition as composition
from apps.simulated_trading.application.execution_settlement_uow import ExecutionCalendarUnavailable
from tests.unit.data_center.test_calendar_workbench_scope_composition import (
    DATASET,
    NOW,
    _candidates,
)


@pytest.mark.parametrize(
    ("settings_module", "environment"),
    [("core.settings.production", "production"), ("core.settings.development", "development")],
)
def test_default_manual_factory_reads_no_configuration_or_source_at_construction(
    monkeypatch: pytest.MonkeyPatch, settings_module: str, environment: str
) -> None:
    """An existing receipt must remain replayable without loading today's sources."""

    builder = getattr(composition, "build_current_reference_manual_trade_use_case", None)
    assert callable(builder), "feature missing: default current-reference manual caller factory"
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", settings_module)
    environments: list[str] = []
    original_factory = composition.build_current_reference_identity_reader

    def identity_factory(*, runtime_environment: str) -> object:
        environments.append(runtime_environment)
        return original_factory(runtime_environment=runtime_environment)

    def forbidden_read(*_args: object, **_kwargs: object) -> None:
        pytest.fail("manual caller construction must not read current configuration or sources")

    monkeypatch.setattr(composition, "build_current_reference_identity_reader", identity_factory)
    for name in (
        "get_active_runtime_profile",
        "get_active_runtime_value",
        "get_latest_runtime_snapshot",
        "read_instrument_reference_snapshot",
        "read_instrument_reference_mapping",
        "read_calendar_capture_configuration_at",
    ):
        monkeypatch.setattr(composition, name, forbidden_read, raising=False)

    use_case = builder()

    assert callable(getattr(use_case, "execute", None))
    assert environments == [environment]


def test_manual_calendar_reader_binds_configured_dataset_to_the_identical_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metadata and the exact publication consume the original request cutoff."""

    reader_type = getattr(composition, "_ConfiguredExecutionCalendarReader", None)
    assert callable(reader_type), "feature missing: configured manual calendar reader"
    configuration = resolve_calendar_capture_configuration(_candidates(), known_at=NOW)
    metadata_cutoffs: list[datetime] = []
    factories: list[tuple[str, str]] = []
    current_reads: list[tuple[str, datetime, date | None]] = []

    def read_configuration(*, as_of: datetime) -> object:
        metadata_cutoffs.append(as_of)
        return configuration

    def read_publication(*, exchange: str, as_of: datetime, coverage_start: date | None) -> None:
        current_reads.append((exchange, as_of, coverage_start))

    def calendar_factory(*, dataset_key: str, runtime_environment: str) -> object:
        factories.append((dataset_key, runtime_environment))
        return SimpleNamespace(get_effective_execution_calendar=read_publication)

    monkeypatch.setattr(composition, "read_calendar_capture_configuration_at", read_configuration)
    monkeypatch.setattr(
        composition, "build_current_published_execution_calendar_reader", calendar_factory
    )
    reader = reader_type(runtime_environment="development")

    result = reader.get_effective_execution_calendar(
        exchange="SSE", as_of=NOW, coverage_start=NOW.date()
    )

    assert result is None
    assert metadata_cutoffs == [NOW]
    assert factories == [(DATASET.value, "development")]
    assert current_reads == [("SSE", NOW, NOW.date())]


def test_manual_calendar_metadata_absence_does_not_query_a_default_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing catalog scope remains a typed unavailability without guessed datasets."""

    reader_type = getattr(composition, "_ConfiguredExecutionCalendarReader", None)
    assert callable(reader_type), "feature missing: configured manual calendar reader"
    owner_error = CalendarCaptureConfigurationError(
        "No selected calendar dataset", code="CALENDAR_CAPTURE_DATASET_MISSING"
    )

    def unavailable(*, as_of: datetime) -> None:
        assert as_of == NOW
        raise owner_error

    def forbidden_factory(**_kwargs: object) -> None:
        pytest.fail("missing calendar metadata must not choose a default publication")

    monkeypatch.setattr(composition, "read_calendar_capture_configuration_at", unavailable)
    monkeypatch.setattr(
        composition, "build_current_published_execution_calendar_reader", forbidden_factory
    )
    reader = reader_type(runtime_environment="development")

    with pytest.raises(ExecutionCalendarUnavailable) as error:
        reader.get_effective_execution_calendar(exchange="SSE", as_of=NOW, coverage_start=None)

    assert error.value.__cause__ is owner_error
