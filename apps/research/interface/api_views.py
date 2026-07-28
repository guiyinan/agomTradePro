"""HTTP contracts for experiments, trials and promotion decisions."""

from __future__ import annotations

from typing import cast

from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.research.composition import (
    make_evaluate_promotion,
    make_register_experiment,
    make_run_trial,
)
from apps.research.domain.contracts import (
    ResearchAccessDeniedError,
    ResearchConflictError,
    ResearchRecordNotFoundError,
    TrialRegistrationPayload,
)
from apps.research.interface.serializers import ExperimentSerializer, TrialSerializer


class ExperimentListCreateView(APIView):
    """Register owner-bound research experiments."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """Validate and register one research experiment."""

        serializer = ExperimentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor_user_id, _ = _actor_context(request)
        try:
            experiment = make_register_experiment().execute(
                question=cast(str, serializer.validated_data["question"]),
                hypothesis=cast(str, serializer.validated_data["hypothesis"]),
                owner_id=actor_user_id,
            )
        except ValueError as exc:
            raise ValidationError({"non_field_errors": [str(exc)]}) from exc
        return Response(
            {
                "experiment_id": experiment.experiment_id,
                "question": experiment.question,
                "hypothesis": experiment.hypothesis,
                "status": experiment.status,
            },
            status=status.HTTP_201_CREATED,
        )


class TrialListCreateView(APIView):
    """Register immutable trial evidence for an owned experiment."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """Validate and persist one owner-scoped research trial."""

        serializer = TrialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor_user_id, actor_is_staff = _actor_context(request)
        payload = cast(TrialRegistrationPayload, serializer.validated_data)
        try:
            trial = make_run_trial().execute(
                payload,
                actor_user_id=actor_user_id,
                actor_is_staff=actor_is_staff,
            )
        except ResearchAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ResearchRecordNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except ResearchConflictError as exc:
            raise ValidationError({"non_field_errors": [str(exc)]}) from exc
        except ValueError as exc:
            raise ValidationError({"non_field_errors": [str(exc)]}) from exc
        return Response(
            {
                "trial_id": trial.trial_id,
                "experiment_id": trial.experiment_id,
                "family_id": trial.family_id,
                "status": trial.status,
                "parameter_hash": trial.parameter_hash,
                "pit_manifest_id": trial.pit_manifest_id,
            },
            status=status.HTTP_201_CREATED,
        )


class PromotionEvaluationView(APIView):
    """Evaluate one owner-scoped trial against promotion gates."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, trial_id: str) -> Response:
        """Run an idempotent promotion evaluation for an authorized actor."""

        actor_user_id, actor_is_staff = _actor_context(request)
        try:
            decision = make_evaluate_promotion().execute(
                trial_id,
                actor_user_id=actor_user_id,
                actor_is_staff=actor_is_staff,
            )
        except ResearchAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ResearchRecordNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except ResearchConflictError as exc:
            raise ValidationError({"non_field_errors": [str(exc)]}) from exc
        except ValueError as exc:
            raise ValidationError({"non_field_errors": [str(exc)]}) from exc
        return Response(
            {
                "decision_id": decision.decision_id,
                "trial_id": decision.trial_id,
                "decision": decision.decision,
                "evidence": decision.evidence,
                "decided_at": decision.decided_at.isoformat(),
            }
        )


def _actor_context(request: Request) -> tuple[int, bool]:
    """Return the authenticated integer actor id and staff flag."""

    raw_user_id: object = getattr(request.user, "pk", None)
    if isinstance(raw_user_id, bool) or not isinstance(raw_user_id, int) or raw_user_id <= 0:
        raise PermissionDenied("authenticated_integer_user_required")
    raw_is_staff: object = getattr(request.user, "is_staff", False)
    return raw_user_id, raw_is_staff is True
