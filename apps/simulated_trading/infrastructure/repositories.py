"""Compatibility exports for simulated-trading repositories."""

from __future__ import annotations

from .account_repository import DjangoSimulatedAccountRepository as DjangoSimulatedAccountRepository
from .account_repository import SimulatedAccountMapper as SimulatedAccountMapper
from .daily_net_value_repository import (
    DjangoDailyNetValueRepository as DjangoDailyNetValueRepository,
)
from .fee_config_repository import DjangoFeeConfigRepository as DjangoFeeConfigRepository
from .fee_config_repository import FeeConfigMapper as FeeConfigMapper
from .inspection_repository import DjangoInspectionRepository as DjangoInspectionRepository
from .position_repository import (
    DjangoPositionMutationRepository as DjangoPositionMutationRepository,
)
from .position_repository import DjangoPositionRepository as DjangoPositionRepository
from .position_repository import PositionMapper as PositionMapper
from .trade_repository import DjangoTradeRepository as DjangoTradeRepository

__all__ = [
    "DjangoSimulatedAccountRepository",
    "SimulatedAccountMapper",
    "DjangoDailyNetValueRepository",
    "DjangoFeeConfigRepository",
    "FeeConfigMapper",
    "DjangoInspectionRepository",
    "DjangoPositionMutationRepository",
    "DjangoPositionRepository",
    "PositionMapper",
    "DjangoTradeRepository",
]
