"""
Terminal Interface Views.

页面视图定义。
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from apps.terminal.application.interface_services import get_terminal_config_page_context


def _staff_required(view_func):
    """Decorator: login_required + staff/superuser check."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            return HttpResponseForbidden("Staff access required.")
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    wrapper.__doc__ = view_func.__doc__
    return wrapper


@method_decorator(login_required, name='dispatch')
class TerminalView(View):
    """
    终端页面视图

    GET /terminal/
    """

    def get(self, request):
        context = {
            'page_title': 'Terminal',
            'page_description': 'AI CLI Interface',
        }
        return render(request, 'terminal/index.html', context)


@method_decorator(_staff_required, name='dispatch')
class TerminalConfigView(View):
    """
    终端命令配置页面视图（仅 staff/admin）

    GET /terminal/config/
    """

    def get(self, request):
        return render(request, 'terminal/config.html', get_terminal_config_page_context())


# 函数式视图兼容
@login_required
def terminal_view(request):
    """终端页面视图（函数式）"""
    return TerminalView.as_view()(request)


@_staff_required
def terminal_config_view(request):
    """终端配置页面视图（函数式，仅 staff/admin）"""
    return TerminalConfigView.as_view()(request)
