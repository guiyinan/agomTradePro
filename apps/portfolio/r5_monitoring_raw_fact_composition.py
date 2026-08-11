"""Capability-isolated composition for Portfolio R5 monitoring raw facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.portfolio.application.r5_monitoring_raw_fact_registry import (
    PortfolioR5MonitoringRawFactClock,
    PortfolioR5MonitoringRawFactDefinitionProvider,
    PortfolioR5MonitoringRawFactSourceProvider,
    PortfolioR5MonitoringRawFactUnavailable,
    RegisterPortfolioR5MonitoringRawFact,
    RegisterPortfolioR5MonitoringRawFactCommand,
)
from apps.portfolio.infrastructure.r5_monitoring_raw_fact_repository import (
    DjangoPortfolioR5MonitoringRawFactClock,
    DjangoPortfolioR5MonitoringRawFactRepository,
    _build_portfolio_r5_monitoring_raw_fact_store,
)


class UnavailablePortfolioR5MonitoringRawFactRegistrationFacade:
    """Validate identity-only input then deny public Portfolio mutation."""

    __slots__ = ()

    def execute(self, command: RegisterPortfolioR5MonitoringRawFactCommand) -> NoReturn:
        """Fail without retaining a definition, source, clock, or store."""

        try:
            if type(command) is not RegisterPortfolioR5MonitoringRawFactCommand:
                raise TypeError("Portfolio R5 monitoring command type differs")
            RegisterPortfolioR5MonitoringRawFactCommand.__post_init__(command)
        except Exception as error:
            raise PortfolioR5MonitoringRawFactUnavailable(
                "malformed Portfolio R5 monitoring raw-fact command"
            ) from error
        raise PortfolioR5MonitoringRawFactUnavailable(
            "canonical Portfolio R5 monitoring definition/source is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoPortfolioR5MonitoringRawFactRuntime:
    """Public exact reads plus an inert registration surface."""

    register: UnavailablePortfolioR5MonitoringRawFactRegistrationFacade
    repository: DjangoPortfolioR5MonitoringRawFactRepository


@dataclass(frozen=True, slots=True)
class _DjangoPortfolioR5MonitoringRawFactRegistrationRuntime:
    """Private source-injected runtime proving owner contracts in tests."""

    register: RegisterPortfolioR5MonitoringRawFact
    repository: DjangoPortfolioR5MonitoringRawFactRepository


def build_django_portfolio_r5_monitoring_raw_fact_runtime(
    *,
    using: str = "default",
) -> DjangoPortfolioR5MonitoringRawFactRuntime:
    """Expose exact PIT reads while retaining no public write authority."""

    return DjangoPortfolioR5MonitoringRawFactRuntime(
        register=UnavailablePortfolioR5MonitoringRawFactRegistrationFacade(),
        repository=DjangoPortfolioR5MonitoringRawFactRepository(using=using),
    )


def _build_django_portfolio_r5_monitoring_raw_fact_registration_runtime(
    *,
    definition_provider: PortfolioR5MonitoringRawFactDefinitionProvider,
    source_provider: PortfolioR5MonitoringRawFactSourceProvider,
    clock: PortfolioR5MonitoringRawFactClock | None = None,
    using: str = "default",
) -> _DjangoPortfolioR5MonitoringRawFactRegistrationRuntime:
    """Wire private source-backed registration without exporting its store."""

    trusted_clock = clock or DjangoPortfolioR5MonitoringRawFactClock(using=using)
    return _DjangoPortfolioR5MonitoringRawFactRegistrationRuntime(
        register=RegisterPortfolioR5MonitoringRawFact(
            definition_provider=definition_provider,
            source_provider=source_provider,
            store=_build_portfolio_r5_monitoring_raw_fact_store(
                using=using,
                clock=trusted_clock,
            ),
            clock=trusted_clock,
        ),
        repository=DjangoPortfolioR5MonitoringRawFactRepository(
            using=using,
            clock=trusted_clock,
        ),
    )


__all__ = [
    "DjangoPortfolioR5MonitoringRawFactRuntime",
    "UnavailablePortfolioR5MonitoringRawFactRegistrationFacade",
    "build_django_portfolio_r5_monitoring_raw_fact_runtime",
]
