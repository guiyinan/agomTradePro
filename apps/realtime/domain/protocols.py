"""
Realtime Module - Domain Layer Protocol Interfaces

This module defines the protocol interfaces that the Infrastructure layer must implement.
Following AgomSaaS architecture rules:
- Protocol interfaces define the contract
- Infrastructure layer provides concrete implementations
- Application layer depends on protocols, not implementations
"""

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from apps.realtime.domain.entities import (
    PriceAlert,
    PriceSnapshot,
    PriceSubscription,
    PriceUpdate,
    RealtimePrice,
)


class PriceAlertRepositoryProtocol(ABC):
    """Persistence boundary for owner-scoped price alerts."""

    @abstractmethod
    def list_for_owner(self, owner_id: int) -> list[PriceAlert]:
        """List alerts belonging to one owner."""

    @abstractmethod
    def get_for_owner(self, owner_id: int, alert_id: int) -> PriceAlert | None:
        """Return one alert only when it belongs to the owner."""

    @abstractmethod
    def create(self, alert: PriceAlert) -> PriceAlert:
        """Persist a new alert."""

    @abstractmethod
    def update(self, alert: PriceAlert) -> PriceAlert | None:
        """Persist an owner-scoped alert update."""

    @abstractmethod
    def delete(self, owner_id: int, alert_id: int) -> bool:
        """Delete an alert belonging to the owner."""

    @abstractmethod
    def list_active_for_assets(self, asset_codes: list[str]) -> list[PriceAlert]:
        """List active alerts for the supplied canonical assets."""

    @abstractmethod
    def claim_trigger(
        self,
        alert_id: int,
        trigger_price: Decimal,
        triggered_at: datetime,
    ) -> PriceAlert | None:
        """Atomically transition an active alert to triggered once."""


class PriceSubscriptionRepositoryProtocol(ABC):
    """Persistence boundary for owner-scoped realtime subscriptions."""

    @abstractmethod
    def list_for_owner(self, owner_id: int) -> list[PriceSubscription]:
        """List the owner's active subscriptions."""

    @abstractmethod
    def subscribe(self, owner_id: int, asset_code: str) -> PriceSubscription:
        """Create or reactivate a durable subscription."""

    @abstractmethod
    def unsubscribe(self, owner_id: int, asset_code: str) -> bool:
        """Deactivate an owner-scoped subscription."""

    @abstractmethod
    def count_active(self, owner_id: int) -> int:
        """Count active subscriptions for one owner."""

    @abstractmethod
    def list_active_asset_codes(self) -> list[str]:
        """List distinct active asset codes across owners for polling."""


class RealtimeChannelNotifierProtocol(ABC):
    """Notification boundary for realtime channel delivery."""

    @abstractmethod
    def publish_price(self, price: RealtimePrice) -> None:
        """Publish a price update to subscribers of the asset."""

    @abstractmethod
    def publish_alert(self, alert: PriceAlert) -> None:
        """Publish a claimed alert to its owner."""

    @abstractmethod
    def subscriptions_changed(self, owner_id: int) -> None:
        """Notify an owner's connected clients to restore groups."""


class RealtimePriceRepositoryProtocol(ABC):
    """实时价格仓储协议接口

    定义实时价格数据持久化的抽象接口
    """

    @abstractmethod
    def save_price(self, price: RealtimePrice) -> None:
        """保存单个实时价格到缓存或数据库

        Args:
            price: 实时价格对象
        """
        pass

    @abstractmethod
    def save_prices_batch(self, prices: list[RealtimePrice]) -> None:
        """批量保存实时价格

        Args:
            prices: 实时价格列表
        """
        pass

    @abstractmethod
    def get_latest_price(self, asset_code: str) -> RealtimePrice | None:
        """获取资产的最新价格

        Args:
            asset_code: 资产代码

        Returns:
            最新的实时价格，如果不存在则返回 None
        """
        pass

    @abstractmethod
    def get_latest_prices(self, asset_codes: list[str]) -> list[RealtimePrice]:
        """批量获取多个资产的最新价格

        Args:
            asset_codes: 资产代码列表

        Returns:
            实时价格列表（与输入顺序一致）
        """
        pass


class PriceDataProviderProtocol(ABC):
    """价格数据提供者协议接口

    定义从外部数据源获取价格的抽象接口
    """

    @abstractmethod
    def get_realtime_price(self, asset_code: str) -> RealtimePrice | None:
        """获取单个资产的实时价格

        Args:
            asset_code: 资产代码

        Returns:
            实时价格对象，如果获取失败则返回 None
        """
        pass

    @abstractmethod
    def get_realtime_prices_batch(self, asset_codes: list[str]) -> list[RealtimePrice]:
        """批量获取多个资产的实时价格

        Args:
            asset_codes: 资产代码列表

        Returns:
            实时价格列表（不包含失败的资产）
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用

        Returns:
            True 如果数据源可用，否则 False
        """
        pass


class PriceUpdateNotifierProtocol(ABC):
    """价格更新通知器协议接口

    定义价格更新通知的抽象接口
    """

    @abstractmethod
    def notify_price_update(self, update: PriceUpdate) -> None:
        """通知单个价格更新

        Args:
            update: 价格更新对象
        """
        pass

    @abstractmethod
    def notify_price_updates_batch(self, updates: list[PriceUpdate]) -> None:
        """批量通知价格更新

        Args:
            updates: 价格更新列表
        """
        pass

    @abstractmethod
    def broadcast_snapshot(self, snapshot: PriceSnapshot) -> None:
        """广播价格快照

        Args:
            snapshot: 价格快照对象
        """
        pass


class WatchlistProviderProtocol(ABC):
    """关注池提供者协议接口

    定义获取需要监控的资产列表的抽象接口
    """

    @abstractmethod
    def get_held_assets(self) -> list[str]:
        """获取所有持仓资产代码

        Returns:
            持仓资产代码列表
        """
        pass

    @abstractmethod
    def get_watchlist_assets(self, user_id: str | None = None) -> list[str]:
        """获取关注池资产代码

        Args:
            user_id: 用户ID（如果为 None，则返回所有用户的关注池）

        Returns:
            关注池资产代码列表
        """
        pass

    @abstractmethod
    def get_all_monitored_assets(self) -> list[str]:
        """获取所有需要监控的资产（持仓 + 关注池）

        Returns:
            去重后的资产代码列表
        """
        pass
