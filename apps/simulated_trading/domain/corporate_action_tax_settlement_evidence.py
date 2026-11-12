"""Explicit, complete settlement-day facts supplied by a trusted adapter.

These frozen values validate scope, dates, arithmetic, and coverage shape. They
do not authenticate a source, qualify a tax-date rule, or prove that a source
revision is current; only a trusted Application/Infrastructure composition may
construct them after those checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from enum import StrEnum

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
    TaxLotOrigin,
    _require_account_id,
    _require_date,
    _require_digest,
    _require_share_quantity,
    _require_token,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    OwnershipAnchorKind,
    OwnershipOpeningAnchor,
    RecordDateOwnershipProof,
)

_ZERO = Decimal("0.000000")
_HISTORY_INCOMPLETE = "DEFERRED_DIVIDEND_TAX_HISTORY_INCOMPLETE"
_SCOPE_INVALID = "DEFERRED_DIVIDEND_TAX_EVIDENCE_INVALID"
_UNSUPPORTED_ORIGIN = "DEFERRED_DIVIDEND_TAX_UNSUPPORTED_ORIGIN"


def _reject(message: str, code: str = _SCOPE_INVALID) -> None:
    """Raise one stable deferred-tax evidence validation error."""

    raise DeferredDividendTaxValidationError(message, code)


class RecordDateTaxEntitlementRuleKind(StrEnum):
    """Explicitly qualified record-date entitlement rules supported by this bridge."""

    ALL_COVERED_POSITIONS = "all_covered_positions"


@dataclass(frozen=True, slots=True)
class RecordDateTaxEntitlementEvidence:
    """Explicit rule and independently sourced aggregate dividend entitlement.

    ``ALL_COVERED_POSITIONS`` may be used only when a trusted adapter has
    qualified the announcement's class and account coverage. The aggregate
    number and rule reference are both retained; this DTO cannot confer that
    qualification itself.
    """

    kind: RecordDateTaxEntitlementRuleKind
    rule_source_id: str
    rule_source_sha256: str
    qualified_total_quantity: Decimal
    total_evidence_id: str
    total_evidence_sha256: str

    def __post_init__(self) -> None:
        """Validate the explicit entitlement rule, aggregate, and source seals."""

        if type(self.kind) is not RecordDateTaxEntitlementRuleKind:
            _reject("record-date entitlement rule must be explicitly selected")
        _require_token(self.rule_source_id, "rule_source_id")
        _require_digest(self.rule_source_sha256, "rule_source_sha256")
        _require_share_quantity(
            self.qualified_total_quantity,
            "qualified_total_quantity",
            allow_zero=True,
        )
        _require_token(self.total_evidence_id, "total_evidence_id")
        _require_digest(self.total_evidence_sha256, "total_evidence_sha256")


@dataclass(frozen=True, slots=True)
class TaxSettlementDayEvidence:
    """One exact account/security settlement-session opening, net, and close.

    Purchase and sale totals are source-qualified trade quantities for one
    explicit settlement date. The bridge applies only their signed daily net;
    it never infers a date from fill clocks or release timestamps.
    """

    account_id: int
    owner_user_id: int
    security_id: str
    asset_code: str
    settlement_date: date
    opening_eod_quantity: Decimal
    gross_purchase_quantity: Decimal
    gross_sale_quantity: Decimal
    non_trade_quantity_delta: Decimal
    closing_eod_quantity: Decimal
    purchase_origin: TaxLotOrigin
    evidence_id: str
    evidence_sha256: str
    source_revision_id: str
    source_revision_sha256: str

    def __post_init__(self) -> None:
        """Validate exact scoped facts and that trade net reconciles to EOD."""

        _require_account_id(self.account_id, "settlement_day.account_id")
        _require_account_id(self.owner_user_id, "settlement_day.owner_user_id")
        _require_token(self.security_id, "settlement_day.security_id", 96)
        _require_token(self.asset_code, "settlement_day.asset_code", 96)
        _require_date(self.settlement_date, "settlement_day.settlement_date")
        for value, field_name in (
            (self.opening_eod_quantity, "opening_eod_quantity"),
            (self.gross_purchase_quantity, "gross_purchase_quantity"),
            (self.gross_sale_quantity, "gross_sale_quantity"),
            (self.closing_eod_quantity, "closing_eod_quantity"),
        ):
            _require_share_quantity(value, f"settlement_day.{field_name}", allow_zero=True)
        if type(self.non_trade_quantity_delta) is not Decimal:
            _reject("non_trade_quantity_delta must be an exact Decimal")
        if not self.non_trade_quantity_delta.is_finite():
            _reject("non_trade_quantity_delta must be finite")
        _require_share_quantity(
            self.non_trade_quantity_delta.copy_abs(),
            "non_trade_quantity_delta",
            allow_zero=True,
        )
        if type(self.purchase_origin) is not TaxLotOrigin:
            _reject("daily purchase origin must be explicitly classified", _UNSUPPORTED_ORIGIN)
        if (
            self.gross_purchase_quantity > _ZERO
            and self.purchase_origin is not TaxLotOrigin.PURCHASE
        ):
            code = (
                "DEFERRED_DIVIDEND_TAX_TRANSFER_UNSUPPORTED"
                if self.purchase_origin is TaxLotOrigin.TRANSFER_IN
                else "DEFERRED_DIVIDEND_TAX_ORIGIN_UNKNOWN"
            )
            _reject("daily purchases lack a supported purchase origin", code)
        if self.non_trade_quantity_delta != _ZERO:
            _reject(
                "share changes without supported purchase/sale lot lineage are unsupported",
                _UNSUPPORTED_ORIGIN,
            )
        _require_token(self.evidence_id, "settlement_day.evidence_id")
        _require_digest(self.evidence_sha256, "settlement_day.evidence_sha256")
        _require_token(self.source_revision_id, "settlement_day.source_revision_id")
        _require_digest(self.source_revision_sha256, "settlement_day.source_revision_sha256")
        with localcontext() as context:
            context.prec = 80
            expected_close = (
                self.opening_eod_quantity
                + self.gross_purchase_quantity
                - self.gross_sale_quantity
                + self.non_trade_quantity_delta
            )
        if expected_close != self.closing_eod_quantity:
            _reject(
                "settlement-day net change does not reconcile to the EOD position",
                _HISTORY_INCOMPLETE,
            )

    @property
    def net_quantity_change(self) -> Decimal:
        """Return the signed purchase-minus-sale net for the explicit day."""

        with localcontext() as context:
            context.prec = 80
            return self.gross_purchase_quantity - self.gross_sale_quantity


@dataclass(frozen=True, slots=True)
class QualifiedTaxSettlementHistory:
    """Complete immutable settlement-session prefix for one record-date action.

    The session list must have been enumerated and source-qualified by the
    caller's injected calendar. A matching tuple/hash is an integrity check,
    not independent proof that the calendar or source is authentic/current.
    """

    account_id: int
    owner_user_id: int
    security_id: str
    asset_code: str
    record_date: date
    complete_through: date
    record_date_ownership_proof: RecordDateOwnershipProof
    opening_anchor: OwnershipOpeningAnchor
    settlement_date_rule_id: str
    settlement_date_rule_sha256: str
    settlement_calendar_id: str
    settlement_calendar_sha256: str
    source_revision_id: str
    source_revision_sha256: str
    covered_session_dates: tuple[date, ...]
    settlement_days: tuple[TaxSettlementDayEvidence, ...]
    record_date_entitlement: RecordDateTaxEntitlementEvidence

    def __post_init__(self) -> None:
        """Require one scoped, anchored, complete and arithmetically consistent prefix."""

        _require_account_id(self.account_id, "history.account_id")
        _require_account_id(self.owner_user_id, "history.owner_user_id")
        _require_token(self.security_id, "history.security_id", 96)
        _require_token(self.asset_code, "history.asset_code", 96)
        _require_date(self.record_date, "history.record_date")
        _require_date(self.complete_through, "history.complete_through")
        if self.complete_through <= self.record_date:
            _reject("complete-through date must be after record date", _HISTORY_INCOMPLETE)
        _require_token(self.settlement_date_rule_id, "settlement_date_rule_id")
        _require_digest(self.settlement_date_rule_sha256, "settlement_date_rule_sha256")
        _require_token(self.settlement_calendar_id, "settlement_calendar_id")
        _require_digest(self.settlement_calendar_sha256, "settlement_calendar_sha256")
        _require_token(self.source_revision_id, "source_revision_id")
        _require_digest(self.source_revision_sha256, "source_revision_sha256")

        proof = self.record_date_ownership_proof
        if type(proof) is not RecordDateOwnershipProof:
            _reject("history requires the exact record-date ownership proof")
        if (
            proof.account_id != self.account_id
            or proof.owner_user_id != self.owner_user_id
            or proof.security_id != self.security_id
            or proof.asset_code != self.asset_code
            or proof.record_date != self.record_date
            or proof.ownership_snapshot_as_of_date != self.record_date
        ):
            _reject("record-date ownership proof crosses scope or date", _SCOPE_INVALID)
        _require_share_quantity(
            proof.eligible_quantity,
            "record_date_ownership_proof.eligible_quantity",
            allow_zero=True,
        )
        _require_token(proof.ownership_snapshot_id, "ownership_snapshot_id", 192)
        _require_digest(proof.ownership_snapshot_sha256, "ownership_snapshot_sha256")
        _require_token(proof.cutoff_policy_id, "ownership_cutoff_policy_id")
        _require_digest(proof.cutoff_policy_sha256, "ownership_cutoff_policy_sha256")
        if (
            type(proof.record_date_end_exclusive) is not datetime
            or proof.record_date_end_exclusive.tzinfo is None
            or proof.record_date_end_exclusive.utcoffset() is None
            or type(proof.ownership_snapshot_observed_at) is not datetime
            or proof.ownership_snapshot_observed_at.tzinfo is None
            or proof.ownership_snapshot_observed_at.utcoffset() is None
        ):
            _reject("record-date ownership proof clocks must be aware")

        anchor = self.opening_anchor
        if type(anchor) is not OwnershipOpeningAnchor:
            _reject("history requires the exact immutable opening anchor", _SCOPE_INVALID)
        anchor.__post_init__()
        if (
            anchor.account_id != self.account_id
            or anchor.owner_user_id != self.owner_user_id
            or anchor.anchor_kind is not OwnershipAnchorKind.ZERO_ORIGIN
            or anchor.quantity != _ZERO
            or anchor.observed_at > proof.ownership_snapshot_observed_at
            or anchor.effective_at >= proof.record_date_end_exclusive
        ):
            _reject(
                "history opening anchor is missing, nonzero, or outside the record-date cutoff",
                _SCOPE_INVALID,
            )

        entitlement = self.record_date_entitlement
        if type(entitlement) is not RecordDateTaxEntitlementEvidence:
            _reject("record-date tax entitlement rule must be explicit")
        entitlement.__post_init__()
        if entitlement.qualified_total_quantity != proof.eligible_quantity:
            _reject(
                "qualified dividend entitlement total differs from record-date ownership",
                _SCOPE_INVALID,
            )

        if type(self.covered_session_dates) is not tuple or not self.covered_session_dates:
            _reject("complete settlement session dates are required", _HISTORY_INCOMPLETE)
        if any(type(day) is not date for day in self.covered_session_dates):
            _reject("settlement session dates must be exact calendar dates", _SCOPE_INVALID)
        if (
            tuple(sorted(set(self.covered_session_dates))) != self.covered_session_dates
            or self.covered_session_dates[-1] != self.complete_through
            or not any(day <= self.record_date for day in self.covered_session_dates)
        ):
            _reject("settlement calendar coverage is incomplete or unordered", _HISTORY_INCOMPLETE)
        if type(self.settlement_days) is not tuple or not self.settlement_days:
            _reject("complete settlement-day evidence is required", _HISTORY_INCOMPLETE)
        if any(type(day) is not TaxSettlementDayEvidence for day in self.settlement_days):
            _reject("settlement-day evidence must be an exact typed tuple", _SCOPE_INVALID)
        if tuple(day.settlement_date for day in self.settlement_days) != self.covered_session_dates:
            _reject(
                "settlement-day evidence is missing a covered session, including a zero-change day",
                _HISTORY_INCOMPLETE,
            )

        previous_close = _ZERO
        record_date_close: Decimal | None = None
        for day in self.settlement_days:
            day.__post_init__()
            if (
                day.account_id != self.account_id
                or day.owner_user_id != self.owner_user_id
                or day.security_id != self.security_id
                or day.asset_code != self.asset_code
            ):
                _reject(
                    "settlement-day evidence crosses owner/account/instrument scope", _SCOPE_INVALID
                )
            if (
                day.source_revision_id != self.source_revision_id
                or day.source_revision_sha256 != self.source_revision_sha256
            ):
                _reject(
                    "settlement-day source revision differs from the bound revision", _SCOPE_INVALID
                )
            if day.opening_eod_quantity != previous_close:
                _reject(
                    "settlement-day EOD quantities are not a continuous prefix", _HISTORY_INCOMPLETE
                )
            if day.settlement_date == self.record_date and (
                day.gross_purchase_quantity != _ZERO or day.gross_sale_quantity != _ZERO
            ):
                _reject(
                    "record-date trading is ambiguous for the ownership proof", _HISTORY_INCOMPLETE
                )
            previous_close = day.closing_eod_quantity
            if day.settlement_date <= self.record_date:
                record_date_close = day.closing_eod_quantity

        if record_date_close is None or record_date_close != proof.eligible_quantity:
            _reject(
                "record-date FIFO position differs from the verified ownership proof",
                _SCOPE_INVALID,
            )


__all__ = [
    "QualifiedTaxSettlementHistory",
    "RecordDateTaxEntitlementEvidence",
    "RecordDateTaxEntitlementRuleKind",
    "TaxSettlementDayEvidence",
]
