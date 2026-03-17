"""
Simulated Trading Facade.

Application 层门面服务，为 strategy 模块和其他模块提供访问模拟交易数据的统一接口。

重构说明 (2026-03-11):
- 将 Position 和 Account 数据聚合到门面服务
- 隐藏 Django ORM 实现细节
- 提供简化的 API 给外部模块使用

使用方式:
    # 在 strategy 模块
    from apps.simulated_trading.application.facade import SimulatedTradingFacade

    facade = SimulatedTradingFacade()
    positions = facade.get_positions(account_id)
    cash = facade.get_cash(account_id)
    account_summary = facade.get_account_summary(account_id)
"""

from dataclasses import dataclass
from typing import List, Optional
from decimal import Decimal

from apps.simulated_trading.infrastructure.repositories import (
    DjangoSimulatedAccountRepository,
    DjangoPositionRepository,
)

logger = __import__('logging').getLogger(__name__)


# ============================================================================
# Data Transfer Objects
# ============================================================================

@dataclass(frozen=True)
class PositionSummary:
    """持仓摘要"""
    asset_code: str
    asset_name: str
    quantity: int
    avg_cost: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Optional[Decimal] = None
    asset_type: str = "equity"
    is_closed: bool = False


@dataclass(frozen=True)
class AccountSummary:
    """账户摘要"""
    account_id: int
    account_name: str
    total_value: Decimal
    current_cash: Decimal
    market_value: Decimal
    active_strategy_id: Optional[int]
    position_count: int
    is_active: bool


@dataclass(frozen=True)
class AccountOverview:
    """账户概览（用于 dashboard）"""
    account_id: int
    account_name: str
    initial_capital: Decimal
    current_cash: Decimal
    market_value: Decimal
    total_value: Decimal
    position_count: int
    active_strategy_id: Optional[int] = None
    total_return_pct: Optional[Decimal] = None


@dataclass(frozen=True)
class StrategyBindingSummary:
    """账户绑定的策略摘要"""
    strategy_id: int
    name: str
    strategy_type: str
    is_active: bool


# ============================================================================
# Facade Service
# ============================================================================

class SimulatedTradingFacade:
    """
    模拟交易门面服务

    提供统一的接口访问模拟交易数据， 隐藏 Django ORM 实现细节。
    策略模块应使用此 Facade 而非直接导入 ORM 模型。

    Example:
        >>> facade = SimulatedTradingFacade()
        >>> positions = facade.get_positions(account_id=1)
        >>> for pos in positions:
        ...     print(f"{pos.asset_code}: {pos.market_value}")
    """

    def __init__(
        self,
        account_repo: Optional[DjangoSimulatedAccountRepository] = None,
        position_repo: Optional[DjangoPositionRepository] = None,
    ) -> None:
        self.account_repo = account_repo or DjangoSimulatedAccountRepository()
        self.position_repo = position_repo or DjangoPositionRepository()

    def _get_active_strategy_binding(self, account_id: int) -> Optional[StrategyBindingSummary]:
        """通过 strategy gateway 获取账户当前激活的策略绑定。"""
        try:
            from apps.strategy.application.execution_gateway import get_strategy_execution_gateway

            gateway = get_strategy_execution_gateway()
            info = gateway.get_active_strategy_binding(account_id)
            if not info:
                return None

            return StrategyBindingSummary(
                strategy_id=info["strategy_id"],
                name=info["name"],
                strategy_type=info["strategy_type"],
                is_active=info["is_active"],
            )
        except Exception as e:
            logger.error(f"Error getting active strategy binding: {e}")
            return None

    def get_account_summary(self, account_id: int) -> Optional[AccountSummary]:
        """
        获取账户摘要

        Args:
            account_id: 账户 ID

        Returns:
            AccountSummary 或 None
        """
        try:
            account = self.account_repo.get_by_id(account_id)
            if not account:
                return None

            positions = self.position_repo.get_by_account(account_id)
            market_value = sum(Decimal(str(pos.market_value or 0)) for pos in positions)
            active_strategy = self._get_active_strategy_binding(account_id)

            return AccountSummary(
                account_id=account.account_id,
                account_name=account.account_name,
                total_value=Decimal(str(account.current_cash)) + market_value,
                current_cash=Decimal(str(account.current_cash)),
                market_value=market_value,
                active_strategy_id=(
                    active_strategy.strategy_id if active_strategy else None
                ),
                position_count=len(positions),
                is_active=account.auto_trading_enabled,
            )

        except Exception as e:
            logger.error(f"Error getting account summary: {e}")
            return None

    def get_positions(self, account_id: int) -> List[PositionSummary]:
        """
        获取账户持仓列表

        Args:
            account_id: 账户 ID

        Returns:
            PositionSummary 列表
        """
        try:
            positions = self.position_repo.get_by_account(account_id)

            return [
                PositionSummary(
                    asset_code=pos.asset_code,
                    asset_name=pos.asset_name or pos.asset_code,
                    quantity=int(pos.quantity),
                    avg_cost=Decimal(str(pos.avg_cost or 0)),
                    current_price=Decimal(str(pos.current_price or 0)),
                    market_value=Decimal(str(pos.market_value or 0)),
                    unrealized_pnl=Decimal(str(pos.unrealized_pnl or 0)),
                    unrealized_pnl_pct=Decimal(str(pos.unrealized_pnl_pct)) if pos.unrealized_pnl_pct is not None else None,
                    asset_type=pos.asset_type or 'equity',
                    is_closed=False,
                )
                for pos in positions
                if pos.quantity > 0
            ]

        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    def get_cash(self, account_id: int) -> Decimal:
        """
        获取账户现金余额

        Args:
            account_id: 账户 ID

        Returns:
            现金余额
        """
        try:
            account = self.account_repo.get_by_id(account_id)
            if account:
                return Decimal(str(account.current_cash or 0))
            return Decimal('0')

        except Exception as e:
            logger.error(f"Error getting cash: {e}")
            return Decimal('0')

    def get_active_strategy_id(self, account_id: int) -> Optional[int]:
        """
        获取账户绑定的活跃策略 ID

        Args:
            account_id: 账户 ID

        Returns:
            策略 ID 或 None
        """
        binding = self._get_active_strategy_binding(account_id)
        return binding.strategy_id if binding else None

    def get_active_strategy_summary(self, account_id: int) -> Optional[StrategyBindingSummary]:
        """获取账户当前绑定策略的摘要信息。"""
        return self._get_active_strategy_binding(account_id)

    def user_owns_account(self, account_id: int, user_id: int) -> bool:
        """判断账户是否属于指定用户。"""
        try:
            return self.account_repo.user_owns_account(account_id, user_id)
        except Exception as e:
            logger.error(f"Error checking account ownership: {e}")
            return False

    def get_account_overview(self, account_id: int) -> Optional[AccountOverview]:
        """
        获取账户概览（用于 dashboard）

        Args:
            account_id: 账户 ID

        Returns:
            AccountOverview 或 None
        """
        try:
            account = self.account_repo.get_by_id(account_id)
            if not account:
                return None

            active_strategy = self._get_active_strategy_binding(account_id)
            positions = self.position_repo.get_by_account(account_id)

            # 计算总收益
            initial_capital = Decimal(str(account.initial_capital or 1000000))
            total_value = Decimal(str(account.current_cash)) + Decimal(str(account.current_market_value or 0))
            total_return_pct = None
            if initial_capital and initial_capital > 0:
                total_return_pct = (total_value - initial_capital) / initial_capital * 100

            return AccountOverview(
                account_id=account.account_id,
                account_name=account.account_name,
                initial_capital=initial_capital,
                current_cash=Decimal(str(account.current_cash)),
                market_value=Decimal(str(account.current_market_value or 0)),
                total_value=total_value,
                total_return_pct=total_return_pct,
                position_count=len([pos for pos in positions if pos.quantity > 0]),
                active_strategy_id=(
                    active_strategy.strategy_id if active_strategy else None
                ),
            )

        except Exception as e:
            logger.error(f"Error getting account overview: {e}")
            return None

    def get_all_active_accounts(self) -> List[AccountOverview]:
        """
        获取所有活跃账户概览

        Returns:
            AccountOverview 列表
        """
        try:
            accounts = self.account_repo.get_active_accounts()

            return [
                overview
                for account in accounts
                if (overview := self.get_account_overview(account.account_id))
            ]

        except Exception as e:
            logger.error(f"Error getting all active accounts: {e}")
            return []

    def position_exists(self, account_id: int, asset_code: str) -> bool:
        """
        检查账户是否持有指定资产

        Args:
            account_id: 账户 ID
            asset_code: 资产代码

        Returns:
            是否存在持仓
        """
        try:
            position = self.position_repo.get_position(account_id, asset_code)
            return position is not None and position.quantity > 0

        except Exception as e:
            logger.error(f"Error checking position exists: {e}")
            return False


# ============================================================================
# 全局单例
# ============================================================================

_facade_instance: Optional[SimulatedTradingFacade] = None


def get_simulated_trading_facade() -> SimulatedTradingFacade:
    """
    获取模拟交易门面服务单例

    Returns:
        SimulatedTradingFacade 实例
    """
    global _facade_instance
    if _facade_instance is None:
        _facade_instance = SimulatedTradingFacade()
    return _facade_instance
