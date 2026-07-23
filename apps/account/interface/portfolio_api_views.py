"""Account portfolio and position API views."""

from __future__ import annotations

from typing import Any, cast

from django.core.exceptions import PermissionDenied
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated, NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.account.application import portfolio_api_services
from apps.account.application.business_provider_gateway import log_audit_operation

from .permissions import ObserverAccessPermission
from .serializers import (
    PortfolioCreateSerializer,
    PortfolioSerializer,
    PortfolioStatisticsSerializer,
    PositionCreateSerializer,
    PositionSerializer,
    PositionUpdateSerializer,
)


def _authenticated_user_id(request: Request) -> int:
    """Return the persisted user ID guaranteed by the API permission boundary."""

    user_id = getattr(request.user, "id", None)
    if not isinstance(user_id, int):
        raise NotAuthenticated("Authenticated user has no persisted ID")
    return user_id


class ObserverAuditMixin:
    """Shared audit logging helpers for observer-visible APIs."""

    def _log_observer_portfolio_access_if_needed(
        self, request: Request, portfolio: Any, action: str
    ) -> None:
        """Log portfolio-level observer access when the actor is not the owner."""

        if portfolio.user != request.user:
            self._log_audit_action(
                request=request,
                action="READ",
                resource_type="portfolio_via_observer_grant",
                resource_id=str(portfolio.id),
                response_status=200,
                extra_context={
                    "portfolio_owner": portfolio.user.username,
                    "portfolio_name": portfolio.name,
                    "access_action": action,
                },
            )

    def _log_observer_position_access_if_needed(
        self,
        request: Request,
        portfolio: Any,
        asset_code: str,
        action: str,
    ) -> None:
        """Log position-level observer access when the actor is not the owner."""

        if portfolio.user != request.user:
            self._log_audit_action(
                request=request,
                action="READ",
                resource_type="position_via_observer_grant",
                resource_id=f"{portfolio.id}:{asset_code}",
                response_status=200,
                extra_context={
                    "portfolio_owner": portfolio.user.username,
                    "portfolio_name": portfolio.name,
                    "position_asset": asset_code,
                    "access_action": action,
                },
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
        """Persist one audit record without interrupting the main flow."""

        try:
            import uuid

            log_audit_operation(
                request_id=str(uuid.uuid4()),
                user_id=_authenticated_user_id(request),
                username=request.user.username,
                source="API",
                operation_type="API_ACCESS",
                module="account",
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                request_method=request.method,
                request_path=request.path,
                response_status=response_status,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
                request_params=extra_context or {},
            )
        except Exception as exc:  # pragma: no cover - audit must stay best effort
            import logging

            logging.getLogger(__name__).error("记录审计日志失败: %s", exc, exc_info=True)

    @staticmethod
    def _get_client_ip(request: Request) -> str | None:
        """Return the client IP address."""

        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return str(x_forwarded_for).split(",")[0]
        remote_addr = request.META.get("REMOTE_ADDR")
        return str(remote_addr) if remote_addr else None


class PortfolioViewSet(ObserverAuditMixin, viewsets.ModelViewSet[Any]):
    """Portfolio API endpoints."""

    permission_classes = [IsAuthenticated, ObserverAccessPermission]

    def get_queryset(self) -> Any:
        """Return portfolios accessible to the current user."""

        return portfolio_api_services.get_accessible_portfolios_queryset(
            _authenticated_user_id(self.request)
        )

    def get_object(self) -> Any:
        """Resolve one portfolio while preserving 404 vs 403 semantics."""

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        portfolio_id = self.kwargs[lookup_url_kwarg]
        try:
            context = portfolio_api_services.resolve_portfolio_for_user(
                user_id=_authenticated_user_id(self.request),
                portfolio_id=portfolio_id,
            )
        except portfolio_api_services.PortfolioNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except portfolio_api_services.PortfolioAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc

        self.check_object_permissions(self.request, context.portfolio)
        return context.portfolio

    def get_serializer_class(self) -> Any:
        """Select the serializer for the current action."""

        if self.action == "create":
            return PortfolioCreateSerializer
        return PortfolioSerializer

    def perform_create(self, serializer: Any) -> None:
        """Attach the authenticated user on create."""

        serializer.save(user=self.request.user)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Owners can update portfolios; observers receive 403."""

        portfolio = self.get_object()
        if portfolio.user != request.user:
            return Response(
                {
                    "success": False,
                    "error": "观察员无权更新投资组合，只有账户拥有者可以执行此操作",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().update(request, *args, **kwargs)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Owners can delete portfolios; observers receive 403."""

        portfolio = self.get_object()
        if portfolio.user != request.user:
            return Response(
                {
                    "success": False,
                    "error": "观察员无权删除投资组合，只有账户拥有者可以执行此操作",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"])
    def positions(self, request: Request, pk: Any = None) -> Response:
        """Return the portfolio positions payload."""

        try:
            context, payload = portfolio_api_services.get_portfolio_positions_payload(
                user_id=_authenticated_user_id(request),
                portfolio_id=pk,
            )
        except portfolio_api_services.PortfolioNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except portfolio_api_services.PortfolioAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc

        self._log_observer_portfolio_access_if_needed(request, context.portfolio, "positions")
        serializer = PositionSerializer(payload, many=True)
        return Response(
            {
                "success": True,
                "count": len(payload),
                "data": serializer.data,
            }
        )

    @action(detail=True, methods=["get"])
    def statistics(self, request: Request, pk: Any = None) -> Response:
        """Return summary statistics for one accessible portfolio."""

        try:
            context, payload = portfolio_api_services.get_portfolio_statistics_payload(
                user_id=_authenticated_user_id(request),
                portfolio_id=pk,
            )
        except portfolio_api_services.PortfolioNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except portfolio_api_services.PortfolioAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc

        self._log_observer_portfolio_access_if_needed(request, context.portfolio, "statistics")
        return Response(PortfolioStatisticsSerializer(payload).data)


class PositionViewSet(ObserverAuditMixin, viewsets.ModelViewSet[Any]):
    """Position API endpoints backed by the unified ledger."""

    permission_classes = [IsAuthenticated, ObserverAccessPermission]

    def get_queryset(self) -> Any:
        """This viewset does not expose ORM querysets directly."""

        return []

    def get_serializer_class(self) -> Any:
        """Select the serializer for the current action."""

        if self.action == "create":
            return PositionCreateSerializer
        if self.action in {"update", "partial_update"}:
            return PositionUpdateSerializer
        return PositionSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create one position through the application service boundary."""

        portfolio_id_raw = request.data.get("portfolio")
        if portfolio_id_raw in (None, ""):
            return Response(
                {"success": False, "error": "缺少 portfolio 参数"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(portfolio_id_raw, (int, str)):
            return Response(
                {"success": False, "error": "portfolio 参数格式无效"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        portfolio_id: int | str = portfolio_id_raw
        try:
            context = portfolio_api_services.resolve_portfolio_for_user(
                user_id=_authenticated_user_id(request),
                portfolio_id=portfolio_id,
            )
        except portfolio_api_services.PortfolioNotFoundError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )
        except portfolio_api_services.PortfolioAccessDeniedError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not context.is_owner:
            return Response(
                {
                    "success": False,
                    "error": "观察员无权创建持仓，只有账户拥有者可以执行此操作",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payload = portfolio_api_services.create_position_payload(
                user_id=_authenticated_user_id(request),
                portfolio_id=portfolio_id,
                validated_data=serializer.validated_data,
            )
        except portfolio_api_services.PositionMutationDeniedError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(PositionSerializer(payload).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return one accessible position."""

        try:
            context, payload = portfolio_api_services.get_position_payload(
                user_id=_authenticated_user_id(request),
                position_id=kwargs["pk"],
            )
        except portfolio_api_services.PositionNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except portfolio_api_services.PortfolioAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc

        self._log_observer_position_access_if_needed(
            request,
            context.portfolio,
            payload["asset_code"],
            "detail",
        )
        return Response(PositionSerializer(payload).data)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Update one position through the application service boundary."""

        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            payload = portfolio_api_services.update_position_payload(
                user_id=_authenticated_user_id(request),
                position_id=kwargs["pk"],
                validated_data=serializer.validated_data,
            )
        except portfolio_api_services.PositionNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except portfolio_api_services.PositionMutationDeniedError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except portfolio_api_services.PortfolioAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc

        return Response(PositionSerializer(payload).data)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Support PATCH updates."""

        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Delete one position through the application service boundary."""

        try:
            portfolio_api_services.delete_position(
                user_id=_authenticated_user_id(request),
                position_id=kwargs["pk"],
            )
        except portfolio_api_services.PositionNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except portfolio_api_services.PositionMutationDeniedError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except portfolio_api_services.PortfolioAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc

        return Response(status=status.HTTP_204_NO_CONTENT)

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return unified positions across all accessible portfolios."""

        payload, observer_portfolios = portfolio_api_services.list_positions_payload(
            user_id=_authenticated_user_id(request),
            portfolio_id=request.query_params.get("portfolio_id"),
            asset_code=request.query_params.get("asset_code"),
        )
        page = self.paginate_queryset(cast(Any, payload))
        positions = page if page is not None else payload

        for portfolio in observer_portfolios:
            self._log_audit_action(
                request=request,
                action="READ",
                resource_type="position_via_observer_grant",
                resource_id=f"portfolio_{portfolio.id}",
                response_status=200,
                extra_context={"portfolio_id": str(portfolio.id)},
            )

        serializer = PositionSerializer(positions, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="read-only")
    def read_only(self, request: Request) -> Response:
        """Return position projections without synchronizing the unified ledger."""

        portfolio_id_raw = request.query_params.get("portfolio_id")
        portfolio_id = (
            int(portfolio_id_raw)
            if isinstance(portfolio_id_raw, str) and portfolio_id_raw
            else None
        )
        include_closed = request.query_params.get("include_closed", "").lower() in {
            "1",
            "true",
            "yes",
        }
        payload = portfolio_api_services.list_position_records_read_payload(
            user_id=_authenticated_user_id(request),
            portfolio_id=portfolio_id,
            asset_code=request.query_params.get("asset_code"),
            include_closed=include_closed,
        )
        page = self.paginate_queryset(cast(Any, payload))
        positions = page if page is not None else payload
        serializer = PositionSerializer(positions, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def close(self, request: Request, pk: Any = None) -> Response:
        """Close one position through the application service boundary."""

        close_shares_raw = request.data.get("shares")
        close_shares = float(close_shares_raw) if close_shares_raw is not None else None

        try:
            payload = portfolio_api_services.close_position_payload(
                user_id=_authenticated_user_id(request),
                position_id=pk,
                close_shares=close_shares,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except RuntimeError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except portfolio_api_services.PositionNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except portfolio_api_services.PositionMutationDeniedError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except portfolio_api_services.PortfolioAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc

        return Response(
            {
                "success": True,
                "message": "持仓已平仓",
                "data": PositionSerializer(payload).data,
            }
        )
