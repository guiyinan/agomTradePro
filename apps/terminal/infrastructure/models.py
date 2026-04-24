"""
Terminal infrastructure ORM models.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.prompt.infrastructure.models import PromptTemplateORM

from ..domain.entities import (
    CommandParameter,
    CommandType,
    TerminalAuditEntry,
    TerminalCommand,
    TerminalRiskLevel,
)


class TerminalCommandORM(models.Model):
    """Terminal command configuration persisted in the terminal app."""

    COMMAND_TYPE_CHOICES = [
        (CommandType.PROMPT.value, 'Prompt模板调用'),
        (CommandType.API.value, 'API端点调用'),
    ]

    RISK_LEVEL_CHOICES = [
        (TerminalRiskLevel.READ.value, '只读'),
        (TerminalRiskLevel.WRITE_LOW.value, '低风险写入'),
        (TerminalRiskLevel.WRITE_HIGH.value, '高风险写入'),
        (TerminalRiskLevel.ADMIN.value, '管理员'),
    ]

    name = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="命令名称（如：analyze, report）",
    )
    description = models.TextField(
        blank=True,
        help_text="命令描述",
    )
    command_type = models.CharField(
        max_length=20,
        choices=COMMAND_TYPE_CHOICES,
        default=CommandType.PROMPT.value,
        help_text="命令类型",
    )
    prompt_template = models.ForeignKey(
        PromptTemplateORM,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='terminal_commands',
        help_text="关联的Prompt模板（command_type=prompt时使用）",
    )
    system_prompt = models.TextField(
        blank=True,
        help_text="系统提示词（可选）",
    )
    user_prompt_template = models.TextField(
        blank=True,
        help_text="用户Prompt模板",
    )
    api_endpoint = models.CharField(
        max_length=255,
        blank=True,
        help_text="API端点路径（command_type=api时使用）",
    )
    api_method = models.CharField(
        max_length=10,
        default='GET',
        help_text="HTTP方法（GET/POST）",
    )
    response_jq_filter = models.CharField(
        max_length=255,
        blank=True,
        help_text="JQ过滤器，从API响应中提取数据",
    )
    parameters = models.JSONField(
        default=list,
        blank=True,
        help_text="参数定义列表",
    )
    timeout = models.IntegerField(
        default=60,
        help_text="超时时间（秒）",
    )
    provider_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="默认AI提供商名称",
    )
    model_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="默认模型名称",
    )
    category = models.CharField(
        max_length=50,
        default='general',
        db_index=True,
        help_text="命令分类",
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="标签列表",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="是否启用",
    )
    risk_level = models.CharField(
        max_length=20,
        choices=RISK_LEVEL_CHOICES,
        default=TerminalRiskLevel.READ.value,
        db_index=True,
        help_text="风险等级",
    )
    requires_mcp = models.BooleanField(
        default=True,
        help_text="是否需要 MCP 权限",
    )
    enabled_in_terminal = models.BooleanField(
        default=True,
        db_index=True,
        help_text="是否在终端中显示",
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")

    class Meta:
        db_table = 'terminal_command'
        ordering = ['category', 'name']
        verbose_name = "终端命令"
        verbose_name_plural = "终端命令配置"
        indexes = [
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['command_type', 'is_active']),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.command_type})"

    def clean(self):
        super().clean()

        if self.command_type == CommandType.PROMPT.value and not self.prompt_template:
            raise ValidationError({
                'prompt_template': 'Prompt类型命令必须关联Prompt模板',
            })

        if self.command_type == CommandType.PROMPT.value and not (
            self.user_prompt_template or self.system_prompt or self.prompt_template_id
        ):
            raise ValidationError({
                'user_prompt_template': 'Prompt类型命令至少需要模板或提示词配置',
            })

        if self.command_type == CommandType.API.value and not self.api_endpoint:
            raise ValidationError({
                'api_endpoint': 'API类型命令必须配置API端点',
            })

        if self.timeout <= 0:
            raise ValidationError({
                'timeout': 'timeout必须为正数',
            })

    def to_entity(self) -> TerminalCommand:
        """Map ORM model to domain entity."""
        return TerminalCommand(
            id=str(self.pk),
            name=self.name,
            description=self.description,
            command_type=self.command_type,
            is_active=self.is_active,
            prompt_template_id=str(self.prompt_template_id) if self.prompt_template_id else None,
            system_prompt=self.system_prompt or None,
            user_prompt_template=self.user_prompt_template,
            api_endpoint=self.api_endpoint or None,
            api_method=self.api_method,
            response_jq_filter=self.response_jq_filter or None,
            parameters=[CommandParameter.from_dict(p) for p in (self.parameters or [])],
            timeout=self.timeout,
            provider_name=self.provider_name or None,
            model_name=self.model_name or None,
            risk_level=TerminalRiskLevel(self.risk_level),
            requires_mcp=self.requires_mcp,
            enabled_in_terminal=self.enabled_in_terminal,
            category=self.category,
            tags=list(self.tags or []),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_entity(cls, entity: TerminalCommand) -> 'TerminalCommandORM':
        """Map domain entity to ORM model."""
        if entity.id and str(entity.id).isdigit():
            instance = cls._default_manager.filter(pk=int(entity.id)).first() or cls(pk=int(entity.id))
        else:
            instance = cls()
        instance.name = entity.name
        instance.description = entity.description
        instance.command_type = entity.command_type.value
        instance.prompt_template_id = int(entity.prompt_template_id) if entity.prompt_template_id else None
        instance.system_prompt = entity.system_prompt or ''
        instance.user_prompt_template = entity.user_prompt_template
        instance.api_endpoint = entity.api_endpoint or ''
        instance.api_method = entity.api_method
        instance.response_jq_filter = entity.response_jq_filter or ''
        instance.parameters = [p.to_dict() for p in entity.parameters]
        instance.timeout = entity.timeout
        instance.provider_name = entity.provider_name or ''
        instance.model_name = entity.model_name or ''
        instance.category = entity.category
        instance.tags = entity.tags or []
        instance.is_active = entity.is_active
        instance.risk_level = entity.risk_level.value if isinstance(entity.risk_level, TerminalRiskLevel) else entity.risk_level
        instance.requires_mcp = entity.requires_mcp
        instance.enabled_in_terminal = entity.enabled_in_terminal
        return instance


class TerminalAuditLogORM(models.Model):
    """终端审计日志"""

    CONFIRMATION_STATUS_CHOICES = [
        ('confirmed', '已确认'),
        ('cancelled', '已取消'),
        ('not_required', '无需确认'),
        ('expired', '已过期'),
    ]

    RESULT_STATUS_CHOICES = [
        ('success', '成功'),
        ('error', '错误'),
        ('blocked', '被阻止'),
        ('pending', '等待确认'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    username = models.CharField(max_length=150, db_index=True)
    session_id = models.CharField(max_length=100, db_index=True)
    command_name = models.CharField(max_length=50, db_index=True)
    risk_level = models.CharField(max_length=20)
    mode = models.CharField(max_length=20)
    params_summary = models.TextField(blank=True)
    confirmation_required = models.BooleanField(default=False)
    confirmation_status = models.CharField(
        max_length=20,
        choices=CONFIRMATION_STATUS_CHOICES,
        default='not_required',
    )
    result_status = models.CharField(
        max_length=20,
        choices=RESULT_STATUS_CHOICES,
        default='pending',
    )
    error_message = models.TextField(blank=True)
    duration_ms = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'terminal_audit_log'
        ordering = ['-created_at']
        verbose_name = "终端审计日志"
        verbose_name_plural = "终端审计日志"

    def __str__(self) -> str:
        return f"{self.username}:{self.command_name} [{self.result_status}]"

    def to_entity(self) -> TerminalAuditEntry:
        """Map ORM model to domain entity."""
        return TerminalAuditEntry(
            user_id=self.user_id,
            username=self.username,
            session_id=self.session_id,
            command_name=self.command_name,
            risk_level=self.risk_level,
            mode=self.mode,
            params_summary=self.params_summary,
            confirmation_required=self.confirmation_required,
            confirmation_status=self.confirmation_status,
            result_status=self.result_status,
            error_message=self.error_message,
            duration_ms=self.duration_ms,
            created_at=self.created_at,
        )


class TerminalRuntimeSettingsORM(models.Model):
    """Terminal runtime settings singleton."""

    singleton_key = models.CharField(max_length=32, unique=True, default='default', editable=False)
    answer_chain_enabled = models.BooleanField(
        default=True,
        help_text="是否允许在 Terminal 回答中展开查看答案链条",
    )
    fallback_chat_system_prompt = models.TextField(
        blank=True,
        default='',
        help_text=(
            "Terminal 与共享网页聊天在 fallback 普通对话时注入的系统提示词。"
            "可由管理员控制回答范围，例如系统状态、Regime、持仓、信号、回测、"
            "RSS 新闻、政策、热点、配置中心等。留空则使用系统默认提示词。"
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'terminal_runtime_settings'
        verbose_name = "Terminal 运行设置"
        verbose_name_plural = "Terminal 运行设置"

    def __str__(self) -> str:
        return "Terminal 运行设置"

    @classmethod
    def get_solo(cls) -> 'TerminalRuntimeSettingsORM':
        settings_obj, _ = cls.objects.get_or_create(
            singleton_key='default',
            defaults={'answer_chain_enabled': True, 'fallback_chat_system_prompt': ''},
        )
        return settings_obj


__all__ = ['TerminalCommandORM', 'TerminalAuditLogORM', 'TerminalRuntimeSettingsORM']
