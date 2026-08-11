"""Narrow Signal owner adapter for the existing R7 monitoring realization port."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.research.domain.r7_post_promotion_monitoring import (
    R7ForecastRealizationMember,
    R7ForecastRealizationOwnerRecord,
)
from apps.research.domain.r7_post_promotion_monitoring_contracts import (
    R7MonitoringPeriodEntry,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
)
from apps.signal.application.forecast_realization_owner import (
    ExactForecastRealizationManifestCommand,
)
from apps.signal.domain.forecast_realization_owner import ForecastRealizationManifest


class ExactSignalForecastRealizationQuery(Protocol):
    """Signal Application query consumed by the Research infrastructure adapter."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared owner transaction identity."""

    def execute(
        self,
        command: ExactForecastRealizationManifestCommand,
    ) -> ForecastRealizationManifest | None:
        """Return one exact Signal owner manifest."""


class SignalForecastRealizationProviderCorruption(ValueError):
    """The Signal owner manifest cannot be projected into the R7 port."""


class SignalForecastRealizationProvider:
    """Adapt one exact Signal receipt manifest without any write capability."""

    __slots__ = ("_query",)

    def __init__(self, query: ExactSignalForecastRealizationQuery) -> None:
        self._query = query

    @property
    def unit_of_work_key(self) -> str:
        """Return the Signal query's exact transaction identity."""

        return self._query.unit_of_work_key

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_result_hash: str,
        period_id: str,
        period_version: str,
        expected_period_hash: str,
        as_of: datetime,
    ) -> R7ForecastRealizationOwnerRecord | None:
        """Return one R7 owner record or preserve missing Signal evidence as ``None``."""

        value = self._query.execute(
            ExactForecastRealizationManifestCommand(
                result_id=result_id,
                result_version=result_version,
                expected_result_hash=expected_result_hash,
                period_id=period_id,
                period_version=period_version,
                expected_period_hash=expected_period_hash,
                as_of=as_of,
            )
        )
        if value is None:
            return None
        try:
            if type(value) is not ForecastRealizationManifest:
                raise TypeError("Signal realization manifest type differs")
            manifest = ForecastRealizationManifest.validated_copy(value)
            period = R7MonitoringPeriodEntry(
                period_id=manifest.period_id,
                period_version=manifest.period_version,
                calendar_id=manifest.calendar_id,
                calendar_version=manifest.calendar_version,
                period_start=manifest.period_start,
                period_end=manifest.period_end,
                content_hash=manifest.period_hash,
            )
            R7MonitoringPeriodEntry.__post_init__(period)
            members: list[R7ForecastRealizationMember] = []
            for receipt in manifest.members:
                observation = ForecastLedgerOutcomeObservation.create(
                    observation_version=receipt.observation_version,
                    entry_id=receipt.entry_id,
                    forecast_group_id=receipt.forecast_group_id,
                    binding=receipt.binding,
                    pit_manifest_id=receipt.pit_manifest_id,
                    pit_manifest_version=receipt.pit_manifest_version,
                    pit_manifest_hash=receipt.pit_manifest_hash,
                    censoring_rule_version=receipt.censoring_rule_version,
                    published_at=receipt.published_at,
                    horizon_end=receipt.horizon_end,
                    scenario_realized=receipt.scenario_realized,
                    outcome_recorded_at=receipt.outcome_recorded_at,
                    outcome_evidence_valid_until=(receipt.outcome_evidence_valid_until),
                )
                if observation.content_hash != receipt.observation_hash:
                    raise ValueError("Signal observation seal differs from Research replay")
                members.append(
                    R7ForecastRealizationMember.from_owner_observation(
                        observation=observation,
                        available_at=receipt.available_at,
                        recorded_at=receipt.recorded_at,
                        evidence_ref=receipt.evidence_ref,
                    )
                )
            return R7ForecastRealizationOwnerRecord.create(
                owner_record_id=manifest.owner_record_id,
                owner_record_version=manifest.owner_record_version,
                period=period,
                pit_as_of=manifest.pit_as_of,
                available_at=manifest.available_at,
                recorded_at=manifest.recorded_at,
                valid_until=manifest.valid_until,
                evidence_ref=manifest.evidence_ref,
                members=tuple(members),
            )
        except SignalForecastRealizationProviderCorruption:
            raise
        except (AttributeError, TypeError, ValueError) as error:
            raise SignalForecastRealizationProviderCorruption(
                "Signal realization owner manifest cannot be replayed exactly"
            ) from error


__all__ = [
    "ExactSignalForecastRealizationQuery",
    "SignalForecastRealizationProvider",
    "SignalForecastRealizationProviderCorruption",
]
