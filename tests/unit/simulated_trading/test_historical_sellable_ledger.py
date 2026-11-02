"""Pure reconstruction rules for a complete system-owned V4 sellability chain."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, Inexact, Rounded, localcontext
from typing import Literal

import pytest

from apps.simulated_trading.domain.historical_sellable_difference import (
    HistoricalLedgerEvidence,
    HistoricalLedgerFillFact,
    HistoricalLedgerHoldFact,
    HistoricalPositionMappingFact,
    HistoricalSourcePositionFact,
    HistoricalTargetPositionFact,
    assemble_historical_difference_rows,
    assemble_simulated_position_sellability_rows,
    prove_historical_ledger_sellability,
)

pytestmark = pytest.mark.unit

_CUTOFF = datetime(2026, 11, 2, 8, tzinfo=UTC)
_RECORDED_AT = datetime(2026, 11, 2, 7, tzinfo=UTC)


def _fill(
    *,
    trade_id: int,
    reservation_id: int,
    quantity: str,
    side: Literal["buy", "sell"] = "buy",
    sequence: int = 1,
    prior: int = 0,
    receipt_version: int = 1,
    mark_hash: str | None = None,
    settlement: Literal["pending", "released"] | None = "released",
    lag: int = 1,
    release_hash: str | None = "d" * 64,
) -> HistoricalLedgerFillFact:
    """Construct an exact already-decoded fill fact for a pure domain test."""

    return HistoricalLedgerFillFact(
        trade_id=trade_id,
        reservation_id=reservation_id,
        fill_sequence=sequence,
        binding_version=4,
        receipt_version=receipt_version,
        receipt_hash=f"{trade_id:064x}",
        security_id="XSHG:600000",
        asset_code="600000.SH",
        side=side,
        quantity=Decimal(quantity),
        recorded_at=_RECORDED_AT,
        prior_fill_count=prior,
        settlement_status=settlement,
        settlement_lag_sessions=lag,
        release_proof_hash=release_hash,
        initial_position_mark_hash=mark_hash,
    )


def _evidence(
    *,
    fills: tuple[HistoricalLedgerFillFact, ...],
    holds: tuple[HistoricalLedgerHoldFact, ...] = (),
    unsupported_trade_ids: tuple[int, ...] = (),
    target_quantity: str = "300.000000",
) -> HistoricalLedgerEvidence:
    """Bind the event chain to one exact owner, account, security, and map row."""

    return HistoricalLedgerEvidence(
        owner_user_id=17,
        account_id=29,
        source_scope="account_position_mapping",
        source_position_id=31,
        target_position_id=37,
        position_mapping_id=41,
        mapping_fact=HistoricalPositionMappingFact(
            mapping_id=41,
            source_app="account",
            source_table="position",
            source_id=31,
            target_table="simulated_position",
            target_id=37,
        ),
        security_id="XSHG:600000",
        asset_code="600000.SH",
        cutoff_at=_CUTOFF,
        source_total_quantity=Decimal("300.000000"),
        source_record_updated_at=None,
        target_total_quantity=Decimal(target_quantity),
        fills=fills,
        active_holds=holds,
        unsupported_trade_ids=unsupported_trade_ids,
    )


def _base_fills() -> tuple[HistoricalLedgerFillFact, ...]:
    """Return the 100 released + 200 pending V4 chain used by positive cases."""

    return (
        _fill(
            trade_id=101,
            reservation_id=51,
            quantity="100.000000",
            receipt_version=2,
            mark_hash="a" * 64,
        ),
        _fill(
            trade_id=109,
            reservation_id=52,
            quantity="200.000000",
            settlement="pending",
            release_hash=None,
        ),
    )


def test_reconstructs_300_total_from_zero_anchor_and_only_100_released() -> None:
    """A marked first BUY proves zero genesis; pending quantity does not become sellable."""

    proof = prove_historical_ledger_sellability(_evidence(fills=_base_fills()))

    assert proof.total_quantity == Decimal("300.000000")
    assert proof.available_quantity == Decimal("100.000000")
    assert proof.active_sell_hold_quantity == Decimal("0.000000")
    assert proof.supported_sellable_quantity == Decimal("100.000000")
    assert proof.cutoff_at == _CUTOFF
    assert isinstance(proof.proof_hash, str) and len(proof.proof_hash) == 64
    assert proof.reason_codes == ()


def test_simulated_self_scope_proves_ledger_without_fabricating_source_mapping() -> None:
    """A native simulated account can report its own V4 ledger with source IDs N/A."""

    mapped_evidence = _evidence(fills=_base_fills())
    evidence = replace(
        mapped_evidence,
        source_scope="simulated_position",
        source_position_id=None,
        position_mapping_id=None,
        mapping_fact=None,
        source_total_quantity=None,
        source_record_updated_at=None,
    )
    proof = prove_historical_ledger_sellability(evidence)
    target = HistoricalTargetPositionFact(
        position_id=37,
        account_id=29,
        asset_code="600000.SH",
        quantity=Decimal("300.000000"),
        available_quantity=Decimal("300.000000"),
        available_quantity_known=False,
        first_buy_date_known=True,
        ledger_proof=proof,
    )

    (row,) = assemble_simulated_position_sellability_rows(
        target_positions=(target,),
        owner_user_id=17,
        account_id=29,
    )

    assert proof.total_quantity == Decimal("300.000000")
    assert proof.available_quantity == Decimal("100.000000")
    assert row.source_scope == "simulated_position"
    assert row.source_position_id is None
    assert row.position_mapping_id is None
    assert row.source_total_quantity is None
    assert row.source_quantity_reason_code == "SOURCE_IDENTITY_NOT_APPLICABLE"
    assert row.repair_available_quantity == Decimal("100.000000")
    assert row.supported_sellable_quantity == Decimal("100.000000")


def test_repair_row_uses_settled_available_before_holds_and_reports_free_sellable_after() -> None:
    """An active SELL hold never rewrites the settled available-share balance."""

    hold = HistoricalLedgerHoldFact(
        reservation_id=71,
        security_id="XSHG:600000",
        asset_code="600000.SH",
        side="sell",
        remaining_shares=Decimal("40.000000"),
        reservation_state_hash="e" * 64,
    )
    proof = prove_historical_ledger_sellability(_evidence(fills=_base_fills(), holds=(hold,)))
    source = HistoricalSourcePositionFact(
        portfolio_id=19,
        position_id=31,
        asset_code="600000.SH",
        quantity=Decimal("300.000000"),
        quantity_known=True,
        quantity_reason_code=None,
        is_closed=False,
        record_updated_at=None,
    )
    target = HistoricalTargetPositionFact(
        position_id=37,
        account_id=29,
        asset_code="600000.SH",
        quantity=Decimal("300.000000"),
        available_quantity=Decimal("300.000000"),
        available_quantity_known=False,
        first_buy_date_known=True,
        ledger_proof=proof,
    )
    mapping = HistoricalPositionMappingFact(
        mapping_id=41,
        source_app="account",
        source_table="position",
        source_id=31,
        target_table="simulated_position",
        target_id=37,
    )

    (row,) = assemble_historical_difference_rows(
        source_positions=(source,),
        target_positions=(target,),
        mappings=(mapping,),
        existing_target_position_ids=frozenset({37}),
        owner_user_id=17,
        account_id=29,
    )

    assert row.ledger_total_quantity == Decimal("300.000000")
    assert row.ledger_available_quantity == Decimal("100.000000")
    assert row.active_sell_hold_quantity == Decimal("40.000000")
    assert row.supported_sellable_quantity == Decimal("60.000000")
    assert row.repair_available_quantity == Decimal("100.000000")
    assert row.repair_ready is True
    assert row.repair_needed is True


def test_current_sell_hold_reduces_supported_sellable_without_rewriting_position_basis() -> None:
    """The row repair quantity remains 100 while a 40 share hold leaves 60 free."""

    hold = HistoricalLedgerHoldFact(
        reservation_id=71,
        security_id="XSHG:600000",
        asset_code="600000.SH",
        side="sell",
        remaining_shares=Decimal("40.000000"),
        reservation_state_hash="e" * 64,
    )

    proof = prove_historical_ledger_sellability(_evidence(fills=_base_fills(), holds=(hold,)))

    assert proof.available_quantity == Decimal("100.000000")
    assert proof.active_sell_hold_quantity == Decimal("40.000000")
    assert proof.supported_sellable_quantity == Decimal("60.000000")


def test_new_position_after_a_complete_sell_zero_does_not_reset_the_original_history() -> None:
    """A later marked BUY after clearing zero is a new cycle within the same chain."""

    fills = (
        _fill(
            trade_id=101,
            reservation_id=51,
            quantity="100.000000",
            receipt_version=2,
            mark_hash="a" * 64,
        ),
        _fill(
            trade_id=104,
            reservation_id=53,
            side="sell",
            quantity="100.000000",
            settlement=None,
            lag=0,
            release_hash=None,
        ),
        _fill(
            trade_id=109,
            reservation_id=52,
            quantity="300.000000",
            receipt_version=2,
            mark_hash="b" * 64,
        ),
    )

    proof = prove_historical_ledger_sellability(_evidence(fills=fills))

    assert proof.total_quantity == Decimal("300.000000")
    assert proof.available_quantity == Decimal("300.000000")
    assert proof.supported_sellable_quantity == Decimal("300.000000")


@pytest.mark.parametrize(
    ("fills", "expected_reason"),
    [
        (
            (_fill(trade_id=101, reservation_id=51, quantity="300.000000"),),
            "LEDGER_OPENING_ANCHOR_INVALID",
        ),
        (
            (_fill(trade_id=101, reservation_id=51, quantity="300.000000", receipt_version=2),),
            "LEDGER_OPENING_ANCHOR_INVALID",
        ),
        (
            (
                _fill(
                    trade_id=101,
                    reservation_id=51,
                    quantity="100.000000",
                    receipt_version=2,
                    mark_hash="a" * 64,
                ),
                _fill(
                    trade_id=109,
                    reservation_id=52,
                    quantity="200.000000",
                    sequence=2,
                    prior=1,
                    settlement="pending",
                    release_hash=None,
                ),
            ),
            "LEDGER_FILL_SEQUENCE_GAP",
        ),
        (
            (
                _fill(
                    trade_id=101,
                    reservation_id=51,
                    quantity="100.000000",
                    receipt_version=2,
                    mark_hash="a" * 64,
                ),
                _fill(
                    trade_id=109,
                    reservation_id=52,
                    quantity="200.000000",
                    settlement="released",
                    release_hash=None,
                ),
            ),
            "LEDGER_RELEASE_PROOF_MISSING",
        ),
        (_base_fills(), "LEDGER_TRADE_VERSION_UNSUPPORTED"),
    ],
)
def test_incomplete_or_old_chains_never_return_a_numeric_sellable_value(
    fills: tuple[HistoricalLedgerFillFact, ...],
    expected_reason: str,
) -> None:
    """Missing genesis, chain gaps, unproved releases, and old trades remain unknown."""

    evidence = _evidence(
        fills=fills,
        unsupported_trade_ids=(
            (99,) if expected_reason == "LEDGER_TRADE_VERSION_UNSUPPORTED" else ()
        ),
    )

    proof = prove_historical_ledger_sellability(evidence)

    assert proof.total_quantity is None
    assert proof.available_quantity is None
    assert proof.supported_sellable_quantity is None
    assert proof.proof_hash is None
    assert expected_reason in proof.reason_codes


def test_sell_must_consume_previously_released_quantity_and_total() -> None:
    """A SELL cannot convert pending or otherwise unsupported shares to released shares."""

    fills = (
        _fill(
            trade_id=101,
            reservation_id=51,
            quantity="100.000000",
            receipt_version=2,
            mark_hash="a" * 64,
        ),
        _fill(
            trade_id=109,
            reservation_id=52,
            side="sell",
            quantity="101.000000",
            settlement=None,
            lag=0,
            release_hash=None,
        ),
    )

    proof = prove_historical_ledger_sellability(_evidence(fills=fills))

    assert proof.supported_sellable_quantity is None
    assert proof.reason_codes[0] == "LEDGER_SELL_EXCEEDS_PROVEN_AVAILABLE"


def test_overreserved_holds_and_wrong_mapping_scope_are_unknown() -> None:
    """Holds cannot exceed proven availability and identities are proof-bound."""

    over_hold = HistoricalLedgerHoldFact(
        reservation_id=71,
        security_id="XSHG:600000",
        asset_code="600000.SH",
        side="sell",
        remaining_shares=Decimal("101.000000"),
        reservation_state_hash="e" * 64,
    )
    proof = prove_historical_ledger_sellability(_evidence(fills=_base_fills(), holds=(over_hold,)))
    assert proof.supported_sellable_quantity is None
    assert proof.reason_codes[0] == "LEDGER_ACTIVE_HOLDS_EXCEED_AVAILABLE"

    proof = prove_historical_ledger_sellability(
        replace(
            _evidence(fills=_base_fills()),
            mapping_fact=HistoricalPositionMappingFact(
                mapping_id=41,
                source_app="account",
                source_table="position",
                source_id=31,
                target_table="simulated_position",
                target_id=38,
            ),
        )
    )
    assert proof.supported_sellable_quantity is None
    assert proof.reason_codes[0] == "LEDGER_SCOPE_INVALID"


def test_proof_hash_binds_cutoff_hold_and_each_receipt_under_small_decimal_context() -> None:
    """An identical replay is stable while any evidence cutoff or active hold changes it."""

    base = _evidence(fills=_base_fills())
    changed_cutoff = replace(base, cutoff_at=datetime(2026, 11, 2, 8, 0, 1, tzinfo=UTC))
    hold = HistoricalLedgerHoldFact(
        reservation_id=71,
        security_id="XSHG:600000",
        asset_code="600000.SH",
        side="sell",
        remaining_shares=Decimal("1.000000"),
        reservation_state_hash="e" * 64,
    )
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        first = prove_historical_ledger_sellability(base)
        replay = prove_historical_ledger_sellability(base)
        later = prove_historical_ledger_sellability(changed_cutoff)
        held = prove_historical_ledger_sellability(_evidence(fills=_base_fills(), holds=(hold,)))

    assert first.proof_hash == replay.proof_hash
    assert first.proof_hash != later.proof_hash
    assert first.proof_hash != held.proof_hash
    assert held.supported_sellable_quantity == Decimal("99.000000")
