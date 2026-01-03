"""
资产分析模块 - Interface 层视图

使用 Django REST Framework 定义 API 视图。
"""

from datetime import date
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.asset_analysis.domain.interfaces import WeightConfigRepositoryProtocol, AssetRepositoryProtocol
from apps.asset_analysis.application.use_cases import MultiDimScreenUseCase, GetWeightConfigsUseCase
from apps.asset_analysis.infrastructure.repositories import DjangoWeightConfigRepository
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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 初始化仓储（实际应该通过依赖注入）
        self.weight_repo = DjangoWeightConfigRepository()
        # asset_repo 需要根据 asset_type 动态创建
        self.asset_repo = None

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

        # 2. 构建评分上下文
        # TODO: 从系统获取实际的 Regime、Policy、Sentiment 数据
        context = ScoreContext(
            current_regime=request.data.get("regime", "Recovery"),
            policy_level=request.data.get("policy_level", "P0"),
            sentiment_index=request.data.get("sentiment_index", 0.0),
            active_signals=request.data.get("active_signals", []),
            score_date=date.today(),
        )

        # 3. 获取资产仓储（根据资产类型）
        # TODO: 实现根据 asset_type 获取对应仓储的逻辑
        # 例如：fund -> DjangoFundRepository, equity -> DjangoEquityRepository

        # 4. 执行用例（暂不实现，因为需要具体的 AssetRepository）
        # use_case = MultiDimScreenUseCase(self.weight_repo, self.asset_repo)
        # response_dto = use_case.execute(request_dto, context)

        # 5. 返回响应（占位）
        return Response({
            "success": False,
            "message": "多维度筛选功能正在开发中，需要先实现具体资产类型的仓储",
            "timestamp": date.today().isoformat(),
            "context": context.to_dict(),
            "weights": self.weight_repo.get_active_weights().to_dict(),
            "assets": [],
        }, status=status.HTTP_501_NOT_IMPLEMENTED)


class WeightConfigsAPIView(APIView):
    """
    权重配置 API 视图

    GET /api/asset-analysis/weight-configs/
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.weight_repo = DjangoWeightConfigRepository()

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
        use_case = GetWeightConfigsUseCase(self.weight_repo)
        result = use_case.execute()

        response_serializer = WeightConfigsResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class CurrentWeightAPIView(APIView):
    """
    当前生效权重 API 视图

    GET /api/asset-analysis/current-weight/?asset_type=fund
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.weight_repo = DjangoWeightConfigRepository()

    def get(self, request):
        """
        获取当前生效的权重配置

        查询参数：
        - asset_type: 资产类型（可选）
        - market_condition: 市场状态（可选）
        """
        asset_type = request.query_params.get("asset_type")
        market_condition = request.query_params.get("market_condition")

        weights = self.weight_repo.get_active_weights(
            asset_type=asset_type,
            market_condition=market_condition
        )

        return Response({
            "success": True,
            "weights": weights.to_dict(),
            "asset_type": asset_type,
            "market_condition": market_condition,
        }, status=status.HTTP_200_OK)
