"""
Realtime Module - Application Layer Price Polling Service

This module provides the price polling service that orchestrates price updates.
Following AgomSaaS architecture rules:
- Application layer orchestrates business logic
- Depends on Protocol interfaces, not concrete implementations
- Uses dependency injection for testability
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from decimal import Decimal

from django.utils import timezone

from apps.realtime.application.repository_provider import (
    get_realtime_price_provider,
    get_realtime_price_repository,
    get_watchlist_provider,
)
from apps.realtime.domain.entities import (
    PricePollingConfig,
    PriceSnapshot,
    PriceUpdate,
    PriceUpdateStatus,
)
from apps.realtime.domain.protocols import (
    PriceDataProviderProtocol,
    RealtimePriceRepositoryProtocol,
    WatchlistProviderProtocol,
)
from core.integration.simulated_positions import get_simulated_position_price_updater

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
        config: PricePollingConfig | None = None,
        position_repository: object | None = None,
    ):
        self.price_repository = price_repository
        self.price_provider = price_provider
        self.watchlist_provider = watchlist_provider
        self.config = config or PricePollingConfig()
        self.position_repository = position_repository or get_simulated_position_price_updater()

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
                timestamp=timezone.now(),
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
        self._update_position_prices(prices)

        # 5. 统计结果
        success_count = len(prices)
        failed_count = total_assets - success_count

        logger.info(
            f"Price polling completed: "
            f"{success_count} succeeded, {failed_count} failed"
        )

        return PriceSnapshot(
            timestamp=timezone.now(),
            prices=prices,
            total_assets=total_assets,
            success_count=success_count,
            failed_count=failed_count
        )

    def poll_single_asset(self, asset_code: str) -> PriceUpdate | None:
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
                timestamp=timezone.now(),
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
            timestamp=timezone.now()
        )

        logger.debug(
            f"Price update for {asset_code}: "
            f"{update.old_price} -> {update.new_price} ({status.value})"
        )

        return update

    def _update_position_prices(self, prices) -> list[PriceUpdate]:
        """更新持仓模型中的当前价格

        Args:
            prices: RealtimePrice 对象列表

        Returns:
            PriceUpdate 对象列表
        """
        updates = []
        price_by_code = {price.asset_code: Decimal(price.price) for price in prices}

        for result in self.position_repository.update_position_prices(price_by_code):
            updates.append(
                PriceUpdate(
                    asset_code=result["asset_code"],
                    old_price=result["old_price"],
                    new_price=result["new_price"],
                    status=(
                        PriceUpdateStatus.SUCCESS
                        if result["price_changed"]
                        else PriceUpdateStatus.NO_CHANGE
                    ),
                    timestamp=timezone.now(),
                )
            )

        logger.info(f"Updated {len(updates)} position prices")
        return updates

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
        from apps.realtime.domain.entities import PricePollingConfig

        # 初始化依赖
        self.price_repository = get_realtime_price_repository()
        self.price_provider = get_realtime_price_provider()
        self.watchlist_provider = get_watchlist_provider()

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

    def get_latest_prices(self, asset_codes: list[str]) -> list[dict]:
        """获取最新价格

        Args:
            asset_codes: 资产代码列表

        Returns:
            价格字典列表
        """
        cached_prices = self.price_repository.get_latest_prices(asset_codes)
        prices_by_code = {price.asset_code: price for price in cached_prices}
        missing_codes = [code for code in asset_codes if code not in prices_by_code]

        if missing_codes:
            fetched_prices = self.price_provider.get_realtime_prices_batch(missing_codes)
            if fetched_prices:
                self.price_repository.save_prices_batch(fetched_prices)
                for price in fetched_prices:
                    prices_by_code[price.asset_code] = price

        return [
            prices_by_code[asset_code].to_dict()
            for asset_code in asset_codes
            if asset_code in prices_by_code
        ]

    def check_provider_availability(self, timeout_seconds: float = 2.0) -> tuple[bool, str | None]:
        """Check whether the configured price provider responds within timeout."""

        health_error = None
        is_available = False
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self.price_provider.is_available)
            is_available = future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            health_error = "provider_check_timeout"
            logger.warning("Realtime health provider check timed out")
        except Exception as exc:
            health_error = str(exc)
            logger.warning("Realtime health provider check failed: %s", exc)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return is_available, health_error

