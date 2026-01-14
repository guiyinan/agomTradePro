"""
Realtime Module - Application Layer Price Polling Service

This module provides the price polling service that orchestrates price updates.
Following AgomSaaS architecture rules:
- Application layer orchestrates business logic
- Depends on Protocol interfaces, not concrete implementations
- Uses dependency injection for testability
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from apps.realtime.domain.entities import (
    PricePollingConfig,
    PriceSnapshot,
    PriceUpdate,
    PriceUpdateStatus
)
from apps.realtime.domain.protocols import (
    RealtimePriceRepositoryProtocol,
    PriceDataProviderProtocol,
    WatchlistProviderProtocol
)
from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedAccountModel


logger = logging.getLogger(__name__)


class PricePollingService:
    """价格轮询服务

    负责定期轮询价格数据并更新系统
    """

    def __init__(
        self,
        price_repository: RealtimePriceRepositoryProtocol,
        price_provider: PriceDataProviderProtocol,
        watchlist_provider: WatchlistProviderProtocol,
        config: PricePollingConfig = None
    ):
        self.price_repository = price_repository
        self.price_provider = price_provider
        self.watchlist_provider = watchlist_provider
        self.config = config or PricePollingConfig()

    def poll_and_update_prices(self) -> PriceSnapshot:
        """执行一次价格轮询和更新

        Returns:
            价格快照对象，包含更新结果统计
        """
        logger.info("Starting price polling...")

        # 1. 获取需要监控的资产列表
        asset_codes = self.watchlist_provider.get_all_monitored_assets()
        total_assets = len(asset_codes)

        if total_assets == 0:
            logger.warning("No assets to monitor")
            return PriceSnapshot(
                timestamp=datetime.now(),
                prices=[],
                total_assets=0,
                success_count=0,
                failed_count=0
            )

        logger.info(f"Monitoring {total_assets} assets")

        # 2. 批量获取价格
        prices = self.price_provider.get_realtime_prices_batch(asset_codes)

        # 3. 保存价格到缓存
        if prices:
            self.price_repository.save_prices_batch(prices)

        # 4. 更新持仓模型中的价格
        updates = self._update_position_prices(prices)

        # 5. 统计结果
        success_count = len(prices)
        failed_count = total_assets - success_count

        logger.info(
            f"Price polling completed: "
            f"{success_count} succeeded, {failed_count} failed"
        )

        return PriceSnapshot(
            timestamp=datetime.now(),
            prices=prices,
            total_assets=total_assets,
            success_count=success_count,
            failed_count=failed_count
        )

    def poll_single_asset(self, asset_code: str) -> Optional[PriceUpdate]:
        """轮询单个资产的价格

        Args:
            asset_code: 资产代码

        Returns:
            价格更新对象，如果失败则返回 None
        """
        logger.debug(f"Polling price for {asset_code}")

        # 获取旧价格
        old_price = self.price_repository.get_latest_price(asset_code)

        # 获取新价格
        new_price = self.price_provider.get_realtime_price(asset_code)

        if new_price is None:
            logger.warning(f"Failed to get price for {asset_code}")
            return PriceUpdate(
                asset_code=asset_code,
                old_price=Decimal(old_price.price) if old_price else None,
                new_price=None,
                status=PriceUpdateStatus.FAILED,
                timestamp=datetime.now(),
                error_message="Failed to fetch price from data provider"
            )

        # 保存新价格
        self.price_repository.save_price(new_price)

        # 判断状态
        if old_price is None:
            status = PriceUpdateStatus.SUCCESS
        elif Decimal(old_price.price) == Decimal(new_price.price):
            status = PriceUpdateStatus.NO_CHANGE
        else:
            status = PriceUpdateStatus.SUCCESS

        update = PriceUpdate(
            asset_code=asset_code,
            old_price=Decimal(old_price.price) if old_price else None,
            new_price=Decimal(new_price.price),
            status=status,
            timestamp=datetime.now()
        )

        logger.debug(
            f"Price update for {asset_code}: "
            f"{update.old_price} -> {update.new_price} ({status.value})"
        )

        return update

    def _update_position_prices(self, prices) -> List[PriceUpdate]:
        """更新持仓模型中的当前价格

        Args:
            prices: RealtimePrice 对象列表

        Returns:
            PriceUpdate 对象列表
        """
        updates = []
        price_dict = {p.asset_code: p for p in prices}

        # 查询所有持仓
        positions = PositionModel.objects.select_related("account").filter(
            quantity__gt=0
        )

        for position in positions:
            price_obj = price_dict.get(position.asset_code)

            if price_obj is None:
                continue

            old_price = position.current_price
            new_price = Decimal(price_obj.price)

            # 更新持仓价格
            position.current_price = new_price
            position.current_value = new_price * position.quantity
            position.save(update_fields=["current_price", "current_value"])

            # 更新账户总价值
            self._update_account_value(position.account)

            updates.append(PriceUpdate(
                asset_code=position.asset_code,
                old_price=old_price,
                new_price=new_price,
                status=PriceUpdateStatus.SUCCESS if old_price != new_price else PriceUpdateStatus.NO_CHANGE,
                timestamp=datetime.now()
            ))

        logger.info(f"Updated {len(updates)} position prices")
        return updates

    def _update_account_value(self, account: SimulatedAccountModel) -> None:
        """更新账户总价值

        Args:
            account: 模拟账户模型
        """
        # 重新计算账户总价值
        positions = PositionModel.objects.filter(account=account)
        total_value = sum(p.current_value for p in positions)

        account.total_value = total_value + account.cash
        account.daily_pnl = total_value - account.initial_cash
        account.daily_pnl_pct = (
            (account.daily_pnl / account.initial_cash * 100)
            if account.initial_cash > 0 else 0
        )
        account.save(update_fields=["total_value", "daily_pnl", "daily_pnl_pct"])

    def force_refresh_all(self) -> PriceSnapshot:
        """强制刷新所有资产价格

        忽略缓存，直接从数据源获取最新价格
        """
        logger.info("Force refreshing all prices...")
        return self.poll_and_update_prices()


class PricePollingUseCase:
    """价格轮询用例

    提供给上层使用的接口
    """

    def __init__(self):
        # 延迟导入，避免循环依赖
        from apps.realtime.infrastructure.repositories import (
            RedisRealtimePriceRepository,
            AKSharePriceDataProvider,
            TusharePriceDataProvider,
            CompositePriceDataProvider,
            DatabaseWatchlistProvider
        )
        from apps.realtime.domain.entities import PricePollingConfig

        # 初始化依赖
        self.price_repository = RedisRealtimePriceRepository()

        # 创建数据提供者（AKShare 优先，因为它是免费的）
        akshare_provider = AKSharePriceDataProvider()  # 主数据源（免费）
        tushare_provider = TusharePriceDataProvider()     # 备用数据源

        # 创建组合数据提供者（按顺序尝试）
        self.price_provider = CompositePriceDataProvider([akshare_provider, tushare_provider])

        self.watchlist_provider = DatabaseWatchlistProvider()

        # 创建价格轮询服务
        self.service = PricePollingService(
            price_repository=self.price_repository,
            price_provider=self.price_provider,
            watchlist_provider=self.watchlist_provider,
            config=PricePollingConfig()
        )

    def execute_price_polling(self) -> dict:
        """执行价格轮询

        Returns:
            价格快照字典
        """
        snapshot = self.service.poll_and_update_prices()
        return snapshot.to_dict()

    def get_latest_prices(self, asset_codes: List[str]) -> List[dict]:
        """获取最新价格

        Args:
            asset_codes: 资产代码列表

        Returns:
            价格字典列表
        """
        prices = self.price_repository.get_latest_prices(asset_codes)
        return [p.to_dict() for p in prices]
