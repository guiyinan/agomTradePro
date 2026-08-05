"""Internal presenter for fixed-income research previews; no route is registered."""

from __future__ import annotations

from decimal import Decimal

from apps.fixed_income.domain.entities import FixedIncomeResearchPreview


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def present_fixed_income_research_preview(
    preview: FixedIncomeResearchPreview,
) -> dict[str, object]:
    """Map a typed preview to an internal, explicitly non-executable payload."""

    analytics: dict[str, object] | None = None
    if preview.analytics is not None:
        analytics = {
            "dirty_price": _decimal(preview.analytics.dirty_price),
            "accrued_interest": _decimal(preview.analytics.accrued_interest),
            "clean_price": _decimal(preview.analytics.clean_price),
            "annual_yield": _decimal(preview.analytics.annual_yield),
            "macaulay_duration_years": _decimal(preview.analytics.macaulay_duration_years),
            "modified_duration_years": _decimal(preview.analytics.modified_duration_years),
            "convexity_years_squared": _decimal(preview.analytics.convexity_years_squared),
        }
    relative_value: dict[str, object] | None = None
    if preview.relative_value is not None:
        relative_value = {
            "credit_spread_bp": _decimal(preview.relative_value.credit_spread_bp),
            "policy_bank_spread_bp": _decimal(preview.relative_value.policy_bank_spread_bp),
            "government_tenor_spread_bp": _decimal(
                preview.relative_value.government_tenor_spread_bp
            ),
            "carry_return": _decimal(preview.relative_value.carry.carry_return),
            "roll_down_return": _decimal(preview.relative_value.roll_down.estimated_price_return),
        }
    return {
        "status": preview.status.value,
        "method_version": preview.method_version,
        "bond_id": preview.bond_id,
        "valuation_at": preview.valuation_at.isoformat(),
        "analytics": analytics,
        "relative_value": relative_value,
        "publication_ids": list(preview.publication_ids),
        "blocked_reasons": list(preview.blocked_reasons),
        "research_only": preview.research_only,
        "must_not_execute": preview.must_not_execute,
        "must_not_use_for_decision": preview.must_not_use_for_decision,
    }
