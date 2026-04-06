"""
板块分析模块 - API 视图

遵循项目架构约束：
- 使用 DRF ViewSet/APIView
- 只做输入验证和输出格式化
- 调用 Application 层用例
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.use_cases import (
    AnalyzeSectorRotationRequest,
    AnalyzeSectorRotationUseCase,
    UpdateSectorDataRequest,
    UpdateSectorDataUseCase,
)
from ..infrastructure.adapters.akshare_sector_adapter import AKShareSectorAdapter
from ..infrastructure.repositories import DjangoSectorRepository
from .serializers import (
    AnalyzeSectorRotationRequestSerializer,
    SectorRotationResultSerializer,
    UpdateSectorDataRequestSerializer,
)


def _get_sector_result_status_code(result) -> int:
    """Map sector analysis results to user-facing HTTP status codes."""
    if result.success:
        return status.HTTP_200_OK
    if getattr(result, "status", "") == "unavailable":
        return status.HTTP_200_OK
    return status.HTTP_503_SERVICE_UNAVAILABLE


class SectorRotationViewSet(viewsets.ViewSet):
    """板块轮动分析 API"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sector_repo = DjangoSectorRepository()
        self.adapter = AKShareSectorAdapter()

    def _run_analysis(self, use_case_request):
        use_case = AnalyzeSectorRotationUseCase(sector_repo=self.sector_repo)
        result = use_case.execute(use_case_request)
        warning_code = getattr(result, "warning_message", "")
        if warning_code != "sector_data_unavailable":
            return result

        sync_result = UpdateSectorDataUseCase(
            sector_repo=self.sector_repo,
            adapter=self.adapter,
        ).execute(
            UpdateSectorDataRequest(
                level=use_case_request.level,
                start_date=None,
                end_date=None,
                force_update=False,
            )
        )
        if not sync_result.success:
            return result
        return use_case.execute(use_case_request)

    @action(detail=False, methods=['post'], url_path='analyze')
    def analyze(self, request):
        """
        分析板块轮动

        POST /api/sector/analyze/

        Request Body:
        {
            "regime": "Recovery",  // 可选
            "lookback_days": 20,
            "momentum_weight": 0.3,
            "rs_weight": 0.4,
            "regime_weight": 0.3,
            "level": "SW1",
            "top_n": 10
        }

        Response:
        {
            "success": true,
            "regime": "Recovery",
            "analysis_date": "2026-01-02",
            "top_sectors": [
                {
                    "rank": 1,
                    "sector_code": "801010",
                    "sector_name": "农林牧渔",
                    "total_score": 75.5,
                    "momentum_score": 70.0,
                    "relative_strength_score": 80.0,
                    "regime_fit_score": 75.0
                }
            ]
        }
        """
        # 1. 验证输入
        serializer = AnalyzeSectorRotationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 2. 转换为用例请求
        use_case_request = serializer.to_use_case_request()

        # 3. 执行用例
        result = self._run_analysis(use_case_request)

        # 4. 格式化输出
        result_serializer = SectorRotationResultSerializer(result)
        response_status = _get_sector_result_status_code(result)
        return Response(result_serializer.data, status=response_status)

    @action(detail=False, methods=['get'], url_path='rotation')
    def rotation(self, request):
        """
        获取板块轮动推荐（GET 方法）

        GET /api/sector/rotation/?regime=Recovery&top_n=10

        Response:
        {
            "success": true,
            "regime": "Recovery",
            "analysis_date": "2026-01-02",
            "top_sectors": [...]
        }
        """
        # 1. 从查询参数获取数据
        regime = request.query_params.get('regime')
        lookback_days = int(request.query_params.get('lookback_days', 20))
        level = request.query_params.get('level', 'SW1')
        top_n = int(request.query_params.get('top_n', 10))

        # 2. 构建用例请求
        use_case_request = AnalyzeSectorRotationRequest(
            regime=regime,
            lookback_days=lookback_days,
            level=level,
            top_n=top_n
        )

        # 3. 执行用例
        result = self._run_analysis(use_case_request)

        # 4. 格式化输出
        result_serializer = SectorRotationResultSerializer(result)
        response_status = _get_sector_result_status_code(result)
        return Response(result_serializer.data, status=response_status)


class SectorDataUpdateView(APIView):
    """板块数据更新 API"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sector_repo = DjangoSectorRepository()
        self.adapter = AKShareSectorAdapter()

    def post(self, request):
        """
        更新板块数据

        POST /api/sector/update-data/

        Request Body:
        {
            "level": "SW1",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "force_update": false
        }

        Response:
        {
            "success": true,
            "updated_count": 500
        }
        """
        # 1. 验证输入
        serializer = UpdateSectorDataRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 2. 构建用例请求
        data = serializer.validated_data
        use_case_request = UpdateSectorDataRequest(
            level=data.get('level', 'SW1'),
            start_date=data.get('start_date').isoformat() if data.get('start_date') else None,
            end_date=data.get('end_date').isoformat() if data.get('end_date') else None,
            force_update=data.get('force_update', False)
        )

        # 3. 执行用例
        use_case = UpdateSectorDataUseCase(
            sector_repo=self.sector_repo,
            adapter=self.adapter
        )
        result = use_case.execute(use_case_request)

        # 4. 格式化输出
        if result.success:
            return Response({
                'success': True,
                'updated_count': result.updated_count
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'success': False,
                'error': result.error
            }, status=status.HTTP_400_BAD_REQUEST)
