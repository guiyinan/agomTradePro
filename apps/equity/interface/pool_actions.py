"""Stock-pool actions for the equity API viewset.

Owns `EquityPoolActionsMixin`. The compatibility facade in `views.py` composes
the final `EquityViewSet` and keeps the legacy monkeypatch surface; do not
import it here.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.data_center.application.public import get_decision_publication_gate
from apps.equity.application.query_services import get_published_stock_context_map
from apps.equity.application.use_cases import ScreenStocksUseCase
from shared.numeric import safe_float

from .pool_refresh_actions import EquityPoolRefreshActionsMixin
from .serializers import PoolActionRequestSerializer
from .valuation_actions import typed_action

if TYPE_CHECKING:
    from apps.equity.application.repository_provider import (
        DjangoStockRepository,
        RegimeRepositoryAdapter,
        StockPoolRepositoryAdapter,
    )

logger = logging.getLogger(__name__)


def _build_sector_distribution(
    stocks: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Aggregate stock rows into portable sector-count chart rows."""

    counts: dict[str, int] = {}
    for stock in stocks:
        sector = str(stock.get("sector") or "未知")
        counts[sector] = counts.get(sector, 0) + 1
    return [
        {"sector": sector, "count": count}
        for sector, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


class EquityPoolActionsMixin(EquityPoolRefreshActionsMixin):
    """Current-pool query and Regime-driven pool refresh actions."""

    stock_repo: DjangoStockRepository
    regime_repo: RegimeRepositoryAdapter
    pool_adapter: StockPoolRepositoryAdapter

    def _build_screen_use_case(self) -> ScreenStocksUseCase:
        """Keep the legacy pool module use-case patch surface working."""

        return ScreenStocksUseCase(
            stock_repository=self.stock_repo,
            regime_repository=self.regime_repo,
        )

    @typed_action(
        detail=False,
        methods=["get"],
        url_path="pool",
        permission_classes=[IsAuthenticated],
    )
    def get_pool(self, request: Request) -> Response:
        """
        GET /api/equity/pool/

        获取当前股票池
        """
        serializer = PoolActionRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        mode = str(serializer.validated_data["mode"])
        publication_key = str(serializer.validated_data["publication_key"])

        try:
            stock_codes = self.pool_adapter.get_current_pool()

            pool_info = self.pool_adapter.get_latest_pool_info()

            pool_regime = str((pool_info or {}).get("regime") or "").strip()
            latest_regime_name = self._resolve_current_regime_name() if not pool_regime else None
            displayed_regime = pool_regime or latest_regime_name

            if not stock_codes:
                # 如果没有股票池，返回空结果
                return Response(
                    {
                        "success": True,
                        "regime": displayed_regime,
                        "count": 0,
                        "update_time": None,
                        "avg_roe": None,
                        "avg_pe": None,
                        "stocks": [],
                        "sector_distribution": [],
                    }
                )

            publication_gates: dict[str, object] = {}
            if mode == "published":
                for dataset_key in ("equity.financial.fact", "equity.valuation.fact"):
                    publication_gates[dataset_key] = get_decision_publication_gate(
                        dataset_key,
                        publication_key,
                    )
                blocked_gates = [
                    gate
                    for gate in publication_gates.values()
                    if not isinstance(gate, dict) or bool(gate.get("must_not_use_for_decision"))
                ]
                if blocked_gates:
                    first_gate = blocked_gates[0]
                    blocked_reason = (
                        str(first_gate.get("blocked_reason") or "canonical_publication_missing")
                        if isinstance(first_gate, dict)
                        else "canonical_publication_missing"
                    )
                    return Response(
                        {
                            "success": False,
                            "status": "blocked",
                            "regime": displayed_regime,
                            "count": 0,
                            "update_time": (pool_info or {}).get("updated_at"),
                            "avg_roe": None,
                            "avg_pe": None,
                            "stocks": [],
                            "sector_distribution": [],
                            "mode": mode,
                            "publication_key": publication_key,
                            "publication_gates": publication_gates,
                            "must_not_use_for_decision": True,
                            "blocked_reason": blocked_reason,
                        },
                        status=status.HTTP_200_OK,
                    )

                published_context = get_published_stock_context_map(
                    stock_codes[:100],
                    publication_key=publication_key,
                    include_price=False,
                )
                blocked_contexts = [
                    row
                    for row in published_context.values()
                    if bool(row.get("must_not_use_for_decision"))
                ]
                if len(published_context) < min(len(stock_codes), 100) or blocked_contexts:
                    first_block = blocked_contexts[0] if blocked_contexts else {}
                    return Response(
                        {
                            "success": False,
                            "status": "blocked",
                            "regime": displayed_regime,
                            "count": 0,
                            "update_time": (pool_info or {}).get("updated_at"),
                            "avg_roe": None,
                            "avg_pe": None,
                            "stocks": [],
                            "sector_distribution": [],
                            "mode": mode,
                            "publication_key": publication_key,
                            "publication_gates": publication_gates,
                            "must_not_use_for_decision": True,
                            "blocked_reason": str(
                                first_block.get("blocked_reason")
                                or "canonical_publication_members_missing"
                            ),
                        },
                        status=status.HTTP_200_OK,
                    )
            else:
                published_context = {}

            # 获取股票详细信息
            stocks: list[dict[str, object]] = []
            total_roe = 0.0
            valid_roe_count = 0
            total_pe = 0.0
            valid_pe_count = 0
            end_date = timezone.localdate()
            start_date = end_date - timedelta(days=7)

            for stock_code in stock_codes[:100]:  # 限制最多返回 100 只
                stock_info = self.stock_repo.get_stock_info(stock_code)
                if not stock_info:
                    continue

                if mode == "published":
                    context = published_context[stock_code]
                    roe = safe_float(context.get("roe"), default=None)
                    revenue_growth = safe_float(context.get("revenue_growth"), default=None)
                    profit_growth = safe_float(context.get("profit_growth"), default=None)
                    pe = safe_float(context.get("pe"), default=None)
                    pb = safe_float(context.get("pb"), default=None)
                else:
                    # 获取最新估值和财务数据
                    valuations = self.stock_repo.get_valuation_history(
                        stock_code,
                        start_date,
                        end_date,
                    )
                    latest_valuation = valuations[-1] if valuations else None

                    financial = self.stock_repo.get_latest_financial_data(
                        stock_code,
                        published_only=False,
                    )
                    roe = safe_float(financial.roe) if financial else None
                    revenue_growth = safe_float(financial.revenue_growth) if financial else None
                    profit_growth = safe_float(financial.net_profit_growth) if financial else None
                    pe = safe_float(latest_valuation.pe) if latest_valuation else None
                    pb = safe_float(latest_valuation.pb) if latest_valuation else None
                pe = pe if pe is not None and pe > 0 else None
                pb = pb if pb is not None and pb > 0 else None

                stock_data: dict[str, object] = {
                    "code": stock_info.stock_code,
                    "name": stock_info.name,
                    "sector": stock_info.sector,
                    "roe": roe,
                    "pe": pe,
                    "pb": pb,
                    "revenue_growth": revenue_growth,
                    "profit_growth": profit_growth,
                    "score": None,
                }
                stocks.append(stock_data)

                if roe is not None:
                    total_roe += roe
                    valid_roe_count += 1
                if pe is not None:
                    total_pe += pe
                    valid_pe_count += 1

            avg_roe = total_roe / valid_roe_count if valid_roe_count > 0 else None
            avg_pe = total_pe / valid_pe_count if valid_pe_count > 0 else None

            payload: dict[str, object] = {
                "success": True,
                "regime": displayed_regime,
                "count": len(stocks),
                "update_time": (pool_info or {}).get("updated_at"),
                "avg_roe": round(avg_roe, 2) if avg_roe is not None else None,
                "avg_pe": round(avg_pe, 2) if avg_pe is not None else None,
                "stocks": stocks,
                "sector_distribution": _build_sector_distribution(stocks),
            }
            if mode == "published":
                payload.update(
                    {
                        "mode": mode,
                        "publication_key": publication_key,
                        "publication_gates": publication_gates,
                        "must_not_use_for_decision": False,
                    }
                )
            return Response(payload)

        except Exception:
            logger.exception("Failed to load equity stock pool")
            return Response(
                {"success": False, "message": "获取股票池失败", "stocks": []},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


__all__ = ["EquityPoolActionsMixin"]
