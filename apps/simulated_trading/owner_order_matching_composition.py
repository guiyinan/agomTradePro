"""Compose the explicit owner order matcher without reading mutable sources."""

from __future__ import annotations

from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_reference,
)
from apps.data_center.calendar_workbench_scope_composition import (
    read_calendar_capture_configuration_reference_at,
)
from apps.data_center.qmt_bridge_composition import build_qmt_bridge_service
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.owner_order_matching import OwnerOrderMatchUseCase
from apps.simulated_trading.execution_current_reference_composition import (
    _runtime_environment_from_settings_module,
    _ServerUTCClock,
    build_configured_execution_calendar_reader,
)
from apps.simulated_trading.infrastructure.owner_order_operation_targets import (
    DjangoOwnerOrderOperationTargetReader,
)
from apps.simulated_trading.local_daily_match_composition import (
    build_record_local_daily_match_use_case,
)


def build_owner_order_matching_use_case() -> OwnerOrderMatchUseCase:
    """Build an owner matcher over the durable producer and retained source adapters.

    Configuration, calendar, QMT binding, policy, and market facts remain lazy;
    this factory only binds readers and the default database alias.
    """

    using = "default"
    environment = _runtime_environment_from_settings_module()
    if type(environment) is not str or not environment:
        raise SimulatedTradeExecutionInputError("模拟撮合运行环境不可用")
    clock = _ServerUTCClock()
    calendar_reader = build_configured_execution_calendar_reader(
        runtime_environment=environment,
        read_publication=read_current_exchange_calendar_reference,
        read_configuration=read_calendar_capture_configuration_reference_at,
    )
    qmt_bridge = build_qmt_bridge_service()
    return OwnerOrderMatchUseCase(
        target_reader=DjangoOwnerOrderOperationTargetReader(
            using=using,
            clock=clock,
            read_bindings=qmt_bridge,
        ),
        record_use_case=build_record_local_daily_match_use_case(
            runtime_environment=environment,
            calendar_reader=calendar_reader,
            clock=clock,
            using=using,
        ),
    )


__all__ = ("build_owner_order_matching_use_case",)
