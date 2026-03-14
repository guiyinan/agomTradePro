"""Config center aggregation for frontend, API, SDK, and MCP."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigCapability:
    key: str
    name: str
    module: str
    section: str
    description: str
    permission: str
    frontend_url: str | None
    api_url: str | None
    sdk_module: str | None
    mcp_tools: tuple[str, ...]
    supports_edit: bool
    docs_ref: str


_CAPABILITIES: tuple[ConfigCapability, ...] = (
    ConfigCapability(
        key="system_settings",
        name="系统设置",
        module="account",
        section="系统级配置",
        description="审批策略、默认 MCP、协议文案与系统基础参数。",
        permission="staff",
        frontend_url="/account/admin/settings/",
        api_url=None,
        sdk_module=None,
        mcp_tools=(),
        supports_edit=True,
        docs_ref="docs/business/config-center-matrix.md#system_settings",
    ),
    ConfigCapability(
        key="macro_datasources",
        name="宏观数据源配置",
        module="macro",
        section="数据源",
        description="AKShare、Tushare 等宏观数据源配置与优先级。",
        permission="staff",
        frontend_url="/macro/datasources/",
        api_url=None,
        sdk_module=None,
        mcp_tools=(),
        supports_edit=True,
        docs_ref="docs/business/config-center-matrix.md#macro_datasources",
    ),
    ConfigCapability(
        key="market_data_providers",
        name="市场数据源状态",
        module="market_data",
        section="数据源",
        description="统一市场数据 provider 的健康状态与可用性。",
        permission="staff",
        frontend_url="/market-data/providers/",
        api_url=None,
        sdk_module="market_data",
        mcp_tools=("get_market_data_provider_health",),
        supports_edit=False,
        docs_ref="docs/business/config-center-matrix.md#market_data_providers",
    ),
    ConfigCapability(
        key="beta_gate",
        name="Beta Gate 配置",
        module="beta_gate",
        section="风控与策略",
        description="风险画像、Regime/Policy/组合约束配置。",
        permission="staff",
        frontend_url="/beta-gate/config/",
        api_url="/api/beta-gate/configs/",
        sdk_module="beta_gate",
        mcp_tools=(
            "list_beta_gate_configs",
            "create_beta_gate_config",
            "rollback_beta_gate_config",
        ),
        supports_edit=True,
        docs_ref="docs/business/config-center-matrix.md#beta_gate",
    ),
    ConfigCapability(
        key="valuation_repair",
        name="估值修复配置",
        module="equity",
        section="风控与策略",
        description="估值修复阈值、确认窗口、停滞窗口与版本管理。",
        permission="staff",
        frontend_url="/equity/valuation-repair/config/",
        api_url="/api/equity/config/valuation-repair/active/",
        sdk_module="equity",
        mcp_tools=(
            "get_valuation_repair_config",
            "list_valuation_repair_configs",
            "create_valuation_repair_config",
            "activate_valuation_repair_config",
            "rollback_valuation_repair_config",
        ),
        supports_edit=True,
        docs_ref="docs/business/config-center-matrix.md#valuation_repair",
    ),
    ConfigCapability(
        key="ai_provider",
        name="AI Provider 配置",
        module="ai_provider",
        section="系统级配置",
        description="AI 供应商、默认模型、启用状态与预算限制。",
        permission="staff",
        frontend_url="/ai/",
        api_url="/api/ai/providers/",
        sdk_module="ai_provider",
        mcp_tools=(
            "list_ai_providers",
            "get_ai_provider",
            "create_ai_provider",
            "update_ai_provider",
            "toggle_ai_provider",
        ),
        supports_edit=True,
        docs_ref="docs/business/config-center-matrix.md#ai_provider",
    ),
    ConfigCapability(
        key="trading_cost",
        name="交易费率配置",
        module="account",
        section="账户级配置",
        description="佣金、印花税、过户费等账户交易成本配置。",
        permission="login",
        frontend_url="/account/settings/",
        api_url="/api/account/trading-cost-configs/",
        sdk_module="account",
        mcp_tools=(
            "get_trading_cost_configs",
            "create_trading_cost_config",
            "update_trading_cost_config",
        ),
        supports_edit=True,
        docs_ref="docs/business/config-center-matrix.md#trading_cost",
    ),
)


def _safe_summary(builder, fallback_name: str) -> dict[str, Any]:
    try:
        return builder()
    except Exception as exc:
        logger.warning("Failed to build %s summary: %s", fallback_name, exc)
        return {
            "status": "attention",
            "summary": {
                "message": f"{fallback_name} 读取失败",
            },
        }


def get_system_settings_summary() -> dict[str, Any]:
    from apps.account.infrastructure.models import SystemSettingsModel

    settings_obj = SystemSettingsModel.get_settings()
    return {
        "status": "configured",
        "summary": {
            "default_mcp_enabled": settings_obj.default_mcp_enabled,
            "allow_token_plaintext_view": settings_obj.allow_token_plaintext_view,
            "benchmark_map_size": len(settings_obj.benchmark_code_map or {}),
            "macro_index_catalog_size": len(settings_obj.macro_index_catalog or []),
            "updated_at": settings_obj.updated_at.isoformat() if getattr(settings_obj, "updated_at", None) else None,
        },
    }


def get_macro_datasource_summary() -> dict[str, Any]:
    from apps.macro.infrastructure.models import DataSourceConfig

    rows = list(
        DataSourceConfig._default_manager.all().values(
            "source_type",
            "name",
            "is_active",
            "api_key",
        )
    )
    if not rows:
        return {
            "status": "missing",
            "summary": {"message": "未配置宏观数据源", "total_sources": 0, "active_sources": 0},
        }

    active_rows = [row for row in rows if row["is_active"]]
    requires_key_types = {"tushare", "fred", "wind", "choice"}
    missing_key_count = sum(
        1
        for row in active_rows
        if row["source_type"] in requires_key_types and not (row.get("api_key") or "").strip()
    )
    status = "configured"
    if not active_rows:
        status = "missing"
    elif missing_key_count > 0:
        status = "attention"
    return {
        "status": status,
        "summary": {
            "total_sources": len(rows),
            "active_sources": len(active_rows),
            "source_types": sorted({row["source_type"] for row in active_rows}),
            "missing_api_key_count": missing_key_count,
        },
    }


def get_market_data_provider_summary() -> dict[str, Any]:
    try:
        from apps.market_data.interface.page_views import build_provider_dashboard

        dashboard = build_provider_dashboard()
        providers = dashboard.get("providers", []) if isinstance(dashboard, dict) else []
        unhealthy_count = sum(1 for provider in providers if not provider.get("healthy", True))
        status = "configured" if providers else "missing"
        if unhealthy_count > 0:
            status = "attention"
        return {
            "status": status,
            "summary": {
                "provider_count": len(providers),
                "unhealthy_count": unhealthy_count,
                "providers": [provider.get("name") for provider in providers[:5]],
            },
        }
    except Exception:
        return {
            "status": "api_only",
            "summary": {
                "message": "仅提供页面入口，未发现统一 provider 摘要接口",
            },
        }


def get_beta_gate_summary() -> dict[str, Any]:
    from apps.beta_gate.infrastructure.models import GateConfigModel

    active_config = GateConfigModel._default_manager.active().first()
    total_versions = GateConfigModel._default_manager.count()
    if not active_config:
        return {
            "status": "missing",
            "summary": {
                "message": "未发现激活的 Beta Gate 配置",
                "total_versions": total_versions,
            },
        }

    return {
        "status": "configured",
        "summary": {
            "config_id": active_config.config_id,
            "risk_profile": active_config.risk_profile,
            "version": active_config.version,
            "total_versions": total_versions,
            "effective_date": active_config.effective_date.isoformat() if active_config.effective_date else None,
        },
    }


def get_valuation_repair_summary() -> dict[str, Any]:
    from apps.equity.application.config import get_valuation_repair_config_summary

    config = get_valuation_repair_config_summary(use_cache=False)
    return {
        "status": "configured",
        "summary": config,
    }


def get_ai_provider_summary() -> dict[str, Any]:
    from apps.ai_provider.infrastructure.models import AIProviderConfig, AIUsageLog

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
            "summary": {"message": "未配置 AI Provider", "provider_count": 0, "active_count": 0},
        }

    active_providers = [provider for provider in providers if provider["is_active"]]
    recent_error_count = AIUsageLog._default_manager.filter(status__in=["error", "timeout"]).count()
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


def get_trading_cost_summary() -> dict[str, Any]:
    from apps.account.infrastructure.models import PortfolioModel, TradingCostConfigModel

    total_portfolios = PortfolioModel._default_manager.count()
    configs = list(
        TradingCostConfigModel._default_manager.all().values(
            "portfolio_id",
            "commission_rate",
            "stamp_duty_rate",
            "is_active",
            "updated_at",
        )
    )
    active_configs = [cfg for cfg in configs if cfg["is_active"]]
    status = "configured" if configs else "api_only"
    return {
        "status": status,
        "summary": {
            "portfolio_count": total_portfolios,
            "config_count": len(configs),
            "active_count": len(active_configs),
            "default_commission_rate": active_configs[0]["commission_rate"] if active_configs else None,
            "default_stamp_duty_rate": active_configs[0]["stamp_duty_rate"] if active_configs else None,
        },
    }


_SUMMARY_BUILDERS = {
    "system_settings": lambda: _safe_summary(get_system_settings_summary, "系统设置"),
    "macro_datasources": lambda: _safe_summary(get_macro_datasource_summary, "宏观数据源配置"),
    "market_data_providers": lambda: _safe_summary(get_market_data_provider_summary, "市场数据源状态"),
    "beta_gate": lambda: _safe_summary(get_beta_gate_summary, "Beta Gate 配置"),
    "valuation_repair": lambda: _safe_summary(get_valuation_repair_summary, "估值修复配置"),
    "ai_provider": lambda: _safe_summary(get_ai_provider_summary, "AI Provider 配置"),
    "trading_cost": lambda: _safe_summary(get_trading_cost_summary, "交易费率配置"),
}


def list_config_capabilities() -> list[dict[str, Any]]:
    return [
        {
            "key": capability.key,
            "name": capability.name,
            "module": capability.module,
            "section": capability.section,
            "description": capability.description,
            "permission": capability.permission,
            "frontend_url": capability.frontend_url,
            "api_url": capability.api_url,
            "sdk_module": capability.sdk_module,
            "mcp_tools": list(capability.mcp_tools),
            "supports_edit": capability.supports_edit,
            "docs_ref": capability.docs_ref,
        }
        for capability in _CAPABILITIES
    ]


def build_config_center_snapshot(user: Any) -> dict[str, Any]:
    sections: dict[str, dict[str, Any]] = {}

    for capability in _CAPABILITIES:
        if capability.permission == "staff" and not getattr(user, "is_staff", False):
            continue
        summary_payload = _SUMMARY_BUILDERS[capability.key]()
        section = sections.setdefault(
            capability.section,
            {"key": capability.section, "title": capability.section, "items": []},
        )
        section["items"].append(
            {
                "key": capability.key,
                "name": capability.name,
                "module": capability.module,
                "description": capability.description,
                "permission": capability.permission,
                "frontend_url": capability.frontend_url,
                "api_url": capability.api_url,
                "sdk_module": capability.sdk_module,
                "mcp_tools": list(capability.mcp_tools),
                "supports_edit": capability.supports_edit,
                "docs_ref": capability.docs_ref,
                "status": summary_payload.get("status", "attention"),
                "summary": summary_payload.get("summary", {}),
            }
        )

    return {
        "generated_at": timezone.now().isoformat(),
        "sections": list(sections.values()),
    }
