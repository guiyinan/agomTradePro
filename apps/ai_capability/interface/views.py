"""
AI capability catalog page views.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.account.interface.views import is_admin_user

from ..application.governance_services import CapabilityCatalogGovernanceService
from ..application.interface_services import (
    build_capability_gateway_agent_prompt,
    get_capability_gateway_page_context,
    get_mcp_tools_page_context,
    toggle_mcp_tool_flag,
)
from ..application.repository_provider import get_capability_repository
from ..application.semantic_governance import SemanticGovernanceService
from ..application.use_cases import SyncCapabilitiesUseCase
from .semantic_governance_serializers import (
    serialize_audit_entries,
    serialize_governance_snapshot,
)


@login_required
@require_GET
def capability_gateway_page(request: HttpRequest) -> HttpResponse:
    user_id = request.user.pk
    if user_id is None:
        return HttpResponse("authenticated_user_required", status=403)
    base_url = request.build_absolute_uri("/").rstrip("/")
    context = get_capability_gateway_page_context(
        user_id=user_id,
        base_url=base_url,
    )
    if request.user.is_staff:
        semantic_service = SemanticGovernanceService(get_capability_repository())
        context["semantic_governance"] = {
            **serialize_governance_snapshot(semantic_service.inspect()),
            "audit": serialize_audit_entries(semantic_service.list_audit(limit=50)),
            "preview_url": reverse("api_ai_capabilities:semantic-governance-preview"),
            "apply_url": reverse("api_ai_capabilities:semantic-governance-apply"),
        }
    new_token_payload = request.session.pop("self_new_token_payload", None)
    context["new_token_payload"] = new_token_payload
    if new_token_payload:
        context.update(
            build_capability_gateway_agent_prompt(
                base_url=base_url,
                route_endpoint=context["route_endpoint"],
                web_endpoint=context["web_endpoint"],
                capability_endpoint=context["capability_endpoint"],
                preferred_token=context.get("preferred_token"),
                default_account_id=context.get("default_account_id"),
                token_payload=new_token_payload,
            )
        )
    return render(request, "ops/capability_gateway.html", context)


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
    governance_result = CapabilityCatalogGovernanceService().execute(apply=True)
    messages.success(
        request,
        (
            "MCP 工具同步完成: "
            f"discovered={result.total_discovered}, created={result.created_count}, "
            f"updated={result.updated_count}, disabled={result.disabled_count}, "
            f"governance_changes={governance_result.changed_count}, "
            f"manual_pending={governance_result.pending_count}"
        ),
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
