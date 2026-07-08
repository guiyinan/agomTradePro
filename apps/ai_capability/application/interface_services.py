"""Application-facing helpers for AI capability interface views."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from apps.account.application.interface_services import (
    TOKEN_ACCESS_LEVEL_CHOICES,
    TOKEN_ACCESS_LEVEL_READ_ONLY,
    build_mcp_guide_context,
    get_token_access_level_choices,
)
from apps.ai_capability.application.repository_provider import (
    get_capability_repository,
    get_capability_sync_log_repository,
)
from apps.ai_capability.application.use_cases import (
    GetCapabilityDetailUseCase,
    GetCapabilityListUseCase,
)


def _derive_module_name(tool_name: str) -> str:
    parts = (tool_name or "").split("_")
    return parts[0] if parts else "misc"


def list_capability_summary_payloads(
    *,
    source_type: str | None = None,
    route_group: str | None = None,
    category: str | None = None,
    enabled_only: bool = True,
) -> list[dict[str, Any]]:
    """Return capability summaries as serializer-ready dict payloads."""

    use_case = GetCapabilityListUseCase(capability_repo=get_capability_repository())
    return [
        capability.to_dict()
        for capability in use_case.execute(
            source_type=source_type,
            route_group=route_group,
            category=category,
            enabled_only=enabled_only,
        )
    ]


def get_mcp_tools_page_context(
    *,
    search_query: str,
    module_filter: str,
    status_filter: str,
) -> dict[str, Any]:
    """Build the template context for the MCP tools page."""

    catalog_payload = get_mcp_tools_catalog_payload(
        search_query=search_query,
        module_filter=module_filter,
        status_filter=status_filter,
        limit=300,
    )

    return {
        "page_title": "MCP 工具管理",
        "page_subtitle": "管理已同步到 AI Capability Catalog 的 MCP 工具，支持检索、查看 Schema、切换终端/路由启用状态以及重新同步。",
        **catalog_payload,
    }


def get_mcp_tools_catalog_payload(
    *,
    search_query: str = "",
    module_filter: str = "",
    status_filter: str = "",
    limit: int = 80,
) -> dict[str, Any]:
    """Return serializer-ready MCP tool catalog payload for web and TUI surfaces."""

    capability_repo = get_capability_repository()
    all_tools = capability_repo.list_capabilities(source_type="mcp_tool", enabled_only=False)
    tools = _filter_mcp_tools(
        all_tools,
        search_query=search_query,
        module_filter=module_filter,
        status_filter=status_filter,
    )
    latest_sync = get_capability_sync_log_repository().get_latest("mcp_tool")

    return {
        "tools": [_mcp_tool_page_payload(tool) for tool in tools[: max(limit, 1)]],
        "total_count": len(tools),
        "module_choices": sorted({_derive_module_name(item.name) for item in all_tools}),
        "search_query": search_query,
        "module_filter": module_filter,
        "status_filter": status_filter,
        "latest_sync": latest_sync,
        "latest_sync_at": latest_sync.finished_at if latest_sync else None,
        "latest_sync_total_discovered": latest_sync.total_discovered if latest_sync else 0,
    }


def get_mcp_tools_stats_payload() -> dict[str, Any]:
    """Return aggregate MCP governance stats for TUI and JSON surfaces."""

    tools = get_capability_repository().list_capabilities(source_type="mcp_tool", enabled_only=False)
    latest_sync = get_capability_sync_log_repository().get_latest("mcp_tool")
    total = len(tools)
    routing_enabled = sum(1 for item in tools if item.enabled_for_routing)
    terminal_enabled = sum(1 for item in tools if item.enabled_for_terminal)

    return {
        "status": "ready" if total else "empty",
        "total": total,
        "module_count": len({_derive_module_name(item.name) for item in tools}),
        "routing_enabled": routing_enabled,
        "routing_disabled": total - routing_enabled,
        "terminal_enabled": terminal_enabled,
        "terminal_disabled": total - terminal_enabled,
        "requires_confirmation": sum(1 for item in tools if item.requires_confirmation),
        "high_risk": sum(
            1
            for item in tools
            if getattr(item.risk_level, "value", str(item.risk_level)) in {"high", "critical"}
        ),
        "latest_sync_at": latest_sync.finished_at if latest_sync else None,
        "latest_sync_total_discovered": latest_sync.total_discovered if latest_sync else 0,
        "latest_sync_created": latest_sync.created_count if latest_sync else 0,
        "latest_sync_updated": latest_sync.updated_count if latest_sync else 0,
        "latest_sync_disabled": latest_sync.disabled_count if latest_sync else 0,
    }


def _filter_mcp_tools(
    tools: list[Any],
    *,
    search_query: str,
    module_filter: str,
    status_filter: str,
) -> list[Any]:
    filtered = list(tools)
    if search_query:
        normalized_query = search_query.lower()
        filtered = [
            item
            for item in filtered
            if normalized_query in item.capability_key.lower()
            or normalized_query in item.name.lower()
            or normalized_query in item.summary.lower()
            or normalized_query in item.description.lower()
        ]

    if module_filter:
        filtered = [item for item in filtered if _derive_module_name(item.name) == module_filter]

    if status_filter == "routing_on":
        filtered = [item for item in filtered if item.enabled_for_routing]
    elif status_filter == "routing_off":
        filtered = [item for item in filtered if not item.enabled_for_routing]
    elif status_filter == "terminal_on":
        filtered = [item for item in filtered if item.enabled_for_terminal]
    elif status_filter == "terminal_off":
        filtered = [item for item in filtered if not item.enabled_for_terminal]

    return filtered


def _mcp_tool_page_payload(capability) -> dict[str, Any]:
    input_schema = dict(capability.input_schema or {})
    return {
        "capability_key": capability.capability_key,
        "name": capability.name,
        "module_name": _derive_module_name(capability.name),
        "summary": capability.summary,
        "description": capability.description,
        "route_group": capability.route_group.value,
        "category": capability.category,
        "risk_level": capability.risk_level.value,
        "review_status": capability.review_status.value,
        "visibility": capability.visibility.value,
        "requires_confirmation": capability.requires_confirmation,
        "input_schema": input_schema,
        "input_schema_json": (
            json.dumps(input_schema, ensure_ascii=False, indent=2)
            if input_schema
            else "未发布 input schema"
        ),
        "enabled_for_routing": capability.enabled_for_routing,
        "enabled_for_terminal": capability.enabled_for_terminal,
    }


def get_capability_gateway_page_context(
    *,
    user_id: int,
    base_url: str,
) -> dict[str, Any]:
    """Build the operator page context for capability gateway onboarding."""

    repository = get_capability_repository()
    stats = repository.get_stats()
    mcp_summary = _source_summary("mcp_tool")
    terminal_summary = _source_summary("terminal_command")
    api_summary = _source_summary("api")
    builtin_summary = _source_summary("builtin")
    mcp_context = build_mcp_guide_context(user_id=user_id, base_url=base_url)

    route_endpoint = f"{base_url}/api/ai-capability/route/"
    web_endpoint = f"{base_url}/api/ai-capability/web/"
    capability_endpoint = f"{base_url}/api/ai-capability/capabilities/"
    agent_prompt = build_capability_gateway_agent_prompt(
        base_url=base_url,
        route_endpoint=route_endpoint,
        web_endpoint=web_endpoint,
        capability_endpoint=capability_endpoint,
        preferred_token=mcp_context.get("preferred_token"),
        default_account_id=mcp_context.get("default_account_id"),
    )
    token_hint = "<your_token>"
    route_payload = {
        "message": "现在系统状态如何？",
        "entrypoint": "agent",
        "context": {
            "answer_chain_enabled": True,
            "params": {},
        },
    }

    return {
        "page_title": "能力路由接入",
        "page_subtitle": "把 AI、Terminal、TUI 和 MCP 工具统一接入 Capability Router，避免模型直接面对大量底层接口。",
        "base_url": base_url,
        "profile": mcp_context["profile"],
        "access_tokens": mcp_context.get("access_tokens", []),
        "preferred_token": mcp_context.get("preferred_token"),
        "token_plaintext_allowed": bool(mcp_context.get("token_plaintext_allowed")),
        "default_account_id": mcp_context.get("default_account_id"),
        "default_account_name": mcp_context.get("default_account_name"),
        "token_access_level_choices": get_token_access_level_choices(),
        "default_token_access_level": TOKEN_ACCESS_LEVEL_READ_ONLY,
        "new_token_payload": mcp_context.get("new_token_payload"),
        **agent_prompt,
        "catalog_stats": stats,
        "source_cards": [
            {"label": "Builtin", **builtin_summary},
            {"label": "Terminal", **terminal_summary},
            {"label": "MCP Tools", **mcp_summary},
            {"label": "Internal APIs", **api_summary},
        ],
        "route_endpoint": route_endpoint,
        "web_endpoint": web_endpoint,
        "capability_endpoint": capability_endpoint,
        "curl_route_example": "\n".join(
            [
                "curl -X POST \\",
                f'  "{route_endpoint}" \\',
                '  -H "Content-Type: application/json" \\',
                f'  -H "Authorization: Token {token_hint}" \\',
                '  -d \'{"message":"现在系统状态如何？","entrypoint":"agent","context":{"answer_chain_enabled":true}}\'',
            ]
        ),
        "route_payload_json": json.dumps(route_payload, ensure_ascii=False, indent=2),
        "onboarding_steps": [
            {
                "title": "1. 获取 Token",
                "body": "用户先在本页或 MCP 接入说明页生成只读 Token；管理员可在 Token 管理页为指定用户开通 MCP/SDK 权限。",
                "href": "/account/mcp/",
                "link_label": "打开 MCP 接入说明",
            },
            {
                "title": "2. 接入统一路由",
                "body": "外部 Agent 只调用 /api/ai-capability/route/，由 Capability Catalog 检索并选择 MCP、Terminal、内置能力或内部 API。",
                "href": "/api/ai-capability/",
                "link_label": "查看路由 API",
            },
            {
                "title": "3. 治理 MCP 工具",
                "body": "管理员在 MCP 工具页同步底层工具，打开 enabled_for_routing 后才允许进入 AI 路由候选集。",
                "href": "/settings/mcp-tools/",
                "link_label": "管理 MCP 工具",
            },
            {
                "title": "4. 从 TUI 验证",
                "body": "TUI 的能力路由屏幕会走同一个路由 API，可用来检查候选能力、确认提示和回答链。",
                "href": "/tui/",
                "link_label": "打开 TUI",
            },
        ],
    }


def build_capability_gateway_agent_prompt(
    *,
    base_url: str,
    route_endpoint: str,
    web_endpoint: str,
    capability_endpoint: str,
    preferred_token: dict[str, Any] | None,
    default_account_id: Any | None,
    token_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a copy-ready bootstrap prompt for external AI agents."""

    token_value = ""
    token_name = ""
    access_level = TOKEN_ACCESS_LEVEL_READ_ONLY
    access_level_label = dict(TOKEN_ACCESS_LEVEL_CHOICES).get(
        TOKEN_ACCESS_LEVEL_READ_ONLY,
        "只读",
    )

    if token_payload:
        token_value = str(token_payload.get("token") or "").strip()
        token_name = str(token_payload.get("token_name") or "").strip()
        access_level = str(token_payload.get("access_level") or TOKEN_ACCESS_LEVEL_READ_ONLY)
        access_level_label = str(token_payload.get("access_level_label") or access_level_label)
    elif preferred_token:
        token_value = str(preferred_token.get("plaintext") or "").strip()
        token_name = str(preferred_token.get("name") or "").strip()
        access_level = str(preferred_token.get("access_level") or TOKEN_ACCESS_LEVEL_READ_ONLY)
        access_level_label = str(
            preferred_token.get("access_level_label")
            or dict(TOKEN_ACCESS_LEVEL_CHOICES).get(access_level, access_level)
        )

    token_placeholder = token_value or "<请先在页面生成一个可见 Token>"
    account_hint = str(default_account_id) if default_account_id not in (None, "") else "可留空"
    safety_line = (
        "- 当前 Token 为只读：只允许 GET/HEAD/OPTIONS 与只读查询，不要执行写入、删除、同步、交易或审批类操作。"
        if access_level == TOKEN_ACCESS_LEVEL_READ_ONLY
        else "- 当前 Token 为读写：仍需遵守账号 RBAC、后端确认流程和能力风险控制，不要假设拥有管理员权限。"
    )
    prompt_lines = [
        "请按以下连接信息接入 AgomTradePro：",
        f"- Base URL: {base_url}",
        f"- Route API: {route_endpoint}",
        f"- Web Chat API: {web_endpoint}",
        f"- Capability Catalog: {capability_endpoint}",
        f"- Authorization: Token {token_placeholder}",
        f"- Token access level: {access_level_label}",
        f"- Default account id: {account_hint}",
        "",
        "执行规则：",
        "- 优先调用 Route API 处理自然语言任务，由后端统一路由到 MCP、Terminal、Builtin 或内部 API。",
        safety_line,
        "- 如果要直接排查目录覆盖，可读取 Capability Catalog 和 stats 接口；不要先猜底层工具名。",
        "",
        "Route API 示例请求：",
        f"POST {route_endpoint}",
        "Headers:",
        f"Authorization: Token {token_placeholder}",
        "Content-Type: application/json",
        "Body:",
        '{"message":"现在系统状态如何？","entrypoint":"agent","context":{"answer_chain_enabled":true,"params":{}}}',
    ]
    return {
        "agent_bootstrap_prompt": "\n".join(prompt_lines),
        "agent_bootstrap_token_ready": bool(token_value),
        "agent_bootstrap_token_name": token_name,
        "agent_bootstrap_access_level": access_level,
        "agent_bootstrap_access_level_label": access_level_label,
    }


def _source_summary(source_type: str) -> dict[str, Any]:
    capabilities = get_capability_repository().get_by_source_type(source_type)
    latest_sync = get_capability_sync_log_repository().get_latest(source_type)
    return {
        "source_type": source_type,
        "total": len(capabilities),
        "routing_enabled": sum(1 for item in capabilities if item.enabled_for_routing),
        "terminal_enabled": sum(1 for item in capabilities if item.enabled_for_terminal),
        "requires_confirmation": sum(1 for item in capabilities if item.requires_confirmation),
        "latest_sync_at": latest_sync.finished_at if latest_sync else None,
        "status": "ready" if capabilities else "empty",
    }


def toggle_mcp_tool_flag(*, capability_key: str, flag: str):
    """Toggle one MCP tool flag and persist the updated capability."""

    capability = GetCapabilityDetailUseCase(capability_repo=get_capability_repository()).execute(
        capability_key
    )
    if capability is None or capability.source_type.value != "mcp_tool":
        return None

    current = bool(getattr(capability, flag))
    updated = replace(capability, **{flag: not current})
    return get_capability_repository().save(updated)
