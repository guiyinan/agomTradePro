"""
URL Configuration for Strategy System

Interface层:
- 配置REST API路由
- 使用DRF Router组织URL
- 配置前端页面路由
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

# Application namespace for URL reversing
app_name = 'strategy'

from apps.strategy.interface.views import (
    StrategyViewSet,
    RuleConditionViewSet,
    ScriptConfigViewSet,
    AIStrategyConfigViewSet,
    PortfolioStrategyAssignmentViewSet,
    StrategyExecutionLogViewSet,
    strategy_list,
    strategy_create,
    strategy_detail,
    strategy_edit,
    strategy_toggle_status,
    strategy_execute,
    bind_strategy,
    unbind_strategy,
    test_script,
    test_strategy,
)

# 创建路由器
router = DefaultRouter()

# 注册 ViewSet
router.register(r'strategies', StrategyViewSet, basename='strategy')
router.register(r'rules', RuleConditionViewSet, basename='rulecondition')
router.register(r'script-configs', ScriptConfigViewSet, basename='scriptconfig')
router.register(r'ai-configs', AIStrategyConfigViewSet, basename='aistrategyconfig')
router.register(r'assignments', PortfolioStrategyAssignmentViewSet, basename='portfoliostrategyassignment')
router.register(r'execution-logs', StrategyExecutionLogViewSet, basename='strategyexecutionlog')

# URL 模式
urlpatterns = [
    # 前端页面路由
    path('', strategy_list, name='list'),
    path('create/', strategy_create, name='create'),
    path('<int:strategy_id>/', strategy_detail, name='detail'),
    path('<int:strategy_id>/edit/', strategy_edit, name='edit'),
    path('<int:strategy_id>/toggle-status/', strategy_toggle_status, name='toggle-status'),
    path('<int:strategy_id>/execute/', strategy_execute, name='execute'),
    path('<int:strategy_id>/test/', test_strategy, name='test-strategy'),

    # API 路由
    path('api/', include(router.urls)),
    path('api/test-script/', test_script, name='test-script'),
    path('api/bind-strategy/', bind_strategy, name='bind-strategy'),
    path('api/unbind-strategy/', unbind_strategy, name='unbind-strategy'),
]
