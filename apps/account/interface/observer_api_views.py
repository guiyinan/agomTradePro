"""Account observer grant API views."""

import logging
import uuid
from collections.abc import Callable
from typing import Any, TypeVar, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    PermissionDenied,
)
from rest_framework.exceptions import (
    ValidationError as DRFValidationError,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from apps.account.application import interface_services
from apps.account.application.business_provider_gateway import log_audit_operation

from .permissions import GeneralPermission
from .serializers import (
    ObserverGrantCreateSerializer,
    ObserverGrantSerializer,
    ObserverGrantUpdateSerializer,
)

ViewMethod = TypeVar("ViewMethod", bound=Callable[..., Any])
typed_action = cast(
    Callable[..., Callable[[ViewMethod], ViewMethod]],
    action,
)
logger = logging.getLogger(__name__)


def _authenticated_user_id(request: Request) -> int:
    """Return a valid authenticated user id for owner-scoped operations."""

    user_id = getattr(request.user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise PermissionDenied("用户身份无效")
    return user_id


class ObserverGrantViewSet(viewsets.ModelViewSet[Any]):
    """
    观察员授权 API ViewSet

    提供以下接口:
    - GET /api/account/observer-grants/ - 获取当前用户的授权列表
    - POST /api/account/observer-grants/ - 创建观察员授权
    - GET /api/account/observer-grants/{id}/ - 获取授权详情
    - PUT /api/account/observer-grants/{id}/ - 更新授权（过期时间）
    - DELETE /api/account/observer-grants/{id}/ - 撤销授权
    """

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get_queryset(self) -> Any:
        """支持 owner 和 observer 双视角查询"""
        unknown_params = set(self.request.query_params) - {"as_observer", "status"}
        if unknown_params:
            raise DRFValidationError(
                {"detail": f"不支持的查询参数: {', '.join(sorted(unknown_params))}"}
            )
        as_observer_value = self.request.query_params.get("as_observer")
        if as_observer_value not in (None, "0", "1"):
            raise DRFValidationError({"as_observer": "必须为 0 或 1"})
        as_observer = as_observer_value == "1"
        status_filter = self.request.query_params.get("status")
        if status_filter not in (None, "active", "revoked", "expired"):
            raise DRFValidationError(
                {"status": "必须为 active、revoked 或 expired"}
            )
        return interface_services.list_observer_grants_queryset(
            user_id=_authenticated_user_id(self.request),
            as_observer=as_observer,
            status_filter=status_filter,
        )

    def get_object(self) -> Any:
        """
        对写操作使用全量查询后做显式鉴权，确保“对象存在但无权限”返回 403。
        """
        if self.action in ["destroy", "update", "partial_update", "retrieve", "positions"]:
            lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
            lookup_value = self.kwargs.get(lookup_url_kwarg)
            try:
                grant = interface_services.get_observer_grant_by_id(lookup_value)
            except DjangoValidationError as exc:
                raise DRFValidationError({"detail": "授权 ID 格式无效"}) from exc
            if grant is None:
                raise Http404
            user_id = _authenticated_user_id(self.request)
            if self.action in ["retrieve", "positions"]:
                if (
                    grant.owner_user_id_id == user_id
                    or grant.observer_user_id_id == user_id
                ):
                    return grant
                self.permission_denied(self.request, message="无权访问此授权")
            if grant.owner_user_id_id != user_id:
                self.permission_denied(self.request, message="无权访问此授权")
            return grant
        return super().get_object()

    @typed_action(detail=True, methods=["get"])
    def positions(self, request: Request, pk: str | None = None) -> Response:
        """
        获取授权对应账户的持仓列表（观察员专用）

        GET /api/account/observer-grants/{id}/positions/
        """
        grant = self.get_object()

        # 验证当前用户是该授权的观察员
        if grant.observer_user_id_id != _authenticated_user_id(request):
            return Response(
                {"success": False, "error": "您无权查看此授权的持仓信息"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 验证授权状态
        if grant.status != "active":
            return Response(
                {"success": False, "error": f"授权状态为 {grant.get_status_display()}，无法查看"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 检查授权是否过期
        if grant.is_expired():
            return Response(
                {"success": False, "error": "授权已过期，无法查看"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = interface_services.build_observer_positions_payload(grant.owner_user_id_id)

        # 记录观察员访问审计日志
        self._log_audit_action(
            request=request,
            action="READ",
            resource_type="observer_grant_positions",
            resource_id=str(grant.id),
            response_status=200,
            extra_context={
                "grant_owner": grant.owner_user_id.username,
                "portfolio_id": payload["portfolio_id"],
            },
        )

        return Response(
            {
                "success": True,
                "data": {
                    "positions": payload["positions"],
                    "statistics": payload["statistics"],
                },
            }
        )

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        """根据操作选择 serializer"""
        if self.action == "create":
            return ObserverGrantCreateSerializer
        elif self.action in ["update", "partial_update"]:
            return ObserverGrantUpdateSerializer
        return ObserverGrantSerializer

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """创建时自动关联当前用户为 owner"""
        serializer.save(owner_user_id=self.request.user)

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        """更新时通过 application service 下沉持久化。"""

        instance = serializer.instance
        if instance is None:
            raise RuntimeError("观察员授权更新缺少持久化对象")
        serializer.instance = interface_services.update_observer_grant(
            grant_id=instance.id,
            expires_at=serializer.validated_data.get("expires_at", instance.expires_at),
        )

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        撤销授权（软删除）

        DELETE /api/account/observer-grants/{id}/
        """
        grant = self.get_object()

        # 验证权限：只有 owner 可以撤销
        user_id = _authenticated_user_id(request)
        if grant.owner_user_id_id != user_id:
            return Response(
                {"success": False, "error": "无权撤销此授权"}, status=status.HTTP_403_FORBIDDEN
            )

        # 已撤销或过期的授权不能再次撤销
        if grant.status != "active":
            return Response(
                {"success": False, "error": f"授权状态为 {grant.get_status_display()}，无法撤销"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 撤销授权
        grant = interface_services.revoke_observer_grant(
            grant_id=grant.id,
            revoked_by_user_id=user_id,
        )

        # 审计打点
        self._log_audit_action(
            request=request,
            action="DELETE",
            resource_type="observer_grant",
            resource_id=str(grant.id),
            response_status=200,
        )

        serializer = ObserverGrantSerializer(grant)
        return Response({"success": True, "message": "授权已撤销", "data": serializer.data})

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        创建观察员授权

        POST /api/account/observer-grants/
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        # 审计打点
        grant = serializer.instance
        if grant is None:
            raise RuntimeError("观察员授权创建未返回持久化对象")
        self._log_audit_action(
            request=request,
            action="CREATE",
            resource_type="observer_grant",
            resource_id=str(grant.id),
            response_status=201,
        )

        # 使用完整序列化器返回创建的数据
        response_serializer = ObserverGrantSerializer(grant)
        headers = self.get_success_headers(response_serializer.data)
        return Response(
            {"success": True, "message": "观察员授权创建成功", "data": response_serializer.data},
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def _log_audit_action(
        self,
        request: Request,
        action: str,
        resource_type: str,
        resource_id: str,
        response_status: int,
        extra_context: dict[str, Any] | None = None,
    ) -> None:
        """
        记录审计日志

        Args:
            request: 请求对象
            action: 操作动作 (CREATE/DELETE/UPDATE/READ)
            resource_type: 资源类型
            resource_id: 资源ID
            response_status: 响应状态码
        """
        try:
            log_audit_operation(
                request_id=str(uuid.uuid4()),
                user_id=_authenticated_user_id(request),
                username=request.user.username,
                source="API",
                operation_type=(
                    "DATA_MODIFY" if action in ("CREATE", "DELETE", "UPDATE") else "API_ACCESS"
                ),
                module="account",
                action=action,
                request_params=extra_context or {},
                resource_type=resource_type,
                resource_id=resource_id,
                request_method=request.method,
                request_path=request.path,
                response_status=response_status,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            )

        except Exception:
            # 审计失败不影响主流程
            logger.exception("记录观察员授权审计日志失败")

    @staticmethod
    def _get_client_ip(request: Request) -> str | None:
        """获取客户端IP地址"""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip if isinstance(ip, str) else None
