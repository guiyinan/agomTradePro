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

import logging

logger = logging.getLogger(__name__)


class AIClientFactory:
    """AI客户端工厂 - 从 ai_provider 模块获取真实 AI 客户端"""

    def __init__(self):
        from apps.ai_provider.infrastructure.repositories import AIProviderRepository
        self._provider_repo = AIProviderRepository()

    def get_client(self, provider_name=None):
        """获取AI客户端（支持指定提供商或自动 failover）"""
        from apps.ai_provider.infrastructure.adapters import (
            OpenAICompatibleAdapter, AIFailoverHelper
        )

        if provider_name:
            # 使用指定的提供商
            provider = self._provider_repo.get_by_name(provider_name)
            if provider:
                api_key = self._provider_repo.get_api_key(provider)
                return OpenAICompatibleAdapter(
                    base_url=provider.base_url,
                    api_key=api_key,
                    default_model=provider.default_model,
                    api_mode=getattr(provider, 'api_mode', None),
                    fallback_enabled=getattr(provider, 'fallback_enabled', None),
                )
            logger.warning("Provider '%s' not found, falling back to failover", provider_name)

        # 使用所有活跃提供商构建 failover 链
        providers = self._provider_repo.get_active_providers()
        if not providers:
            logger.error("No active AI providers configured")
            return _NullAIClient()

        provider_dicts = []
        for p in providers:
            provider_dicts.append({
                "name": p.name,
                "base_url": p.base_url,
                "api_key_decrypted": self._provider_repo.get_api_key(p),
                "default_model": p.default_model,
                "api_mode": getattr(p, 'api_mode', None),
                "fallback_enabled": getattr(p, 'fallback_enabled', None),
            })

        return _FailoverAIClient(AIFailoverHelper(provider_dicts))


class _FailoverAIClient:
    """Failover AI 客户端包装器，适配 chat_completion 接口"""

    def __init__(self, failover_helper):
        self._helper = failover_helper

    def chat_completion(self, messages, model=None, temperature=0.7, max_tokens=None):
        return self._helper.chat_completion_with_failover(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )


class _NullAIClient:
    """无可用提供商时返回的空客户端"""

    def chat_completion(self, messages, model=None, temperature=0.7, max_tokens=None):
        return {
            "status": "error",
            "content": "",
            "provider_used": "",
            "model": model or "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost": 0.0,
            "error_message": "没有可用的AI提供商，请先在 ai_provider 模块配置",
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
    """聊天视图 - 通过 AIClientFactory 统一走 ai_provider 模块"""

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

        # 构建消息
        messages = context.get('history', [])
        messages.append({'role': 'user', 'content': message})

        # 通过 AIClientFactory 获取客户端（自动 failover）
        import time
        start_time = time.time()

        try:
            ai_factory = AIClientFactory()
            ai_client = ai_factory.get_client(provider_name)
            ai_response = ai_client.chat_completion(
                messages=messages,
                model=model,
            )

            ai_status = ai_response.get('status', 'error')
            if ai_status != 'success':
                error_msg = ai_response.get('error_message', 'AI 调用失败')
                return Response({
                    'error': error_msg
                }, status=status.HTTP_502_BAD_GATEWAY)

        except Exception as e:
            logger.error("Chat AI call failed: %s", e)
            return Response({
                'error': f'AI 调用异常: {str(e)}'
            }, status=status.HTTP_502_BAD_GATEWAY)

        response_data = {
            'reply': ai_response.get('content', ''),
            'session_id': session_id,
            'metadata': {
                'provider': ai_response.get('provider_used', ''),
                'model': ai_response.get('model', ''),
                'tokens': ai_response.get('total_tokens', 0),
                'response_time_ms': int((time.time() - start_time) * 1000),
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
    """获取指定提供商的可用模型列表 - 从 ai_provider 模块读取"""

    def get(self, request):
        """获取模型列表"""
        provider_name = request.query_params.get('provider', '')

        from apps.ai_provider.infrastructure.repositories import AIProviderRepository
        from apps.ai_provider.domain.services import AICostCalculator

        provider_repo = AIProviderRepository()

        if provider_name:
            # 按提供商名称查询
            provider = provider_repo.get_by_name(provider_name)
            if provider:
                # 优先从 extra_config 读取 supported_models
                extra = provider.extra_config or {}
                models = extra.get('supported_models')
                if not models:
                    # 取同 provider_type 的所有已知模型 + 当前 default_model
                    models = self._models_by_type(provider.provider_type)
                    if provider.default_model not in models:
                        models.insert(0, provider.default_model)
                return Response({'models': models})

            # 按 provider_type 查询（兼容传入 "openai" / "deepseek" 等类型名）
            providers = provider_repo.get_by_type(provider_name)
            if providers:
                models = list({p.default_model for p in providers})
                type_models = self._models_by_type(provider_name)
                for m in type_models:
                    if m not in models:
                        models.append(m)
                return Response({'models': models})

        # 无指定提供商：汇总所有活跃提供商的模型
        active_providers = provider_repo.get_active_providers()
        models = list({p.default_model for p in active_providers})
        # 补充定价表中的已知模型
        for m in AICostCalculator.MODEL_PRICING:
            if m not in models:
                models.append(m)

        return Response({'models': models})

    @staticmethod
    def _models_by_type(provider_type: str) -> list:
        """从定价表中按 provider_type 归类已知模型"""
        from apps.ai_provider.domain.services import AICostCalculator

        type_prefixes = {
            'openai': 'gpt-',
            'deepseek': 'deepseek-',
            'qwen': 'qwen-',
            'moonshot': 'moonshot-',
        }
        prefix = type_prefixes.get(provider_type, '')
        if not prefix:
            return []
        return [m for m in AICostCalculator.MODEL_PRICING if m.startswith(prefix)]


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

