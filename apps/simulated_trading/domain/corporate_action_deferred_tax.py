"""Pure, evidence-bound allocation for deferred dividend withholding.

Statutory rule selection, source qualification, persistence, and posting remain
outside this module. Callers inject the exact versioned policy and the complete
account/security evidence prefix through the target settlement date.
"""

from __future__ import annotations

import calendar
import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum

_ZERO = Decimal("0")
_ONE = Decimal("1")
_MAX_DECIMAL_INTEGER_DIGITS = 18
_MAX_DIVIDEND_PER_SHARE_SCALE = 12
_MAX_CURRENCY_QUANTUM_SCALE = 12
# Technical capacity across Python's date range, not a statutory holding band.
MAX_SUPPORTED_HOLDING_MONTHS = (
    (date.max.year - date.min.year) * 12 + date.max.month - date.min.month
)
_DIGEST_CHARACTERS = frozenset("0123456789abcdef")


class DeferredDividendTaxValidationError(ValueError):
    """Raised when a deferred dividend tax request is incomplete or ambiguous."""

    def __init__(self, message: str, code: str = "DEFERRED_DIVIDEND_TAX_INVALID") -> None:
        """Create a stable, classifiable domain validation error."""

        self.code = code
        super().__init__(message)


class TaxLotOrigin(StrEnum):
    """Origin classification for a retained acquisition lot."""

    PURCHASE = "purchase"
    TRANSFER_IN = "transfer_in"
    UNKNOWN = "unknown"


class TaxRoundingMode(StrEnum):
    """Supported Decimal rounding modes selected by an injected policy."""

    CEILING = "ROUND_CEILING"
    DOWN = "ROUND_DOWN"
    FLOOR = "ROUND_FLOOR"
    HALF_DOWN = "ROUND_HALF_DOWN"
    HALF_EVEN = "ROUND_HALF_EVEN"
    HALF_UP = "ROUND_HALF_UP"
    UP = "ROUND_UP"
    ZERO_FIVE_UP = "ROUND_05UP"


def _require_token(value: str | None, field_name: str, limit: int = 192) -> None:
    """Require a bounded stable identifier without whitespace."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(character.isspace() for character in value)
    ):
        raise DeferredDividendTaxValidationError(f"{field_name} is not a valid stable identifier")


def _require_digest(value: str | None, field_name: str) -> None:
    """Require an exact lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in _DIGEST_CHARACTERS for character in value)
    ):
        raise DeferredDividendTaxValidationError(
            f"{field_name} must be a lowercase SHA-256 digest",
            "DEFERRED_DIVIDEND_TAX_EVIDENCE_INVALID",
        )


def _require_date(value: date | None, field_name: str) -> date:
    """Require an exact calendar date, excluding datetime subclasses."""

    if type(value) is not date:
        raise DeferredDividendTaxValidationError(
            f"{field_name} must be an explicit calendar date",
            "DEFERRED_DIVIDEND_TAX_EVIDENCE_INVALID",
        )
    return value


def _require_account_id(value: int, field_name: str) -> None:
    """Require a positive, exact integer account identifier."""

    if type(value) is not int or value <= 0:
        raise DeferredDividendTaxValidationError(f"{field_name} must be a positive account id")


def _require_share_quantity(value: Decimal, field_name: str, allow_zero: bool) -> Decimal:
    """Require a finite share amount with bounded precision."""

    if type(value) is not Decimal or not value.is_finite():
        raise DeferredDividendTaxValidationError(f"{field_name} must be an exact Decimal")
    if value < _ZERO or (value == _ZERO and not allow_zero):
        qualifier = "nonnegative" if allow_zero else "positive"
        raise DeferredDividendTaxValidationError(f"{field_name} must be {qualifier}")
    exponent = value.as_tuple().exponent
    if (
        type(exponent) is not int
        or exponent < -6
        or exponent > _MAX_DECIMAL_INTEGER_DIGITS - 1
        or value.adjusted() >= _MAX_DECIMAL_INTEGER_DIGITS
    ):
        raise DeferredDividendTaxValidationError(
            f"{field_name} exceeds the supported share precision"
        )
    return value


def _require_unit_decimal(value: Decimal, field_name: str) -> None:
    """Require a finite ratio between zero and one inclusive."""

    if type(value) is not Decimal or not value.is_finite() or value < _ZERO or value > _ONE:
        raise DeferredDividendTaxValidationError(f"{field_name} must be a Decimal from zero to one")
    exponent = value.as_tuple().exponent
    if type(exponent) is not int or exponent < -12 or exponent > 0:
        raise DeferredDividendTaxValidationError(f"{field_name} precision is unsupported")


def _require_positive_money_quantum(value: Decimal) -> None:
    """Require a positive power-of-ten currency quantum."""

    if type(value) is not Decimal or not value.is_finite() or value <= _ZERO:
        raise DeferredDividendTaxValidationError("currency_quantum must be a positive Decimal")
    sign, digits, exponent = value.as_tuple()
    if (
        type(exponent) is not int
        or sign != 0
        or digits != (1,)
        or exponent > 0
        or exponent < -_MAX_CURRENCY_QUANTUM_SCALE
    ):
        raise DeferredDividendTaxValidationError(
            "currency_quantum must be a power of ten within supported scale"
        )


def _decimal_text(value: Decimal) -> str:
    """Serialize a Decimal without exponent notation for stable hashing."""

    return format(value, "f")


def _sha256_json(value: object) -> str:
    """Hash canonical JSON produced only from validated domain values."""

    serialized = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class HoldingPeriodTaxBand:
    """One injected inclusive natural-month holding band and its tax terms."""

    band_id: str
    maximum_holding_months: int | None
    taxable_dividend_ratio: Decimal
    withholding_rate: Decimal

    def __post_init__(self) -> None:
        """Validate the stable identifier, threshold, and injected ratios."""

        _require_token(self.band_id, "band_id", 96)
        if self.maximum_holding_months is not None and (
            type(self.maximum_holding_months) is not int
            or self.maximum_holding_months <= 0
            or self.maximum_holding_months > MAX_SUPPORTED_HOLDING_MONTHS
        ):
            raise DeferredDividendTaxValidationError(
                "maximum_holding_months must fit the supported calendar span or be None"
            )
        _require_unit_decimal(self.taxable_dividend_ratio, "taxable_dividend_ratio")
        _require_unit_decimal(self.withholding_rate, "withholding_rate")


@dataclass(frozen=True, slots=True)
class DeferredDividendTaxPolicy:
    """Versioned statutory terms selected by the caller for one record date.

    Effective dates, source identity and digest, holding bands, rates, taxable
    ratios, currency precision, and rounding mode are all explicit inputs.
    """

    policy_id: str
    version: str
    effective_from: date
    effective_through: date | None
    source_identity: str
    source_sha256: str
    bands: tuple[HoldingPeriodTaxBand, ...]
    currency_quantum: Decimal
    rounding_mode: TaxRoundingMode

    def __post_init__(self) -> None:
        """Reject incomplete policy source, date range, band, or rounding terms."""

        _require_token(self.policy_id, "policy_id", 96)
        _require_token(self.version, "version", 96)
        _require_token(self.source_identity, "source_identity", 192)
        _require_digest(self.source_sha256, "source_sha256")
        effective_from = _require_date(self.effective_from, "effective_from")
        if self.effective_through is not None:
            effective_through = _require_date(self.effective_through, "effective_through")
            if effective_through < effective_from:
                raise DeferredDividendTaxValidationError(
                    "policy effective_through precedes effective_from"
                )
        if type(self.bands) is not tuple or not self.bands:
            raise DeferredDividendTaxValidationError("policy bands must be a nonempty typed tuple")
        previous_maximum = 0
        band_ids: set[str] = set()
        for index, band in enumerate(self.bands):
            if type(band) is not HoldingPeriodTaxBand:
                raise DeferredDividendTaxValidationError("policy contains an untyped holding band")
            if band.band_id in band_ids:
                raise DeferredDividendTaxValidationError("policy contains duplicate band ids")
            band_ids.add(band.band_id)
            if band.maximum_holding_months is None:
                if index != len(self.bands) - 1:
                    raise DeferredDividendTaxValidationError(
                        "unbounded holding band must be the final band"
                    )
            elif band.maximum_holding_months <= previous_maximum:
                raise DeferredDividendTaxValidationError(
                    "holding-period band thresholds must be strictly increasing"
                )
            else:
                previous_maximum = band.maximum_holding_months
        if self.bands[-1].maximum_holding_months is not None:
            raise DeferredDividendTaxValidationError(
                "policy must include a final unbounded holding-period band"
            )
        _require_positive_money_quantum(self.currency_quantum)
        if type(self.rounding_mode) is not TaxRoundingMode:
            raise DeferredDividendTaxValidationError("rounding_mode must be explicitly selected")

    @property
    def policy_sha256(self) -> str:
        """Hash explicit policy terms; callers independently qualify the source."""

        return _sha256_json(
            {
                "policy_id": self.policy_id,
                "version": self.version,
                "effective_from": self.effective_from.isoformat(),
                "effective_through": (
                    self.effective_through.isoformat()
                    if self.effective_through is not None
                    else None
                ),
                "source_identity": self.source_identity,
                "source_sha256": self.source_sha256,
                "bands": [
                    {
                        "band_id": band.band_id,
                        "maximum_holding_months": band.maximum_holding_months,
                        "taxable_dividend_ratio": _decimal_text(band.taxable_dividend_ratio),
                        "withholding_rate": _decimal_text(band.withholding_rate),
                    }
                    for band in self.bands
                ],
                "currency_quantum": _decimal_text(self.currency_quantum),
                "rounding_mode": self.rounding_mode.value,
            }
        )


@dataclass(frozen=True, slots=True)
class TaxLotEvidence:
    """One acquisition batch with account-scoped record-date entitlement proof."""

    account_id: int
    security_id: str
    lot_id: str
    acquired_on: date
    acquisition_order: int
    origin: TaxLotOrigin
    acquired_quantity: Decimal
    acquisition_evidence_id: str | None
    acquisition_evidence_sha256: str | None
    record_date: date
    position_quantity_at_record_date: Decimal
    record_date_quantity: Decimal
    record_date_evidence_id: str | None
    record_date_evidence_sha256: str | None
    dividend_per_share: Decimal
    origin_transfer_evidence_id: str | None = None
    origin_transfer_evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        """Validate source references and exact lot quantities without guessing origin."""

        _require_account_id(self.account_id, "account_id")
        _require_token(self.security_id, "security_id", 96)
        _require_token(self.lot_id, "lot_id", 128)
        _require_date(self.acquired_on, "acquired_on")
        _require_date(self.record_date, "record_date")
        if type(self.acquisition_order) is not int or self.acquisition_order <= 0:
            raise DeferredDividendTaxValidationError("acquisition_order must be positive")
        if type(self.origin) is not TaxLotOrigin:
            raise DeferredDividendTaxValidationError("lot origin must be explicitly classified")
        _require_share_quantity(self.acquired_quantity, "acquired_quantity", allow_zero=False)
        _require_share_quantity(
            self.position_quantity_at_record_date,
            "position_quantity_at_record_date",
            allow_zero=True,
        )
        _require_share_quantity(self.record_date_quantity, "record_date_quantity", allow_zero=True)
        if self.position_quantity_at_record_date > self.acquired_quantity:
            raise DeferredDividendTaxValidationError(
                "record-date position exceeds the acquisition lot quantity"
            )
        if self.record_date_quantity > self.position_quantity_at_record_date:
            raise DeferredDividendTaxValidationError(
                "record-date entitlement exceeds the account position on the record date"
            )
        if self.acquired_on > self.record_date and (
            self.position_quantity_at_record_date != _ZERO or self.record_date_quantity != _ZERO
        ):
            raise DeferredDividendTaxValidationError(
                "a post-record-date acquisition cannot carry record-date position or entitlement"
            )
        if type(self.dividend_per_share) is not Decimal or not self.dividend_per_share.is_finite():
            raise DeferredDividendTaxValidationError("dividend_per_share must be a finite Decimal")
        if self.dividend_per_share < _ZERO:
            raise DeferredDividendTaxValidationError("dividend_per_share cannot be negative")
        exponent = self.dividend_per_share.as_tuple().exponent
        if (
            type(exponent) is not int
            or exponent < -_MAX_DIVIDEND_PER_SHARE_SCALE
            or exponent > _MAX_DECIMAL_INTEGER_DIGITS - 1
            or self.dividend_per_share.adjusted() >= _MAX_DECIMAL_INTEGER_DIGITS
        ):
            raise DeferredDividendTaxValidationError(
                "dividend_per_share exceeds supported exact decimal precision"
            )
        for value, field_name in (
            (self.acquisition_evidence_id, "acquisition_evidence_id"),
            (self.record_date_evidence_id, "record_date_evidence_id"),
        ):
            _require_token(value, field_name)
        for value, field_name in (
            (self.acquisition_evidence_sha256, "acquisition_evidence_sha256"),
            (self.record_date_evidence_sha256, "record_date_evidence_sha256"),
        ):
            _require_digest(value, field_name)
        if self.origin_transfer_evidence_id is not None:
            _require_token(self.origin_transfer_evidence_id, "origin_transfer_evidence_id")
        if self.origin_transfer_evidence_sha256 is not None:
            _require_digest(self.origin_transfer_evidence_sha256, "origin_transfer_evidence_sha256")
        if (self.origin_transfer_evidence_id is None) != (
            self.origin_transfer_evidence_sha256 is None
        ):
            raise DeferredDividendTaxValidationError(
                "origin transfer evidence requires both its identity and digest"
            )


@dataclass(frozen=True, slots=True)
class TaxableDispositionEvidence:
    """One daily net position decrease with an explicit transfer settlement date."""

    account_id: int
    security_id: str
    disposition_id: str
    transfer_settlement_date: date | None
    quantity: Decimal
    transfer_evidence_id: str | None
    transfer_evidence_sha256: str | None

    def __post_init__(self) -> None:
        """Require complete, account-scoped transfer evidence and settlement date."""

        _require_account_id(self.account_id, "account_id")
        _require_token(self.security_id, "security_id", 96)
        _require_token(self.disposition_id, "disposition_id", 128)
        _require_date(self.transfer_settlement_date, "transfer settlement date")
        _require_share_quantity(self.quantity, "disposition.quantity", allow_zero=False)
        _require_token(self.transfer_evidence_id, "transfer_evidence_id")
        _require_digest(self.transfer_evidence_sha256, "transfer_evidence_sha256")


@dataclass(frozen=True, slots=True)
class DeferredDividendTaxRequest:
    """Complete per-account event evidence prefix through one disposition."""

    account_id: int
    security_id: str
    corporate_action_id: str
    record_date: date
    target_disposition_id: str
    complete_through: date
    history_complete: bool
    history_snapshot_id: str
    history_snapshot_sha256: str
    lots: tuple[TaxLotEvidence, ...]
    dispositions: tuple[TaxableDispositionEvidence, ...]

    def __post_init__(self) -> None:
        """Validate request scope and complete-history attestation fields."""

        _require_account_id(self.account_id, "account_id")
        _require_token(self.security_id, "security_id", 96)
        _require_token(self.corporate_action_id, "corporate_action_id", 128)
        _require_date(self.record_date, "record_date")
        _require_token(self.target_disposition_id, "target_disposition_id", 128)
        _require_date(self.complete_through, "complete_through")
        if type(self.history_complete) is not bool:
            raise DeferredDividendTaxValidationError("history_complete must be an explicit boolean")
        _require_token(self.history_snapshot_id, "history_snapshot_id", 128)
        _require_digest(self.history_snapshot_sha256, "history_snapshot_sha256")
        if type(self.lots) is not tuple or not self.lots:
            raise DeferredDividendTaxValidationError("complete acquisition history cannot be empty")
        if type(self.dispositions) is not tuple or not self.dispositions:
            raise DeferredDividendTaxValidationError("complete disposition history cannot be empty")


@dataclass(frozen=True, slots=True)
class TaxLotAllocation:
    """One FIFO lot slice; contribution amounts remain unrounded and auditable."""

    lot_id: str
    sold_quantity: Decimal
    entitled_quantity: Decimal
    acquired_on: date
    holding_period_end: date
    holding_period_months: int
    holding_period_band_id: str
    gross_dividend_contribution: Decimal
    taxable_dividend_contribution: Decimal
    withholding_contribution: Decimal


@dataclass(frozen=True, slots=True)
class DeferredDividendTaxAssessment:
    """Deterministic result bound to one event, sale batch, policy, and evidence prefix."""

    account_id: int
    security_id: str
    corporate_action_id: str
    record_date: date
    disposition_id: str
    settlement_date: date
    policy_id: str
    policy_version: str
    policy_sha256: str
    evidence_sha256: str
    idempotency_key: str
    allocations: tuple[TaxLotAllocation, ...]
    gross_dividend_amount: Decimal
    taxable_dividend_amount: Decimal
    withholding_amount: Decimal
    assessment_sha256: str


def _add_calendar_months(day: date, month_count: int) -> date | None:
    """Return a representable clamped anniversary, or None beyond date limits."""

    month_index = (day.year * 12) + (day.month - 1) + month_count
    target_year, target_month_index = divmod(month_index, 12)
    if target_year < date.min.year or target_year > date.max.year:
        return None
    target_month = target_month_index + 1
    target_day = min(day.day, calendar.monthrange(target_year, target_month)[1])
    return date(target_year, target_month, target_day)


def _completed_calendar_months(acquired_on: date, settlement_date: date) -> int:
    """Count complete calendar months in the interval ending at settlement."""

    if settlement_date < acquired_on:
        raise DeferredDividendTaxValidationError(
            "transfer settlement precedes the supported acquisition date"
        )
    month_count = ((settlement_date.year - acquired_on.year) * 12) + (
        settlement_date.month - acquired_on.month
    )
    if month_count < 0:
        return 0
    anniversary = _add_calendar_months(acquired_on, month_count)
    while month_count > 0 and (anniversary is None or anniversary > settlement_date):
        month_count -= 1
        anniversary = _add_calendar_months(acquired_on, month_count)
    while True:
        next_anniversary = _add_calendar_months(acquired_on, month_count + 1)
        if next_anniversary is None or next_anniversary > settlement_date:
            break
        month_count += 1
    return month_count


def _select_band(
    acquired_on: date,
    settlement_date: date,
    bands: tuple[HoldingPeriodTaxBand, ...],
) -> tuple[HoldingPeriodTaxBand, int]:
    """Select the first injected band covering the acquisition-to-settlement interval."""

    months_held = _completed_calendar_months(acquired_on, settlement_date)
    for band in bands:
        maximum_months = band.maximum_holding_months
        anniversary = (
            _add_calendar_months(acquired_on, maximum_months)
            if maximum_months is not None
            else None
        )
        if maximum_months is None or anniversary is None or settlement_date <= anniversary:
            return band, months_held
    raise DeferredDividendTaxValidationError(
        "policy bands do not cover the lot holding period",
        "DEFERRED_DIVIDEND_TAX_POLICY_INVALID",
    )


def _validate_request(
    request: DeferredDividendTaxRequest,
    policy: DeferredDividendTaxPolicy,
) -> tuple[
    TaxableDispositionEvidence, tuple[TaxLotEvidence, ...], tuple[TaxableDispositionEvidence, ...]
]:
    """Check policy applicability, evidence completeness, scope, and replay order."""

    if type(request) is not DeferredDividendTaxRequest:
        raise DeferredDividendTaxValidationError("request must be an exact typed request")
    if type(policy) is not DeferredDividendTaxPolicy:
        raise DeferredDividendTaxValidationError(
            "policy must be an exact injected statutory policy"
        )
    if request.record_date < policy.effective_from or (
        policy.effective_through is not None and request.record_date > policy.effective_through
    ):
        raise DeferredDividendTaxValidationError(
            "record date is outside the injected policy effective window",
            "DEFERRED_DIVIDEND_TAX_POLICY_NOT_APPLICABLE",
        )
    if not request.history_complete:
        raise DeferredDividendTaxValidationError(
            "complete history through the target settlement date is required",
            "DEFERRED_DIVIDEND_TAX_HISTORY_INCOMPLETE",
        )
    if type(request.lots) is not tuple or not request.lots:
        raise DeferredDividendTaxValidationError("complete acquisition history cannot be empty")
    if type(request.dispositions) is not tuple or not request.dispositions:
        raise DeferredDividendTaxValidationError("complete disposition history cannot be empty")

    lots: list[TaxLotEvidence] = []
    lot_ids: set[str] = set()
    acquisition_orders: set[tuple[date, int]] = set()
    for lot in request.lots:
        if type(lot) is not TaxLotEvidence:
            raise DeferredDividendTaxValidationError("acquisition history contains an untyped lot")
        if lot.account_id != request.account_id or lot.security_id != request.security_id:
            raise DeferredDividendTaxValidationError(
                "acquisition history crosses account or security scope"
            )
        if lot.record_date != request.record_date:
            raise DeferredDividendTaxValidationError(
                "record-date entitlement evidence does not match the corporate action"
            )
        if lot.acquired_on > request.complete_through:
            raise DeferredDividendTaxValidationError(
                "acquisition history extends beyond the complete-through date"
            )
        if lot.origin is TaxLotOrigin.UNKNOWN:
            raise DeferredDividendTaxValidationError(
                "unknown acquisition origin blocks tax-basis calculation",
                "DEFERRED_DIVIDEND_TAX_ORIGIN_UNKNOWN",
            )
        if lot.origin is TaxLotOrigin.TRANSFER_IN:
            if (
                lot.origin_transfer_evidence_id is None
                or lot.origin_transfer_evidence_sha256 is None
            ):
                raise DeferredDividendTaxValidationError(
                    "transfer-in lot lacks complete origin-chain evidence",
                    "DEFERRED_DIVIDEND_TAX_ORIGIN_UNKNOWN",
                )
            raise DeferredDividendTaxValidationError(
                "transfer-in lot requires a separately qualified carryover policy",
                "DEFERRED_DIVIDEND_TAX_TRANSFER_UNSUPPORTED",
            )
        lot.__post_init__()
        order_key = (lot.acquired_on, lot.acquisition_order)
        if lot.lot_id in lot_ids:
            raise DeferredDividendTaxValidationError(
                "acquisition history contains duplicate lot ids"
            )
        if order_key in acquisition_orders:
            raise DeferredDividendTaxValidationError(
                "acquisition order is ambiguous within one calendar date"
            )
        lot_ids.add(lot.lot_id)
        acquisition_orders.add(order_key)
        lots.append(lot)

    dispositions: list[TaxableDispositionEvidence] = []
    disposition_ids: set[str] = set()
    settlement_dates: set[date] = set()
    for disposition in request.dispositions:
        if type(disposition) is not TaxableDispositionEvidence:
            raise DeferredDividendTaxValidationError(
                "disposition history contains an untyped transfer row"
            )
        if (
            disposition.account_id != request.account_id
            or disposition.security_id != request.security_id
        ):
            raise DeferredDividendTaxValidationError(
                "disposition history crosses account or security scope"
            )
        disposition.__post_init__()
        settlement_date = disposition.transfer_settlement_date
        if settlement_date is None:
            raise DeferredDividendTaxValidationError(
                "transfer settlement date is unknown",
                "DEFERRED_DIVIDEND_TAX_SETTLEMENT_UNKNOWN",
            )
        if settlement_date <= request.record_date:
            raise DeferredDividendTaxValidationError(
                "disposition on or before record date requires a separately qualified entitlement"
            )
        if settlement_date > request.complete_through:
            raise DeferredDividendTaxValidationError(
                "disposition history exceeds its complete-through date"
            )
        if disposition.disposition_id in disposition_ids:
            raise DeferredDividendTaxValidationError(
                "disposition history contains duplicate disposition ids",
                "DEFERRED_DIVIDEND_TAX_DUPLICATE_DISPOSITION",
            )
        if settlement_date in settlement_dates:
            raise DeferredDividendTaxValidationError(
                "multiple rows on one settlement date must be netted before FIFO allocation"
            )
        disposition_ids.add(disposition.disposition_id)
        settlement_dates.add(settlement_date)
        dispositions.append(disposition)

    if request.target_disposition_id not in disposition_ids:
        raise DeferredDividendTaxValidationError(
            "target disposition is absent from the history prefix"
        )
    try:
        ordered_dispositions = tuple(
            sorted(
                dispositions,
                key=lambda row: (
                    row.transfer_settlement_date or date.min,
                    row.disposition_id,
                ),
            )
        )
    except (TypeError, ValueError) as error:
        raise DeferredDividendTaxValidationError("disposition history cannot be ordered") from error
    target = ordered_dispositions[-1]
    if target.disposition_id != request.target_disposition_id:
        raise DeferredDividendTaxValidationError(
            "target disposition must end the complete replay prefix"
        )
    if target.transfer_settlement_date != request.complete_through:
        raise DeferredDividendTaxValidationError(
            "complete-through date must equal the target settlement date"
        )
    return target, tuple(lots), ordered_dispositions


def _evidence_sha256(
    request: DeferredDividendTaxRequest,
    lots: tuple[TaxLotEvidence, ...],
    dispositions: tuple[TaxableDispositionEvidence, ...],
) -> str:
    """Digest the complete, normalized source evidence used in an assessment."""

    return _sha256_json(
        {
            "account_id": request.account_id,
            "security_id": request.security_id,
            "corporate_action_id": request.corporate_action_id,
            "record_date": request.record_date.isoformat(),
            "target_disposition_id": request.target_disposition_id,
            "complete_through": request.complete_through.isoformat(),
            "history_snapshot_id": request.history_snapshot_id,
            "history_snapshot_sha256": request.history_snapshot_sha256,
            "lots": [
                {
                    "account_id": lot.account_id,
                    "security_id": lot.security_id,
                    "lot_id": lot.lot_id,
                    "acquired_on": lot.acquired_on.isoformat(),
                    "acquisition_order": lot.acquisition_order,
                    "origin": lot.origin.value,
                    "acquired_quantity": _decimal_text(lot.acquired_quantity),
                    "acquisition_evidence_id": lot.acquisition_evidence_id,
                    "acquisition_evidence_sha256": lot.acquisition_evidence_sha256,
                    "record_date": lot.record_date.isoformat(),
                    "position_quantity_at_record_date": _decimal_text(
                        lot.position_quantity_at_record_date
                    ),
                    "record_date_quantity": _decimal_text(lot.record_date_quantity),
                    "record_date_evidence_id": lot.record_date_evidence_id,
                    "record_date_evidence_sha256": lot.record_date_evidence_sha256,
                    "dividend_per_share": _decimal_text(lot.dividend_per_share),
                    "origin_transfer_evidence_id": lot.origin_transfer_evidence_id,
                    "origin_transfer_evidence_sha256": lot.origin_transfer_evidence_sha256,
                }
                for lot in sorted(lots, key=lambda row: (row.acquired_on, row.acquisition_order))
            ],
            "dispositions": [
                {
                    "account_id": row.account_id,
                    "security_id": row.security_id,
                    "disposition_id": row.disposition_id,
                    "transfer_settlement_date": (
                        row.transfer_settlement_date.isoformat()
                        if row.transfer_settlement_date is not None
                        else None
                    ),
                    "quantity": _decimal_text(row.quantity),
                    "transfer_evidence_id": row.transfer_evidence_id,
                    "transfer_evidence_sha256": row.transfer_evidence_sha256,
                }
                for row in dispositions
            ],
        }
    )


def calculate_deferred_dividend_tax(
    request: DeferredDividendTaxRequest,
    policy: DeferredDividendTaxPolicy,
) -> DeferredDividendTaxAssessment:
    """Calculate one deterministic FIFO withholding assessment from complete evidence.

    The replay starts with qualified holdings on the record date, adds verified
    later purchase lots, and applies one day-net disposition per settlement date.
    Transfer-in lots and unknown acquisition origins block calculation. The caller
    is responsible for selecting and retaining the applicable statutory policy.
    """

    target, lots, dispositions = _validate_request(request, policy)
    settlement_date = target.transfer_settlement_date
    if settlement_date is None:
        raise DeferredDividendTaxValidationError(
            "transfer settlement date is unknown",
            "DEFERRED_DIVIDEND_TAX_SETTLEMENT_UNKNOWN",
        )
    ordered_lots = tuple(sorted(lots, key=lambda row: (row.acquired_on, row.acquisition_order)))
    remaining_shares: dict[str, Decimal] = {
        lot.lot_id: (
            lot.position_quantity_at_record_date
            if lot.acquired_on <= request.record_date
            else _ZERO
        )
        for lot in ordered_lots
    }
    remaining_entitlement: dict[str, Decimal] = {
        lot.lot_id: lot.record_date_quantity for lot in ordered_lots
    }
    activated_lot_ids: set[str] = {
        lot.lot_id for lot in ordered_lots if lot.acquired_on <= request.record_date
    }
    target_allocations: list[TaxLotAllocation] = []

    with localcontext() as context:
        # Bounded shares (18 integer/6 fractional), per-share amounts (18/12),
        # and two unit ratios (12 fractional) require at most 78 exact digits.
        context.prec = 80
        for disposition in dispositions:
            disposition_settlement_date = disposition.transfer_settlement_date
            if disposition_settlement_date is None:
                raise DeferredDividendTaxValidationError(
                    "transfer settlement date is unknown",
                    "DEFERRED_DIVIDEND_TAX_SETTLEMENT_UNKNOWN",
                )
            same_day_acquisitions = tuple(
                lot
                for lot in ordered_lots
                if lot.acquired_on > request.record_date
                and lot.acquired_on == disposition_settlement_date
            )
            if same_day_acquisitions:
                raise DeferredDividendTaxValidationError(
                    "same-day acquisition and disposition require qualified day-end net evidence",
                    "DEFERRED_DIVIDEND_TAX_SAME_DAY_NET_UNKNOWN",
                )
            for lot in ordered_lots:
                if (
                    lot.lot_id not in activated_lot_ids
                    and lot.acquired_on < disposition_settlement_date
                ):
                    remaining_shares[lot.lot_id] = lot.acquired_quantity
                    activated_lot_ids.add(lot.lot_id)
            sold_remaining = disposition.quantity
            is_target = disposition.disposition_id == request.target_disposition_id
            for lot in ordered_lots:
                lot_balance = remaining_shares[lot.lot_id]
                if lot_balance <= _ZERO or sold_remaining <= _ZERO:
                    continue
                sold_from_lot = min(lot_balance, sold_remaining)
                entitled_quantity = min(remaining_entitlement[lot.lot_id], sold_from_lot)
                remaining_shares[lot.lot_id] = lot_balance - sold_from_lot
                remaining_entitlement[lot.lot_id] -= entitled_quantity
                sold_remaining -= sold_from_lot
                if not is_target:
                    continue
                held_through = settlement_date - timedelta(days=1)
                band, months_held = _select_band(lot.acquired_on, settlement_date, policy.bands)
                gross_contribution = entitled_quantity * lot.dividend_per_share
                taxable_contribution = gross_contribution * band.taxable_dividend_ratio
                withholding_contribution = taxable_contribution * band.withholding_rate
                target_allocations.append(
                    TaxLotAllocation(
                        lot_id=lot.lot_id,
                        sold_quantity=sold_from_lot,
                        entitled_quantity=entitled_quantity,
                        acquired_on=lot.acquired_on,
                        holding_period_end=held_through,
                        holding_period_months=months_held,
                        holding_period_band_id=band.band_id,
                        gross_dividend_contribution=gross_contribution,
                        taxable_dividend_contribution=taxable_contribution,
                        withholding_contribution=withholding_contribution,
                    )
                )
            if sold_remaining > _ZERO:
                raise DeferredDividendTaxValidationError(
                    "disposition quantity exceeds available shares in complete FIFO history",
                    "DEFERRED_DIVIDEND_TAX_POSITION_INCOMPLETE",
                )

        gross_unrounded = sum(
            (row.gross_dividend_contribution for row in target_allocations),
            start=_ZERO,
        )
        taxable_unrounded = sum(
            (row.taxable_dividend_contribution for row in target_allocations),
            start=_ZERO,
        )
        withholding_unrounded = sum(
            (row.withholding_contribution for row in target_allocations),
            start=_ZERO,
        )
        try:
            gross_amount = gross_unrounded.quantize(
                policy.currency_quantum,
                rounding=policy.rounding_mode.value,
            )
            taxable_amount = taxable_unrounded.quantize(
                policy.currency_quantum,
                rounding=policy.rounding_mode.value,
            )
            withholding_amount = withholding_unrounded.quantize(
                policy.currency_quantum,
                rounding=policy.rounding_mode.value,
            )
        except (InvalidOperation, ValueError) as error:
            raise DeferredDividendTaxValidationError(
                "assessment amounts cannot be rounded under the injected policy"
            ) from error

    policy_sha256 = policy.policy_sha256
    evidence_sha256 = _evidence_sha256(request, lots, dispositions)
    idempotency_key = _sha256_json(
        {
            "account_id": request.account_id,
            "security_id": request.security_id,
            "corporate_action_id": request.corporate_action_id,
            "disposition_id": request.target_disposition_id,
        }
    )
    assessment_sha256 = _sha256_json(
        {
            "idempotency_key": idempotency_key,
            "policy_id": policy.policy_id,
            "policy_version": policy.version,
            "policy_sha256": policy_sha256,
            "evidence_sha256": evidence_sha256,
            "allocations": [
                {
                    "lot_id": row.lot_id,
                    "sold_quantity": _decimal_text(row.sold_quantity),
                    "entitled_quantity": _decimal_text(row.entitled_quantity),
                    "acquired_on": row.acquired_on.isoformat(),
                    "holding_period_end": row.holding_period_end.isoformat(),
                    "holding_period_months": row.holding_period_months,
                    "holding_period_band_id": row.holding_period_band_id,
                    "gross_dividend_contribution": _decimal_text(row.gross_dividend_contribution),
                    "taxable_dividend_contribution": _decimal_text(
                        row.taxable_dividend_contribution
                    ),
                    "withholding_contribution": _decimal_text(row.withholding_contribution),
                }
                for row in target_allocations
            ],
            "gross_dividend_amount": _decimal_text(gross_amount),
            "taxable_dividend_amount": _decimal_text(taxable_amount),
            "withholding_amount": _decimal_text(withholding_amount),
        }
    )
    return DeferredDividendTaxAssessment(
        account_id=request.account_id,
        security_id=request.security_id,
        corporate_action_id=request.corporate_action_id,
        record_date=request.record_date,
        disposition_id=request.target_disposition_id,
        settlement_date=settlement_date,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_sha256=policy_sha256,
        evidence_sha256=evidence_sha256,
        idempotency_key=idempotency_key,
        allocations=tuple(target_allocations),
        gross_dividend_amount=gross_amount,
        taxable_dividend_amount=taxable_amount,
        withholding_amount=withholding_amount,
        assessment_sha256=assessment_sha256,
    )


__all__ = [
    "DeferredDividendTaxAssessment",
    "DeferredDividendTaxPolicy",
    "DeferredDividendTaxRequest",
    "DeferredDividendTaxValidationError",
    "HoldingPeriodTaxBand",
    "MAX_SUPPORTED_HOLDING_MONTHS",
    "TaxLotAllocation",
    "TaxLotEvidence",
    "TaxLotOrigin",
    "TaxRoundingMode",
    "TaxableDispositionEvidence",
    "calculate_deferred_dividend_tax",
]
