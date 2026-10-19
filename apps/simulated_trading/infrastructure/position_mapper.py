"""Domain and ORM mapping for simulated-trading positions."""

from apps.simulated_trading.domain.entities import Position
from apps.simulated_trading.infrastructure.models import PositionModel


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
