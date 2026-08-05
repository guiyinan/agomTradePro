"""Canonical DRF transport for governed stress-scenario reads and validation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.risk_center.application.scenario_governance import (
    CommitScenarioGovernanceCommand,
    PreviewScenarioGovernanceCommand,
    ReviewScenarioGovernanceProposalCommand,
    ScenarioGovernanceRequest,
    ScenarioGovernanceTarget,
    get_scenario_governance_facade,
)
from apps.risk_center.application.scenario_inputs import (
    build_revision_command,
    build_validation_revision,
)
from apps.risk_center.application.scenario_public import (
    get_active_scenario_set,
    list_scenario_revisions,
    list_scenarios,
    validate_scenario_revision,
)
from apps.risk_center.application.scenario_use_cases import (
    ScenarioConfigurationError,
    ScenarioNotFoundError,
)
from apps.risk_center.domain.scenario_governance import (
    ScenarioGovernanceActor,
    ScenarioGovernanceActorKind,
    ScenarioGovernanceError,
    ScenarioGovernanceErrorCode,
    ScenarioGovernanceOperation,
)
from apps.risk_center.domain.scenarios import ScenarioRevisionStatus, ScenarioType
from apps.risk_center.interface.scenario_presenters import (
    present_revision,
    present_set_revision,
    present_summary,
    present_validation,
)
from apps.risk_center.interface.scenario_serializers import (
    ActiveScenarioSetQuerySerializer,
    ScenarioActivationSerializer,
    ScenarioGovernancePreviewSerializer,
    ScenarioListQuerySerializer,
    ScenarioProposalReviewSerializer,
    ScenarioRetireSerializer,
    ScenarioRevisionSerializer,
    ScenarioRollbackSerializer,
)

_CAPABILITY_KEYS = {
    ScenarioGovernanceOperation.PROPOSE: "risk_center.stress_scenario.propose_revision",
    ScenarioGovernanceOperation.ACTIVATE: "risk_center.stress_scenario.activate_revision",
    ScenarioGovernanceOperation.ROLLBACK: "risk_center.stress_scenario.rollback_revision",
    ScenarioGovernanceOperation.RETIRE: "risk_center.stress_scenario.retire",
}

_TRANSPORT_FIELDS = frozenset(
    {
        "preview_id",
        "proposal_id",
        "idempotency_key",
        "expected_active_version",
        "expected_active_hash",
        "correlation_id",
    }
)


def _actor_name(request: Request) -> str:
    actor = request.user.get_username()
    return actor or f"user:{request.user.pk}"


def _governance_actor(request: Request) -> ScenarioGovernanceActor:
    """Build actor identity only from authenticated server-side metadata."""

    auth_kind = str(getattr(request.auth, "actor_kind", "human")).lower()
    kind = {
        "ai": ScenarioGovernanceActorKind.AI,
        "service": ScenarioGovernanceActorKind.SERVICE,
    }.get(auth_kind, ScenarioGovernanceActorKind.HUMAN)
    raw_roles = getattr(request.auth, "roles", ())
    roles = tuple(str(role) for role in raw_roles) if isinstance(raw_roles, (tuple, list)) else ()
    if request.user.is_superuser:
        roles = (*roles, "admin")
    elif request.user.is_staff:
        roles = (*roles, "staff")
    user_id = request.user.pk if kind is ScenarioGovernanceActorKind.HUMAN else None
    if kind is ScenarioGovernanceActorKind.HUMAN and not isinstance(user_id, int):
        raise ValueError("human governance actor must have a persisted user id")
    return ScenarioGovernanceActor(
        actor_id=_actor_name(request),
        kind=kind,
        is_staff=bool(request.user.is_staff),
        user_id=user_id,
        roles=roles,
    )


def _operation_request(
    *,
    actor: ScenarioGovernanceActor,
    operation: ScenarioGovernanceOperation,
    payload: dict[str, object],
    target: ScenarioGovernanceTarget,
    change_reason: str,
    correlation_id: str,
    expected_base_version: int | None,
    expected_base_hash: str | None,
    revision_command: Any = None,
) -> ScenarioGovernanceRequest:
    return ScenarioGovernanceRequest(
        actor=actor,
        capability_key=_CAPABILITY_KEYS[operation],
        operation=operation,
        payload=payload,
        target=target,
        change_reason=change_reason,
        correlation_id=correlation_id,
        expected_base_version=expected_base_version,
        expected_base_hash=expected_base_hash,
        revision_command=revision_command,
    )


def _governance_error(exc: Exception, *, correlation_id: str) -> Response:
    if isinstance(exc, ScenarioGovernanceError):
        http_status: int
        if exc.conflict:
            http_status = status.HTTP_409_CONFLICT
        elif exc.code is ScenarioGovernanceErrorCode.PERMISSION_DENIED:
            http_status = status.HTTP_403_FORBIDDEN
        elif exc.code in {
            ScenarioGovernanceErrorCode.TARGET_NOT_FOUND,
            ScenarioGovernanceErrorCode.PREVIEW_NOT_FOUND,
            ScenarioGovernanceErrorCode.PROPOSAL_NOT_FOUND,
        }:
            http_status = status.HTTP_404_NOT_FOUND
        else:
            http_status = status.HTTP_400_BAD_REQUEST
        return Response(exc.as_dict(correlation_id=correlation_id), status=http_status)
    return _blocked(str(exc), http_status=status.HTTP_400_BAD_REQUEST)


def _revision_payload(validated: dict[str, Any]) -> dict[str, object]:
    return {key: value for key, value in validated.items() if key not in _TRANSPORT_FIELDS}


def _blocked(detail: str, *, http_status: int) -> Response:
    return Response(
        {
            "success": False,
            "data": None,
            "detail": detail,
            "must_not_use_for_decision": True,
            "blocked_reason": detail,
        },
        status=http_status,
    )


class StressScenarioListView(APIView):
    """List repository-backed scenario definitions and selected revisions."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        serializer = ScenarioListQuerySerializer(data=request.query_params.dict())
        serializer.is_valid(raise_exception=True)
        scenario_type_raw = serializer.validated_data.get("scenario_type")
        scenario_type = ScenarioType(scenario_type_raw) if scenario_type_raw else None
        try:
            summaries = list_scenarios(
                scenario_type=scenario_type,
                include_inactive=bool(serializer.validated_data["include_inactive"]),
            )
        except ScenarioConfigurationError as exc:
            return _blocked(str(exc), http_status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"success": True, "data": [present_summary(item) for item in summaries]})


class StressScenarioDetailView(APIView):
    """Read a scenario identity and its complete immutable revision history."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, scenario_key: str) -> Response:
        del request
        try:
            revisions = list_scenario_revisions(scenario_key)
            summaries = list_scenarios(include_inactive=True)
        except ScenarioNotFoundError as exc:
            return _blocked(str(exc), http_status=status.HTTP_404_NOT_FOUND)
        except ScenarioConfigurationError as exc:
            return _blocked(str(exc), http_status=status.HTTP_503_SERVICE_UNAVAILABLE)
        summary = next(
            (
                item
                for item in summaries
                if scenario_key == item.definition.scenario_key
                or scenario_key in item.definition.legacy_aliases
            ),
            None,
        )
        if summary is None:
            return _blocked(
                f"stress scenario not found: {scenario_key}",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        payload = present_summary(summary)
        payload["revisions"] = [present_revision(item) for item in revisions]
        return Response({"success": True, "data": payload})


class ActiveScenarioSetView(APIView):
    """Return the sole active set revision for a production scope."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        serializer = ActiveScenarioSetQuerySerializer(data=request.query_params.dict())
        serializer.is_valid(raise_exception=True)
        try:
            revision = get_active_scenario_set(
                environment=str(serializer.validated_data["environment"]),
                purpose=str(serializer.validated_data["purpose"]),
            )
        except ScenarioConfigurationError as exc:
            return _blocked(str(exc), http_status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"success": True, "data": present_set_revision(revision)})


class ValidateScenarioRevisionView(APIView):
    """Validate a typed replacement revision with zero persistence writes."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = ScenarioRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            revision = build_validation_revision(
                serializer.validated_data,
                actor=_actor_name(request),
            )
            result = validate_scenario_revision(revision)
        except ValueError as exc:
            return Response(
                {
                    "success": True,
                    "data": {
                        "valid": False,
                        "errors": [str(exc)],
                        "must_not_use_for_decision": True,
                    },
                }
            )
        return Response({"success": True, "data": present_validation(result)})


class PreviewScenarioGovernanceView(APIView):
    """Persist a short-lived preview bound to an exact actor and payload."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        if "operation" in request.data:
            envelope = ScenarioGovernancePreviewSerializer(data=request.data)
            envelope.is_valid(raise_exception=True)
            data = envelope.validated_data
            operation = ScenarioGovernanceOperation(str(data["operation"]))
            raw_payload = data["payload"]
            if not isinstance(raw_payload, dict):
                return _blocked(
                    "payload must be an object",
                    http_status=status.HTTP_400_BAD_REQUEST,
                )
            payload: dict[str, object] = dict(raw_payload)
            if operation is ScenarioGovernanceOperation.PROPOSE:
                revision_serializer = ScenarioRevisionSerializer(data=payload)
                revision_serializer.is_valid(raise_exception=True)
                payload = _revision_payload(revision_serializer.validated_data)
                revision_command = build_revision_command(
                    payload,
                    actor=_actor_name(request),
                    status=ScenarioRevisionStatus.PROPOSED,
                )
            else:
                if payload:
                    return _blocked(
                        "action preview payload must be empty; use typed target fields",
                        http_status=status.HTTP_400_BAD_REQUEST,
                    )
                revision_command = None
            target = ScenarioGovernanceTarget(
                scenario_key=data.get("scenario_key"),
                scenario_set_revision_id=data.get("scenario_set_revision_id"),
                environment=data.get("environment"),
                purpose=data.get("purpose"),
                target_version=data.get("target_version"),
            )
            change_reason = str(data["change_reason"])
            correlation_id = str(data["correlation_id"])
            expected_version = data.get("expected_active_version")
            expected_hash = data.get("expected_active_hash")
        else:
            revision_serializer = ScenarioRevisionSerializer(data=request.data)
            revision_serializer.is_valid(raise_exception=True)
            data = revision_serializer.validated_data
            operation = ScenarioGovernanceOperation.PROPOSE
            payload = _revision_payload(data)
            revision_command = build_revision_command(
                payload,
                actor=_actor_name(request),
                status=ScenarioRevisionStatus.PROPOSED,
            )
            target = ScenarioGovernanceTarget(scenario_key=str(data["scenario_key"]))
            change_reason = str(data["change_reason"])
            correlation_id = str(data.get("correlation_id") or "scenario-preview")
            expected_version = data.get("based_on_version")
            expected_hash = data.get("expected_active_hash")
        ttl_seconds = int(settings.SCENARIO_GOVERNANCE_PREVIEW_TTL_SECONDS)
        if ttl_seconds <= 0:
            return _blocked(
                "scenario preview TTL is not configured",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            governance_request = _operation_request(
                actor=_governance_actor(request),
                operation=operation,
                payload=payload,
                target=target,
                change_reason=change_reason,
                correlation_id=correlation_id,
                expected_base_version=expected_version,
                expected_base_hash=expected_hash,
                revision_command=revision_command,
            )
            outcome = get_scenario_governance_facade().preview(
                PreviewScenarioGovernanceCommand(
                    request=governance_request,
                    expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
                )
            )
        except (RuntimeError, ValueError, ScenarioGovernanceError) as exc:
            return _governance_error(exc, correlation_id=correlation_id)
        return Response({"success": True, "data": outcome.as_dict()})


class ProposeScenarioRevisionView(APIView):
    """Create an immutable revision plus persistent AgentProposal."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = ScenarioRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        correlation_id = str(data.get("correlation_id") or "")
        payload = _revision_payload(data)
        try:
            revision_command = build_revision_command(
                payload,
                actor=_actor_name(request),
                status=ScenarioRevisionStatus.PROPOSED,
            )
            governance_request = _operation_request(
                actor=_governance_actor(request),
                operation=ScenarioGovernanceOperation.PROPOSE,
                payload=payload,
                target=ScenarioGovernanceTarget(scenario_key=str(data["scenario_key"])),
                change_reason=str(data["change_reason"]),
                correlation_id=correlation_id,
                expected_base_version=data.get("based_on_version"),
                expected_base_hash=data.get("expected_active_hash"),
                revision_command=revision_command,
            )
            outcome = get_scenario_governance_facade().propose_revision(
                CommitScenarioGovernanceCommand(
                    request=governance_request,
                    preview_id=str(data.get("preview_id") or ""),
                    idempotency_key=str(data.get("idempotency_key") or ""),
                )
            )
        except (RuntimeError, ValueError, ScenarioGovernanceError) as exc:
            return _governance_error(exc, correlation_id=correlation_id)
        return Response(
            {"success": True, "data": outcome.as_dict()},
            status=status.HTTP_201_CREATED,
        )


class ReviewScenarioProposalView(APIView):
    """Approve or reject a proposal as an authenticated human staff user."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, proposal_id: int, decision: str) -> Response:
        serializer = ScenarioProposalReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = str(serializer.validated_data["correlation_id"])
        command = ReviewScenarioGovernanceProposalCommand(
            actor=_governance_actor(request),
            proposal_id=proposal_id,
            reason=str(serializer.validated_data["reason"]),
            correlation_id=correlation_id,
        )
        try:
            facade = get_scenario_governance_facade()
            if decision == "approve":
                outcome = facade.approve(command)
            elif decision == "reject":
                outcome = facade.reject(command)
            else:
                return _blocked(
                    "unsupported proposal decision",
                    http_status=status.HTTP_404_NOT_FOUND,
                )
        except (RuntimeError, ValueError, ScenarioGovernanceError) as exc:
            return _governance_error(exc, correlation_id=correlation_id)
        return Response({"success": True, "data": outcome.as_dict()})


class ScenarioActionView(APIView):
    """Propose or execute activation/rollback under persistent governance."""

    permission_classes = [IsAuthenticated]
    operation: ScenarioGovernanceOperation
    serializer_class: type[ScenarioActivationSerializer]

    def _target(self, data: dict[str, Any]) -> ScenarioGovernanceTarget:
        if self.operation is ScenarioGovernanceOperation.ACTIVATE:
            return ScenarioGovernanceTarget(
                scenario_set_revision_id=str(data["scenario_set_revision_id"]),
                environment=str(data["environment"]),
                purpose=str(data["purpose"]),
            )
        return ScenarioGovernanceTarget(
            scenario_key=str(data["scenario_key"]),
            environment=str(data["environment"]),
            purpose=str(data["purpose"]),
            target_version=int(data["target_version"]),
        )

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        correlation_id = str(data["correlation_id"])
        try:
            governance_request = _operation_request(
                actor=_governance_actor(request),
                operation=self.operation,
                payload={},
                target=self._target(data),
                change_reason=str(data["change_reason"]),
                correlation_id=correlation_id,
                expected_base_version=data.get("expected_active_version"),
                expected_base_hash=data.get("expected_active_hash"),
            )
            command = CommitScenarioGovernanceCommand(
                request=governance_request,
                preview_id=str(data["preview_id"]),
                idempotency_key=str(data["idempotency_key"]),
                proposal_id=data.get("proposal_id"),
            )
            facade = get_scenario_governance_facade()
            if command.proposal_id is None:
                outcome = facade.propose_action(command)
            elif self.operation is ScenarioGovernanceOperation.ACTIVATE:
                outcome = facade.activate(command)
            else:
                outcome = facade.rollback(command)
        except (RuntimeError, ValueError, ScenarioGovernanceError) as exc:
            return _governance_error(exc, correlation_id=correlation_id)
        return Response({"success": True, "data": outcome.as_dict()})


class ActivateScenarioSetView(ScenarioActionView):
    """Propose or execute an active scenario-set transition."""

    operation = ScenarioGovernanceOperation.ACTIVATE
    serializer_class = ScenarioActivationSerializer


class RollbackScenarioSetView(ScenarioActionView):
    """Propose or execute an append-only scenario-set rollback."""

    operation = ScenarioGovernanceOperation.ROLLBACK
    serializer_class = ScenarioRollbackSerializer


class RetireScenarioView(APIView):
    """Propose or execute retirement without deleting revision history."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, scenario_key: str) -> Response:
        serializer = ScenarioRetireSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        correlation_id = str(data["correlation_id"])
        try:
            governance_request = _operation_request(
                actor=_governance_actor(request),
                operation=ScenarioGovernanceOperation.RETIRE,
                payload={},
                target=ScenarioGovernanceTarget(scenario_key=scenario_key),
                change_reason=str(data["change_reason"]),
                correlation_id=correlation_id,
                expected_base_version=data.get("expected_active_version"),
                expected_base_hash=data.get("expected_active_hash"),
            )
            command = CommitScenarioGovernanceCommand(
                request=governance_request,
                preview_id=str(data["preview_id"]),
                idempotency_key=str(data["idempotency_key"]),
                proposal_id=data.get("proposal_id"),
            )
            facade = get_scenario_governance_facade()
            outcome = (
                facade.propose_action(command)
                if command.proposal_id is None
                else facade.retire(command)
            )
        except (RuntimeError, ValueError, ScenarioGovernanceError) as exc:
            return _governance_error(exc, correlation_id=correlation_id)
        return Response({"success": True, "data": outcome.as_dict()})


class ScenarioResearchUnavailableView(APIView):
    """Fail closed until canonical portfolio and research evidence ports are wired."""

    permission_classes = [IsAuthenticated]

    def _response(self) -> Response:
        return Response(
            {
                "success": False,
                "data": {
                    "status": "blocked",
                    "must_not_use_for_decision": True,
                    "blocked_reason": "canonical_research_evidence_provider_not_configured",
                    "missing_items": [
                        "portfolio_snapshot_provider",
                        "market_state_evidence_provider",
                        "versioned_score_weight_provider",
                    ],
                },
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    def get(self, request: Request) -> Response:
        del request
        return self._response()

    def post(self, request: Request) -> Response:
        del request
        return self._response()


__all__ = [
    "ActivateScenarioSetView",
    "ActiveScenarioSetView",
    "PreviewScenarioGovernanceView",
    "ProposeScenarioRevisionView",
    "RetireScenarioView",
    "ReviewScenarioProposalView",
    "RollbackScenarioSetView",
    "ScenarioResearchUnavailableView",
    "StressScenarioDetailView",
    "StressScenarioListView",
    "ValidateScenarioRevisionView",
]
