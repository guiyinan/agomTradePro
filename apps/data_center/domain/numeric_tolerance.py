"""Pure numeric tolerance policy and comparison rules for reconciliation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Final

_DECIMAL_RE: Final[re.Pattern[str]] = re.compile(r"^-?\d+(?:\.\d+)?$")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/|-]{1,256}$")
_NATURAL_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/|=-]{1,512}$")
_RULE: Final[str] = "absolute_or_relative"
_ARITHMETIC_PRECISION: Final[int] = 384


def _canonical_decimal(parsed: Decimal) -> str:
    """Format one already-validated Decimal without context rounding."""

    if parsed == 0:
        return "0"
    rendered = format(parsed, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def canonical_decimal_text(value: str, *, field_name: str) -> str:
    """Return a finite, non-exponent decimal string in canonical form."""

    if type(value) is not str or len(value) > 128 or _DECIMAL_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a bounded decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a finite decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be a finite decimal string")
    return _canonical_decimal(parsed)


def _bounded_token(value: str, field_name: str) -> str:
    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a bounded token")
    return value


def _natural_key_token(value: str) -> str:
    if type(value) is not str or _NATURAL_KEY_RE.fullmatch(value) is None:
        raise ValueError("natural_key must be a bounded token")
    return value


@dataclass(frozen=True, slots=True)
class NumericToleranceField:
    """One field/unit pair and its governed absolute and relative limits."""

    field_name: str
    unit: str
    absolute_tolerance: str
    relative_tolerance: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_name", _bounded_token(self.field_name, "field_name"))
        object.__setattr__(self, "unit", _bounded_token(self.unit, "unit"))
        absolute = canonical_decimal_text(self.absolute_tolerance, field_name="absolute_tolerance")
        relative = canonical_decimal_text(self.relative_tolerance, field_name="relative_tolerance")
        if Decimal(absolute) < 0 or Decimal(relative) < 0:
            raise ValueError("numeric tolerances must be non-negative")
        object.__setattr__(self, "absolute_tolerance", absolute)
        object.__setattr__(self, "relative_tolerance", relative)

    def to_dict(self) -> dict[str, str]:
        """Return the canonical hash and evidence representation."""

        return {
            "absolute_tolerance": self.absolute_tolerance,
            "field_name": self.field_name,
            "relative_tolerance": self.relative_tolerance,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class NumericTolerancePolicy:
    """Content-addressed numeric reconciliation policy for one dataset."""

    dataset_key: str
    policy_version: str
    rule: str
    fields: tuple[NumericToleranceField, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_key", _bounded_token(self.dataset_key, "dataset_key"))
        object.__setattr__(
            self, "policy_version", _bounded_token(self.policy_version, "policy_version")
        )
        if self.rule != _RULE:
            raise ValueError(f"numeric tolerance rule must be {_RULE}")
        if not self.fields:
            raise ValueError("numeric tolerance policy requires fields")
        if any(not isinstance(field, NumericToleranceField) for field in self.fields):
            raise TypeError("numeric tolerance fields must be NumericToleranceField values")
        ordered = tuple(sorted(self.fields, key=lambda item: item.field_name))
        names = [field.field_name for field in ordered]
        if len(names) != len(set(names)):
            raise ValueError("numeric tolerance policy field names must be unique")
        object.__setattr__(self, "fields", ordered)

    @property
    def content_hash(self) -> str:
        """Hash every decision field in the numeric tolerance policy."""

        payload: dict[str, object] = {
            "dataset_key": self.dataset_key,
            "encoding": "data02-numeric-tolerance-policy-v1",
            "fields": [field.to_dict() for field in self.fields],
            "policy_version": self.policy_version,
            "rule": self.rule,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def identity(self) -> str:
        """Return a self-describing identity that embeds the content hash."""

        return f"data02-tolerance-v1:{self.policy_version}:{self.content_hash}"


@dataclass(frozen=True, slots=True)
class NumericToleranceComparison:
    """One computed field comparison with stable breach semantics."""

    natural_key: str
    field_name: str
    unit: str
    canonical_value: str
    observed_value: str
    absolute_difference: str
    relative_difference: str | None
    breached: bool

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe per-field tolerance evidence."""

        return {
            "absolute_difference": self.absolute_difference,
            "breached": self.breached,
            "canonical_value": self.canonical_value,
            "field_name": self.field_name,
            "natural_key": self.natural_key,
            "observed_value": self.observed_value,
            "relative_difference": self.relative_difference,
            "unit": self.unit,
        }


def compare_numeric_value(
    *,
    natural_key: str,
    tolerance: NumericToleranceField,
    unit: str,
    canonical_value: str,
    observed_value: str,
) -> NumericToleranceComparison:
    """Compute absolute/relative deviation and apply the governed OR rule."""

    normalized_key = _natural_key_token(natural_key)
    if unit != tolerance.unit:
        raise ValueError("comparison unit does not match tolerance policy")
    canonical_text = canonical_decimal_text(canonical_value, field_name="canonical_value")
    observed_text = canonical_decimal_text(observed_value, field_name="observed_value")
    canonical = Decimal(canonical_text)
    observed = Decimal(observed_text)
    with localcontext() as context:
        context.prec = _ARITHMETIC_PRECISION
        difference = abs(observed - canonical)
        relative: Decimal | None = None
        if canonical != 0:
            relative = difference / abs(canonical)
        within_relative = canonical != 0 and difference <= (
            abs(canonical) * Decimal(tolerance.relative_tolerance)
        )
    difference_text = _canonical_decimal(difference)
    relative_text = _canonical_decimal(relative) if relative is not None else None
    within_absolute = difference <= Decimal(tolerance.absolute_tolerance)
    return NumericToleranceComparison(
        natural_key=normalized_key,
        field_name=tolerance.field_name,
        unit=unit,
        canonical_value=canonical_text,
        observed_value=observed_text,
        absolute_difference=difference_text,
        relative_difference=relative_text,
        breached=not (within_absolute or within_relative),
    )


__all__ = [
    "NumericToleranceComparison",
    "NumericToleranceField",
    "NumericTolerancePolicy",
    "canonical_decimal_text",
    "compare_numeric_value",
]
