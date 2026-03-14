"""URL Configuration for Strategy System."""
from django.urls import path, include

app_name = 'strategy'

from apps.strategy.interface.views import (
    strategy_list,
    strategy_create,
    strategy_detail,
    strategy_edit,
    strategy_toggle_status,
    strategy_execute,
    test_strategy,
)

urlpatterns = [
    # 前端页面路由
    path('', strategy_list, name='list'),
    path('create/', strategy_create, name='create'),
    path('<int:strategy_id>/', strategy_detail, name='detail'),
    path('<int:strategy_id>/edit/', strategy_edit, name='edit'),
    path('<int:strategy_id>/toggle-status/', strategy_toggle_status, name='toggle-status'),
    path('<int:strategy_id>/execute/', strategy_execute, name='execute'),
    path('<int:strategy_id>/test/', test_strategy, name='test-strategy'),
    # Legacy API compatibility under /strategy/api/*
    path('api/', include(('apps.strategy.interface.api_urls', 'strategy_api'), namespace='legacy_strategy_api')),
]
