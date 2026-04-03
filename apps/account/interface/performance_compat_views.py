"""
账户业绩与估值兼容 API 视图（account app 入口）

将 /api/account/portfolios/{portfolio_id}/xxx/ 路由代理到
/api/simulated-trading/accounts/{account_id}/xxx/ 同名用例。

通过 LedgerMigrationMapModel 找到 portfolio → unified_account 的映射。
"""
from __future__ import annotations

import logging
from typing import Optional

from django.apps import apps as django_apps
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


def _resolve_account_id(portfolio_id: int) -> Optional[int]:
    """
    通过 LedgerMigrationMapModel 将 portfolio_id 映射到统一账户 ID。
    未找到映射则返回 None。
    """
    LedgerMigrationMapModel = django_apps.get_model("simulated_trading", "LedgerMigrationMapModel")

    mapping = (
        LedgerMigrationMapModel.objects.filter(
            source_table="portfolio",
            source_id=portfolio_id,
            target_table="simulated_account",
        )
        .values_list("target_id", flat=True)
        .first()
    )
    return mapping


def _delegate(request: Request, account_id: int, view_class, **kwargs):
    """将请求委托给 simulated_trading 对应视图类。"""
    view = view_class.as_view()
    return view(request._request, account_id=account_id, **kwargs)


class PortfolioPerformanceReportCompatView(APIView):
    """
    GET /api/account/portfolios/{portfolio_id}/performance-report/

    兼容入口，委托给统一账户业绩报告接口。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, portfolio_id: int) -> Response:
        from apps.simulated_trading.interface.performance_views import AccountPerformanceReportAPIView

        account_id = _resolve_account_id(portfolio_id)
        if account_id is None:
            return Response(
                {"error": f"portfolio {portfolio_id} 未找到对应的统一账户，请先执行账本迁移"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _delegate(request, account_id, AccountPerformanceReportAPIView)


class PortfolioValuationSnapshotCompatView(APIView):
    """
    GET /api/account/portfolios/{portfolio_id}/valuation-snapshot/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, portfolio_id: int) -> Response:
        from apps.simulated_trading.interface.performance_views import AccountValuationSnapshotAPIView

        account_id = _resolve_account_id(portfolio_id)
        if account_id is None:
            return Response(
                {"error": f"portfolio {portfolio_id} 未找到对应的统一账户"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _delegate(request, account_id, AccountValuationSnapshotAPIView)


class PortfolioValuationTimelineCompatView(APIView):
    """
    GET /api/account/portfolios/{portfolio_id}/valuation-timeline/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, portfolio_id: int) -> Response:
        from apps.simulated_trading.interface.performance_views import AccountValuationTimelineAPIView

        account_id = _resolve_account_id(portfolio_id)
        if account_id is None:
            return Response(
                {"error": f"portfolio {portfolio_id} 未找到对应的统一账户"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _delegate(request, account_id, AccountValuationTimelineAPIView)


class PortfolioBenchmarksCompatView(APIView):
    """
    GET|PUT /api/account/portfolios/{portfolio_id}/benchmarks/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, portfolio_id: int) -> Response:
        from apps.simulated_trading.interface.performance_views import AccountBenchmarksAPIView

        account_id = _resolve_account_id(portfolio_id)
        if account_id is None:
            return Response(
                {"error": f"portfolio {portfolio_id} 未找到对应的统一账户"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _delegate(request, account_id, AccountBenchmarksAPIView)

    def put(self, request: Request, portfolio_id: int) -> Response:
        from apps.simulated_trading.interface.performance_views import AccountBenchmarksAPIView

        account_id = _resolve_account_id(portfolio_id)
        if account_id is None:
            return Response(
                {"error": f"portfolio {portfolio_id} 未找到对应的统一账户"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return _delegate(request, account_id, AccountBenchmarksAPIView)
