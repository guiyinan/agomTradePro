"""
DRF serializers for AI provider management.
"""

from rest_framework import serializers

from ..infrastructure.models import AIProviderConfig, AIUsageLog, AIUserFallbackQuota
from ..infrastructure.repositories import AIProviderRepository


class AIProviderConfigSerializer(serializers.ModelSerializer):
    """Base provider serializer with masked API key."""

    owner_username = serializers.CharField(source="owner_user.username", read_only=True)
    _provider_repo = AIProviderRepository()

    class Meta:
        model = AIProviderConfig
        fields = [
            "id",
            "name",
            "scope",
            "owner_user",
            "owner_username",
            "provider_type",
            "is_active",
            "priority",
            "base_url",
            "api_key",
            "default_model",
            "api_mode",
            "fallback_enabled",
            "daily_budget_limit",
            "monthly_budget_limit",
            "extra_config",
            "description",
            "created_at",
            "updated_at",
            "last_used_at",
        ]
        read_only_fields = [
            "scope",
            "owner_user",
            "owner_username",
            "created_at",
            "updated_at",
            "last_used_at",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        api_key = self._provider_repo.get_api_key(instance)
        data["api_key"] = f"****{api_key[-4:]}" if api_key and len(api_key) >= 4 else "****"
        return data


class AdminProviderCreateSerializer(serializers.ModelSerializer):
    """Admin serializer for system provider create/update."""

    class Meta:
        model = AIProviderConfig
        fields = [
            "name",
            "provider_type",
            "is_active",
            "priority",
            "base_url",
            "api_key",
            "default_model",
            "api_mode",
            "fallback_enabled",
            "daily_budget_limit",
            "monthly_budget_limit",
            "extra_config",
            "description",
        ]


class PersonalProviderCreateSerializer(serializers.ModelSerializer):
    """User serializer for personal provider create/update."""

    class Meta:
        model = AIProviderConfig
        fields = [
            "name",
            "provider_type",
            "is_active",
            "priority",
            "base_url",
            "api_key",
            "default_model",
            "api_mode",
            "fallback_enabled",
            "extra_config",
            "description",
        ]


AIProviderConfigCreateSerializer = AdminProviderCreateSerializer


class AIUsageLogSerializer(serializers.ModelSerializer):
    """Usage log serializer with attribution fields."""

    provider_name = serializers.CharField(source="provider.name", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = AIUsageLog
        fields = [
            "id",
            "provider",
            "provider_name",
            "user",
            "username",
            "provider_scope",
            "quota_charged",
            "model",
            "request_type",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "estimated_cost",
            "response_time_ms",
            "status",
            "error_message",
            "request_metadata",
            "created_at",
        ]
        read_only_fields = [
            "created_at",
        ]


class UserFallbackQuotaSerializer(serializers.ModelSerializer):
    """Serializer for one user's fallback quota."""

    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = AIUserFallbackQuota
        fields = [
            "user",
            "username",
            "daily_limit",
            "monthly_limit",
            "is_active",
            "admin_note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "username"]


class UserFallbackQuotaUpdateSerializer(serializers.Serializer):
    """Admin serializer for per-user quota updates."""

    daily_limit = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    monthly_limit = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, default=True)
    admin_note = serializers.CharField(required=False, allow_blank=True, default="")


class BatchQuotaApplySerializer(serializers.Serializer):
    """Admin serializer for batch quota apply."""

    daily_limit = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    monthly_limit = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    overwrite_existing = serializers.BooleanField(required=False, default=False)
    is_active = serializers.BooleanField(required=False, default=True)
    admin_note = serializers.CharField(required=False, allow_blank=True, default="")


class AIChatRequestSerializer(serializers.Serializer):
    """AI聊天请求序列化器"""

    provider_id = serializers.IntegerField(required=False, help_text="提供商ID（不指定则自动选择）")
    model = serializers.CharField(required=False, help_text="模型名称（不指定则使用默认模型）")
    messages = serializers.ListField(
        child=serializers.DictField(),
        help_text="消息列表 [{'role': 'user', 'content': '...'}]",
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
    provider_scope = serializers.CharField()
    quota_charged = serializers.BooleanField()
    status = serializers.CharField()
    error_message = serializers.CharField(required=False, allow_null=True)
