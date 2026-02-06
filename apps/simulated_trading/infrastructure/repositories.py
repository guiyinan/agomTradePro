"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""
from typing import List, Optional
from datetime import date

from django.db import models
from django.db.models import Q, F, Sum, Count, Avg, Max, Min

from apps.simulated_trading.domain.entities import (
    SimulatedAccount,
    Position,
    SimulatedTrade,
    FeeConfig,
    AccountType,
    TradeAction,
    OrderStatus
)
from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel,
    PositionModel,
    SimulatedTradeModel,
    FeeConfigModel
)


class SimulatedAccountMapper:
    """模拟账户Mapper - Domain实体 ↔ ORM模型"""

    @staticmethod
    def to_entity(model: SimulatedAccountModel) -> SimulatedAccount:
        """ORM模型 → Domain实体"""
        return SimulatedAccount(
            account_id=model.id,
            account_name=model.account_name,
            account_type=AccountType(model.account_type),
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
            invalidation_description=entity.invalidation_description,
            is_invalidated=entity.is_invalidated,
            invalidation_reason=entity.invalidation_reason,
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

    def get_by_id(self, account_id: int) -> Optional[SimulatedAccount]:
        """根据ID获取账户"""
        try:
            model = SimulatedAccountModel._default_manager.get(id=account_id)
            return SimulatedAccountMapper.to_entity(model)
        except SimulatedAccountModel.DoesNotExist:
            return None

    def get_by_name(self, account_name: str) -> Optional[SimulatedAccount]:
        """根据名称获取账户"""
        try:
            model = SimulatedAccountModel._default_manager.get(account_name=account_name)
            return SimulatedAccountMapper.to_entity(model)
        except SimulatedAccountModel.DoesNotExist:
            return None

    def get_active_accounts(self) -> List[SimulatedAccount]:
        """获取所有活跃的自动交易账户"""
        models = SimulatedAccountModel._default_manager.filter(
            is_active=True,
            auto_trading_enabled=True
        )
        return [SimulatedAccountMapper.to_entity(m) for m in models]

    def get_all_accounts(self) -> List[SimulatedAccount]:
        """获取所有账户"""
        models = SimulatedAccountModel._default_manager.all()
        return [SimulatedAccountMapper.to_entity(m) for m in models]

    def get_by_user(self, user_id: int) -> List[SimulatedAccount]:
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

    def get_by_user_and_type(self, user_id: int, account_type: str) -> List[SimulatedAccount]:
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


class DjangoPositionRepository:
    """持仓Repository实现"""

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

    def get_by_account(self, account_id: int) -> List[Position]:
        """获取账户的所有持仓"""
        models = PositionModel._default_manager.filter(account_id=account_id)
        return [PositionMapper.to_entity(m) for m in models]

    def get_position(self, account_id: int, asset_code: str) -> Optional[Position]:
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


class DjangoTradeRepository:
    """交易记录Repository实现"""

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

    def get_by_account(self, account_id: int) -> List[SimulatedTrade]:
        """获取账户的所有交易记录"""
        models = SimulatedTradeModel._default_manager.filter(
            account_id=account_id
        ).order_by('-execution_date', '-execution_time')
        return [SimulatedTradeMapper.to_entity(m) for m in models]

    def get_by_date_range(
        self,
        account_id: int,
        start_date: date,
        end_date: date
    ) -> List[SimulatedTrade]:
        """获取日期范围内的交易记录"""
        models = SimulatedTradeModel._default_manager.filter(
            account_id=account_id,
            execution_date__gte=start_date,
            execution_date__lte=end_date
        ).order_by('-execution_date', '-execution_time')
        return [SimulatedTradeMapper.to_entity(m) for m in models]

    def get_by_asset(self, account_id: int, asset_code: str) -> List[SimulatedTrade]:
        """获取特定资产的所有交易记录"""
        models = SimulatedTradeModel._default_manager.filter(
            account_id=account_id,
            asset_code=asset_code
        ).order_by('-execution_date', '-execution_time')
        return [SimulatedTradeMapper.to_entity(m) for m in models]


class DjangoFeeConfigRepository:
    """费率配置Repository实现"""

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

    def get_by_id(self, config_id: int) -> Optional[FeeConfig]:
        """根据ID获取费率配置"""
        try:
            model = FeeConfigModel._default_manager.get(id=config_id)
            return FeeConfigMapper.to_entity(model)
        except FeeConfigModel.DoesNotExist:
            return None

    def get_default_config(self, asset_type: str = "all") -> Optional[FeeConfig]:
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

    def get_all_configs(self, asset_type: str = None) -> List[FeeConfig]:
        """获取所有费率配置"""
        if asset_type:
            models = FeeConfigModel._default_manager.filter(
                asset_type=asset_type,
                is_active=True
            )
        else:
            models = FeeConfigModel._default_manager.filter(is_active=True)
        return [FeeConfigMapper.to_entity(m) for m in models]

