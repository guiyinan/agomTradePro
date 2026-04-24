"""Application-facing helpers for AI capability interface views."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

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

    use_case = GetCapabilityListUseCase(capability_repo=get_capability_repository())
    tools = use_case.execute(source_type="mcp_tool", enabled_only=False)

    if search_query:
        normalized_query = search_query.lower()
        tools = [
            item
            for item in tools
            if normalized_query in item.capability_key.lower()
            or normalized_query in item.name.lower()
            or normalized_query in item.summary.lower()
            or normalized_query in item.description.lower()
        ]

    if module_filter:
        tools = [item for item in tools if _derive_module_name(item.name) == module_filter]

    if status_filter == "routing_on":
        tools = [item for item in tools if item.enabled_for_routing]
    elif status_filter == "routing_off":
        tools = [item for item in tools if not item.enabled_for_routing]
    elif status_filter == "terminal_on":
        tools = [item for item in tools if item.enabled_for_terminal]
    elif status_filter == "terminal_off":
        tools = [item for item in tools if not item.enabled_for_terminal]

    module_choices = sorted({_derive_module_name(item.name) for item in use_case.execute(source_type="mcp_tool", enabled_only=False)})
    latest_sync = get_capability_sync_log_repository().get_latest("mcp_tool")

    return {
        "page_title": "MCP 工具管理",
        "page_subtitle": "管理已同步到 AI Capability Catalog 的 MCP 工具，支持检索、查看 Schema、切换终端/路由启用状态以及重新同步。",
        "tools": tools[:300],
        "total_count": len(tools),
        "module_choices": module_choices,
        "search_query": search_query,
        "module_filter": module_filter,
        "status_filter": status_filter,
        "latest_sync": latest_sync,
    }


def toggle_mcp_tool_flag(*, capability_key: str, flag: str):
    """Toggle one MCP tool flag and persist the updated capability."""

    capability = GetCapabilityDetailUseCase(
        capability_repo=get_capability_repository()
    ).execute(capability_key)
    if capability is None or capability.source_type.value != "mcp_tool":
        return None

    current = bool(getattr(capability, flag))
    updated = replace(capability, **{flag: not current})
    return get_capability_repository().save(updated)
