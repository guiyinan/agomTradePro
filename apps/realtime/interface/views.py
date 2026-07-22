"""
Realtime Module - Interface Layer Views

This module provides API endpoints for the realtime price monitoring system.
Following AgomSaaS architecture rules:
- Interface layer handles input validation and output formatting
- No business logic, delegates to Application layer
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

from django.http import HttpRequest, JsonResponse
from django.views import View
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.realtime.application.price_polling_service import PricePollingUseCase
from apps.realtime.application.query_services import (
    list_cached_top_movers_payloads,
)
from apps.realtime.application.repository_provider import (
    get_realtime_alert_service,
    get_realtime_subscription_service,
)
from apps.realtime.application.use_cases import SubscriptionLimitExceeded
from apps.realtime.interface.authentication import RealtimeTokenAuthentication
from apps.realtime.interface.serializers import (
    PriceAlertCreateSerializer,
    PriceAlertResponseSerializer,
    PriceAlertUpdateSerializer,
    PriceSubscriptionCommandSerializer,
    PriceSubscriptionResponseSerializer,
    SectorPerformanceQuerySerializer,
    TopMoversQuerySerializer,
)
from core.integration.realtime_sector_performance import (
    list_realtime_sector_performance_payloads,
)

logger = logging.getLogger(__name__)


def _authenticated_owner_id(request: Request) -> int:
    """Return the persisted integer owner ID for an authenticated request."""

    owner_id = request.user.pk
    if owner_id is None:
        raise NotAuthenticated("Authenticated user must be persisted.")
    return int(owner_id)


class RealtimeAuthenticatedAPIView(APIView):
    """Use formal token and session identities for realtime owner APIs."""

    authentication_classes = [RealtimeTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]


class RealtimeApiRootView(RealtimeAuthenticatedAPIView):
    """Return the discoverable realtime API surface."""

    def get(self, request: Request) -> Response:
        """List stable realtime endpoints."""

        return Response(
            {
                "endpoints": {
                    "alerts": "/api/realtime/alerts/",
                    "subscriptions": "/api/realtime/subscriptions/",
                    "prices": "/api/realtime/prices/",
                    "sector-performance": "/api/realtime/sector-performance/",
                    "top-movers": "/api/realtime/top-movers/",
                    "market-summary": "/api/realtime/market-summary/",
                    "poll": "/api/realtime/poll/",
                    "health": "/api/realtime/health/",
                }
            }
        )


class PriceAlertListCreateView(RealtimeAuthenticatedAPIView):
    """List and create alerts for the authenticated owner."""

    def get(self, request: Request) -> Response:
        """List only the authenticated owner's alerts."""

        results = get_realtime_alert_service().list(_authenticated_owner_id(request))
        payload = PriceAlertResponseSerializer(results, many=True).data
        return Response({"results": payload, "count": len(payload)})

    def post(self, request: Request) -> Response:
        """Create an active owner-scoped price alert."""

        serializer = PriceAlertCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = get_realtime_alert_service().create(
            _authenticated_owner_id(request),
            **serializer.validated_data,
        )
        return Response(
            PriceAlertResponseSerializer(created).data,
            status=status.HTTP_201_CREATED,
        )


class PriceAlertDetailView(RealtimeAuthenticatedAPIView):
    """Read, update, or delete one owner-scoped alert."""

    def get(self, request: Request, alert_id: int) -> Response:
        """Return one alert or an owner-scoped 404."""

        result = get_realtime_alert_service().get(_authenticated_owner_id(request), alert_id)
        if result is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(PriceAlertResponseSerializer(result).data)

    def patch(self, request: Request, alert_id: int) -> Response:
        """Apply a bounded update to one owner-scoped alert."""

        serializer = PriceAlertUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = get_realtime_alert_service().update(
            _authenticated_owner_id(request),
            alert_id,
            dict(serializer.validated_data),
        )
        if result is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(PriceAlertResponseSerializer(result).data)

    def delete(self, request: Request, alert_id: int) -> Response:
        """Delete one alert within the authenticated owner scope."""

        deleted = get_realtime_alert_service().delete(
            _authenticated_owner_id(request), alert_id
        )
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PriceSubscriptionListCreateView(RealtimeAuthenticatedAPIView):
    """List and create durable subscriptions for the authenticated owner."""

    def get(self, request: Request) -> Response:
        """List the authenticated owner's active subscriptions."""

        results = get_realtime_subscription_service().list(
            _authenticated_owner_id(request)
        )
        payload = PriceSubscriptionResponseSerializer(results, many=True).data
        return Response({"results": payload, "count": len(payload)})

    def post(self, request: Request) -> Response:
        """Create or return an idempotent durable subscription."""

        serializer = PriceSubscriptionCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = get_realtime_subscription_service().subscribe(
                _authenticated_owner_id(request),
                serializer.validated_data["asset_code"],
            )
        except SubscriptionLimitExceeded as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            PriceSubscriptionResponseSerializer(result.subscription).data,
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


class PriceSubscriptionDetailView(RealtimeAuthenticatedAPIView):
    """Deactivate one canonical owner subscription."""

    def delete(self, request: Request, asset_code: str) -> Response:
        """Deactivate a subscription or return an owner-scoped 404."""

        removed = get_realtime_subscription_service().unsubscribe(
            _authenticated_owner_id(request),
            asset_code,
        )
        if not removed:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MarketSummaryView(View):
    """兼容 SDK/MCP 的市场概况接口。"""

    INDEX_CODES = {
        "sh_index": "000001.SH",
        "sz_index": "399001.SZ",
        "cyb_index": "399006.SZ",
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.use_case = PricePollingUseCase()

    def get(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> JsonResponse:
        """GET /api/realtime/market-summary/"""
        prices = self.use_case.get_latest_prices(list(self.INDEX_CODES.values()))
        prices_by_code = {item["asset_code"]: item for item in prices}
        index_payload: dict[str, Any] = {}
        latest_timestamp: str | None = None
        total_volume: int | float = 0
        available_count = 0

        for field_name, asset_code in self.INDEX_CODES.items():
            price = prices_by_code.get(asset_code)
            if price is None:
                index_payload[field_name] = None
                continue

            index_payload[field_name] = float(price["price"])
            index_payload[f"{field_name}_change"] = price.get("change")
            index_payload[f"{field_name}_change_pct"] = price.get("change_pct")
            timestamp = price.get("timestamp")
            if timestamp:
                latest_timestamp = (
                    timestamp
                    if latest_timestamp is None
                    else max(
                        latest_timestamp,
                        timestamp,
                    )
                )
            volume = price.get("volume")
            if isinstance(volume, (int, float)) and not isinstance(volume, bool):
                total_volume += volume
            available_count += 1

        payload: dict[str, Any] = {
            "success": available_count > 0,
            "stats_available": False,
            "message": (
                "Major index snapshot is available; breadth statistics are unavailable in the current realtime data providers."
                if available_count
                else "No realtime index snapshot is available from cache or configured providers."
            ),
            "timestamp": latest_timestamp,
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "total_volume": total_volume,
            "total_value": 0,
        }
        payload.update(index_payload)
        return JsonResponse(payload, status=200 if available_count else 503)


class RealtimePriceView(View):
    """实时价格 API 视图"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.use_case = PricePollingUseCase()

    def get(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> JsonResponse:
        """GET /api/realtime/prices/

        查询参数:
            - assets: 资产代码列表，逗号分隔（可选）
                    如果不提供，则返回所有监控资产的价格

        Returns:
            {
                "timestamp": "2024-01-13T10:30:00",
                "prices": [
                    {
                        "asset_code": "ASSET_CODE",
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

        # Note: Realtime prices have very short cache TTL (30s) to reduce load
        # while still providing near-realtime data
        if asset_codes_str:
            # 获取指定资产的价格
            asset_codes = [code.strip() for code in asset_codes_str.split(",") if code.strip()]
            prices = self.use_case.get_latest_prices(asset_codes)

            return JsonResponse(
                {
                    "success_flag": True,
                    "timestamp": prices[0].get("timestamp") if prices else None,
                    "prices": prices,
                    "total": len(asset_codes),
                    "success": len(prices),
                    "failed": len(asset_codes) - len(prices),
                }
            )
        else:
            # 触发价格轮询
            snapshot = self.use_case.execute_price_polling()
            snapshot.setdefault("success_flag", True)
            return JsonResponse(snapshot)

    def post(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> JsonResponse:
        """POST /api/realtime/prices/

        手动触发价格轮询

        Returns:
            价格快照
        """
        snapshot = self.use_case.execute_price_polling()
        snapshot.setdefault("success_flag", True)
        return JsonResponse(snapshot)


class SingleAssetPriceView(View):
    """单个资产价格 API 视图"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.use_case = PricePollingUseCase()

    def get(
        self,
        request: HttpRequest,
        asset_code: str,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse:
        """GET /api/realtime/prices/{asset_code}/

        获取单个资产的最新价格

        Args:
            asset_code: 资产代码

        Returns:
            {
                "asset_code": "ASSET_CODE",
                "price": 10.50,
                "change": 0.10,
                "change_pct": 0.96,
                ...
            }
        """
        prices = self.use_case.get_latest_prices([asset_code])

        if not prices:
            return JsonResponse(
                {"success": False, "error": f"Price not found for asset: {asset_code}"}, status=404
            )

        payload: dict[str, Any] = {"success": True}
        payload.update(prices[0])
        return JsonResponse(payload)


class SectorPerformanceView(APIView):
    """Read latest persisted sector index performance."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        query = SectorPerformanceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        results = list_realtime_sector_performance_payloads()
        return Response({"results": results, "count": len(results)})


class TopMoversView(APIView):
    """Read top movers from cached monitored prices without polling providers."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        query = TopMoversQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        results = list_cached_top_movers_payloads(**query.validated_data)
        return Response(
            {
                "results": results,
                "count": len(results),
                "source": "cached_monitored_prices",
            }
        )


class PricePollingTriggerView(View):
    """价格轮询触发视图

    用于手动触发价格更新或定时任务调用
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.use_case = PricePollingUseCase()

    def post(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> JsonResponse:
        """POST /api/realtime/poll/

        触发价格轮询

        Returns:
            价格快照
        """
        logger.info("Manual price polling triggered")
        snapshot = self.use_case.execute_price_polling()
        snapshot.setdefault("success_flag", True)
        return JsonResponse(snapshot)


class HealthCheckView(View):
    """健康检查视图

    检查实时价格服务是否正常
    """

    def get(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> JsonResponse:
        """GET /api/realtime/health/

        Returns:
            {
                "status": "healthy",
                "data_provider_available": true,
                "last_poll_time": "2024-01-13T10:30:00"
            }
        """
        use_case = PricePollingUseCase()
        check_provider_availability = getattr(type(use_case), "check_provider_availability", None)
        is_available: bool
        health_error: str | None
        if callable(check_provider_availability):
            is_available, health_error = use_case.check_provider_availability(timeout_seconds=2.0)
        else:
            is_available = False
            health_error = None
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(use_case.price_provider.is_available)
                is_available = future.result(timeout=2.0)
            except FutureTimeoutError:
                health_error = "provider_check_timeout"
                logger.warning("Realtime health provider check timed out")
            except Exception as exc:
                health_error = str(exc)
                logger.warning("Realtime health provider check failed: %s", exc)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

        return JsonResponse(
            {
                "success": True,
                "status": "healthy" if is_available else "unhealthy",
                "data_provider_available": is_available,
                "timestamp": use_case.service.config.to_dict(),
                "error": health_error,
            }
        )
