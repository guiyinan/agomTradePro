"""
ORM Models for AI Prompt Management.

Django models for persisting prompt templates, chain configurations,
and execution logs.
"""

from django.db import models
from django.core.exceptions import ValidationError


class PromptTemplateORM(models.Model):
    """Prompt模板ORM模型"""

    CATEGORY_CHOICES = [
        ('report', 'Report Analysis'),
        ('signal', 'Signal Generation'),
        ('analysis', 'Data Analysis'),
        ('chat', 'Chat'),
    ]

    # 基本信息
    name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="模板名称（唯一标识）"
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        db_index=True,
        help_text="分类"
    )
    version = models.CharField(
        max_length=20,
        default="1.0",
        help_text="版本号"
    )

    # 模板内容
    template_content = models.TextField(
        help_text="模板内容（支持Jinja2语法）"
    )
    system_prompt = models.TextField(
        blank=True,
        help_text="系统提示词"
    )

    # 占位符定义（JSON存储）
    placeholders = models.JSONField(
        default=list,
        blank=True,
        help_text="占位符定义列表"
    )

    # AI参数
    temperature = models.FloatField(
        default=0.7,
        help_text="温度参数（0.0-2.0）"
    )
    max_tokens = models.IntegerField(
        null=True,
        blank=True,
        help_text="最大token数"
    )

    # 元数据
    description = models.TextField(
        blank=True,
        help_text="描述"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="是否激活"
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="最后使用时间"
    )

    class Meta:
        db_table = 'prompt_template'
        ordering = ['category', 'name']
        verbose_name = "Prompt模板"
        verbose_name_plural = "Prompt模板"
        indexes = [
            models.Index(fields=['category', 'is_active']),
        ]

    def __str__(self):
        return f"{self.category}/{self.name}@{self.version}"

    def clean(self):
        """验证数据"""
        super().clean()

        # 验证temperature
        if not (0 <= self.temperature <= 2):
            raise ValidationError({
                'temperature': 'temperature必须在0.0-2.0之间'
            })

        # 验证max_tokens
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValidationError({
                'max_tokens': 'max_tokens必须为正数'
            })

        # 验证placeholders格式
        if not isinstance(self.placeholders, list):
            raise ValidationError({
                'placeholders': 'placeholders必须是列表格式'
            })


class ChainConfigORM(models.Model):
    """链式配置ORM模型"""

    EXECUTION_MODE_CHOICES = [
        ('serial', 'Serial'),
        ('parallel', 'Parallel'),
        ('tool', 'Tool Calling'),
        ('hybrid', 'Hybrid'),
    ]

    name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="链名称（唯一标识）"
    )
    category = models.CharField(
        max_length=20,
        choices=PromptTemplateORM.CATEGORY_CHOICES,
        db_index=True,
        help_text="分类"
    )
    description = models.TextField(
        blank=True,
        help_text="描述"
    )
    steps = models.JSONField(
        default=list,
        help_text="步骤定义列表"
    )
    execution_mode = models.CharField(
        max_length=20,
        choices=EXECUTION_MODE_CHOICES,
        default='serial',
        help_text="执行模式"
    )
    aggregate_step = models.JSONField(
        null=True,
        blank=True,
        help_text="汇总步骤配置"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
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
        db_table = 'chain_config'
        ordering = ['category', 'name']
        verbose_name = "链配置"
        verbose_name_plural = "链配置"
        indexes = [
            models.Index(fields=['category', 'is_active']),
        ]

    def __str__(self):
        return f"{self.category}/{self.name} ({self.execution_mode})"


class PromptExecutionLogORM(models.Model):
    """Prompt执行日志ORM模型"""

    STATUS_CHOICES = [
        ('success', 'Success'),
        ('error', 'Error'),
        ('timeout', 'Timeout'),
    ]

    # 关联
    template = models.ForeignKey(
        PromptTemplateORM,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='execution_logs',
        help_text="关联的模板"
    )
    chain = models.ForeignKey(
        ChainConfigORM,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='execution_logs',
        help_text="关联的链"
    )

    # 执行信息
    execution_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text="执行ID"
    )
    step_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="步骤ID"
    )

    # 请求
    placeholder_values = models.JSONField(
        default=dict,
        blank=True,
        help_text="占位符值"
    )
    rendered_prompt = models.TextField(
        help_text="渲染后的Prompt"
    )

    # 响应
    ai_response = models.TextField(
        help_text="AI响应内容"
    )
    parsed_output = models.JSONField(
        null=True,
        blank=True,
        help_text="解析后的输出"
    )

    # 性能指标
    response_time_ms = models.IntegerField(
        help_text="响应时间（毫秒）"
    )
    prompt_tokens = models.IntegerField(
        default=0,
        help_text="输入token数"
    )
    completion_tokens = models.IntegerField(
        default=0,
        help_text="输出token数"
    )
    total_tokens = models.IntegerField(
        default=0,
        help_text="总token数"
    )
    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
        help_text="预估成本"
    )

    # 提供商信息
    provider_used = models.CharField(
        max_length=50,
        blank=True,
        help_text="使用的提供商"
    )
    model_used = models.CharField(
        max_length=50,
        blank=True,
        help_text="使用的模型"
    )

    # 状态
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='success',
        help_text="执行状态"
    )
    error_message = models.TextField(
        blank=True,
        help_text="错误信息"
    )

    # 时间戳
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="执行时间"
    )

    class Meta:
        db_table = 'prompt_execution_log'
        ordering = ['-created_at']
        verbose_name = "执行日志"
        verbose_name_plural = "执行日志"
        indexes = [
            models.Index(fields=['execution_id', '-created_at']),
            models.Index(fields=['template', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"{self.execution_id} - {self.status}"


class ChatSessionORM(models.Model):
    """聊天会话ORM模型"""

    session_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="会话ID"
    )
    user_message = models.TextField(
        help_text="用户消息"
    )
    ai_response = models.TextField(
        help_text="AI响应"
    )
    context = models.JSONField(
        default=dict,
        blank=True,
        help_text="上下文数据"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="创建时间"
    )

    class Meta:
        db_table = 'chat_session'
        ordering = ['-created_at']
        verbose_name = "聊天会话"
        verbose_name_plural = "聊天会话"

    def __str__(self):
        return f"Session: {self.session_id}"


class TerminalCommandORM(models.Model):
    """
    终端命令配置ORM模型
    
    支持两种执行类型：
    - prompt: 调用Prompt模板，通过AI生成响应
    - api: 调用系统API端点
    """

    COMMAND_TYPE_CHOICES = [
        ('prompt', 'Prompt模板调用'),
        ('api', 'API端点调用'),
        ('builtin', '内置命令'),
    ]

    OUTPUT_FORMAT_CHOICES = [
        ('text', '纯文本'),
        ('json', 'JSON格式'),
        ('table', '表格格式'),
        ('markdown', 'Markdown格式'),
    ]

    # 基本信息
    name = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="命令名称（如：analyze, report）"
    )
    display_name = models.CharField(
        max_length=100,
        help_text="显示名称"
    )
    description = models.TextField(
        blank=True,
        help_text="命令描述"
    )
    category = models.CharField(
        max_length=50,
        default='general',
        db_index=True,
        help_text="命令分类"
    )

    # 执行配置
    command_type = models.CharField(
        max_length=20,
        choices=COMMAND_TYPE_CHOICES,
        default='prompt',
        help_text="命令类型"
    )
    
    # Prompt类型配置
    prompt_template = models.ForeignKey(
        PromptTemplateORM,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='terminal_commands',
        help_text="关联的Prompt模板（command_type=prompt时使用）"
    )
    system_prompt_override = models.TextField(
        blank=True,
        help_text="覆盖系统提示词（可选）"
    )
    
    # API类型配置
    api_endpoint = models.CharField(
        max_length=255,
        blank=True,
        help_text="API端点路径（command_type=api时使用，如：/api/regime/current/）"
    )
    api_method = models.CharField(
        max_length=10,
        default='GET',
        help_text="HTTP方法（GET/POST）"
    )
    api_payload_template = models.JSONField(
        default=dict,
        blank=True,
        help_text="API请求体模板（支持变量插值）"
    )
    
    # 响应处理
    response_jq_filter = models.CharField(
        max_length=255,
        blank=True,
        help_text="JQ过滤器，从API响应中提取数据"
    )
    output_format = models.CharField(
        max_length=20,
        choices=OUTPUT_FORMAT_CHOICES,
        default='text',
        help_text="输出格式"
    )
    output_template = models.TextField(
        blank=True,
        help_text="输出模板（Jinja2格式，可使用{{变量}}）"
    )

    # 参数定义（交互式输入）
    # 格式: [{"name": "symbol", "type": "text", "prompt": "请输入股票代码", "required": true, "default": ""}]
    parameters = models.JSONField(
        default=list,
        blank=True,
        help_text="参数定义列表（用于交互式输入）"
    )

    # 权限和状态
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="是否启用"
    )
    requires_auth = models.BooleanField(
        default=True,
        help_text="是否需要登录"
    )
    allowed_roles = models.JSONField(
        default=list,
        blank=True,
        help_text="允许访问的角色列表（空表示所有用户）"
    )

    # 使用统计
    usage_count = models.IntegerField(
        default=0,
        help_text="使用次数"
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="最后使用时间"
    )

    # 排序和分组
    sort_order = models.IntegerField(
        default=0,
        help_text="排序顺序"
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")

    class Meta:
        db_table = 'terminal_command'
        ordering = ['category', 'sort_order', 'name']
        verbose_name = "终端命令"
        verbose_name_plural = "终端命令配置"
        indexes = [
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['command_type', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_command_type_display()})"

    def clean(self):
        """验证配置"""
        super().clean()
        
        # Prompt类型必须关联模板
        if self.command_type == 'prompt' and not self.prompt_template:
            from django.core.exceptions import ValidationError
            raise ValidationError({
                'prompt_template': 'Prompt类型命令必须关联Prompt模板'
            })
        
        # API类型必须配置端点
        if self.command_type == 'api' and not self.api_endpoint:
            from django.core.exceptions import ValidationError
            raise ValidationError({
                'api_endpoint': 'API类型命令必须配置API端点'
            })

    def get_parameter_schema(self):
        """获取参数的JSON Schema，用于前端验证"""
        schema = {
            "type": "object",
            "properties": {},
            "required": []
        }
        
        for param in self.parameters:
            name = param.get('name', '')
            param_type = param.get('type', 'text')
            
            # 映射到JSON Schema类型
            type_map = {
                'text': 'string',
                'number': 'number',
                'integer': 'integer',
                'boolean': 'boolean',
                'select': 'string',
                'date': 'string',
            }
            
            schema['properties'][name] = {
                'type': type_map.get(param_type, 'string'),
                'description': param.get('prompt', ''),
                'default': param.get('default', ''),
            }
            
            if param.get('required', False):
                schema['required'].append(name)
            
            if param_type == 'select':
                schema['properties'][name]['enum'] = param.get('options', [])
        
        return schema
