"""Fail-closed production composition for R5 monitoring persistence."""

from __future__ import annotations

from dataclasses import dataclass

from apps.research.application.r5_relative_value_monitoring import (
    EvaluateR5PostPromotionMonitoringCommand,
)
from apps.research.application.r5_relative_value_monitoring_persistence import (
    AuditR5MonitoringAssessmentsCommand,
    GetExactR5MonitoringAssessment,
    R5MonitoringAuditPage,
    R5MonitoringPersistedAssessment,
    R5MonitoringPersistenceUnavailable,
)
from apps.research.infrastructure.r5_relative_value_monitoring_repository import (
    DjangoR5MonitoringRepository,
)


class UnavailableR5MonitoringRegisterFacade:
    """Inert production writer until every canonical owner adapter exists."""

    __slots__ = ()

    def execute(
        self,
        command: EvaluateR5PostPromotionMonitoringCommand,
    ) -> R5MonitoringPersistedAssessment:
        """Reject registration without retaining a writer or owner object graph."""

        try:
            if type(command) is not EvaluateR5PostPromotionMonitoringCommand:
                raise TypeError
            EvaluateR5PostPromotionMonitoringCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring registration command is malformed"
            ) from error
        raise R5MonitoringPersistenceUnavailable(
            "canonical R5 monitoring owner providers are unavailable"
        )


class UnavailableR5MonitoringAuditFacade:
    """Inert audit writer; exact reads remain available separately."""

    __slots__ = ()

    def execute(self, command: AuditR5MonitoringAssessmentsCommand) -> R5MonitoringAuditPage:
        """Reject snapshot-producing audit until trusted internal composition exists."""

        try:
            if type(command) is not AuditR5MonitoringAssessmentsCommand:
                raise TypeError
            AuditR5MonitoringAssessmentsCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring audit command is malformed"
            ) from error
        raise R5MonitoringPersistenceUnavailable(
            "canonical R5 monitoring audit composition is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoR5MonitoringRuntime:
    """Public runtime exposing no repository store, token, provider, or clock."""

    register: UnavailableR5MonitoringRegisterFacade
    get_exact: GetExactR5MonitoringAssessment
    audit: UnavailableR5MonitoringAuditFacade


def build_django_r5_monitoring_runtime(
    *,
    using: str = "default",
) -> DjangoR5MonitoringRuntime:
    """Build safe exact reads and explicit unavailable mutation/audit facades."""

    repository = DjangoR5MonitoringRepository(using=using)
    return DjangoR5MonitoringRuntime(
        register=UnavailableR5MonitoringRegisterFacade(),
        get_exact=GetExactR5MonitoringAssessment(repository),
        audit=UnavailableR5MonitoringAuditFacade(),
    )


__all__ = [
    "DjangoR5MonitoringRuntime",
    "UnavailableR5MonitoringAuditFacade",
    "UnavailableR5MonitoringRegisterFacade",
    "build_django_r5_monitoring_runtime",
]
