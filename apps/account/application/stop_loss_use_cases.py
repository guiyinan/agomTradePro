"""
Account Application - Stop Loss Use Cases

自动止损止盈用例编排。
集成行情数据服务和通知服务。
"""

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, cast

from apps.account.application.repository_provider import (
    PositionRepository,
    StopLossRepository,
    TakeProfitRepository,
    build_in_memory_stop_loss_notification_service,
    build_market_price_service,
)
from apps.account.domain.interfaces import (
    MarketDataPort,
    PositionRepositoryProtocol,
    StopLossNotificationData,
    StopLossNotificationPort,
    StopLossRepositoryProtocol,
    TakeProfitRepositoryProtocol,
)
from apps.account.domain.services import (
    StopLossCheckResult,
    StopLossService,
    TakeProfitCheckResult,
    TakeProfitService,
)

logger = logging.getLogger(__name__)


class RiskPolicyProviderProtocol(Protocol):
    """Risk-policy lookup required by stop-loss and take-profit checks."""

    def get_effective_parameters(self, account_id: int) -> dict[str, Any]: ...


class _RiskCenterPolicyProvider:
    """Read effective risk parameters without coupling account to risk-center ORM."""

    def get_effective_parameters(self, account_id: int) -> dict[str, Any]:
        from apps.risk_center.application.use_cases import (
            ResolveEffectiveRiskPolicyForAccountUseCase,
        )

        payload = ResolveEffectiveRiskPolicyForAccountUseCase().execute(account_id=account_id)
        parameters: object = payload.get("parameters", {})
        if not isinstance(parameters, dict):
            return {}
        return {str(key): value for key, value in parameters.items()}


def MarketPriceService() -> MarketDataPort:
    """Backward-compatible market price service factory for legacy tests/callers."""

    return cast(MarketDataPort, build_market_price_service())


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
        stop_loss_repo: StopLossRepositoryProtocol | None = None,
        position_repo: PositionRepositoryProtocol | None = None,
        risk_policy_provider: RiskPolicyProviderProtocol | None = None,
    ) -> None:
        """
        初始化自动止损用例

        Args:
            market_data_service: 行情数据服务（默认使用 MarketPriceService）
            notification_service: 通知服务（默认使用内存通知服务）
        """
        self.market_data_service = market_data_service or _MarketDataAdapter()
        self.notification_service = (
            notification_service or build_in_memory_stop_loss_notification_service()
        )
        self.stop_loss_repo = stop_loss_repo or StopLossRepository()
        self.position_repo = position_repo or PositionRepository()
        self.risk_policy_provider = risk_policy_provider or _RiskCenterPolicyProvider()

    def check_and_execute_stop_loss(self, user_id: int | None = None) -> list[StopLossCheckOutput]:
        """
        检查并执行止损

        Args:
            user_id: 指定用户ID，None表示检查所有用户

        Returns:
            List[StopLossCheckOutput]: 检查结果列表
        """
        # 获取所有激活的止损配置
        active_configs = self.stop_loss_repo.get_active_stop_loss_configs(user_id=user_id)

        results: list[StopLossCheckOutput] = []

        for config in active_configs:
            result = self._check_single_position(config)
            if result:
                results.append(result)

                # 如果触发止损，执行平仓
                if result.should_close:
                    self._execute_stop_loss(config, result)

        return results

    def _check_single_position(self, config: dict[str, Any]) -> StopLossCheckOutput | None:
        """
        检查单个持仓的止损

        Args:
            config: 止损配置

        Returns:
            StopLossCheckOutput or None
        """
        position = config["position"]

        # 从行情接口获取当前价格
        current_price = self._get_current_price(position["asset_code"])
        if current_price is None:
            logger.warning(f"无法获取资产 {position['asset_code']} 的价格，跳过止损检查")
            return None

        entry_price = float(position["avg_cost"])
        highest_price = float(config["highest_price"] or entry_price)
        stop_loss_pct = self._resolve_stop_loss_pct(config)

        # 检查价格止损
        if config["stop_loss_type"] in ["fixed", "trailing"]:
            check_result = StopLossService.check_stop_loss(
                entry_price=entry_price,
                current_price=current_price,
                highest_price=highest_price,
                stop_loss_pct=stop_loss_pct,
                stop_loss_type=config["stop_loss_type"],
                trailing_stop_pct=config["trailing_stop_pct"],
            )

        # 检查时间止损
        elif config["stop_loss_type"] == "time_based" and config["max_holding_days"]:
            check_result = StopLossService.check_time_stop_loss(
                opened_at=position["opened_at"],
                current_time=datetime.now(UTC),
                max_holding_days=config["max_holding_days"],
            )
        else:
            return None

        # 更新移动止损的最高价
        if config["stop_loss_type"] == "trailing":
            new_highest, new_time = StopLossService.update_trailing_stop_highest(
                current_highest=highest_price,
                current_price=current_price,
                current_price_time=datetime.now(UTC),
                last_update_time=config["highest_price_updated_at"],
            )
            if new_highest != highest_price:
                highest_price_decimal = Decimal(str(new_highest))
                self.stop_loss_repo.update_stop_loss_config(
                    config["id"],
                    highest_price=highest_price_decimal,
                    highest_price_updated_at=new_time,
                )
                config["highest_price"] = highest_price_decimal
                config["highest_price_updated_at"] = new_time

        # 计算盈亏
        unrealized_pnl = Decimal(str(check_result.unrealized_pnl_pct)) * Decimal(
            str(position["shares"] * float(position["avg_cost"]))
        )

        return StopLossCheckOutput(
            position_id=position["id"],
            asset_code=position["asset_code"],
            should_close=check_result.should_trigger,
            check_result=check_result,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=check_result.unrealized_pnl_pct,
        )

    def _resolve_stop_loss_pct(self, config: dict[str, Any]) -> float:
        configured_pct = float(config["stop_loss_pct"])
        account_id = config["position"].get("portfolio_id")
        if not account_id:
            return configured_pct
        try:
            parameters = self.risk_policy_provider.get_effective_parameters(int(account_id))
        except Exception as exc:
            logger.warning("无法读取风控中心有效策略，沿用持仓止损配置: %s", exc)
            return configured_pct
        max_stop_loss_pct = parameters.get("max_stop_loss_pct")
        if max_stop_loss_pct is None:
            return configured_pct
        return min(configured_pct, float(max_stop_loss_pct))

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

    def _execute_stop_loss(
        self,
        config: dict[str, Any],
        check_result: StopLossCheckOutput,
    ) -> None:
        """
        执行止损平仓

        Args:
            config: 止损配置
            check_result: 检查结果
        """
        position = config["position"]
        current_price = Decimal(str(check_result.current_price))

        # 执行平仓
        self.position_repo.close_position(
            position_id=position["id"],
            shares=None,  # 全部平仓
            price=current_price,
            reason=f"止损触发: {check_result.check_result.trigger_reason}",
        )

        # 更新止损配置状态
        self.stop_loss_repo.update_stop_loss_config(
            config["id"],
            status="triggered",
            triggered_at=datetime.now(UTC),
        )

        # 创建触发记录
        self.stop_loss_repo.create_stop_loss_trigger(
            position_id=position["id"],
            trigger_type=config["stop_loss_type"],
            trigger_price=current_price,
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
        position: dict[str, Any],
        config: dict[str, Any],
        check_result: StopLossCheckOutput,
    ) -> None:
        """
        发送止损触发通知

        Args:
            position: 持仓模型
            config: 止损配置
            check_result: 检查结果
        """
        try:
            # 获取用户邮箱
            user_email = position["user_email"]

            # 构造通知数据
            notification_data = StopLossNotificationData(
                user_id=position["user_id"],
                user_email=user_email,
                position_id=position["id"],
                asset_code=position["asset_code"],
                trigger_type=config["stop_loss_type"],
                trigger_price=Decimal(str(check_result.current_price)),
                trigger_time=datetime.now(UTC),
                trigger_reason=check_result.check_result.trigger_reason,
                pnl=check_result.unrealized_pnl,
                pnl_pct=check_result.unrealized_pnl_pct,
                shares_closed=position["shares"],  # 全部平仓
            )

            # 发送通知
            success = self.notification_service.notify_stop_loss_triggered(notification_data)
            if success:
                logger.info(f"止损通知已发送: 用户 {position['user_id']}, 持仓 {position['id']}")
            else:
                logger.warning(
                    f"止损通知发送失败: 用户 {position['user_id']}, 持仓 {position['id']}"
                )

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
        take_profit_repo: TakeProfitRepositoryProtocol | None = None,
        position_repo: PositionRepositoryProtocol | None = None,
        risk_policy_provider: RiskPolicyProviderProtocol | None = None,
    ) -> None:
        """
        初始化自动止盈用例

        Args:
            market_data_service: 行情数据服务（默认使用 MarketPriceService）
            notification_service: 通知服务（默认使用内存通知服务）
        """
        self.market_data_service = market_data_service or _MarketDataAdapter()
        self.notification_service = (
            notification_service or build_in_memory_stop_loss_notification_service()
        )
        self.take_profit_repo = take_profit_repo or TakeProfitRepository()
        self.position_repo = position_repo or PositionRepository()
        self.risk_policy_provider = risk_policy_provider or _RiskCenterPolicyProvider()

    def check_and_execute_take_profit(
        self, user_id: int | None = None
    ) -> list[TakeProfitCheckOutput]:
        """
        检查并执行止盈

        Args:
            user_id: 指定用户ID，None表示检查所有用户

        Returns:
            List[TakeProfitCheckOutput]: 检查结果列表
        """
        # 获取所有激活的止盈配置
        active_configs = self.take_profit_repo.get_active_take_profit_configs(user_id=user_id)

        results: list[TakeProfitCheckOutput] = []

        for config in active_configs:
            result = self._check_single_position(config)
            if result is None:
                continue
            if result.should_close and not self._execute_take_profit(config, result):
                result = replace(result, should_close=False)
            results.append(result)

        return results

    def _check_single_position(self, config: dict[str, Any]) -> TakeProfitCheckOutput | None:
        """
        检查单个持仓的止盈

        Args:
            config: 止盈配置

        Returns:
            TakeProfitCheckOutput or None
        """
        position = config["position"]

        # 从行情接口获取当前价格
        current_price = self._get_current_price(position["asset_code"])
        if current_price is None:
            logger.warning(f"无法获取资产 {position['asset_code']} 的价格，跳过止盈检查")
            return None

        entry_price = float(position["avg_cost"])
        take_profit_pct = self._resolve_take_profit_pct(config)

        # 检查止盈
        check_result = TakeProfitService.check_take_profit(
            entry_price=entry_price,
            current_price=current_price,
            take_profit_pct=take_profit_pct,
            partial_levels=config["partial_profit_levels"],
        )

        # 计算盈亏
        unrealized_pnl = Decimal(str(check_result.unrealized_pnl_pct)) * Decimal(
            str(position["shares"] * float(position["avg_cost"]))
        )

        return TakeProfitCheckOutput(
            position_id=position["id"],
            asset_code=position["asset_code"],
            should_close=check_result.should_trigger,
            check_result=check_result,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=check_result.unrealized_pnl_pct,
            partial_level=check_result.partial_level,
        )

    def _resolve_take_profit_pct(self, config: dict[str, Any]) -> float:
        configured_pct = float(config["take_profit_pct"])
        account_id = config["position"].get("portfolio_id")
        if not account_id:
            return configured_pct
        try:
            parameters = self.risk_policy_provider.get_effective_parameters(int(account_id))
        except Exception as exc:
            logger.warning("无法读取风控中心有效策略，沿用持仓止盈配置: %s", exc)
            return configured_pct
        take_profit_pct = parameters.get("take_profit_pct")
        if take_profit_pct is None:
            return configured_pct
        return min(configured_pct, float(take_profit_pct))

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

    def _execute_take_profit(
        self,
        config: dict[str, Any],
        check_result: TakeProfitCheckOutput,
    ) -> bool:
        """
        执行止盈平仓

        Args:
            config: 止盈配置
            check_result: 检查结果
        """
        position = config["position"]
        current_price = Decimal(str(check_result.current_price))
        partial_levels = [float(level) for level in (config["partial_profit_levels"] or [])]

        # 如果是分批止盈，计算平仓数量
        if check_result.partial_level and partial_levels:
            level_index = check_result.partial_level - 1
            if level_index < 0 or level_index >= len(partial_levels):
                logger.error(
                    "止盈档位越界: config=%s, partial_level=%s",
                    config["id"],
                    check_result.partial_level,
                )
                return False
            sell_shares = float(position["shares"]) / len(partial_levels)
            remaining_partial_levels = partial_levels[level_index + 1 :]
            deactivate = not remaining_partial_levels
        else:
            # 全部止盈
            sell_shares = None
            remaining_partial_levels = []
            deactivate = True

        executed = self.take_profit_repo.execute_take_profit_tranche(
            config_id=int(config["id"]),
            position_id=position["id"],
            expected_partial_levels=partial_levels,
            remaining_partial_levels=remaining_partial_levels,
            shares=sell_shares,
            price=current_price,
            reason=f"止盈触发: {check_result.check_result.trigger_reason}",
            deactivate=deactivate,
        )
        if not executed:
            logger.info(
                "止盈档位已由其他任务处理或配置已失效: config=%s",
                config["id"],
            )
            return False

        # 发送通知
        self._send_take_profit_notification(
            position=position,
            config=config,
            check_result=check_result,
            sell_shares=sell_shares,
        )
        return True

    def _send_take_profit_notification(
        self,
        position: dict[str, Any],
        config: dict[str, Any],
        check_result: TakeProfitCheckOutput,
        sell_shares: float | None,
    ) -> None:
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
            user_email = position["user_email"]

            # 构造通知数据
            notification_data = StopLossNotificationData(
                user_id=position["user_id"],
                user_email=user_email,
                position_id=position["id"],
                asset_code=position["asset_code"],
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
                logger.info(f"止盈通知已发送: 用户 {position['user_id']}, 持仓 {position['id']}")
            else:
                logger.warning(
                    f"止盈通知发送失败: 用户 {position['user_id']}, 持仓 {position['id']}"
                )

        except Exception as e:
            # 通知失败不应影响止盈执行
            logger.error(f"发送止盈通知异常: {e}", exc_info=True)


class CreateStopLossConfigUseCase:
    """
    创建止损配置用例
    """

    def __init__(
        self,
        position_repo: PositionRepositoryProtocol | None = None,
        stop_loss_repo: StopLossRepositoryProtocol | None = None,
    ) -> None:
        self.position_repo = position_repo or PositionRepository()
        self.stop_loss_repo = stop_loss_repo or StopLossRepository()

    def execute(
        self,
        position_id: int,
        stop_loss_type: str,
        stop_loss_pct: float,
        trailing_stop_pct: float | None = None,
        max_holding_days: int | None = None,
    ) -> dict[str, Any]:
        """
        创建止损配置

        Args:
            position_id: 持仓ID
            stop_loss_type: 止损类型 (fixed/trailing/time_based)
            stop_loss_pct: 止损百分比
            trailing_stop_pct: 移动止损百分比
            max_holding_days: 最大持仓天数

        Returns:
            dict: 创建的止损配置
        """
        # 获取持仓
        position = self.position_repo.get_position_stop_management_context(position_id)
        if position is None:
            raise ValueError(f"持仓 {position_id} 不存在")

        # 检查是否已有止损配置
        if self.stop_loss_repo.get_stop_loss_config_by_position(position_id):
            raise ValueError(f"持仓 {position_id} 已有止损配置")

        # 创建止损配置
        config = self.stop_loss_repo.create_stop_loss_config(
            position_id=position_id,
            stop_loss_type=stop_loss_type,
            stop_loss_pct=stop_loss_pct,
            trailing_stop_pct=trailing_stop_pct,
            max_holding_days=max_holding_days,
            highest_price=position["avg_cost"],  # 初始最高价为开仓价
        )

        return config


class CreateTakeProfitConfigUseCase:
    """
    创建止盈配置用例
    """

    def __init__(
        self,
        position_repo: PositionRepositoryProtocol | None = None,
        take_profit_repo: TakeProfitRepositoryProtocol | None = None,
    ) -> None:
        self.position_repo = position_repo or PositionRepository()
        self.take_profit_repo = take_profit_repo or TakeProfitRepository()

    def execute(
        self,
        position_id: int,
        take_profit_pct: float,
        partial_profit_levels: list[float] | None = None,
    ) -> dict[str, Any]:
        """
        创建止盈配置

        Args:
            position_id: 持仓ID
            take_profit_pct: 止盈百分比
            partial_profit_levels: 分批止盈点位

        Returns:
            dict: 创建的止盈配置
        """
        # 获取持仓
        position = self.position_repo.get_position_stop_management_context(position_id)
        if position is None:
            raise ValueError(f"持仓 {position_id} 不存在")

        # 检查是否已有止盈配置
        if self.take_profit_repo.get_take_profit_config_by_position(position_id):
            raise ValueError(f"持仓 {position_id} 已有止盈配置")

        # 创建止盈配置
        config = self.take_profit_repo.create_take_profit_config(
            position_id=position_id,
            take_profit_pct=take_profit_pct,
            partial_profit_levels=partial_profit_levels,
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

    def __init__(self) -> None:
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
