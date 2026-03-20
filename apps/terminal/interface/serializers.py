"""
Terminal Interface Serializers.

DRF序列化器定义。
"""

from rest_framework import serializers
from ..infrastructure.models import TerminalCommandORM


class CommandParameterSerializer(serializers.Serializer):
    """命令参数序列化器"""
    name = serializers.CharField(max_length=50)
    type = serializers.ChoiceField(choices=['text', 'number', 'select', 'date', 'boolean'], default='text')
    description = serializers.CharField(allow_blank=True, required=False)
    required = serializers.BooleanField(default=True)
    default = serializers.JSONField(required=False, allow_null=True)
    options = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    prompt = serializers.CharField(allow_blank=True, required=False)


class TerminalCommandSerializer(serializers.ModelSerializer):
    """终端命令序列化器"""

    type = serializers.CharField(source='command_type', read_only=True)
    param_count = serializers.SerializerMethodField()

    class Meta:
        model = TerminalCommandORM
        fields = [
            'id', 'name', 'description', 'type', 'command_type',
            'prompt_template', 'system_prompt', 'user_prompt_template',
            'api_endpoint', 'api_method', 'response_jq_filter',
            'parameters', 'param_count',
            'timeout', 'provider_name', 'model_name',
            'risk_level', 'requires_mcp', 'enabled_in_terminal',
            'category', 'tags', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_param_count(self, obj):
        return len(obj.parameters) if obj.parameters else 0


class TerminalCommandCreateSerializer(serializers.ModelSerializer):
    """终端命令创建序列化器"""

    parameters = CommandParameterSerializer(many=True, required=False, default=list)
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)

    class Meta:
        model = TerminalCommandORM
        fields = [
            'name', 'description', 'command_type',
            'prompt_template', 'system_prompt', 'user_prompt_template',
            'api_endpoint', 'api_method', 'response_jq_filter',
            'parameters', 'timeout', 'provider_name', 'model_name',
            'risk_level', 'requires_mcp', 'enabled_in_terminal',
            'category', 'tags', 'is_active'
        ]

    def validate_parameters(self, value):
        """验证参数格式"""
        for param in value:
            if param.get('type') == 'select' and not param.get('options'):
                raise serializers.ValidationError(
                    f"Parameter '{param.get('name')}' of type 'select' must have 'options'"
                )
        return value


class TerminalCommandUpdateSerializer(serializers.ModelSerializer):
    """终端命令更新序列化器"""

    parameters = CommandParameterSerializer(many=True, required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False)

    class Meta:
        model = TerminalCommandORM
        fields = [
            'name', 'description', 'command_type',
            'prompt_template', 'system_prompt', 'user_prompt_template',
            'api_endpoint', 'api_method', 'response_jq_filter',
            'parameters', 'timeout', 'provider_name', 'model_name',
            'risk_level', 'requires_mcp', 'enabled_in_terminal',
            'category', 'tags', 'is_active'
        ]
        extra_kwargs = {
            field: {'required': False}
            for field in fields
        }


class ExecuteCommandSerializer(serializers.Serializer):
    """执行命令请求序列化器"""
    name = serializers.CharField(max_length=50)
    params = serializers.DictField(required=False, default=dict)
    session_id = serializers.CharField(allow_blank=True, required=False)
    provider_name = serializers.CharField(allow_blank=True, required=False)
    model_name = serializers.CharField(allow_blank=True, required=False)
    mode = serializers.ChoiceField(
        choices=['readonly', 'confirm_each', 'auto_confirm'],
        default='confirm_each',
        required=False,
    )
    confirmation_token = serializers.CharField(required=False, allow_blank=True)


class ExecuteCommandResponseSerializer(serializers.Serializer):
    """执行命令响应序列化器"""
    success = serializers.BooleanField()
    output = serializers.CharField(allow_blank=True, default='')
    metadata = serializers.DictField(default=dict)
    error = serializers.CharField(allow_null=True, allow_blank=True, default=None)
    command = serializers.DictField(allow_null=True, default=None)
    confirmation_required = serializers.BooleanField(default=False)
    confirmation_token = serializers.CharField(allow_null=True, allow_blank=True, default=None)
    confirmation_prompt = serializers.CharField(allow_null=True, allow_blank=True, default=None)
    command_summary = serializers.CharField(allow_null=True, allow_blank=True, default=None)
    risk_level = serializers.CharField(allow_null=True, allow_blank=True, default=None)


class AvailableCommandSerializer(serializers.Serializer):
    """可用命令列表序列化器（简化版）"""
    name = serializers.CharField()
    description = serializers.CharField()
    type = serializers.CharField()
    category = serializers.CharField()
    parameters = CommandParameterSerializer(many=True)
    is_active = serializers.BooleanField()
    risk_level = serializers.CharField(default='read')
    requires_mcp = serializers.BooleanField(default=True)
    confirmation_required = serializers.BooleanField(default=False)
    terminal_enabled = serializers.BooleanField(default=True)


class ConfirmExecuteSerializer(serializers.Serializer):
    """确认执行请求序列化器"""
    name = serializers.CharField(max_length=50)
    params = serializers.DictField(required=False, default=dict)
    confirmation_token = serializers.CharField()
    session_id = serializers.CharField(allow_blank=True, required=False)
    mode = serializers.ChoiceField(
        choices=['readonly', 'confirm_each', 'auto_confirm'],
        default='confirm_each',
        required=False,
    )


class TerminalCapabilitiesSerializer(serializers.Serializer):
    """终端能力信息序列化器"""
    mcp_enabled = serializers.BooleanField()
    role = serializers.CharField()
    available_modes = serializers.ListField(child=serializers.CharField())
    current_mode = serializers.CharField()
    max_risk_level = serializers.CharField()
    reason_if_locked = serializers.CharField(allow_blank=True, allow_null=True, default=None)
    answer_chain_enabled = serializers.BooleanField(default=False)
    answer_chain_visibility = serializers.CharField(default='masked')


class TerminalAuditEntrySerializer(serializers.Serializer):
    """终端审计条目序列化器"""
    username = serializers.CharField()
    session_id = serializers.CharField()
    command_name = serializers.CharField()
    risk_level = serializers.CharField()
    mode = serializers.CharField()
    params_summary = serializers.CharField(allow_blank=True)
    confirmation_required = serializers.BooleanField()
    confirmation_status = serializers.CharField()
    result_status = serializers.CharField()
    error_message = serializers.CharField(allow_blank=True)
    duration_ms = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class TerminalChatRequestSerializer(serializers.Serializer):
    """Terminal 自然语言输入请求"""
    message = serializers.CharField()
    session_id = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    context = serializers.JSONField(allow_null=True, required=False)
    provider_ref = serializers.JSONField(required=False)
    provider_name = serializers.CharField(allow_blank=True, required=False)
    model = serializers.CharField(allow_blank=True, required=False)


class TerminalChatResponseSerializer(serializers.Serializer):
    """Terminal 自然语言输出响应"""
    reply = serializers.CharField()
    session_id = serializers.CharField()
    metadata = serializers.JSONField()
    route_confirmation_required = serializers.BooleanField(default=False)
    selected_capability_key = serializers.CharField(allow_null=True, allow_blank=True, default=None)
    suggested_command = serializers.CharField(allow_null=True, allow_blank=True, default=None)
    suggested_intent = serializers.CharField(allow_null=True, allow_blank=True, default=None)
    suggestion_prompt = serializers.CharField(allow_null=True, allow_blank=True, default=None)
    missing_params = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )
