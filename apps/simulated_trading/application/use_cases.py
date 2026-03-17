"""
模拟盘用例定义

Application层:
- 用例(Use Case)编排业务逻辑
- 通过依赖倒置使用Infrastructure层
- 实现具体的业务流程
"""
from typing import List, Optional, Protocol
from datetime import date, datetime
import logging
from dataclasses import replace

from django.utils import timezone

from apps.simulated_trading.domain.entities import (
    SimulatedAccount,
    Position,
    SimulatedTrade,
    AccountType,
    TradeAction,
    OrderStatus
)
from apps.simulated_trading.domain.rules import TradingConstraintRule
from apps.simulated_trading.application.ports import SignalQueryRepositoryProtocol

logger = logging.getLogger(__name__)


# Protocol接口定义（依赖倒置）
class SimulatedAccountRepositoryProtocol(Protocol):
    """模拟账户Repository接口"""
    def save(self, account: SimulatedAccount) -> int: ...
    def get_by_id(self, account_id: int) -> Optional[SimulatedAccount]: ...
    def get_by_name(self, account_name: str) -> Optional[SimulatedAccount]: ...
    def get_active_accounts(self) -> List[SimulatedAccount]: ...
    def get_all_accounts(self) -> List[SimulatedAccount]: ...
    def delete(self, account_id: int) -> bool: ...


class PositionRepositoryProtocol(Protocol):
    """持仓Repository接口"""
    def save(self, position: Position) -> int: ...
    def get_by_account(self, account_id: int) -> List[Position]: ...
    def get_position(self, account_id: int, asset_code: str) -> Optional[Position]: ...
    def delete(self, account_id: int, asset_code: str) -> bool: ...


class TradeRepositoryProtocol(Protocol):
    """交易记录Repository接口"""
    def save(self, trade: SimulatedTrade) -> int: ...
    def get_by_account(self, account_id: int) -> List[SimulatedTrade]: ...
    def get_by_date_range(self, account_id: int, start: date, end: date) -> List[SimulatedTrade]: ...


class CreateSimulatedAccountUseCase:
    """创建模拟账户用例"""

    def __init__(self, account_repo: SimulatedAccountRepositoryProtocol):
        self.account_repo = account_repo

    def execute(
        self,
        account_name: str,
        initial_capital: float,
        auto_trading_enabled: bool = True,
        max_position_pct: float = 20.0,
        stop_loss_pct: Optional[float] = None,
        commission_rate: float = 0.0003,
        slippage_rate: float = 0.001
    ) -> SimulatedAccount:
        """
        创建模拟账户

        Args:
            account_name: 账户名称
            initial_capital: 初始资金(元)
            auto_trading_enabled: 是否启用自动交易
            max_position_pct: 单资产最大持仓比例(%)
            stop_loss_pct: 止损比例(%)
            commission_rate: 手续费率
            slippage_rate: 滑点率

        Returns:
            创建的模拟账户
        """
        # 1. 检查账户名称是否已存在
        existing = self.account_repo.get_by_name(account_name)
        if existing:
            raise ValueError(f"账户名称已存在: {account_name}")

        # 2. 创建账户实体
        account = SimulatedAccount(
            account_id=0,  # 由数据库生成
            account_name=account_name,
            account_type=AccountType.SIMULATED,
            initial_capital=initial_capital,
            current_cash=initial_capital,
            current_market_value=0.0,
            total_value=initial_capital,
            auto_trading_enabled=auto_trading_enabled,
            max_position_pct=max_position_pct,
            stop_loss_pct=stop_loss_pct,
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
            start_date=date.today()
        )

        # 3. 保存到数据库
        account_id = self.account_repo.save(account)

        logger.info(f"创建模拟账户成功: {account_name} (ID={account_id}), 初始资金: {initial_capital}")

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
            start_date=account.start_date
        )


class GetAccountPerformanceUseCase:
    """获取账户绩效用例"""

    def __init__(
        self,
        account_repo: SimulatedAccountRepositoryProtocol,
        position_repo: PositionRepositoryProtocol,
        trade_repo: TradeRepositoryProtocol
    ):
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo

    def execute(self, account_id: int) -> dict:
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

        # 3. 获取交易记录
        trades = self.trade_repo.get_by_account(account_id)

        # 4. 统计盈利交易
        winning_trades = sum(
            1 for t in trades
            if t.realized_pnl and t.realized_pnl > 0
        )

        # 5. 计算胜率
        win_rate = (winning_trades / len(trades) * 100) if trades else 0.0

        return {
            "account": account,
            "positions": positions,
            "total_positions": len(positions),
            "total_trades": len(trades),
            "winning_trades": winning_trades,
            "win_rate": win_rate,
            "performance": {
                "total_return": account.total_return,
                "annual_return": account.annual_return,
                "max_drawdown": account.max_drawdown,
                "sharpe_ratio": account.sharpe_ratio,
                "win_rate": win_rate
            }
        }


class ExecuteBuyOrderUseCase:
    """执行买入订单用例"""

    def __init__(
        self,
        account_repo: SimulatedAccountRepositoryProtocol,
        position_repo: PositionRepositoryProtocol,
        trade_repo: TradeRepositoryProtocol,
        signal_repo: Optional[SignalQueryRepositoryProtocol] = None,
    ):
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo
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
        signal_id: Optional[int] = None
    ) -> SimulatedTrade:
        """
        执行买入订单

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

        existing_position = self.position_repo.get_position(account_id, asset_code)
        current_position_value = (
            existing_position.quantity * price if existing_position else 0.0
        )

        # 2. 验证订单
        valid, error_msg = TradingConstraintRule.validate_buy_order(
            account, asset_code, quantity, price, current_position_value
        )
        if not valid:
            raise ValueError(f"买入订单验证失败: {error_msg}")

        # 3. 计算费用
        amount = quantity * price
        commission = amount * account.commission_rate
        # 最低手续费5元
        commission = max(commission, 5.0)
        slippage = amount * account.slippage_rate
        total_cost = amount + commission + slippage

        # 4. 创建交易记录
        trade = SimulatedTrade(
            trade_id=0,
            account_id=account_id,
            asset_code=asset_code,
            asset_name=asset_name,
            asset_type=asset_type,
            action=TradeAction.BUY,
            quantity=quantity,
            price=price,
            amount=amount,
            commission=commission,
            slippage=slippage,
            total_cost=total_cost,
            reason=reason,
            signal_id=signal_id,
            order_date=date.today(),
            execution_date=date.today(),
            execution_time=timezone.now(),
            status=OrderStatus.EXECUTED
        )

        # 5. 保存交易记录
        trade_id = self.trade_repo.save(trade)
        trade = SimulatedTrade(
            trade_id=trade_id,
            **{k: v for k, v in trade.__dict__.items() if k != 'trade_id'}
        )

        # 6. 更新或创建持仓

        # 从信号获取证伪条件（如果有 signal_id）
        invalidation_rule_json = None
        invalidation_description = ""
        if signal_id:
            invalidation_rule_json, invalidation_description = self._get_signal_invalidation(signal_id)
        invalidation_description = invalidation_description or ""

        if existing_position:
            # 加仓：更新持仓（保留原有的证伪条件）
            new_quantity = existing_position.quantity + quantity
            new_avg_cost = (
                (existing_position.avg_cost * existing_position.quantity + price * quantity) /
                new_quantity
            )
            new_total_cost = new_avg_cost * new_quantity

            updated_position = Position(
                account_id=account_id,
                asset_code=asset_code,
                asset_name=asset_name,
                asset_type=asset_type,
                quantity=new_quantity,
                available_quantity=new_quantity,  # 买入当天不可卖(T+1)
                avg_cost=new_avg_cost,
                total_cost=new_total_cost,
                current_price=price,
                market_value=new_quantity * price,
                unrealized_pnl=(price - new_avg_cost) * new_quantity,
                unrealized_pnl_pct=((price - new_avg_cost) / new_avg_cost) * 100,
                first_buy_date=existing_position.first_buy_date,
                last_update_date=date.today(),
                signal_id=signal_id,
                entry_reason=reason or existing_position.entry_reason,
                # 保留原有的证伪条件
                invalidation_rule_json=existing_position.invalidation_rule_json,
                invalidation_description=existing_position.invalidation_description,
                is_invalidated=existing_position.is_invalidated,
                invalidation_reason=existing_position.invalidation_reason,
                invalidation_checked_at=existing_position.invalidation_checked_at,
            )
            self.position_repo.save(updated_position)
        else:
            # 新建持仓 - 从信号继承证伪条件
            position = Position(
                account_id=account_id,
                asset_code=asset_code,
                asset_name=asset_name,
                asset_type=asset_type,
                quantity=quantity,
                available_quantity=quantity,  # 买入当天不可卖(T+1)
                avg_cost=price,
                total_cost=amount,
                current_price=price,
                market_value=amount,
                unrealized_pnl=0.0,
                unrealized_pnl_pct=0.0,
                first_buy_date=date.today(),
                last_update_date=date.today(),
                signal_id=signal_id,
                entry_reason=reason,
                # 从信号继承证伪条件
                invalidation_rule_json=invalidation_rule_json,
                invalidation_description=invalidation_description,
            )
            self.position_repo.save(position)

        # 7. 更新账户资金
        updated_account = replace(
            account,
            current_cash=account.current_cash - total_cost,
            current_market_value=account.current_market_value + amount,
            total_value=account.current_cash - total_cost + account.current_market_value + amount,
            total_trades=account.total_trades + 1,
            last_trade_date=date.today()
        )
        self.account_repo.save(updated_account)

        logger.info(
            f"买入成功: {account.account_name} -> {asset_name} x{quantity} @ {price:.2f}, "
            f"总成本: {total_cost:.2f}"
        )

        return trade

    def _get_signal_invalidation(self, signal_id: int):
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
            return self.signal_repo.get_signal_invalidation_payload(signal_id)
        except Exception:
            return None, ""


class ExecuteSellOrderUseCase:
    """执行卖出订单用例"""

    def __init__(
        self,
        account_repo: SimulatedAccountRepositoryProtocol,
        position_repo: PositionRepositoryProtocol,
        trade_repo: TradeRepositoryProtocol
    ):
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo

    def execute(
        self,
        account_id: int,
        asset_code: str,
        quantity: int,
        price: float,
        reason: str = ""
    ) -> SimulatedTrade:
        """
        执行卖出订单

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

        # 2. 验证订单
        valid, error_msg = TradingConstraintRule.validate_sell_order(
            position, quantity
        )
        if not valid:
            raise ValueError(f"卖出订单验证失败: {error_msg}")

        # 3. 计算费用
        amount = quantity * price
        commission = max(amount * account.commission_rate, 5.0)
        stamp_duty = amount * 0.001 if position.asset_type == "equity" else 0  # 股票印花税
        slippage = amount * account.slippage_rate
        total_cost = commission + stamp_duty + slippage

        # 4. 计算盈亏
        avg_cost_total = position.avg_cost * quantity
        net_amount = amount - total_cost
        realized_pnl = net_amount - avg_cost_total
        realized_pnl_pct = (realized_pnl / avg_cost_total) * 100 if avg_cost_total else 0

        # 5. 创建交易记录
        trade = SimulatedTrade(
            trade_id=0,
            account_id=account_id,
            asset_code=asset_code,
            asset_name=position.asset_name,
            asset_type=position.asset_type,
            action=TradeAction.SELL,
            quantity=quantity,
            price=price,
            amount=amount,
            commission=commission,
            slippage=slippage,
            total_cost=total_cost,
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            reason=reason,
            signal_id=position.signal_id,
            order_date=date.today(),
            execution_date=date.today(),
            execution_time=timezone.now(),
            status=OrderStatus.EXECUTED
        )

        # 6. 保存交易记录
        trade_id = self.trade_repo.save(trade)
        trade = SimulatedTrade(
            trade_id=trade_id,
            **{k: v for k, v in trade.__dict__.items() if k != 'trade_id'}
        )

        # 7. 更新持仓
        remaining_quantity = position.quantity - quantity
        if remaining_quantity > 0:
            # 部分卖出
            updated_position = Position(
                account_id=account_id,
                asset_code=asset_code,
                asset_name=position.asset_name,
                asset_type=position.asset_type,
                quantity=remaining_quantity,
                available_quantity=remaining_quantity,
                avg_cost=position.avg_cost,
                total_cost=position.avg_cost * remaining_quantity,
                current_price=price,
                market_value=remaining_quantity * price,
                unrealized_pnl=(price - position.avg_cost) * remaining_quantity,
                unrealized_pnl_pct=((price - position.avg_cost) / position.avg_cost) * 100,
                first_buy_date=position.first_buy_date,
                last_update_date=date.today(),
                signal_id=position.signal_id,
                entry_reason=position.entry_reason
            )
            self.position_repo.save(updated_position)
        else:
            # 全部卖出，删除持仓
            self.position_repo.delete(account_id, asset_code)

        # 8. 更新账户资金
        new_market_value = account.current_market_value - position.quantity * price
        if remaining_quantity > 0:
            new_market_value += remaining_quantity * price

        updated_account = replace(
            account,
            current_cash=account.current_cash + net_amount,
            current_market_value=new_market_value,
            total_value=account.current_cash + net_amount + new_market_value,
            total_trades=account.total_trades + 1,
            winning_trades=account.winning_trades + (1 if realized_pnl > 0 else 0),
            last_trade_date=date.today()
        )
        self.account_repo.save(updated_account)

        logger.info(
            f"卖出成功: {account.account_name} -> {position.asset_name} x{quantity} @ {price:.2f}, "
            f"盈亏: {realized_pnl:.2f} ({realized_pnl_pct:.2f}%)"
        )

        return trade


class ListAccountsUseCase:
    """列出所有账户用例"""

    def __init__(self, account_repo: SimulatedAccountRepositoryProtocol):
        self.account_repo = account_repo

    def execute(self, active_only: bool = True) -> List[SimulatedAccount]:
        """
        列出所有账户

        Args:
            active_only: 是否只返回活跃账户

        Returns:
            账户列表
        """
        if active_only:
            return self.account_repo.get_active_accounts()
        else:
            return self.account_repo.get_all_accounts()

