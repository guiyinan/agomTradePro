"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""
from datetime import date
from decimal import Decimal
from typing import Any, List, Optional

from django.db import models, transaction
from django.db.models import Avg, Count, F, Max, Min, Q, Sum

from apps.simulated_trading.domain.entities import (
    AccountType,
    FeeConfig,
    OrderStatus,
    Position,
    SimulatedAccount,
    SimulatedTrade,
    TradeAction,
)
from apps.simulated_trading.infrastructure.models import (
    DailyInspectionNotificationConfigModel,
    DailyInspectionReportModel,
    DailyNetValueModel,
    FeeConfigModel,
    NotificationHistoryModel,
    PositionModel,
    RebalanceProposalModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)


class SimulatedAccountMapper:
    """模拟账户Mapper - Domain实体 ↔ ORM模型"""

    @staticmethod
    def _normalize_account_type(raw_value: str) -> AccountType:
        """
        兼容历史脏数据:
        - "SIMULATED" / "REAL"（大写）
        - "simulated" / "real"（标准值）
        """
        value = (raw_value or "").strip()
        if not value:
            raise ValueError("account_type 不能为空")

        normalized = value.lower()
        try:
            return AccountType(normalized)
        except ValueError:
            # 兜底支持枚举名称格式
            try:
                return AccountType[value.upper()]
            except KeyError as ex:
                raise ValueError(f"非法 account_type: {raw_value}") from ex

    @staticmethod
    def to_entity(model: SimulatedAccountModel) -> SimulatedAccount:
        """ORM模型 → Domain实体"""
        return SimulatedAccount(
            account_id=model.id,
            account_name=model.account_name,
            account_type=SimulatedAccountMapper._normalize_account_type(model.account_type),
            initial_capital=float(model.initial_capital),
            current_cash=float(model.current_cash),
            current_market_value=float(model.current_market_value),
            total_value=float(model.total_value),
            total_return=model.total_return,
            annual_return=model.annual_return,
            max_drawdown=model.max_drawdown,
            sharpe_ratio=model.sharpe_ratio,
            win_rate=model.win_rate,
            total_trades=model.total_trades,
            winning_trades=model.winning_trades,
            start_date=model.start_date,
            last_trade_date=model.last_trade_date,
            is_active=model.is_active,
            auto_trading_enabled=model.auto_trading_enabled,
            max_position_pct=model.max_position_pct,
            max_total_position_pct=model.max_total_position_pct,
            stop_loss_pct=model.stop_loss_pct,
            commission_rate=model.commission_rate,
            slippage_rate=model.slippage_rate
        )

    @staticmethod
    def to_model(entity: SimulatedAccount) -> SimulatedAccountModel:
        """Domain实体 → ORM模型"""
        return SimulatedAccountModel(
            id=entity.account_id,
            account_name=entity.account_name,
            account_type=entity.account_type.value,
            initial_capital=entity.initial_capital,
            current_cash=entity.current_cash,
            current_market_value=entity.current_market_value,
            total_value=entity.total_value,
            total_return=entity.total_return,
            annual_return=entity.annual_return,
            max_drawdown=entity.max_drawdown,
            sharpe_ratio=entity.sharpe_ratio,
            win_rate=entity.win_rate,
            total_trades=entity.total_trades,
            winning_trades=entity.winning_trades,
            start_date=entity.start_date,
            last_trade_date=entity.last_trade_date,
            is_active=entity.is_active,
            auto_trading_enabled=entity.auto_trading_enabled,
            max_position_pct=entity.max_position_pct,
            max_total_position_pct=entity.max_total_position_pct,
            stop_loss_pct=entity.stop_loss_pct,
            commission_rate=entity.commission_rate,
            slippage_rate=entity.slippage_rate
        )


class PositionMapper:
    """持仓Mapper - Domain实体 ↔ ORM模型"""

    @staticmethod
    def to_entity(model: PositionModel) -> Position:
        """ORM模型 → Domain实体"""
        # 将 JSON 字段转换为字符串
        import json
        invalidation_json = None
        if model.invalidation_rule_json:
            invalidation_json = json.dumps(model.invalidation_rule_json, ensure_ascii=False)

        return Position(
            account_id=model.account_id,
            asset_code=model.asset_code,
            asset_name=model.asset_name,
            asset_type=model.asset_type,
            quantity=model.quantity,
            available_quantity=model.available_quantity,
            avg_cost=float(model.avg_cost),
            total_cost=float(model.total_cost),
            current_price=float(model.current_price),
            market_value=float(model.market_value),
            unrealized_pnl=float(model.unrealized_pnl),
            unrealized_pnl_pct=model.unrealized_pnl_pct,
            first_buy_date=model.first_buy_date,
            last_update_date=model.last_update_date,
            signal_id=model.signal_id,
            entry_reason=model.entry_reason,
            # 证伪相关字段
            invalidation_rule_json=invalidation_json,
            invalidation_description=model.invalidation_description,
            is_invalidated=model.is_invalidated,
            invalidation_reason=model.invalidation_reason,
            invalidation_checked_at=model.invalidation_checked_at,
        )

    @staticmethod
    def to_model(entity: Position) -> PositionModel:
        """Domain实体 → ORM模型"""
        import json
        invalidation_json = None
        if entity.invalidation_rule_json:
            invalidation_json = json.loads(entity.invalidation_rule_json)

        return PositionModel(
            account_id=entity.account_id,
            asset_code=entity.asset_code,
            asset_name=entity.asset_name,
            asset_type=entity.asset_type,
            quantity=entity.quantity,
            available_quantity=entity.available_quantity,
            avg_cost=entity.avg_cost,
            total_cost=entity.total_cost,
            current_price=entity.current_price,
            market_value=entity.market_value,
            unrealized_pnl=entity.unrealized_pnl,
            unrealized_pnl_pct=entity.unrealized_pnl_pct,
            first_buy_date=entity.first_buy_date,
            last_update_date=entity.last_update_date,
            signal_id=entity.signal_id,
            entry_reason=entity.entry_reason,
            # 证伪相关字段
            invalidation_rule_json=invalidation_json,
            invalidation_description=entity.invalidation_description or "",
            is_invalidated=entity.is_invalidated,
            invalidation_reason=entity.invalidation_reason or "",
            invalidation_checked_at=entity.invalidation_checked_at,
        )


class SimulatedTradeMapper:
    """交易记录Mapper - Domain实体 ↔ ORM模型"""

    @staticmethod
    def to_entity(model: SimulatedTradeModel) -> SimulatedTrade:
        """ORM模型 → Domain实体"""
        return SimulatedTrade(
            trade_id=model.id,
            account_id=model.account_id,
            asset_code=model.asset_code,
            asset_name=model.asset_name,
            asset_type=model.asset_type,
            action=TradeAction(model.action),
            quantity=model.quantity,
            price=float(model.price),
            amount=float(model.amount),
            commission=float(model.commission),
            slippage=float(model.slippage),
            total_cost=float(model.total_cost),
            realized_pnl=float(model.realized_pnl) if model.realized_pnl else None,
            realized_pnl_pct=model.realized_pnl_pct,
            reason=model.reason,
            signal_id=model.signal_id,
            order_date=model.order_date,
            execution_date=model.execution_date,
            execution_time=model.execution_time,
            status=OrderStatus(model.status)
        )

    @staticmethod
    def to_model(entity: SimulatedTrade) -> SimulatedTradeModel:
        """Domain实体 → ORM模型"""
        return SimulatedTradeModel(
            id=entity.trade_id,
            account_id=entity.account_id,
            asset_code=entity.asset_code,
            asset_name=entity.asset_name,
            asset_type=entity.asset_type,
            action=entity.action.value,
            quantity=entity.quantity,
            price=entity.price,
            amount=entity.amount,
            commission=entity.commission,
            slippage=entity.slippage,
            total_cost=entity.total_cost,
            realized_pnl=entity.realized_pnl,
            realized_pnl_pct=entity.realized_pnl_pct,
            reason=entity.reason,
            signal_id=entity.signal_id,
            order_date=entity.order_date,
            execution_date=entity.execution_date,
            execution_time=entity.execution_time,
            status=entity.status.value
        )


class FeeConfigMapper:
    """费率配置Mapper - Domain实体 ↔ ORM模型"""

    @staticmethod
    def to_entity(model: FeeConfigModel) -> FeeConfig:
        """ORM模型 → Domain实体"""
        return FeeConfig(
            config_id=model.id,
            config_name=model.config_name,
            asset_type=model.asset_type,
            commission_rate_buy=model.commission_rate_buy,
            commission_rate_sell=model.commission_rate_sell,
            min_commission=model.min_commission,
            stamp_duty_rate=model.stamp_duty_rate,
            transfer_fee_rate=model.transfer_fee_rate,
            min_transfer_fee=model.min_transfer_fee,
            slippage_rate=model.slippage_rate,
            is_default=model.is_default,
            is_active=model.is_active,
            description=model.description
        )

    @staticmethod
    def to_model(entity: FeeConfig) -> FeeConfigModel:
        """Domain实体 → ORM模型"""
        return FeeConfigModel(
            id=entity.config_id,
            config_name=entity.config_name,
            asset_type=entity.asset_type,
            commission_rate_buy=entity.commission_rate_buy,
            commission_rate_sell=entity.commission_rate_sell,
            min_commission=entity.min_commission,
            stamp_duty_rate=entity.stamp_duty_rate,
            transfer_fee_rate=entity.transfer_fee_rate,
            min_transfer_fee=entity.min_transfer_fee,
            slippage_rate=entity.slippage_rate,
            is_default=entity.is_default,
            is_active=entity.is_active,
            description=entity.description
        )


class DjangoSimulatedAccountRepository:
    """模拟账户Repository实现"""

    def save(self, account: SimulatedAccount) -> int:
        """
        保存账户(创建或更新)

        Returns:
            账户ID
        """
        if account.account_id == 0:
            # 创建新账户
            model = SimulatedAccountMapper.to_model(account)
            model.id = None  # 确保是新记录
            model.save()
            return model.id
        else:
            # 更新现有账户
            model = SimulatedAccountModel._default_manager.get(id=account.account_id)
            model.account_name = account.account_name
            model.current_cash = account.current_cash
            model.current_market_value = account.current_market_value
            model.total_value = account.total_value
            model.total_return = account.total_return
            model.annual_return = account.annual_return
            model.max_drawdown = account.max_drawdown
            model.sharpe_ratio = account.sharpe_ratio
            model.win_rate = account.win_rate
            model.total_trades = account.total_trades
            model.winning_trades = account.winning_trades
            model.last_trade_date = account.last_trade_date
            model.is_active = account.is_active
            model.auto_trading_enabled = account.auto_trading_enabled
            model.save()
            return account.account_id

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        """根据ID获取账户"""
        try:
            model = SimulatedAccountModel._default_manager.get(id=account_id)
            return SimulatedAccountMapper.to_entity(model)
        except SimulatedAccountModel.DoesNotExist:
            return None

    def get_account_model_by_id(self, account_id: int) -> Any | None:
        """Return one account ORM row for UI/application composition."""

        return SimulatedAccountModel._default_manager.filter(id=account_id).first()

    def get_account_model_for_user(self, account_id: int, user_id: int) -> Any | None:
        """Return one account ORM row owned by a specific user."""

        return SimulatedAccountModel._default_manager.filter(
            id=account_id,
            user_id=user_id,
        ).first()

    def get_by_name(self, account_name: str) -> SimulatedAccount | None:
        """根据名称获取账户"""
        try:
            model = SimulatedAccountModel._default_manager.get(account_name=account_name)
            return SimulatedAccountMapper.to_entity(model)
        except SimulatedAccountModel.DoesNotExist:
            return None

    def get_active_accounts(self) -> list[SimulatedAccount]:
        """获取所有活跃的自动交易账户"""
        models = SimulatedAccountModel._default_manager.filter(
            is_active=True,
            auto_trading_enabled=True
        )
        return [SimulatedAccountMapper.to_entity(m) for m in models]

    def get_all_accounts(self) -> list[SimulatedAccount]:
        """获取所有账户"""
        models = SimulatedAccountModel._default_manager.all()
        return [SimulatedAccountMapper.to_entity(m) for m in models]

    def count_active_account_models(self) -> int:
        """Return the number of active account ORM rows."""

        return SimulatedAccountModel._default_manager.filter(is_active=True).count()

    def sum_active_total_value(self):
        """Return the aggregate total value across active accounts."""

        return (
            SimulatedAccountModel._default_manager.filter(is_active=True).aggregate(
                total=Sum("total_value")
            )["total"]
            or 0
        )

    def get_by_user(self, user_id: int) -> list[SimulatedAccount]:
        """
        ⭐ 新增：根据用户ID获取所有投资组合

        Args:
            user_id: 用户ID

        Returns:
            用户的所有投资组合
        """
        models = SimulatedAccountModel._default_manager.filter(
            user_id=user_id
        ).order_by('-created_at')
        return [SimulatedAccountMapper.to_entity(m) for m in models]

    def list_account_models_for_user(self, user_id: int) -> list[Any]:
        """Return account ORM rows for a user's account management pages."""

        return list(
            SimulatedAccountModel._default_manager.filter(
                user_id=user_id,
            ).order_by("-created_at")
        )

    def create_account_model_for_user(
        self,
        *,
        user: Any,
        account_name: str,
        account_type: str,
        initial_capital: Any,
    ) -> Any:
        """Create one account ORM row for user-facing account pages."""

        return SimulatedAccountModel._default_manager.create(
            user=user,
            account_name=account_name,
            account_type=account_type,
            initial_capital=initial_capital,
            current_cash=initial_capital,
            total_value=initial_capital,
        )

    def get_active_account_models_for_user(self, user_id: int) -> list[Any]:
        """Return active ORM account rows for UI contexts that need model display helpers."""
        return list(
            SimulatedAccountModel._default_manager.filter(
                user_id=user_id,
                is_active=True,
            ).select_related('rotation_config').order_by('account_type', 'account_name')
        )

    def get_by_user_and_type(self, user_id: int, account_type: str) -> list[SimulatedAccount]:
        """
        ⭐ 新增：根据用户ID和账户类型获取投资组合

        Args:
            user_id: 用户ID
            account_type: 'real' 或 'simulated'

        Returns:
            用户的指定类型的投资组合
        """
        models = SimulatedAccountModel._default_manager.filter(
            user_id=user_id,
            account_type=account_type
        ).order_by('-created_at')
        return [SimulatedAccountMapper.to_entity(m) for m in models]

    def delete(self, account_id: int) -> bool:
        """删除账户"""
        try:
            model = SimulatedAccountModel._default_manager.get(id=account_id)
            model.delete()
            return True
        except SimulatedAccountModel.DoesNotExist:
            return False

    def user_owns_account(self, account_id: int, user_id: int) -> bool:
        """判断账户是否属于指定用户。"""
        return SimulatedAccountModel._default_manager.filter(
            id=account_id,
            user_id=user_id,
        ).exists()

    def delete_account_with_summary(self, account_id: int) -> dict | None:
        """Delete an account row and return small cascade counts for UI feedback."""

        account = self.get_account_model_by_id(account_id)
        if not account:
            return None

        summary = {
            "account_id": account.id,
            "account_name": account.account_name,
            "deleted_positions": PositionModel._default_manager.filter(account=account).count(),
            "deleted_trades": SimulatedTradeModel._default_manager.filter(account=account).count(),
            "deleted_reports": DailyInspectionReportModel._default_manager.filter(account=account).count(),
        }
        account.delete()
        return summary


class DjangoPositionRepository:
    """持仓Repository实现"""

    def get_position_record(self, account_id: int, asset_code: str) -> PositionModel | None:
        """Return one ORM position row for compatibility call sites."""

        return PositionModel._default_manager.filter(
            account_id=account_id,
            asset_code=asset_code,
        ).first()

    def count_position_models(self) -> int:
        """Return the total number of position ORM rows."""

        return PositionModel._default_manager.count()

    def update_position_prices(self, price_by_code: dict[str, Any]) -> list[dict]:
        """Update open positions and account totals from latest prices."""

        if not price_by_code:
            return []

        updates = []
        positions = PositionModel._default_manager.select_related("account").filter(
            asset_code__in=price_by_code.keys(),
            quantity__gt=0,
        )

        for position in positions:
            old_price = position.current_price
            new_price = Decimal(str(price_by_code[position.asset_code]))
            market_value = new_price * position.quantity
            unrealized_pnl = market_value - position.total_cost
            unrealized_pnl_pct = (
                float((unrealized_pnl / position.total_cost) * Decimal("100"))
                if position.total_cost > 0
                else 0.0
            )

            position.current_price = new_price
            position.market_value = market_value
            position.unrealized_pnl = unrealized_pnl
            position.unrealized_pnl_pct = unrealized_pnl_pct
            position.save(
                update_fields=[
                    "current_price",
                    "market_value",
                    "unrealized_pnl",
                    "unrealized_pnl_pct",
                ]
            )

            self._update_account_value(position.account)
            updates.append(
                {
                    "asset_code": position.asset_code,
                    "old_price": old_price,
                    "new_price": new_price,
                    "price_changed": old_price != new_price,
                }
            )

        return updates

    def _update_account_value(self, account: Any) -> None:
        """Recalculate account totals after position price changes."""

        positions = PositionModel._default_manager.filter(account=account)
        market_value = sum(
            (position.market_value for position in positions),
            start=Decimal("0"),
        )
        total_value = market_value + account.current_cash
        total_return = (
            float(((total_value - account.initial_capital) / account.initial_capital) * Decimal("100"))
            if account.initial_capital > 0
            else 0.0
        )

        account.current_market_value = market_value
        account.total_value = total_value
        account.total_return = total_return
        account.save(update_fields=["current_market_value", "total_value", "total_return"])

    def save_position_record(
        self,
        *,
        account_id: int,
        asset_code: str,
        defaults: dict,
    ) -> PositionModel:
        """Create or update one ORM position row and return it."""

        model, _ = PositionModel._default_manager.update_or_create(
            account_id=account_id,
            asset_code=asset_code,
            defaults=defaults,
        )
        return model

    def save(self, position: Position) -> int:
        """
        保存持仓(创建或更新)

        Returns:
            持仓ID
        """
        # 检查是否已存在
        existing = PositionModel._default_manager.filter(
            account_id=position.account_id,
            asset_code=position.asset_code
        ).first()

        if existing:
            # 更新现有持仓
            model = existing
            model.quantity = position.quantity
            model.available_quantity = position.available_quantity
            model.avg_cost = position.avg_cost
            model.total_cost = position.total_cost
            model.current_price = position.current_price
            model.market_value = position.market_value
            model.unrealized_pnl = position.unrealized_pnl
            model.unrealized_pnl_pct = position.unrealized_pnl_pct
            model.last_update_date = position.last_update_date
            model.save()
            return model.id
        else:
            # 创建新持仓
            model = PositionMapper.to_model(position)
            model.id = None
            model.save()
            return model.id

    def get_by_account(self, account_id: int) -> list[Position]:
        """获取账户的所有持仓"""
        models = PositionModel._default_manager.filter(account_id=account_id)
        return [PositionMapper.to_entity(m) for m in models]

    def list_position_models_for_account(self, account_id: int, limit: int | None = None) -> list[Any]:
        """Return position ORM rows for template rendering."""

        queryset = PositionModel._default_manager.filter(account_id=account_id)
        if limit is not None:
            queryset = queryset[:limit]
        return list(queryset)

    def get_position_snapshots(self, account_id: int) -> list[dict]:
        """返回交易计划所需的持仓快照。"""
        return list(
            PositionModel._default_manager.filter(account_id=account_id).values(
                "asset_code",
                "asset_name",
                "quantity",
                "avg_cost",
                "current_price",
                "market_value",
                "unrealized_pnl_pct",
            )
        )

    def get_position(self, account_id: int, asset_code: str) -> Position | None:
        """获取特定持仓"""
        try:
            model = PositionModel._default_manager.get(
                account_id=account_id,
                asset_code=asset_code
            )
            return PositionMapper.to_entity(model)
        except PositionModel.DoesNotExist:
            return None

    def delete(self, account_id: int, asset_code: str) -> bool:
        """删除持仓"""
        deleted, _ = PositionModel._default_manager.filter(
            account_id=account_id,
            asset_code=asset_code
        ).delete()
        return deleted > 0

    def get_pending_invalidation_positions(self) -> list[Position]:
        """获取需要做证伪检查的持仓。"""
        models = PositionModel._default_manager.filter(
            invalidation_rule_json__isnull=False,
            is_invalidated=False,
        ).exclude(invalidation_rule_json={})
        return [PositionMapper.to_entity(m) for m in models]

    def get_position_by_id(self, position_id: int) -> Position | None:
        """按主键获取持仓。"""
        try:
            model = PositionModel._default_manager.get(id=position_id)
            return PositionMapper.to_entity(model)
        except PositionModel.DoesNotExist:
            return None

    def mark_invalidation_checked(self, account_id: int, asset_code: str, checked_at) -> bool:
        updated = PositionModel._default_manager.filter(
            account_id=account_id,
            asset_code=asset_code,
        ).update(invalidation_checked_at=checked_at)
        return updated > 0

    def mark_invalidated(
        self,
        account_id: int,
        asset_code: str,
        reason: str,
        checked_at,
    ) -> bool:
        updated = PositionModel._default_manager.filter(
            account_id=account_id,
            asset_code=asset_code,
        ).update(
            is_invalidated=True,
            invalidation_reason=reason,
            invalidation_checked_at=checked_at,
        )
        return updated > 0

    def count_positions_with_invalidation_rules(self) -> int:
        return PositionModel._default_manager.filter(
            invalidation_rule_json__isnull=False
        ).exclude(invalidation_rule_json={}).count()

    def get_invalidated_position_summaries(self) -> list[dict]:
        models = PositionModel._default_manager.filter(
            is_invalidated=True,
            quantity__gt=0,
        ).select_related("account").order_by("-invalidation_checked_at")
        return [
            {
                "account_id": model.account_id,
                "account_name": model.account.account_name,
                "asset_code": model.asset_code,
                "asset_name": model.asset_name,
                "quantity": model.quantity,
                "market_value": float(model.market_value),
                "unrealized_pnl": float(model.unrealized_pnl),
                "unrealized_pnl_pct": model.unrealized_pnl_pct,
                "invalidation_reason": model.invalidation_reason,
                "invalidation_checked_at": (
                    model.invalidation_checked_at.isoformat()
                    if model.invalidation_checked_at else None
                ),
            }
            for model in models
        ]


class DjangoTradeRepository:
    """交易记录Repository实现"""

    def create_trade_record(self, **payload) -> SimulatedTradeModel:
        """Create one ORM trade row and return it."""

        return SimulatedTradeModel._default_manager.create(**payload)

    def save(self, trade: SimulatedTrade) -> int:
        """
        保存交易记录

        Returns:
            交易ID
        """
        model = SimulatedTradeMapper.to_model(trade)
        model.id = None  # 确保是新记录
        model.save()
        return model.id

    def get_by_account(self, account_id: int) -> list[SimulatedTrade]:
        """获取账户的所有交易记录"""
        models = SimulatedTradeModel._default_manager.filter(
            account_id=account_id
        ).order_by('-execution_date', '-execution_time')
        return [SimulatedTradeMapper.to_entity(m) for m in models]

    def count_trade_models(self) -> int:
        """Return the total number of trade ORM rows."""

        return SimulatedTradeModel._default_manager.count()

    def summarize_trade_models_for_date(self, execution_date) -> dict[str, int]:
        """Return buy/sell counts for one execution date."""

        queryset = SimulatedTradeModel._default_manager.filter(execution_date=execution_date)
        return {
            "buy_count": queryset.filter(action="buy").count(),
            "sell_count": queryset.filter(action="sell").count(),
        }

    def sum_realized_pnl_for_closed_trades(self):
        """Return aggregated realized pnl for completed sell trades."""

        return (
            SimulatedTradeModel._default_manager.filter(
                action="sell",
                realized_pnl__isnull=False,
            ).aggregate(total=Sum("realized_pnl"))["total"]
            or 0
        )

    def list_trade_models_for_account(self, account_id: int, limit: int | None = None) -> list[Any]:
        """Return trade ORM rows for template rendering."""

        queryset = SimulatedTradeModel._default_manager.filter(account_id=account_id)
        if limit is not None:
            queryset = queryset[:limit]
        return list(queryset)

    def get_trade_model_summary_for_account(self, account_id: int, limit: int = 100) -> dict:
        """Return trade rows plus lightweight counts for account trade pages."""

        queryset = SimulatedTradeModel._default_manager.filter(account_id=account_id)
        buy_count = queryset.filter(action="buy").count()
        sell_count = queryset.filter(action="sell").count()
        trades = list(queryset[:limit])
        total_realized_pnl = sum(float(trade.realized_pnl or 0) for trade in trades)
        return {
            "trades": trades,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_realized_pnl": total_realized_pnl,
        }


class DjangoPositionMutationRepository:
    """Coordinate multi-table position mutations inside infrastructure transactions."""

    def create_or_merge_position_with_buy_trade(
        self,
        *,
        account_id: int,
        asset_code: str,
        position_defaults: dict[str, Any],
        trade_payload: dict[str, Any],
    ) -> PositionModel:
        """Persist the updated position row and matching buy trade atomically."""

        with transaction.atomic():
            model, _ = PositionModel._default_manager.update_or_create(
                account_id=account_id,
                asset_code=asset_code,
                defaults=position_defaults,
            )
            SimulatedTradeModel._default_manager.create(**trade_payload)
        return model

    def close_position_with_sell_trade(
        self,
        *,
        account_id: int,
        asset_code: str,
        remaining_position_defaults: dict[str, Any] | None,
        trade: SimulatedTrade,
    ) -> None:
        """Persist the sell trade and remaining position state atomically."""

        with transaction.atomic():
            trade_model = SimulatedTradeMapper.to_model(trade)
            trade_model.id = None
            trade_model.save()

            if remaining_position_defaults is None:
                PositionModel._default_manager.filter(
                    account_id=account_id,
                    asset_code=asset_code,
                ).delete()
                return

            PositionModel._default_manager.update_or_create(
                account_id=account_id,
                asset_code=asset_code,
                defaults=remaining_position_defaults,
            )

    def get_by_date_range(
        self,
        account_id: int,
        start_date: date,
        end_date: date
    ) -> list[SimulatedTrade]:
        """获取日期范围内的交易记录"""
        models = SimulatedTradeModel._default_manager.filter(
            account_id=account_id,
            execution_date__gte=start_date,
            execution_date__lte=end_date
        ).order_by('-execution_date', '-execution_time')
        return [SimulatedTradeMapper.to_entity(m) for m in models]

    def get_by_asset(self, account_id: int, asset_code: str) -> list[SimulatedTrade]:
        """获取特定资产的所有交易记录"""
        models = SimulatedTradeModel._default_manager.filter(
            account_id=account_id,
            asset_code=asset_code
        ).order_by('-execution_date', '-execution_time')
        return [SimulatedTradeMapper.to_entity(m) for m in models]

    def count_by_execution_date(self, account_id: int, execution_date: date) -> int:
        """按执行日期统计交易数。"""
        return SimulatedTradeModel._default_manager.filter(
            account_id=account_id,
            execution_date=execution_date,
        ).count()


class DjangoDailyNetValueRepository:
    """日净值记录仓储。"""

    def upsert_daily_record(self, account_id: int, record_date: date, payload: dict) -> None:
        DailyNetValueModel._default_manager.update_or_create(
            account_id=account_id,
            record_date=record_date,
            defaults=payload,
        )

    def list_daily_records(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict]:
        queryset = DailyNetValueModel._default_manager.filter(account_id=account_id).order_by("record_date")
        if start_date:
            queryset = queryset.filter(record_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(record_date__lte=end_date)
        return list(
            queryset.values(
                "record_date",
                "net_value",
                "cash",
                "market_value",
                "daily_return",
                "cumulative_return",
                "drawdown",
                "total_trades",
                "positions_count",
            )
        )

    def get_latest_record_before(self, account_id: int, current_date: date) -> dict | None:
        return DailyNetValueModel._default_manager.filter(
            account_id=account_id,
            record_date__lt=current_date,
        ).order_by("-record_date").values(
            "record_date",
            "net_value",
            "cumulative_return",
        ).first()

    def get_max_net_value_before(self, account_id: int, before_date: date) -> float | None:
        record = DailyNetValueModel._default_manager.filter(
            account_id=account_id,
            record_date__lt=before_date,
        ).order_by("-net_value").values("net_value").first()
        return float(record["net_value"]) if record else None


class DjangoFeeConfigRepository:
    """费率配置Repository实现"""

    def create_config(
        self,
        config_name: str,
        asset_type: str,
        commission_rate_buy: float = 0.0003,
        commission_rate_sell: float = 0.0003,
        min_commission: float = 5.0,
        stamp_duty_rate: float = 0.001,
        transfer_fee_rate: float = 0.00002,
        min_transfer_fee: float = 0.0,
        slippage_rate: float = 0.001,
        is_default: bool = False,
        is_active: bool = True,
        description: str = "",
    ) -> FeeConfig:
        """创建费率配置并返回实体（兼容旧接口）。"""
        config = FeeConfig(
            config_id=0,
            config_name=config_name,
            asset_type=asset_type,
            commission_rate_buy=commission_rate_buy,
            commission_rate_sell=commission_rate_sell,
            min_commission=min_commission,
            stamp_duty_rate=stamp_duty_rate,
            transfer_fee_rate=transfer_fee_rate,
            min_transfer_fee=min_transfer_fee,
            slippage_rate=slippage_rate,
            is_default=is_default,
            is_active=is_active,
            description=description,
        )
        config_id = self.save(config)
        created = self.get_by_id(config_id)
        if created is None:
            raise ValueError(f"费率配置创建失败: {config_name}")
        return created

    def save(self, config: FeeConfig) -> int:
        """
        保存费率配置

        Returns:
            配置ID
        """
        if config.config_id == 0:
            # 创建新配置
            model = FeeConfigMapper.to_model(config)
            model.id = None
            model.save()
            return model.id
        else:
            # 更新现有配置
            model = FeeConfigModel._default_manager.get(id=config.config_id)
            model.config_name = config.config_name
            model.asset_type = config.asset_type
            model.commission_rate_buy = config.commission_rate_buy
            model.commission_rate_sell = config.commission_rate_sell
            model.min_commission = config.min_commission
            model.stamp_duty_rate = config.stamp_duty_rate
            model.transfer_fee_rate = config.transfer_fee_rate
            model.min_transfer_fee = config.min_transfer_fee
            model.slippage_rate = config.slippage_rate
            model.is_default = config.is_default
            model.is_active = config.is_active
            model.description = config.description
            model.save()
            return config.config_id

    def get_by_id(self, config_id: int) -> FeeConfig | None:
        """根据ID获取费率配置"""
        try:
            model = FeeConfigModel._default_manager.get(id=config_id)
            return FeeConfigMapper.to_entity(model)
        except FeeConfigModel.DoesNotExist:
            return None

    def get_default_config(self, asset_type: str = "all") -> FeeConfig | None:
        """获取默认费率配置"""
        try:
            model = FeeConfigModel._default_manager.filter(
                asset_type__in=[asset_type, "all"],
                is_default=True,
                is_active=True
            ).first()
            if model:
                return FeeConfigMapper.to_entity(model)
            return None
        except FeeConfigModel.DoesNotExist:
            return None

    def get_all_configs(self, asset_type: str = None) -> list[FeeConfig]:
        """获取所有费率配置"""
        if asset_type:
            models = FeeConfigModel._default_manager.filter(
                asset_type=asset_type,
                is_active=True
            )
        else:
            models = FeeConfigModel._default_manager.filter(is_active=True)
        return [FeeConfigMapper.to_entity(m) for m in models]


class DjangoInspectionRepository:
    """日更巡检相关仓储。"""

    def get_or_create_notification_config_model(self, account_id: int) -> tuple[Any, Any] | None:
        """Return account and notification config ORM rows for the settings page."""

        account = SimulatedAccountModel._default_manager.filter(id=account_id).first()
        if not account:
            return None
        config, _ = DailyInspectionNotificationConfigModel._default_manager.get_or_create(account=account)
        return account, config

    def update_notification_config(
        self,
        account_id: int,
        *,
        is_enabled: bool,
        include_owner_email: bool,
        notify_on: str,
        recipient_emails: list[str],
    ) -> Any | None:
        """Persist notification settings for one account."""

        context = self.get_or_create_notification_config_model(account_id)
        if context is None:
            return None
        _, config = context
        config.is_enabled = is_enabled
        config.include_owner_email = include_owner_email
        config.notify_on = notify_on
        config.recipient_emails = sorted(set(recipient_emails))
        config.save()
        return config

    def list_report_payloads(
        self,
        account_id: int,
        *,
        limit: int,
        inspection_date: date | None = None,
    ) -> list[dict]:
        """Return serialized daily inspection reports for API responses."""

        queryset = DailyInspectionReportModel._default_manager.filter(account_id=account_id).order_by(
            "-inspection_date",
            "-updated_at",
        )
        if inspection_date:
            queryset = queryset.filter(inspection_date=inspection_date)

        return [
            {
                "report_id": report.id,
                "account_id": report.account_id,
                "inspection_date": report.inspection_date.isoformat(),
                "status": report.status,
                "macro_regime": report.macro_regime,
                "policy_gear": report.policy_gear,
                "strategy_id": report.strategy_id,
                "position_rule_id": report.position_rule_id,
                "summary": report.summary,
                "checks": report.checks,
            }
            for report in queryset[:limit]
        ]

    def upsert_report(
        self,
        account_id: int,
        inspection_date: date,
        defaults: dict,
    ) -> dict:
        report, _ = DailyInspectionReportModel._default_manager.update_or_create(
            account_id=account_id,
            inspection_date=inspection_date,
            defaults=defaults,
        )
        return {
            "report_id": report.id,
            "status": report.status,
            "macro_regime": report.macro_regime,
            "policy_gear": report.policy_gear,
        }

    def create_rebalance_proposal(self, payload: dict) -> dict:
        proposal = RebalanceProposalModel._default_manager.create(**payload)
        return {
            "proposal_id": proposal.id,
            "account_id": proposal.account_id,
            "inspection_report_id": proposal.inspection_report_id,
            "strategy_id": proposal.strategy_id,
            "source": proposal.source,
            "source_description": proposal.source_description,
            "priority": proposal.priority,
            "status": proposal.status,
            "proposals": list(proposal.proposals or []),
            "summary": dict(proposal.summary or {}),
            "metadata": dict(proposal.metadata or {}),
            "proposed_by": proposal.proposed_by,
        }

    def get_account_notification_context(self, account_id: int) -> dict | None:
        account = SimulatedAccountModel._default_manager.filter(id=account_id).select_related("user").first()
        if not account:
            return None
        config, _ = DailyInspectionNotificationConfigModel._default_manager.get_or_create(account=account)
        return {
            "account_id": account.id,
            "account_name": account.account_name,
            "user_id": account.user.id if account.user else None,
            "user_email": account.user.email if account.user else "",
            "config": {
                "is_enabled": config.is_enabled,
                "include_owner_email": config.include_owner_email,
                "notify_on": config.notify_on,
                "recipient_emails": list(config.recipient_emails or []),
            },
        }

    def get_rebalance_proposal_detail(self, proposal_id: int) -> dict | None:
        proposal = RebalanceProposalModel._default_manager.filter(id=proposal_id).first()
        if not proposal:
            return None
        return {
            "proposal_id": proposal.id,
            "priority": proposal.priority,
            "priority_display": proposal.get_priority_display(),
            "status": proposal.status,
            "status_display": proposal.get_status_display(),
            "proposals": list(proposal.proposals or []),
            "source_description": proposal.source_description,
        }

    def record_notification_history(
        self,
        account_id: int,
        proposal_id: int | None,
        notification_type: str,
        recipients: list[str],
        status: str,
        subject: str,
        body: str,
        recipient_user_id: int | None = None,
    ) -> None:
        for email in recipients:
            NotificationHistoryModel._default_manager.create(
                account_id=account_id,
                rebalance_proposal_id=proposal_id,
                notification_type=notification_type,
                channel="email",
                recipient_user_id=recipient_user_id,
                recipient_email=email,
                subject=subject,
                body=body,
                status=status,
            )

