"""
ORM Models for AI Provider Management.

Django models for persisting AI provider configurations and usage logs.
参考 DataSourceConfig 的设计模式。
"""

from django.conf import settings
from django.db import models
from django.db.models import Q


class AIProviderConfig(models.Model):
    """
    AI提供商配置 ORM 模型

    参考 DataSourceConfig 设计，支持OpenAI兼容的多个AI提供商。
    """
    PROVIDER_TYPE_CHOICES = [
        ('openai', 'OpenAI'),
        ('deepseek', 'DeepSeek'),
        ('qwen', '通义千问'),
        ('moonshot', 'Moonshot'),
        ('custom', '自定义'),
    ]
    API_MODE_CHOICES = [
        ("dual", "Dual (Responses + Chat Fallback)"),
        ("responses_only", "Responses Only"),
        ("chat_only", "Chat Completions Only"),
    ]
    SCOPE_CHOICES = [
        ("system", "System"),
        ("user", "User"),
    ]

    # 基本信息
    name = models.CharField(
        max_length=50,
        db_index=True,
        help_text="配置名称（唯一标识）"
    )
    scope = models.CharField(
        max_length=20,
        choices=SCOPE_CHOICES,
        default="system",
        db_index=True,
        help_text="配置归属范围（system/user）",
    )
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="ai_provider_configs",
        help_text="当 scope=user 时对应的拥有者",
    )
    provider_type = models.CharField(
        max_length=20,
        choices=PROVIDER_TYPE_CHOICES,
        help_text="提供商类型"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="是否启用"
    )
    priority = models.IntegerField(
        default=10,
        db_index=True,
        help_text="优先级（数字越小越优先，用于failover）"
    )

    # 连接配置
    base_url = models.URLField(
        max_length=500,
        help_text="API Base URL（如 https://api.openai.com/v1）"
    )
    api_key = models.CharField(
        max_length=500,
        blank=True,
        help_text="API Key (plaintext, deprecated - use api_key_encrypted)"
    )
    api_key_encrypted = models.TextField(
        blank=True,
        help_text="API Key (encrypted at rest)"
    )
    default_model = models.CharField(
        max_length=50,
        default="gpt-3.5-turbo",
        help_text="默认模型名称"
    )
    api_mode = models.CharField(
        max_length=20,
        choices=API_MODE_CHOICES,
        default="dual",
        help_text="OpenAI API 模式：dual/responses_only/chat_only",
    )
    fallback_enabled = models.BooleanField(
        default=True,
        help_text="dual 模式下是否允许从 Responses 回退到 Chat Completions",
    )

    # 预算控制
    daily_budget_limit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="每日预算限制（美元）"
    )
    monthly_budget_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="每月预算限制（美元）"
    )

    # 额外配置
    extra_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="额外配置参数"
    )
    description = models.TextField(
        blank=True,
        help_text="描述"
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="最后使用时间"
    )

    class Meta:
        db_table = 'ai_provider_config'
        ordering = ['priority', 'name']
        verbose_name = "AI提供商配置"
        verbose_name_plural = "AI提供商配置"
        indexes = [
            models.Index(fields=['scope', 'owner_user', 'is_active']),
            models.Index(fields=['provider_type', 'is_active']),
            models.Index(fields=['is_active', 'priority']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['owner_user', 'name'],
                condition=Q(scope='user'),
                name='ai_provider_user_name_unique',
            ),
            models.UniqueConstraint(
                fields=['name'],
                condition=Q(scope='system'),
                name='ai_provider_system_name_unique',
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.scope}:{self.get_provider_type_display()})"


class AIUsageLog(models.Model):
    """
    AI API调用日志 ORM 模型

    记录每次API调用的详细信息，用于统计和成本追踪。
    """
    PROVIDER_SCOPE_CHOICES = [
        ('system_global', 'System Global'),
        ('system_fallback', 'System Fallback'),
        ('personal', 'Personal'),
    ]
    STATUS_CHOICES = [
        ('success', '成功'),
        ('error', '错误'),
        ('timeout', '超时'),
        ('rate_limited', '限流'),
    ]

    # 关联提供商
    provider = models.ForeignKey(
        AIProviderConfig,
        on_delete=models.CASCADE,
        related_name='usage_logs',
        db_index=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ai_usage_logs',
        db_index=True,
    )
    provider_scope = models.CharField(
        max_length=20,
        choices=PROVIDER_SCOPE_CHOICES,
        default='system_global',
        db_index=True,
        help_text='命中的 provider 归属范围',
    )
    quota_charged = models.BooleanField(
        default=False,
        help_text='是否计入用户系统兜底额度',
    )

    # 请求信息
    model = models.CharField(
        max_length=50,
        db_index=True,
        help_text="使用的模型"
    )
    request_type = models.CharField(
        max_length=20,
        default='chat',
        help_text="请求类型（chat/completion/embedding等）"
    )

    # Token使用
    prompt_tokens = models.IntegerField(
        default=0,
        help_text="输入token数量"
    )
    completion_tokens = models.IntegerField(
        default=0,
        help_text="输出token数量"
    )
    total_tokens = models.IntegerField(
        default=0,
        db_index=True,
        help_text="总token数量"
    )

    # 性能
    response_time_ms = models.IntegerField(
        help_text="响应时间（毫秒）"
    )

    # 成本
    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        db_index=True,
        help_text="预估成本（美元）"
    )

    # 状态
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        db_index=True,
        help_text="调用状态"
    )
    error_message = models.TextField(
        blank=True,
        help_text="错误信息"
    )

    # 元数据
    request_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="请求元数据"
    )

    # 时间戳
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="创建时间"
    )

    class Meta:
        db_table = 'ai_usage_log'
        ordering = ['-created_at']
        verbose_name = "AI调用日志"
        verbose_name_plural = "AI调用日志"
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['provider_scope', '-created_at']),
            models.Index(fields=['provider', '-created_at']),
            models.Index(fields=['model', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.provider.name} - {self.model} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class AIUserFallbackQuota(models.Model):
    """User-scoped quota for consuming system fallback providers."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_fallback_quota',
    )
    daily_limit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='每日系统兜底额度（美元）',
    )
    monthly_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='每月系统兜底额度（美元）',
    )
    is_active = models.BooleanField(default=True, help_text='是否启用用户系统兜底额度')
    admin_note = models.TextField(blank=True, help_text='管理员备注')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_user_fallback_quota'
        verbose_name = 'AI 用户兜底额度'
        verbose_name_plural = 'AI 用户兜底额度'
        indexes = [
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.user} fallback quota"
