"""Exact quantity and unknown-state contracts for the historical diagnostic."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, Inexact, Rounded, localcontext

import pytest

from apps.account.domain.historical_position_quantity import normalize_legacy_share_quantity
from apps.simulated_trading.domain.historical_sellable_difference import (
    HistoricalPositionMappingFact,
    HistoricalSourcePositionFact,
    HistoricalTargetPositionFact,
    assemble_historical_difference_rows,
    exact_quantity_difference,
    format_ledger_quantity,
    normalize_ledger_quantity,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected", "reason"),
    [
        (None, None, "SOURCE_QUANTITY_INVALID"),
        (True, None, "SOURCE_QUANTITY_INVALID"),
        ("100", None, "SOURCE_QUANTITY_INVALID"),
        (float("nan"), None, "SOURCE_QUANTITY_INVALID"),
        (float("inf"), None, "SOURCE_QUANTITY_INVALID"),
        (float("-inf"), None, "SOURCE_QUANTITY_INVALID"),
        (-1, None, "SOURCE_QUANTITY_INVALID"),
        (Decimal("NaN"), None, "SOURCE_QUANTITY_INVALID"),
        (Decimal("-0.000001"), None, "SOURCE_QUANTITY_INVALID"),
        (Decimal("100000000000000"), None, "SOURCE_QUANTITY_PRECISION_UNSUPPORTED"),
        (Decimal("0.0000001"), None, "SOURCE_QUANTITY_PRECISION_UNSUPPORTED"),
        (0.1, "0.100000", None),
        (0, "0.000000", None),
        (Decimal("100.0000010"), "100.000001", None),
        (Decimal("99999999999999.999999"), "99999999999999.999999", None),
    ],
)
def test_legacy_quantity_preserves_scale_and_never_replaces_unknown_with_zero(
    value: object,
    expected: str | None,
    reason: str | None,
) -> None:
    """Interpret stored legacy numbers without repairing or rounding the shares."""

    result = normalize_legacy_share_quantity(value)

    assert result.known is (expected is not None)
    assert result.value == (Decimal(expected) if expected is not None else None)
    assert result.reason_code == reason


@pytest.mark.parametrize(
    ("value", "expected", "reason"),
    [
        (None, None, "TARGET_QUANTITY_INVALID"),
        (Decimal("NaN"), None, "TARGET_QUANTITY_INVALID"),
        (Decimal("Infinity"), None, "TARGET_QUANTITY_INVALID"),
        (Decimal("-Infinity"), None, "TARGET_QUANTITY_INVALID"),
        (Decimal("-0.000001"), None, "TARGET_QUANTITY_INVALID"),
        (Decimal("100000000000000"), None, "TARGET_QUANTITY_PRECISION_UNSUPPORTED"),
        (Decimal("0.0000001"), None, "TARGET_QUANTITY_PRECISION_UNSUPPORTED"),
        (Decimal("0"), "0.000000", None),
        (Decimal("100.0000010"), "100.000001", None),
        (Decimal("99999999999999.999999"), "99999999999999.999999", None),
    ],
)
def test_target_quantity_keeps_unknown_distinct_from_explicit_zero(
    value: Decimal | None,
    expected: str | None,
    reason: str | None,
) -> None:
    """A malformed or over-precision stored target is diagnostic, never a zero."""

    result = normalize_ledger_quantity(value)

    assert result.value == (Decimal(expected) if expected is not None else None)
    assert result.reason_code == reason


@pytest.mark.parametrize("value", [Decimal("7.0000000"), Decimal("7.0000004")])
def test_caller_decimal_traps_do_not_change_legacy_quantity_knowledge(value: Decimal) -> None:
    """Lossless trailing zeros and unsupported fractions have stable outcomes."""

    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        result = normalize_legacy_share_quantity(value)

    if value == Decimal("7.0000000"):
        assert result.value == Decimal("7.000000")
        assert result.known is True
    else:
        assert result.value is None
        assert result.known is False
        assert result.reason_code == "SOURCE_QUANTITY_PRECISION_UNSUPPORTED"


@pytest.mark.parametrize("value", [Decimal("7.0000000"), Decimal("7.0000004")])
def test_caller_decimal_traps_do_not_change_target_quantity_knowledge(value: Decimal) -> None:
    """Storage validation cannot inherit exceptions from the caller's context."""

    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        result = normalize_ledger_quantity(value)

    if value == Decimal("7.0000000"):
        assert result.value == Decimal("7.000000")
        assert result.reason_code is None
    else:
        assert result.value is None
        assert result.reason_code == "TARGET_QUANTITY_PRECISION_UNSUPPORTED"


def test_quantity_difference_is_exact_under_low_caller_precision() -> None:
    """The many-digit difference distinguishes a protected Decimal operation."""

    with localcontext() as context:
        context.prec = 2
        difference = exact_quantity_difference(Decimal("300.123456"), Decimal("100.000001"))

    assert difference == Decimal("200.123455")


@pytest.mark.parametrize(
    ("source", "target"),
    [(None, Decimal("1")), (Decimal("1"), None), (None, None)],
)
def test_unknown_quantity_produces_no_numeric_difference(
    source: Decimal | None,
    target: Decimal | None,
) -> None:
    """A missing side of the comparison must never be filled with zero."""

    assert exact_quantity_difference(source, target) is None


def test_format_keeps_null_zero_and_lossless_trailing_zeros_distinct() -> None:
    """Canonical decimal strings stay usable under caller-enabled rounding traps."""

    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        assert format_ledger_quantity(None) is None
        assert format_ledger_quantity(Decimal("0")) == "0.000000"
        assert format_ledger_quantity(Decimal("7.0000000")) == "7.000000"


def _injected_source(
    quantity: Decimal | None,
    known: bool,
    reason: str | None,
) -> HistoricalSourcePositionFact:
    """Build a typed read-port result without relying on the default ORM reader."""

    return HistoricalSourcePositionFact(
        portfolio_id=11,
        position_id=12,
        asset_code="600000.SH",
        quantity=quantity,
        quantity_known=known,
        quantity_reason_code=reason,
        is_closed=False,
        record_updated_at=datetime(2026, 10, 25, tzinfo=UTC),
    )


def _injected_mapping() -> HistoricalPositionMappingFact:
    """Bind one exact legacy position to the target locator under inspection."""

    return HistoricalPositionMappingFact(
        mapping_id=13,
        source_app="account",
        source_table="position",
        source_id=12,
        target_table="simulated_position",
        target_id=14,
    )


def test_injected_foreign_account_fact_cannot_expose_target_values() -> None:
    """The Domain scope check must survive an inconsistent typed reader response."""

    foreign = HistoricalTargetPositionFact(
        position_id=14,
        account_id=99,
        asset_code="FOREIGN-PRIVATE-ASSET",
        quantity=Decimal("987.000000"),
        available_quantity=Decimal("987.000000"),
        available_quantity_known=True,
    )

    rows = assemble_historical_difference_rows(
        source_positions=(_injected_source(Decimal("300.000000"), True, None),),
        target_positions=(foreign,),
        mappings=(_injected_mapping(),),
        existing_target_position_ids=frozenset({14}),
        account_id=15,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.target_position_id is None
    assert row.mapping_target_id is None
    assert row.target_asset_code is None
    assert row.target_total_quantity is None
    assert row.stored_available_quantity is None
    assert row.total_quantity_difference is None
    assert "POSITION_MAP_ACCOUNT_MISMATCH" in row.reason_codes


@pytest.mark.parametrize(
    ("quantity", "known", "reason"),
    [
        (Decimal("300.000000"), False, None),
        (Decimal("300.000000"), True, "SOURCE_QUANTITY_PRECISION_UNSUPPORTED"),
        (None, True, None),
        (Decimal("0.0000001"), True, None),
        (Decimal("NaN"), True, None),
    ],
)
def test_injected_inconsistent_source_knowledge_cannot_create_a_numeric_difference(
    quantity: Decimal | None,
    known: bool,
    reason: str | None,
) -> None:
    """Unknown or contradictory source metadata must not become a repair amount."""

    target = HistoricalTargetPositionFact(
        position_id=14,
        account_id=15,
        asset_code="600000.SH",
        quantity=Decimal("100.000000"),
        available_quantity=Decimal("100.000000"),
        available_quantity_known=True,
    )

    rows = assemble_historical_difference_rows(
        source_positions=(_injected_source(quantity, known, reason),),
        target_positions=(target,),
        mappings=(_injected_mapping(),),
        existing_target_position_ids=frozenset({14}),
        account_id=15,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.source_total_quantity is None
    assert row.source_quantity_known is False
    assert row.total_quantity_difference is None
    assert "SOURCE_QUANTITY_UNKNOWN" in row.reason_codes
