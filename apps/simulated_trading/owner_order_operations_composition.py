"""Compose owner operations from original saved events and existing ledger writers."""

from __future__ import annotations

from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_reference,
)
from apps.data_center.calendar_workbench_scope_composition import (
    read_calendar_capture_configuration_reference_at,
)
from apps.simulated_trading.application.owner_order_operations import OwnerOrderOperationsUseCase
from apps.simulated_trading.execution_current_reference_composition import (
    _runtime_environment_from_settings_module,
    _ServerUTCClock,
    build_configured_execution_calendar_reader,
)
from apps.simulated_trading.execution_settlement_composition import (
    build_cancel_simulated_order_reservation_use_case,
)
from apps.simulated_trading.infrastructure.owner_order_operation_targets import (
    DjangoOwnerOrderOperationTargetReader,
)
from apps.simulated_trading.local_daily_match_composition import (
    build_apply_local_daily_match_with_calendar,
)


def build_owner_order_operations_use_case() -> OwnerOrderOperationsUseCase:
    """Keep existing receipt recovery independent of current configuration reads."""
    environment = _runtime_environment_from_settings_module()
    clock = _ServerUTCClock()
    calendar_reader = build_configured_execution_calendar_reader(
        runtime_environment=environment,
        read_publication=read_current_exchange_calendar_reference,
        read_configuration=read_calendar_capture_configuration_reference_at,
    )
    return OwnerOrderOperationsUseCase(
        target_reader=DjangoOwnerOrderOperationTargetReader(using="default", clock=clock),
        apply_use_case=build_apply_local_daily_match_with_calendar(
            runtime_environment=environment, calendar_reader=calendar_reader, clock=clock
        ),
        cancel_use_case=build_cancel_simulated_order_reservation_use_case(
            using="default", clock=clock
        ),
    )
