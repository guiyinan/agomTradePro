"""
Account Application - Stop Loss Use Cases

自动止损止盈用例编排。
"""

from decimal import Decimal
from typing import List, Dict, Optional
from datetime import datetime
from dataclasses import dataclass

from apps.account.domain.entities import (
    Position,
    StopLossConfig,
    StopLossTrigger,
    StopLossType,
    StopLossStatus,
)
from apps.account.domain.services import (
    StopLossService,
    StopLossCheckResult,
    TakeProfitService,
    TakeProfitCheckResult,
)
from apps.account.infrastructure.models import (
    PositionModel,
    StopLossConfigModel,
    TakeProfitConfigModel,
    StopLossTriggerModel,
)


@dataclass
class StopLossCheckOutput:
    """止损检查输出"""
    position_id: int
    asset_code: str
    should_close: bool
    check_result: StopLossCheckResult
    current_price: float
    unrealized_pnl: Decimal
    unrealized_pnl_pct: float


@dataclass
class TakeProfitCheckOutput:
    """止盈检查输出"""
    position_id: int
    asset_code: str
    should_close: bool
    check_result: TakeProfitCheckResult
    current_price: float
    unrealized_pnl: Decimal
    unrealized_pnl_pct: float
    partial_level: Optional[int] = None


class AutoStopLossUseCase:
    """
    自动止损用例

    定期检查所有激活的止损配置，触发止损时自动平仓。
    """

    def __init__(self, position_repo=None):
        # 暂时直接使用 ORM，后续通过依赖注入传入
        self.position_repo = position_repo

    def check_and_execute_stop_loss(self, user_id: Optional[int] = None) -> List[StopLossCheckOutput]:
        """
        检查并执行止损

        Args:
            user_id: 指定用户ID，None表示检查所有用户

        Returns:
            List[StopLossCheckOutput]: 检查结果列表
        """
        # 获取所有激活的止损配置
        queryset = StopLossConfigModel._default_manager.filter(status='active')
        if user_id:
            queryset = queryset.filter(position__portfolio__user_id=user_id)

        active_configs = queryset.select_related('position', 'position__portfolio').all()

        results = []

        for config in active_configs:
            result = self._check_single_position(config)
            if result:
                results.append(result)

                # 如果触发止损，执行平仓
                if result.should_close:
                    self._execute_stop_loss(config, result)

        return results

    def _check_single_position(self, config: StopLossConfigModel) -> Optional[StopLossCheckOutput]:
        """
        检查单个持仓的止损

        Args:
            config: 止损配置

        Returns:
            StopLossCheckOutput or None
        """
        position = config.position

        # 获取当前价格（TODO: 从行情接口获取）
        current_price = float(position.current_price or position.avg_cost)
        entry_price = float(position.avg_cost)
        highest_price = float(config.highest_price or entry_price)

        # 检查价格止损
        if config.stop_loss_type in ['fixed', 'trailing']:
            check_result = StopLossService.check_stop_loss(
                entry_price=entry_price,
                current_price=current_price,
                highest_price=highest_price,
                stop_loss_pct=config.stop_loss_pct,
                stop_loss_type=config.stop_loss_type,
                trailing_stop_pct=config.trailing_stop_pct,
            )

        # 检查时间止损
        elif config.stop_loss_type == 'time_based' and config.max_holding_days:
            check_result = StopLossService.check_time_stop_loss(
                opened_at=position.opened_at,
                current_time=datetime.now(),
                max_holding_days=config.max_holding_days,
            )
        else:
            return None

        # 更新移动止损的最高价
        if config.stop_loss_type == 'trailing':
            new_highest, new_time = StopLossService.update_trailing_stop_highest(
                current_highest=highest_price,
                current_price=current_price,
                current_price_time=datetime.now(),
                last_update_time=config.highest_price_updated_at,
            )
            if new_highest != highest_price:
                config.highest_price = Decimal(str(new_highest))
                config.highest_price_updated_at = new_time
                config.save(update_fields=['highest_price', 'highest_price_updated_at'])

        # 计算盈亏
        unrealized_pnl = Decimal(str(check_result.unrealized_pnl_pct)) * Decimal(str(position.shares * float(position.avg_cost)))

        return StopLossCheckOutput(
            position_id=position.id,
            asset_code=position.asset_code,
            should_close=check_result.should_trigger,
            check_result=check_result,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=check_result.unrealized_pnl_pct,
        )

    def _execute_stop_loss(self, config: StopLossConfigModel, check_result: StopLossCheckOutput):
        """
        执行止损平仓

        Args:
            config: 止损配置
            check_result: 检查结果
        """
        from apps.account.infrastructure.repositories import PositionRepository

        position = config.position
        current_price = Decimal(str(check_result.current_price))

        # 执行平仓
        repo = PositionRepository()
        closed_position = repo.close_position(
            position_id=position.id,
            shares=None,  # 全部平仓
            price=current_price,
            reason=f"止损触发: {check_result.check_result.trigger_reason}",
        )

        # 更新止损配置状态
        config.status = 'triggered'
        config.triggered_at = datetime.now()
        config.save(update_fields=['status', 'triggered_at'])

        # 创建触发记录
        StopLossTriggerModel._default_manager.create(
            position=position,
            trigger_type=config.stop_loss_type,
            trigger_price=current_price,
            trigger_time=datetime.now(),
            trigger_reason=check_result.check_result.trigger_reason,
            pnl=check_result.unrealized_pnl,
            pnl_pct=check_result.unrealized_pnl_pct,
            notes=f"自动止损执行",
        )

        # TODO: 发送通知


class AutoTakeProfitUseCase:
    """
    自动止盈用例

    定期检查所有激活的止盈配置，触发止盈时自动平仓或部分平仓。
    """

    def __init__(self, position_repo=None):
        self.position_repo = position_repo

    def check_and_execute_take_profit(self, user_id: Optional[int] = None) -> List[TakeProfitCheckOutput]:
        """
        检查并执行止盈

        Args:
            user_id: 指定用户ID，None表示检查所有用户

        Returns:
            List[TakeProfitCheckOutput]: 检查结果列表
        """
        # 获取所有激活的止盈配置
        queryset = TakeProfitConfigModel._default_manager.filter(is_active=True)
        if user_id:
            queryset = queryset.filter(position__portfolio__user_id=user_id)

        active_configs = queryset.select_related('position', 'position__portfolio').all()

        results = []

        for config in active_configs:
            result = self._check_single_position(config)
            if result and result.should_close:
                results.append(result)
                # 执行止盈
                self._execute_take_profit(config, result)

        return results

    def _check_single_position(self, config: TakeProfitConfigModel) -> Optional[TakeProfitCheckOutput]:
        """
        检查单个持仓的止盈

        Args:
            config: 止盈配置

        Returns:
            TakeProfitCheckOutput or None
        """
        position = config.position

        # 获取当前价格
        current_price = float(position.current_price or position.avg_cost)
        entry_price = float(position.avg_cost)

        # 检查止盈
        check_result = TakeProfitService.check_take_profit(
            entry_price=entry_price,
            current_price=current_price,
            take_profit_pct=config.take_profit_pct,
            partial_levels=config.partial_profit_levels,
        )

        # 计算盈亏
        unrealized_pnl = Decimal(str(check_result.unrealized_pnl_pct)) * Decimal(str(position.shares * float(position.avg_cost)))

        return TakeProfitCheckOutput(
            position_id=position.id,
            asset_code=position.asset_code,
            should_close=check_result.should_trigger,
            check_result=check_result,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=check_result.unrealized_pnl_pct,
            partial_level=check_result.partial_level,
        )

    def _execute_take_profit(self, config: TakeProfitConfigModel, check_result: TakeProfitCheckOutput):
        """
        执行止盈平仓

        Args:
            config: 止盈配置
            check_result: 检查结果
        """
        from apps.account.infrastructure.repositories import PositionRepository

        position = config.position
        current_price = Decimal(str(check_result.current_price))

        # 如果是分批止盈，计算平仓数量
        if check_result.partial_level and config.partial_profit_levels:
            # 简化处理：每批平仓 1/3
            sell_shares = position.shares / len(config.partial_profit_levels)
        else:
            # 全部止盈
            sell_shares = None

        # 执行平仓
        repo = PositionRepository()
        repo.close_position(
            position_id=position.id,
            shares=sell_shares,
            price=current_price,
            reason=f"止盈触发: {check_result.check_result.trigger_reason}",
        )

        # 如果全部止盈，禁用配置
        if sell_shares is None:
            config.is_active = False
            config.save(update_fields=['is_active'])

        # TODO: 发送通知


class CreateStopLossConfigUseCase:
    """
    创建止损配置用例
    """

    def execute(
        self,
        position_id: int,
        stop_loss_type: str,
        stop_loss_pct: float,
        trailing_stop_pct: Optional[float] = None,
        max_holding_days: Optional[int] = None,
    ) -> StopLossConfigModel:
        """
        创建止损配置

        Args:
            position_id: 持仓ID
            stop_loss_type: 止损类型 (fixed/trailing/time_based)
            stop_loss_pct: 止损百分比
            trailing_stop_pct: 移动止损百分比
            max_holding_days: 最大持仓天数

        Returns:
            StopLossConfigModel: 创建的止损配置
        """
        # 获取持仓
        try:
            position = PositionModel._default_manager.get(id=position_id)
        except PositionModel.DoesNotExist:
            raise ValueError(f"持仓 {position_id} 不存在")

        # 检查是否已有止损配置
        if hasattr(position, 'stop_loss_config'):
            raise ValueError(f"持仓 {position_id} 已有止损配置")

        # 创建止损配置
        config = StopLossConfigModel._default_manager.create(
            position_id=position_id,
            stop_loss_type=stop_loss_type,
            stop_loss_pct=stop_loss_pct,
            trailing_stop_pct=trailing_stop_pct,
            max_holding_days=max_holding_days,
            highest_price=position.avg_cost,  # 初始最高价为开仓价
            status='active',
        )

        return config


class CreateTakeProfitConfigUseCase:
    """
    创建止盈配置用例
    """

    def execute(
        self,
        position_id: int,
        take_profit_pct: float,
        partial_profit_levels: Optional[List[float]] = None,
    ) -> TakeProfitConfigModel:
        """
        创建止盈配置

        Args:
            position_id: 持仓ID
            take_profit_pct: 止盈百分比
            partial_profit_levels: 分批止盈点位

        Returns:
            TakeProfitConfigModel: 创建的止盈配置
        """
        # 获取持仓
        try:
            position = PositionModel._default_manager.get(id=position_id)
        except PositionModel.DoesNotExist:
            raise ValueError(f"持仓 {position_id} 不存在")

        # 检查是否已有止盈配置
        if hasattr(position, 'take_profit_config'):
            raise ValueError(f"持仓 {position_id} 已有止盈配置")

        # 创建止盈配置
        config = TakeProfitConfigModel._default_manager.create(
            position_id=position_id,
            take_profit_pct=take_profit_pct,
            partial_profit_levels=partial_profit_levels,
            is_active=True,
        )

        return config

