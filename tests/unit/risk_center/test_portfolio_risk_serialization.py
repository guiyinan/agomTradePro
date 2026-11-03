"""Lossless portfolio-risk JSON and digest contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

import pytest

from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
    portfolio_risk_content_hash,
)


def test_decimal_serialization_does_not_round_under_small_decimal_context() -> None:
    """Exact financial digits survive when the ambient arithmetic precision is small."""

    amount = Decimal("123456789012345678901234567890.123456789012345678901")
    with localcontext() as context:
        context.prec = 3
        result = canonical_portfolio_risk_json({"amount": amount})

    assert result == ('{"amount":"123456789012345678901234567890.123456789012345678901"}')


def test_datetime_serialization_preserves_the_original_aware_offset() -> None:
    """Canonical output keeps the source offset instead of rewriting the clock to UTC."""

    observed_at = datetime(
        2026,
        11,
        3,
        15,
        45,
        12,
        345678,
        tzinfo=timezone(timedelta(hours=8)),
    )

    assert canonical_portfolio_risk_json({"observed_at": observed_at}) == (
        '{"observed_at":"2026-11-03T15:45:12.345678+08:00"}'
    )


@pytest.mark.parametrize(
    ("value", "error_type"),
    [
        (1.25, TypeError),
        (datetime(2026, 11, 3, 15, 0), ValueError),
    ],
)
def test_float_and_naive_datetime_are_rejected(
    value: object,
    error_type: type[Exception],
) -> None:
    """Dynamic numeric or clock values cannot enter canonical decision evidence."""

    with pytest.raises(error_type):
        canonical_portfolio_risk_json({"value": value})


def test_content_hash_is_order_stable_and_binds_every_value_change() -> None:
    """The digest is canonical across mapping order and changes with exact content."""

    observed_at = datetime(2026, 11, 3, 15, 0, tzinfo=timezone(timedelta(hours=8)))
    first = {"amount": Decimal("10.2300"), "observed_at": observed_at}
    same_content = {"observed_at": observed_at, "amount": Decimal("10.2300")}
    changed_amount = {"amount": Decimal("10.2301"), "observed_at": observed_at}
    changed_offset = {
        "amount": Decimal("10.2300"),
        "observed_at": observed_at.astimezone(timezone.utc),
    }

    first_hash = portfolio_risk_content_hash(first)
    assert first_hash == portfolio_risk_content_hash(same_content)
    assert first_hash != portfolio_risk_content_hash(changed_amount)
    assert first_hash != portfolio_risk_content_hash(changed_offset)
