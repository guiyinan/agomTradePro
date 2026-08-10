"""Fail-closed production composition for R4 monitoring persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringClock,
)
from apps.research.application.r4_promotion_monitoring_persistence import (
    AuditR4MonitoringAssessmentsCommand,
    GetExactR4MonitoringAssessment,
    R4MonitoringPersistenceUnavailable,
)
from apps.research.infrastructure.r4_promotion_monitoring_repository import (
    DjangoR4MonitoringClock,
    DjangoR4MonitoringRepository,
)


class UnavailableR4MonitoringRegisterFacade:
    """Expose no write capability until every canonical owner is wired."""

    __slots__ = ()

    def execute(self, command: EvaluateR4PromotionMonitoringCommand) -> NoReturn:
        """Revalidate the ID-only command and fail before persistence access."""

        try:
            if type(command) is not EvaluateR4PromotionMonitoringCommand:
                raise TypeError("R4 monitoring command type differs")
            EvaluateR4PromotionMonitoringCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring registration command is malformed"
            ) from error
        raise R4MonitoringPersistenceUnavailable(
            "canonical R4 monitoring owner providers are unavailable"
        )


class UnavailableR4MonitoringAuditFacade:
    """Keep audit snapshot writes outside the public runtime object graph."""

    __slots__ = ()

    def execute(self, command: AuditR4MonitoringAssessmentsCommand) -> NoReturn:
        """Validate the query and fail until an internal snapshot writer is wired."""

        try:
            if type(command) is not AuditR4MonitoringAssessmentsCommand:
                raise TypeError("R4 monitoring audit command type differs")
            AuditR4MonitoringAssessmentsCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring audit query is malformed"
            ) from error
        raise R4MonitoringPersistenceUnavailable(
            "R4 monitoring audit snapshot writer is unavailable in production composition"
        )


@dataclass(frozen=True)
class DjangoR4MonitoringRuntime:
    """Read-safe runtime with inert registration and audit surfaces."""

    register: UnavailableR4MonitoringRegisterFacade
    get_exact: GetExactR4MonitoringAssessment
    audit: UnavailableR4MonitoringAuditFacade


def build_django_r4_monitoring_runtime(
    *,
    using: str = "default",
    clock: R4MonitoringClock | None = None,
) -> DjangoR4MonitoringRuntime:
    """Build production reads without retaining any store or write token."""

    repository = DjangoR4MonitoringRepository(
        using=using,
        clock=clock or DjangoR4MonitoringClock(),
    )
    return DjangoR4MonitoringRuntime(
        register=UnavailableR4MonitoringRegisterFacade(),
        get_exact=GetExactR4MonitoringAssessment(repository),
        audit=UnavailableR4MonitoringAuditFacade(),
    )


__all__ = [
    "DjangoR4MonitoringRuntime",
    "UnavailableR4MonitoringAuditFacade",
    "UnavailableR4MonitoringRegisterFacade",
    "build_django_r4_monitoring_runtime",
]
