"""
Share ORM Models

Infrastructure层:
- 使用Django ORM定义数据表
- 对应Domain层的实体
- 包含索引优化和约束
"""
from django.db import models
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone


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
        related_name='share_links',
        verbose_name="所有者",
        db_index=True,
    )
    account_id = models.IntegerField(
        "关联账户ID",
        db_index=True,
        help_text="关联的模拟账户ID"
    )

    # 短码（唯一，不可预测）
    short_code = models.CharField(
        "短码",
        max_length=16,
        unique=True,
        db_index=True,
        help_text="用于公开访问的唯一短码"
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
        help_text="公开分享页的展示风格"
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
        help_text="决定数据展示的详细程度"
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
        help_text="使用 Django 的 make_password 生成"
    )
    expires_at = models.DateTimeField(
        "过期时间",
        blank=True,
        null=True,
        db_index=True,
        help_text="过期后无法访问"
    )
    max_access_count = models.IntegerField(
        "最大访问次数",
        blank=True,
        null=True,
        help_text="null 表示无限制"
    )
    access_count = models.IntegerField(
        "访问次数",
        default=0,
    )

    # 快照时间
    last_snapshot_at = models.DateTimeField(
        "最后快照时间",
        blank=True,
        null=True,
        help_text="最近一次生成快照的时间"
    )
    last_accessed_at = models.DateTimeField(
        "最后访问时间",
        blank=True,
        null=True,
    )

    # SEO 配置
    allow_indexing = models.BooleanField(
        "允许搜索引擎索引",
        default=False,
        help_text="允许后页面可被搜索引擎收录"
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
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', '-created_at']),
            models.Index(fields=['short_code']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['account_id']),
        ]

    def __str__(self):
        return f"{self.title} ({self.short_code})"

    def clean(self):
        """验证模型数据"""
        if self.share_level == "snapshot" and self.max_access_count is not None and self.max_access_count < 1:
            raise ValidationError({"max_access_count": "静态快照模式的访问次数必须大于0"})
        if self.expires_at and self.expires_at <= timezone.now():
            raise ValidationError({"expires_at": "过期时间必须晚于当前时间"})

    def is_accessible(self) -> bool:
        """检查链接是否可访问"""
        if self.status != "active":
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        if self.max_access_count and self.access_count >= self.max_access_count:
            return False
        return True

    def requires_password(self) -> bool:
        """是否需要密码"""
        return bool(self.password_hash)

    def increment_access_count(self):
        """增加访问次数"""
        self.access_count += 1
        self.last_accessed_at = timezone.now()
        self.save(update_fields=['access_count', 'last_accessed_at'])


class ShareSnapshotModel(models.Model):
    """
    分享快照模型

    存储分享链接在某个时间点的完整状态快照。
    """
    # 关联分享链接
    share_link = models.ForeignKey(
        ShareLinkModel,
        on_delete=models.CASCADE,
        related_name='snapshots',
        verbose_name="分享链接",
        db_index=True,
    )

    # 快照版本
    snapshot_version = models.IntegerField(
        "快照版本",
        default=1,
        help_text="同一分享链接的快照版本号"
    )

    # 数据负载（JSON）
    summary_payload = models.JSONField(
        "摘要数据",
        blank=True,
        null=True,
        default=dict,
        help_text="账户摘要信息"
    )
    performance_payload = models.JSONField(
        "绩效数据",
        blank=True,
        null=True,
        default=dict,
        help_text="绩效指标"
    )
    positions_payload = models.JSONField(
        "持仓数据",
        blank=True,
        null=True,
        default=dict,
        help_text="持仓列表"
    )
    transactions_payload = models.JSONField(
        "交易数据",
        blank=True,
        null=True,
        default=dict,
        help_text="交易记录"
    )
    decision_payload = models.JSONField(
        "决策数据",
        blank=True,
        null=True,
        default=dict,
        help_text="决策依据和证伪逻辑"
    )

    # 生成时间
    generated_at = models.DateTimeField(
        "生成时间",
        auto_now_add=True,
        db_index=True,
    )

    # 数据来源时间范围
    source_range_start = models.DateField(
        "数据起始日期",
        blank=True,
        null=True,
        help_text="快照数据的起始日期"
    )
    source_range_end = models.DateField(
        "数据结束日期",
        blank=True,
        null=True,
        help_text="快照数据的结束日期"
    )

    class Meta:
        db_table = "share_snapshot"
        verbose_name = "分享快照"
        verbose_name_plural = "分享快照"
        ordering = ['-snapshot_version']
        indexes = [
            models.Index(fields=['share_link', '-snapshot_version']),
            models.Index(fields=['-generated_at']),
        ]
        unique_together = [['share_link', 'snapshot_version']]

    def __str__(self):
        return f"Snapshot v{self.snapshot_version} for {self.share_link.title}"

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
        related_name='access_logs',
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
        "IP哈希",
        max_length=64,
        db_index=True,
        help_text="IP地址的哈希值，不存储原始IP"
    )
    user_agent = models.TextField(
        "用户代理",
        blank=True,
        null=True,
        help_text="浏览器/客户端信息"
    )
    referer = models.TextField(
        "来源页面",
        blank=True,
        null=True,
        help_text="HTTP Referer"
    )

    # 验证状态
    is_verified = models.BooleanField(
        "已验证",
        default=False,
        help_text="是否通过密码验证（如果有密码）"
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
        ordering = ['-accessed_at']
        indexes = [
            models.Index(fields=['share_link', '-accessed_at']),
            models.Index(fields=['ip_hash']),
            models.Index(fields=['result_status']),
            models.Index(fields=['-accessed_at']),
        ]

    def __str__(self):
        return f"{self.share_link.short_code} - {self.accessed_at.strftime('%Y-%m-%d %H:%M')}"

    def is_successful(self) -> bool:
        """是否是成功的访问"""
        return self.result_status == "success"


class ShareDisclaimerConfigModel(models.Model):
    """Global disclaimer content and modal behavior for public share pages."""

    singleton_key = models.CharField("单例键", max_length=32, unique=True, default="default", editable=False)
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

    def __str__(self):
        return "分享页风险提示配置"

    @classmethod
    def get_solo(cls):
        defaults = {
            "is_enabled": True,
            "modal_enabled": True,
            "modal_title": "重要声明",
            "modal_confirm_text": "我已知悉",
            "lines": [
                "本页面内容主要用于账户分享、策略复盘和公开交流，不构成投资建议。",
                "页面观点和持仓展示仅代表分享账户当时状态，不代表系统作者观点。",
                "历史业绩不代表未来表现，投资有风险，入市需谨慎。",
                "数据可能存在延迟或缺口，请以实际交易和行情数据为准。",
            ],
        }
        config, _ = cls.objects.get_or_create(singleton_key="default", defaults=defaults)
        if not config.lines:
            config.lines = defaults["lines"]
            config.save(update_fields=["lines", "updated_at"])
        return config
