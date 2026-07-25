"""DRF JSON APIs for MCP self-service and admin governance."""

from __future__ import annotations

from collections.abc import Mapping

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application import interface_services

from .permissions import GeneralPermission
from .serializers import (
    MCPAdminUserDetailSerializer,
    MCPAdminUsersPayloadSerializer,
    MCPAdminUsersQuerySerializer,
    MCPMutationResultSerializer,
    MCPSelfServicePayloadSerializer,
    MCPTokenCreateRequestSerializer,
)

UserModel = get_user_model()


def _base_url(request: Request) -> str:
    """Return one normalized external base URL for prompt payloads."""

    return str(request.build_absolute_uri("/")).rstrip("/")


def _request_user_id(request: Request) -> int:
    """Return one valid authenticated actor id."""

    user_id = getattr(request.user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise PermissionDenied("用户身份无效")
    return user_id


def _positive_path_id(value: int, *, field_name: str) -> int:
    """Reject zero or malformed identifiers before mutation services run."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError({field_name: "必须是正整数"})
    return value


def _token_access_level_choices() -> list[dict[str, str]]:
    """Return serializer-friendly token access-level choices."""

    return [
        {"value": value, "label": label}
        for value, label in interface_services.get_token_access_level_choices()
    ]


def _resolve_token_name(raw_name: str, *, prefix: str) -> str:
    """Build one stable token name when the caller did not supply one."""

    name = str(raw_name or "").strip()
    if name:
        return name
    return f"{prefix}-{timezone.now().strftime('%Y%m%d%H%M%S')}"


def _self_service_payload(*, user_id: int, base_url: str) -> dict[str, object]:
    """Build one serialized self-service MCP payload."""

    payload = interface_services.build_self_mcp_api_payload(user_id, base_url=base_url)
    payload["token_access_level_choices"] = _token_access_level_choices()
    return payload


def _admin_user_detail_payload(*, user_id: int, base_url: str) -> dict[str, object]:
    """Build one serialized admin MCP user detail payload."""

    payload = interface_services.build_admin_mcp_user_detail_payload(user_id, base_url=base_url)
    payload["token_access_level_choices"] = _token_access_level_choices()
    return payload


def _created_agent_prompt(
    *,
    token_payload: Mapping[str, object] | None,
    base_url: str,
    default_account_id: object | None,
) -> dict[str, object] | None:
    """Build a copy-ready prompt from one freshly issued token payload."""

    if not token_payload:
        return None
    return interface_services.build_mcp_agent_prompt_payload(
        base_url=base_url,
        token_value=str(token_payload.get("token") or "").strip(),
        token_name=str(token_payload.get("token_name") or "").strip(),
        access_level=str(token_payload.get("access_level") or "").strip(),
        access_level_label=str(token_payload.get("access_level_label") or "").strip(),
        default_account_id=default_account_id,
    )


class MCPSelfServiceView(APIView):
    """Current-user MCP status, tokens, and copy-ready prompt context."""

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request: Request) -> Response:
        payload = _self_service_payload(
            user_id=_request_user_id(request),
            base_url=_base_url(request),
        )
        return Response(MCPSelfServicePayloadSerializer(payload).data)


class MCPSelfTokenCreateView(APIView):
    """Create one MCP token for the current user."""

    permission_classes = [IsAuthenticated, GeneralPermission]

    def post(self, request: Request) -> Response:
        user_id = _request_user_id(request)
        serializer = MCPTokenCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_name = _resolve_token_name(
            serializer.validated_data.get("token_name", ""),
            prefix="self",
        )
        try:
            outcome = interface_services.create_self_token(
                user_id,
                token_name=token_name,
                access_level=str(serializer.validated_data["access_level"]),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        refreshed = _self_service_payload(user_id=user_id, base_url=_base_url(request))
        payload = {
            "success": True,
            "message": outcome.message,
            "token_payload": outcome.payload,
            "created_agent_prompt": _created_agent_prompt(
                token_payload=outcome.payload,
                base_url=str(refreshed["base_url"]),
                default_account_id=refreshed.get("default_account_id"),
            ),
            "self_service": refreshed,
        }
        return Response(MCPMutationResultSerializer(payload).data, status=status.HTTP_201_CREATED)


class MCPSelfTokenRevokeView(APIView):
    """Revoke one MCP token owned by the current user."""

    permission_classes = [IsAuthenticated, GeneralPermission]

    def post(self, request: Request, token_id: int) -> Response:
        user_id = _request_user_id(request)
        token_id = _positive_path_id(token_id, field_name="token_id")
        try:
            outcome = interface_services.revoke_self_token(user_id, token_id)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        refreshed = _self_service_payload(user_id=user_id, base_url=_base_url(request))
        payload = {
            "success": True,
            "message": outcome.message,
            "token_id": token_id,
            "self_service": refreshed,
        }
        return Response(MCPMutationResultSerializer(payload).data)


class MCPAdminUsersView(APIView):
    """Admin MCP governance list for all users."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        serializer = MCPAdminUsersQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        payload = interface_services.build_admin_mcp_users_payload(
            search_query=str(serializer.validated_data.get("q") or ""),
            only_without_token=bool(serializer.validated_data.get("without_token", False)),
        )
        return Response(MCPAdminUsersPayloadSerializer(payload).data)


class MCPAdminUserDetailView(APIView):
    """Admin MCP detail for one specific user."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request, user_id: int) -> Response:
        user_id = _positive_path_id(user_id, field_name="user_id")
        try:
            payload = _admin_user_detail_payload(user_id=user_id, base_url=_base_url(request))
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(MCPAdminUserDetailSerializer(payload).data)


class MCPAdminUserTokenCreateView(APIView):
    """Admin creates one MCP token for a target user."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request, user_id: int) -> Response:
        actor_user_id = _request_user_id(request)
        user_id = _positive_path_id(user_id, field_name="user_id")
        serializer = MCPTokenCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_name = _resolve_token_name(
            serializer.validated_data.get("token_name", ""),
            prefix="admin",
        )
        try:
            outcome = interface_services.rotate_user_token(
                actor_user_id=actor_user_id,
                target_user_id=user_id,
                token_name=token_name,
                access_level=str(serializer.validated_data["access_level"]),
            )
            refreshed = _admin_user_detail_payload(user_id=user_id, base_url=_base_url(request))
        except UserModel.DoesNotExist:
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payload = {
            "success": True,
            "message": outcome.message,
            "token_payload": outcome.payload,
            "created_agent_prompt": _created_agent_prompt(
                token_payload=outcome.payload,
                base_url=str(refreshed.get("base_url") or _base_url(request)),
                default_account_id=refreshed.get("default_account_id"),
            ),
            "user_detail": refreshed,
        }
        return Response(MCPMutationResultSerializer(payload).data, status=status.HTTP_201_CREATED)


class MCPAdminUserTokensRevokeView(APIView):
    """Admin revokes all active MCP tokens for one target user."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request, user_id: int) -> Response:
        user_id = _positive_path_id(user_id, field_name="user_id")
        try:
            result = interface_services.revoke_user_tokens(user_id)
            refreshed = _admin_user_detail_payload(user_id=user_id, base_url=_base_url(request))
        except UserModel.DoesNotExist:
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        payload = {
            "success": True,
            "message": str(result.get("message") or ""),
            "user_detail": refreshed,
        }
        return Response(MCPMutationResultSerializer(payload).data)


class MCPAdminTokenRevokeView(APIView):
    """Admin revokes one specific MCP token by id."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request, token_id: int) -> Response:
        token_id = _positive_path_id(token_id, field_name="token_id")
        try:
            outcome = interface_services.revoke_access_token(token_id)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        payload = {
            "success": True,
            "message": outcome.message,
            "token_id": token_id,
        }
        return Response(MCPMutationResultSerializer(payload).data)


class MCPAdminUserToggleView(APIView):
    """Admin toggles MCP permission for one target user."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request, user_id: int) -> Response:
        user_id = _positive_path_id(user_id, field_name="user_id")
        try:
            outcome = interface_services.toggle_user_mcp(user_id)
            refreshed = _admin_user_detail_payload(user_id=user_id, base_url=_base_url(request))
        except UserModel.DoesNotExist:
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        payload = {
            "success": True,
            "message": outcome.message,
            "user_detail": refreshed,
        }
        return Response(MCPMutationResultSerializer(payload).data)
