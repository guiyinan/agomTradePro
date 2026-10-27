"""Compatibility facade for simulated trade writes and guarded reads."""

from datetime import date as date
from datetime import datetime as datetime
from typing import Any

from django.db import DEFAULT_DB_ALIAS as DEFAULT_DB_ALIAS
from django.db import transaction as transaction
from django.utils import timezone as timezone

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionAccountHistoryProjection as FeeCorrectionAccountHistoryProjection,
)
from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionHistoryRepositoryProtocol as FeeCorrectionHistoryRepositoryProtocol,
)
from apps.simulated_trading.application.ports import (
    AdminDashboardRealizedPnlSummary as AdminDashboardRealizedPnlSummary,
)
from apps.simulated_trading.domain.entities import FeeConfig as FeeConfig
from apps.simulated_trading.domain.entities import Position as Position
from apps.simulated_trading.domain.entities import SimulatedAccount as SimulatedAccount
from apps.simulated_trading.domain.entities import SimulatedTrade as SimulatedTrade
from apps.simulated_trading.domain.rules import TradingConstraintRule as TradingConstraintRule
from apps.simulated_trading.infrastructure.models import FeeConfigModel as FeeConfigModel
from apps.simulated_trading.infrastructure.models import PositionModel as PositionModel
from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel as SimulatedAccountModel,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel as SimulatedTradeModel
from core.exceptions import BusinessLogicError

from .account_mapper import SimulatedAccountMapper as SimulatedAccountMapper
from .fee_config_repository import FeeConfigMapper as FeeConfigMapper
from .fee_correction_runtime import (
    build_django_fee_correction_repository as build_django_fee_correction_repository,
)
from .order_reservation_fill_account_history import (
    validate_account_v4_fill_history as validate_account_v4_fill_history,
)
from .order_reservation_fill_trade_read_guard import (
    validate_v4_trade_history as validate_v4_trade_history,
)
from .order_reservation_guard import (
    lock_active_order_reservations as lock_active_order_reservations,
)
from .position_mapper import PositionMapper as PositionMapper
from .position_repository_guard import (
    require_no_retained_v4_fill_history as require_no_retained_v4_fill_history,
)
from .repository_helpers import _require_saved_id as _require_saved_id
from .trade_history_read_repository import DjangoTradeHistoryReadRepository
from .trade_history_repository import DjangoTradeHistoryRepository as DjangoTradeHistoryRepository
from .trade_ledger_write_repository import DjangoTradeLedgerWriteRepository
from .trade_mapper import SimulatedTradeMapper as SimulatedTradeMapper
from .trade_summary_repository import DjangoTradeSummaryRepository as DjangoTradeSummaryRepository


class DjangoTradeRepository(DjangoTradeHistoryReadRepository):
    """Preserve the public trade repository over focused read/write owners."""

    def __init__(
        self,
        *,
        fee_correction_history: FeeCorrectionHistoryRepositoryProtocol | None = None,
    ) -> None:
        """Configure the existing correction-aware factory and atomic writer."""

        history = (
            fee_correction_history
            if fee_correction_history is not None
            else build_django_fee_correction_repository()
        )
        super().__init__(fee_correction_history=history)
        self._ledger_writer = DjangoTradeLedgerWriteRepository()

    def create_trade_record(self, **payload: Any) -> SimulatedTradeModel:
        """Reject legacy direct inserts that bypass the account-first ledger lock."""

        del payload
        raise BusinessLogicError(
            "模拟交易必须通过账户锁定的原子结算入口写入",
            code="SIMULATED_TRADE_ATOMIC_WRITE_REQUIRED",
        )

    def save(self, trade: SimulatedTrade) -> int:
        """Reject naked legacy inserts and require account-first atomic settlement."""

        del trade
        raise BusinessLogicError(
            "模拟交易必须通过账户锁定的原子结算入口写入",
            code="SIMULATED_TRADE_ATOMIC_WRITE_REQUIRED",
        )

    def execute_legacy_trade_atomically(
        self,
        *,
        expected_account: SimulatedAccount,
        expected_position: Position | None,
        fee_config: FeeConfig,
        trade: SimulatedTrade,
        resulting_position: Position | None,
        resulting_account: SimulatedAccount,
    ) -> SimulatedTrade:
        """Delegate the complete legacy ledger write to its atomic owner."""

        return self._ledger_writer.execute_legacy_trade_atomically(
            expected_account=expected_account,
            expected_position=expected_position,
            fee_config=fee_config,
            trade=trade,
            resulting_position=resulting_position,
            resulting_account=resulting_account,
        )

    def sum_realized_pnl_for_closed_trades(self) -> AdminDashboardRealizedPnlSummary:
        """Return the closed-trade summary from its focused read owner."""

        return DjangoTradeSummaryRepository(
            fee_correction_history=self._fee_correction_history
        ).sum_realized_pnl_for_closed_trades()

    def has_incomplete_closed_trade_costs(
        self,
        account_id: int | None = None,
        *,
        using: str = DEFAULT_DB_ALIAS,
    ) -> bool:
        """Return whether the focused summary owner finds incomplete costs."""

        return DjangoTradeSummaryRepository().has_incomplete_closed_trade_costs(
            account_id,
            using=using,
        )

    def get_trade_model_summary_for_account(
        self,
        account_id: int,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return the account trade-page summary from its focused read owner."""

        return DjangoTradeSummaryRepository(
            fee_correction_history=self._fee_correction_history
        ).get_trade_model_summary_for_account(
            account_id,
            limit,
        )

    def get_owned_trade_by_id(
        self,
        *,
        trade_id: int,
        account_id: int,
        user_id: int,
    ) -> SimulatedTrade | None:
        """Preserve the registered owner marker and delegate scoped history reads."""

        return super().get_owned_trade_by_id(
            trade_id=trade_id,
            account_id=account_id,
            user_id=user_id,
        )
