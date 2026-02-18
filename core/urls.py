"""
URL configuration for AgomSAAF project.
"""
from django.contrib import admin
from django.urls import path, include

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
    asset_screen_view,
    decision_workspace_view,
    ops_center_view,
)
from core.admin_log_views import (
    server_logs_page,
    server_logs_stream,
    server_logs_export,
    automation_server_logs_stream,
    automation_server_logs_export,
)

core_patterns = [
    path('', index_view, name='index'),
    path('health/', health_view, name='health'),
    path('chat-example/', chat_example_view, name='chat-example'),
    path('policy/dashboard/', policy_dashboard_view, name='policy-dashboard'),
    path('asset-analysis/screen/', asset_screen_view, name='asset-screen'),
    path('decision/workspace/', decision_workspace_view, name='decision-workspace'),
    path('ops/', ops_center_view, name='ops-center'),
    # More specific pattern must come first.
    path('docs/<str:doc_slug>/', docs_view, name='docs-detail'),
    path('docs/', docs_view, name='docs'),
]

admin_docs_patterns = [
    path('admin/server-logs/', server_logs_page, name='admin-server-logs'),
    path('admin/server-logs/stream/', server_logs_stream, name='admin-server-logs-stream'),
    path('admin/server-logs/export/', server_logs_export, name='admin-server-logs-export'),
    path('admin/docs/manage/', docs_manage, name='admin-docs-manage'),
    path('admin/docs/edit/', doc_edit, name='admin-docs-create'),
    path('admin/docs/edit/<int:doc_id>/', doc_edit, name='admin-docs-edit'),
    path('admin/docs/delete/<int:doc_id>/', doc_delete, name='admin-docs-delete'),
    path('admin/docs/export/<int:doc_id>/md/', doc_export_markdown, name='admin-docs-export-md'),
    path('admin/docs/export/', doc_export_all, name='admin-docs-export'),
    path('admin/docs/import/', doc_import, name='admin-docs-import'),
]

api_docs_patterns = [
    path('admin/', admin.site.urls),
    path('api/debug/server-logs/stream/', automation_server_logs_stream, name='api-debug-server-logs-stream'),
    path('api/debug/server-logs/export/', automation_server_logs_export, name='api-debug-server-logs-export'),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

module_patterns = [
    # Account & Auth.
    path('account/', include(('apps.account.interface.urls', 'account'), namespace='account')),
    # Dashboard (requires login).
    path('dashboard/', include('apps.dashboard.interface.urls')),
    # Main module routes.
    path('backtest/', include('apps.backtest.interface.urls')),
    path('regime/', include('apps.regime.interface.urls')),
    path('macro/', include(('apps.macro.interface.urls', 'macro'), namespace='macro')),
    path('filter/', include('apps.filter.interface.urls')),
    path('signal/', include('apps.signal.interface.urls')),
    path('ai/', include('apps.ai_provider.interface.urls')),
    path('prompt/', include('apps.prompt.interface.urls')),
    path('audit/', include('apps.audit.interface.urls')),
    path('sector/', include('apps.sector.interface.urls')),
    path('equity/', include('apps.equity.interface.urls')),
    path('fund/', include('apps.fund.interface.urls')),
    path('asset-analysis/', include('apps.asset_analysis.interface.urls')),
    path('simulated-trading/', include('apps.simulated_trading.interface.urls')),
    path('strategy/', include('apps.strategy.interface.urls')),
    path('realtime/', include('apps.realtime.interface.urls')),
    # Policy management (包含页面和 API).
    path('policy/', include('apps.policy.interface.urls')),
    # Decision workflow modules.
    path('', include('apps.decision_rhythm.interface.urls')),
    path('', include('apps.beta_gate.interface.urls')),
    path('', include('apps.alpha_trigger.interface.urls')),
    # Factor / Rotation / Hedge.
    path('factor/', include('apps.factor.interface.urls')),
    path('rotation/', include('apps.rotation.interface.urls')),
    path('hedge/', include('apps.hedge.interface.urls')),
    # Alpha signal abstraction.
    path('api/alpha/', include('apps.alpha.interface.urls')),
]


urlpatterns = [
    *core_patterns,
    *admin_docs_patterns,
    *api_docs_patterns,
    *module_patterns,
]
