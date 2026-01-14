"""
Realtime Module - Interface Layer Views

This module provides API endpoints for the realtime price monitoring system.
Following AgomSaaS architecture rules:
- Interface layer handles input validation and output formatting
- No business logic, delegates to Application layer
"""

import logging
from typing import List

from django.http import JsonResponse
from django.views import View
from django.views.decorators.http import require_http_methods

from apps.realtime.application.price_polling_service import PricePollingUseCase


logger = logging.getLogger(__name__)


class RealtimePriceView(View):
    """实时价格 API 视图"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_case = PricePollingUseCase()

    def get(self, request, *args, **kwargs):
        """GET /api/realtime/prices/

        查询参数:
            - assets: 资产代码列表，逗号分隔（可选）
                    如果不提供，则返回所有监控资产的价格

        Returns:
            {
                "timestamp": "2024-01-13T10:30:00",
                "prices": [
                    {
                        "asset_code": "000001.SZ",
                        "price": 10.50,
                        "change": 0.10,
                        "change_pct": 0.96,
                        ...
                    }
                ],
                "total": 10,
                "success": 10,
                "failed": 0
            }
        """
        asset_codes_str = request.GET.get("assets")

        if asset_codes_str:
            # 获取指定资产的价格
            asset_codes = [code.strip() for code in asset_codes_str.split(",") if code.strip()]
            prices = self.use_case.get_latest_prices(asset_codes)

            return JsonResponse({
                "timestamp": self.use_case.service.price_repository.get_latest_price(asset_codes[0]).timestamp.isoformat() if prices else None,
                "prices": prices,
                "total": len(asset_codes),
                "success": len(prices),
                "failed": len(asset_codes) - len(prices)
            })
        else:
            # 触发价格轮询
            snapshot = self.use_case.execute_price_polling()
            return JsonResponse(snapshot)

    def post(self, request, *args, **kwargs):
        """POST /api/realtime/prices/

        手动触发价格轮询

        Returns:
            价格快照
        """
        snapshot = self.use_case.execute_price_polling()
        return JsonResponse(snapshot)


class SingleAssetPriceView(View):
    """单个资产价格 API 视图"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_case = PricePollingUseCase()

    def get(self, request, asset_code, *args, **kwargs):
        """GET /api/realtime/prices/{asset_code}/

        获取单个资产的最新价格

        Args:
            asset_code: 资产代码

        Returns:
            {
                "asset_code": "000001.SZ",
                "price": 10.50,
                "change": 0.10,
                "change_pct": 0.96,
                ...
            }
        """
        prices = self.use_case.get_latest_prices([asset_code])

        if not prices:
            return JsonResponse({
                "error": f"Price not found for asset: {asset_code}"
            }, status=404)

        return JsonResponse(prices[0])


class PricePollingTriggerView(View):
    """价格轮询触发视图

    用于手动触发价格更新或定时任务调用
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_case = PricePollingUseCase()

    def post(self, request, *args, **kwargs):
        """POST /api/realtime/poll/

        触发价格轮询

        Returns:
            价格快照
        """
        logger.info("Manual price polling triggered")
        snapshot = self.use_case.execute_price_polling()
        return JsonResponse(snapshot)


class HealthCheckView(View):
    """健康检查视图

    检查实时价格服务是否正常
    """

    def get(self, request, *args, **kwargs):
        """GET /api/realtime/health/

        Returns:
            {
                "status": "healthy",
                "data_provider_available": true,
                "last_poll_time": "2024-01-13T10:30:00"
            }
        """
        from apps.realtime.infrastructure.repositories import CompositePriceDataProvider

        # 检查数据源是否可用
        use_case = PricePollingUseCase()
        is_available = use_case.price_provider.is_available()

        return JsonResponse({
            "status": "healthy" if is_available else "unhealthy",
            "data_provider_available": is_available,
            "timestamp": use_case.service.config.to_dict()
        })
