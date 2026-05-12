"""Account portfolio and position API views."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.account.application import portfolio_api_services
from apps.audit.application import interface_services as audit_interface_services

from .permissions import ObserverAccessPermission
from .serializers import (
    PortfolioCreateSerializer,
    PortfolioSerializer,
    PortfolioStatisticsSerializer,
    PositionCreateSerializer,
    PositionSerializer,
    PositionUpdateSerializer,
)


class ObserverAuditMixin:
    """Shared audit logging helpers for observer-visible APIs."""

    def _log_observer_portfolio_access_if_needed(self, request, portfolio, action: str) -> None:
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
        request,
        portfolio,
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
        request,
        action: str,
        resource_type: str,
        resource_id: str,
        response_status: int,
        extra_context: dict[str, Any] | None = None,
    ) -> None:
        """Persist one audit record without interrupting the main flow."""

        try:
            import uuid

            audit_interface_services.log_operation_payload(
                request_id=str(uuid.uuid4()),
                user_id=request.user.id,
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
    def _get_client_ip(request):
        """Return the client IP address."""

        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0]
        return request.META.get("REMOTE_ADDR")


class PortfolioViewSet(ObserverAuditMixin, viewsets.ModelViewSet):
    """Portfolio API endpoints."""

    permission_classes = [IsAuthenticated, ObserverAccessPermission]

    def get_queryset(self):
        """Return portfolios accessible to the current user."""

        return portfolio_api_services.get_accessible_portfolios_queryset(self.request.user.id)

    def get_object(self):
        """Resolve one portfolio while preserving 404 vs 403 semantics."""

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        portfolio_id = self.kwargs[lookup_url_kwarg]
        try:
            context = portfolio_api_services.resolve_portfolio_for_user(
                user_id=self.request.user.id,
                portfolio_id=portfolio_id,
            )
        except portfolio_api_services.PortfolioNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except portfolio_api_services.PortfolioAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc

        self.check_object_permissions(self.request, context.portfolio)
        return context.portfolio

    def get_serializer_class(self):
        """Select the serializer for the current action."""

        if self.action == "create":
            return PortfolioCreateSerializer
        return PortfolioSerializer

    def perform_create(self, serializer):
        """Attach the authenticated user on create."""

        serializer.save(user=self.request.user)

    def update(self, request, *args, **kwargs):
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

    def destroy(self, request, *args, **kwargs):
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
    def positions(self, request, pk=None):
        """Return the portfolio positions payload."""

        try:
            context, payload = portfolio_api_services.get_portfolio_positions_payload(
                user_id=request.user.id,
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
    def statistics(self, request, pk=None):
        """Return summary statistics for one accessible portfolio."""

        try:
            context, payload = portfolio_api_services.get_portfolio_statistics_payload(
                user_id=request.user.id,
                portfolio_id=pk,
            )
        except portfolio_api_services.PortfolioNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except portfolio_api_services.PortfolioAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc

        self._log_observer_portfolio_access_if_needed(request, context.portfolio, "statistics")
        return Response(PortfolioStatisticsSerializer(payload).data)


class PositionViewSet(ObserverAuditMixin, viewsets.ModelViewSet):
    """Position API endpoints backed by the unified ledger."""

    permission_classes = [IsAuthenticated, ObserverAccessPermission]

    def get_queryset(self):
        """This viewset does not expose ORM querysets directly."""

        return []

    def get_serializer_class(self):
        """Select the serializer for the current action."""

        if self.action == "create":
            return PositionCreateSerializer
        if self.action in {"update", "partial_update"}:
            return PositionUpdateSerializer
        return PositionSerializer

    def create(self, request, *args, **kwargs):
        """Create one position through the application service boundary."""

        portfolio_id = request.data.get("portfolio")
        if portfolio_id in (None, ""):
            return Response(
                {"success": False, "error": "缺少 portfolio 参数"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            context = portfolio_api_services.resolve_portfolio_for_user(
                user_id=request.user.id,
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
                user_id=request.user.id,
                portfolio_id=portfolio_id,
                validated_data=serializer.validated_data,
            )
        except portfolio_api_services.PositionMutationDeniedError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(PositionSerializer(payload).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        """Return one accessible position."""

        try:
            context, payload = portfolio_api_services.get_position_payload(
                user_id=request.user.id,
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

    def update(self, request, *args, **kwargs):
        """Update one position through the application service boundary."""

        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            payload = portfolio_api_services.update_position_payload(
                user_id=request.user.id,
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

    def partial_update(self, request, *args, **kwargs):
        """Support PATCH updates."""

        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """Delete one position through the application service boundary."""

        try:
            portfolio_api_services.delete_position(
                user_id=request.user.id,
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

    def list(self, request, *args, **kwargs):
        """Return unified positions across all accessible portfolios."""

        payload, observer_portfolios = portfolio_api_services.list_positions_payload(
            user_id=request.user.id,
            portfolio_id=request.query_params.get("portfolio_id"),
            asset_code=request.query_params.get("asset_code"),
        )
        page = self.paginate_queryset(payload)
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

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Close one position through the application service boundary."""

        close_shares_raw = request.data.get("shares")
        close_shares = float(close_shares_raw) if close_shares_raw is not None else None

        try:
            payload = portfolio_api_services.close_position_payload(
                user_id=request.user.id,
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
