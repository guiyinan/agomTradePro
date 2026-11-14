"""New cash debit requires complete current tax exposure, not an empty accepted ledger."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageReason,
    TaxCashCoverageStatus,
)
from apps.simulated_trading.infrastructure import corporate_action_tax_cash_admission as admission
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_tax_cash_coverage import _NOW, _complete


class _Reader:
    database_alias = "default"

    def __init__(self, snapshot=None):
        self.snapshot = snapshot or _complete()
        self.calls = []
        self.final_calls = []

    def read_locked(self, **kwargs):
        self.calls.append(kwargs)
        return self.snapshot

    def assert_still_current(self, snapshot, *, using):
        self.final_calls.append((snapshot, using))


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(admission.timezone, "now", lambda: _NOW)


def test_unknown_unassessed_exposure_cannot_clear_new_buy_cash():
    unknown = replace(
        _complete(),
        accepted_unpaid_tax=Decimal(0),
        modeled_unapplied_tax_reserve=None,
        coverage_status=TaxCashCoverageStatus.UNKNOWN,
        reason_codes=(TaxCashCoverageReason.UNASSESSED_DISPOSITION,),
    )
    with pytest.raises(BusinessLogicError) as error:
        admission.require_current_tax_cash_coverage(
            reader=_Reader(unknown), physical_account_id=17, owner_user_id=29, using="default"
        )
    assert error.value.code == "ORDER_TAX_CASH_COVERAGE_UNAVAILABLE"


def test_exact_owner_alias_and_finite_current_debt_are_verified():
    reader = _Reader()
    proof = admission.require_current_tax_cash_coverage(
        reader=reader, physical_account_id=17, owner_user_id=29, using="default"
    )
    assert proof.tax_cash_unavailable == Decimal("12.34")
    assert reader.calls == [{"physical_account_id": 17, "owner_user_id": 29, "using": "default"}]
    admission.assert_tax_cash_coverage_before_commit(reader=reader, snapshot=proof, using="default")
    assert reader.final_calls == [(proof, "default")]


@pytest.mark.parametrize("defect", ["missing", "alias", "owner", "account", "expired", "future"])
def test_wrong_or_missing_coverage_never_reaches_cash_write(defect):
    reader = _Reader()
    if defect == "missing":
        reader = None
    elif defect == "alias":
        reader.database_alias = "another"
    elif defect == "owner":
        reader.snapshot = replace(
            reader.snapshot, query=replace(reader.snapshot.query, owner_user_id=30)
        )
    elif defect == "account":
        reader.snapshot = replace(
            reader.snapshot, query=replace(reader.snapshot.query, physical_account_id=18)
        )
    elif defect == "expired":
        reader.snapshot = replace(
            reader.snapshot,
            checked_at=_NOW - timedelta(seconds=2),
            coverage_known_at=_NOW - timedelta(seconds=3),
            valid_until=_NOW,
        )
    else:
        reader.snapshot = replace(reader.snapshot, checked_at=_NOW + timedelta(seconds=1))
    with pytest.raises(BusinessLogicError):
        admission.require_current_tax_cash_coverage(
            reader=reader, physical_account_id=17, owner_user_id=29, using="default"
        )


def test_completion_clock_after_final_source_io_can_expire_the_original_proof(monkeypatch):
    reader = _Reader()

    def final(snapshot, *, using):
        monkeypatch.setattr(admission.timezone, "now", lambda: snapshot.valid_until)

    reader.assert_still_current = final
    with pytest.raises(BusinessLogicError):
        admission.assert_tax_cash_coverage_before_commit(
            reader=reader, snapshot=reader.snapshot, using="default"
        )
