"""Fail-closed production composition for R8 monitoring persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.portfolio.application.governed_optimization_monitoring import (
    EvaluateGovernedOptimizationMonitoringCommand,
    GovernedOptimizationMonitoringClock,
)
from apps.portfolio.application.governed_optimization_monitoring_persistence import (
    AuditGovernedOptimizationMonitoringAssessmentsCommand,
    GetExactGovernedOptimizationMonitoringAssessment,
    GovernedOptimizationMonitoringPersistenceUnavailable,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_repository import (
    DjangoGovernedOptimizationMonitoringClock,
    DjangoGovernedOptimizationMonitoringRepository,
)


class UnavailableGovernedOptimizationMonitoringRegisterFacade:
    """Expose no write capability until every canonical owner is wired."""

    __slots__ = ()

    def execute(
        self,
        command: EvaluateGovernedOptimizationMonitoringCommand,
    ) -> NoReturn:
        """Revalidate the ID-only command and fail before database access."""

        try:
            if type(command) is not EvaluateGovernedOptimizationMonitoringCommand:
                raise TypeError("monitoring command type differs")
            EvaluateGovernedOptimizationMonitoringCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as exc:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring registration command is malformed"
            ) from exc
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "canonical R8 monitoring owner providers are unavailable"
        )


class UnavailableGovernedOptimizationMonitoringAuditFacade:
    """Keep audit snapshot writes outside the public runtime object graph."""

    __slots__ = ()

    def execute(
        self,
        command: AuditGovernedOptimizationMonitoringAssessmentsCommand,
    ) -> NoReturn:
        """Validate the query and fail until an internal snapshot writer exists."""

        try:
            if type(command) is not AuditGovernedOptimizationMonitoringAssessmentsCommand:
                raise TypeError("monitoring audit command type differs")
            AuditGovernedOptimizationMonitoringAssessmentsCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as exc:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring audit query is malformed"
            ) from exc
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring audit snapshot writer is unavailable in production"
        )


@dataclass(frozen=True)
class DjangoGovernedOptimizationMonitoringRuntime:
    """Read-safe runtime with inert registration and audit surfaces."""

    register: UnavailableGovernedOptimizationMonitoringRegisterFacade
    get_exact: GetExactGovernedOptimizationMonitoringAssessment
    audit: UnavailableGovernedOptimizationMonitoringAuditFacade


def build_django_governed_optimization_monitoring_runtime(
    *,
    using: str = "default",
) -> DjangoGovernedOptimizationMonitoringRuntime:
    """Build production reads without retaining a store, token, or writer."""

    return _build_django_governed_optimization_monitoring_runtime_for_test(
        using=using,
        clock=DjangoGovernedOptimizationMonitoringClock(),
    )


def _build_django_governed_optimization_monitoring_runtime_for_test(
    *,
    using: str = "default",
    clock: GovernedOptimizationMonitoringClock,
) -> DjangoGovernedOptimizationMonitoringRuntime:
    """Build the read-safe graph with an explicit clock for isolated tests."""

    repository = DjangoGovernedOptimizationMonitoringRepository(
        using=using,
        clock=clock,
    )
    return DjangoGovernedOptimizationMonitoringRuntime(
        register=UnavailableGovernedOptimizationMonitoringRegisterFacade(),
        get_exact=GetExactGovernedOptimizationMonitoringAssessment(repository),
        audit=UnavailableGovernedOptimizationMonitoringAuditFacade(),
    )


__all__ = [
    "DjangoGovernedOptimizationMonitoringRuntime",
    "UnavailableGovernedOptimizationMonitoringAuditFacade",
    "UnavailableGovernedOptimizationMonitoringRegisterFacade",
    "build_django_governed_optimization_monitoring_runtime",
]
