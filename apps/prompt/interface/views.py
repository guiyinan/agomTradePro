"""
DRF Views for AI Prompt Management.

Django Rest Framework views for API endpoints.
"""

import logging
import time
import uuid
from typing import Any

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_provider.application.chat_completion import generate_chat_completion
from apps.ai_provider.application.query_services import (
    list_active_provider_summaries,
    list_supported_models,
)

from ..application.dtos import (
    ExecuteChainRequest,
    ExecutePromptRequest,
    GenerateReportRequest,
    GenerateSignalRequest,
)
from ..application.interface_services import (
    build_agent_runtime,
    build_execute_chain_use_case,
    build_execute_prompt_use_case,
    build_generate_report_use_case,
    build_generate_signal_use_case,
    get_chain_config_queryset,
    get_execution_log_queryset,
    get_prompt_template_queryset,
)
from .serializers import (
    ChainConfigCreateSerializer,
    ChainConfigSerializer,
    ChatRequestSerializer,
    ChatResponseSerializer,
    ExecuteChainResponseSerializer,
    ExecuteChainSerializer,
    ExecutePromptResponseSerializer,
    ExecutePromptSerializer,
    ExecutionLogSerializer,
    GenerateReportResponseSerializer,
    GenerateReportSerializer,
    GenerateSignalResponseSerializer,
    GenerateSignalSerializer,
    PromptTemplateCreateSerializer,
    PromptTemplateSerializer,
)

logger = logging.getLogger(__name__)


class PromptTemplateViewSet(viewsets.ModelViewSet[Any]):
    """Prompt模板管理ViewSet"""

    serializer_class = PromptTemplateSerializer
    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def get_queryset(self) -> Any:
        """Return the interface-safe prompt template queryset."""

        include_inactive = (
            self.request.query_params.get("include_inactive", "").strip().lower()
            in {"1", "true", "yes"}
            and self.request.user.is_staff
        )
        return get_prompt_template_queryset(
            name=self.request.query_params.get("name") or None,
            include_inactive=include_inactive,
        )

    def get_permissions(self) -> list[BasePermission]:
        """Restrict prompt-template mutations to staff users."""

        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Any]]:
        """根据操作选择序列化器"""
        if self.action in ["create", "update", "partial_update"]:
            return PromptTemplateCreateSerializer
        return PromptTemplateSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
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

    @action(detail=True, methods=["post"])
    def execute(self, request: Request, pk: str | None = None) -> Response:
        """执行模板"""
        self.get_object()
        serializer = ExecutePromptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        use_case = build_execute_prompt_use_case()

        request_dto = ExecutePromptRequest(
            **serializer.validated_data,
            user_id=request.user.id if request.user.is_authenticated else None,
        )
        result = use_case.execute(request_dto)

        # 返回结果
        response_serializer = ExecutePromptResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def categories(self, request: Request) -> Response:
        """获取所有分类"""
        categories = [
            {"value": "report", "label": "Report Analysis"},
            {"value": "signal", "label": "Signal Generation"},
            {"value": "analysis", "label": "Data Analysis"},
            {"value": "chat", "label": "Chat"},
        ]
        return Response(categories)


class ChainConfigViewSet(viewsets.ModelViewSet[Any]):
    """链配置管理ViewSet"""

    serializer_class = ChainConfigSerializer
    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def get_queryset(self) -> Any:
        """Return the interface-safe chain config queryset."""

        return get_chain_config_queryset()

    def get_permissions(self) -> list[BasePermission]:
        """Restrict chain configuration mutations to administrators."""

        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Any]]:
        """根据操作选择序列化器"""
        if self.action in ["create", "update", "partial_update"]:
            return ChainConfigCreateSerializer
        return ChainConfigSerializer

    @action(detail=True, methods=["post"])
    def execute(self, request: Request, pk: str | None = None) -> Response:
        """执行链"""
        self.get_object()
        serializer = ExecuteChainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        chain_use_case = build_execute_chain_use_case()

        request_dto = ExecuteChainRequest(
            **serializer.validated_data,
            user_id=request.user.id if request.user.is_authenticated else None,
        )
        result = chain_use_case.execute(request_dto)

        # 返回结果
        response_serializer = ExecuteChainResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def execution_modes(self, request: Request) -> Response:
        """获取所有执行模式"""
        modes = [
            {"value": "serial", "label": "Serial"},
            {"value": "parallel", "label": "Parallel"},
            {"value": "tool", "label": "Tool Calling"},
            {"value": "hybrid", "label": "Hybrid"},
        ]
        return Response(modes)


class ReportGenerationView(APIView):
    """报告生成视图"""

    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """生成投资分析报告"""
        serializer = GenerateReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        report_use_case = build_generate_report_use_case()

        request_dto = GenerateReportRequest(
            **serializer.validated_data,
            user_id=request.user.id if request.user.is_authenticated else None,
        )
        result = report_use_case.execute(request_dto)

        # 返回结果
        response_serializer = GenerateReportResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class SignalGenerationView(APIView):
    """信号生成视图"""

    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """生成投资信号"""
        serializer = GenerateSignalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        signal_use_case = build_generate_signal_use_case()

        request_dto = GenerateSignalRequest(
            **serializer.validated_data,
            user_id=request.user.id if request.user.is_authenticated else None,
        )
        result = signal_use_case.execute(request_dto)

        # 返回结果
        response_serializer = GenerateSignalResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class ChatView(APIView):
    """聊天视图 - 通过 ai_provider application 服务统一执行。"""

    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """聊天提问"""
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 获取参数
        message = serializer.validated_data["message"]
        session_id = serializer.validated_data.get("session_id") or self._generate_session_id()
        provider_ref = serializer.validated_data.get(
            "provider_ref", serializer.validated_data.get("provider_name")
        )
        model = serializer.validated_data.get("model")
        context = serializer.validated_data.get("context", {})

        # 构建消息
        messages = list(context.get("history", []))
        messages.append({"role": "user", "content": message})

        start_time = time.time()

        try:
            ai_response = generate_chat_completion(
                messages=messages,
                model=model,
                provider_ref=provider_ref,
                user=request.user if request.user.is_authenticated else None,
            )

            ai_status = ai_response.get("status", "error")
            if ai_status != "success":
                error_msg = ai_response.get("error_message", "AI 调用失败")
                return Response({"error": error_msg}, status=status.HTTP_502_BAD_GATEWAY)

        except Exception as e:
            logger.error("Chat AI call failed: %s", e)
            return Response({"error": f"AI 调用异常: {str(e)}"}, status=status.HTTP_502_BAD_GATEWAY)

        response_data = {
            "reply": ai_response.get("content", ""),
            "session_id": session_id,
            "metadata": {
                "provider": ai_response.get("provider_used", ""),
                "provider_scope": ai_response.get("provider_scope", "system_global"),
                "quota_charged": ai_response.get("quota_charged", False),
                "model": ai_response.get("model", ""),
                "tokens": ai_response.get("total_tokens", 0),
                "response_time_ms": int((time.time() - start_time) * 1000),
            },
        }

        response_serializer = ChatResponseSerializer(response_data)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def _generate_session_id(self) -> str:
        """生成会话ID"""

        return str(uuid.uuid4())


class ChatProvidersView(APIView):
    """获取可用的AI提供商列表"""

    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """获取所有活跃的AI提供商"""
        providers_data = list_active_provider_summaries()

        return Response(
            {
                "providers": providers_data,
                "default_provider": providers_data[0]["name"] if providers_data else None,
            }
        )


class ChatModelsView(APIView):
    """获取指定提供商的可用模型列表 - 从 ai_provider 模块读取"""

    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """获取模型列表"""
        provider_name = request.query_params.get("provider", "")
        return Response({"models": list_supported_models(provider_name)})


class AgentExecuteView(APIView):
    """Agent Runtime 统一执行入口"""

    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """执行 Agent 任务"""
        from ..domain.agent_entities import AgentExecutionRequest
        from .serializers import AgentExecuteRequestSerializer, AgentExecuteResponseSerializer

        serializer = AgentExecuteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            runtime = build_agent_runtime()

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
                "tool_calls": (
                    [
                        {
                            "tool_name": tc.tool_name,
                            "arguments": tc.arguments,
                            "success": tc.success,
                            "result": tc.result,
                            "error_message": tc.error_message,
                            "duration_ms": tc.duration_ms,
                        }
                        for tc in (response.tool_calls or [])
                    ]
                    if response.tool_calls
                    else None
                ),
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
            http_status = (
                status.HTTP_200_OK if response.success else status.HTTP_422_UNPROCESSABLE_ENTITY
            )
            return Response(resp_serializer.data, status=http_status)

        except Exception as e:
            logger.error("Agent execution failed: %s", e, exc_info=True)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ExecutionLogViewSet(viewsets.ReadOnlyModelViewSet[Any]):
    """执行日志ViewSet（只读）"""

    serializer_class = ExecutionLogSerializer
    permission_classes: list[type[BasePermission]] = [IsAdminUser]

    def get_queryset(self) -> Any:
        """获取查询集"""
        template_id = self.request.query_params.get("template_id")
        chain_id = self.request.query_params.get("chain_id")
        execution_id = self.request.query_params.get("execution_id")
        status_filter = self.request.query_params.get("status")
        return get_execution_log_queryset(
            template_id=template_id,
            chain_id=chain_id,
            execution_id=execution_id,
            status_filter=status_filter,
        )

    @action(detail=False, methods=["get"])
    def recent(self, request: Request) -> Response:
        """获取最近的日志"""
        try:
            limit = int(request.query_params.get("limit", 50))
        except (TypeError, ValueError):
            return Response(
                {"error": "limit must be an integer between 1 and 200"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not 1 <= limit <= 200:
            return Response(
                {"error": "limit must be an integer between 1 and 200"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        logs = self.get_queryset()[:limit]
        serializer = self.get_serializer(logs, many=True)
        return Response(serializer.data)


# ==================== 页面视图 ====================


@staff_member_required
def prompt_manage_view(request: HttpRequest) -> HttpResponse:
    """Prompt 模板管理页面"""
    return render(request, "prompt/manage.html")
