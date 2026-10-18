"""Preserve the broker parser's established cents normalization contract."""

from __future__ import annotations

from decimal import Decimal

from apps.account.infrastructure.broker_import_parser import BrokerTradeFileParser


def test_normalized_fee_uses_existing_half_up_cents_rule() -> None:
    """A half-cent broker fee normalizes to one cent rather than becoming invalid."""
    parser = BrokerTradeFileParser()
    result = parser.parse_normalized_facts(
        content=(
            b"traded_at,action,asset_code,shares,price,commission\n"
            b"2026-10-16T10:00:00+08:00,buy,600000.SH,1,10.00,0.005\n"
        ),
        filename="fees.csv",
        broker_name="fixture-broker",
        portfolio_id=11,
    )

    assert result.errors == ()
    assert len(result.rows) == 1
    assert result.rows[0].commission == Decimal("0.01")
