"""Component coverage for the Signal-owned R7 realization receipt ledger."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.signal.application.forecast_realization_owner import (
    AppendForecastRealizationManifestCommand,
    ExactForecastRealizationManifestCommand,
    ForecastRealizationOwnerUnavailable,
)
from apps.signal.application.forecast_realization_source_definition import (
    RegisterForecastRealizationSourceDefinitionCommand,
)
from apps.signal.domain.forecast_realization_owner import (
    ForecastRealizationManifestSource,
    ForecastRealizationMemberSource,
    forecast_observation_hash_from_values,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding
from apps.signal.forecast_realization_composition import (
    _build_django_forecast_realization_owner_test_runtime,
    build_django_forecast_realization_owner_runtime,
)
from apps.signal.forecast_realization_source_definition_composition import (
    _build_django_forecast_realization_source_definition_test_runtime,
)
from apps.signal.infrastructure.forecast_models import ForecastLedgerEntry, ForecastOutcome
from apps.signal.infrastructure.forecast_realization_models import (
    ForecastRealizationManifestModel,
    ForecastRealizationReceiptModel,
)
from apps.signal.infrastructure.forecast_realization_repository import (
    ForecastRealizationOwnerCorruption,
)

PUBLISHED_AT = datetime(2026, 7, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 8, 1, tzinfo=UTC)
OUTCOME_RECORDED_AT = PERIOD_END + timedelta(hours=1)
MEMBER_AVAILABLE_AT = PERIOD_END + timedelta(hours=2)
MANIFEST_AVAILABLE_AT = PERIOD_END + timedelta(hours=3)
SERVER_NOW = PERIOD_END + timedelta(hours=4)
VALID_UNTIL = PERIOD_END + timedelta(days=30)


class _SourceProvider:
    unit_of_work_key = "django:default"

    def __init__(self, source: ForecastRealizationManifestSource | None) -> None:
        self.source = source

    def get_exact(
        self,
        *,
        owner_record_id: str,
        owner_record_version: str,
        as_of: datetime,
    ) -> ForecastRealizationManifestSource | None:
        if self.source is None:
            return None
        assert (owner_record_id, owner_record_version) == (
            self.source.owner_record_id,
            self.source.owner_record_version,
        )
        assert as_of == SERVER_NOW
        return self.source


class _Clock:
    unit_of_work_key = "django:default"

    def now(self) -> datetime:
        return SERVER_NOW


def _source(
    *,
    evidence_ref: str = "forecast-realization-manifest:1",
) -> ForecastRealizationManifestSource:
    binding = ScenarioForecastBinding.from_values(
        scenario_revision_id=UUID("11111111-1111-1111-1111-111111111111"),
        scenario_set_revision_id=UUID("22222222-2222-2222-2222-222222222222"),
        subjective_probability=Decimal("0.600000000000"),
        subjective_probability_source_version="committee.v1",
        model_probability=Decimal("0.550000000000"),
        model_probability_source_version="model.v1",
        model_promotion_decision_id="promotion-1",
    )
    observation_hash = forecast_observation_hash_from_values(
        observation_version="r7-forecast-observation.v1",
        observation_id="forecast-1",
        entry_id="forecast-1",
        forecast_group_id="forecast-group-1",
        binding=binding,
        pit_manifest_id="pit-1",
        pit_manifest_version="pit-manifest.v1",
        pit_manifest_hash="c" * 64,
        censoring_rule_version="censoring.v1",
        published_at=PUBLISHED_AT,
        horizon_end=PERIOD_END,
        scenario_realized=True,
        outcome_recorded_at=OUTCOME_RECORDED_AT,
        outcome_evidence_valid_until=VALID_UNTIL,
    )
    member = ForecastRealizationMemberSource.create(
        entry_id="forecast-1",
        observation_id="forecast-1",
        observation_version="r7-forecast-observation.v1",
        expected_observation_hash=observation_hash,
        forecast_group_id="forecast-group-1",
        pit_manifest_version="pit-manifest.v1",
        pit_manifest_hash="c" * 64,
        censoring_rule_version="censoring.v1",
        outcome_evidence_valid_until=VALID_UNTIL,
        available_at=MEMBER_AVAILABLE_AT,
        evidence_ref="forecast-outcome:forecast-1",
    )
    return ForecastRealizationManifestSource.create(
        owner_record_id="realization-manifest-1",
        owner_record_version="manifest.v1",
        result_id="result-1",
        result_version="result.v1",
        result_hash="a" * 64,
        calendar_id="calendar-1",
        calendar_version="calendar.v1",
        period_id="period-1",
        period_version="period.v1",
        period_hash="b" * 64,
        period_start=PUBLISHED_AT,
        period_end=PERIOD_END,
        available_at=MANIFEST_AVAILABLE_AT,
        valid_until=VALID_UNTIL,
        evidence_ref=evidence_ref,
        members=(member,),
    )


def _persist_outcome() -> None:
    entry = ForecastLedgerEntry._default_manager.create(
        entry_id="forecast-1",
        published_at=PUBLISHED_AT,
        direction="LONG",
        asset_code="000300.SH",
        horizon_end=PERIOD_END,
        benchmark_asset="000300.SH",
        probability=0.6,
        invalidation_rule_version="invalidation.v1",
        decision_snapshot_id="decision-1",
        pit_manifest_id="pit-1",
        strategy_version="strategy.v1",
        model_version="",
        prompt_version="",
        source="research",
        regime="",
        scenario_revision_id=UUID("11111111-1111-1111-1111-111111111111"),
        scenario_set_revision_id=UUID("22222222-2222-2222-2222-222222222222"),
        subjective_probability=Decimal("0.6"),
        subjective_probability_source_version="committee.v1",
        model_probability=Decimal("0.55"),
        model_probability_source_version="model.v1",
        model_promotion_decision_id="promotion-1",
    )
    ForecastOutcome._default_manager.create(
        entry=entry,
        outcome_type="expired",
        finalized_at=OUTCOME_RECORDED_AT,
        scenario_realized=True,
        subjective_brier_score=0.16,
        model_brier_score=0.2025,
        evidence={"source": "canonical-test-owner"},
    )


def _register_source(
    source: ForecastRealizationManifestSource | None = None,
) -> None:
    runtime = _build_django_forecast_realization_source_definition_test_runtime(
        source_provider=_SourceProvider(source or _source()),
        clock=_Clock(),
    )
    runtime.register.execute(
        RegisterForecastRealizationSourceDefinitionCommand(
            owner_record_id="realization-manifest-1",
            owner_record_version="manifest.v1",
        )
    )


@pytest.mark.django_db
def test_id_only_append_rereads_outcome_and_exact_query_round_trips() -> None:
    """The receipt outcome comes from ForecastOutcome, never the caller command."""

    _persist_outcome()
    _register_source()
    runtime = _build_django_forecast_realization_owner_test_runtime(
        clock=_Clock(),
    )

    persisted = runtime.append.execute(
        AppendForecastRealizationManifestCommand(
            owner_record_id="realization-manifest-1",
            owner_record_version="manifest.v1",
        )
    )
    winner = runtime.append.execute(
        AppendForecastRealizationManifestCommand(
            owner_record_id="realization-manifest-1",
            owner_record_version="manifest.v1",
        )
    )
    restored = runtime.query.execute(
        ExactForecastRealizationManifestCommand(
            result_id="result-1",
            result_version="result.v1",
            expected_result_hash="a" * 64,
            period_id="period-1",
            period_version="period.v1",
            expected_period_hash="b" * 64,
            as_of=SERVER_NOW,
        )
    )

    assert restored == persisted
    assert winner == persisted
    assert persisted.members[0].scenario_realized is True
    assert ForecastRealizationManifestModel._default_manager.count() == 1
    assert ForecastRealizationReceiptModel._default_manager.count() == 1


@pytest.mark.django_db
def test_missing_outcome_fails_before_any_receipt_write() -> None:
    """Metadata alone cannot fabricate a realization."""

    _register_source()
    runtime = _build_django_forecast_realization_owner_test_runtime(
        clock=_Clock(),
    )

    with pytest.raises(ForecastRealizationOwnerUnavailable, match="outcome.*unavailable"):
        runtime.append.execute(
            AppendForecastRealizationManifestCommand(
                owner_record_id="realization-manifest-1",
                owner_record_version="manifest.v1",
            )
        )
    assert ForecastRealizationManifestModel._default_manager.count() == 0
    assert ForecastRealizationReceiptModel._default_manager.count() == 0


@pytest.mark.django_db
def test_empty_owner_ledger_exact_query_returns_none() -> None:
    """A production-empty schema remains an explicit absence."""

    runtime = build_django_forecast_realization_owner_runtime()

    assert (
        runtime.query.execute(
            ExactForecastRealizationManifestCommand(
                result_id="result-1",
                result_version="result.v1",
                expected_result_hash="a" * 64,
                period_id="period-1",
                period_version="period.v1",
                expected_period_hash="b" * 64,
                as_of=SERVER_NOW,
            )
        )
        is None
    )


@pytest.mark.django_db
def test_public_append_facade_is_zero_write_for_valid_and_malformed_commands() -> None:
    """Production never exposes the private owner-source writer."""

    runtime = build_django_forecast_realization_owner_runtime()
    command = AppendForecastRealizationManifestCommand(
        owner_record_id="realization-manifest-1",
        owner_record_version="manifest.v1",
    )
    with pytest.raises(ForecastRealizationOwnerUnavailable, match="provider.*unavailable"):
        runtime.append.execute(command)
    object.__setattr__(command, "owner_record_id", "")
    with pytest.raises(ForecastRealizationOwnerUnavailable, match="malformed"):
        runtime.append.execute(command)
    assert ForecastRealizationManifestModel._default_manager.count() == 0
    assert ForecastRealizationReceiptModel._default_manager.count() == 0


@pytest.mark.django_db
def test_realization_rows_are_append_only() -> None:
    """Normal ORM update/delete shortcuts cannot rewrite owner evidence."""

    _persist_outcome()
    _register_source()
    runtime = _build_django_forecast_realization_owner_test_runtime(
        clock=_Clock(),
    )
    runtime.append.execute(
        AppendForecastRealizationManifestCommand(
            owner_record_id="realization-manifest-1",
            owner_record_version="manifest.v1",
        )
    )

    with pytest.raises(ValidationError, match="append-only|updated"):
        ForecastRealizationManifestModel._default_manager.update(evidence_ref="forged")
    with pytest.raises(ValidationError, match="deleted|cannot be deleted"):
        ForecastRealizationReceiptModel._default_manager.all().delete()
    with pytest.raises(ValidationError, match="exact insert claim"):
        ForecastRealizationManifestModel().save()
    with pytest.raises(ValidationError, match="get_or_create"):
        ForecastRealizationManifestModel._default_manager.get_or_create(
            owner_record_id="forged",
            owner_record_version="v1",
        )
    with pytest.raises(ValidationError, match="exact appends"):
        ForecastRealizationReceiptModel._default_manager.bulk_create([])


@pytest.mark.django_db
def test_missing_source_definition_is_zero_write() -> None:
    """The 0011 writer cannot bypass an empty 0012 owner registry."""

    _persist_outcome()
    runtime = _build_django_forecast_realization_owner_test_runtime(clock=_Clock())

    with pytest.raises(ForecastRealizationOwnerUnavailable, match="source.*unavailable"):
        runtime.append.execute(
            AppendForecastRealizationManifestCommand(
                owner_record_id="realization-manifest-1",
                owner_record_version="manifest.v1",
            )
        )
    assert ForecastRealizationManifestModel._default_manager.count() == 0
    assert ForecastRealizationReceiptModel._default_manager.count() == 0


@pytest.mark.django_db
def test_receipt_insert_failure_rolls_back_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The header and every member receipt share one atomic append."""

    _persist_outcome()
    _register_source()
    runtime = _build_django_forecast_realization_owner_test_runtime(
        clock=_Clock(),
    )

    def fail_receipt_save(
        self: ForecastRealizationReceiptModel,
        **kwargs: object,
    ) -> None:
        raise ValidationError("injected receipt failure")

    monkeypatch.setattr(ForecastRealizationReceiptModel, "save", fail_receipt_save)
    with pytest.raises(ForecastRealizationOwnerUnavailable, match="append failed"):
        runtime.append.execute(
            AppendForecastRealizationManifestCommand(
                owner_record_id="realization-manifest-1",
                owner_record_version="manifest.v1",
            )
        )
    assert ForecastRealizationManifestModel._default_manager.count() == 0
    assert ForecastRealizationReceiptModel._default_manager.count() == 0


@pytest.mark.django_db
def test_exact_query_rejects_raw_manifest_header_tampering() -> None:
    """Strict source reconstruction detects mutation outside the guarded manager."""

    _persist_outcome()
    _register_source()
    runtime = _build_django_forecast_realization_owner_test_runtime(
        clock=_Clock(),
    )
    persisted = runtime.append.execute(
        AppendForecastRealizationManifestCommand(
            owner_record_id="realization-manifest-1",
            owner_record_version="manifest.v1",
        )
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE signal_forecast_realization_manifest "
            "SET evidence_ref = %s WHERE owner_record_id = %s",
            ["forged", persisted.owner_record_id],
        )

    with pytest.raises(ForecastRealizationOwnerCorruption, match="source hash"):
        runtime.query.execute(
            ExactForecastRealizationManifestCommand(
                result_id=persisted.result_id,
                result_version=persisted.result_version,
                expected_result_hash=persisted.result_hash,
                period_id=persisted.period_id,
                period_version=persisted.period_version,
                expected_period_hash=persisted.period_hash,
                as_of=SERVER_NOW,
            )
        )


@pytest.mark.django_db
def test_exact_query_rejects_raw_receipt_outcome_tampering() -> None:
    """Persisted realization cannot differ from the live immutable outcome reread."""

    _persist_outcome()
    _register_source()
    runtime = _build_django_forecast_realization_owner_test_runtime(
        clock=_Clock(),
    )
    persisted = runtime.append.execute(
        AppendForecastRealizationManifestCommand(
            owner_record_id="realization-manifest-1",
            owner_record_version="manifest.v1",
        )
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE signal_forecast_realization_receipt "
            "SET scenario_realized = %s WHERE observation_id = %s",
            [False, persisted.members[0].observation_id],
        )

    with pytest.raises(ForecastRealizationOwnerCorruption, match="receipt header"):
        runtime.query.execute(
            ExactForecastRealizationManifestCommand(
                result_id=persisted.result_id,
                result_version=persisted.result_version,
                expected_result_hash=persisted.result_hash,
                period_id=persisted.period_id,
                period_version=persisted.period_version,
                expected_period_hash=persisted.period_hash,
                as_of=SERVER_NOW,
            )
        )
