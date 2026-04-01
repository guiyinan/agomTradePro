"""Policy event API views."""

import logging
from datetime import date

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.use_cases import (
    CreatePolicyEventInput,
    CreatePolicyEventOutput,
    CreatePolicyEventUseCase,
    DeletePolicyEventUseCase,
    GetPolicyHistoryUseCase,
    GetPolicyStatusUseCase,
    PolicyHistoryOutput,
    PolicyStatusOutput,
    UpdatePolicyEventUseCase,
)
from ..domain.entities import PolicyLevel
from ..infrastructure.repositories import DjangoPolicyRepository
from .serializers import (
    PolicyCreateResponseSerializer,
    PolicyEventSerializer,
    PolicyHistorySerializer,
    PolicyHistoryWithStatsSerializer,
    PolicyStatusSerializer,
)

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
            from django.conf import settings

            from shared.infrastructure.alert_service import create_default_alert_service
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

        except ValidationError as e:
            return Response(
                {
                    "success": False,
                    "errors": e.detail,
                    "event": None,
                    "warnings": [],
                    "alert_triggered": False,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
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
            from django.conf import settings

            from shared.infrastructure.alert_service import create_default_alert_service
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

