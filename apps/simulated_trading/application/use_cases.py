"""
模拟盘用例定义

Application层:
- 用例(Use Case)编排业务逻辑
- 通过依赖倒置使用Infrastructure层
- 实现具体的业务流程
"""

import logging
from dataclasses import replace
from datetime import date, datetime
from typing import Literal, Protocol, TypedDict

from django.utils import timezone

from apps.simulated_trading.application.daily_net_value_metrics import (
    project_daily_net_value_metrics,
)
from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionAccountHistoryProjection,
    FeeCorrectionCashPosting,
)
from apps.simulated_trading.application.ports import (
    DailyNetValueAccountRepositoryProtocol,
    DailyNetValueRepositoryProtocol,
    SignalQueryRepositoryProtocol,
)
from apps.simulated_trading.domain.corrected_account_performance_metrics import (
    CorrectedAccountPerformanceInput,
    calculate_corrected_account_performance_metrics,
)
from apps.simulated_trading.domain.entities import (
    AccountType,
    FeeConfig,
    OrderStatus,
    Position,
    SimulatedAccount,
    SimulatedTrade,
    TradeAction,
)
from apps.simulated_trading.domain.rules import TradingConstraintRule
from apps.simulated_trading.domain.services import PositionCostBasisService
from core.exceptions import BusinessLogicError
from shared.numeric import safe_float

logger = logging.getLogger(__name__)


def _as_float(value: object) -> float:
    result: float = safe_float(value, default=0.0)
    return result


def _merge_cost_basis_knowledge(
    existing_known: bool | None,
    added_basis_complete: bool,
) -> bool | None:
    """Retain prior knowledge and mark newly omitted known fees as partial."""
    if not added_basis_complete:
        return False
    return existing_known


def _account_performance_unknown_reason(
    account: SimulatedAccount,
    positions: list[Position],
) -> str:
    """Return the first stable evidence reason for an unknown account snapshot."""

    if account.cash_known is not True:
        return "ACCOUNT_CASH_UNKNOWN"
    if any(position.valuation_known is not True for position in positions):
        return "POSITION_VALUATION_UNKNOWN"
    return "TRADE_PERFORMANCE_KNOWLEDGE_UNKNOWN"


def _corrected_daily_performance(
    *,
    account: SimulatedAccount,
    daily_net_value_repo: DailyNetValueRepositoryProtocol | None,
    as_of: datetime,
    cash_events: tuple[FeeCorrectionCashPosting, ...],
) -> tuple[dict[str, float] | None, str | None]:
    """Recalculate time-series metrics only from a covered, current daily history."""

    unknown = "FEE_CORRECTION_PERFORMANCE_HISTORY_UNKNOWN"
    if daily_net_value_repo is None or not cash_events:
        return None, unknown
    if any(event.posting_date >= as_of.date() for event in cash_events):
        return None, unknown

    records = daily_net_value_repo.list_daily_records(
        account_id=account.account_id,
        end_date=as_of.date(),
    )
    metric_projections = project_daily_net_value_metrics(
        records,
        initial_capital=account.initial_capital,
    )
    if len(records) < 3 or any(
        record["correction_coverage_known"] is not True for record in records
    ):
        return None, unknown
    if max(event.posting_date for event in cash_events) > records[-1]["record_date"]:
        return None, unknown

    if (
        isinstance(records[-1]["net_value"], bool)
        or isinstance(account.total_value, bool)
        or isinstance(account.initial_capital, bool)
    ):
        return None, unknown

    last_value = safe_float(records[-1]["net_value"])
    current_value = safe_float(account.total_value)
    initial_capital = safe_float(account.initial_capital)
    if (
        last_value is None
        or current_value is None
        or initial_capital is None
        or initial_capital <= 0.0
        or round(last_value, 2) != round(current_value, 2)
    ):
        return None, unknown

    end_date = records[-1]["record_date"]
    days = (end_date - account.start_date).days
    if days <= 0:
        return None, unknown

    drawdowns = tuple(projection.drawdown for projection in metric_projections)
    daily_returns = tuple(projection.daily_return for projection in metric_projections[1:])
    if any(value is None for value in drawdowns) or any(value is None for value in daily_returns):
        return None, unknown
    metrics = calculate_corrected_account_performance_metrics(
        CorrectedAccountPerformanceInput(
            initial_capital=initial_capital,
            final_net_value=last_value,
            elapsed_days=days,
            drawdowns=drawdowns,
            daily_returns_percent=daily_returns,
        )
    )
    if metrics is None:
        return None, unknown
    return {
        "total_return": metrics.total_return,
        "annual_return": metrics.annual_return,
        "max_drawdown": metrics.max_drawdown,
        "sharpe_ratio": metrics.sharpe_ratio,
    }, None


class AccountPerformanceValues(TypedDict):
    """Persisted performance values with evidence-aware nullable metrics."""

    total_return: float | None
    annual_return: float | None
    max_drawdown: float | None
    sharpe_ratio: float | None
    win_rate: float | None


class AccountPerformanceResult(TypedDict):
    """Account, positions, trade counts, and performance values."""

    account: SimulatedAccount
    positions: list[Position]
    total_positions: int
    total_trades: int
    winning_trades: int | None
    win_rate: float | None
    win_rate_known: bool
    performance: AccountPerformanceValues
    original_performance: AccountPerformanceValues
    performance_metrics_known: bool
    performance_reason_code: str | None
    performance_source: Literal["account_snapshot", "corrected_daily_history", "unknown"]


# Protocol接口定义（依赖倒置）
class SimulatedAccountRepositoryProtocol(DailyNetValueAccountRepositoryProtocol, Protocol):
    """模拟账户Repository接口"""

    def save(self, account: SimulatedAccount, user_id: int | None = None) -> int: ...
    def get_by_id(self, account_id: int) -> SimulatedAccount | None: ...
    def get_by_name(
        self,
        account_name: str,
        user_id: int | None = None,
    ) -> SimulatedAccount | None: ...
    def get_active_accounts(self) -> list[SimulatedAccount]: ...
    def get_all_accounts(self) -> list[SimulatedAccount]: ...
    def get_by_user(self, user_id: int) -> list[SimulatedAccount]: ...
    def delete(self, account_id: int) -> bool: ...


class PositionRepositoryProtocol(Protocol):
    """持仓Repository接口"""

    def save(self, position: Position) -> int: ...
    def get_by_account(self, account_id: int) -> list[Position]: ...
    def get_position(self, account_id: int, asset_code: str) -> Position | None: ...
    def delete(self, account_id: int, asset_code: str) -> bool: ...


class TradeRepositoryProtocol(Protocol):
    """交易记录Repository接口"""

    def save(self, trade: SimulatedTrade) -> int: ...
    def execute_legacy_trade_atomically(
        self,
        *,
        expected_account: SimulatedAccount,
        expected_position: Position | None,
        fee_config: FeeConfig,
        trade: SimulatedTrade,
        resulting_position: Position | None,
        resulting_account: SimulatedAccount,
    ) -> SimulatedTrade: ...
    def get_by_account(self, account_id: int) -> list[SimulatedTrade]: ...
    def get_account_history(
        self,
        *,
        account_id: int,
        as_of: datetime,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FeeCorrectionAccountHistoryProjection: ...
    def get_by_date_range(
        self,
        account_id: int,
        start: date,
        end: date,
    ) -> list[SimulatedTrade]: ...


class FeeConfigRepositoryProtocol(Protocol):
    """Trading fee configuration repository boundary."""

    def get_default_config(self, asset_type: str = "all") -> FeeConfig | None: ...


class CreateSimulatedAccountUseCase:
    """创建统一账户用例。"""

    def __init__(self, account_repo: SimulatedAccountRepositoryProtocol) -> None:
        self.account_repo = account_repo

    def execute(
        self,
        account_name: str,
        initial_capital: float,
        account_type: AccountType = AccountType.SIMULATED,
        auto_trading_enabled: bool | None = None,
        max_position_pct: float = 20.0,
        stop_loss_pct: float | None = None,
        commission_rate: float = 0.0003,
        slippage_rate: float = 0.001,
        user_id: int | None = None,
    ) -> SimulatedAccount:
        """
        创建账户

        Args:
            account_name: 账户名称
            initial_capital: 初始资金(元)
            auto_trading_enabled: 是否启用自动交易
            max_position_pct: 单资产最大持仓比例(%)
            stop_loss_pct: 止损比例(%)
            commission_rate: 手续费率
            slippage_rate: 滑点率

        Returns:
            创建的账户
        """
        # 1. 检查账户名称是否已存在
        existing = self.account_repo.get_by_name(account_name, user_id=user_id)
        if existing:
            raise ValueError(f"账户名称已存在: {account_name}")

        resolved_auto_trading_enabled = (
            account_type == AccountType.SIMULATED
            if auto_trading_enabled is None
            else auto_trading_enabled
        )

        # 2. 创建账户实体
        account = SimulatedAccount(
            account_id=0,  # 由数据库生成
            account_name=account_name,
            account_type=account_type,
            initial_capital=initial_capital,
            current_cash=initial_capital,
            current_market_value=0.0,
            total_value=initial_capital,
            auto_trading_enabled=resolved_auto_trading_enabled,
            max_position_pct=max_position_pct,
            stop_loss_pct=stop_loss_pct,
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
            start_date=date.today(),
        )

        # 3. 保存到数据库
        account_id = self.account_repo.save(account, user_id=user_id)

        logger.info(
            "创建账户成功: %s (ID=%s, type=%s), 初始资金: %s",
            account_name,
            account_id,
            account_type.value,
            initial_capital,
        )

        # 4. 返回带ID的账户
        return SimulatedAccount(
            account_id=account_id,
            account_name=account.account_name,
            account_type=account.account_type,
            initial_capital=account.initial_capital,
            current_cash=account.current_cash,
            current_market_value=account.current_market_value,
            total_value=account.total_value,
            auto_trading_enabled=account.auto_trading_enabled,
            max_position_pct=account.max_position_pct,
            stop_loss_pct=account.stop_loss_pct,
            commission_rate=account.commission_rate,
            slippage_rate=account.slippage_rate,
            start_date=account.start_date,
        )


class GetAccountPerformanceUseCase:
    """获取账户绩效用例"""

    def __init__(
        self,
        account_repo: SimulatedAccountRepositoryProtocol,
        position_repo: PositionRepositoryProtocol,
        trade_repo: TradeRepositoryProtocol,
        daily_net_value_repo: DailyNetValueRepositoryProtocol | None = None,
    ) -> None:
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo
        self.daily_net_value_repo = daily_net_value_repo

    def execute(self, account_id: int) -> AccountPerformanceResult:
        """
        获取账户绩效

        Args:
            account_id: 账户ID

        Returns:
            绩效字典(含账户、持仓、交易记录、绩效指标)
        """
        # 1. 获取账户
        account = self.account_repo.get_by_id(account_id)
        if not account:
            raise ValueError(f"账户不存在: {account_id}")

        # 2. 获取持仓
        positions = self.position_repo.get_by_account(account_id)

        # 3. Read the full correction-aware account history at one aware as-of clock.
        as_of = timezone.now()
        history = self.trade_repo.get_account_history(account_id=account_id, as_of=as_of)
        trades = list(reversed(history.trades))

        # Only executed SELL facts count toward realized trade metrics.
        sell_trades = [
            trade
            for trade in trades
            if trade.status is OrderStatus.EXECUTED and trade.action is TradeAction.SELL
        ]
        win_rate_known = all(
            trade.cost_basis_known is True
            and trade.fee_amounts_known is True
            and trade.current_realized_pnl is not None
            for trade in sell_trades
        )
        if win_rate_known:
            known_winning_trades = sum(
                1
                for trade in sell_trades
                if trade.current_realized_pnl is not None and trade.current_realized_pnl > 0
            )
            winning_trades: int | None = known_winning_trades
            win_rate: float | None = (
                known_winning_trades / len(sell_trades) * 100 if sell_trades else 0.0
            )
        else:
            winning_trades = None
            win_rate = None

        performance_known = (
            account.cash_known is True
            and all(position.valuation_known is True for position in positions)
            and win_rate_known
        )
        original_performance: AccountPerformanceValues = {
            "total_return": safe_float(account.total_return),
            "annual_return": safe_float(account.annual_return),
            "max_drawdown": safe_float(account.max_drawdown),
            "sharpe_ratio": safe_float(account.sharpe_ratio),
            "win_rate": safe_float(account.win_rate),
        }
        performance_source: Literal["account_snapshot", "corrected_daily_history", "unknown"] = (
            "account_snapshot" if performance_known else "unknown"
        )
        performance_reason_code: str | None = (
            None if performance_known else _account_performance_unknown_reason(account, positions)
        )
        if history.cash_events:
            if account.cash_known is not True:
                corrected_metrics = None
                performance_reason_code = "ACCOUNT_CASH_UNKNOWN"
            elif any(position.valuation_known is not True for position in positions):
                corrected_metrics = None
                performance_reason_code = "POSITION_VALUATION_UNKNOWN"
            else:
                corrected_metrics, performance_reason_code = _corrected_daily_performance(
                    account=account,
                    daily_net_value_repo=self.daily_net_value_repo,
                    as_of=as_of,
                    cash_events=history.cash_events,
                )
            if corrected_metrics is None:
                total_return = None
                annual_return = None
                max_drawdown = None
                sharpe_ratio = None
                performance_source = "unknown"
            else:
                total_return = corrected_metrics["total_return"]
                annual_return = corrected_metrics["annual_return"]
                max_drawdown = corrected_metrics["max_drawdown"]
                sharpe_ratio = corrected_metrics["sharpe_ratio"]
                performance_source = "corrected_daily_history"
        else:
            total_return = original_performance["total_return"] if performance_known else None
            annual_return = original_performance["annual_return"] if performance_known else None
            max_drawdown = original_performance["max_drawdown"] if performance_known else None
            sharpe_ratio = original_performance["sharpe_ratio"] if performance_known else None

        effective_metrics_known = all(
            value is not None for value in (total_return, annual_return, max_drawdown, sharpe_ratio)
        )
        if not effective_metrics_known and performance_reason_code is None:
            performance_reason_code = "PERFORMANCE_METRIC_VALUE_UNKNOWN"
            performance_source = "unknown"

        return {
            "account": account,
            "positions": positions,
            "total_positions": len(positions),
            "total_trades": len(trades),
            "winning_trades": winning_trades,
            "win_rate": win_rate,
            "win_rate_known": win_rate_known,
            "original_performance": original_performance,
            "performance_metrics_known": effective_metrics_known,
            "performance_reason_code": performance_reason_code,
            "performance_source": performance_source,
            "performance": {
                "total_return": total_return,
                "annual_return": annual_return,
                "max_drawdown": max_drawdown,
                "sharpe_ratio": sharpe_ratio,
                "win_rate": win_rate,
            },
        }


class ExecuteBuyOrderUseCase:
    """执行买入订单用例"""

    def __init__(
        self,
        account_repo: SimulatedAccountRepositoryProtocol,
        position_repo: PositionRepositoryProtocol,
        trade_repo: TradeRepositoryProtocol,
        fee_config_repo: FeeConfigRepositoryProtocol,
        signal_repo: SignalQueryRepositoryProtocol | None = None,
    ) -> None:
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo
        self.fee_config_repo = fee_config_repo
        self.signal_repo = signal_repo

    def execute(
        self,
        account_id: int,
        asset_code: str,
        asset_name: str,
        asset_type: str,
        quantity: int,
        price: float,
        reason: str = "",
        signal_id: int | None = None,
        execution_date: date | None = None,
    ) -> SimulatedTrade:
        """Execute a BUY with bounded retries after a stale financial snapshot."""
        for attempt in range(3):
            try:
                return self._execute_once(
                    account_id=account_id,
                    asset_code=asset_code,
                    asset_name=asset_name,
                    asset_type=asset_type,
                    quantity=quantity,
                    price=price,
                    reason=reason,
                    signal_id=signal_id,
                    execution_date=execution_date,
                )
            except BusinessLogicError as exc:
                if exc.code != "POSITION_CHANGED_RETRY_REQUIRED":
                    raise
                if attempt == 2:
                    raise BusinessLogicError(
                        "账户、持仓或费用状态持续变化，交易未写入，请重新提交",
                        code="POSITION_CHANGED_RETRY_EXHAUSTED",
                        details={"account_id": account_id, "asset_code": asset_code},
                    ) from exc
        raise AssertionError("bounded BUY retry loop exited unexpectedly")

    def _execute_once(
        self,
        account_id: int,
        asset_code: str,
        asset_name: str,
        asset_type: str,
        quantity: int,
        price: float,
        reason: str = "",
        signal_id: int | None = None,
        execution_date: date | None = None,
    ) -> SimulatedTrade:
        """
        Compute a BUY from freshly read state and commit it atomically.

        Args:
            account_id: 账户ID
            asset_code: 资产代码
            asset_name: 资产名称
            asset_type: 资产类型
            quantity: 买入数量
            price: 买入价格
            reason: 买入原因
            signal_id: 关联信号ID

        Returns:
            交易记录
        """
        # 1. 获取账户
        account = self.account_repo.get_by_id(account_id)
        if not account:
            raise ValueError(f"账户不存在: {account_id}")

        effective_date = execution_date or date.today()
        order_quantity = _as_float(quantity)
        existing_position = self.position_repo.get_position(account_id, asset_code)
        if existing_position and existing_position.is_invalidated:
            raise ValueError(f"持仓已触发证伪条件，禁止加仓: {asset_code}")
        if existing_position and existing_position.available_quantity_known is not True:
            raise BusinessLogicError(
                "现有持仓可卖数量未知，拒绝加仓",
                code="SELLABLE_BALANCE_UNKNOWN",
                details={"account_id": account_id, "asset_code": asset_code},
            )
        current_position_value = (
            _as_float(existing_position.quantity) * price if existing_position else 0.0
        )
        fee_config = self.fee_config_repo.get_default_config(asset_type)
        if fee_config is None:
            raise ValueError(f"未配置启用的默认交易费率: {asset_type}")

        # 2. 验证订单
        valid, error_msg = TradingConstraintRule.validate_buy_order(
            account,
            asset_code,
            order_quantity,
            price,
            current_position_value,
            fee_config,
        )
        if not valid:
            raise ValueError(f"买入订单验证失败: {error_msg}")

        # 3. 计算费用
        amount = order_quantity * price
        fee_values = fee_config.calculate_buy_fee(
            amount,
            is_shanghai=asset_code.upper().endswith(".SH"),
        )
        commission = fee_values["commission"]
        slippage = fee_values["slippage"]
        total_cost = amount + fee_values["total_fee"]
        lot_avg_cost, lot_total_cost = PositionCostBasisService.calculate_lot_cost(
            quantity=order_quantity,
            price=price,
            commission=commission,
            slippage=slippage,
        )
        # The existing basis formula omits transfer fee, so nonzero transfer fees stay partial.
        lot_basis_complete = fee_values["transfer_fee"] == 0.0

        # 4. 创建交易记录
        trade = SimulatedTrade(
            trade_id=0,
            account_id=account_id,
            asset_code=asset_code,
            asset_name=asset_name,
            asset_type=asset_type,
            action=TradeAction.BUY,
            quantity=order_quantity,
            price=price,
            amount=amount,
            commission=commission,
            slippage=slippage,
            total_cost=total_cost,
            transfer_fee=fee_values["transfer_fee"],
            stamp_duty=fee_values["stamp_duty"],
            fee_amounts_known=True,
            cost_basis_known=lot_basis_complete,
            reason=reason,
            signal_id=signal_id,
            order_date=effective_date,
            execution_date=effective_date,
            execution_time=timezone.now(),
            status=OrderStatus.EXECUTED,
        )

        # 从信号获取证伪条件（如果有 signal_id）
        invalidation_rule_json = None
        invalidation_description = ""
        if signal_id:
            invalidation_rule_json, invalidation_description = self._get_signal_invalidation(
                signal_id
            )
        invalidation_description = invalidation_description or ""

        if existing_position:
            # Add shares while preserving existing invalidation and knowledge flags.
            existing_quantity = _as_float(existing_position.quantity)
            existing_total_cost = _as_float(existing_position.total_cost)
            new_quantity = existing_quantity + order_quantity
            new_avg_cost, new_total_cost = PositionCostBasisService.merge_position_cost(
                existing_quantity=existing_quantity,
                existing_total_cost=existing_total_cost,
                added_quantity=order_quantity,
                added_total_cost=lot_total_cost,
            )

            updated_position = Position(
                account_id=account_id,
                asset_code=asset_code,
                asset_name=asset_name,
                asset_type=asset_type,
                quantity=new_quantity,
                available_quantity=new_quantity,  # 买入当天不可卖(T+1)
                avg_cost=new_avg_cost,
                total_cost=new_total_cost,
                cost_basis_known=_merge_cost_basis_knowledge(
                    existing_position.cost_basis_known,
                    lot_basis_complete,
                ),
                current_price=price,
                market_value=new_quantity * price,
                unrealized_pnl=(price - new_avg_cost) * new_quantity,
                unrealized_pnl_pct=((price - new_avg_cost) / new_avg_cost) * 100,
                first_buy_date=existing_position.first_buy_date,
                first_buy_date_known=existing_position.first_buy_date_known,
                available_quantity_known=existing_position.available_quantity_known,
                last_update_date=effective_date,
                signal_id=signal_id,
                entry_reason=reason or existing_position.entry_reason,
                # 保留原有的证伪条件
                invalidation_rule_json=existing_position.invalidation_rule_json,
                invalidation_description=existing_position.invalidation_description,
                is_invalidated=existing_position.is_invalidated,
                invalidation_reason=existing_position.invalidation_reason,
                invalidation_checked_at=existing_position.invalidation_checked_at,
            )
        else:
            # 新建持仓 - 从信号继承证伪条件
            position = Position(
                account_id=account_id,
                asset_code=asset_code,
                asset_name=asset_name,
                asset_type=asset_type,
                quantity=order_quantity,
                available_quantity=order_quantity,  # 买入当天不可卖(T+1)
                avg_cost=lot_avg_cost,
                total_cost=lot_total_cost,
                cost_basis_known=lot_basis_complete,
                current_price=price,
                market_value=amount,
                unrealized_pnl=amount - lot_total_cost,
                unrealized_pnl_pct=((price - lot_avg_cost) / lot_avg_cost) * 100,
                first_buy_date=effective_date,
                last_update_date=effective_date,
                signal_id=signal_id,
                entry_reason=reason,
                # 从信号继承证伪条件
                invalidation_rule_json=invalidation_rule_json,
                invalidation_description=invalidation_description,
            )
            updated_position = position

        # 7. 更新账户资金
        updated_account = replace(
            account,
            current_cash=_as_float(account.current_cash) - total_cost,
            current_market_value=_as_float(account.current_market_value) + amount,
            total_value=_as_float(account.current_cash)
            - total_cost
            + _as_float(account.current_market_value)
            + amount,
            total_trades=account.total_trades + 1,
            last_trade_date=effective_date,
        )
        persisted_trade = self.trade_repo.execute_legacy_trade_atomically(
            expected_account=account,
            expected_position=existing_position,
            fee_config=fee_config,
            trade=trade,
            resulting_position=updated_position,
            resulting_account=updated_account,
        )

        logger.info(
            f"买入成功: {account.account_name} -> {asset_name} x{quantity} @ {price:.2f}, "
            f"总成本: {total_cost:.2f}"
        )

        return persisted_trade

    def _get_signal_invalidation(self, signal_id: int) -> tuple[str | None, str]:
        """
        从信号获取证伪条件

        Args:
            signal_id: 信号ID

        Returns:
            (invalidation_rule_json, invalidation_description) 或 (None, None)
        """
        if self.signal_repo is None:
            return None, ""
        try:
            payload: tuple[str | None, str] = self.signal_repo.get_signal_invalidation_payload(
                signal_id
            )
            return payload
        except Exception:
            logger.warning(
                "读取交易信号证伪条件失败: signal_id=%s",
                signal_id,
                exc_info=True,
            )
            return None, ""


class ExecuteSellOrderUseCase:
    """执行卖出订单用例"""

    def __init__(
        self,
        account_repo: SimulatedAccountRepositoryProtocol,
        position_repo: PositionRepositoryProtocol,
        trade_repo: TradeRepositoryProtocol,
        fee_config_repo: FeeConfigRepositoryProtocol,
    ) -> None:
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo
        self.fee_config_repo = fee_config_repo

    def execute(
        self,
        account_id: int,
        asset_code: str,
        quantity: int,
        price: float,
        reason: str = "",
        execution_date: date | None = None,
    ) -> SimulatedTrade:
        """Execute a SELL with bounded retries after a stale financial snapshot."""
        for attempt in range(3):
            try:
                return self._execute_once(
                    account_id=account_id,
                    asset_code=asset_code,
                    quantity=quantity,
                    price=price,
                    reason=reason,
                    execution_date=execution_date,
                )
            except BusinessLogicError as exc:
                if exc.code != "POSITION_CHANGED_RETRY_REQUIRED":
                    raise
                if attempt == 2:
                    raise BusinessLogicError(
                        "账户、持仓或费用状态持续变化，交易未写入，请重新提交",
                        code="POSITION_CHANGED_RETRY_EXHAUSTED",
                        details={"account_id": account_id, "asset_code": asset_code},
                    ) from exc
        raise AssertionError("bounded SELL retry loop exited unexpectedly")

    def _execute_once(
        self,
        account_id: int,
        asset_code: str,
        quantity: int,
        price: float,
        reason: str = "",
        execution_date: date | None = None,
    ) -> SimulatedTrade:
        """
        Compute a SELL from freshly read state and commit it atomically.

        Args:
            account_id: 账户ID
            asset_code: 资产代码
            quantity: 卖出数量
            price: 卖出价格
            reason: 卖出原因

        Returns:
            交易记录
        """
        # 1. 获取账户和持仓
        account = self.account_repo.get_by_id(account_id)
        if not account:
            raise ValueError(f"账户不存在: {account_id}")

        position = self.position_repo.get_position(account_id, asset_code)
        if not position:
            raise ValueError(f"持仓不存在: {asset_code}")
        if position.available_quantity_known is not True:
            raise BusinessLogicError(
                "现有持仓可卖数量未知，拒绝卖出",
                code="SELLABLE_BALANCE_UNKNOWN",
                details={"account_id": account_id, "asset_code": asset_code},
            )

        effective_date = execution_date or date.today()
        order_quantity = _as_float(quantity)
        position_quantity = _as_float(position.quantity)
        position_avg_cost = _as_float(position.avg_cost)
        fee_config = self.fee_config_repo.get_default_config(position.asset_type)
        if fee_config is None:
            raise ValueError(f"未配置启用的默认交易费率: {position.asset_type}")

        # 2. 验证订单
        valid, error_msg = TradingConstraintRule.validate_sell_order(
            position, order_quantity, price
        )
        if not valid:
            raise ValueError(f"卖出订单验证失败: {error_msg}")

        # 3. 计算费用
        amount = order_quantity * price
        fee_values = fee_config.calculate_sell_fee(
            amount,
            is_shanghai=asset_code.upper().endswith(".SH"),
        )
        commission = fee_values["commission"]
        slippage = fee_values["slippage"]
        total_cost = fee_values["total_fee"]

        # 4. 计算盈亏
        avg_cost_total = position_avg_cost * order_quantity
        net_amount = amount - total_cost
        realized_pnl = net_amount - avg_cost_total if position.cost_basis_known is True else None
        realized_pnl_pct = (
            (realized_pnl / avg_cost_total) * 100
            if realized_pnl is not None and avg_cost_total
            else None
        )

        # 5. 创建交易记录
        trade = SimulatedTrade(
            trade_id=0,
            account_id=account_id,
            asset_code=asset_code,
            asset_name=position.asset_name,
            asset_type=position.asset_type,
            action=TradeAction.SELL,
            quantity=order_quantity,
            price=price,
            amount=amount,
            commission=commission,
            slippage=slippage,
            total_cost=total_cost,
            transfer_fee=fee_values["transfer_fee"],
            stamp_duty=fee_values["stamp_duty"],
            fee_amounts_known=True,
            cost_basis_known=position.cost_basis_known,
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            reason=reason,
            signal_id=position.signal_id,
            order_date=effective_date,
            execution_date=effective_date,
            execution_time=timezone.now(),
            status=OrderStatus.EXECUTED,
        )

        # 6. Prepare the resulting position without writing before account validation.
        remaining_quantity = position_quantity - order_quantity
        if remaining_quantity > 0:
            # 部分卖出
            updated_position = Position(
                account_id=account_id,
                asset_code=asset_code,
                asset_name=position.asset_name,
                asset_type=position.asset_type,
                quantity=remaining_quantity,
                available_quantity=max(
                    _as_float(position.available_quantity) - order_quantity,
                    0.0,
                ),
                avg_cost=position_avg_cost,
                total_cost=position_avg_cost * remaining_quantity,
                current_price=price,
                market_value=remaining_quantity * price,
                unrealized_pnl=(price - position_avg_cost) * remaining_quantity,
                unrealized_pnl_pct=((price - position_avg_cost) / position_avg_cost) * 100,
                first_buy_date=position.first_buy_date,
                first_buy_date_known=position.first_buy_date_known,
                available_quantity_known=position.available_quantity_known,
                cost_basis_known=position.cost_basis_known,
                last_update_date=effective_date,
                signal_id=position.signal_id,
                entry_reason=position.entry_reason,
            )
        else:
            # 全部卖出，删除持仓
            updated_position = None

        # 8. 更新账户资金
        new_market_value = _as_float(account.current_market_value) - position_quantity * price
        if remaining_quantity > 0:
            new_market_value += remaining_quantity * price

        updated_account = replace(
            account,
            current_cash=_as_float(account.current_cash) + net_amount,
            current_market_value=new_market_value,
            total_value=_as_float(account.current_cash) + net_amount + new_market_value,
            total_trades=account.total_trades + 1,
            winning_trades=account.winning_trades
            + (1 if realized_pnl is not None and realized_pnl > 0 else 0),
            last_trade_date=effective_date,
        )
        persisted_trade = self.trade_repo.execute_legacy_trade_atomically(
            expected_account=account,
            expected_position=position,
            fee_config=fee_config,
            trade=trade,
            resulting_position=updated_position,
            resulting_account=updated_account,
        )

        realized_pnl_text = f"{realized_pnl:.2f}" if realized_pnl is not None else "未知"
        realized_pnl_pct_text = (
            f"{realized_pnl_pct:.2f}%" if realized_pnl_pct is not None else "未知"
        )
        logger.info(
            f"卖出成功: {account.account_name} -> {position.asset_name} x{quantity} @ {price:.2f}, "
            f"盈亏: {realized_pnl_text} ({realized_pnl_pct_text})"
        )

        return persisted_trade


class ListAccountsUseCase:
    """列出所有账户用例"""

    def __init__(self, account_repo: SimulatedAccountRepositoryProtocol):
        self.account_repo = account_repo

    def execute(
        self,
        active_only: bool = True,
        user_id: int | None = None,
        account_type: AccountType | None = None,
    ) -> list[SimulatedAccount]:
        """
        列出所有账户

        Args:
            active_only: 是否只返回活跃账户
            user_id: 可选，限制为当前用户拥有的账户
            account_type: 可选，按账户类型过滤

        Returns:
            账户列表
        """
        if user_id is not None:
            accounts = self.account_repo.get_by_user(user_id)
        elif active_only:
            accounts = self.account_repo.get_active_accounts()
        else:
            accounts = self.account_repo.get_all_accounts()

        if active_only:
            accounts = [account for account in accounts if account.is_active]
        if account_type is not None:
            accounts = [account for account in accounts if account.account_type == account_type]
        return accounts
