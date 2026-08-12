"""Side-effect-free Strategy execution preview with explicit display-only semantics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.strategy.domain.services import DecisionPolicyEngine, PreTradeRiskGate, SizingEngine


@dataclass(frozen=True, slots=True)
class ExecutionPreviewPolicy:
    """Injected policy values used by the deterministic preview engines."""

    signal_threshold: float
    confidence_threshold: float
    regime_alignment_required: bool
    max_daily_loss_pct: float
    max_daily_trades: int
    sizing_method: str
    risk_per_trade_pct: float
    sizing_max_position_pct: float
    risk_max_single_position_pct: float
    min_qty: int
    min_volume: int
    market_max_age_seconds: int
    signal_max_age_seconds: int
    regime_max_age_seconds: int
    account_max_age_seconds: int


@dataclass(frozen=True, slots=True)
class ExecutionPreviewRequest:
    """Complete caller-supplied snapshot required for one preview."""

    symbol: str
    side: str
    current_price: float
    signal_strength: float
    signal_direction: str
    signal_confidence: float
    current_regime: str
    regime_confidence: float
    account_equity: float
    current_position_value: float
    daily_pnl_pct: float
    daily_trade_count: int
    market_observed_at: datetime
    signal_observed_at: datetime
    regime_observed_at: datetime
    account_observed_at: datetime
    stop_loss_price: float | None = None
    atr: float | None = None
    target_regime: str | None = None
    volatility_z: float | None = None
    avg_volume: float | None = None
    sizing_method: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionPreviewResult:
    """Research-only preview that can never authorize an order."""

    decision_action: str
    decision_reasons: tuple[str, ...]
    decision_text: str
    decision_confidence: float
    valid_until_seconds: int | None
    target_notional: float
    qty: int
    expected_risk_pct: float
    sizing_method: str
    sizing_explain: str
    risk_snapshot: dict[str, object]
    can_execute: bool
    requires_confirmation: bool
    research_only: bool
    governance_state: str
    permission: str
    blocker_codes: tuple[str, ...]
    must_not_use_for_decision: bool
    must_not_execute: bool
    evaluated_at: datetime
    market_observed_at: datetime
    signal_observed_at: datetime
    regime_observed_at: datetime
    account_observed_at: datetime

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-compatible Interface payload."""

        return {
            "decision_action": self.decision_action,
            "decision_reasons": list(self.decision_reasons),
            "decision_text": self.decision_text,
            "decision_confidence": self.decision_confidence,
            "valid_until_seconds": self.valid_until_seconds,
            "target_notional": self.target_notional,
            "qty": self.qty,
            "expected_risk_pct": self.expected_risk_pct,
            "sizing_method": self.sizing_method,
            "sizing_explain": self.sizing_explain,
            "risk_snapshot": self.risk_snapshot,
            "can_execute": self.can_execute,
            "requires_confirmation": self.requires_confirmation,
            "research_only": self.research_only,
            "governance_state": self.governance_state,
            "permission": self.permission,
            "blocker_codes": list(self.blocker_codes),
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "must_not_execute": self.must_not_execute,
            "evaluated_at": _utc_text(self.evaluated_at),
            "market_observed_at": _utc_text(self.market_observed_at),
            "signal_observed_at": _utc_text(self.signal_observed_at),
            "regime_observed_at": _utc_text(self.regime_observed_at),
            "account_observed_at": _utc_text(self.account_observed_at),
        }


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _require_aware_not_future(
    value: datetime,
    field_name: str,
    *,
    evaluated_at: datetime,
    max_age_seconds: int,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value > evaluated_at:
        raise ValueError(f"{field_name} cannot be later than evaluated_at")
    if (evaluated_at - value).total_seconds() > max_age_seconds:
        raise ValueError(f"{field_name} is stale at evaluated_at")


def _validate_request(
    request: ExecutionPreviewRequest,
    *,
    policy: ExecutionPreviewPolicy,
    evaluated_at: datetime,
) -> None:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    for field_name in (
        "market_max_age_seconds",
        "signal_max_age_seconds",
        "regime_max_age_seconds",
        "account_max_age_seconds",
    ):
        value = getattr(policy, field_name)
        if type(value) is not int or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
    if not request.symbol.strip() or len(request.symbol) > 32:
        raise ValueError("symbol must be bounded non-blank text")
    if request.side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if request.signal_direction not in {"bullish", "bearish", "neutral"}:
        raise ValueError("signal_direction is invalid")
    if not request.current_regime.strip() or len(request.current_regime) > 50:
        raise ValueError("current_regime must be bounded non-blank text")
    if request.target_regime is not None and (
        not request.target_regime.strip() or len(request.target_regime) > 50
    ):
        raise ValueError("target_regime must be bounded non-blank text")
    for field_name in (
        "current_price",
        "signal_strength",
        "signal_confidence",
        "regime_confidence",
        "account_equity",
        "current_position_value",
        "daily_pnl_pct",
    ):
        value = getattr(request, field_name)
        if type(value) is not float or not math.isfinite(value):
            raise ValueError(f"{field_name} must be a finite float")
    for field_name in ("stop_loss_price", "atr", "volatility_z", "avg_volume"):
        value = getattr(request, field_name)
        if value is not None and (type(value) is not float or not math.isfinite(value)):
            raise ValueError(f"{field_name} must be a finite float when provided")
    if request.current_price <= 0 or request.account_equity <= 0:
        raise ValueError("price and account equity must be positive")
    if request.current_position_value < 0:
        raise ValueError("current_position_value must be non-negative")
    if not 0 <= request.signal_strength <= 1:
        raise ValueError("signal_strength must be between zero and one")
    if not 0 <= request.signal_confidence <= 1:
        raise ValueError("signal_confidence must be between zero and one")
    if not 0 <= request.regime_confidence <= 1:
        raise ValueError("regime_confidence must be between zero and one")
    if type(request.daily_trade_count) is not int or request.daily_trade_count < 0:
        raise ValueError("daily_trade_count must be a non-negative integer")
    for field_name, max_age_seconds in (
        ("market_observed_at", policy.market_max_age_seconds),
        ("signal_observed_at", policy.signal_max_age_seconds),
        ("regime_observed_at", policy.regime_max_age_seconds),
        ("account_observed_at", policy.account_max_age_seconds),
    ):
        _require_aware_not_future(
            getattr(request, field_name),
            field_name,
            evaluated_at=evaluated_at,
            max_age_seconds=max_age_seconds,
        )


def evaluate_execution_preview(
    request: ExecutionPreviewRequest,
    *,
    policy: ExecutionPreviewPolicy,
    evaluated_at: datetime,
) -> ExecutionPreviewResult:
    """Evaluate one complete snapshot without granting decision or execution rights."""

    _validate_request(request, policy=policy, evaluated_at=evaluated_at)
    decision_engine = DecisionPolicyEngine(
        signal_threshold=policy.signal_threshold,
        confidence_threshold=policy.confidence_threshold,
        regime_alignment_required=policy.regime_alignment_required,
        max_daily_loss_pct=policy.max_daily_loss_pct,
        max_daily_trades=policy.max_daily_trades,
    )
    sizing_engine = SizingEngine(
        default_method=policy.sizing_method,
        risk_per_trade_pct=policy.risk_per_trade_pct,
        max_position_pct=policy.sizing_max_position_pct,
        min_qty=policy.min_qty,
    )
    risk_gate = PreTradeRiskGate(
        max_single_position_pct=policy.risk_max_single_position_pct,
        max_daily_trades=policy.max_daily_trades,
        max_daily_loss_pct=policy.max_daily_loss_pct,
        min_volume=policy.min_volume,
    )

    decision_action, reason_codes, reason_text, valid_until_seconds = decision_engine.evaluate(
        signal_strength=request.signal_strength,
        signal_direction=request.signal_direction,
        signal_confidence=request.signal_confidence,
        regime=request.current_regime,
        regime_confidence=request.regime_confidence,
        daily_pnl_pct=request.daily_pnl_pct,
        daily_trade_count=request.daily_trade_count,
        volatility_z=request.volatility_z,
        target_regime=request.target_regime,
    )
    target_notional, qty, expected_risk_pct, sizing_method, sizing_explain = (
        sizing_engine.calculate(
            method=request.sizing_method or policy.sizing_method,
            account_equity=request.account_equity,
            current_price=request.current_price,
            stop_loss_price=request.stop_loss_price,
            atr=request.atr,
            current_position_value=request.current_position_value,
        )
    )
    passed, violations, warnings, details = risk_gate.check(
        symbol=request.symbol,
        side=request.side,
        qty=qty,
        price=request.current_price,
        account_equity=request.account_equity,
        current_position_value=request.current_position_value,
        daily_trade_count=request.daily_trade_count,
        daily_pnl_pct=request.daily_pnl_pct,
        avg_volume=request.avg_volume,
    )
    return ExecutionPreviewResult(
        decision_action=decision_action,
        decision_reasons=tuple(reason_codes),
        decision_text=reason_text,
        decision_confidence=request.signal_confidence,
        valid_until_seconds=valid_until_seconds,
        target_notional=target_notional,
        qty=qty,
        expected_risk_pct=expected_risk_pct,
        sizing_method=sizing_method,
        sizing_explain=sizing_explain,
        risk_snapshot={
            "passed": passed,
            "violations": tuple(violations),
            "warnings": tuple(warnings),
            "details": details,
        },
        can_execute=False,
        requires_confirmation=decision_action == "watch",
        research_only=True,
        governance_state="research_only",
        permission="display_only",
        blocker_codes=("evidence.not_integrated", "strategy.execution_preview.display_only"),
        must_not_use_for_decision=True,
        must_not_execute=True,
        evaluated_at=evaluated_at,
        market_observed_at=request.market_observed_at,
        signal_observed_at=request.signal_observed_at,
        regime_observed_at=request.regime_observed_at,
        account_observed_at=request.account_observed_at,
    )


__all__ = [
    "ExecutionPreviewPolicy",
    "ExecutionPreviewRequest",
    "ExecutionPreviewResult",
    "evaluate_execution_preview",
]
