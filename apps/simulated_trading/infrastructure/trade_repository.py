"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""

from datetime import date, datetime
from typing import Any

from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionAccountHistoryProjection,
    FeeCorrectionHistoryRepositoryProtocol,
)
from apps.simulated_trading.application.ports import (
    AdminDashboardRealizedPnlSummary,
)
from apps.simulated_trading.domain.entities import (
    FeeConfig,
    Position,
    SimulatedAccount,
    SimulatedTrade,
)
from apps.simulated_trading.domain.rules import TradingConstraintRule
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from core.exceptions import BusinessLogicError

from .account_mapper import SimulatedAccountMapper
from .fee_config_repository import FeeConfigMapper
from .fee_correction_runtime import build_django_fee_correction_repository
from .order_reservation_fill_account_history import validate_account_v4_fill_history
from .order_reservation_fill_trade_read_guard import validate_v4_trade_history
from .order_reservation_guard import (
    lock_active_order_reservations,
)
from .position_mapper import PositionMapper
from .position_repository_guard import require_no_retained_v4_fill_history
from .repository_helpers import _require_saved_id
from .trade_history_repository import DjangoTradeHistoryRepository
from .trade_mapper import SimulatedTradeMapper
from .trade_summary_repository import DjangoTradeSummaryRepository


class DjangoTradeRepository:
    """交易记录Repository实现"""

    def __init__(
        self,
        *,
        fee_correction_history: FeeCorrectionHistoryRepositoryProtocol | None = None,
    ) -> None:
        """Configure the correction-aware read port without enabling writes."""

        self._fee_correction_history = (
            fee_correction_history
            if fee_correction_history is not None
            else build_django_fee_correction_repository()
        )

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
        """Commit one compatibility BUY/SELL under the account-first ledger lock.

        The caller computes the business result from fresh repository reads.
        This method re-reads and compares every input under the account lock,
        locks order reservations and retained V4 history, then revalidates the
        fee configuration and order rule before the first insert. A concurrent
        correction or trade causes a retryable stale-state error, never a
        partial Trade/Position/Account write.
        """

        account_id = expected_account.account_id
        if (
            type(expected_account) is not SimulatedAccount
            or type(account_id) is not int
            or account_id <= 0
            or type(fee_config) is not FeeConfig
            or type(trade) is not SimulatedTrade
            or trade.account_id != account_id
            or trade.trade_id != 0
            or trade.status.value != "executed"
            or (expected_position is not None and type(expected_position) is not Position)
            or (resulting_position is not None and type(resulting_position) is not Position)
            or type(resulting_account) is not SimulatedAccount
            or resulting_account.account_id != account_id
            or trade.asset_code == ""
            or (expected_position is not None and expected_position.asset_code != trade.asset_code)
            or (
                resulting_position is not None and resulting_position.asset_code != trade.asset_code
            )
        ):
            raise BusinessLogicError(
                "模拟交易兼容写入范围无效",
                code="SIMULATED_TRADE_WRITE_SCOPE_INVALID",
            )

        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            account_model = (
                SimulatedAccountModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(pk=account_id, account_type="simulated", is_active=True)
                .first()
            )
            if account_model is None:
                raise BusinessLogicError(
                    "模拟账户不存在或未激活", code="SIMULATED_ACCOUNT_UNAVAILABLE"
                )
            current_account = SimulatedAccountMapper.to_entity(account_model)
            if current_account != expected_account:
                raise BusinessLogicError(
                    "账户状态已变化，请重试",
                    code="POSITION_CHANGED_RETRY_REQUIRED",
                )
            if (
                account_model.cash_known is not True
                or account_model.cash_reconciliation_status != "simulated_ledger"
            ):
                raise BusinessLogicError(
                    "模拟账户现金账本未核实",
                    code="ACCOUNT_CASH_UNKNOWN",
                )

            active_rows = lock_active_order_reservations(
                account_id=account_id,
                using=DEFAULT_DB_ALIAS,
            )
            if active_rows:
                raise BusinessLogicError(
                    "账户存在未完成订单预留，拒绝兼容交易写入",
                    code="ORDER_RESERVATION_ACTIVE",
                )
            validate_account_v4_fill_history(
                account=account_model,
                intent=None,
                using=DEFAULT_DB_ALIAS,
            )
            require_no_retained_v4_fill_history(
                account_id=account_id,
                asset_code=trade.asset_code,
                using=DEFAULT_DB_ALIAS,
            )

            locked_config = (
                FeeConfigModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(pk=fee_config.config_id, is_active=True, is_default=True)
                .first()
            )
            if locked_config is None or FeeConfigMapper.to_entity(locked_config) != fee_config:
                raise BusinessLogicError(
                    "默认费用配置已变化，请重试",
                    code="POSITION_CHANGED_RETRY_REQUIRED",
                )

            position_model = (
                PositionModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(account_id=account_id, asset_code=trade.asset_code)
                .first()
            )
            current_position = (
                PositionMapper.to_entity(position_model) if position_model is not None else None
            )
            if current_position != expected_position:
                raise BusinessLogicError(
                    "持仓状态已变化，请重试",
                    code="POSITION_CHANGED_RETRY_REQUIRED",
                )
            if trade.action.value == "buy":
                current_position_value = (
                    current_position.quantity * trade.price if current_position is not None else 0.0
                )
                is_valid, reason = TradingConstraintRule.validate_buy_order(
                    current_account,
                    trade.asset_code,
                    trade.quantity,
                    trade.price,
                    current_position_value,
                    fee_config,
                )
            else:
                if current_position is None:
                    raise BusinessLogicError("卖出持仓不存在", code="POSITION_NOT_FOUND")
                is_valid, reason = TradingConstraintRule.validate_sell_order(
                    current_position,
                    trade.quantity,
                    trade.price,
                )
            if not is_valid:
                raise BusinessLogicError(
                    f"模拟订单状态已变化，拒绝记账：{reason}",
                    code="SIMULATED_TRADE_RULE_REVALIDATION_FAILED",
                )

            if resulting_position is None:
                if position_model is None:
                    raise BusinessLogicError(
                        "待删除持仓不存在",
                        code="POSITION_CHANGED_RETRY_REQUIRED",
                    )
            elif (
                resulting_position.account_id != account_id
                or resulting_position.asset_code != trade.asset_code
            ):
                raise BusinessLogicError(
                    "交易与结果持仓范围不一致",
                    code="SIMULATED_TRADE_WRITE_SCOPE_INVALID",
                )
            if resulting_account.current_cash < 0 or resulting_account.current_market_value < 0:
                raise BusinessLogicError(
                    "模拟交易结果现金或市值无效",
                    code="SIMULATED_TRADE_RESULT_INVALID",
                )

            trade_model = SimulatedTradeMapper.to_model(trade)
            trade_model.id = None
            trade_model.save(using=DEFAULT_DB_ALIAS)
            trade_id = _require_saved_id(trade_model.id, "simulated trade")

            if position_model is None:
                if resulting_position is None:
                    raise BusinessLogicError(
                        "模拟交易结果缺少持仓",
                        code="SIMULATED_TRADE_RESULT_INVALID",
                    )
                position_model = PositionMapper.to_model(resulting_position)
                position_model.pk = None
                position_model.save(using=DEFAULT_DB_ALIAS)
            elif resulting_position is None:
                position_model.delete(using=DEFAULT_DB_ALIAS)
            else:
                mapped_position = PositionMapper.to_model(resulting_position)
                for field_name in (
                    "asset_name",
                    "asset_type",
                    "quantity",
                    "available_quantity",
                    "available_quantity_known",
                    "avg_cost",
                    "total_cost",
                    "cost_basis_known",
                    "current_price",
                    "market_value",
                    "valuation_known",
                    "unrealized_pnl",
                    "unrealized_pnl_pct",
                    "first_buy_date",
                    "first_buy_date_known",
                    "last_update_date",
                    "signal_id",
                    "entry_reason",
                    "invalidation_rule_json",
                    "invalidation_description",
                    "is_invalidated",
                    "invalidation_reason",
                    "invalidation_checked_at",
                ):
                    setattr(position_model, field_name, getattr(mapped_position, field_name))
                position_model.save(
                    using=DEFAULT_DB_ALIAS,
                    update_fields=(
                        "asset_name",
                        "asset_type",
                        "quantity",
                        "available_quantity",
                        "available_quantity_known",
                        "avg_cost",
                        "total_cost",
                        "cost_basis_known",
                        "current_price",
                        "market_value",
                        "valuation_known",
                        "unrealized_pnl",
                        "unrealized_pnl_pct",
                        "first_buy_date",
                        "first_buy_date_known",
                        "last_update_date",
                        "signal_id",
                        "entry_reason",
                        "invalidation_rule_json",
                        "invalidation_description",
                        "is_invalidated",
                        "invalidation_reason",
                        "invalidation_checked_at",
                        "updated_at",
                    ),
                )

            account_model.current_cash = resulting_account.current_cash
            account_model.current_market_value = resulting_account.current_market_value
            account_model.total_value = resulting_account.total_value
            account_model.total_return = resulting_account.total_return
            account_model.total_trades = resulting_account.total_trades
            account_model.winning_trades = resulting_account.winning_trades
            account_model.last_trade_date = resulting_account.last_trade_date
            account_model.save(
                using=DEFAULT_DB_ALIAS,
                update_fields=(
                    "current_cash",
                    "current_market_value",
                    "total_value",
                    "total_return",
                    "total_trades",
                    "winning_trades",
                    "last_trade_date",
                    "updated_at",
                    "cash_known",
                    "cash_reconciliation_status",
                ),
            )
        return SimulatedTradeMapper.to_entity(
            SimulatedTradeModel._default_manager.using(DEFAULT_DB_ALIAS).get(pk=trade_id)
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

    def sum_realized_pnl_for_closed_trades(self) -> AdminDashboardRealizedPnlSummary:
        """Return the closed-trade summary from its focused read owner."""
        return DjangoTradeSummaryRepository(
            fee_correction_history=self._fee_correction_history
        ).sum_realized_pnl_for_closed_trades()

    def has_incomplete_closed_trade_costs(self, account_id: int | None = None) -> bool:
        """Return whether the focused summary owner finds incomplete costs."""
        return DjangoTradeSummaryRepository().has_incomplete_closed_trade_costs(account_id)

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
