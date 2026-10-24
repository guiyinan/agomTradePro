"""Pure row-assembly contracts for the historical sellable diagnostic."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, Inexact, Rounded, localcontext

import pytest

from apps.simulated_trading.domain.historical_sellable_difference import (
    HistoricalPositionMappingFact,
    HistoricalSellableDifferenceRow,
    HistoricalSourcePositionFact,
    HistoricalTargetPositionFact,
    assemble_historical_difference_rows,
)

pytestmark = pytest.mark.unit

_ACCOUNT_ID = 15
_REPORTED_AT = datetime(2026, 10, 25, tzinfo=UTC)


def _source(
    *,
    position_id: int = 12,
    asset_code: str = "600000.SH",
    quantity: Decimal | None = Decimal("300.000000"),
    quantity_known: bool = True,
    quantity_reason_code: str | None = None,
    is_closed: bool = False,
) -> HistoricalSourcePositionFact:
    """Build a complete source fact without ORM or Application fixtures."""

    return HistoricalSourcePositionFact(
        portfolio_id=11,
        position_id=position_id,
        asset_code=asset_code,
        quantity=quantity,
        quantity_known=quantity_known,
        quantity_reason_code=quantity_reason_code,
        is_closed=is_closed,
        record_updated_at=_REPORTED_AT,
    )


def _target(
    *,
    position_id: int = 14,
    account_id: int = _ACCOUNT_ID,
    asset_code: str = "600000.SH",
    quantity: Decimal | None = Decimal("300.000000"),
    available_quantity: Decimal | None = Decimal("80.000000"),
    available_quantity_known: bool | None = True,
) -> HistoricalTargetPositionFact:
    """Build a selected target fact from its complete typed projection."""

    return HistoricalTargetPositionFact(
        position_id=position_id,
        account_id=account_id,
        asset_code=asset_code,
        quantity=quantity,
        available_quantity=available_quantity,
        available_quantity_known=available_quantity_known,
    )


def _mapping(
    *,
    mapping_id: int = 13,
    source_app: str = "account",
    source_table: str = "position",
    source_id: int = 12,
    target_table: str = "simulated_position",
    target_id: int = 14,
) -> HistoricalPositionMappingFact:
    """Build a migration locator with explicit source and target identity."""

    return HistoricalPositionMappingFact(
        mapping_id=mapping_id,
        source_app=source_app,
        source_table=source_table,
        source_id=source_id,
        target_table=target_table,
        target_id=target_id,
    )


def _assemble(
    *,
    sources: tuple[HistoricalSourcePositionFact, ...] = (),
    targets: tuple[HistoricalTargetPositionFact, ...] = (),
    mappings: tuple[HistoricalPositionMappingFact, ...] = (),
    existing_target_position_ids: frozenset[int] | None = None,
) -> tuple[HistoricalSellableDifferenceRow, ...]:
    """Call the public pure assembler with the requested account scope."""

    known_target_ids = (
        existing_target_position_ids
        if existing_target_position_ids is not None
        else frozenset(target.position_id for target in targets)
    )
    return assemble_historical_difference_rows(
        source_positions=sources,
        target_positions=targets,
        mappings=mappings,
        existing_target_position_ids=known_target_ids,
        account_id=_ACCOUNT_ID,
    )


def _source_row(
    rows: tuple[HistoricalSellableDifferenceRow, ...],
    position_id: int,
) -> HistoricalSellableDifferenceRow:
    """Select exactly one row emitted for a source position."""

    matches = tuple(row for row in rows if row.source_position_id == position_id)
    assert len(matches) == 1
    return matches[0]


def _assert_unqualified(row: HistoricalSellableDifferenceRow) -> None:
    """No diagnostic row is a settlement or sellability decision input."""

    assert row.supported_sellable_quantity is None
    assert row.requires_reconciliation is True


@pytest.mark.parametrize("available_known", [True, False])
def test_exact_one_to_one_mapping_preserves_stored_available_knowledge(
    available_known: bool,
) -> None:
    """An exact mapped comparison keeps the source flag but never claims support."""

    rows = _assemble(
        sources=(_source(),),
        targets=(_target(available_quantity_known=available_known),),
        mappings=(_mapping(),),
    )

    assert len(rows) == 1
    row = _source_row(rows, 12)
    assert row.position_mapping_id == 13
    assert row.target_position_id == 14
    assert row.source_asset_code == row.target_asset_code == "600000.SH"
    assert row.source_total_quantity == row.target_total_quantity == Decimal("300.000000")
    assert row.stored_available_quantity == Decimal("80.000000")
    assert row.stored_available_quantity_known is available_known
    assert row.total_quantity_difference == Decimal("0.000000")
    assert "TOTAL_QUANTITY_MISMATCH" not in row.reason_codes
    _assert_unqualified(row)


def test_missing_source_mapping_retains_source_but_has_no_target_values() -> None:
    """A source with no map is visible as a gap without an inferred target."""

    rows = _assemble(sources=(_source(),))

    assert len(rows) == 1
    row = _source_row(rows, 12)
    assert row.position_mapping_id is None
    assert row.target_position_id is None
    assert row.target_total_quantity is None
    assert row.total_quantity_difference is None
    assert "POSITION_MAP_MISSING" in row.reason_codes
    _assert_unqualified(row)


def test_wrong_target_table_does_not_read_a_simulated_position() -> None:
    """A mapping to a different table cannot be treated as a target match."""

    rows = _assemble(
        sources=(_source(),),
        targets=(_target(),),
        mappings=(_mapping(target_table="other_position"),),
    )

    assert len(rows) == 2
    row = _source_row(rows, 12)
    assert row.mapping_target_table == "other_position"
    assert row.mapping_target_id is None
    assert row.target_position_id is None
    assert row.target_asset_code is None
    assert row.target_total_quantity is None
    assert "POSITION_MAP_TARGET_TABLE_MISMATCH" in row.reason_codes
    _assert_unqualified(row)
    target_only = next(item for item in rows if item.source_position_id is None)
    assert target_only.target_position_id == 14
    assert target_only.source_total_quantity is None
    assert "POSITION_SOURCE_MISSING" in target_only.reason_codes
    _assert_unqualified(target_only)


def test_mapping_to_missing_target_is_reported_without_target_values() -> None:
    """A dangling target locator does not cause an unrelated row to be read."""

    rows = _assemble(sources=(_source(),), mappings=(_mapping(target_id=99),))

    assert len(rows) == 1
    row = _source_row(rows, 12)
    assert row.position_mapping_id == 13
    assert row.mapping_target_id is None
    assert row.target_position_id is None
    assert row.target_total_quantity is None
    assert "POSITION_MAP_TARGET_MISSING" in row.reason_codes
    _assert_unqualified(row)


def test_forward_ambiguous_source_mapping_is_not_resolved_by_order() -> None:
    """Two mappings for one source remain ambiguous even when both targets exist."""

    rows = _assemble(
        sources=(_source(),),
        targets=(_target(position_id=14), _target(position_id=16)),
        mappings=(_mapping(mapping_id=13), _mapping(mapping_id=17, target_id=16)),
    )

    assert len(rows) == 1
    row = _source_row(rows, 12)
    assert row.position_mapping_id is None
    assert row.target_position_id is None
    assert row.total_quantity_difference is None
    assert "POSITION_MAP_SOURCE_AMBIGUOUS" in row.reason_codes
    _assert_unqualified(row)


def test_reverse_many_to_one_mapping_marks_each_source_ambiguous() -> None:
    """Two source positions cannot both claim the same unique target mapping."""

    rows = _assemble(
        sources=(_source(position_id=12), _source(position_id=18)),
        targets=(_target(),),
        mappings=(_mapping(mapping_id=13), _mapping(mapping_id=19, source_id=18)),
    )

    assert len(rows) == 2
    for source_id in (12, 18):
        row = _source_row(rows, source_id)
        assert row.target_position_id == 14
        assert "POSITION_MAP_REVERSE_AMBIGUOUS" in row.reason_codes
        _assert_unqualified(row)


def test_asset_mismatch_is_reported_even_when_quantities_match() -> None:
    """Equal numeric totals do not override a different security identity."""

    rows = _assemble(
        sources=(_source(asset_code="600000.SH"),),
        targets=(_target(asset_code="000001.SZ"),),
        mappings=(_mapping(),),
    )

    row = _source_row(rows, 12)
    assert row.total_quantity_difference == Decimal("0.000000")
    assert "POSITION_MAP_ASSET_MISMATCH" in row.reason_codes
    _assert_unqualified(row)


def test_total_quantity_delta_is_exact_under_low_decimal_context() -> None:
    """Assembler comparison retains all six places despite caller precision."""

    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        rows = _assemble(
            sources=(_source(quantity=Decimal("300.123456")),),
            targets=(_target(quantity=Decimal("100.000001")),),
            mappings=(_mapping(),),
        )

    row = _source_row(rows, 12)
    assert row.total_quantity_difference == Decimal("200.123455")
    assert "TOTAL_QUANTITY_MISMATCH" in row.reason_codes
    _assert_unqualified(row)


def test_owned_target_only_row_does_not_expose_source_fields() -> None:
    """A selected target without a source map stays target-only and unlinked."""

    rows = _assemble(targets=(_target(),))

    assert len(rows) == 1
    row = rows[0]
    assert row.source_position_id is None
    assert row.source_asset_code is None
    assert row.source_total_quantity is None
    assert row.source_quantity_reason_code is None
    assert row.source_position_closed is None
    assert row.position_mapping_id is None
    assert row.total_quantity_difference is None
    assert "POSITION_SOURCE_MISSING" in row.reason_codes
    _assert_unqualified(row)


def test_dangling_source_mapping_does_not_disclose_source_locator() -> None:
    """A dangling in-scope map reports the owned target without source identity."""

    rows = _assemble(
        targets=(_target(),),
        mappings=(_mapping(source_id=999),),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.target_position_id == 14
    assert row.position_mapping_id == 13
    assert row.mapping_target_id == 14
    assert row.source_position_id is None
    assert row.source_asset_code is None
    assert row.source_total_quantity is None
    assert row.source_position_closed is None
    assert "POSITION_MAP_SOURCE_MISSING_OR_OUTSIDE_SCOPE" in row.reason_codes
    _assert_unqualified(row)


def test_closed_source_is_retained_and_explicitly_marked() -> None:
    """Closed legacy rows remain historical rows and cannot imply current support."""

    rows = _assemble(
        sources=(_source(is_closed=True),),
        targets=(_target(),),
        mappings=(_mapping(),),
    )

    assert len(rows) == 1
    row = _source_row(rows, 12)
    assert row.source_position_closed is True
    assert row.source_total_quantity == Decimal("300.000000")
    assert "SOURCE_POSITION_CLOSED" in row.reason_codes
    _assert_unqualified(row)


@pytest.mark.parametrize(
    "target_quantity",
    [None, Decimal("NaN"), Decimal("-1")],
)
def test_invalid_target_quantity_stays_unknown(
    target_quantity: Decimal | None,
) -> None:
    """Malformed stored totals remain null and never produce a numeric delta."""

    rows = _assemble(
        sources=(_source(),),
        targets=(_target(quantity=target_quantity),),
        mappings=(_mapping(),),
    )

    row = _source_row(rows, 12)
    assert row.target_total_quantity is None
    assert row.total_quantity_difference is None
    assert "TARGET_QUANTITY_INVALID" in row.reason_codes
    _assert_unqualified(row)


@pytest.mark.parametrize(
    "available_quantity",
    [None, Decimal("NaN"), Decimal("-1")],
)
def test_invalid_available_quantity_is_null_without_erasing_knowledge_flag(
    available_quantity: Decimal | None,
) -> None:
    """Invalid available values are not repaired, while their stored flag remains visible."""

    rows = _assemble(
        sources=(_source(),),
        targets=(
            _target(
                available_quantity=available_quantity,
                available_quantity_known=False,
            ),
        ),
        mappings=(_mapping(),),
    )

    row = _source_row(rows, 12)
    assert row.stored_available_quantity is None
    assert row.stored_available_quantity_known is False
    assert "AVAILABLE_QUANTITY_INVALID" in row.reason_codes
    _assert_unqualified(row)


def test_empty_inputs_produce_no_synthetic_differences() -> None:
    """An empty selected scope remains an empty report row tuple."""

    assert _assemble() == ()
