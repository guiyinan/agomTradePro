from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext

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


@pytest.mark.parametrize("policy_id", ["", " leading", "trailing ", "inside space", "x" * 97])
def test_policy_rejects_unstable_identifiers(policy_id: str) -> None:
    with pytest.raises(DeferredDividendTaxValidationError, match="stable identifier"):
        replace(_policy(), policy_id=policy_id)


@pytest.mark.parametrize("digest", [None, "a" * 63, "A" * 64, "g" * 64])
def test_policy_rejects_noncanonical_source_digests(digest: str | None) -> None:
    with pytest.raises(DeferredDividendTaxValidationError, match="SHA-256"):
        replace(_policy(), source_sha256=digest)


@pytest.mark.parametrize("bands", [(), (object(),)])
def test_policy_rejects_empty_or_untyped_bands(bands: tuple[object, ...]) -> None:
    with pytest.raises(
        DeferredDividendTaxValidationError,
        match="bands|holding band",
    ):
        replace(_policy(), bands=bands)  # type: ignore[arg-type]


def test_policy_rejects_duplicate_nonincreasing_or_misplaced_bands() -> None:
    band = HoldingPeriodTaxBand("duplicate", 1, Decimal("1"), Decimal("0.2"))
    duplicate = (band, replace(band, maximum_holding_months=None))
    with pytest.raises(DeferredDividendTaxValidationError, match="duplicate band ids"):
        replace(_policy(), bands=duplicate)

    unordered = (
        HoldingPeriodTaxBand("later", 12, Decimal("1"), Decimal("0.2")),
        HoldingPeriodTaxBand("earlier", 6, Decimal("1"), Decimal("0.2")),
        HoldingPeriodTaxBand("tail", None, Decimal("1"), Decimal("0.2")),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="strictly increasing"):
        replace(_policy(), bands=unordered)

    misplaced_unbounded = (
        HoldingPeriodTaxBand("open", None, Decimal("1"), Decimal("0.2")),
        HoldingPeriodTaxBand("tail", None, Decimal("1"), Decimal("0.2")),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="final"):
        replace(_policy(), bands=misplaced_unbounded)

    bounded = (HoldingPeriodTaxBand("bounded", 1, Decimal("1"), Decimal("0.2")),)
    with pytest.raises(DeferredDividendTaxValidationError, match="final unbounded"):
        replace(_policy(), bands=bounded)


@pytest.mark.parametrize(
    "value",
    [Decimal("0"), Decimal("-0.01"), Decimal("0.03"), Decimal("1E-13")],
)
def test_policy_rejects_invalid_currency_quanta(value: Decimal) -> None:
    with pytest.raises(DeferredDividendTaxValidationError, match="currency_quantum"):
        replace(_policy(), currency_quantum=value)


@pytest.mark.parametrize(
    "value",
    [Decimal("-0.01"), Decimal("1.01"), Decimal("0.0000000000001")],
)
def test_tax_band_rejects_invalid_ratio_or_rate(value: Decimal) -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        HoldingPeriodTaxBand("invalid-ratio", None, value, Decimal("0.2"))
    with pytest.raises(DeferredDividendTaxValidationError):
        HoldingPeriodTaxBand("invalid-rate", None, Decimal("1"), value)


def test_tax_band_rejects_nonpositive_or_noninteger_month_thresholds() -> None:
    for value in (0, -1, True):
        with pytest.raises(DeferredDividendTaxValidationError, match="maximum_holding_months"):
            HoldingPeriodTaxBand("invalid-months", value, Decimal("1"), Decimal("0.2"))


def test_lot_rejects_invalid_scope_date_order_and_origin() -> None:
    lot = _lot(
        lot_id="invalid-lot",
        acquired_on=date(2025, 1, 1),
        acquisition_order=1,
        record_date=date(2025, 12, 1),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="account id"):
        replace(lot, account_id=True)
    with pytest.raises(DeferredDividendTaxValidationError, match="calendar date"):
        replace(lot, acquired_on=None)
    with pytest.raises(DeferredDividendTaxValidationError, match="acquisition_order"):
        replace(lot, acquisition_order=0)
    with pytest.raises(DeferredDividendTaxValidationError, match="explicitly classified"):
        replace(lot, origin="purchase")


@pytest.mark.parametrize(
    "quantity",
    [Decimal("-1"), Decimal("0"), Decimal("1E-7"), Decimal("1E+18")],
)
def test_lot_rejects_share_quantities_outside_exact_capacity(quantity: Decimal) -> None:
    lot = _lot(
        lot_id="quantity-boundary",
        acquired_on=date(2025, 1, 1),
        acquisition_order=1,
        record_date=date(2025, 12, 1),
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(lot, acquired_quantity=quantity)


def test_lot_rejects_inconsistent_positions_dividends_and_transfer_evidence() -> None:
    record_date = date(2025, 12, 1)
    lot = _lot(
        lot_id="evidence-boundary",
        acquired_on=date(2025, 1, 1),
        acquisition_order=1,
        record_date=record_date,
        acquired_quantity="10",
        record_date_position_quantity="10",
        record_date_quantity="5",
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="position exceeds"):
        replace(lot, position_quantity_at_record_date=Decimal("11"))
    with pytest.raises(DeferredDividendTaxValidationError, match="entitlement exceeds"):
        replace(lot, record_date_quantity=Decimal("11"))
    with pytest.raises(DeferredDividendTaxValidationError, match="post-record-date"):
        replace(lot, acquired_on=date(2025, 12, 2))
    with pytest.raises(DeferredDividendTaxValidationError, match="cannot be negative"):
        replace(lot, dividend_per_share=Decimal("-0.01"))
    with pytest.raises(DeferredDividendTaxValidationError, match="finite Decimal"):
        replace(lot, dividend_per_share=0.5)
    with pytest.raises(DeferredDividendTaxValidationError, match="both its identity and digest"):
        replace(lot, origin_transfer_evidence_id="partial-origin")


def test_request_rejects_invalid_completeness_and_empty_history() -> None:
    record_date = date(2025, 12, 1)
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-request-invalid",
        lots=(
            _lot(
                lot_id="request-lot",
                acquired_on=date(2025, 1, 1),
                acquisition_order=1,
                record_date=record_date,
            ),
        ),
        dispositions=(_disposition("sale-request-invalid", date(2026, 1, 5), "10"),),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="explicit boolean"):
        replace(request, history_complete=1)
    with pytest.raises(
        DeferredDividendTaxValidationError, match="acquisition history cannot be empty"
    ):
        replace(request, lots=())
    with pytest.raises(
        DeferredDividendTaxValidationError, match="disposition history cannot be empty"
    ):
        replace(request, dispositions=())


def test_request_replay_rejects_untyped_and_mismatched_lot_evidence() -> None:
    record_date = date(2025, 12, 1)
    lot = _lot(
        lot_id="scope-lot",
        acquired_on=date(2025, 1, 1),
        acquisition_order=1,
        record_date=record_date,
    )
    sale = _disposition("sale-scope", date(2026, 1, 5), "10")
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-scope",
        lots=(lot,),
        dispositions=(sale,),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="untyped lot"):
        calculate_deferred_dividend_tax(replace(request, lots=(object(),)), _policy())  # type: ignore[arg-type]
    with pytest.raises(
        DeferredDividendTaxValidationError,
        match="crosses account or security",
    ):
        calculate_deferred_dividend_tax(
            replace(request, lots=(replace(lot, account_id=8),)), _policy()
        )
    with pytest.raises(DeferredDividendTaxValidationError, match="record-date entitlement"):
        calculate_deferred_dividend_tax(
            replace(request, lots=(replace(lot, record_date=date(2025, 11, 30)),)),
            _policy(),
        )
    later_lot = replace(
        lot,
        acquired_on=date(2026, 1, 6),
        position_quantity_at_record_date=Decimal("0"),
        record_date_quantity=Decimal("0"),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="extends beyond"):
        calculate_deferred_dividend_tax(replace(request, lots=(later_lot,)), _policy())


def test_request_replay_rejects_duplicate_acquisition_identity_and_order() -> None:
    record_date = date(2025, 12, 1)
    first = _lot(
        lot_id="same-lot",
        acquired_on=date(2025, 1, 1),
        acquisition_order=1,
        record_date=record_date,
    )
    second_id = replace(first, lot_id="second-lot", acquisition_order=2)
    second_order = replace(first, lot_id="second-lot")
    sale = _disposition("sale-duplicates", date(2026, 1, 5), "10")
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-duplicates",
        lots=(first, second_id),
        dispositions=(sale,),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="duplicate lot ids"):
        calculate_deferred_dividend_tax(
            replace(request, lots=(first, replace(second_id, lot_id="same-lot"))), _policy()
        )
    with pytest.raises(DeferredDividendTaxValidationError, match="acquisition order is ambiguous"):
        calculate_deferred_dividend_tax(replace(request, lots=(first, second_order)), _policy())


def test_request_replay_rejects_untyped_or_out_of_scope_dispositions() -> None:
    record_date = date(2025, 12, 1)
    lot = _lot(
        lot_id="disposition-scope-lot",
        acquired_on=date(2025, 1, 1),
        acquisition_order=1,
        record_date=record_date,
    )
    sale = _disposition("sale-disposition-scope", date(2026, 1, 5), "10")
    request = _request(
        record_date=record_date,
        target_disposition_id=sale.disposition_id,
        lots=(lot,),
        dispositions=(sale,),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="untyped transfer row"):
        calculate_deferred_dividend_tax(
            replace(request, dispositions=(object(),)), _policy()  # type: ignore[arg-type]
        )
    with pytest.raises(DeferredDividendTaxValidationError, match="crosses account or security"):
        calculate_deferred_dividend_tax(
            replace(request, dispositions=(replace(sale, security_id="000001.SZ"),)),
            _policy(),
        )
    with pytest.raises(DeferredDividendTaxValidationError, match="on or before record date"):
        calculate_deferred_dividend_tax(
            replace(
                request,
                dispositions=(replace(sale, transfer_settlement_date=record_date),),
            ),
            _policy(),
        )
    later_sale = _disposition("sale-after-complete", date(2026, 1, 6), "1")
    with pytest.raises(DeferredDividendTaxValidationError, match="exceeds its complete-through"):
        calculate_deferred_dividend_tax(
            replace(request, dispositions=(sale, later_sale)), _policy()
        )


def test_request_replay_rejects_duplicate_target_and_prefix_mismatches() -> None:
    record_date = date(2025, 12, 1)
    lot = _lot(
        lot_id="prefix-lot",
        acquired_on=date(2025, 1, 1),
        acquisition_order=1,
        record_date=record_date,
    )
    first = _disposition("sale-prefix-1", date(2026, 1, 5), "5")
    target = _disposition("sale-prefix-2", date(2026, 1, 6), "5")
    request = _request(
        record_date=record_date,
        target_disposition_id=first.disposition_id,
        lots=(lot,),
        dispositions=(first,),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="duplicate disposition ids"):
        calculate_deferred_dividend_tax(
            replace(
                request,
                complete_through=date(2026, 1, 6),
                dispositions=(first, replace(first, transfer_settlement_date=date(2026, 1, 6))),
            ),
            _policy(),
        )
    with pytest.raises(DeferredDividendTaxValidationError, match="netted before FIFO"):
        calculate_deferred_dividend_tax(
            replace(
                request,
                dispositions=(
                    first,
                    replace(target, transfer_settlement_date=first.transfer_settlement_date),
                ),
            ),
            _policy(),
        )

    later_prefix = replace(
        request,
        target_disposition_id=first.disposition_id,
        complete_through=target.transfer_settlement_date,
        dispositions=(first, target),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="target disposition must end"):
        calculate_deferred_dividend_tax(later_prefix, _policy())
    with pytest.raises(DeferredDividendTaxValidationError, match="target disposition is absent"):
        calculate_deferred_dividend_tax(
            replace(request, target_disposition_id="missing-sale"), _policy()
        )
    with pytest.raises(
        DeferredDividendTaxValidationError, match="complete-through date must equal"
    ):
        calculate_deferred_dividend_tax(
            replace(
                request,
                target_disposition_id=target.disposition_id,
                complete_through=date(2026, 1, 7),
                dispositions=(target,),
            ),
            _policy(),
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


def test_unsupported_dividend_precision_is_rejected_and_supported_boundary_rounds_exactly() -> None:
    record_date = date(2025, 12, 1)
    lot = _lot(
        lot_id="precision-boundary",
        acquired_on=date(2025, 1, 1),
        acquisition_order=1,
        record_date=record_date,
        acquired_quantity="1",
        record_date_quantity="1",
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="dividend_per_share"):
        replace(lot, dividend_per_share=Decimal("0.0049" + "9" * 100))

    supported_lot = replace(
        lot,
        dividend_per_share=Decimal("0.004999999999"),
    )
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-precision-boundary",
        lots=(supported_lot,),
        dispositions=(_disposition("sale-precision-boundary", date(2026, 1, 5), "1"),),
    )
    policy = replace(
        _policy(),
        bands=(
            HoldingPeriodTaxBand(
                band_id="all",
                maximum_holding_months=None,
                taxable_dividend_ratio=Decimal("1"),
                withholding_rate=Decimal("1"),
            ),
        ),
    )

    result = calculate_deferred_dividend_tax(request, policy)

    assert result.gross_dividend_amount == Decimal("0.00")
    assert result.withholding_amount == Decimal("0.00")


def test_policy_rejects_currency_quantum_beyond_exact_supported_scale() -> None:
    with pytest.raises(DeferredDividendTaxValidationError, match="currency_quantum"):
        replace(_policy(), currency_quantum=Decimal("1E-100"))


def test_maximum_supported_amount_capacity_sums_exactly_before_final_quantization() -> None:
    record_date = date(2025, 12, 1)
    first_quantity = Decimal("999999999999999999.000000")
    second_quantity = Decimal("0.999999")
    total_quantity = first_quantity + second_quantity
    dividend_per_share = Decimal("999999999999999999.999999999999")
    first_lot = replace(
        _lot(
            lot_id="max-quantity-first",
            acquired_on=date(2025, 1, 1),
            acquisition_order=1,
            record_date=record_date,
            acquired_quantity=str(first_quantity),
            record_date_position_quantity=str(first_quantity),
            record_date_quantity=str(first_quantity),
        ),
        dividend_per_share=dividend_per_share,
    )
    second_lot = replace(
        _lot(
            lot_id="max-quantity-second",
            acquired_on=date(2025, 1, 1),
            acquisition_order=2,
            record_date=record_date,
            acquired_quantity=str(second_quantity),
            record_date_position_quantity=str(second_quantity),
            record_date_quantity=str(second_quantity),
        ),
        dividend_per_share=dividend_per_share,
    )
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-max-capacity",
        lots=(first_lot, second_lot),
        dispositions=(_disposition("sale-max-capacity", date(2026, 1, 5), str(total_quantity)),),
    )
    quantum = Decimal("1E-12")
    policy = replace(
        _policy(),
        bands=(
            HoldingPeriodTaxBand(
                band_id="exact-boundary",
                maximum_holding_months=None,
                taxable_dividend_ratio=Decimal("1.000000000000"),
                withholding_rate=Decimal("1.000000000000"),
            ),
        ),
        currency_quantum=quantum,
    )

    result = calculate_deferred_dividend_tax(request, policy)

    with localcontext() as context:
        context.prec = 120
        expected = (total_quantity * dividend_per_share).quantize(quantum)
    assert len(result.allocations) == 2
    assert result.gross_dividend_amount == expected
    assert result.taxable_dividend_amount == expected
    assert result.withholding_amount == expected


def test_date_max_anniversary_is_compared_without_inventing_or_overflowing_a_date() -> None:
    record_date = date(9999, 12, 30)
    lot = _lot(
        lot_id="date-max",
        acquired_on=record_date,
        acquisition_order=1,
        record_date=record_date,
        acquired_quantity="1",
        record_date_quantity="1",
    )
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-date-max",
        lots=(lot,),
        dispositions=(_disposition("sale-date-max", date.max, "1"),),
    )
    policy = replace(_policy(), effective_from=date.min, effective_through=None)

    result = calculate_deferred_dividend_tax(request, policy)

    assert result.allocations[0].holding_period_months == 0
    assert result.allocations[0].holding_period_band_id == "short"


def test_holding_month_threshold_beyond_supported_calendar_span_is_rejected() -> None:
    with pytest.raises(DeferredDividendTaxValidationError, match="maximum_holding_months"):
        HoldingPeriodTaxBand(
            band_id="unsupported-span",
            maximum_holding_months=10**10,
            taxable_dividend_ratio=Decimal("1"),
            withholding_rate=Decimal("0.2"),
        )


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


def test_transfer_in_lot_with_chain_proof_still_requires_qualified_carryover_policy() -> None:
    record_date = date(2025, 12, 1)
    lot = replace(
        _lot(
            lot_id="transferred-with-chain",
            acquired_on=date(2025, 1, 1),
            acquisition_order=1,
            record_date=record_date,
        ),
        origin=TaxLotOrigin.TRANSFER_IN,
        origin_transfer_evidence_id="transfer-chain",
        origin_transfer_evidence_sha256="f" * 64,
    )
    request = _request(
        record_date=record_date,
        target_disposition_id="sale-transfer-in",
        lots=(lot,),
        dispositions=(_disposition("sale-transfer-in", date(2026, 1, 5), "10"),),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="carryover policy"):
        calculate_deferred_dividend_tax(request, _policy())


def test_calculator_rejects_untyped_request_or_policy() -> None:
    with pytest.raises(DeferredDividendTaxValidationError, match="typed request"):
        calculate_deferred_dividend_tax(object(), _policy())  # type: ignore[arg-type]
    valid_request = _request(
        record_date=date(2025, 12, 1),
        target_disposition_id="sale-untyped-policy",
        lots=(
            _lot(
                lot_id="untyped-policy-lot",
                acquired_on=date(2025, 1, 1),
                acquisition_order=1,
                record_date=date(2025, 12, 1),
            ),
        ),
        dispositions=(_disposition("sale-untyped-policy", date(2026, 1, 5), "10"),),
    )
    with pytest.raises(DeferredDividendTaxValidationError, match="injected statutory policy"):
        calculate_deferred_dividend_tax(valid_request, object())  # type: ignore[arg-type]


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
