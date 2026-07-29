"""
Django admin configuration for AI provider management.
"""

from django.contrib import admin
from django.http import HttpRequest

from apps.ai_provider.application.repository_provider import get_ai_provider_repository
from apps.ai_provider.models import AIProviderConfig, AIUsageLog, AIUserFallbackQuota
from shared.infrastructure.django_admin import TypedModelAdmin


@admin.register(AIProviderConfig)
class AIProviderConfigAdmin(TypedModelAdmin[AIProviderConfig]):
    """AI提供商配置管理"""

    list_display = [
        "name",
        "scope",
        "owner_user",
        "provider_type",
        "is_active",
        "priority",
        "default_model",
        "api_mode",
        "fallback_enabled",
        "masked_api_key",
        "last_used_at",
        "created_at",
    ]
    list_filter = ["scope", "provider_type", "is_active"]
    search_fields = ["name", "description", "base_url", "owner_user__username"]
    ordering = ["scope", "priority", "name"]

    fieldsets = (
        ("归属", {"fields": ("scope", "owner_user")}),
        ("基本信息", {"fields": ("name", "provider_type", "description")}),
        (
            "连接配置",
            {
                "fields": (
                    "base_url",
                    "masked_api_key",
                    "default_model",
                    "api_mode",
                    "fallback_enabled",
                )
            },
        ),
        ("状态与优先级", {"fields": ("is_active", "priority")}),
        ("预算控制", {"fields": ("daily_budget_limit", "monthly_budget_limit")}),
        ("额外配置", {"fields": ("extra_config",), "classes": ("collapse",)}),
    )
    readonly_fields = ["masked_api_key", "created_at", "updated_at", "last_used_at"]

    @admin.display(description="API Key")
    def masked_api_key(self, obj: AIProviderConfig) -> str:
        """Return a non-identifying fixed credential mask."""
        api_key = get_ai_provider_repository().get_api_key(obj)
        return "****" if api_key else "Not configured"


@admin.register(AIUsageLog)
class AIUsageLogAdmin(TypedModelAdmin[AIUsageLog]):
    """AI调用日志管理"""

    list_display = [
        "id",
        "provider",
        "user",
        "provider_scope",
        "quota_charged",
        "model",
        "status",
        "total_tokens",
        "estimated_cost",
        "response_time_ms",
        "created_at",
    ]
    list_filter = ["provider_scope", "quota_charged", "status", "provider", "model", "request_type"]
    search_fields = ["error_message", "user__username"]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"
    readonly_fields = [
        "provider",
        "user",
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
    list_per_page = 50

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: AIUsageLog | None = None,
    ) -> bool:
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: AIUsageLog | None = None,
    ) -> bool:
        """Keep generated usage and billing evidence append-only."""

        del request, obj
        return False


@admin.register(AIUserFallbackQuota)
class AIUserFallbackQuotaAdmin(TypedModelAdmin[AIUserFallbackQuota]):
    """管理员维护用户系统兜底额度。"""

    list_display = ["user", "daily_limit", "monthly_limit", "is_active", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["user__username", "admin_note"]
