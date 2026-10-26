"""Stable Trade and qualification-policy fingerprints for fee evidence."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime

from .fee_correction_evidence_contracts import (
    FeeCorrectionPolicySnapshotJSON,
    OperatorAttestedFeeEvidenceRow,
    TradeEconomicFingerprintInput,
)
from .fee_correction_evidence_values import (
    _canonical_aware_datetime,
    _currency_token,
    _decimal_fixed,
    _optional_decimal_fixed,
    _valid_sha256,
)


def trade_economic_fingerprint_sha256(
    snapshot: TradeEconomicFingerprintInput,
) -> str:
    """Return the stable SHA-256 of immutable Trade economics and identity."""

    if type(snapshot) is not TradeEconomicFingerprintInput:
        raise ValueError("trade fingerprint requires the exact typed snapshot")
    if any(
        type(value) is not int or value <= 0
        for value in (snapshot.account_id, snapshot.account_owner_id, snapshot.trade_id)
    ):
        raise ValueError("trade fingerprint identifiers must be positive integers")
    if snapshot.status != "executed":
        raise ValueError("only executed trades can be bound to a fee evidence row")
    if snapshot.original_v4_receipt_hash is not None and not _valid_sha256(
        snapshot.original_v4_receipt_hash
    ):
        raise ValueError("original V4 receipt hash must be lowercase SHA-256")
    if snapshot.request_payload_hash is not None and not _valid_sha256(
        snapshot.request_payload_hash
    ):
        raise ValueError("request payload hash must be lowercase SHA-256")
    if snapshot.fee_schedule_hash is not None and not _valid_sha256(snapshot.fee_schedule_hash):
        raise ValueError("fee schedule hash must be lowercase SHA-256")
    if snapshot.settlement_plan_binding_hash is not None and not _valid_sha256(
        snapshot.settlement_plan_binding_hash
    ):
        raise ValueError("settlement plan hash must be lowercase SHA-256")
    if snapshot.settlement_bundle_hash is not None and not _valid_sha256(
        snapshot.settlement_bundle_hash
    ):
        raise ValueError("settlement bundle hash must be lowercase SHA-256")
    if snapshot.settlement_policy_hash is not None and not _valid_sha256(
        snapshot.settlement_policy_hash
    ):
        raise ValueError("settlement policy hash must be lowercase SHA-256")
    if snapshot.execution_rule_v2_hash is not None and not _valid_sha256(
        snapshot.execution_rule_v2_hash
    ):
        raise ValueError("execution rule hash must be lowercase SHA-256")
    if snapshot.realized_pnl_pct is not None and (
        type(snapshot.realized_pnl_pct) is not float or not math.isfinite(snapshot.realized_pnl_pct)
    ):
        raise ValueError("realized PnL percentage must be finite")
    if snapshot.execution_time.tzinfo is None or snapshot.execution_time.utcoffset() is None:
        raise ValueError("execution time must be timezone-aware")

    payload: dict[str, str | int | float | bool | None] = {
        "schema": "simulated-trade-economic-fingerprint.v1",
        "account_id": snapshot.account_id,
        "account_owner_id": snapshot.account_owner_id,
        "trade_id": snapshot.trade_id,
        "asset_code": snapshot.asset_code,
        "asset_name": snapshot.asset_name,
        "asset_type": snapshot.asset_type,
        "action": snapshot.action,
        "quantity": _decimal_fixed(snapshot.quantity, 6),
        "price": _decimal_fixed(snapshot.price, 4),
        "amount": _decimal_fixed(snapshot.amount, 2),
        "commission": _optional_decimal_fixed(snapshot.commission, 2),
        "transfer_fee": _optional_decimal_fixed(snapshot.transfer_fee, 2),
        "stamp_duty": _optional_decimal_fixed(snapshot.stamp_duty, 2),
        "slippage": _decimal_fixed(snapshot.slippage, 2),
        "total_cost": _decimal_fixed(snapshot.total_cost, 2),
        "fee_amounts_known": snapshot.fee_amounts_known,
        "cost_basis_known": snapshot.cost_basis_known,
        "realized_pnl": _optional_decimal_fixed(snapshot.realized_pnl, 2),
        "realized_pnl_pct": (
            repr(snapshot.realized_pnl_pct) if snapshot.realized_pnl_pct is not None else None
        ),
        "order_date": snapshot.order_date.isoformat(),
        "execution_date": snapshot.execution_date.isoformat(),
        "execution_time": _canonical_aware_datetime(snapshot.execution_time),
        "status": snapshot.status,
        "idempotency_key": snapshot.idempotency_key,
        "request_payload_hash": snapshot.request_payload_hash,
        "fee_config_id": snapshot.fee_config_id,
        "fee_schedule_hash": snapshot.fee_schedule_hash,
        "fee_precision_basis": snapshot.fee_precision_basis,
        "fee_calculation_purpose": snapshot.fee_calculation_purpose,
        "fee_rounding_policy": snapshot.fee_rounding_policy,
        "settlement_security_id": snapshot.settlement_security_id,
        "settlement_market": snapshot.settlement_market,
        "settlement_exchange": snapshot.settlement_exchange,
        "settlement_board": snapshot.settlement_board,
        "settlement_market_session": (
            snapshot.settlement_market_session.isoformat()
            if snapshot.settlement_market_session is not None
            else None
        ),
        "settlement_lag_sessions": snapshot.settlement_lag_sessions,
        "settlement_plan_binding_version": snapshot.settlement_plan_binding_version,
        "settlement_plan_binding_hash": snapshot.settlement_plan_binding_hash,
        "settlement_bundle_id": snapshot.settlement_bundle_id,
        "settlement_bundle_version": snapshot.settlement_bundle_version,
        "settlement_bundle_hash": snapshot.settlement_bundle_hash,
        "settlement_policy_id": snapshot.settlement_policy_id,
        "settlement_policy_version": snapshot.settlement_policy_version,
        "settlement_policy_hash": snapshot.settlement_policy_hash,
        "execution_rule_v2_hash": snapshot.execution_rule_v2_hash,
        "original_v4_receipt_hash": snapshot.original_v4_receipt_hash,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fee_correction_policy_sha256(
    *,
    account_id: int,
    version: int,
    enabled: bool,
    allows_operator_attested_upload: bool,
    ledger_currency: str,
    valid_from: datetime | None,
    valid_until: datetime | None,
    updated_by_id: int | None,
) -> str:
    """Return a digest of the exact local policy version used for qualification."""

    payload = fee_correction_policy_snapshot_json(
        account_id=account_id,
        version=version,
        enabled=enabled,
        allows_operator_attested_upload=allows_operator_attested_upload,
        ledger_currency=ledger_currency,
        valid_from=valid_from,
        valid_until=valid_until,
        updated_by_id=updated_by_id,
    )
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fee_correction_policy_snapshot_json(
    *,
    account_id: int,
    version: int,
    enabled: bool,
    allows_operator_attested_upload: bool,
    ledger_currency: str,
    valid_from: datetime | None,
    valid_until: datetime | None,
    updated_by_id: int | None,
) -> FeeCorrectionPolicySnapshotJSON:
    """Return exact JSON-safe policy values for current and historical checks."""

    if type(account_id) is not int or account_id <= 0 or type(version) is not int or version <= 0:
        raise ValueError("policy identity must use positive integer identifiers")
    if type(enabled) is not bool or type(allows_operator_attested_upload) is not bool:
        raise ValueError("policy flags must be booleans")
    if not _currency_token(ledger_currency):
        raise ValueError("ledger currency must be an explicit uppercase three-letter code")
    if updated_by_id is not None and (type(updated_by_id) is not int or updated_by_id <= 0):
        raise ValueError("policy actor must be a positive integer or null")
    for value in (valid_from, valid_until):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("policy validity timestamps must be timezone-aware")
    return {
        "schema": "simulated-fee-correction-policy.v2",
        "account_id": account_id,
        "version": version,
        "enabled": enabled,
        "allows_operator_attested_upload": allows_operator_attested_upload,
        "ledger_currency": ledger_currency,
        "valid_from": _canonical_aware_datetime(valid_from) if valid_from is not None else None,
        "valid_until": _canonical_aware_datetime(valid_until) if valid_until is not None else None,
        "updated_by_id": updated_by_id,
    }


def operator_fee_evidence_row_matches_trade(
    row: OperatorAttestedFeeEvidenceRow,
    trade: TradeEconomicFingerprintInput,
) -> bool:
    """Compare exact source-row economics to the selected simulated Trade."""

    try:
        return (
            trade.status == "executed"
            and row.asset_code == trade.asset_code
            and row.side == trade.action
            and row.quantity == trade.quantity
            and row.price == trade.price
            and row.amount == trade.amount
            and _canonical_aware_datetime(row.execution_at)
            == _canonical_aware_datetime(trade.execution_time)
        )
    except (ArithmeticError, TypeError, ValueError):
        return False
