"""
DRF Views for AI Prompt Management.

Django Rest Framework views for API endpoints.
"""

from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from ..infrastructure.models import PromptTemplateORM, ChainConfigORM, PromptExecutionLogORM
from ..infrastructure.repositories import (
    DjangoPromptRepository, DjangoChainRepository, DjangoExecutionLogRepository
)
from ..infrastructure.adapters.macro_adapter import MacroDataAdapter
from ..infrastructure.adapters.regime_adapter import RegimeDataAdapter
from ..infrastructure.adapters.function_registry import create_builtin_tools
from ..application.use_cases import (
    ExecutePromptUseCase, ExecuteChainUseCase,
    GenerateReportUseCase, GenerateSignalUseCase
)
from .serializers import (
    PromptTemplateSerializer, PromptTemplateCreateSerializer,
    ChainConfigSerializer, ChainConfigCreateSerializer,
    ExecutePromptSerializer, ExecutePromptResponseSerializer,
    ExecuteChainSerializer, ExecuteChainResponseSerializer,
    GenerateReportSerializer, GenerateReportResponseSerializer,
    GenerateSignalSerializer, GenerateSignalResponseSerializer,
    ChatRequestSerializer, ChatResponseSerializer,
    ExecutionLogSerializer
)


# 依赖注入工厂
class AIClientFactory:
    """AI客户端工厂（简化实现）"""

    def __init__(self):
        # 实际使用时应该从ai_provider模块获取
        self._providers = {}

    def get_client(self, provider_name=None):
        """获取AI客户端"""
        # 简化实现
        return MockAIClient()


class MockAIClient:
    """模拟AI客户端"""

    def chat_completion(self, messages, model, temperature, max_tokens):
        """模拟聊天完成"""
        return {
            "status": "success",
            "content": "这是模拟的AI响应内容",
            "provider_used": "mock",
            "model": model,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "estimated_cost": 0.001
        }


class PromptTemplateViewSet(viewsets.ModelViewSet):
    """Prompt模板管理ViewSet"""

    queryset = PromptTemplateORM._default_manager.filter(is_active=True)
    serializer_class = PromptTemplateSerializer

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action in ['create', 'update']:
            return PromptTemplateCreateSerializer
        return PromptTemplateSerializer

    def create(self, request, *args, **kwargs):
        """创建模板后返回稳定的 JSON 结构。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template = serializer.save()
        return Response(
            {
                "id": template.id,
                "name": template.name,
                "category": template.category.value,
                "version": template.version,
                "template_content": template.template_content,
                "system_prompt": template.system_prompt,
                "placeholders": [
                    {
                        "name": p.name,
                        "type": p.type.value,
                        "description": p.description,
                        "default_value": p.default_value,
                        "required": p.required,
                        "function_name": p.function_name,
                        "function_params": p.function_params,
                    }
                    for p in template.placeholders
                ],
                "temperature": template.temperature,
                "max_tokens": template.max_tokens,
                "description": template.description,
                "is_active": template.is_active,
                "created_at": template.created_at.isoformat() if template.created_at else None,
                "updated_at": None,
                "last_used_at": None,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """执行模板"""
        template = self.get_object()
        serializer = ExecutePromptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 创建用例
        ai_factory = AIClientFactory()
        macro_adapter = MacroDataAdapter()
        regime_adapter = RegimeDataAdapter()
        use_case = ExecutePromptUseCase(
            prompt_repository=DjangoPromptRepository(),
            execution_log_repository=DjangoExecutionLogRepository(),
            ai_client_factory=ai_factory,
            macro_adapter=macro_adapter,
            regime_adapter=regime_adapter
        )

        # 执行
        result = use_case.execute(serializer.validated_data)

        # 返回结果
        response_serializer = ExecutePromptResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def categories(self, request):
        """获取所有分类"""
        categories = [
            {'value': 'report', 'label': 'Report Analysis'},
            {'value': 'signal', 'label': 'Signal Generation'},
            {'value': 'analysis', 'label': 'Data Analysis'},
            {'value': 'chat', 'label': 'Chat'},
        ]
        return Response(categories)


class ChainConfigViewSet(viewsets.ModelViewSet):
    """链配置管理ViewSet"""

    queryset = ChainConfigORM._default_manager.filter(is_active=True)
    serializer_class = ChainConfigSerializer

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action in ['create', 'update']:
            return ChainConfigCreateSerializer
        return ChainConfigSerializer

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """执行链"""
        chain = self.get_object()
        serializer = ExecuteChainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 创建用例
        ai_factory = AIClientFactory()
        macro_adapter = MacroDataAdapter()
        regime_adapter = RegimeDataAdapter()

        prompt_use_case = ExecutePromptUseCase(
            prompt_repository=DjangoPromptRepository(),
            execution_log_repository=DjangoExecutionLogRepository(),
            ai_client_factory=ai_factory,
            macro_adapter=macro_adapter,
            regime_adapter=regime_adapter
        )
        chain_use_case = ExecuteChainUseCase(
            chain_repository=DjangoChainRepository(),
            prompt_use_case=prompt_use_case
        )

        # 执行
        result = chain_use_case.execute(serializer.validated_data)

        # 返回结果
        response_serializer = ExecuteChainResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def execution_modes(self, request):
        """获取所有执行模式"""
        modes = [
            {'value': 'serial', 'label': 'Serial'},
            {'value': 'parallel', 'label': 'Parallel'},
            {'value': 'tool', 'label': 'Tool Calling'},
            {'value': 'hybrid', 'label': 'Hybrid'},
        ]
        return Response(modes)


class ReportGenerationView(APIView):
    """报告生成视图"""

    def post(self, request):
        """生成投资分析报告"""
        serializer = GenerateReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 创建用例
        ai_factory = AIClientFactory()
        macro_adapter = MacroDataAdapter()
        regime_adapter = RegimeDataAdapter()

        prompt_use_case = ExecutePromptUseCase(
            prompt_repository=DjangoPromptRepository(),
            execution_log_repository=DjangoExecutionLogRepository(),
            ai_client_factory=ai_factory,
            macro_adapter=macro_adapter,
            regime_adapter=regime_adapter
        )
        chain_use_case = ExecuteChainUseCase(
            chain_repository=DjangoChainRepository(),
            prompt_use_case=prompt_use_case
        )
        report_use_case = GenerateReportUseCase(chain_use_case=chain_use_case)

        # 执行
        result = report_use_case.execute(serializer.validated_data)

        # 返回结果
        response_serializer = GenerateReportResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class SignalGenerationView(APIView):
    """信号生成视图"""

    def post(self, request):
        """生成投资信号"""
        serializer = GenerateSignalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 创建用例
        ai_factory = AIClientFactory()
        macro_adapter = MacroDataAdapter()
        regime_adapter = RegimeDataAdapter()

        prompt_use_case = ExecutePromptUseCase(
            prompt_repository=DjangoPromptRepository(),
            execution_log_repository=DjangoExecutionLogRepository(),
            ai_client_factory=ai_factory,
            macro_adapter=macro_adapter,
            regime_adapter=regime_adapter
        )
        chain_use_case = ExecuteChainUseCase(
            chain_repository=DjangoChainRepository(),
            prompt_use_case=prompt_use_case
        )
        signal_use_case = GenerateSignalUseCase(chain_use_case=chain_use_case)

        # 执行
        result = signal_use_case.execute(serializer.validated_data)

        # 返回结果
        response_serializer = GenerateSignalResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class ChatView(APIView):
    """聊天视图 - 支持多提供商和模型切换"""

    def post(self, request):
        """聊天提问"""
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 获取参数
        message = serializer.validated_data['message']
        session_id = serializer.validated_data.get('session_id') or self._generate_session_id()
        provider_name = serializer.validated_data.get('provider_name')
        model = serializer.validated_data.get('model')
        context = serializer.validated_data.get('context', {})

        # 获取AI提供商
        from apps.ai_provider.infrastructure.repositories import AIProviderRepository
        provider_repo = AIProviderRepository()

        # 如果指定了提供商，使用指定的；否则使用默认的
        if provider_name:
            provider = provider_repo.get_by_name(provider_name)
        else:
            # 获取优先级最高的活跃提供商
            active_providers = provider_repo.get_active_providers()
            provider = active_providers[0] if active_providers else None

        if not provider:
            return Response({
                'error': '没有可用的AI提供商，请先配置'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # 使用提供商的默认模型或请求中指定的模型
        model_to_use = model or provider.default_model

        # 构建消息
        messages = context.get('history', [])
        messages.append({'role': 'user', 'content': message})

        # 调用AI（使用模拟实现，实际应使用真实AI客户端）
        import time
        start_time = time.time()

        # TODO: 实际实现时替换为真实的AI调用
        # from apps.ai_provider.infrastructure.adapters import OpenAIAdapter
        # ai_adapter = OpenAIAdapter(provider.base_url, provider.api_key)
        # response = ai_adapter.chat_completion(messages, model_to_use, 0.7, None)

        # 模拟响应
        response_data = {
            'reply': f"[{provider.name} - {model_to_use}] 收到您的问题：{message}",
            'session_id': session_id,
            'metadata': {
                'provider': provider.name,
                'model': model_to_use,
                'tokens': 100,
                'response_time_ms': int((time.time() - start_time) * 1000)
            }
        }

        response_serializer = ChatResponseSerializer(response_data)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def _generate_session_id(self):
        """生成会话ID"""
        import uuid
        return str(uuid.uuid4())


class ChatProvidersView(APIView):
    """获取可用的AI提供商列表"""

    def get(self, request):
        """获取所有活跃的AI提供商"""
        from apps.ai_provider.infrastructure.repositories import AIProviderRepository

        provider_repo = AIProviderRepository()
        providers = provider_repo.get_active_providers()

        providers_data = []
        for p in providers:
            providers_data.append({
                'name': p.name,
                'provider_type': p.provider_type,
                'default_model': p.default_model,
                'is_active': p.is_active,
                'priority': p.priority,
                'display_label': f"{p.name} ({p.default_model})"
            })

        return Response({
            'providers': providers_data,
            'default_provider': providers_data[0]['name'] if providers_data else None
        })


class ChatModelsView(APIView):
    """获取指定提供商的可用模型列表"""

    def get(self, request):
        """获取模型列表"""
        provider_name = request.query_params.get('provider', '')

        # 简化实现：返回预设的模型列表
        # 实际应该从AI提供商API获取可用模型
        models_map = {
            'openai': ['gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo'],
            'deepseek': ['deepseek-chat', 'deepseek-coder'],
            'qwen': ['qwen-turbo', 'qwen-plus', 'qwen-max'],
            'moonshot': ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k'],
        }

        if provider_name and provider_name in models_map:
            models = models_map[provider_name]
        else:
            # 默认返回所有模型
            models = ['gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo',
                     'deepseek-chat', 'deepseek-coder',
                     'qwen-turbo', 'qwen-plus', 'qwen-max',
                     'moonshot-v1-8k', 'moonshot-v1-32k']

        return Response({'models': models})


class ExecutionLogViewSet(viewsets.ReadOnlyModelViewSet):
    """执行日志ViewSet（只读）"""

    queryset = PromptExecutionLogORM._default_manager.all()
    serializer_class = ExecutionLogSerializer

    def get_queryset(self):
        """获取查询集"""
        queryset = super().get_queryset()

        # 过滤参数
        template_id = self.request.query_params.get('template_id')
        chain_id = self.request.query_params.get('chain_id')
        execution_id = self.request.query_params.get('execution_id')
        status_filter = self.request.query_params.get('status')

        if template_id:
            queryset = queryset.filter(template_id=template_id)
        if chain_id:
            queryset = queryset.filter(chain_id=chain_id)
        if execution_id:
            queryset = queryset.filter(execution_id=execution_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by('-created_at')

    @action(detail=False, methods=['get'])
    def recent(self, request):
        """获取最近的日志"""
        limit = int(request.query_params.get('limit', 50))
        logs = self.get_queryset()[:limit]
        serializer = self.get_serializer(logs, many=True)
        return Response(serializer.data)


# ==================== 页面视图 ====================

def prompt_manage_view(request):
    """Prompt 模板管理页面"""
    return render(request, 'prompt/manage.html')

