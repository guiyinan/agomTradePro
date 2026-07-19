"""Multi-dimensional screening API view for the equity module.

Owns `EquityMultiDimScreenAPIView` (generic asset-analysis framework
integration). The compatibility facade in `views.py` remains the stable import
surface; do not import it here.
"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.equity.application.repository_provider import get_equity_asset_repository
from apps.signal.application.repository_provider import get_signal_repository

# ==================== 多维度筛选 API（通用资产分析框架集成） ====================


class EquityMultiDimScreenAPIView(APIView):
    """个股多维度筛选 API

    POST /api/equity/multidim-screen/

    使用通用资产分析框架进行多维度评分筛选。
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from apps.equity.application.services import EquityMultiDimScorer

        self.asset_repo = get_equity_asset_repository()
        self.scorer = EquityMultiDimScorer(self.asset_repo)

    def post(self, request) -> Response:
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
        # 1. 验证请求
        filters = request.data.get("filters", {})
        context_data = request.data.get("context", {})
        max_count = request.data.get("max_count", 30)

        # 2. 构建评分上下文
        from apps.asset_analysis.domain.value_objects import ScoreContext

        # 获取激活的信号
        signal_repo = get_signal_repository()
        active_signals = signal_repo.get_active_signals()

        context = ScoreContext(
            current_regime=context_data.get("regime", "Recovery"),
            policy_level=context_data.get("policy_level", "P0"),
            sentiment_index=context_data.get("sentiment_index", 0.0),
            active_signals=active_signals,
        )

        # 3. 执行筛选
        try:
            result = self.scorer.screen_stocks(
                filters=filters,
                context=context,
                max_count=max_count,
            )

            # 4. 返回响应
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

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": f"筛选失败: {str(e)}",
                    "stocks": [],
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


__all__ = ["EquityMultiDimScreenAPIView"]
