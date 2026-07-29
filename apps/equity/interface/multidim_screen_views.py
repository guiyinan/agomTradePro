"""Multi-dimensional screening API view for the equity module.

Owns `EquityMultiDimScreenAPIView` (generic asset-analysis framework
integration). The compatibility facade in `views.py` remains the stable import
surface; do not import it here.
"""

import logging
from typing import Any, cast

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.equity.application.repository_provider import get_equity_asset_repository
from apps.signal.application.repository_provider import get_signal_repository

from .serializers import EquityMultiDimScreenRequestSerializer

logger = logging.getLogger(__name__)


class EquityMultiDimScreenAPIView(APIView):
    """个股多维度筛选 API

    POST /api/equity/multidim-screen/

    使用通用资产分析框架进行多维度评分筛选。
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        from apps.equity.application.services import EquityMultiDimScorer

        self.asset_repo = get_equity_asset_repository()
        self.scorer = EquityMultiDimScorer(self.asset_repo)

    def post(self, request: Request) -> Response:
        """
        多维度筛选个股

        请求体：
        {
            "filters": {
                "sector": "银行",
                "market": "SH",
                "min_market_cap": 50000000000,
                "max_pe": 15.0
            },
            "context": {
                "regime": "Recovery",
                "policy_level": "P0",
                "sentiment_index": 0.5
            },
            "max_count": 30
        }
        """
        request_serializer = EquityMultiDimScreenRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        filters = cast(dict[str, object], request_serializer.validated_data["filters"])
        context_data = cast(dict[str, object], request_serializer.validated_data["context"])
        max_count = cast(int, request_serializer.validated_data["max_count"])

        # 2. 构建评分上下文
        from apps.asset_analysis.domain.value_objects import ScoreContext

        # 获取激活的信号
        signal_repo = get_signal_repository()
        active_signals = signal_repo.get_active_signals()

        context = ScoreContext(
            current_regime=cast(str, context_data.get("regime", "Recovery")),
            policy_level=cast(str, context_data.get("policy_level", "P0")),
            sentiment_index=cast(float, context_data.get("sentiment_index", 0.0)),
            active_signals=active_signals,
        )

        try:
            result = self.scorer.screen_stocks(
                filters=filters,
                context=context,
                max_count=max_count,
            )
        except Exception as exc:
            logger.error(
                "Equity multi-dimensional screening failed error_type=%s",
                type(exc).__name__,
            )
            return Response(
                {
                    "success": False,
                    "message": "筛选服务暂时不可用",
                    "stocks": [],
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "success": result["success"],
                "count": result["count"],
                "context": {
                    "regime": context.current_regime,
                    "policy_level": context.policy_level,
                    "sentiment_index": context.sentiment_index,
                    "active_signals_count": len(active_signals),
                },
                "stocks": result["stocks"],
            },
            status=status.HTTP_200_OK if result["success"] else status.HTTP_404_NOT_FOUND,
        )


__all__ = ["EquityMultiDimScreenAPIView"]
