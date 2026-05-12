"""Policy workbench API views."""

import logging

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.repository_provider import (
    get_current_policy_repository,
    get_policy_workbench_interface_service,
    get_rss_repository,
    get_workbench_repository,
)
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
    WorkbenchItemDetailSerializer,
    WorkbenchItemsQuerySerializer,
    WorkbenchItemsResponseSerializer,
    WorkbenchSummarySerializer,
)

logger = logging.getLogger(__name__)

def _workbench_repository():
    return get_workbench_repository()


def _policy_repository():
    return get_current_policy_repository()


def _rss_repository():
    return get_rss_repository()


def _workbench_interface_service():
    """Return the workbench interface service."""

    return get_policy_workbench_interface_service()

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
                workbench_repo=_workbench_repository()
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
            use_case = GetWorkbenchItemsUseCase(workbench_repo=_workbench_repository())
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
            use_case = ApproveEventUseCase(workbench_repo=_workbench_repository())
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
            use_case = RejectEventUseCase(workbench_repo=_workbench_repository())
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
            use_case = RollbackEventUseCase(workbench_repo=_workbench_repository())
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
            use_case = OverrideEventUseCase(workbench_repo=_workbench_repository())
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
            use_case = GetSentimentGateStateUseCase(workbench_repo=_workbench_repository())
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
            workbench_repo = _workbench_repository()
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

            workbench_repo = _workbench_repository()
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
            return Response(_workbench_interface_service().list_gate_configs())

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

            return Response(
                _workbench_interface_service().upsert_gate_config(
                    payload=serializer.validated_data,
                    updated_by_id=request.user.id,
                )
            )

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
            bootstrap = _workbench_interface_service().get_workbench_bootstrap()
            summary = bootstrap['summary']
            return Response({
                'success': True,
                'summary': WorkbenchSummarySerializer(summary).data if summary else {},
                'default_list': bootstrap['default_list'],
                'filter_options': bootstrap['filter_options'],
                'trend': bootstrap['trend'],
                'fetch_status': bootstrap['fetch_status'],
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
            item = _workbench_interface_service().get_workbench_item_detail(event_id)
            if item is None:
                return Response(
                    {'success': False, 'error': 'Event not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            return Response({
                'success': True,
                'item': item,
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
            from .serializers import WorkbenchFetchInputSerializer

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
                rss_repository=_rss_repository(),
                policy_repository=_policy_repository()
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

