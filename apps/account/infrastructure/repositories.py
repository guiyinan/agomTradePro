"""
Account Infrastructure Repositories

数据仓储实现，负责数据持久化和查询。
遵循依赖反转原则：Domain层定义接口，Infrastructure层实现。
"""

from decimal import Decimal
from typing import List, Optional, Dict, Any
from datetime import date, datetime, timedelta

from django.contrib.auth.models import User
from django.db.models import Sum, Q, F, Count
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.account.infrastructure.models import (
    AccountProfileModel,
    PortfolioModel,
    PositionModel,
    TransactionModel,
    AssetMetadataModel,
    PositionSignalLogModel,
    PortfolioDailySnapshotModel,
    StopLossConfigModel,
    TakeProfitConfigModel,
    StopLossTriggerModel,
)
from apps.account.domain.entities import (
    AccountProfile,
    Position,
    PortfolioSnapshot,
    Transaction,
    RiskTolerance,
    PositionSource,
    PositionStatus,
    AssetClassType,
    Region,
    CrossBorderFlag,
    InvestmentStyle,
)
from apps.signal.infrastructure.models import InvestmentSignalModel


class AccountRepository:
    """用户账户仓储"""

    def get_by_user_id(self, user_id: int) -> Optional[AccountProfile]:
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
            user_id=user_id,
            name="默认组合",
            defaults={"is_active": True}
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


class PortfolioRepository:
    """投资组合仓储"""

    def get_user_portfolios(self, user_id: int) -> List[Dict]:
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

    def get_portfolio_snapshot(self, portfolio_id: int) -> Optional[PortfolioSnapshot]:
        """获取组合快照（包含持仓详情）"""
        from apps.account.infrastructure.models import PortfolioDailySnapshotModel
        from datetime import timedelta

        try:
            portfolio = PortfolioModel._default_manager.get(id=portfolio_id)
        except PortfolioModel.DoesNotExist:
            return None

        # 获取活跃持仓
        position_models = PositionModel._default_manager.filter(
            portfolio=portfolio,
            is_closed=False
        ).select_related("portfolio").order_by("-opened_at")

        positions = self._convert_to_position_entities(position_models)

        # 计算当前总览数据
        cash_balance = self._calculate_cash_balance(portfolio, positions)
        invested_value = sum(float(p.market_value) for p in positions)
        total_value = cash_balance + invested_value

        # 回溯收益率计算
        # 1. 年收益率（对比1年前）
        one_year_ago = timezone.now() - timedelta(days=365)
        yearly_snapshot = PortfolioDailySnapshotModel._default_manager.filter(
            portfolio=portfolio,
            snapshot_date__lte=one_year_ago.date()
            ).order_by('-snapshot_date').first()

        # 2. 月收益率（对比1个月前）
        one_month_ago = timezone.now() - timedelta(days=30)
        monthly_snapshot = PortfolioDailySnapshotModel._default_manager.filter(
            portfolio=portfolio,
            snapshot_date__lte=one_month_ago.date()
            ).order_by('-snapshot_date').first()

        # 计算收益率
        if yearly_snapshot:
            yearly_return = total_value - float(yearly_snapshot.total_value)
            yearly_return_pct = (yearly_return / float(yearly_snapshot.total_value) * 100)
        else:
            # 没有历史快照，使用累计入金作为基准
            from apps.account.infrastructure.models import CapitalFlowModel
            total_deposit = CapitalFlowModel._default_manager.filter(
                portfolio=portfolio,
                flow_type='deposit'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            total_withdraw = CapitalFlowModel._default_manager.filter(
                portfolio=portfolio,
                flow_type='withdraw'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            net_capital = float(total_deposit - total_withdraw)

            # 如果没有任何入金记录，收益为0
            if net_capital == 0:
                yearly_return = 0.0
                yearly_return_pct = 0.0
            else:
                yearly_return = (total_value - net_capital)
                yearly_return_pct = (yearly_return / net_capital * 100)

        if monthly_snapshot:
            monthly_return = total_value - float(monthly_snapshot.total_value)
            monthly_return_pct = (monthly_return / float(monthly_snapshot.total_value) * 100)
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
                'total_value': Decimal(str(total_value)),
                'cash_balance': Decimal(str(cash_balance)),
                'invested_value': Decimal(str(invested_value)),
                'position_count': len(positions),
            }
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

    def _convert_to_position_entities(self, models: List[PositionModel]) -> List[Position]:
        """将ORM模型转换为Domain实体"""
        entities = []
        for model in models:
            entities.append(Position(
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
            ))
        return entities

    def _calculate_cash_balance(self, portfolio: PortfolioModel, positions: List[Position]) -> float:
        """
        计算现金余额

        逻辑：
        - 入金增加现金，出金减少现金
        - 买入交易减少现金，卖出交易增加现金
        - 当前现金 = 入金 - 出金 - 买入支出 + 卖出收入
        - 总资产 = 当前现金 + 持仓市值
        """
        from apps.account.infrastructure.models import CapitalFlowModel, TransactionModel
        from django.db.models import Sum

        # 1. 资金流动（入金 - 出金）
        total_deposit = CapitalFlowModel._default_manager.filter(
            portfolio=portfolio,
            flow_type='deposit'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        total_withdraw = CapitalFlowModel._default_manager.filter(
            portfolio=portfolio,
            flow_type='withdraw'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # 2. 交易对现金的影响
        buy_total = TransactionModel._default_manager.filter(
            portfolio=portfolio,
            action='buy'
        ).aggregate(total=Sum('notional'))['total'] or Decimal('0')

        sell_total = TransactionModel._default_manager.filter(
            portfolio=portfolio,
            action='sell'
        ).aggregate(total=Sum('notional'))['total'] or Decimal('0')

        # 3. 当前现金 = 入金 - 出金 - 买入支出 + 卖出收入
        cash_balance = float(total_deposit - total_withdraw - buy_total + sell_total)

        return max(0, cash_balance)


class PositionRepository:
    """持仓仓储"""

    def get_user_positions(
        self,
        user_id: int,
        status: Optional[str] = None,
        asset_class: Optional[str] = None,
    ) -> List[Position]:
        """获取用户持仓列表"""
        queryset = PositionModel._default_manager.filter(
            portfolio__user_id=user_id
        ).select_related("portfolio").order_by("-opened_at")

        if status == "active":
            queryset = queryset.filter(is_closed=False)
        elif status == "closed":
            queryset = queryset.filter(is_closed=True)

        if asset_class:
            queryset = queryset.filter(asset_class=asset_class)

        return PortfolioRepository()._convert_to_position_entities(queryset)

    def get_position_by_id(self, position_id: int) -> Optional[Position]:
        """根据ID获取持仓"""
        try:
            model = PositionModel._default_manager.get(id=position_id)
            return PortfolioRepository()._convert_to_position_entities([model])[0]
        except PositionModel.DoesNotExist:
            return None

    def create_position(
        self,
        portfolio_id: int,
        asset_code: str,
        shares: float,
        price: Decimal,
        source: str = "manual",
        source_id: Optional[int] = None,
    ) -> Position:
        """创建新持仓"""
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

    def close_position(self, position_id: int, shares: Optional[float] = None) -> Optional[Position]:
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

        model.save()

        return PortfolioRepository()._convert_to_position_entities([model])[0]

    def update_position_price(self, position_id: int, new_price: Decimal) -> Optional[Position]:
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
    ) -> Optional[Position]:
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
        position = self.create_position(
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
    ) -> List[Transaction]:
        """获取组合交易记录"""
        models = TransactionModel._default_manager.filter(
            portfolio_id=portfolio_id
        ).select_related("position").order_by("-traded_at")[:limit]

        transactions = []
        for model in models:
            transactions.append(Transaction(
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
            ))
        return transactions


class AssetMetadataRepository:
    """资产元数据仓储"""

    def get_or_create_asset(
        self,
        asset_code: str,
        name: str,
        asset_class: str = "equity",
        region: str = "CN",
        **kwargs
    ) -> Dict:
        """获取或创建资产元数据"""
        asset, created = AssetMetadataModel._default_manager.get_or_create(
            asset_code=asset_code,
            defaults={
                "name": name,
                "asset_class": asset_class,
                "region": region,
                **kwargs
            }
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
        asset_class: Optional[str] = None,
        region: Optional[str] = None,
    ) -> List[Dict]:
        """搜索资产"""
        queryset = AssetMetadataModel._default_manager.all()

        if query:
            queryset = queryset.filter(
                Q(asset_code__icontains=query) | Q(name__icontains=query)
            )

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
        """批量更新用户持仓的当前价格（需要外部行情接口）"""
        # TODO: 集成行情数据源
        # 这里提供一个接口框架，实际价格获取需要调用外部API
        count = PositionModel._default_manager.filter(
            portfolio__user_id=user_id,
            is_closed=False
        ).update(
            current_price=F("avg_cost")  # 暂时使用成本价
        )
        return count

    def get_asset_by_code(self, asset_code: str) -> Optional[Dict[str, Any]]:
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

    def get_active_stop_loss_configs(
        self, user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all active stop loss configurations.

        Args:
            user_id: Optional user ID to filter by

        Returns:
            List of stop loss config dicts with position relationship
        """
        queryset = StopLossConfigModel._default_manager.filter(status='active')

        if user_id:
            queryset = queryset.filter(position__portfolio__user_id=user_id)

        configs = queryset.select_related('position', 'position__portfolio').all()

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
                },
            }
            for config in configs
        ]

    def get_stop_loss_config_by_position(
        self, position_id: int
    ) -> Optional[Dict[str, Any]]:
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
        trailing_stop_pct: Optional[float] = None,
        max_holding_days: Optional[int] = None,
        highest_price: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """Create stop loss configuration."""
        config = StopLossConfigModel._default_manager.create(
            position_id=position_id,
            stop_loss_type=stop_loss_type,
            stop_loss_pct=stop_loss_pct,
            trailing_stop_pct=trailing_stop_pct,
            max_holding_days=max_holding_days,
            highest_price=highest_price,
            status='active',
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
        status: Optional[str] = None,
        highest_price: Optional[Decimal] = None,
        highest_price_updated_at: Optional[Any] = None,
        triggered_at: Optional[Any] = None,
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
    ) -> Dict[str, Any]:
        """Create stop loss trigger record."""
        trigger = StopLossTriggerModel._default_manager.create(
            position_id=position_id,
            trigger_type=trigger_type,
            trigger_price=trigger_price,
            trigger_time=datetime.now(),
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

    def get_active_take_profit_configs(
        self, user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
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

        configs = queryset.select_related('position', 'position__portfolio').all()

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
                    "portfolio_id": config.position.portfolio_id,
                    "user_id": config.position.portfolio.user_id,
                },
            }
            for config in configs
        ]

    def get_take_profit_config_by_position(
        self, position_id: int
    ) -> Optional[Dict[str, Any]]:
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
        partial_profit_levels: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
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
        is_active: Optional[bool] = None,
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
    ) -> List[Dict[str, Any]]:
        """
        Get portfolio daily snapshots for volatility calculation.

        Returns:
            List of dicts with snapshot_date, total_value
        """
        snapshots = PortfolioDailySnapshotModel._default_manager.filter(
            portfolio_id=portfolio_id
        ).order_by('-snapshot_date')[:days]

        return [
            {
                "snapshot_date": snap.snapshot_date,
                "total_value": float(snap.total_value),
            }
            for snap in reversed(list(snapshots))
        ]


# ============================================================
# Transaction Cost Config Repository
# ============================================================

class TransactionCostConfigRepository:
    """交易成本配置仓储"""

    def get_cost_config(
        self, market: str, asset_class: str
    ) -> Optional[Dict[str, Any]]:
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

    def get_default_cost_config(self, market: str, asset_class: str) -> Dict[str, Any]:
        """
        Get default cost configuration.

        Returns:
            Dict with default values
        """
        return {
            "market": market,
            "asset_class": asset_class,
            "commission_rate": Decimal('0.0003'),
            "slippage_rate": Decimal('0.0002'),
            "stamp_duty_rate": Decimal('0.001'),
            "transfer_fee_rate": Decimal('0.00001'),
            "min_commission": Decimal('5.00'),
            "cost_warning_threshold": 0.005,
        }

