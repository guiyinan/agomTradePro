from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

import pytest

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxPolicy,
    DeferredDividendTaxValidationError,
    HoldingPeriodTaxBand,
    TaxLotOrigin,
    TaxRoundingMode,
    calculate_deferred_dividend_tax,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    OwnershipAnchorKind,
    OwnershipFillFact,
    OwnershipFillSide,
    OwnershipOpeningAnchor,
    OwnershipReplayRequest,
    RecordDateOwnershipProof,
    replay_record_date_ownership,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_bridge import (
    build_deferred_dividend_tax_history_request,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    QualifiedTaxSettlementHistory,
    RecordDateTaxEntitlementEvidence,
    RecordDateTaxEntitlementRuleKind,
    TaxSettlementDayEvidence,
)

_ACCOUNT_ID = 7
_OWNER_ID = 11
_SECURITY_ID = "600000.SH"
_ASSET_CODE = "600000.SH"
_RECORD_DATE = date(2025, 2, 28)
_SOURCE_REVISION_ID = "synthetic-settlement-source:v1"
_CALENDAR = ZoneInfo("Asia/Shanghai")


def _anchor() -> OwnershipOpeningAnchor:
    return OwnershipOpeningAnchor(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        anchor_id="synthetic-account-zero-origin:v1",
        anchor_kind=OwnershipAnchorKind.ZERO_ORIGIN,
        quantity=Decimal("0.000000"),
        effective_at=datetime(2024, 1, 1, tzinfo=UTC),
        observed_at=datetime(2024, 1, 1, tzinfo=UTC),
        evidence_sha256="a" * 64,
    )


def _fill(
    *,
    trade_id: int,
    side: OwnershipFillSide,
    quantity: str,
    occurred_at: datetime,
) -> OwnershipFillFact:
    return OwnershipFillFact(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        trade_id=trade_id,
        reservation_id=trade_id + 100,
        fill_sequence=1,
        side=side,
        quantity=Decimal(quantity),
        execution_date=occurred_at.astimezone(_CALENDAR).date(),
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(minutes=1),
        binding_version=4,
        receipt_version=1,
        receipt_sha256=f"{trade_id:064x}",
    )


def _proof_and_anchor() -> tuple[RecordDateOwnershipProof, OwnershipOpeningAnchor]:
    anchor = _anchor()
    fills = (
        _fill(
            trade_id=1,
            side=OwnershipFillSide.BUY,
            quantity="100.000000",
            occurred_at=datetime(2024, 1, 30, 2, tzinfo=UTC),
        ),
        _fill(
            trade_id=2,
            side=OwnershipFillSide.SELL,
            quantity="30.000000",
            occurred_at=datetime(2024, 2, 9, 2, tzinfo=UTC),
        ),
        _fill(
            trade_id=3,
            side=OwnershipFillSide.BUY,
            quantity="60.000000",
            occurred_at=datetime(2025, 1, 31, 2, tzinfo=UTC),
        ),
    )
    record_date_end = datetime.combine(_RECORD_DATE + timedelta(days=1), time.min, tzinfo=_CALENDAR)
    request = OwnershipReplayRequest(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        record_date=_RECORD_DATE,
        record_date_end_exclusive=record_date_end,
        exchange="SYNTHETIC",
        exchange_timezone_name="Asia/Shanghai",
        cutoff_policy_id="synthetic-exchange-close:v1",
        cutoff_policy_sha256="b" * 64,
        evidence_cutoff_at=datetime(2025, 3, 15, tzinfo=UTC),
        opening_anchor=anchor,
        fills=fills,
        corporate_actions=(),
    )
    return replay_record_date_ownership(request), anchor


def _day(
    settled: date,
    opening: str,
    purchases: str,
    sales: str,
    closing: str,
    *,
    source_revision_id: str = _SOURCE_REVISION_ID,
    source_revision_sha256: str = "c" * 64,
    purchase_origin: TaxLotOrigin = TaxLotOrigin.PURCHASE,
) -> TaxSettlementDayEvidence:
    return TaxSettlementDayEvidence(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        settlement_date=settled,
        opening_eod_quantity=Decimal(opening),
        gross_purchase_quantity=Decimal(purchases),
        gross_sale_quantity=Decimal(sales),
        non_trade_quantity_delta=Decimal("0.000000"),
        closing_eod_quantity=Decimal(closing),
        purchase_origin=purchase_origin,
        evidence_id=f"synthetic-settled-eod:{settled.isoformat()}",
        evidence_sha256=f"{settled.day:02x}" * 32,
        source_revision_id=source_revision_id,
        source_revision_sha256=source_revision_sha256,
    )


def _history(
    *,
    through: date = date(2025, 3, 8),
    source_revision_id: str = _SOURCE_REVISION_ID,
    source_revision_sha256: str = "c" * 64,
    revision_days: tuple[TaxSettlementDayEvidence, ...] | None = None,
) -> QualifiedTaxSettlementHistory:
    proof, anchor = _proof_and_anchor()
    days = (
        (
            _day(date(2024, 1, 31), "0", "100", "0", "100"),
            _day(date(2024, 2, 10), "100", "0", "30", "70"),
            _day(date(2025, 2, 1), "70", "60", "0", "130"),
            _day(date(2025, 2, 28), "130", "0", "0", "130"),
            _day(date(2025, 3, 1), "130", "25", "10", "145"),
            _day(date(2025, 3, 3), "145", "0", "80", "65"),
            _day(date(2025, 3, 5), "65", "10", "30", "45"),
            _day(date(2025, 3, 7), "45", "8", "8", "45"),
            _day(date(2025, 3, 8), "45", "0", "5", "40"),
        )
        if revision_days is None
        else revision_days
    )
    selected_days = tuple(day for day in days if day.settlement_date <= through)
    entitlement = RecordDateTaxEntitlementEvidence(
        kind=RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS,
        rule_source_id="synthetic-all-covered-positions-rule:v1",
        rule_source_sha256="d" * 64,
        qualified_total_quantity=Decimal("130.000000"),
        total_evidence_id="synthetic-dividend-entitlement-total:v1",
        total_evidence_sha256="e" * 64,
    )
    return QualifiedTaxSettlementHistory(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        record_date=_RECORD_DATE,
        complete_through=selected_days[-1].settlement_date,
        record_date_ownership_proof=proof,
        opening_anchor=anchor,
        settlement_date_rule_id="synthetic-settlement-date-rule:v1",
        settlement_date_rule_sha256="1" * 64,
        settlement_calendar_id="synthetic-settlement-calendar:v1",
        settlement_calendar_sha256="2" * 64,
        source_revision_id=source_revision_id,
        source_revision_sha256=source_revision_sha256,
        covered_session_dates=tuple(day.settlement_date for day in selected_days),
        settlement_days=selected_days,
        record_date_entitlement=entitlement,
    )


def _policy() -> DeferredDividendTaxPolicy:
    return DeferredDividendTaxPolicy(
        policy_id="synthetic-tax-policy",
        version="synthetic-v1",
        effective_from=date(2024, 1, 1),
        effective_through=None,
        source_identity="synthetic-policy-source",
        source_sha256="f" * 64,
        bands=(
            HoldingPeriodTaxBand(
                band_id="short",
                maximum_holding_months=1,
                taxable_dividend_ratio=Decimal("1"),
                withholding_rate=Decimal("0.2"),
            ),
            HoldingPeriodTaxBand(
                band_id="medium",
                maximum_holding_months=12,
                taxable_dividend_ratio=Decimal("0.5"),
                withholding_rate=Decimal("0.2"),
            ),
            HoldingPeriodTaxBand(
                band_id="long",
                maximum_holding_months=None,
                taxable_dividend_ratio=Decimal("0"),
                withholding_rate=Decimal("0"),
            ),
        ),
        currency_quantum=Decimal("0.01"),
        rounding_mode=TaxRoundingMode.HALF_UP,
    )


def _low_precision_history(
    *, purchases: tuple[str, ...], target_sale: str
) -> tuple[QualifiedTaxSettlementHistory, date]:
    """Build a compact complete history for ambient Decimal-context checks."""

    proof, anchor = _proof_and_anchor()
    record_quantity = Decimal("0.000000")
    days: list[TaxSettlementDayEvidence] = []
    purchase_dates = (date(2024, 1, 31), date(2024, 2, 10))[: len(purchases)]
    for settled, purchase in zip(purchase_dates, purchases, strict=True):
        purchase_quantity = Decimal(purchase)
        closing = record_quantity + purchase_quantity
        days.append(
            _day(
                settled,
                str(record_quantity),
                purchase,
                "0",
                str(closing),
            )
        )
        record_quantity = closing
    days.append(_day(_RECORD_DATE, str(record_quantity), "0", "0", str(record_quantity)))
    target_date = date(2025, 3, 1)
    target_quantity = Decimal(target_sale)
    closing = record_quantity - target_quantity
    days.append(
        _day(
            target_date,
            str(record_quantity),
            "0",
            target_sale,
            str(closing),
        )
    )
    base = _history()
    history = replace(
        base,
        complete_through=target_date,
        record_date_ownership_proof=replace(
            proof,
            eligible_quantity=record_quantity,
        ),
        opening_anchor=anchor,
        covered_session_dates=tuple(day.settlement_date for day in days),
        settlement_days=tuple(days),
        record_date_entitlement=replace(
            base.record_date_entitlement,
            qualified_total_quantity=record_quantity,
        ),
    )
    return history, target_date


def test_bridge_uses_explicit_settlement_dates_and_preserves_complete_fifo_prefix() -> None:
    history = _history()
    action_id = "synthetic-cash-action:v1"
    first = build_deferred_dividend_tax_history_request(
        history,
        target_settlement_date=date(2025, 3, 3),
        corporate_action_id=action_id,
        dividend_per_share=Decimal("1.00"),
    )
    second = build_deferred_dividend_tax_history_request(
        history,
        target_settlement_date=date(2025, 3, 5),
        corporate_action_id=action_id,
        dividend_per_share=Decimal("1.00"),
    )
    third = build_deferred_dividend_tax_history_request(
        history,
        target_settlement_date=date(2025, 3, 8),
        corporate_action_id=action_id,
        dividend_per_share=Decimal("1.00"),
    )

    assert first.owner_user_id == _OWNER_ID
    assert first.asset_code == _ASSET_CODE
    assert first.request.history_complete is True
    assert first.request.complete_through == date(2025, 3, 3)
    lot_by_date = {lot.acquired_on: lot for lot in third.request.lots}
    old_lot = lot_by_date[date(2024, 1, 31)]
    young_lot = lot_by_date[date(2025, 2, 1)]
    post_record_net_lot = lot_by_date[date(2025, 3, 1)]
    assert old_lot.acquired_quantity == Decimal("100.000000")
    assert old_lot.position_quantity_at_record_date == Decimal("70.000000")
    assert old_lot.record_date_quantity == Decimal("70.000000")
    assert young_lot.position_quantity_at_record_date == Decimal("60.000000")
    assert young_lot.record_date_quantity == Decimal("60.000000")
    assert post_record_net_lot.acquired_quantity == Decimal("15.000000")
    assert post_record_net_lot.position_quantity_at_record_date == Decimal("0.000000")
    assert old_lot.acquired_on != date(2024, 1, 30)  # execution date is not substituted

    disposition_quantities = {
        row.transfer_settlement_date: row.quantity for row in third.request.dispositions
    }
    assert disposition_quantities == {
        date(2025, 3, 3): Decimal("80.000000"),
        date(2025, 3, 5): Decimal("20.000000"),
        date(2025, 3, 8): Decimal("5.000000"),
    }
    assert date(2025, 2, 10) not in disposition_quantities
    assert date(2025, 3, 1) not in disposition_quantities
    assert date(2025, 3, 7) not in disposition_quantities

    first_assessment = calculate_deferred_dividend_tax(first.request, _policy())
    second_assessment = calculate_deferred_dividend_tax(second.request, _policy())
    third_assessment = calculate_deferred_dividend_tax(third.request, _policy())
    assert [(row.lot_id, row.sold_quantity) for row in first_assessment.allocations] == [
        (old_lot.lot_id, Decimal("70.000000")),
        (young_lot.lot_id, Decimal("10.000000")),
    ]
    assert [(row.lot_id, row.sold_quantity) for row in second_assessment.allocations] == [
        (young_lot.lot_id, Decimal("20.000000")),
    ]
    assert [(row.lot_id, row.sold_quantity) for row in third_assessment.allocations] == [
        (young_lot.lot_id, Decimal("5.000000")),
    ]
    assert first_assessment.allocations[0].holding_period_band_id == "long"
    assert first_assessment.allocations[1].holding_period_band_id == "medium"
    assert third_assessment.gross_dividend_amount == Decimal("5.00")
    assert third_assessment.withholding_amount == Decimal("0.50")
    assert (
        len(
            {
                first.request.history_snapshot_sha256,
                second.request.history_snapshot_sha256,
                third.request.history_snapshot_sha256,
            }
        )
        == 3
    )


def test_bridge_record_position_total_ignores_callers_low_decimal_precision() -> None:
    history, target_date = _low_precision_history(
        purchases=("101.000000", "202.000000"),
        target_sale="12.345678",
    )
    arguments = {
        "target_settlement_date": target_date,
        "corporate_action_id": "synthetic-low-precision-action:v1",
        "dividend_per_share": Decimal("1.00"),
    }
    normal = build_deferred_dividend_tax_history_request(history, **arguments)

    with localcontext() as context:
        context.prec = 2
        low_precision = build_deferred_dividend_tax_history_request(history, **arguments)

    assert low_precision.history_snapshot_sha256 == normal.history_snapshot_sha256
    assert tuple(lot.position_quantity_at_record_date for lot in low_precision.request.lots) == (
        Decimal("101.000000"),
        Decimal("202.000000"),
    )


def test_bridge_net_sale_negation_ignores_callers_low_decimal_precision() -> None:
    history, target_date = _low_precision_history(
        purchases=("300.000000",),
        target_sale="12.345678",
    )
    arguments = {
        "target_settlement_date": target_date,
        "corporate_action_id": "synthetic-low-precision-sale:v1",
        "dividend_per_share": Decimal("1.00"),
    }
    normal = build_deferred_dividend_tax_history_request(history, **arguments)

    with localcontext() as context:
        context.prec = 2
        low_precision = build_deferred_dividend_tax_history_request(history, **arguments)

    assert low_precision.history_snapshot_sha256 == normal.history_snapshot_sha256
    assert low_precision.request.dispositions[-1].quantity == Decimal("12.345678")


def test_same_day_gross_buy_and_sale_emit_only_the_signed_daily_net() -> None:
    history = _history(through=date(2025, 3, 5))
    result = build_deferred_dividend_tax_history_request(
        history,
        target_settlement_date=date(2025, 3, 5),
        corporate_action_id="synthetic-cash-action:v1",
        dividend_per_share=Decimal("1"),
    )

    sale = result.request.dispositions[-1]
    assert sale.transfer_settlement_date == date(2025, 3, 5)
    assert sale.quantity == Decimal("20.000000")
    assert all(lot.acquired_on != date(2025, 3, 5) for lot in result.request.lots)


@pytest.mark.parametrize(
    ("target_date", "corporate_action_id", "dividend_per_share"),
    (
        (date(2025, 3, 7), "synthetic-action", Decimal("1")),
        (date(2025, 3, 9), "synthetic-action", Decimal("1")),
        (date(2025, 3, 8), "", Decimal("1")),
        (date(2025, 3, 8), "synthetic-action", Decimal("1.0000000000001")),
        (datetime(2025, 3, 8, tzinfo=UTC), "synthetic-action", Decimal("1")),
    ),
)
def test_bridge_rejects_missing_non_decrease_or_unqualified_target_inputs(
    target_date: date,
    corporate_action_id: str,
    dividend_per_share: Decimal,
) -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        build_deferred_dividend_tax_history_request(
            _history(),
            target_settlement_date=target_date,
            corporate_action_id=corporate_action_id,
            dividend_per_share=dividend_per_share,
        )


def test_bridge_rejects_targets_before_record_date_and_misaligned_result_wrappers() -> None:
    history = _history()
    with pytest.raises(DeferredDividendTaxValidationError):
        build_deferred_dividend_tax_history_request(
            history,
            target_settlement_date=_RECORD_DATE,
            corporate_action_id="synthetic-action",
            dividend_per_share=Decimal("1"),
        )

    valid = build_deferred_dividend_tax_history_request(
        history,
        target_settlement_date=date(2025, 3, 8),
        corporate_action_id="synthetic-action",
        dividend_per_share=Decimal("1"),
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, request=object())  # type: ignore[arg-type]
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, account_id=8)


def test_bridge_source_revision_change_changes_hash_but_not_sale_identity() -> None:
    history = _history()
    updated_revision_id = "synthetic-settlement-source:v2"
    updated_days = tuple(
        replace(
            day,
            source_revision_id=updated_revision_id,
            source_revision_sha256="9" * 64,
        )
        for day in history.settlement_days
    )
    updated = replace(
        history,
        source_revision_id=updated_revision_id,
        source_revision_sha256="9" * 64,
        settlement_days=updated_days,
    )
    first = build_deferred_dividend_tax_history_request(
        history,
        target_settlement_date=date(2025, 3, 8),
        corporate_action_id="synthetic-cash-action:v1",
        dividend_per_share=Decimal("1"),
    )
    changed = build_deferred_dividend_tax_history_request(
        updated,
        target_settlement_date=date(2025, 3, 8),
        corporate_action_id="synthetic-cash-action:v1",
        dividend_per_share=Decimal("1"),
    )

    assert first.request.history_snapshot_sha256 != changed.request.history_snapshot_sha256
    assert first.request.target_disposition_id == changed.request.target_disposition_id
    assert first.request.history_snapshot_id != changed.request.history_snapshot_id


def test_bridge_blocks_unknown_purchase_origin_instead_of_masquerading_as_purchase() -> None:
    history = _history()
    with pytest.raises(DeferredDividendTaxValidationError) as caught:
        replace(
            history.settlement_days[2],
            purchase_origin=TaxLotOrigin.UNKNOWN,
        )
    assert caught.value.code == "DEFERRED_DIVIDEND_TAX_ORIGIN_UNKNOWN"


def test_bridge_binds_record_proof_entitlement_rule_and_zero_change_day_in_snapshot() -> None:
    base = _history()
    result = build_deferred_dividend_tax_history_request(
        base,
        target_settlement_date=date(2025, 3, 8),
        corporate_action_id="synthetic-cash-action:v1",
        dividend_per_share=Decimal("1"),
    )
    changed_zero_row = replace(
        base.settlement_days[7],
        evidence_sha256="8" * 64,
    )
    changed_history = replace(
        base,
        settlement_days=(*base.settlement_days[:7], changed_zero_row, base.settlement_days[8]),
    )
    changed = build_deferred_dividend_tax_history_request(
        changed_history,
        target_settlement_date=date(2025, 3, 8),
        corporate_action_id="synthetic-cash-action:v1",
        dividend_per_share=Decimal("1"),
    )

    assert result.request.history_snapshot_sha256 != changed.request.history_snapshot_sha256
    assert result.record_date_ownership_snapshot_sha256 == (
        base.record_date_ownership_proof.ownership_snapshot_sha256
    )
    assert result.settlement_date_rule_sha256 == "1" * 64
    assert result.settlement_calendar_sha256 == "2" * 64


def test_bridge_hash_binds_date_rule_calendar_ownership_and_entitlement_sources() -> None:
    history = _history()
    base = build_deferred_dividend_tax_history_request(
        history,
        target_settlement_date=date(2025, 3, 8),
        corporate_action_id="synthetic-cash-action:v1",
        dividend_per_share=Decimal("1"),
    )
    changed_rule = replace(
        history,
        settlement_date_rule_id="synthetic-settlement-date-rule:v2",
        settlement_date_rule_sha256="3" * 64,
    )
    changed_calendar = replace(
        history,
        settlement_calendar_id="synthetic-settlement-calendar:v2",
        settlement_calendar_sha256="4" * 64,
    )
    changed_proof = replace(
        history,
        record_date_ownership_proof=replace(
            history.record_date_ownership_proof,
            ownership_snapshot_sha256="5" * 64,
        ),
    )
    changed_entitlement = replace(
        history,
        record_date_entitlement=replace(
            history.record_date_entitlement,
            rule_source_sha256="6" * 64,
        ),
    )
    changed_results = tuple(
        build_deferred_dividend_tax_history_request(
            changed,
            target_settlement_date=date(2025, 3, 8),
            corporate_action_id="synthetic-cash-action:v1",
            dividend_per_share=Decimal("1"),
        )
        for changed in (changed_rule, changed_calendar, changed_proof, changed_entitlement)
    )

    assert all(
        result.request.history_snapshot_sha256 != base.request.history_snapshot_sha256
        for result in changed_results
    )
