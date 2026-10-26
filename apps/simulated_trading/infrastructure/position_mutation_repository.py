"""Transactional position mutations and trade-range queries."""

from datetime import date
from decimal import Decimal
from typing import Any

from django.db import DEFAULT_DB_ALIAS, transaction

from apps.simulated_trading.domain.entities import Position, SimulatedTrade
from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedTradeModel
from core.exceptions import BusinessLogicError

from .legacy_position_adoption_repository import DjangoLegacyPositionAdoptionRepository
from .order_reservation_guard import require_no_active_order_reservations
from .position_cost_basis_knowledge import (
    _cost_basis_economics_changed,
    _merge_cost_basis_knowledge,
)
from .position_mapper import PositionMapper
from .position_repository_guard import (
    _lock_account_for_order_guard,
    _validate_position_record_defaults,
    _validated_buy_trade_payload,
    require_no_retained_v4_fill_history,
)
from .trade_mapper import SimulatedTradeMapper


class DjangoPositionMutationRepository:
    """Coordinate multi-table position mutations inside infrastructure transactions."""

    def adopt_legacy_position_projection(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        portfolio_id: int,
        source_position_id: int,
        asset_code: str,
        asset_name: str,
        asset_type: str,
        quantity: Decimal,
        avg_cost: Decimal,
        current_price: Decimal | None,
        first_buy_date: date,
    ) -> int | None:
        """Delegate legacy balance adoption to its bounded infrastructure owner."""
        return DjangoLegacyPositionAdoptionRepository().adopt_legacy_position_projection(
            account_id=account_id,
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
            source_position_id=source_position_id,
            asset_code=asset_code,
            asset_name=asset_name,
            asset_type=asset_type,
            quantity=quantity,
            avg_cost=avg_cost,
            current_price=current_price,
            first_buy_date=first_buy_date,
        )

    def create_or_merge_position_with_buy_trade(
        self,
        *,
        account_id: int,
        asset_code: str,
        position_defaults: dict[str, Any],
        trade_payload: dict[str, Any],
        expected_position: Position | None = None,
    ) -> PositionModel:
        """Persist the updated position row and matching buy trade atomically."""

        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            _lock_account_for_order_guard(account_id)
            require_no_active_order_reservations(
                account_id=account_id,
                using=DEFAULT_DB_ALIAS,
            )
            _validate_position_record_defaults(position_defaults)
            trade_payload = _validated_buy_trade_payload(
                account_id=account_id,
                asset_code=asset_code,
                trade_payload=trade_payload,
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
                    defaults=position_defaults,
                )
            )
            if model.available_quantity_known is not True:
                raise BusinessLogicError("可卖数量未知", code="SELLABLE_BALANCE_UNKNOWN")
            if model.valuation_known is not True:
                raise BusinessLogicError("持仓估值未知", code="POSITION_VALUATION_UNKNOWN")
            if (created and expected_position is not None) or (
                not created
                and (
                    expected_position is None
                    or PositionMapper.to_entity(model) != expected_position
                )
            ):
                raise BusinessLogicError(
                    "持仓已变化，请重试", code="POSITION_CHANGED_RETRY_REQUIRED"
                )
            if not created:
                persisted_defaults = dict(position_defaults)
                persisted_defaults["available_quantity_known"] = (
                    model.available_quantity_known is True
                    and position_defaults.get("available_quantity_known", True) is True
                )
                persisted_defaults["first_buy_date_known"] = (
                    model.first_buy_date_known is True
                    and position_defaults.get("first_buy_date_known", True) is True
                )
                persisted_defaults["cost_basis_known"] = _merge_cost_basis_knowledge(
                    model.cost_basis_known,
                    position_defaults.get("cost_basis_known"),
                    economics_changed=_cost_basis_economics_changed(model, position_defaults),
                )
                for field_name, value in persisted_defaults.items():
                    setattr(model, field_name, value)
                model.save(using=DEFAULT_DB_ALIAS)
            SimulatedTradeModel._default_manager.using(DEFAULT_DB_ALIAS).create(**trade_payload)
        return model

    def close_position_with_sell_trade(
        self,
        *,
        account_id: int,
        asset_code: str,
        remaining_position_defaults: dict[str, Any] | None,
        expected_position: Position,
        trade: SimulatedTrade,
    ) -> None:
        """Persist the sell trade and remaining position state atomically."""

        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            _lock_account_for_order_guard(account_id)
            require_no_active_order_reservations(
                account_id=account_id,
                using=DEFAULT_DB_ALIAS,
            )
            if remaining_position_defaults is not None:
                _validate_position_record_defaults(remaining_position_defaults)
            require_no_retained_v4_fill_history(
                account_id=account_id,
                asset_code=asset_code,
                using=DEFAULT_DB_ALIAS,
            )
            existing = (
                PositionModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(account_id=account_id, asset_code=asset_code)
                .first()
            )
            if existing is None:
                raise BusinessLogicError("持仓不存在", code="POSITION_NOT_FOUND")
            if PositionMapper.to_entity(existing) != expected_position:
                raise BusinessLogicError(
                    "持仓状态已变化，请重新读取",
                    code="POSITION_CHANGED_RETRY_REQUIRED",
                    details={"account_id": account_id, "asset_code": asset_code},
                )
            if existing.available_quantity_known is not True:
                raise BusinessLogicError("可卖数量未知", code="SELLABLE_BALANCE_UNKNOWN")
            if existing.valuation_known is not True:
                raise BusinessLogicError("持仓估值未知", code="POSITION_VALUATION_UNKNOWN")
            try:
                close_quantity = Decimal(str(trade.quantity))
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise BusinessLogicError("卖出数量无效", code="CLOSE_SHARES_INVALID") from exc
            if not close_quantity.is_finite() or close_quantity <= 0:
                raise BusinessLogicError("卖出数量无效", code="CLOSE_SHARES_INVALID")
            if (
                not existing.quantity.is_finite()
                or not existing.available_quantity.is_finite()
                or existing.available_quantity < 0
                or existing.available_quantity > existing.quantity
            ):
                raise BusinessLogicError("持仓余额无效", code="POSITION_BALANCE_INVALID")
            if close_quantity > existing.available_quantity:
                raise BusinessLogicError("可卖数量不足", code="SELLABLE_BALANCE_INSUFFICIENT")
            if trade.account_id != account_id or trade.asset_code != asset_code:
                raise BusinessLogicError(
                    "持仓与成交身份不一致", code="POSITION_TRADE_SCOPE_MISMATCH"
                )
            expected_remaining = existing.quantity - close_quantity
            if remaining_position_defaults is None:
                if expected_remaining != 0:
                    raise BusinessLogicError(
                        "持仓已变化，请重试", code="POSITION_CHANGED_RETRY_REQUIRED"
                    )
            elif (
                remaining_position_defaults.get("quantity") != expected_remaining
                or remaining_position_defaults.get("available_quantity")
                != existing.available_quantity - close_quantity
            ):
                raise BusinessLogicError(
                    "持仓已变化，请重试", code="POSITION_CHANGED_RETRY_REQUIRED"
                )
            trade_model = SimulatedTradeMapper.to_model(trade)
            trade_model.id = None
            trade_model.save(using=DEFAULT_DB_ALIAS)

            if remaining_position_defaults is None:
                existing.delete(using=DEFAULT_DB_ALIAS)
                return

            persisted_defaults = dict(remaining_position_defaults)
            persisted_defaults["available_quantity_known"] = (
                existing.available_quantity_known is True
                and remaining_position_defaults.get("available_quantity_known", True) is True
            )
            persisted_defaults["first_buy_date_known"] = (
                existing.first_buy_date_known is True
                and remaining_position_defaults.get("first_buy_date_known", True) is True
            )
            persisted_defaults["cost_basis_known"] = _merge_cost_basis_knowledge(
                existing.cost_basis_known,
                remaining_position_defaults.get("cost_basis_known"),
                economics_changed=_cost_basis_economics_changed(
                    existing,
                    remaining_position_defaults,
                ),
            )
            for field_name, value in persisted_defaults.items():
                setattr(existing, field_name, value)
            existing.save(using=DEFAULT_DB_ALIAS)

    def get_by_date_range(
        self, account_id: int, start_date: date, end_date: date
    ) -> list[SimulatedTrade]:
        """获取日期范围内的交易记录"""
        models = SimulatedTradeModel._default_manager.filter(
            account_id=account_id, execution_date__gte=start_date, execution_date__lte=end_date
        ).order_by("-execution_date", "-execution_time")
        return [SimulatedTradeMapper.to_entity(m) for m in models]

    def get_by_asset(self, account_id: int, asset_code: str) -> list[SimulatedTrade]:
        """获取特定资产的所有交易记录"""
        models = SimulatedTradeModel._default_manager.filter(
            account_id=account_id, asset_code=asset_code
        ).order_by("-execution_date", "-execution_time")
        return [SimulatedTradeMapper.to_entity(m) for m in models]

    def count_by_execution_date(self, account_id: int, execution_date: date) -> int:
        """按执行日期统计交易数。"""
        return int(
            SimulatedTradeModel._default_manager.filter(
                account_id=account_id,
                execution_date=execution_date,
            ).count()
        )
