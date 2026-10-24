"""Typed facts and exact arithmetic for the G5 historical quantity diagnostic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, Inexact, InvalidOperation, Rounded, localcontext
from typing import Literal

_QUANTITY_QUANTUM = Decimal("0.000001")
_MAX_LEDGER_QUANTITY = Decimal("99999999999999.999999")


@dataclass(frozen=True)
class HistoricalSellableDifferenceRow:
    """One owner-scoped source, target, or mapping discrepancy row."""

    portfolio_id: int | None
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
    total_quantity_difference: Decimal | None
    supported_sellable_quantity: Decimal | None
    requires_reconciliation: Literal[True]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class HistoricalSellableDifferenceReport:
    """Best-effort report for one explicitly selected user and account."""

    user_id: int
    account_id: int
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


def assemble_historical_difference_rows(
    *,
    source_positions: tuple[HistoricalSourcePositionFact, ...],
    target_positions: tuple[HistoricalTargetPositionFact, ...],
    mappings: tuple[HistoricalPositionMappingFact, ...],
    existing_target_position_ids: frozenset[int],
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
        reasons = ["SETTLEMENT_EVIDENCE_UNAVAILABLE"]
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

        rows.append(
            HistoricalSellableDifferenceRow(
                portfolio_id=source.portfolio_id,
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
                total_quantity_difference=difference,
                supported_sellable_quantity=None,
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
        total_quantity_difference=None,
        supported_sellable_quantity=None,
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
