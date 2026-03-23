"""URL Configuration for AI Provider Management."""

from django.urls import include, path

from . import views

app_name = 'ai_provider'

urlpatterns = [
    # 管理页面
    path('', views.page_views.ai_manage_view, name='manage'),
    path('logs/', views.page_views.ai_usage_logs_view, name='logs'),
    path('detail/<int:provider_id>/', views.page_views.ai_provider_detail_view, name='detail'),
    path('detail/<int:provider_id>/edit/', views.page_views.ai_provider_edit_view, name='edit'),
]

# Legacy API compatibility under /ai/api/*
urlpatterns += [
    path('api/', include(('apps.ai_provider.interface.api_urls', 'ai_provider_api'), namespace='legacy_ai_provider_api')),
]
