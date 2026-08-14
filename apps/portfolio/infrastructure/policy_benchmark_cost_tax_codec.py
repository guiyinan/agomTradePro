"""Strict codec for Portfolio benchmark cost/tax methodologies."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from apps.portfolio.domain.policy_benchmark_cost_tax import (
    PolicyBenchmarkCostTaxRule,
    PolicyBenchmarkCostTaxSourceRef,
    PortfolioPolicyBenchmarkCostTax,
)


class PolicyBenchmarkCostTaxCodecError(ValueError):
    """Canonical cost/tax methodology cannot be restored exactly."""


def encode_policy_benchmark_cost_tax(
    value: PortfolioPolicyBenchmarkCostTax,
) -> dict[str, object]:
    """Encode one methodology without derived authority markers."""

    return {
        key: item
        for key, item in value.to_payload().items()
        if key
        not in {
            "activation_available",
            "automatic_fallback_allowed",
            "silent_zero_allowed",
            "must_not_execute",
        }
    }


def decode_policy_benchmark_cost_tax(payload: object) -> PortfolioPolicyBenchmarkCostTax:
    """Restore and revalidate one exact canonical methodology."""

    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "schema",
            "methodology_id",
            "methodology_version",
            "source_priority",
            "charge_rules",
            "business_date_policy",
            "currency_basis_policy",
            "currency_conversion_policy",
            "missing_fx_policy",
            "unknown_asset_policy",
            "unknown_fee_policy",
            "unknown_tax_policy",
            "missing_source_policy",
            "source_failure_policy",
            "estimation_policy",
            "silent_zero_policy",
            "duplicate_charge_policy",
            "cash_dividend_charge_policy",
            "cash_dividend_payment_policy",
            "corporate_action_charge_policy",
            "already_net_amount_policy",
            "recorded_at",
            "valid_until",
            "permission",
            "identity_hash",
            "content_hash",
        },
    )
    try:
        value = PortfolioPolicyBenchmarkCostTax(
            methodology_id=_string(data["methodology_id"]),
            methodology_version=_string(data["methodology_version"]),
            source_priority=tuple(_source(item) for item in _list(data["source_priority"])),
            charge_rules=tuple(_rule(item) for item in _list(data["charge_rules"])),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            business_date_policy=_string(data["business_date_policy"]),
            currency_basis_policy=_string(data["currency_basis_policy"]),
            currency_conversion_policy=_string(data["currency_conversion_policy"]),
            missing_fx_policy=_string(data["missing_fx_policy"]),
            unknown_asset_policy=_string(data["unknown_asset_policy"]),
            unknown_fee_policy=_string(data["unknown_fee_policy"]),
            unknown_tax_policy=_string(data["unknown_tax_policy"]),
            missing_source_policy=_string(data["missing_source_policy"]),
            source_failure_policy=_string(data["source_failure_policy"]),
            estimation_policy=_string(data["estimation_policy"]),
            silent_zero_policy=_string(data["silent_zero_policy"]),
            duplicate_charge_policy=_string(data["duplicate_charge_policy"]),
            cash_dividend_charge_policy=_string(data["cash_dividend_charge_policy"]),
            cash_dividend_payment_policy=_string(data["cash_dividend_payment_policy"]),
            corporate_action_charge_policy=_string(data["corporate_action_charge_policy"]),
            already_net_amount_policy=_string(data["already_net_amount_policy"]),
        )
    except (PolicyBenchmarkCostTaxCodecError, TypeError, ValueError) as error:
        raise PolicyBenchmarkCostTaxCodecError("cost/tax methodology is invalid") from error
    if payload != encode_policy_benchmark_cost_tax(value):
        raise PolicyBenchmarkCostTaxCodecError("cost/tax methodology is non-canonical")
    return value


def _source(payload: object) -> PolicyBenchmarkCostTaxSourceRef:
    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "artifact_id",
            "artifact_version",
            "content_hash",
            "ordinal",
            "charge_kind",
            "charge_code",
            "asset_scope_code",
            "jurisdiction_code",
            "recorded_at",
            "valid_until",
        },
    )
    return PolicyBenchmarkCostTaxSourceRef(
        owner=_string(data["owner"]),
        artifact_type=_string(data["artifact_type"]),
        artifact_id=_string(data["artifact_id"]),
        artifact_version=_string(data["artifact_version"]),
        content_hash=_string(data["content_hash"]),
        ordinal=_non_negative(data["ordinal"]),
        charge_kind=_string(data["charge_kind"]),
        charge_code=_string(data["charge_code"]),
        asset_scope_code=_string(data["asset_scope_code"]),
        jurisdiction_code=_string(data["jurisdiction_code"]),
        recorded_at=_datetime(data["recorded_at"]),
        valid_until=_datetime(data["valid_until"]),
    )


def _rule(payload: object) -> PolicyBenchmarkCostTaxRule:
    data = _mapping(
        payload,
        {
            "ordinal",
            "source_ordinal",
            "charge_kind",
            "charge_code",
            "asset_scope_code",
            "jurisdiction_code",
            "charge_event",
            "trade_side",
            "calculation_basis",
            "recognition_timing",
            "calculation_mode",
            "rate",
            "fixed_amount",
            "minimum_amount",
            "maximum_amount",
            "charge_currency",
            "rate_precision_places",
            "amount_precision_places",
            "rounding_increment",
            "rounding_mode",
        },
    )
    return PolicyBenchmarkCostTaxRule(
        ordinal=_non_negative(data["ordinal"]),
        source_ordinal=_non_negative(data["source_ordinal"]),
        charge_kind=_string(data["charge_kind"]),
        charge_code=_string(data["charge_code"]),
        asset_scope_code=_string(data["asset_scope_code"]),
        jurisdiction_code=_string(data["jurisdiction_code"]),
        charge_event=_string(data["charge_event"]),
        trade_side=_string(data["trade_side"]),
        calculation_basis=_string(data["calculation_basis"]),
        recognition_timing=_string(data["recognition_timing"]),
        calculation_mode=_string(data["calculation_mode"]),
        rate=_optional_decimal(data["rate"]),
        fixed_amount=_optional_decimal(data["fixed_amount"]),
        minimum_amount=_optional_decimal(data["minimum_amount"]),
        maximum_amount=_optional_decimal(data["maximum_amount"]),
        charge_currency=_string(data["charge_currency"]),
        rate_precision_places=_non_negative(data["rate_precision_places"]),
        amount_precision_places=_non_negative(data["amount_precision_places"]),
        rounding_increment=_decimal(data["rounding_increment"]),
        rounding_mode=_string(data["rounding_mode"]),
    )


def _mapping(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise PolicyBenchmarkCostTaxCodecError("cost/tax payload shape is invalid")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise TypeError("expected list")
    return cast(list[object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _non_negative(value: object) -> int:
    if type(value) is not int or value < 0:
        raise TypeError("expected non-negative integer")
    return value


def _decimal(value: object) -> Decimal:
    text = _string(value)
    try:
        result = Decimal(text)
    except InvalidOperation as error:
        raise ValueError("expected canonical Decimal text") from error
    if not result.is_finite():
        raise ValueError("expected finite Decimal text")
    return result


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value)


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.isoformat().replace("+00:00", "Z") != text:
        raise ValueError("datetime is non-canonical")
    return result


__all__ = [
    "PolicyBenchmarkCostTaxCodecError",
    "decode_policy_benchmark_cost_tax",
    "encode_policy_benchmark_cost_tax",
]
