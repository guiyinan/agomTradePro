"""Fail-closed production composition for R2 trial-monitoring persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.research.application.r2_market_structure_trial_monitoring import (
    EvaluateR2MarketStructureTrialCommand,
)
from apps.research.application.r2_market_structure_trial_monitoring_persistence import (
    AuditR2MonitoringCommand,
    GetExactR2MonitoringAssessment,
    GetExactR2TrialAssessment,
    R2TrialMonitoringPersistenceUnavailable,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_repository import (
    DjangoR2TrialMonitoringRepository,
)


class UnavailableR2TrialRegisterFacade:
    """Inert trial writer until every canonical owner adapter exists."""

    __slots__ = ()

    def execute(self, command: EvaluateR2MarketStructureTrialCommand) -> NoReturn:
        """Validate ID-only input, then reject without retaining capabilities."""

        _validate_registration_command(command)
        raise R2TrialMonitoringPersistenceUnavailable(
            "canonical R2 explanatory-trial owner providers are unavailable"
        )


class UnavailableR2MonitoringRegisterFacade:
    """Inert monitoring writer until every canonical owner adapter exists."""

    __slots__ = ()

    def execute(self, command: EvaluateR2MarketStructureTrialCommand) -> NoReturn:
        """Validate ID-only input, then reject without retaining capabilities."""

        _validate_registration_command(command)
        raise R2TrialMonitoringPersistenceUnavailable(
            "canonical R2 monitoring owner providers are unavailable"
        )


class UnavailableR2MonitoringAuditFacade:
    """Inert snapshot writer; exact reads remain separately available."""

    __slots__ = ()

    def execute(self, command: AuditR2MonitoringCommand) -> NoReturn:
        """Reject snapshot mutation without a trusted internal composition."""

        try:
            if type(command) is not AuditR2MonitoringCommand:
                raise TypeError("audit command type differs")
            AuditR2MonitoringCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 monitoring audit command is malformed"
            ) from error
        raise R2TrialMonitoringPersistenceUnavailable(
            "canonical R2 monitoring audit composition is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoR2TrialMonitoringRuntime:
    """Public runtime exposing exact reads and no writer/provider/clock graph."""

    register_trial: UnavailableR2TrialRegisterFacade
    register_monitoring: UnavailableR2MonitoringRegisterFacade
    get_trial_exact: GetExactR2TrialAssessment
    get_monitoring_exact: GetExactR2MonitoringAssessment
    audit: UnavailableR2MonitoringAuditFacade


def build_django_r2_trial_monitoring_runtime(
    *,
    using: str = "default",
) -> DjangoR2TrialMonitoringRuntime:
    """Build exact reads plus explicit unavailable mutation facades."""

    repository = DjangoR2TrialMonitoringRepository(using=using)
    return DjangoR2TrialMonitoringRuntime(
        register_trial=UnavailableR2TrialRegisterFacade(),
        register_monitoring=UnavailableR2MonitoringRegisterFacade(),
        get_trial_exact=GetExactR2TrialAssessment(repository),
        get_monitoring_exact=GetExactR2MonitoringAssessment(repository),
        audit=UnavailableR2MonitoringAuditFacade(),
    )


def _validate_registration_command(command: object) -> None:
    try:
        if type(command) is not EvaluateR2MarketStructureTrialCommand:
            raise TypeError("registration command type differs")
        EvaluateR2MarketStructureTrialCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 trial monitoring registration command is malformed"
        ) from error


__all__ = [
    "DjangoR2TrialMonitoringRuntime",
    "UnavailableR2MonitoringAuditFacade",
    "UnavailableR2MonitoringRegisterFacade",
    "UnavailableR2TrialRegisterFacade",
    "build_django_r2_trial_monitoring_runtime",
]
