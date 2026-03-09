"""
Market Data 模块 - API 路由

路由规范：API 路由放在 api_urls.py。
"""

from django.urls import path

from apps.market_data.interface import views

app_name = "market_data"

urlpatterns = [
    # 实时行情
    path(
        "quotes/",
        views.get_realtime_quotes,
        name="realtime-quotes",
    ),
    # 资金流向
    path(
        "capital-flows/",
        views.get_capital_flows,
        name="capital-flows",
    ),
    path(
        "capital-flows/sync/",
        views.sync_capital_flow,
        name="sync-capital-flow",
    ),
    # 股票新闻
    path(
        "news/",
        views.get_stock_news,
        name="stock-news",
    ),
    path(
        "news/ingest/",
        views.ingest_stock_news,
        name="ingest-stock-news",
    ),
    # Provider 健康检查
    path(
        "providers/health/",
        views.provider_health,
        name="provider-health",
    ),
    # 交叉校验
    path(
        "cross-validate/",
        views.cross_validate,
        name="cross-validate",
    ),
]
