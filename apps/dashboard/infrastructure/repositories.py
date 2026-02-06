"""
Dashboard Infrastructure Repositories

仪表盘数据仓储实现。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.dashboard.domain.entities import (
    DashboardLayout,
    DashboardCard,
    DashboardWidget,
    DashboardPreferences,
    AlertConfig,
    CardType,
    WidgetType,
    AlertSeverity,
)
from apps.dashboard.domain.services import LayoutResolutionResult
from .models import (
    DashboardConfigModel,
    DashboardUserConfigModel,
    DashboardCardModel,
    DashboardAlertModel,
    DashboardSnapshotModel,
)


logger = logging.getLogger(__name__)

User = get_user_model()


class DashboardConfigRepository:
    """
    仪表盘配置仓储

    管理仪表盘配置的持久化操作。

    Example:
        >>> repo = DashboardConfigRepository()
        >>> config = repo.get_default_config()
        >>> cards = repo.get_cards_for_config(config.config_id)
    """

    def get_default_config(self) -> Optional[DashboardConfigModel]:
        """
        获取默认配置

        Returns:
            默认配置或 None
        """
        try:
            return DashboardConfigModel._default_manager.filter(
                is_default=True,
                is_active=True
            ).first()
        except Exception as e:
            logger.error(f"Error getting default config: {e}")
            return None

    def get_config_by_id(self, config_id: str) -> Optional[DashboardConfigModel]:
        """
        按 ID 获取配置

        Args:
            config_id: 配置 ID

        Returns:
            配置或 None
        """
        try:
            return DashboardConfigModel._default_manager.get(config_id=config_id)
        except DashboardConfigModel.DoesNotExist:
            return None

    def get_all_active_configs(self) -> List[DashboardConfigModel]:
        """
        获取所有激活的配置

        Returns:
            配置列表
        """
        return list(DashboardConfigModel._default_manager.filter(is_active=True))

    def create_config(
        self,
        config_id: str,
        name: str,
        layout_config: Dict[str, Any],
        card_configs: List[Dict[str, Any]],
        is_default: bool = False,
        description: str = "",
    ) -> DashboardConfigModel:
        """
        创建配置

        Args:
            config_id: 配置 ID
            name: 名称
            layout_config: 布局配置
            card_configs: 卡片配置列表
            is_default: 是否默认
            description: 描述

        Returns:
            创建的配置
        """
        if is_default:
            # 取消其他默认配置
            DashboardConfigModel._default_manager.filter(is_default=True).update(is_default=False)

        config = DashboardConfigModel._default_manager.create(
            config_id=config_id,
            name=name,
            description=description,
            layout_config=layout_config,
            card_configs=card_configs,
            is_default=is_default,
        )
        return config

    def update_config(
        self,
        config_id: str,
        **kwargs
    ) -> Optional[DashboardConfigModel]:
        """
        更新配置

        Args:
            config_id: 配置 ID
            **kwargs: 更新字段

        Returns:
            更新后的配置或 None
        """
        try:
            config = DashboardConfigModel._default_manager.get(config_id=config_id)
            for key, value in kwargs.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            config.save()
            return config
        except DashboardConfigModel.DoesNotExist:
            return None


class DashboardPreferencesRepository:
    """
    仪表盘用户偏好仓储

    管理用户仪表盘偏好的持久化操作。

    Example:
        >>> repo = DashboardPreferencesRepository()
        >>> prefs = repo.get_or_create_preferences(user_id)
    """

    def get_preferences(self, user_id: int) -> Optional[DashboardPreferences]:
        """
        获取用户偏好

        Args:
            user_id: 用户 ID

        Returns:
            用户偏好或 None
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)
            return self._to_domain_entity(config_model)
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return None

    def get_or_create_preferences(
        self,
        user_id: int
    ) -> DashboardPreferences:
        """
        获取或创建用户偏好

        Args:
            user_id: 用户 ID

        Returns:
            用户偏好
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model, created = DashboardUserConfigModel._default_manager.get_or_create(
                user=user,
                defaults={
                    "dashboard_config": DashboardConfigRepository().get_default_config(),
                }
            )
            return self._to_domain_entity(config_model)
        except User.DoesNotExist:
            # 创建默认偏好
            return DashboardPreferences(
                user_id=user_id,
                layout_id="default",
            )

    def update_preferences(
        self,
        user_id: int,
        **kwargs
    ) -> Optional[DashboardPreferences]:
        """
        更新用户偏好

        Args:
            user_id: 用户 ID
            **kwargs: 更新字段

        Returns:
            更新后的偏好或 None
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)

            for key, value in kwargs.items():
                if hasattr(config_model, key):
                    setattr(config_model, key, value)

            config_model.save()
            return self._to_domain_entity(config_model)
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return None

    def add_hidden_card(self, user_id: int, card_id: str) -> bool:
        """
        添加隐藏卡片

        Args:
            user_id: 用户 ID
            card_id: 卡片 ID

        Returns:
            是否成功
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)

            if card_id not in config_model.hidden_cards:
                config_model.hidden_cards.append(card_id)
                config_model.save()

            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    def remove_hidden_card(self, user_id: int, card_id: str) -> bool:
        """
        移除隐藏卡片

        Args:
            user_id: 用户 ID
            card_id: 卡片 ID

        Returns:
            是否成功
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)

            if card_id in config_model.hidden_cards:
                config_model.hidden_cards.remove(card_id)
                config_model.save()

            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    def add_collapsed_card(self, user_id: int, card_id: str) -> bool:
        """
        添加折叠卡片

        Args:
            user_id: 用户 ID
            card_id: 卡片 ID

        Returns:
            是否成功
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)

            if card_id not in config_model.collapsed_cards:
                config_model.collapsed_cards.append(card_id)
                config_model.save()

            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    def remove_collapsed_card(self, user_id: int, card_id: str) -> bool:
        """
        移除折叠卡片

        Args:
            user_id: 用户 ID
            card_id: 卡片 ID

        Returns:
            是否成功
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)

            if card_id in config_model.collapsed_cards:
                config_model.collapsed_cards.remove(card_id)
                config_model.save()

            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    def update_card_order(self, user_id: int, card_order: List[str]) -> bool:
        """
        更新卡片顺序

        Args:
            user_id: 用户 ID
            card_order: 卡片顺序

        Returns:
            是否成功
        """
        try:
            user = User._default_manager.get(id=user_id)
            config_model = DashboardUserConfigModel._default_manager.get(user=user)
            config_model.card_order = card_order
            config_model.save()
            return True
        except (User.DoesNotExist, DashboardUserConfigModel.DoesNotExist):
            return False

    def _to_domain_entity(self, model: DashboardUserConfigModel) -> DashboardPreferences:
        """转换为领域实体"""
        return DashboardPreferences(
            user_id=model.user_id,
            layout_id=model.dashboard_config.config_id if model.dashboard_config else "default",
            hidden_cards=model.hidden_cards or [],
            collapsed_cards=model.collapsed_cards or [],
            card_order=model.card_order or [],
            custom_card_config=model.custom_card_config or {},
            theme=model.theme,
            refresh_enabled=model.refresh_enabled,
            refresh_interval=model.refresh_interval,
            last_updated=model.last_updated,
        )


class DashboardCardRepository:
    """
    仪表盘卡片仓储

    管理仪表盘卡片的持久化操作。

    Example:
        >>> repo = DashboardCardRepository()
        >>> card = repo.get_card_by_id("portfolio_summary")
    """

    def get_card_by_id(self, card_id: str) -> Optional[DashboardCardModel]:
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

    def get_all_visible_cards(self) -> List[DashboardCardModel]:
        """
        获取所有可见卡片

        Returns:
            卡片列表
        """
        return list(DashboardCardModel._default_manager.filter(is_visible=True))

    def get_cards_by_type(self, card_type: CardType) -> List[DashboardCardModel]:
        """
        按类型获取卡片

        Args:
            card_type: 卡片类型

        Returns:
            卡片列表
        """
        return list(DashboardCardModel._default_manager.filter(
            card_type=card_type.value,
            is_visible=True
        ))

    def create_card(
        self,
        card_id: str,
        card_type: CardType,
        title: str = "",
        **kwargs
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
            card_id=card_id,
            card_type=card_type.value,
            title=title,
            **kwargs
        )
        return card

    def update_card_visibility(
        self,
        card_id: str,
        is_visible: bool
    ) -> bool:
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

    def get_alert_by_id(self, alert_id: str) -> Optional[DashboardAlertModel]:
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

    def get_enabled_alerts(self) -> List[DashboardAlertModel]:
        """
        获取所有启用的告警

        Returns:
            告警列表
        """
        return list(DashboardAlertModel._default_manager.filter(is_enabled=True))

    def get_alerts_by_severity(self, severity: AlertSeverity) -> List[DashboardAlertModel]:
        """
        按严重级别获取告警

        Args:
            severity: 告警级别

        Returns:
            告警列表
        """
        return list(DashboardAlertModel._default_manager.filter(
            severity=severity.value,
            is_enabled=True
        ))

    def create_alert(
        self,
        alert_id: str,
        name: str,
        metric: str,
        threshold: float,
        severity: AlertSeverity = AlertSeverity.WARNING,
        **kwargs
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
            **kwargs
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
        self,
        user_id: int,
        snapshot_data: Dict[str, Any]
    ) -> Optional[DashboardSnapshotModel]:
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
                user=user,
                snapshot_data=snapshot_data
            )
            return snapshot
        except User.DoesNotExist:
            return None

    def get_recent_snapshots(
        self,
        user_id: int,
        limit: int = 10
    ) -> List[DashboardSnapshotModel]:
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
            return list(DashboardSnapshotModel._default_manager.filter(
                user=user
            ).order_by("-captured_at")[:limit])
        except User.DoesNotExist:
            return []

    def delete_old_snapshots(
        self,
        user_id: int,
        keep_count: int = 100
    ) -> int:
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
            snapshots = DashboardSnapshotModel._default_manager.filter(
                user=user
            ).order_by("-captured_at")

            total = snapshots.count()
            if total > keep_count:
                to_delete = snapshots[keep_count:]
                count = len(to_delete)
                to_delete.delete()
                return count
            return 0
        except User.DoesNotExist:
            return 0

