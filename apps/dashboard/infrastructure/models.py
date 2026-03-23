"""
Dashboard Infrastructure Models

仪表盘 Django ORM 模型定义。
"""

import json
import logging
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from apps.dashboard.domain.entities import (
    AlertSeverity,
    CardType,
    WidgetType,
)

logger = logging.getLogger(__name__)

User = get_user_model()


class DashboardConfigModel(models.Model):
    """
    仪表盘配置模型

    存储系统级的仪表盘配置。

    Attributes:
        config_id: 配置ID
        name: 配置名称
        description: 描述
        layout_config: 布局配置（JSON）
        card_configs: 卡片配置列表（JSON）
        is_default: 是否默认配置
        is_active: 是否激活
        created_at: 创建时间
        updated_at: 更新时间
    """

    config_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="配置唯一标识符"
    )

    name = models.CharField(
        max_length=100,
        help_text="配置名称"
    )

    description = models.TextField(
        blank=True,
        help_text="描述"
    )

    layout_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="布局配置"
    )

    card_configs = models.JSONField(
        default=list,
        blank=True,
        help_text="卡片配置列表"
    )

    is_default = models.BooleanField(
        default=False,
        help_text="是否默认配置"
    )

    is_active = models.BooleanField(
        default=True,
        help_text="是否激活"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="更新时间"
    )

    class Meta:
        db_table = "dashboard_config"
        verbose_name = "仪表盘配置"
        verbose_name_plural = "仪表盘配置"
        ordering = ["-is_default", "name"]

    def __str__(self):
        return f"DashboardConfig({self.name})"


class DashboardUserConfigModel(models.Model):
    """
    用户仪表盘配置模型

    存储用户个人的仪表盘偏好设置。

    Attributes:
        user: 关联用户
        dashboard_config: 仪表盘配置
        hidden_cards: 隐藏的卡片ID列表（JSON）
        collapsed_cards: 折叠的卡片ID列表（JSON）
        card_order: 卡片顺序（JSON）
        custom_card_config: 自定义卡片配置（JSON）
        theme: 主题
        refresh_enabled: 是否启用自动刷新
        refresh_interval: 刷新间隔（秒）
        last_updated: 最后更新时间
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="dashboard_config",
        help_text="关联用户"
    )

    dashboard_config = models.ForeignKey(
        DashboardConfigModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_configs",
        help_text="仪表盘配置"
    )

    hidden_cards = models.JSONField(
        default=list,
        blank=True,
        help_text="隐藏的卡片ID列表"
    )

    collapsed_cards = models.JSONField(
        default=list,
        blank=True,
        help_text="折叠的卡片ID列表"
    )

    card_order = models.JSONField(
        default=list,
        blank=True,
        help_text="卡片顺序"
    )

    custom_card_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="自定义卡片配置"
    )

    theme = models.CharField(
        max_length=20,
        default="light",
        help_text="主题"
    )

    refresh_enabled = models.BooleanField(
        default=True,
        help_text="是否启用自动刷新"
    )

    refresh_interval = models.IntegerField(
        default=60,
        help_text="刷新间隔（秒）"
    )

    last_updated = models.DateTimeField(
        auto_now=True,
        help_text="最后更新时间"
    )

    class Meta:
        db_table = "dashboard_user_config"
        verbose_name = "用户仪表盘配置"
        verbose_name_plural = "用户仪表盘配置"
        unique_together = [["user", "dashboard_config"]]

    def __str__(self):
        return f"DashboardUserConfig({self.user.username})"


class DashboardCardModel(models.Model):
    """
    仪表盘卡片模型

    存储可复用的仪表盘卡片定义。

    Attributes:
        card_id: 卡片ID
        card_type: 卡片类型
        title: 卡片标题
        description: 描述
        widget_config: 组件配置（JSON）
        data_source: 数据源
        visibility_conditions: 可见性条件（JSON）
        position: 位置配置（JSON）
        size: 尺寸配置（JSON）
        is_visible: 是否可见
        is_collapsible: 是否可折叠
        is_draggable: 是否可拖动
        is_resizable: 是否可调整大小
        dependencies: 依赖的卡片ID列表（JSON）
        display_order: 显示顺序
        created_at: 创建时间
        updated_at: 更新时间
    """

    card_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="卡片唯一标识符"
    )

    card_type = models.CharField(
        max_length=20,
        choices=[(t.value, t.name) for t in CardType],
        help_text="卡片类型"
    )

    title = models.CharField(
        max_length=100,
        blank=True,
        help_text="卡片标题"
    )

    description = models.TextField(
        blank=True,
        help_text="描述"
    )

    widget_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="组件配置"
    )

    data_source = models.CharField(
        max_length=200,
        blank=True,
        help_text="数据源"
    )

    visibility_conditions = models.JSONField(
        default=dict,
        blank=True,
        help_text="可见性条件"
    )

    position = models.JSONField(
        default=dict,
        blank=True,
        help_text="位置配置"
    )

    size = models.JSONField(
        default=dict,
        blank=True,
        help_text="尺寸配置"
    )

    is_visible = models.BooleanField(
        default=True,
        help_text="是否可见"
    )

    is_collapsible = models.BooleanField(
        default=True,
        help_text="是否可折叠"
    )

    is_draggable = models.BooleanField(
        default=True,
        help_text="是否可拖动"
    )

    is_resizable = models.BooleanField(
        default=True,
        help_text="是否可调整大小"
    )

    dependencies = models.JSONField(
        default=list,
        blank=True,
        help_text="依赖的卡片ID列表"
    )

    display_order = models.IntegerField(
        default=0,
        help_text="显示顺序"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="更新时间"
    )

    class Meta:
        db_table = "dashboard_card"
        verbose_name = "仪表盘卡片"
        verbose_name_plural = "仪表盘卡片"
        ordering = ["display_order", "card_id"]

    def __str__(self):
        return f"DashboardCard({self.card_id}, {self.title})"


class DashboardAlertModel(models.Model):
    """
    仪表盘告警模型

    存储仪表盘告警配置。

    Attributes:
        alert_id: 告警ID
        name: 告警名称
        description: 描述
        metric: 监控指标
        condition: 告警条件
        severity: 告警级别
        threshold: 阈值
        notification_channels: 通知渠道（JSON）
        is_enabled: 是否启用
        cooldown: 冷却时间（秒）
        last_triggered_at: 最后触发时间
        trigger_count: 触发次数
        created_at: 创建时间
        updated_at: 更新时间
    """

    alert_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="告警唯一标识符"
    )

    name = models.CharField(
        max_length=100,
        help_text="告警名称"
    )

    description = models.TextField(
        blank=True,
        help_text="描述"
    )

    metric = models.CharField(
        max_length=100,
        blank=True,
        help_text="监控指标"
    )

    condition = models.CharField(
        max_length=50,
        blank=True,
        help_text="告警条件"
    )

    severity = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in AlertSeverity],
        default=AlertSeverity.WARNING.value,
        help_text="告警级别"
    )

    threshold = models.FloatField(
        null=True,
        blank=True,
        help_text="阈值"
    )

    notification_channels = models.JSONField(
        default=list,
        blank=True,
        help_text="通知渠道"
    )

    is_enabled = models.BooleanField(
        default=True,
        help_text="是否启用"
    )

    cooldown = models.IntegerField(
        default=300,
        help_text="冷却时间（秒）"
    )

    last_triggered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="最后触发时间"
    )

    trigger_count = models.IntegerField(
        default=0,
        help_text="触发次数"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="更新时间"
    )

    class Meta:
        db_table = "dashboard_alert"
        verbose_name = "仪表盘告警"
        verbose_name_plural = "仪表盘告警"
        ordering = ["severity", "name"]

    def __str__(self):
        return f"DashboardAlert({self.alert_id}, {self.name})"

    def update_trigger(self) -> None:
        """更新触发信息"""
        self.last_triggered_at = timezone.now()
        self.trigger_count += 1
        self.save(update_fields=["last_triggered_at", "trigger_count"])


class DashboardSnapshotModel(models.Model):
    """
    仪表盘快照模型

    存储仪表盘状态快照，用于历史回溯。

    Attributes:
        user: 关联用户
        snapshot_data: 快照数据（JSON）
        captured_at: 捕获时间
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="dashboard_snapshots",
        help_text="关联用户"
    )

    snapshot_data = models.JSONField(
        help_text="快照数据"
    )

    captured_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="捕获时间"
    )

    class Meta:
        db_table = "dashboard_snapshot"
        verbose_name = "仪表盘快照"
        verbose_name_plural = "仪表盘快照"
        ordering = ["-captured_at"]

    def __str__(self):
        return f"DashboardSnapshot({self.user.username}, {self.captured_at})"
