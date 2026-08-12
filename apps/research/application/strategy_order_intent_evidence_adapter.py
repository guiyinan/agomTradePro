"""Fail-closed Evidence projection for one legacy Strategy order intent."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal

from apps.research.application.evidence_summary import EvidenceSummaryDTO
from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    ClaimKind,
    MethodKind,
    build_legacy_unverified_envelope,
)

_ARTIFACT_VERSION = "order-intent-v1"
_ACTIONS = frozenset({"allow", "deny", "watch"})
_SIDES = frozenset({"buy", "sell"})
_STATUSES = frozenset(
    {
        "approved",
        "canceled",
        "draft",
        "failed",
        "filled",
        "partial_filled",
        "pending_approval",
        "rejected",
        "sent",
    }
)
_TIME_IN_FORCE_VALUES = frozenset({"day", "fok", "gtc", "ioc"})


@dataclass(frozen=True, slots=True)
class LegacyStrategyOrderIntentProjection:
    """Data-only, exact projection supplied by the Strategy composition boundary."""

    intent_id: str
    strategy_id: int
    portfolio_id: int
    symbol: str
    side: str
    qty: int
    limit_price: Decimal | None
    time_in_force: str
    reason: str
    idempotency_key: str
    status: str
    created_at: datetime
    updated_at: datetime
    decision_action: str
    decision_reason_codes: tuple[str, ...]
    decision_reason_text: str
    decision_valid_until: datetime
    decision_confidence: Decimal
    sizing_target_notional: Decimal
    sizing_qty: int
    sizing_expected_risk_pct: Decimal
    sizing_method: str
    sizing_explain: str
    risk_total_equity: Decimal
    risk_cash_balance: Decimal
    risk_total_position_value: Decimal
    risk_daily_pnl_pct: Decimal
    risk_max_single_position_pct: Decimal
    risk_top3_position_pct: Decimal
    risk_current_regime: str
    risk_regime_confidence: Decimal
    risk_volatility_index: Decimal | None
    risk_max_position_limit_pct: Decimal
    risk_daily_loss_limit_pct: Decimal
    risk_daily_trade_limit: int


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value


def _require_text(
    value: object, field_name: str, *, maximum: int, allow_blank: bool = False
) -> str:
    if type(value) is not str or len(value) > maximum:
        raise ValueError(f"{field_name} must be bounded text")
    if not allow_blank and not value.strip():
        raise ValueError(f"{field_name} must be non-blank")
    return value


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    token = _require_text(value, field_name, maximum=maximum)
    if any(character.isspace() for character in token):
        raise ValueError(f"{field_name} must not contain whitespace")
    return token


def _require_decimal(
    value: object,
    field_name: str,
    *,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field_name} is below its minimum")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field_name} is above its maximum")
    return value


def _validate_projection(
    projection: LegacyStrategyOrderIntentProjection, *, evaluated_at: datetime
) -> None:
    if type(projection) is not LegacyStrategyOrderIntentProjection:
        raise TypeError("projection must be an exact LegacyStrategyOrderIntentProjection")
    evaluation_clock = _require_aware(evaluated_at, "evaluated_at")
    created_at = _require_aware(projection.created_at, "created_at")
    updated_at = _require_aware(projection.updated_at, "updated_at")
    valid_until = _require_aware(projection.decision_valid_until, "decision_valid_until")
    if created_at > updated_at or updated_at > evaluation_clock:
        raise ValueError("order intent timestamps must be monotonic and known at evaluated_at")
    if valid_until <= evaluation_clock:
        raise ValueError("order intent decision is expired at evaluated_at")

    _require_token(projection.intent_id, "intent_id")
    _require_token(projection.idempotency_key, "idempotency_key")
    _require_token(projection.symbol, "symbol", maximum=64)
    if type(projection.strategy_id) is not int or projection.strategy_id <= 0:
        raise ValueError("strategy_id must be a positive integer")
    if type(projection.portfolio_id) is not int or projection.portfolio_id <= 0:
        raise ValueError("portfolio_id must be a positive integer")
    if type(projection.qty) is not int or projection.qty <= 0:
        raise ValueError("qty must be a positive integer")
    if type(projection.sizing_qty) is not int or projection.sizing_qty != projection.qty:
        raise ValueError("sizing_qty must equal the order quantity")
    if projection.side not in _SIDES:
        raise ValueError("side must be a canonical Strategy order side")
    if projection.time_in_force not in _TIME_IN_FORCE_VALUES:
        raise ValueError("time_in_force must be canonical")
    if projection.status not in _STATUSES:
        raise ValueError("status must be a canonical Strategy order status")
    _require_text(projection.reason, "reason", maximum=2_000, allow_blank=True)

    if projection.decision_action not in _ACTIONS:
        raise ValueError("decision_action must be canonical")
    if type(projection.decision_reason_codes) is not tuple or not projection.decision_reason_codes:
        raise ValueError("decision_reason_codes must be a non-empty tuple")
    for reason_code in projection.decision_reason_codes:
        _require_token(reason_code, "decision_reason_code", maximum=128)
    if projection.decision_reason_codes != tuple(sorted(set(projection.decision_reason_codes))):
        raise ValueError("decision_reason_codes must be ordered and unique")
    _require_text(projection.decision_reason_text, "decision_reason_text", maximum=2_000)
    _require_decimal(
        projection.decision_confidence,
        "decision_confidence",
        minimum=Decimal("0"),
        maximum=Decimal("1"),
    )

    _require_decimal(
        projection.sizing_target_notional,
        "sizing_target_notional",
        minimum=Decimal("0.000000000000000001"),
    )
    _require_decimal(
        projection.sizing_expected_risk_pct,
        "sizing_expected_risk_pct",
        minimum=Decimal("0"),
    )
    _require_text(projection.sizing_method, "sizing_method", maximum=128)
    _require_text(projection.sizing_explain, "sizing_explain", maximum=2_000)
    if projection.limit_price is not None:
        _require_decimal(
            projection.limit_price,
            "limit_price",
            minimum=Decimal("0.000000000000000001"),
        )

    for field_name in (
        "risk_total_equity",
        "risk_cash_balance",
        "risk_total_position_value",
        "risk_daily_pnl_pct",
        "risk_max_single_position_pct",
        "risk_top3_position_pct",
        "risk_regime_confidence",
        "risk_max_position_limit_pct",
        "risk_daily_loss_limit_pct",
    ):
        _require_decimal(getattr(projection, field_name), field_name)
    if projection.risk_volatility_index is not None:
        _require_decimal(projection.risk_volatility_index, "risk_volatility_index")
    if projection.risk_total_equity <= 0:
        raise ValueError("risk_total_equity must be positive")
    if projection.risk_cash_balance < 0 or projection.risk_total_position_value < 0:
        raise ValueError("risk cash and position values must be non-negative")
    if not Decimal("0") <= projection.risk_regime_confidence <= Decimal("1"):
        raise ValueError("risk_regime_confidence must be between zero and one")
    if projection.risk_max_position_limit_pct <= 0 or projection.risk_daily_loss_limit_pct <= 0:
        raise ValueError("risk limits must be positive")
    if type(projection.risk_daily_trade_limit) is not int or projection.risk_daily_trade_limit <= 0:
        raise ValueError("risk_daily_trade_limit must be a positive integer")
    _require_text(projection.risk_current_regime, "risk_current_regime", maximum=128)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal_text(value: Decimal) -> str:
    integer, separator, fraction = format(value, "f").partition(".")
    canonical = integer if not separator else f"{integer}.{fraction.rstrip('0')}"
    canonical = canonical.rstrip(".")
    return "0" if canonical in {"-0", ""} else canonical


def _content_hash(projection: LegacyStrategyOrderIntentProjection) -> str:
    payload = asdict(projection)
    for field_name in (
        "created_at",
        "decision_valid_until",
        "updated_at",
    ):
        payload[field_name] = _utc_text(getattr(projection, field_name))
    for field_name in (
        "decision_confidence",
        "limit_price",
        "risk_cash_balance",
        "risk_daily_loss_limit_pct",
        "risk_daily_pnl_pct",
        "risk_max_position_limit_pct",
        "risk_max_single_position_pct",
        "risk_regime_confidence",
        "risk_top3_position_pct",
        "risk_total_equity",
        "risk_total_position_value",
        "risk_volatility_index",
        "sizing_expected_risk_pct",
        "sizing_target_notional",
    ):
        value = getattr(projection, field_name)
        payload[field_name] = _decimal_text(value) if value is not None else None
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_strategy_order_intent_legacy_evidence_summary(
    projection: LegacyStrategyOrderIntentProjection, *, evaluated_at: datetime
) -> EvidenceSummaryDTO:
    """Wrap one exact Strategy order intent as legacy-unverified display-only Evidence."""

    _validate_projection(projection, evaluated_at=evaluated_at)
    content_hash = _content_hash(projection)
    artifact = ArtifactRef(
        owner="strategy",
        artifact_type="order_intent",
        artifact_id=projection.intent_id,
        artifact_version=f"{_ARTIFACT_VERSION}.{content_hash}",
        content_hash=content_hash,
    )
    envelope = build_legacy_unverified_envelope(
        output_artifact=artifact,
        claim_kind=ClaimKind.RECOMMENDATION,
        method_kind=MethodKind.DETERMINISTIC,
        evaluated_at=evaluated_at,
        valid_until=projection.decision_valid_until,
    )
    return EvidenceSummaryDTO.from_legacy_envelope(envelope=envelope)


__all__ = [
    "LegacyStrategyOrderIntentProjection",
    "build_strategy_order_intent_legacy_evidence_summary",
]
