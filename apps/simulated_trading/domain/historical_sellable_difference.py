"""Typed facts and exact arithmetic for the G5 historical quantity diagnostic."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, Inexact, InvalidOperation, Rounded, localcontext
from typing import Literal

_QUANTITY_QUANTUM = Decimal("0.000001")
_MAX_LEDGER_QUANTITY = Decimal("99999999999999.999999")


@dataclass(frozen=True)
class HistoricalSellableDifferenceRow:
    """One owner-scoped mapped discrepancy or native simulated Position row."""

    portfolio_id: int | None
    source_scope: Literal["account_position_mapping", "simulated_position"]
    source_position_id: int | None
    position_mapping_id: int | None
    mapping_target_table: str | None
    mapping_target_id: int | None
    target_position_id: int | None
    source_asset_code: str | None
    target_asset_code: str | None
    source_total_quantity: Decimal | None
    source_quantity_known: bool
    source_quantity_reason_code: str | None
    source_position_closed: bool | None
    source_observed_at: datetime | None
    legacy_record_updated_at: datetime | None
    target_total_quantity: Decimal | None
    stored_available_quantity: Decimal | None
    stored_available_quantity_known: bool | None
    ledger_total_quantity: Decimal | None
    ledger_available_quantity: Decimal | None
    active_sell_hold_quantity: Decimal | None
    evidence_cutoff_at: datetime | None
    evidence_proof_hash: str | None
    total_quantity_difference: Decimal | None
    supported_sellable_quantity: Decimal | None
    repair_available_quantity: Decimal | None
    repair_ready: bool
    repair_needed: bool
    requires_reconciliation: Literal[True]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class HistoricalSellableDifferenceReport:
    """Best-effort report for one explicitly selected user and account."""

    user_id: int
    account_id: int
    source_scope: Literal["account_position_mapping", "simulated_position"]
    portfolio_mapping_id: int | None
    database_alias: str
    reported_at: datetime
    scope_status: Literal["ok", "blocked"]
    reason_codes: tuple[str, ...]
    rows: tuple[HistoricalSellableDifferenceRow, ...]


@dataclass(frozen=True)
class LedgerQuantity:
    """A Decimal quantity validated against the unified position ledger scale."""

    value: Decimal | None
    reason_code: str | None


@dataclass(frozen=True)
class HistoricalLedgerFillFact:
    """One V4 applied fill already validated against its immutable receipt chain."""

    trade_id: int
    reservation_id: int
    fill_sequence: int
    binding_version: int
    receipt_version: int
    receipt_hash: str
    security_id: str
    asset_code: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    recorded_at: datetime
    prior_fill_count: int
    settlement_status: Literal["pending", "released"] | None
    settlement_lag_sessions: int
    release_proof_hash: str | None
    initial_position_mark_hash: str | None


@dataclass(frozen=True)
class HistoricalLedgerHoldFact:
    """One exact active SELL reservation hold reconstructed from its stored chain."""

    reservation_id: int
    security_id: str
    asset_code: str
    side: Literal["buy", "sell"]
    remaining_shares: Decimal
    reservation_state_hash: str


@dataclass(frozen=True)
class HistoricalLedgerEvidence:
    """Locked event chain and current holds for one mapped or native Position."""

    owner_user_id: int
    account_id: int
    source_scope: Literal["account_position_mapping", "simulated_position"]
    source_position_id: int | None
    target_position_id: int
    position_mapping_id: int | None
    mapping_fact: HistoricalPositionMappingFact | None
    security_id: str
    asset_code: str
    cutoff_at: datetime
    source_total_quantity: Decimal | None
    source_record_updated_at: datetime | None
    target_total_quantity: Decimal
    fills: tuple[HistoricalLedgerFillFact, ...]
    active_holds: tuple[HistoricalLedgerHoldFact, ...]
    unsupported_trade_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class HistoricalLedgerSellabilityProof:
    """Reconstructed total, settled availability, active holds, and exact proof digest."""

    total_quantity: Decimal | None
    available_quantity: Decimal | None
    active_sell_hold_quantity: Decimal | None
    supported_sellable_quantity: Decimal | None
    owner_user_id: int | None
    account_id: int | None
    source_scope: Literal["account_position_mapping", "simulated_position"] | None
    source_position_id: int | None
    target_position_id: int | None
    position_mapping_id: int | None
    security_id: str | None
    asset_code: str | None
    source_record_updated_at: datetime | None
    cutoff_at: datetime | None
    proof_hash: str | None
    reason_codes: tuple[str, ...]


def prove_historical_ledger_sellability(
    evidence: HistoricalLedgerEvidence,
) -> HistoricalLedgerSellabilityProof:
    """Rebuild one position from its V4 zero genesis, all fills/releases, and holds."""

    if type(evidence) is not HistoricalLedgerEvidence:
        raise TypeError("evidence must be a HistoricalLedgerEvidence")
    if (
        type(evidence.owner_user_id) is not int
        or evidence.owner_user_id <= 0
        or type(evidence.account_id) is not int
        or evidence.account_id <= 0
        or type(evidence.target_position_id) is not int
        or evidence.target_position_id <= 0
        or type(evidence.source_scope) is not str
        or evidence.source_scope not in ("account_position_mapping", "simulated_position")
        or type(evidence.security_id) is not str
        or not evidence.security_id.strip()
        or type(evidence.asset_code) is not str
        or not evidence.asset_code.strip()
        or type(evidence.cutoff_at) is not datetime
        or evidence.cutoff_at.tzinfo is None
        or evidence.cutoff_at.utcoffset() is None
        or type(evidence.source_total_quantity) not in (Decimal, type(None))
        or type(evidence.source_record_updated_at) not in (datetime, type(None))
        or (
            evidence.source_record_updated_at is not None
            and (
                evidence.source_record_updated_at.tzinfo is None
                or evidence.source_record_updated_at.utcoffset() is None
            )
        )
        or type(evidence.target_total_quantity) is not Decimal
        or type(evidence.unsupported_trade_ids) is not tuple
        or any(
            type(trade_id) is not int or trade_id <= 0
            for trade_id in evidence.unsupported_trade_ids
        )
    ):
        return _unproven_ledger(evidence, "LEDGER_SCOPE_INVALID")
    if evidence.source_scope == "simulated_position":
        if any(
            value is not None
            for value in (
                evidence.source_position_id,
                evidence.position_mapping_id,
                evidence.mapping_fact,
                evidence.source_total_quantity,
                evidence.source_record_updated_at,
            )
        ):
            return _unproven_ledger(evidence, "LEDGER_SCOPE_INVALID")
    else:
        mapping_fact = evidence.mapping_fact
        if (
            type(evidence.source_position_id) is not int
            or evidence.source_position_id <= 0
            or type(evidence.position_mapping_id) is not int
            or evidence.position_mapping_id <= 0
            or type(evidence.source_total_quantity) is not Decimal
            or type(mapping_fact) is not HistoricalPositionMappingFact
            or type(mapping_fact.mapping_id) is not int
            or type(mapping_fact.source_id) is not int
            or type(mapping_fact.target_id) is not int
            or mapping_fact.mapping_id != evidence.position_mapping_id
            or type(mapping_fact.source_app) is not str
            or mapping_fact.source_app != "account"
            or type(mapping_fact.source_table) is not str
            or mapping_fact.source_table != "position"
            or mapping_fact.source_id != evidence.source_position_id
            or type(mapping_fact.target_table) is not str
            or mapping_fact.target_table != "simulated_position"
            or mapping_fact.target_id != evidence.target_position_id
        ):
            return _unproven_ledger(evidence, "LEDGER_SCOPE_INVALID")
    if type(evidence.fills) is not tuple or type(evidence.active_holds) is not tuple:
        return _unproven_ledger(evidence, "LEDGER_HISTORY_INVALID")
    if any(type(fill) is not HistoricalLedgerFillFact for fill in evidence.fills):
        return _unproven_ledger(evidence, "LEDGER_HISTORY_INVALID")
    if any(type(hold) is not HistoricalLedgerHoldFact for hold in evidence.active_holds):
        return _unproven_ledger(evidence, "LEDGER_HISTORY_INVALID")
    if evidence.unsupported_trade_ids:
        return _unproven_ledger(evidence, "LEDGER_TRADE_VERSION_UNSUPPORTED")
    if not evidence.fills:
        return _unproven_ledger(evidence, "LEDGER_OPENING_ANCHOR_MISSING")

    total = Decimal("0.000000")
    available = Decimal("0.000000")
    prior_counts: dict[int, int] = {}
    previous_trade_id = 0
    canonical_fills: list[dict[str, object]] = []
    first = evidence.fills[0]
    if (
        first.side != "buy"
        or first.fill_sequence != 1
        or first.prior_fill_count != 0
        or first.receipt_version != 2
        or first.initial_position_mark_hash is None
    ):
        return _unproven_ledger(evidence, "LEDGER_OPENING_ANCHOR_INVALID")

    for fill in evidence.fills:
        if (
            type(fill) is not HistoricalLedgerFillFact
            or type(fill.trade_id) is not int
            or fill.trade_id <= previous_trade_id
            or type(fill.reservation_id) is not int
            or fill.reservation_id <= 0
            or type(fill.binding_version) is not int
            or fill.binding_version != 4
            or type(fill.receipt_version) is not int
            or fill.receipt_version not in (1, 2)
            or type(fill.security_id) is not str
            or fill.security_id != evidence.security_id
            or type(fill.asset_code) is not str
            or fill.asset_code != evidence.asset_code
            or type(fill.side) is not str
            or fill.side not in ("buy", "sell")
            or not _is_sha256(fill.receipt_hash)
            or type(fill.fill_sequence) is not int
            or fill.fill_sequence <= 0
            or type(fill.prior_fill_count) is not int
            or fill.prior_fill_count < 0
            or type(fill.settlement_lag_sessions) is not int
            or fill.settlement_lag_sessions < 0
            or type(fill.quantity) is not Decimal
            or type(fill.settlement_status) not in (str, type(None))
            or type(fill.release_proof_hash) not in (str, type(None))
            or type(fill.initial_position_mark_hash) not in (str, type(None))
            or type(fill.recorded_at) is not datetime
            or fill.recorded_at.tzinfo is None
            or fill.recorded_at.utcoffset() is None
        ):
            return _unproven_ledger(evidence, "LEDGER_FILL_IDENTITY_INVALID")
        if fill.recorded_at > evidence.cutoff_at:
            return _unproven_ledger(evidence, "LEDGER_FILL_AFTER_CUTOFF")
        normalized_quantity = normalize_ledger_quantity(fill.quantity)
        if normalized_quantity.value is None or normalized_quantity.value <= 0:
            return _unproven_ledger(evidence, "LEDGER_FILL_QUANTITY_INVALID")
        if fill.initial_position_mark_hash is not None:
            if fill.receipt_version != 2 or not _is_sha256(fill.initial_position_mark_hash):
                return _unproven_ledger(evidence, "LEDGER_INITIAL_MARK_INVALID")
            if total != 0 or available != 0:
                return _unproven_ledger(evidence, "LEDGER_POSITION_CYCLE_MISMATCH")
        elif fill.receipt_version != 1:
            return _unproven_ledger(evidence, "LEDGER_INITIAL_MARK_MISSING")

        expected_prior_count = prior_counts.get(fill.reservation_id, 0)
        if (
            fill.fill_sequence != expected_prior_count + 1
            or fill.prior_fill_count != expected_prior_count
        ):
            return _unproven_ledger(evidence, "LEDGER_FILL_SEQUENCE_GAP")
        prior_counts[fill.reservation_id] = fill.fill_sequence

        if fill.side == "buy":
            if fill.settlement_status not in ("pending", "released"):
                return _unproven_ledger(evidence, "LEDGER_BUY_SETTLEMENT_UNKNOWN")
            if fill.settlement_status == "pending" and fill.release_proof_hash is not None:
                return _unproven_ledger(evidence, "LEDGER_PENDING_RELEASE_CONFLICT")
            if fill.settlement_status == "released":
                if fill.release_proof_hash is not None and not _is_sha256(fill.release_proof_hash):
                    return _unproven_ledger(evidence, "LEDGER_RELEASE_PROOF_INVALID")
                if fill.settlement_lag_sessions > 0 and not _is_sha256(fill.release_proof_hash):
                    return _unproven_ledger(evidence, "LEDGER_RELEASE_PROOF_MISSING")
                available_after_buy = _add_exact_quantity(available, normalized_quantity.value)
                if available_after_buy is None:
                    return _unproven_ledger(evidence, "LEDGER_AVAILABLE_QUANTITY_INVALID")
                available = available_after_buy
            elif fill.release_proof_hash is not None:
                return _unproven_ledger(evidence, "LEDGER_PENDING_RELEASE_CONFLICT")
            total_after_buy = _add_exact_quantity(total, normalized_quantity.value)
            if total_after_buy is None:
                return _unproven_ledger(evidence, "LEDGER_TOTAL_QUANTITY_INVALID")
            total = total_after_buy
        else:
            if fill.settlement_status is not None or fill.release_proof_hash is not None:
                return _unproven_ledger(evidence, "LEDGER_SELL_SETTLEMENT_INVALID")
            if normalized_quantity.value > total or normalized_quantity.value > available:
                return _unproven_ledger(evidence, "LEDGER_SELL_EXCEEDS_PROVEN_AVAILABLE")
            total_after_sell = exact_quantity_difference(total, normalized_quantity.value)
            available_after_sell = exact_quantity_difference(available, normalized_quantity.value)
            if total_after_sell is None or available_after_sell is None:
                return _unproven_ledger(evidence, "LEDGER_SELL_QUANTITY_INVALID")
            total = total_after_sell
            available = available_after_sell

        previous_trade_id = fill.trade_id
        canonical_fills.append(
            {
                "trade_id": fill.trade_id,
                "reservation_id": fill.reservation_id,
                "fill_sequence": fill.fill_sequence,
                "binding_version": fill.binding_version,
                "receipt_version": fill.receipt_version,
                "prior_fill_count": fill.prior_fill_count,
                "receipt_hash": fill.receipt_hash,
                "security_id": fill.security_id,
                "asset_code": fill.asset_code,
                "side": fill.side,
                "quantity": format_ledger_quantity(normalized_quantity.value),
                "recorded_at": fill.recorded_at.astimezone(UTC).isoformat(),
                "settlement_status": fill.settlement_status,
                "settlement_lag_sessions": fill.settlement_lag_sessions,
                "release_proof_hash": fill.release_proof_hash,
                "initial_position_mark_hash": fill.initial_position_mark_hash,
            }
        )
    if evidence.source_scope == "account_position_mapping":
        if total != normalize_ledger_quantity(evidence.source_total_quantity).value:
            return _unproven_ledger(evidence, "LEDGER_SOURCE_TOTAL_MISMATCH")
    if total != normalize_ledger_quantity(evidence.target_total_quantity).value:
        return _unproven_ledger(evidence, "LEDGER_TARGET_TOTAL_MISMATCH")

    hold_total = Decimal("0.000000")
    canonical_holds: list[dict[str, object]] = []
    seen_reservations: set[int] = set()
    for hold in evidence.active_holds:
        if type(hold.remaining_shares) is not Decimal:
            return _unproven_ledger(evidence, "LEDGER_ACTIVE_HOLD_INVALID")
        quantity = normalize_ledger_quantity(hold.remaining_shares)
        if (
            type(hold.reservation_id) is not int
            or hold.reservation_id <= 0
            or hold.reservation_id in seen_reservations
            or type(hold.security_id) is not str
            or hold.security_id != evidence.security_id
            or type(hold.asset_code) is not str
            or hold.asset_code != evidence.asset_code
            or type(hold.side) is not str
            or hold.side != "sell"
            or not _is_sha256(hold.reservation_state_hash)
            or quantity.value is None
            or quantity.value <= 0
        ):
            return _unproven_ledger(evidence, "LEDGER_ACTIVE_HOLD_INVALID")
        seen_reservations.add(hold.reservation_id)
        hold_total_after_add = _add_exact_quantity(hold_total, quantity.value)
        if hold_total_after_add is None:
            return _unproven_ledger(evidence, "LEDGER_ACTIVE_HOLD_INVALID")
        hold_total = hold_total_after_add
        canonical_holds.append(
            {
                "reservation_id": hold.reservation_id,
                "security_id": hold.security_id,
                "asset_code": hold.asset_code,
                "side": hold.side,
                "remaining_shares": format_ledger_quantity(quantity.value),
                "reservation_state_hash": hold.reservation_state_hash,
            }
        )
    if hold_total > available:
        return _unproven_ledger(evidence, "LEDGER_ACTIVE_HOLDS_EXCEED_AVAILABLE")

    cutoff_text = evidence.cutoff_at.astimezone(UTC).isoformat()
    proof_payload: dict[str, object] = {
        "schema": "ash03.historical-sellable-proof.v1",
        "owner_user_id": evidence.owner_user_id,
        "account_id": evidence.account_id,
        "source_scope": evidence.source_scope,
        "source_position_id": evidence.source_position_id,
        "target_position_id": evidence.target_position_id,
        "position_mapping_id": evidence.position_mapping_id,
        "mapping_source_app": (
            evidence.mapping_fact.source_app if evidence.mapping_fact is not None else None
        ),
        "mapping_source_table": (
            evidence.mapping_fact.source_table if evidence.mapping_fact is not None else None
        ),
        "mapping_source_id": (
            evidence.mapping_fact.source_id if evidence.mapping_fact is not None else None
        ),
        "mapping_target_table": (
            evidence.mapping_fact.target_table if evidence.mapping_fact is not None else None
        ),
        "mapping_target_id": (
            evidence.mapping_fact.target_id if evidence.mapping_fact is not None else None
        ),
        "security_id": evidence.security_id,
        "asset_code": evidence.asset_code,
        "cutoff_at": cutoff_text,
        "source_total_quantity": format_ledger_quantity(evidence.source_total_quantity),
        "source_record_updated_at": (
            evidence.source_record_updated_at.astimezone(UTC).isoformat()
            if evidence.source_record_updated_at is not None
            else None
        ),
        "target_total_quantity": format_ledger_quantity(evidence.target_total_quantity),
        "fills": canonical_fills,
        "active_holds": canonical_holds,
        "available_quantity": format_ledger_quantity(available),
        "active_sell_hold_quantity": format_ledger_quantity(hold_total),
    }
    encoded_payload = json.dumps(
        proof_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return HistoricalLedgerSellabilityProof(
        total_quantity=total,
        available_quantity=available,
        active_sell_hold_quantity=hold_total,
        supported_sellable_quantity=exact_quantity_difference(available, hold_total),
        owner_user_id=evidence.owner_user_id,
        account_id=evidence.account_id,
        source_scope=evidence.source_scope,
        source_position_id=evidence.source_position_id,
        target_position_id=evidence.target_position_id,
        position_mapping_id=evidence.position_mapping_id,
        security_id=evidence.security_id,
        asset_code=evidence.asset_code,
        source_record_updated_at=evidence.source_record_updated_at,
        cutoff_at=evidence.cutoff_at,
        proof_hash=hashlib.sha256(encoded_payload).hexdigest(),
        reason_codes=(),
    )


def _unproven_ledger(
    evidence: HistoricalLedgerEvidence,
    reason_code: str,
) -> HistoricalLedgerSellabilityProof:
    """Fail closed without returning partial computed balances as usable values."""

    cutoff_at = evidence.cutoff_at if type(evidence.cutoff_at) is datetime else None
    return HistoricalLedgerSellabilityProof(
        total_quantity=None,
        available_quantity=None,
        active_sell_hold_quantity=None,
        supported_sellable_quantity=None,
        owner_user_id=None,
        account_id=None,
        source_scope=None,
        source_position_id=None,
        target_position_id=None,
        position_mapping_id=None,
        security_id=None,
        asset_code=None,
        source_record_updated_at=None,
        cutoff_at=cutoff_at,
        proof_hash=None,
        reason_codes=(reason_code, "SETTLEMENT_EVIDENCE_UNAVAILABLE"),
    )


def _is_sha256(value: str | None) -> bool:
    """Check one canonical lowercase SHA-256 without coercing external input."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _add_exact_quantity(left: Decimal, right: Decimal) -> Decimal | None:
    """Add nonnegative shares under an explicit context and ledger precision."""

    try:
        with localcontext() as decimal_context:
            decimal_context.prec = 50
            decimal_context.traps[Inexact] = False
            decimal_context.traps[Rounded] = False
            value = left + right
    except (ArithmeticError, InvalidOperation):
        return None
    normalized = normalize_ledger_quantity(value)
    return normalized.value


@dataclass(frozen=True)
class HistoricalSourcePositionFact:
    """Account-owned source facts projected without importing its Application type."""

    portfolio_id: int
    position_id: int
    asset_code: str
    quantity: Decimal | None
    quantity_known: bool
    quantity_reason_code: str | None
    is_closed: bool
    record_updated_at: datetime | None


@dataclass(frozen=True)
class HistoricalPositionMappingFact:
    """Exact source and target identifiers from a migration map row."""

    mapping_id: int
    source_app: str
    source_table: str
    source_id: int
    target_table: str
    target_id: int


@dataclass(frozen=True)
class HistoricalTargetPositionFact:
    """Target position facts owned by the selected simulated account."""

    position_id: int
    account_id: int
    asset_code: str
    quantity: Decimal | None
    available_quantity: Decimal | None
    available_quantity_known: bool | None
    first_buy_date_known: bool | None = None
    ledger_proof: HistoricalLedgerSellabilityProof | None = None


def assemble_historical_difference_rows(
    *,
    source_positions: tuple[HistoricalSourcePositionFact, ...],
    target_positions: tuple[HistoricalTargetPositionFact, ...],
    mappings: tuple[HistoricalPositionMappingFact, ...],
    existing_target_position_ids: frozenset[int],
    owner_user_id: int,
    account_id: int,
) -> tuple[HistoricalSellableDifferenceRow, ...]:
    """Compare exact mapped quantities and report unresolved rows without sellable claims."""

    source_ids = {position.position_id for position in source_positions}
    selected_positions = tuple(
        position for position in target_positions if position.account_id == account_id
    )
    target_by_id = {position.position_id: position for position in selected_positions}
    selected_target_ids = {position.position_id for position in selected_positions}
    rows: list[HistoricalSellableDifferenceRow] = []
    represented_target_ids: set[int] = set()

    for source in source_positions:
        reasons: list[str] = []
        source_quantity, source_known, source_reason = _source_values(source)
        if source.is_closed:
            reasons.append("SOURCE_POSITION_CLOSED")
        if source_reason is not None:
            reasons.append(source_reason)
        if not source_known:
            reasons.append("SOURCE_QUANTITY_UNKNOWN")

        source_mappings = tuple(
            mapping
            for mapping in mappings
            if mapping.source_app == "account"
            and mapping.source_table == "position"
            and mapping.source_id == source.position_id
        )
        mapping = source_mappings[0] if len(source_mappings) == 1 else None
        if not source_mappings:
            reasons.append("POSITION_MAP_MISSING")
        elif len(source_mappings) > 1:
            reasons.append("POSITION_MAP_SOURCE_AMBIGUOUS")

        target: HistoricalTargetPositionFact | None = None
        target_position_id: int | None = None
        mapping_target_id: int | None = None
        if mapping is not None:
            if mapping.target_table != "simulated_position":
                reasons.append("POSITION_MAP_TARGET_TABLE_MISMATCH")
            else:
                candidate = target_by_id.get(mapping.target_id)
                if candidate is None and mapping.target_id in existing_target_position_ids:
                    reasons.append("POSITION_MAP_ACCOUNT_MISMATCH")
                elif candidate is None:
                    reasons.append("POSITION_MAP_TARGET_MISSING")
                else:
                    target = candidate
                    target_position_id = candidate.position_id
                    mapping_target_id = candidate.position_id
                    represented_target_ids.add(candidate.position_id)
                    reverse_mappings = tuple(
                        item
                        for item in mappings
                        if item.target_table == "simulated_position"
                        and item.target_id == candidate.position_id
                    )
                    if len(reverse_mappings) > 1:
                        reasons.append("POSITION_MAP_REVERSE_AMBIGUOUS")

        target_quantity, available_quantity, available_known, target_reasons = _target_values(
            target
        )
        reasons.extend(target_reasons)
        if target is not None and target.asset_code != source.asset_code:
            reasons.append("POSITION_MAP_ASSET_MISMATCH")
        difference = exact_quantity_difference(source_quantity, target_quantity)
        if difference is not None and difference != 0:
            reasons.append("TOTAL_QUANTITY_MISMATCH")

        proof = target.ledger_proof if target is not None else None
        proof_matches = (
            proof is not None
            and not proof.reason_codes
            and proof.source_scope == "account_position_mapping"
            and proof.owner_user_id == owner_user_id
            and proof.owner_user_id is not None
            and proof.owner_user_id > 0
            and proof.account_id == account_id
            and proof.source_position_id == source.position_id
            and proof.target_position_id == target_position_id
            and proof.position_mapping_id == (mapping.mapping_id if mapping is not None else None)
            and type(proof.security_id) is str
            and bool(proof.security_id.strip())
            and proof.asset_code == source.asset_code
            and proof.source_record_updated_at == source.record_updated_at
            and proof.total_quantity == source_quantity == target_quantity
            and proof.cutoff_at is not None
            and proof.cutoff_at.tzinfo is not None
            and proof.cutoff_at.utcoffset() is not None
            and _is_sha256(proof.proof_hash)
            and proof.available_quantity is not None
            and proof.active_sell_hold_quantity is not None
            and proof.supported_sellable_quantity
            == exact_quantity_difference(
                proof.available_quantity,
                proof.active_sell_hold_quantity,
            )
        )
        matched_proof = proof if proof is not None and proof_matches else None
        repair_ready = (
            proof_matches
            and source_known
            and not source.is_closed
            and target is not None
            and target.asset_code == source.asset_code
            and target.first_buy_date_known is True
            and difference == Decimal("0.000000")
            and mapping is not None
            and mapping.target_table == "simulated_position"
            and len(source_mappings) == 1
            and len(
                tuple(
                    item
                    for item in mappings
                    if item.target_table == "simulated_position"
                    and item.target_id == target.position_id
                )
            )
            == 1
        )
        if not repair_ready:
            reasons.append("SETTLEMENT_EVIDENCE_UNAVAILABLE")
        repair_needed = bool(
            repair_ready
            and proof is not None
            and (available_known is not True or available_quantity != proof.available_quantity)
        )
        if repair_needed:
            reasons.append("AVAILABLE_QUANTITY_MISMATCH")

        rows.append(
            HistoricalSellableDifferenceRow(
                portfolio_id=source.portfolio_id,
                source_scope="account_position_mapping",
                source_position_id=source.position_id,
                position_mapping_id=mapping.mapping_id if mapping is not None else None,
                mapping_target_table=(mapping.target_table if mapping is not None else None),
                mapping_target_id=mapping_target_id,
                target_position_id=target_position_id,
                source_asset_code=source.asset_code,
                target_asset_code=target.asset_code if target is not None else None,
                source_total_quantity=source_quantity,
                source_quantity_known=source_known,
                source_quantity_reason_code=source_reason,
                source_position_closed=source.is_closed,
                source_observed_at=None,
                legacy_record_updated_at=source.record_updated_at,
                target_total_quantity=target_quantity,
                stored_available_quantity=available_quantity,
                stored_available_quantity_known=available_known,
                ledger_total_quantity=(
                    matched_proof.total_quantity if matched_proof is not None else None
                ),
                ledger_available_quantity=(
                    matched_proof.available_quantity if matched_proof is not None else None
                ),
                active_sell_hold_quantity=(
                    matched_proof.active_sell_hold_quantity if matched_proof is not None else None
                ),
                evidence_cutoff_at=(matched_proof.cutoff_at if matched_proof is not None else None),
                evidence_proof_hash=(
                    matched_proof.proof_hash if matched_proof is not None else None
                ),
                total_quantity_difference=difference,
                supported_sellable_quantity=(
                    matched_proof.supported_sellable_quantity
                    if repair_ready and matched_proof is not None
                    else None
                ),
                repair_available_quantity=(
                    matched_proof.available_quantity
                    if repair_ready and matched_proof is not None
                    else None
                ),
                repair_ready=bool(repair_ready),
                repair_needed=repair_needed,
                requires_reconciliation=True,
                reason_codes=tuple(dict.fromkeys(reasons)),
            )
        )

    for target in selected_positions:
        target_refs = tuple(
            mapping
            for mapping in mappings
            if mapping.target_table == "simulated_position"
            and mapping.target_id == target.position_id
        )
        if target.position_id in represented_target_ids or any(
            mapping.source_app == "account" and mapping.source_table == "position"
            for mapping in target_refs
        ):
            continue
        normalized = normalize_ledger_quantity(target.quantity)
        available = normalize_ledger_quantity(target.available_quantity)
        reasons = ["POSITION_SOURCE_MISSING", "SETTLEMENT_EVIDENCE_UNAVAILABLE"]
        if normalized.reason_code is not None:
            reasons.append(normalized.reason_code)
        if available.reason_code is not None:
            reasons.append("AVAILABLE_QUANTITY_INVALID")
        rows.append(
            _target_only_row(
                target=target,
                quantity=normalized.value,
                available_quantity=available.value,
                reasons=tuple(reasons),
            )
        )

    for mapping in mappings:
        if (
            mapping.source_app != "account"
            or mapping.source_table != "position"
            or mapping.target_table != "simulated_position"
            or mapping.target_id not in selected_target_ids
            or mapping.source_id in source_ids
        ):
            continue
        target = target_by_id.get(mapping.target_id)
        if target is None or target.account_id != account_id:
            continue
        normalized = normalize_ledger_quantity(target.quantity)
        available = normalize_ledger_quantity(target.available_quantity)
        reasons = [
            "POSITION_MAP_SOURCE_MISSING_OR_OUTSIDE_SCOPE",
            "SETTLEMENT_EVIDENCE_UNAVAILABLE",
        ]
        if normalized.reason_code is not None:
            reasons.append(normalized.reason_code)
        if available.reason_code is not None:
            reasons.append("AVAILABLE_QUANTITY_INVALID")
        rows.append(
            _target_only_row(
                target=target,
                quantity=normalized.value,
                available_quantity=available.value,
                reasons=tuple(reasons),
                mapping=mapping,
            )
        )

    return tuple(rows)


def assemble_simulated_position_sellability_rows(
    *,
    target_positions: tuple[HistoricalTargetPositionFact, ...],
    owner_user_id: int,
    account_id: int,
) -> tuple[HistoricalSellableDifferenceRow, ...]:
    """Report only the selected simulated account's own ledger identities."""

    rows: list[HistoricalSellableDifferenceRow] = []
    for target in target_positions:
        if target.account_id != account_id:
            continue
        target_quantity = normalize_ledger_quantity(target.quantity).value
        stored_available = normalize_ledger_quantity(target.available_quantity).value
        proof = target.ledger_proof
        proof_matches = (
            proof is not None
            and not proof.reason_codes
            and proof.source_scope == "simulated_position"
            and proof.owner_user_id == owner_user_id
            and proof.account_id == account_id
            and target.account_id == account_id
            and proof.source_position_id is None
            and proof.target_position_id == target.position_id
            and proof.position_mapping_id is None
            and proof.source_record_updated_at is None
            and type(proof.security_id) is str
            and bool(proof.security_id.strip())
            and proof.asset_code == target.asset_code
            and proof.total_quantity == target_quantity
            and proof.cutoff_at is not None
            and proof.cutoff_at.tzinfo is not None
            and proof.cutoff_at.utcoffset() is not None
            and _is_sha256(proof.proof_hash)
            and proof.available_quantity is not None
            and proof.active_sell_hold_quantity is not None
            and proof.supported_sellable_quantity
            == exact_quantity_difference(
                proof.available_quantity,
                proof.active_sell_hold_quantity,
            )
        )
        matched_proof = proof if proof is not None and proof_matches else None
        repair_ready = bool(
            proof_matches and target.first_buy_date_known is True and target_quantity is not None
        )
        repair_needed = bool(
            repair_ready
            and proof is not None
            and (
                target.available_quantity_known is not True
                or stored_available != proof.available_quantity
            )
        )
        reasons = ["SOURCE_IDENTITY_NOT_APPLICABLE"]
        if not repair_ready:
            reasons.append("SETTLEMENT_EVIDENCE_UNAVAILABLE")
        if repair_needed:
            reasons.append("AVAILABLE_QUANTITY_MISMATCH")
        rows.append(
            HistoricalSellableDifferenceRow(
                portfolio_id=None,
                source_scope="simulated_position",
                source_position_id=None,
                position_mapping_id=None,
                mapping_target_table=None,
                mapping_target_id=None,
                target_position_id=target.position_id,
                source_asset_code=None,
                target_asset_code=target.asset_code,
                source_total_quantity=None,
                source_quantity_known=False,
                source_quantity_reason_code="SOURCE_IDENTITY_NOT_APPLICABLE",
                source_position_closed=None,
                source_observed_at=None,
                legacy_record_updated_at=None,
                target_total_quantity=target_quantity,
                stored_available_quantity=stored_available,
                stored_available_quantity_known=target.available_quantity_known,
                ledger_total_quantity=(
                    matched_proof.total_quantity if matched_proof is not None else None
                ),
                ledger_available_quantity=(
                    matched_proof.available_quantity if matched_proof is not None else None
                ),
                active_sell_hold_quantity=(
                    matched_proof.active_sell_hold_quantity if matched_proof is not None else None
                ),
                evidence_cutoff_at=(matched_proof.cutoff_at if matched_proof is not None else None),
                evidence_proof_hash=(
                    matched_proof.proof_hash if matched_proof is not None else None
                ),
                total_quantity_difference=None,
                supported_sellable_quantity=(
                    matched_proof.supported_sellable_quantity
                    if repair_ready and matched_proof is not None
                    else None
                ),
                repair_available_quantity=(
                    matched_proof.available_quantity
                    if repair_ready and matched_proof is not None
                    else None
                ),
                repair_ready=repair_ready,
                repair_needed=repair_needed,
                requires_reconciliation=True,
                reason_codes=tuple(reasons),
            )
        )
    return tuple(rows)


def _source_values(
    source: HistoricalSourcePositionFact,
) -> tuple[Decimal | None, bool, str | None]:
    """Keep contradictory or unverified source quantities out of numeric comparisons."""

    if not source.quantity_known or source.quantity_reason_code is not None:
        return None, False, source.quantity_reason_code or "SOURCE_QUANTITY_UNKNOWN"
    normalized = normalize_ledger_quantity(source.quantity)
    reason = (
        "SOURCE_" + normalized.reason_code.removeprefix("TARGET_")
        if normalized.reason_code is not None
        else None
    )
    return normalized.value, normalized.value is not None, reason


def _target_values(
    target: HistoricalTargetPositionFact | None,
) -> tuple[Decimal | None, Decimal | None, bool | None, tuple[str, ...]]:
    """Validate target quantities while preserving its stored knowledge flag."""

    if target is None:
        return None, None, None, ()
    quantity = normalize_ledger_quantity(target.quantity)
    available = normalize_ledger_quantity(target.available_quantity)
    reason_codes: list[str] = []
    if quantity.reason_code is not None:
        reason_codes.append(quantity.reason_code)
    if available.reason_code is not None:
        reason_codes.append("AVAILABLE_QUANTITY_INVALID")
    return quantity.value, available.value, target.available_quantity_known, tuple(reason_codes)


def _target_only_row(
    *,
    target: HistoricalTargetPositionFact,
    quantity: Decimal | None,
    available_quantity: Decimal | None,
    reasons: tuple[str, ...],
    mapping: HistoricalPositionMappingFact | None = None,
) -> HistoricalSellableDifferenceRow:
    """Build an owned target row without inventing a source link."""

    return HistoricalSellableDifferenceRow(
        portfolio_id=None,
        source_scope="account_position_mapping",
        source_position_id=None,
        position_mapping_id=mapping.mapping_id if mapping is not None else None,
        mapping_target_table=mapping.target_table if mapping is not None else None,
        mapping_target_id=target.position_id if mapping is not None else None,
        target_position_id=target.position_id,
        source_asset_code=None,
        target_asset_code=target.asset_code,
        source_total_quantity=None,
        source_quantity_known=False,
        source_quantity_reason_code=None,
        source_position_closed=None,
        source_observed_at=None,
        legacy_record_updated_at=None,
        target_total_quantity=quantity,
        stored_available_quantity=available_quantity,
        stored_available_quantity_known=target.available_quantity_known,
        ledger_total_quantity=None,
        ledger_available_quantity=None,
        active_sell_hold_quantity=None,
        evidence_cutoff_at=None,
        evidence_proof_hash=None,
        total_quantity_difference=None,
        supported_sellable_quantity=None,
        repair_available_quantity=None,
        repair_ready=False,
        repair_needed=False,
        requires_reconciliation=True,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def normalize_ledger_quantity(value: Decimal | None) -> LedgerQuantity:
    """Keep only finite, nonnegative quantities exactly represented at scale six."""

    if value is None or not value.is_finite() or value < 0:
        return LedgerQuantity(None, "TARGET_QUANTITY_INVALID")
    if value > _MAX_LEDGER_QUANTITY:
        return LedgerQuantity(None, "TARGET_QUANTITY_PRECISION_UNSUPPORTED")
    try:
        with localcontext() as decimal_context:
            decimal_context.prec = max(40, len(value.as_tuple().digits) + 8)
            decimal_context.traps[Inexact] = False
            decimal_context.traps[Rounded] = False
            normalized = value.quantize(_QUANTITY_QUANTUM)
    except InvalidOperation:
        return LedgerQuantity(None, "TARGET_QUANTITY_PRECISION_UNSUPPORTED")
    if normalized != value:
        return LedgerQuantity(None, "TARGET_QUANTITY_PRECISION_UNSUPPORTED")
    return LedgerQuantity(normalized, None)


def exact_quantity_difference(
    source_quantity: Decimal | None,
    target_quantity: Decimal | None,
) -> Decimal | None:
    """Subtract validated quantities without inheriting the caller's Decimal context."""

    if source_quantity is None or target_quantity is None:
        return None
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        decimal_context.traps[Inexact] = False
        decimal_context.traps[Rounded] = False
        return source_quantity - target_quantity


def format_ledger_quantity(value: Decimal | None) -> str | None:
    """Serialize a validated quantity as a fixed six-place decimal string."""

    if value is None:
        return None
    with localcontext() as decimal_context:
        decimal_context.prec = max(40, len(value.as_tuple().digits) + 8)
        decimal_context.traps[Inexact] = False
        decimal_context.traps[Rounded] = False
        return format(value.quantize(_QUANTITY_QUANTUM), "f")
