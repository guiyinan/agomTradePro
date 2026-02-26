"""
ORM Models for AI Provider Management.

Django models for persisting AI provider configurations and usage logs.
参考 DataSourceConfig 的设计模式。
"""

from django.db import models


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

    # 基本信息
    name = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="配置名称（唯一标识）"
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
        help_text="API Key"
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
            models.Index(fields=['provider_type', 'is_active']),
            models.Index(fields=['is_active', 'priority']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"


class AIUsageLog(models.Model):
    """
    AI API调用日志 ORM 模型

    记录每次API调用的详细信息，用于统计和成本追踪。
    """
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
            models.Index(fields=['provider', '-created_at']),
            models.Index(fields=['model', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.provider.name} - {self.model} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
