"""Pure position valuation calculations for account-domain use cases."""

from decimal import Decimal


def calculate_observed_unrealized_pnl(
    entry_price: float, shares: float, current_price: float
) -> tuple[Decimal, float]:
    """Calculate observed P&L from validated non-zero position and price inputs.

    Return the percentage as a fractional ratio (0.10 means 10%), not percentage points.
    """

    entry_price_decimal = Decimal(str(entry_price))
    shares_decimal = Decimal(str(shares))
    current_price_decimal = Decimal(str(current_price))
    price_difference = current_price_decimal - entry_price_decimal
    amount = price_difference * shares_decimal
    percentage = float(price_difference / entry_price_decimal)
    return amount, percentage
