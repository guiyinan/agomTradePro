"""API views for config center."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import BasePermission, IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.config_center.application.use_cases import (
    ConflictError,
    CreateOrUpdateQlibTrainingProfileUseCase,
    GetQlibRuntimeConfigUseCase,
    GetQlibTrainingRunDetailUseCase,
    GetSystemGovernanceSettingsUseCase,
    ListAlphaUniverseConfigsUseCase,
    ListQlibTrainingProfilesUseCase,
    ListQlibTrainingRunsUseCase,
    QlibAccessDeniedError,
    ResolveAlphaUniverseMembersUseCase,
    SaveAlphaUniverseConfigUseCase,
    TriggerQlibTrainingUseCase,
    UpdateQlibRuntimeConfigUseCase,
    UpdateSystemGovernanceSettingsUseCase,
    ValidationFailureError,
)
from apps.config_center.interface.serializers import (
    AlphaUniverseConfigSerializer,
    QlibRuntimeConfigSerializer,
    QlibTrainingProfileSerializer,
    QlibTrainingRunTriggerSerializer,
    SystemGovernanceSettingsSerializer,
)


class StaffReadSuperuserWriteMixin(APIView):
    permission_classes: list[type[BasePermission]] = [IsAdminUser]

    @staticmethod
    def _permission_denied(exc: QlibAccessDeniedError) -> Response:
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)


def _serialize_profile(model: Any) -> dict[str, Any]:
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


def _serialize_alpha_universe(model: Any, *, member_count: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": model.id,
        "universe_id": model.universe_id,
        "name": model.name,
        "source_type": model.source_type,
        "stock_codes": model.stock_codes or [],
        "filters": model.filters or {},
        "is_active": model.is_active,
        "description": model.description,
        "created_at": model.created_at.isoformat(),
        "updated_at": model.updated_at.isoformat(),
    }
    if member_count is not None:
        payload["member_count"] = member_count
    return payload


def _serialize_run(model: Any) -> dict[str, Any]:
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


class QlibRuntimeConfigView(StaffReadSuperuserWriteMixin):
    def get(self, request: Request) -> Response:
        try:
            payload = GetQlibRuntimeConfigUseCase().execute(actor=request.user)
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        return Response({"success": True, "data": payload})

    def post(self, request: Request) -> Response:
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


class SystemGovernanceSettingsView(APIView):
    """Read and update global settings through the config-center owner."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        payload = GetSystemGovernanceSettingsUseCase().execute()
        return Response(SystemGovernanceSettingsSerializer(payload).data)

    def put(self, request: Request) -> Response:
        serializer = SystemGovernanceSettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        payload = UpdateSystemGovernanceSettingsUseCase().execute(
            payload=dict(serializer.validated_data),
            actor=request.user,
        )
        return Response(SystemGovernanceSettingsSerializer(payload).data)


class QlibTrainingProfileListCreateView(StaffReadSuperuserWriteMixin):
    def get(self, request: Request) -> Response:
        try:
            models = ListQlibTrainingProfilesUseCase().execute(actor=request.user)
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        return Response({"success": True, "data": [_serialize_profile(item) for item in models]})

    def post(self, request: Request) -> Response:
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


class AlphaUniverseConfigListCreateView(StaffReadSuperuserWriteMixin):
    def get(self, request: Request) -> Response:
        include_inactive = str(request.query_params.get("include_inactive", "")).lower() in {
            "1",
            "true",
            "yes",
        }
        try:
            models = ListAlphaUniverseConfigsUseCase().execute(
                actor=request.user,
                include_inactive=include_inactive,
            )
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        return Response(
            {"success": True, "data": [_serialize_alpha_universe(item) for item in models]}
        )

    def post(self, request: Request) -> Response:
        serializer = AlphaUniverseConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            model = SaveAlphaUniverseConfigUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
            members = ResolveAlphaUniverseMembersUseCase().execute(
                actor=request.user,
                universe_id=model.universe_id,
            )
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "success": True,
                "data": _serialize_alpha_universe(model, member_count=len(members)),
            }
        )


class AlphaUniverseMembersView(StaffReadSuperuserWriteMixin):
    def get(self, request: Request, universe_id: str) -> Response:
        try:
            members = ResolveAlphaUniverseMembersUseCase().execute(
                actor=request.user,
                universe_id=universe_id,
            )
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        if not members:
            return Response(
                {
                    "success": True,
                    "data": {
                        "universe_id": universe_id,
                        "member_count": 0,
                        "members": [],
                    },
                }
            )
        limit = int(request.query_params.get("limit", 100) or 100)
        limit = max(1, min(limit, 1000))
        return Response(
            {
                "success": True,
                "data": {
                    "universe_id": universe_id,
                    "member_count": len(members),
                    "members": members[:limit],
                    "limit": limit,
                },
            }
        )


class QlibTrainingRunListView(StaffReadSuperuserWriteMixin):
    def get(self, request: Request) -> Response:
        limit = int(request.query_params.get("limit", 50) or 50)
        try:
            models = ListQlibTrainingRunsUseCase().execute(actor=request.user, limit=limit)
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        return Response({"success": True, "data": [_serialize_run(item) for item in models]})


class QlibTrainingRunDetailView(StaffReadSuperuserWriteMixin):
    def get(self, request: Request, run_id: str) -> Response:
        try:
            model = GetQlibTrainingRunDetailUseCase().execute(actor=request.user, run_id=run_id)
        except QlibAccessDeniedError as exc:
            return self._permission_denied(exc)
        if model is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": _serialize_run(model)})


class QlibTrainingRunTriggerView(StaffReadSuperuserWriteMixin):
    def post(self, request: Request) -> Response:
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
