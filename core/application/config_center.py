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
        key="mcp_guide",
        name="MCP 接入说明",
        module="account",
        section="账户级配置",
        description="复制当前用户的 Token、Base URL、默认账户和 Agent 接入片段。",
        permission="login",
        frontend_url="/account/mcp/",
        api_url="/api/account/profile/",
        sdk_module="account",
        mcp_tools=(),
        supports_edit=False,
        docs_ref="docs/business/config-center-matrix.md#mcp_guide",
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
        module="config_center",
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
        key="qlib_runtime",
        name="Qlib Runtime 配置",
        module="config_center",
        section="系统级配置",
        description="Qlib provider、模型目录、默认 universe/feature/label 与训练队列配置。",
        permission="staff",
        frontend_url="/settings/config-center/qlib/",
        api_url="/api/system/config-center/qlib/runtime/",
        sdk_module="config_center",
        mcp_tools=("get_qlib_runtime_config", "update_qlib_runtime_config"),
        supports_edit=True,
        docs_ref="docs/business/config-center-matrix.md#qlib_runtime",
    ),
    ConfigCapability(
        key="qlib_training",
        name="Qlib 在线训练中心",
        module="config_center",
        section="系统级配置",
        description="训练模板、训练记录与异步训练触发入口。",
        permission="staff",
        frontend_url="/settings/config-center/qlib/",
        api_url="/api/system/config-center/qlib/training-runs/",
        sdk_module="config_center",
        mcp_tools=(
            "list_qlib_training_profiles",
            "save_qlib_training_profile",
            "list_qlib_training_runs",
            "get_qlib_training_run_detail",
            "trigger_qlib_training",
        ),
        supports_edit=True,
        docs_ref="docs/business/config-center-matrix.md#qlib_training",
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
    from apps.account.application.config_summary_service import (
        get_account_config_summary_service,
    )

    return get_account_config_summary_service().get_account_settings_summary(user)


def get_system_settings_summary(user: Any = None) -> dict[str, Any]:
    from apps.config_center.application.config_summary_service import (
        get_config_center_summary_service,
    )

    return get_config_center_summary_service().get_system_settings_summary()


def get_qlib_runtime_summary(user: Any = None) -> dict[str, Any]:
    from apps.config_center.application.use_cases import GetQlibRuntimeConfigUseCase

    return {
        "status": "configured",
        "summary": GetQlibRuntimeConfigUseCase().execute(),
    }


def get_qlib_training_summary(user: Any = None) -> dict[str, Any]:
    from apps.config_center.application.use_cases import ListQlibTrainingRunsUseCase

    runs = ListQlibTrainingRunsUseCase().execute(limit=5)
    latest_run = runs[0] if runs else None
    return {
        "status": "configured",
        "summary": {
            "latest_run_status": getattr(latest_run, "status", None),
            "recent_run_count": len(runs),
            "training_task_running": any(
                run.status in {"PENDING", "RUNNING"}
                for run in runs
            ),
        },
    }


def get_mcp_guide_summary(user: Any) -> dict[str, Any]:
    from apps.account.application.config_summary_service import (
        get_account_config_summary_service,
    )

    summary = get_account_config_summary_service().get_account_settings_summary(user)
    payload = dict(summary.get("summary", {}))
    active_token_count = int(payload.get("active_token_count") or 0)
    mcp_enabled = bool(payload.get("mcp_enabled"))
    if mcp_enabled and active_token_count > 0:
        status = "configured"
    elif mcp_enabled:
        status = "attention"
    else:
        status = "missing"
    payload["token_ready"] = "yes" if active_token_count > 0 else "no"
    return {
        "status": status,
        "summary": payload,
    }


def get_agent_runtime_operator_summary(user: Any) -> dict[str, Any]:
    from apps.agent_runtime.application.config_summary_service import (
        get_agent_runtime_config_summary_service,
    )

    return get_agent_runtime_config_summary_service().get_operator_summary(user)


def get_data_center_provider_summary(user: Any) -> dict[str, Any]:
    from apps.data_center.application.config_summary_service import (
        get_data_center_config_summary_service,
    )

    return get_data_center_config_summary_service().get_provider_summary()


def get_data_center_runtime_summary(user: Any) -> dict[str, Any]:
    from apps.data_center.application.config_summary_service import (
        get_data_center_config_summary_service,
    )

    return get_data_center_config_summary_service().get_runtime_summary()


def get_beta_gate_summary(user: Any) -> dict[str, Any]:
    from apps.beta_gate.application.config_summary_service import (
        get_beta_gate_config_summary_service,
    )

    return get_beta_gate_config_summary_service().get_beta_gate_summary(user)


def get_valuation_repair_summary(user: Any) -> dict[str, Any]:
    from apps.equity.application.config import get_valuation_repair_config_summary

    config = get_valuation_repair_config_summary(use_cache=False)
    return {
        "status": "configured",
        "summary": config,
    }


def get_ai_provider_summary(user: Any) -> dict[str, Any]:
    from apps.ai_provider.application.config_summary_service import (
        get_ai_provider_config_summary_service,
    )

    return get_ai_provider_config_summary_service().get_provider_summary(user)


def get_trading_cost_summary(user: Any) -> dict[str, Any]:
    from apps.account.application.config_summary_service import (
        get_account_config_summary_service,
    )

    return get_account_config_summary_service().get_trading_cost_summary(user)


_SUMMARY_BUILDERS = {
    "account_settings": lambda user: _safe_summary(get_account_settings_summary, "账户设置", user),
    "mcp_guide": lambda user: _safe_summary(get_mcp_guide_summary, "MCP 接入说明", user),
    "agent_runtime_operator": lambda user: _safe_summary(
        get_agent_runtime_operator_summary, "Agent Runtime Operator", user
    ),
    "system_settings": lambda user: _safe_summary(get_system_settings_summary, "系统设置", user),
    "qlib_runtime": lambda user: _safe_summary(get_qlib_runtime_summary, "Qlib Runtime 配置", user),
    "qlib_training": lambda user: _safe_summary(get_qlib_training_summary, "Qlib 在线训练中心", user),
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
