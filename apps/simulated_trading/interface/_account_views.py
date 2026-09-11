"""Account lifecycle API views for simulated trading.

The compatibility facade in :mod:`views` keeps the established import surface;
this module owns account listing, creation, deletion, and detail handlers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar, cast

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application import interface_services as simulated_interface_services

from ._view_helpers import (
    _account_payload,
    _delete_account_with_summary,
    _get_owned_account_or_response,
)
from .serializers import (
    AccountBatchDeleteRequestSerializer,
    AccountBatchDeleteResponseSerializer,
    AccountDeleteResponseSerializer,
    AccountResponseSerializer,
)

ViewMethodT = TypeVar("ViewMethodT", bound=Callable[..., Any])


class ExtendSchemaProtocol(Protocol):
    """Typed façade for drf-spectacular's decorator factory."""

    def __call__(self, *args: Any, **kwargs: Any) -> Callable[[ViewMethodT], ViewMethodT]: ...


typed_extend_schema = cast(ExtendSchemaProtocol, extend_schema)


__all__ = [
    "AccountBatchDeleteAPIView",
    "AccountDetailAPIView",
]


class AccountDetailAPIView(APIView):
    """账户详情与删除 API。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.account_repo = simulated_interface_services.get_account_repository()
        self.position_repo = simulated_interface_services.get_position_repository()
        self.trade_repo = simulated_interface_services.get_trade_repository()

    @typed_extend_schema(
        summary="获取账户详情",
        description="获取单个账户的完整信息",
        responses={200: AccountResponseSerializer},
    )
    def get(self, request: Request, account_id: int) -> Response:
        """Return one account after checking caller ownership."""

        account_model = _get_owned_account_or_response(request, account_id, action="查看")
        if isinstance(account_model, Response):
            return account_model

        account = self.account_repo.get_by_id(account_id)
        if not account:
            return Response(
                {"success": False, "error": f"账户不存在: {account_id}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, "account": _account_payload(account)})

    @typed_extend_schema(
        summary="删除账户",
        description="删除当前用户拥有的单个模拟/实仓账户，并级联删除关联持仓、交易与巡检记录。",
        responses={200: AccountDeleteResponseSerializer},
    )
    def delete(self, request: Request, account_id: int) -> Response:
        """Delete one owned account and return cascade statistics."""

        if not request.user or not request.user.is_authenticated:
            return Response(
                {"success": False, "error": "请先登录后再执行删除操作"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        account = _get_owned_account_or_response(request, account_id, action="删除")
        if isinstance(account, Response):
            return account

        summary = _delete_account_with_summary(account)
        return Response(
            {
                "success": True,
                **summary,
                "message": f"账户 {summary['account_name']} 已删除",
            }
        )


class AccountBatchDeleteAPIView(APIView):
    """账户批量删除 API。"""

    @typed_extend_schema(
        summary="批量删除账户",
        description="批量删除当前用户拥有的账户，并返回逐项失败原因。",
        request=AccountBatchDeleteRequestSerializer,
        responses={200: AccountBatchDeleteResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        """Delete each requested owned account and report itemized failures."""

        if not request.user or not request.user.is_authenticated:
            return Response(
                {"success": False, "error": "请先登录后再执行删除操作"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = AccountBatchDeleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        deleted_account_ids = []
        deleted_account_names = []
        failed = []
        for account_id in serializer.validated_data["account_ids"]:
            account = _get_owned_account_or_response(request, account_id, action="删除")
            if isinstance(account, Response):
                failed.append({"account_id": account_id, "error": account.data.get("error")})
                continue

            summary = _delete_account_with_summary(account)
            deleted_account_ids.append(summary["account_id"])
            deleted_account_names.append(summary["account_name"])

        return Response(
            {
                "success": True,
                "requested_count": len(serializer.validated_data["account_ids"]),
                "deleted_count": len(deleted_account_ids),
                "deleted_account_ids": deleted_account_ids,
                "deleted_account_names": deleted_account_names,
                "failed": failed,
                "message": f"已删除 {len(deleted_account_ids)} 个账户",
            }
        )
