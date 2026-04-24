"""
Terminal Interface Serializers.

DRF序列化器定义。
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..domain.entities import CommandType, TerminalRiskLevel


class CommandParameterSerializer(serializers.Serializer):
    """命令参数序列化器"""

    name = serializers.CharField(max_length=50)
    type = serializers.ChoiceField(
        choices=['text', 'number', 'select', 'date', 'boolean'],
        default='text',
    )
    description = serializers.CharField(allow_blank=True, required=False)
    required = serializers.BooleanField(default=True)
    default = serializers.JSONField(required=False, allow_null=True)
    options = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )
    prompt = serializers.CharField(allow_blank=True, required=False)


class TerminalCommandSerializer(serializers.Serializer):
    """终端命令响应序列化器"""

    id = serializers.CharField()
    name = serializers.CharField(max_length=50)
    description = serializers.CharField(allow_blank=True)
    type = serializers.ChoiceField(choices=[choice.value for choice in CommandType])
    command_type = serializers.ChoiceField(choices=[choice.value for choice in CommandType])
    prompt_template = serializers.CharField(allow_null=True, required=False)
    system_prompt = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    user_prompt_template = serializers.CharField(allow_blank=True, required=False)
    api_endpoint = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    api_method = serializers.CharField(allow_blank=True, required=False)
    response_jq_filter = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    parameters = CommandParameterSerializer(many=True, required=False, default=list)
    param_count = serializers.IntegerField(required=False)
    timeout = serializers.IntegerField()
    provider_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    model_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    risk_level = serializers.ChoiceField(choices=[choice.value for choice in TerminalRiskLevel])
    requires_mcp = serializers.BooleanField()
    enabled_in_terminal = serializers.BooleanField()
    category = serializers.CharField()
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField(allow_null=True, required=False)
    updated_at = serializers.DateTimeField(allow_null=True, required=False)

    @extend_schema_field(OpenApiTypes.INT)
    def get_param_count(self, obj) -> int:
        return len(obj.get("parameters", []) or [])


class TerminalCommandCreateSerializer(serializers.Serializer):
    """终端命令创建序列化器"""

    name = serializers.CharField(max_length=50)
    description = serializers.CharField(allow_blank=True, required=False, default='')
    command_type = serializers.ChoiceField(choices=[choice.value for choice in CommandType])
    prompt_template = serializers.IntegerField(required=False, allow_null=True)
    system_prompt = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    user_prompt_template = serializers.CharField(allow_blank=True, required=False, default='')
    api_endpoint = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    api_method = serializers.CharField(required=False, default='GET')
    response_jq_filter = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    parameters = CommandParameterSerializer(many=True, required=False, default=list)
    timeout = serializers.IntegerField(required=False, default=60, min_value=1)
    provider_name = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    model_name = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    risk_level = serializers.ChoiceField(
        choices=[choice.value for choice in TerminalRiskLevel],
        required=False,
        default=TerminalRiskLevel.READ.value,
    )
    requires_mcp = serializers.BooleanField(required=False, default=True)
    enabled_in_terminal = serializers.BooleanField(required=False, default=True)
    category = serializers.CharField(required=False, default='general')
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    is_active = serializers.BooleanField(required=False, default=True)

    def validate_parameters(self, value):
        """验证参数格式"""

        for param in value:
            if param.get('type') == 'select' and not param.get('options'):
                raise serializers.ValidationError(
                    f"Parameter '{param.get('name')}' of type 'select' must have 'options'"
                )
        return value


class TerminalCommandUpdateSerializer(serializers.Serializer):
    """终端命令更新序列化器"""

    name = serializers.CharField(max_length=50, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    command_type = serializers.ChoiceField(
        choices=[choice.value for choice in CommandType],
        required=False,
    )
    prompt_template = serializers.IntegerField(required=False, allow_null=True)
    system_prompt = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    user_prompt_template = serializers.CharField(allow_blank=True, required=False)
    api_endpoint = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    api_method = serializers.CharField(required=False)
    response_jq_filter = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    parameters = CommandParameterSerializer(many=True, required=False)
    timeout = serializers.IntegerField(required=False, min_value=1)
    provider_name = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    model_name = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    risk_level = serializers.ChoiceField(
        choices=[choice.value for choice in TerminalRiskLevel],
        required=False,
    )
    requires_mcp = serializers.BooleanField(required=False)
    enabled_in_terminal = serializers.BooleanField(required=False)
    category = serializers.CharField(required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_parameters(self, value):
        """验证参数格式"""

        for param in value:
            if param.get('type') == 'select' and not param.get('options'):
                raise serializers.ValidationError(
                    f"Parameter '{param.get('name')}' of type 'select' must have 'options'"
                )
        return value


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
