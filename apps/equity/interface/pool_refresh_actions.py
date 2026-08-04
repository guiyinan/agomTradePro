"""Regime-driven stock-pool refresh action for the equity API viewset.

The refresh workflow is isolated from the pool read action to keep each
interface owner bounded.  ``views.py`` reaches it transitively through
``EquityPoolActionsMixin``; this module never imports the compatibility
facade.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.equity.application.use_cases import (
    ScreenStocksRequest,
    ScreenStocksUseCase,
)
from apps.regime.domain.services_v2 import RegimeType

from .serializers import PoolActionRequestSerializer
from .valuation_actions import typed_action

if TYPE_CHECKING:
    from apps.equity.application.repository_provider import (
        DjangoStockRepository,
        RegimeRepositoryAdapter,
        StockPoolRepositoryAdapter,
    )

logger = logging.getLogger(__name__)


class EquityPoolRefreshActionsMixin:
    """Regime-driven stock-pool refresh action."""

    stock_repo: DjangoStockRepository
    regime_repo: RegimeRepositoryAdapter
    pool_adapter: StockPoolRepositoryAdapter

    def _build_screen_use_case(self) -> ScreenStocksUseCase:
        """Build the screening use case; the facade may override this hook."""

        return ScreenStocksUseCase(
            stock_repository=self.stock_repo,
            regime_repository=self.regime_repo,
        )

    @staticmethod
    def _resolve_current_regime_name() -> str | None:
        """Resolve a canonical current Regime for pool display."""

        from apps.regime.application.current_regime import resolve_current_regime

        try:
            result = resolve_current_regime()
        except Exception:
            logger.warning("Current Regime unavailable while loading stock pool", exc_info=True)
            return None
        regime = str(getattr(result, "dominant_regime", "") or "").strip()
        return regime if regime in {item.value for item in RegimeType} else None

    @typed_action(
        detail=False,
        methods=["post"],
        url_path="pool/refresh",
        permission_classes=[IsAdminUser],
    )
    def refresh_pool(self, request: Request) -> Response:
        """
        POST /api/equity/pool/refresh/

        刷新股票池

        基于当前 Regime 重新筛选股票池。
        """
        from apps.regime.application.current_regime import resolve_current_regime

        serializer = PoolActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # 获取当前 Regime
            latest_regime = resolve_current_regime()
            if not latest_regime or bool(getattr(latest_regime, "is_fallback", False)):
                return Response(
                    {
                        "success": False,
                        "message": "当前 Regime 不可用或处于降级状态，请先完成正式判定",
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            regime = str(latest_regime.dominant_regime or "").strip()
            if regime not in {item.value for item in RegimeType}:
                return Response(
                    {"success": False, "message": "当前 Regime 不是有效四象限结果"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            # 构造筛选请求
            screen_request = ScreenStocksRequest(
                regime=regime,
            )

            # 执行筛选
            screen_use_case = self._build_screen_use_case()
            screen_response = screen_use_case.execute(screen_request)

            if not screen_response.success:
                return Response(
                    {"success": False, "message": "股票池筛选失败"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            if not screen_response.stock_codes:
                return Response(
                    {
                        "success": False,
                        "message": "筛选结果为空，已保留现有股票池",
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

            # 保存新的股票池
            self.pool_adapter.save_pool(
                stock_codes=screen_response.stock_codes,
                regime=regime,
                as_of_date=timezone.localdate(),
            )

            return Response(
                {
                    "success": True,
                    "message": "股票池已刷新",
                    "regime": regime,
                    "count": len(screen_response.stock_codes),
                    "update_time": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        except Exception:
            logger.exception("Failed to refresh equity stock pool")
            return Response(
                {"success": False, "message": "刷新股票池失败"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


__all__ = ["EquityPoolRefreshActionsMixin"]
