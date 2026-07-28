"""Stock-pool actions for the equity API viewset.

Owns `EquityPoolActionsMixin`. The compatibility facade in `views.py` composes
the final `EquityViewSet` and keeps the legacy monkeypatch surface; do not
import it here.
"""

from datetime import date
from typing import Any

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.equity.application.use_cases import (
    ScreenStocksRequest,
    ScreenStocksUseCase,
)


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


class EquityPoolActionsMixin:
    """Current-pool query and Regime-driven pool refresh actions."""

    pool_adapter: Any
    regime_repo: Any
    stock_repo: Any

    @action(detail=False, methods=["get"], url_path="pool")
    def get_pool(self, request: Request) -> Response:
        """
        GET /api/equity/pool/

        获取当前股票池
        """
        from apps.regime.application.current_regime import resolve_current_regime

        try:
            # 获取当前股票池
            stock_codes = self.pool_adapter.get_current_pool()

            # 获取股票池元数据
            pool_info = self.pool_adapter.get_latest_pool_info()

            # 获取当前 Regime
            latest_regime = resolve_current_regime()

            if not stock_codes:
                # 如果没有股票池，返回空结果
                return Response(
                    {
                        "success": True,
                        "regime": latest_regime.dominant_regime if latest_regime else "Unknown",
                        "count": 0,
                        "update_time": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "stocks": [],
                        "sector_distribution": [],
                    }
                )

            # 获取股票详细信息
            stocks: list[dict[str, object]] = []
            total_roe = 0
            total_pe = 0
            valid_pe_count = 0

            for stock_code in stock_codes[:100]:  # 限制最多返回 100 只
                stock_info = self.stock_repo.get_stock_info(stock_code)
                if not stock_info:
                    continue

                # 获取最新估值和财务数据
                from datetime import timedelta

                end_date = date.today()
                start_date = end_date - timedelta(days=7)

                valuations = self.stock_repo.get_valuation_history(stock_code, start_date, end_date)
                latest_valuation = valuations[-1] if valuations else None

                financial = self.stock_repo.get_latest_financial_data(stock_code)

                stock_data = {
                    "code": stock_info.stock_code,
                    "name": stock_info.name,
                    "sector": stock_info.sector,
                    "roe": financial.roe if financial else 0,
                    "pe": (
                        latest_valuation.pe if latest_valuation and latest_valuation.pe > 0 else 0
                    ),
                    "pb": (
                        latest_valuation.pb if latest_valuation and latest_valuation.pb > 0 else 0
                    ),
                    "revenue_growth": financial.revenue_growth if financial else 0,
                    "profit_growth": financial.net_profit_growth if financial else 0,
                    "score": 0,  # 暂时为 0，后续可添加评分逻辑
                }
                stocks.append(stock_data)

                if financial:
                    total_roe += financial.roe
                if latest_valuation and latest_valuation.pe > 0:
                    total_pe += latest_valuation.pe
                    valid_pe_count += 1

            avg_roe = total_roe / len(stocks) if stocks else 0
            avg_pe = total_pe / valid_pe_count if valid_pe_count > 0 else 0

            return Response(
                {
                    "success": True,
                    "regime": (
                        pool_info.get("regime")
                        if pool_info
                        else (latest_regime.dominant_regime if latest_regime else "Unknown")
                    ),
                    "count": len(stocks),
                    "update_time": (
                        pool_info.get("updated_at")
                        if pool_info
                        else timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                    ),
                    "avg_roe": round(avg_roe, 2),
                    "avg_pe": round(avg_pe, 2),
                    "stocks": stocks,
                    "sector_distribution": _build_sector_distribution(stocks),
                }
            )

        except Exception as e:
            return Response(
                {"success": False, "message": f"获取股票池失败: {str(e)}", "stocks": []},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"], url_path="pool/refresh")
    def refresh_pool(self, request: Request) -> Response:
        """
        POST /api/equity/pool/refresh/

        刷新股票池

        基于当前 Regime 重新筛选股票池。
        """
        from apps.regime.application.current_regime import resolve_current_regime

        try:
            # 获取当前 Regime
            latest_regime = resolve_current_regime()
            if not latest_regime:
                return Response(
                    {"success": False, "message": "无法获取当前 Regime，请先运行 Regime 判定"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            # 构造筛选请求
            screen_request = ScreenStocksRequest(
                regime=latest_regime.dominant_regime,
                max_count=50,  # 默认筛选 50 只股票
            )

            # 执行筛选
            screen_use_case = ScreenStocksUseCase(
                stock_repository=self.stock_repo, regime_repository=self.regime_repo
            )
            screen_response = screen_use_case.execute(screen_request)

            if not screen_response.success:
                return Response(
                    {"success": False, "message": f"筛选失败: {screen_response.error}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            # 保存新的股票池
            self.pool_adapter.save_pool(
                stock_codes=screen_response.stock_codes,
                regime=latest_regime.dominant_regime,
                as_of_date=date.today(),
            )

            return Response(
                {
                    "success": True,
                    "message": "股票池已刷新",
                    "regime": latest_regime.dominant_regime,
                    "count": len(screen_response.stock_codes),
                    "update_time": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        except Exception as e:
            return Response(
                {"success": False, "message": f"刷新股票池失败: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


__all__ = ["EquityPoolActionsMixin"]
