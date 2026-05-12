"""
DRF Serializers for AI Prompt Management.

Django Rest Framework serializers for request/response validation.
"""

from rest_framework import serializers

from ..application.interface_services import (
    create_chain_config,
    create_prompt_template,
    update_chain_config,
    update_prompt_template,
)

PROMPT_CATEGORY_CHOICES = [
    "report",
    "signal",
    "analysis",
    "chat",
]

CHAIN_EXECUTION_MODE_CHOICES = [
    "serial",
    "parallel",
    "tool",
    "hybrid",
]


class PlaceholderSerializer(serializers.Serializer):
    """占位符序列化器"""
    name = serializers.CharField(max_length=50)
    type = serializers.ChoiceField(choices=[
        'simple', 'structured', 'function', 'conditional'
    ])
    description = serializers.CharField(allow_blank=True, required=False)
    default_value = serializers.JSONField(required=False, allow_null=True)
    required = serializers.BooleanField(default=True)
    function_name = serializers.CharField(allow_blank=True, required=False)
    function_params = serializers.JSONField(required=False, allow_null=True)


class PromptTemplateSerializer(serializers.Serializer):
    """Prompt模板序列化器"""
    id = serializers.CharField(read_only=True)
    name = serializers.CharField(max_length=100)
    category = serializers.ChoiceField(choices=PROMPT_CATEGORY_CHOICES)
    version = serializers.CharField(max_length=20, required=False, default="1.0")
    template_content = serializers.CharField()
    system_prompt = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        required=False,
    )
    placeholders = PlaceholderSerializer(many=True, required=False)
    temperature = serializers.FloatField(required=False, default=0.7)
    max_tokens = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(allow_blank=True, required=False, default="")
    is_active = serializers.BooleanField(required=False, default=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    last_used_at = serializers.DateTimeField(read_only=True, allow_null=True)

    def validate_temperature(self, value):
        """验证温度参数"""
        if not (0 <= value <= 2):
            raise serializers.ValidationError("temperature必须在0.0-2.0之间")
        return value

    def validate_max_tokens(self, value):
        """验证最大token数"""
        if value is not None and value <= 0:
            raise serializers.ValidationError("max_tokens必须为正数")
        return value

    def validate_placeholders(self, value):
        """验证占位符格式"""
        if not isinstance(value, list):
            raise serializers.ValidationError("placeholders必须是列表格式")

        # 使用嵌套序列化器验证每个占位符
        for ph in value:
            serializer = PlaceholderSerializer(data=ph)
            if not serializer.is_valid():
                raise serializers.ValidationError(f"占位符验证失败: {serializer.errors}")

        return value

    def to_representation(self, instance):
        """Normalize domain entities and ORM instances into the same payload."""

        data = super().to_representation(instance)
        category = getattr(instance, "category", None)
        if hasattr(category, "value"):
            data["category"] = category.value

        placeholders = getattr(instance, "placeholders", None) or []
        if placeholders and not isinstance(placeholders[0], dict):
            data["placeholders"] = [
                {
                    "name": placeholder.name,
                    "type": placeholder.type.value,
                    "description": placeholder.description,
                    "default_value": placeholder.default_value,
                    "required": placeholder.required,
                    "function_name": placeholder.function_name,
                    "function_params": placeholder.function_params,
                }
                for placeholder in placeholders
            ]

        return data


class PromptTemplateCreateSerializer(PromptTemplateSerializer):
    """Prompt模板创建序列化器"""

    def _build_entity(self, validated_data):
        """Build the prompt template domain entity from validated data."""

        from ..domain.entities import (
            PlaceholderDef,
            PlaceholderType,
            PromptCategory,
            PromptTemplate,
        )

        placeholders_data = validated_data.pop('placeholders', [])

        placeholders = [
            PlaceholderDef(
                name=p['name'],
                type=PlaceholderType(p['type']),
                description=p.get('description', ''),
                default_value=p.get('default_value'),
                required=p.get('required', True),
                function_name=p.get('function_name'),
                function_params=p.get('function_params')
            )
            for p in placeholders_data
        ]

        entity = PromptTemplate(
            id=None,
            name=validated_data['name'],
            category=PromptCategory(validated_data['category']),
            version=validated_data.get('version', '1.0'),
            template_content=validated_data['template_content'],
            placeholders=placeholders,
            system_prompt=validated_data.get('system_prompt'),
            temperature=validated_data.get('temperature', 0.7),
            max_tokens=validated_data.get('max_tokens'),
            description=validated_data.get('description', ''),
            is_active=validated_data.get('is_active', True)
        )
        return entity

    def create(self, validated_data):
        """创建模板"""

        return create_prompt_template(self._build_entity(dict(validated_data)))

    def update(self, instance, validated_data):
        """更新模板"""

        merged_data = {
            "name": getattr(instance, "name", ""),
            "category": getattr(getattr(instance, "category", None), "value", getattr(instance, "category", "")),
            "version": getattr(instance, "version", "1.0"),
            "template_content": getattr(instance, "template_content", ""),
            "placeholders": getattr(instance, "placeholders", []),
            "system_prompt": getattr(instance, "system_prompt", None),
            "temperature": getattr(instance, "temperature", 0.7),
            "max_tokens": getattr(instance, "max_tokens", None),
            "description": getattr(instance, "description", ""),
            "is_active": getattr(instance, "is_active", True),
        }
        merged_data.update(validated_data)
        updated = update_prompt_template(int(instance.id), self._build_entity(merged_data))
        if updated is None:
            raise serializers.ValidationError("模板不存在或更新失败")
        return updated


class ChainStepSerializer(serializers.Serializer):
    """链步骤序列化器"""
    step_id = serializers.CharField(max_length=50)
    template_id = serializers.CharField()
    step_name = serializers.CharField(max_length=100)
    order = serializers.IntegerField()
    input_mapping = serializers.JSONField()
    output_parser = serializers.CharField(allow_blank=True, required=False)
    parallel_group = serializers.CharField(allow_blank=True, required=False)
    enable_tool_calling = serializers.BooleanField(default=False)
    available_tools = serializers.ListField(
        child=serializers.CharField(),
        allow_null=True,
        required=False
    )


class ChainConfigSerializer(serializers.Serializer):
    """链配置序列化器"""
    id = serializers.CharField(read_only=True)
    name = serializers.CharField(max_length=100)
    category = serializers.ChoiceField(choices=PROMPT_CATEGORY_CHOICES)
    description = serializers.CharField(allow_blank=True, required=False, default="")
    steps = ChainStepSerializer(many=True)
    execution_mode = serializers.ChoiceField(choices=CHAIN_EXECUTION_MODE_CHOICES)
    aggregate_step = ChainStepSerializer(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, default=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def validate_steps(self, value):
        """验证步骤配置"""
        if not isinstance(value, list):
            raise serializers.ValidationError("steps必须是列表格式")

        # 验证每个步骤
        for step in value:
            serializer = ChainStepSerializer(data=step)
            if not serializer.is_valid():
                raise serializers.ValidationError(f"步骤验证失败: {serializer.errors}")

        # 检查order唯一性
        orders = [s.get('order') for s in value]
        if len(orders) != len(set(orders)):
            raise serializers.ValidationError("步骤order必须唯一")

        return value

    def to_representation(self, instance):
        """Normalize domain entities and ORM instances into the same payload."""

        data = super().to_representation(instance)
        category = getattr(instance, "category", None)
        execution_mode = getattr(instance, "execution_mode", None)
        if hasattr(category, "value"):
            data["category"] = category.value
        if hasattr(execution_mode, "value"):
            data["execution_mode"] = execution_mode.value

        def _serialize_step(step):
            if isinstance(step, dict):
                return step
            return {
                "step_id": step.step_id,
                "template_id": step.template_id,
                "step_name": step.step_name,
                "order": step.order,
                "input_mapping": step.input_mapping,
                "output_parser": step.output_parser,
                "parallel_group": step.parallel_group,
                "enable_tool_calling": step.enable_tool_calling,
                "available_tools": step.available_tools,
            }

        steps = getattr(instance, "steps", None) or []
        data["steps"] = [_serialize_step(step) for step in steps]

        aggregate_step = getattr(instance, "aggregate_step", None)
        data["aggregate_step"] = _serialize_step(aggregate_step) if aggregate_step else None
        return data


class ChainConfigCreateSerializer(ChainConfigSerializer):
    """链配置创建序列化器"""

    def _build_entity(self, validated_data):
        """Build the chain config domain entity from validated data."""

        from ..domain.entities import ChainConfig, ChainExecutionMode, ChainStep, PromptCategory

        steps_data = validated_data.pop('steps')
        aggregate_data = validated_data.pop('aggregate_step', None)

        steps = [
            ChainStep(
                step_id=s['step_id'],
                template_id=s['template_id'],
                step_name=s['step_name'],
                order=s['order'],
                input_mapping=s['input_mapping'],
                output_parser=s.get('output_parser'),
                parallel_group=s.get('parallel_group'),
                enable_tool_calling=s.get('enable_tool_calling', False),
                available_tools=s.get('available_tools')
            )
            for s in steps_data
        ]

        aggregate_step = None
        if aggregate_data:
            aggregate_step = ChainStep(
                step_id=aggregate_data['step_id'],
                template_id=aggregate_data['template_id'],
                step_name=aggregate_data['step_name'],
                order=aggregate_data['order'],
                input_mapping=aggregate_data['input_mapping'],
                output_parser=aggregate_data.get('output_parser'),
                parallel_group=aggregate_data.get('parallel_group'),
                enable_tool_calling=aggregate_data.get('enable_tool_calling', False),
                available_tools=aggregate_data.get('available_tools')
            )

        entity = ChainConfig(
            id=None,
            name=validated_data['name'],
            category=PromptCategory(validated_data['category']),
            description=validated_data.get('description', ''),
            steps=steps,
            execution_mode=ChainExecutionMode(validated_data['execution_mode']),
            aggregate_step=aggregate_step,
            is_active=validated_data.get('is_active', True)
        )
        return entity

    def create(self, validated_data):
        """创建链配置"""

        return create_chain_config(self._build_entity(dict(validated_data)))

    def update(self, instance, validated_data):
        """更新链配置"""

        merged_data = {
            "name": getattr(instance, "name", ""),
            "category": getattr(getattr(instance, "category", None), "value", getattr(instance, "category", "")),
            "description": getattr(instance, "description", ""),
            "steps": getattr(instance, "steps", []),
            "execution_mode": getattr(
                getattr(instance, "execution_mode", None),
                "value",
                getattr(instance, "execution_mode", "serial"),
            ),
            "aggregate_step": getattr(instance, "aggregate_step", None),
            "is_active": getattr(instance, "is_active", True),
        }
        merged_data.update(validated_data)
        updated = update_chain_config(int(instance.id), self._build_entity(merged_data))
        if updated is None:
            raise serializers.ValidationError("链配置不存在或更新失败")
        return updated


class ExecutePromptSerializer(serializers.Serializer):
    """执行Prompt请求序列化器"""
    template_id = serializers.IntegerField()
    placeholder_values = serializers.JSONField(default=dict)
    provider_ref = serializers.JSONField(required=False)
    provider_name = serializers.CharField(allow_blank=True, required=False)
    model = serializers.CharField(allow_blank=True, required=False)
    temperature = serializers.FloatField(allow_null=True, required=False)
    max_tokens = serializers.IntegerField(allow_null=True, required=False)


class ExecutePromptResponseSerializer(serializers.Serializer):
    """执行Prompt响应序列化器"""
    success = serializers.BooleanField()
    content = serializers.CharField()
    provider_used = serializers.CharField(allow_blank=True)
    model_used = serializers.CharField(allow_blank=True)
    prompt_tokens = serializers.IntegerField()
    completion_tokens = serializers.IntegerField()
    total_tokens = serializers.IntegerField()
    estimated_cost = serializers.FloatField()
    response_time_ms = serializers.IntegerField()
    error_message = serializers.CharField(allow_blank=True, required=False)
    parsed_output = serializers.JSONField(allow_null=True, required=False)
    template_name = serializers.CharField()


class ExecuteChainSerializer(serializers.Serializer):
    """执行链请求序列化器"""
    chain_id = serializers.IntegerField()
    placeholder_values = serializers.JSONField(default=dict)
    provider_ref = serializers.JSONField(required=False)
    provider_name = serializers.CharField(allow_blank=True, required=False)
    model = serializers.CharField(allow_blank=True, required=False)


class ExecuteChainResponseSerializer(serializers.Serializer):
    """执行链响应序列化器"""
    success = serializers.BooleanField()
    chain_name = serializers.CharField()
    execution_mode = serializers.CharField()
    step_results = serializers.JSONField()
    final_output = serializers.CharField(allow_blank=True, required=False)
    total_tokens = serializers.IntegerField()
    total_cost = serializers.FloatField()
    total_time_ms = serializers.IntegerField()
    error_message = serializers.CharField(allow_blank=True, required=False)


class GenerateReportSerializer(serializers.Serializer):
    """生成报告请求序列化器"""
    as_of_date = serializers.DateField()
    include_regime = serializers.BooleanField(default=True)
    include_policy = serializers.BooleanField(default=True)
    include_macro = serializers.BooleanField(default=True)
    indicators = serializers.ListField(
        child=serializers.CharField(),
        allow_null=True,
        required=False
    )
    provider_ref = serializers.JSONField(required=False)
    provider_name = serializers.CharField(allow_blank=True, required=False)
    model = serializers.CharField(allow_blank=True, required=False)


class GenerateReportResponseSerializer(serializers.Serializer):
    """生成报告响应序列化器"""
    report = serializers.CharField()
    metadata = serializers.JSONField()


class GenerateSignalSerializer(serializers.Serializer):
    """生成信号请求序列化器"""
    asset_code = serializers.CharField(max_length=20)
    analysis_context = serializers.JSONField(default=dict)
    provider_ref = serializers.JSONField(required=False)
    provider_name = serializers.CharField(allow_blank=True, required=False)


class GenerateSignalResponseSerializer(serializers.Serializer):
    """生成信号响应序列化器"""
    asset_code = serializers.CharField()
    direction = serializers.CharField()
    logic_desc = serializers.CharField()
    invalidation_logic = serializers.CharField()
    invalidation_threshold = serializers.FloatField(allow_null=True, required=False)
    target_regime = serializers.CharField()
    confidence = serializers.FloatField()


class ChatRequestSerializer(serializers.Serializer):
    """聊天请求序列化器"""
    message = serializers.CharField()
    session_id = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    context = serializers.JSONField(allow_null=True, required=False)
    provider_ref = serializers.JSONField(required=False)
    provider_name = serializers.CharField(allow_blank=True, required=False)
    model = serializers.CharField(allow_blank=True, required=False)


class ChatResponseSerializer(serializers.Serializer):
    """聊天响应序列化器"""
    reply = serializers.CharField()
    session_id = serializers.CharField()
    metadata = serializers.JSONField()


class ExecutionLogSerializer(serializers.Serializer):
    """执行日志序列化器"""
    id = serializers.IntegerField(read_only=True)
    execution_id = serializers.CharField(read_only=True)
    template_id = serializers.IntegerField(read_only=True, allow_null=True)
    chain_id = serializers.IntegerField(read_only=True, allow_null=True)
    step_id = serializers.CharField(read_only=True, allow_null=True, allow_blank=True)
    status = serializers.CharField(read_only=True)
    provider_used = serializers.CharField(read_only=True, allow_blank=True)
    model_used = serializers.CharField(read_only=True, allow_blank=True)
    total_tokens = serializers.IntegerField(read_only=True)
    estimated_cost = serializers.DecimalField(
        max_digits=10,
        decimal_places=6,
        read_only=True,
    )
    response_time_ms = serializers.IntegerField(read_only=True)
    error_message = serializers.CharField(read_only=True, allow_blank=True)
    created_at = serializers.DateTimeField(read_only=True)


class ChatSessionSerializer(serializers.Serializer):
    """聊天会话序列化器"""
    id = serializers.IntegerField(read_only=True)
    session_id = serializers.CharField(read_only=True)
    user_message = serializers.CharField(read_only=True)
    ai_response = serializers.CharField(read_only=True)
    context = serializers.JSONField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


# ==================== Agent Runtime Serializers ====================


class AgentExecuteRequestSerializer(serializers.Serializer):
    """Agent Runtime 执行请求序列化器"""
    task_type = serializers.CharField(max_length=50)
    user_input = serializers.CharField()
    provider_ref = serializers.JSONField(required=False, allow_null=True)
    model = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    temperature = serializers.FloatField(required=False, allow_null=True)
    max_tokens = serializers.IntegerField(required=False, allow_null=True)
    context_scope = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True
    )
    context_params = serializers.JSONField(required=False, allow_null=True)
    tool_names = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True
    )
    response_schema = serializers.JSONField(required=False, allow_null=True)
    max_rounds = serializers.IntegerField(default=4, required=False)
    session_id = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    system_prompt = serializers.CharField(required=False, allow_null=True)
    metadata = serializers.JSONField(required=False, allow_null=True)


class ToolCallRecordSerializer(serializers.Serializer):
    """工具调用记录序列化器"""
    tool_name = serializers.CharField()
    arguments = serializers.JSONField()
    success = serializers.BooleanField()
    result = serializers.JSONField(allow_null=True)
    error_message = serializers.CharField(allow_null=True, required=False)
    duration_ms = serializers.IntegerField()


class AgentExecuteResponseSerializer(serializers.Serializer):
    """Agent Runtime 执行响应序列化器"""
    success = serializers.BooleanField()
    final_answer = serializers.CharField(allow_null=True, allow_blank=True)
    structured_output = serializers.JSONField(allow_null=True, required=False)
    used_context = serializers.ListField(
        child=serializers.CharField(), allow_null=True, required=False
    )
    tool_calls = ToolCallRecordSerializer(many=True, allow_null=True, required=False)
    turn_count = serializers.IntegerField()
    provider_used = serializers.CharField(allow_null=True, allow_blank=True)
    model_used = serializers.CharField(allow_null=True, allow_blank=True)
    total_tokens = serializers.IntegerField()
    prompt_tokens = serializers.IntegerField()
    completion_tokens = serializers.IntegerField()
    estimated_cost = serializers.FloatField()
    response_time_ms = serializers.IntegerField()
    error_message = serializers.CharField(allow_null=True, required=False)
    execution_id = serializers.CharField(allow_null=True)
