"""
DRF Serializers for AI Provider Management.

Django REST Framework 序列化器。
"""

from rest_framework import serializers

from ..infrastructure.models import AIProviderConfig, AIUsageLog
from ..infrastructure.repositories import AIProviderRepository


class AIProviderConfigSerializer(serializers.ModelSerializer):
    """AI提供商配置序列化器"""
    _provider_repo = AIProviderRepository()

    class Meta:
        model = AIProviderConfig
        fields = [
            'id', 'name', 'provider_type', 'is_active', 'priority',
            'base_url', 'api_key', 'default_model', 'api_mode', 'fallback_enabled',
            'daily_budget_limit', 'monthly_budget_limit',
            'extra_config', 'description',
            'created_at', 'updated_at', 'last_used_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'last_used_at']

    def to_representation(self, instance):
        """隐藏API Key的部分内容"""
        data = super().to_representation(instance)
        api_key = self._provider_repo.get_api_key(instance)
        data['api_key'] = f"****{api_key[-4:]}" if api_key and len(api_key) >= 4 else '****'
        return data


class AIProviderConfigCreateSerializer(serializers.ModelSerializer):
    """AI提供商配置创建序列化器"""

    class Meta:
        model = AIProviderConfig
        fields = [
            'name', 'provider_type', 'is_active', 'priority',
            'base_url', 'api_key', 'default_model', 'api_mode', 'fallback_enabled',
            'daily_budget_limit', 'monthly_budget_limit',
            'extra_config', 'description'
        ]


class AIUsageLogSerializer(serializers.ModelSerializer):
    """AI调用日志序列化器"""

    provider_name = serializers.CharField(source='provider.name', read_only=True)

    class Meta:
        model = AIUsageLog
        fields = [
            'id', 'provider', 'provider_name', 'model', 'request_type',
            'prompt_tokens', 'completion_tokens', 'total_tokens',
            'estimated_cost', 'response_time_ms', 'status',
            'error_message', 'request_metadata', 'created_at'
        ]
        read_only_fields = ['created_at']


class AIChatRequestSerializer(serializers.Serializer):
    """AI聊天请求序列化器"""

    provider_id = serializers.IntegerField(required=False, help_text="提供商ID（不指定则自动选择）")
    model = serializers.CharField(required=False, help_text="模型名称（不指定则使用默认模型）")
    messages = serializers.ListField(
        child=serializers.DictField(),
        help_text="消息列表 [{'role': 'user', 'content': '...'}]"
    )
    temperature = serializers.FloatField(default=0.7, help_text="温度参数")
    max_tokens = serializers.IntegerField(required=False, help_text="最大输出token数")


class AIChatResponseSerializer(serializers.Serializer):
    """AI聊天响应序列化器"""

    content = serializers.CharField()
    model = serializers.CharField()
    prompt_tokens = serializers.IntegerField()
    completion_tokens = serializers.IntegerField()
    total_tokens = serializers.IntegerField()
    estimated_cost = serializers.FloatField()
    response_time_ms = serializers.IntegerField()
    provider_used = serializers.CharField()
    status = serializers.CharField()
    error_message = serializers.CharField(required=False, allow_null=True)
