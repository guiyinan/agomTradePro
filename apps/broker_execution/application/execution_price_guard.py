"""Check the executable publication and account price limit at an order transition."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.data_center.application.execution_quotes import ExecutionQuoteUnavailable
from apps.data_center.application.public import get_execution_quote

from .use_case_errors import BrokerExecutionConflictError


def require_current_execution_price(
    *, asset_code: str, limit_price: Decimal | None, max_deviation: Decimal
) -> None:
    """Require a fresh execution quote and compare the limit against the locked account rule."""
    if limit_price is None or limit_price <= 0 or max_deviation <= 0:
        raise BrokerExecutionConflictError("Order and price-deviation limits must be positive")
    try:
        quote = get_execution_quote(asset_code, as_of=timezone.now())
    except ExecutionQuoteUnavailable as error:
        raise BrokerExecutionConflictError(error.reason.value) from error
    if timezone.now() >= quote.freshness_deadline:
        raise BrokerExecutionConflictError("execution_quote_stale")
    if abs(limit_price - quote.last) > max_deviation * quote.last:
        raise BrokerExecutionConflictError(
            "Order price exceeds the configured market-price deviation"
        )
