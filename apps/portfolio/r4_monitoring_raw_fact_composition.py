"""Capability-isolated composition for Portfolio R4 monitoring raw facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.portfolio.application.r4_monitoring_raw_fact_receipt import (
    PortfolioR4MonitoringRawFactClock,
    PortfolioR4MonitoringRawFactDefinitionProvider,
    PortfolioR4MonitoringRawFactSourceProvider,
    PortfolioR4MonitoringRawFactUnavailable,
    RegisterPortfolioR4MonitoringRawFact,
    RegisterPortfolioR4MonitoringRawFactCommand,
)
from apps.portfolio.infrastructure.r4_monitoring_raw_fact_repository import (
    DjangoPortfolioR4MonitoringRawFactClock,
    DjangoPortfolioR4MonitoringRawFactRepository,
    _build_portfolio_r4_monitoring_raw_fact_store,
)


class UnavailablePortfolioR4MonitoringRawFactRegistrationFacade:
    """Deny public writes until a canonical Portfolio raw source exists."""

    __slots__ = ()

    def execute(self, command: RegisterPortfolioR4MonitoringRawFactCommand) -> NoReturn:
        """Validate the ID-only command and fail without a write."""

        try:
            if type(command) is not RegisterPortfolioR4MonitoringRawFactCommand:
                raise TypeError("raw-fact command type is invalid")
            RegisterPortfolioR4MonitoringRawFactCommand.__post_init__(command)
        except Exception as error:
            raise PortfolioR4MonitoringRawFactUnavailable(
                "malformed raw-fact registration command"
            ) from error
        raise PortfolioR4MonitoringRawFactUnavailable(
            "canonical raw-fact definition/source provider is unavailable"
        )


@dataclass(frozen=True)
class DjangoPortfolioR4MonitoringRawFactRuntime:
    """Public exact reads plus a deliberately inert owner registration surface."""

    register: UnavailablePortfolioR4MonitoringRawFactRegistrationFacade
    repository: DjangoPortfolioR4MonitoringRawFactRepository


@dataclass(frozen=True)
class _DjangoPortfolioR4MonitoringRawFactRegistrationRuntime:
    """Private source-injected runtime used only by owner contract tests."""

    register: RegisterPortfolioR4MonitoringRawFact
    repository: DjangoPortfolioR4MonitoringRawFactRepository


def build_django_portfolio_r4_monitoring_raw_fact_runtime(
    *, using: str = "default"
) -> DjangoPortfolioR4MonitoringRawFactRuntime:
    """Expose canonical exact reads while keeping public mutation inert."""

    return DjangoPortfolioR4MonitoringRawFactRuntime(
        register=UnavailablePortfolioR4MonitoringRawFactRegistrationFacade(),
        repository=DjangoPortfolioR4MonitoringRawFactRepository(using=using),
    )


def _build_django_portfolio_r4_monitoring_raw_fact_registration_runtime(
    *,
    definition_provider: PortfolioR4MonitoringRawFactDefinitionProvider,
    source_provider: PortfolioR4MonitoringRawFactSourceProvider,
    clock: PortfolioR4MonitoringRawFactClock | None = None,
    using: str = "default",
) -> _DjangoPortfolioR4MonitoringRawFactRegistrationRuntime:
    """Wire private source-backed registration without exporting its store."""

    trusted_clock = clock or DjangoPortfolioR4MonitoringRawFactClock(using=using)
    return _DjangoPortfolioR4MonitoringRawFactRegistrationRuntime(
        register=RegisterPortfolioR4MonitoringRawFact(
            definition_provider=definition_provider,
            source_provider=source_provider,
            store=_build_portfolio_r4_monitoring_raw_fact_store(using=using),
            clock=trusted_clock,
        ),
        repository=DjangoPortfolioR4MonitoringRawFactRepository(using=using),
    )


__all__ = [
    "DjangoPortfolioR4MonitoringRawFactRuntime",
    "UnavailablePortfolioR4MonitoringRawFactRegistrationFacade",
    "build_django_portfolio_r4_monitoring_raw_fact_runtime",
]
