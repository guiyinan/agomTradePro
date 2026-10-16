"""Explicit composition for the settlement-bound simulated-ledger use cases."""

from __future__ import annotations

from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    PublishedExecutionCalendarReader,
    ReleaseDueSimulatedSettlementsUseCase,
    SettlementV3RuleReader,
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)


def build_execute_settlement_bound_simulated_trade_use_case(
    *,
    using: str,
    rule_reader: SettlementV3RuleReader,
    calendar_reader: PublishedExecutionCalendarReader,
    clock: SimulatedTradeExecutionClock,
) -> ExecuteSettlementBoundSimulatedTradeUseCase:
    """Compose one trade use case with explicit source ports and DB alias.

    No rule, calendar, or clock provider is selected here. Callers must inject
    adapters that enforce their own source and database scope. The ledger and
    FeeConfig reads share one repository instance bound to ``using``.
    """

    repository = DjangoSimulatedTradeExecutionRepository(using=using)
    return ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=rule_reader,
        calendar_reader=calendar_reader,
        fee_policy_reader=repository,
        repository=repository,
        clock=clock,
    )


def build_release_due_simulated_settlements_use_case(
    *,
    using: str,
    calendar_reader: PublishedExecutionCalendarReader,
    clock: SimulatedTradeExecutionClock,
) -> ReleaseDueSimulatedSettlementsUseCase:
    """Compose explicit settlement release ports and one ledger DB alias.

    No calendar adapter or clock is selected implicitly. The returned use case
    blocks when the injected calendar reader cannot provide valid evidence.
    """

    repository = DjangoSimulatedTradeExecutionRepository(using=using)
    return ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=calendar_reader,
        repository=repository,
        clock=clock,
    )
