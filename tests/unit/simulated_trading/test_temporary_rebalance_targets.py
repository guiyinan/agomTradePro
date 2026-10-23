"""Exact and bounded one-request target value-object contracts."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.simulated_trading.domain.temporary_rebalance_targets import (
    TemporarySecurityTargets,
    TemporarySecurityTargetWeight,
    TemporaryTargetValidationError,
)


def _uppercase_code(value: str) -> str:
    """Stand in for the application boundary's canonical security normalizer."""

    return value.upper()


def test_parse_percent_lines_keeps_exact_fraction_and_residual_cash() -> None:
    targets = TemporarySecurityTargets.parse_percent_lines(
        " 600000.sh ,90.000001\n000001.SZ,0",
        normalize_code=_uppercase_code,
    )

    assert targets.weights_by_code() == {
        "600000.SH": Decimal("0.90000001"),
        "000001.SZ": Decimal("0E-8"),
    }
    assert targets.residual_cash_weight == Decimal("0.09999999")
    assert targets.audit_record()["target_weights"]["600000.SH"] == "0.90000001"


@pytest.mark.parametrize(
    ("raw_text", "reason_code"),
    [
        ("", "TARGET_ENTRY_COUNT_INVALID"),
        ("600000.SH", "TARGET_ROW_FORMAT_INVALID"),
        ("600000.SH,10,20", "TARGET_ROW_FORMAT_INVALID"),
        (",10", "TARGET_SECURITY_CODE_INVALID"),
        ("not-a-code,10", "TARGET_SECURITY_CODE_INVALID"),
        ("00700.HK,10", "TARGET_SECURITY_CODE_INVALID"),
        ("600000.SH,１０", "TARGET_WEIGHT_INVALID"),
        ("600000.SH,-1", "TARGET_WEIGHT_INVALID"),
        ("600000.SH,100.000001", "TARGET_WEIGHT_INVALID"),
        ("600000.SH,1.0000001", "TARGET_WEIGHT_INVALID"),
        (
            "600000.SH,60\n000001.SZ,40.000001",
            "TARGET_WEIGHT_SUM_EXCEEDS_ONE",
        ),
        (
            "600000.sh,10\n600000.SH,20",
            "TARGET_DUPLICATE_NORMALIZED_ASSET",
        ),
    ],
)
def test_parser_rejects_invalid_target_rows_with_stable_reason(
    raw_text: str,
    reason_code: str,
) -> None:
    with pytest.raises(TemporaryTargetValidationError) as error:
        TemporarySecurityTargets.parse_percent_lines(
            raw_text,
            normalize_code=_uppercase_code,
        )

    assert error.value.reason_code == reason_code


def test_parser_rejects_overlong_and_nontext_input_before_row_processing() -> None:
    with pytest.raises(TemporaryTargetValidationError) as too_many:
        TemporarySecurityTargets.parse_percent_lines(
            "\n".join("600000.SH,1" for _ in range(51)),
            normalize_code=_uppercase_code,
        )
    with pytest.raises(TemporaryTargetValidationError) as wrong_type:
        TemporarySecurityTargets.parse_percent_lines(
            7,  # type: ignore[arg-type]
            normalize_code=_uppercase_code,
        )

    assert too_many.value.reason_code == "TARGET_ENTRY_COUNT_INVALID"
    assert wrong_type.value.reason_code == "TARGET_TEXT_INVALID"


def test_parser_wraps_normalizer_failure_without_exposing_provider_details() -> None:
    def fail_normalization(_value: str) -> str:
        raise ValueError("provider-specific private detail")

    with pytest.raises(TemporaryTargetValidationError) as error:
        TemporarySecurityTargets.parse_percent_lines(
            "600000.SH,10",
            normalize_code=fail_normalization,
        )

    assert error.value.reason_code == "TARGET_SECURITY_CODE_INVALID"
    assert "private detail" not in str(error.value)


@pytest.mark.parametrize(
    ("asset_code", "weight", "reason_code"),
    [
        ("600000", Decimal("0.5"), "TARGET_SECURITY_CODE_INVALID"),
        ("600000.SH", 0.5, "TARGET_WEIGHT_INVALID"),
        ("600000.SH", Decimal("NaN"), "TARGET_WEIGHT_INVALID"),
        ("600000.SH", Decimal("1.1"), "TARGET_WEIGHT_INVALID"),
        ("600000.SH", Decimal("0.000000001"), "TARGET_WEIGHT_PRECISION_EXCEEDED"),
    ],
)
def test_typed_weight_rejects_invalid_direct_construction(
    asset_code: str,
    weight: object,
    reason_code: str,
) -> None:
    with pytest.raises(TemporaryTargetValidationError) as error:
        TemporarySecurityTargetWeight(asset_code, weight)  # type: ignore[arg-type]

    assert error.value.reason_code == reason_code


def test_typed_target_set_rejects_empty_duplicate_and_inaccurate_remainder() -> None:
    one = TemporarySecurityTargetWeight("600000.SH", Decimal("0.5"))
    full = TemporarySecurityTargetWeight("600000.SH", Decimal("1"))
    with pytest.raises(TemporaryTargetValidationError) as empty:
        TemporarySecurityTargets((), Decimal("1"))
    with pytest.raises(TemporaryTargetValidationError) as duplicate:
        TemporarySecurityTargets((one, one), Decimal("0"))
    with pytest.raises(TemporaryTargetValidationError) as wrong_cash:
        TemporarySecurityTargets((one,), Decimal("0.4"))
    with pytest.raises(TemporaryTargetValidationError) as invalid_cash:
        TemporarySecurityTargets((one,), Decimal("Infinity"))
    with pytest.raises(TemporaryTargetValidationError) as signed_zero_cash:
        TemporarySecurityTargets((full,), Decimal("-0"))

    assert empty.value.reason_code == "TARGET_ENTRY_COUNT_INVALID"
    assert duplicate.value.reason_code == "TARGET_DUPLICATE_NORMALIZED_ASSET"
    assert wrong_cash.value.reason_code == "TARGET_CASH_REMAINDER_INVALID"
    assert invalid_cash.value.reason_code == "TARGET_CASH_REMAINDER_INVALID"
    assert signed_zero_cash.value.reason_code == "TARGET_CASH_REMAINDER_INVALID"


@pytest.mark.parametrize(
    ("current_codes", "reason_code"),
    [
        (("000001.SZ",), "TARGET_SCOPE_INCOMPLETE"),
        (("bad",), "TARGET_HOLDING_CODE_INVALID"),
        ((7,), "TARGET_HOLDING_CODE_INVALID"),
    ],
)
def test_current_holdings_must_have_canonical_explicit_targets(
    current_codes: tuple[object, ...],
    reason_code: str,
) -> None:
    targets = TemporarySecurityTargets(
        (TemporarySecurityTargetWeight("600000.SH", Decimal("0")),),
        Decimal("1"),
    )

    with pytest.raises(TemporaryTargetValidationError) as error:
        targets.require_current_position_coverage(current_codes)  # type: ignore[arg-type]

    assert error.value.reason_code == reason_code
