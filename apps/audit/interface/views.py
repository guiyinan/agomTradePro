"""
Views for Audit API.
"""

from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from datetime import datetime
import logging

from apps.audit.application.use_cases import (
    GenerateAttributionReportUseCase,
    GenerateAttributionReportRequest,
    GetAuditSummaryUseCase,
    GetAuditSummaryRequest,
)
from apps.audit.infrastructure.repositories import DjangoAuditRepository
from apps.backtest.infrastructure.repositories import DjangoBacktestRepository
from .serializers import (
    AttributionReportSerializer,
    GenerateAttributionReportRequestSerializer,
    GenerateAttributionReportResponseSerializer,
)

logger = logging.getLogger(__name__)


class GenerateAttributionReportView(APIView):
    """生成归因报告 API"""

    @extend_schema(
        summary="生成归因分析报告",
        description="为指定的回测结果生成详细的归因分析报告，包括收益分解、损失分析和经验总结",
        request=GenerateAttributionReportRequestSerializer,
        responses={
            201: GenerateAttributionReportResponseSerializer,
            400: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "成功示例",
                value={"backtest_id": 1},
                response_only=True,
            )
        ]
    )
    def post(self, request):
        """生成归因报告"""
        serializer = GenerateAttributionReportRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': '验证失败', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        backtest_id = serializer.validated_data['backtest_id']

        # 执行 Use Case
        use_case = GenerateAttributionReportUseCase(
            audit_repository=DjangoAuditRepository(),
            backtest_repository=DjangoBacktestRepository(),
        )

        response = use_case.execute(
            GenerateAttributionReportRequest(backtest_id=backtest_id)
        )

        if not response.success:
            return Response(
                {'error': response.error},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 获取并返回报告
        audit_repo = DjangoAuditRepository()
        report = audit_repo.get_attribution_report(response.report_id)
        if report:
            report['loss_analyses'] = audit_repo.get_loss_analyses(response.report_id)
            report['experience_summaries'] = audit_repo.get_experience_summaries(response.report_id)

        serializer = AttributionReportSerializer(report)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AuditSummaryView(APIView):
    """审计摘要 API"""

    @extend_schema(
        summary="获取审计摘要",
        description="获取指定条件的审计报告摘要，支持按回测ID或日期范围查询",
        parameters=[
            OpenApiParameter(
                name='backtest_id',
                type=int,
                required=False,
                description='回测 ID',
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='start_date',
                type=str,
                required=False,
                description='开始日期（YYYY-MM-DD）',
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='end_date',
                type=str,
                required=False,
                description='结束日期（YYYY-MM-DD）',
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: AttributionReportSerializer(many=True),
            400: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "按回测ID查询",
                value={'backtest_id': 1},
                parameter_only=('backtest_id',)
            ),
            OpenApiExample(
                "按日期范围查询",
                value={'start_date': '2024-01-01', 'end_date': '2024-12-31'},
                parameter_only=('start_date', 'end_date')
            )
        ]
    )
    def get(self, request):
        """获取审计摘要"""
        backtest_id = request.query_params.get('backtest_id')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        # 构建请求
        req = GetAuditSummaryRequest()

        if backtest_id:
            try:
                req.backtest_id = int(backtest_id)
            except ValueError:
                return Response(
                    {'error': 'backtest_id 必须是整数'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        if start_date and end_date:
            try:
                req.start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                req.end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': '日期格式错误，应为 YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # 执行 Use Case
        use_case = GetAuditSummaryUseCase(
            audit_repository=DjangoAuditRepository()
        )

        response = use_case.execute(req)

        if not response.success:
            return Response(
                {'error': response.error},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = AttributionReportSerializer(response.reports, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ========== HTML Page Views ==========

class AuditPageView(LoginRequiredMixin, TemplateView):
    """审计页面 - HTML 视图"""
    template_name = 'audit/audit_page.html'
    login_url = '/account/login/'
