"""Risk center API views."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.risk_center.application.use_cases import (
    ApplyRiskTemplateToPolicyUseCase,
    CreateRiskExceptionUseCase,
    CreateRiskTemplateUseCase,
    GetAccountRiskPolicyUseCase,
    GetEffectiveRiskPolicyUseCase,
    GetRiskFloorUseCase,
    ListAccountRiskPoliciesUseCase,
    ListRiskExceptionsUseCase,
    ListRiskTemplatesUseCase,
    RiskCenterAccessDeniedError,
    RiskCenterNotFoundError,
    RiskCenterValidationError,
    UpdateRiskFloorUseCase,
    UpdateRiskTemplateUseCase,
    UpsertAccountRiskPolicyUseCase,
)
from apps.risk_center.interface.serializers import (
    AccountRiskPolicySerializer,
    AccountRiskPolicyUpdateSerializer,
    ApplyTemplateSerializer,
    RiskExceptionSerializer,
    RiskFloorSerializer,
    RiskTemplateSerializer,
    RiskTemplateUpdateSerializer,
)


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _serialize_model(model: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in model._meta.fields:
        value = getattr(model, field.name)
        if hasattr(value, "pk"):
            value = value.pk
        payload[field.name] = _iso(value)
    if hasattr(model, "template") and getattr(model, "template", None):
        payload["template_key"] = model.template.key
        payload["template_name"] = model.template.name
    if hasattr(model, "created_by") and getattr(model, "created_by", None):
        payload["created_by_username"] = model.created_by.username
    if hasattr(model, "is_current"):
        payload["is_current"] = model.is_current
    return payload


def _error_response(exc: Exception) -> Response:
    if isinstance(exc, RiskCenterAccessDeniedError):
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, RiskCenterNotFoundError):
        return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, RiskCenterValidationError):
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class RiskCenterApiHomeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        return Response(
            {
                "module": "risk-center",
                "endpoints": {
                    "floor": "/api/risk-center/floor/",
                    "templates": "/api/risk-center/templates/",
                    "account_policies": "/api/risk-center/account-policies/",
                    "exceptions": "/api/risk-center/exceptions/",
                    "effective_policy": "/api/risk-center/effective-policy/?account_id=1",
                },
            }
        )


class RiskFloorView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        try:
            floor = GetRiskFloorUseCase().execute(actor=request.user)
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        return Response({"success": True, "data": _serialize_model(floor)})

    def put(self, request) -> Response:
        serializer = RiskFloorSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            floor = UpdateRiskFloorUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
        except (RiskCenterAccessDeniedError, RiskCenterValidationError) as exc:
            return _error_response(exc)
        return Response({"success": True, "data": _serialize_model(floor)})


class RiskTemplateListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        try:
            templates = ListRiskTemplatesUseCase().execute(actor=request.user)
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        return Response({"success": True, "data": [_serialize_model(item) for item in templates]})

    def post(self, request) -> Response:
        serializer = RiskTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            template = CreateRiskTemplateUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
        except (RiskCenterAccessDeniedError, RiskCenterValidationError) as exc:
            return _error_response(exc)
        return Response(
            {"success": True, "data": _serialize_model(template)},
            status=status.HTTP_201_CREATED,
        )


class RiskTemplateDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, template_id: int) -> Response:
        return self._update(request, template_id, partial=False)

    def patch(self, request, template_id: int) -> Response:
        return self._update(request, template_id, partial=True)

    def get(self, request, template_id: int) -> Response:
        try:
            templates = ListRiskTemplatesUseCase().execute(actor=request.user)
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        for template in templates:
            if template.id == template_id:
                return Response({"success": True, "data": _serialize_model(template)})
        return Response({"detail": "Risk template not found."}, status=status.HTTP_404_NOT_FOUND)

    def _update(self, request, template_id: int, *, partial: bool) -> Response:
        serializer = RiskTemplateUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            template = UpdateRiskTemplateUseCase().execute(
                actor=request.user,
                template_id=template_id,
                payload=serializer.validated_data,
            )
        except (RiskCenterAccessDeniedError, RiskCenterNotFoundError) as exc:
            return _error_response(exc)
        return Response({"success": True, "data": _serialize_model(template)})


class AccountRiskPolicyListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        try:
            policies = ListAccountRiskPoliciesUseCase().execute(actor=request.user)
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        return Response({"success": True, "data": [_serialize_model(item) for item in policies]})

    def post(self, request) -> Response:
        serializer = AccountRiskPolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            policy = UpsertAccountRiskPolicyUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
        except (RiskCenterAccessDeniedError, RiskCenterValidationError) as exc:
            return _error_response(exc)
        return Response(
            {"success": True, "data": _serialize_model(policy)},
            status=status.HTTP_201_CREATED,
        )


class AccountRiskPolicyByAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id: int) -> Response:
        try:
            policy = GetAccountRiskPolicyUseCase().execute(
                actor=request.user,
                account_id=account_id,
            )
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        if policy is None:
            return Response(
                {"detail": "Account risk policy not found."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response({"success": True, "data": _serialize_model(policy)})


class AccountRiskPolicyDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, policy_id: int) -> Response:
        return self._update(request, policy_id, partial=False)

    def patch(self, request, policy_id: int) -> Response:
        return self._update(request, policy_id, partial=True)

    def _update(self, request, policy_id: int, *, partial: bool) -> Response:
        serializer = AccountRiskPolicyUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        if "account_id" not in payload:
            policy = ListAccountRiskPoliciesUseCase().execute(actor=request.user)
            matched = next((item for item in policy if item.id == policy_id), None)
            if matched is None:
                return Response(
                    {"detail": "Account risk policy not found."}, status=status.HTTP_404_NOT_FOUND
                )
            payload["account_id"] = matched.account_id
        try:
            updated = UpsertAccountRiskPolicyUseCase().execute(
                actor=request.user,
                payload=payload,
            )
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        return Response({"success": True, "data": _serialize_model(updated)})


class ApplyTemplateToPolicyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, policy_id: int) -> Response:
        serializer = ApplyTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            policy = ApplyRiskTemplateToPolicyUseCase().execute(
                actor=request.user,
                policy_id=policy_id,
                template_id=serializer.validated_data["template_id"],
            )
        except (RiskCenterAccessDeniedError, RiskCenterNotFoundError) as exc:
            return _error_response(exc)
        return Response({"success": True, "data": _serialize_model(policy)})


class RiskExceptionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        account_id = request.query_params.get("account_id")
        try:
            exceptions = ListRiskExceptionsUseCase().execute(
                actor=request.user,
                account_id=int(account_id) if account_id else None,
            )
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        return Response({"success": True, "data": [_serialize_model(item) for item in exceptions]})

    def post(self, request) -> Response:
        serializer = RiskExceptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            exception = CreateRiskExceptionUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
        except (RiskCenterAccessDeniedError, RiskCenterValidationError) as exc:
            return _error_response(exc)
        return Response(
            {"success": True, "data": _serialize_model(exception)},
            status=status.HTTP_201_CREATED,
        )


class EffectiveRiskPolicyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        account_id = request.query_params.get("account_id")
        if not account_id:
            return Response(
                {"detail": "account_id is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            payload = GetEffectiveRiskPolicyUseCase().execute(
                actor=request.user,
                account_id=int(account_id),
            )
        except (RiskCenterAccessDeniedError, RiskCenterNotFoundError) as exc:
            return _error_response(exc)
        return Response({"success": True, "data": payload})
