"""
Account Infrastructure Repositories

数据仓储实现，负责数据持久化和查询。
遵循依赖反转原则：Domain层定义接口，Infrastructure层实现。
"""

import json
import logging
import warnings
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from apps.account.infrastructure.backup_service import (
    generate_backup_archive,
    validate_download_token,
)
from apps.account.domain.entities import (
    AccountProfile,
    AssetClassType,
    CrossBorderFlag,
    InvestmentStyle,
    MacroSizingConfig,
    PortfolioSnapshot,
    Position,
    PositionSource,
    PositionStatus,
    PulseTier,
    DrawdownTier,
    RegimeTier,
    Region,
    RiskTolerance,
    Transaction,
)
from apps.account.infrastructure.models import (
    AccountProfileModel,
    AssetCategoryModel,
    AssetMetadataModel,
    CapitalFlowModel,
    CurrencyModel,
    ExchangeRateModel,
    MacroSizingConfigModel,
    PortfolioDailySnapshotModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
    PositionSignalLogModel,
    StopLossConfigModel,
    SystemSettingsModel,
    StopLossTriggerModel,
    TakeProfitConfigModel,
    TradingCostConfigModel,
    TransactionModel,
    UserAccessTokenModel,
)
from apps.signal.infrastructure.models import InvestmentSignalModel


class AccountRepository:
    """用户账户仓储"""

    def list_investment_accounts(self, user_id: int) -> list[dict[str, Any]]:
        """返回用户投资组合账户摘要，供 Interface 层只读展示。"""
        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

        accounts = (
            SimulatedAccountModel._default_manager.filter(user_id=user_id)
            .only("id", "account_name", "account_type", "total_value", "total_return")
            .order_by("account_type", "-created_at")
        )
        return [
            {
                "id": account.id,
                "account_name": account.account_name,
                "account_type": account.account_type,
                "total_value": float(account.total_value or 0),
                "total_return": float(account.total_return or 0),
            }
            for account in accounts
        ]

    def get_by_user_id(self, user_id: int) -> AccountProfile | None:
        """根据用户ID获取账户配置"""
        try:
            model = AccountProfileModel._default_manager.get(user_id=user_id)
            return AccountProfile(
                user_id=model.user_id,
                display_name=model.display_name,
                initial_capital=model.initial_capital,
                risk_tolerance=RiskTolerance(model.risk_tolerance),
                created_at=model.created_at,
            )
        except AccountProfileModel.DoesNotExist:
            return None

    def create_default_profile(self, user_id: int) -> AccountProfile:
        """为用户创建默认账户配置（接受user_id）"""
        try:
            user = User._default_manager.get(id=user_id)
        except User.DoesNotExist:
            raise ValueError(f"用户 {user_id} 不存在")

        return self.create_default_account(user)

    def get_or_create_default_portfolio(self, user_id: int) -> int:
        """获取或创建默认投资组合，返回portfolio_id"""
        portfolio, created = PortfolioModel._default_manager.get_or_create(
            user_id=user_id, name="默认组合", defaults={"is_active": True}
        )
        return portfolio.id

    def create_default_account(self, user: User) -> AccountProfile:
        """为新用户创建默认账户配置"""
        profile = AccountProfileModel._default_manager.create(
            user=user,
            display_name=user.username,
            initial_capital=Decimal("1000000.00"),
            risk_tolerance="moderate",
        )
        PortfolioModel._default_manager.create(
            user=user,
            name="默认组合",
            is_active=True,
        )
        return AccountProfile(
            user_id=profile.user_id,
            display_name=profile.display_name,
            initial_capital=profile.initial_capital,
            risk_tolerance=RiskTolerance(profile.risk_tolerance),
            created_at=profile.created_at,
        )

    def get_volatility_settings(self, user_id: int) -> dict[str, Any] | None:
        """获取用户波动率控制配置。"""
        try:
            model = AccountProfileModel._default_manager.get(user_id=user_id)
        except AccountProfileModel.DoesNotExist:
            return None

        return {
            "user_id": model.user_id,
            "target_volatility": model.target_volatility,
            "volatility_tolerance": model.volatility_tolerance,
            "max_volatility_reduction": model.max_volatility_reduction,
        }

    def update_volatility_settings(
        self,
        user_id: int,
        *,
        target_volatility: float | None = None,
        volatility_tolerance: float | None = None,
        max_volatility_reduction: float | None = None,
    ) -> dict[str, Any] | None:
        """更新用户波动率控制配置。"""
        try:
            model = AccountProfileModel._default_manager.get(user_id=user_id)
        except AccountProfileModel.DoesNotExist:
            return None

        if target_volatility is not None:
            model.target_volatility = target_volatility
        if volatility_tolerance is not None:
            model.volatility_tolerance = volatility_tolerance
        if max_volatility_reduction is not None:
            model.max_volatility_reduction = max_volatility_reduction
        model.save(
            update_fields=[
                "target_volatility",
                "volatility_tolerance",
                "max_volatility_reduction",
                "updated_at",
            ]
        )
        return self.get_volatility_settings(user_id)


class AccountClassificationRepository:
    """Classification and FX persistence helpers for interface/application layers."""

    def list_active_asset_categories(self):
        """Return active asset categories with related parent/children loaded."""

        return (
            AssetCategoryModel._default_manager.filter(is_active=True)
            .select_related("parent")
            .prefetch_related("children")
            .order_by("path", "sort_order")
        )

    def list_root_asset_categories(self):
        """Return active root-level asset categories."""

        return self.list_active_asset_categories().filter(level=1)

    def list_tree_root_asset_categories(self):
        """Return active root categories without parents."""

        return self.list_active_asset_categories().filter(level=1, parent__isnull=True)

    def list_child_asset_categories(self, category_id: int):
        """Return active child categories for one parent."""

        return (
            AssetCategoryModel._default_manager.filter(parent_id=category_id, is_active=True)
            .select_related("parent")
            .order_by("sort_order")
        )

    def create_asset_category(self, **validated_data):
        """Create one asset category."""

        return AssetCategoryModel._default_manager.create(**validated_data)

    def update_asset_category(self, *, category_id: int, **validated_data):
        """Update one asset category and return the refreshed model."""

        model = AssetCategoryModel._default_manager.get(id=category_id)
        for field, value in validated_data.items():
            setattr(model, field, value)
        model.save()
        return model

    def delete_asset_category(self, *, category_id: int) -> None:
        """Delete one asset category."""

        AssetCategoryModel._default_manager.filter(id=category_id).delete()

    def list_active_currencies(self):
        """Return active currencies."""

        return CurrencyModel._default_manager.filter(is_active=True).order_by("-is_base", "code")

    def get_base_currency(self):
        """Return the configured base currency."""

        return self.list_active_currencies().filter(is_base=True).first() or self.list_active_currencies().filter(
            code="CNY"
        ).first()

    def list_exchange_rates(self):
        """Return exchange rates with currency relations loaded."""

        return (
            ExchangeRateModel._default_manager.select_related("from_currency", "to_currency")
            .all()
            .order_by("-effective_date")
        )

    def create_exchange_rate(self, **validated_data):
        """Create one exchange rate."""

        return ExchangeRateModel._default_manager.create(**validated_data)

    def update_exchange_rate(self, *, exchange_rate_id: int, **validated_data):
        """Update one exchange rate and return the refreshed model."""

        model = ExchangeRateModel._default_manager.get(id=exchange_rate_id)
        for field, value in validated_data.items():
            setattr(model, field, value)
        model.save()
        return model

    def delete_exchange_rate(self, *, exchange_rate_id: int) -> None:
        """Delete one exchange rate."""

        ExchangeRateModel._default_manager.filter(id=exchange_rate_id).delete()

    def get_latest_exchange_rate(self, *, from_code: str, to_code: str):
        """Return the latest exchange rate for one currency pair."""

        return self.list_exchange_rates().filter(
            from_currency__code=from_code,
            to_currency__code=to_code,
        ).first()

    def get_exchange_rate_for_conversion(self, *, from_code: str, to_code: str, date_value=None):
        """Return the effective exchange rate used for conversion."""

        queryset = self.list_exchange_rates().filter(
            from_currency__code=from_code,
            to_currency__code=to_code,
        )
        if date_value:
            queryset = queryset.filter(effective_date__lte=date_value)
        return queryset.first()

    def convert_amount(self, *, amount: Decimal, from_code: str, to_code: str, date_value=None) -> Decimal:
        """Convert one amount between currencies."""

        if from_code == to_code:
            return amount

        rate_model = self.get_exchange_rate_for_conversion(
            from_code=from_code,
            to_code=to_code,
            date_value=date_value,
        )
        if rate_model is None:
            raise ValueError(f"No exchange rate found for {from_code} -> {to_code}")
        return rate_model.convert(amount)

    def get_portfolio_for_user(self, *, portfolio_id: int, user_id: int):
        """Return one portfolio owned by the given user."""

        return (
            PortfolioModel._default_manager.select_related("base_currency")
            .filter(id=portfolio_id, user_id=user_id)
            .first()
        )

    def list_portfolio_allocation_rows(self, *, portfolio_id: int) -> list[dict[str, Any]]:
        """Return position rows required for category/currency allocation summaries."""

        positions = (
            PositionModel._default_manager.filter(portfolio_id=portfolio_id, is_closed=False)
            .select_related("category", "currency")
            .order_by("id")
        )
        return [
            {
                "category_path": position.category.get_full_path() if position.category else "未分类",
                "currency_code": position.currency.code if position.currency else "CNY",
                "currency_name": position.currency.name if position.currency else "CNY",
                "amount": position.market_value,
            }
            for position in positions
        ]


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

    def get_user_portfolios(self, user_id: int) -> list[dict]:
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

        from apps.account.infrastructure.models import PortfolioDailySnapshotModel

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
                monthly_return_pct = 0.0
            else:
                monthly_return_pct = monthly_return / monthly_baseline * 100
        else:
            monthly_return_pct = 0.0

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

    def _convert_to_position_entities(self, models: list[PositionModel]) -> list[Position]:
        """将ORM模型转换为Domain实体"""
        entities = []
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

        from apps.account.infrastructure.models import CapitalFlowModel, TransactionModel

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


class PositionRepository:
    """持仓仓储"""

    def get_user_positions(
        self,
        user_id: int,
        status: str | None = None,
        asset_class: str | None = None,
    ) -> list[Position]:
        """获取用户持仓列表"""
        queryset = (
            PositionModel._default_manager.filter(portfolio__user_id=user_id)
            .select_related("portfolio")
            .order_by("-opened_at")
        )

        if status == "active":
            queryset = queryset.filter(is_closed=False)
        elif status == "closed":
            queryset = queryset.filter(is_closed=True)

        if asset_class:
            queryset = queryset.filter(asset_class=asset_class)

        return PortfolioRepository()._convert_to_position_entities(queryset)

    def get_position_by_id(self, position_id: int) -> Position | None:
        """根据ID获取持仓"""
        try:
            model = PositionModel._default_manager.get(id=position_id)
            return PortfolioRepository()._convert_to_position_entities([model])[0]
        except PositionModel.DoesNotExist:
            return None

    def get_user_position_by_asset_code(self, *, user_id: int, asset_code: str) -> Position | None:
        """Return one active user position by asset code."""

        model = (
            PositionModel._default_manager.filter(
                portfolio__user_id=user_id,
                asset_code=asset_code,
                is_closed=False,
            )
            .order_by("-opened_at")
            .first()
        )
        if model is None:
            return None
        return PortfolioRepository()._convert_to_position_entities([model])[0]

    def list_open_positions_for_adjustment(self, portfolio_id: int) -> list[dict[str, Any]]:
        """获取用于风控调仓的活跃持仓。"""
        models = PositionModel._default_manager.filter(
            portfolio_id=portfolio_id,
            is_closed=False,
        ).only("id", "asset_code", "shares", "current_price", "avg_cost")
        return [
            {
                "id": model.id,
                "asset_code": model.asset_code,
                "shares": model.shares,
                "current_price": model.current_price,
                "avg_cost": model.avg_cost,
            }
            for model in models
        ]

    def list_portfolio_position_weights(self, portfolio_id: int) -> list[dict[str, Any]]:
        """获取组合中各持仓的权重。"""
        positions = list(
            PositionModel._default_manager.filter(
                portfolio_id=portfolio_id,
                market_value__gt=0,
            ).values("asset_code", "market_value")
        )
        if not positions:
            return []

        total_value = sum(float(position["market_value"]) for position in positions)
        if total_value <= 0:
            return []

        return [
            {
                "asset_code": position["asset_code"],
                "weight": float(position["market_value"]) / total_value,
            }
            for position in positions
        ]

    def get_position_notification_context(self, position_id: int) -> dict[str, Any] | None:
        """获取持仓通知所需的最小上下文。"""
        try:
            model = PositionModel._default_manager.select_related("portfolio__user").get(
                id=position_id
            )
        except PositionModel.DoesNotExist:
            return None

        return {
            "id": model.id,
            "asset_code": model.asset_code,
            "user_id": model.portfolio.user_id,
            "user_email": model.portfolio.user.email,
            "portfolio_id": model.portfolio_id,
            "portfolio_name": model.portfolio.name,
        }

    def get_position_stop_management_context(self, position_id: int) -> dict[str, Any] | None:
        """Return stop-loss/take-profit management context for one position."""

        try:
            model = PositionModel._default_manager.select_related("portfolio__user").get(
                id=position_id
            )
        except PositionModel.DoesNotExist:
            return None

        return {
            "id": model.id,
            "asset_code": model.asset_code,
            "shares": model.shares,
            "avg_cost": model.avg_cost,
            "current_price": model.current_price,
            "opened_at": model.opened_at,
            "portfolio_id": model.portfolio_id,
            "user_id": model.portfolio.user_id,
            "user_email": model.portfolio.user.email,
        }

    def create_position_legacy(
        self,
        portfolio_id: int,
        asset_code: str,
        shares: float,
        price: Decimal,
        source: str = "manual",
        source_id: int | None = None,
    ) -> Position:
        """Create a position in the legacy `apps/account` ledger tables."""
        # 获取资产元数据
        try:
            asset_meta = AssetMetadataModel._default_manager.get(asset_code=asset_code)
        except AssetMetadataModel.DoesNotExist:
            # 如果元数据不存在，使用默认值
            asset_meta = None

        model = PositionModel._default_manager.create(
            portfolio_id=portfolio_id,
            asset_code=asset_code,
            asset_class=asset_meta.asset_class if asset_meta else "equity",
            region=asset_meta.region if asset_meta else "CN",
            cross_border=asset_meta.cross_border if asset_meta else "domestic",
            shares=shares,
            avg_cost=price,
            current_price=price,
            market_value=Decimal(str(shares * float(price))),
            source=source,
            source_id=source_id,
        )

        # 创建交易记录
        TransactionModel._default_manager.create(
            portfolio_id=portfolio_id,
            position_id=model.id,
            action="buy",
            asset_code=asset_code,
            shares=shares,
            price=price,
            notional=Decimal(str(shares * float(price))),
            traded_at=timezone.now(),
            notes=f"开仓 ({source})",
        )

        # 更新持仓状态为活跃
        model.is_closed = False
        model.save()

        return PortfolioRepository()._convert_to_position_entities([model])[0]

    def create_position(
        self,
        portfolio_id: int,
        asset_code: str,
        shares: float,
        price: Decimal,
        source: str = "manual",
        source_id: int | None = None,
    ) -> Position:
        """创建新持仓

        .. deprecated::
            此方法写入旧账本表（apps/account）。
            新代码请使用 UnifiedPositionService（apps/simulated_trading）。
            旧路径将于 2026-09-27 停用。
        """
        warnings.warn(
            "PositionRepository.create_position() is deprecated and will be removed on 2026-09-27. "
            "Use apps.simulated_trading.application.unified_position_service.UnifiedPositionService instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.create_position_legacy(
            portfolio_id=portfolio_id,
            asset_code=asset_code,
            shares=shares,
            price=price,
            source=source,
            source_id=source_id,
        )

    def close_position(self, position_id: int, shares: float | None = None) -> Position | None:
        """平仓（全部或部分）"""
        try:
            model = PositionModel._default_manager.get(id=position_id)
        except PositionModel.DoesNotExist:
            return None

        if shares is None:
            shares = model.shares  # 默认全部平仓

        # 创建交易记录
        TransactionModel._default_manager.create(
            portfolio_id=model.portfolio_id,
            position_id=model.id,
            action="sell",
            asset_code=model.asset_code,
            shares=shares,
            price=model.current_price or model.avg_cost,
            notional=Decimal(str(shares * float(model.current_price or model.avg_cost))),
            traded_at=timezone.now(),
            notes="平仓",
        )

        # 更新持仓
        if shares >= model.shares:
            model.is_closed = True
            model.closed_at = timezone.now()
        else:
            model.shares -= shares

        # Recalculate derived fields
        from shared.domain.position_calculations import recalculate_derived_fields
        price = float(model.current_price or model.avg_cost)
        mv, pnl, pnl_pct = recalculate_derived_fields(
            shares=model.shares if not model.is_closed else 0,
            avg_cost=float(model.avg_cost),
            current_price=price,
        )
        model.market_value = mv
        model.unrealized_pnl = pnl
        model.unrealized_pnl_pct = pnl_pct

        model.save()

        return PortfolioRepository()._convert_to_position_entities([model])[0]

    def update_position_price(self, position_id: int, new_price: Decimal) -> Position | None:
        """更新持仓当前价格并重算盈亏"""
        try:
            model = PositionModel._default_manager.get(id=position_id)
        except PositionModel.DoesNotExist:
            return None

        model.current_price = new_price
        model.market_value = Decimal(str(model.shares * float(new_price)))

        # 计算盈亏
        pnl = (new_price - model.avg_cost) * model.shares
        model.unrealized_pnl = pnl
        model.unrealized_pnl_pct = float((new_price / model.avg_cost - 1) * 100)

        model.save()
        return PortfolioRepository()._convert_to_position_entities([model])[0]

    def create_position_from_signal(
        self,
        user_id: int,
        signal_id: int,
        price: Decimal,
    ) -> Position | None:
        """从投资信号创建持仓"""
        try:
            signal = InvestmentSignalModel._default_manager.get(id=signal_id, user_id=user_id)
        except InvestmentSignalModel.DoesNotExist:
            return None

        # 获取用户默认组合
        account_repo = AccountRepository()
        portfolio_id = account_repo.get_or_create_default_portfolio(user_id)

        # 计算仓位（使用默认策略）
        profile = account_repo.get_by_user_id(user_id)
        max_notional = float(profile.initial_capital) * 0.1  # 默认10%
        shares = int(max_notional / float(price))

        # 创建持仓
        position = self.create_position_legacy(
            portfolio_id=portfolio_id,
            asset_code=signal.asset_code,
            shares=shares,
            price=price,
            source="signal",
            source_id=signal_id,
        )

        # 记录信号关联
        PositionSignalLogModel._default_manager.create(
            signal_id=signal_id,
            position_id=position.id,
            notes=f"从信号 {signal_id} 创建",
        )

        return position

    def update_or_create_position(
        self,
        portfolio_id: int,
        asset_code: str,
        shares: float,
        avg_cost: Decimal,
        current_price: Decimal,
        source: str = "signal",
    ) -> Position:
        """
        更新或创建持仓（P2-11: 添加此方法以支持架构合规）

        Args:
            portfolio_id: 投资组合 ID
            asset_code: 资产代码
            shares: 持仓数量
            avg_cost: 平均成本
            current_price: 当前价格
            source: 来源

        Returns:
            Position 实体
        """
        # 获取资产元数据
        try:
            asset_meta = AssetMetadataModel._default_manager.get(asset_code=asset_code)
        except AssetMetadataModel.DoesNotExist:
            asset_meta = None

        # 创建或更新持仓
        model, created = PositionModel._default_manager.update_or_create(
            portfolio_id=portfolio_id,
            asset_code=asset_code,
            defaults={
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "market_value": Decimal(str(shares * float(current_price))),
                "asset_class": asset_meta.asset_class if asset_meta else "equity",
                "region": asset_meta.region if asset_meta else "CN",
                "cross_border": asset_meta.cross_border if asset_meta else "domestic",
                "source": source,
                "is_closed": False,
            },
        )

        return PortfolioRepository()._convert_to_position_entities([model])[0]


class TransactionRepository:
    """交易记录仓储"""

    def get_portfolio_transactions(
        self,
        portfolio_id: int,
        limit: int = 50,
    ) -> list[Transaction]:
        """获取组合交易记录"""
        models = (
            TransactionModel._default_manager.filter(portfolio_id=portfolio_id)
            .select_related("position")
            .order_by("-traded_at")[:limit]
        )

        transactions = []
        for model in models:
            transactions.append(
                Transaction(
                    id=model.id,
                    portfolio_id=model.portfolio_id,
                    user_id=model.portfolio.user_id,
                    position_id=model.position_id,
                    asset_code=model.asset_code,
                    action=model.action,
                    shares=model.shares,
                    price=model.price,
                    notional=model.notional,
                    commission=model.commission,
                    traded_at=model.traded_at,
                    notes=model.notes,
                )
            )
        return transactions

    def get_transaction_cost_record(self, transaction_id: int) -> dict[str, Any] | None:
        """获取交易成本分析所需的交易明细。"""
        try:
            model = TransactionModel._default_manager.get(id=transaction_id)
        except TransactionModel.DoesNotExist:
            return None

        return self._to_transaction_cost_dict(model)

    def update_transaction_costs(
        self,
        transaction_id: int,
        *,
        commission: Decimal,
        slippage: Decimal | None = None,
        stamp_duty: Decimal | None = None,
        transfer_fee: Decimal | None = None,
    ) -> dict[str, Any] | None:
        """更新交易的实际成本并返回最新明细。"""
        try:
            model = TransactionModel._default_manager.get(id=transaction_id)
        except TransactionModel.DoesNotExist:
            return None

        model.commission = commission
        if slippage is not None:
            model.slippage = slippage
        if stamp_duty is not None:
            model.stamp_duty = stamp_duty
        if transfer_fee is not None:
            model.transfer_fee = transfer_fee

        total_actual = (
            commission
            + (slippage or Decimal("0"))
            + (stamp_duty or Decimal("0"))
            + (transfer_fee or Decimal("0"))
        )
        if model.estimated_cost:
            variance = total_actual - model.estimated_cost
            variance_pct = (
                float(variance) / float(model.estimated_cost) if model.estimated_cost > 0 else 0
            )
            model.cost_variance = variance
            model.cost_variance_pct = variance_pct

        model.save()
        return self._to_transaction_cost_dict(model)

    def list_user_transaction_costs(
        self,
        user_id: int,
        *,
        portfolio_id: int | None = None,
        since_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """列出用户指定时间范围内的交易成本明细。"""
        queryset = TransactionModel._default_manager.filter(portfolio__user_id=user_id)
        if portfolio_id is not None:
            queryset = queryset.filter(portfolio_id=portfolio_id)
        if since_date is not None:
            queryset = queryset.filter(created_at__gte=since_date)
        return [
            self._to_transaction_cost_dict(model)
            for model in queryset.order_by("-created_at").all()
        ]

    @staticmethod
    def _to_transaction_cost_dict(model: TransactionModel) -> dict[str, Any]:
        """转换为交易成本分析用的字典。"""
        return {
            "id": model.id,
            "portfolio_id": model.portfolio_id,
            "position_id": model.position_id,
            "asset_code": model.asset_code,
            "action": model.action,
            "notional": model.notional,
            "commission": model.commission,
            "slippage": model.slippage,
            "stamp_duty": model.stamp_duty,
            "transfer_fee": model.transfer_fee,
            "estimated_cost": model.estimated_cost,
            "cost_variance": model.cost_variance,
            "cost_variance_pct": model.cost_variance_pct,
            "traded_at": model.traded_at,
        }


class AssetMetadataRepository:
    """资产元数据仓储"""

    def get_or_create_asset(
        self, asset_code: str, name: str, asset_class: str = "equity", region: str = "CN", **kwargs
    ) -> dict:
        """获取或创建资产元数据"""
        asset, created = AssetMetadataModel._default_manager.get_or_create(
            asset_code=asset_code,
            defaults={"name": name, "asset_class": asset_class, "region": region, **kwargs},
        )
        return {
            "id": asset.id,
            "asset_code": asset.asset_code,
            "name": asset.name,
            "asset_class": asset.asset_class,
            "region": asset.region,
            "created": created,
        }

    def search_assets(
        self,
        query: str,
        asset_class: str | None = None,
        region: str | None = None,
    ) -> list[dict]:
        """搜索资产"""
        queryset = AssetMetadataModel._default_manager.all()

        if query:
            queryset = queryset.filter(Q(asset_code__icontains=query) | Q(name__icontains=query))

        if asset_class:
            queryset = queryset.filter(asset_class=asset_class)

        if region:
            queryset = queryset.filter(region=region)

        return [
            {
                "asset_code": a.asset_code,
                "name": a.name,
                "asset_class": a.asset_class,
                "region": a.region,
            }
            for a in queryset[:20]
        ]

    def update_position_prices(self, user_id: int) -> int:
        """
        批量更新用户持仓的当前价格

        从行情接口获取最新价格并更新持仓记录。
        如果行情接口不可用，则使用当前价格（成本价作为后备）。

        Args:
            user_id: 用户ID

        Returns:
            int: 更新的持仓数量
        """
        from .market_price_service import get_market_price_service

        # 获取用户所有活跃持仓
        positions = PositionModel._default_manager.filter(
            portfolio__user_id=user_id, is_closed=False
        )

        updated_count = 0
        price_service = get_market_price_service()

        for position in positions:
            try:
                # 从行情接口获取价格
                price_metadata = price_service.get_price_with_metadata(position.asset_code)
                if price_metadata and price_metadata["price"] is not None:
                    new_price = price_metadata["price"]
                    # 更新持仓价格
                    position.current_price = new_price
                    position.market_value = Decimal(str(position.shares * float(new_price)))
                    # 计算盈亏
                    pnl = (new_price - position.avg_cost) * position.shares
                    position.unrealized_pnl = pnl
                    position.unrealized_pnl_pct = float((new_price / position.avg_cost - 1) * 100)
                    position.save(
                        update_fields=[
                            "current_price",
                            "market_value",
                            "unrealized_pnl",
                            "unrealized_pnl_pct",
                        ]
                    )
                    updated_count += 1
                else:
                    # 行情接口不可用时，保持当前价格不变
                    logger.warning(
                        f"无法获取持仓 {position.id} ({position.asset_code}) 的价格，"
                        f"使用现有价格 {position.current_price}"
                    )
            except Exception as e:
                logger.error(f"更新持仓 {position.id} ({position.asset_code}) 价格失败: {e}")
                # 继续处理其他持仓

        return updated_count

    def get_asset_by_code(self, asset_code: str) -> dict[str, Any] | None:
        """
        Get asset metadata by code.

        Returns:
            Dict with asset_class, region, etc., or None
        """
        try:
            asset = AssetMetadataModel._default_manager.get(asset_code=asset_code)
            return {
                "asset_code": asset.asset_code,
                "name": asset.name,
                "asset_class": asset.asset_class,
                "region": asset.region,
                "cross_border": asset.cross_border,
                "style": asset.style,
            }
        except AssetMetadataModel.DoesNotExist:
            return None


# ============================================================
# Stop Loss Repository
# ============================================================


class StopLossRepository:
    """止损配置仓储"""

    def get_active_stop_loss_configs(self, user_id: int | None = None) -> list[dict[str, Any]]:
        """
        Get all active stop loss configurations.

        Args:
            user_id: Optional user ID to filter by

        Returns:
            List of stop loss config dicts with position relationship
        """
        queryset = StopLossConfigModel._default_manager.filter(status="active")

        if user_id:
            queryset = queryset.filter(position__portfolio__user_id=user_id)

        configs = queryset.select_related("position", "position__portfolio").all()

        return [
            {
                "id": config.id,
                "position_id": config.position_id,
                "stop_loss_type": config.stop_loss_type,
                "stop_loss_pct": config.stop_loss_pct,
                "trailing_stop_pct": config.trailing_stop_pct,
                "max_holding_days": config.max_holding_days,
                "highest_price": config.highest_price,
                "highest_price_updated_at": config.highest_price_updated_at,
                "status": config.status,
                "position": {
                    "id": config.position.id,
                    "asset_code": config.position.asset_code,
                    "shares": config.position.shares,
                    "avg_cost": config.position.avg_cost,
                    "current_price": config.position.current_price,
                    "opened_at": config.position.opened_at,
                    "portfolio_id": config.position.portfolio_id,
                    "user_id": config.position.portfolio.user_id,
                    "user_email": config.position.portfolio.user.email,
                },
            }
            for config in configs
        ]

    def get_stop_loss_config_by_position(self, position_id: int) -> dict[str, Any] | None:
        """Get stop loss config for a position."""
        try:
            config = StopLossConfigModel._default_manager.get(position_id=position_id)
            return {
                "id": config.id,
                "position_id": config.position_id,
                "stop_loss_type": config.stop_loss_type,
                "stop_loss_pct": config.stop_loss_pct,
                "trailing_stop_pct": config.trailing_stop_pct,
                "max_holding_days": config.max_holding_days,
                "highest_price": config.highest_price,
                "status": config.status,
            }
        except StopLossConfigModel.DoesNotExist:
            return None

    def create_stop_loss_config(
        self,
        position_id: int,
        stop_loss_type: str,
        stop_loss_pct: float,
        trailing_stop_pct: float | None = None,
        max_holding_days: int | None = None,
        highest_price: Decimal | None = None,
    ) -> dict[str, Any]:
        """Create stop loss configuration."""
        config = StopLossConfigModel._default_manager.create(
            position_id=position_id,
            stop_loss_type=stop_loss_type,
            stop_loss_pct=stop_loss_pct,
            trailing_stop_pct=trailing_stop_pct,
            max_holding_days=max_holding_days,
            highest_price=highest_price,
            status="active",
        )
        return {
            "id": config.id,
            "position_id": config.position_id,
            "stop_loss_type": config.stop_loss_type,
            "stop_loss_pct": config.stop_loss_pct,
            "status": config.status,
        }

    def update_stop_loss_config(
        self,
        config_id: int,
        status: str | None = None,
        highest_price: Decimal | None = None,
        highest_price_updated_at: Any | None = None,
        triggered_at: Any | None = None,
    ) -> bool:
        """Update stop loss configuration."""
        try:
            config = StopLossConfigModel._default_manager.get(id=config_id)
            if status is not None:
                config.status = status
            if highest_price is not None:
                config.highest_price = highest_price
            if highest_price_updated_at is not None:
                config.highest_price_updated_at = highest_price_updated_at
            if triggered_at is not None:
                config.triggered_at = triggered_at
            config.save()
            return True
        except StopLossConfigModel.DoesNotExist:
            return False

    def create_stop_loss_trigger(
        self,
        position_id: int,
        trigger_type: str,
        trigger_price: Decimal,
        trigger_reason: str,
        pnl: Decimal,
        pnl_pct: float,
        notes: str = "",
    ) -> dict[str, Any]:
        """Create stop loss trigger record."""
        trigger = StopLossTriggerModel._default_manager.create(
            position_id=position_id,
            trigger_type=trigger_type,
            trigger_price=trigger_price,
            trigger_time=timezone.now(),
            trigger_reason=trigger_reason,
            pnl=pnl,
            pnl_pct=pnl_pct,
            notes=notes,
        )
        return {
            "id": trigger.id,
            "position_id": trigger.position_id,
            "trigger_type": trigger.trigger_type,
            "trigger_price": trigger.trigger_price,
            "trigger_time": trigger.trigger_time,
        }


# ============================================================
# Take Profit Repository
# ============================================================


class TakeProfitRepository:
    """止盈配置仓储"""

    def get_active_take_profit_configs(self, user_id: int | None = None) -> list[dict[str, Any]]:
        """
        Get all active take profit configurations.

        Args:
            user_id: Optional user ID to filter by

        Returns:
            List of take profit config dicts with position relationship
        """
        queryset = TakeProfitConfigModel._default_manager.filter(is_active=True)

        if user_id:
            queryset = queryset.filter(position__portfolio__user_id=user_id)

        configs = queryset.select_related("position", "position__portfolio").all()

        return [
            {
                "id": config.id,
                "position_id": config.position_id,
                "take_profit_pct": config.take_profit_pct,
                "partial_profit_levels": config.partial_profit_levels,
                "is_active": config.is_active,
                "position": {
                    "id": config.position.id,
                    "asset_code": config.position.asset_code,
                    "shares": config.position.shares,
                    "avg_cost": config.position.avg_cost,
                    "current_price": config.position.current_price,
                    "opened_at": config.position.opened_at,
                    "portfolio_id": config.position.portfolio_id,
                    "user_id": config.position.portfolio.user_id,
                    "user_email": config.position.portfolio.user.email,
                },
            }
            for config in configs
        ]

    def get_take_profit_config_by_position(self, position_id: int) -> dict[str, Any] | None:
        """Get take profit config for a position."""
        try:
            config = TakeProfitConfigModel._default_manager.get(position_id=position_id)
            return {
                "id": config.id,
                "position_id": config.position_id,
                "take_profit_pct": config.take_profit_pct,
                "partial_profit_levels": config.partial_profit_levels,
                "is_active": config.is_active,
            }
        except TakeProfitConfigModel.DoesNotExist:
            return None

    def create_take_profit_config(
        self,
        position_id: int,
        take_profit_pct: float,
        partial_profit_levels: list[float] | None = None,
    ) -> dict[str, Any]:
        """Create take profit configuration."""
        config = TakeProfitConfigModel._default_manager.create(
            position_id=position_id,
            take_profit_pct=take_profit_pct,
            partial_profit_levels=partial_profit_levels,
            is_active=True,
        )
        return {
            "id": config.id,
            "position_id": config.position_id,
            "take_profit_pct": config.take_profit_pct,
            "is_active": config.is_active,
        }

    def update_take_profit_config(
        self,
        config_id: int,
        is_active: bool | None = None,
    ) -> bool:
        """Update take profit configuration."""
        try:
            config = TakeProfitConfigModel._default_manager.get(id=config_id)
            if is_active is not None:
                config.is_active = is_active
            config.save()
            return True
        except TakeProfitConfigModel.DoesNotExist:
            return False


# ============================================================
# Portfolio Snapshot Repository
# ============================================================


class PortfolioSnapshotRepository:
    """投资组合快照仓储"""

    def get_snapshots_for_volatility(
        self,
        portfolio_id: int,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """
        Get portfolio daily snapshots for volatility calculation.

        Returns:
            List of dicts with snapshot_date, total_value
        """
        snapshots = PortfolioDailySnapshotModel._default_manager.filter(
            portfolio_id=portfolio_id
        ).order_by("-snapshot_date")[:days]

        return [
            {
                "snapshot_date": snap.snapshot_date,
                "total_value": float(snap.total_value),
            }
            for snap in reversed(list(snapshots))
        ]

    def list_performance_rows(self, portfolio_id: int) -> list[dict[str, Any]]:
        """Return ordered snapshot rows for dashboard performance charts."""

        snapshots = PortfolioDailySnapshotModel._default_manager.filter(
            portfolio_id=portfolio_id
        ).order_by("snapshot_date")
        return [
            {
                "snapshot_date": snapshot.snapshot_date,
                "total_value": float(snapshot.total_value or 0),
                "cash_balance": float(snapshot.cash_balance or 0),
                "invested_value": float(snapshot.invested_value or 0),
                "position_count": int(snapshot.position_count or 0),
            }
            for snapshot in snapshots
        ]


# ============================================================
# Transaction Cost Config Repository
# ============================================================


class TransactionCostConfigRepository:
    """交易成本配置仓储"""

    def get_cost_config(self, market: str, asset_class: str) -> dict[str, Any] | None:
        """
        Get transaction cost configuration for market and asset class.

        Returns:
            Dict with commission_rate, slippage_rate, etc., or None
        """
        from shared.infrastructure.models import TransactionCostConfigModel

        try:
            config = TransactionCostConfigModel._default_manager.get(
                market=market,
                asset_class=asset_class,
                is_active=True,
            )
            return {
                "id": config.id,
                "market": config.market,
                "asset_class": config.asset_class,
                "commission_rate": config.commission_rate,
                "slippage_rate": config.slippage_rate,
                "stamp_duty_rate": config.stamp_duty_rate,
                "transfer_fee_rate": config.transfer_fee_rate,
                "min_commission": config.min_commission,
                "cost_warning_threshold": config.cost_warning_threshold,
            }
        except TransactionCostConfigModel.DoesNotExist:
            return None

    def get_default_cost_config(self, market: str, asset_class: str) -> dict[str, Any]:
        """
        Get default cost configuration.

        Returns:
            Dict with default values
        """
        return {
            "market": market,
            "asset_class": asset_class,
            "commission_rate": Decimal("0.0003"),
            "slippage_rate": Decimal("0.0002"),
            "stamp_duty_rate": Decimal("0.001"),
            "transfer_fee_rate": Decimal("0.00001"),
            "min_commission": Decimal("5.00"),
            "cost_warning_threshold": 0.005,
        }


class SystemSettingsRepository:
    """系统设置仓储。"""

    def get_settings(self):
        """返回系统设置模型实例。"""
        from apps.account.infrastructure.models import SystemSettingsModel

        return SystemSettingsModel.get_settings()

    def get_runtime_asset_proxy_code(self, asset_class: str, default: str = "") -> str:
        """获取运行时资产代理代码。"""
        from apps.account.infrastructure.models import SystemSettingsModel

        return SystemSettingsModel.get_runtime_asset_proxy_code(asset_class, default)


class MacroSizingConfigRepository:
    """宏观仓位系数配置仓储。"""

    _DEFAULT_REGIME_TIERS = [
        {"min_confidence": 0.6, "factor": 1.0},
        {"min_confidence": 0.4, "factor": 0.8},
        {"min_confidence": 0.0, "factor": 0.5},
    ]
    _DEFAULT_PULSE_TIERS = [
        {"min_composite": 0.3, "max_composite": 99, "factor": 1.0},
        {"min_composite": -0.3, "max_composite": 0.3, "factor": 0.85},
        {"min_composite": -99, "max_composite": -0.3, "factor": 0.7},
    ]
    _DEFAULT_DRAWDOWN_TIERS = [
        {"min_drawdown": 0.15, "factor": 0.0},
        {"min_drawdown": 0.1, "factor": 0.5},
        {"min_drawdown": 0.05, "factor": 0.8},
        {"min_drawdown": 0.0, "factor": 1.0},
    ]

    def get_active_config(self) -> MacroSizingConfig:
        """返回当前生效配置；若库中不存在则返回默认配置。"""
        try:
            model = (
                MacroSizingConfigModel._default_manager.filter(is_active=True)
                .order_by("-version")
                .first()
            )
        except (OperationalError, ProgrammingError):
            logger.warning("MacroSizingConfigModel table unavailable; using default sizing config")
            model = None
        if model is None:
            return self._build_config(
                regime_tiers=self._DEFAULT_REGIME_TIERS,
                pulse_tiers=self._DEFAULT_PULSE_TIERS,
                warning_factor=0.5,
                drawdown_tiers=self._DEFAULT_DRAWDOWN_TIERS,
                version=1,
            )
        return self._to_entity(model)

    def _to_entity(self, model: MacroSizingConfigModel) -> MacroSizingConfig:
        return self._build_config(
            regime_tiers=model.regime_tiers_json,
            pulse_tiers=model.pulse_tiers_json,
            warning_factor=model.warning_factor,
            drawdown_tiers=model.drawdown_tiers_json,
            version=model.version,
        )

    def _build_config(
        self,
        *,
        regime_tiers: list[dict[str, Any]],
        pulse_tiers: list[dict[str, Any]],
        warning_factor: float,
        drawdown_tiers: list[dict[str, Any]],
        version: int,
    ) -> MacroSizingConfig:
        return MacroSizingConfig(
            regime_tiers=[
                RegimeTier(
                    min_confidence=float(item["min_confidence"]),
                    factor=float(item["factor"]),
                )
                for item in regime_tiers
            ],
            pulse_tiers=[
                PulseTier(
                    min_composite=float(item["min_composite"]),
                    max_composite=float(item.get("max_composite", item["min_composite"])),
                    factor=float(item["factor"]),
                )
                for item in pulse_tiers
            ],
            warning_factor=float(warning_factor),
            drawdown_tiers=[
                DrawdownTier(
                    min_drawdown=float(item["min_drawdown"]),
                    factor=float(item["factor"]),
                )
                for item in drawdown_tiers
            ],
            version=version,
        )


class AccountInterfaceRepository:
    """Interface-facing query and command helpers for the account module."""

    def get_system_settings(self):
        """Return the singleton system settings model."""

        return SystemSettingsModel.get_settings()

    def list_global_investment_rule_payloads(self) -> list[dict[str, Any]]:
        """Return active global investment rules for read-only consumers."""

        from apps.account.infrastructure.models import InvestmentRuleModel

        queryset = (
            InvestmentRuleModel._default_manager.filter(
                is_active=True,
                user__isnull=True,
            )
            .order_by("priority", "id")
            .values("rule_type", "conditions", "advice_template")
        )
        return [
            {
                "rule_type": str(row["rule_type"]),
                "conditions": dict(row.get("conditions") or {}),
                "advice_template": str(row.get("advice_template") or ""),
            }
            for row in queryset
        ]

    def has_system_settings_singleton(self) -> bool:
        """Return whether the singleton system settings row already exists."""

        return SystemSettingsModel._default_manager.exists()

    def get_existing_system_settings(self):
        """Return the existing singleton settings row without creating one."""

        return SystemSettingsModel._default_manager.first()

    def get_active_access_token(self, key: str):
        """Return one active access token with user/profile preloaded."""

        return (
            UserAccessTokenModel._default_manager.select_related(
                "user",
                "user__account_profile",
            )
            .filter(key=key, is_active=True)
            .first()
        )

    def touch_access_token(self, token) -> None:
        """Persist last-used metadata for one access token."""

        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at", "updated_at"])

    def provision_registered_user(
        self,
        *,
        user: User,
        display_name: str,
        system_settings,
        client_ip: str | None,
        approval_status: str,
        rbac_role: str,
    ) -> None:
        """Create account scaffolding for a newly registered user."""

        AccountProfileModel._default_manager.update_or_create(
            user=user,
            defaults={
                "display_name": display_name,
                "initial_capital": Decimal("1000000.00"),
                "risk_tolerance": "moderate",
                "mcp_enabled": system_settings.default_mcp_enabled,
                "user_agreement_accepted": True,
                "risk_warning_acknowledged": True,
                "agreement_accepted_at": timezone.now(),
                "agreement_ip_address": client_ip,
                "approval_status": approval_status,
                "rbac_role": rbac_role,
            },
        )
        PortfolioModel._default_manager.get_or_create(
            user=user,
            name="默认组合",
            defaults={"is_active": True},
        )

    def build_profile_context(self, user_id: int) -> dict[str, Any]:
        """Build the profile page context."""

        user = User._default_manager.select_related("account_profile").get(id=user_id)
        portfolios = PortfolioModel._default_manager.filter(user_id=user_id).order_by("-created_at")
        investment_accounts = AccountRepository().list_investment_accounts(user_id)

        total_assets = 0.0
        if investment_accounts:
            total_assets = sum(float(account["total_value"]) for account in investment_accounts)
        else:
            portfolio_repo = PortfolioRepository()
            for portfolio in portfolios.filter(is_active=True):
                snapshot = portfolio_repo.get_portfolio_snapshot(portfolio.id)
                if snapshot:
                    total_assets += float(snapshot.total_value)

        return {
            "user": user,
            "profile": user.account_profile,
            "portfolios": portfolios,
            "investment_accounts": investment_accounts,
            "total_assets": total_assets,
        }

    def build_settings_context(self, user_id: int) -> dict[str, Any]:
        """Build the settings page context."""

        user = User._default_manager.select_related("account_profile").get(id=user_id)
        profile = user.account_profile
        portfolio = PortfolioModel._default_manager.filter(user_id=user_id, is_active=True).first()
        system_settings = SystemSettingsModel.get_settings()

        if portfolio:
            capital_flows = CapitalFlowModel._default_manager.filter(portfolio=portfolio).order_by(
                "-flow_date", "-created_at"
            )
            total_deposit = capital_flows.filter(flow_type="deposit").aggregate(
                total=Sum("amount")
            )["total"] or Decimal("0")
            total_withdraw = capital_flows.filter(flow_type="withdraw").aggregate(
                total=Sum("amount")
            )["total"] or Decimal("0")
            net_capital = total_deposit - total_withdraw
            trading_cost_config = TradingCostConfigModel._default_manager.filter(
                portfolio=portfolio
            ).first()
        else:
            capital_flows = []
            total_deposit = Decimal("0")
            total_withdraw = Decimal("0")
            net_capital = Decimal("0")
            trading_cost_config = None

        access_tokens = UserAccessTokenModel._default_manager.filter(
            user_id=user_id,
            is_active=True,
        ).order_by("-created_at")

        return {
            "user": user,
            "profile": profile,
            "portfolio": portfolio,
            "capital_flows": capital_flows,
            "total_deposit": total_deposit,
            "total_withdraw": total_withdraw,
            "net_capital": net_capital,
            "trading_cost_config": trading_cost_config,
            "system_settings": system_settings,
            "access_tokens": access_tokens,
        }

    def update_account_settings(
        self,
        user_id: int,
        *,
        display_name: str,
        risk_tolerance: str,
        email: str,
        new_password: str,
    ) -> bool:
        """Persist profile and credential changes. Returns whether password changed."""

        user = User._default_manager.select_related("account_profile").get(id=user_id)
        profile = user.account_profile
        profile.display_name = display_name
        profile.risk_tolerance = risk_tolerance
        profile.save(update_fields=["display_name", "risk_tolerance", "updated_at"])

        user_update_fields: list[str] = []
        if email:
            user.email = email
            user_update_fields.append("email")
        if new_password:
            user.set_password(new_password)
            user_update_fields.append("password")
        if user_update_fields:
            user.save(update_fields=user_update_fields)
        return bool(new_password)

    def get_api_profile(self, user_id: int):
        """Return the account profile model for API serialization."""

        user = User._default_manager.select_related("account_profile").get(id=user_id)
        return user.account_profile

    def update_api_profile(
        self,
        user_id: int,
        *,
        profile_data: Mapping[str, Any],
        email: str | None = None,
    ):
        """Persist API profile updates and return the refreshed profile model."""

        user = User._default_manager.select_related("account_profile").get(id=user_id)
        profile = user.account_profile

        update_fields: list[str] = []
        for field_name in ("display_name", "risk_tolerance"):
            if field_name in profile_data:
                setattr(profile, field_name, profile_data[field_name])
                update_fields.append(field_name)

        if update_fields:
            update_fields.append("updated_at")
            profile.save(update_fields=update_fields)

        if email:
            user.email = email
            user.save(update_fields=["email"])

        return profile

    def get_asset_metadata_queryset(self):
        """Return the asset metadata queryset for API listing/retrieval."""

        return AssetMetadataModel._default_manager.all()

    def get_user_transaction_queryset(self, user_id: int):
        """Return transactions scoped to portfolios owned by the user."""

        return TransactionModel._default_manager.filter(
            portfolio__user_id=user_id
        ).select_related("portfolio", "position")

    def get_user_capital_flow_queryset(self, user_id: int):
        """Return capital flows scoped to portfolios owned by the user."""

        return CapitalFlowModel._default_manager.filter(
            portfolio__user_id=user_id
        ).select_related("portfolio")

    def get_user_portfolio(self, *, user_id: int, portfolio_id: int):
        """Return one owned portfolio when available."""

        return PortfolioModel._default_manager.filter(
            id=portfolio_id,
            user_id=user_id,
        ).first()

    def get_account_health_payload(self, user_id: int) -> dict[str, Any]:
        """Return the API health summary for one user."""

        return {
            "status": "healthy",
            "service": "account",
            "portfolio_count": PortfolioModel._default_manager.filter(user_id=user_id).count(),
            "position_count": PositionModel._default_manager.filter(
                portfolio__user_id=user_id,
                is_closed=False,
            ).count(),
        }

    def search_observer_candidates(
        self,
        *,
        owner_user_id: int,
        query: str,
    ) -> list[dict[str, Any]]:
        """Search active users for collaboration grants."""

        users = (
            User._default_manager.filter(is_active=True)
            .filter(
                Q(username__icontains=query)
                | Q(account_profile__display_name__icontains=query)
            )
            .exclude(id=owner_user_id)
            .select_related("account_profile")[:10]
        )
        granted_user_ids = set(
            PortfolioObserverGrantModel._default_manager.filter(
                owner_user_id_id=owner_user_id,
                status="active",
            ).values_list("observer_user_id", flat=True)
        )

        return [
            {
                "id": user.id,
                "username": user.username,
                "display_name": (
                    user.account_profile.display_name
                    if hasattr(user, "account_profile")
                    else user.username
                ),
                "email": user.email or "",
                "is_already_granted": user.id in granted_user_ids,
            }
            for user in users
        ]

    def get_trading_cost_config_queryset(self, user_id: int):
        """Return trading cost configs for portfolios owned by the user."""

        return TradingCostConfigModel._default_manager.filter(
            portfolio__user_id=user_id
        ).select_related("portfolio")

    def save_api_trading_cost_config(
        self,
        *,
        actor_user_id: int,
        portfolio_id: int,
        commission_rate: float,
        min_commission: float,
        stamp_duty_rate: float,
        transfer_fee_rate: float,
        is_active: bool,
    ):
        """Create or update one trading cost configuration for the actor's portfolio."""

        portfolio = PortfolioModel._default_manager.get(id=portfolio_id)
        if portfolio.user_id != actor_user_id:
            raise PermissionError("无权为此投资组合配置费率")

        if commission_rate < 0 or commission_rate > 0.01:
            raise ValueError("佣金率应在 0 ~ 0.01（万0 ~ 万10）之间")
        if min_commission < 0:
            raise ValueError("最低佣金不能为负数")
        if stamp_duty_rate < 0 or stamp_duty_rate > 0.01:
            raise ValueError("印花税率应在 0 ~ 0.01 之间")
        if transfer_fee_rate < 0 or transfer_fee_rate > 0.001:
            raise ValueError("过户费率应在 0 ~ 0.001 之间")

        defaults = {
            "commission_rate": commission_rate,
            "min_commission": min_commission,
            "stamp_duty_rate": stamp_duty_rate,
            "transfer_fee_rate": transfer_fee_rate,
            "is_active": is_active,
        }
        config, _ = TradingCostConfigModel._default_manager.update_or_create(
            portfolio=portfolio,
            defaults=defaults,
        )
        return config

    def list_observer_grants_queryset(
        self,
        *,
        user_id: int,
        as_observer: bool,
        status_filter: str | None = None,
    ):
        """Return observer grants scoped to the current owner or observer view."""

        filter_key = "observer_user_id_id" if as_observer else "owner_user_id_id"
        queryset = PortfolioObserverGrantModel._default_manager.filter(
            **{filter_key: user_id}
        ).select_related("observer_user_id", "owner_user_id", "revoked_by")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset.order_by("-created_at")

    def get_observer_grant_by_id(self, grant_id):
        """Return one observer grant with related users when available."""

        return (
            PortfolioObserverGrantModel._default_manager.select_related(
                "owner_user_id",
                "observer_user_id",
                "revoked_by",
            )
            .filter(id=grant_id)
            .first()
        )

    def build_observer_positions_payload(self, owner_user_id: int) -> dict[str, Any]:
        """Return positions and summary statistics for the owner's active portfolio."""

        portfolio = (
            PortfolioModel._default_manager.filter(user_id=owner_user_id, is_active=True)
            .first()
        )
        empty_statistics = {
            "position_count": 0,
            "total_value": 0.0,
            "total_cost": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
        }
        if portfolio is None:
            return {
                "portfolio_id": None,
                "positions": [],
                "statistics": empty_statistics,
            }

        positions = list(
            PositionModel._default_manager.filter(portfolio=portfolio, is_closed=False)
        )
        position_count = len(positions)
        total_value = sum((position.market_value or Decimal("0")) for position in positions)
        total_cost = sum(
            Decimal(str(position.shares)) * (position.avg_cost or Decimal("0"))
            for position in positions
        )
        total_pnl = total_value - total_cost
        total_pnl_pct = float((total_pnl / total_cost * 100) if total_cost > 0 else 0)

        return {
            "portfolio_id": portfolio.id,
            "positions": [
                {
                    "id": position.id,
                    "asset_code": position.asset_code,
                    "asset_name": getattr(position, "asset_name", position.asset_code),
                    "asset_class": position.asset_class,
                    "shares": float(position.shares),
                    "avg_cost": float(position.avg_cost),
                    "current_price": float(position.current_price),
                    "market_value": float(position.market_value),
                    "unrealized_pnl": float(position.unrealized_pnl),
                    "unrealized_pnl_pct": float(position.unrealized_pnl_pct),
                }
                for position in positions
            ],
            "statistics": {
                "position_count": position_count,
                "total_value": float(total_value),
                "total_cost": float(total_cost),
                "total_pnl": float(total_pnl),
                "total_pnl_pct": total_pnl_pct,
            },
        }

    def update_observer_grant(self, *, grant_id, expires_at):
        """Persist a grant expiry update and return the refreshed model."""

        grant = self.get_observer_grant_by_id(grant_id)
        if grant is None:
            raise PortfolioObserverGrantModel.DoesNotExist
        grant.expires_at = expires_at
        grant.save(update_fields=["expires_at"])
        return grant

    def revoke_observer_grant(self, *, grant_id, revoked_by_user_id: int):
        """Revoke one observer grant and return the refreshed model."""

        grant = self.get_observer_grant_by_id(grant_id)
        if grant is None:
            raise PortfolioObserverGrantModel.DoesNotExist
        revoked_by = User._default_manager.get(id=revoked_by_user_id)
        grant.revoke(revoked_by)
        return grant

    def save_trading_cost_config(
        self,
        *,
        portfolio_id: int,
        commission_rate: float,
        min_commission: float,
        stamp_duty_rate: float,
        transfer_fee_rate: float,
    ) -> TradingCostConfigModel:
        """Create or update the trading cost configuration for a portfolio."""

        if commission_rate < 0 or commission_rate > 0.01:
            raise ValueError("佣金率应在 0 ~ 0.01（万0 ~ 万10）之间")
        if min_commission < 0:
            raise ValueError("最低佣金不能为负数")
        if stamp_duty_rate < 0 or stamp_duty_rate > 0.01:
            raise ValueError("印花税率应在 0 ~ 0.01 之间")
        if transfer_fee_rate < 0 or transfer_fee_rate > 0.001:
            raise ValueError("过户费率应在 0 ~ 0.001 之间")

        portfolio = PortfolioModel._default_manager.get(id=portfolio_id)
        defaults = {
            "commission_rate": commission_rate,
            "min_commission": min_commission,
            "stamp_duty_rate": stamp_duty_rate,
            "transfer_fee_rate": transfer_fee_rate,
            "is_active": True,
        }
        config, _ = TradingCostConfigModel._default_manager.update_or_create(
            portfolio=portfolio,
            defaults=defaults,
        )
        return config

    def create_access_token(
        self,
        *,
        target_user_id: int,
        created_by_user_id: int,
        token_name: str,
    ) -> tuple[UserAccessTokenModel, str]:
        """Create a token for the target user."""

        target_user = User._default_manager.select_related("account_profile").get(id=target_user_id)
        created_by = User._default_manager.get(id=created_by_user_id)
        token, raw_key = UserAccessTokenModel.create_token(
            user=target_user,
            name=token_name,
            created_by=created_by,
        )
        return token, raw_key

    def revoke_access_token_for_user(self, *, target_user_id: int, token_id: int) -> str:
        """Revoke one active token owned by the target user."""

        token = UserAccessTokenModel._default_manager.get(
            id=token_id,
            user_id=target_user_id,
            is_active=True,
        )
        token_name = token.name
        token.revoke()
        return token_name

    def revoke_all_access_tokens_for_user(self, *, target_user_id: int) -> dict[str, Any]:
        """Revoke all active tokens for the target user."""

        target_user = User._default_manager.get(id=target_user_id)
        active_tokens = list(
            UserAccessTokenModel._default_manager.filter(user=target_user, is_active=True)
        )
        for token in active_tokens:
            token.revoke()
        return {
            "username": target_user.username,
            "deleted_count": len(active_tokens),
        }

    def revoke_access_token_by_id(self, token_id: int) -> dict[str, Any]:
        """Revoke a token by id."""

        token = UserAccessTokenModel._default_manager.select_related("user").get(
            id=token_id,
            is_active=True,
        )
        username = token.user.username
        token_name = token.name
        token.revoke()
        return {"username": username, "token_name": token_name}

    def create_capital_flow(
        self,
        *,
        user_id: int,
        flow_type: str,
        amount: Decimal,
        flow_date: date,
        notes: str,
    ) -> None:
        """Create a capital flow for the user's active portfolio."""

        user = User._default_manager.get(id=user_id)
        portfolio = PortfolioModel._default_manager.filter(user_id=user_id, is_active=True).first()
        if portfolio is None:
            portfolio = PortfolioModel._default_manager.create(
                user=user,
                name="默认组合",
                is_active=True,
            )

        CapitalFlowModel._default_manager.create(
            user=user,
            portfolio=portfolio,
            flow_type=flow_type,
            amount=amount,
            flow_date=flow_date,
            notes=notes,
        )

    def build_user_management_context(
        self,
        *,
        status_filter: str,
        search_query: str,
    ) -> dict[str, Any]:
        """Build the admin user management context."""

        profiles = AccountProfileModel._default_manager.select_related("user", "approved_by").all()
        if status_filter:
            profiles = profiles.filter(approval_status=status_filter)
        if search_query:
            profiles = profiles.filter(
                Q(user__username__icontains=search_query)
                | Q(user__email__icontains=search_query)
                | Q(display_name__icontains=search_query)
            )
        profiles = profiles.order_by("-created_at")

        return {
            "profiles": profiles,
            "system_settings": SystemSettingsModel.get_settings(),
            "status_filter": status_filter,
            "search_query": search_query,
            "total_count": profiles.count(),
            "pending_count": profiles.filter(approval_status="pending").count(),
            "approved_count": profiles.filter(
                approval_status__in=["approved", "auto_approved"]
            ).count(),
            "rejected_count": profiles.filter(approval_status="rejected").count(),
        }

    def build_token_management_context(
        self,
        *,
        search_query: str,
        only_without_token: bool,
    ) -> dict[str, Any]:
        """Build the admin token management context."""

        users = User._default_manager.select_related("account_profile").all().order_by("-date_joined")
        if search_query:
            users = users.filter(
                Q(username__icontains=search_query) | Q(email__icontains=search_query)
            )

        tokens = (
            UserAccessTokenModel._default_manager.select_related("created_by")
            .filter(is_active=True)
            .order_by("-created_at")
        )
        token_map: dict[int, list[UserAccessTokenModel]] = {}
        for token in tokens:
            token_map.setdefault(token.user_id, []).append(token)

        rows = []
        for user in users:
            user_tokens = token_map.get(user.id, [])
            if only_without_token and user_tokens:
                continue
            rows.append(
                {
                    "user": user,
                    "profile": getattr(user, "account_profile", None),
                    "tokens": user_tokens,
                    "has_token": bool(user_tokens),
                    "token_count": len(user_tokens),
                }
            )

        return {
            "rows": rows,
            "search_query": search_query,
            "only_without_token": only_without_token,
            "total_users": len(rows),
            "with_token_count": sum(1 for row in rows if row["has_token"]),
            "without_token_count": sum(1 for row in rows if not row["has_token"]),
            "total_token_count": sum(row["token_count"] for row in rows),
            "system_settings": SystemSettingsModel.get_settings(),
        }

    def toggle_user_mcp(self, target_user_id: int) -> dict[str, Any]:
        """Toggle MCP access for a user."""

        settings_obj = SystemSettingsModel.get_settings()
        target_user = User._default_manager.select_related("account_profile").get(id=target_user_id)
        profile = target_user.account_profile
        profile.mcp_enabled = not profile.mcp_enabled
        profile.save(update_fields=["mcp_enabled", "updated_at"])

        if not profile.mcp_enabled:
            for token in UserAccessTokenModel._default_manager.filter(
                user=target_user,
                is_active=True,
            ):
                token.revoke()

        return {
            "username": target_user.username,
            "mcp_enabled": profile.mcp_enabled,
            "default_mcp_enabled": settings_obj.default_mcp_enabled,
        }

    def approve_user(self, *, actor_user_id: int, target_user_id: int) -> dict[str, Any]:
        """Approve a pending user."""

        with transaction.atomic():
            actor = User._default_manager.get(id=actor_user_id)
            target_user = User._default_manager.get(id=target_user_id)
            profile = target_user.account_profile

            if profile.approval_status == "approved":
                return {
                    "level": "warning",
                    "message": f"用户 {target_user.username} 已经被批准过了",
                    "username": target_user.username,
                }
            if profile.approval_status == "rejected":
                return {
                    "level": "error",
                    "message": f"用户 {target_user.username} 已被拒绝，请先取消拒绝状态",
                    "username": target_user.username,
                }
            if profile.approval_status != "pending":
                return {
                    "level": "error",
                    "message": f"用户 {target_user.username} 当前状态不允许批准",
                    "username": target_user.username,
                }

            target_user.is_active = True
            target_user.save(update_fields=["is_active"])

            profile.approval_status = "approved"
            profile.approved_at = timezone.now()
            profile.approved_by = actor
            profile.mcp_enabled = SystemSettingsModel.get_settings().default_mcp_enabled
            profile.rejection_reason = ""
            profile.save(
                update_fields=[
                    "approval_status",
                    "approved_at",
                    "approved_by",
                    "mcp_enabled",
                    "rejection_reason",
                    "updated_at",
                ]
            )

            return {
                "level": "success",
                "message": f"已批准用户 {target_user.username}",
                "username": target_user.username,
            }

    def reject_user(
        self,
        *,
        actor_user_id: int,
        target_user_id: int,
        rejection_reason: str,
    ) -> dict[str, Any]:
        """Reject a pending user and revoke active tokens."""

        with transaction.atomic():
            actor = User._default_manager.get(id=actor_user_id)
            target_user = User._default_manager.get(id=target_user_id)
            profile = target_user.account_profile

            if target_user.id == actor.id:
                return {"level": "error", "message": "不能拒绝自己", "username": target_user.username}

            if profile.approval_status != "pending":
                return {
                    "level": "error",
                    "message": f"用户 {target_user.username} 当前状态不允许拒绝",
                    "username": target_user.username,
                }

            profile.approval_status = "rejected"
            profile.rejection_reason = rejection_reason
            profile.approved_at = None
            profile.approved_by = None
            profile.save(
                update_fields=[
                    "approval_status",
                    "rejection_reason",
                    "approved_at",
                    "approved_by",
                    "updated_at",
                ]
            )

            target_user.is_active = False
            target_user.save(update_fields=["is_active"])
            for token in UserAccessTokenModel._default_manager.filter(
                user=target_user,
                is_active=True,
            ):
                token.revoke()

            return {
                "level": "success",
                "message": f"已拒绝用户 {target_user.username}",
                "username": target_user.username,
            }

    def set_user_role(self, *, target_user_id: int, rbac_role: str) -> dict[str, Any]:
        """Update a user's RBAC role."""

        target_user = User._default_manager.get(id=target_user_id)
        profile = target_user.account_profile
        profile.rbac_role = rbac_role
        profile.save(update_fields=["rbac_role", "updated_at"])
        return {
            "level": "success",
            "message": f"已将用户 {target_user.username} 角色更新为 {rbac_role}",
            "username": target_user.username,
        }

    def reset_user_status(self, *, actor_user_id: int, target_user_id: int) -> dict[str, Any]:
        """Reset a user's approval status back to pending."""

        with transaction.atomic():
            actor = User._default_manager.get(id=actor_user_id)
            target_user = User._default_manager.get(id=target_user_id)
            profile = target_user.account_profile

            if target_user.id == actor.id:
                return {"level": "error", "message": "不能重置自己", "username": target_user.username}

            profile.approval_status = "pending"
            profile.approved_at = None
            profile.approved_by = None
            profile.rejection_reason = ""
            profile.save(
                update_fields=[
                    "approval_status",
                    "approved_at",
                    "approved_by",
                    "rejection_reason",
                    "updated_at",
                ]
            )

            target_user.is_active = False
            target_user.save(update_fields=["is_active"])
            for token in UserAccessTokenModel._default_manager.filter(
                user=target_user,
                is_active=True,
            ):
                token.revoke()

            return {
                "level": "success",
                "message": f"已重置用户 {target_user.username} 的状态",
                "username": target_user.username,
            }

    def build_system_settings_context(self) -> dict[str, Any]:
        """Build the system settings page context."""

        system_settings = SystemSettingsModel.get_settings()
        return {
            "system_settings": system_settings,
            "market_color_choices": SystemSettingsModel.MARKET_COLOR_CONVENTION_CHOICES,
            "alpha_pool_mode_choices": SystemSettingsModel.ALPHA_POOL_MODE_CHOICES,
            "market_visuals": system_settings.get_market_visual_tokens(),
            "benchmark_code_map_json": json.dumps(
                system_settings.benchmark_code_map or {},
                ensure_ascii=False,
                indent=2,
            ),
            "asset_proxy_code_map_json": json.dumps(
                system_settings.asset_proxy_code_map or {},
                ensure_ascii=False,
                indent=2,
            ),
        }

    def update_system_settings_from_mapping(self, data: Mapping[str, Any]) -> None:
        """Update system settings from an HTTP form mapping."""

        system_settings = SystemSettingsModel.get_settings()
        market_color_choices = {key for key, _ in SystemSettingsModel.MARKET_COLOR_CONVENTION_CHOICES}
        alpha_pool_mode_choices = {key for key, _ in SystemSettingsModel.ALPHA_POOL_MODE_CHOICES}

        benchmark_code_map = json.loads(data.get("benchmark_code_map", "{}") or "{}")
        asset_proxy_code_map = json.loads(data.get("asset_proxy_code_map", "{}") or "{}")
        market_color_convention = data.get(
            "market_color_convention",
            system_settings.market_color_convention,
        )
        alpha_pool_mode = data.get("alpha_pool_mode", system_settings.alpha_pool_mode)

        if not isinstance(benchmark_code_map, dict):
            raise ValueError("基准代码映射必须是 JSON 对象")
        if not isinstance(asset_proxy_code_map, dict):
            raise ValueError("资产代理代码映射必须是 JSON 对象")
        if market_color_convention not in market_color_choices:
            raise ValueError("市场颜色约定不合法")
        if alpha_pool_mode not in alpha_pool_mode_choices:
            raise ValueError("Alpha 股票池模式不合法")

        system_settings.require_user_approval = data.get("require_user_approval") == "on"
        system_settings.auto_approve_first_admin = data.get("auto_approve_first_admin") == "on"
        system_settings.default_mcp_enabled = data.get("default_mcp_enabled") == "on"
        system_settings.allow_token_plaintext_view = data.get("allow_token_plaintext_view") == "on"
        system_settings.market_color_convention = market_color_convention
        system_settings.alpha_pool_mode = alpha_pool_mode
        system_settings.user_agreement_content = data.get("user_agreement_content", "")
        system_settings.risk_warning_content = data.get("risk_warning_content", "")
        system_settings.notes = data.get("notes", "")
        system_settings.benchmark_code_map = benchmark_code_map
        system_settings.asset_proxy_code_map = asset_proxy_code_map
        system_settings.save()

    def build_backup_download_payload(self, token: str) -> dict[str, Any]:
        """Validate the download token and return a generated backup payload."""

        config = SystemSettingsModel.get_settings()
        max_age_seconds = max(config.backup_link_ttl_days, 1) * 86400

        try:
            payload = validate_download_token(token, max_age_seconds=max_age_seconds)
        except Exception as exc:
            raise LookupError("备份链接无效或已过期") from exc

        if payload.get("settings_id") != config.pk or payload.get("email") != config.backup_email:
            raise LookupError("备份链接无效")

        if not config.backup_enabled:
            raise ValueError("数据库备份邮件功能未启用")

        archive = generate_backup_archive(config)
        return {
            "filename": archive.filename,
            "content": archive.content,
            "content_type": archive.content_type,
        }

    def has_active_observer_access(self, *, owner_user_id: int, observer_user_id: int) -> bool:
        """Return whether the observer currently has a valid read grant."""

        now = timezone.now()
        return PortfolioObserverGrantModel._default_manager.filter(
            owner_user_id=owner_user_id,
            observer_user_id=observer_user_id,
            status="active",
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        ).exists()

    def get_accessible_portfolios_queryset(self, user_id: int):
        """Return portfolios owned by or shared with the given user."""

        now = timezone.now()
        active_grants = PortfolioObserverGrantModel._default_manager.filter(
            observer_user_id=user_id,
            status="active",
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        ).values_list("owner_user_id", flat=True)
        return PortfolioModel._default_manager.filter(
            Q(user_id=user_id) | Q(user_id__in=active_grants)
        )

    def count_owned_active_observer_grants(self, user_id: int) -> int:
        """Count active observer grants granted by the user."""

        return PortfolioObserverGrantModel._default_manager.filter(
            owner_user_id_id=user_id,
            status="active",
        ).count()

    def count_observable_active_grants(self, user_id: int) -> int:
        """Count active observer grants received by the user."""

        return PortfolioObserverGrantModel._default_manager.filter(
            observer_user_id_id=user_id,
            status="active",
        ).count()

    def find_user_by_username(self, username: str):
        """Return one user by username when available."""

        return User._default_manager.filter(username=username).first()

    def find_user_by_id(self, user_id: int):
        """Return one user by id when available."""

        return User._default_manager.filter(id=user_id).first()

    def get_active_observer_grant(self, *, owner_user_id: int, observer_user_id: int):
        """Return one active observer grant for the owner/observer pair."""

        return PortfolioObserverGrantModel._default_manager.filter(
            owner_user_id_id=owner_user_id,
            observer_user_id_id=observer_user_id,
            status="active",
        ).first()

    def create_observer_grant(
        self,
        *,
        owner_user_id: int,
        observer_user_id: int,
        created_by_user_id: int,
        expires_at,
    ):
        """Create one observer grant record."""

        return PortfolioObserverGrantModel._default_manager.create(
            owner_user_id_id=owner_user_id,
            observer_user_id_id=observer_user_id,
            created_by_id=created_by_user_id,
            expires_at=expires_at,
        )
