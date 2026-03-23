"""
资产分析模块 - Interface 层视图

使用 Django REST Framework 定义 API 视图。
"""

from datetime import date

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.asset_analysis.application.use_cases import GetWeightConfigsUseCase, MultiDimScreenUseCase
from apps.asset_analysis.domain.interfaces import (
    AssetRepositoryProtocol,
    WeightConfigRepositoryProtocol,
)
from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.asset_analysis.infrastructure.repositories import (
    DjangoAssetRepository,
    DjangoWeightConfigRepository,
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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 初始化仓储
        self.weight_repo = DjangoWeightConfigRepository()
        self.asset_repo = DjangoAssetRepository()

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
        use_case = MultiDimScreenUseCase(self.weight_repo, self.asset_repo)
        response_dto = use_case.execute(request_dto, context)

        # 5. 返回响应
        response_serializer = ScreenResponseSerializer(response_dto.to_dict())
        http_status = status.HTTP_200_OK if response_dto.success else status.HTTP_500_INTERNAL_SERVER_ERROR
        return Response(response_serializer.data, status=http_status)

    def _build_score_context(self, request) -> ScoreContext:
        """
        构建评分上下文

        从系统中获取实际的 Regime、Policy、Sentiment 数据。
        """
        # 获取当前 Regime
        current_regime = "Recovery"  # 默认值
        try:
            from apps.regime.application.current_regime import resolve_current_regime

            regime_value = resolve_current_regime().dominant_regime
            regime_mapping = {
                "Recovery": "Recovery",
                "Overheat": "Overheat",
                "Stagflation": "Stagflation",
                "Deflation": "Deflation",
            }
            current_regime = regime_mapping.get(regime_value, "Recovery")
        except Exception:
            # 使用默认值
            pass

        # 获取当前 Policy 档位
        policy_level = "P0"  # 默认值
        try:
            from apps.policy.application.use_cases import GetCurrentPolicyUseCase
            from apps.policy.infrastructure.repositories import DjangoPolicyRepository

            policy_repo = DjangoPolicyRepository()
            policy_use_case = GetCurrentPolicyUseCase(policy_repo)
            policy_response = policy_use_case.execute()

            if policy_response.success and policy_response.policy_level:
                policy_level = policy_response.policy_level.value
        except Exception:
            # 使用默认值
            pass

        # 获取当前情绪指数
        sentiment_index = 0.0  # 默认值
        try:
            from apps.sentiment.infrastructure.repositories import SentimentIndexRepository

            sentiment_repo = SentimentIndexRepository()
            # 获取最新的情绪记录
            latest_sentiment = sentiment_repo.get_latest()

            if latest_sentiment:
                # 将情绪值转换为 -3.0 到 3.0 的范围
                # composite_index 范围是 -1 到 1，需要转换
                sentiment_index = latest_sentiment.composite_index * 3
        except Exception:
            # 使用默认值
            pass

        # 获取激活的投资信号
        active_signals = []
        try:
            from apps.signal.infrastructure.repositories import DjangoSignalRepository

            signal_repo = DjangoSignalRepository()
            active_signals = signal_repo.get_active_signals()

            if not active_signals:
                active_signals = []
        except Exception:
            # 使用空列表
            pass

        # 支持从请求中覆盖上下文值（用于测试）
        current_regime = request.data.get("regime", current_regime)
        policy_level = request.data.get("policy_level", policy_level)
        sentiment_index = request.data.get("sentiment_index", sentiment_index)
        active_signals = request.data.get("active_signals", active_signals)

        return ScoreContext(
            current_regime=current_regime,
            policy_level=policy_level,
            sentiment_index=sentiment_index,
            active_signals=active_signals,
            score_date=date.today(),
        )


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
