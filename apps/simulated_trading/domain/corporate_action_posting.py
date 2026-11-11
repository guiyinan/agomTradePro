"""Exact domain contracts for simulated corporate-action posting stages.

This module contains no provider, ORM, calendar, or market-price integration.
Only explicit, source-qualified facts can be represented here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class CorporateActionInputValidationError(ValueError):
    """Raised when a corporate-action stage is incomplete or ambiguous."""

    def __init__(self, message: str, code: str = "CORPORATE_ACTION_INPUT_INVALID") -> None:
        self.code = code
        super().__init__(message)


class CorporateActionKind(StrEnum):
    """Supported corporate-action families."""

    CASH_DIVIDEND = "cash_dividend"
    SHARE_DISTRIBUTION = "share_distribution"
    RIGHTS_ISSUE = "rights_issue"
    UNKNOWN = "unknown"


class CorporateActionStage(StrEnum):
    """Economic or no-effect stage recorded in the simulated ledger."""

    CASH_ENTITLEMENT = "cash_entitlement"
    CASH_PAYMENT = "cash_payment"
    TAX_WITHHOLDING = "tax_withholding"
    SHARE_ENTITLEMENT = "share_entitlement"
    SHARE_DELIVERY = "share_delivery"
    SHARE_SELLABLE_RELEASE = "share_sellable_release"
    RIGHTS_NOT_EXERCISED = "rights_not_exercised"


class CorporateActionEntryKind(StrEnum):
    """Whether a row starts, reverses, replaces, or records no effect."""

    POSTING = "posting"
    REVERSAL = "reversal"
    SUCCESSOR = "successor"
    NO_EFFECT = "no_effect"


_SUPPORTED_ODD_LOT_POLICIES = frozenset({"whole_shares", "registry_final_quantity"})
_DIGEST_CHARACTERS = frozenset("0123456789abcdef")
_ZERO = Decimal("0")


def _require_digest(value: str | None, field_name: str) -> None:
    """Require an exact lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in _DIGEST_CHARACTERS for character in value)
    ):
        raise CorporateActionInputValidationError(
            f"{field_name} must be a lowercase SHA-256 digest",
            "CORPORATE_ACTION_EVIDENCE_INVALID",
        )


def _require_token(value: str, field_name: str, max_length: int = 192) -> None:
    """Require a bounded, non-empty identifier without surrounding whitespace."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > max_length
        or any(character.isspace() for character in value)
    ):
        raise CorporateActionInputValidationError(f"{field_name} is not a valid stable identifier")


def _require_aware(value: datetime, field_name: str) -> None:
    """Reject naive event clocks."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise CorporateActionInputValidationError(
            f"{field_name} must be timezone-aware",
            "CORPORATE_ACTION_EVIDENCE_INVALID",
        )


def _require_positive_money(value: Decimal | None, field_name: str) -> None:
    """Require positive cent-exact money."""

    if type(value) is not Decimal or not value.is_finite() or value <= _ZERO:
        raise CorporateActionInputValidationError(
            f"{field_name} must be positive and exact to cents"
        )
    exponent = value.as_tuple().exponent
    if type(exponent) is not int or exponent < -2:
        raise CorporateActionInputValidationError(
            f"{field_name} must be positive and exact to cents"
        )


def _require_positive_shares(value: Decimal | None) -> Decimal:
    """Require positive share quantity with at most six decimal places."""

    if type(value) is not Decimal or not value.is_finite() or value <= _ZERO:
        raise CorporateActionInputValidationError(
            "share amount must be positive and exact to six decimals"
        )
    exponent = value.as_tuple().exponent
    if type(exponent) is not int or exponent < -6:
        raise CorporateActionInputValidationError(
            "share amount must be positive and exact to six decimals"
        )
    return value


@dataclass(frozen=True, slots=True)
class CorporateActionStageRequest:
    """One explicit stage from a qualified public-source corporate-action record."""

    account_id: int
    owner_user_id: int
    security_id: str
    asset_code: str
    asset_name: str
    source_namespace: str
    source_record_id: str
    source_event_id: str
    source_revision_id: str
    source_payload_sha256: str
    qualification_sha256: str
    qualifier_identity: str
    source_observed_at: datetime
    qualified_at: datetime
    posted_at: datetime
    action_kind: CorporateActionKind
    stage: CorporateActionStage
    entry_kind: CorporateActionEntryKind
    record_date: date
    effective_date: date
    stage_date: date
    cash_amount: Decimal | None = None
    share_amount: Decimal | None = None
    payment_date: date | None = None
    sellable_date: date | None = None
    tax_treatment: str | None = None
    tax_rule_id: str | None = None
    tax_rule_sha256: str | None = None
    tax_basis_record_id: str | None = None
    tax_basis_sha256: str | None = None
    ownership_snapshot_id: str | None = None
    ownership_snapshot_sha256: str | None = None
    ownership_snapshot_as_of_date: date | None = None
    ownership_snapshot_observed_at: datetime | None = None
    eligible_quantity: Decimal | None = None
    entitlement_calculation_sha256: str | None = None
    rights_terms_sha256: str | None = None
    rights_election: str | None = None
    odd_lot_policy: str | None = None
    odd_lot_confirmation_sha256: str | None = None
    supersedes_revision_id: str | None = None
    reversal_of_entry_id: int | None = None

    def __post_init__(self) -> None:
        """Reject unsupported, under-specified, and non-exact stage terms."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
        ):
            raise CorporateActionInputValidationError("account identity is invalid")
        _require_token(self.source_revision_id, "source_revision_id", 192)
        if self.supersedes_revision_id is not None:
            _require_token(self.supersedes_revision_id, "supersedes_revision_id", 192)
            if self.supersedes_revision_id == self.source_revision_id:
                raise CorporateActionInputValidationError(
                    "a source revision cannot supersede itself"
                )
        for value, field_name, limit in (
            (self.security_id, "security_id", 96),
            (self.asset_code, "asset_code", 32),
            (self.source_namespace, "source_namespace", 128),
            (self.source_record_id, "source_record_id", 192),
            (self.source_event_id, "source_event_id", 192),
            (self.qualifier_identity, "qualifier_identity", 128),
        ):
            _require_token(value, field_name, limit)

        if (
            type(self.asset_name) is not str
            or not self.asset_name
            or self.asset_name != self.asset_name.strip()
            or len(self.asset_name) > 128
        ):
            raise CorporateActionInputValidationError("asset_name is invalid")
        if self.source_namespace != "exchange_official_disclosure":
            raise CorporateActionInputValidationError(
                "only a qualified official exchange disclosure namespace is accepted",
                "CORPORATE_ACTION_SOURCE_NOT_OFFICIAL",
            )
        _require_digest(self.source_payload_sha256, "source_payload_sha256")
        _require_digest(self.qualification_sha256, "qualification_sha256")
        _require_aware(self.source_observed_at, "source_observed_at")
        _require_aware(self.qualified_at, "qualified_at")
        _require_aware(self.posted_at, "posted_at")
        if not self.source_observed_at <= self.qualified_at <= self.posted_at:
            raise CorporateActionInputValidationError(
                "qualified source clocks are not ordered",
                "CORPORATE_ACTION_EVIDENCE_INVALID",
            )
        if any(
            type(value) is not date
            for value in (self.record_date, self.effective_date, self.stage_date)
        ):
            raise CorporateActionInputValidationError(
                "record, effective, and stage dates must be explicit dates"
            )
        if type(self.action_kind) is not CorporateActionKind:
            raise CorporateActionInputValidationError("unknown corporate-action type")
        if self.action_kind is CorporateActionKind.UNKNOWN:
            raise CorporateActionInputValidationError(
                "unknown corporate-action type is blocked",
                "CORPORATE_ACTION_UNKNOWN_TYPE",
            )
        if type(self.stage) is not CorporateActionStage:
            raise CorporateActionInputValidationError("unknown corporate-action stage")
        if type(self.entry_kind) is not CorporateActionEntryKind:
            raise CorporateActionInputValidationError("unknown corporate-action entry kind")

        compatible: dict[CorporateActionKind, frozenset[CorporateActionStage]] = {
            CorporateActionKind.CASH_DIVIDEND: frozenset(
                {
                    CorporateActionStage.CASH_ENTITLEMENT,
                    CorporateActionStage.CASH_PAYMENT,
                    CorporateActionStage.TAX_WITHHOLDING,
                }
            ),
            CorporateActionKind.SHARE_DISTRIBUTION: frozenset(
                {
                    CorporateActionStage.TAX_WITHHOLDING,
                    CorporateActionStage.SHARE_ENTITLEMENT,
                    CorporateActionStage.SHARE_DELIVERY,
                    CorporateActionStage.SHARE_SELLABLE_RELEASE,
                }
            ),
            CorporateActionKind.RIGHTS_ISSUE: frozenset(
                {CorporateActionStage.RIGHTS_NOT_EXERCISED}
            ),
        }
        if self.stage not in compatible[self.action_kind]:
            raise CorporateActionInputValidationError(
                "stage is incompatible with corporate-action type"
            )

        if self.entry_kind is CorporateActionEntryKind.REVERSAL:
            if (
                type(self.reversal_of_entry_id) is not int
                or self.reversal_of_entry_id <= 0
                or self.supersedes_revision_id is None
            ):
                raise CorporateActionInputValidationError(
                    "a correction reversal must identify the immediate predecessor stage"
                )
            if any(
                value is not None
                for value in (
                    self.cash_amount,
                    self.share_amount,
                    self.tax_treatment,
                    self.tax_rule_id,
                    self.tax_rule_sha256,
                    self.tax_basis_record_id,
                    self.tax_basis_sha256,
                    self.ownership_snapshot_id,
                    self.ownership_snapshot_sha256,
                    self.ownership_snapshot_as_of_date,
                    self.ownership_snapshot_observed_at,
                    self.eligible_quantity,
                    self.entitlement_calculation_sha256,
                    self.rights_terms_sha256,
                    self.rights_election,
                    self.odd_lot_policy,
                    self.odd_lot_confirmation_sha256,
                )
            ):
                raise CorporateActionInputValidationError(
                    "reversal economics must be derived from the immutable target entry"
                )
            return

        if self.reversal_of_entry_id is not None:
            raise CorporateActionInputValidationError(
                "only a reversal may reference a predecessor entry"
            )
        if self.entry_kind is CorporateActionEntryKind.POSTING:
            if self.supersedes_revision_id is not None:
                raise CorporateActionInputValidationError(
                    "an initial posting cannot supersede another source revision"
                )
        elif self.entry_kind is CorporateActionEntryKind.SUCCESSOR:
            if self.supersedes_revision_id is None:
                raise CorporateActionInputValidationError(
                    "successor entries must name their predecessor source revision"
                )
        elif self.entry_kind is CorporateActionEntryKind.NO_EFFECT:
            if self.action_kind is not CorporateActionKind.RIGHTS_ISSUE:
                raise CorporateActionInputValidationError(
                    "no-effect entries are reserved for unexercised rights"
                )
        else:
            raise CorporateActionInputValidationError("unsupported corporate-action entry kind")
        if self.entry_kind is CorporateActionEntryKind.NO_EFFECT:
            if (
                self.action_kind is not CorporateActionKind.RIGHTS_ISSUE
                or self.stage is not CorporateActionStage.RIGHTS_NOT_EXERCISED
                or self.rights_election != "not_exercised"
                or self.cash_amount is not None
                or self.share_amount is not None
                or self.tax_treatment is not None
                or self.tax_rule_id is not None
                or self.tax_rule_sha256 is not None
                or self.tax_basis_record_id is not None
                or self.tax_basis_sha256 is not None
                or self.odd_lot_policy is not None
                or self.odd_lot_confirmation_sha256 is not None
            ):
                raise CorporateActionInputValidationError(
                    "rights with no exercise require explicit known terms and a zero-effect election"
                )
            _require_digest(self.rights_terms_sha256, "rights_terms_sha256")
            if self.stage_date < self.record_date:
                raise CorporateActionInputValidationError(
                    "rights election predates the record date"
                )
            self._require_ownership_snapshot()
            return

        if self.rights_terms_sha256 is not None or self.rights_election is not None:
            raise CorporateActionInputValidationError(
                "rights-election terms are only valid for a no-effect rights stage"
            )

        if type(self.tax_treatment) is not str or self.tax_treatment not in {
            "not_applicable",
            "deferred_withholding",
        }:
            raise CorporateActionInputValidationError(
                "corporate-action tax treatment must be explicitly qualified",
                "CORPORATE_ACTION_TAX_TERMS_UNKNOWN",
            )

        if self.stage is CorporateActionStage.TAX_WITHHOLDING:
            _require_positive_money(self.cash_amount, "cash_amount")
            if (
                self.tax_treatment != "deferred_withholding"
                or self.share_amount is not None
                or type(self.tax_rule_id) is not str
                or not self.tax_rule_id
                or self.tax_rule_id != self.tax_rule_id.strip()
                or type(self.tax_basis_record_id) is not str
                or not self.tax_basis_record_id
                or self.tax_basis_record_id != self.tax_basis_record_id.strip()
            ):
                raise CorporateActionInputValidationError(
                    "withholding requires deferred treatment and a qualified tax-basis record",
                    "CORPORATE_ACTION_TAX_TERMS_UNKNOWN",
                )
            _require_digest(self.tax_rule_sha256, "tax_rule_sha256")
            _require_digest(self.tax_basis_sha256, "tax_basis_sha256")
            if self.stage_date < self.effective_date:
                raise CorporateActionInputValidationError(
                    "withholding predates the action effective date"
                )
            if any(
                value is not None
                for value in (
                    self.payment_date,
                    self.sellable_date,
                    self.ownership_snapshot_id,
                    self.ownership_snapshot_sha256,
                    self.ownership_snapshot_as_of_date,
                    self.ownership_snapshot_observed_at,
                    self.eligible_quantity,
                    self.entitlement_calculation_sha256,
                    self.odd_lot_policy,
                    self.odd_lot_confirmation_sha256,
                    self.rights_terms_sha256,
                    self.rights_election,
                )
            ):
                raise CorporateActionInputValidationError(
                    "withholding contains unrelated stage terms"
                )
            return

        if self.tax_rule_id is not None or self.tax_rule_sha256 is not None:
            raise CorporateActionInputValidationError(
                "legal tax rule provenance is only valid on a withholding stage",
                "CORPORATE_ACTION_TAX_TERMS_UNKNOWN",
            )
        if self.tax_basis_record_id is not None or self.tax_basis_sha256 is not None:
            raise CorporateActionInputValidationError(
                "tax-basis evidence is only valid for a withholding stage"
            )
        if self.stage in {
            CorporateActionStage.CASH_ENTITLEMENT,
            CorporateActionStage.CASH_PAYMENT,
        }:
            _require_positive_money(self.cash_amount, "cash_amount")
            if self.share_amount is not None:
                raise CorporateActionInputValidationError("cash stages cannot carry share amounts")
            if self.stage is CorporateActionStage.CASH_ENTITLEMENT:
                if self.stage_date < self.record_date:
                    raise CorporateActionInputValidationError(
                        "cash entitlement predates the record date"
                    )
                self._require_ownership_snapshot()
                if self.payment_date is not None:
                    raise CorporateActionInputValidationError(
                        "cash entitlement cannot be recorded as a cash payment"
                    )
            else:
                self._require_no_ownership_snapshot()
                if self.payment_date is None or type(self.payment_date) is not date:
                    raise CorporateActionInputValidationError(
                        "cash payment requires an explicit payment date"
                    )
                if self.stage_date < self.payment_date:
                    raise CorporateActionInputValidationError(
                        "cash payment cannot precede its qualified payment date"
                    )
            if (
                self.sellable_date is not None
                or self.odd_lot_policy is not None
                or self.odd_lot_confirmation_sha256 is not None
                or self.rights_terms_sha256 is not None
                or self.rights_election is not None
            ):
                raise CorporateActionInputValidationError(
                    "cash stage contains unrelated share or rights terms"
                )
        else:
            share_amount = _require_positive_shares(self.share_amount)
            if self.cash_amount is not None:
                raise CorporateActionInputValidationError("share stages cannot carry cash amounts")
            if self.stage is CorporateActionStage.SHARE_ENTITLEMENT:
                if self.stage_date < self.record_date:
                    raise CorporateActionInputValidationError(
                        "share entitlement predates the record date"
                    )
                self._require_ownership_snapshot()
                if self.sellable_date is not None:
                    raise CorporateActionInputValidationError(
                        "share entitlement cannot declare a delivery date"
                    )
            else:
                self._require_no_ownership_snapshot()
            if (
                type(self.odd_lot_policy) is not str
                or self.odd_lot_policy not in _SUPPORTED_ODD_LOT_POLICIES
            ):
                raise CorporateActionInputValidationError(
                    "odd-lot allocation terms are unknown",
                    "CORPORATE_ACTION_ODD_LOT_TERMS_UNKNOWN",
                )
            if self.odd_lot_policy == "whole_shares" and (
                share_amount != share_amount.to_integral_value()
            ):
                raise CorporateActionInputValidationError(
                    "fractional share allocation requires final registry confirmation",
                    "CORPORATE_ACTION_ODD_LOT_TERMS_UNKNOWN",
                )
            if self.odd_lot_policy == "registry_final_quantity":
                _require_digest(
                    self.odd_lot_confirmation_sha256,
                    "odd_lot_confirmation_sha256",
                )
                if share_amount != share_amount.to_integral_value():
                    raise CorporateActionInputValidationError(
                        "registry final quantity must be an exact whole-share allotment"
                    )
            elif self.odd_lot_confirmation_sha256 is not None:
                raise CorporateActionInputValidationError(
                    "registry confirmation is unexpected for the whole-share policy"
                )
            if self.payment_date is not None:
                raise CorporateActionInputValidationError(
                    "share stages cannot carry a cash payment date"
                )
            if self.stage is CorporateActionStage.SHARE_DELIVERY:
                if (
                    self.sellable_date is None
                    or type(self.sellable_date) is not date
                    or self.sellable_date < self.stage_date
                    or self.stage_date < self.effective_date
                ):
                    raise CorporateActionInputValidationError(
                        "share delivery requires an explicit sellable date"
                    )
            elif self.stage is CorporateActionStage.SHARE_SELLABLE_RELEASE:
                if (
                    self.sellable_date is None
                    or type(self.sellable_date) is not date
                    or self.stage_date < self.sellable_date
                ):
                    raise CorporateActionInputValidationError(
                        "share release requires a reached explicit sellable date"
                    )
            elif self.sellable_date is not None:
                raise CorporateActionInputValidationError(
                    "share entitlement cannot declare a sellable release"
                )

    def _require_ownership_snapshot(self) -> None:
        """Require the historical account position as known on the rights record date."""

        if (
            type(self.ownership_snapshot_id) is not str
            or not self.ownership_snapshot_id
            or self.ownership_snapshot_id != self.ownership_snapshot_id.strip()
            or type(self.ownership_snapshot_as_of_date) is not date
            or self.ownership_snapshot_as_of_date != self.record_date
            or type(self.eligible_quantity) is not Decimal
            or not self.eligible_quantity.is_finite()
            or self.eligible_quantity <= 0
            or type(self.ownership_snapshot_observed_at) is not datetime
            or self.ownership_snapshot_observed_at.tzinfo is None
            or self.ownership_snapshot_observed_at.utcoffset() is None
            or self.ownership_snapshot_observed_at > self.qualified_at
        ):
            raise CorporateActionInputValidationError(
                "a record-date account ownership snapshot is required; current holdings cannot substitute",
                "CORPORATE_ACTION_HISTORICAL_OWNERSHIP_UNKNOWN",
            )
        eligible_quantity = self.eligible_quantity
        if type(eligible_quantity) is not Decimal:
            raise CorporateActionInputValidationError(
                "a record-date account ownership snapshot is required; current holdings cannot substitute",
                "CORPORATE_ACTION_HISTORICAL_OWNERSHIP_UNKNOWN",
            )
        exponent = eligible_quantity.as_tuple().exponent
        if type(exponent) is not int or exponent < -6:
            raise CorporateActionInputValidationError(
                "a record-date account ownership snapshot is required; current holdings cannot substitute",
                "CORPORATE_ACTION_HISTORICAL_OWNERSHIP_UNKNOWN",
            )
        _require_digest(self.ownership_snapshot_sha256, "ownership_snapshot_sha256")
        _require_digest(
            self.entitlement_calculation_sha256,
            "entitlement_calculation_sha256",
        )

    def _require_no_ownership_snapshot(self) -> None:
        """Reject a current or unrelated ownership snapshot on later settlement stages."""

        if any(
            value is not None
            for value in (
                self.ownership_snapshot_id,
                self.ownership_snapshot_sha256,
                self.ownership_snapshot_as_of_date,
                self.ownership_snapshot_observed_at,
                self.eligible_quantity,
                self.entitlement_calculation_sha256,
            )
        ):
            raise CorporateActionInputValidationError(
                "settlement stages must reference their ledger entitlement, not current holdings"
            )

    @property
    def stage_key(self) -> str:
        """Return the stable source-revision stage identity."""

        return f"{self.entry_kind.value}:{self.stage.value}"

    @property
    def payload_sha256(self) -> str:
        """Return a canonical hash for idempotency and conflicting-replay detection."""

        values: dict[str, str | int | None] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(
                value, (CorporateActionKind, CorporateActionStage, CorporateActionEntryKind)
            ):
                values[item.name] = value.value
            elif isinstance(value, (datetime, date)):
                values[item.name] = value.isoformat()
            elif isinstance(value, Decimal):
                values[item.name] = format(value, "f")
            else:
                values[item.name] = value
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CorporateActionLedgerDelta:
    """Signed changes applied to account and position projections."""

    cash: Decimal = _ZERO
    cash_receivable: Decimal = _ZERO
    shares: Decimal = _ZERO
    share_receivable: Decimal = _ZERO
    available_shares: Decimal = _ZERO


def calculate_corporate_action_delta(
    request: CorporateActionStageRequest,
) -> CorporateActionLedgerDelta:
    """Calculate exact signed stage effects without touching prices or market value."""

    request.__post_init__()
    if request.entry_kind in {
        CorporateActionEntryKind.REVERSAL,
        CorporateActionEntryKind.NO_EFFECT,
    }:
        return CorporateActionLedgerDelta()
    if request.stage is CorporateActionStage.CASH_ENTITLEMENT:
        amount = request.cash_amount
        if amount is None:
            raise CorporateActionInputValidationError("cash entitlement amount is missing")
        return CorporateActionLedgerDelta(cash_receivable=amount)
    if request.stage is CorporateActionStage.CASH_PAYMENT:
        amount = request.cash_amount
        if amount is None:
            raise CorporateActionInputValidationError("cash payment amount is missing")
        return CorporateActionLedgerDelta(cash=amount, cash_receivable=-amount)
    if request.stage is CorporateActionStage.TAX_WITHHOLDING:
        amount = request.cash_amount
        if amount is None:
            raise CorporateActionInputValidationError("withholding amount is missing")
        return CorporateActionLedgerDelta(cash=-amount)
    if request.stage is CorporateActionStage.SHARE_ENTITLEMENT:
        amount = request.share_amount
        if amount is None:
            raise CorporateActionInputValidationError("share entitlement amount is missing")
        return CorporateActionLedgerDelta(share_receivable=amount)
    if request.stage is CorporateActionStage.SHARE_DELIVERY:
        amount = request.share_amount
        if amount is None:
            raise CorporateActionInputValidationError("share delivery amount is missing")
        return CorporateActionLedgerDelta(shares=amount, share_receivable=-amount)
    if request.stage is CorporateActionStage.SHARE_SELLABLE_RELEASE:
        amount = request.share_amount
        if amount is None:
            raise CorporateActionInputValidationError("sellable share amount is missing")
        return CorporateActionLedgerDelta(available_shares=amount)
    if request.stage is CorporateActionStage.RIGHTS_NOT_EXERCISED:
        return CorporateActionLedgerDelta()
    raise CorporateActionInputValidationError(
        "unknown corporate-action stage is blocked",
        "CORPORATE_ACTION_UNKNOWN_STAGE",
    )
