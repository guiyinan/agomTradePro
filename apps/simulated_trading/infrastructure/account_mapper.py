"""Map simulated account persistence models to and from domain entities."""

from __future__ import annotations

from apps.simulated_trading.domain.entities import (
    AccountCashReconciliationStatus,
    AccountType,
    SimulatedAccount,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


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
            cash_known=model.cash_known,
            cash_reconciliation_status=AccountCashReconciliationStatus(
                model.cash_reconciliation_status
            ),
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
            slippage_rate=model.slippage_rate,
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
            cash_known=entity.cash_known,
            cash_reconciliation_status=(
                entity.cash_reconciliation_status.value
                if entity.cash_reconciliation_status is not None
                else AccountCashReconciliationStatus.UNVERIFIED.value
            ),
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
            slippage_rate=entity.slippage_rate,
        )
