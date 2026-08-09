"""ORM-backed config-center summary repository."""

from __future__ import annotations

import os
from typing import Any

from apps.config_center.application.runtime_public import (
    get_active_account_runtime_config,
    get_active_alpha_runtime_config,
    get_active_market_runtime_config,
    get_active_qlib_runtime_config,
    get_active_runtime_value,
)
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

    def _get_typed_alpha_runtime_config(self) -> dict[str, object] | None:
        """Return the complete canonical Alpha projection when available."""

        return get_active_alpha_runtime_config(self._runtime_environment())

    def _get_typed_market_runtime_config(self) -> dict[str, object] | None:
        """Return the complete canonical market projection when available."""

        return get_active_market_runtime_config(self._runtime_environment())

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
        runtime_qlib = self.get_runtime_qlib_config()
        typed_market = self._get_typed_market_runtime_config()
        typed_account = get_active_account_runtime_config(self._runtime_environment())
        default_mcp_enabled = bool(
            typed_account["default_mcp_enabled"] if typed_account is not None else False
        )
        allow_token_plaintext_view = bool(
            typed_account["allow_token_plaintext_view"] if typed_account is not None else False
        )
        if typed_market is not None:
            market_convention = str(typed_market["market_color_convention"])
            market_tokens = self._market_visual_tokens(market_convention)
            benchmark_map = typed_market["benchmark_code_map"]
            asset_proxy_map = typed_market["asset_proxy_code_map"]
        else:
            market_convention = ""
            market_tokens = self._market_visual_tokens("cn_a_share")
            benchmark_map = {}
            asset_proxy_map = {}
        return {
            "status": (
                "configured"
                if typed_account is not None and typed_market is not None
                else "blocked"
            ),
            "summary": {
                "default_mcp_enabled": default_mcp_enabled,
                "allow_token_plaintext_view": allow_token_plaintext_view,
                "market_color_convention": market_convention,
                "market_color_label": market_tokens["label"],
                "benchmark_map_size": len(benchmark_map) if isinstance(benchmark_map, dict) else 0,
                "asset_proxy_map_size": (
                    len(asset_proxy_map) if isinstance(asset_proxy_map, dict) else 0
                ),
                "qlib_enabled": runtime_qlib["enabled"],
                "qlib_configured": runtime_qlib["is_configured"],
                "updated_at": None,
            },
        }

    def get_runtime_market_visual_tokens(self) -> dict[str, str]:
        """Return the configured market visual token mapping."""

        typed = self._get_typed_market_runtime_config()
        if typed is not None:
            return self._market_visual_tokens(str(typed["market_color_convention"]))
        return self._market_visual_tokens("cn_a_share")

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

        Runtime consumers must never silently fall back to the retired
        singleton. A missing or stale Config Center snapshot therefore becomes
        an explicit disabled and decision-unsafe payload.
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
        typed = self._get_typed_alpha_runtime_config()
        if typed is not None:
            return str(typed["alpha_fixed_provider"])
        return ""

    def get_runtime_alpha_pool_mode(self, default_mode: str = "") -> str:
        typed = self._get_typed_alpha_runtime_config()
        if typed is not None:
            return str(typed["alpha_pool_mode"])
        return default_mode

    def get_runtime_benchmark_code(self, key: str, default: str = "") -> str:
        typed = self._get_typed_market_runtime_config()
        if typed is not None:
            value = typed["benchmark_code_map"]
            if isinstance(value, dict) and isinstance(value.get(key), str):
                return str(value[key])
            return default
        return default

    def get_runtime_asset_proxy_map(self) -> dict[str, str]:
        typed = self._get_typed_market_runtime_config()
        if typed is not None:
            value = typed["asset_proxy_code_map"]
            if isinstance(value, dict):
                return {key: str(item) for key, item in value.items() if isinstance(item, str)}
            return {}
        return {}

    def get_runtime_config_value(self, definition_key: str) -> object | None:
        """Return one value from the active typed profile for the current environment."""

        normalized_key = str(definition_key or "").strip()
        if not normalized_key:
            return None
        return get_active_runtime_value(
            environment=self._runtime_environment(),
            definition_key=normalized_key,
        )
