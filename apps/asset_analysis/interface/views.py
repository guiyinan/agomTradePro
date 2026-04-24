"""
资产分析模块 - Interface 层视图

使用 Django REST Framework 定义 API 视图。
"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.asset_analysis.application.interface_services import (
    build_asset_pool_context,
    execute_multidim_screen,
    get_current_weight_config,
    get_weight_configs,
)
from apps.asset_analysis.interface.serializers import (
    ScreenRequestSerializer,
    ScreenResponseSerializer,
    WeightConfigsResponseSerializer,
)


class MultiDimScreenAPIView(APIView):
    """
    多维度筛选 API 视图

    POST /api/asset-analysis/multidim-screen/
    """

    def post(self, request):
        """
        处理多维度筛选请求

        请求体：
        {
            "asset_type": "fund",
            "filters": {"fund_type": "股票型"},
            "weights": {"regime": 0.40, ...},  // 可选
            "max_count": 30
        }
        """
        # 1. 验证请求
        request_serializer = ScreenRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(
                {"success": False, "message": "请求参数错误", "errors": request_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = request_serializer.validated_data

        # 2. 构建评分上下文（从实际系统获取数据）
        context = self._build_score_context(request)

        # 3. 构建请求 DTO
        from apps.asset_analysis.application.dtos import ScreenRequest
        request_dto = ScreenRequest(
            asset_type=validated_data["asset_type"],
            filters=validated_data.get("filters", {}),
            weights=validated_data.get("weights"),
            max_count=validated_data.get("max_count", 30),
        )

        # 4. 执行用例
        response_dto = execute_multidim_screen(request_dto, context)

        # 5. 返回响应
        response_serializer = ScreenResponseSerializer(response_dto.to_dict())
        http_status = status.HTTP_200_OK if response_dto.success else status.HTTP_500_INTERNAL_SERVER_ERROR
        return Response(response_serializer.data, status=http_status)

    def _build_score_context(self, request):
        """
        构建评分上下文

        从系统中获取实际的 Regime、Policy、Sentiment 数据。
        """
        payload = build_asset_pool_context(
            regime_override=request.data.get("regime"),
            policy_level_override=request.data.get("policy_level"),
            sentiment_index_override=request.data.get("sentiment_index"),
            active_signals_override=request.data.get("active_signals"),
        )
        return payload.score_context


class WeightConfigsAPIView(APIView):
    """
    权重配置 API 视图

    GET /api/asset-analysis/weight-configs/
    """

    def get(self, request):
        """
        获取所有权重配置

        返回：
        {
            "configs": {
                "default": {"regime": 0.40, ...},
                "policy_crisis": {"regime": 0.20, ...}
            },
            "active": "default"
        }
        """
        result = get_weight_configs()

        response_serializer = WeightConfigsResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class CurrentWeightAPIView(APIView):
    """
    当前生效权重 API 视图

    GET /api/asset-analysis/current-weight/?asset_type=fund
    """

    def get(self, request):
        """
        获取当前生效的权重配置

        查询参数：
        - asset_type: 资产类型（可选）
        - market_condition: 市场状态（可选）
        """
        asset_type = request.query_params.get("asset_type")
        market_condition = request.query_params.get("market_condition")

        result = get_current_weight_config(
            asset_type=asset_type,
            market_condition=market_condition
        )

        return Response(result, status=status.HTTP_200_OK)
