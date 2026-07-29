"""Portfolio aggregate repository owner."""

import logging
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.utils import timezone

from apps.account.domain.entities import (
    AssetClassType,
    CrossBorderFlag,
    PortfolioSnapshot,
    Position,
    PositionSource,
    PositionStatus,
    Region,
)
from apps.account.infrastructure.models import (
    CapitalFlowModel,
    PortfolioDailySnapshotModel,
    PortfolioModel,
    PositionModel,
    TransactionModel,
)

logger = logging.getLogger(__name__)


class PortfolioRepository:
    """投资组合仓储"""

    def user_owns_portfolio(self, portfolio_id: int, user_id: int) -> bool:
        """检查投资组合归属。"""
        return PortfolioModel._default_manager.filter(id=portfolio_id, user_id=user_id).exists()

    def list_active_portfolios(self, user_id: int | None = None) -> list[dict[str, Any]]:
        """列出激活中的投资组合摘要。"""
        queryset = PortfolioModel._default_manager.filter(is_active=True)
        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)
        portfolios = queryset.select_related("user").order_by("-created_at")
        return [
            {
                "id": portfolio.id,
                "user_id": portfolio.user_id,
                "name": portfolio.name,
                "user_email": portfolio.user.email,
            }
            for portfolio in portfolios
        ]

    def get_portfolio_notification_context(self, portfolio_id: int) -> dict[str, Any] | None:
        """获取投资组合通知所需的最小上下文。"""
        try:
            portfolio = PortfolioModel._default_manager.select_related("user").get(id=portfolio_id)
        except PortfolioModel.DoesNotExist:
            return None

        return {
            "id": portfolio.id,
            "user_id": portfolio.user_id,
            "name": portfolio.name,
            "user_email": portfolio.user.email,
        }

    def get_user_portfolios(self, user_id: int) -> list[dict[str, Any]]:
        """获取用户的所有投资组合"""
        portfolios = PortfolioModel._default_manager.filter(user_id=user_id).order_by("-created_at")
        return [
            {
                "id": p.id,
                "name": p.name,
                "is_active": p.is_active,
                "created_at": p.created_at,
            }
            for p in portfolios
        ]

    def get_portfolio_snapshot(self, portfolio_id: int) -> PortfolioSnapshot | None:
        """获取组合快照（包含持仓详情）"""
        from datetime import timedelta

        try:
            portfolio = PortfolioModel._default_manager.get(id=portfolio_id)
        except PortfolioModel.DoesNotExist:
            return None

        # 获取活跃持仓
        position_models = (
            PositionModel._default_manager.filter(portfolio=portfolio, is_closed=False)
            .select_related("portfolio")
            .order_by("-opened_at")
        )

        positions = self._convert_to_position_entities(position_models)

        # 计算当前总览数据
        cash_balance = self._calculate_cash_balance(portfolio, positions)
        invested_value = sum(float(p.market_value) for p in positions)
        total_value = cash_balance + invested_value

        # 回溯收益率计算
        # 1. 年收益率（对比1年前）
        one_year_ago = timezone.now() - timedelta(days=365)
        yearly_snapshot = (
            PortfolioDailySnapshotModel._default_manager.filter(
                portfolio=portfolio, snapshot_date__lte=one_year_ago.date()
            )
            .order_by("-snapshot_date")
            .first()
        )

        # 2. 月收益率（对比1个月前）
        one_month_ago = timezone.now() - timedelta(days=30)
        monthly_snapshot = (
            PortfolioDailySnapshotModel._default_manager.filter(
                portfolio=portfolio, snapshot_date__lte=one_month_ago.date()
            )
            .order_by("-snapshot_date")
            .first()
        )

        # 计算收益率
        if yearly_snapshot:
            yearly_return = total_value - float(yearly_snapshot.total_value)
            yearly_return_pct = yearly_return / float(yearly_snapshot.total_value) * 100
        else:
            # 没有历史快照，使用累计入金作为基准
            from apps.account.infrastructure.models import CapitalFlowModel

            total_deposit = CapitalFlowModel._default_manager.filter(
                portfolio=portfolio, flow_type="deposit"
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            total_withdraw = CapitalFlowModel._default_manager.filter(
                portfolio=portfolio, flow_type="withdraw"
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            net_capital = float(total_deposit - total_withdraw)

            # 如果没有任何入金记录，收益为0
            if net_capital == 0:
                yearly_return = 0.0
                yearly_return_pct = 0.0
            else:
                yearly_return = total_value - net_capital
                yearly_return_pct = yearly_return / net_capital * 100

        if monthly_snapshot:
            monthly_baseline = float(monthly_snapshot.total_value)
            monthly_return = total_value - monthly_baseline
            if monthly_baseline == 0:
                pass
            else:
                monthly_return / monthly_baseline * 100
        else:
            pass

        # 总收益使用年收益率
        total_return = yearly_return
        total_return_pct = yearly_return_pct

        # 保存今日快照
        today = timezone.now().date()
        PortfolioDailySnapshotModel._default_manager.update_or_create(
            portfolio=portfolio,
            snapshot_date=today,
            defaults={
                "total_value": Decimal(str(total_value)),
                "cash_balance": Decimal(str(cash_balance)),
                "invested_value": Decimal(str(invested_value)),
                "position_count": len(positions),
            },
        )

        return PortfolioSnapshot(
            portfolio_id=portfolio.id,
            user_id=portfolio.user_id,
            name=portfolio.name,
            snapshot_date=timezone.now(),
            cash_balance=Decimal(str(cash_balance)),
            total_value=Decimal(str(total_value)),
            invested_value=Decimal(str(invested_value)),
            total_return=Decimal(str(total_return)),
            total_return_pct=round(total_return_pct, 2),
            positions=positions,
        )

    def _convert_to_position_entities(
        self,
        models: Iterable[PositionModel],
    ) -> list[Position]:
        """将ORM模型转换为Domain实体"""
        entities: list[Position] = []
        for model in models:
            entities.append(
                Position(
                    id=model.id,
                    portfolio_id=model.portfolio_id,
                    user_id=model.portfolio.user_id,
                    asset_code=model.asset_code,
                    asset_class=AssetClassType(model.asset_class),
                    region=Region(model.region),
                    cross_border=CrossBorderFlag(model.cross_border),
                    shares=model.shares,
                    avg_cost=model.avg_cost,
                    current_price=model.current_price or model.avg_cost,
                    market_value=model.market_value,
                    unrealized_pnl=model.unrealized_pnl,
                    unrealized_pnl_pct=model.unrealized_pnl_pct,
                    opened_at=model.opened_at,
                    status=PositionStatus.ACTIVE if not model.is_closed else PositionStatus.CLOSED,
                    source=PositionSource(model.source),
                    source_id=model.source_id,
                )
            )
        return entities

    def _calculate_cash_balance(
        self, portfolio: PortfolioModel, positions: list[Position]
    ) -> float:
        """
        计算现金余额

        逻辑：
        - 入金增加现金，出金减少现金
        - 买入交易减少现金，卖出交易增加现金
        - 当前现金 = 入金 - 出金 - 买入支出 + 卖出收入
        - 总资产 = 当前现金 + 持仓市值
        """
        from django.db.models import Sum

        # 1. 资金流动（入金 - 出金）
        total_deposit = CapitalFlowModel._default_manager.filter(
            portfolio=portfolio, flow_type="deposit"
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        total_withdraw = CapitalFlowModel._default_manager.filter(
            portfolio=portfolio, flow_type="withdraw"
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        # 2. 交易对现金的影响
        buy_total = TransactionModel._default_manager.filter(
            portfolio=portfolio, action="buy"
        ).aggregate(total=Sum("notional"))["total"] or Decimal("0")

        sell_total = TransactionModel._default_manager.filter(
            portfolio=portfolio, action="sell"
        ).aggregate(total=Sum("notional"))["total"] or Decimal("0")

        # 3. 当前现金 = 入金 - 出金 - 买入支出 + 卖出收入
        cash_balance = float(total_deposit - total_withdraw - buy_total + sell_total)

        return max(0, cash_balance)
