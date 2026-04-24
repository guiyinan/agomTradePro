"""
AI capability catalog page views.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.account.interface.views import is_admin_user

from ..application.interface_services import (
    get_mcp_tools_page_context,
    toggle_mcp_tool_flag,
)
from ..application.use_cases import SyncCapabilitiesUseCase


@login_required
@user_passes_test(is_admin_user)
@require_GET
def mcp_tools_page(request: HttpRequest) -> HttpResponse:
    search_query = (request.GET.get("q") or "").strip()
    module_filter = (request.GET.get("module") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()

    context = get_mcp_tools_page_context(
        search_query=search_query,
        module_filter=module_filter,
        status_filter=status_filter,
    )
    return render(request, "ops/mcp_tools.html", context)


@login_required
@user_passes_test(is_admin_user)
@require_POST
def sync_mcp_tools_view(request: HttpRequest) -> HttpResponse:
    result = SyncCapabilitiesUseCase().execute(sync_type="incremental", source="mcp_tool")
    messages.success(
        request,
        f"MCP 工具同步完成: discovered={result.total_discovered}, created={result.created_count}, updated={result.updated_count}, disabled={result.disabled_count}",
    )
    return redirect("/settings/mcp-tools/")


@login_required
@user_passes_test(is_admin_user)
@require_POST
def toggle_mcp_tool_flag_view(request: HttpRequest, capability_key: str, flag: str) -> HttpResponse:
    if flag not in {"enabled_for_terminal", "enabled_for_routing"}:
        messages.error(request, "不支持的切换字段")
        return redirect("/settings/mcp-tools/")

    tool = toggle_mcp_tool_flag(capability_key=capability_key, flag=flag)
    if tool is None:
        messages.error(request, "未找到对应的 MCP 工具")
        return redirect("/settings/mcp-tools/")

    messages.success(request, f"{tool.name} 的 {flag} 已切换为 {getattr(tool, flag)}")
    return redirect("/settings/mcp-tools/")
