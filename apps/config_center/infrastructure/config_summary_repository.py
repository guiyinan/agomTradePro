"""ORM-backed config-center summary repository."""

from __future__ import annotations

from typing import Any

from apps.config_center.infrastructure.models import SystemSettingsModel
from apps.data_center.application.public import get_macro_runtime_metadata


class DjangoConfigCenterSummaryRepository:
    """Owns runtime config summaries for the core bridge."""

    @staticmethod
    def _build_runtime_macro_metadata_map() -> dict[str, dict[str, Any]]:
        return get_macro_runtime_metadata()

    def get_system_settings_summary(self) -> dict[str, Any]:
        settings_obj = SystemSettingsModel.get_settings_for_read()
        runtime_qlib = settings_obj.get_runtime_qlib_config_payload()
        return {
            "status": "configured",
            "summary": {
                "default_mcp_enabled": settings_obj.default_mcp_enabled,
                "allow_token_plaintext_view": settings_obj.allow_token_plaintext_view,
                "market_color_convention": settings_obj.market_color_convention,
                "market_color_label": settings_obj.get_market_visual_tokens()["label"],
                "benchmark_map_size": len(settings_obj.benchmark_code_map or {}),
                "asset_proxy_map_size": len(settings_obj.asset_proxy_code_map or {}),
                "qlib_enabled": runtime_qlib["enabled"],
                "qlib_configured": runtime_qlib["is_configured"],
                "updated_at": (
                    settings_obj.updated_at.isoformat()
                    if getattr(settings_obj, "updated_at", None)
                    else None
                ),
            },
        }

    def get_runtime_macro_index_metadata_map(self) -> dict[str, dict[str, Any]]:
        return self._build_runtime_macro_metadata_map()

    def get_runtime_macro_index_codes(self) -> list[str]:
        return list(self._build_runtime_macro_metadata_map().keys())

    def get_runtime_macro_publication_lags(self) -> dict[str, dict[str, Any]]:
        return {
            code: {
                "days": item.get("publication_lag_days", 0),
                "description": item.get("publication_lag_description", "实时"),
            }
            for code, item in self._build_runtime_macro_metadata_map().items()
        }

    def get_runtime_qlib_config(self) -> dict[str, Any]:
        return SystemSettingsModel.get_runtime_qlib_config()

    def get_runtime_alpha_fixed_provider(self) -> str:
        return SystemSettingsModel.get_runtime_alpha_fixed_provider()

    def get_runtime_alpha_pool_mode(self, default_mode: str = "") -> str:
        mode = SystemSettingsModel.get_runtime_alpha_pool_mode()
        return mode or default_mode

    def get_runtime_benchmark_code(self, key: str, default: str = "") -> str:
        return SystemSettingsModel.get_runtime_benchmark_code(key, default)

    def get_runtime_asset_proxy_map(self) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in SystemSettingsModel.get_runtime_asset_proxy_map().items()
        }
