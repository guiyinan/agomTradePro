"""Exact quantity and unknown-state contracts for the historical diagnostic."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, Inexact, Rounded, localcontext
from typing import Literal

import pytest

from apps.account.domain.historical_position_quantity import normalize_legacy_share_quantity
from apps.simulated_trading.domain.historical_sellable_difference import (
    HistoricalLedgerEvidence,
    HistoricalLedgerFillFact,
    HistoricalLedgerHoldFact,
    HistoricalLedgerSellabilityProof,
    HistoricalPositionMappingFact,
    HistoricalSourcePositionFact,
    HistoricalTargetPositionFact,
    assemble_historical_difference_rows,
    assemble_simulated_position_sellability_rows,
    exact_quantity_difference,
    format_ledger_quantity,
    normalize_ledger_quantity,
    prove_historical_ledger_sellability,
)

pytestmark = pytest.mark.unit

_LEDGER_CUTOFF = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
_SOURCE_UPDATED_AT = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
_LEDGER_SECURITY_ID = "SIM.SECURITY.14"
_LEDGER_ASSET_CODE = "600000.SH"
_RECEIPT_HASH = "a" * 64
_OPENING_MARK_HASH = "b" * 64
_HOLD_HASH = "c" * 64


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
        owner_user_id=15,
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
        owner_user_id=15,
        account_id=15,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.source_total_quantity is None
    assert row.source_quantity_known is False
    assert row.total_quantity_difference is None
    assert "SOURCE_QUANTITY_UNKNOWN" in row.reason_codes


def _ledger_fill(
    *,
    trade_id: int = 1,
    reservation_id: int = 101,
    side: Literal["buy", "sell"] = "buy",
    quantity: Decimal = Decimal("300.000000"),
    recorded_at: datetime | None = None,
    settlement_status: Literal["pending", "released"] | None = "released",
    settlement_lag_sessions: int = 0,
    release_proof_hash: str | None = None,
    initial_position_mark_hash: str | None = _OPENING_MARK_HASH,
    receipt_version: int = 2,
    receipt_hash: str = _RECEIPT_HASH,
) -> HistoricalLedgerFillFact:
    """Build one typed immutable receipt row for the public ledger verifier."""

    return HistoricalLedgerFillFact(
        trade_id=trade_id,
        reservation_id=reservation_id,
        fill_sequence=1,
        binding_version=4,
        receipt_version=receipt_version,
        receipt_hash=receipt_hash,
        security_id=_LEDGER_SECURITY_ID,
        asset_code=_LEDGER_ASSET_CODE,
        side=side,
        quantity=quantity,
        recorded_at=recorded_at or _LEDGER_CUTOFF - timedelta(minutes=5),
        prior_fill_count=0,
        settlement_status=settlement_status,
        settlement_lag_sessions=settlement_lag_sessions,
        release_proof_hash=release_proof_hash,
        initial_position_mark_hash=initial_position_mark_hash,
    )


def _ledger_hold(quantity: Decimal = Decimal("70.000000")) -> HistoricalLedgerHoldFact:
    """Build one active sell reservation bound to the ledger security."""

    return HistoricalLedgerHoldFact(
        reservation_id=901,
        security_id=_LEDGER_SECURITY_ID,
        asset_code=_LEDGER_ASSET_CODE,
        side="sell",
        remaining_shares=quantity,
        reservation_state_hash=_HOLD_HASH,
    )


def _ledger_evidence(
    *,
    source_scope: Literal["account_position_mapping", "simulated_position"] = (
        "account_position_mapping"
    ),
    source_total_quantity: Decimal | None = Decimal("300.000000"),
    target_total_quantity: Decimal = Decimal("300.000000"),
    fills: tuple[HistoricalLedgerFillFact, ...] | None = None,
    active_holds: tuple[HistoricalLedgerHoldFact, ...] = (),
    unsupported_trade_ids: tuple[int, ...] = (),
) -> HistoricalLedgerEvidence:
    """Build a complete source-mapped or native simulated-position proof input."""

    mapped = source_scope == "account_position_mapping"
    return HistoricalLedgerEvidence(
        owner_user_id=15,
        account_id=15,
        source_scope=source_scope,
        source_position_id=12 if mapped else None,
        target_position_id=14,
        position_mapping_id=13 if mapped else None,
        mapping_fact=_injected_mapping() if mapped else None,
        security_id=_LEDGER_SECURITY_ID,
        asset_code=_LEDGER_ASSET_CODE,
        cutoff_at=_LEDGER_CUTOFF,
        source_total_quantity=source_total_quantity if mapped else None,
        source_record_updated_at=_SOURCE_UPDATED_AT if mapped else None,
        target_total_quantity=target_total_quantity,
        fills=(fills if fills is not None else (_ledger_fill(),)),
        active_holds=active_holds,
        unsupported_trade_ids=unsupported_trade_ids,
    )


def _assert_unproven_ledger(
    proof: HistoricalLedgerSellabilityProof,
    reason_code: str,
) -> None:
    """Failed evidence returns no partial balances or proof digest as usable data."""

    assert proof.reason_codes[0] == reason_code
    assert proof.total_quantity is None
    assert proof.available_quantity is None
    assert proof.active_sell_hold_quantity is None
    assert proof.supported_sellable_quantity is None
    assert proof.proof_hash is None


def test_v4_replay_keeps_total_settled_available_and_sell_holds_distinct() -> None:
    """A pending buy increases total only; a sell and active hold reduce free shares."""

    fills = (
        _ledger_fill(),
        _ledger_fill(
            trade_id=2,
            reservation_id=102,
            quantity=Decimal("100.000000"),
            receipt_version=1,
            initial_position_mark_hash=None,
            settlement_status="pending",
        ),
        _ledger_fill(
            trade_id=3,
            reservation_id=103,
            side="sell",
            quantity=Decimal("50.000000"),
            receipt_version=1,
            initial_position_mark_hash=None,
            settlement_status=None,
        ),
    )
    evidence = _ledger_evidence(
        source_total_quantity=Decimal("350.000000"),
        target_total_quantity=Decimal("350.000000"),
        fills=fills,
        active_holds=(_ledger_hold(),),
    )

    proof = prove_historical_ledger_sellability(evidence)

    assert proof.reason_codes == ()
    assert proof.total_quantity == Decimal("350.000000")
    assert proof.available_quantity == Decimal("250.000000")
    assert proof.active_sell_hold_quantity == Decimal("70.000000")
    assert proof.supported_sellable_quantity == Decimal("180.000000")
    assert proof.proof_hash is not None and len(proof.proof_hash) == 64

    source = _injected_source(Decimal("350.000000"), True, None)
    target = HistoricalTargetPositionFact(
        position_id=14,
        account_id=15,
        asset_code=_LEDGER_ASSET_CODE,
        quantity=Decimal("350.000000"),
        available_quantity=Decimal("220.000000"),
        available_quantity_known=False,
        first_buy_date_known=True,
        ledger_proof=proof,
    )
    rows = assemble_historical_difference_rows(
        source_positions=(source,),
        target_positions=(target,),
        mappings=(_injected_mapping(),),
        existing_target_position_ids=frozenset({14}),
        owner_user_id=15,
        account_id=15,
    )

    row = rows[0]
    assert row.total_quantity_difference == Decimal("0.000000")
    assert row.ledger_total_quantity == Decimal("350.000000")
    assert row.ledger_available_quantity == Decimal("250.000000")
    assert row.active_sell_hold_quantity == Decimal("70.000000")
    assert row.supported_sellable_quantity == Decimal("180.000000")
    assert row.repair_available_quantity == Decimal("250.000000")
    assert row.repair_ready is True
    assert row.repair_needed is True


def test_empty_or_legacy_chain_has_no_proven_opening_anchor() -> None:
    """An absent chain or a pre-anchor receipt cannot be interpreted as zero shares."""

    empty_proof = prove_historical_ledger_sellability(
        _ledger_evidence(fills=()),
    )
    legacy_opening_proof = prove_historical_ledger_sellability(
        _ledger_evidence(
            fills=(
                _ledger_fill(
                    receipt_version=1,
                    initial_position_mark_hash=None,
                ),
            ),
        ),
    )

    _assert_unproven_ledger(empty_proof, "LEDGER_OPENING_ANCHOR_MISSING")
    _assert_unproven_ledger(legacy_opening_proof, "LEDGER_OPENING_ANCHOR_INVALID")


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("source_total_quantity", None),
        ("position_mapping_id", 99),
        ("mapping_fact", None),
    ],
)
def test_missing_source_or_mapping_identity_cannot_prove_a_balance(
    field_name: str,
    replacement: object,
) -> None:
    """The proof is tied to a known source total and its exact source-to-target map."""

    evidence = replace(_ledger_evidence(), **{field_name: replacement})

    proof = prove_historical_ledger_sellability(evidence)

    _assert_unproven_ledger(proof, "LEDGER_SCOPE_INVALID")


@pytest.mark.parametrize(
    "quantity",
    [Decimal("0.0000001"), Decimal("NaN")],
)
def test_invalid_fill_decimal_cannot_enter_the_proven_ledger(
    quantity: Decimal,
) -> None:
    """Unsupported scale and non-finite share quantities block the whole proof."""

    proof = prove_historical_ledger_sellability(
        _ledger_evidence(fills=(_ledger_fill(quantity=quantity),)),
    )

    _assert_unproven_ledger(proof, "LEDGER_FILL_QUANTITY_INVALID")


def test_fill_after_cutoff_and_tampered_receipt_hash_are_unproven() -> None:
    """Neither later events nor malformed receipt digests can support a historical row."""

    later_fill = _ledger_fill(recorded_at=_LEDGER_CUTOFF + timedelta(seconds=1))
    late_proof = prove_historical_ledger_sellability(
        _ledger_evidence(fills=(later_fill,)),
    )
    tampered_hash_proof = prove_historical_ledger_sellability(
        _ledger_evidence(fills=(_ledger_fill(receipt_hash="not-a-sha256"),)),
    )

    _assert_unproven_ledger(late_proof, "LEDGER_FILL_AFTER_CUTOFF")
    _assert_unproven_ledger(tampered_hash_proof, "LEDGER_FILL_IDENTITY_INVALID")


def test_total_shares_do_not_substitute_for_settled_sellable_shares() -> None:
    """A pending opening buy contributes total shares but cannot fund a later sell."""

    fills = (
        _ledger_fill(settlement_status="pending"),
        _ledger_fill(
            trade_id=2,
            reservation_id=102,
            side="sell",
            quantity=Decimal("1.000000"),
            receipt_version=1,
            initial_position_mark_hash=None,
            settlement_status=None,
        ),
    )
    proof = prove_historical_ledger_sellability(
        _ledger_evidence(
            source_total_quantity=Decimal("299.000000"),
            target_total_quantity=Decimal("299.000000"),
            fills=fills,
        ),
    )

    _assert_unproven_ledger(proof, "LEDGER_SELL_EXCEEDS_PROVEN_AVAILABLE")


def test_source_total_mismatch_and_unknown_legacy_trade_are_not_normalized_away() -> None:
    """Known source disagreement and unsupported trade versions both fail closed."""

    mismatch = prove_historical_ledger_sellability(
        _ledger_evidence(source_total_quantity=Decimal("301.000000")),
    )
    unknown_trade = prove_historical_ledger_sellability(
        _ledger_evidence(unsupported_trade_ids=(22,)),
    )

    _assert_unproven_ledger(mismatch, "LEDGER_SOURCE_TOTAL_MISMATCH")
    _assert_unproven_ledger(unknown_trade, "LEDGER_TRADE_VERSION_UNSUPPORTED")


def test_target_total_mismatch_and_invalid_hold_chain_fail_closed() -> None:
    """Ledger totals and each active reservation digest are independently verified."""

    target_mismatch = prove_historical_ledger_sellability(
        _ledger_evidence(target_total_quantity=Decimal("301.000000")),
    )
    bad_hold_hash = prove_historical_ledger_sellability(
        _ledger_evidence(
            active_holds=(replace(_ledger_hold(), reservation_state_hash="bad"),),
        ),
    )
    hold_exceeds_available = prove_historical_ledger_sellability(
        _ledger_evidence(active_holds=(_ledger_hold(Decimal("301.000000")),)),
    )

    _assert_unproven_ledger(target_mismatch, "LEDGER_TARGET_TOTAL_MISMATCH")
    _assert_unproven_ledger(bad_hold_hash, "LEDGER_ACTIVE_HOLD_INVALID")
    _assert_unproven_ledger(hold_exceeds_available, "LEDGER_ACTIVE_HOLDS_EXCEED_AVAILABLE")


def test_settlement_release_requires_its_exact_proof() -> None:
    """A delayed buy release cannot become available without a valid release digest."""

    missing_release = prove_historical_ledger_sellability(
        _ledger_evidence(
            fills=(
                _ledger_fill(
                    settlement_lag_sessions=1,
                ),
            ),
        ),
    )

    _assert_unproven_ledger(missing_release, "LEDGER_RELEASE_PROOF_MISSING")


def test_native_simulated_row_preserves_scope_and_rejects_bad_proof_hash() -> None:
    """Native rows carry no fabricated legacy mapping and require a valid proof digest."""

    evidence = _ledger_evidence(
        source_scope="simulated_position",
        active_holds=(_ledger_hold(Decimal("100.000000")),),
    )
    proof = prove_historical_ledger_sellability(evidence)
    target = HistoricalTargetPositionFact(
        position_id=14,
        account_id=15,
        asset_code=_LEDGER_ASSET_CODE,
        quantity=Decimal("300.000000"),
        available_quantity=Decimal("300.000000"),
        available_quantity_known=True,
        first_buy_date_known=True,
        ledger_proof=proof,
    )

    row = assemble_simulated_position_sellability_rows(
        target_positions=(target,),
        owner_user_id=15,
        account_id=15,
    )[0]
    tampered_row = assemble_simulated_position_sellability_rows(
        target_positions=(replace(target, ledger_proof=replace(proof, proof_hash="bad")),),
        owner_user_id=15,
        account_id=15,
    )[0]

    assert proof.reason_codes == ()
    assert row.source_position_id is None
    assert row.position_mapping_id is None
    assert row.ledger_total_quantity == Decimal("300.000000")
    assert row.ledger_available_quantity == Decimal("300.000000")
    assert row.active_sell_hold_quantity == Decimal("100.000000")
    assert row.supported_sellable_quantity == Decimal("200.000000")
    assert row.repair_ready is True
    assert tampered_row.ledger_total_quantity is None
    assert tampered_row.supported_sellable_quantity is None
    assert tampered_row.repair_ready is False


def test_native_projection_excludes_a_valid_foreign_account_row() -> None:
    """A caller-supplied foreign target must not be emitted in selected account scope."""

    foreign_evidence = replace(
        _ledger_evidence(source_scope="simulated_position"),
        account_id=99,
    )
    foreign_proof = prove_historical_ledger_sellability(foreign_evidence)
    foreign_target = HistoricalTargetPositionFact(
        position_id=14,
        account_id=99,
        asset_code=_LEDGER_ASSET_CODE,
        quantity=Decimal("300.000000"),
        available_quantity=Decimal("300.000000"),
        available_quantity_known=True,
        first_buy_date_known=True,
        ledger_proof=foreign_proof,
    )

    rows = assemble_simulated_position_sellability_rows(
        target_positions=(foreign_target,),
        owner_user_id=15,
        account_id=15,
    )

    assert rows == ()
