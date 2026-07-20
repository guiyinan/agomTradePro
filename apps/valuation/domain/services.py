"""Pure valuation snapshot construction services."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

from .entities import ValuationSnapshot, create_valuation_snapshot


class ValuationSnapshotService:
    """Create formal, legacy, and explicit fallback valuation snapshots."""

    DEFAULT_STOP_LOSS_PCT = 0.10
    DEFAULT_TARGET_UPSIDE_PCT = 0.20
    ENTRY_PRICE_TOLERANCE = 0.05

    def create_snapshot(
        self,
        security_code: str,
        valuation_method: str,
        fair_value: Decimal,
        current_price: Decimal,
        input_parameters: dict[str, Any],
        stop_loss_pct: float | None = None,
        target_upside_pct: float | None = None,
    ) -> ValuationSnapshot:
        """Create a formal valuation snapshot and price bands."""
        stop_loss_pct = stop_loss_pct or self.DEFAULT_STOP_LOSS_PCT
        target_upside_pct = target_upside_pct or self.DEFAULT_TARGET_UPSIDE_PCT
        entry_price_low = fair_value * Decimal(str(1 - self.ENTRY_PRICE_TOLERANCE))
        entry_price_high = fair_value * Decimal(str(1 + self.ENTRY_PRICE_TOLERANCE))
        if current_price < fair_value:
            entry_price_high = max(entry_price_high, current_price * Decimal("1.02"))
            entry_price_low = min(entry_price_low, current_price * Decimal("0.98"))
        target_price_low = fair_value * Decimal(str(1 + target_upside_pct * 0.8))
        target_price_high = fair_value * Decimal(str(1 + target_upside_pct * 1.2))
        stop_loss_price = entry_price_low * Decimal(str(1 - stop_loss_pct))
        return create_valuation_snapshot(
            security_code=security_code,
            valuation_method=valuation_method,
            fair_value=fair_value,
            entry_price_low=entry_price_low,
            entry_price_high=entry_price_high,
            target_price_low=target_price_low,
            target_price_high=target_price_high,
            stop_loss_price=stop_loss_price,
            input_parameters=input_parameters,
        )

    def create_from_comprehensive_valuation(
        self,
        stock_code: str,
        valuation_result: Any,
        current_price: Decimal,
    ) -> ValuationSnapshot:
        """Create a snapshot from a comprehensive valuation score."""
        score = valuation_result.overall_score
        if score >= 80:
            multiplier = 1.3
        elif score >= 60:
            multiplier = 1.15
        elif score >= 40:
            multiplier = 1.0
        else:
            multiplier = 0.9
        fair_value = current_price * Decimal(str(multiplier))
        return self.create_snapshot(
            security_code=stock_code,
            valuation_method="COMPOSITE",
            fair_value=fair_value,
            current_price=current_price,
            input_parameters={
                "overall_score": score,
                "overall_signal": valuation_result.overall_signal,
                "confidence": valuation_result.confidence,
                "scores": [
                    {"method": item.method, "score": item.score, "signal": item.signal}
                    for item in valuation_result.scores
                ],
            },
        )

    def create_legacy_snapshot(
        self,
        security_code: str,
        estimated_fair_value: Decimal,
        current_price: Decimal,
    ) -> ValuationSnapshot:
        """Create a compatibility snapshot explicitly marked as legacy."""
        snapshot = self.create_snapshot(
            security_code=security_code,
            valuation_method="LEGACY",
            fair_value=estimated_fair_value or current_price,
            current_price=current_price,
            input_parameters={"source": "legacy_migration"},
        )
        return replace(snapshot, is_legacy=True)

    def create_current_price_fallback_snapshot(
        self,
        security_code: str,
        current_price: Decimal,
        *,
        source: str = "current_price",
    ) -> ValuationSnapshot:
        """Create a conservative snapshot explicitly marked as FALLBACK."""
        return create_valuation_snapshot(
            security_code=security_code,
            valuation_method="FALLBACK",
            fair_value=current_price,
            entry_price_low=current_price * Decimal("0.95"),
            entry_price_high=current_price * Decimal("1.02"),
            target_price_low=current_price * Decimal("1.15"),
            target_price_high=current_price * Decimal("1.25"),
            stop_loss_price=current_price * Decimal("0.90"),
            input_parameters={
                "source": source,
                "fallback_type": "current_price_based",
                "fair_value_formula": "current_price",
                "entry_band": "current_price * 0.95..1.02",
                "target_band": "current_price * 1.15..1.25",
                "stop_loss": "current_price * 0.90",
            },
        )
