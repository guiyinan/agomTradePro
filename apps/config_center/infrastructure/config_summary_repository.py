"""ORM-backed config-center summary repository."""

from __future__ import annotations

import os
from typing import Any

from apps.config_center.application.runtime_public import (
    get_active_domain_runtime_config,
    get_active_qlib_runtime_config,
    get_active_runtime_value,
)
from apps.config_center.infrastructure.models import SystemSettingsModel
from core.integration.data_center_readiness import get_macro_runtime_metadata


class DjangoConfigCenterSummaryRepository:
    """Owns runtime config summaries for the core bridge."""

    @staticmethod
    def _runtime_environment() -> str:
        """Map the Django settings module to the profile environment name."""

        settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
        return "production" if settings_module.endswith(".production") else "development"

    @staticmethod
    def _build_runtime_macro_metadata_map() -> dict[str, dict[str, Any]]:
        return get_macro_runtime_metadata()

    def _get_typed_domain_runtime_config(self) -> dict[str, object] | None:
        """Return the complete typed Alpha/market projection when available."""

        return get_active_domain_runtime_config(self._runtime_environment())

    @staticmethod
    def _market_visual_tokens(convention: str) -> dict[str, str]:
        """Build visual tokens without reading the compatibility singleton."""

        palettes = {
            "cn_a_share": {
                "rise": "var(--color-error)",
                "fall": "var(--color-success)",
                "rise_soft": "var(--color-error-light)",
                "fall_soft": "var(--color-success-light)",
                "rise_strong": "var(--color-error-dark)",
                "fall_strong": "var(--color-success-dark)",
                "inflow": "var(--color-error)",
                "outflow": "var(--color-success)",
                "convention": "cn_a_share",
                "label": "A股红涨绿跌",
            },
            "us_market": {
                "rise": "var(--color-success)",
                "fall": "var(--color-error)",
                "rise_soft": "var(--color-success-light)",
                "fall_soft": "var(--color-error-light)",
                "rise_strong": "var(--color-success-dark)",
                "fall_strong": "var(--color-error-dark)",
                "inflow": "var(--color-success)",
                "outflow": "var(--color-error)",
                "convention": "us_market",
                "label": "美股绿涨红跌",
            },
        }
        return dict(palettes.get(convention, palettes["cn_a_share"]))

    def get_system_settings_summary(self) -> dict[str, Any]:
        settings_obj = SystemSettingsModel.get_settings_for_read()
        runtime_qlib = self.get_runtime_qlib_config()
        typed_domain = self._get_typed_domain_runtime_config()
        if typed_domain is not None:
            market_convention = str(typed_domain["market_color_convention"])
            market_tokens = self._market_visual_tokens(market_convention)
            benchmark_map = typed_domain["benchmark_code_map"]
            asset_proxy_map = typed_domain["asset_proxy_code_map"]
        else:
            market_convention = settings_obj.market_color_convention
            market_tokens = settings_obj.get_market_visual_tokens()
            benchmark_map = settings_obj.benchmark_code_map or {}
            asset_proxy_map = settings_obj.asset_proxy_code_map or {}
        return {
            "status": "configured",
            "summary": {
                "default_mcp_enabled": settings_obj.default_mcp_enabled,
                "allow_token_plaintext_view": settings_obj.allow_token_plaintext_view,
                "market_color_convention": market_convention,
                "market_color_label": market_tokens["label"],
                "benchmark_map_size": len(benchmark_map) if isinstance(benchmark_map, dict) else 0,
                "asset_proxy_map_size": (
                    len(asset_proxy_map) if isinstance(asset_proxy_map, dict) else 0
                ),
                "qlib_enabled": runtime_qlib["enabled"],
                "qlib_configured": runtime_qlib["is_configured"],
                "updated_at": (
                    settings_obj.updated_at.isoformat()
                    if getattr(settings_obj, "updated_at", None)
                    else None
                ),
            },
        }

    def get_runtime_market_visual_tokens(self) -> dict[str, str]:
        """Return the configured market visual token mapping."""

        typed = self._get_typed_domain_runtime_config()
        if typed is not None:
            return self._market_visual_tokens(str(typed["market_color_convention"]))
        return SystemSettingsModel.get_runtime_market_visual_tokens()

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
        """Return typed Qlib runtime config, blocking when its snapshot is absent.

        SystemSettingsModel still exposes a migration-only compatibility method,
        but runtime consumers must never silently fall back to it.  A missing or
        stale Config Center snapshot therefore becomes an explicit disabled and
        decision-unsafe payload.
        """

        typed_runtime = get_active_qlib_runtime_config(self._runtime_environment())
        if typed_runtime is not None:
            return typed_runtime
        return {
            "enabled": False,
            "is_configured": False,
            "status": "blocked",
            "source": "config_center_runtime_profile",
            "must_not_use_for_decision": True,
            "blocked_reason": "runtime_config_snapshot_unavailable",
        }

    def get_runtime_alpha_fixed_provider(self) -> str:
        typed = self._get_typed_domain_runtime_config()
        if typed is not None:
            return str(typed["alpha_fixed_provider"])
        return SystemSettingsModel.get_runtime_alpha_fixed_provider()

    def get_runtime_alpha_pool_mode(self, default_mode: str = "") -> str:
        typed = self._get_typed_domain_runtime_config()
        if typed is not None:
            return str(typed["alpha_pool_mode"])
        mode = SystemSettingsModel.get_runtime_alpha_pool_mode()
        return mode or default_mode

    def get_runtime_benchmark_code(self, key: str, default: str = "") -> str:
        typed = self._get_typed_domain_runtime_config()
        if typed is not None:
            value = typed["benchmark_code_map"]
            if isinstance(value, dict) and isinstance(value.get(key), str):
                return str(value[key])
            return default
        return SystemSettingsModel.get_runtime_benchmark_code(key, default)

    def get_runtime_asset_proxy_map(self) -> dict[str, str]:
        typed = self._get_typed_domain_runtime_config()
        if typed is not None:
            value = typed["asset_proxy_code_map"]
            if isinstance(value, dict):
                return {key: str(item) for key, item in value.items() if isinstance(item, str)}
            return {}
        return {
            key: str(value)
            for key, value in SystemSettingsModel.get_runtime_asset_proxy_map().items()
        }

    def get_runtime_config_value(self, definition_key: str) -> object | None:
        """Return one value from the active typed profile for the current environment."""

        normalized_key = str(definition_key or "").strip()
        if not normalized_key:
            return None
        return get_active_runtime_value(
            environment=self._runtime_environment(),
            definition_key=normalized_key,
        )
