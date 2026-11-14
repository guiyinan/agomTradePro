"""Controlled arithmetic goldens do not stand in for retained source/owner proofs."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.simulated_trading.domain.corporate_action_performance_projection import (
    CorporateActionRestatementInput,
    CorporateActionRestatementInvalid,
    RestatementEntitlement,
    RestatementRawMark,
    RestatementTransfer,
    project_corporate_action_restatement,
)

_DAYS = (date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 16))
_KNOWN = datetime(2026, 11, 17, 2, tzinfo=UTC)


def _mark(day: date, price: str) -> RestatementRawMark:
    return RestatementRawMark(
        day,
        "synthetic.SZ",
        "CNY",
        "share",
        Decimal(price),
        "none",
        datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
        _KNOWN,
        _KNOWN + timedelta(seconds=1),
        None,
    )


def _case(*, shares: bool = False) -> CorporateActionRestatementInput:
    transfer = RestatementTransfer(
        "synthetic-transfer",
        _DAYS[2],
        Decimal("7" if shares else "14"),
        _KNOWN,
    )
    action = RestatementEntitlement(
        "synthetic-action",
        "synthetic.SZ",
        _DAYS[1],
        Decimal("0" if shares else "14"),
        Decimal("7" if shares else "0"),
        _KNOWN,
        () if shares else (transfer,),
        (transfer,) if shares else (),
    )
    return CorporateActionRestatementInput(
        "synthetic.SZ",
        "CNY",
        "share",
        Decimal("0.01"),
        Decimal("0.000001"),
        _KNOWN + timedelta(seconds=2),
        date(2026, 11, 17),
        _DAYS,
        Decimal("100" if shares else "114"),
        Decimal("77" if shares else "70"),
        Decimal("0"),
        tuple(
            _mark(day, ("11" if shares else "10") if index == 0 else ("10" if shares else "9.8"))
            for index, day in enumerate(_DAYS)
        ),
        (action,),
        (date(2026, 11, 11),),
    )


def test_cash_ex_date_and_late_actual_payment_keep_total_value_continuous() -> None:
    points = project_corporate_action_restatement(_case())
    assert tuple(point.total_value for point in points) == (Decimal("800"),) * 3
    assert tuple(point.cash for point in points) == (Decimal("100"), Decimal("100"), Decimal("114"))
    assert tuple(point.dividend_receivable for point in points) == (
        Decimal("0"),
        Decimal("14"),
        Decimal("0"),
    )
    assert tuple(point.market_value for point in points) == (
        Decimal("700"),
        Decimal("686"),
        Decimal("686"),
    )


def test_share_right_and_late_delivery_are_valued_once_before_and_after_delivery() -> None:
    points = project_corporate_action_restatement(_case(shares=True))
    assert tuple(point.total_value for point in points) == (Decimal("870"),) * 3
    assert tuple(point.physical_shares for point in points) == (
        Decimal("70"),
        Decimal("70"),
        Decimal("77"),
    )
    assert tuple(point.share_receivable for point in points) == (
        Decimal("0"),
        Decimal("7"),
        Decimal("0"),
    )
    assert tuple(point.market_value for point in points) == (Decimal("770"),) * 3


@pytest.mark.parametrize("day", (_DAYS[0], _DAYS[1], _DAYS[2], date(2026, 11, 17)))
def test_intervening_or_later_unmodeled_financial_history_returns_no_curve(day: date) -> None:
    with pytest.raises(CorporateActionRestatementInvalid, match="INTERVENING_HISTORY_UNSUPPORTED"):
        project_corporate_action_restatement(replace(_case(), unmodeled_event_dates=(day,)))


@pytest.mark.parametrize("adjustment", ("forward", "backward", "unknown", ""))
def test_adjusted_prices_cannot_be_combined_with_explicit_entitlements(adjustment: str) -> None:
    with pytest.raises(CorporateActionRestatementInvalid, match="RAW_MARK_REQUIRED"):
        replace(_case().marks[1], adjustment=adjustment)


@pytest.mark.parametrize(
    "defect",
    (
        "missing",
        "duplicate",
        "reordered",
        "wrong_asset",
        "wrong_money",
        "wrong_quantity",
        "future_known",
    ),
)
def test_source_arithmetic_scope_or_calendar_holes_fail_closed(defect: str) -> None:
    data = _case()
    if defect == "missing":
        data = replace(data, marks=data.marks[:-1])
    elif defect == "duplicate":
        data = replace(data, marks=(data.marks[0], data.marks[0], data.marks[2]))
    elif defect == "reordered":
        data = replace(data, marks=tuple(reversed(data.marks)))
    else:
        changes = {
            "wrong_asset": {"asset_code": "other.SZ"},
            "wrong_money": {"money_unit": "USD"},
            "wrong_quantity": {"quantity_unit": "lot"},
            "future_known": {
                "publication_recorded_at": data.knowledge_cutoff + timedelta(seconds=1)
            },
        }[defect]
        data = replace(
            data, marks=(data.marks[0], replace(data.marks[1], **changes), data.marks[2])
        )
    with pytest.raises(CorporateActionRestatementInvalid):
        project_corporate_action_restatement(data)


def test_original_supplier_clock_stays_unknown_and_old_marks_are_not_retimed() -> None:
    data = _case()
    original = data.marks
    project_corporate_action_restatement(data)
    assert data.marks == original
    assert all(
        mark.source_observed_at is None and mark.local_known_at == _KNOWN for mark in data.marks
    )


def test_constant_original_debt_is_subtracted_once_without_double_debiting_cash() -> None:
    points = project_corporate_action_restatement(
        replace(_case(), current_tax_payable=Decimal("5"))
    )
    assert tuple(point.total_value for point in points) == (Decimal("795"),) * 3
    assert points[-1].cash == Decimal("114")


def test_nonzero_value_beyond_supported_precision_cannot_disappear_into_rounded_cash() -> None:
    data = _case()
    data = replace(data, marks=(replace(data.marks[0], price=Decimal("1E-200")), *data.marks[1:]))
    with pytest.raises(CorporateActionRestatementInvalid, match="ARITHMETIC_INVALID"):
        project_corporate_action_restatement(data)


@pytest.mark.parametrize(
    "defect",
    (
        "duplicate_action",
        "duplicate_transfer",
        "overpaid",
        "fractional_cent",
        "future_transfer",
        "before_effective",
    ),
)
def test_inconsistent_or_unrepresentable_original_effects_return_no_partial_curve(
    defect: str,
) -> None:
    data = _case()
    action = data.entitlements[0]
    transfer = action.cash_transfers[0]
    if defect == "duplicate_action":
        data = replace(data, entitlements=(action, action))
    elif defect == "duplicate_transfer":
        data = replace(data, entitlements=(replace(action, cash_transfers=(transfer, transfer)),))
    else:
        changes = {
            "overpaid": {"amount": Decimal("15")},
            "fractional_cent": {"amount": Decimal("14.005")},
            "future_transfer": {"recorded_at": data.knowledge_cutoff + timedelta(seconds=1)},
            "before_effective": {"accounting_on": _DAYS[0]},
        }[defect]
        data = replace(
            data, entitlements=(replace(action, cash_transfers=(replace(transfer, **changes),)),)
        )
    with pytest.raises(CorporateActionRestatementInvalid):
        project_corporate_action_restatement(data)
