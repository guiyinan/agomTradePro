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
        key="account_settings",
        name="账户设置",
        module="account",
        section="账户级配置",
        description="个人资料、风险偏好、密码与 MCP/SDK Token 管理。",
        permission="login",
        frontend_url="/account/settings/",
        api_url=None,
        sdk_module="account",
        mcp_tools=(),
        supports_edit=True,
        docs_ref="docs/business/config-center-matrix.md#account_settings",
    ),
    ConfigCapability(
        key="agent_runtime_operator",
        name="Agent Runtime Operator",
        module="agent_runtime",
        section="系统级配置",
        description="查看 AI-native task/proposal 队列，并进入 operator 页面执行审批与处置。",
        permission="staff",
        frontend_url="/settings/agent-runtime/",
        api_url="/api/agent-runtime/dashboard/summary/",
        sdk_module="agent_runtime",
        mcp_tools=(
            "start_research_task",
            "resume_agent_task",
            "create_agent_proposal",
            "approve_agent_proposal",
            "execute_agent_proposal",
        ),
        supports_edit=False,
        docs_ref="docs/plans/ai-native/M4-observability-recovery-and-release.md",
    ),
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
        key="data_center_providers",
        name="数据中台 Provider 配置",
        module="data_center",
        section="数据源",
        description="配置 Tushare、AKShare、EastMoney、QMT、FRED 等统一数据源 Provider。",
        permission="staff",
        frontend_url="/data-center/providers/",
        api_url="/api/data-center/providers/",
        sdk_module="data_center",
        mcp_tools=(
            "list_data_center_providers",
            "create_data_center_provider",
            "update_data_center_provider",
            "test_data_center_provider_connection",
        ),
        supports_edit=True,
        docs_ref="docs/business/config-center-matrix.md#data_center_providers",
    ),
    ConfigCapability(
        key="data_center_runtime",
        name="数据中台运行状态",
        module="data_center",
        section="数据源",
        description="查看 Provider 运行状态、健康检查和实时能力覆盖。",
        permission="staff",
        frontend_url="/data-center/monitor/",
        api_url="/api/data-center/providers/status/",
        sdk_module="data_center",
        mcp_tools=("get_data_center_provider_status",),
        supports_edit=False,
        docs_ref="docs/business/config-center-matrix.md#data_center_runtime",
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


def _safe_summary(builder, fallback_name: str, user: Any) -> dict[str, Any]:
    try:
        return builder(user)
    except Exception as exc:
        logger.warning("Failed to build %s summary: %s", fallback_name, exc)
        return {
            "status": "attention",
            "summary": {
                "message": f"{fallback_name} 读取失败",
            },
        }


def get_account_settings_summary(user: Any) -> dict[str, Any]:
    from apps.account.infrastructure.models import AccountProfileModel, UserAccessTokenModel

    if not getattr(user, "is_authenticated", False):
        return {
            "status": "missing",
            "summary": {"message": "请先登录"},
        }

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


def get_system_settings_summary(user: Any) -> dict[str, Any]:
    from apps.account.infrastructure.models import SystemSettingsModel

    settings_obj = SystemSettingsModel.get_settings()
    return {
        "status": "configured",
        "summary": {
            "default_mcp_enabled": settings_obj.default_mcp_enabled,
            "allow_token_plaintext_view": settings_obj.allow_token_plaintext_view,
            "market_color_convention": settings_obj.market_color_convention,
            "market_color_label": settings_obj.get_market_visual_tokens()["label"],
            "benchmark_map_size": len(settings_obj.benchmark_code_map or {}),
            "macro_index_catalog_size": len(settings_obj.macro_index_catalog or []),
            "updated_at": (
                settings_obj.updated_at.isoformat()
                if getattr(settings_obj, "updated_at", None)
                else None
            ),
        },
    }


def get_agent_runtime_operator_summary(user: Any) -> dict[str, Any]:
    from django.db.models import Q

    from apps.agent_runtime.infrastructure.models import AgentProposalModel, AgentTaskModel

    needs_attention_count = (
        AgentTaskModel._default_manager.filter(
            Q(requires_human=True) | Q(status__in=["needs_human", "failed"])
        )
        .distinct()
        .count()
    )
    pending_approval_count = AgentProposalModel._default_manager.filter(
        status__in=["generated", "submitted", "approved"]
    ).count()

    status = "configured"
    if needs_attention_count > 0 or pending_approval_count > 0:
        status = "attention"

    return {
        "status": status,
        "summary": {
            "total_tasks": AgentTaskModel._default_manager.count(),
            "needs_attention_count": needs_attention_count,
            "pending_approval_count": pending_approval_count,
            "operator_url": "/settings/agent-runtime/",
        },
    }


def get_data_center_provider_summary(user: Any) -> dict[str, Any]:
    from apps.data_center.infrastructure.models import (
        DataProviderSettingsModel,
        ProviderConfigModel,
    )

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


def get_data_center_runtime_summary(user: Any) -> dict[str, Any]:
    from apps.data_center.application.registry_factory import get_registry
    from apps.data_center.infrastructure.models import ProviderConfigModel

    configured = list(
        ProviderConfigModel._default_manager.filter(is_active=True).values_list("name", flat=True)
    )
    snapshots = [snapshot.to_dict() for snapshot in get_registry().get_all_statuses()]
    unique_providers = sorted({snap["provider_name"] for snap in snapshots})
    circuit_open_count = sum(1 for snap in snapshots if snap["status"] == "circuit_open")
    degraded_count = sum(1 for snap in snapshots if snap["status"] == "degraded")
    healthy_count = sum(1 for snap in snapshots if snap["status"] == "healthy")

    status = "configured" if configured else "missing"
    if circuit_open_count > 0 or degraded_count > 0:
        status = "attention"

    return {
        "status": status,
        "summary": {
            "configured_provider_count": len(configured),
            "runtime_provider_count": len(unique_providers),
            "healthy_snapshot_count": healthy_count,
            "degraded_snapshot_count": degraded_count,
            "circuit_open_snapshot_count": circuit_open_count,
            "providers": unique_providers[:5],
        },
    }


def get_beta_gate_summary(user: Any) -> dict[str, Any]:
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
            "effective_date": (
                active_config.effective_date.isoformat() if active_config.effective_date else None
            ),
        },
    }


def get_valuation_repair_summary(user: Any) -> dict[str, Any]:
    from apps.equity.application.config import get_valuation_repair_config_summary

    config = get_valuation_repair_config_summary(use_cache=False)
    return {
        "status": "configured",
        "summary": config,
    }


def get_ai_provider_summary(user: Any) -> dict[str, Any]:
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


def get_trading_cost_summary(user: Any) -> dict[str, Any]:
    from apps.account.infrastructure.models import PortfolioModel, TradingCostConfigModel

    if not getattr(user, "is_authenticated", False):
        return {
            "status": "missing",
            "summary": {"message": "请先登录"},
        }

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


_SUMMARY_BUILDERS = {
    "account_settings": lambda user: _safe_summary(get_account_settings_summary, "账户设置", user),
    "agent_runtime_operator": lambda user: _safe_summary(
        get_agent_runtime_operator_summary, "Agent Runtime Operator", user
    ),
    "system_settings": lambda user: _safe_summary(get_system_settings_summary, "系统设置", user),
    "data_center_providers": lambda user: _safe_summary(
        get_data_center_provider_summary, "数据中台 Provider 配置", user
    ),
    "data_center_runtime": lambda user: _safe_summary(
        get_data_center_runtime_summary, "数据中台运行状态", user
    ),
    "beta_gate": lambda user: _safe_summary(get_beta_gate_summary, "Beta Gate 配置", user),
    "valuation_repair": lambda user: _safe_summary(
        get_valuation_repair_summary, "估值修复配置", user
    ),
    "ai_provider": lambda user: _safe_summary(get_ai_provider_summary, "AI Provider 配置", user),
    "trading_cost": lambda user: _safe_summary(get_trading_cost_summary, "交易费率配置", user),
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
        summary_payload = _SUMMARY_BUILDERS[capability.key](user)
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
