"""Policy workbench API views."""

import logging

from django.db import models
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.use_cases import (
    ApproveEventInput,
    ApproveEventUseCase,
    FetchRSSInput,
    FetchRSSUseCase,
    GetSentimentGateStateUseCase,
    GetWorkbenchItemsUseCase,
    GetWorkbenchSummaryUseCase,
    OverrideEventInput,
    OverrideEventUseCase,
    RejectEventInput,
    RejectEventUseCase,
    RollbackEventInput,
    RollbackEventUseCase,
    SentimentGateStateInput,
    WorkbenchItemsInput,
    WorkbenchSummaryInput,
)
from ..infrastructure.models import PolicyLog, RSSFetchLog, RSSSourceConfigModel
from ..infrastructure.repositories import (
    DjangoPolicyRepository,
    RSSRepository,
    WorkbenchRepository,
)
from .serializers import (
    ActionResponseSerializer,
    ApproveEventSerializer,
    IngestionConfigSerializer,
    OverrideEventSerializer,
    RejectEventSerializer,
    RollbackEventSerializer,
    SentimentGateConfigSerializer,
    SentimentGateStateSerializer,
    WorkbenchBootstrapSerializer,
    WorkbenchFetchInputSerializer,
    WorkbenchFetchOutputSerializer,
    WorkbenchFetchStatusSerializer,
    WorkbenchFilterOptionsSerializer,
    WorkbenchItemDetailSerializer,
    WorkbenchItemSerializer,
    WorkbenchItemsQuerySerializer,
    WorkbenchItemsResponseSerializer,
    WorkbenchSummarySerializer,
    WorkbenchTrendSerializer,
)

logger = logging.getLogger(__name__)

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
            from ..infrastructure.models import RSSFetchLog, RSSSourceConfigModel
            from .serializers import (
                WorkbenchBootstrapSerializer,
                WorkbenchFetchStatusSerializer,
                WorkbenchFilterOptionsSerializer,
                WorkbenchTrendSerializer,
            )

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

            from django.db.models import Avg, Count
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
                rss_repository=RSSRepository(),
                policy_repository=DjangoPolicyRepository()
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

