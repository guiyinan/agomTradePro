"""
Share ORM Models

Infrastructure层:
- 使用Django ORM定义数据表
- 对应Domain层的实体
- 包含索引优化和约束
"""

import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.share.domain.services import validate_short_code

from .model_constraints import (
    SHARE_ACCESS_LOG_CONSTRAINTS,
    SHARE_DISCLAIMER_CONSTRAINTS,
    SHARE_LINK_CONSTRAINTS,
    SHARE_SNAPSHOT_CONSTRAINTS,
)

User = get_user_model()


class ShareLinkModel(models.Model):
    """
    分享链接模型

    存储账户分享链接的核心信息。
    """

    # 关联信息
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="share_links",
        verbose_name="所有者",
        db_index=True,
    )
    account_id = models.IntegerField("关联账户ID", db_index=True, help_text="关联的模拟账户ID")

    # 短码（唯一，不可预测）
    short_code = models.CharField(
        "短码", max_length=16, unique=True, db_index=True, help_text="用于公开访问的唯一短码"
    )

    # 基本信息
    title = models.CharField("标题", max_length=100)
    subtitle = models.CharField("副标题", max_length=200, blank=True, null=True)
    THEME_CHOICES = [
        ("bloomberg", "彭博终端风格"),
        ("monopoly", "大富翁游戏风格"),
    ]
    theme = models.CharField(
        "页面风格",
        max_length=20,
        choices=THEME_CHOICES,
        default="bloomberg",
        help_text="公开分享页的展示风格",
    )

    # 分享级别
    SHARE_LEVEL_CHOICES = [
        ("snapshot", "静态快照"),
        ("observer", "观察者模式"),
        ("research", "研究模式"),
    ]
    share_level = models.CharField(
        "分享级别",
        max_length=20,
        choices=SHARE_LEVEL_CHOICES,
        default="snapshot",
        db_index=True,
        help_text="决定数据展示的详细程度",
    )

    # 状态
    STATUS_CHOICES = [
        ("active", "活跃"),
        ("revoked", "已撤销"),
        ("expired", "已过期"),
        ("disabled", "已禁用"),
    ]
    status = models.CharField(
        "状态",
        max_length=20,
        choices=STATUS_CHOICES,
        default="active",
        db_index=True,
    )

    # 访问控制
    password_hash = models.CharField(
        "密码哈希",
        max_length=128,
        blank=True,
        null=True,
        help_text="使用 Django 的 make_password 生成",
    )
    expires_at = models.DateTimeField(
        "过期时间", blank=True, null=True, db_index=True, help_text="过期后无法访问"
    )
    max_access_count = models.IntegerField(
        "最大访问次数", blank=True, null=True, help_text="null 表示无限制"
    )
    access_count = models.IntegerField(
        "访问次数",
        default=0,
    )

    # 快照时间
    last_snapshot_at = models.DateTimeField(
        "最后快照时间", blank=True, null=True, help_text="最近一次生成快照的时间"
    )
    last_accessed_at = models.DateTimeField(
        "最后访问时间",
        blank=True,
        null=True,
    )

    # SEO 配置
    allow_indexing = models.BooleanField(
        "允许搜索引擎索引", default=False, help_text="允许后页面可被搜索引擎收录"
    )

    # 可见性控制
    show_amounts = models.BooleanField("显示金额", default=False)
    show_positions = models.BooleanField("显示持仓", default=True)
    show_transactions = models.BooleanField("显示交易", default=True)
    show_decision_summary = models.BooleanField("显示决策摘要", default=True)
    show_decision_evidence = models.BooleanField("显示决策依据", default=False)
    show_invalidation_logic = models.BooleanField("显示证伪逻辑", default=False)

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "share_link"
        verbose_name = "分享链接"
        verbose_name_plural = "分享链接"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["short_code"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["expires_at"]),
            models.Index(fields=["account_id"]),
        ]
        constraints = SHARE_LINK_CONSTRAINTS

    def __str__(self) -> str:
        return f"{self.title} ({self.short_code})"

    def clean(self) -> None:
        """验证模型数据"""
        super().clean()
        errors: dict[str, str] = {}
        if self.account_id < 1:
            errors["account_id"] = "关联账户 ID 必须为正整数"
        if not validate_short_code(self.short_code, min_length=6, max_length=16):
            errors["short_code"] = "短码必须为 6 至 16 位 ASCII 字母或数字"
        if self.access_count < 0:
            errors["access_count"] = "访问次数不能为负数"
        if self.max_access_count is not None:
            if self.max_access_count < 1:
                errors["max_access_count"] = "最大访问次数必须大于 0"
            elif self.access_count > self.max_access_count:
                errors["access_count"] = "访问次数不能超过最大访问次数"
        if self.expires_at:
            if timezone.is_naive(self.expires_at):
                errors["expires_at"] = "过期时间必须包含时区"
            elif self.expires_at <= timezone.now():
                errors["expires_at"] = "过期时间必须晚于当前时间"
        if errors:
            raise ValidationError(errors)

    def is_accessible(self) -> bool:
        """检查链接是否可访问"""
        if self.status != "active":
            return False
        if self.expires_at:
            if timezone.is_naive(self.expires_at) or timezone.now() > self.expires_at:
                return False
        if self.max_access_count is not None and self.access_count >= self.max_access_count:
            return False
        return True

    def requires_password(self) -> bool:
        """是否需要密码"""
        return bool(self.password_hash)

    def increment_access_count(self) -> bool:
        """Atomically consume one access without exceeding status, time, or count limits."""

        if self.pk is None:
            raise ValueError("未保存的分享链接不能增加访问次数")
        now = timezone.now()
        updated = (
            type(self)
            ._default_manager.filter(pk=self.pk, status="active")
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .filter(Q(max_access_count__isnull=True) | Q(access_count__lt=F("max_access_count")))
            .update(access_count=F("access_count") + 1, last_accessed_at=now)
        )
        if updated != 1:
            return False
        self.refresh_from_db(fields=["access_count", "last_accessed_at"])
        return True


class ShareSnapshotModel(models.Model):
    """
    分享快照模型

    存储分享链接在某个时间点的完整状态快照。
    """

    # 关联分享链接
    share_link = models.ForeignKey(
        ShareLinkModel,
        on_delete=models.CASCADE,
        related_name="snapshots",
        verbose_name="分享链接",
        db_index=True,
    )

    # 快照版本
    snapshot_version = models.IntegerField(
        "快照版本", default=1, help_text="同一分享链接的快照版本号"
    )

    # 数据负载（JSON）
    summary_payload = models.JSONField(
        "摘要数据", blank=True, null=True, default=dict, help_text="账户摘要信息"
    )
    performance_payload = models.JSONField(
        "绩效数据", blank=True, null=True, default=dict, help_text="绩效指标"
    )
    positions_payload = models.JSONField(
        "持仓数据", blank=True, null=True, default=dict, help_text="持仓列表"
    )
    transactions_payload = models.JSONField(
        "交易数据", blank=True, null=True, default=dict, help_text="交易记录"
    )
    decision_payload = models.JSONField(
        "决策数据", blank=True, null=True, default=dict, help_text="决策依据和证伪逻辑"
    )

    # 生成时间
    generated_at = models.DateTimeField(
        "生成时间",
        auto_now_add=True,
        db_index=True,
    )

    # 数据来源时间范围
    source_range_start = models.DateField(
        "数据起始日期", blank=True, null=True, help_text="快照数据的起始日期"
    )
    source_range_end = models.DateField(
        "数据结束日期", blank=True, null=True, help_text="快照数据的结束日期"
    )

    class Meta:
        db_table = "share_snapshot"
        verbose_name = "分享快照"
        verbose_name_plural = "分享快照"
        ordering = ["-snapshot_version"]
        indexes = [
            models.Index(fields=["share_link", "-snapshot_version"]),
            models.Index(fields=["-generated_at"]),
        ]
        unique_together = [["share_link", "snapshot_version"]]
        constraints = SHARE_SNAPSHOT_CONSTRAINTS

    def __str__(self) -> str:
        return f"Snapshot v{self.snapshot_version} for {self.share_link.title}"

    def clean(self) -> None:
        """Validate snapshot version, payload shape, and source date range."""

        super().clean()
        errors: dict[str, str] = {}
        if self.snapshot_version < 1:
            errors["snapshot_version"] = "快照版本必须大于 0"
        for field_name in (
            "summary_payload",
            "performance_payload",
            "positions_payload",
            "transactions_payload",
            "decision_payload",
        ):
            payload = getattr(self, field_name)
            if not isinstance(payload, dict):
                errors[field_name] = "快照数据必须为 JSON 对象"
                continue
            try:
                json.dumps(payload, allow_nan=False)
            except (TypeError, ValueError):
                errors[field_name] = "快照数据必须可序列化且不得包含 NaN/Inf"
        if (self.source_range_start is None) != (self.source_range_end is None):
            errors["source_range_end"] = "数据起止日期必须同时提供"
        elif (
            self.source_range_start is not None
            and self.source_range_end is not None
            and self.source_range_end < self.source_range_start
        ):
            errors["source_range_end"] = "数据结束日期不能早于开始日期"
        if errors:
            raise ValidationError(errors)

    def is_empty(self) -> bool:
        """检查快照是否为空"""
        return (
            not self.summary_payload
            and not self.performance_payload
            and not self.positions_payload
            and not self.transactions_payload
            and not self.decision_payload
        )


class ShareAccessLogModel(models.Model):
    """
    分享访问日志模型

    记录每次访问分享链接的行为，用于审计和分析。
    """

    # 关联分享链接
    share_link = models.ForeignKey(
        ShareLinkModel,
        on_delete=models.CASCADE,
        related_name="access_logs",
        verbose_name="分享链接",
        db_index=True,
    )

    # 访问时间
    accessed_at = models.DateTimeField(
        "访问时间",
        auto_now_add=True,
        db_index=True,
    )

    # 访问者信息（匿名化）
    ip_hash = models.CharField(
        "IP哈希", max_length=64, db_index=True, help_text="IP地址的哈希值，不存储原始IP"
    )
    user_agent = models.TextField("用户代理", blank=True, null=True, help_text="浏览器/客户端信息")
    referer = models.TextField("来源页面", blank=True, null=True, help_text="HTTP Referer")

    # 验证状态
    is_verified = models.BooleanField(
        "已验证", default=False, help_text="是否通过密码验证（如果有密码）"
    )
    RESULT_STATUS_CHOICES = [
        ("success", "成功"),
        ("password_required", "需要密码"),
        ("password_invalid", "密码错误"),
        ("expired", "已过期"),
        ("revoked", "已撤销"),
        ("max_count_exceeded", "超过访问次数"),
        ("not_found", "不存在"),
    ]
    result_status = models.CharField(
        "访问结果",
        max_length=30,
        choices=RESULT_STATUS_CHOICES,
        default="success",
        db_index=True,
    )

    class Meta:
        db_table = "share_access_log"
        verbose_name = "访问日志"
        verbose_name_plural = "访问日志"
        ordering = ["-accessed_at"]
        indexes = [
            models.Index(fields=["share_link", "-accessed_at"]),
            models.Index(fields=["ip_hash"]),
            models.Index(fields=["result_status"]),
            models.Index(fields=["-accessed_at"]),
        ]
        constraints = SHARE_ACCESS_LOG_CONSTRAINTS

    def __str__(self) -> str:
        return f"{self.share_link.short_code} - {self.accessed_at.strftime('%Y-%m-%d %H:%M')}"

    def is_successful(self) -> bool:
        """是否是成功的访问"""
        return self.result_status == "success"


class ShareDisclaimerConfigModel(models.Model):
    """Global disclaimer content and modal behavior for public share pages."""

    singleton_key = models.CharField(
        "单例键", max_length=32, unique=True, default="default", editable=False
    )
    is_enabled = models.BooleanField("显示底部风险提示", default=True)
    modal_enabled = models.BooleanField("启用风险提示弹窗", default=True)
    modal_title = models.CharField("提示标题", max_length=120, default="重要声明")
    modal_confirm_text = models.CharField("弹窗确认按钮文案", max_length=40, default="我已知悉")
    lines = models.JSONField(
        "风险提示内容",
        default=list,
        blank=True,
        help_text="按顺序展示的风险提示条目",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "share_disclaimer_config"
        verbose_name = "分享页风险提示配置"
        verbose_name_plural = "分享页风险提示配置"
        constraints = SHARE_DISCLAIMER_CONSTRAINTS

    def __str__(self) -> str:
        return "分享页风险提示配置"

    def clean(self) -> None:
        """Validate singleton identity and bounded disclaimer lines."""

        super().clean()
        errors: dict[str, str] = {}
        if self.singleton_key != "default":
            errors["singleton_key"] = "单例键必须为 default"
        if not _valid_disclaimer_lines(self.lines):
            errors["lines"] = "风险提示必须为最多 20 条、每条不超过 500 字的非空字符串"
        if errors:
            raise ValidationError(errors)

    @classmethod
    def get_solo(cls) -> "ShareDisclaimerConfigModel":
        default_lines = [
            "本页面内容主要用于账户分享、策略复盘和公开交流，不构成投资建议。",
            "页面观点和持仓展示仅代表分享账户当时状态，不代表系统作者观点。",
            "历史业绩不代表未来表现，投资有风险，入市需谨慎。",
            "数据可能存在延迟或缺口，请以实际交易和行情数据为准。",
        ]
        defaults = {
            "is_enabled": True,
            "modal_enabled": True,
            "modal_title": "重要声明",
            "modal_confirm_text": "我已知悉",
            "lines": default_lines,
        }
        config, _ = cls.objects.get_or_create(singleton_key="default", defaults=defaults)
        if not _valid_disclaimer_lines(config.lines):
            config.lines = list(default_lines)
            config.save(update_fields=["lines", "updated_at"])
        return config


def _valid_disclaimer_lines(value: object) -> bool:
    """Return whether public disclaimer content has the governed JSON shape."""

    return bool(
        isinstance(value, list)
        and 1 <= len(value) <= 20
        and all(
            isinstance(item, str) and bool(item.strip()) and len(item) <= 500 and "\x00" not in item
            for item in value
        )
    )
