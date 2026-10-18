"""Stable execution identity comparisons used by broker import orchestration."""

from __future__ import annotations

from decimal import Decimal

from apps.account.application.broker_trade_reconciliation_contracts import (
    BrokerFactRecord,
    NormalizedTradeRow,
)
from apps.account.domain.broker_trade_reconciliation_fingerprints import BrokerFactIdentity


def _to_fact_identity(row: NormalizedTradeRow) -> BrokerFactIdentity:
    """Translate the typed normalized row into the shared exact fingerprint input."""
    return BrokerFactIdentity(
        broker_trade_key=row.broker_trade_key,
        action=row.action,
        asset_code=row.asset_code,
        shares=Decimal(str(row.shares)),
        price=row.price,
        commission=row.commission,
        stamp_duty=row.stamp_duty,
        transfer_fee=row.transfer_fee,
        traded_at=row.traded_at,
    )


def _same_source_execution(left: NormalizedTradeRow, right: NormalizedTradeRow) -> bool:
    """Compare same-file rows by every source/economic identity field."""
    return _to_fact_identity(left) == _to_fact_identity(right)


def _same_execution(
    record: BrokerFactRecord,
    row: NormalizedTradeRow,
    *,
    broker_name: str,
) -> bool:
    """Check a persisted stable-key hit against the complete immutable execution."""
    if (
        record.broker_trade_key != row.broker_trade_key
        or record.broker_name != broker_name
        or record.external_trade_id != row.external_trade_id
    ):
        return False
    if (
        record.action != row.action
        or record.asset_code != row.asset_code
        or Decimal(str(record.shares)) != Decimal(str(row.shares))
        or record.price != row.price
        or record.traded_at != row.traded_at
    ):
        return False
    return all(
        _same_optional_decimal(stored, supplied, known=known)
        for stored, supplied, known in (
            (record.commission, row.commission, record.commission_known),
            (record.stamp_duty, row.stamp_duty, record.stamp_duty_known),
            (record.transfer_fee, row.transfer_fee, record.transfer_fee_known),
        )
    )


def _same_optional_decimal(
    stored: Decimal,
    supplied: Decimal | None,
    *,
    known: bool | None,
) -> bool:
    """Compare supplied fees while retaining missing-versus-explicit-zero semantics."""
    if supplied is None:
        return known is not True
    return known is True and stored == supplied
