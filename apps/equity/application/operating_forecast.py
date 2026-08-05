"""Application orchestration for the R1 operating-forecast ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from apps.equity.domain.operating_forecast import (
    OperatingFactEvidence,
    OperatingForecastAssumption,
    OperatingForecastEvaluation,
    OperatingForecastProjection,
    OperatingForecastVersion,
    build_quarterly_evaluations,
)


class OperatingFactEvidenceProvider(Protocol):
    """Resolve exact Data Center operating PIT fact versions."""

    def get_operating_facts(
        self,
        version_ids: tuple[int, ...],
        *,
        as_of_time: datetime,
    ) -> tuple[OperatingFactEvidence, ...]: ...


class ResearchPromotionDecisionChecker(Protocol):
    """Check immutable Research PromotionDecision evidence."""

    def is_approved(self, decision_id: str) -> bool: ...


class OperatingForecastRepository(Protocol):
    """Append-only persistence contract owned by Equity."""

    def append_version(
        self,
        forecast: OperatingForecastVersion,
    ) -> OperatingForecastVersion: ...

    def get_version(self, forecast_id: str) -> OperatingForecastVersion | None: ...

    def append_evaluations(
        self,
        evaluations: tuple[OperatingForecastEvaluation, ...],
    ) -> tuple[OperatingForecastEvaluation, ...]: ...


class OperatingForecastNotFoundError(LookupError):
    """Raised when a quarterly actual references an unknown forecast."""


class OperatingForecastPromotionError(PermissionError):
    """Raised when Valuation consumption lacks approved Research evidence."""


class OperatingForecastEvidenceError(ValueError):
    """Raised when requested PIT versions are missing or substituted."""


class OperatingForecastConflictError(ValueError):
    """Raised when an immutable forecast identity has conflicting content."""


@dataclass(frozen=True)
class CreateOperatingForecastCommand:
    """Internal command for one immutable forecast version."""

    forecast_id: str
    forecast_key: str
    forecast_version: int
    subject_code: str
    industry_code: str
    as_of_time: datetime
    target_period_end: date
    horizon_quarters: int
    methodology_ref: str
    created_by_ref: str
    fact_version_ids: tuple[int, ...]
    assumptions: tuple[OperatingForecastAssumption, ...]
    projections: tuple[OperatingForecastProjection, ...]
    valuation_consumable: bool = False
    promotion_decision_id: str = ""


@dataclass(frozen=True)
class RecordQuarterlyActualCommand:
    """Internal command for actual-versus-forecast reconciliation."""

    forecast_id: str
    actual_period_end: date
    recorded_at: datetime
    actual_fact_version_ids: tuple[int, ...]
    actual_revenue: Decimal
    actual_net_profit: Decimal
    currency_unit: str


class CreateOperatingForecastVersionUseCase:
    """Resolve canonical facts, enforce promotion and append one version."""

    def __init__(
        self,
        repository: OperatingForecastRepository,
        fact_provider: OperatingFactEvidenceProvider,
        promotion_checker: ResearchPromotionDecisionChecker,
    ) -> None:
        self._repository = repository
        self._fact_provider = fact_provider
        self._promotion_checker = promotion_checker

    def execute(self, command: CreateOperatingForecastCommand) -> OperatingForecastVersion:
        """Create a research-only or approved-for-valuation forecast version."""

        facts = self._fact_provider.get_operating_facts(
            command.fact_version_ids,
            as_of_time=command.as_of_time,
        )
        requested_ids = set(command.fact_version_ids)
        resolved_ids = {fact.version_id for fact in facts}
        if len(requested_ids) != len(command.fact_version_ids) or resolved_ids != requested_ids:
            raise OperatingForecastEvidenceError(
                "operating PIT evidence must resolve exactly without duplicates or substitution"
            )
        forecast = OperatingForecastVersion(
            forecast_id=command.forecast_id,
            forecast_key=command.forecast_key,
            forecast_version=command.forecast_version,
            subject_code=command.subject_code,
            industry_code=command.industry_code,
            as_of_time=command.as_of_time,
            target_period_end=command.target_period_end,
            horizon_quarters=command.horizon_quarters,
            methodology_ref=command.methodology_ref,
            created_by_ref=command.created_by_ref,
            facts=facts,
            assumptions=command.assumptions,
            projections=command.projections,
            valuation_consumable=command.valuation_consumable,
            promotion_decision_id=command.promotion_decision_id,
        )
        if forecast.valuation_consumable and not self._promotion_checker.is_approved(
            forecast.promotion_decision_id
        ):
            raise OperatingForecastPromotionError(
                "valuation consumption requires an approved Research PromotionDecision"
            )
        return self._repository.append_version(forecast)


class RecordQuarterlyOperatingActualUseCase:
    """Append all three scenario error observations for one quarterly actual."""

    def __init__(
        self,
        repository: OperatingForecastRepository,
        fact_provider: OperatingFactEvidenceProvider,
    ) -> None:
        self._repository = repository
        self._fact_provider = fact_provider

    def execute(
        self,
        command: RecordQuarterlyActualCommand,
    ) -> tuple[OperatingForecastEvaluation, ...]:
        """Resolve actual evidence and append deterministic error metrics."""

        forecast = self._repository.get_version(command.forecast_id)
        if forecast is None:
            raise OperatingForecastNotFoundError(command.forecast_id)
        projection_units = {projection.currency_unit for projection in forecast.projections}
        if projection_units != {command.currency_unit}:
            raise OperatingForecastEvidenceError(
                "actual and forecast currency units must match exactly"
            )
        facts = self._fact_provider.get_operating_facts(
            command.actual_fact_version_ids,
            as_of_time=command.recorded_at,
        )
        requested_ids = set(command.actual_fact_version_ids)
        if (
            len(requested_ids) != len(command.actual_fact_version_ids)
            or {fact.version_id for fact in facts} != requested_ids
        ):
            raise OperatingForecastEvidenceError(
                "actual PIT evidence must resolve exactly without duplicates or substitution"
            )
        evaluations = build_quarterly_evaluations(
            forecast,
            actual_period_end=command.actual_period_end,
            recorded_at=command.recorded_at,
            actual_facts=facts,
            actual_revenue=command.actual_revenue,
            actual_net_profit=command.actual_net_profit,
            currency_unit=command.currency_unit,
        )
        return self._repository.append_evaluations(evaluations)


__all__ = [
    "CreateOperatingForecastCommand",
    "CreateOperatingForecastVersionUseCase",
    "OperatingFactEvidenceProvider",
    "OperatingForecastConflictError",
    "OperatingForecastEvidenceError",
    "OperatingForecastNotFoundError",
    "OperatingForecastPromotionError",
    "OperatingForecastRepository",
    "RecordQuarterlyActualCommand",
    "RecordQuarterlyOperatingActualUseCase",
    "ResearchPromotionDecisionChecker",
]
