"""Compatibility conversion for portfolio-owned transition-plan rows."""

from decimal import Decimal
from typing import Any

from core.integration.transition_plan_contracts import require_legacy_transition_plan_family

from ..domain.entities import PortfolioTransitionPlan, TransitionOrder, TransitionPlanStatus


def transition_model_to_domain(model: Any) -> PortfolioTransitionPlan:
    """Convert the portfolio-owned persistence row to the legacy domain value."""

    require_legacy_transition_plan_family(getattr(model, "plan_contract_family", None))

    orders = [
        TransitionOrder(
            security_code=str(item.get("security_code") or ""),
            action=str(item.get("action") or "HOLD"),
            current_qty=int(item.get("current_qty") or 0),
            target_qty=int(item.get("target_qty") or 0),
            delta_qty=int(item.get("delta_qty") or 0),
            current_weight=float(item.get("current_weight") or 0.0),
            target_weight=float(item.get("target_weight") or 0.0),
            price_band_low=Decimal(str(item.get("price_band_low") or "0")),
            price_band_high=Decimal(str(item.get("price_band_high") or "0")),
            max_capital=Decimal(str(item.get("max_capital") or "0")),
            stop_loss_price=(
                Decimal(str(item.get("stop_loss_price")))
                if item.get("stop_loss_price") not in [None, ""]
                else None
            ),
            invalidation_rule=item.get("invalidation_rule") or {},
            execution_price=(
                Decimal(str(item.get("execution_price")))
                if item.get("execution_price") not in [None, ""]
                else None
            ),
            price_source=str(item.get("price_source") or ""),
            take_profit_price=(
                Decimal(str(item.get("take_profit_price")))
                if item.get("take_profit_price") not in [None, ""]
                else None
            ),
            take_profit_source=str(item.get("take_profit_source") or ""),
            stop_loss_source=str(item.get("stop_loss_source") or ""),
            thesis=str(item.get("thesis") or ""),
            risk_summary=str(item.get("risk_summary") or ""),
            reward_risk=dict(item.get("reward_risk") or {}),
            data_asof=str(item.get("data_asof") or ""),
            invalidation_description=str(item.get("invalidation_description") or ""),
            requires_user_confirmation=bool(item.get("requires_user_confirmation", False)),
            review_by=item.get("review_by"),
            time_horizon=str(item.get("time_horizon") or "swing"),
            source_recommendation_id=str(item.get("source_recommendation_id") or ""),
            notes=list(item.get("notes") or []),
        )
        for item in (model.orders or [])
    ]
    return PortfolioTransitionPlan(
        plan_id=model.plan_id,
        account_id=model.account_id,
        as_of=model.as_of,
        source_recommendation_ids=list(model.source_recommendation_ids or []),
        current_positions_snapshot=list(model.current_positions_snapshot or []),
        target_positions_snapshot=list(model.target_positions_snapshot or []),
        orders=orders,
        risk_contract=dict(model.risk_contract or {}),
        summary=dict(model.summary or {}),
        status=TransitionPlanStatus(model.status),
        approval_request_id=model.approval_request_id or None,
    )
