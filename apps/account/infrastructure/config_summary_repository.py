"""Django read model for account config-center summaries."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import User

from apps.data_center.infrastructure.models import IndicatorCatalogModel, IndicatorUnitRuleModel

from .models import (
    AccountProfileModel,
    PortfolioModel,
    SystemSettingsModel,
    TradingCostConfigModel,
    UserAccessTokenModel,
)


class DjangoAccountConfigSummaryRepository:
    """ORM-backed account config-summary repository."""

    @staticmethod
    def _build_runtime_macro_metadata_map() -> dict[str, dict[str, Any]]:
        metadata: dict[str, dict[str, Any]] = {}
        catalogs = IndicatorCatalogModel.objects.filter(is_active=True).order_by("code")
        rules: dict[str, IndicatorUnitRuleModel] = {}
        for rule in (
            IndicatorUnitRuleModel.objects.filter(is_active=True, source_type="")
            .order_by("indicator_code", "-priority", "id")
        ):
            rules.setdefault(rule.indicator_code, rule)

        for catalog in catalogs:
            rule = rules.get(catalog.code)
            unit = ""
            if rule is not None:
                unit = rule.display_unit or rule.original_unit or rule.storage_unit
            extra = catalog.extra or {}
            metadata[catalog.code] = {
                "name": catalog.name_cn,
                "name_en": catalog.name_en or catalog.code,
                "category": catalog.category or "其他",
                "unit": unit,
                "description": catalog.description or "",
                "publication_lag_days": int(extra.get("publication_lag_days", 0) or 0),
                "publication_lag_description": extra.get("publication_lag_description", "实时"),
            }
        return metadata

    def get_account_settings_summary(self, user: Any) -> dict[str, Any]:
        """Return account profile and access-token summary for one user."""

        profile = AccountProfileModel._default_manager.filter(user=user).first()
        if profile is None:
            return {
                "status": "missing",
                "summary": {
                    "message": "未发现账户档案",
                    "email_configured": bool(getattr(user, "email", "")),
                },
            }

        active_token_count = UserAccessTokenModel._default_manager.filter(
            user=user,
            is_active=True,
        ).count()
        return {
            "status": "configured",
            "summary": {
                "display_name": profile.display_name or getattr(user, "username", ""),
                "risk_tolerance": profile.risk_tolerance,
                "mcp_enabled": profile.mcp_enabled,
                "active_token_count": active_token_count,
            },
        }

    def get_system_settings_summary(self) -> dict[str, Any]:
        """Return singleton system settings summary."""

        settings_obj = SystemSettingsModel.get_settings()
        return {
            "status": "configured",
            "summary": {
                "default_mcp_enabled": settings_obj.default_mcp_enabled,
                "allow_token_plaintext_view": settings_obj.allow_token_plaintext_view,
                "market_color_convention": settings_obj.market_color_convention,
                "market_color_label": settings_obj.get_market_visual_tokens()["label"],
                "benchmark_map_size": len(settings_obj.benchmark_code_map or {}),
                "data_center_indicator_catalog_size": IndicatorCatalogModel.objects.filter(
                    is_active=True
                ).count(),
                "updated_at": (
                    settings_obj.updated_at.isoformat()
                    if getattr(settings_obj, "updated_at", None)
                    else None
                ),
            },
        }

    def get_trading_cost_summary(self, user: Any) -> dict[str, Any]:
        """Return portfolio trading-cost summary for one user."""

        portfolios = list(
            PortfolioModel._default_manager.filter(user=user).values("id", "name", "is_active")
        )
        if not portfolios:
            return {
                "status": "missing",
                "summary": {
                    "message": "当前用户暂无投资组合",
                    "portfolio_count": 0,
                },
            }

        portfolio_ids = [portfolio["id"] for portfolio in portfolios]
        configs = list(
            TradingCostConfigModel._default_manager.filter(portfolio_id__in=portfolio_ids).values(
                "portfolio_id",
                "commission_rate",
                "stamp_duty_rate",
                "is_active",
                "updated_at",
            )
        )
        active_configs = [cfg for cfg in configs if cfg["is_active"]]
        active_portfolio_count = sum(1 for portfolio in portfolios if portfolio["is_active"])
        status = "configured" if active_configs else "attention"
        return {
            "status": status,
            "summary": {
                "portfolio_count": len(portfolios),
                "active_portfolio_count": active_portfolio_count,
                "config_count": len(configs),
                "active_count": len(active_configs),
                "commission_rate": active_configs[0]["commission_rate"] if active_configs else None,
                "stamp_duty_rate": active_configs[0]["stamp_duty_rate"] if active_configs else None,
            },
        }

    def get_market_visual_tokens(self) -> dict[str, str]:
        """Return runtime market visual tokens."""

        return SystemSettingsModel.get_runtime_market_visual_tokens()

    def get_admin_console_counts(self) -> dict[str, int]:
        """Return admin console account counters."""

        return {
            "pending_profiles": AccountProfileModel._default_manager.filter(
                approval_status="pending"
            ).count(),
            "active_tokens": UserAccessTokenModel._default_manager.filter(
                is_active=True
            ).count(),
            "users": User.objects.count(),
        }

    def get_runtime_macro_index_metadata_map(self) -> dict[str, dict[str, Any]]:
        """Return runtime macro indicator metadata map."""

        return self._build_runtime_macro_metadata_map()

    def get_runtime_macro_index_codes(self) -> list[str]:
        """Return runtime macro indicator codes."""

        return list(self._build_runtime_macro_metadata_map().keys())

    def get_runtime_macro_publication_lags(self) -> dict[str, dict[str, Any]]:
        """Return runtime macro publication lag settings."""

        return {
            code: {
                "days": item.get("publication_lag_days", 0),
                "description": item.get("publication_lag_description", "实时"),
            }
            for code, item in self._build_runtime_macro_metadata_map().items()
        }

    def get_runtime_qlib_config(self) -> dict[str, Any]:
        """Return runtime qlib config."""

        return SystemSettingsModel.get_runtime_qlib_config()

    def get_runtime_alpha_fixed_provider(self) -> str:
        """Return runtime fixed alpha provider."""

        return SystemSettingsModel.get_runtime_alpha_fixed_provider()

    def get_runtime_alpha_pool_mode(self, default_mode: str = "") -> str:
        """Return runtime alpha pool mode."""

        mode = SystemSettingsModel.get_runtime_alpha_pool_mode()
        return mode or default_mode

    def get_runtime_benchmark_code(self, key: str, default: str = "") -> str:
        """Return a runtime benchmark code by key."""

        return SystemSettingsModel.get_runtime_benchmark_code(key, default)
