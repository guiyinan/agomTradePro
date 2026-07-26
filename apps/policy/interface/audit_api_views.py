"""Policy audit API views."""

import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import ValidationError
from rest_framework.views import APIView

from ..application.audit_use_cases import ReviewerProtocol
from ..application.repository_provider import get_current_policy_repository
from ..application.use_cases import (
    AutoAssignAuditsUseCase,
    BulkReviewUseCase,
    GetAuditQueueUseCase,
    ReviewPolicyItemInput,
    ReviewPolicyItemUseCase,
)
from .serializers import (
    AuditQueueQuerySerializer,
    AutoAssignAuditsRequestSerializer,
    BulkReviewRequestSerializer,
    ReviewPolicyItemRequestSerializer,
)

logger = logging.getLogger(__name__)
ViewMethod = TypeVar("ViewMethod", bound=Callable[..., Any])


def typed_schema(*args: Any, **kwargs: Any) -> Callable[[ViewMethod], ViewMethod]:
    """Narrow drf-spectacular's dynamically typed decorator."""

    return cast(Callable[[ViewMethod], ViewMethod], extend_schema(*args, **kwargs))


class AuditQueueView(APIView):
    """
    审核队列视图

    GET /api/policy/audit/queue/ - 获取待审核队列
    """

    permission_classes = [IsAdminUser]

    @typed_schema(
        tags=["Policy Audit"],
        summary="获取审核队列",
        description="获取当前用户的待审核政策列表",
        parameters=[
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="审核状态 (pending_review/auto_approved/manual_approved/rejected)",
                required=False,
            ),
            OpenApiParameter(
                name="priority",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="优先级 (urgent/high/normal/low)",
                required=False,
            ),
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="返回数量限制",
                required=False,
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        """获取审核队列"""
        try:
            serializer = AuditQueueQuerySerializer(data=request.query_params)
            serializer.is_valid(raise_exception=True)
            use_case = GetAuditQueueUseCase(policy_repository=get_current_policy_repository())

            items = use_case.execute(
                user=cast(ReviewerProtocol, request.user),
                status=cast(str, serializer.validated_data["status"]),
                priority=cast(str | None, serializer.validated_data.get("priority")),
                limit=cast(int, serializer.validated_data["limit"]),
            )

            return Response({"success": True, "items": items, "count": len(items)})

        except ValidationError as exc:
            return Response(
                {"success": False, "errors": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.error("Failed to get audit queue", exc_info=True)
            return Response(
                {"success": False, "error": "audit_queue_unavailable"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ReviewPolicyItemView(APIView):
    """
    政策审核视图

    POST /api/policy/audit/review/{id}/ - 审核单个政策
    """

    permission_classes = [IsAdminUser]

    @typed_schema(
        tags=["Policy Audit"],
        summary="审核政策条目",
        description="审核单个政策条目（通过或拒绝）",
        parameters=[
            OpenApiParameter(
                name="policy_log_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description="政策日志ID",
                required=True,
            )
        ],
        request=ReviewPolicyItemRequestSerializer,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request, policy_log_id: int) -> Response:
        """审核政策条目"""
        try:
            serializer = ReviewPolicyItemRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            use_case = ReviewPolicyItemUseCase(policy_repository=get_current_policy_repository())
            input_dto = ReviewPolicyItemInput(
                policy_log_id=policy_log_id,
                approved=cast(bool, serializer.validated_data["approved"]),
                reviewer=cast(ReviewerProtocol, request.user),
                notes=cast(str, serializer.validated_data.get("notes", "")),
                modifications=cast(
                    dict[str, object] | None,
                    serializer.validated_data.get("modifications"),
                ),
            )

            output = use_case.execute(input_dto)

            if output.success:
                return Response(
                    {
                        "success": True,
                        "audit_status": output.audit_status.value,
                        "message": output.message,
                    }
                )
            return Response(
                {"success": False, "errors": output.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except ValidationError as exc:
            return Response(
                {"success": False, "errors": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.error("Failed to review policy", exc_info=True)
            return Response(
                {"success": False, "error": "policy_review_failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class BulkReviewView(APIView):
    """
    批量审核视图

    POST /api/policy/audit/bulk_review/ - 批量审核政策
    """

    permission_classes = [IsAdminUser]

    @typed_schema(
        tags=["Policy Audit"],
        summary="批量审核政策",
        description="批量审核多个政策条目",
        request=BulkReviewRequestSerializer,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        """批量审核"""
        try:
            serializer = BulkReviewRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            review_use_case = ReviewPolicyItemUseCase(
                policy_repository=get_current_policy_repository()
            )
            bulk_use_case = BulkReviewUseCase(review_use_case)
            results = bulk_use_case.execute(
                policy_log_ids=cast(list[int], serializer.validated_data["policy_log_ids"]),
                approved=cast(bool, serializer.validated_data["approved"]),
                reviewer=cast(ReviewerProtocol, request.user),
                notes=cast(str, serializer.validated_data.get("notes", "")),
            )

            return Response({"success": results["failed"] == 0, "results": results})

        except ValidationError as exc:
            return Response(
                {"success": False, "errors": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.error("Failed to bulk review", exc_info=True)
            return Response(
                {"success": False, "error": "bulk_policy_review_failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AutoAssignAuditsView(APIView):
    """
    自动分配审核任务视图

    POST /api/policy/audit/auto_assign/ - 自动分配审核任务
    """

    permission_classes = [IsAdminUser]

    @typed_schema(
        tags=["Policy Audit"],
        summary="自动分配审核任务",
        description="将待审核的政策自动分配给审核人员",
        request=AutoAssignAuditsRequestSerializer,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        """自动分配审核任务"""
        try:
            serializer = AutoAssignAuditsRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            use_case = AutoAssignAuditsUseCase()
            results = use_case.execute(
                max_per_user=cast(int, serializer.validated_data["max_per_user"])
            )

            return Response({"success": True, "results": results})

        except ValidationError as exc:
            return Response(
                {"success": False, "errors": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.error("Failed to auto assign audits", exc_info=True)
            return Response(
                {"success": False, "error": "audit_auto_assign_failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
