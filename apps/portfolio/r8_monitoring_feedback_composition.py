"""Capability-isolated composition for Portfolio R8 raw feedback receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.portfolio.application.r8_monitoring_feedback_registry import (
    PortfolioR8MonitoringFeedbackDefinitionProvider,
    PortfolioR8MonitoringFeedbackRegistryClock,
    PortfolioR8MonitoringFeedbackRegistryUnavailable,
    PortfolioR8MonitoringFeedbackSourceProvider,
    RegisterPortfolioR8MonitoringFeedback,
    RegisterPortfolioR8MonitoringFeedbackCommand,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationUnitOfWork,
)
from apps.portfolio.infrastructure.r8_monitoring_feedback_repository import (
    DjangoPortfolioR8MonitoringFeedbackClock,
    DjangoPortfolioR8MonitoringFeedbackRepository,
    _build_portfolio_r8_monitoring_feedback_store,
)
from apps.portfolio.infrastructure.r8_portfolio_monitoring_feedback_adapter import (
    DjangoPortfolioR8MonitoringFeedbackAdapter,
)


class UnavailablePortfolioR8MonitoringFeedbackRegistrationFacade:
    """Stateless production facade that cannot retain raw receipt write authority."""

    __slots__ = ()

    def execute(self, command: RegisterPortfolioR8MonitoringFeedbackCommand) -> NoReturn:
        """Validate an exact identity command and stop before database access."""

        try:
            if type(command) is not RegisterPortfolioR8MonitoringFeedbackCommand:
                raise TypeError("Portfolio R8 feedback command type differs")
            RegisterPortfolioR8MonitoringFeedbackCommand.__post_init__(command)
            rebuilt = RegisterPortfolioR8MonitoringFeedbackCommand(
                feedback_id=command.feedback_id,
                feedback_version=command.feedback_version,
            )
            if rebuilt != command:
                raise ValueError("Portfolio R8 feedback command differs after replay")
        except (AttributeError, TypeError, ValueError) as error:
            raise PortfolioR8MonitoringFeedbackRegistryUnavailable(
                "malformed Portfolio R8 monitoring feedback registration command"
            ) from error
        raise PortfolioR8MonitoringFeedbackRegistryUnavailable(
            "canonical Portfolio R8 monitoring feedback definition/source is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoPortfolioR8MonitoringFeedbackRuntime:
    """Public exact receipt reads and projections plus inert registration."""

    register: UnavailablePortfolioR8MonitoringFeedbackRegistrationFacade
    feedback_provider: DjangoPortfolioR8MonitoringFeedbackRepository
    monitoring_feedback_provider: DjangoPortfolioR8MonitoringFeedbackAdapter


@dataclass(frozen=True, slots=True)
class _DjangoPortfolioR8MonitoringFeedbackRegistrationRuntime:
    """Private source-backed registration graph used by owner component tests."""

    register: RegisterPortfolioR8MonitoringFeedback
    feedback_provider: DjangoPortfolioR8MonitoringFeedbackRepository
    monitoring_feedback_provider: DjangoPortfolioR8MonitoringFeedbackAdapter


def build_django_portfolio_r8_monitoring_feedback_runtime(
    *, using: str = "default"
) -> DjangoPortfolioR8MonitoringFeedbackRuntime:
    """Expose exact reads without a definition, source, clock, UoW, or store."""

    return DjangoPortfolioR8MonitoringFeedbackRuntime(
        register=UnavailablePortfolioR8MonitoringFeedbackRegistrationFacade(),
        feedback_provider=DjangoPortfolioR8MonitoringFeedbackRepository(using=using),
        monitoring_feedback_provider=DjangoPortfolioR8MonitoringFeedbackAdapter(using=using),
    )


def _build_django_portfolio_r8_monitoring_feedback_registration_runtime(
    *,
    definition_provider: PortfolioR8MonitoringFeedbackDefinitionProvider,
    source_provider: PortfolioR8MonitoringFeedbackSourceProvider,
    clock: PortfolioR8MonitoringFeedbackRegistryClock | None = None,
    using: str = "default",
    unit_of_work: DjangoGovernedOptimizationUnitOfWork | None = None,
) -> _DjangoPortfolioR8MonitoringFeedbackRegistrationRuntime:
    """Wire the private raw owner graph without exporting its store or claim token."""

    owner_uow = unit_of_work or DjangoGovernedOptimizationUnitOfWork(using=using)
    trusted_clock = clock or DjangoPortfolioR8MonitoringFeedbackClock(
        unit_of_work_key=owner_uow.unit_of_work_key
    )
    return _DjangoPortfolioR8MonitoringFeedbackRegistrationRuntime(
        register=RegisterPortfolioR8MonitoringFeedback(
            definition_provider=definition_provider,
            source_provider=source_provider,
            store=_build_portfolio_r8_monitoring_feedback_store(
                unit_of_work=owner_uow,
                clock=trusted_clock,
            ),
            clock=trusted_clock,
        ),
        feedback_provider=DjangoPortfolioR8MonitoringFeedbackRepository(using=using),
        monitoring_feedback_provider=DjangoPortfolioR8MonitoringFeedbackAdapter(using=using),
    )


__all__ = [
    "DjangoPortfolioR8MonitoringFeedbackRuntime",
    "UnavailablePortfolioR8MonitoringFeedbackRegistrationFacade",
    "build_django_portfolio_r8_monitoring_feedback_runtime",
]
