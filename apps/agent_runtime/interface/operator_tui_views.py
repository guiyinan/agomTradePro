"""Typed operator-only Agent Runtime endpoints used by the TUI."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agent_runtime.application.interface_services import (
    get_operator_proposal_detail_context,
    get_operator_proposal_list_context,
    get_operator_task_list_context,
)
from apps.agent_runtime.interface.operator_tui_serializers import (
    OperatorProposalListQuerySerializer,
    OperatorTaskListQuerySerializer,
)
from apps.agent_runtime.interface.serializers import (
    AgentExecutionRecordSerializer,
    AgentGuardrailDecisionSerializer,
    AgentProposalSerializer,
    AgentTaskListSerializer,
    AgentTimelineEventSerializer,
)


class OperatorTuiPermission(BasePermission):
    """Allow staff and members of the operator group."""

    def has_permission(self, request: Request, view: Any) -> bool:
        """Return whether the authenticated actor belongs to the operator audience."""

        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_staff:
            return True
        return bool(user.groups.filter(name="operator").exists())


class OperatorTaskListAPIView(APIView):
    """List all runtime tasks for staff or operator users."""

    permission_classes = [OperatorTuiPermission]

    def get(self, request: Request) -> Response:
        """Return the operator task queue with bounded business filters."""

        serializer = OperatorTaskListQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        context = get_operator_task_list_context(
            status_filter=str(data.get("status") or ""),
            domain_filter=str(data.get("task_domain") or ""),
            search=str(data.get("search") or ""),
            attention_only=bool(data.get("attention", False)),
        )
        tasks = AgentTaskListSerializer(context["tasks"], many=True).data
        return Response(
            {
                "success": True,
                "summary": context["summary"],
                "count": len(tasks),
                "tasks": tasks,
            }
        )


class OperatorProposalListAPIView(APIView):
    """List the approval queue for staff or operator users."""

    permission_classes = [OperatorTuiPermission]

    def get(self, request: Request) -> Response:
        """Return the proposal queue with status, approval, risk and search filters."""

        serializer = OperatorProposalListQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        context = get_operator_proposal_list_context(
            status_filter=str(data.get("status") or ""),
            approval_filter=str(data.get("approval_status") or ""),
            risk_filter=str(data.get("risk_level") or ""),
            search=str(data.get("search") or ""),
        )
        proposals = AgentProposalSerializer(context["proposals"], many=True).data
        return Response(
            {
                "success": True,
                "summary": context["summary"],
                "count": len(proposals),
                "proposals": proposals,
            }
        )


class OperatorProposalDetailAPIView(APIView):
    """Read one proposal and its guardrail/execution evidence."""

    permission_classes = [OperatorTuiPermission]

    def get(self, request: Request, proposal_id: int) -> Response:
        """Return the operator proposal detail without a Classic template."""

        context = get_operator_proposal_detail_context(proposal_id=proposal_id)
        if context is None:
            return Response(
                {"success": False, "error": "Proposal 不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "success": True,
                "proposal": AgentProposalSerializer(context["proposal"]).data,
                "guardrail_decisions": AgentGuardrailDecisionSerializer(
                    context["guardrails"],
                    many=True,
                ).data,
                "execution_records": AgentExecutionRecordSerializer(
                    context["executions"],
                    many=True,
                ).data,
                "task_timeline": AgentTimelineEventSerializer(
                    context["task_timeline"],
                    many=True,
                ).data,
            }
        )
