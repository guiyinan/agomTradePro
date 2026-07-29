"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""

from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum

from apps.simulated_trading.domain.entities import (
    AccountType,
    SimulatedAccount,
)
from apps.simulated_trading.infrastructure.models import (
    DailyInspectionReportModel,
    DailyNetValueModel,
    PositionModel,
    RebalanceProposalModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)

from .repository_helpers import _require_saved_id


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


class DjangoSimulatedAccountRepository:
    """模拟账户Repository实现"""

    def save(self, account: SimulatedAccount, user_id: int | None = None) -> int:
        """
        保存账户(创建或更新)

        Returns:
            账户ID
        """
        if account.account_id == 0:
            # 创建新账户
            model = SimulatedAccountMapper.to_model(account)
            model.id = None  # 确保是新记录
            if user_id is not None:
                user_model = get_user_model()
                model.user = user_model._default_manager.get(id=user_id)
            model.save()
            return _require_saved_id(model.id, "simulated account")
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
            return int(account.account_id)

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

    def get_by_name(self, account_name: str, user_id: int | None = None) -> SimulatedAccount | None:
        """Return an account by name, scoped to the owner when available."""
        queryset = SimulatedAccountModel._default_manager.filter(account_name=account_name)
        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)
        model = queryset.order_by("id").first()
        return SimulatedAccountMapper.to_entity(model) if model is not None else None

    def get_active_accounts(self) -> list[SimulatedAccount]:
        """获取所有活跃的自动交易账户"""
        models = SimulatedAccountModel._default_manager.filter(
            is_active=True, auto_trading_enabled=True
        )
        return [SimulatedAccountMapper.to_entity(m) for m in models]

    def get_all_accounts(self) -> list[SimulatedAccount]:
        """获取所有账户"""
        models = SimulatedAccountModel._default_manager.all()
        return [SimulatedAccountMapper.to_entity(m) for m in models]

    def list_active_account_targets(self) -> list[dict[str, Any]]:
        """Return active account/user ids for cross-app scheduled jobs."""

        rows = (
            SimulatedAccountModel._default_manager.filter(is_active=True)
            .only("id", "user_id", "account_name", "account_type")
            .order_by("user_id", "id")
        )
        return [
            {
                "account_id": int(row.id),
                "user_id": row.user_id,
                "account_name": row.account_name,
                "account_type": row.account_type,
            }
            for row in rows
        ]

    def count_active_account_models(self) -> int:
        """Return the number of active account ORM rows."""

        return int(SimulatedAccountModel._default_manager.filter(is_active=True).count())

    def sum_active_total_value(self) -> Decimal:
        """Return the aggregate total value across active accounts."""

        total = SimulatedAccountModel._default_manager.filter(is_active=True).aggregate(
            total=Sum("total_value")
        )
        return Decimal(str(total["total"] or 0))

    def get_by_user(self, user_id: int) -> list[SimulatedAccount]:
        """
        ⭐ 新增：根据用户ID获取所有投资组合

        Args:
            user_id: 用户ID

        Returns:
            用户的所有投资组合
        """
        models = SimulatedAccountModel._default_manager.filter(user_id=user_id).order_by(
            "-created_at"
        )
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
            )
            .select_related("rotation_config")
            .order_by("account_type", "account_name")
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
            user_id=user_id, account_type=account_type
        ).order_by("-created_at")
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
        return bool(
            SimulatedAccountModel._default_manager.filter(
                id=account_id,
                user_id=user_id,
            ).exists()
        )

    def delete_account_with_summary(self, account_id: int) -> dict[str, Any] | None:
        """Delete an account row and return small cascade counts for UI feedback."""

        account = self.get_account_model_by_id(account_id)
        if not account:
            return None

        summary = {
            "account_id": account.id,
            "account_name": account.account_name,
            "deleted_positions": PositionModel._default_manager.filter(account=account).count(),
            "deleted_trades": SimulatedTradeModel._default_manager.filter(account=account).count(),
            "deleted_reports": DailyInspectionReportModel._default_manager.filter(
                account=account
            ).count(),
        }
        account.delete()
        return summary

    def reset_account_with_summary(
        self,
        account_id: int,
        new_initial_capital: Decimal | None = None,
    ) -> dict[str, Any] | None:
        """Reset one account ledger atomically while preserving its identity and settings."""

        with transaction.atomic():
            account = (
                SimulatedAccountModel._default_manager.select_for_update()
                .filter(id=account_id)
                .first()
            )
            if account is None:
                return None

            initial_capital = Decimal(new_initial_capital or account.initial_capital)
            deleted_positions, _ = PositionModel._default_manager.filter(
                account_id=account_id
            ).delete()
            deleted_trades, _ = SimulatedTradeModel._default_manager.filter(
                account_id=account_id
            ).delete()
            deleted_net_values, _ = DailyNetValueModel._default_manager.filter(
                account_id=account_id
            ).delete()
            deleted_inspections, _ = DailyInspectionReportModel._default_manager.filter(
                account_id=account_id
            ).delete()
            deleted_proposals, _ = RebalanceProposalModel._default_manager.filter(
                account_id=account_id
            ).delete()

            account.initial_capital = initial_capital
            account.current_cash = initial_capital
            account.current_market_value = Decimal("0")
            account.total_value = initial_capital
            account.total_return = 0.0
            account.annual_return = 0.0
            account.max_drawdown = 0.0
            account.sharpe_ratio = 0.0
            account.win_rate = 0.0
            account.total_trades = 0
            account.winning_trades = 0
            account.last_trade_date = None
            account.save(
                update_fields=[
                    "initial_capital",
                    "current_cash",
                    "current_market_value",
                    "total_value",
                    "total_return",
                    "annual_return",
                    "max_drawdown",
                    "sharpe_ratio",
                    "win_rate",
                    "total_trades",
                    "winning_trades",
                    "last_trade_date",
                    "updated_at",
                ]
            )

        return {
            "account_id": account_id,
            "account_name": account.account_name,
            "initial_capital": str(initial_capital),
            "deleted_positions": deleted_positions,
            "deleted_trades": deleted_trades,
            "deleted_net_values": deleted_net_values,
            "deleted_inspections": deleted_inspections,
            "deleted_proposals": deleted_proposals,
        }
