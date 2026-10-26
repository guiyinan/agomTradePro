"""Correction-aware, guarded trade history and count reads."""

from datetime import date, datetime

from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionAccountHistoryProjection,
    FeeCorrectionHistoryRepositoryProtocol,
)
from apps.simulated_trading.domain.entities import SimulatedTrade
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from apps.simulated_trading.infrastructure.order_reservation_fill_trade_read_guard import (
    validate_v4_trade_history,
)

from .trade_history_repository import DjangoTradeHistoryRepository


class DjangoTradeHistoryReadRepository:
    """Own guarded correction-aware trade history and count queries."""

    def __init__(
        self,
        *,
        fee_correction_history: FeeCorrectionHistoryRepositoryProtocol,
    ) -> None:
        """Use the same correction history injected into the compatibility facade."""

        self._fee_correction_history = fee_correction_history

    def _history_projection(
        self,
        *,
        account_id: int,
        as_of: datetime,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FeeCorrectionAccountHistoryProjection:
        """Read the complete account history before applying output date filters."""

        return self._fee_correction_history.get_account_history(
            account_id=account_id,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
        )

    def get_account_history(
        self,
        *,
        account_id: int,
        as_of: datetime,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FeeCorrectionAccountHistoryProjection:
        """Return a correction-aware projection after validating full V4 history."""

        validate_v4_trade_history(
            SimulatedTradeModel._default_manager.filter(account_id=account_id)
        )
        return self._history_projection(
            account_id=account_id,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
        )

    def get_by_account(
        self,
        account_id: int,
        *,
        as_of: datetime | None = None,
    ) -> list[SimulatedTrade]:
        """获取账户的所有交易记录"""
        projection = self.get_account_history(
            account_id=account_id,
            as_of=as_of if as_of is not None else timezone.now(),
        )
        return list(reversed(projection.trades))

    def count_trade_models(self) -> int:
        """Return the total number of trade ORM rows."""

        validate_v4_trade_history(SimulatedTradeModel._default_manager.all())
        return int(SimulatedTradeModel._default_manager.count())

    def summarize_trade_models_for_date(self, execution_date: date) -> dict[str, int]:
        """Return buy/sell counts for one execution date."""

        queryset = SimulatedTradeModel._default_manager.filter(execution_date=execution_date)
        validate_v4_trade_history(queryset)
        return {
            "buy_count": int(queryset.filter(action="buy").count()),
            "sell_count": int(queryset.filter(action="sell").count()),
        }

    def list_trade_models_for_account(
        self,
        account_id: int,
        limit: int | None = None,
    ) -> list[SimulatedTrade]:
        """Return correction-aware trade entities for the existing account page."""

        if limit is not None and limit < 0:
            raise ValueError("Negative indexing is not supported.")
        validate_v4_trade_history(
            SimulatedTradeModel._default_manager.filter(account_id=account_id)
        )
        projection = self.get_account_history(
            account_id=account_id,
            as_of=timezone.now(),
        )
        rows = list(reversed(projection.trades))
        return rows if limit is None else rows[:limit]

    def get_admin_read_only_trade_ids(self, trade_ids: tuple[int, ...]) -> frozenset[int]:
        """Return selected Trades carrying a V4 marker or immutable fill receipt."""

        return DjangoTradeHistoryRepository().get_admin_read_only_trade_ids(trade_ids)

    def get_owned_trade_by_id(
        self,
        *,
        trade_id: int,
        account_id: int,
        user_id: int,
    ) -> SimulatedTrade | None:
        """Return one trade only when its account belongs to the exact user."""

        original = DjangoTradeHistoryRepository().get_owned_trade_by_id(
            trade_id=trade_id,
            account_id=account_id,
            user_id=user_id,
        )
        if original is None:
            return None
        projection = self.get_account_history(
            account_id=account_id,
            as_of=timezone.now(),
        )
        return next(
            (trade for trade in projection.trades if trade.trade_id == trade_id),
            None,
        )

    def get_by_date_range(
        self,
        account_id: int,
        start_date: date,
        end_date: date,
        *,
        as_of: datetime | None = None,
    ) -> list[SimulatedTrade]:
        """获取日期范围内的交易记录。"""

        projection = self.get_account_history(
            account_id=account_id,
            as_of=as_of if as_of is not None else timezone.now(),
            start_date=start_date,
            end_date=end_date,
        )
        return list(reversed(projection.trades))

    def get_by_asset(
        self,
        account_id: int,
        asset_code: str,
        *,
        as_of: datetime | None = None,
    ) -> list[SimulatedTrade]:
        """获取特定资产的所有交易记录。"""

        projection = self.get_account_history(
            account_id=account_id,
            as_of=as_of if as_of is not None else timezone.now(),
        )
        return [trade for trade in reversed(projection.trades) if trade.asset_code == asset_code]

    def count_by_execution_date(self, account_id: int, execution_date: date) -> int:
        """按执行日期统计交易数。"""

        validate_v4_trade_history(
            SimulatedTradeModel._default_manager.filter(
                account_id=account_id,
                execution_date=execution_date,
            )
        )
        return int(
            SimulatedTradeModel._default_manager.filter(
                account_id=account_id,
                execution_date=execution_date,
            ).count()
        )
