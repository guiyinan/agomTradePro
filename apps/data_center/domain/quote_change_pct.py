"""Typed source candidates and exact evidence for quote change percentages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from apps.data_center.domain.contracts import QuoteMetricSourceContract

_QUOTE_CHANGE_PCT_STORAGE_DECIMAL_PLACES = 12
_QUOTE_CHANGE_PCT_STORAGE_FACTOR = 10**_QUOTE_CHANGE_PCT_STORAGE_DECIMAL_PLACES
_QUOTE_CHANGE_PCT_STORAGE_LIMIT = Fraction(10**26, 1)
_SQLITE_DECIMAL_SIGNIFICANT_DIGITS_LIMIT = 15


def _decimal_significant_digits(value: Decimal) -> int:
    """Count significant decimal digits after ignoring representation zeros."""

    digits = list(value.as_tuple().digits)
    while len(digits) > 1 and digits[0] == 0:
        digits.pop(0)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
    return len(digits)


def quote_change_pct_storage_value(value: Fraction) -> Decimal | None:
    """Return the exact quote metric value representable by the canonical DB field.

    The model stores twelve fractional places in a Decimal(38, 12) column.  A
    conservative fifteen-significant-digit ceiling keeps the same values exact
    on SQLite, which is used by local development and migration checks.
    """

    if abs(value) >= _QUOTE_CHANGE_PCT_STORAGE_LIMIT:
        return None
    storage_units = value * _QUOTE_CHANGE_PCT_STORAGE_FACTOR
    if storage_units.denominator != 1:
        return None
    stored_value = Decimal(f"{storage_units.numerator}e-{_QUOTE_CHANGE_PCT_STORAGE_DECIMAL_PLACES}")
    if (
        not stored_value.is_finite()
        or Fraction(stored_value) != value
        or _decimal_significant_digits(stored_value) > _SQLITE_DECIMAL_SIGNIFICANT_DIGITS_LIMIT
    ):
        return None
    return stored_value


@dataclass(frozen=True)
class QuoteChangePctCandidate:
    """One untrusted provider field candidate before catalog interpretation."""

    raw_value: str
    source_field: str
    origin: str
    provider_source: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.raw_value, str)
            or not self.raw_value.strip()
            or not isinstance(self.source_field, str)
            or not self.source_field.strip()
            or not isinstance(self.provider_source, str)
            or not self.provider_source.strip()
        ):
            raise ValueError(
                "QuoteChangePctCandidate raw_value, source_field, and provider_source are required"
            )
        if self.origin not in {"vendor_reported", "derived", "unknown"}:
            raise ValueError("QuoteChangePctCandidate origin is unsupported")


def _quote_metric_text(payload: Mapping[str, object], field_name: str) -> str:
    """Narrow one required text field from persisted metric evidence."""

    value = payload.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"Quote change_pct evidence {field_name} must be text")
    return value


@dataclass(frozen=True)
class QuoteChangePctEvidence:
    """Typed proof that one quote metric used an exact immutable source contract."""

    metric_value: Decimal
    source_value: str
    dataset_contract_key: str
    dataset_contract_version: str
    dataset_schema_version: str
    source_contract: QuoteMetricSourceContract
    source_contract_hash: str
    observed_at: datetime
    quote_source: str

    def __post_init__(self) -> None:
        if not isinstance(self.metric_value, Decimal) or not self.metric_value.is_finite():
            raise ValueError("QuoteChangePctEvidence.metric_value must be finite")
        if not isinstance(self.source_value, str) or not self.source_value.strip():
            raise ValueError("QuoteChangePctEvidence.source_value is required")
        for name, value in (
            ("dataset_contract_key", self.dataset_contract_key),
            ("dataset_contract_version", self.dataset_contract_version),
            ("dataset_schema_version", self.dataset_schema_version),
        ):
            if (
                not isinstance(value, str)
                or not value.strip()
                or value.strip().casefold() == "unknown"
            ):
                raise ValueError(f"QuoteChangePctEvidence.{name} is required")
        try:
            source_value = Decimal(self.source_value)
        except InvalidOperation as error:
            raise ValueError("QuoteChangePctEvidence.source_value must be decimal text") from error
        if not source_value.is_finite():
            raise ValueError("QuoteChangePctEvidence.source_value must be finite")
        expected_metric = Fraction(source_value) * Fraction(
            self.source_contract.scale_numerator,
            self.source_contract.scale_denominator,
        )
        if expected_metric != Fraction(self.metric_value):
            raise ValueError("QuoteChangePctEvidence value does not match source scaling")
        if self.source_contract.origin != "vendor_reported":
            raise ValueError("QuoteChangePctEvidence requires a vendor-reported source")
        if not isinstance(self.source_contract_hash, str) or (
            self.source_contract_hash != self.source_contract.content_hash
        ):
            raise ValueError("QuoteChangePctEvidence source contract hash mismatch")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("QuoteChangePctEvidence.observed_at must be timezone-aware")
        if not isinstance(self.quote_source, str) or not self.quote_source.strip():
            raise ValueError("QuoteChangePctEvidence.quote_source is required")

    def to_dict(self) -> dict[str, object]:
        """Return canonical JSON fields for publication and cache evidence."""

        return {
            **self.source_contract.to_dict(),
            "source_contract_hash": self.source_contract_hash,
            "observed_at": self.observed_at.isoformat(),
            "source_value": self.source_value,
            "dataset_contract_key": self.dataset_contract_key,
            "dataset_contract_version": self.dataset_contract_version,
            "dataset_schema_version": self.dataset_schema_version,
            "metric_value": format(self.metric_value, "f"),
            "quote_source": self.quote_source,
        }

    @classmethod
    def from_payload(cls, payload: object) -> QuoteChangePctEvidence:
        """Narrow a persisted quote-metric evidence object from a JSON boundary."""

        if not isinstance(payload, Mapping):
            raise ValueError("Quote change_pct source evidence must be an object")
        numerator = payload.get("scale_numerator")
        denominator = payload.get("scale_denominator")
        if type(numerator) is not int or type(denominator) is not int:
            raise ValueError("Quote change_pct source scale must use integer values")
        source_contract = QuoteMetricSourceContract(
            provider_source=_quote_metric_text(payload, "provider_source"),
            source_field=_quote_metric_text(payload, "source_field"),
            origin=_quote_metric_text(payload, "origin"),
            source_unit=_quote_metric_text(payload, "source_unit"),
            canonical_unit=_quote_metric_text(payload, "canonical_unit"),
            scale_numerator=numerator,
            scale_denominator=denominator,
            reference_session=_quote_metric_text(payload, "reference_session"),
            action_basis=_quote_metric_text(payload, "action_basis"),
        )
        observed_at_value = payload.get("observed_at")
        source_value = payload.get("source_value")
        dataset_contract_key = payload.get("dataset_contract_key")
        dataset_contract_version = payload.get("dataset_contract_version")
        dataset_schema_version = payload.get("dataset_schema_version")
        metric_value = payload.get("metric_value")
        source_contract_hash = payload.get("source_contract_hash")
        quote_source = payload.get("quote_source")
        if not isinstance(observed_at_value, str):
            raise ValueError("Quote change_pct evidence observed_at must be text")
        if not isinstance(source_value, str):
            raise ValueError("Quote change_pct evidence source_value must be text")
        if not isinstance(dataset_contract_key, str):
            raise ValueError("Quote change_pct evidence dataset_contract_key must be text")
        if not isinstance(dataset_contract_version, str):
            raise ValueError("Quote change_pct evidence dataset_contract_version must be text")
        if not isinstance(dataset_schema_version, str):
            raise ValueError("Quote change_pct evidence dataset_schema_version must be text")
        if not isinstance(metric_value, str):
            raise ValueError("Quote change_pct evidence metric_value must be text")
        if not isinstance(source_contract_hash, str):
            raise ValueError("Quote change_pct evidence source hash must be text")
        if not isinstance(quote_source, str):
            raise ValueError("Quote change_pct evidence quote_source must be text")
        try:
            observed_at = datetime.fromisoformat(observed_at_value.replace("Z", "+00:00"))
            parsed_metric = Decimal(metric_value)
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Quote change_pct evidence contains an invalid value") from None
        return cls(
            metric_value=parsed_metric,
            source_value=source_value,
            dataset_contract_key=dataset_contract_key,
            dataset_contract_version=dataset_contract_version,
            dataset_schema_version=dataset_schema_version,
            source_contract=source_contract,
            source_contract_hash=source_contract_hash,
            observed_at=observed_at,
            quote_source=quote_source,
        )


__all__ = [
    "QuoteChangePctCandidate",
    "QuoteChangePctEvidence",
    "quote_change_pct_storage_value",
]
