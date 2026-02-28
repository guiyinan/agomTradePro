"""
Interface Layer - API Views for Policy Management

定义 DRF 视图，处理 HTTP 请求和响应。
"""

import logging
from datetime import date
from typing import Optional

from django.db import models
from django.utils import timezone
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from ..domain.entities import PolicyLevel, PolicyEvent
from ..infrastructure.models import PolicyLog, RSSSourceConfigModel, PolicyLevelKeywordModel, RSSFetchLog
from ..infrastructure.repositories import DjangoPolicyRepository
from ..application.use_cases import (
    CreatePolicyEventUseCase,
    GetPolicyStatusUseCase,
    GetPolicyHistoryUseCase,
    UpdatePolicyEventUseCase,
    DeletePolicyEventUseCase,
    CreatePolicyEventInput,
    CreatePolicyEventOutput,
    PolicyStatusOutput,
    PolicyHistoryOutput,
    FetchRSSUseCase,
    FetchRSSInput,
    FetchRSSOutput,
    GetAuditQueueUseCase,
    ReviewPolicyItemUseCase,
    ReviewPolicyItemInput,
    ReviewPolicyItemOutput,
    BulkReviewUseCase,
    AutoAssignAuditsUseCase,
)
from rest_framework.permissions import IsAuthenticated
from .serializers import (
    PolicyEventSerializer,
    PolicyLogSerializer,
    PolicyStatusSerializer,
    PolicyCreateResponseSerializer,
    PolicyHistorySerializer,
    PolicyHistoryWithStatsSerializer,
    PolicyLevelField,
    RSSSourceConfigSerializer,
    RSSSourceConfigCreateSerializer,
    PolicyLevelKeywordSerializer,
    RSSFetchLogSerializer,
    RSSFetchOutputSerializer,
    RSSTriggerSerializer,
)
from .forms import PolicyEventForm, RSSSourceForm, PolicyKeywordForm

logger = logging.getLogger(__name__)


class PolicyStatusView(APIView):
    """
    政策状态视图

    GET /api/policy/status/ - 获取当前政策状态
    """

    @extend_schema(
        tags=["Policy"],
        summary="获取当前政策状态",
        description="获取当前政策档位、响应配置和操作建议",
        parameters=[
            OpenApiParameter(
                name="as_of_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description="截止日期 (YYYY-MM-DD)，默认为今天",
                required=False
            )
        ],
        responses={200: PolicyStatusSerializer}
    )
    def get(self, request):
        """
        获取当前政策状态

        Query Parameters:
            as_of_date: 截止日期（可选）
        """
        try:
            # 获取参数
            as_of_date_str = request.query_params.get("as_of_date")
            as_of_date = (
                date.fromisoformat(as_of_date_str) if as_of_date_str else None
            )

            # 执行用例
            repo = DjangoPolicyRepository()
            use_case = GetPolicyStatusUseCase(event_store=repo)
            output: PolicyStatusOutput = use_case.execute(as_of_date)

            # 序列化响应
            response_data = {
                "current_level": output.current_level.value,
                "level_name": output.level_name,
                "is_intervention_active": output.is_intervention_active,
                "is_crisis_mode": output.is_crisis_mode,
                "recommendations": output.recommendations,
                "as_of_date": output.as_of_date.isoformat(),
                # 响应配置
                "market_action": output.response_config.market_action.value,
                "cash_adjustment": output.response_config.cash_adjustment,
                "signal_pause_hours": output.response_config.signal_pause_hours,
                "requires_manual_approval": output.response_config.requires_manual_approval,
                # 最新事件
                "latest_event": None,
            }

            if output.latest_event:
                response_data["latest_event"] = {
                    "event_date": output.latest_event.event_date.isoformat(),
                    "level": output.latest_event.level.value,
                    "title": output.latest_event.title,
                    "description": output.latest_event.description,
                    "evidence_url": output.latest_event.evidence_url,
                }

            # Return response_data directly (already formatted for JSON serialization)
            return Response(response_data, status=status.HTTP_200_OK)

        except ValueError as e:
            return Response(
                {"error": f"Invalid date format: {e}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Failed to get policy status: {e}", exc_info=True)
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PolicyEventListView(APIView):
    """
    政策事件列表视图

    GET /api/policy/events/ - 获取政策事件列表
    POST /api/policy/events/ - 创建新的政策事件
    """

    @extend_schema(
        tags=["Policy"],
        summary="获取政策事件列表",
        description="获取指定日期范围内的政策事件",
        parameters=[
            OpenApiParameter(
                name="start_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description="起始日期 (YYYY-MM-DD)",
                required=True
            ),
            OpenApiParameter(
                name="end_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description="结束日期 (YYYY-MM-DD)",
                required=True
            ),
            OpenApiParameter(
                name="level",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="筛选档位 (P0/P1/P2/P3)",
                required=False
            )
        ],
        responses={200: PolicyHistorySerializer}
    )
    def get(self, request):
        """获取政策事件列表"""
        try:
            # 获取参数
            start_date_str = request.query_params.get("start_date")
            end_date_str = request.query_params.get("end_date")
            level_str = request.query_params.get("level")

            if not start_date_str or not end_date_str:
                return Response(
                    {"error": "start_date and end_date are required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)
            level = PolicyLevel(level_str) if level_str else None

            # 执行用例
            repo = DjangoPolicyRepository()
            use_case = GetPolicyHistoryUseCase(event_store=repo)
            output: PolicyHistoryOutput = use_case.execute(start_date, end_date, level)

            # 序列化响应
            events_data = [
                {
                    "event_date": e.event_date.isoformat(),
                    "level": e.level.value,
                    "title": e.title,
                    "description": e.description,
                    "evidence_url": e.evidence_url,
                }
                for e in output.events
            ]

            response_data = {
                "events": events_data,
                "total_count": output.total_count,
                "level_stats": output.level_stats,
                "start_date": output.start_date.isoformat(),
                "end_date": output.end_date.isoformat(),
            }

            serializer = PolicyHistoryWithStatsSerializer(data=response_data)
            serializer.is_valid(raise_exception=True)

            return Response(serializer.validated_data, status=status.HTTP_200_OK)

        except ValueError as e:
            return Response(
                {"error": f"Invalid parameter: {e}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Failed to get policy events: {e}", exc_info=True)
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        tags=["Policy"],
        summary="创建政策事件",
        description="创建新的政策事件记录",
        request=PolicyEventSerializer,
        responses={201: PolicyCreateResponseSerializer}
    )
    def post(self, request):
        """创建新的政策事件"""
        try:
            # 验证输入
            serializer = PolicyEventSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            # 创建输入 DTO
            input_data = CreatePolicyEventInput(
                event_date=serializer.validated_data["event_date"],
                level=serializer.validated_data["level"],
                title=serializer.validated_data["title"],
                description=serializer.validated_data["description"],
                evidence_url=serializer.validated_data["evidence_url"],
            )

            # 执行用例
            repo = DjangoPolicyRepository()

            # 创建告警服务（仅控制台输出，可在 settings 中配置更多渠道）
            from shared.infrastructure.alert_service import create_default_alert_service
            from django.conf import settings
            alert_service = create_default_alert_service(
                slack_webhook=getattr(settings, 'SLACK_WEBHOOK_URL', None),
                email_config=getattr(settings, 'ALERT_EMAIL_CONFIG', None),
                use_console=getattr(settings, 'DEBUG', True)
            )

            use_case = CreatePolicyEventUseCase(
                event_store=repo,
                alert_service=alert_service
            )
            output: CreatePolicyEventOutput = use_case.execute(input_data)

            # 构建响应
            response_data = {
                "success": output.success,
                "event": None,
                "errors": output.errors,
                "warnings": output.warnings,
                "alert_triggered": output.alert_triggered,
            }

            if output.event:
                response_data["event"] = {
                    "event_date": output.event.event_date.isoformat(),
                    "level": output.event.level.value,
                    "title": output.event.title,
                    "description": output.event.description,
                    "evidence_url": output.event.evidence_url,
                }

            status_code = (
                status.HTTP_201_CREATED if output.success
                else status.HTTP_400_BAD_REQUEST
            )

            return Response(response_data, status=status_code)

        except Exception as e:
            logger.error(f"Failed to create policy event: {e}", exc_info=True)
            return Response(
                {
                    "success": False,
                    "errors": [f"Internal server error: {str(e)}"],
                    "event": None,
                    "warnings": [],
                    "alert_triggered": False
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PolicyEventDetailView(APIView):
    """
    政策事件详情视图

    GET /api/policy/events/{date}/ - 获取指定日期的事件
    PUT /api/policy/events/{date}/ - 更新指定日期的事件（支持 ?event_id= 精确更新）
    DELETE /api/policy/events/{date}/ - 删除指定日期的事件（支持 ?event_id= 精确删除）
    """

    @extend_schema(
        tags=["Policy"],
        summary="获取指定日期的政策事件",
        description="根据日期获取政策事件详情",
        parameters=[
            OpenApiParameter(
                name="event_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.PATH,
                description="事件日期 (YYYY-MM-DD)",
                required=True
            )
        ],
        responses={200: PolicyEventSerializer}
    )
    def get(self, request, event_date: str):
        """获取指定日期的政策事件"""
        try:
            event_date_obj = date.fromisoformat(event_date)

            repo = DjangoPolicyRepository()
            event = repo.get_event_by_date(event_date_obj)

            if not event:
                return Response(
                    {"error": "Event not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

            response_data = {
                "event_date": event.event_date.isoformat(),
                "level": event.level.value,
                "title": event.title,
                "description": event.description,
                "evidence_url": event.evidence_url,
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except ValueError:
            return Response(
                {"error": "Invalid date format"},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Failed to get policy event: {e}", exc_info=True)
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        tags=["Policy"],
        summary="更新政策事件",
        description="更新指定日期的政策事件",
        parameters=[
            OpenApiParameter(
                name="event_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="事件 ID（可选，传入后优先按 ID 精确更新）",
                required=False
            )
        ],
        request=PolicyEventSerializer,
        responses={200: PolicyCreateResponseSerializer}
    )
    def put(self, request, event_date: str):
        """更新指定日期的政策事件"""
        try:
            event_date_obj = date.fromisoformat(event_date)
            event_id_raw = request.query_params.get("event_id")
            event_id = int(event_id_raw) if event_id_raw else None

            # 验证输入
            serializer = PolicyEventSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            repo = DjangoPolicyRepository()

            # 创建告警服务（仅控制台输出，可在 settings 中配置更多渠道）
            from shared.infrastructure.alert_service import create_default_alert_service
            from django.conf import settings
            alert_service = create_default_alert_service(
                slack_webhook=getattr(settings, 'SLACK_WEBHOOK_URL', None),
                email_config=getattr(settings, 'ALERT_EMAIL_CONFIG', None),
                use_console=getattr(settings, 'DEBUG', True)
            )

            use_case = UpdatePolicyEventUseCase(
                event_store=repo,
                alert_service=alert_service
            )

            output = use_case.execute(
                event_date=event_date_obj,
                level=serializer.validated_data["level"],
                title=serializer.validated_data["title"],
                description=serializer.validated_data["description"],
                evidence_url=serializer.validated_data["evidence_url"],
                event_id=event_id,
            )

            response_data = {
                "success": output.success,
                "event": None,
                "errors": output.errors,
                "warnings": output.warnings,
                "alert_triggered": output.alert_triggered,
            }

            if output.event:
                response_data["event"] = {
                    "event_date": output.event.event_date.isoformat(),
                    "level": output.event.level.value,
                    "title": output.event.title,
                    "description": output.event.description,
                    "evidence_url": output.event.evidence_url,
                }

            status_code = (
                status.HTTP_200_OK if output.success
                else status.HTTP_400_BAD_REQUEST
            )

            return Response(response_data, status=status_code)

        except ValueError as e:
            return Response(
                {"error": f"Invalid parameter: {e}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Failed to update policy event: {e}", exc_info=True)
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        tags=["Policy"],
        summary="删除政策事件",
        description="删除指定日期的政策事件（可通过 event_id 精确删除单条）",
        parameters=[
            OpenApiParameter(
                name="event_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.PATH,
                description="事件日期 (YYYY-MM-DD)",
                required=True
            ),
            OpenApiParameter(
                name="event_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="事件 ID（可选，传入后优先按 ID 精确删除）",
                required=False
            )
        ],
        responses={204: None}
    )
    def delete(self, request, event_date: str):
        """删除指定日期的政策事件"""
        try:
            event_date_obj = date.fromisoformat(event_date)
            event_id_raw = request.query_params.get("event_id")
            event_id = int(event_id_raw) if event_id_raw else None

            repo = DjangoPolicyRepository()
            use_case = DeletePolicyEventUseCase(event_store=repo)

            success, message = use_case.execute(event_date=event_date_obj, event_id=event_id)

            if success:
                return Response(status=status.HTTP_204_NO_CONTENT)
            else:
                return Response(
                    {"error": message},
                    status=status.HTTP_404_NOT_FOUND
                )

        except ValueError:
            return Response(
                {"error": "Invalid date format"},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Failed to delete policy event: {e}", exc_info=True)
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ========== RSS 相关视图 ==========

class RSSSourceConfigViewSet(viewsets.ModelViewSet):
    """RSS源配置API"""

    queryset = RSSSourceConfigModel._default_manager.all()
    serializer_class = RSSSourceConfigSerializer
    filterset_fields = ['category', 'is_active', 'parser_type']
    search_fields = ['name', 'url']

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action == 'create':
            return RSSSourceConfigCreateSerializer
        return RSSSourceConfigSerializer

    @action(detail=True, methods=['post'])
    def trigger_fetch(self, request, pk=None):
        """手动触发抓取指定源"""
        try:
            from ..application.tasks import fetch_rss_sources
            from django.conf import settings

            source = self.get_object()
            logger.info(f"Triggering RSS fetch for source: {source.name} (ID: {source.id})")

            # 调试：检查 Celery 配置
            eager_mode = getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False)
            broker_url = getattr(settings, 'CELERY_BROKER_URL', 'not set')
            logger.info(f"Celery config - ALWAYS_EAGER={eager_mode}, BROKER_URL={broker_url}")

            # 检查是否为同步模式（开发环境无 Redis）
            if eager_mode:
                # 同步执行模式
                logger.info("Running in synchronous mode (CELERY_TASK_ALWAYS_EAGER=True)")
                try:
                    result = fetch_rss_sources(source_id=source.id)
                    return Response({
                        'status': 'completed',
                        'result': result,
                        'source': source.name,
                        'message': '抓取已完成（同步模式）'
                    })
                except Exception as sync_error:
                    logger.error(f"Synchronous fetch failed: {sync_error}", exc_info=True)
                    return Response({
                        'status': 'error',
                        'error': f'抓取失败: {str(sync_error)}'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                # 异步执行模式（需要 Celery worker）
                try:
                    task = fetch_rss_sources.delay(source_id=source.id)
                    logger.info(f"Task {task.id} queued successfully")
                    return Response({
                        'status': 'triggered',
                        'task_id': task.id,
                        'source': source.name
                    })
                except Exception as celery_error:
                    logger.error(f"Celery task failed: {celery_error}", exc_info=True)
                    return Response({
                        'status': 'error',
                        'error': f'Celery任务调度失败: {str(celery_error)}. 请确保Celery worker正在运行.'
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        except Exception as e:
            logger.error(f"Failed to trigger RSS fetch: {e}", exc_info=True)
            return Response({
                'status': 'error',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def fetch_all(self, request):
        """抓取所有启用的源"""
        from ..application.tasks import fetch_rss_sources

        serializer = RSSTriggerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        task = fetch_rss_sources.delay(
            source_id=serializer.validated_data.get('source_id'),
        )

        return Response({
            'status': 'triggered',
            'task_id': task.id
        })


class RSSFetchLogViewSet(viewsets.ReadOnlyModelViewSet):
    """RSS抓取日志API（只读）"""

    queryset = RSSFetchLog._default_manager.all()
    serializer_class = RSSFetchLogSerializer
    filterset_fields = ['source', 'status']
    ordering = ['-fetched_at']

    def get_queryset(self):
        """支持通过 source__name 参数过滤"""
        queryset = super().get_queryset()
        source_name = self.request.query_params.get('source__name')
        source_id = self.request.query_params.get('source')

        if source_name:
            queryset = queryset.filter(source__name=source_name)
        elif source_id:
            queryset = queryset.filter(source_id=source_id)

        return queryset.select_related('source')


class PolicyLevelKeywordViewSet(viewsets.ModelViewSet):
    """政策档位关键词规则API"""

    queryset = PolicyLevelKeywordModel._default_manager.all()
    serializer_class = PolicyLevelKeywordSerializer
    filterset_fields = ['level', 'is_active', 'category']
    ordering = ['-weight', 'level']


# ========== HTML 页面视图 ==========

class RSSSourceListView(LoginRequiredMixin, ListView):
    """RSS源管理页面"""
    model = RSSSourceConfigModel
    template_name = 'policy/rss_manage.html'
    context_object_name = 'sources'
    paginate_by = 20

    def get_queryset(self):
        queryset = RSSSourceConfigModel._default_manager.all()
        category = self.request.GET.get('category')
        is_active = self.request.GET.get('is_active')
        search = self.request.GET.get('search')

        if category:
            queryset = queryset.filter(category=category)
        if is_active:
            queryset = queryset.filter(is_active=is_active == 'true')
        if search:
            queryset = queryset.filter(name__icontains=search)

        return queryset.order_by('category', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = RSSSourceConfigModel.CATEGORY_CHOICES
        context['selected_category'] = self.request.GET.get('category', '')
        context['selected_active'] = self.request.GET.get('is_active', '')
        context['search_query'] = self.request.GET.get('search', '')
        return context


class RSSKeywordListView(LoginRequiredMixin, ListView):
    """关键词规则管理页面"""
    model = PolicyLevelKeywordModel
    template_name = 'policy/rss_keywords.html'
    context_object_name = 'keywords'
    paginate_by = 20

    def get_queryset(self):
        queryset = PolicyLevelKeywordModel._default_manager.all()
        level = self.request.GET.get('level')
        is_active = self.request.GET.get('is_active')

        if level:
            queryset = queryset.filter(level=level)
        if is_active:
            queryset = queryset.filter(is_active=is_active == 'true')

        return queryset.order_by('-weight', 'level')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['levels'] = PolicyLevelKeywordModel.POLICY_LEVELS
        context['selected_level'] = self.request.GET.get('level', '')
        context['selected_active'] = self.request.GET.get('is_active', '')
        return context


class RSSFetchLogListView(LoginRequiredMixin, ListView):
    """抓取日志查询页面"""
    model = RSSFetchLog
    template_name = 'policy/rss_logs.html'
    context_object_name = 'logs'
    paginate_by = 50

    def get_queryset(self):
        queryset = RSSFetchLog._default_manager.select_related('source').all()
        source_id = self.request.GET.get('source')
        status_filter = self.request.GET.get('status')

        if source_id:
            queryset = queryset.filter(source_id=source_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by('-fetched_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sources'] = RSSSourceConfigModel._default_manager.all()
        context['statuses'] = RSSFetchLog.STATUS_CHOICES
        context['selected_source'] = self.request.GET.get('source', '')
        context['selected_status'] = self.request.GET.get('status', '')

        # 添加统计数据
        queryset = self.get_queryset()
        context['success_count'] = queryset.filter(status='success').count()
        context['error_count'] = queryset.filter(status='error').count()

        return context


class RSSReaderView(LoginRequiredMixin, ListView):
    """RSS阅读器页面 - 显示抓取的文章"""
    model = PolicyLog
    template_name = 'policy/rss_reader.html'
    context_object_name = 'items'
    paginate_by = 20

    def get_queryset(self):
        # 使用 rss_source 作为外键
        queryset = PolicyLog._default_manager.select_related('rss_source').all()
        source_id = self.request.GET.get('source')
        level = self.request.GET.get('level')
        category = self.request.GET.get('category')

        if source_id:
            queryset = queryset.filter(rss_source_id=source_id)
        if level:
            queryset = queryset.filter(level=level)
        if category:
            queryset = queryset.filter(info_category=category)

        # 按事件日期排序，最新的在前
        return queryset.order_by('-event_date', '-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sources'] = RSSSourceConfigModel._default_manager.all()
        context['levels'] = PolicyLog.POLICY_LEVELS
        context['categories'] = PolicyLog.INFO_CATEGORY_CHOICES
        context['selected_source'] = self.request.GET.get('source', '')
        context['selected_level'] = self.request.GET.get('level', '')
        context['selected_category'] = self.request.GET.get('category', '')

        # 统计数据
        queryset = self.get_queryset()
        from django.utils import timezone
        today = timezone.now().date()
        context['total_items'] = queryset.count()
        context['today_items'] = queryset.filter(created_at__date=today).count()
        context['p3_items'] = queryset.filter(level='P3').count()

        return context


class PolicyEventsPageView(LoginRequiredMixin, ListView):
    """Policy events list page (HTML)"""
    model = PolicyLog
    template_name = 'policy/policy_events.html'
    context_object_name = 'events'
    paginate_by = 20

    def get_queryset(self):
        queryset = PolicyLog._default_manager.all()
        level = self.request.GET.get('level')
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')

        if level:
            queryset = queryset.filter(level=level)
        if start_date:
            queryset = queryset.filter(event_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(event_date__lte=end_date)

        return queryset.order_by('-event_date', '-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['levels'] = PolicyLog.POLICY_LEVELS
        context['selected_level'] = self.request.GET.get('level', '')
        context['selected_start'] = self.request.GET.get('start_date', '')
        context['selected_end'] = self.request.GET.get('end_date', '')
        return context


class PolicyEventCreateView(LoginRequiredMixin, CreateView):
    """Create policy event without Django admin."""

    model = PolicyLog
    form_class = PolicyEventForm
    template_name = "policy/policy_event_form.html"
    success_url = reverse_lazy("policy:events-page")

    def form_valid(self, form):
        messages.success(self.request, "政策事件已创建")
        return super().form_valid(form)


class RSSSourceCreateView(LoginRequiredMixin, CreateView):
    """Create RSS source without Django admin."""

    model = RSSSourceConfigModel
    form_class = RSSSourceForm
    template_name = "policy/rss_source_form.html"
    success_url = reverse_lazy("policy:rss-manage")

    def form_valid(self, form):
        messages.success(self.request, "RSS 源已创建")
        return super().form_valid(form)


class RSSSourceUpdateView(LoginRequiredMixin, UpdateView):
    """Update RSS source without Django admin."""

    model = RSSSourceConfigModel
    form_class = RSSSourceForm
    template_name = "policy/rss_source_form.html"
    success_url = reverse_lazy("policy:rss-manage")
    pk_url_kwarg = "source_id"

    def form_valid(self, form):
        messages.success(self.request, "RSS 源已更新")
        return super().form_valid(form)


class PolicyKeywordCreateView(LoginRequiredMixin, CreateView):
    """Create policy keyword rule without Django admin."""

    model = PolicyLevelKeywordModel
    form_class = PolicyKeywordForm
    template_name = "policy/keyword_form.html"
    success_url = reverse_lazy("policy:rss-keywords")

    def form_valid(self, form):
        messages.success(self.request, "关键词规则已创建")
        return super().form_valid(form)


class PolicyKeywordUpdateView(LoginRequiredMixin, UpdateView):
    """Update policy keyword rule without Django admin."""

    model = PolicyLevelKeywordModel
    form_class = PolicyKeywordForm
    template_name = "policy/keyword_form.html"
    success_url = reverse_lazy("policy:rss-keywords")
    pk_url_kwarg = "keyword_id"

    def form_valid(self, form):
        messages.success(self.request, "关键词规则已更新")
        return super().form_valid(form)


# ========== 审核相关API视图 ==========

class AuditQueueView(APIView):
    """
    审核队列视图

    GET /api/policy/audit/queue/ - 获取待审核队列
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Audit"],
        summary="获取审核队列",
        description="获取当前用户的待审核政策列表",
        parameters=[
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="审核状态 (pending_review/auto_approved/manual_approved/rejected)",
                required=False
            ),
            OpenApiParameter(
                name="priority",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="优先级 (urgent/high/normal/low)",
                required=False
            ),
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="返回数量限制",
                required=False
            )
        ],
        responses={200: OpenApiTypes.OBJECT}
    )
    def get(self, request):
        """获取审核队列"""
        try:
            use_case = GetAuditQueueUseCase(
                policy_repository=DjangoPolicyRepository()
            )

            status_filter = request.query_params.get('status', 'pending_review')
            priority_filter = request.query_params.get('priority', None)
            limit = int(request.query_params.get('limit', 50))

            items = use_case.execute(
                user=request.user,
                status=status_filter,
                priority=priority_filter,
                limit=limit
            )

            return Response({
                'success': True,
                'items': items,
                'count': len(items)
            })

        except Exception as e:
            logger.error(f"Failed to get audit queue: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ReviewPolicyItemView(APIView):
    """
    政策审核视图

    POST /api/policy/audit/review/{id}/ - 审核单个政策
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Audit"],
        summary="审核政策条目",
        description="审核单个政策条目（通过或拒绝）",
        parameters=[
            OpenApiParameter(
                name="policy_log_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description="政策日志ID",
                required=True
            )
        ],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT}
    )
    def post(self, request, policy_log_id):
        """审核政策条目"""
        try:
            use_case = ReviewPolicyItemUseCase(
                policy_repository=DjangoPolicyRepository()
            )

            input_dto = ReviewPolicyItemInput(
                policy_log_id=policy_log_id,
                approved=request.data.get('approved', False),
                reviewer=request.user,
                notes=request.data.get('notes', ''),
                modifications=request.data.get('modifications', None)
            )

            output = use_case.execute(input_dto)

            if output.success:
                return Response({
                    'success': True,
                    'audit_status': output.audit_status.value,
                    'message': output.message
                })
            else:
                return Response({
                    'success': False,
                    'errors': output.errors
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Failed to review policy: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BulkReviewView(APIView):
    """
    批量审核视图

    POST /api/policy/audit/bulk_review/ - 批量审核政策
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Audit"],
        summary="批量审核政策",
        description="批量审核多个政策条目",
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT}
    )
    def post(self, request):
        """批量审核"""
        try:
            review_use_case = ReviewPolicyItemUseCase(
                policy_repository=DjangoPolicyRepository()
            )
            bulk_use_case = BulkReviewUseCase(review_use_case)

            results = bulk_use_case.execute(
                policy_log_ids=request.data.get('policy_log_ids', []),
                approved=request.data.get('approved', False),
                reviewer=request.user,
                notes=request.data.get('notes', '')
            )

            return Response({
                'success': True,
                'results': results
            })

        except Exception as e:
            logger.error(f"Failed to bulk review: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AutoAssignAuditsView(APIView):
    """
    自动分配审核任务视图

    POST /api/policy/audit/auto_assign/ - 自动分配审核任务
    """

    @extend_schema(
        tags=["Policy Audit"],
        summary="自动分配审核任务",
        description="将待审核的政策自动分配给审核人员",
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT}
    )
    def post(self, request):
        """自动分配审核任务"""
        try:
            use_case = AutoAssignAuditsUseCase()
            results = use_case.execute(
                max_per_user=request.data.get('max_per_user', 10)
            )

            return Response({
                'success': True,
                'results': results
            })

        except Exception as e:
            logger.error(f"Failed to auto assign: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================================
# 工作台 API 视图
# ============================================================

from ..application.use_cases import (
    GetWorkbenchSummaryUseCase,
    GetWorkbenchItemsUseCase,
    ApproveEventUseCase,
    RejectEventUseCase,
    RollbackEventUseCase,
    OverrideEventUseCase,
    GetSentimentGateStateUseCase,
    WorkbenchSummaryInput,
    WorkbenchItemsInput,
    ApproveEventInput,
    RejectEventInput,
    RollbackEventInput,
    OverrideEventInput,
    SentimentGateStateInput,
)
from ..infrastructure.repositories import WorkbenchRepository
from .serializers import (
    WorkbenchSummarySerializer,
    WorkbenchItemsQuerySerializer,
    WorkbenchItemsResponseSerializer,
    ApproveEventSerializer,
    RejectEventSerializer,
    RollbackEventSerializer,
    OverrideEventSerializer,
    ActionResponseSerializer,
    SentimentGateStateSerializer,
    IngestionConfigSerializer,
    SentimentGateConfigSerializer,
    # 新增序列化器
    WorkbenchBootstrapSerializer,
    WorkbenchFilterOptionsSerializer,
    WorkbenchTrendSerializer,
    WorkbenchFetchStatusSerializer,
    WorkbenchItemDetailSerializer,
    WorkbenchFetchInputSerializer,
    WorkbenchFetchOutputSerializer,
    WorkbenchItemSerializer,
)


class WorkbenchSummaryView(APIView):
    """
    工作台概览视图

    GET /api/policy/workbench/summary/ - 获取工作台概览数据
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="获取工作台概览",
        description="获取双闸状态、待审核数、SLA超时数等概览数据",
        responses={200: WorkbenchSummarySerializer}
    )
    def get(self, request):
        """获取工作台概览"""
        try:
            use_case = GetWorkbenchSummaryUseCase(
                workbench_repo=WorkbenchRepository()
            )
            output = use_case.execute(WorkbenchSummaryInput())

            if output.success:
                serializer = WorkbenchSummarySerializer(output.summary)
                return Response(serializer.data)
            else:
                return Response(
                    {'success': False, 'error': output.error},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        except Exception as e:
            logger.error(f"Failed to get workbench summary: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WorkbenchItemsView(APIView):
    """
    工作台事件列表视图

    GET /api/policy/workbench/items/ - 获取工作台事件列表
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="获取工作台事件列表",
        description="获取待审核/已生效/全部事件列表，支持多种筛选",
        parameters=[
            OpenApiParameter(name="tab", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY,
                           description="Tab类型: pending/effective/all", required=False),
            OpenApiParameter(name="event_type", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY,
                           description="事件类型: policy/hotspot/sentiment/mixed", required=False),
            OpenApiParameter(name="level", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY,
                           description="政策档位: P0/P1/P2/P3/PX", required=False),
            OpenApiParameter(name="gate_level", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY,
                           description="闸门等级: L0/L1/L2/L3", required=False),
            OpenApiParameter(name="asset_class", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY,
                           description="资产分类: equity/bond/commodity/fx/crypto/all", required=False),
            OpenApiParameter(name="start_date", type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY,
                           description="起始日期", required=False),
            OpenApiParameter(name="end_date", type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY,
                           description="结束日期", required=False),
            OpenApiParameter(name="search", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY,
                           description="搜索关键词", required=False),
            OpenApiParameter(name="limit", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY,
                           description="返回数量限制", required=False),
            OpenApiParameter(name="offset", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY,
                           description="偏移量", required=False),
        ],
        responses={200: WorkbenchItemsResponseSerializer}
    )
    def get(self, request):
        """获取工作台事件列表"""
        try:
            query_serializer = WorkbenchItemsQuerySerializer(data=request.query_params)
            if not query_serializer.is_valid():
                return Response(
                    {'success': False, 'errors': query_serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            input_dto = WorkbenchItemsInput(**query_serializer.validated_data)
            use_case = GetWorkbenchItemsUseCase(workbench_repo=WorkbenchRepository())
            output = use_case.execute(input_dto)

            if output.success:
                return Response({
                    'success': True,
                    'items': output.items,
                    'total': output.total
                })
            else:
                return Response(
                    {'success': False, 'error': output.error},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        except Exception as e:
            logger.error(f"Failed to get workbench items: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ApproveEventView(APIView):
    """
    审核通过视图

    POST /api/policy/workbench/items/{id}/approve/ - 审核通过事件
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="审核通过事件",
        description="审核通过指定事件，使其生效",
        request=ApproveEventSerializer,
        responses={200: ActionResponseSerializer}
    )
    def post(self, request, event_id):
        """审核通过事件"""
        try:
            serializer = ApproveEventSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {'success': False, 'errors': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            input_dto = ApproveEventInput(
                event_id=event_id,
                user_id=request.user.id,
                reason=serializer.validated_data.get('reason', '')
            )
            use_case = ApproveEventUseCase(workbench_repo=WorkbenchRepository())
            output = use_case.execute(input_dto)

            if output.success:
                return Response({
                    'success': True,
                    'event_id': output.event_id
                })
            else:
                return Response(
                    {'success': False, 'error': output.error},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error(f"Failed to approve event: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class RejectEventView(APIView):
    """
    审核拒绝视图

    POST /api/policy/workbench/items/{id}/reject/ - 审核拒绝事件
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="审核拒绝事件",
        description="审核拒绝指定事件（必须填写原因）",
        request=RejectEventSerializer,
        responses={200: ActionResponseSerializer}
    )
    def post(self, request, event_id):
        """审核拒绝事件"""
        try:
            serializer = RejectEventSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {'success': False, 'errors': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            input_dto = RejectEventInput(
                event_id=event_id,
                user_id=request.user.id,
                reason=serializer.validated_data['reason']
            )
            use_case = RejectEventUseCase(workbench_repo=WorkbenchRepository())
            output = use_case.execute(input_dto)

            if output.success:
                return Response({
                    'success': True,
                    'event_id': output.event_id
                })
            else:
                return Response(
                    {'success': False, 'error': output.error},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error(f"Failed to reject event: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class RollbackEventView(APIView):
    """
    回滚生效视图

    POST /api/policy/workbench/items/{id}/rollback/ - 回滚事件生效状态
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="回滚事件生效状态",
        description="回滚已生效事件（必须填写原因）",
        request=RollbackEventSerializer,
        responses={200: ActionResponseSerializer}
    )
    def post(self, request, event_id):
        """回滚事件生效状态"""
        try:
            serializer = RollbackEventSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {'success': False, 'errors': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            input_dto = RollbackEventInput(
                event_id=event_id,
                user_id=request.user.id,
                reason=serializer.validated_data['reason']
            )
            use_case = RollbackEventUseCase(workbench_repo=WorkbenchRepository())
            output = use_case.execute(input_dto)

            if output.success:
                return Response({
                    'success': True,
                    'event_id': output.event_id
                })
            else:
                return Response(
                    {'success': False, 'error': output.error},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error(f"Failed to rollback event: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class OverrideEventView(APIView):
    """
    临时豁免视图

    POST /api/policy/workbench/items/{id}/override/ - 临时豁免事件
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="临时豁免事件",
        description="临时豁免事件（必须填写原因，可选修改档位）",
        request=OverrideEventSerializer,
        responses={200: ActionResponseSerializer}
    )
    def post(self, request, event_id):
        """临时豁免事件"""
        try:
            serializer = OverrideEventSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {'success': False, 'errors': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            input_dto = OverrideEventInput(
                event_id=event_id,
                user_id=request.user.id,
                reason=serializer.validated_data['reason'],
                new_level=serializer.validated_data.get('new_level')
            )
            use_case = OverrideEventUseCase(workbench_repo=WorkbenchRepository())
            output = use_case.execute(input_dto)

            if output.success:
                return Response({
                    'success': True,
                    'event_id': output.event_id
                })
            else:
                return Response(
                    {'success': False, 'error': output.error},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error(f"Failed to override event: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SentimentGateStateView(APIView):
    """
    热点情绪闸门状态视图

    GET /api/policy/sentiment-gate/state/ - 获取热点情绪闸门状态
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="获取热点情绪闸门状态",
        description="获取指定资产类的热点情绪闸门状态",
        parameters=[
            OpenApiParameter(name="asset_class", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY,
                           description="资产分类: equity/bond/commodity/fx/crypto/all", required=False),
        ],
        responses={200: SentimentGateStateSerializer}
    )
    def get(self, request):
        """获取热点情绪闸门状态"""
        try:
            asset_class = request.query_params.get('asset_class', 'all')
            input_dto = SentimentGateStateInput(asset_class=asset_class)
            use_case = GetSentimentGateStateUseCase(workbench_repo=WorkbenchRepository())
            output = use_case.execute(input_dto)

            if output.success:
                return Response({
                    'success': True,
                    'asset_class': output.asset_class,
                    'gate_level': output.gate_level,
                    'heat_score': output.heat_score,
                    'sentiment_score': output.sentiment_score,
                    'max_position_cap': output.max_position_cap,
                    'thresholds': output.thresholds
                })
            else:
                return Response(
                    {'success': False, 'error': output.error},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error(f"Failed to get sentiment gate state: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class IngestionConfigView(APIView):
    """
    摄入配置视图

    GET /api/policy/ingestion-config/ - 获取摄入配置
    PUT /api/policy/ingestion-config/ - 更新摄入配置
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="获取摄入配置",
        description="获取政策摄入配置（自动生效、SLA 等）",
        responses={200: IngestionConfigSerializer}
    )
    def get(self, request):
        """获取摄入配置"""
        try:
            workbench_repo = WorkbenchRepository()
            config = workbench_repo.get_ingestion_config()
            serializer = IngestionConfigSerializer({
                'auto_approve_enabled': config.auto_approve_enabled,
                'auto_approve_min_level': config.auto_approve_min_level,
                'auto_approve_threshold': config.auto_approve_threshold,
                'p23_sla_hours': config.p23_sla_hours,
                'normal_sla_hours': config.normal_sla_hours,
                'version': config.version,
            })
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Failed to get ingestion config: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        tags=["Policy Workbench"],
        summary="更新摄入配置",
        description="更新政策摄入配置",
        request=IngestionConfigSerializer,
        responses={200: IngestionConfigSerializer}
    )
    def put(self, request):
        """更新摄入配置"""
        try:
            serializer = IngestionConfigSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {'success': False, 'errors': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            workbench_repo = WorkbenchRepository()
            config = workbench_repo.update_ingestion_config(
                **serializer.validated_data,
                updated_by=request.user
            )

            return Response({
                'success': True,
                'version': config.version
            })

        except Exception as e:
            logger.error(f"Failed to update ingestion config: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SentimentGateConfigView(APIView):
    """
    闸门配置视图

    GET /api/policy/sentiment-gate-config/ - 获取闸门配置列表
    PUT /api/policy/sentiment-gate-config/ - 更新闸门配置
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="获取闸门配置列表",
        description="获取所有资产类的闸门配置",
        responses={200: SentimentGateConfigSerializer(many=True)}
    )
    def get(self, request):
        """获取闸门配置列表"""
        try:
            workbench_repo = WorkbenchRepository()
            configs = workbench_repo.get_all_gate_configs()
            data = [
                {
                    'asset_class': c.asset_class,
                    'heat_l1_threshold': c.heat_l1_threshold,
                    'heat_l2_threshold': c.heat_l2_threshold,
                    'heat_l3_threshold': c.heat_l3_threshold,
                    'sentiment_l1_threshold': c.sentiment_l1_threshold,
                    'sentiment_l2_threshold': c.sentiment_l2_threshold,
                    'sentiment_l3_threshold': c.sentiment_l3_threshold,
                    'max_position_cap_l2': c.max_position_cap_l2,
                    'max_position_cap_l3': c.max_position_cap_l3,
                    'enabled': c.enabled,
                    'version': c.version,
                }
                for c in configs
            ]
            return Response(data)

        except Exception as e:
            logger.error(f"Failed to get gate configs: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        tags=["Policy Workbench"],
        summary="更新闸门配置",
        description="更新指定资产类的闸门配置",
        request=SentimentGateConfigSerializer,
        responses={200: SentimentGateConfigSerializer}
    )
    def put(self, request):
        """更新闸门配置"""
        try:
            serializer = SentimentGateConfigSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {'success': False, 'errors': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            from ..infrastructure.models import SentimentGateConfig

            asset_class = serializer.validated_data['asset_class']

            # 尝试获取已存在的配置
            try:
                config = SentimentGateConfig.objects.get(asset_class=asset_class)
                # 更新已存在的配置
                for key, value in serializer.validated_data.items():
                    if key != 'asset_class':
                        setattr(config, key, value)
                config.updated_by = request.user
                config.version = models.F('version') + 1
                config.save()
                config.refresh_from_db()  # 刷新以获取实际的 version 值
                created = False
            except SentimentGateConfig.DoesNotExist:
                # 创建新配置
                config = SentimentGateConfig.objects.create(
                    **serializer.validated_data,
                    updated_by=request.user,
                    version=1
                )
                created = True

            return Response({
                'success': True,
                'asset_class': config.asset_class,
                'version': config.version,
                'created': created
            })

        except Exception as e:
            logger.error(f"Failed to update gate config: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================================
# 工作台页面视图
# ============================================================

class WorkbenchBootstrapView(APIView):
    """
    工作台启动数据视图

    GET /api/policy/workbench/bootstrap/ - 获取工作台初始化所需的所有数据
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="获取工作台启动数据",
        description="一次性获取工作台初始化所需的所有数据：summary, default_list, filter_options, trend, fetch_status",
        responses={200: WorkbenchBootstrapSerializer}
    )
    def get(self, request):
        """获取工作台启动数据"""
        try:
            from .serializers import (
                WorkbenchBootstrapSerializer,
                WorkbenchFilterOptionsSerializer,
                WorkbenchTrendSerializer,
                WorkbenchFetchStatusSerializer,
            )
            from ..infrastructure.models import RSSSourceConfigModel, RSSFetchLog

            # 1. 获取 summary
            summary_use_case = GetWorkbenchSummaryUseCase(workbench_repo=WorkbenchRepository())
            summary_output = summary_use_case.execute(WorkbenchSummaryInput())
            summary_data = WorkbenchSummarySerializer(summary_output.summary).data if summary_output.success else {}

            # 2. 获取 default list (tab=all, limit=50)
            items_input = WorkbenchItemsInput(tab='all', limit=50, offset=0)
            items_use_case = GetWorkbenchItemsUseCase(workbench_repo=WorkbenchRepository())
            items_output = items_use_case.execute(items_input)
            default_list = items_output.items if items_output.success else []

            # 3. 获取 filter options
            event_types = [
                {'value': choice[0], 'label': choice[1]}
                for choice in PolicyLog.EVENT_TYPE_CHOICES
            ]
            levels = [
                {'value': choice[0], 'label': choice[1]}
                for choice in PolicyLog.POLICY_LEVELS
            ]
            gate_levels = [
                {'value': choice[0], 'label': choice[1]}
                for choice in PolicyLog.GATE_LEVEL_CHOICES
            ]
            asset_classes = ['equity', 'bond', 'commodity', 'fx', 'crypto', 'all']
            sources = list(RSSSourceConfigModel.objects.filter(is_active=True).values('id', 'name', 'category'))

            filter_options = {
                'event_types': event_types,
                'levels': levels,
                'gate_levels': gate_levels,
                'asset_classes': asset_classes,
                'sources': sources,
            }

            # 4. 获取 trend data (近30天)
            from datetime import timedelta
            from django.db.models import Count, Avg
            from django.utils import timezone

            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=30)

            # 情绪趋势
            sentiment_trend = list(
                PolicyLog.objects.filter(
                    gate_effective=True,
                    event_type__in=['hotspot', 'sentiment', 'mixed'],
                    event_date__gte=start_date,
                    event_date__lte=end_date,
                )
                .extra(select={'day': 'date(event_date)'})
                .values('day')
                .annotate(
                    avg_heat=Avg('heat_score'),
                    avg_sentiment=Avg('sentiment_score'),
                    count=Count('id')
                )
                .order_by('day')
            )

            # 生效事件趋势
            events_trend = list(
                PolicyLog.objects.filter(
                    gate_effective=True,
                    event_date__gte=start_date,
                    event_date__lte=end_date,
                )
                .extra(select={'day': 'date(event_date)'})
                .values('day', 'event_type')
                .annotate(count=Count('id'))
                .order_by('day', 'event_type')
            )

            trend = {
                'sentiment_recent_30d': sentiment_trend,
                'effective_events_recent_30d': events_trend,
            }

            # 5. 获取 fetch status
            last_fetch_log = RSSFetchLog.objects.order_by('-fetched_at').first()
            recent_errors = list(
                RSSFetchLog.objects.filter(status='error')
                .order_by('-fetched_at')[:5]
                .values('fetched_at', 'source__name', 'error_message')
            )

            fetch_status = {
                'last_fetch_at': last_fetch_log.fetched_at if last_fetch_log else None,
                'last_fetch_status': last_fetch_log.status if last_fetch_log else None,
                'recent_fetch_errors': recent_errors,
            }

            return Response({
                'success': True,
                'summary': summary_data,
                'default_list': default_list,
                'filter_options': filter_options,
                'trend': trend,
                'fetch_status': fetch_status,
            })

        except Exception as e:
            logger.error(f"Failed to get workbench bootstrap: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WorkbenchItemDetailView(APIView):
    """
    工作台事件详情视图

    GET /api/policy/workbench/items/{id}/ - 获取单个事件的详细信息
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="获取事件详情",
        description="获取单个事件的完整详情，包括来源信息",
        parameters=[
            OpenApiParameter(name="id", type=OpenApiTypes.INT, location=OpenApiParameter.PATH,
                           description="事件ID", required=True),
        ],
        responses={200: WorkbenchItemDetailSerializer}
    )
    def get(self, request, event_id):
        """获取事件详情"""
        try:
            from .serializers import WorkbenchItemDetailSerializer

            event = PolicyLog.objects.filter(pk=event_id).first()
            if not event:
                return Response(
                    {'success': False, 'error': 'Event not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 获取来源名称
            rss_source_name = None
            if event.rss_source_id:
                source = RSSSourceConfigModel.objects.filter(pk=event.rss_source_id).first()
                if source:
                    rss_source_name = source.name

            # 获取生效人名称
            effective_by_name = None
            if event.effective_by_id:
                from django.contrib.auth.models import User
                user = User.objects.filter(pk=event.effective_by_id).first()
                if user:
                    effective_by_name = user.username

            # 获取审核人名称
            reviewed_by_name = None
            if event.reviewed_by_id:
                reviewed_by_name = event.reviewed_by.username if event.reviewed_by else None

            data = {
                'id': event.id,
                'event_date': event.event_date,
                'event_type': event.event_type,
                'level': event.level,
                'gate_level': event.gate_level,
                'title': event.title,
                'description': event.description,
                'evidence_url': event.evidence_url,
                'ai_confidence': event.ai_confidence,
                'heat_score': event.heat_score,
                'sentiment_score': event.sentiment_score,
                'structured_data': event.structured_data or {},
                'gate_effective': event.gate_effective,
                'effective_at': event.effective_at,
                'effective_by_id': event.effective_by_id,
                'effective_by_name': effective_by_name,
                'audit_status': event.audit_status,
                'reviewed_by_id': event.reviewed_by_id,
                'reviewed_by_name': reviewed_by_name,
                'reviewed_at': event.reviewed_at,
                'review_notes': event.review_notes or '',
                'asset_class': event.asset_class,
                'asset_scope': event.asset_scope or [],
                'rollback_reason': event.rollback_reason or '',
                'rss_source_id': event.rss_source_id,
                'rss_source_name': rss_source_name,
                'rss_item_guid': event.rss_item_guid,
                'created_at': event.created_at,
                'updated_at': event.updated_at if hasattr(event, 'updated_at') else None,
            }

            return Response({
                'success': True,
                'item': data,
            })

        except Exception as e:
            logger.error(f"Failed to get event detail: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WorkbenchFetchView(APIView):
    """
    工作台抓取触发视图

    POST /api/policy/workbench/fetch/ - 触发 RSS 抓取
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Policy Workbench"],
        summary="触发RSS抓取",
        description="触发RSS源抓取，可选择抓取全部或指定源",
        request=WorkbenchFetchInputSerializer,
        responses={200: WorkbenchFetchOutputSerializer}
    )
    def post(self, request):
        """触发RSS抓取"""
        try:
            from .serializers import WorkbenchFetchInputSerializer, WorkbenchFetchOutputSerializer

            serializer = WorkbenchFetchInputSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {'success': False, 'errors': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            source_id = serializer.validated_data.get('source_id')
            force_refetch = serializer.validated_data.get('force_refetch', False)

            # 调用抓取用例
            fetch_input = FetchRSSInput(
                source_id=source_id,
                force_refetch=force_refetch
            )
            fetch_use_case = FetchRSSUseCase(
                rss_repo=RSSRepository(),
                policy_repo=DjangoPolicyRepository()
            )
            output = fetch_use_case.execute(fetch_input)

            return Response({
                'success': output.success,
                'mode': 'single' if source_id else 'all',
                'task_id': None,  # 同步执行，无 task_id
                'sources_processed': output.sources_processed,
                'total_items': output.total_items,
                'new_policy_events': output.new_policy_events,
                'errors': output.errors,
                'details': output.details,
            })

        except Exception as e:
            logger.error(f"Failed to trigger fetch: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WorkbenchView(LoginRequiredMixin, ListView):
    """
    工作台页面视图

    GET /policy/workbench/ - 工作台页面
    """
    template_name = "policy/workbench.html"
    model = PolicyLog
    context_object_name = "events"
    paginate_by = 50

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "工作台"
        context['event_types'] = PolicyLog.EVENT_TYPE_CHOICES
        context['levels'] = PolicyLog.POLICY_LEVELS
        context['gate_levels'] = PolicyLog.GATE_LEVEL_CHOICES
        return context

