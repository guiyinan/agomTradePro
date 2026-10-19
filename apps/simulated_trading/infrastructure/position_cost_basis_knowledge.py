"""Cost-basis knowledge helpers shared by position repository owners."""

from decimal import Decimal
from typing import Any

from apps.simulated_trading.infrastructure.models import PositionModel

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
