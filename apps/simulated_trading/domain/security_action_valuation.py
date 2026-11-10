"""Reconcile a security action against unadjusted holding prices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SecurityActionReturnInput:
    """Exact position values around one action, excluding external cash flows."""

    quantity_before: Decimal
    quantity_after: Decimal
    price_before: Decimal
    price_after: Decimal
    cash_entitlement: Decimal
    price_basis: str
    share_delivery_confirmed: bool

    def __post_init__(self) -> None:
        for field_name in (
            "quantity_before",
            "quantity_after",
            "price_before",
            "price_after",
            "cash_entitlement",
        ):
            amount = getattr(self, field_name)
            if type(amount) is not Decimal or not amount.is_finite():
                raise ValueError(f"{field_name} must be a finite Decimal")
        if type(self.share_delivery_confirmed) is not bool:
            raise ValueError("share_delivery_confirmed must be a boolean")
        if self.price_basis != "unadjusted":
            raise ValueError("action return requires unadjusted observed prices")
        if self.quantity_before <= 0 or self.quantity_after < 0:
            raise ValueError("holding quantities are invalid")
        if self.price_before <= 0 or self.price_after < 0:
            raise ValueError("holding prices are invalid")
        if self.cash_entitlement < 0:
            raise ValueError("cash entitlement is invalid")
        if not self.share_delivery_confirmed and self.quantity_after != self.quantity_before:
            raise ValueError("changed quantity requires confirmed share delivery")


def reconcile_security_action_return(value: SecurityActionReturnInput) -> Decimal:
    """Return the holding return with cash counted once and confirmed shares valued once."""

    before = value.quantity_before * value.price_before
    after = value.quantity_after * value.price_after + value.cash_entitlement
    return (after - before) / before
