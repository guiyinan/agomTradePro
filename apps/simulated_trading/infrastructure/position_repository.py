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

from .repository_helpers import _require_saved_id
from .trade_mapper import SimulatedTradeMapper


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
        """Create or update one ORM position row and return it."""

        model, _ = PositionModel._default_manager.update_or_create(
            account_id=account_id,
            asset_code=asset_code,
            defaults=defaults,
        )
        return model

    def save(self, position: Position) -> int:
        """
        保存持仓(创建或更新)

        Returns:
            持仓ID
        """
        # 检查是否已存在
        existing = PositionModel._default_manager.filter(
            account_id=position.account_id, asset_code=position.asset_code
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
            return _require_saved_id(model.id, "position")
        else:
            # 创建新持仓
            model = PositionMapper.to_model(position)
            model.id = None
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
        """返回交易计划所需的持仓快照。"""
        rows = PositionModel._default_manager.filter(account_id=account_id).values(
            "asset_code",
            "asset_name",
            "quantity",
            "avg_cost",
            "current_price",
            "market_value",
            "unrealized_pnl_pct",
        )
        return [dict(row) for row in rows]

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

    def create_or_merge_position_with_buy_trade(
        self,
        *,
        account_id: int,
        asset_code: str,
        position_defaults: dict[str, Any],
        trade_payload: dict[str, Any],
    ) -> PositionModel:
        """Persist the updated position row and matching buy trade atomically."""

        with transaction.atomic():
            model, _ = PositionModel._default_manager.update_or_create(
                account_id=account_id,
                asset_code=asset_code,
                defaults=position_defaults,
            )
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
            trade_model = SimulatedTradeMapper.to_model(trade)
            trade_model.id = None
            trade_model.save()

            if remaining_position_defaults is None:
                PositionModel._default_manager.filter(
                    account_id=account_id,
                    asset_code=asset_code,
                ).delete()
                return

            PositionModel._default_manager.update_or_create(
                account_id=account_id,
                asset_code=asset_code,
                defaults=remaining_position_defaults,
            )

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
