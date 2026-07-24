"""Portfolio access, observer grant, and trading-cost repository operations."""

import logging
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from apps.account.application.simulated_trading_gateway import (
    get_unified_account_id_for_portfolio,
)
from apps.account.infrastructure.models import (
    AssetMetadataModel,
    CapitalFlowModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
    TradingCostConfigModel,
    TransactionModel,
)

logger = logging.getLogger(__name__)


def _validate_trading_cost_values(
    *,
    commission_rate: float,
    min_commission: float,
    stamp_duty_rate: float,
    transfer_fee_rate: float,
) -> None:
    """Validate configured fees at the persistence boundary."""

    values = {
        "commission_rate": (commission_rate, 0.01),
        "stamp_duty_rate": (stamp_duty_rate, 0.01),
        "transfer_fee_rate": (transfer_fee_rate, 0.001),
    }
    for field_name, (value, maximum) in values.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
            or value > maximum
        ):
            raise ValueError(f"{field_name} 必须是 0 到 {maximum} 之间的有限数")
    if (
        isinstance(min_commission, bool)
        or not isinstance(min_commission, (int, float))
        or not math.isfinite(float(min_commission))
        or min_commission < 0
    ):
        raise ValueError("min_commission 必须是非负有限数")


class AccountInterfacePortfolioRepositoryMixin:
    """Persist portfolio access, observer grants, and related account data."""

    def get_asset_metadata_queryset(self) -> Any:
        """Return the asset metadata queryset for API listing/retrieval."""

        return AssetMetadataModel._default_manager.order_by("asset_code", "id")

    def get_user_transaction_queryset(self, user_id: int) -> Any:
        """Return transactions scoped to portfolios owned by the user."""

        return TransactionModel._default_manager.filter(portfolio__user_id=user_id).select_related(
            "portfolio", "position"
        )

    def get_user_capital_flow_queryset(self, user_id: int) -> Any:
        """Return capital flows scoped to portfolios owned by the user."""

        return CapitalFlowModel._default_manager.filter(portfolio__user_id=user_id).select_related(
            "portfolio"
        )

    def get_user_portfolio(self, *, user_id: int, portfolio_id: int) -> Any:
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
                Q(username__icontains=query) | Q(account_profile__display_name__icontains=query)
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

    def get_trading_cost_config_queryset(self, user_id: int) -> Any:
        """Return trading cost configs for portfolios owned by the user."""

        return (
            TradingCostConfigModel._default_manager.filter(portfolio__user_id=user_id)
            .select_related("portfolio")
            .order_by("portfolio_id", "id")
        )

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
    ) -> TradingCostConfigModel:
        """Create or update one trading cost configuration for the actor's portfolio."""

        portfolio = PortfolioModel._default_manager.filter(
            id=portfolio_id,
            user_id=actor_user_id,
        ).first()
        if portfolio is None:
            raise PermissionError("无权为此投资组合配置费率")
        _validate_trading_cost_values(
            commission_rate=commission_rate,
            min_commission=min_commission,
            stamp_duty_rate=stamp_duty_rate,
            transfer_fee_rate=transfer_fee_rate,
        )

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
    ) -> Any:
        """Return observer grants scoped to the current owner or observer view."""

        filter_key = "observer_user_id_id" if as_observer else "owner_user_id_id"
        queryset = PortfolioObserverGrantModel._default_manager.filter(
            **{filter_key: user_id}
        ).select_related("observer_user_id", "owner_user_id", "revoked_by")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset.order_by("-created_at")

    def get_observer_grant_by_id(self, grant_id: Any) -> Any:
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

        portfolio = PortfolioModel._default_manager.filter(
            user_id=owner_user_id, is_active=True
        ).first()
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
                    "avg_cost": float(position.avg_cost or Decimal("0")),
                    "current_price": float(position.current_price or Decimal("0")),
                    "market_value": float(position.market_value or Decimal("0")),
                    "unrealized_pnl": float(position.unrealized_pnl or Decimal("0")),
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

    def update_observer_grant(self, *, grant_id: Any, expires_at: Any) -> Any:
        """Persist a grant expiry update and return the refreshed model."""

        grant = self.get_observer_grant_by_id(grant_id)
        if grant is None:
            raise PortfolioObserverGrantModel.DoesNotExist
        grant.expires_at = expires_at
        grant.save(update_fields=["expires_at"])
        return grant

    def revoke_observer_grant(
        self,
        *,
        grant_id: Any,
        revoked_by_user_id: int,
    ) -> Any:
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

        _validate_trading_cost_values(
            commission_rate=commission_rate,
            min_commission=min_commission,
            stamp_duty_rate=stamp_duty_rate,
            transfer_fee_rate=transfer_fee_rate,
        )

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

    def has_active_observer_access(self, *, owner_user_id: int, observer_user_id: int) -> bool:
        """Return whether the observer currently has a valid read grant."""

        now = timezone.now()
        return (
            PortfolioObserverGrantModel._default_manager.filter(
                owner_user_id=owner_user_id,
                observer_user_id=observer_user_id,
                status="active",
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .exists()
        )

    def get_accessible_portfolios_queryset(self, user_id: int) -> Any:
        """Return portfolios owned by or shared with the given user."""

        now = timezone.now()
        active_grants = (
            PortfolioObserverGrantModel._default_manager.filter(
                observer_user_id=user_id,
                status="active",
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .values_list("owner_user_id", flat=True)
        )
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

    def find_user_by_username(self, username: str) -> User | None:
        """Return one user by username when available."""

        return User._default_manager.filter(username=username).first()

    def find_user_by_id(self, user_id: int) -> User | None:
        """Return one user by id when available."""

        return User._default_manager.filter(id=user_id).first()

    def get_unified_account_id_for_portfolio(self, portfolio_id: int) -> int | None:
        """Return the unified account id mapped from one legacy portfolio id."""
        return get_unified_account_id_for_portfolio(portfolio_id)

    def get_active_observer_grant(
        self,
        *,
        owner_user_id: int,
        observer_user_id: int,
    ) -> Any:
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
        expires_at: datetime | None,
    ) -> Any:
        """Create one observer grant record."""

        return PortfolioObserverGrantModel._default_manager.create(
            owner_user_id_id=owner_user_id,
            observer_user_id_id=observer_user_id,
            created_by_id=created_by_user_id,
            expires_at=expires_at,
        )
