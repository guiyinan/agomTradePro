"""Empty accepted debt is never account-wide unassessed-tax clearance."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageQuery,
    TaxCashCoverageReason,
    TaxCashCoverageSnapshot,
    TaxCashCoverageStatus,
)
from core.exceptions import BusinessLogicError

_NOW = datetime(2026, 11, 14, 4, tzinfo=UTC)


def _query():
    return TaxCashCoverageQuery(17, 29, "synthetic-canonical-17", "test")


def _complete():
    return TaxCashCoverageSnapshot(
        _query(),
        Decimal("0.01"),
        Decimal("12.34"),
        Decimal("0.00"),
        TaxCashCoverageStatus.COMPLETE,
        (),
        _NOW,
        _NOW - timedelta(seconds=1),
        _NOW + timedelta(seconds=30),
        "a" * 64,
    )


def test_empty_accepted_ledger_does_not_clear_unassessed_exposure():
    result = TaxCashCoverageSnapshot(
        _query(),
        Decimal("0.01"),
        Decimal("0.00"),
        None,
        TaxCashCoverageStatus.UNKNOWN,
        (TaxCashCoverageReason.UNASSESSED_DISPOSITION,),
        _NOW,
    )
    assert result.accepted_unpaid_tax == 0
    assert result.modeled_unapplied_tax_reserve is None
    assert result.tax_cash_unavailable is None
    assert result.must_not_use_for_decision is True


def test_separate_model_reserve_does_not_mutate_or_double_count_accepted_debt():
    result = replace(_complete(), modeled_unapplied_tax_reserve=Decimal("5.66"))
    with localcontext() as context:
        context.prec = 2
        assert result.tax_cash_unavailable == Decimal("18.00")
    assert result.accepted_unpaid_tax == Decimal("12.34")
    assert _complete().tax_cash_unavailable == Decimal("12.34")


def test_explicit_complete_zero_requires_full_finite_coverage_proof():
    result = replace(_complete(), accepted_unpaid_tax=Decimal(0))
    result.verify_for(_query(), as_of=_NOW)
    assert result.tax_cash_unavailable == 0
    with pytest.raises(BusinessLogicError):
        replace(result, coverage_sha256=None)


@pytest.mark.parametrize(
    "field,value",
    [
        ("physical_account_id", True),
        ("physical_account_id", 0),
        ("owner_user_id", False),
        ("canonical_account_id", "other owner"),
        ("environment", ""),
    ],
)
def test_query_rejects_coercion_or_incomplete_identity(field, value):
    with pytest.raises(BusinessLogicError):
        replace(_query(), **{field: value})


@pytest.mark.parametrize(
    "change",
    [{"owner_user_id": 30}, {"physical_account_id": 18}, {"canonical_account_id": "another"}],
)
def test_coverage_cannot_be_reused_for_another_owner_or_account(change):
    with pytest.raises(BusinessLogicError):
        _complete().verify_for(replace(_query(), **change), as_of=_NOW)


def test_original_proof_cannot_be_extended_or_backdated_for_new_cash_admission():
    result = _complete()
    with pytest.raises(BusinessLogicError):
        result.verify_for(_query(), as_of=result.valid_until)
    with pytest.raises(BusinessLogicError):
        result.verify_for(_query(), as_of=_NOW - timedelta(seconds=1))
    with pytest.raises(BusinessLogicError):
        replace(result, coverage_known_at=_NOW + timedelta(seconds=1))


@pytest.mark.parametrize(
    "change",
    [
        {"accepted_unpaid_tax": None},
        {"modeled_unapplied_tax_reserve": None},
        {"reason_codes": (TaxCashCoverageReason.MODEL_UNVERIFIED,)},
        {"must_not_use_for_decision": 1},
    ],
)
def test_incomplete_or_ambiguous_result_never_claims_complete_coverage(change):
    with pytest.raises(BusinessLogicError):
        replace(_complete(), **change)
