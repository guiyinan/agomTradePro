"""Compose explicit simulated fee policies and settlement-bound ledger use cases."""

from __future__ import annotations

from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    ExecutionInstrumentIdentityReader,
    PublishedExecutionCalendarReader,
    ReleaseDueSimulatedSettlementsUseCase,
    SettlementV3RuleReader,
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.application.fee_policy_v2 import (
    CreateFeePolicyVersionUseCase,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)


def build_execute_settlement_bound_simulated_trade_use_case(
    *,
    using: str,
    rule_reader: SettlementV3RuleReader,
    identity_reader: ExecutionInstrumentIdentityReader,
    calendar_reader: PublishedExecutionCalendarReader,
    clock: SimulatedTradeExecutionClock,
) -> ExecuteSettlementBoundSimulatedTradeUseCase:
    """Compose one trade use case with explicit source ports and DB alias.

    No rule, identity, calendar, or clock provider is selected here. Callers
    must inject adapters that enforce their own source and database scope; the
    identity adapter must supply the exact source exchange without inference.
    The ledger and FeeConfig reads share one repository instance bound to
    ``using``.
    """

    repository = DjangoSimulatedTradeExecutionRepository(using=using)
    return ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=rule_reader,
        identity_reader=identity_reader,
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


def build_create_fee_policy_version_use_case(
    *,
    using: str,
) -> CreateFeePolicyVersionUseCase:
    """Compose the operator use case with one explicit FeeConfig database alias."""

    repository = DjangoFeePolicyV2Repository(using=using)
    return CreateFeePolicyVersionUseCase(repository=repository)
