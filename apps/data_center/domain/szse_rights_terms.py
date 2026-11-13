"""Typed source facts for SZSE rights offerings and confirmed outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


def _is_security_code(value: object) -> bool:
    """Return whether value is exactly a six digit exchange code."""
    return (
        type(value) is str
        and len(value) == 6
        and all("0" <= character <= "9" for character in value)
    )


def _is_bounded_positive_decimal(value: Decimal) -> bool:
    """Reject non-finite, non-positive, or unbounded decimal source values."""
    if not value.is_finite() or value <= 0:
        return False
    parts = value.as_tuple()
    exponent = parts.exponent
    if not isinstance(exponent, int):
        return False
    if len(parts.digits) > 24 or abs(exponent) > 18:
        return False
    return -18 <= value.adjusted() <= 18


def _is_exact_cents(value: Decimal) -> bool:
    """Return whether a positive Decimal is exactly representable in cents."""
    parts = value.as_tuple()
    exponent = parts.exponent
    if not isinstance(exponent, int):
        return False
    digits = parts.digits
    while exponent < -2 and digits and digits[-1] == 0:
        digits = digits[:-1]
        exponent += 1
    return exponent >= -2


def _is_calendar_date(value: date) -> bool:
    """Reject datetime instances where a date-only source fact is required."""
    return isinstance(value, date) and not isinstance(value, datetime)


@dataclass(frozen=True)
class SzseRightsOfferingTerms:
    """Facts stated by one SZSE rights-offering source document."""

    source_security_code: str
    record_date: date
    subscription_start_date: date
    subscription_end_date: date
    offered_rights_per_ten: Decimal
    subscription_price_cny_per_share: Decimal

    def __post_init__(self) -> None:
        """Validate source facts without rounding or supplying defaults."""
        if not _is_security_code(self.source_security_code):
            raise ValueError("source security code must contain six ASCII digits")
        if not all(
            _is_calendar_date(value)
            for value in (
                self.record_date,
                self.subscription_start_date,
                self.subscription_end_date,
            )
        ):
            raise ValueError("rights offering dates must be date-only values")
        if self.subscription_start_date > self.subscription_end_date:
            raise ValueError("subscription dates must be an ordered inclusive range")
        if self.record_date > self.subscription_start_date:
            raise ValueError("record date cannot follow subscription start")
        if type(self.offered_rights_per_ten) is not Decimal or not (
            _is_bounded_positive_decimal(self.offered_rights_per_ten)
        ):
            raise ValueError("offered rights ratio must be a bounded positive Decimal")
        if type(self.subscription_price_cny_per_share) is not Decimal or not (
            _is_bounded_positive_decimal(self.subscription_price_cny_per_share)
            and _is_exact_cents(self.subscription_price_cny_per_share)
        ):
            raise ValueError("subscription price must be a positive exact CNY cent amount")


@dataclass(frozen=True)
class SzseRightsCompletionTerms:
    """Facts explicitly confirmed by a successful SZSE rights result notice."""

    source_security_code: str
    record_date: date
    subscription_end_date: date
    offered_rights_per_ten: Decimal
    subscription_price_cny_per_share: Decimal
    actual_aggregate_rights_per_ten: Decimal
    actual_ex_rights_date: date

    def __post_init__(self) -> None:
        """Validate independently stated offering and successful-result facts."""
        if not _is_security_code(self.source_security_code):
            raise ValueError("source security code must contain six ASCII digits")
        if not all(
            _is_calendar_date(value)
            for value in (
                self.record_date,
                self.subscription_end_date,
                self.actual_ex_rights_date,
            )
        ):
            raise ValueError("rights completion dates must be date-only values")
        if self.subscription_end_date < self.record_date:
            raise ValueError("subscription end date cannot precede the record date")
        if self.actual_ex_rights_date < self.subscription_end_date:
            raise ValueError("confirmed ex-rights date cannot precede subscription close")
        if type(self.offered_rights_per_ten) is not Decimal or not (
            _is_bounded_positive_decimal(self.offered_rights_per_ten)
        ):
            raise ValueError("offered rights ratio must be a bounded positive Decimal")
        if type(self.actual_aggregate_rights_per_ten) is not Decimal or not (
            _is_bounded_positive_decimal(self.actual_aggregate_rights_per_ten)
        ):
            raise ValueError("actual aggregate ratio must be a bounded positive Decimal")
        if type(self.subscription_price_cny_per_share) is not Decimal or not (
            _is_bounded_positive_decimal(self.subscription_price_cny_per_share)
            and _is_exact_cents(self.subscription_price_cny_per_share)
        ):
            raise ValueError("subscription price must be a positive exact CNY cent amount")
