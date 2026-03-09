"""
Market Data 模块 - 页面路由

页面路由放在 urls.py，API 路由放在 api_urls.py。
"""

from django.urls import path

from apps.market_data.interface.page_views import providers_page

app_name = "market_data"

urlpatterns = [
    path("providers/", providers_page, name="providers"),
]
