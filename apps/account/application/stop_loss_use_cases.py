"""
Account Application - Stop Loss Use Cases

自动止损止盈用例编排。
集成行情数据服务和通知服务。
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from apps.account.domain.entities import (
    Position,
    StopLossConfig,
    StopLossStatus,
    StopLossTrigger,
    StopLossType,
)
from apps.account.domain.interfaces import (
    MarketDataPort,
    StopLossNotificationData,
    StopLossNotificationPort,
)
from apps.account.domain.services import (
    StopLossCheckResult,
    StopLossService,
    TakeProfitCheckResult,
    TakeProfitService,
)
from apps.account.infrastructure.market_price_service import MarketPriceService
from apps.account.infrastructure.models import (
    PositionModel,
    StopLossConfigModel,
    StopLossTriggerModel,
    TakeProfitConfigModel,
)
from apps.account.infrastructure.notification_service import InMemoryStopLossNotificationService
from core.exceptions import DataFetchError

logger = logging.getLogger(__name__)


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
    partial_level: int | None = None


class AutoStopLossUseCase:
    """
    自动止损用例

    定期检查所有激活的止损配置，触发止损时自动平仓。
    """

    def __init__(
        self,
        market_data_service: MarketDataPort | None = None,
        notification_service: StopLossNotificationPort | None = None,
    ):
        """
        初始化自动止损用例

        Args:
            market_data_service: 行情数据服务（默认使用 MarketPriceService）
            notification_service: 通知服务（默认使用内存通知服务）
        """
        self.market_data_service = market_data_service or _MarketDataAdapter()
        self.notification_service = notification_service or InMemoryStopLossNotificationService()

    def check_and_execute_stop_loss(self, user_id: int | None = None) -> list[StopLossCheckOutput]:
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

    def _check_single_position(self, config: StopLossConfigModel) -> StopLossCheckOutput | None:
        """
        检查单个持仓的止损

        Args:
            config: 止损配置

        Returns:
            StopLossCheckOutput or None
        """
        position = config.position

        # 从行情接口获取当前价格
        current_price = self._get_current_price(position.asset_code)
        if current_price is None:
            logger.warning(f"无法获取资产 {position.asset_code} 的价格，跳过止损检查")
            return None

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
                current_time=datetime.now(UTC),
                max_holding_days=config.max_holding_days,
            )
        else:
            return None

        # 更新移动止损的最高价
        if config.stop_loss_type == 'trailing':
            new_highest, new_time = StopLossService.update_trailing_stop_highest(
                current_highest=highest_price,
                current_price=current_price,
                current_price_time=datetime.now(UTC),
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

    def _get_current_price(self, asset_code: str) -> float | None:
        """
        从行情接口获取当前价格

        Args:
            asset_code: 资产代码

        Returns:
            float: 当前价格，获取失败返回 None
        """
        try:
            price = self.market_data_service.get_current_price(asset_code)
            if price is not None:
                return float(price)
            return None
        except Exception as e:
            logger.error(f"获取资产 {asset_code} 价格失败: {e}")
            return None

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
        config.triggered_at = datetime.now(UTC)
        config.save(update_fields=['status', 'triggered_at'])

        # 创建触发记录
        StopLossTriggerModel._default_manager.create(
            position=position,
            trigger_type=config.stop_loss_type,
            trigger_price=current_price,
            trigger_time=datetime.now(UTC),
            trigger_reason=check_result.check_result.trigger_reason,
            pnl=check_result.unrealized_pnl,
            pnl_pct=check_result.unrealized_pnl_pct,
            notes="自动止损执行",
        )

        # 发送通知
        self._send_stop_loss_notification(
            position=position,
            config=config,
            check_result=check_result,
        )

    def _send_stop_loss_notification(
        self,
        position: PositionModel,
        config: StopLossConfigModel,
        check_result: StopLossCheckOutput,
    ):
        """
        发送止损触发通知

        Args:
            position: 持仓模型
            config: 止损配置
            check_result: 检查结果
        """
        try:
            # 获取用户邮箱
            user_email = position.portfolio.user.email

            # 构造通知数据
            notification_data = StopLossNotificationData(
                user_id=position.portfolio.user_id,
                user_email=user_email,
                position_id=position.id,
                asset_code=position.asset_code,
                trigger_type=config.stop_loss_type,
                trigger_price=Decimal(str(check_result.current_price)),
                trigger_time=datetime.now(UTC),
                trigger_reason=check_result.check_result.trigger_reason,
                pnl=check_result.unrealized_pnl,
                pnl_pct=check_result.unrealized_pnl_pct,
                shares_closed=position.shares,  # 全部平仓
            )

            # 发送通知
            success = self.notification_service.notify_stop_loss_triggered(notification_data)
            if success:
                logger.info(f"止损通知已发送: 用户 {position.portfolio.user_id}, 持仓 {position.id}")
            else:
                logger.warning(f"止损通知发送失败: 用户 {position.portfolio.user_id}, 持仓 {position.id}")

        except Exception as e:
            # 通知失败不应影响止损执行
            logger.error(f"发送止损通知异常: {e}", exc_info=True)


class AutoTakeProfitUseCase:
    """
    自动止盈用例

    定期检查所有激活的止盈配置，触发止盈时自动平仓或部分平仓。
    """

    def __init__(
        self,
        market_data_service: MarketDataPort | None = None,
        notification_service: StopLossNotificationPort | None = None,
    ):
        """
        初始化自动止盈用例

        Args:
            market_data_service: 行情数据服务（默认使用 MarketPriceService）
            notification_service: 通知服务（默认使用内存通知服务）
        """
        self.market_data_service = market_data_service or _MarketDataAdapter()
        self.notification_service = notification_service or InMemoryStopLossNotificationService()

    def check_and_execute_take_profit(self, user_id: int | None = None) -> list[TakeProfitCheckOutput]:
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

    def _check_single_position(self, config: TakeProfitConfigModel) -> TakeProfitCheckOutput | None:
        """
        检查单个持仓的止盈

        Args:
            config: 止盈配置

        Returns:
            TakeProfitCheckOutput or None
        """
        position = config.position

        # 从行情接口获取当前价格
        current_price = self._get_current_price(position.asset_code)
        if current_price is None:
            logger.warning(f"无法获取资产 {position.asset_code} 的价格，跳过止盈检查")
            return None

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

    def _get_current_price(self, asset_code: str) -> float | None:
        """
        从行情接口获取当前价格

        Args:
            asset_code: 资产代码

        Returns:
            float: 当前价格，获取失败返回 None
        """
        try:
            price = self.market_data_service.get_current_price(asset_code)
            if price is not None:
                return float(price)
            return None
        except Exception as e:
            logger.error(f"获取资产 {asset_code} 价格失败: {e}")
            return None

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

        # 发送通知
        self._send_take_profit_notification(
            position=position,
            config=config,
            check_result=check_result,
            sell_shares=sell_shares,
        )

    def _send_take_profit_notification(
        self,
        position: PositionModel,
        config: TakeProfitConfigModel,
        check_result: TakeProfitCheckOutput,
        sell_shares: float | None,
    ):
        """
        发送止盈触发通知

        Args:
            position: 持仓模型
            config: 止盈配置
            check_result: 检查结果
            sell_shares: 平仓数量
        """
        try:
            # 获取用户邮箱
            user_email = position.portfolio.user.email

            # 构造通知数据
            notification_data = StopLossNotificationData(
                user_id=position.portfolio.user_id,
                user_email=user_email,
                position_id=position.id,
                asset_code=position.asset_code,
                trigger_type="take_profit",
                trigger_price=Decimal(str(check_result.current_price)),
                trigger_time=datetime.now(UTC),
                trigger_reason=check_result.check_result.trigger_reason,
                pnl=check_result.unrealized_pnl,
                pnl_pct=check_result.unrealized_pnl_pct,
                shares_closed=sell_shares,
            )

            # 发送通知
            success = self.notification_service.notify_take_profit_triggered(notification_data)
            if success:
                logger.info(f"止盈通知已发送: 用户 {position.portfolio.user_id}, 持仓 {position.id}")
            else:
                logger.warning(f"止盈通知发送失败: 用户 {position.portfolio.user_id}, 持仓 {position.id}")

        except Exception as e:
            # 通知失败不应影响止盈执行
            logger.error(f"发送止盈通知异常: {e}", exc_info=True)


class CreateStopLossConfigUseCase:
    """
    创建止损配置用例
    """

    def execute(
        self,
        position_id: int,
        stop_loss_type: str,
        stop_loss_pct: float,
        trailing_stop_pct: float | None = None,
        max_holding_days: int | None = None,
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
        partial_profit_levels: list[float] | None = None,
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


# =============================================================================
# Internal Adapter - 将 MarketPriceService 适配为 MarketDataPort
# =============================================================================

class _MarketDataAdapter(MarketDataPort):
    """
    MarketPriceService 适配器

    将 MarketPriceService 适配为 MarketDataPort 协议接口。
    这是一个内部适配器，用于在不修改现有 MarketPriceService 的情况下
    满足新的协议接口要求。
    """

    def __init__(self):
        self._service = MarketPriceService()

    def get_current_price(self, asset_code: str) -> Decimal | None:
        """获取当前价格"""
        try:
            return self._service.get_current_price(asset_code)
        except Exception as e:
            logger.error(f"获取资产 {asset_code} 价格失败: {e}")
            return None

    def get_prices_batch(self, asset_codes: list[str]) -> dict[str, Decimal | None]:
        """批量获取价格"""
        return self._service.get_prices_batch(asset_codes)

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return self._service.is_available()
