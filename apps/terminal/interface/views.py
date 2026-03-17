"""
Terminal Interface Views.

页面视图定义。
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View


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


@method_decorator(login_required, name='dispatch')
class TerminalConfigView(View):
    """
    终端命令配置页面视图
    
    GET /terminal/config/
    """
    
    def get(self, request):
        from ..infrastructure.models import TerminalCommandORM
        
        commands = TerminalCommandORM._default_manager.all().order_by('category', 'name')
        
        # 按分类分组
        categories = {}
        for cmd in commands:
            if cmd.category not in categories:
                categories[cmd.category] = []
            categories[cmd.category].append(cmd)
        
        context = {
            'page_title': 'Terminal Command Config',
            'page_description': 'Configure terminal commands',
            'commands': commands,
            'categories': categories,
        }
        return render(request, 'terminal/config.html', context)


# 函数式视图兼容
@login_required
def terminal_view(request):
    """终端页面视图（函数式）"""
    return TerminalView.as_view()(request)


@login_required
def terminal_config_view(request):
    """终端配置页面视图（函数式）"""
    return TerminalConfigView.as_view()(request)
