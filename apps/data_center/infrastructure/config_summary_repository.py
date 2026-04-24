"""Django read model for data-center config summaries."""

from __future__ import annotations

from typing import Any

from .models import DataProviderSettingsModel, ProviderConfigModel


class DjangoDataCenterConfigSummaryRepository:
    """ORM-backed data-center config-summary repository."""

    def get_provider_summary(self) -> dict[str, Any]:
        """Return provider configuration summary."""

        provider_settings = DataProviderSettingsModel.load()
        rows = list(
            ProviderConfigModel._default_manager.all().values(
                "source_type",
                "name",
                "is_active",
                "api_key",
                "http_url",
            )
        )
        active_rows = [row for row in rows if row["is_active"]]
        requires_key_types = {"tushare", "fred", "wind", "choice"}
        missing_key_count = sum(
            1
            for row in active_rows
            if row["source_type"] in requires_key_types and not (row.get("api_key") or "").strip()
        )
        status = "configured"
        if active_rows and missing_key_count > 0:
            status = "attention"
        custom_http_url_count = sum(
            1
            for row in active_rows
            if row["source_type"] == "tushare" and (row.get("http_url") or "").strip()
        )
        if not rows:
            return {
                "status": status,
                "summary": {
                    "message": "当前没有配置 Provider 记录。",
                    "total_providers": 0,
                    "active_providers": 0,
                    "default_source": provider_settings.default_source,
                    "enable_failover": provider_settings.enable_failover,
                    "custom_http_url_count": 0,
                    "missing_api_key_count": 0,
                },
            }

        return {
            "status": status,
            "summary": {
                "total_providers": len(rows),
                "active_providers": len(active_rows),
                "source_types": sorted({row["source_type"] for row in active_rows}),
                "default_source": provider_settings.default_source,
                "enable_failover": provider_settings.enable_failover,
                "missing_api_key_count": missing_key_count,
                "custom_http_url_count": custom_http_url_count,
            },
        }

    def list_active_provider_names(self) -> list[str]:
        """Return active provider names configured in the database."""

        return list(
            ProviderConfigModel._default_manager.filter(is_active=True).values_list("name", flat=True)
        )

