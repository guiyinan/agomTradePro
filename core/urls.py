"""
URL configuration for AgomSAAF project.
"""
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render

# Apply custom admin branding
import core.admin as agom_admin_config
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

# 文档管理后台视图
from apps.account.infrastructure.views import (
    docs_manage,
    doc_edit,
    doc_delete,
    doc_export_markdown,
    doc_export_all,
    doc_import,
)

# 核心视图
from core.views import (
    index_view,
    health_view,
    chat_example_view,
    docs_view,
    policy_dashboard_view,
)


def index_view_wrapper(request):
    """首页视图包装器"""
    if not request.user.is_authenticated:
        return index_view(request)
    return index_view(request)


urlpatterns = [
    path('', index_view, name='index'),
    path('health/', health_view, name='health'),
    path('chat-example/', chat_example_view, name='chat-example'),
    # Policy Dashboard
    path('policy/dashboard/', policy_dashboard_view, name='policy-dashboard'),
    # More specific pattern must come first
    path('docs/<str:doc_slug>/', docs_view, name='docs-detail'),
    path('docs/', docs_view, name='docs'),
    # 文档管理后台
    path('admin/docs/manage/', docs_manage, name='admin-docs-manage'),
    path('admin/docs/edit/', doc_edit, name='admin-docs-create'),
    path('admin/docs/edit/<int:doc_id>/', doc_edit, name='admin-docs-edit'),
    path('admin/docs/delete/<int:doc_id>/', doc_delete, name='admin-docs-delete'),
    path('admin/docs/export/<int:doc_id>/md/', doc_export_markdown, name='admin-docs-export-md'),
    path('admin/docs/export/', doc_export_all, name='admin-docs-export'),
    path('admin/docs/import/', doc_import, name='admin-docs-import'),
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Account & Auth
    path('account/', include('apps.account.interface.urls')),

    # Dashboard (requires login)
    path('dashboard/', include('apps.dashboard.interface.urls')),

    # Page routes
    path('backtest/', include('apps.backtest.interface.urls')),
    path('regime/', include('apps.regime.interface.urls')),
    path('macro/', include('apps.macro.interface.urls')),
    path('filter/', include('apps.filter.interface.urls')),
    path('signal/', include('apps.signal.interface.urls')),
    path('ai/', include('apps.ai_provider.interface.urls')),
    path('prompt/', include('apps.prompt.interface.urls')),
    path('audit/', include('apps.audit.interface.urls')),
    path('sector/', include('apps.sector.interface.urls')),
    path('equity/', include('apps.equity.interface.urls')),
    path('fund/', include('apps.fund.interface.urls')),
    path('asset-analysis/', include('apps.asset_analysis.interface.urls')),

    # Policy Management (包含页面和API)
    path('policy/', include('apps.policy.interface.urls')),
]
