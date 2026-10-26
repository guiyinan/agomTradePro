"""Account-locked atomic compatibility trade ledger writes."""

from django.db import DEFAULT_DB_ALIAS, transaction

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
from .order_reservation_fill_account_history import validate_account_v4_fill_history
from .order_reservation_guard import lock_active_order_reservations
from .position_mapper import PositionMapper
from .position_repository_guard import require_no_retained_v4_fill_history
from .repository_helpers import _require_saved_id
from .trade_mapper import SimulatedTradeMapper


class DjangoTradeLedgerWriteRepository:
    """Own the existing single-transaction compatibility ledger write."""

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
