"""Capability-isolated Broker owner composition for R8 monitoring receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.broker_execution.application.r8_monitoring_reconciliation_registry import (
    R8BrokerMonitoringRegistryClock,
    R8BrokerMonitoringRegistryUnavailable,
    R8BrokerReconciliationDefinitionProvider,
    R8BrokerReconciliationSourceProvider,
    RegisterR8BrokerMonitoringPeriod,
    RegisterR8BrokerMonitoringPeriodCommand,
)
from apps.broker_execution.infrastructure.r8_monitoring_reconciliation_repository import (
    DjangoR8BrokerMonitoringPeriodReceiptRepository,
    DjangoR8BrokerMonitoringRegistryClock,
    _build_r8_broker_monitoring_period_store,
)


class UnavailableR8BrokerMonitoringRegistrationFacade:
    """Stateless production mutation façade while canonical sources are unwired."""

    __slots__ = ()

    def execute(self, command: RegisterR8BrokerMonitoringPeriodCommand) -> NoReturn:
        """Class-bound validate identity input, then fail before database access."""

        try:
            if type(command) is not RegisterR8BrokerMonitoringPeriodCommand:
                raise TypeError("Broker monitoring command type differs")
            RegisterR8BrokerMonitoringPeriodCommand.__post_init__(command)
            rebuilt = RegisterR8BrokerMonitoringPeriodCommand(
                definition_id=command.definition_id,
                definition_version=command.definition_version,
                source_receipt_id=command.source_receipt_id,
                source_receipt_version=command.source_receipt_version,
                as_of=command.as_of,
            )
            if rebuilt != command:
                raise ValueError("Broker monitoring command is noncanonical")
        except (AttributeError, TypeError, ValueError) as error:
            raise R8BrokerMonitoringRegistryUnavailable(
                "malformed R8 Broker monitoring registration command"
            ) from error
        raise R8BrokerMonitoringRegistryUnavailable(
            "canonical R8 Broker reconciliation definition/source is unavailable"
        )


@dataclass(frozen=True)
class DjangoR8BrokerMonitoringOwnerRuntime:
    """Read-only exact receipt provider plus inert production registration."""

    register_period: UnavailableR8BrokerMonitoringRegistrationFacade
    receipt_provider: DjangoR8BrokerMonitoringPeriodReceiptRepository


@dataclass(frozen=True)
class _DjangoR8BrokerMonitoringRegistrationRuntime:
    """Private source-injected registration runtime for owner tests only."""

    register_period: RegisterR8BrokerMonitoringPeriod
    receipt_provider: DjangoR8BrokerMonitoringPeriodReceiptRepository


def build_django_r8_broker_monitoring_owner_runtime(
    *, using: str = "default"
) -> DjangoR8BrokerMonitoringOwnerRuntime:
    """Build public read-only owner wiring with no source or write capability."""

    return DjangoR8BrokerMonitoringOwnerRuntime(
        register_period=UnavailableR8BrokerMonitoringRegistrationFacade(),
        receipt_provider=DjangoR8BrokerMonitoringPeriodReceiptRepository(using=using),
    )


def build_django_r8_broker_monitoring_receipt_provider(
    *, using: str = "default"
) -> DjangoR8BrokerMonitoringPeriodReceiptRepository:
    """Expose the Broker Application-bound exact read provider only."""

    return build_django_r8_broker_monitoring_owner_runtime(using=using).receipt_provider


def _build_django_r8_broker_monitoring_test_runtime(
    *,
    definition_provider: R8BrokerReconciliationDefinitionProvider,
    source_provider: R8BrokerReconciliationSourceProvider,
    clock: R8BrokerMonitoringRegistryClock | None = None,
    using: str = "default",
) -> _DjangoR8BrokerMonitoringRegistrationRuntime:
    """Wire private source-backed registration without exporting its store."""

    trusted_clock = clock or DjangoR8BrokerMonitoringRegistryClock(using=using)
    return _DjangoR8BrokerMonitoringRegistrationRuntime(
        register_period=RegisterR8BrokerMonitoringPeriod(
            definition_provider=definition_provider,
            source_provider=source_provider,
            store=_build_r8_broker_monitoring_period_store(using=using),
            clock=trusted_clock,
        ),
        receipt_provider=DjangoR8BrokerMonitoringPeriodReceiptRepository(using=using),
    )


__all__ = [
    "DjangoR8BrokerMonitoringOwnerRuntime",
    "UnavailableR8BrokerMonitoringRegistrationFacade",
    "build_django_r8_broker_monitoring_owner_runtime",
    "build_django_r8_broker_monitoring_receipt_provider",
]
