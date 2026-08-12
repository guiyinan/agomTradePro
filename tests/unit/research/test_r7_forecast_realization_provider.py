"""Narrow adapter tests from Signal receipts to the R7 monitoring owner port."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from apps.research.domain.r7_post_promotion_monitoring_contracts import (
    R7MonitoringPeriodEntry,
)
from apps.research.infrastructure.r7_forecast_realization_provider import (
    SignalForecastRealizationProvider,
)
from apps.signal.application.forecast_realization_owner import (
    ExactForecastRealizationManifestCommand,
)
from apps.signal.domain.forecast_realization_owner import (
    ForecastOutcomeOwnerRecord,
    ForecastRealizationManifest,
    ForecastRealizationManifestSource,
    ForecastRealizationMemberSource,
    forecast_observation_hash_from_values,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding

PUBLISHED_AT = datetime(2026, 7, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 8, 1, tzinfo=UTC)
OUTCOME_RECORDED_AT = PERIOD_END + timedelta(hours=1)
MEMBER_AVAILABLE_AT = PERIOD_END + timedelta(hours=2)
MANIFEST_AVAILABLE_AT = PERIOD_END + timedelta(hours=3)
RECORDED_AT = PERIOD_END + timedelta(hours=4)
VALID_UNTIL = PERIOD_END + timedelta(days=30)


def _manifest() -> ForecastRealizationManifest:
    period = R7MonitoringPeriodEntry.create(
        calendar_id="calendar-1",
        calendar_version="calendar.v1",
        period_start=PUBLISHED_AT,
        period_end=PERIOD_END,
    )
    binding = ScenarioForecastBinding.from_values(
        scenario_revision_id=UUID("11111111-1111-1111-1111-111111111111"),
        scenario_set_revision_id=UUID("22222222-2222-2222-2222-222222222222"),
        subjective_probability=Decimal("0.6"),
        subjective_probability_source_version="committee.v1",
        model_probability=Decimal("0.55"),
        model_probability_source_version="model.v1",
        model_promotion_decision_id="promotion-1",
    )
    outcome = ForecastOutcomeOwnerRecord.create(
        entry_id="forecast-1",
        binding=binding,
        pit_manifest_id="pit-1",
        published_at=PUBLISHED_AT,
        horizon_end=PERIOD_END,
        scenario_realized=True,
        outcome_recorded_at=OUTCOME_RECORDED_AT,
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
    source = ForecastRealizationManifestSource.create(
        owner_record_id="realization-manifest-1",
        owner_record_version="manifest.v1",
        result_id="result-1",
        result_version="result.v1",
        result_hash="a" * 64,
        calendar_id=period.calendar_id,
        calendar_version=period.calendar_version,
        period_id=period.period_id,
        period_version=period.period_version,
        period_hash=period.content_hash,
        period_start=period.period_start,
        period_end=period.period_end,
        available_at=MANIFEST_AVAILABLE_AT,
        valid_until=VALID_UNTIL,
        evidence_ref="forecast-realization-manifest:1",
        members=(member,),
    )
    return ForecastRealizationManifest.from_sources(
        source=source,
        outcomes=(outcome,),
        recorded_at=RECORDED_AT,
    )


class _Query:
    unit_of_work_key = "django:default"

    def __init__(self, value: ForecastRealizationManifest | None) -> None:
        self.value = value
        self.calls = 0

    def execute(
        self,
        command: ExactForecastRealizationManifestCommand,
    ) -> ForecastRealizationManifest | None:
        self.calls += 1
        command.__post_init__()
        return self.value


def test_adapter_projects_complete_identity_hash_horizon_and_knowledge_clocks() -> None:
    """The adapter maps exact receipts without deriving or rewriting outcomes."""

    manifest = _manifest()
    query = _Query(manifest)
    provider = SignalForecastRealizationProvider(query)

    record = provider.get_exact(
        result_id=manifest.result_id,
        result_version=manifest.result_version,
        expected_result_hash=manifest.result_hash,
        period_id=manifest.period_id,
        period_version=manifest.period_version,
        expected_period_hash=manifest.period_hash,
        as_of=RECORDED_AT,
    )

    assert record is not None
    assert record.owner == "signal.forecast_ledger"
    assert record.owner_record_id == manifest.owner_record_id
    assert record.period_id == manifest.period_id
    assert record.period_hash == manifest.period_hash
    assert record.pit_as_of == manifest.pit_as_of
    assert record.available_at == manifest.available_at
    assert record.recorded_at == manifest.recorded_at
    assert len(record.members) == 1
    assert record.members[0].observation_id == "forecast-1"
    assert record.members[0].observation_version == "r7-forecast-observation.v1"
    assert record.members[0].observation_hash == manifest.members[0].observation_hash
    assert record.members[0].horizon_end == PERIOD_END
    assert record.members[0].realized is True
    assert query.calls == 1


def test_adapter_preserves_missing_receipt_as_none() -> None:
    """An empty Signal owner ledger remains the monitoring port's stable absence."""

    query = _Query(None)
    provider = SignalForecastRealizationProvider(query)
    manifest = _manifest()

    assert (
        provider.get_exact(
            result_id=manifest.result_id,
            result_version=manifest.result_version,
            expected_result_hash=manifest.result_hash,
            period_id=manifest.period_id,
            period_version=manifest.period_version,
            expected_period_hash=manifest.period_hash,
            as_of=RECORDED_AT,
        )
        is None
    )
