"""
API Views for AI Provider Management.

DRF ViewSet for CRUD operations via AJAX.
遵循项目架构约束：Interface 层调用 Application 层，不直接访问 Infrastructure 层。
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from ...application.use_cases import (
    ListProvidersUseCase,
    CreateProviderUseCase,
    UpdateProviderUseCase,
    DeleteProviderUseCase,
    ToggleProviderUseCase,
    GetProviderStatsUseCase,
    GetOverallStatsUseCase,
    ListUsageLogsUseCase,
)
from ...infrastructure.models import AIProviderConfig, AIUsageLog
from ..serializers import (
    AIProviderConfigSerializer,
    AIProviderConfigCreateSerializer,
    AIUsageLogSerializer,
)


class AIProviderConfigViewSet(viewsets.ModelViewSet):
    """
    AI提供商配置 API ViewSet

    提供增删改查接口，用于前端模态窗口操作。
    通过 Application 层编排业务逻辑。
    """
    queryset = AIProviderConfig._default_manager.all().order_by('priority', 'name')
    serializer_class = AIProviderConfigSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action in ['create', 'update', 'partial_update']:
            return AIProviderConfigCreateSerializer
        return AIProviderConfigSerializer

    def list(self, request, *args, **kwargs):
        """获取提供商列表，带今日统计数据"""
        use_case = ListProvidersUseCase()
        providers = use_case.execute(include_inactive=True)

        # 转换为序列化器格式
        serializer = self.get_serializer(self.get_queryset(), many=True)
        provider_data_dict = {p['id']: p for p in serializer.data}

        # 用 DTO 中的统计数据更新
        result = []
        for dto in providers:
            data = provider_data_dict.get(dto.id)
            if data:
                data.update({
                    'today_requests': dto.today_requests,
                    'today_cost': str(dto.today_cost),
                    'month_requests': dto.month_requests,
                    'month_cost': str(dto.month_cost),
                })
                result.append(data)

        return Response(result)

    def create(self, request, *args, **kwargs):
        """创建新提供商"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            use_case = CreateProviderUseCase()
            provider = use_case.execute(**serializer.validated_data)
            return_response_serializer = AIProviderConfigSerializer(provider)
            return Response(return_response_serializer.data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        """更新提供商"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            use_case = UpdateProviderUseCase()
            provider = use_case.execute(instance.id, **serializer.validated_data)
            return_response_serializer = AIProviderConfigSerializer(provider)
            return Response(return_response_serializer.data)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        """删除提供商"""
        try:
            use_case = DeleteProviderUseCase()
            use_case.execute(pk=self.get_object().id)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """切换启用/禁用状态"""
        try:
            use_case = ToggleProviderUseCase()
            provider = use_case.execute(pk=pk)
            serializer = AIProviderConfigSerializer(provider)
            return Response(serializer.data)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'], url_path='test-connection')
    def test_connection(self, request, pk=None):
        """测试 AI 提供商连接是否可用"""
        from ...infrastructure.repositories import AIProviderRepository
        from ...infrastructure.adapters import OpenAICompatibleAdapter

        provider_repo = AIProviderRepository()
        provider = provider_repo.get_by_id(pk)
        if provider is None:
            return Response({'error': f'Provider {pk} not found'}, status=status.HTTP_404_NOT_FOUND)

        api_key = provider_repo.get_api_key(provider)
        if not api_key:
            return Response({
                'status': 'error',
                'error_message': 'API Key 未配置',
                'response_time_ms': 0,
            })

        try:
            adapter = OpenAICompatibleAdapter(
                base_url=provider.base_url,
                api_key=api_key,
                default_model=provider.default_model,
                api_mode=provider.api_mode,
                fallback_enabled=provider.fallback_enabled,
            )
            result = adapter.chat_completion(
                messages=[{"role": "user", "content": "Hi, reply with 'OK' only."}],
                max_tokens=10,
                temperature=0,
            )
            return Response({
                'status': result.get('status', 'error'),
                'content': result.get('content', ''),
                'model': result.get('model', ''),
                'response_time_ms': result.get('response_time_ms', 0),
                'total_tokens': result.get('total_tokens', 0),
                'error_message': result.get('error_message', ''),
                'request_type': result.get('request_type', ''),
                'fallback_used': result.get('fallback_used', False),
            })
        except ImportError:
            return Response({
                'status': 'error',
                'error_message': 'openai 库未安装',
                'response_time_ms': 0,
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'error_message': str(e),
                'response_time_ms': 0,
            })

    @action(detail=True, methods=['get'])
    def usage_stats(self, request, pk=None):
        """获取使用统计"""
        try:
            use_case = GetProviderStatsUseCase()
            dto = use_case.execute(pk=pk)

            return Response({
                'provider_id': dto.provider_id,
                'provider_name': dto.provider_name,
                'today_usage': {
                    'total_requests': dto.today_requests,
                    'total_cost': dto.today_cost,
                },
                'month_usage': {
                    'total_requests': dto.month_requests,
                    'total_cost': dto.month_cost,
                },
                'usage_by_date': dto.usage_by_date,
                'model_stats': dto.model_stats,
            })
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['get'])
    def overall_stats(self, request):
        """获取总体统计"""
        use_case = GetOverallStatsUseCase()
        dto = use_case.execute()

        return Response({
            'total_providers': dto.total_providers,
            'active_providers': dto.active_providers,
            'total_requests_today': dto.total_requests_today,
            'total_cost_today': dto.total_cost_today,
        })


class AIUsageLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    AI调用日志 API ViewSet

    只读接口，用于查看日志。
    通过 Application 层获取数据。
    """
    queryset = AIUsageLog._default_manager.all().order_by('-created_at')
    serializer_class = AIUsageLogSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        """支持过滤的日志列表"""
        provider_id = request.query_params.get('provider')
        provider_id = int(provider_id) if provider_id else None
        status_filter = request.query_params.get('status')

        use_case = ListUsageLogsUseCase()
        logs = use_case.execute(
            provider_id=provider_id,
            status=status_filter,
            limit=100,
        )

        # 转换为序列化器格式
        result = []
        for dto in logs:
            result.append({
                'id': dto.id,
                'provider': dto.provider_id,
                'provider_name': dto.provider_name,
                'model': dto.model,
                'request_type': dto.request_type,
                'prompt_tokens': dto.prompt_tokens,
                'completion_tokens': dto.completion_tokens,
                'total_tokens': dto.total_tokens,
                'estimated_cost': str(dto.estimated_cost),
                'response_time_ms': dto.response_time_ms,
                'status': dto.status,
                'error_message': dto.error_message,
                'created_at': dto.created_at.isoformat(),
            })

        return Response(result)

