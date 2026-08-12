"""Component coverage for the Signal calibration sample owner registry."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.signal.application.forecast_calibration_sample import (
    ExactForecastCalibrationSampleCommand,
    ForecastCalibrationSampleUnavailable,
    RegisterForecastCalibrationSampleDefinitionCommand,
    RegisterForecastCalibrationSampleReceiptCommand,
)
from apps.signal.domain.forecast_calibration_sample import (
    ForecastCalibrationEntryOwnerRecord,
    ForecastCalibrationResolution,
    ForecastCalibrationSampleSource,
)
from apps.signal.forecast_calibration_sample_composition import (
    _build_django_forecast_calibration_sample_test_runtime,
    _DjangoForecastCalibrationSampleTestRuntime,
)
from apps.signal.infrastructure.forecast_calibration_sample_models import (
    ForecastCalibrationExpectedMemberModel,
    ForecastCalibrationSampleDefinitionModel,
    ForecastCalibrationSampleMemberReceiptModel,
    ForecastCalibrationSampleReceiptModel,
)
from apps.signal.infrastructure.forecast_calibration_sample_repository import (
    ForecastCalibrationSampleCorruption,
)
from tests.unit.signal.test_forecast_calibration_sample import (
    NOW,
    WINDOW_END,
    WINDOW_START,
    _definition,
    _owner,
    _source,
)


class _SourceProvider:
    unit_of_work_key = "django:default"

    def __init__(self, source: ForecastCalibrationSampleSource | None) -> None:
        self.source = source
        self.calls = 0

    def get_source(
        self,
        *,
        sample_id: str,
        sample_version: str,
        as_of: datetime,
    ) -> ForecastCalibrationSampleSource | None:
        assert sample_id == "calibration-sample-1"
        assert sample_version == "sample.v1"
        assert as_of >= NOW
        self.calls += 1
        return self.source


class _DriftingSourceProvider(_SourceProvider):
    def get_source(
        self,
        *,
        sample_id: str,
        sample_version: str,
        as_of: datetime,
    ) -> ForecastCalibrationSampleSource | None:
        value = super().get_source(
            sample_id=sample_id,
            sample_version=sample_version,
            as_of=as_of,
        )
        if self.calls == 1:
            self.unit_of_work_key = "django:drifted"
        return value


class _EntryProvider:
    unit_of_work_key = "django:default"

    def __init__(self, values: dict[str, ForecastCalibrationEntryOwnerRecord]) -> None:
        self.values = values
        self.calls = 0

    def get_entry(
        self,
        *,
        entry_id: str,
        as_of: datetime,
    ) -> ForecastCalibrationEntryOwnerRecord | None:
        assert as_of >= NOW
        self.calls += 1
        return self.values.get(entry_id)


class _ForkingEntryProvider(_EntryProvider):
    def __init__(
        self,
        first: dict[str, ForecastCalibrationEntryOwnerRecord],
        second: dict[str, ForecastCalibrationEntryOwnerRecord],
    ) -> None:
        super().__init__(first)
        self.second = second

    def get_entry(
        self,
        *,
        entry_id: str,
        as_of: datetime,
    ) -> ForecastCalibrationEntryOwnerRecord | None:
        self.calls += 1
        values = self.values if self.calls <= len(self.values) else self.second
        return values.get(entry_id)


class _Clock:
    unit_of_work_key = "django:default"

    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _owners(*, first_realized: bool = True) -> dict[str, ForecastCalibrationEntryOwnerRecord]:
    members = _source().members
    return {
        members[0].entry_id: _owner(
            members[0],
            ForecastCalibrationResolution.RESOLVED,
            scenario_realized=first_realized,
        ),
        members[1].entry_id: _owner(
            members[1],
            ForecastCalibrationResolution.RESOLVED,
            scenario_realized=False,
        ),
        members[2].entry_id: _owner(
            members[2],
            ForecastCalibrationResolution.UNRESOLVED,
        ),
        members[3].entry_id: _owner(
            members[3],
            ForecastCalibrationResolution.CENSORED,
        ),
    }


def _runtime(
    *,
    source: ForecastCalibrationSampleSource | None = None,
    owners: dict[str, ForecastCalibrationEntryOwnerRecord] | None = None,
    clock: _Clock | None = None,
) -> _DjangoForecastCalibrationSampleTestRuntime:
    return _build_django_forecast_calibration_sample_test_runtime(
        source_provider=_SourceProvider(_source() if source is None else source),
        entry_provider=_EntryProvider(_owners() if owners is None else owners),
        clock=clock or _Clock(),
    )


def _definition_command(
    as_of: datetime = NOW,
) -> RegisterForecastCalibrationSampleDefinitionCommand:
    return RegisterForecastCalibrationSampleDefinitionCommand(
        sample_id="calibration-sample-1",
        sample_version="sample.v1",
        as_of=as_of,
    )


def _receipt_command(as_of: datetime = NOW) -> RegisterForecastCalibrationSampleReceiptCommand:
    return RegisterForecastCalibrationSampleReceiptCommand(
        sample_id="calibration-sample-1",
        sample_version="sample.v1",
        as_of=as_of,
    )


def _query_command(as_of: datetime = NOW) -> ExactForecastCalibrationSampleCommand:
    return ExactForecastCalibrationSampleCommand(
        scope_content_hash="a" * 64,
        sample_window_start=WINDOW_START,
        sample_window_end=WINDOW_END,
        as_of=as_of,
    )


@pytest.mark.django_db
def test_definition_and_four_state_receipt_round_trip_exact_pit() -> None:
    """ID-only owner rereads append one complete definition and receipt graph."""

    runtime = _runtime()
    definition = runtime.register_definition.execute(_definition_command())
    receipt = runtime.register_receipt.execute(_receipt_command())
    restored = runtime.query.execute(_query_command())

    assert definition == _definition()
    assert restored == receipt
    assert tuple(member.resolution for member in receipt.members) == (
        ForecastCalibrationResolution.RESOLVED,
        ForecastCalibrationResolution.RESOLVED,
        ForecastCalibrationResolution.UNRESOLVED,
        ForecastCalibrationResolution.CENSORED,
    )
    assert ForecastCalibrationSampleDefinitionModel._default_manager.count() == 1
    assert ForecastCalibrationExpectedMemberModel._default_manager.count() == 4
    assert ForecastCalibrationSampleReceiptModel._default_manager.count() == 1
    assert ForecastCalibrationSampleMemberReceiptModel._default_manager.count() == 4


@pytest.mark.django_db
def test_live_uow_drift_is_rejected_before_any_definition_write() -> None:
    """A provider cannot change transaction identity after the builder check."""

    runtime = _build_django_forecast_calibration_sample_test_runtime(
        source_provider=_DriftingSourceProvider(_source()),
        entry_provider=_EntryProvider(_owners()),
        clock=_Clock(),
    )
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="units of work"):
        runtime.register_definition.execute(_definition_command())
    assert ForecastCalibrationSampleDefinitionModel._default_manager.count() == 0


@pytest.mark.django_db
def test_missing_membership_or_ledger_entry_is_zero_partial_write() -> None:
    """Missing owner data cannot become an empty denominator or partial receipt."""

    missing_source = _build_django_forecast_calibration_sample_test_runtime(
        source_provider=_SourceProvider(None),
        entry_provider=_EntryProvider(_owners()),
        clock=_Clock(),
    )
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="unavailable"):
        missing_source.register_definition.execute(_definition_command())
    assert ForecastCalibrationSampleDefinitionModel._default_manager.count() == 0

    owners = _owners()
    owners.pop("entry-d")
    runtime = _runtime(owners=owners)
    runtime.register_definition.execute(_definition_command())
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="unavailable"):
        runtime.register_receipt.execute(_receipt_command())
    assert ForecastCalibrationSampleReceiptModel._default_manager.count() == 0
    assert ForecastCalibrationSampleMemberReceiptModel._default_manager.count() == 0


@pytest.mark.django_db
def test_owner_change_between_double_reads_rolls_back_receipt() -> None:
    """A changed raw outcome graph leaves no receipt header or member rows."""

    runtime = _build_django_forecast_calibration_sample_test_runtime(
        source_provider=_SourceProvider(_source()),
        entry_provider=_ForkingEntryProvider(_owners(), _owners(first_realized=False)),
        clock=_Clock(),
    )
    runtime.register_definition.execute(_definition_command())
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="changed"):
        runtime.register_receipt.execute(_receipt_command())
    assert ForecastCalibrationSampleReceiptModel._default_manager.count() == 0
    assert ForecastCalibrationSampleMemberReceiptModel._default_manager.count() == 0


@pytest.mark.django_db
def test_member_insert_failure_rolls_back_receipt_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Receipt header and all explicit state rows share one transaction."""

    runtime = _runtime()
    runtime.register_definition.execute(_definition_command())

    def fail_save(
        self: ForecastCalibrationSampleMemberReceiptModel,
        **kwargs: object,
    ) -> None:
        raise ValidationError("injected receipt member failure")

    monkeypatch.setattr(ForecastCalibrationSampleMemberReceiptModel, "save", fail_save)
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="append failed"):
        runtime.register_receipt.execute(_receipt_command())
    assert ForecastCalibrationSampleReceiptModel._default_manager.count() == 0
    assert ForecastCalibrationSampleMemberReceiptModel._default_manager.count() == 0


@pytest.mark.django_db
def test_latest_pit_wins_and_same_rank_owner_fork_fails_closed() -> None:
    """Later PIT receipts win, while two different same-rank receipts are ambiguous."""

    runtime = _runtime()
    runtime.register_definition.execute(_definition_command())
    first = runtime.register_receipt.execute(_receipt_command())

    later = NOW + timedelta(hours=1)
    later_runtime = _runtime(clock=_Clock(later))
    second = later_runtime.register_receipt.execute(_receipt_command(later))
    assert later_runtime.query.execute(_query_command(later)) == second
    assert second.pit_as_of > first.pit_as_of

    fork_runtime = _runtime(owners=_owners(first_realized=False), clock=_Clock(later))
    fork_runtime.register_receipt.execute(_receipt_command(later))
    with pytest.raises(ForecastCalibrationSampleCorruption, match="winner fork"):
        fork_runtime.query.execute(_query_command(later))


@pytest.mark.django_db
def test_definition_fork_fails_closed() -> None:
    """Two active definitions with one identity never select a winner."""

    runtime = _runtime()
    persisted = runtime.register_definition.execute(_definition_command())
    changed = ForecastCalibrationSampleSource.create(
        sample_id=persisted.source.sample_id,
        sample_version=persisted.source.sample_version,
        scope_content_hash=persisted.source.scope_content_hash,
        scenario_set_revision_id=persisted.source.scenario_set_revision_id,
        scenario_revision_ids=persisted.source.scenario_revision_ids,
        forecast_horizon=persisted.source.forecast_horizon,
        censoring_rule_version=persisted.source.censoring_rule_version,
        sample_window_start=persisted.source.sample_window_start,
        sample_window_end=persisted.source.sample_window_end,
        available_at=persisted.source.available_at,
        valid_until=persisted.source.valid_until,
        evidence_ref="signal://calibration/replacement",
        members=persisted.source.members,
    )
    _runtime(source=changed).register_definition.execute(_definition_command())
    with pytest.raises(ForecastCalibrationSampleCorruption, match="fork"):
        runtime.query.execute(_query_command())


@pytest.mark.django_db
def test_relational_tamper_fails_closed() -> None:
    """Receipt member mirrors must agree with the strict sealed payload."""

    runtime = _runtime()
    runtime.register_definition.execute(_definition_command())
    receipt = runtime.register_receipt.execute(_receipt_command())
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE signal_forecast_calibration_sample_member_receipt "
            "SET owner_record_hash = %s WHERE entry_id = %s",
            ["f" * 64, receipt.members[0].entry_id],
        )
    with pytest.raises(ForecastCalibrationSampleCorruption, match="member"):
        runtime.query.execute(_query_command())


@pytest.mark.django_db
def test_rows_reject_orm_mutation_deletion_and_unclaimed_insert() -> None:
    """All four tables remain append-only behind the private UoW claim."""

    runtime = _runtime()
    runtime.register_definition.execute(_definition_command())
    runtime.register_receipt.execute(_receipt_command())

    with pytest.raises(ValidationError, match="append-only|updated"):
        ForecastCalibrationSampleReceiptModel._default_manager.update(content_hash="f" * 64)
    with pytest.raises((ValidationError, ValueError), match="delete|deleted"):
        ForecastCalibrationSampleMemberReceiptModel._default_manager.all().delete()
    with pytest.raises(ValidationError, match="exact insert claim"):
        ForecastCalibrationSampleDefinitionModel().save()
    with pytest.raises(ValidationError, match="get_or_create"):
        ForecastCalibrationSampleReceiptModel._default_manager.get_or_create(receipt_id="forged")
