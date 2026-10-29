"""Compose opt-in local daily simulation from retained public source reads."""

from __future__ import annotations

from apps.data_center.application.public_published_queries import get_published_price_bar_source
from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_reference,
)
from apps.data_center.instrument_reference_snapshot_composition import (
    read_instrument_reference_snapshot,
)
from apps.data_center.price_limit_publication_operations_composition import (
    read_published_price_limit_reference,
)
from apps.data_center.qmt_bridge_composition import read_qmt_daily_status
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchDecisionDiscovery,
    LocalDailyMatchQualificationReader,
    RecordLocalDailyMatchUseCase,
)
from apps.simulated_trading.execution_settlement_composition import (
    build_current_published_execution_calendar_reader,
)
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    DjangoLocalDailyMatchRepository,
)
from apps.simulated_trading.infrastructure.local_daily_match_source_reader import (
    RetainedLocalDailyMatchSourceReader,
)
from apps.simulated_trading.local_daily_simulation_policy_composition import (
    ConfiguredLocalDailySimulationPolicyReader,
)


def build_local_daily_match_source_reader(
    *, runtime_environment: str, calendar_dataset_key: str
) -> LocalDailyMatchQualificationReader:
    """Bind explicit runtime/calendar scope without writing configuration or fetching data."""
    return RetainedLocalDailyMatchSourceReader(
        policy_reader=ConfiguredLocalDailySimulationPolicyReader(
            runtime_environment=runtime_environment,
        ),
        calendar_reader=build_current_published_execution_calendar_reader(
            dataset_key=calendar_dataset_key,
            runtime_environment=runtime_environment,
            read_publication=read_current_exchange_calendar_reference,
        ),
        get_price_source=get_published_price_bar_source,
        read_instrument_snapshot=read_instrument_reference_snapshot,
        read_qmt_status=read_qmt_daily_status,
        read_limit_reference=read_published_price_limit_reference,
    )


def build_record_local_daily_match_use_case(
    *,
    runtime_environment: str,
    calendar_dataset_key: str,
    clock: SimulatedTradeExecutionClock,
    using: str = "default",
) -> RecordLocalDailyMatchUseCase:
    """Build an explicit producer that commits source decisions without ledger effects."""
    if using != "default":
        raise SimulatedTradeExecutionInputError(
            "公开市场来源与模拟撮合必须使用同一默认数据库",
            code="LOCAL_DAILY_MATCH_ALIAS_MISMATCH",
        )
    return RecordLocalDailyMatchUseCase(
        repository=DjangoLocalDailyMatchRepository(using=using),
        qualification_reader=build_local_daily_match_source_reader(
            runtime_environment=runtime_environment,
            calendar_dataset_key=calendar_dataset_key,
        ),
        clock=clock,
    )


def build_local_daily_match_event_reader(
    *, using: str = "default"
) -> LocalDailyMatchDecisionDiscovery:
    """Build a read-only original-event adapter; construction cannot generate a fill."""
    return DjangoLocalDailyMatchEventReader(using=using)
