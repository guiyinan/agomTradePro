"""Policy audit API views."""

import logging

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.repository_provider import get_current_policy_repository
from ..application.use_cases import (
    AutoAssignAuditsUseCase,
    BulkReviewUseCase,
    GetAuditQueueUseCase,
    ReviewPolicyItemInput,
    ReviewPolicyItemUseCase,
)

logger = logging.getLogger(__name__)

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
                policy_repository=get_current_policy_repository()
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
                policy_repository=get_current_policy_repository()
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
                policy_repository=get_current_policy_repository()
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

