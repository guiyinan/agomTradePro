"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""

from datetime import date
from decimal import Decimal
from math import isfinite
from typing import Any

from django.contrib.auth import get_user_model
from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models import Sum

from apps.simulated_trading.application.ports import AccountPerformanceUpdate
from apps.simulated_trading.domain.entities import (
    AccountCashReconciliationStatus,
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
from core.exceptions import BusinessLogicError

from .account_mapper import SimulatedAccountMapper as SimulatedAccountMapper
from .account_repository_guard import (
    _account_order_scope_changed,
    _lock_account_for_order_guard,
    _require_account_snapshot_matches,
    _require_order_history_deletable,
    _require_reset_fill_history_absent,
)
from .order_reservation_guard import require_no_active_order_reservations
from .repository_helpers import _require_saved_id


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
            with transaction.atomic(using=DEFAULT_DB_ALIAS):
                # Re-read and compare under the same parent lock as the guard.
                model = _lock_account_for_order_guard(account.account_id)
                allowed_fields = frozenset(
                    {
                        "account_name",
                        "is_active",
                        "auto_trading_enabled",
                        "max_position_pct",
                        "max_total_position_pct",
                        "stop_loss_pct",
                        "commission_rate",
                        "slippage_rate",
                    }
                )
                _require_account_snapshot_matches(
                    model,
                    account,
                    ignored_fields=allowed_fields,
                )
                if _account_order_scope_changed(model, account):
                    require_no_active_order_reservations(
                        account_id=account.account_id,
                        using=DEFAULT_DB_ALIAS,
                    )
                model.account_name = account.account_name
                model.is_active = account.is_active
                model.auto_trading_enabled = account.auto_trading_enabled
                model.max_position_pct = account.max_position_pct
                model.max_total_position_pct = account.max_total_position_pct
                model.stop_loss_pct = account.stop_loss_pct
                model.commission_rate = account.commission_rate
                model.slippage_rate = account.slippage_rate
                model.save(
                    using=DEFAULT_DB_ALIAS,
                    update_fields=(
                        "account_name",
                        "is_active",
                        "auto_trading_enabled",
                        "max_position_pct",
                        "max_total_position_pct",
                        "stop_loss_pct",
                        "commission_rate",
                        "slippage_rate",
                        "updated_at",
                    ),
                )
            return int(account.account_id)

    def update_performance_metrics(
        self,
        *,
        account_id: int,
        expected_account: SimulatedAccount,
        metrics: AccountPerformanceUpdate,
    ) -> None:
        """Update performance columns while preserving the locked ledger state."""

        if (
            type(account_id) is not int
            or account_id <= 0
            or type(expected_account) is not SimulatedAccount
            or expected_account.account_id != account_id
            or type(metrics) is not AccountPerformanceUpdate
        ):
            raise BusinessLogicError(
                "账户绩效更新输入无效",
                code="ACCOUNT_PERFORMANCE_UPDATE_INVALID",
            )
        values = (
            metrics.total_return,
            metrics.annual_return,
            metrics.max_drawdown,
            metrics.sharpe_ratio,
            metrics.win_rate,
        )
        if any(type(value) not in (int, float) or not isfinite(value) for value in values) or (
            type(metrics.winning_trades) is not int or metrics.winning_trades < 0
        ):
            raise BusinessLogicError(
                "账户绩效数值无效",
                code="ACCOUNT_PERFORMANCE_UPDATE_INVALID",
            )
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            model = _lock_account_for_order_guard(account_id)
            _require_account_snapshot_matches(model, expected_account)
            model.total_return = float(metrics.total_return)
            model.annual_return = float(metrics.annual_return)
            model.max_drawdown = float(metrics.max_drawdown)
            model.sharpe_ratio = float(metrics.sharpe_ratio)
            model.win_rate = float(metrics.win_rate)
            model.winning_trades = metrics.winning_trades
            model.save(
                using=DEFAULT_DB_ALIAS,
                update_fields=(
                    "total_return",
                    "annual_return",
                    "max_drawdown",
                    "sharpe_ratio",
                    "win_rate",
                    "winning_trades",
                    "updated_at",
                ),
            )

    def deactivate_if_inactive_since(self, account_id: int, cutoff_date: date) -> bool:
        """Disable an inactive account under its lock without replacing ledger values."""

        if type(account_id) is not int or account_id <= 0 or type(cutoff_date) is not date:
            raise BusinessLogicError(
                "账户停用检查输入无效",
                code="INACTIVE_ACCOUNT_CHECK_INVALID",
            )
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            model = (
                SimulatedAccountModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(pk=account_id, is_active=True, auto_trading_enabled=True)
                .first()
            )
            if (
                model is None
                or model.last_trade_date is None
                or model.last_trade_date >= cutoff_date
            ):
                return False
            require_no_active_order_reservations(
                account_id=account_id,
                using=DEFAULT_DB_ALIAS,
            )
            model.is_active = False
            model.auto_trading_enabled = False
            model.save(
                using=DEFAULT_DB_ALIAS,
                update_fields=("is_active", "auto_trading_enabled", "updated_at"),
            )
            return True

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

    def get_owner_id(self, *, account_id: int) -> int | None:
        """Read the owner of an active simulated account; the writer rechecks under lock."""
        if type(account_id) is not int or account_id <= 0:
            return None
        owner_id = (
            SimulatedAccountModel._default_manager.filter(
                pk=account_id, account_type="simulated", is_active=True
            )
            .values_list("user_id", flat=True)
            .first()
        )
        return owner_id if type(owner_id) is int and owner_id > 0 else None

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

        cash_known = account_type == AccountType.SIMULATED.value
        cash_status = (
            AccountCashReconciliationStatus.SIMULATED_LEDGER.value
            if cash_known
            else AccountCashReconciliationStatus.UNVERIFIED.value
        )
        return SimulatedAccountModel._default_manager.create(
            user=user,
            account_name=account_name,
            account_type=account_type,
            initial_capital=initial_capital,
            current_cash=initial_capital,
            cash_known=cash_known,
            cash_reconciliation_status=cash_status,
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
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            model = (
                SimulatedAccountModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(pk=account_id)
                .first()
            )
            if model is None:
                return False
            require_no_active_order_reservations(
                account_id=account_id,
                using=DEFAULT_DB_ALIAS,
            )
            _require_order_history_deletable(account_id)
            model.delete(using=DEFAULT_DB_ALIAS)
            return True

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

        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            account = (
                SimulatedAccountModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(pk=account_id)
                .first()
            )
            if account is None:
                return None
            require_no_active_order_reservations(
                account_id=account_id,
                using=DEFAULT_DB_ALIAS,
            )
            _require_order_history_deletable(account_id)
            summary = {
                "account_id": account.id,
                "account_name": account.account_name,
                "deleted_positions": PositionModel._default_manager.using(DEFAULT_DB_ALIAS)
                .filter(account=account)
                .count(),
                "deleted_trades": SimulatedTradeModel._default_manager.using(DEFAULT_DB_ALIAS)
                .filter(account=account)
                .count(),
                "deleted_reports": DailyInspectionReportModel._default_manager.using(
                    DEFAULT_DB_ALIAS
                )
                .filter(account=account)
                .count(),
            }
            account.delete(using=DEFAULT_DB_ALIAS)
            return summary

    def reset_account_with_summary(
        self,
        account_id: int,
        new_initial_capital: Decimal | None = None,
    ) -> dict[str, Any] | None:
        """Reset one account ledger atomically while preserving its identity and settings."""

        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            account = (
                SimulatedAccountModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(id=account_id)
                .first()
            )
            if account is None:
                return None
            require_no_active_order_reservations(
                account_id=account_id,
                using=DEFAULT_DB_ALIAS,
            )
            _require_reset_fill_history_absent(account_id)

            initial_capital = Decimal(new_initial_capital or account.initial_capital)
            deleted_positions, _ = (
                PositionModel._default_manager.using(DEFAULT_DB_ALIAS)
                .filter(account_id=account_id)
                .delete()
            )
            deleted_trades, _ = (
                SimulatedTradeModel._default_manager.using(DEFAULT_DB_ALIAS)
                .filter(account_id=account_id)
                .delete()
            )
            deleted_net_values, _ = (
                DailyNetValueModel._default_manager.using(DEFAULT_DB_ALIAS)
                .filter(account_id=account_id)
                .delete()
            )
            deleted_inspections, _ = (
                DailyInspectionReportModel._default_manager.using(DEFAULT_DB_ALIAS)
                .filter(account_id=account_id)
                .delete()
            )
            deleted_proposals, _ = (
                RebalanceProposalModel._default_manager.using(DEFAULT_DB_ALIAS)
                .filter(account_id=account_id)
                .delete()
            )

            account.initial_capital = initial_capital
            account.current_cash = initial_capital
            account.cash_known = account.account_type == AccountType.SIMULATED.value
            account.cash_reconciliation_status = (
                AccountCashReconciliationStatus.SIMULATED_LEDGER.value
                if account.cash_known
                else AccountCashReconciliationStatus.UNVERIFIED.value
            )
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
                using=DEFAULT_DB_ALIAS,
                update_fields=[
                    "initial_capital",
                    "current_cash",
                    "cash_known",
                    "cash_reconciliation_status",
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
                ],
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
