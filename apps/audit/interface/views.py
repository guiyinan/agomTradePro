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
                    'run_date': summary.created_at,
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
            ).order_by('-created_at').first()

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
            ).order_by('-created_at').first()

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
            else:
                # 没有验证记录时的默认数据
                context['total_indicators'] = 0
                context['approved_indicators'] = 0
                context['pending_indicators'] = 0
                context['rejected_indicators'] = 0
                context['avg_f1_score'] = 0
                context['avg_stability_score'] = 0
                context['indicator_reports'] = []

        except Exception as e:
            logger.error(f"获取指标表现数据失败: {e}")
            # 设置默认值
            context['total_indicators'] = 0
            context['indicator_reports'] = []

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

            # 获取最新验证状态
            latest_validation = ValidationSummaryModel._default_manager.filter(
                is_shadow_mode=False
            ).order_by('-created_at').first()

            if latest_validation:
                context['validation_status'] = latest_validation.status
                context['validation_status_label'] = latest_validation.get_status_display()
                context['validation_message'] = f"验证于 {latest_validation.created_at.strftime('%Y-%m-%d %H:%M')} 运行"
            else:
                context['validation_status'] = 'pending'
                context['validation_status_label'] = '待运行'
                context['validation_message'] = '尚未运行验证'

        except Exception as e:
            logger.error(f"获取阈值验证数据失败: {e}")
            context['threshold_configs'] = []
            context['validation_status'] = 'pending'
            context['validation_status_label'] = '错误'
            context['validation_message'] = str(e)

        return context

