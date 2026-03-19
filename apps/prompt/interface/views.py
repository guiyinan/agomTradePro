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

from apps.ai_provider.infrastructure.client_factory import AIClientFactory

logger = logging.getLogger(__name__)


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
        provider_ref = serializer.validated_data.get('provider_ref', serializer.validated_data.get('provider_name'))
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
            ai_client = ai_factory.get_client(provider_ref)
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


class AgentExecuteView(APIView):
    """Agent Runtime 统一执行入口"""

    def post(self, request):
        """执行 Agent 任务"""
        from .serializers import AgentExecuteRequestSerializer, AgentExecuteResponseSerializer
        from ..application.agent_runtime import AgentRuntime
        from ..application.context_builders import (
            ContextBundleBuilder,
            MacroContextProvider,
            RegimeContextProvider,
            PortfolioContextProvider,
            SignalContextProvider,
            AssetPoolContextProvider,
        )
        from ..application.tool_execution import create_agent_tool_registry
        from ..application.trace_logging import AgentExecutionLogger
        from ..domain.agent_entities import AgentExecutionRequest

        serializer = AgentExecuteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            # 构建依赖
            ai_factory = AIClientFactory()
            macro_adapter = MacroDataAdapter()
            regime_adapter = RegimeDataAdapter()

            # 构建 portfolio/signal/asset_pool providers（按需加载）
            portfolio_provider = None
            signal_provider = None
            asset_pool_provider = None
            try:
                from apps.strategy.infrastructure.providers import (
                    DjangoPortfolioDataProvider,
                    DjangoSignalProvider,
                    DjangoAssetPoolProvider,
                )
                portfolio_provider = DjangoPortfolioDataProvider()
                signal_provider = DjangoSignalProvider()
                asset_pool_provider = DjangoAssetPoolProvider()
            except ImportError:
                logger.warning("Strategy providers not available, portfolio/signal/asset_pool context disabled")

            # 构建工具注册表
            tool_registry = create_agent_tool_registry(
                macro_adapter=macro_adapter,
                regime_adapter=regime_adapter,
                portfolio_provider=portfolio_provider,
                signal_provider=signal_provider,
                asset_pool_provider=asset_pool_provider,
            )

            # 构建上下文构建器
            context_builder = ContextBundleBuilder()
            context_builder.register_provider(MacroContextProvider(macro_adapter))
            context_builder.register_provider(RegimeContextProvider(regime_adapter))
            if portfolio_provider:
                context_builder.register_provider(PortfolioContextProvider(portfolio_provider))
            if signal_provider:
                context_builder.register_provider(SignalContextProvider(signal_provider))
            if asset_pool_provider:
                context_builder.register_provider(AssetPoolContextProvider(asset_pool_provider))

            # 构建执行日志器
            execution_logger = AgentExecutionLogger(
                execution_log_repository=DjangoExecutionLogRepository()
            )

            # 构建 Runtime
            runtime = AgentRuntime(
                ai_client_factory=ai_factory,
                tool_registry=tool_registry,
                context_builder=context_builder,
                execution_logger=execution_logger,
            )

            # 构建执行请求
            agent_request = AgentExecutionRequest(
                task_type=data["task_type"],
                user_input=data["user_input"],
                provider_ref=data.get("provider_ref"),
                model=data.get("model"),
                temperature=data.get("temperature"),
                max_tokens=data.get("max_tokens"),
                context_scope=data.get("context_scope"),
                context_params=data.get("context_params"),
                tool_names=data.get("tool_names"),
                response_schema=data.get("response_schema"),
                max_rounds=data.get("max_rounds", 4),
                session_id=data.get("session_id"),
                system_prompt=data.get("system_prompt"),
                metadata=data.get("metadata"),
            )

            # 执行
            response = runtime.execute(agent_request)

            # 序列化响应
            response_data = {
                "success": response.success,
                "final_answer": response.final_answer,
                "structured_output": response.structured_output,
                "used_context": response.used_context,
                "tool_calls": [
                    {
                        "tool_name": tc.tool_name,
                        "arguments": tc.arguments,
                        "success": tc.success,
                        "result": tc.result,
                        "error_message": tc.error_message,
                        "duration_ms": tc.duration_ms,
                    }
                    for tc in (response.tool_calls or [])
                ] if response.tool_calls else None,
                "turn_count": response.turn_count,
                "provider_used": response.provider_used,
                "model_used": response.model_used,
                "total_tokens": response.total_tokens,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "estimated_cost": response.estimated_cost,
                "response_time_ms": response.response_time_ms,
                "error_message": response.error_message,
                "execution_id": response.execution_id,
            }

            resp_serializer = AgentExecuteResponseSerializer(response_data)
            http_status = status.HTTP_200_OK if response.success else status.HTTP_422_UNPROCESSABLE_ENTITY
            return Response(resp_serializer.data, status=http_status)

        except Exception as e:
            logger.error("Agent execution failed: %s", e, exc_info=True)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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
