"""Repository for stop-loss configuration and observation records."""

import math
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Any

from django.db import router, transaction
from django.utils import timezone

from apps.account.domain.interfaces import StopLossPeakObservation
from apps.account.infrastructure.models import (
    PortfolioModel,
    PositionModel,
    StopLossConfigModel,
    StopLossTriggerModel,
)


def _has_exact_stop_price_precision(value: Decimal) -> bool:
    """Return whether a price fits the persisted decimal(20, 4) without rounding."""

    if not isinstance(value, Decimal):
        return False
    if not value.is_finite() or value <= 0:
        return False
    try:
        with localcontext() as context:
            context.prec = max(context.prec, 32)
            normalized = value.quantize(Decimal("0.0001"))
    except ArithmeticError:
        return False
    return normalized == value and len(normalized.as_tuple().digits) <= 20


def _is_aware(value: datetime | None) -> bool:
    """Return whether an optional observation timestamp is timezone-aware."""

    return isinstance(value, datetime) and timezone.is_aware(value)


class StopLossRepository:
    """Read and update stop-loss rules without coupling callers to ORM models."""

    def get_active_stop_loss_configs(self, user_id: int | None = None) -> list[dict[str, Any]]:
        """Return active rules with the position and owner snapshot needed for evaluation."""

        queryset = StopLossConfigModel._default_manager.filter(
            status="active",
            position__is_closed=False,
        )
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
                "updated_at": config.updated_at,
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
        """Return one position's stop-loss rule, if it exists."""

        try:
            config = StopLossConfigModel._default_manager.get(position_id=position_id)
        except StopLossConfigModel.DoesNotExist:
            return None
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

    def create_stop_loss_config(
        self,
        position_id: int,
        stop_loss_type: str,
        stop_loss_pct: float,
        trailing_stop_pct: float | None = None,
        max_holding_days: int | None = None,
        highest_price: Decimal | None = None,
    ) -> dict[str, Any]:
        """Create an active stop-loss rule for a position."""

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
        """Update stop-loss configuration through the existing general-purpose path."""

        try:
            config = StopLossConfigModel._default_manager.get(id=config_id)
        except StopLossConfigModel.DoesNotExist:
            return False
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

    def record_trailing_stop_peak_observation(
        self,
        observation: StopLossPeakObservation,
    ) -> bool:
        """Lock the owner/position/rule in order and CAS one exact peak observation."""

        if not self._is_valid_peak_observation(observation):
            return False
        using = router.db_for_write(StopLossConfigModel)
        with transaction.atomic(using=using):
            try:
                portfolio = (
                    PortfolioModel._base_manager.using(using)
                    .select_for_update()
                    .only("id", "user_id")
                    .get(pk=observation.portfolio_id)
                )
            except PortfolioModel.DoesNotExist:
                return False
            if portfolio.user_id != observation.owner_user_id:
                return False

            try:
                position = (
                    PositionModel._base_manager.using(using)
                    .select_for_update()
                    .only(
                        "id",
                        "portfolio_id",
                        "asset_code",
                        "shares",
                        "avg_cost",
                        "is_closed",
                    )
                    .get(pk=observation.position_id)
                )
            except PositionModel.DoesNotExist:
                return False
            if (
                position.portfolio_id != portfolio.pk
                or position.asset_code != observation.asset_code
                or position.shares != observation.position_shares
                or position.avg_cost != observation.average_cost
                or position.is_closed
            ):
                return False

            try:
                config = (
                    StopLossConfigModel._base_manager.using(using)
                    .select_for_update()
                    .get(pk=observation.config_id, position_id=position.pk)
                )
            except StopLossConfigModel.DoesNotExist:
                return False
            if (
                config.status != "active"
                or config.stop_loss_type != "trailing"
                or config.stop_loss_pct != observation.stop_loss_pct
                or config.trailing_stop_pct != observation.trailing_stop_pct
                or config.max_holding_days != observation.max_holding_days
                or config.updated_at != observation.config_updated_at
                or config.highest_price != observation.expected_highest_price
                or config.highest_price_updated_at != observation.expected_highest_price_updated_at
            ):
                return False

            previous_peak = config.highest_price or position.avg_cost
            if observation.exact_price <= previous_peak:
                return False
            previous_time = config.highest_price_updated_at
            if previous_time is not None and observation.observed_at < previous_time:
                return False
            updated_at = timezone.now()
            updated_count = (
                StopLossConfigModel._base_manager.using(using)
                .filter(
                    pk=config.pk,
                    position_id=position.pk,
                    status="active",
                    stop_loss_type="trailing",
                    stop_loss_pct=observation.stop_loss_pct,
                    trailing_stop_pct=observation.trailing_stop_pct,
                    max_holding_days=observation.max_holding_days,
                    updated_at=observation.config_updated_at,
                    highest_price=observation.expected_highest_price,
                    highest_price_updated_at=observation.expected_highest_price_updated_at,
                )
                .update(
                    highest_price=observation.exact_price,
                    highest_price_updated_at=observation.observed_at,
                    updated_at=updated_at,
                )
            )
        return updated_count == 1

    @staticmethod
    def _is_valid_peak_observation(observation: StopLossPeakObservation) -> bool:
        """Reject malformed, naive, or unrepresentable peak observations before locking."""

        if type(observation) is not StopLossPeakObservation:
            return False
        return (
            type(observation.config_id) is int
            and observation.config_id > 0
            and type(observation.position_id) is int
            and observation.position_id > 0
            and type(observation.portfolio_id) is int
            and observation.portfolio_id > 0
            and type(observation.owner_user_id) is int
            and observation.owner_user_id > 0
            and isinstance(observation.asset_code, str)
            and bool(observation.asset_code.strip())
            and type(observation.position_shares) is float
            and math.isfinite(observation.position_shares)
            and observation.position_shares > 0
            and isinstance(observation.average_cost, Decimal)
            and observation.average_cost.is_finite()
            and observation.average_cost > 0
            and _has_exact_stop_price_precision(observation.average_cost)
            and type(observation.stop_loss_pct) is float
            and math.isfinite(observation.stop_loss_pct)
            and 0 <= observation.stop_loss_pct <= 1
            and (
                observation.trailing_stop_pct is None
                or (
                    type(observation.trailing_stop_pct) is float
                    and math.isfinite(observation.trailing_stop_pct)
                    and 0 <= observation.trailing_stop_pct <= 1
                )
            )
            and (
                observation.max_holding_days is None
                or (type(observation.max_holding_days) is int and observation.max_holding_days > 0)
            )
            and _is_aware(observation.config_updated_at)
            and (
                observation.expected_highest_price is None
                or _has_exact_stop_price_precision(observation.expected_highest_price)
            )
            and (
                observation.expected_highest_price_updated_at is None
                or _is_aware(observation.expected_highest_price_updated_at)
            )
            and _has_exact_stop_price_precision(observation.exact_price)
            and _is_aware(observation.observed_at)
        )

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
        """Persist a stop-loss trigger record without altering a position ledger."""

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
