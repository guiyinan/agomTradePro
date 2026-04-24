"""
DRF Views for Agent Runtime API.

WP-M1-06: API Endpoints (025-026)
WP-M3-01: Proposal lifecycle endpoints
FROZEN: Only endpoints explicitly listed in the contract are exposed.
See: docs/plans/ai-native/schema-contract.md
"""

import logging
from typing import Any, Dict, Optional

from django.apps import apps as django_apps
from django.db.models import Q
from django.http import Http404
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.agent_runtime.application.proposal_use_cases import (
    ApproveProposalUseCase,
    CreateProposalInput,
    CreateProposalUseCase,
    ExecuteProposalUseCase,
    GetProposalUseCase,
    GuardrailBlockedError,
    InvalidProposalTransitionError,
    RejectProposalUseCase,
    SubmitProposalForApprovalUseCase,
)
from apps.agent_runtime.application.interface_services import (
    get_dashboard_executions_payload,
    get_dashboard_guardrails_payload,
    get_dashboard_proposals_payload,
    get_dashboard_summary_payload,
    get_dashboard_task_detail_payload,
    get_needs_attention_tasks,
    get_proposal_model,
    get_task_for_actor,
    get_task_artifacts,
    get_task_models_by_ids,
    get_task_queryset_for_actor,
    get_task_request_id,
    get_task_timeline_events,
)
from apps.agent_runtime.application.use_cases import (
    CancelTaskInput,
    CancelTaskUseCase,
    CreateTaskInput,
    CreateTaskUseCase,
    GetTaskUseCase,
    ListTasksInput,
    ListTasksUseCase,
    ResumeTaskInput,
    ResumeTaskUseCase,
)
from apps.agent_runtime.domain.entities import EventSource, TaskDomain, TaskStatus
from apps.agent_runtime.domain.services import InvalidStateTransitionError
from apps.agent_runtime.interface.serializers import (
    AgentArtifactSerializer,
    AgentExecutionRecordSerializer,
    AgentGuardrailDecisionSerializer,
    AgentProposalCreateSerializer,
    AgentProposalSerializer,
    AgentTaskCreateSerializer,
    AgentTaskListQuerySerializer,
    AgentTaskListSerializer,
    AgentTaskSerializer,
    AgentTimelineEventSerializer,
)

logger = logging.getLogger(__name__)

AgentArtifactModel = django_apps.get_model("agent_runtime", "AgentArtifactModel")
AgentExecutionRecordModel = django_apps.get_model("agent_runtime", "AgentExecutionRecordModel")
AgentGuardrailDecisionModel = django_apps.get_model("agent_runtime", "AgentGuardrailDecisionModel")
AgentProposalModel = django_apps.get_model("agent_runtime", "AgentProposalModel")
AgentTaskModel = django_apps.get_model("agent_runtime", "AgentTaskModel")
AgentTimelineEventModel = django_apps.get_model("agent_runtime", "AgentTimelineEventModel")


class IsStaffOrOperator(BasePermission):
    """Allow access only to staff users or users in the 'operator' group."""

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_staff:
            return True
        return request.user.groups.filter(name="operator").exists()


def build_error_response(
    request_id: str,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> Response:
    """
    Build an error response following the FROZEN error contract.

    Error contract format (from schema-contract.md:151):
    {
        "request_id": "atr_20260316_000001",
        "success": false,
        "error_code": "invalid_task_domain",
        "message": "Unsupported task_domain.",
        "details": {...}  // Optional additional context
    }
    """
    response_data = {
        "request_id": request_id,
        "success": False,
        "error_code": error_code,
        "message": message,
    }
    if details:
        response_data["details"] = details

    return Response(response_data, status=status_code)


def generate_request_id() -> str:
    """Generate a unique request ID for error responses."""
    from apps.agent_runtime.application.use_cases import generate_request_id as gen_rid
    return gen_rid()


def _build_validation_error_response(
    request_id: str,
    exc: drf_serializers.ValidationError,
) -> Response:
    """Normalize DRF serializer validation errors to the frozen contract."""
    return build_error_response(
        request_id=request_id,
        error_code="validation_error",
        message="Request validation failed",
        details=exc.detail if hasattr(exc, "detail") else None,
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _serialize_task_like(task_obj: Any) -> dict[str, Any]:
    """Serialize either a model instance or a domain/mock task object."""
    if isinstance(task_obj, AgentTaskModel):
        return AgentTaskSerializer(task_obj).data

    def _enum_value(value: Any) -> Any:
        return getattr(value, "value", value)

    created_at = getattr(task_obj, "created_at", None)
    updated_at = getattr(task_obj, "updated_at", None)
    return {
        "id": getattr(task_obj, "id", None),
        "request_id": getattr(task_obj, "request_id", None),
        "schema_version": getattr(task_obj, "schema_version", "v1"),
        "task_domain": _enum_value(getattr(task_obj, "task_domain", None)),
        "task_type": getattr(task_obj, "task_type", None),
        "status": _enum_value(getattr(task_obj, "status", None)),
        "input_payload": getattr(task_obj, "input_payload", {}) or {},
        "current_step": getattr(task_obj, "current_step", None),
        "last_error": getattr(task_obj, "last_error", None),
        "requires_human": getattr(task_obj, "requires_human", False),
        "created_by": getattr(task_obj, "created_by", None),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        "steps_count": 0,
        "proposals_count": 0,
        "artifacts_count": 0,
        "timeline_events_count": 0,
    }


class AgentTaskViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API ViewSet for AgentTask operations.

    FROZEN: Only read operations and specific actions are allowed.
    No direct PUT/PATCH/DELETE - all state changes go through use cases.

    Allowed operations:
    - GET /tasks/ - List tasks
    - POST /tasks/ - Create task (via perform_create)
    - GET /tasks/{id}/ - Get task detail
    - POST /tasks/{id}/resume/ - Resume task
    - POST /tasks/{id}/cancel/ - Cancel task
    - GET /tasks/{id}/timeline/ - Get timeline events
    - GET /tasks/{id}/artifacts/ - Get artifacts
    - GET /tasks/needs_attention/ - Get tasks needing attention

    All responses include request_id for tracing.
    """

    permission_classes = [IsAuthenticated]
    lookup_field = "pk"

    def get_queryset(self):
        """Return queryset with user filtering."""
        return get_task_queryset_for_actor(
            user_id=getattr(self.request.user, "id", None),
            is_staff=getattr(self.request.user, "is_staff", False),
        )

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == "create":
            return AgentTaskCreateSerializer
        elif self.action == "list":
            return AgentTaskListSerializer
        return AgentTaskSerializer

    def _get_task_for_action(self, pk: Any) -> AgentTaskModel:
        """Fetch a task with the same ownership rules used by the queryset."""
        task_model = get_task_for_actor(
            task_id=pk,
            user_id=getattr(self.request.user, "id", None),
            is_staff=getattr(self.request.user, "is_staff", False),
        )
        if task_model is None:
            raise Http404
        return task_model

    def _build_actor(self, request: Any) -> dict[str, Any] | None:
        """Build actor dict from request, including Django group names as roles."""
        user = request.user
        if not user.is_authenticated:
            return None
        roles = []
        if hasattr(user, "groups"):
            try:
                roles = list(user.groups.values_list("name", flat=True))
            except Exception:
                roles = []
        return {
            "user_id": user.id,
            "is_staff": getattr(user, "is_staff", False),
            "roles": roles,
        }

    def _lookup_task_request_id(self, pk: Any) -> str | None:
        """Best-effort request_id lookup for error responses."""
        try:
            return get_task_request_id(task_id=int(pk))
        except Exception:
            return None

    def create(self, request, *args, **kwargs):
        """
        Create a new AgentTask.

        POST /api/agent-runtime/tasks/

        Request body:
        {
            "task_domain": "research",
            "task_type": "macro_portfolio_review",
            "input_payload": {...}
        }

        Response (schema-contract.md:129):
        {
            "request_id": "atr_20260316_000001",
            "task": {
                "id": 101,
                "request_id": "atr_20260316_000001",
                "schema_version": "v1",
                "task_domain": "research",
                ...
            }
        }
        """
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except drf_serializers.ValidationError as e:
            return _build_validation_error_response(generate_request_id(), e)

        use_case = CreateTaskUseCase()
        try:
            input_dto = CreateTaskInput(
                task_domain=serializer.validated_data["task_domain"],
                task_type=serializer.validated_data["task_type"],
                input_payload=serializer.validated_data.get("input_payload", {}),
                created_by=request.user.id if request.user.is_authenticated else None,
            )

            output = use_case.execute(input_dto)

            return Response(
                {
                    "request_id": output.request_id,
                    "task": _serialize_task_like(output.task),
                },
                status=status.HTTP_201_CREATED,
            )

        except ValueError as e:
            request_id = generate_request_id()
            return build_error_response(
                request_id=request_id,
                error_code="validation_error",
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    def list(self, request, *args, **kwargs):
        """
        List AgentTasks with filters.

        GET /api/agent-runtime/tasks/?status=draft&task_domain=research

        Query params:
        - status: Filter by status
        - task_domain: Filter by domain
        - task_type: Filter by type (partial match)
        - requires_human: Filter by requires_human flag
        - search: Search in task_type and request_id
        - limit: Results per page (default 50)
        - offset: Pagination offset (default 0)

        Response:
        {
            "request_id": "atr_20260316_000002",
            "tasks": [...],
            "total_count": 100
        }
        """
        query_serializer = AgentTaskListQuerySerializer(data=request.query_params)
        try:
            query_serializer.is_valid(raise_exception=True)
        except drf_serializers.ValidationError as e:
            return _build_validation_error_response(generate_request_id(), e)

        use_case = ListTasksUseCase()
        input_dto = ListTasksInput(
            status=query_serializer.validated_data.get("status"),
            task_domain=query_serializer.validated_data.get("task_domain"),
            task_type=query_serializer.validated_data.get("task_type"),
            requires_human=query_serializer.validated_data.get("requires_human"),
            search=query_serializer.validated_data.get("search"),
            limit=query_serializer.validated_data.get("limit", 50),
            offset=query_serializer.validated_data.get("offset", 0),
        )

        output = use_case.execute(input_dto)

        # Get models for serialization
        task_ids = [t.id for t in output.tasks if getattr(t, "id", None) is not None]
        task_models = get_task_models_by_ids(task_ids=task_ids)
        task_map = {t.id: t for t in task_models}

        # Serialize in order
        tasks_data = []
        for task in output.tasks:
            if task.id in task_map:
                serializer = AgentTaskListSerializer(task_map[task.id])
                tasks_data.append(serializer.data)

        return Response(
            {
                "request_id": output.request_id,
                "tasks": tasks_data,
                "total_count": output.total_count,
            }
        )

    def retrieve(self, request, *args, **kwargs):
        """
        Get a single AgentTask.

        GET /api/agent-runtime/tasks/{id}/

        Response:
        {
            "request_id": "atr_20260316_000001",
            "task": {...}
        }
        """
        try:
            pk = kwargs.get("pk")
            use_case = GetTaskUseCase()
            output = use_case.execute(task_id=int(pk))

            return Response(
                {
                    "request_id": output.request_id,
                    "task": _serialize_task_like(output.task),
                }
            )

        except AgentTaskModel.DoesNotExist:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="not_found",
                message=f"Task {kwargs.get('pk')} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    # FROZEN: update, partial_update, destroy are NOT allowed
    # All state changes must go through use cases (resume/cancel)

    def update(self, request, *args, **kwargs):
        """Direct updates are not allowed. Use /resume or /cancel endpoints."""
        return build_error_response(
            request_id=generate_request_id(),
            error_code="method_not_allowed",
            message="Direct task updates are not allowed. Use /resume or /cancel endpoints.",
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def partial_update(self, request, *args, **kwargs):
        """Direct updates are not allowed. Use /resume or /cancel endpoints."""
        return build_error_response(
            request_id=generate_request_id(),
            error_code="method_not_allowed",
            message="Direct task updates are not allowed. Use /resume or /cancel endpoints.",
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def destroy(self, request, *args, **kwargs):
        """Task deletion is not allowed in M1."""
        return build_error_response(
            request_id=generate_request_id(),
            error_code="method_not_allowed",
            message="Task deletion is not allowed. Use /cancel to cancel a task.",
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        """
        Resume a task from failed or needs_human state.

        POST /api/agent-runtime/tasks/{id}/resume/

        Request body:
        {
            "target_status": "draft",  // Optional, defaults based on current state
            "reason": "Fixed the issue"  // Optional
        }

        Response:
        {
            "request_id": "atr_20260316_000001",
            "task": {...},
            "timeline_event_id": 123
        }
        """
        request_id = self._lookup_task_request_id(pk) or generate_request_id()

        use_case = ResumeTaskUseCase()
        try:
            input_dto = ResumeTaskInput(
                task_id=int(pk),
                target_status=request.data.get("target_status"),
                reason=request.data.get("reason"),
                actor=self._build_actor(request),
            )

            output = use_case.execute(input_dto)

            return Response(
                {
                    "request_id": output.request_id,
                    "task": _serialize_task_like(output.task),
                    "timeline_event_id": output.timeline_event_id,
                }
            )

        except AgentTaskModel.DoesNotExist:
            return build_error_response(
                request_id=request_id,
                error_code="not_found",
                message=f"Task {pk} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except InvalidStateTransitionError as e:
            return build_error_response(
                request_id=request_id,
                error_code="invalid_state_transition",
                message=e.message,
                details={
                    "current_status": e.current_status,
                    "target_status": e.target_status,
                    "allowed_transitions": e.allowed_transitions,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except ValueError as e:
            return build_error_response(
                request_id=request_id,
                error_code="validation_error",
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """
        Cancel a task.

        POST /api/agent-runtime/tasks/{id}/cancel/

        Request body:
        {
            "reason": "No longer needed"  // Required
        }

        Response:
        {
            "request_id": "atr_20260316_000001",
            "task": {...},
            "timeline_event_id": 123
        }
        """
        request_id = self._lookup_task_request_id(pk) or generate_request_id()

        reason = request.data.get("reason", "")

        if not reason:
            return build_error_response(
                request_id=request_id,
                error_code="validation_error",
                message="reason is required for cancellation",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        use_case = CancelTaskUseCase()
        try:
            input_dto = CancelTaskInput(
                task_id=int(pk),
                reason=reason,
                actor=self._build_actor(request),
            )

            output = use_case.execute(input_dto)

            return Response(
                {
                    "request_id": output.request_id,
                    "task": _serialize_task_like(output.task),
                    "timeline_event_id": output.timeline_event_id,
                }
            )

        except AgentTaskModel.DoesNotExist:
            return build_error_response(
                request_id=request_id,
                error_code="not_found",
                message=f"Task {pk} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except InvalidStateTransitionError as e:
            return build_error_response(
                request_id=request_id,
                error_code="invalid_state_transition",
                message=e.message,
                details={
                    "current_status": e.current_status,
                    "target_status": e.target_status,
                    "allowed_transitions": e.allowed_transitions,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """
        Get timeline events for a task.

        GET /api/agent-runtime/tasks/{id}/timeline/

        Response:
        {
            "request_id": "atr_20260316_000001",
            "events": [...]
        }
        """
        task_model = self.get_object()

        events = get_task_timeline_events(task_id=task_model.id)

        serializer = AgentTimelineEventSerializer(events, many=True)

        return Response(
            {
                "request_id": task_model.request_id,
                "events": serializer.data,
            }
        )

    @action(detail=True, methods=["get"])
    def artifacts(self, request, pk=None):
        """
        Get artifacts for a task.

        GET /api/agent-runtime/tasks/{id}/artifacts/

        Response:
        {
            "request_id": "atr_20260316_000001",
            "artifacts": [...]
        }
        """
        task_model = self.get_object()

        artifacts = get_task_artifacts(task_id=task_model.id)

        serializer = AgentArtifactSerializer(artifacts, many=True)

        return Response(
            {
                "request_id": task_model.request_id,
                "artifacts": serializer.data,
            }
        )

    @action(detail=True, methods=["post"])
    def handoff(self, request, pk=None):
        """
        Hand a task to another agent or human.

        POST /api/agent-runtime/tasks/{id}/handoff/

        Request body:
        {
            "to_agent": "human_operator",
            "handoff_reason": "Needs domain expertise",
            "recommended_next_action": "Review signal logic",
            "open_risks": ["macro data stale"]
        }

        Response includes complete handoff payload with task status,
        completed/pending steps, context references, and open risks.
        """
        from apps.agent_runtime.application.handoff_use_cases import (
            HandoffInput,
            HandoffTaskUseCase,
        )

        to_agent = request.data.get("to_agent", "")
        handoff_reason = request.data.get("handoff_reason", "")

        if not to_agent or not handoff_reason:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="validation_error",
                message="to_agent and handoff_reason are required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            use_case = HandoffTaskUseCase()
            output = use_case.execute(HandoffInput(
                task_id=int(pk),
                to_agent=to_agent,
                handoff_reason=handoff_reason,
                recommended_next_action=request.data.get("recommended_next_action"),
                open_risks=request.data.get("open_risks"),
                actor=self._build_actor(request),
            ))

            return Response({
                "request_id": output.request_id,
                "handoff_id": output.handoff_id,
                "handoff_payload": output.handoff_payload,
            })

        except AgentTaskModel.DoesNotExist:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="not_found",
                message=f"Task {pk} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=False, methods=["get"])
    def needs_attention(self, request):
        """
        Get tasks that need human attention.

        GET /api/agent-runtime/tasks/needs_attention/

        Returns tasks with requires_human=True or in needs_human/failed state.

        Response:
        {
            "request_id": "atr_20260316_000003",
            "tasks": [...],
            "total_count": 5
        }
        """
        limit = min(int(request.query_params.get("limit", 20)), 100)
        queryset, total_count = get_needs_attention_tasks(
            base_queryset=self.get_queryset(),
            limit=limit,
        )

        serializer = AgentTaskListSerializer(queryset, many=True)

        return Response(
            {
                "request_id": generate_request_id(),
                "tasks": serializer.data,
                "total_count": total_count,
            }
        )


class ContextSnapshotViewSet(viewsets.ViewSet):
    """
    WP-M2-01: Context Snapshot API.

    Provides domain-specific context snapshots aggregated through facades.
    All five domain endpoints return a structured snapshot even when
    underlying data sources are partially unavailable.

    Endpoints:
    - GET /api/agent-runtime/context/research/
    - GET /api/agent-runtime/context/monitoring/
    - GET /api/agent-runtime/context/decision/
    - GET /api/agent-runtime/context/execution/
    - GET /api/agent-runtime/context/ops/
    """

    permission_classes = [IsAuthenticated]

    def _build_snapshot_response(self, domain: str) -> Response:
        """Build and return a context snapshot for the given domain."""
        from apps.agent_runtime.application.facades import get_facade

        try:
            facade = get_facade(domain)
        except ValueError:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="invalid_domain",
                message=f"Unknown context domain: {domain}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        snapshot = facade.build_snapshot()
        request_id = generate_request_id()

        return Response({
            "request_id": request_id,
            "domain": snapshot.domain,
            "generated_at": snapshot.generated_at,
            "regime_summary": snapshot.regime_summary,
            "policy_summary": snapshot.policy_summary,
            "portfolio_summary": snapshot.portfolio_summary,
            "active_signals_summary": snapshot.active_signals_summary,
            "open_decisions_summary": snapshot.open_decisions_summary,
            "risk_alerts_summary": snapshot.risk_alerts_summary,
            "task_health_summary": snapshot.task_health_summary,
            "data_freshness_summary": snapshot.data_freshness_summary,
        })

    @action(detail=False, methods=["get"], url_path="research")
    def research(self, request):
        """
        GET /api/agent-runtime/context/research/

        Context snapshot tailored for research tasks: macro trends,
        regime history depth, signal invalidation status.
        """
        return self._build_snapshot_response("research")

    @action(detail=False, methods=["get"], url_path="monitoring")
    def monitoring(self, request):
        """
        GET /api/agent-runtime/context/monitoring/

        Context snapshot tailored for monitoring tasks: price alerts,
        sentiment freshness, data quality metrics.
        """
        return self._build_snapshot_response("monitoring")

    @action(detail=False, methods=["get"], url_path="decision")
    def decision(self, request):
        """
        GET /api/agent-runtime/context/decision/

        Context snapshot tailored for decision tasks: quotas,
        pending approvals, signal eligibility.
        """
        return self._build_snapshot_response("decision")

    @action(detail=False, methods=["get"], url_path="execution")
    def execution(self, request):
        """
        GET /api/agent-runtime/context/execution/

        Context snapshot tailored for execution tasks: positions,
        simulated accounts, trading cost context.
        """
        return self._build_snapshot_response("execution")

    @action(detail=False, methods=["get"], url_path="ops")
    def ops(self, request):
        """
        GET /api/agent-runtime/context/ops/

        Context snapshot tailored for ops tasks: event bus status,
        AI provider health, audit freshness.
        """
        return self._build_snapshot_response("ops")


class AgentProposalViewSet(viewsets.ViewSet):
    """
    WP-M3-01: Proposal lifecycle API.

    Endpoints:
    - POST   /api/agent-runtime/proposals/                      - Create proposal
    - GET    /api/agent-runtime/proposals/{id}/                 - Get proposal
    - POST   /api/agent-runtime/proposals/{id}/submit-approval/ - Submit for approval
    - POST   /api/agent-runtime/proposals/{id}/approve/         - Approve proposal (staff/operator only)
    - POST   /api/agent-runtime/proposals/{id}/reject/          - Reject proposal (staff/operator only)
    - POST   /api/agent-runtime/proposals/{id}/execute/         - Execute proposal (staff/operator only)
    """

    permission_classes = [IsAuthenticated]

    def _serialize_proposal(self, proposal_model: Any) -> dict[str, Any]:
        """Serialize a proposal model to dict."""
        if isinstance(proposal_model, AgentProposalModel):
            return AgentProposalSerializer(proposal_model).data

        # Domain entity fallback
        created_at = getattr(proposal_model, "created_at", None)
        updated_at = getattr(proposal_model, "updated_at", None)
        return {
            "id": getattr(proposal_model, "id", None),
            "request_id": getattr(proposal_model, "request_id", None),
            "schema_version": getattr(proposal_model, "schema_version", "v1"),
            "task_id": getattr(proposal_model, "task_id", None),
            "proposal_type": getattr(proposal_model, "proposal_type", None),
            "status": getattr(proposal_model, "status", None),
            "risk_level": getattr(proposal_model, "risk_level", None),
            "approval_required": getattr(proposal_model, "approval_required", True),
            "approval_status": getattr(proposal_model, "approval_status", None),
            "approval_reason": getattr(proposal_model, "approval_reason", None),
            "proposal_payload": getattr(proposal_model, "proposal_payload", {}),
            "created_by": getattr(proposal_model, "created_by", None),
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
            "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        }

    def _get_proposal_data(self, proposal_entity: Any) -> dict[str, Any]:
        """Get serialized proposal data, preferring model if available."""
        model = get_proposal_model(proposal_id=proposal_entity.id)
        if model is not None:
            return AgentProposalSerializer(model).data
        return self._serialize_proposal(proposal_entity)

    def _get_actor(self, request: Any) -> dict[str, Any]:
        """Build actor dict from request, including Django group names as roles."""
        user = request.user
        roles = []
        if hasattr(user, "groups"):
            try:
                roles = list(user.groups.values_list("name", flat=True))
            except Exception:
                roles = []
        return {
            "user_id": user.id if user.is_authenticated else None,
            "is_staff": getattr(user, "is_staff", False),
            "roles": roles,
        }

    def _require_staff_or_operator(self, request: Any) -> Response | None:
        """Return an error response if the user is not staff or operator. None if OK."""
        user = request.user
        if user.is_staff:
            return None
        if hasattr(user, "groups") and user.groups.filter(name="operator").exists():
            return None
        return build_error_response(
            request_id=generate_request_id(),
            error_code="permission_denied",
            message="This action requires staff or operator role",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    def create(self, request):
        """
        Create a new proposal.

        POST /api/agent-runtime/proposals/

        Request body:
        {
            "task_id": 101,           // Optional
            "proposal_type": "signal_create",
            "risk_level": "medium",   // Optional, default medium
            "approval_required": true, // Optional, default true
            "proposal_payload": {...},
            "approval_reason": "..."  // Optional
        }
        """
        serializer = AgentProposalCreateSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except drf_serializers.ValidationError as e:
            return _build_validation_error_response(generate_request_id(), e)

        use_case = CreateProposalUseCase()
        try:
            inp = CreateProposalInput(
                task_id=serializer.validated_data.get("task_id"),
                proposal_type=serializer.validated_data["proposal_type"],
                risk_level=serializer.validated_data.get("risk_level", "medium"),
                approval_required=serializer.validated_data.get("approval_required", True),
                proposal_payload=serializer.validated_data.get("proposal_payload", {}),
                approval_reason=serializer.validated_data.get("approval_reason"),
                created_by=request.user.id if request.user.is_authenticated else None,
            )
            output = use_case.execute(inp)

            return Response(
                {
                    "request_id": output.request_id,
                    "proposal": self._get_proposal_data(output.proposal),
                },
                status=status.HTTP_201_CREATED,
            )

        except ValueError as e:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="validation_error",
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    def retrieve(self, request, pk=None):
        """
        Get a single proposal.

        GET /api/agent-runtime/proposals/{id}/
        """
        try:
            use_case = GetProposalUseCase()
            output = use_case.execute(proposal_id=int(pk))

            return Response(
                {
                    "request_id": output.request_id,
                    "proposal": self._get_proposal_data(output.proposal),
                }
            )
        except AgentProposalModel.DoesNotExist:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="not_found",
                message=f"Proposal {pk} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=True, methods=["post"], url_path="submit-approval")
    def submit_approval(self, request, pk=None):
        """
        Submit a proposal for approval.

        POST /api/agent-runtime/proposals/{id}/submit-approval/

        Runs pre-approval guardrail checks.
        """
        try:
            use_case = SubmitProposalForApprovalUseCase()
            output = use_case.execute(
                proposal_id=int(pk),
                actor=self._get_actor(request),
            )

            return Response({
                "request_id": output.request_id,
                "proposal": self._get_proposal_data(output.proposal),
                "guardrail_decision": output.guardrail_decision,
            })

        except AgentProposalModel.DoesNotExist:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="not_found",
                message=f"Proposal {pk} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except InvalidProposalTransitionError as e:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="invalid_state_transition",
                message=e.message,
                details={
                    "current_status": e.current_status,
                    "target_status": e.target_status,
                    "allowed_transitions": e.allowed_transitions,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except GuardrailBlockedError as e:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="guardrail_blocked",
                message=e.guardrail_message,
                details={
                    "decision": e.decision,
                    "reason_code": e.reason_code,
                    "evidence": e.evidence,
                },
                status_code=status.HTTP_403_FORBIDDEN,
            )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """
        Approve a submitted proposal.

        POST /api/agent-runtime/proposals/{id}/approve/

        Request body:
        {
            "reason": "Looks good"  // Optional
        }

        Requires staff or operator role.
        """
        perm_error = self._require_staff_or_operator(request)
        if perm_error is not None:
            return perm_error

        try:
            use_case = ApproveProposalUseCase()
            output = use_case.execute(
                proposal_id=int(pk),
                reason=request.data.get("reason"),
                actor=self._get_actor(request),
            )

            return Response({
                "request_id": output.request_id,
                "proposal": self._get_proposal_data(output.proposal),
            })

        except AgentProposalModel.DoesNotExist:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="not_found",
                message=f"Proposal {pk} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except InvalidProposalTransitionError as e:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="invalid_state_transition",
                message=e.message,
                details={
                    "current_status": e.current_status,
                    "target_status": e.target_status,
                    "allowed_transitions": e.allowed_transitions,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """
        Reject a submitted proposal.

        POST /api/agent-runtime/proposals/{id}/reject/

        Request body:
        {
            "reason": "Risk too high"  // Optional
        }

        Requires staff or operator role.
        """
        perm_error = self._require_staff_or_operator(request)
        if perm_error is not None:
            return perm_error

        try:
            use_case = RejectProposalUseCase()
            output = use_case.execute(
                proposal_id=int(pk),
                reason=request.data.get("reason"),
                actor=self._get_actor(request),
            )

            return Response({
                "request_id": output.request_id,
                "proposal": self._get_proposal_data(output.proposal),
            })

        except AgentProposalModel.DoesNotExist:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="not_found",
                message=f"Proposal {pk} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except InvalidProposalTransitionError as e:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="invalid_state_transition",
                message=e.message,
                details={
                    "current_status": e.current_status,
                    "target_status": e.target_status,
                    "allowed_transitions": e.allowed_transitions,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        """
        Execute an approved proposal.

        POST /api/agent-runtime/proposals/{id}/execute/

        Runs pre-execution guardrail checks, creates execution record.
        Requires staff or operator role.
        """
        perm_error = self._require_staff_or_operator(request)
        if perm_error is not None:
            return perm_error

        try:
            use_case = ExecuteProposalUseCase()
            output = use_case.execute(
                proposal_id=int(pk),
                actor=self._get_actor(request),
            )

            return Response({
                "request_id": output.request_id,
                "proposal": self._get_proposal_data(output.proposal),
                "execution_record_id": output.execution_record_id,
                "guardrail_decision": output.guardrail_decision,
            })

        except AgentProposalModel.DoesNotExist:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="not_found",
                message=f"Proposal {pk} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except InvalidProposalTransitionError as e:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="invalid_state_transition",
                message=e.message,
                details={
                    "current_status": e.current_status,
                    "target_status": e.target_status,
                    "allowed_transitions": e.allowed_transitions,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except GuardrailBlockedError as e:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="guardrail_blocked",
                message=e.guardrail_message,
                details={
                    "decision": e.decision,
                    "reason_code": e.reason_code,
                    "evidence": e.evidence,
                },
                status_code=status.HTTP_403_FORBIDDEN,
            )


class OperatorDashboardViewSet(viewsets.ViewSet):
    """
    WP-M4-01: Operator Dashboard API.

    Read-only aggregation endpoints for operator observability.
    Allows inspecting any task end-to-end without database access.
    Restricted to staff users and users in the 'operator' group.

    Endpoints:
    - GET /api/agent-runtime/dashboard/summary/     - System overview
    - GET /api/agent-runtime/dashboard/task/{id}/    - Full task detail with timeline + proposals
    - GET /api/agent-runtime/dashboard/proposals/    - Proposal list with approval status
    - GET /api/agent-runtime/dashboard/guardrails/   - Recent guardrail decisions
    - GET /api/agent-runtime/dashboard/executions/   - Recent execution outcomes
    """

    permission_classes = [IsStaffOrOperator]

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """System-wide summary for operator dashboard."""
        payload = get_dashboard_summary_payload()
        payload["request_id"] = generate_request_id()
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="task/(?P<task_id>[^/.]+)")
    def task_detail(self, request, task_id=None):
        """Full task detail with timeline, proposals, and guardrails."""
        payload = get_dashboard_task_detail_payload(task_id=int(task_id))
        if payload is None:
            return build_error_response(
                request_id=generate_request_id(),
                error_code="not_found",
                message=f"Task {task_id} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return Response({
            "request_id": generate_request_id(),
            "task": AgentTaskSerializer(payload["task"]).data,
            "timeline": AgentTimelineEventSerializer(payload["timeline"], many=True).data,
            "proposals": AgentProposalSerializer(payload["proposals"], many=True).data,
            "guardrail_decisions": AgentGuardrailDecisionSerializer(
                payload["guardrail_decisions"],
                many=True,
            ).data,
            "execution_records": AgentExecutionRecordSerializer(
                payload["execution_records"],
                many=True,
            ).data,
        })

    @action(detail=False, methods=["get"], url_path="proposals")
    def proposals(self, request):
        """Proposal list with approval status."""
        limit = min(int(request.query_params.get("limit", 50)), 200)
        offset = int(request.query_params.get("offset", 0))
        status_filter = request.query_params.get("status")

        proposals_qs, total = get_dashboard_proposals_payload(
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )
        proposals = AgentProposalSerializer(proposals_qs, many=True).data

        return Response({
            "request_id": generate_request_id(),
            "proposals": proposals,
            "total_count": total,
        })

    @action(detail=False, methods=["get"], url_path="guardrails")
    def guardrails(self, request):
        """Recent guardrail decisions."""
        limit = min(int(request.query_params.get("limit", 50)), 200)

        decisions = AgentGuardrailDecisionSerializer(
            get_dashboard_guardrails_payload(limit=limit),
            many=True,
        ).data

        return Response({
            "request_id": generate_request_id(),
            "guardrail_decisions": decisions,
        })

    @action(detail=False, methods=["get"], url_path="executions")
    def executions(self, request):
        """Recent execution outcomes."""
        limit = min(int(request.query_params.get("limit", 50)), 200)

        records = AgentExecutionRecordSerializer(
            get_dashboard_executions_payload(limit=limit),
            many=True,
        ).data

        return Response({
            "request_id": generate_request_id(),
            "execution_records": records,
        })


class AgentTaskHealthViewSet(viewsets.ViewSet):
    """
    Health check endpoints for Agent Runtime.

    NOTE: This is an additional read-only endpoint, not part of the FROZEN contract.
    """

    permission_classes = []  # Public endpoint

    def list(self, request):
        """
        Health check for Agent Runtime API.

        GET /api/agent-runtime/health/

        Response:
        {
            "status": "healthy",
            "version": "v1",
            "timestamp": "2026-03-16T10:00:00Z"
        }
        """
        from django.utils import timezone

        return Response(
            {
                "status": "healthy",
                "version": "v1",
                "timestamp": timezone.now().isoformat(),
            }
        )
