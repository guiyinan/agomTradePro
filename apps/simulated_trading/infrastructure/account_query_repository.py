"""Read-only owner of simulated-account repository queries."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Sum

from apps.simulated_trading.domain.entities import SimulatedAccount
from apps.simulated_trading.infrastructure.account_mapper import SimulatedAccountMapper
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


class SimulatedAccountQueryRepositoryMixin:
    """Provide account reads while preserving the established repository API."""

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
