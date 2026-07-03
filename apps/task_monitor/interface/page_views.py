from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.task_monitor.application.interface_services import (
    bootstrap_scheduler_defaults,
    configure_readiness_schedule,
    get_scheduler_console_context,
)


def _ensure_task_monitor_access(request: HttpRequest) -> None:
    user = request.user
    if not user.is_authenticated:
        raise PermissionDenied
    if user.is_staff or user.is_superuser:
        return
    raise PermissionDenied


@require_http_methods(["GET", "POST"])
def scheduler_console_view(request: HttpRequest) -> HttpResponse:
    _ensure_task_monitor_access(request)

    if request.method == "POST":
        action_name = (request.POST.get("action") or "").strip()
        if action_name == "bootstrap_defaults":
            try:
                result = bootstrap_scheduler_defaults()
                messages.success(
                    request,
                    "默认计划任务已初始化: "
                    + ", ".join(result["executed_commands"]),
                )
            except Exception as exc:
                messages.error(request, f"初始化默认计划任务失败: {exc}")
            return redirect(reverse("task_monitor_pages:scheduler_console"))

        if action_name == "configure_readiness_schedule":
            try:
                result = configure_readiness_schedule(
                    quote_pre_refresh_time=(
                        request.POST.get("quote_pre_refresh_time") or ""
                    ),
                    daily_evidence_time=(
                        request.POST.get("daily_evidence_time") or ""
                    ),
                    weekly_auto_advisor_time=(
                        request.POST.get("weekly_auto_advisor_time") or ""
                    ),
                )
                messages.success(
                    request,
                    "Readiness 时间已保存: "
                    f"行情预刷新 {result['quote_pre_refresh_time']}, "
                    f"每日证据 {result['daily_evidence_time']}, "
                    f"周报自动顾问 {result['weekly_auto_advisor_time']}",
                )
            except Exception as exc:
                messages.error(request, f"保存 readiness 时间失败: {exc}")
            return redirect(reverse("task_monitor_pages:scheduler_console"))

        messages.error(request, "不支持的操作。")
        return redirect(reverse("task_monitor_pages:scheduler_console"))

    limit = max(1, min(int(request.GET.get("limit", 100) or 100), 200))
    context = get_scheduler_console_context(limit=limit)
    return render(request, "task_monitor/scheduler_console.html", context)
