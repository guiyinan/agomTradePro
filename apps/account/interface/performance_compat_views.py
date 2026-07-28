"""
账户业绩与估值兼容 API 视图（account app 入口）

将 /api/account/portfolios/{portfolio_id}/xxx/ 路由代理到
/api/simulated-trading/accounts/{account_id}/xxx/ 同名用例。

通过 LedgerMigrationMapModel 找到 portfolio → unified_account 的映射。
"""

from __future__ import annotations

import logging

from django.http import HttpRequest
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application import interface_services
from apps.account.application.simulated_trading_gateway import (
    AccountViewKey,
    get_simulated_trading_view,
)

logger = logging.getLogger(__name__)

_MAX_DATABASE_ID = 2_147_483_647
_VIEW_RESOLUTION_EXCEPTIONS = (AttributeError, LookupError, RuntimeError, TypeError)


def _resolve_account_id(portfolio_id: object) -> int | None:
    """
    通过 LedgerMigrationMapModel 将 portfolio_id 映射到统一账户 ID。
    未找到映射则返回 None。
    """
    if isinstance(portfolio_id, bool) or not isinstance(portfolio_id, int):
        return None
    if not 1 <= portfolio_id <= _MAX_DATABASE_ID:
        return None
    account_id = interface_services.get_unified_account_id_for_portfolio(portfolio_id)
    if isinstance(account_id, bool) or not isinstance(account_id, int):
        return None
    return account_id if 1 <= account_id <= _MAX_DATABASE_ID else None


def _delegate(
    request: Request,
    account_id: int,
    view_key: AccountViewKey,
    **kwargs: object,
) -> Response:
    """将请求委托给 simulated_trading 对应视图类。"""

    raw_request = getattr(request, "_request", None)
    if not isinstance(raw_request, HttpRequest):
        logger.error("Account compatibility delegation received an invalid request shape")
        return Response(
            {"error": "账户服务暂时不可用"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        view_class = get_simulated_trading_view(view_key)
        view = view_class.as_view()
    except _VIEW_RESOLUTION_EXCEPTIONS as exc:
        logger.error(
            "Failed to resolve account compatibility view %s: %s",
            view_key,
            type(exc).__name__,
        )
        return Response(
            {"error": "账户服务暂时不可用"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    response = view(raw_request, account_id=account_id, **kwargs)
    if not isinstance(response, Response):
        logger.error(
            "Account compatibility view %s returned an invalid response type %s",
            view_key,
            type(response).__name__,
        )
        return Response(
            {"error": "账户服务暂时不可用"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return response


class PortfolioPerformanceReportCompatView(APIView):
    """
    GET /api/account/portfolios/{portfolio_id}/performance-report/

    兼容入口，委托给统一账户业绩报告接口。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, portfolio_id: int) -> Response:
        account_id = _resolve_account_id(portfolio_id)
        if account_id is None:
            return Response(
                {"error": f"portfolio {portfolio_id} 未找到对应的统一账户，请先执行账本迁移"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _delegate(
            request,
            account_id,
            "account-performance-report",
        )


class PortfolioValuationSnapshotCompatView(APIView):
    """
    GET /api/account/portfolios/{portfolio_id}/valuation-snapshot/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, portfolio_id: int) -> Response:
        account_id = _resolve_account_id(portfolio_id)
        if account_id is None:
            return Response(
                {"error": f"portfolio {portfolio_id} 未找到对应的统一账户"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _delegate(
            request,
            account_id,
            "account-valuation-snapshot",
        )


class PortfolioValuationTimelineCompatView(APIView):
    """
    GET /api/account/portfolios/{portfolio_id}/valuation-timeline/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, portfolio_id: int) -> Response:
        account_id = _resolve_account_id(portfolio_id)
        if account_id is None:
            return Response(
                {"error": f"portfolio {portfolio_id} 未找到对应的统一账户"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _delegate(
            request,
            account_id,
            "account-valuation-timeline",
        )


class PortfolioBenchmarksCompatView(APIView):
    """
    GET|PUT /api/account/portfolios/{portfolio_id}/benchmarks/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, portfolio_id: int) -> Response:
        account_id = _resolve_account_id(portfolio_id)
        if account_id is None:
            return Response(
                {"error": f"portfolio {portfolio_id} 未找到对应的统一账户"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _delegate(request, account_id, "account-benchmarks")

    def put(self, request: Request, portfolio_id: int) -> Response:
        account_id = _resolve_account_id(portfolio_id)
        if account_id is None:
            return Response(
                {"error": f"portfolio {portfolio_id} 未找到对应的统一账户"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _delegate(request, account_id, "account-benchmarks")
