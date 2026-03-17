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


class ExecuteCommandResponseSerializer(serializers.Serializer):
    """执行命令响应序列化器"""
    success = serializers.BooleanField()
    output = serializers.CharField()
    metadata = serializers.DictField()
    error = serializers.CharField(allow_null=True)
    command = TerminalCommandSerializer(allow_null=True)


class AvailableCommandSerializer(serializers.Serializer):
    """可用命令列表序列化器（简化版）"""
    name = serializers.CharField()
    description = serializers.CharField()
    type = serializers.CharField()
    category = serializers.CharField()
    parameters = CommandParameterSerializer(many=True)
    is_active = serializers.BooleanField()
