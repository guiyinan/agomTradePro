"""DRF APIs for administrator user-access governance."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application import interface_services

from .serializers import (
    UserAccessGovernancePayloadSerializer,
    UserAccessGovernanceQuerySerializer,
    UserAccessMutationRequestSerializer,
    UserAccessMutationResultSerializer,
)

UserModel = get_user_model()


def _request_user_id(request: Request) -> int:
    """Return the authenticated administrator id."""

    user_id = getattr(request.user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise PermissionDenied("用户身份无效")
    return user_id


def _positive_user_id(user_id: int) -> int:
    """Reject malformed user identifiers before running a mutation."""

    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValidationError({"user_id": "必须是正整数"})
    return user_id


def _profile_row(profile: Any) -> dict[str, object]:
    """Project one account profile into a stable JSON row."""

    approved_by = getattr(profile, "approved_by", None)
    return {
        "user_id": int(profile.user_id),
        "username": str(profile.user.username),
        "display_name": str(profile.display_name or ""),
        "email": str(profile.user.email or ""),
        "is_active": bool(profile.user.is_active),
        "approval_status": str(profile.approval_status or ""),
        "rbac_role": str(profile.rbac_role or ""),
        "created_at": profile.created_at,
        "approved_by": str(getattr(approved_by, "username", "") or ""),
        "approved_at": profile.approved_at,
        "rejection_reason": str(profile.rejection_reason or ""),
    }


def _governance_payload(*, status_filter: str, search_query: str) -> dict[str, object]:
    """Build the serialized administrator user-governance payload."""

    context = interface_services.build_user_management_context(status_filter, search_query)
    return {
        "status_filter": status_filter,
        "search_query": search_query,
        "total_count": context["total_count"],
        "pending_count": context["pending_count"],
        "approved_count": context["approved_count"],
        "rejected_count": context["rejected_count"],
        "role_choices": [
            {"value": value, "display_label": label} for value, label in context["role_choices"]
        ],
        "rows": [_profile_row(profile) for profile in context["profiles"]],
    }


def _mutation_response(
    *,
    outcome: interface_services.FlashOutcome,
    user_id: int,
) -> Response:
    """Return a consistent mutation receipt with a refreshed user list."""

    success = outcome.level == "success"
    payload = {
        "success": success,
        "message": outcome.message,
        "user_id": user_id,
        "governance": _governance_payload(status_filter="", search_query=""),
    }
    serializer = UserAccessMutationResultSerializer(payload)
    return Response(
        serializer.data,
        status=status.HTTP_200_OK if success else status.HTTP_409_CONFLICT,
    )


class UserAccessGovernanceView(APIView):
    """List user approval and role state for administrators."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        serializer = UserAccessGovernanceQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        payload = _governance_payload(
            status_filter=str(serializer.validated_data.get("approval_status") or ""),
            search_query=str(serializer.validated_data.get("q") or ""),
        )
        return Response(UserAccessGovernancePayloadSerializer(payload).data)


class UserApproveView(APIView):
    """Approve one pending user."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request, user_id: int) -> Response:
        user_id = _positive_user_id(user_id)
        try:
            outcome = interface_services.approve_user(
                actor_user_id=_request_user_id(request),
                target_user_id=user_id,
            )
        except UserModel.DoesNotExist:
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        return _mutation_response(outcome=outcome, user_id=user_id)


class UserRejectView(APIView):
    """Reject one pending user and record an optional reason."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request, user_id: int) -> Response:
        user_id = _positive_user_id(user_id)
        serializer = UserAccessMutationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            outcome = interface_services.reject_user(
                actor_user_id=_request_user_id(request),
                target_user_id=user_id,
                rejection_reason=str(serializer.validated_data.get("rejection_reason") or ""),
            )
        except UserModel.DoesNotExist:
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        return _mutation_response(outcome=outcome, user_id=user_id)


class UserRoleView(APIView):
    """Change one user's RBAC role."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request, user_id: int) -> Response:
        user_id = _positive_user_id(user_id)
        serializer = UserAccessMutationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = str(serializer.validated_data.get("rbac_role") or "")
        if not role:
            raise ValidationError({"rbac_role": "此字段为必填项"})
        try:
            outcome = interface_services.set_user_role(
                target_user_id=user_id,
                raw_role=role,
            )
        except UserModel.DoesNotExist:
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        return _mutation_response(outcome=outcome, user_id=user_id)


class UserApprovalResetView(APIView):
    """Reset one rejected or approved user to pending."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request, user_id: int) -> Response:
        user_id = _positive_user_id(user_id)
        try:
            outcome = interface_services.reset_user_status(
                actor_user_id=_request_user_id(request),
                target_user_id=user_id,
            )
        except UserModel.DoesNotExist:
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        return _mutation_response(outcome=outcome, user_id=user_id)
