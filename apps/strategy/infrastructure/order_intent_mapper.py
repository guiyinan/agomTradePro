"""JSON-to-domain mapping helpers for portfolio-owned order intents."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.strategy.domain.entities import (
    DecisionAction,
    DecisionResult,
    RiskSnapshot,
    SizingResult,
)


def build_decision(data: dict[str, Any]) -> DecisionResult:
    """Build a decision value object from persisted JSON."""

    valid_until_raw = data.get("valid_until")
    valid_until: datetime | None = None
    if isinstance(valid_until_raw, str) and valid_until_raw:
        try:
            valid_until = datetime.fromisoformat(valid_until_raw)
        except ValueError:
            valid_until = None
    return DecisionResult(
        action=DecisionAction(data.get("action", DecisionAction.DENY.value)),
        reason_codes=data.get("reason_codes", []),
        reason_text=data.get("reason_text", ""),
        valid_until=valid_until,
        confidence=float(data.get("confidence", 1.0)),
    )


def build_sizing(data: dict[str, Any]) -> SizingResult:
    """Build a sizing value object from persisted JSON."""

    return SizingResult(
        target_notional=float(data.get("target_notional", 0.0)),
        qty=int(data.get("qty", 0)),
        expected_risk_pct=float(data.get("expected_risk_pct", 0.0)),
        sizing_method=data.get("sizing_method", ""),
        sizing_explain=data.get("sizing_explain", ""),
    )


def build_risk_snapshot(data: dict[str, Any]) -> RiskSnapshot:
    """Build a risk snapshot value object from persisted JSON."""

    return RiskSnapshot(
        total_equity=float(data.get("total_equity", 0.0)),
        cash_balance=float(data.get("cash_balance", 0.0)),
        total_position_value=float(data.get("total_position_value", 0.0)),
        daily_pnl_pct=float(data.get("daily_pnl_pct", 0.0)),
        max_single_position_pct=float(data.get("max_single_position_pct", 0.0)),
        top3_position_pct=float(data.get("top3_position_pct", 0.0)),
        current_regime=data.get("current_regime", "Unknown"),
        regime_confidence=float(data.get("regime_confidence", 0.0)),
        volatility_index=data.get("volatility_index"),
        max_position_limit_pct=float(data.get("max_position_limit_pct", 20.0)),
        daily_loss_limit_pct=float(data.get("daily_loss_limit_pct", 5.0)),
        daily_trade_limit=int(data.get("daily_trade_limit", 10)),
    )
