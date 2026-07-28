"""
Terminal Interface Views.

页面视图定义。
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponseForbidden
from django.http.response import HttpResponseBase
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from apps.terminal.application.interface_services import (
    get_terminal_page_context,
)
from core.ui_modes import UI_MODE_TUI, set_ui_mode_cookie


def _staff_required(
    view_func: Callable[..., HttpResponseBase],
) -> Callable[..., HttpResponseBase]:
    """Decorator: login_required + staff/superuser check."""

    @wraps(view_func)
    @login_required
    def wrapper(
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponseBase:
        if not (request.user.is_staff or request.user.is_superuser):
            return HttpResponseForbidden("Staff access required.")
        return view_func(request, *args, **kwargs)

    return wrapper


@method_decorator(login_required, name="dispatch")
class TerminalView(View):
    """
    终端页面视图

    GET /terminal/
    """

    def get(self, request: HttpRequest) -> HttpResponseBase:
        return render(request, "terminal/index.html", get_terminal_page_context())


@method_decorator(_staff_required, name="dispatch")
class TerminalConfigView(View):
    """
    终端命令配置页面视图（仅 staff/admin）

    GET /terminal/config/
    """

    def get(self, request: HttpRequest) -> HttpResponseBase:
        return redirect(
            "/tui/?screen=ai-ops.terminal&action=terminal.agent_chat",
        )


@method_decorator(login_required, name="dispatch")
class TuiWorkbenchView(View):
    """
    Standalone TUI workbench page.

    GET /tui/
    """

    def get(self, request: HttpRequest) -> HttpResponseBase:
        context = {
            "page_title": "TUI Workbench",
            "page_description": "API-native PC tools interface",
        }
        response = render(request, "terminal/tui_workbench.html", context)
        return set_ui_mode_cookie(response, mode=UI_MODE_TUI)


# 函数式视图兼容
@login_required
def terminal_view(request: HttpRequest) -> HttpResponseBase:
    """终端页面视图（函数式）"""
    return TerminalView.as_view()(request)


@_staff_required
def terminal_config_view(request: HttpRequest) -> HttpResponseBase:
    """终端配置页面视图（函数式，仅 staff/admin）"""
    return TerminalConfigView.as_view()(request)


@login_required
def tui_workbench_view(request: HttpRequest) -> HttpResponseBase:
    """Standalone TUI workbench page."""
    return TuiWorkbenchView.as_view()(request)
