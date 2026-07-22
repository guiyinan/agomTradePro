"""Classic Web pages for user-facing live execution tasks."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.broker_execution.application.authorization import action_permissions
from apps.broker_execution.application.query_services import BrokerExecutionQueryService
from apps.broker_execution.application.use_case_errors import BrokerExecutionError

_PAGE_COPY = {
    "overview": ("实盘执行中心", "先确认连接、停止开关、待审批订单和对账差异。"),
    "orders": ("实盘订单", "复核订单证据，并通过预览后批准、拒绝或撤单。"),
    "order_detail": ("订单详情", "查看审批摘要、风险快照、成交与完整状态时间线。"),
    "reconciliation": ("实盘对账", "核对委托、成交、资金和持仓差异。"),
    "connection": ("本地连接", "查看 Windows Agent、QMT 和绑定账户的最近健康状态。"),
    "settings": ("执行设置", "管理账户额度、标的白名单和自动执行门禁。"),
    "audit": ("实盘审计", "追踪批准、撤单、启停、凭证和差异处置。"),
}

_PAGE_NEXT_ACTIONS = {
    "overview": ["查看待确认订单", "检查本地连接", "查看对账差异"],
    "orders": ["复核订单证据", "预览批准或拒绝", "跟踪执行状态"],
    "order_detail": ["核对审批摘要", "查看券商事件", "预览可用操作"],
    "reconciliation": ["检查四维差异", "预览差异处置", "保留处置证据"],
    "connection": ["检查 Agent/QMT 状态", "测试连接或立即同步", "管理凭证"],
    "settings": ["检查账户授权", "预览执行设置", "确认受控变更"],
    "audit": ["筛选审计事件", "核对请求标识", "导出审计记录"],
}


def _page_view_model(
    *,
    page_key: str,
    title: str,
    subtitle: str,
    data: dict[str, Any],
    error: str,
    permissions: dict[str, bool],
) -> dict[str, Any]:
    """Build the stable Classic Web presentation envelope."""

    status = "ERROR" if error else "OK"
    if page_key == "overview" and not error:
        status = str(data.get("today_readiness") or "OFFLINE")
    return {
        "status": status,
        "summary": {"title": title, "subtitle": subtitle},
        "data": data,
        "warnings": [error] if error else [],
        "next_actions": list(_PAGE_NEXT_ACTIONS[page_key]),
        "permissions": dict(permissions),
    }


def _render_page(
    request: HttpRequest,
    *,
    page_key: str,
    client_order_id: str | None = None,
) -> HttpResponse:
    service = BrokerExecutionQueryService()
    data: dict[str, Any] = {}
    error = ""
    permissions = action_permissions(request.user)
    try:
        if page_key == "overview":
            data = service.overview(actor=request.user)
        elif page_key == "orders":
            data = service.orders(actor=request.user)
        elif page_key == "order_detail" and client_order_id:
            data = service.order_detail(actor=request.user, client_order_id=client_order_id)
        elif page_key == "connection":
            data = service.connections(actor=request.user)
        elif page_key == "settings":
            data = service.connections(actor=request.user)
            if permissions["manage_access"]:
                data.update(service.account_access_grants(actor=request.user))
        elif page_key == "reconciliation":
            data = service.reconciliations(actor=request.user)
        elif page_key == "audit":
            data = service.audits(actor=request.user)
    except BrokerExecutionError as exc:
        error = str(exc)
    title, subtitle = _PAGE_COPY[page_key]
    page_view_model = _page_view_model(
        page_key=page_key,
        title=title,
        subtitle=subtitle,
        data=data,
        error=error,
        permissions=permissions,
    )
    return render(
        request,
        "broker_execution/workbench.html",
        {
            "page_key": page_key,
            "page_title": title,
            "page_subtitle": subtitle,
            "page_data": data,
            "page_view_model": page_view_model,
            "page_error": error,
            "permissions": permissions,
        },
    )


@login_required
def overview_view(request: HttpRequest) -> HttpResponse:
    return _render_page(request, page_key="overview")


@login_required
def orders_view(request: HttpRequest) -> HttpResponse:
    return _render_page(request, page_key="orders")


@login_required
def order_detail_view(request: HttpRequest, client_order_id: str) -> HttpResponse:
    return _render_page(
        request, page_key="order_detail", client_order_id=client_order_id
    )


@login_required
def reconciliation_view(request: HttpRequest) -> HttpResponse:
    return _render_page(request, page_key="reconciliation")


@login_required
def connection_view(request: HttpRequest) -> HttpResponse:
    return _render_page(request, page_key="connection")


@login_required
def settings_view(request: HttpRequest) -> HttpResponse:
    return _render_page(request, page_key="settings")


@login_required
def audit_view(request: HttpRequest) -> HttpResponse:
    return _render_page(request, page_key="audit")
