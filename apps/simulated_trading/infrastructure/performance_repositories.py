"""
统一账户业绩域 Infrastructure 层 - 仓储实现

实现 application/performance_use_cases.py 中定义的所有 Protocol 接口。
严格遵守四层架构：Infrastructure 层可使用 Django ORM 和外部库。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.data_center.domain.entities import PriceBar
from apps.simulated_trading.application.daily_net_value_metrics import (
    project_daily_net_value_metrics,
)
from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionCashPosting,
    FeeCorrectionHistoryRepositoryProtocol,
)
from apps.simulated_trading.application.ports import DailyNetValueRecord
from apps.simulated_trading.domain.entities import OrderStatus, TradeAction
from apps.simulated_trading.infrastructure.daily_net_value_correction_overlay import (
    DailyCorrectionOverlay,
    overlay_daily_correction_cash,
)
from apps.simulated_trading.infrastructure.fee_correction_runtime import (
    build_django_fee_correction_repository,
)
from apps.simulated_trading.infrastructure.trade_repository import DjangoTradeRepository
from core.exceptions import DataFetchError
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
            "cash_known": obj.cash_known,
            "cash_reconciliation_status": obj.cash_reconciliation_status,
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
        return bool(grant.is_valid())


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

    def mirror_from_capital_flow(self, account_id: int, capital_flow_dict: dict[str, Any]) -> None:
        from apps.simulated_trading.infrastructure.models import UnifiedAccountCashFlowModel

        source_id = str(capital_flow_dict.get("id", ""))
        flow_type_map = {
            "deposit": "deposit",
            "withdraw": "withdrawal",
            "dividend": "dividend",
            "interest": "interest",
            "adjustment": "adjustment",
        }
        flow_type = flow_type_map.get(capital_flow_dict.get("flow_type", ""), "adjustment")
        flow_date = capital_flow_dict.get("flow_date")
        if not isinstance(flow_date, date):
            raise ValueError("capital flow requires a valid flow_date")
        UnifiedAccountCashFlowModel.objects.update_or_create(
            account_id=account_id,
            source_app="account",
            source_id=source_id,
            defaults={
                "flow_type": flow_type,
                "amount": float(capital_flow_dict.get("amount", 0)),
                "flow_date": flow_date,
                "notes": capital_flow_dict.get("notes", ""),
            },
        )


class DjangoPerformanceDailyNetValueRepository:
    """
    DailyNetValueRepositoryProtocol 实现（业绩用例专用）。

    注意：DailyNetValueModel.net_value 字段存储的是账户总资产（元），
    即 cash + market_value，而非单位净值比例。
    """

    def __init__(
        self,
        *,
        correction_history: FeeCorrectionHistoryRepositoryProtocol | None = None,
    ) -> None:
        """Inject the full-history correction validator for daily-value reads."""

        self._correction_history = correction_history or build_django_fee_correction_repository()

    def list_range(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        from apps.simulated_trading.infrastructure.models import DailyNetValueModel

        qs = DailyNetValueModel.objects.using(DEFAULT_DB_ALIAS).filter(account_id=account_id)
        if end_date:
            qs = qs.filter(record_date__lte=end_date)
        objects = list(qs.order_by("record_date"))
        if not objects:
            return []
        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

        initial_capital = (
            SimulatedAccountModel.objects.using(DEFAULT_DB_ALIAS)
            .filter(pk=account_id)
            .values_list("initial_capital", flat=True)
            .first()
        )
        history_through_date = end_date or objects[-1].record_date
        events = self._correction_events_through(account_id, history_through_date)
        fee_correction_after_last_snapshot = any(
            event.posting_date > objects[-1].record_date for event in events
        )
        rows: list[dict[str, Any]] = []
        metric_inputs: list[DailyNetValueRecord] = []
        overlays: list[DailyCorrectionOverlay] = []
        for obj in objects:
            overlay = overlay_daily_correction_cash(
                account_id=account_id,
                record_date=obj.record_date,
                cash=obj.cash,
                total_value=obj.net_value,
                correction_event_watermark=obj.correction_event_watermark,
                correction_event_watermark_sha256=obj.correction_event_watermark_sha256,
                events=events,
            )
            overlays.append(overlay)
            metric_inputs.append(
                DailyNetValueRecord(
                    record_date=obj.record_date,
                    net_value=overlay.total_value,
                    cash=overlay.cash,
                    market_value=obj.market_value,
                    daily_return=float(obj.daily_return),
                    cumulative_return=float(obj.cumulative_return),
                    drawdown=float(obj.drawdown),
                    total_trades=obj.total_trades,
                    positions_count=obj.positions_count,
                    correction_event_watermark=obj.correction_event_watermark,
                    correction_event_watermark_sha256=obj.correction_event_watermark_sha256,
                    correction_coverage_known=overlay.correction_coverage_known,
                    original_daily_return=float(obj.daily_return),
                    original_cumulative_return=float(obj.cumulative_return),
                    original_drawdown=float(obj.drawdown),
                    correction_overlay_applied=(
                        overlay.cash != obj.cash or overlay.total_value != obj.net_value
                    ),
                )
            )
        metric_projections = project_daily_net_value_metrics(
            metric_inputs,
            initial_capital=initial_capital,
        )
        for obj, overlay, metrics, metric_input in zip(
            objects,
            overlays,
            metric_projections,
            metric_inputs,
            strict=True,
        ):
            rows.append(
                {
                    "record_date": obj.record_date,
                    "cash": float(overlay.cash),
                    "market_value": float(obj.market_value),
                    # net_value字段即账户总资产（help_text: "账户总资产（元）"）
                    "total_value": float(overlay.total_value),
                    "net_value": float(overlay.total_value),
                    "original_net_value": float(obj.net_value),
                    "original_cash": float(obj.cash),
                    "daily_return": metrics.daily_return,
                    "cumulative_return": metrics.cumulative_return,
                    "drawdown": metrics.drawdown,
                    "original_daily_return": metrics.original_daily_return,
                    "original_cumulative_return": metrics.original_cumulative_return,
                    "original_drawdown": metrics.original_drawdown,
                    "effective_metrics_known": metrics.metrics_known,
                    "effective_metrics_reason_code": metrics.reason_code,
                    "correction_event_watermark": obj.correction_event_watermark,
                    "correction_event_watermark_sha256": obj.correction_event_watermark_sha256,
                    "correction_coverage_known": overlay.correction_coverage_known,
                    "correction_overlay_applied": metric_input["correction_overlay_applied"],
                    "fee_correction_after_last_daily_snapshot": (
                        fee_correction_after_last_snapshot
                    ),
                }
            )
        if start_date:
            rows = [row for row in rows if row["record_date"] >= start_date]
        return rows

    def get_record_for_date(self, account_id: int, record_date: date) -> dict[str, Any] | None:
        """返回某日净值记录（用于历史时点现金获取）。无则返回 None。"""
        from apps.simulated_trading.infrastructure.models import DailyNetValueModel

        try:
            obj = DailyNetValueModel.objects.using(DEFAULT_DB_ALIAS).get(
                account_id=account_id,
                record_date=record_date,
            )
        except DailyNetValueModel.DoesNotExist:
            return None
        events = self._correction_events_through(account_id, record_date)
        overlay = overlay_daily_correction_cash(
            account_id=account_id,
            record_date=obj.record_date,
            cash=obj.cash,
            total_value=obj.net_value,
            correction_event_watermark=obj.correction_event_watermark,
            correction_event_watermark_sha256=obj.correction_event_watermark_sha256,
            events=events,
        )
        return {
            "record_date": obj.record_date,
            "cash": float(overlay.cash),
            "market_value": float(obj.market_value),
            "total_value": float(overlay.total_value),
            "original_net_value": float(obj.net_value),
            "original_cash": float(obj.cash),
            "correction_event_watermark": obj.correction_event_watermark,
            "correction_event_watermark_sha256": obj.correction_event_watermark_sha256,
            "correction_coverage_known": overlay.correction_coverage_known,
        }

    def _correction_events_through(
        self,
        account_id: int,
        end_date: date,
    ) -> tuple[FeeCorrectionCashPosting, ...]:
        """Read proof-validated correction events through one local end-of-day."""

        as_of = timezone.make_aware(datetime.combine(end_date, time.max))
        projection = self._correction_history.get_account_history(
            account_id=account_id,
            as_of=as_of,
        )
        return projection.cash_events


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

    def __init__(self, trade_repository: DjangoTradeRepository | None = None) -> None:
        """Use the correction-aware account history reader for realized PnL."""

        self._trades = trade_repository or DjangoTradeRepository()

    def list_closed_trades(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        as_of = (
            timezone.make_aware(datetime.combine(end_date, time.max))
            if end_date is not None
            else timezone.now()
        )
        history = self._trades.get_account_history(
            account_id=account_id,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
        )
        return [
            {
                "realized_pnl": trade.realized_pnl,
                "original_realized_pnl": trade.realized_pnl,
                "effective_realized_pnl": trade.current_realized_pnl,
                "realized_pnl_pct": trade.realized_pnl_pct,
                "original_realized_pnl_pct": trade.realized_pnl_pct,
                "effective_realized_pnl_pct": trade.current_realized_pnl_pct,
                "effective_commission": trade.current_commission,
                "effective_transfer_fee": trade.current_transfer_fee,
                "effective_stamp_duty": trade.current_stamp_duty,
                "effective_total_cost": trade.current_total_cost,
                "fee_correction_revision": trade.fee_correction_revision,
                "fee_correction_overlay_applied": trade.fee_correction_overlay_applied,
                "effective_realized_pnl_known": (
                    trade.cost_basis_known is True
                    and trade.fee_amounts_known is True
                    and trade.current_realized_pnl is not None
                ),
                "cost_basis_known": trade.cost_basis_known,
                "fee_amounts_known": trade.fee_amounts_known,
            }
            for trade in history.trades
            if trade.action is TradeAction.SELL and trade.status is OrderStatus.EXECUTED
        ]


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
            price: float | None = svc.get_price(
                asset_code=asset_code,
                trade_date=trade_date,
            )
            return price
        except DataFetchError:
            logger.warning("获取收盘价失败: %s @ %s", asset_code, trade_date, exc_info=True)
            return None

    def _fetch_index_bars(
        self, index_code: str, start_date: date, end_date: date
    ) -> list[PriceBar]:
        """优先通过 data_center 拉取指数历史价格柱（按日期升序）。"""
        from apps.data_center.application.public import get_price_bar_repository_port

        repo = get_price_bar_repository_port()
        bars = repo.get_bars(index_code, start=start_date, end=end_date, limit=5000)
        return sorted(bars, key=lambda bar: bar.bar_date)

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
                result.append((bars[i].bar_date, r))
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

    def list_for_account_via_ledger(self, account_id: int) -> list[dict[str, Any]]:
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

        CapitalFlowModel = get_capital_flow_model()
        qs = CapitalFlowModel.objects.filter(portfolio_id__in=portfolio_ids).order_by("flow_date")
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
