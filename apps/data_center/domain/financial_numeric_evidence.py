"""Typed, exact evidence for one native financial metric observation.

This standard-library-only value object preserves a source decimal and an
explicit exact unit scale. It does not verify provider bytes or qualify D1 or
production data. It is a prerequisite for a later exact canonical-value path;
it does not change the precision of ``FinancialFactModel.value`` or prove that
decision consumers use the preserved source value. Its ``source_value_text``
is a plain decimal representation of a parsed numeric value, not the original
JSON token; the retained body is needed to prove lexical source bytes.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from apps.data_center.domain.numeric_tolerance import (
    canonical_decimal_text,
    numeric_unit_text_v2,
)

_CONTRACT_SCHEMA: str = "financial-metric-source-contract.v1"
_OBSERVATION_SCHEMA: str = "financial-native-metric-observation.v1"
_MAX_DECIMAL_TEXT_LENGTH: int = 128
_MAX_IDENTITY_TEXT_LENGTH: int = 512
_MAX_INTEGER_BITS: int = 426


def _identity_text(value: object, *, field_name: str, maximum: int) -> str:
    """Validate a nonempty, exact Unicode identifier without cleaning it."""

    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or value.strip() != value
        or unicodedata.normalize("NFC", value) != value
        or any(
            character.isspace() or unicodedata.category(character).startswith("C")
            for character in value
        )
    ):
        raise ValueError(f"{field_name} must be explicit bounded text")
    return value


def _positive_scale_integer(value: object, *, field_name: str) -> int:
    """Require a bounded positive integer scale component, excluding booleans."""

    if type(value) is not int or value <= 0 or value.bit_length() > _MAX_INTEGER_BITS:
        raise ValueError(f"{field_name} must be a bounded positive integer")
    return value


def _raw_decimal_parts(value: object) -> tuple[str, str, int]:
    """Return plain source decimal text, exact canonical text and source places."""

    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("financial source value must be a finite decimal")
        sign, digits, exponent = value.as_tuple()
        if type(exponent) is not int:
            raise ValueError("financial source value must have a finite decimal exponent")
        if value.is_zero():
            fixed_length = (1 if exponent >= 0 else 2 - exponent) + sign
        elif exponent >= 0:
            fixed_length = len(digits) + exponent + sign
        else:
            fixed_length = max(len(digits) + 1, 2 - exponent) + sign
        if fixed_length > _MAX_DECIMAL_TEXT_LENGTH:
            raise ValueError("financial source decimal exceeds the exact text length limit")
        source_text = format(value, "f")
    elif type(value) is int:
        if value.bit_length() > _MAX_INTEGER_BITS:
            raise ValueError("financial source integer exceeds the exact text length limit")
        source_text = str(value)
    elif type(value) is str:
        source_text = value
    else:
        raise ValueError("financial source value must be Decimal, integer, or decimal text")
    if not source_text.isascii():
        raise ValueError("financial source decimal text must use ASCII digits")
    source_value = canonical_decimal_text(source_text, field_name="source_value")
    fractional_text = source_text.partition(".")[2]
    source_decimal_places = len(fractional_text) if "." in source_text else 0
    return source_text, source_value, source_decimal_places


def _finite_decimal_text(value: Fraction) -> str:
    """Render a rational number only when it has an exact finite decimal form."""

    denominator = value.denominator
    twos = 0
    fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError("financial metric scale does not produce a terminating decimal")

    decimal_places = max(twos, fives)
    scale = 10**decimal_places
    scaled_integer = value.numerator * (scale // value.denominator)
    sign = "-" if scaled_integer < 0 else ""
    digits = str(abs(scaled_integer))
    if decimal_places == 0:
        rendered = f"{sign}{digits}"
    else:
        padded = digits.rjust(decimal_places + 1, "0")
        rendered = f"{sign}{padded[:-decimal_places]}.{padded[-decimal_places:]}"
    return canonical_decimal_text(rendered, field_name="canonical_value")


@dataclass(frozen=True, slots=True)
class FinancialMetricSourceContract:
    """One fully explicit native source-field interpretation.

    Metric names and units are supplied by a caller-owned catalog. This type
    contains no financial metric or unit defaults, and only represents native
    fields; derived metrics require a separate, explicitly governed contract.
    """

    provider: str
    dataset_key: str
    metric_code: str
    source_field: str
    source_unit: str
    canonical_unit: str
    scale_numerator: int
    scale_denominator: int
    contract_version: str
    origin: Literal["native"]

    def __post_init__(self) -> None:
        """Reject incomplete identities, placeholder units and implicit scales."""

        for name, value, maximum in (
            ("provider", self.provider, 128),
            ("dataset_key", self.dataset_key, 160),
            ("metric_code", self.metric_code, 128),
            ("source_field", self.source_field, 256),
            ("contract_version", self.contract_version, 40),
        ):
            _identity_text(value, field_name=name, maximum=maximum)
        if ":" in self.metric_code:
            raise ValueError("metric_code cannot contain a natural-key delimiter")
        object.__setattr__(self, "source_unit", numeric_unit_text_v2(self.source_unit))
        object.__setattr__(self, "canonical_unit", numeric_unit_text_v2(self.canonical_unit))
        _positive_scale_integer(self.scale_numerator, field_name="scale_numerator")
        _positive_scale_integer(self.scale_denominator, field_name="scale_denominator")
        if type(self.origin) is not str or self.origin != "native":
            raise ValueError("financial metric source contract must have native origin")

    def to_dict(self) -> dict[str, object]:
        """Return every source interpretation field used by the contract hash."""

        return {
            "canonical_unit": self.canonical_unit,
            "contract_version": self.contract_version,
            "dataset_key": self.dataset_key,
            "metric_code": self.metric_code,
            "origin": self.origin,
            "provider": self.provider,
            "scale_denominator": self.scale_denominator,
            "scale_numerator": self.scale_numerator,
            "schema": _CONTRACT_SCHEMA,
            "source_field": self.source_field,
            "source_unit": self.source_unit,
        }

    @classmethod
    def from_payload(cls, value: object) -> FinancialMetricSourceContract:
        """Restore one exact versioned JSON contract without coercing its fields."""

        payload = _payload_mapping(value)
        if _payload_text(payload, "origin") != "native":
            raise ValueError("financial metric contract must have native origin")
        result = cls(
            provider=_payload_text(payload, "provider"),
            dataset_key=_payload_text(payload, "dataset_key"),
            metric_code=_payload_text(payload, "metric_code"),
            source_field=_payload_text(payload, "source_field"),
            source_unit=_payload_text(payload, "source_unit"),
            canonical_unit=_payload_text(payload, "canonical_unit"),
            scale_numerator=_payload_integer(payload, "scale_numerator"),
            scale_denominator=_payload_integer(payload, "scale_denominator"),
            contract_version=_payload_text(payload, "contract_version"),
            origin="native",
        )
        if not _same_wire_payload(payload, result.to_dict()):
            raise ValueError("financial metric contract payload differs from exact reconstruction")
        return result

    @property
    def content_hash(self) -> str:
        """Hash the complete provider, metric, field, unit, scale and version."""

        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def identity(self) -> str:
        """Return a readable contract version bound to its full content hash."""

        return f"{_CONTRACT_SCHEMA}:{self.contract_version}:{self.content_hash}"


@dataclass(frozen=True, slots=True)
class NativeFinancialMetricObservation:
    """Exact numeric evidence for one native field in a retained source row.

    This evidence binds a decimal claim to a body hash, native row identifier,
    exact source field and full contract identity. Callers remain responsible
    for independently verifying that the row and field came from those bytes.
    The observation preserves raw numeric evidence only; it does not make a
    rounded canonical fact exact or qualify a D1 or production comparison.
    """

    contract: FinancialMetricSourceContract
    source_field: str
    body_sha256: str
    native_row_id: str
    source_value_text: str
    source_value: str
    source_decimal_places: int
    canonical_value: str
    contract_hash: str
    contract_identity: str

    def __post_init__(self) -> None:
        """Verify exact values and identities without applying rounding."""

        if type(self.contract) is not FinancialMetricSourceContract:
            raise TypeError("contract must be a FinancialMetricSourceContract")
        source_field = _identity_text(
            self.source_field,
            field_name="source_field",
            maximum=256,
        )
        if source_field != self.contract.source_field:
            raise ValueError("observation source field does not match its contract")
        if (
            type(self.body_sha256) is not str
            or len(self.body_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.body_sha256)
        ):
            raise ValueError("body_sha256 must be a lowercase SHA-256 digest")
        _identity_text(
            self.native_row_id,
            field_name="native_row_id",
            maximum=_MAX_IDENTITY_TEXT_LENGTH,
        )
        source_text, source_value, source_places = _raw_decimal_parts(self.source_value_text)
        if source_text != self.source_value_text or source_value != self.source_value:
            raise ValueError("observation source value is not in exact canonical form")
        if (
            type(self.source_decimal_places) is not int
            or self.source_decimal_places != source_places
        ):
            raise ValueError("observation source decimal precision does not match its source text")
        canonical_value = canonical_decimal_text(
            self.canonical_value,
            field_name="canonical_value",
        )
        expected_value = _scale_exact_decimal(source_value, self.contract)
        if canonical_value != expected_value:
            raise ValueError("observation canonical value does not match exact contract scaling")
        if canonical_value != self.canonical_value:
            raise ValueError("observation canonical value is not in canonical decimal form")
        if (
            type(self.contract_hash) is not str
            or self.contract_hash != self.contract.content_hash
            or type(self.contract_identity) is not str
            or self.contract_identity != self.contract.identity
        ):
            raise ValueError("observation contract identity does not match its contract")

    @classmethod
    def from_payload(cls, value: object) -> NativeFinancialMetricObservation:
        """Decode strict evidence while retaining its non-authorizing semantics."""

        payload = _payload_mapping(value)
        contract = FinancialMetricSourceContract.from_payload(payload.get("contract"))
        result = cls.from_raw_value(
            contract=contract,
            raw_value=_payload_text(payload, "source_value_text"),
            source_field=_payload_text(payload, "source_field"),
            body_sha256=_payload_text(payload, "body_sha256"),
            native_row_id=_payload_text(payload, "native_row_id"),
        )
        if not _same_wire_payload(payload, result.to_dict()):
            raise ValueError("financial numeric payload differs from exact reconstruction")
        return result

    @classmethod
    def from_raw_value(
        cls,
        *,
        contract: FinancialMetricSourceContract,
        raw_value: object,
        source_field: str,
        body_sha256: str,
        native_row_id: str,
    ) -> NativeFinancialMetricObservation:
        """Build exact native evidence from a strict JSON-boundary value.

        Accepted values are finite ``Decimal`` instances, integers, or plain
        decimal text. Binary floats, missing values, derived-origin contracts,
        malformed body identities and field mismatches fail closed. This
        factory does not read or verify the retained source body itself.
        """

        if type(contract) is not FinancialMetricSourceContract:
            raise TypeError("contract must be a FinancialMetricSourceContract")
        source_text, source_value, source_places = _raw_decimal_parts(raw_value)
        canonical_value = _scale_exact_decimal(source_value, contract)
        return cls(
            contract=contract,
            source_field=source_field,
            body_sha256=body_sha256,
            native_row_id=native_row_id,
            source_value_text=source_text,
            source_value=source_value,
            source_decimal_places=source_places,
            canonical_value=canonical_value,
            contract_hash=contract.content_hash,
            contract_identity=contract.identity,
        )

    @property
    def origin(self) -> Literal["native"]:
        """Return the native-only origin represented by this value object."""

        return self.contract.origin

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe exact evidence with its complete contract identity."""

        return {
            "body_sha256": self.body_sha256,
            "canonical_unit": self.contract.canonical_unit,
            "canonical_value": self.canonical_value,
            "contract": self.contract.to_dict(),
            "contract_hash": self.contract_hash,
            "contract_identity": self.contract_identity,
            "evidence_only": True,
            "metric_code": self.contract.metric_code,
            "must_not_use_for_decision": True,
            "native_row_id": self.native_row_id,
            "origin": self.origin,
            "production_ready": False,
            "provider": self.contract.provider,
            "scale_denominator": self.contract.scale_denominator,
            "scale_numerator": self.contract.scale_numerator,
            "schema": _OBSERVATION_SCHEMA,
            "source_decimal_places": self.source_decimal_places,
            "source_field": self.source_field,
            "source_unit": self.contract.source_unit,
            "source_value": self.source_value,
            "source_value_text": self.source_value_text,
        }

    @property
    def content_hash(self) -> str:
        """Hash the source binding, exact values and complete contract payload."""

        payload = {"encoding": _OBSERVATION_SCHEMA, **self.to_dict()}
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
        """Return the immutable content-addressed observation identity."""

        return f"{_OBSERVATION_SCHEMA}:{self.content_hash}"


def _scale_exact_decimal(
    source_value: str,
    contract: FinancialMetricSourceContract,
) -> str:
    """Apply the declared rational scale only when the result terminates."""

    exact_value = Fraction(Decimal(source_value)) * Fraction(
        contract.scale_numerator,
        contract.scale_denominator,
    )
    return _finite_decimal_text(exact_value)


def _payload_mapping(value: object) -> dict[str, object]:
    """Narrow one JSON object without cleaning identifiers or dropping fields."""

    if not isinstance(value, Mapping):
        raise ValueError("financial numeric payload must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if type(key) is not str:
            raise ValueError("financial numeric payload keys must be text")
        result[key] = item
    return result


def _payload_text(payload: Mapping[str, object], name: str) -> str:
    """Read exact required text at the JSON boundary."""

    value = payload.get(name)
    if type(value) is not str:
        raise ValueError(f"{name} must be text")
    return value


def _payload_integer(payload: Mapping[str, object], name: str) -> int:
    """Read an integer without treating a JSON boolean as one."""

    value = payload.get(name)
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _same_wire_payload(left: dict[str, object], right: dict[str, object]) -> bool:
    """Compare the exact declared fields and scalar types before equality."""

    return left.keys() == right.keys() and all(
        type(left[key]) is type(expected) and left[key] == expected
        for key, expected in right.items()
    )


__all__ = ["FinancialMetricSourceContract", "NativeFinancialMetricObservation"]
