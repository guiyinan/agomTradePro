"""
URL configuration for AgomSAAF project.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.http import HttpResponse, JsonResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

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
from apps.account.interface.backup_views import admin_db_backup_download_view

# 核心视图
from core.views import (
    index_view,
    health_view,
    readiness_view,
    chat_example_view,
    docs_view,
    asset_screen_view,
    decision_workspace_view,
    ops_center_view,
)
from core.api_views import ConfigCenterSnapshotView, ConfigCapabilitiesView
from core.admin_log_views import (
    server_logs_page,
    server_logs_stream,
    server_logs_export,
    automation_server_logs_stream,
    automation_server_logs_export,
)


# API 根路径视图
def api_root_view(request):
    """API 根路径 - 返回可用的 API 端点列表"""
    return JsonResponse({
        'endpoints': {
            'account': '/api/account/',
            'alpha': '/api/alpha/',
            'asset-analysis': '/api/asset-analysis/',
            'audit': '/api/audit/',
            'backtest': '/api/backtest/',
            'dashboard': '/api/dashboard/',
            'equity': '/api/equity/',
            'factor': '/api/factor/',
            'filter': '/api/filter/',
            'fund': '/api/fund/',
            'hedge': '/api/hedge/',
            'macro': '/api/macro/',
            'policy': '/api/policy/',
            'portfolio': '/api/portfolio/',
            'prompt': '/api/prompt/',
            'realtime': '/api/realtime/',
            'regime': '/api/regime/',
            'rotation': '/api/rotation/',
            'sector': '/api/sector/',
            'market-data': '/api/market-data/',
            'sentiment': '/api/sentiment/',
            'signal': '/api/signal/',
            'signals': '/api/signals/',
            'simulated-trading': '/api/simulated-trading/',
            'strategy': '/api/strategy/',
            'share': '/api/share/',
            'system': '/api/system/',
            'system-config-center': '/api/system/config-center/',
            'docs': '/api/docs/',
            'schema': '/api/schema/',
        }
    })


core_patterns = [
    path('', index_view, name='index'),
    path('api/', api_root_view, name='api-root'),
    path('api/health/', health_view, name='health'),
    path('api/ready/', readiness_view, name='readiness'),
    path('api/system/config-center/', ConfigCenterSnapshotView.as_view(), name='api-system-config-center'),
    path('api/system/config-capabilities/', ConfigCapabilitiesView.as_view(), name='api-system-config-capabilities'),
    path('chat-example/', chat_example_view, name='chat-example'),
    # 301 重定向旧页面到统一工作台
    path('policy/dashboard/', RedirectView.as_view(url='/policy/workbench/', permanent=True), name='policy-dashboard'),
    path('asset-analysis/screen/', asset_screen_view, name='asset-screen'),
    path('decision/workspace/', decision_workspace_view, name='decision-workspace'),
    path('ops/', ops_center_view, name='ops-center'),
    # More specific pattern must come first.
    path('docs/<str:doc_slug>/', docs_view, name='docs-detail'),
    path('docs/', docs_view, name='docs'),
    # 301 重定向 sentiment 旧页面
    path('sentiment/dashboard/', RedirectView.as_view(url='/policy/workbench/', permanent=True), name='sentiment-dashboard-redirect'),
    path('sentiment/analyze/', RedirectView.as_view(url='/policy/workbench/', permanent=True), name='sentiment-analyze-redirect'),

    # Legacy page-path compatibility aliases (prevent 404 from historical links/bookmarks)
    path('simulated_trading/my-accounts/', RedirectView.as_view(url='/simulated-trading/my-accounts/', permanent=False), name='simulated-trading-legacy-my-accounts'),
    path('ai/manage/', RedirectView.as_view(url='/ai/', permanent=False), name='ai-manage-legacy'),
    path('sector/dashboard/', RedirectView.as_view(url='/sector/', permanent=False), name='sector-dashboard-legacy'),
]

admin_docs_patterns = [
    path('admin/db-backup/<str:token>/', admin_db_backup_download_view, name='admin-db-backup-download'),
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
    path('backtest/', include(('apps.backtest.interface.urls', 'backtest'), namespace='backtest')),
    path('regime/', include('apps.regime.interface.urls')),
    path('macro/', include(('apps.macro.interface.urls', 'macro'), namespace='macro')),
    path('filter/', include(('apps.filter.interface.urls', 'filter'), namespace='filter')),
    path('signal/', include('apps.signal.interface.urls')),
    path('ai/', include(('apps.ai_provider.interface.urls', 'ai_provider'), namespace='ai_provider')),
    path('prompt/', include(('apps.prompt.interface.urls', 'prompt'), namespace='prompt')),
    path('audit/', include(('apps.audit.interface.urls', 'audit'), namespace='audit')),
    path('sector/', include(('apps.sector.interface.urls', 'sector'), namespace='sector')),
    path('equity/', include(('apps.equity.interface.urls', 'equity'), namespace='equity')),
    path('fund/', include(('apps.fund.interface.urls', 'fund'), namespace='fund')),
    path('asset-analysis/', include(('apps.asset_analysis.interface.urls', 'asset_analysis'), namespace='asset_analysis')),
    path('simulated-trading/', include(('apps.simulated_trading.interface.urls', 'simulated_trading'), namespace='simulated_trading')),
    path('strategy/', include(('apps.strategy.interface.urls', 'strategy'), namespace='strategy')),
    path('realtime/', include(('apps.realtime.interface.urls', 'realtime'), namespace='realtime')),
    # Policy management (包含页面和 API).
    path('policy/', include(('apps.policy.interface.urls', 'policy'), namespace='policy')),
    # Events module - 事件总线 API
    path('events/', include(('apps.events.interface.urls', 'events'), namespace='events')),
    # Decision workflow modules.
    path('', include('apps.decision_rhythm.interface.urls')),
    path('', include('apps.beta_gate.interface.urls')),
    path('', include('apps.alpha_trigger.interface.urls')),
    # Factor / Rotation / Hedge.
    path('factor/', include(('apps.factor.interface.urls', 'factor'), namespace='factor')),
    path('rotation/', include(('apps.rotation.interface.urls', 'rotation'), namespace='rotation')),
    path('hedge/', include(('apps.hedge.interface.urls', 'hedge'), namespace='hedge')),
    # Sentiment analysis.
    path('sentiment/', include(('apps.sentiment.interface.urls', 'sentiment'), namespace='sentiment')),
    # Alpha signal abstraction.
    path('api/alpha/', include('apps.alpha.interface.urls')),

    # ========== 统一 API 路由挂载（新规范） ==========
    # 这些路由提供 /api/{module}/ 模式的 API 端点
    # P0: Account 模块
    path('api/account/', include(('apps.account.interface.api_urls', 'account'), namespace='api_account')),
    # P1: Simulated Trading 模块
    path('api/simulated-trading/accounts/', RedirectView.as_view(url='/api/simulated-trading/api/accounts/', permanent=False), name='api-simulated-trading-accounts-legacy'),
    path('api/simulated-trading/', include(('apps.simulated_trading.interface.urls', 'simulated_trading'), namespace='api_simulated_trading')),
    # P1: Strategy 模块
    path('api/strategy/', include(('apps.strategy.interface.urls', 'strategy'), namespace='api_strategy')),
    # P2: Regime 模块
    path('api/regime/', include(('apps.regime.interface.api_urls', 'regime'), namespace='api_regime')),
    # P2: Policy 模块（仅挂载 API 路由，避免与页面路由冲突）
    path('api/policy/', include(('apps.policy.interface.api_urls', 'policy'), namespace='api_policy')),
    # P2: Signal 模块
    path('api/signal/', include(('apps.signal.interface.api_urls', 'signal'), namespace='api_signal')),
    # P2: Signal 模块（复数别名）
    path('api/signals/', include(('apps.signal.interface.api_urls', 'signal'), namespace='api_signals')),
    # P2: Macro 模块
    path('api/macro/', include(('apps.macro.interface.api_urls', 'macro'), namespace='api_macro')),
    # P2: Macro indicators 别名
    path('api/macro/indicators/', RedirectView.as_view(url='/api/macro/supported-indicators/', permanent=False), name='api-macro-indicators'),
    # P2: Filter 模块
    path('api/filter/', include(('apps.filter.interface.api_urls', 'api_filter'), namespace='api_filter')),
    # P2: Backtest 模块
    path('api/backtest/', include(('apps.backtest.interface.api_urls', 'api_backtest'), namespace='api_backtest')),
    # P2: Audit 模块
    path('api/audit/', include(('apps.audit.interface.api_urls', 'api_audit'), namespace='api_audit')),
    # P3: 其他模块
    path('api/equity/', include(('apps.equity.interface.api_urls', 'api_equity'), namespace='api_equity')),
    path('api/fund/', include(('apps.fund.interface.api_urls', 'api_fund'), namespace='api_fund')),
    path('api/asset-analysis/', include(('apps.asset_analysis.interface.urls', 'api_asset_analysis'), namespace='api_asset_analysis')),
    path('api/sector/', include(('apps.sector.interface.urls', 'api_sector'), namespace='api_sector')),
    path('api/ai/', include(('apps.ai_provider.interface.api_urls', 'api_ai_provider'), namespace='api_ai_provider')),
    path('api/prompt/', include(('apps.prompt.interface.api_urls', 'api_prompt'), namespace='api_prompt')),
    path('api/realtime/', include(('apps.realtime.interface.urls', 'api_realtime'), namespace='api_realtime')),
    path('api/factor/', include(('apps.factor.interface.api_urls', 'api_factor'), namespace='api_factor')),
    path('api/rotation/', include(('apps.rotation.interface.api_urls', 'api_rotation'), namespace='api_rotation')),
    path('api/hedge/', include(('apps.hedge.interface.api_urls', 'api_hedge'), namespace='api_hedge')),
    # Market Data 统一数据源接入层
    path('market-data/', include(('apps.market_data.interface.urls', 'market_data'), namespace='market_data')),
    path('api/market-data/', include(('apps.market_data.interface.api_urls', 'market_data'), namespace='api_market_data')),
    # Sentiment API routes (separate from page routes to avoid conflicts)
    path('api/sentiment/', include(('apps.sentiment.interface.api_urls', 'api_sentiment'), namespace='api_sentiment')),
    # Task Monitor
    path('api/system/', include(('apps.task_monitor.interface.urls', 'task_monitor'), namespace='task_monitor')),
    # Dashboard API routes
    path('api/dashboard/', include(('apps.dashboard.interface.api_urls', 'api_dashboard'), namespace='api_dashboard')),
    # Share API routes
    path('api/share/', include(('apps.share.interface.api_urls', 'share_api'), namespace='share_api')),
    # Share public routes
    path('', include(('apps.share.interface.urls', 'share'), namespace='share')),
    # Portfolio API routes (alias for simulated-trading accounts)
    path('api/portfolio/', RedirectView.as_view(url='/api/simulated-trading/api/accounts/', permanent=False), name='api-portfolio'),
]


urlpatterns = [
    *core_patterns,
    *admin_docs_patterns,
    *api_docs_patterns,
    *module_patterns,
]

# ========== Prometheus 指标端点 ==========
def metrics_view(request):
    """
    Prometheus 指标导出端点

    将所有指标以 Prometheus 文本格式导出，供 Prometheus 服务器抓取。

    访问方式: GET /metrics/

    返回格式:
        # HELP api_request_total Total API requests
        # TYPE api_request_total counter
        api_request_total{method="GET",endpoint="/api/regime/",status_code="200",view_name="RegimeViewSet"} 123.0
        ...
    """
    # 检查权限（可选：生产环境建议添加认证）
    # 可以通过 IP 白名单、Token 或 Basic Auth 保护

    response = HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)

    # 添加 CORS 头（如果需要跨域访问）
    response['Access-Control-Allow-Origin'] = '*'

    return response


# 将 metrics 端点添加到核心路由
urlpatterns += [
    path('metrics/', metrics_view, name='prometheus-metrics'),
]
