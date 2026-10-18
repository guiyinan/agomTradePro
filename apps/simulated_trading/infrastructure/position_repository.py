"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db import transaction

from apps.simulated_trading.domain.entities import (
    Position,
    SimulatedTrade,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from core.exceptions import BusinessLogicError

from .legacy_position_adoption_repository import DjangoLegacyPositionAdoptionRepository
from .repository_helpers import _require_saved_id
from .trade_mapper import SimulatedTradeMapper

_COST_BASIS_ECONOMIC_FIELDS: tuple[str, ...] = ("quantity", "avg_cost", "total_cost")


def _cost_basis_economics_changed(
    model: PositionModel,
    incoming: dict[str, Any],
) -> bool:
    """Detect changes to the persisted quantity or cost basis values."""
    for field_name in _COST_BASIS_ECONOMIC_FIELDS:
        if field_name not in incoming:
            continue
        try:
            stored_value = Decimal(str(getattr(model, field_name)))
            incoming_value = Decimal(str(incoming[field_name]))
        except (ArithmeticError, TypeError, ValueError):
            return True
        if (
            not stored_value.is_finite()
            or not incoming_value.is_finite()
            or stored_value != incoming_value
        ):
            return True
    return False


def _merge_cost_basis_knowledge(
    stored_known: bool | None,
    incoming_known: bool | None,
    *,
    economics_changed: bool,
) -> bool | None:
    """Preserve sticky states and forget completeness after unqualified changes."""
    if stored_known is False or incoming_known is False:
        return False
    if stored_known is True:
        return None if incoming_known is None and economics_changed else True
    return None


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
            quantity=float(model.quantity),
            available_quantity=float(model.available_quantity),
            avg_cost=float(model.avg_cost),
            total_cost=float(model.total_cost),
            current_price=float(model.current_price),
            market_value=float(model.market_value),
            unrealized_pnl=float(model.unrealized_pnl),
            unrealized_pnl_pct=model.unrealized_pnl_pct,
            first_buy_date=model.first_buy_date,
            last_update_date=model.last_update_date,
            available_quantity_known=model.available_quantity_known,
            first_buy_date_known=model.first_buy_date_known,
            valuation_known=model.valuation_known,
            cost_basis_known=model.cost_basis_known,
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
            available_quantity_known=entity.available_quantity_known,
            first_buy_date_known=entity.first_buy_date_known,
            valuation_known=entity.valuation_known,
            cost_basis_known=entity.cost_basis_known,
            signal_id=entity.signal_id,
            entry_reason=entity.entry_reason,
            # 证伪相关字段
            invalidation_rule_json=invalidation_json,
            invalidation_description=entity.invalidation_description or "",
            is_invalidated=entity.is_invalidated,
            invalidation_reason=entity.invalidation_reason or "",
            invalidation_checked_at=entity.invalidation_checked_at,
        )


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
        with transaction.atomic():
            model, created = PositionModel._default_manager.select_for_update().get_or_create(
                account_id=account_id,
                asset_code=asset_code,
                defaults=defaults,
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
            model.save()
            return model

    def save(self, position: Position) -> int:
        """
        Persist a position while preserving any previously unknown flags.

        Returns the stored position ID.
        """
        with transaction.atomic():
            model = (
                PositionModel._default_manager.select_for_update()
                .filter(account_id=position.account_id, asset_code=position.asset_code)
                .first()
            )
            if model is None:
                model = PositionMapper.to_model(position)
                model.id = None
                model.save()
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
            model.save()
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
        deleted, _ = PositionModel._default_manager.filter(
            account_id=account_id, asset_code=asset_code
        ).delete()
        return int(deleted) > 0

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

        with transaction.atomic():
            model, created = PositionModel._default_manager.select_for_update().get_or_create(
                account_id=account_id,
                asset_code=asset_code,
                defaults=position_defaults,
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
                model.save()
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
            existing = (
                PositionModel._default_manager.select_for_update()
                .filter(account_id=account_id, asset_code=asset_code)
                .first()
            )
            if existing is None:
                raise BusinessLogicError("持仓不存在", code="POSITION_NOT_FOUND")
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
            trade_model.save()

            if remaining_position_defaults is None:
                existing.delete()
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
            existing.save()

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
