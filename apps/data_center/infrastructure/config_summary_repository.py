"""Django read model for data-center config summaries."""

from __future__ import annotations

import os
from typing import Any

from .macro_sources.failover_adapter import (
    _resolve_default_source,
    _resolve_failover_enabled,
    _resolve_failover_tolerance,
)
from .models import DataProviderSettingsModel, ProviderConfigModel
from .provider_credentials import ProviderCredentialStore


class DjangoDataCenterConfigSummaryRepository:
    """ORM-backed data-center config-summary repository."""

    def get_provider_summary(self) -> dict[str, Any]:
        """Return provider configuration summary."""

        provider_settings = DataProviderSettingsModel.load_for_read()
        module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
        environment = "production" if module.endswith(".production") else "development"
        default_source = _resolve_default_source(
            provider_settings.default_source,
            environment=environment,
        )
        enable_failover = _resolve_failover_enabled(
            provider_settings.enable_failover,
            environment=environment,
        )
        failover_tolerance = _resolve_failover_tolerance(
            provider_settings.failover_tolerance,
            environment=environment,
        )
        provider_rows = list(
            ProviderConfigModel._default_manager.all().values(
                "id",
                "source_type",
                "name",
                "is_active",
                "http_url",
            )
        )
        credential_statuses = ProviderCredentialStore().statuses_from_rows(provider_rows)
        rows: list[dict[str, Any]] = [
            {
                "id": provider.get("id"),
                "source_type": provider.get("source_type"),
                "name": provider.get("name"),
                "is_active": provider.get("is_active"),
                "http_url": provider.get("http_url"),
                "has_api_key": credential_statuses[int(provider["id"])].has_api_key,
            }
            for provider in provider_rows
        ]
        active_rows = [row for row in rows if row["is_active"]]
        requires_key_types = {"tushare", "fred", "wind", "choice"}
        missing_key_count = sum(
            1
            for row in active_rows
            if str(row.get("source_type") or "") in requires_key_types
            and not bool(row.get("has_api_key"))
        )
        status = "configured"
        if active_rows and missing_key_count > 0:
            status = "attention"
        custom_http_url_count = sum(
            1
            for row in active_rows
            if str(row.get("source_type") or "") == "tushare"
            and str(row.get("http_url") or "").strip()
        )
        if not rows:
            return {
                "status": status,
                "summary": {
                    "message": "当前没有配置 Provider 记录。",
                    "total_providers": 0,
                    "active_providers": 0,
                    "default_source": default_source,
                    "enable_failover": enable_failover,
                    "failover_tolerance": failover_tolerance,
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
                "default_source": default_source,
                "enable_failover": enable_failover,
                "failover_tolerance": failover_tolerance,
                "missing_api_key_count": missing_key_count,
                "custom_http_url_count": custom_http_url_count,
            },
        }

    def list_active_provider_names(self) -> list[str]:
        """Return active provider names configured in the database."""

        return list(
            ProviderConfigModel._default_manager.filter(is_active=True).values_list(
                "name", flat=True
            )
        )
