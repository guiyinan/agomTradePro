"""
Views for Audit API.
"""

from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from datetime import datetime, date
import json
import logging

from apps.audit.application.use_cases import (
    GenerateAttributionReportUseCase,
    GenerateAttributionReportRequest,
    GetAuditSummaryUseCase,
    GetAuditSummaryRequest,
    EvaluateIndicatorPerformanceUseCase,
    EvaluateIndicatorPerformanceRequest,
    ValidateThresholdsUseCase,
    ValidateThresholdsRequest,
)
from apps.audit.infrastructure.repositories import DjangoAuditRepository
from apps.audit.infrastructure.models import (
    AttributionReport,
    LossAnalysis,
    ExperienceSummary,
    IndicatorThresholdConfigModel,
    ValidationSummaryModel,
    IndicatorPerformanceModel,
)
from apps.backtest.infrastructure.repositories import DjangoBacktestRepository
from .serializers import (
    AttributionReportSerializer,
    GenerateAttributionReportRequestSerializer,
    GenerateAttributionReportResponseSerializer,
)

logger = logging.getLogger(__name__)


# ============ Attribution API Views ============

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


class AttributionChartDataView(APIView):
    """归因图表数据 API"""

    def get(self, request, report_id):
        """获取归因报告的图表数据"""
        try:
            audit_repo = DjangoAuditRepository()
            report = audit_repo.get_attribution_report(report_id)

            if not report:
                return Response(
                    {'error': '报告不存在'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 构造图表数据
            chart_data = {
                'report_id': report_id,
                'total_pnl': report.get('total_pnl', 0),
                'regime_timing_pnl': report.get('regime_timing_pnl', 0),
                'asset_selection_pnl': report.get('asset_selection_pnl', 0),
                'interaction_pnl': report.get('interaction_pnl', 0),
                'regime_accuracy': report.get('regime_accuracy', 0),
                'period_attributions': report.get('period_attributions', []),
                'loss_analyses': report.get('loss_analyses', []),
                'experience_summaries': report.get('experience_summaries', []),
            }

            return Response(chart_data)

        except Exception as e:
            logger.error(f"获取图表数据失败: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


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


# ============ Indicator Performance API Views ============

class IndicatorPerformanceDetailView(APIView):
    """指标表现详情 API"""

    def get(self, request, indicator_code):
        """获取单个指标的详细表现数据"""
        try:
            # 获取最新的评估结果
            performance = IndicatorPerformanceModel._default_manager.filter(
                indicator_code=indicator_code
            ).order_by('-evaluation_period_end').first()

            if not performance:
                return Response(
                    {'error': f'指标 {indicator_code} 暂无评估数据'},
                    status=status.HTTP_404_NOT_FOUND
                )

            data = {
                'indicator_code': performance.indicator_code,
                'evaluation_period_start': performance.evaluation_period_start,
                'evaluation_period_end': performance.evaluation_period_end,
                'true_positive_count': performance.true_positive_count,
                'false_positive_count': performance.false_positive_count,
                'true_negative_count': performance.true_negative_count,
                'false_negative_count': performance.false_negative_count,
                'precision': performance.precision,
                'recall': performance.recall,
                'f1_score': performance.f1_score,
                'accuracy': performance.accuracy,
                'lead_time_mean': performance.lead_time_mean,
                'lead_time_std': performance.lead_time_std,
                'stability_score': performance.stability_score,
                'decay_rate': performance.decay_rate,
                'signal_strength': performance.signal_strength,
                'recommended_action': performance.recommended_action,
                'recommended_weight': performance.recommended_weight,
                'confidence_level': performance.confidence_level,
            }

            return Response(data)

        except Exception as e:
            logger.error(f"获取指标表现详情失败: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class IndicatorPerformanceChartDataView(APIView):
    """指标表现图表数据 API"""

    def get(self, request, validation_id):
        """获取指标验证的图表数据"""
        try:
            # 获取验证摘要
            summary = ValidationSummaryModel._default_manager.get(id=validation_id)

            # 获取该次验证的所有指标表现
            performances = IndicatorPerformanceModel._default_manager.filter(
                evaluation_period_start=summary.evaluation_period_start,
                evaluation_period_end=summary.evaluation_period_end,
            )

            # 构造图表数据
            chart_data = {
                'validation_run_id': summary.validation_run_id,
                'evaluation_period': {
                    'start': summary.evaluation_period_start,
                    'end': summary.evaluation_period_end,
                },
                'total_indicators': summary.total_indicators,
                'approved_indicators': summary.approved_indicators,
                'rejected_indicators': summary.rejected_indicators,
                'pending_indicators': summary.pending_indicators,
                'avg_f1_score': summary.avg_f1_score,
                'avg_stability_score': summary.avg_stability_score,
                'indicators': [
                    {
                        'indicator_code': p.indicator_code,
                        'f1_score': p.f1_score,
                        'stability_score': p.stability_score,
                        'recommended_action': p.recommended_action,
                    }
                    for p in performances
                ],
            }

            return Response(chart_data)

        except ValidationSummaryModel.DoesNotExist:
            return Response(
                {'error': '验证记录不存在'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"获取图表数据失败: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ValidateAllIndicatorsView(APIView):
    """验证所有指标 API"""

    def post(self, request):
        """触发所有指标的验证"""
        try:
            data = request.data
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            use_shadow_mode = data.get('use_shadow_mode', False)

            if not start_date or not end_date:
                return Response(
                    {'error': '必须提供 start_date 和 end_date'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

            # 执行验证
            use_case = ValidateThresholdsUseCase(
                audit_repository=DjangoAuditRepository()
            )

            request_obj = ValidateThresholdsRequest(
                start_date=start_date,
                end_date=end_date,
                use_shadow_mode=use_shadow_mode
            )

            response = use_case.execute(request_obj)

            if not response.success:
                return Response(
                    {'error': response.error},
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response({
                'validation_run_id': response.validation_run_id,
                'message': '验证已启动'
            })

        except ValueError as e:
            return Response(
                {'error': f'日期格式错误: {e}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"验证指标失败: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UpdateThresholdView(APIView):
    """更新阈值配置 API"""

    def post(self, request):
        """更新指标阈值配置"""
        try:
            data = request.data
            indicator_code = data.get('indicator_code')
            level_low = data.get('level_low')
            level_high = data.get('level_high')

            if not indicator_code or level_low is None or level_high is None:
                return Response(
                    {'error': '必须提供 indicator_code, level_low, level_high'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 更新配置
            config = IndicatorThresholdConfigModel._default_manager.filter(
                indicator_code=indicator_code,
                is_active=True
            ).first()

            if not config:
                return Response(
                    {'error': f'指标 {indicator_code} 的配置不存在'},
                    status=status.HTTP_404_NOT_FOUND
                )

            config.level_low = level_low
            config.level_high = level_high
            config.save()

            return Response({
                'success': True,
                'message': '阈值已更新'
            })

        except Exception as e:
            logger.error(f"更新阈值失败: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class RunValidationView(APIView):
    """运行验证 API"""

    def post(self, request):
        """运行阈值验证"""
        try:
            data = request.data
            start_date = data.get('start_date')
            end_date = data.get('end_date')

            if not start_date or not end_date:
                # 默认使用过去一年
                end_date = date.today()
                start_date = date(end_date.year - 1, end_date.month, end_date.day)
            else:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

            # 执行验证
            use_case = ValidateThresholdsUseCase(
                audit_repository=DjangoAuditRepository()
            )

            request_obj = ValidateThresholdsRequest(
                start_date=start_date,
                end_date=end_date,
                use_shadow_mode=False
            )

            response = use_case.execute(request_obj)

            if not response.success:
                return Response(
                    {'error': response.error},
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response({
                'validation_run_id': response.validation_run_id,
                'report': response.validation_report
            })

        except Exception as e:
            logger.error(f"运行验证失败: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ThresholdValidationDataView(APIView):
    """阈值验证数据 API"""

    def get(self, request, summary_id):
        """获取阈值验证的详细数据"""
        try:
            summary = ValidationSummaryModel._default_manager.get(id=summary_id)

            # 获取所有相关的指标表现
            performances = IndicatorPerformanceModel._default_manager.filter(
                evaluation_period_start=summary.evaluation_period_start,
                evaluation_period_end=summary.evaluation_period_end,
            )

            # 获取所有阈值配置
            threshold_configs = IndicatorThresholdConfigModel._default_manager.filter(
                is_active=True
            )

            # 构造响应数据
            validation_data = {
                'summary': {
                    'validation_run_id': summary.validation_run_id,
                    'run_date': summary.run_date,
                    'evaluation_period_start': summary.evaluation_period_start,
                    'evaluation_period_end': summary.evaluation_period_end,
                    'total_indicators': summary.total_indicators,
                    'approved_indicators': summary.approved_indicators,
                    'rejected_indicators': summary.rejected_indicators,
                    'pending_indicators': summary.pending_indicators,
                    'avg_f1_score': summary.avg_f1_score,
                    'avg_stability_score': summary.avg_stability_score,
                    'overall_recommendation': summary.overall_recommendation,
                    'status': summary.status,
                },
                'indicator_reports': [
                    {
                        'indicator_code': p.indicator_code,
                        'f1_score': p.f1_score,
                        'precision': p.precision,
                        'recall': p.recall,
                        'stability_score': p.stability_score,
                        'decay_rate': p.decay_rate,
                        'signal_strength': p.signal_strength,
                        'recommended_action': p.recommended_action,
                        'recommended_weight': p.recommended_weight,
                    }
                    for p in performances
                ],
                'threshold_configs': [
                    {
                        'indicator_code': c.indicator_code,
                        'indicator_name': c.indicator_name,
                        'level_low': c.level_low,
                        'level_high': c.level_high,
                        'base_weight': c.base_weight,
                    }
                    for c in threshold_configs
                ],
            }

            return Response(validation_data)

        except ValidationSummaryModel.DoesNotExist:
            return Response(
                {'error': '验证记录不存在'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"获取验证数据失败: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============ HTML Page Views ============

class AuditPageView(LoginRequiredMixin, TemplateView):
    """审计模块主页 - HTML 视图"""
    template_name = 'audit/audit_page.html'
    login_url = '/account/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # 获取最新验证摘要
        try:
            latest_validation = ValidationSummaryModel._default_manager.filter(
                is_shadow_mode=False
            ).order_by('-run_date').first()

            # 获取最近的归因报告
            recent_reports = AttributionReport._default_manager.select_related(
                'backtest'
            ).order_by('-created_at')[:5]

            context['latest_validation'] = latest_validation
            context['recent_reports'] = recent_reports
        except Exception as e:
            logger.error(f"获取审计数据失败: {e}")
            context['latest_validation'] = None
            context['recent_reports'] = []

        return context


class AttributionDetailView(LoginRequiredMixin, TemplateView):
    """归因详情页 - HTML 视图"""
    template_name = 'audit/attribution_detail.html'
    login_url = '/account/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        report_id = kwargs.get('report_id')

        try:
            audit_repo = DjangoAuditRepository()
            report = audit_repo.get_attribution_report(report_id)

            if report:
                report['loss_analyses'] = audit_repo.get_loss_analyses(report_id)
                report['experience_summaries'] = audit_repo.get_experience_summaries(report_id)

            context['report'] = report
        except Exception as e:
            logger.error(f"获取归因详情失败: {e}")
            context['report'] = None

        return context


class IndicatorPerformancePageView(LoginRequiredMixin, TemplateView):
    """指标表现评估页 - HTML 视图"""
    template_name = 'audit/indicator_performance.html'
    login_url = '/account/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        try:
            # 获取最新的验证摘要
            latest_summary = ValidationSummaryModel._default_manager.filter(
                is_shadow_mode=False
            ).order_by('-run_date').first()

            if latest_summary:
                # 获取所有指标表现
                performances = IndicatorPerformanceModel._default_manager.filter(
                    evaluation_period_start=latest_summary.evaluation_period_start,
                    evaluation_period_end=latest_summary.evaluation_period_end,
                )

                # 获取阈值配置用于分类
                threshold_configs = {
                    c.indicator_code: c
                    for c in IndicatorThresholdConfigModel._default_manager.filter(is_active=True)
                }

                # 为每个表现添加分类
                indicator_reports = []
                for p in performances:
                    config = threshold_configs.get(p.indicator_code)
                    report_data = {
                        'indicator_code': p.indicator_code,
                        'indicator_name': config.indicator_name if config else p.indicator_code,
                        'category': config.category if config else '',
                        'f1_score': p.f1_score,
                        'stability_score': p.stability_score,
                        'lead_time_mean': p.lead_time_mean,
                        'recommended_action': p.recommended_action,
                        'recommended_weight': p.recommended_weight,
                        'true_positive_count': p.true_positive_count,
                        'false_positive_count': p.false_positive_count,
                        'true_negative_count': p.true_negative_count,
                        'false_negative_count': p.false_negative_count,
                    }
                    indicator_reports.append(report_data)

                context['total_indicators'] = latest_summary.total_indicators
                context['approved_indicators'] = latest_summary.approved_indicators
                context['pending_indicators'] = latest_summary.pending_indicators
                context['rejected_indicators'] = latest_summary.rejected_indicators
                context['avg_f1_score'] = latest_summary.avg_f1_score
                context['avg_stability_score'] = latest_summary.avg_stability_score
                context['indicator_reports'] = indicator_reports
                context['indicator_data'] = json.dumps(indicator_reports, ensure_ascii=False)
            else:
                # 没有验证记录时的默认数据
                context['total_indicators'] = 0
                context['approved_indicators'] = 0
                context['pending_indicators'] = 0
                context['rejected_indicators'] = 0
                context['avg_f1_score'] = 0
                context['avg_stability_score'] = 0
                context['indicator_reports'] = []
                context['indicator_data'] = '[]'

        except Exception as e:
            logger.error(f"获取指标表现数据失败: {e}")
            # 设置默认值
            context['total_indicators'] = 0
            context['indicator_reports'] = []
            context['indicator_data'] = '[]'

        return context


class ThresholdValidationPageView(LoginRequiredMixin, TemplateView):
    """阈值验证页 - HTML 视图"""
    template_name = 'audit/threshold_validation.html'
    login_url = '/account/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        try:
            # 获取所有活跃的阈值配置
            threshold_configs = IndicatorThresholdConfigModel._default_manager.filter(
                is_active=True
            )

            # 为每个配置添加历史验证结果
            configs_with_history = []
            for config in threshold_configs:
                # 获取该指标的历史验证结果
                validation_history = IndicatorPerformanceModel._default_manager.filter(
                    indicator_code=config.indicator_code
                ).order_by('-evaluation_period_end')[:3]

                config_dict = {
                    'indicator_code': config.indicator_code,
                    'indicator_name': config.indicator_name,
                    'level_low': config.level_low,
                    'level_high': config.level_high,
                    'base_weight': config.base_weight,
                    'category': config.category,
                    'validation_history': [
                        {
                            'validation_date': p.evaluation_period_end,
                            'f1_score': p.f1_score,
                            'stability_score': p.stability_score,
                        }
                        for p in validation_history
                    ],
                }
                configs_with_history.append(config_dict)

            context['threshold_configs'] = configs_with_history
            context['threshold_data'] = json.dumps(
                {
                    c['indicator_code']: {
                        'level_low': float(c['level_low'] or 0),
                        'level_high': float(c['level_high'] or 0),
                    }
                    for c in configs_with_history
                },
                ensure_ascii=False,
            )

            # 获取最新验证状态
            latest_validation = ValidationSummaryModel._default_manager.filter(
                is_shadow_mode=False
            ).order_by('-run_date').first()

            if latest_validation:
                context['validation_status'] = latest_validation.status
                context['validation_status_label'] = latest_validation.get_status_display()
                context['validation_message'] = f"验证于 {latest_validation.run_date.strftime('%Y-%m-%d %H:%M')} 运行"
            else:
                context['validation_status'] = 'pending'
                context['validation_status_label'] = '待运行'
                context['validation_message'] = '尚未运行验证'

        except Exception as e:
            logger.error(f"获取阈值验证数据失败: {e}")
            context['threshold_configs'] = []
            context['threshold_data'] = '{}'
            context['validation_status'] = 'pending'
            context['validation_status_label'] = '错误'
            context['validation_message'] = str(e)

        return context


class OperationLogsAdminPageView(LoginRequiredMixin, TemplateView):
    """操作审计日志管理页 - HTML 视图（仅管理员）"""
    template_name = 'audit/operation_logs_admin.html'
    login_url = '/account/login/'

    def dispatch(self, request, *args, **kwargs):
        # 检查管理员权限
        if not IsAuditAdmin().has_permission(request, self):
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("需要审计管理员权限")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = '操作审计日志 - 管理员'
        return context


class MyOperationLogsPageView(LoginRequiredMixin, TemplateView):
    """用户操作记录页 - HTML 视图"""
    template_name = 'audit/my_operation_logs.html'
    login_url = '/account/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = '我的操作记录'
        context['current_user_id'] = self.request.user.id
        return context


# ============ MCP/SDK 操作审计日志 API Views ============

from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from .permissions import (
    IsAuditAdmin,
    OperationLogReadPermission,
    HasInternalAuditSignature,
    IsSelfOrAuditAdmin,
)
from .serializers import (
    OperationLogSerializer,
    OperationLogListSerializer,
    OperationLogDetailSerializer,
    OperationLogQuerySerializer,
    OperationLogIngestSerializer,
    OperationStatsSerializer,
    ExportOperationLogsSerializer,
)


class OperationLogPagination(PageNumberPagination):
    """操作日志分页器"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class OperationLogListView(APIView):
    """操作日志列表 API"""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    @extend_schema(
        summary="查询操作日志",
        description="查询 MCP/SDK 操作审计日志。管理员可查询全量日志，普通用户仅可查询本人日志。",
        parameters=[
            OpenApiParameter(
                name='user_id',
                type=int,
                required=False,
                description='用户 ID（普通用户会被覆盖为本人）',
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='username',
                type=str,
                required=False,
                description='用户名（模糊匹配）',
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='operation_type',
                type=str,
                required=False,
                description='操作类型（MCP_CALL/API_ACCESS/DATA_MODIFY）',
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='module',
                type=str,
                required=False,
                description='模块名',
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='mcp_tool_name',
                type=str,
                required=False,
                description='MCP 工具名',
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='response_status',
                type=int,
                required=False,
                description='响应状态码',
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
            OpenApiParameter(
                name='page',
                type=int,
                required=False,
                description='页码',
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='page_size',
                type=int,
                required=False,
                description='每页数量（最大 100）',
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: OperationLogListSerializer,
            400: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request):
        """查询操作日志列表"""
        serializer = OperationLogQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'error': '参数验证失败', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data

        # 判断是否为管理员
        is_admin = IsAuditAdmin().has_permission(request, self)

        from apps.audit.application.use_cases import (
            QueryOperationLogsUseCase,
            QueryOperationLogsRequest,
        )

        use_case = QueryOperationLogsUseCase(
            audit_repository=DjangoAuditRepository()
        )

        response = use_case.execute(
            QueryOperationLogsRequest(
                user_id=data.get('user_id'),
                username=data.get('username'),
                operation_type=data.get('operation_type'),
                module=data.get('module'),
                action=data.get('action'),
                mcp_tool_name=data.get('mcp_tool_name'),
                mcp_role=data.get('mcp_role'),
                response_status=data.get('response_status'),
                start_date=data.get('start_date'),
                end_date=data.get('end_date'),
                resource_id=data.get('resource_id'),
                source=data.get('source'),
                ordering=data.get('ordering', '-timestamp'),
                page=data.get('page', 1),
                page_size=data.get('page_size', 20),
                is_admin=is_admin,
                current_user_id=request.user.id if request.user.is_authenticated else None,
            )
        )

        if not response.success:
            return Response(
                {'success': False, 'error': response.error},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            'success': True,
            'logs': response.logs,
            'total_count': response.total_count,
            'page': response.page,
            'page_size': response.page_size,
        })


class OperationLogDetailView(APIView):
    """操作日志详情 API"""

    permission_classes = [IsAuthenticated, OperationLogReadPermission]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    @extend_schema(
        summary="获取操作日志详情",
        description="获取单条操作日志的详细信息。管理员可查看所有日志，普通用户仅可查看本人日志。",
        responses={
            200: OperationLogDetailSerializer,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request, log_id):
        """获取操作日志详情"""
        from apps.audit.application.use_cases import (
            GetOperationLogDetailUseCase,
            GetOperationLogDetailRequest,
        )

        is_admin = IsAuditAdmin().has_permission(request, self)

        use_case = GetOperationLogDetailUseCase(
            audit_repository=DjangoAuditRepository()
        )

        response = use_case.execute(
            GetOperationLogDetailRequest(
                log_id=log_id,
                current_user_id=request.user.id if request.user.is_authenticated else None,
                is_admin=is_admin,
            )
        )

        if not response.success:
            if '无权' in (response.error or ''):
                return Response(
                    {'success': False, 'error': response.error},
                    status=status.HTTP_403_FORBIDDEN
                )
            return Response(
                {'success': False, 'error': response.error},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({
            'success': True,
            'log': response.log,
        })


class OperationLogExportView(APIView):
    """操作日志导出 API（仅管理员）"""

    permission_classes = [IsAuthenticated, IsAuditAdmin]
    parser_classes = [JSONParser]
    # 禁用 DRF 的 ?format=... 渲染器协商，避免与导出格式参数冲突
    format_kwarg = None

    @extend_schema(
        summary="导出操作日志",
        description="导出操作日志为 CSV 或 JSON 格式。仅管理员可用。最多导出 10000 条，时间范围最多 90 天。",
        parameters=[
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
            OpenApiParameter(
                name='format',
                type=str,
                required=False,
                description='导出格式（csv 或 json）',
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: OpenApiTypes.STR,
            403: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request):
        """导出操作日志"""
        from apps.audit.application.use_cases import (
            ExportOperationLogsUseCase,
            ExportOperationLogsRequest,
        )

        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        export_format = request.query_params.get('format', 'csv')

        # 解析日期
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
            end = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
        except ValueError:
            return Response(
                {'success': False, 'error': '日期格式错误，应为 YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )

        use_case = ExportOperationLogsUseCase(
            audit_repository=DjangoAuditRepository()
        )

        response = use_case.execute(
            ExportOperationLogsRequest(
                start_date=start,
                end_date=end,
                format=export_format,
            )
        )

        if not response.success:
            return Response(
                {'success': False, 'error': response.error},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 设置响应头
        from django.http import HttpResponse
        content_type = 'text/csv' if export_format == 'csv' else 'application/json'
        http_response = HttpResponse(response.data, content_type=content_type)
        http_response['Content-Disposition'] = f'attachment; filename="{response.filename}"'
        return http_response


class OperationLogStatsView(APIView):
    """操作统计 API（仅管理员）"""

    permission_classes = [IsAuthenticated, IsAuditAdmin]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    @extend_schema(
        summary="获取操作统计",
        description="获取操作日志的统计数据，包括总量、错误率、平均耗时等。仅管理员可用。",
        parameters=[
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
            OpenApiParameter(
                name='group_by',
                type=str,
                required=False,
                description='分组维度（module/tool/user/status）',
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: OperationStatsSerializer,
            403: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request):
        """获取操作统计"""
        from apps.audit.application.use_cases import (
            GetOperationStatsUseCase,
            GetOperationStatsRequest,
        )

        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        group_by = request.query_params.get('group_by', 'module')

        # 解析日期
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
            end = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
        except ValueError:
            return Response(
                {'success': False, 'error': '日期格式错误，应为 YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )

        use_case = GetOperationStatsUseCase(
            audit_repository=DjangoAuditRepository()
        )

        response = use_case.execute(
            GetOperationStatsRequest(
                start_date=start,
                end_date=end,
                group_by=group_by,
            )
        )

        if not response.success:
            return Response(
                {'success': False, 'error': response.error},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(response.stats)


class OperationLogIngestView(APIView):
    """操作日志内部写入 API"""

    permission_classes = [HasInternalAuditSignature]
    parser_classes = [JSONParser]
    authentication_classes = []  # 不需要用户认证，使用签名验证

    @extend_schema(
        summary="内部写入操作日志",
        description="MCP/SDK 服务调用此接口写入操作日志。需要 X-Audit-Signature 和 X-Audit-Timestamp 头。",
        request=OperationLogIngestSerializer,
        responses={
            201: OpenApiTypes.OBJECT,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request):
        """写入操作日志"""
        serializer = OperationLogIngestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'error': '参数验证失败', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data

        from apps.audit.application.use_cases import (
            LogOperationUseCase,
            LogOperationRequest,
        )

        use_case = LogOperationUseCase(
            audit_repository=DjangoAuditRepository()
        )

        response = use_case.execute(
            LogOperationRequest(
                request_id=data.get('request_id', ''),
                user_id=data.get('user_id'),
                username=data.get('username', 'anonymous'),
                source=data.get('source', 'MCP'),
                operation_type=data.get('operation_type', 'MCP_CALL'),
                module=data.get('module', ''),
                action=data.get('action', 'READ'),
                mcp_tool_name=data.get('mcp_tool_name'),
                request_params=data.get('request_params'),
                response_status=data.get('response_status', 200),
                response_message=data.get('response_message', ''),
                error_code=data.get('error_code', ''),
                duration_ms=data.get('duration_ms'),
                ip_address=data.get('ip_address'),
                user_agent=data.get('user_agent', ''),
                client_id=data.get('client_id', ''),
                resource_type=data.get('resource_type', ''),
                resource_id=data.get('resource_id'),
                mcp_client_id=data.get('mcp_client_id', ''),
                mcp_role=data.get('mcp_role', ''),
                sdk_version=data.get('sdk_version', ''),
                request_method=data.get('request_method', 'MCP'),
                request_path=data.get('request_path', ''),
            )
        )

        if response.success:
            return Response(
                {'success': True, 'log_id': response.log_id},
                status=status.HTTP_201_CREATED
            )
        else:
            # 审计失败：返回 202 Accepted 表示请求已收到但处理不完整
            # 这样 SDK 可以通过检查 response.success 来判断是否真正成功
            return Response(
                {'success': False, 'error': response.error, 'log_id': None},
                status=status.HTTP_202_ACCEPTED
            )


# ============ Health Check API Views ============

class AuditHealthCheckView(APIView):
    """审计模块健康检查 API"""

    permission_classes = []  # 健康检查不需要认证

    @extend_schema(
        summary="审计模块健康检查",
        description="检查审计日志系统的健康状态，包括失败计数器、数据库连接和表可访问性",
        responses={
            200: OpenApiTypes.OBJECT,
            503: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request):
        """
        执行健康检查

        Query Parameters:
            warning_threshold: WARNING 状态阈值（可选，默认 10）
            error_threshold: ERROR 状态阈值（可选，默认 50）
        """
        from apps.audit.application.health_check import check_audit_health

        warning_threshold = request.query_params.get('warning_threshold')
        error_threshold = request.query_params.get('error_threshold')

        # 转换参数类型
        if warning_threshold:
            try:
                warning_threshold = int(warning_threshold)
            except ValueError:
                warning_threshold = None
        if error_threshold:
            try:
                error_threshold = int(error_threshold)
            except ValueError:
                error_threshold = None

        # 执行健康检查
        report = check_audit_health(
            warning_threshold=warning_threshold,
            error_threshold=error_threshold,
        )

        # 根据 overall_status 设置 HTTP 状态码
        http_status = status.HTTP_200_OK
        if report.overall_status == "ERROR":
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE
        elif report.overall_status == "WARNING":
            http_status = status.HTTP_200_OK  # WARNING 仍然返回 200，但 status 字段为 WARNING

        return Response(report.to_dict(), status=http_status)


class AuditFailureCounterView(APIView):
    """审计失败计数器 API"""

    permission_classes = []  # 公开访问（可配置权限）

    @extend_schema(
        summary="获取审计失败计数",
        description="获取审计日志写入失败的统计信息",
        responses={
            200: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request):
        """获取失败计数"""
        from apps.audit.infrastructure.failure_counter import get_audit_failure_counter

        counter = get_audit_failure_counter()
        stats = counter.get_failure_stats()

        return Response(stats.to_dict())

    @extend_schema(
        summary="重置审计失败计数器",
        description="重置审计失败计数器（需要管理员权限）",
        responses={
            200: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request):
        """重置计数器"""
        from apps.audit.infrastructure.failure_counter import get_audit_failure_counter

        # TODO: 添加管理员权限检查
        # if not request.user.is_staff:
        #     return Response(
        #         {'error': '需要管理员权限'},
        #         status=status.HTTP_403_FORBIDDEN
        #     )

        counter = get_audit_failure_counter()
        counter.reset()

        logger.info("Audit failure counter reset", extra={'user': request.user})

        return Response({'success': True, 'message': '计数器已重置'})


class AuditMetricsView(APIView):
    """审计模块 Prometheus 指标 API"""

    permission_classes = []  # 指标端点通常是公开的

    @extend_schema(
        summary="审计模块 Prometheus 指标",
        description="获取审计日志写入的 Prometheus 指标，包括成功/失败计数和延迟直方图",
        responses={
            200: str,
            500: dict,
        },
    )
    def get(self, request):
        """
        获取 Prometheus 格式的指标

        支持的格式：
        - prometheus: Prometheus 文本格式（默认）
        - json: JSON 格式的指标摘要
        """
        from apps.audit.infrastructure.metrics import export_metrics, get_audit_metrics_summary

        format_type = request.query_params.get('format', 'prometheus')

        if format_type == 'json':
            # 返回 JSON 格式的指标摘要
            summary = get_audit_metrics_summary()
            return Response(summary)

        else:
            # 返回 Prometheus 文本格式
            from django.http import HttpResponse

            metrics_text = export_metrics()
            return HttpResponse(
                metrics_text,
                content_type='text/plain; version=0.0.4; charset=utf-8',
                status=status.HTTP_200_OK,
            )


