"""Django read model for AI-provider config summaries."""

from __future__ import annotations

from typing import Any

from .models import AIProviderConfig, AIUsageLog


class DjangoAIProviderConfigSummaryRepository:
    """ORM-backed AI-provider config-summary repository."""

    def get_provider_summary(self) -> dict[str, Any]:
        """Return AI-provider configuration summary."""

        providers = list(
            AIProviderConfig._default_manager.all().values(
                "id",
                "name",
                "provider_type",
                "is_active",
                "default_model",
            )
        )
        if not providers:
            return {
                "status": "missing",
                "summary": {
                    "message": "未配置 AI Provider",
                    "provider_count": 0,
                    "active_count": 0,
                },
            }

        active_providers = [provider for provider in providers if provider["is_active"]]
        recent_error_count = AIUsageLog._default_manager.filter(
            status__in=["error", "timeout"]
        ).count()
        status = "configured" if active_providers else "attention"
        return {
            "status": status,
            "summary": {
                "provider_count": len(providers),
                "active_count": len(active_providers),
                "active_names": [provider["name"] for provider in active_providers[:5]],
                "recent_error_count": recent_error_count,
            },
        }
