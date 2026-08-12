"""Narrow read-only adapter from Signal calibration samples to the R7 port."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
    ScenarioInvalidationEvidence,
    ScenarioResearchScope,
)
from apps.signal.application.forecast_calibration_sample import (
    ExactForecastCalibrationSampleCommand,
)
from apps.signal.domain.forecast_calibration_sample import (
    ForecastCalibrationResolution,
    ForecastCalibrationSampleReceipt,
)


class ExactSignalForecastCalibrationSampleQuery(Protocol):
    """Signal Application query consumed by the Research adapter."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared owner transaction identity."""

    def execute(
        self,
        command: ExactForecastCalibrationSampleCommand,
    ) -> ForecastCalibrationSampleReceipt | None:
        """Return one exact Signal owner sample."""


class SignalForecastCalibrationSampleProviderCorruption(ValueError):
    """Raised when a Signal sample cannot be projected without invention."""


def _scope_copy(value: object) -> ScenarioResearchScope:
    if type(value) is not ScenarioResearchScope:
        raise ValueError("scope must use the exact Research domain type")
    assert isinstance(value, ScenarioResearchScope)
    rebuilt = ScenarioResearchScope.create(
        scope_version=value.scope_version,
        scenario_set_revision_id=value.scenario_set_revision_id,
        scenario_revision_ids=value.scenario_revision_ids,
        forecast_horizon=value.forecast_horizon,
        censoring_rule_version=value.censoring_rule_version,
        path_horizon_periods=value.path_horizon_periods,
        path_initial_state_revision_ids=value.path_initial_state_revision_ids,
    )
    if rebuilt.content_hash != value.content_hash:
        raise ValueError("scope seal is invalid")
    return rebuilt


class SignalForecastCalibrationSampleProvider:
    """Adapt one exhaustive Signal receipt into immutable R7 observations."""

    __slots__ = ("_query",)

    def __init__(self, query: ExactSignalForecastCalibrationSampleQuery) -> None:
        self._query = query

    @property
    def unit_of_work_key(self) -> str:
        """Return the Signal query's exact transaction identity."""

        return self._query.unit_of_work_key

    def list_exact(
        self,
        *,
        scope: ScenarioResearchScope,
        window_start: datetime,
        window_end: datetime,
        as_of: datetime,
    ) -> tuple[ForecastLedgerOutcomeObservation, ...]:
        """Return a complete denominator; missing owner data remains empty."""

        try:
            canonical_scope = _scope_copy(scope)
            value = self._query.execute(
                ExactForecastCalibrationSampleCommand(
                    scope_content_hash=canonical_scope.content_hash,
                    sample_window_start=window_start,
                    sample_window_end=window_end,
                    as_of=as_of,
                )
            )
            if value is None:
                return ()
            if type(value) is not ForecastCalibrationSampleReceipt:
                raise TypeError("Signal sample type differs")
            receipt = value.validated_copy()
            source = receipt.definition.source
            if (
                source.scope_content_hash != canonical_scope.content_hash
                or source.scenario_set_revision_id != canonical_scope.scenario_set_revision_id
                or source.scenario_revision_ids != canonical_scope.scenario_revision_ids
                or source.forecast_horizon != canonical_scope.forecast_horizon
                or source.censoring_rule_version != canonical_scope.censoring_rule_version
                or source.sample_window_start != window_start
                or source.sample_window_end != window_end
                or receipt.pit_as_of > as_of
                or receipt.recorded_at > as_of
            ):
                raise ValueError("Signal sample does not match the exact Research selectors")
            observations: list[ForecastLedgerOutcomeObservation] = []
            for member in receipt.members:
                expected = member.expected
                scenario_realized: bool | None = None
                outcome_recorded_at: datetime | None = None
                outcome_evidence_valid_until: datetime | None = None
                invalidation: ScenarioInvalidationEvidence | None = None
                if member.resolution is ForecastCalibrationResolution.RESOLVED:
                    scenario_realized = member.scenario_realized
                    outcome_recorded_at = member.outcome_recorded_at
                    outcome_evidence_valid_until = expected.outcome_evidence_valid_until
                elif member.resolution is ForecastCalibrationResolution.INVALIDATED:
                    owner_invalidation = member.invalidation
                    if owner_invalidation is None:
                        raise ValueError("invalidated member lacks owner evidence")
                    invalidation = ScenarioInvalidationEvidence.create(
                        evidence_version=owner_invalidation.evidence_version,
                        scenario_revision_id=expected.binding.scenario_revision_id,
                        scenario_set_revision_id=expected.binding.scenario_set_revision_id,
                        invalidated_at=owner_invalidation.invalidated_at,
                        invalidation_rule_version=(owner_invalidation.invalidation_rule_version),
                        pit_manifest_id=expected.pit_manifest_id,
                        evidence_refs=owner_invalidation.evidence_refs,
                    )
                observations.append(
                    ForecastLedgerOutcomeObservation.create(
                        observation_version=expected.observation_version,
                        entry_id=expected.entry_id,
                        forecast_group_id=expected.forecast_group_id,
                        binding=expected.binding,
                        pit_manifest_id=expected.pit_manifest_id,
                        pit_manifest_version=expected.pit_manifest_version,
                        pit_manifest_hash=expected.pit_manifest_hash,
                        censoring_rule_version=expected.censoring_rule_version,
                        published_at=expected.published_at,
                        horizon_end=expected.horizon_end,
                        scenario_realized=scenario_realized,
                        outcome_recorded_at=outcome_recorded_at,
                        outcome_evidence_valid_until=outcome_evidence_valid_until,
                        invalidation=invalidation,
                    )
                )
            return tuple(observations)
        except SignalForecastCalibrationSampleProviderCorruption:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise SignalForecastCalibrationSampleProviderCorruption(
                "Signal calibration sample cannot be replayed exactly"
            ) from exc


__all__ = [
    "ExactSignalForecastCalibrationSampleQuery",
    "SignalForecastCalibrationSampleProvider",
    "SignalForecastCalibrationSampleProviderCorruption",
]
