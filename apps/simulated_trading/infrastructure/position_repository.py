"""模拟盘持仓查询与兼容读写仓储。"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import DEFAULT_DB_ALIAS, transaction

from apps.simulated_trading.domain.entities import Position
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
)

from .order_reservation_guard import require_no_active_order_reservations
from .position_cost_basis_knowledge import (
    _COST_BASIS_ECONOMIC_FIELDS as _COST_BASIS_ECONOMIC_FIELDS,
)
from .position_cost_basis_knowledge import (
    _cost_basis_economics_changed,
    _merge_cost_basis_knowledge,
)
from .position_mapper import PositionMapper
from .position_mutation_repository import (
    DjangoPositionMutationRepository as DjangoPositionMutationRepository,
)
from .position_repository_guard import (
    _lock_account_for_order_guard,
    _position_order_resources_changed,
    _validate_position_record_defaults,
    require_no_retained_v4_fill_history,
)
from .repository_helpers import _require_saved_id


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

        return int(PositionModel._default_manager.count())

    def update_position_prices(
        self,
        price_by_code: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Update open positions and account totals from latest prices."""

        if not price_by_code:
            return []

        updates: list[dict[str, Any]] = []
        positions = PositionModel._default_manager.select_related("account").filter(
            asset_code__in=price_by_code.keys(),
            quantity__gt=0,
        )

        for position in positions:
            if not position.valuation_known:
                # A bare numeric price has no source qualification for this holding.
                continue
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

    def _update_account_value(self, account: SimulatedAccountModel) -> None:
        """Recalculate account totals after position price changes."""

        positions = PositionModel._default_manager.filter(account=account)
        if positions.filter(valuation_known=False, quantity__gt=0).exists():
            # Preserve the old cache; public reads publish incomplete valuation.
            return
        market_value = sum(
            (position.market_value for position in positions),
            start=Decimal("0"),
        )
        total_value = market_value + account.current_cash
        total_return = (
            float(
                ((total_value - account.initial_capital) / account.initial_capital) * Decimal("100")
            )
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
        defaults: dict[str, Any],
    ) -> PositionModel:
        """Create or update a row without upgrading either knowledge flag."""
        _validate_position_record_defaults(defaults)
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            _lock_account_for_order_guard(account_id)
            current = (
                PositionModel._default_manager.using(DEFAULT_DB_ALIAS)
                .filter(account_id=account_id, asset_code=asset_code)
                .first()
            )
            if _position_order_resources_changed(current, defaults):
                require_no_active_order_reservations(
                    account_id=account_id,
                    using=DEFAULT_DB_ALIAS,
                )
                require_no_retained_v4_fill_history(
                    account_id=account_id,
                    asset_code=asset_code,
                    using=DEFAULT_DB_ALIAS,
                )
            model, created = (
                PositionModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .get_or_create(
                    account_id=account_id,
                    asset_code=asset_code,
                    defaults=defaults,
                )
            )
            if created:
                return model
            persisted_defaults = dict(defaults)
            persisted_defaults["available_quantity_known"] = (
                model.available_quantity_known is True
                and defaults.get("available_quantity_known", True) is True
            )
            persisted_defaults["first_buy_date_known"] = (
                model.first_buy_date_known is True
                and defaults.get("first_buy_date_known", True) is True
            )
            persisted_defaults["valuation_known"] = (
                model.valuation_known is True and defaults.get("valuation_known", True) is True
            )
            persisted_defaults["cost_basis_known"] = _merge_cost_basis_knowledge(
                model.cost_basis_known,
                defaults.get("cost_basis_known"),
                economics_changed=_cost_basis_economics_changed(model, defaults),
            )
            for field_name, value in persisted_defaults.items():
                setattr(model, field_name, value)
            model.save(using=DEFAULT_DB_ALIAS)
            return model

    def save(self, position: Position) -> int:
        """
        Persist a position while preserving any previously unknown flags.

        Returns the stored position ID.
        """
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            _lock_account_for_order_guard(position.account_id)
            incoming = {
                "asset_type": position.asset_type,
                "quantity": position.quantity,
                "available_quantity": position.available_quantity,
                "available_quantity_known": position.available_quantity_known,
                "avg_cost": position.avg_cost,
                "total_cost": position.total_cost,
                "cost_basis_known": position.cost_basis_known,
                "first_buy_date": position.first_buy_date,
                "first_buy_date_known": position.first_buy_date_known,
            }
            current = (
                PositionModel._default_manager.using(DEFAULT_DB_ALIAS)
                .filter(account_id=position.account_id, asset_code=position.asset_code)
                .first()
            )
            if _position_order_resources_changed(current, incoming):
                require_no_active_order_reservations(
                    account_id=position.account_id,
                    using=DEFAULT_DB_ALIAS,
                )
                require_no_retained_v4_fill_history(
                    account_id=position.account_id,
                    asset_code=position.asset_code,
                    using=DEFAULT_DB_ALIAS,
                )
            model = (
                PositionModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(account_id=position.account_id, asset_code=position.asset_code)
                .first()
            )
            if model is None:
                model = PositionMapper.to_model(position)
                model.id = None
                model.save(using=DEFAULT_DB_ALIAS)
                return _require_saved_id(model.id, "position")

            economics_changed = _cost_basis_economics_changed(
                model,
                {
                    "quantity": position.quantity,
                    "avg_cost": position.avg_cost,
                    "total_cost": position.total_cost,
                },
            )
            model.quantity = position.quantity
            model.available_quantity = position.available_quantity
            model.available_quantity_known = (
                model.available_quantity_known is True and position.available_quantity_known is True
            )
            model.first_buy_date_known = (
                model.first_buy_date_known is True and position.first_buy_date_known is True
            )
            model.valuation_known = (
                model.valuation_known is True and position.valuation_known is True
            )
            model.cost_basis_known = _merge_cost_basis_knowledge(
                model.cost_basis_known,
                position.cost_basis_known,
                economics_changed=economics_changed,
            )
            model.avg_cost = position.avg_cost
            model.total_cost = position.total_cost
            model.current_price = position.current_price
            model.market_value = position.market_value
            model.unrealized_pnl = position.unrealized_pnl
            model.unrealized_pnl_pct = position.unrealized_pnl_pct
            model.first_buy_date = position.first_buy_date
            model.last_update_date = position.last_update_date
            model.save(using=DEFAULT_DB_ALIAS)
            return _require_saved_id(model.id, "position")

    def get_by_account(self, account_id: int) -> list[Position]:
        """获取账户的所有持仓"""
        models = PositionModel._default_manager.filter(account_id=account_id)
        return [PositionMapper.to_entity(m) for m in models]

    def list_position_models_for_account(
        self, account_id: int, limit: int | None = None
    ) -> list[Any]:
        """Return position ORM rows for template rendering."""

        queryset = PositionModel._default_manager.filter(account_id=account_id)
        if limit is not None:
            queryset = queryset[:limit]
        return list(queryset)

    def get_position_snapshots(self, account_id: int) -> list[dict[str, Any]]:
        """Return holdings while keeping unknown valuation unavailable to decisions."""
        rows = PositionModel._default_manager.filter(account_id=account_id).values(
            "asset_code",
            "asset_name",
            "quantity",
            "avg_cost",
            "current_price",
            "market_value",
            "unrealized_pnl_pct",
            "valuation_known",
            "cost_basis_known",
        )
        snapshots: list[dict[str, Any]] = []
        for row in rows:
            snapshot = dict(row)
            known = snapshot["valuation_known"] is True
            snapshot["valuation_status"] = "unconfirmed" if known else "unknown"
            basis_known = snapshot["cost_basis_known"]
            snapshot["cost_basis_status"] = (
                "known" if basis_known is True else "partial" if basis_known is False else "unknown"
            )
            snapshot["cost_basis_usable_for_decision"] = basis_known is True
            snapshot["must_not_use_for_decision"] = not known
            snapshot["blocking_reason_codes"] = [] if known else ["POSITION_VALUATION_UNKNOWN"]
            if not known:
                for field in ("current_price", "market_value", "unrealized_pnl_pct"):
                    snapshot[field] = None
            if basis_known is not True:
                snapshot["unrealized_pnl_pct"] = None
            snapshots.append(snapshot)
        return snapshots

    def list_held_asset_codes(self) -> list[str]:
        """Return distinct asset codes for currently held positions."""

        codes = (
            PositionModel._default_manager.filter(
                quantity__gt=0,
            )
            .values_list("asset_code", flat=True)
            .distinct()
        )
        return list(codes)

    def get_position(self, account_id: int, asset_code: str) -> Position | None:
        """获取特定持仓"""
        try:
            model = PositionModel._default_manager.get(account_id=account_id, asset_code=asset_code)
            return PositionMapper.to_entity(model)
        except PositionModel.DoesNotExist:
            return None

    def delete(self, account_id: int, asset_code: str) -> bool:
        """删除持仓"""
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            _lock_account_for_order_guard(account_id)
            exists = (
                PositionModel._default_manager.using(DEFAULT_DB_ALIAS)
                .filter(
                    account_id=account_id,
                    asset_code=asset_code,
                )
                .exists()
            )
            if not exists:
                return False
            require_no_active_order_reservations(
                account_id=account_id,
                using=DEFAULT_DB_ALIAS,
            )
            require_no_retained_v4_fill_history(
                account_id=account_id,
                asset_code=asset_code,
                using=DEFAULT_DB_ALIAS,
            )
            model = (
                PositionModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(account_id=account_id, asset_code=asset_code)
                .first()
            )
            if model is None:
                return False
            model.delete(using=DEFAULT_DB_ALIAS)
            return True

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

    def mark_invalidation_checked(
        self,
        account_id: int,
        asset_code: str,
        checked_at: datetime,
    ) -> bool:
        updated = PositionModel._default_manager.filter(
            account_id=account_id,
            asset_code=asset_code,
        ).update(invalidation_checked_at=checked_at)
        return int(updated) > 0

    def mark_invalidated(
        self,
        account_id: int,
        asset_code: str,
        reason: str,
        checked_at: datetime,
    ) -> bool:
        updated = PositionModel._default_manager.filter(
            account_id=account_id,
            asset_code=asset_code,
        ).update(
            is_invalidated=True,
            invalidation_reason=reason,
            invalidation_checked_at=checked_at,
        )
        return int(updated) > 0

    def count_positions_with_invalidation_rules(self) -> int:
        return int(
            PositionModel._default_manager.filter(invalidation_rule_json__isnull=False)
            .exclude(invalidation_rule_json={})
            .count()
        )

    def get_invalidated_position_summaries(self) -> list[dict[str, Any]]:
        models = (
            PositionModel._default_manager.filter(
                is_invalidated=True,
                quantity__gt=0,
            )
            .select_related("account")
            .order_by("-invalidation_checked_at")
        )
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
                    if model.invalidation_checked_at
                    else None
                ),
            }
            for model in models
        ]
