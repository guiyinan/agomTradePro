"""Fail closed when calculated fee fields exceed the persisted Trade schema."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import (
    FieldDoesNotExist,
)
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_uow import TradeFeeBreakdown
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel

_FEE_STORAGE_ERROR_CODE = "SIMULATED_TRADE_FEE_STORAGE_INVALID"


def require_trade_fee_storage_range(fees: TradeFeeBreakdown) -> None:
    """Validate each calculated fee against its actual persisted DecimalField."""

    if type(fees) is not TradeFeeBreakdown:
        raise SimulatedTradeExecutionBlocked(
            "模拟交易费用超出账本可记录范围",
            code=_FEE_STORAGE_ERROR_CODE,
        )

    components: tuple[tuple[str, Decimal], ...] = (
        ("commission", fees.commission),
        ("transfer_fee", fees.transfer_fee),
        ("stamp_duty", fees.stamp_duty),
        ("slippage", fees.slippage),
    )
    for field_name, value in components:
        try:
            field = SimulatedTradeModel._meta.get_field(field_name)
        except FieldDoesNotExist as error:
            raise SimulatedTradeExecutionBlocked(
                "模拟交易费用超出账本可记录范围",
                code=_FEE_STORAGE_ERROR_CODE,
            ) from error
        if not isinstance(field, models.DecimalField):
            raise SimulatedTradeExecutionBlocked(
                "模拟交易费用超出账本可记录范围",
                code=_FEE_STORAGE_ERROR_CODE,
            )
        try:
            field.run_validators(value)
        except DjangoValidationError as error:
            raise SimulatedTradeExecutionBlocked(
                "模拟交易费用超出账本可记录范围",
                code=_FEE_STORAGE_ERROR_CODE,
            ) from error
