from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxAssessment,
    DeferredDividendTaxPolicy,
    DeferredDividendTaxRequest,
    DeferredDividendTaxValidationError,
    HoldingPeriodTaxBand,
    TaxableDispositionEvidence,
    TaxLotEvidence,
    TaxLotOrigin,
    TaxRoundingMode,
    calculate_deferred_dividend_tax,
)


def _policy() -> DeferredDividendTaxPolicy:
    return DeferredDividendTaxPolicy(
        policy_id="cn-dividend-withholding",
        version="test-2026-01",
        effective_from=date(2025, 1, 1),
        effective_through=date(2027, 12, 31),
        source_identity="official-statutory-source-fixture",
        source_sha256="e" * 64,
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


def _lot(
    *,
    lot_id: str,
    acquired_on: date,
    acquisition_order: int,
    record_date: date,
    acquired_quantity: str = "100",
    record_date_quantity: str = "100",
    record_date_position_quantity: str | None = None,
    origin: TaxLotOrigin = TaxLotOrigin.PURCHASE,
    account_id: int = 7,
    security_id: str = "600000.SH",
) -> TaxLotEvidence:
    return TaxLotEvidence(
        account_id=account_id,
        security_id=security_id,
        lot_id=lot_id,
        acquired_on=acquired_on,
        acquisition_order=acquisition_order,
        origin=origin,
        acquired_quantity=Decimal(acquired_quantity),
        acquisition_evidence_id=f"acquisition-{lot_id}",
        acquisition_evidence_sha256="a" * 64,
        record_date=record_date,
        position_quantity_at_record_date=Decimal(
            record_date_position_quantity
            if record_date_position_quantity is not None
            else (record_date_quantity if acquired_on <= record_date else "0")
        ),
        record_date_quantity=Decimal(record_date_quantity),
        record_date_evidence_id=f"record-{lot_id}",
        record_date_evidence_sha256="b" * 64,
        dividend_per_share=Decimal("0.50"),
    )


def _disposition(
    disposition_id: str,
    transfer_date: date,
    quantity: str,
    *,
    account_id: int = 7,
    security_id: str = "600000.SH",
) -> TaxableDispositionEvidence:
    return TaxableDispositionEvidence(
        account_id=account_id,
        security_id=security_id,
        disposition_id=disposition_id,
        transfer_settlement_date=transfer_date,
        quantity=Decimal(quantity),
        transfer_evidence_id=f"transfer-{disposition_id}",
        transfer_evidence_sha256="c" * 64,
    )


def _request(
    *,
    record_date: date,
    target_disposition_id: str,
    lots: tuple[TaxLotEvidence, ...],
    dispositions: tuple[TaxableDispositionEvidence, ...],
    account_id: int = 7,
    security_id: str = "600000.SH",
    history_complete: bool = True,
) -> DeferredDividendTaxRequest:
    target = next(row for row in dispositions if row.disposition_id == target_disposition_id)
    if target.transfer_settlement_date is None:
        raise ValueError("test request requires a known target settlement date")
    return DeferredDividendTaxRequest(
        account_id=account_id,
        security_id=security_id,
        corporate_action_id="dividend-2026-01",
        record_date=record_date,
        target_disposition_id=target_disposition_id,
        complete_through=target.transfer_settlement_date,
        history_complete=history_complete,
        history_snapshot_id="snapshot-1",
        history_snapshot_sha256="d" * 64,
        lots=lots,
        dispositions=dispositions,
    )


def test_partial_sale_replay_is_fifo_and_idempotent() -> None:
    record_date = date(2025, 12, 1)
    lots = (
        _lot(
            lot_id="old",
            acquired_on=date(2025, 1, 1),
            acquisition_order=1,
            record_date=record_date,
        ),
        _lot(
            lot_id="new",
            acquired_on=date(2025, 11, 15),
            acquisition_order=2,
            record_date=record_date,
        ),
    )
    dispositions = (
        _disposition("sale-1", date(2026, 1, 5), "50"),
        _disposition("sale-2", date(2026, 2, 5), "100"),
    )

    first = calculate_deferred_dividend_tax(
        _request(
            record_date=record_date,
            target_disposition_id="sale-1",
            lots=lots,
            dispositions=dispositions[:1],
        ),
        _policy(),
    )
    second_request = _request(
        record_date=record_date,
        target_disposition_id="sale-2",
        lots=lots,
        dispositions=dispositions,
    )
    second = calculate_deferred_dividend_tax(second_request, _policy())
    replay = calculate_deferred_dividend_tax(second_request, _policy())
    revised_policy = replace(_policy(), source_sha256="f" * 64)
    revised_policy_assessment = calculate_deferred_dividend_tax(
        second_request,
        revised_policy,
    )

    assert [(item.lot_id, item.sold_quantity) for item in first.allocations] == [
        ("old", Decimal("50"))
    ]
    assert [(item.lot_id, item.sold_quantity) for item in second.allocations] == [
        ("old", Decimal("50")),
        ("new", Decimal("50")),
    ]
    assert second.gross_dividend_amount == Decimal("50.00")
    assert second.withholding_amount == Decimal("2.50")
    assert replay == second
    assert replay.idempotency_key == second.idempotency_key
    assert replay.assessment_sha256 == second.assessment_sha256
    assert first.idempotency_key != second.idempotency_key
    assert revised_policy_assessment.idempotency_key == second.idempotency_key
    assert revised_policy_assessment.policy_sha256 != second.policy_sha256
    assert revised_policy_assessment.assessment_sha256 != second.assessment_sha256


def test_record_date_entitlement_excludes_post_record_date_lot() -> None:
    record_date = date(2026, 1, 10)
    lots = (
        _lot(
            lot_id="entitled",
            acquired_on=date(2025, 10, 1),
            acquisition_order=1,
            record_date=record_date,
            acquired_quantity="100",
            record_date_position_quantity="100",
            record_date_quantity="80",
        ),
        _lot(
            lot_id="non-entitled-record-position",
            acquired_on=date(2025, 12, 1),
            acquisition_order=2,
            record_date=record_date,
            acquired_quantity="10",
            record_date_position_quantity="10",
            record_date_quantity="0",
        ),
        _lot(
            lot_id="after-record",
            acquired_on=date(2026, 1, 11),
            acquisition_order=3,
            record_date=record_date,
            acquired_quantity="20",
            record_date_quantity="0",
        ),
    )
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-1",
        lots=lots,
        dispositions=(_disposition("sale-1", date(2026, 1, 20), "120"),),
    )

    result = calculate_deferred_dividend_tax(request, _policy())

    assert [
        (item.lot_id, item.sold_quantity, item.entitled_quantity) for item in result.allocations
    ] == [
        ("entitled", Decimal("100"), Decimal("80")),
        ("non-entitled-record-position", Decimal("10"), Decimal("0")),
        ("after-record", Decimal("10"), Decimal("0")),
    ]
    assert result.gross_dividend_amount == Decimal("40.00")


def test_natural_calendar_month_boundary_is_injected_policy_driven() -> None:
    record_date = date(2026, 1, 20)

    def assess(settlement_date: date, disposition_id: str) -> DeferredDividendTaxAssessment:
        request = _request(
            record_date=record_date,
            target_disposition_id=disposition_id,
            lots=(
                _lot(
                    lot_id=f"month-boundary-{disposition_id}",
                    acquired_on=date(2026, 1, 8),
                    acquisition_order=1,
                    record_date=record_date,
                    acquired_quantity="10",
                    record_date_quantity="10",
                ),
            ),
            dispositions=(_disposition(disposition_id, settlement_date, "10"),),
        )
        return calculate_deferred_dividend_tax(request, _policy())

    exact_month = assess(date(2026, 2, 8), "sale-exact-month")
    after_month = assess(date(2026, 2, 9), "sale-after-month")

    assert exact_month.allocations[0].holding_period_band_id == "short"
    assert exact_month.allocations[0].holding_period_months == 1
    assert exact_month.withholding_amount == Decimal("1.00")
    assert after_month.allocations[0].holding_period_band_id == "medium"
    assert after_month.allocations[0].holding_period_months == 1
    assert after_month.withholding_amount == Decimal("0.50")


def test_natural_year_boundary_changes_band_only_after_anniversary() -> None:
    record_date = date(2025, 1, 1)

    def assess(settlement_date: date, disposition_id: str) -> DeferredDividendTaxAssessment:
        request = _request(
            record_date=record_date,
            target_disposition_id=disposition_id,
            lots=(
                _lot(
                    lot_id=f"year-boundary-{disposition_id}",
                    acquired_on=date(2024, 1, 3),
                    acquisition_order=1,
                    record_date=record_date,
                    acquired_quantity="10",
                    record_date_quantity="10",
                ),
            ),
            dispositions=(_disposition(disposition_id, settlement_date, "10"),),
        )
        return calculate_deferred_dividend_tax(request, _policy())

    before_year = assess(date(2025, 1, 2), "sale-before-year")
    exact_year = assess(date(2025, 1, 3), "sale-exact-year")
    after_year = assess(date(2025, 1, 4), "sale-after-year")

    assert before_year.allocations[0].holding_period_band_id == "medium"
    assert exact_year.allocations[0].holding_period_band_id == "medium"
    assert exact_year.allocations[0].holding_period_months == 12
    assert after_year.allocations[0].holding_period_band_id == "long"
    assert after_year.allocations[0].holding_period_months == 12
    assert before_year.withholding_amount == Decimal("0.50")
    assert exact_year.withholding_amount == Decimal("0.50")
    assert after_year.withholding_amount == Decimal("0.00")


def test_unknown_origin_and_incomplete_history_fail_closed() -> None:
    record_date = date(2025, 12, 1)
    transfer_lot = _lot(
        lot_id="transferred",
        acquired_on=date(2025, 1, 1),
        acquisition_order=1,
        record_date=record_date,
        origin=TaxLotOrigin.TRANSFER_IN,
    )
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-1",
        lots=(transfer_lot,),
        dispositions=(_disposition("sale-1", date(2026, 1, 5), "10"),),
    )

    with pytest.raises(DeferredDividendTaxValidationError, match="transfer-in lot"):
        calculate_deferred_dividend_tax(request, _policy())

    incomplete = _request(
        record_date=record_date,
        target_disposition_id="sale-1",
        lots=(
            _lot(
                lot_id="known",
                acquired_on=date(2025, 1, 1),
                acquisition_order=1,
                record_date=record_date,
            ),
        ),
        dispositions=(_disposition("sale-1", date(2026, 1, 5), "10"),),
        history_complete=False,
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="complete history"):
        calculate_deferred_dividend_tax(incomplete, _policy())


def test_unknown_transfer_or_settlement_evidence_is_blocked() -> None:
    with pytest.raises(DeferredDividendTaxValidationError, match="settlement date"):
        TaxableDispositionEvidence(
            account_id=7,
            security_id="600000.SH",
            disposition_id="unknown-settlement",
            transfer_settlement_date=None,
            quantity=Decimal("10"),
            transfer_evidence_id="transfer-unknown-settlement",
            transfer_evidence_sha256="c" * 64,
        )

    record_date = date(2025, 12, 1)
    unknown_origin = _lot(
        lot_id="unknown",
        acquired_on=date(2025, 1, 1),
        acquisition_order=1,
        record_date=record_date,
        origin=TaxLotOrigin.UNKNOWN,
    )
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-1",
        lots=(unknown_origin,),
        dispositions=(_disposition("sale-1", date(2026, 1, 5), "10"),),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="unknown acquisition origin"):
        calculate_deferred_dividend_tax(request, _policy())


def test_fifo_never_consumes_a_lot_before_its_acquisition_date() -> None:
    record_date = date(2026, 1, 10)
    lots = (
        _lot(
            lot_id="existing",
            acquired_on=date(2026, 1, 2),
            acquisition_order=1,
            record_date=record_date,
            acquired_quantity="10",
            record_date_position_quantity="10",
            record_date_quantity="10",
        ),
        _lot(
            lot_id="future-buy",
            acquired_on=date(2026, 1, 15),
            acquisition_order=1,
            record_date=record_date,
            acquired_quantity="20",
            record_date_position_quantity="0",
            record_date_quantity="0",
        ),
    )
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-2",
        lots=lots,
        dispositions=(
            _disposition("sale-1", date(2026, 1, 12), "15"),
            _disposition("sale-2", date(2026, 2, 1), "5"),
        ),
    )

    with pytest.raises(DeferredDividendTaxValidationError, match="exceeds available shares"):
        calculate_deferred_dividend_tax(request, _policy())


def test_same_day_post_record_acquisition_and_disposition_block_without_net_proof() -> None:
    record_date = date(2026, 1, 10)
    lots = (
        _lot(
            lot_id="existing",
            acquired_on=date(2026, 1, 2),
            acquisition_order=1,
            record_date=record_date,
            acquired_quantity="10",
            record_date_position_quantity="10",
            record_date_quantity="10",
        ),
        _lot(
            lot_id="same-day-buy",
            acquired_on=date(2026, 1, 15),
            acquisition_order=1,
            record_date=record_date,
            acquired_quantity="20",
            record_date_position_quantity="0",
            record_date_quantity="0",
        ),
    )
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-same-day",
        lots=lots,
        dispositions=(_disposition("sale-same-day", date(2026, 1, 15), "5"),),
    )

    with pytest.raises(DeferredDividendTaxValidationError, match="same-day acquisition"):
        calculate_deferred_dividend_tax(request, _policy())


def test_duplicate_replay_ids_and_oversell_are_blocked() -> None:
    record_date = date(2025, 12, 1)
    lot = _lot(
        lot_id="known",
        acquired_on=date(2025, 1, 1),
        acquisition_order=1,
        record_date=record_date,
        acquired_quantity="20",
        record_date_quantity="20",
    )
    duplicate = _disposition("sale-1", date(2026, 1, 5), "5")
    with pytest.raises(DeferredDividendTaxValidationError, match="duplicate disposition"):
        calculate_deferred_dividend_tax(
            _request(
                record_date=record_date,
                target_disposition_id="sale-1",
                lots=(lot,),
                dispositions=(duplicate, duplicate),
            ),
            _policy(),
        )

    with pytest.raises(DeferredDividendTaxValidationError, match="exceeds available shares"):
        calculate_deferred_dividend_tax(
            _request(
                record_date=record_date,
                target_disposition_id="sale-1",
                lots=(lot,),
                dispositions=(_disposition("sale-1", date(2026, 1, 5), "21"),),
            ),
            _policy(),
        )


def test_request_cannot_cross_account_or_policy_window() -> None:
    record_date = date(2025, 12, 1)
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-1",
        lots=(
            _lot(
                lot_id="known",
                acquired_on=date(2025, 1, 1),
                acquisition_order=1,
                record_date=record_date,
            ),
        ),
        dispositions=(_disposition("sale-1", date(2026, 1, 5), "10", account_id=8),),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="crosses account or security"):
        calculate_deferred_dividend_tax(request, _policy())

    out_of_window = _request(
        record_date=date(2024, 12, 31),
        target_disposition_id="sale-1",
        lots=(
            _lot(
                lot_id="old",
                acquired_on=date(2024, 1, 1),
                acquisition_order=1,
                record_date=date(2024, 12, 31),
            ),
        ),
        dispositions=(_disposition("sale-1", date(2025, 1, 5), "10"),),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="policy effective window"):
        calculate_deferred_dividend_tax(out_of_window, _policy())
