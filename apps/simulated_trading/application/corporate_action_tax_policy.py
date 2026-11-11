"""Strict decoding for explicitly supplied deferred-dividend tax policies.

This module validates a versioned configuration shape and narrows it into the
existing Domain value. It does not qualify statutory source material, select a
current policy, or establish that a source identity/hash is genuine.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TypedDict, TypeGuard, cast

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    MAX_SUPPORTED_HOLDING_MONTHS,
    DeferredDividendTaxPolicy,
    DeferredDividendTaxValidationError,
    HoldingPeriodTaxBand,
    TaxRoundingMode,
)
from core.exceptions import BusinessLogicError

_SCHEMA_VERSION = "simulated_trading.deferred_dividend_tax_policy.v1"
_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
# Signed 18-digit integer capacity plus a decimal point and 12 fractional digits.
_MAX_DECIMAL_TEXT_LENGTH = 32

_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "policy_id",
        "version",
        "effective_from",
        "effective_through",
        "source_identity",
        "source_sha256",
        "bands",
        "currency_quantum",
        "rounding_mode",
    }
)
_BAND_FIELDS = frozenset(
    {
        "band_id",
        "maximum_holding_months",
        "taxable_dividend_ratio",
        "withholding_rate",
    }
)


class HoldingPeriodTaxBandJSON(TypedDict):
    """One exact JSON holding-period band with no implied threshold or rate."""

    band_id: str
    maximum_holding_months: int | None
    taxable_dividend_ratio: str
    withholding_rate: str


class DeferredDividendTaxPolicyJSON(TypedDict):
    """Versioned JSON shape for a source-identified statutory policy candidate."""

    schema_version: str
    policy_id: str
    version: str
    effective_from: str
    effective_through: str | None
    source_identity: str
    source_sha256: str
    bands: list[HoldingPeriodTaxBandJSON]
    currency_quantum: str
    rounding_mode: str


class CorporateActionTaxPolicyDecodeError(BusinessLogicError):
    """The explicit tax-policy JSON cannot be narrowed to a valid Domain value."""

    default_message = "显式公司行为税务规则配置无效"
    default_code = "CORPORATE_ACTION_TAX_POLICY_DECODE_INVALID"


def _invalid(field: str, reason: str) -> CorporateActionTaxPolicyDecodeError:
    """Build one stable application error without echoing untrusted JSON values."""

    return CorporateActionTaxPolicyDecodeError(f"{field}: {reason}")


def _is_string_object(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow an exact built-in dictionary whose keys are exact strings."""

    if type(value) is not dict:
        return False
    raw = cast(dict[object, object], value)
    return all(type(key) is str for key in raw)


def _require_object_fields(
    value: object,
    *,
    expected_fields: frozenset[str],
    field: str,
) -> dict[str, object]:
    """Require an exact JSON object with every required key and no unknown keys."""

    if not _is_string_object(value):
        raise _invalid(field, "must be an exact JSON object with string keys")
    if frozenset(value) != expected_fields:
        raise _invalid(field, "required fields are missing or unknown fields are present")
    return value


def _require_string(value: object, *, field: str) -> str:
    """Require one exact string rather than coercing JSON scalars."""

    if type(value) is not str:
        raise _invalid(field, "must be a string")
    return value


def _parse_date(value: object, *, field: str, allow_none: bool = False) -> date | None:
    """Parse only canonical YYYY-MM-DD dates; null is accepted only explicitly."""

    if allow_none and value is None:
        return None
    text = _require_string(value, field=field)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise _invalid(field, "must be a canonical YYYY-MM-DD date") from error
    if parsed.isoformat() != text:
        raise _invalid(field, "must be a canonical YYYY-MM-DD date")
    return parsed


def _parse_decimal(value: object, *, field: str) -> Decimal:
    """Parse a finite plain decimal string without float or exponent coercion."""

    text = _require_string(value, field=field)
    if len(text) > _MAX_DECIMAL_TEXT_LENGTH:
        raise _invalid(field, "exceeds the supported decimal text length")
    if _DECIMAL_PATTERN.fullmatch(text) is None:
        raise _invalid(field, "must be a plain decimal string")
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise _invalid(field, "must be a valid decimal string") from error
    if not parsed.is_finite() or (parsed.is_zero() and parsed.is_signed()):
        raise _invalid(field, "must be a finite nonnegative decimal representation")
    return parsed


def _parse_optional_months(value: object, *, field: str) -> int | None:
    """Accept a positive exact integer or explicit null for the final unbounded band."""

    if value is None:
        return None
    if type(value) is not int:
        raise _invalid(field, "must be an exact integer or explicit null")
    if value <= 0 or value > MAX_SUPPORTED_HOLDING_MONTHS:
        raise _invalid(field, "exceeds the supported calendar month span")
    return value


def _parse_rounding_mode(value: object) -> TaxRoundingMode:
    """Require one explicitly supported Decimal rounding mode."""

    text = _require_string(value, field="rounding_mode")
    try:
        return TaxRoundingMode(text)
    except ValueError as error:
        raise _invalid("rounding_mode", "is not a supported explicit rounding mode") from error


def _parse_band(value: object, *, index: int) -> HoldingPeriodTaxBand:
    """Narrow one exact JSON band into the existing Domain band type."""

    field = f"bands[{index}]"
    raw = _require_object_fields(value, expected_fields=_BAND_FIELDS, field=field)
    band = cast(HoldingPeriodTaxBandJSON, raw)
    try:
        return HoldingPeriodTaxBand(
            band_id=_require_string(band["band_id"], field=f"{field}.band_id"),
            maximum_holding_months=_parse_optional_months(
                band["maximum_holding_months"], field=f"{field}.maximum_holding_months"
            ),
            taxable_dividend_ratio=_parse_decimal(
                band["taxable_dividend_ratio"], field=f"{field}.taxable_dividend_ratio"
            ),
            withholding_rate=_parse_decimal(
                band["withholding_rate"], field=f"{field}.withholding_rate"
            ),
        )
    except DeferredDividendTaxValidationError as error:
        raise _invalid(field, "failed Domain validation") from error


def decode_deferred_dividend_tax_policy(value: object) -> DeferredDividendTaxPolicy:
    """Decode explicit versioned JSON into a validated Domain policy value.

    All policy dates, statutory source identities/hashes, holding thresholds,
    taxable ratios, withholding rates, currency quantum, and rounding mode must
    be present. JSON decimals are strings to avoid binary floating-point input.
    This function performs structural/domain validation only; it does not
    authenticate the source identity or source hash.
    """

    raw = _require_object_fields(value, expected_fields=_POLICY_FIELDS, field="policy")
    policy = cast(DeferredDividendTaxPolicyJSON, raw)
    if _require_string(policy["schema_version"], field="schema_version") != _SCHEMA_VERSION:
        raise _invalid("schema_version", "is unsupported")

    raw_bands = policy["bands"]
    if type(raw_bands) is not list:
        raise _invalid("bands", "must be a JSON array")
    band_values = cast(list[object], raw_bands)

    effective_from = _parse_date(policy["effective_from"], field="effective_from")
    effective_through = _parse_date(
        policy["effective_through"], field="effective_through", allow_none=True
    )
    if effective_from is None:
        raise _invalid("effective_from", "cannot be null")
    bands = tuple(_parse_band(item, index=index) for index, item in enumerate(band_values))
    try:
        return DeferredDividendTaxPolicy(
            policy_id=_require_string(policy["policy_id"], field="policy_id"),
            version=_require_string(policy["version"], field="version"),
            effective_from=effective_from,
            effective_through=effective_through,
            source_identity=_require_string(policy["source_identity"], field="source_identity"),
            source_sha256=_require_string(policy["source_sha256"], field="source_sha256"),
            bands=bands,
            currency_quantum=_parse_decimal(policy["currency_quantum"], field="currency_quantum"),
            rounding_mode=_parse_rounding_mode(policy["rounding_mode"]),
        )
    except DeferredDividendTaxValidationError as error:
        raise _invalid("policy", "failed Domain validation") from error


__all__ = [
    "CorporateActionTaxPolicyDecodeError",
    "DeferredDividendTaxPolicyJSON",
    "HoldingPeriodTaxBandJSON",
    "decode_deferred_dividend_tax_policy",
]
