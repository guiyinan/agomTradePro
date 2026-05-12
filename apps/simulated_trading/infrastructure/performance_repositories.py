"""
统一账户业绩域 Infrastructure 层 - 仓储实现

实现 application/performance_use_cases.py 中定义的所有 Protocol 接口。
严格遵守四层架构：Infrastructure 层可使用 Django ORM 和外部库。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from core.integration.account_ledger import (
    get_capital_flow_model,
    get_portfolio_observer_grant_model,
)

logger = logging.getLogger(__name__)


class DjangoPerformanceAccountRepository:
    """AccountRepositoryProtocol 实现。"""

    def get_by_id(self, account_id: int) -> dict[str, Any] | None:
        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

        try:
            obj = SimulatedAccountModel.objects.get(pk=account_id)
        except SimulatedAccountModel.DoesNotExist:
            return None
        return {
            "account_id": obj.pk,
            "account_name": obj.account_name,
            "account_type": obj.account_type,
            "initial_capital": float(obj.initial_capital),
            "current_cash": float(obj.current_cash),
            "total_value": float(obj.total_value),
            "start_date": obj.start_date,
            "user_id": obj.user_id,
        }


class DjangoObserverGrantRepository:
    """ObserverGrantRepositoryProtocol 实现。"""

    def has_valid_grant(self, owner_user_id: int, observer_user_id: int) -> bool:
        PortfolioObserverGrantModel = get_portfolio_observer_grant_model()

        try:
            grant = PortfolioObserverGrantModel._default_manager.get(
                owner_user_id=owner_user_id,
                observer_user_id=observer_user_id,
                status="active",
            )
        except PortfolioObserverGrantModel.DoesNotExist:
            return False
        return grant.is_valid()


class DjangoBenchmarkComponentRepository:
    """BenchmarkComponentRepositoryProtocol 实现。"""

    def list_active(self, account_id: int) -> list[dict[str, Any]]:
        from apps.simulated_trading.infrastructure.models import AccountBenchmarkComponentModel

        qs = AccountBenchmarkComponentModel.objects.filter(
            account_id=account_id, is_active=True
        ).order_by("sort_order")
        return [
            {
                "benchmark_code": obj.benchmark_code,
                "weight": obj.weight,
                "display_name": obj.display_name,
                "sort_order": obj.sort_order,
                "is_active": obj.is_active,
            }
            for obj in qs
        ]

    def upsert_components(self, account_id: int, components: list[dict[str, Any]]) -> None:
        from apps.simulated_trading.infrastructure.models import AccountBenchmarkComponentModel

        AccountBenchmarkComponentModel.objects.filter(account_id=account_id).delete()
        AccountBenchmarkComponentModel.objects.bulk_create(
            [
                AccountBenchmarkComponentModel(
                    account_id=account_id,
                    benchmark_code=c["benchmark_code"],
                    weight=float(c["weight"]),
                    display_name=c.get("display_name", ""),
                    sort_order=int(c.get("sort_order", i)),
                    is_active=True,
                )
                for i, c in enumerate(components)
            ]
        )


class DjangoUnifiedCashFlowRepository:
    """UnifiedCashFlowRepositoryProtocol 实现。"""

    def list_for_account(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        from apps.simulated_trading.infrastructure.models import UnifiedAccountCashFlowModel

        qs = UnifiedAccountCashFlowModel.objects.filter(account_id=account_id)
        if start_date:
            qs = qs.filter(flow_date__gte=start_date)
        if end_date:
            qs = qs.filter(flow_date__lte=end_date)
        qs = qs.order_by("flow_date")
        return [
            {
                "flow_id": obj.pk,
                "account_id": obj.account_id,
                "flow_type": obj.flow_type,
                "amount": float(obj.amount),
                "flow_date": obj.flow_date,
                "source_app": obj.source_app,
                "source_id": obj.source_id,
                "notes": obj.notes,
            }
            for obj in qs
        ]

    def create_initial_capital(self, account_id: int, amount: float, flow_date: date) -> None:
        from apps.simulated_trading.infrastructure.models import UnifiedAccountCashFlowModel

        UnifiedAccountCashFlowModel.objects.get_or_create(
            account_id=account_id,
            flow_type="initial_capital",
            defaults={
                "amount": amount,
                "flow_date": flow_date,
                "source_app": "simulated_trading",
                "source_id": "",
                "notes": "初始入金（自动回填）",
            },
        )

    def mirror_from_capital_flow(
        self, account_id: int, capital_flow_dict: dict[str, Any]
    ) -> None:
        from apps.simulated_trading.infrastructure.models import UnifiedAccountCashFlowModel

        source_id = str(capital_flow_dict.get("id", ""))
        flow_type_map = {
            "deposit": "deposit",
            "withdraw": "withdrawal",
            "dividend": "dividend",
            "interest": "interest",
            "adjustment": "adjustment",
        }
        flow_type = flow_type_map.get(
            capital_flow_dict.get("flow_type", ""), "adjustment"
        )
        UnifiedAccountCashFlowModel.objects.update_or_create(
            account_id=account_id,
            source_app="account",
            source_id=source_id,
            defaults={
                "flow_type": flow_type,
                "amount": float(capital_flow_dict.get("amount", 0)),
                "flow_date": capital_flow_dict.get("flow_date"),
                "notes": capital_flow_dict.get("notes", ""),
            },
        )


class DjangoPerformanceDailyNetValueRepository:
    """
    DailyNetValueRepositoryProtocol 实现（业绩用例专用）。

    注意：DailyNetValueModel.net_value 字段存储的是账户总资产（元），
    即 cash + market_value，而非单位净值比例。
    """

    def list_range(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        from apps.simulated_trading.infrastructure.models import DailyNetValueModel

        qs = DailyNetValueModel.objects.filter(account_id=account_id)
        if start_date:
            qs = qs.filter(record_date__gte=start_date)
        if end_date:
            qs = qs.filter(record_date__lte=end_date)
        qs = qs.order_by("record_date")
        return [
            {
                "record_date": obj.record_date,
                "cash": float(obj.cash),
                "market_value": float(obj.market_value),
                # net_value 字段即账户总资产（help_text: "账户总资产（元）"）
                "total_value": float(obj.net_value),
                "net_value": float(obj.net_value),
                "daily_return": float(obj.daily_return),
                "cumulative_return": float(obj.cumulative_return),
                "drawdown": float(obj.drawdown),
            }
            for obj in qs
        ]

    def get_record_for_date(
        self, account_id: int, record_date: date
    ) -> dict[str, Any] | None:
        """返回某日净值记录（用于历史时点现金获取）。无则返回 None。"""
        from apps.simulated_trading.infrastructure.models import DailyNetValueModel

        try:
            obj = DailyNetValueModel.objects.get(
                account_id=account_id, record_date=record_date
            )
        except DailyNetValueModel.DoesNotExist:
            return None
        return {
            "record_date": obj.record_date,
            "cash": float(obj.cash),
            "market_value": float(obj.market_value),
            "total_value": float(obj.net_value),
        }


class DjangoValuationSnapshotRepository:
    """ValuationSnapshotRepositoryProtocol 实现。"""

    def get_for_date(self, account_id: int, record_date: date) -> list[dict[str, Any]]:
        from apps.simulated_trading.infrastructure.models import (
            AccountPositionValuationSnapshotModel,
        )

        qs = AccountPositionValuationSnapshotModel.objects.filter(
            account_id=account_id, record_date=record_date
        ).order_by("-market_value")
        return [
            {
                "asset_code": obj.asset_code,
                "asset_name": obj.asset_name,
                "asset_type": obj.asset_type,
                "quantity": float(obj.quantity),
                "avg_cost": float(obj.avg_cost),
                "close_price": float(obj.close_price),
                "market_value": float(obj.market_value),
                "weight": obj.weight,
                "unrealized_pnl": float(obj.unrealized_pnl),
                "unrealized_pnl_pct": obj.unrealized_pnl_pct,
            }
            for obj in qs
        ]

    def upsert_snapshot(
        self,
        account_id: int,
        record_date: date,
        rows: list[dict[str, Any]],
    ) -> None:
        from apps.simulated_trading.infrastructure.models import (
            AccountPositionValuationSnapshotModel,
        )

        AccountPositionValuationSnapshotModel.objects.filter(
            account_id=account_id, record_date=record_date
        ).delete()
        AccountPositionValuationSnapshotModel.objects.bulk_create(
            [
                AccountPositionValuationSnapshotModel(
                    account_id=account_id,
                    record_date=record_date,
                    asset_code=r["asset_code"],
                    asset_name=r.get("asset_name", ""),
                    asset_type=r.get("asset_type", "equity"),
                    quantity=r["quantity"],
                    avg_cost=r.get("avg_cost", 0),
                    close_price=r.get("close_price", 0),
                    market_value=r["market_value"],
                    weight=r.get("weight", 0),
                    unrealized_pnl=r.get("unrealized_pnl", 0),
                    unrealized_pnl_pct=r.get("unrealized_pnl_pct", 0),
                )
                for r in rows
            ]
        )


class DjangoTradeHistoryRepository:
    """TradeHistoryRepositoryProtocol 实现。"""

    def list_closed_trades(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        from apps.simulated_trading.infrastructure.models import SimulatedTradeModel

        qs = SimulatedTradeModel.objects.filter(
            account_id=account_id,
            action="sell",
            status="executed",
            realized_pnl__isnull=False,
        )
        if start_date:
            qs = qs.filter(execution_date__gte=start_date)
        if end_date:
            qs = qs.filter(execution_date__lte=end_date)
        return [{"realized_pnl": float(obj.realized_pnl)} for obj in qs]


class DjangoMarketDataRepository:
    """
    MarketDataRepositoryProtocol 实现。

    通过 data_center 统一价格入口拉取指数历史价格柱，
    计算日收益率和区间累计收益。
    单个收盘价委托给 UnifiedPriceService。
    """

    def get_close_price(self, asset_code: str, trade_date: date) -> float | None:
        try:
            from apps.data_center.application.price_service import UnifiedPriceService

            svc = UnifiedPriceService()
            return svc.get_price(asset_code=asset_code, trade_date=trade_date)
        except Exception:
            logger.warning(
                "获取收盘价失败: %s @ %s", asset_code, trade_date, exc_info=True
            )
            return None

    def _fetch_index_bars(
        self, index_code: str, start_date: date, end_date: date
    ) -> list:
        """优先通过 data_center 拉取指数历史价格柱（按日期升序）。"""
        try:
            from apps.data_center.infrastructure.repositories import PriceBarRepository

            repo = PriceBarRepository()
            bars = repo.get_bars(index_code, start=start_date, end=end_date, limit=5000)
            return sorted(bars, key=lambda b: b.bar_date)
        except Exception:
            logger.warning(
                "获取指数行情失败: %s %s~%s", index_code, start_date, end_date, exc_info=True
            )
            return []

    def get_index_daily_returns(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, float]]:
        bars = self._fetch_index_bars(index_code, start_date, end_date)
        if len(bars) < 2:
            return []
        result: list[tuple[date, float]] = []
        for i in range(1, len(bars)):
            prev_close = float(bars[i - 1].close)
            curr_close = float(bars[i].close)
            if prev_close > 0:
                r = (curr_close - prev_close) / prev_close
                result.append((getattr(bars[i], "trade_date", bars[i].bar_date), r))
        return result

    def get_index_cumulative_return(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> float | None:
        bars = self._fetch_index_bars(index_code, start_date, end_date)
        if len(bars) < 2:
            return None
        start_close = float(bars[0].close)
        end_close = float(bars[-1].close)
        if start_close <= 0:
            return None
        return (end_close - start_close) / start_close * 100.0


class DjangoCapitalFlowRepository:
    """
    账本现金流仓储（真实账户 backfill 专用）。

    通过 LedgerMigrationMapModel 找到统一账户对应的 PortfolioModel，
    再从 CapitalFlowModel 读取现金流记录。
    """

    def list_for_account_via_ledger(
        self, account_id: int
    ) -> list[dict[str, Any]]:
        """
        查找该统一账户对应的全部 CapitalFlowModel 记录。

        Returns:
            list of dicts with keys: id, flow_type, amount, flow_date, notes
        """
        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

        portfolio_ids = list(
            LedgerMigrationMapModel.objects.filter(
                target_table="simulated_account",
                target_id=account_id,
                source_table="portfolio",
            ).values_list("source_id", flat=True)
        )
        if not portfolio_ids:
            return []

        try:
            CapitalFlowModel = get_capital_flow_model()

            qs = CapitalFlowModel.objects.filter(
                portfolio_id__in=portfolio_ids
            ).order_by("flow_date")
            return [
                {
                    "id": obj.pk,
                    "flow_type": obj.flow_type,
                    "amount": float(obj.amount),
                    "flow_date": obj.flow_date,
                    "notes": obj.notes or "",
                }
                for obj in qs
            ]
        except Exception:
            logger.warning(
                "读取 CapitalFlowModel 失败 (account_id=%d)", account_id, exc_info=True
            )
            return []
