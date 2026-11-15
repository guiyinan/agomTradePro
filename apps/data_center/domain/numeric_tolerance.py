"""Pure numeric tolerance policy and comparison rules for reconciliation."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from typing import Final

from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.rules import normalize_asset_code

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


def numeric_unit_text_v2(value: object) -> str:
    """Validate an explicit catalog unit without converting or cleaning its text."""

    if (
        type(value) is not str
        or not value
        or value.casefold()
        in {"unknown", "native", "canonical-unit", "catalog", "none", "null", "n/a", "-"}
        or len(value) > 128
        or unicodedata.normalize("NFC", value) != value
        or any(
            character.isspace() or unicodedata.category(character).startswith("C")
            for character in value
        )
    ):
        raise ValueError("numeric tolerance v2 unit must be canonical bounded text")
    return value


@dataclass(frozen=True, slots=True)
class NumericToleranceFieldV2:
    """One explicit field with its actual unit and independently governed limits."""

    field_name: str
    unit: str
    absolute_tolerance: str
    relative_tolerance: str

    def __post_init__(self) -> None:
        """Retain native unit labels while enforcing exact finite tolerances."""

        object.__setattr__(self, "field_name", _bounded_token(self.field_name, "field_name"))
        object.__setattr__(self, "unit", numeric_unit_text_v2(self.unit))
        for name, raw in (
            ("absolute_tolerance", self.absolute_tolerance),
            ("relative_tolerance", self.relative_tolerance),
        ):
            value = canonical_decimal_text(raw, field_name=name)
            if Decimal(value) < 0:
                raise ValueError("numeric tolerances must be non-negative")
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, str]:
        """Return every field participating in the versioned policy hash."""

        return {
            "absolute_tolerance": self.absolute_tolerance,
            "field_name": self.field_name,
            "relative_tolerance": self.relative_tolerance,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class NumericTolerancePolicyV2:
    """Bind member selection and actual units without changing v1 policy bytes."""

    dataset_key: str
    policy_version: str
    rule: str
    fields: tuple[NumericToleranceFieldV2, ...]
    selector: str

    def __post_init__(self) -> None:
        """Reject implicit financial selection and ambiguous configured metrics."""

        for name, value in (
            ("dataset_key", self.dataset_key),
            ("policy_version", self.policy_version),
        ):
            object.__setattr__(self, name, _bounded_token(value, name))
        if self.rule != _RULE:
            raise ValueError(f"numeric tolerance rule must be {_RULE}")
        required_selector = (
            "financial_metric_code_v1"
            if self.dataset_key == "equity.financial.fact"
            else "all_fields_per_member"
        )
        if self.selector != required_selector:
            raise ValueError("numeric tolerance v2 selector does not match the dataset")
        if (
            not isinstance(self.fields, tuple)
            or not self.fields
            or any(type(field) is not NumericToleranceFieldV2 for field in self.fields)
        ):
            raise ValueError("numeric tolerance v2 requires immutable typed fields")
        ordered = tuple(sorted(self.fields, key=lambda item: item.field_name))
        names = tuple(field.field_name for field in ordered)
        if len(set(names)) != len(names) or (
            self.selector == "financial_metric_code_v1" and any(":" in name for name in names)
        ):
            raise ValueError("numeric tolerance v2 fields are ambiguous")
        object.__setattr__(self, "fields", ordered)

    @property
    def content_hash(self) -> str:
        """Hash the explicit selector, field limits and actual unit labels."""

        payload = {
            "dataset_key": self.dataset_key,
            "encoding": "data02-numeric-tolerance-policy-v2",
            "fields": [field.to_dict() for field in self.fields],
            "policy_version": self.policy_version,
            "rule": self.rule,
            "selector": self.selector,
        }
        raw = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @property
    def identity(self) -> str:
        """Return a distinct v2 identity bound to the complete policy content."""

        return f"data02-tolerance-v2:{self.policy_version}:{self.content_hash}"

    def fields_for_member(
        self, natural_key: str, *, source: str
    ) -> tuple[NumericToleranceFieldV2, ...]:
        """Select one financial metric only from its exact canonical member key."""

        key = _natural_key_token(natural_key)
        if self.selector == "all_fields_per_member":
            return self.fields
        parts = key.split(":")
        if len(parts) != 5 or parts[4] != source:
            raise ValueError("financial member identity or source is ambiguous")
        asset, period, period_type, metric, _source = parts
        if normalize_asset_code(asset) != asset or re.fullmatch(r"\d+\.[A-Z]{2}", asset) is None:
            raise ValueError("financial member asset is not canonical")
        if date.fromisoformat(period).isoformat() != period or period_type not in {
            item.value for item in FinancialPeriodType
        }:
            raise ValueError("financial member period is invalid")
        selected = tuple(field for field in self.fields if field.field_name == metric)
        if len(selected) != 1:
            raise ValueError("financial member metric is absent from the governed matrix")
        return selected

    def validate_member_coverage(self, members: tuple[tuple[str, str], ...]) -> None:
        """Require the complete metric matrix for every financial report/source group."""

        if not members:
            raise ValueError("numeric tolerance v2 member coverage is empty")
        groups: dict[tuple[str, str, str, str], set[str]] = {}
        seen: set[str] = set()
        for natural_key, source in members:
            selected = self.fields_for_member(natural_key, source=source)
            if natural_key in seen:
                raise ValueError("numeric tolerance v2 member identities are duplicated")
            seen.add(natural_key)
            if self.selector == "financial_metric_code_v1":
                asset, period, period_type, _metric, provider = natural_key.split(":")
                groups.setdefault((asset, period, period_type, provider), set()).update(
                    field.field_name for field in selected
                )
        required = {field.field_name for field in self.fields}
        if any(metrics != required for metrics in groups.values()):
            raise ValueError("financial member coverage omits governed metrics from a report group")


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
    tolerance: NumericToleranceField | NumericToleranceFieldV2,
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
    "NumericToleranceFieldV2",
    "NumericTolerancePolicyV2",
    "numeric_unit_text_v2",
    "canonical_decimal_text",
    "compare_numeric_value",
]
