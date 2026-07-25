"""
DRF serializers for AI provider management.
"""

from decimal import Decimal
from typing import Any

from rest_framework import serializers


class AIProviderConfigSerializer(serializers.Serializer[Any]):
    """Read serializer for provider payloads."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    scope = serializers.CharField(read_only=True)
    owner_user_id = serializers.IntegerField(read_only=True, allow_null=True)
    owner_username = serializers.CharField(read_only=True, allow_null=True)
    provider_type = serializers.CharField(read_only=True)
    provider_type_label = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    priority = serializers.IntegerField(read_only=True)
    base_url = serializers.URLField(read_only=True)
    api_key = serializers.SerializerMethodField()
    api_key_configured = serializers.BooleanField(read_only=True)
    default_model = serializers.CharField(read_only=True)
    api_mode = serializers.CharField(read_only=True)
    fallback_enabled = serializers.BooleanField(read_only=True)
    daily_budget_limit = serializers.FloatField(read_only=True, allow_null=True)
    monthly_budget_limit = serializers.FloatField(read_only=True, allow_null=True)
    extra_config = serializers.JSONField(read_only=True)
    description = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    last_used_at = serializers.DateTimeField(read_only=True, allow_null=True)
    today_requests = serializers.IntegerField(read_only=True, required=False)
    today_cost = serializers.FloatField(read_only=True, required=False)
    month_requests = serializers.IntegerField(read_only=True, required=False)
    month_cost = serializers.FloatField(read_only=True, required=False)

    def get_api_key(self, obj: object) -> str:
        """Return a fixed mask without decrypting or fingerprinting the credential."""
        return "****" if bool(getattr(obj, "api_key_configured", False)) else ""


class AdminProviderCreateSerializer(serializers.Serializer[Any]):
    """Admin serializer for system provider create/update."""

    name = serializers.CharField(max_length=50)
    provider_type = serializers.ChoiceField(
        choices=["openai", "deepseek", "qwen", "moonshot", "custom"]
    )
    is_active = serializers.BooleanField(required=False, default=True)
    priority = serializers.IntegerField(required=False, default=10, min_value=1)
    base_url = serializers.URLField()
    api_key = serializers.CharField(required=False, allow_blank=True)
    default_model = serializers.CharField(required=False, default="gpt-3.5-turbo")
    api_mode = serializers.ChoiceField(
        choices=["dual", "responses_only", "chat_only"], required=False, default="dual"
    )
    fallback_enabled = serializers.BooleanField(required=False, default=True)
    daily_budget_limit = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal("0"),
    )
    monthly_budget_limit = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal("0"),
    )
    extra_config = serializers.JSONField(required=False, default=dict)
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_extra_config(self, value: object) -> dict[str, Any]:
        """Require an object so downstream provider options remain key-addressable."""
        return _validate_extra_config(value)


class PersonalProviderCreateSerializer(serializers.Serializer[Any]):
    """User serializer for personal provider create/update."""

    name = serializers.CharField(max_length=50)
    provider_type = serializers.ChoiceField(
        choices=["openai", "deepseek", "qwen", "moonshot", "custom"]
    )
    is_active = serializers.BooleanField(required=False, default=True)
    priority = serializers.IntegerField(required=False, default=10, min_value=1)
    base_url = serializers.URLField()
    api_key = serializers.CharField(required=False, allow_blank=True)
    default_model = serializers.CharField(required=False, default="gpt-3.5-turbo")
    api_mode = serializers.ChoiceField(
        choices=["dual", "responses_only", "chat_only"], required=False, default="dual"
    )
    fallback_enabled = serializers.BooleanField(required=False, default=True)
    extra_config = serializers.JSONField(required=False, default=dict)
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_extra_config(self, value: object) -> dict[str, Any]:
        """Require an object so downstream provider options remain key-addressable."""
        return _validate_extra_config(value)


AIProviderConfigCreateSerializer = AdminProviderCreateSerializer


class AIUsageLogSerializer(serializers.Serializer[Any]):
    """Usage log serializer with attribution fields."""

    id = serializers.IntegerField(read_only=True)
    provider_id = serializers.IntegerField(read_only=True)
    provider_name = serializers.CharField(read_only=True)
    user_id = serializers.IntegerField(read_only=True, allow_null=True)
    username = serializers.CharField(read_only=True, allow_null=True)
    provider_scope = serializers.CharField(read_only=True)
    quota_charged = serializers.BooleanField(read_only=True)
    model = serializers.CharField(read_only=True)
    request_type = serializers.CharField(read_only=True)
    prompt_tokens = serializers.IntegerField(read_only=True)
    completion_tokens = serializers.IntegerField(read_only=True)
    total_tokens = serializers.IntegerField(read_only=True)
    estimated_cost = serializers.FloatField(read_only=True)
    response_time_ms = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
    error_message = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class UserFallbackQuotaSerializer(serializers.Serializer[Any]):
    """Serializer for one user's fallback quota."""

    user_id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    daily_limit = serializers.FloatField(read_only=True, allow_null=True)
    monthly_limit = serializers.FloatField(read_only=True, allow_null=True)
    is_active = serializers.BooleanField(read_only=True)
    admin_note = serializers.CharField(read_only=True)
    daily_spent = serializers.FloatField(read_only=True)
    monthly_spent = serializers.FloatField(read_only=True)
    daily_remaining = serializers.FloatField(read_only=True, allow_null=True)
    monthly_remaining = serializers.FloatField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)


class UserFallbackQuotaUpdateSerializer(serializers.Serializer[Any]):
    """Admin serializer for per-user quota updates."""

    daily_limit = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal("0"),
    )
    monthly_limit = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal("0"),
    )
    is_active = serializers.BooleanField(required=False, default=True)
    admin_note = serializers.CharField(required=False, allow_blank=True, default="")


class BatchQuotaApplySerializer(serializers.Serializer[Any]):
    """Admin serializer for batch quota apply."""

    daily_limit = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal("0"),
    )
    monthly_limit = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal("0"),
    )
    overwrite_existing = serializers.BooleanField(required=False, default=False)
    is_active = serializers.BooleanField(required=False, default=True)
    admin_note = serializers.CharField(required=False, allow_blank=True, default="")


class AIChatRequestSerializer(serializers.Serializer[Any]):
    """AI聊天请求序列化器"""

    provider_id = serializers.IntegerField(required=False, help_text="提供商ID（不指定则自动选择）")
    model = serializers.CharField(required=False, help_text="模型名称（不指定则使用默认模型）")
    messages = serializers.ListField(
        child=serializers.DictField(),
        help_text="消息列表 [{'role': 'user', 'content': '...'}]",
    )
    temperature = serializers.FloatField(
        default=0.7,
        min_value=0.0,
        max_value=2.0,
        help_text="温度参数",
    )
    max_tokens = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="最大输出token数",
    )


class AIChatResponseSerializer(serializers.Serializer[Any]):
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


def _validate_extra_config(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise serializers.ValidationError("extra_config must be an object")
    return value
