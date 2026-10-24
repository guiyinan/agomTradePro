"""Exact interpretation of legacy floating-point share quantities."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, Inexact, InvalidOperation, Rounded, localcontext

_SHARE_QUANTUM = Decimal("0.000001")
_MAX_LEDGER_SHARES = Decimal("99999999999999.999999")


@dataclass(frozen=True)
class LegacyShareQuantity:
    """A legacy share count that is exact at the unified ledger's six-place scale."""

    value: Decimal | None
    known: bool
    reason_code: str | None


def normalize_legacy_share_quantity(value: object) -> LegacyShareQuantity:
    """Convert a legacy numeric share count without rounding or inventing precision."""

    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float)):
        return LegacyShareQuantity(None, False, "SOURCE_QUANTITY_INVALID")

    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return LegacyShareQuantity(None, False, "SOURCE_QUANTITY_INVALID")

    if not decimal_value.is_finite() or decimal_value < 0:
        return LegacyShareQuantity(None, False, "SOURCE_QUANTITY_INVALID")
    if decimal_value > _MAX_LEDGER_SHARES:
        return LegacyShareQuantity(None, False, "SOURCE_QUANTITY_PRECISION_UNSUPPORTED")

    try:
        with localcontext() as decimal_context:
            decimal_context.prec = max(40, len(decimal_value.as_tuple().digits) + 8)
            decimal_context.traps[Inexact] = False
            decimal_context.traps[Rounded] = False
            normalized = decimal_value.quantize(_SHARE_QUANTUM)
    except InvalidOperation:
        return LegacyShareQuantity(None, False, "SOURCE_QUANTITY_PRECISION_UNSUPPORTED")

    if normalized != decimal_value:
        return LegacyShareQuantity(None, False, "SOURCE_QUANTITY_PRECISION_UNSUPPORTED")
    return LegacyShareQuantity(normalized, True, None)
