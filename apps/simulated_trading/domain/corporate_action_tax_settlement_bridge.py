"""Pure bridge from qualified daily settlement facts to existing tax evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from typing import NoReturn

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxRequest,
    DeferredDividendTaxValidationError,
    TaxableDispositionEvidence,
    TaxLotEvidence,
    TaxLotOrigin,
    _require_account_id,
    _require_date,
    _require_digest,
    _require_token,
    _sha256_json,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    QualifiedTaxSettlementHistory,
    RecordDateTaxEntitlementRuleKind,
    TaxSettlementDayEvidence,
)

_ZERO = Decimal("0.000000")
_HISTORY_INCOMPLETE = "DEFERRED_DIVIDEND_TAX_HISTORY_INCOMPLETE"
_POSITION_INCOMPLETE = "DEFERRED_DIVIDEND_TAX_POSITION_INCOMPLETE"
_ORIGIN_UNKNOWN = "DEFERRED_DIVIDEND_TAX_ORIGIN_UNKNOWN"
_SCOPE_INVALID = "DEFERRED_DIVIDEND_TAX_EVIDENCE_INVALID"


def _reject(message: str, code: str = "DEFERRED_DIVIDEND_TAX_EVIDENCE_INVALID") -> NoReturn:
    """Raise one stable deferred-tax bridge validation error."""

    raise DeferredDividendTaxValidationError(message, code)


def _share_text(value: Decimal) -> str:
    """Serialize bounded shares at the tax Domain's six-place ledger precision."""

    with localcontext() as context:
        context.prec = 80
        return format(value.quantize(Decimal("0.000001")), "f")


def _sale_id(
    *,
    account_id: int,
    security_id: str,
    corporate_action_id: str,
    settlement_date: date,
) -> str:
    """Return one stable net-sale identity independent of source revisions."""

    digest = _sha256_json(
        {
            "account_id": account_id,
            "security_id": security_id,
            "corporate_action_id": corporate_action_id,
            "settlement_date": settlement_date.isoformat(),
        }
    )
    return f"daily-net-sale.v1:{settlement_date.isoformat()}:{digest}"


def _purchase_lot_id(
    *,
    account_id: int,
    security_id: str,
    settlement_date: date,
) -> str:
    """Return one stable net-purchase lot identity for a scoped settlement day."""

    digest = _sha256_json(
        {
            "account_id": account_id,
            "security_id": security_id,
            "settlement_date": settlement_date.isoformat(),
        }
    )
    return f"daily-net-purchase.v1:{settlement_date.isoformat()}:{digest}"


def _record_date_evidence(
    *,
    history: QualifiedTaxSettlementHistory,
    lot_id: str,
    quantity: Decimal,
) -> tuple[str, str]:
    """Bind a derived per-lot entitlement to ownership and explicit rule sources."""

    entitlement = history.record_date_entitlement
    proof = history.record_date_ownership_proof
    digest = _sha256_json(
        {
            "schema": "deferred-dividend-record-date-lot.v1",
            "account_id": history.account_id,
            "owner_user_id": history.owner_user_id,
            "security_id": history.security_id,
            "asset_code": history.asset_code,
            "record_date": history.record_date.isoformat(),
            "lot_id": lot_id,
            "position_quantity": _share_text(quantity),
            "entitled_quantity": _share_text(quantity),
            "ownership_snapshot_id": proof.ownership_snapshot_id,
            "ownership_snapshot_sha256": proof.ownership_snapshot_sha256,
            "rule_kind": entitlement.kind.value,
            "rule_source_id": entitlement.rule_source_id,
            "rule_source_sha256": entitlement.rule_source_sha256,
            "entitlement_total_evidence_id": entitlement.total_evidence_id,
            "entitlement_total_evidence_sha256": entitlement.total_evidence_sha256,
            "qualified_total_quantity": _share_text(entitlement.qualified_total_quantity),
        }
    )
    return f"record-date-lot.v1:{digest}", digest


def _day_payload(day: TaxSettlementDayEvidence) -> dict[str, object]:
    """Build the canonical digest entry for a session, including zero-change days."""

    return {
        "account_id": day.account_id,
        "owner_user_id": day.owner_user_id,
        "security_id": day.security_id,
        "asset_code": day.asset_code,
        "settlement_date": day.settlement_date.isoformat(),
        "opening_eod_quantity": _share_text(day.opening_eod_quantity),
        "gross_purchase_quantity": _share_text(day.gross_purchase_quantity),
        "gross_sale_quantity": _share_text(day.gross_sale_quantity),
        "non_trade_quantity_delta": _share_text(day.non_trade_quantity_delta),
        "closing_eod_quantity": _share_text(day.closing_eod_quantity),
        "purchase_origin": day.purchase_origin.value,
        "evidence_id": day.evidence_id,
        "evidence_sha256": day.evidence_sha256,
        "source_revision_id": day.source_revision_id,
        "source_revision_sha256": day.source_revision_sha256,
    }


def _request_payload(
    *,
    history: QualifiedTaxSettlementHistory,
    days: tuple[TaxSettlementDayEvidence, ...],
    lot_evidence: tuple[TaxLotEvidence, ...],
    dispositions: tuple[TaxableDispositionEvidence, ...],
    corporate_action_id: str,
    target_settlement_date: date,
) -> dict[str, object]:
    """Canonicalize the complete selected prefix and all derived tax evidence."""

    proof = history.record_date_ownership_proof
    anchor = history.opening_anchor
    entitlement = history.record_date_entitlement
    return {
        "schema": "simulated-corporate-action-tax-settlement.v1",
        "scope": {
            "account_id": history.account_id,
            "owner_user_id": history.owner_user_id,
            "security_id": history.security_id,
            "asset_code": history.asset_code,
            "corporate_action_id": corporate_action_id,
            "record_date": history.record_date.isoformat(),
            "target_settlement_date": target_settlement_date.isoformat(),
        },
        "date_rule": {
            "id": history.settlement_date_rule_id,
            "sha256": history.settlement_date_rule_sha256,
        },
        "calendar": {
            "id": history.settlement_calendar_id,
            "sha256": history.settlement_calendar_sha256,
            "covered_sessions": [
                day.isoformat()
                for day in history.covered_session_dates
                if day <= target_settlement_date
            ],
        },
        "source_revision": {
            "id": history.source_revision_id,
            "sha256": history.source_revision_sha256,
        },
        "record_date_ownership": {
            "snapshot_id": proof.ownership_snapshot_id,
            "snapshot_sha256": proof.ownership_snapshot_sha256,
            "eligible_quantity": _share_text(proof.eligible_quantity),
            "cutoff_policy_id": proof.cutoff_policy_id,
            "cutoff_policy_sha256": proof.cutoff_policy_sha256,
        },
        "opening_anchor": {
            "anchor_id": anchor.anchor_id,
            "anchor_kind": anchor.anchor_kind.value,
            "quantity": _share_text(anchor.quantity),
            "effective_at": anchor.effective_at.isoformat(),
            "observed_at": anchor.observed_at.isoformat(),
            "evidence_sha256": anchor.evidence_sha256,
        },
        "record_date_entitlement": {
            "kind": entitlement.kind.value,
            "rule_source_id": entitlement.rule_source_id,
            "rule_source_sha256": entitlement.rule_source_sha256,
            "qualified_total_quantity": _share_text(entitlement.qualified_total_quantity),
            "total_evidence_id": entitlement.total_evidence_id,
            "total_evidence_sha256": entitlement.total_evidence_sha256,
        },
        "settlement_days": [_day_payload(day) for day in days],
        "lots": [
            {
                "lot_id": lot.lot_id,
                "acquired_on": lot.acquired_on.isoformat(),
                "acquisition_order": lot.acquisition_order,
                "origin": lot.origin.value,
                "acquired_quantity": _share_text(lot.acquired_quantity),
                "position_quantity_at_record_date": _share_text(
                    lot.position_quantity_at_record_date
                ),
                "record_date_quantity": _share_text(lot.record_date_quantity),
                "dividend_per_share": format(lot.dividend_per_share, "f"),
                "acquisition_evidence_id": lot.acquisition_evidence_id,
                "acquisition_evidence_sha256": lot.acquisition_evidence_sha256,
                "record_date_evidence_id": lot.record_date_evidence_id,
                "record_date_evidence_sha256": lot.record_date_evidence_sha256,
            }
            for lot in lot_evidence
        ],
        "dispositions": [
            {
                "disposition_id": row.disposition_id,
                "settlement_date": (
                    row.transfer_settlement_date.isoformat()
                    if row.transfer_settlement_date is not None
                    else None
                ),
                "quantity": _share_text(row.quantity),
                "transfer_evidence_id": row.transfer_evidence_id,
                "transfer_evidence_sha256": row.transfer_evidence_sha256,
            }
            for row in dispositions
        ],
    }


@dataclass(frozen=True, slots=True)
class DeferredDividendTaxSettlementBridgeResult:
    """Existing tax request plus its owner/asset and source-scope provenance."""

    account_id: int
    owner_user_id: int
    security_id: str
    asset_code: str
    corporate_action_id: str
    record_date: date
    complete_through: date
    record_date_ownership_snapshot_id: str
    record_date_ownership_snapshot_sha256: str
    settlement_date_rule_id: str
    settlement_date_rule_sha256: str
    settlement_calendar_id: str
    settlement_calendar_sha256: str
    source_revision_id: str
    source_revision_sha256: str
    history_snapshot_id: str
    history_snapshot_sha256: str
    request: DeferredDividendTaxRequest

    def __post_init__(self) -> None:
        """Ensure wrapper provenance and the legacy tax request remain aligned."""

        if type(self.request) is not DeferredDividendTaxRequest:
            _reject("bridge result requires the exact legacy tax request")
        self.request.__post_init__()
        _require_account_id(self.account_id, "bridge_result.account_id")
        _require_account_id(self.owner_user_id, "bridge_result.owner_user_id")
        _require_token(self.security_id, "bridge_result.security_id", 96)
        _require_token(self.asset_code, "bridge_result.asset_code", 96)
        _require_token(self.corporate_action_id, "bridge_result.corporate_action_id", 128)
        _require_date(self.record_date, "bridge_result.record_date")
        _require_date(self.complete_through, "bridge_result.complete_through")
        _require_token(
            self.record_date_ownership_snapshot_id,
            "record_date_ownership_snapshot_id",
            192,
        )
        _require_digest(
            self.record_date_ownership_snapshot_sha256,
            "record_date_ownership_snapshot_sha256",
        )
        for token, field_name in (
            (self.settlement_date_rule_id, "settlement_date_rule_id"),
            (self.settlement_calendar_id, "settlement_calendar_id"),
            (self.source_revision_id, "source_revision_id"),
            (self.history_snapshot_id, "history_snapshot_id"),
        ):
            _require_token(token, field_name, 192)
        for digest, field_name in (
            (self.settlement_date_rule_sha256, "settlement_date_rule_sha256"),
            (self.settlement_calendar_sha256, "settlement_calendar_sha256"),
            (self.source_revision_sha256, "source_revision_sha256"),
            (self.history_snapshot_sha256, "history_snapshot_sha256"),
        ):
            _require_digest(digest, field_name)
        if (
            self.account_id != self.request.account_id
            or self.security_id != self.request.security_id
            or self.corporate_action_id != self.request.corporate_action_id
            or self.record_date != self.request.record_date
            or self.complete_through != self.request.complete_through
            or self.history_snapshot_id != self.request.history_snapshot_id
            or self.history_snapshot_sha256 != self.request.history_snapshot_sha256
        ):
            _reject("bridge provenance wrapper differs from its tax request")


@dataclass(slots=True)
class _LotState:
    """Private FIFO work row used only while deriving the immutable tax facts."""

    lot_id: str
    acquired_on: date
    acquisition_order: int
    acquired_quantity: Decimal
    acquisition_evidence_id: str
    acquisition_evidence_sha256: str
    remaining_quantity: Decimal


def _apply_fifo_decrease(
    lots: list[_LotState],
    quantity: Decimal,
) -> None:
    """Consume one validated net decrease from the oldest available lots."""

    sold_remaining = quantity
    with localcontext() as context:
        context.prec = 80
        for lot in lots:
            if lot.remaining_quantity <= _ZERO or sold_remaining <= _ZERO:
                continue
            sold = min(lot.remaining_quantity, sold_remaining)
            lot.remaining_quantity -= sold
            sold_remaining -= sold
    if sold_remaining > _ZERO:
        _reject(
            "daily net decrease exceeds the complete FIFO position",
            _POSITION_INCOMPLETE,
        )


def _make_tax_lot(
    *,
    state: _LotState,
    history: QualifiedTaxSettlementHistory,
    record_position: Decimal,
    dividend_per_share: Decimal,
) -> TaxLotEvidence:
    """Build an existing tax lot with explicit acquisition and record-date evidence."""

    if (
        history.record_date_entitlement.kind
        is not RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS
    ):
        _reject("record-date entitlement rule is unsupported", _SCOPE_INVALID)
    record_evidence_id, record_evidence_sha256 = _record_date_evidence(
        history=history,
        lot_id=state.lot_id,
        quantity=record_position,
    )
    return TaxLotEvidence(
        account_id=history.account_id,
        security_id=history.security_id,
        lot_id=state.lot_id,
        acquired_on=state.acquired_on,
        acquisition_order=state.acquisition_order,
        origin=TaxLotOrigin.PURCHASE,
        acquired_quantity=state.acquired_quantity,
        acquisition_evidence_id=state.acquisition_evidence_id,
        acquisition_evidence_sha256=state.acquisition_evidence_sha256,
        record_date=history.record_date,
        position_quantity_at_record_date=record_position,
        record_date_quantity=record_position,
        record_date_evidence_id=record_evidence_id,
        record_date_evidence_sha256=record_evidence_sha256,
        dividend_per_share=dividend_per_share,
    )


def build_deferred_dividend_tax_history_request(
    history: QualifiedTaxSettlementHistory,
    *,
    target_settlement_date: date,
    corporate_action_id: str,
    dividend_per_share: Decimal,
) -> DeferredDividendTaxSettlementBridgeResult:
    """Build one complete-prefix request from explicit qualified settlement facts.

    The history and its date-rule/calendar identities must already have been
    authenticated and qualified by the trusted caller. This pure bridge never
    maps execution timestamps or release dates to settlement dates and does
    not choose a tax rule or source.
    """

    if type(history) is not QualifiedTaxSettlementHistory:
        _reject("tax bridge requires the exact qualified settlement history")
    history.__post_init__()
    if (
        history.record_date_entitlement.kind
        is not RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS
    ):
        _reject("record-date entitlement rule is unsupported", _SCOPE_INVALID)
    _require_date(target_settlement_date, "target_settlement_date")
    _require_token(corporate_action_id, "corporate_action_id", 128)
    if target_settlement_date <= history.record_date:
        _reject("target tax disposition must settle after the record date", _HISTORY_INCOMPLETE)
    target_index = next(
        (
            index
            for index, day in enumerate(history.settlement_days)
            if day.settlement_date == target_settlement_date
        ),
        None,
    )
    if target_index is None:
        _reject(
            "target settlement date is absent from complete session coverage", _HISTORY_INCOMPLETE
        )
    prefix_days = history.settlement_days[: target_index + 1]
    if prefix_days[-1].net_quantity_change >= _ZERO:
        _reject("target date must contain one net position decrease", _HISTORY_INCOMPLETE)
    prefix_dates = history.covered_session_dates[: target_index + 1]

    lots: list[_LotState] = []
    record_positions: dict[str, Decimal] = {}
    record_boundary_captured = False
    with localcontext() as context:
        context.prec = 80
        for day in prefix_days:
            if day.settlement_date > history.record_date and not record_boundary_captured:
                record_positions = {lot.lot_id: lot.remaining_quantity for lot in lots}
                record_boundary_captured = True
            net_change = day.net_quantity_change
            if net_change > _ZERO:
                lot_id = _purchase_lot_id(
                    account_id=history.account_id,
                    security_id=history.security_id,
                    settlement_date=day.settlement_date,
                )
                lots.append(
                    _LotState(
                        lot_id=lot_id,
                        acquired_on=day.settlement_date,
                        acquisition_order=1,
                        acquired_quantity=net_change,
                        acquisition_evidence_id=day.evidence_id,
                        acquisition_evidence_sha256=day.evidence_sha256,
                        remaining_quantity=net_change,
                    )
                )
            elif net_change < _ZERO:
                _apply_fifo_decrease(lots, -net_change)
        if not record_boundary_captured:
            record_positions = {lot.lot_id: lot.remaining_quantity for lot in lots}

    with localcontext() as context:
        context.prec = 80
        record_position_total = sum(record_positions.values(), start=_ZERO)
    if record_position_total != history.record_date_ownership_proof.eligible_quantity:
        _reject("derived record-date lots differ from ownership proof", _POSITION_INCOMPLETE)
    if (
        history.record_date_entitlement.kind
        is RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS
        and record_position_total != history.record_date_entitlement.qualified_total_quantity
    ):
        _reject("all-covered entitlement total differs from derived lot positions", _SCOPE_INVALID)

    lot_evidence: list[TaxLotEvidence] = []
    for state in lots:
        record_position = record_positions.get(state.lot_id, _ZERO)
        lot_evidence.append(
            _make_tax_lot(
                state=state,
                history=history,
                record_position=record_position,
                dividend_per_share=dividend_per_share,
            )
        )

    dispositions = tuple(
        TaxableDispositionEvidence(
            account_id=history.account_id,
            security_id=history.security_id,
            disposition_id=_sale_id(
                account_id=history.account_id,
                security_id=history.security_id,
                corporate_action_id=corporate_action_id,
                settlement_date=day.settlement_date,
            ),
            transfer_settlement_date=day.settlement_date,
            quantity=day.net_quantity_change.copy_negate(),
            transfer_evidence_id=day.evidence_id,
            transfer_evidence_sha256=day.evidence_sha256,
        )
        for day in prefix_days
        if day.settlement_date > history.record_date and day.net_quantity_change < _ZERO
    )
    target_disposition_id = _sale_id(
        account_id=history.account_id,
        security_id=history.security_id,
        corporate_action_id=corporate_action_id,
        settlement_date=target_settlement_date,
    )
    if not any(row.disposition_id == target_disposition_id for row in dispositions):
        _reject(
            "target settlement decrease is absent from the disposition prefix", _HISTORY_INCOMPLETE
        )

    record_date = history.record_date
    request_complete_through = target_settlement_date
    payload = _request_payload(
        history=history,
        days=prefix_days,
        lot_evidence=tuple(lot_evidence),
        dispositions=dispositions,
        corporate_action_id=corporate_action_id,
        target_settlement_date=target_settlement_date,
    )
    payload["calendar"] = {
        "id": history.settlement_calendar_id,
        "sha256": history.settlement_calendar_sha256,
        "covered_sessions": [day.isoformat() for day in prefix_dates],
    }
    snapshot_sha256 = _sha256_json(payload)
    snapshot_id = f"deferred-tax-history.v1:{snapshot_sha256}"
    request = DeferredDividendTaxRequest(
        account_id=history.account_id,
        security_id=history.security_id,
        corporate_action_id=corporate_action_id,
        record_date=record_date,
        target_disposition_id=target_disposition_id,
        complete_through=request_complete_through,
        history_complete=True,
        history_snapshot_id=snapshot_id,
        history_snapshot_sha256=snapshot_sha256,
        lots=tuple(lot_evidence),
        dispositions=dispositions,
    )
    return DeferredDividendTaxSettlementBridgeResult(
        account_id=history.account_id,
        owner_user_id=history.owner_user_id,
        security_id=history.security_id,
        asset_code=history.asset_code,
        corporate_action_id=corporate_action_id,
        record_date=record_date,
        complete_through=request_complete_through,
        record_date_ownership_snapshot_id=(
            history.record_date_ownership_proof.ownership_snapshot_id
        ),
        record_date_ownership_snapshot_sha256=(
            history.record_date_ownership_proof.ownership_snapshot_sha256
        ),
        settlement_date_rule_id=history.settlement_date_rule_id,
        settlement_date_rule_sha256=history.settlement_date_rule_sha256,
        settlement_calendar_id=history.settlement_calendar_id,
        settlement_calendar_sha256=history.settlement_calendar_sha256,
        source_revision_id=history.source_revision_id,
        source_revision_sha256=history.source_revision_sha256,
        history_snapshot_id=snapshot_id,
        history_snapshot_sha256=snapshot_sha256,
        request=request,
    )


__all__ = [
    "DeferredDividendTaxSettlementBridgeResult",
    "build_deferred_dividend_tax_history_request",
]
