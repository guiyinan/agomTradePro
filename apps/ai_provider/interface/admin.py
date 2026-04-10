"""
Django admin configuration for AI provider management.
"""

from django.contrib import admin

from ..infrastructure.models import AIProviderConfig, AIUsageLog, AIUserFallbackQuota
from ..infrastructure.repositories import AIProviderRepository


@admin.register(AIProviderConfig)
class AIProviderConfigAdmin(admin.ModelAdmin):
    """AI提供商配置管理"""

    _provider_repo = AIProviderRepository()

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
        ("连接配置", {"fields": ("base_url", "api_key", "default_model", "api_mode", "fallback_enabled")}),
        ("状态与优先级", {"fields": ("is_active", "priority")}),
        ("预算控制", {"fields": ("daily_budget_limit", "monthly_budget_limit")}),
        ("额外配置", {"fields": ("extra_config",), "classes": ("collapse",)}),
    )
    readonly_fields = ["created_at", "updated_at", "last_used_at"]

    def masked_api_key(self, obj):
        api_key = self._provider_repo.get_api_key(obj)
        if api_key:
            return f"****{api_key[-4:]}" if len(api_key) >= 4 else "****"
        return "****"

    masked_api_key.short_description = "API Key"


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AIUserFallbackQuota)
class AIUserFallbackQuotaAdmin(admin.ModelAdmin):
    """管理员维护用户系统兜底额度。"""

    list_display = ["user", "daily_limit", "monthly_limit", "is_active", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["user__username", "admin_note"]
