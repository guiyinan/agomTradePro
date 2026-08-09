"""Persistence repositories for dashboard cards, alerts, and snapshots."""

from typing import Any

from django.contrib.auth import get_user_model

from apps.dashboard.domain.entities import AlertSeverity, CardType

from .models import DashboardAlertModel, DashboardCardModel, DashboardSnapshotModel

User = get_user_model()


class DashboardCardRepository:
    """
    仪表盘卡片仓储

    管理仪表盘卡片的持久化操作。

    Example:
        >>> repo = DashboardCardRepository()
        >>> card = repo.get_card_by_id("portfolio_summary")
    """

    def get_card_by_id(self, card_id: str) -> DashboardCardModel | None:
        """
        按 ID 获取卡片

        Args:
            card_id: 卡片 ID

        Returns:
            卡片或 None
        """
        try:
            return DashboardCardModel._default_manager.get(card_id=card_id)
        except DashboardCardModel.DoesNotExist:
            return None

    def get_all_visible_cards(self) -> list[DashboardCardModel]:
        """
        获取所有可见卡片

        Returns:
            卡片列表
        """
        return list(DashboardCardModel._default_manager.filter(is_visible=True))

    def get_cards_by_type(self, card_type: CardType) -> list[DashboardCardModel]:
        """
        按类型获取卡片

        Args:
            card_type: 卡片类型

        Returns:
            卡片列表
        """
        return list(
            DashboardCardModel._default_manager.filter(card_type=card_type.value, is_visible=True)
        )

    def create_card(
        self,
        card_id: str,
        card_type: CardType,
        title: str = "",
        **kwargs: Any,
    ) -> DashboardCardModel:
        """
        创建卡片

        Args:
            card_id: 卡片 ID
            card_type: 卡片类型
            title: 标题
            **kwargs: 其他字段

        Returns:
            创建的卡片
        """
        card = DashboardCardModel._default_manager.create(
            card_id=card_id, card_type=card_type.value, title=title, **kwargs
        )
        return card

    def update_card_visibility(self, card_id: str, is_visible: bool) -> bool:
        """
        更新卡片可见性

        Args:
            card_id: 卡片 ID
            is_visible: 是否可见

        Returns:
            是否成功
        """
        try:
            card = DashboardCardModel._default_manager.get(card_id=card_id)
            card.is_visible = is_visible
            card.save()
            return True
        except DashboardCardModel.DoesNotExist:
            return False


class DashboardAlertRepository:
    """
    仪表盘告警仓储

    管理仪表盘告警的持久化操作。

    Example:
        >>> repo = DashboardAlertRepository()
        >>> alerts = repo.get_enabled_alerts()
    """

    def get_alert_by_id(self, alert_id: str) -> DashboardAlertModel | None:
        """
        按 ID 获取告警

        Args:
            alert_id: 告警 ID

        Returns:
            告警或 None
        """
        try:
            return DashboardAlertModel._default_manager.get(alert_id=alert_id)
        except DashboardAlertModel.DoesNotExist:
            return None

    def get_enabled_alerts(self) -> list[DashboardAlertModel]:
        """
        获取所有启用的告警

        Returns:
            告警列表
        """
        return list(DashboardAlertModel._default_manager.filter(is_enabled=True))

    def get_alerts_by_severity(self, severity: AlertSeverity) -> list[DashboardAlertModel]:
        """
        按严重级别获取告警

        Args:
            severity: 告警级别

        Returns:
            告警列表
        """
        return list(
            DashboardAlertModel._default_manager.filter(severity=severity.value, is_enabled=True)
        )

    def create_alert(
        self,
        alert_id: str,
        name: str,
        metric: str,
        threshold: float,
        severity: AlertSeverity = AlertSeverity.WARNING,
        **kwargs: Any,
    ) -> DashboardAlertModel:
        """
        创建告警

        Args:
            alert_id: 告警 ID
            name: 名称
            metric: 监控指标
            threshold: 阈值
            severity: 告警级别
            **kwargs: 其他字段

        Returns:
            创建的告警
        """
        alert = DashboardAlertModel._default_manager.create(
            alert_id=alert_id,
            name=name,
            metric=metric,
            threshold=threshold,
            severity=severity.value,
            **kwargs,
        )
        return alert

    def update_trigger_time(self, alert_id: str) -> bool:
        """
        更新告警触发时间

        Args:
            alert_id: 告警 ID

        Returns:
            是否成功
        """
        try:
            alert = DashboardAlertModel._default_manager.get(alert_id=alert_id)
            alert.update_trigger()
            return True
        except DashboardAlertModel.DoesNotExist:
            return False


class DashboardSnapshotRepository:
    """
    仪表盘快照仓储

    管理仪表盘快照的持久化操作。

    Example:
        >>> repo = DashboardSnapshotRepository()
        >>> repo.create_snapshot(user_id, snapshot_data)
    """

    def create_snapshot(
        self, user_id: int, snapshot_data: dict[str, Any]
    ) -> DashboardSnapshotModel | None:
        """
        创建快照

        Args:
            user_id: 用户 ID
            snapshot_data: 快照数据

        Returns:
            创建的快照或 None
        """
        try:
            user = User._default_manager.get(id=user_id)
            snapshot = DashboardSnapshotModel._default_manager.create(
                user=user, snapshot_data=snapshot_data
            )
            return snapshot
        except User.DoesNotExist:
            return None

    def get_recent_snapshots(self, user_id: int, limit: int = 10) -> list[DashboardSnapshotModel]:
        """
        获取最近的快照

        Args:
            user_id: 用户 ID
            limit: 数量限制

        Returns:
            快照列表
        """
        try:
            user = User._default_manager.get(id=user_id)
            return list(
                DashboardSnapshotModel._default_manager.filter(user=user).order_by("-captured_at")[
                    :limit
                ]
            )
        except User.DoesNotExist:
            return []

    def delete_old_snapshots(self, user_id: int, keep_count: int = 100) -> int:
        """
        删除旧快照

        Args:
            user_id: 用户 ID
            keep_count: 保留数量

        Returns:
            删除的数量
        """
        try:
            user = User._default_manager.get(id=user_id)
            snapshots = DashboardSnapshotModel._default_manager.filter(user=user).order_by(
                "-captured_at"
            )

            total = snapshots.count()
            if total > keep_count:
                to_delete = snapshots[keep_count:]
                count = len(to_delete)
                to_delete.delete()
                return count
            return 0
        except User.DoesNotExist:
            return 0
