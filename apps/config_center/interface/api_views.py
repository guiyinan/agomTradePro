"""API views for config center."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.config_center.application.use_cases import (
    ConflictError,
    CreateOrUpdateQlibTrainingProfileUseCase,
    GetQlibRuntimeConfigUseCase,
    GetQlibTrainingRunDetailUseCase,
    ListQlibTrainingProfilesUseCase,
    ListQlibTrainingRunsUseCase,
    QlibAccessDeniedError,
    TriggerQlibTrainingUseCase,
    UpdateQlibRuntimeConfigUseCase,
    ValidationFailureError,
)
from apps.config_center.interface.serializers import (
    QlibRuntimeConfigSerializer,
    QlibTrainingProfileSerializer,
    QlibTrainingRunTriggerSerializer,
)


class StaffReadSuperuserWriteMixin:
    permission_classes = [IsAdminUser]

    @staticmethod
    def _permission_denied(exc: QlibAccessDeniedError) -> Response:
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)


def _serialize_profile(model) -> dict:
    return {
        "id": model.id,
        "profile_key": model.profile_key,
        "name": model.name,
        "model_name": model.model_name,
        "model_type": model.model_type,
        "universe": model.universe,
        "start_date": model.start_date.isoformat() if model.start_date else None,
        "end_date": model.end_date.isoformat() if model.end_date else None,
        "feature_set_id": model.feature_set_id,
        "label_id": model.label_id,
        "learning_rate": model.learning_rate,
        "epochs": model.epochs,
        "model_params": model.model_params or {},
        "extra_train_config": model.extra_train_config or {},
        "activate_after_train": model.activate_after_train,
        "is_active": model.is_active,
        "notes": model.notes,
        "created_at": model.created_at.isoformat(),
        "updated_at": model.updated_at.isoformat(),
    }


def _serialize_run(model) -> dict:
    return {
        "run_id": str(model.run_id),
        "status": model.status,
        "model_name": model.model_name,
        "model_type": model.model_type,
        "requested_by": getattr(model.requested_by, "username", None),
        "requested_at": model.requested_at.isoformat() if model.requested_at else None,
        "started_at": model.started_at.isoformat() if model.started_at else None,
        "finished_at": model.finished_at.isoformat() if model.finished_at else None,
        "celery_task_id": model.celery_task_id,
        "resolved_train_config": model.resolved_train_config or {},
        "result_model_name": model.result_model_name,
        "result_artifact_hash": model.result_artifact_hash,
        "result_metrics": model.result_metrics or {},
        "registry_result": model.registry_result or {},
        "error_message": model.error_message,
        "profile": (
            {
                "profile_key": model.profile.profile_key,
                "name": model.profile.name,
            }
            if model.profile
            else None
        ),
    }


class QlibRuntimeConfigView(StaffReadSuperuserWriteMixin, APIView):
    def get(self, request):
        try:
            payload = GetQlibRuntimeConfigUseCase().execute(actor=request.user)
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        return Response({"success": True, "data": payload})

    def post(self, request):
        serializer = QlibRuntimeConfigSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            payload = UpdateQlibRuntimeConfigUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        return Response({"success": True, "data": payload})


class QlibTrainingProfileListCreateView(StaffReadSuperuserWriteMixin, APIView):
    def get(self, request):
        try:
            models = ListQlibTrainingProfilesUseCase().execute(actor=request.user)
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        return Response({"success": True, "data": [_serialize_profile(item) for item in models]})

    def post(self, request):
        serializer = QlibTrainingProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            model = CreateOrUpdateQlibTrainingProfileUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        return Response({"success": True, "data": _serialize_profile(model)})


class QlibTrainingRunListView(StaffReadSuperuserWriteMixin, APIView):
    def get(self, request):
        limit = int(request.query_params.get("limit", 50) or 50)
        try:
            models = ListQlibTrainingRunsUseCase().execute(actor=request.user, limit=limit)
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        return Response({"success": True, "data": [_serialize_run(item) for item in models]})


class QlibTrainingRunDetailView(StaffReadSuperuserWriteMixin, APIView):
    def get(self, request, run_id: str):
        try:
            model = GetQlibTrainingRunDetailUseCase().execute(actor=request.user, run_id=run_id)
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        if model is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": _serialize_run(model)})


class QlibTrainingRunTriggerView(StaffReadSuperuserWriteMixin, APIView):
    def post(self, request):
        serializer = QlibTrainingRunTriggerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = TriggerQlibTrainingUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        except ConflictError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except ValidationFailureError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"success": True, "data": payload}, status=status.HTTP_202_ACCEPTED)
