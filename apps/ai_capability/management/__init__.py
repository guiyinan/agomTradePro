"""
AI capability catalog page views.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.account.interface.views import is_admin_user

from ..application.use_cases import SyncCapabilitiesUseCase
from ..infrastructure.models import CapabilityCatalogModel, CapabilitySyncLogModel


def _derive_module_name(tool_name: str) -> str:
    parts = (tool_name or "").split("_")
    return parts[0] if parts else "misc"


@login_required
@user_passes_test(is_admin_user)
@require_GET
def mcp_tools_page(request: HttpRequest) -> HttpResponse:
    search_query = (request.GET.get("q") or "").strip()
    module_filter = (request.GET.get("module") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()

    queryset = CapabilityCatalogModel.objects.filter(source_type="mcp_tool").order_by("capability_key")

    if search_query:
        queryset = queryset.filter(
            Q(capability_key__icontains=search_query)
            | Q(name__icontains=search_query)
            | Q(summary__icontains=search_query)
            | Q(description__icontains=search_query)
        )

    if module_filter:
        queryset = [obj for obj in queryset if _derive_module_name(obj.name) == module_filter]
    else:
        queryset = list(queryset)

    if status_filter == "routing_on":
        queryset = [obj for obj in queryset if obj.enabled_for_routing]
    elif status_filter == "routing_off":
        queryset = [obj for obj in queryset if not obj.enabled_for_routing]
    elif status_filter == "terminal_on":
        queryset = [obj for obj in queryset if obj.enabled_for_terminal]
    elif status_filter == "terminal_off":
        queryset = [obj for obj in queryset if not obj.enabled_for_terminal]

    module_choices = sorted({_derive_module_name(obj.name) for obj in CapabilityCatalogModel.objects.filter(source_type="mcp_tool")})
    latest_sync = CapabilitySyncLogModel.objects.filter(sync_type="mcp_tool").order_by("-started_at").first()

    context = {
        "page_title": "MCP 工具管理",
        "page_subtitle": "管理已同步到 AI Capability Catalog 的 MCP 工具，支持检索、查看 Schema、切换终端/路由启用状态以及重新同步。",
        "tools": queryset[:300],
        "total_count": len(queryset),
        "module_choices": module_choices,
        "search_query": search_query,
        "module_filter": module_filter,
        "status_filter": status_filter,
        "latest_sync": latest_sync,
    }
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
    return redirect("/ops/mcp-tools/")


@login_required
@user_passes_test(is_admin_user)
@require_POST
def toggle_mcp_tool_flag_view(request: HttpRequest, capability_key: str, flag: str) -> HttpResponse:
    if flag not in {"enabled_for_terminal", "enabled_for_routing"}:
        messages.error(request, "不支持的切换字段")
        return redirect("/ops/mcp-tools/")

    tool = get_object_or_404(CapabilityCatalogModel, capability_key=capability_key, source_type="mcp_tool")
    current = bool(getattr(tool, flag))
    setattr(tool, flag, not current)
    tool.save(update_fields=[flag, "updated_at"])
    messages.success(request, f"{tool.name} 的 {flag} 已切换为 {getattr(tool, flag)}")
    return redirect("/ops/mcp-tools/")
